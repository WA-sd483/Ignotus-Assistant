# -*- coding: utf-8 -*-
"""冒烟测试：静音模式下的「睡下」语义 —— 说了「休息吧」就不许再被叫醒去聆听/回复。

用户报的 bug（静音模式）：
    给出「休息吧」进入待机后，**她仍然会聆听下一条指令并回复**。

根因是两个条件叠加（缺一不可）：
  1. 静音模式没有音频，文字一显示就 `rearm_listening()` 把聆听接回来 —— 这是**刻意**的
     （没有声音在播，不该拖着不让用户下一条指令），副作用是用户能在「说话态」还没结束
     （`silent_hold` 窗口）时就说出「休息吧」；
  2. 此时**上一条回复的收尾还没发生**。`go_idle()` 关掉聆听之后，那份迟到的收尾走到
     `tts_done → back_to_listening()` —— 把聆听接回来、桌宠姿态也从 idle 翻回 listening，
     于是「说了休息吧，她还在听、还在答」。

修法（`app/main.py`）：
  - 新增 `asleep` 标志；`go_idle()` 置位 + 掐掉在途流水线（并顺手把用户点名的「打开类」
    动作落掉，别因为掐回复而吞掉一个已经过权限校验的指令）；
  - `rearm_listening()` / `back_to_listening()` 在 `asleep` 时**直接返回**（连桌宠姿态一起挡）；
  - 三条「显示回复」的入口（`on_speak_started` / `_reply_text_fallback` / `on_tts_ready`）
    加 `asleep` 守卫，丢掉睡下之后才到的回复；
  - `on_text()` 命中唤醒词时**解除** `asleep`，否则会「叫醒了却只答一句、之后又聋了」。

本套件分两层：
  1. 结构层（AST）：守卫必须**真的在**那四个函数里。删掉守卫不会让别的测试变红，
     所以这里钉死（本项目的一贯做法：给「已经修好的东西」补反向/正向断言）。
  2. 行为层：用 `tests/sleep_probe.py` 在子进程里真实跑 `app.main.main()`，按脚本注入
     语音识别结果，检查「睡下之后」的桌宠姿态 / 消息条数 / AI 调用次数。
     **流式主路径与非流式回退路径各跑一遍** —— 后者挂的是裸 `QTimer`，`cancel()` 管不着，
     只能靠 `back_to_listening` 的守卫挡住，不跑它就验不到。

跑法（在项目根目录）：
    .venv\\Scripts\\python.exe tests\\smoke_sleep.py
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
try:  # 控制台重定向时保证中文输出可读
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

fails = []
total = [0]


def check(name, ok, detail=""):
    total[0] += 1
    print(("OK   " if ok else "FAIL ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


# ========== 1. 结构层（AST）：守卫必须在位 ==========
print("== 1. 代码结构：asleep 守卫在位 ==")

_SRC = (BASE / "app" / "main.py").read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)


def _func(name):
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _body_wo_docstring(node):
    return [s for s in node.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]


def _mentions(node, name):
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _first_stmt_is_asleep_guard(node):
    body = _body_wo_docstring(node)
    if not body:
        return False
    first = body[0]
    if not isinstance(first, ast.If):
        return False
    return any(isinstance(n, ast.Name) and n.id == "asleep" for n in ast.walk(first.test))


def _sets_asleep(node, value):
    for n in ast.walk(node):
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            t = n.targets[0]
            if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                    and t.value.id == "asleep"
                    and isinstance(n.value, ast.Constant) and n.value.value is value):
                return True
    return False


def _calls_cancel(node):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "cancel" for n in ast.walk(node))


def _sets_awake(node, value):
    """函数体里有没有 `awake["v"] = <value>`（字面量）。

    ★与 `_sets_asleep` 同款，只是换个标志 —— 「已经醒着」这件事必须留痕，
      否则「思考/说话那几秒里再喊唤醒词」就又走一遍唤醒流程（2026-09-27 的 bug）。
    """
    for n in ast.walk(node):
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            t = n.targets[0]
            if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                    and t.value.id == "awake"
                    and isinstance(n.value, ast.Constant) and n.value.value is value):
                return True
    return False


def _if_tests_awake(node):
    """函数体里有没有一个 `if` 的**条件**用到 `awake`（唤醒流程的成立条件）。"""
    for n in ast.walk(node):
        if isinstance(n, ast.If) and _mentions(n.test, "awake"):
            return True
    return False


def _calls_func(node, name):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Name) and f.id == name) or \
               (isinstance(f, ast.Attribute) and f.attr == name):
                return True
    return False


for _fn in ("go_idle", "rearm_listening", "back_to_listening", "on_text",
            "on_speak_started", "_reply_text_fallback", "on_tts_ready"):
    check(f"main.py 里能找 {_fn}()", _func(_fn) is not None)

_go, _rearm, _back = _func("go_idle"), _func("rearm_listening"), _func("back_to_listening")
check("go_idle：置位 asleep（睡下的唯一入口）", _go is not None and _sets_asleep(_go, True))
check("go_idle：掐掉在途回复流水线（否则它的收尾会把聆听接回来）",
      _go is not None and _calls_cancel(_go))
check("go_idle：顺手把待执行的「打开类」动作落掉（别吞掉已过权限校验的指令）",
      _go is not None and _calls_func(_go, "_run_pending_action"))
check("rearm_listening：第一条就是 asleep 守卫（不许把聆听接回来）",
      _rearm is not None and _first_stmt_is_asleep_guard(_rearm))
check("back_to_listening：第一条就是 asleep 守卫（连桌宠姿态一起挡住）",
      _back is not None and _first_stmt_is_asleep_guard(_back))
check("on_text：唤醒时解除 asleep（否则叫醒后只答一句、之后又聋了）",
      _func("on_text") is not None and _sets_asleep(_func("on_text"), False))
for _fn in ("on_speak_started", "_reply_text_fallback", "on_tts_ready"):
    check(f"{_fn}：丢弃睡下之后才到的回复",
          _func(_fn) is not None and _mentions(_func(_fn), "asleep"))

# ---- ★「反复被唤醒」（2026-09-27 用户报：叫出角色名唤醒后，再喊唤醒词会显示反复被唤醒）----
print()
print("== 1b. 代码结构：醒着时再喊唤醒词，不许重走唤醒流程 ==")
_ot = _func("on_text")
_gi2 = _func("go_idle")
check("on_text：唤醒流程的条件用到 awake（成立条件是「还没醒」而不是「不在聆听」）",
      _ot is not None and _if_tests_awake(_ot),
      "只看 listening[\"active\"] 的话，她思考/说话那几秒里会再唤醒一遍")
check("on_text：真唤醒时置位 awake（把「已经醒了」记下来）",
      _ot is not None and _sets_awake(_ot, True))
check("go_idle：睡下时清掉 awake（否则「叫也叫不醒」—— 睡了再喊唤醒词也被这条守卫挡住）",
      _gi2 is not None and _sets_awake(_gi2, False))
_awake_writes = [n for n in ast.walk(_TREE)
                 if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Subscript)
                 and isinstance(n.targets[0].value, ast.Name)
                 and n.targets[0].value.id == "awake"]
check("★awake 只在两处被写（唤醒置 True / go_idle 置 False），没有第三处偷偷改它",
      len(_awake_writes) == 2, str(len(_awake_writes)))
check("★「纯唤醒词回声被吞掉」那段已删除（再喊唤醒词要走正常交流，用户 2026-09-27 拍板）",
      "is_pure_wake" not in _SRC, "is_pure_wake 还在")


# ========== 2. 行为层：真实跑 main()，脚本注入识别结果 ==========
print("== 2. 真实跑 main()：说了「休息吧」之后不再聆听 / 不再回复 ==")

tmp_dir = Path(tempfile.mkdtemp(prefix="ignotus_sleep_smoke_"))
PROBE = BASE / "tests" / "sleep_probe.py"


def run_probe(mode: str) -> dict:
    out = tmp_dir / f"sleep_{mode}.json"
    env = os.environ.copy()                 # 整份继承：缺 TEMP/SYSTEMROOT 会让子进程踩坑
    env.pop("PYTHONPATH", None)
    env["SLEEP_PROBE_OUT"] = str(out)
    env["SLEEP_PROBE_MODE"] = mode
    env["QT_QPA_PLATFORM"] = "offscreen"
    r = subprocess.run([sys.executable, str(PROBE)], cwd=str(BASE), env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not out.exists():
        return {"_error": f"rc={r.returncode}\n{(r.stderr or '')[-900:]}"}
    return json.loads(out.read_text(encoding="utf-8"))


for mode, label in (("stream", "流式主路径"), ("fallback", "非流式回退路径")):
    res = run_probe(mode)
    if "_error" in res:
        check(f"[{label}] 探针跑通", False, res["_error"])
        continue
    check(f"[{label}] 探针跑通", res["rc"] == 0, str(res["rc"]))
    check(f"[{label}] 语音识别替身把回调交出来了", res["feed_ready"] is True)
    st = res["steps"]
    base, asleep_snap = st.get("before_probe"), st.get("after_sleep")
    if not base or not asleep_snap:
        check(f"[{label}] 脚本快照齐全", False, str(list(st.keys())))
        continue

    check(f"[{label}] 第一轮：唤醒并回复了一次（前置条件成立）",
          base["assistant"] == 1 and base["user"] == 1 and base["wake_msgs"] == 1,
          str(base))
    check(f"[{label}] 确实睡下了（落了「我先休息了」提示）",
          any("我先休息了" in x for x in res["messages"]),
          str(res["messages"])[-200:])
    check(f"[{label}] 睡下后桌宠**停在 idle**（迟到的收尾没把它翻回 listening）",
          asleep_snap["pet"] == "idle", asleep_snap["pet"])
    check(f"[{label}] 睡下后没有冒出第二条回复",
          asleep_snap["assistant"] == base["assistant"], str(asleep_snap))
    check(f"[{label}] 睡下后「现在几点了」被忽略（不添用户气泡、不回复）",
          asleep_snap["user"] == base["user"], str(asleep_snap))
    check(f"[{label}] 睡下后没有再调用 AI",
          asleep_snap["stream_calls"] == base["stream_calls"]
          and asleep_snap["once_calls"] == base["once_calls"], str(asleep_snap))
    check(f"[{label}] 没有出现「1 分钟未收到指令」的超时待机（是主动睡下的）",
          not any("超过 1 分钟" in x for x in res["messages"]),
          str(res["messages"])[-200:])

    if mode == "stream":
        wake = st.get("after_wake")
        check("[流式主路径] 快照齐全（唤醒后）", wake is not None, str(list(st.keys())))
        if wake:
            check("[流式主路径] 喊一声能重新唤醒（asleep 被解除，不是「叫醒也聋」）",
                  wake["wake_msgs"] == 2, str(wake))
            check("[流式主路径] 唤醒后她照常回复（比睡下时多一条）",
                  wake["assistant"] == asleep_snap["assistant"] + 1, str(wake))
            check("[流式主路径] 唤醒后桌宠离开 idle",
                  wake["pet"] != "idle", wake["pet"])

# ========== 3. ★行为层：醒着时再喊一次唤醒词 ==========
# 改之前：她思考 / 说话那几秒里 `listening["active"]` 是 False ⇒ 再喊一次唤醒词会
# **又**走一遍唤醒流程（又弹「已唤醒」、又主动打招呼）。这里就在那个窗口里再喊一次，
# 看她是「再被唤醒一遍」还是「当普通说话正常交流」。
# ★窗口靠探针里给 AI 加的人为延迟撑开（真机是 AI 延迟 + 合成耗时）；详见 `sleep_probe.py`。
print()
print("== 3. 真实跑 main()：醒着时再喊一次唤醒词（不再重复唤醒）==")
_res_rw = run_probe("rewake")
if "_error" in _res_rw:
    check("[rewake] 探针跑通", False, _res_rw["_error"])
else:
    check("[rewake] 探针跑通", _res_rw["rc"] == 0, str(_res_rw["rc"]))
    check("[rewake] 语音识别替身把回调交出来了", _res_rw["feed_ready"] is True)
    _st = _res_rw["steps"]
    _first, _second, _settled = (_st.get("after_first_wake"), _st.get("after_second_wake"),
                                 _st.get("settled"))
    if not (_first and _second and _settled):
        check("[rewake] 脚本快照齐全", False, str(list(_st.keys())))
    else:
        check("[rewake] 第一次唤醒：弹了一次「已唤醒」、且没混进用户消息",
              _first["wake_msgs"] == 1 and _first["user"] == 0, str(_first))
        check("[rewake] ★窗口内再喊一次唤醒词：**没有再唤醒**（「已唤醒」始终 1 次）",
              _second["wake_msgs"] == 1, str(_second))
        check("[rewake] ★那次唤醒词被当成一句**普通的用户消息**（走正常交流，不是被吞掉）",
              _second["user"] == 1, str(_second))
        check("[rewake] 收尾：她又走完一轮对话（AI 共调用 2 次）、「已唤醒」始终 1 次",
              _settled["stream_calls"] == 2 and _settled["wake_msgs"] == 1
              and _settled["user"] == 1, str(_settled))
        check("[rewake] 她一直醒着（桌宠没停在 idle）", _settled["pet"] != "idle",
              _settled["pet"])
        # ★这里**刻意不**断言「聊天区落了 2 条回复文字」：实测（2026-09-27）在「上一轮还没
        #   开口就来了下一句」时只会落 1 条 —— `_ask_ai` 一进来就重置 `stream_ui["bubble"]`，
        #   而上一轮**迟到**的 `on_speak_started` 随后又把它置 True ⇒ 下一轮那次建泡被吃掉。
        #   ★这是**既有**竞态：改之前走「再唤醒」那条路同样会 `_ask_ai`、同样重置，一样复现；
        #     与本次的 `awake` 修复没有因果关系。已记进 `docs/02`（已知问题），**不在这里钉死**——
        #     将来谁把它修好了，这条不该拦着他。

print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)
