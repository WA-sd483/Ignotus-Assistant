# -*- coding: utf-8 -*-
"""回复流水线端到端探针：真实跑一遍 `app.main.main()`，用假 AI / 假 TTS 走完整条回复。

`QApplication` 一个进程只能建一个，所以本文件**自己就是一个独立进程**（由 `run_all.py`
或人工直接调用），`exec()` 被替换成"跑固定时长就返回"。

替身（都不联网、不发声、不写注册表）：
  - `app.asr`   → 假麦克风：按脚本喂三句话（验多轮历史 + 三种时序）；
  - `app.ai`    → 假流式客户端，逐字吐一条「日语在前」的双语回复（每轮速度可调）；
  - `app.tts`   → 假合成 / 假播放；**假播放刻意模拟「打开音频设备」的耗时**，
                  用来复现「文字先出、声音后到」这类真机才会暴露的错位；
  - `autostart` → 读写全部替换为假实现；
  - 托盘        → offscreen 下不可靠，换假对象。

三轮各盯一件事：
  1. 快流 + 快合成 → 理想路径：气泡一次建成完整中文、日语整段一次合成、文字与声音同刻；
  2. 慢流 + 快合成 → 「思考中」提示**可见**时，由正常开场路径清掉（不能与回复文字共存）；
  3. 慢合成 → 触发最后兜底：文字提前显示时，也必须清掉「思考中」并切「说话中」。

跑法（在项目根目录，注意必须单独一个进程）：
    .venv\\Scripts\\python.exe tests\\reply_probe.py
"""
import os
import sys
import threading
import time
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
try:
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


# ---------- 1. 把外部依赖换成替身 ----------
REPLY = ("日语：おはようございます。今日はいい天気ですね。散歩でもどうですか？"
         "|||中文：早上好。今天天气不错呢。要不要去散散步？")
ZH_FULL = "早上好。今天天气不错呢。要不要去散散步？"

# 每轮的时序参数：流式吐字间隔（秒/字）/ 合成耗时（秒）
ROUNDS = [
    {"interval": 0.02, "synth": 0.05},   # 1 理想路径
    {"interval": 0.05, "synth": 0.05},   # 2 思考提示可见 → 正常开场清掉
    {"interval": 0.05, "synth": 2.50},   # 3 合成慢 → 触发最后兜底
]
# 模拟「打开音频设备 + 写缓冲」的耗时：这段里声音还没出来（真机 0.3~1s）
PLAY_DEVICE_DELAY = 0.4
# 兜底窗口调小，好在探针时长内走完第 3 轮（真机按日语字数自适应，见 main.reply_text_fallback_ms）
FALLBACK_MS = 600

synth_calls = []      # [(t, text)]
play_calls = []       # [(t, path)]   t = 声音真正开始的时刻
stream_done = []      # 每条回复"AI 吐完"的时间戳
api_calls = []        # 每次请求的 messages


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


COMMANDS = ["爱丽丝，帮我看看今天冷不冷", "爱丽丝，那明天呢", "爱丽丝，那后天呢"]
# 三句话的发出时刻（秒，从 main() 启动算起）
SEND_AT = [0.2, 2.8, 8.0]


class _FakeMic:
    def __init__(self, recognizer=None, on_text=None):
        self._on_text = on_text

    def start(self):
        def fire():
            prev = 0.0
            for cmd, at in zip(COMMANDS, SEND_AT):
                time.sleep(at - prev)
                prev = at
                self._on_text(cmd)
        threading.Thread(target=fire, daemon=True).start()

    def stop(self):
        pass


_round = {"n": 0}


def _fake_synth(role_key, text, text_language="ja"):
    idx = min(_round["n"], len(ROUNDS) - 1)
    synth_calls.append((time.time(), text))
    time.sleep(ROUNDS[idx]["synth"])
    return f"wav::{text}"


def _fake_play(path, on_started=None):
    """假播放：先模拟打开音频设备的耗时，**然后**才回调「声音开始」。"""
    time.sleep(PLAY_DEVICE_DELAY)
    play_calls.append((time.time(), path))
    if on_started is not None:
        on_started()


_stub("app.asr", MicListener=_FakeMic, Recognizer=lambda *a, **k: object())
_stub(
    "app.tts",
    # ★替身必须与 `app/tts.py` 的**公开名**对齐（理由见 boot_probe.py 同一处注释）：
    #   少了 `DEFAULT_TEXT_LANGUAGE`，`main.py` 的 worker 线程会静默死于 ImportError。
    DEFAULT_TEXT_LANGUAGE="ja",
    TEXT_LANGUAGE_NAMES={"zh": "中文", "en": "英语", "ja": "日语"},
    start_in_background=lambda *a, **k: None,
    set_volume=lambda *a, **k: None,
    set_muted=lambda *a, **k: None,
    is_muted=lambda: False,
    synthesize_with_bang=_fake_synth,
    play_wav=_fake_play,
)

import app.config as cfgmod  # noqa: E402

_tmp_cfg = BASE / "tools" / "_reply_probe_config.json"
# ★2026-10-02 起 API 是**每个角色一份独立列表**（`{角色key: [条目,…]}` / `{角色key: 名字}`）。
#   本探针走的是**真的 `load_config`**（只是把 CONFIG_PATH 指到临时文件），所以旧扁平结构
#   本来也能被迁移兜住；这里显式写成新结构，免得「迁移那条路」哪天坏了这套会跟着变哑。
_tmp_cfg.write_text(
    '{"apis": {"alice": [{"name": "\u6d4b\u8bd5", "api_key": "sk-x",'
    ' "base_url": "https://example.com/v1", "model": "m"}]},'
    ' "current_api": {"alice": "\u6d4b\u8bd5"},'
    ' "current_role": "alice"}',
    encoding="utf-8",
)
cfgmod.CONFIG_PATH = _tmp_cfg

# ★★2026-09-27：把「模型已就位」**钉死**。上面那份临时配置里没有 `general.mute_mode` 也没有
#   安装位置 ⇒ `voice_model.candidate_dirs()` 只能去「项目内 → D:\GPT-SoVITS」找模型，
#   而本机模型已被卸载 ⇒ `main._apply_model_gate()` 会把 `mute_mode` **锁死在开**
#   （`docs/01` F7：没有模型就一声都出不来）⇒ 回复管线**整条跳过合成**
#   ⇒ 本套里那几条「日语整段一次合成 / 送去合成的是日语 / 语音只播一次」会**确定性地**全红。
#   ★那不是契约坏了，是「本探针依赖硬盘上有没有那 1.15 GB」。显式声明前置条件，
#     让它与模型在不在解耦 —— 它要测的是**回复与合成的时序**，不是模型状态。
import app.voice_model as _vm_mod  # noqa: E402
_vm_mod.is_installed = lambda cfg: True

from app import autostart  # noqa: E402

autostart.current_command = lambda: ""
autostart.is_enabled = lambda: False
autostart.enable = lambda: (True, "")
autostart.disable = lambda: (True, "")
autostart.refresh_command = lambda: (False, "")

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app.ai as ai  # noqa: E402
import app.main as m  # noqa: E402

_orig_fallback_ms = m.reply_text_fallback_ms          # 留一份真实现，末尾要量它的标定
m.reply_text_fallback_ms = lambda _ja="": FALLBACK_MS   # 兜底窗口调小（真机按字数自适应，探针跑不完）


class _Delta:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c, fr=None):
        self.delta = _Delta(c)
        self.finish_reason = fr


class _Chunk:
    def __init__(self, c, fr=None):
        self.choices = [_Choice(c, fr)]


class _FakeStream:
    def __init__(self, text, interval):
        self._text, self._interval = text, interval

    def __iter__(self):
        for i, ch in enumerate(self._text):
            time.sleep(self._interval)
            yield _Chunk(ch, "stop" if i == len(self._text) - 1 else None)
        stream_done.append(time.time())


class _Completions:
    def create(self, **kw):
        if not kw.get("stream"):
            raise AssertionError("本探针只验证流式路径")
        api_calls.append(kw.get("messages"))
        idx = min(len(api_calls) - 1, len(ROUNDS) - 1)
        _round["n"] = idx
        return _FakeStream(REPLY, ROUNDS[idx]["interval"])


class _Client:
    def __init__(self):
        self.chat = type("C", (), {"completions": _Completions()})()


ai.OpenAI = lambda **kw: _Client()


class _FakeTray(QObject):
    activated = Signal(object)
    Trigger = "trigger"
    DoubleClick = "double"

    def __init__(self, *a, **k):
        super().__init__()

    def setToolTip(self, *a, **k):
        pass

    def setContextMenu(self, *a, **k):
        pass

    def show(self):
        pass

    def hide(self):
        pass

    def showMessage(self, *a, **k):
        pass


# ui 每条：(t, kind, text, thinking_row 是否存在, 左栏状态文字)
ui = []
# 周期性采样「思考中」提示/状态：它出现与消失都可能落在两次 UI 事件之间，
# 只靠事件式记录会漏（这正是「思考中与文字共存」这类 bug 藏身的地方）。
samples = []          # [(t, thinking_row, 状态文字)]
captured = {}


class _SpyWindow(m.MainWindow):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        captured["win"] = self
        self._sampler = QTimer(self)
        self._sampler.setInterval(50)
        self._sampler.timeout.connect(self._sample)
        self._sampler.start()

    def _sample(self):
        cv = self._chat_view
        samples.append((time.time(), getattr(cv, "_thinking_row", None) is not None,
                        self._status_label.text()))

    def _snap(self, kind, text):
        cv = self._chat_view
        ui.append((time.time(), kind, str(text),
                   getattr(cv, "_thinking_row", None) is not None,
                   self._status_label.text()))

    def add_user_message(self, text):
        self._snap("user", text)
        return super().add_user_message(text)

    def add_system_message(self, text, *a, **k):
        self._snap("system", text)
        return super().add_system_message(text, *a, **k)

    def add_assistant_message(self, role_key, name, text):
        self._snap("whole", text)
        return super().add_assistant_message(role_key, name, text)

    def begin_assistant_message(self, role_key, name, text):
        self._snap("begin", text)
        return super().begin_assistant_message(role_key, name, text)

    def finish_assistant_message(self, role_key, text):
        self._snap("finish", text)
        return super().finish_assistant_message(role_key, text)

    def set_status(self, state):
        self._snap("status", state.value)
        return super().set_status(state)


class _SpyPet(m.PetWindow):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        captured["pet"] = self


WINDOW_MS = 14000   # 第 3 轮的声音最晚在 ~13.1s 开始


class _ShortApp(QApplication):
    def exec(self):
        loop = QEventLoop()
        QTimer.singleShot(WINDOW_MS, loop.quit)
        loop.exec()
        return 0


m.MainWindow = _SpyWindow
m.PetWindow = _SpyPet
m.QSystemTrayIcon = _FakeTray
m.QApplication = _ShortApp
sys.argv = ["run.py"]

rc = m.main()

# ---------- 2. 断言 ----------
print("== 回复流水线端到端 ==")
win = captured["win"]

cmd_idx = [i for i, (_, k, *_rest) in enumerate(ui) if k == "user"]
assert len(cmd_idx) == len(COMMANDS), f"预期 {len(COMMANDS)} 轮，实到 {len(cmd_idx)} 轮"
ui1 = ui[:cmd_idx[1]]
ui2 = ui[cmd_idx[1]:cmd_idx[2]]
ui3 = ui[cmd_idx[2]:]
t_cmd = [ui[i][0] for i in cmd_idx]
kinds1 = [k for _, k, *_ in ui1]
ev1 = [(k, v) for _, k, v, *_ in ui1]


def begins(rows):
    return [r for r in rows if r[1] == "begin"]


def first_begin(rows):
    return next((r for r in rows if r[1] == "begin"), None)


def plays_in(rows, lo, hi):
    return [t for t, _ in play_calls if lo <= t < hi]


def thought_bubble_seen(lo, hi):
    """这一轮里「正在思考...」气泡是否真的**出现过**（周期性采样判定）。"""
    return any(th for t, th, _ in samples if lo <= t < hi)


check("启动后跑到了正常退出码", rc == 0, str(rc))
check("没有出现「回复失败」类系统提示",
      not any("失败" in v or "未配置" in v for k, v in ev1 if k == "system"),
      str([v for k, v in ev1 if k == "system"]))
check("气泡只建了一次（回复不会整条重建）", kinds1.count("begin") == 1, str(kinds1))
check("走的是流式路径（没走整条一次性写入）", kinds1.count("whole") == 0, str(kinds1))
check("没有「逐段回填」中间态（文字一次性出现）", kinds1.count("update") == 0, str(kinds1))

begins1 = [v for k, v in ev1 if k == "begin"]
check("气泡里一次就是完整中文", begins1 == [ZH_FULL], str(begins1))
finals1 = [v for k, v in ev1 if k == "finish"]
check("收尾时写入的完整中文与解析结果一致", finals1[-1:] == [ZH_FULL], str(finals1))
check("界面文字全是中文（没有把日语显示出来）",
      all(not ai._has_kana(v) for v in begins1), str(begins1))

# ---- 语音：整段一次合成 / 一次播放（这是"没有句间停顿"的根据）----
JA_FULL = REPLY.split("|||")[0].split("：", 1)[1]
r1_synths = [(t, txt) for t, txt in synth_calls if t < t_cmd[1]]
r1_plays = plays_in(ui1, 0, t_cmd[1])
check("日语**整段一次**合成（不再逐句 → 没有句间停顿）",
      len(r1_synths) == 1 and r1_synths[0][1] == JA_FULL, str(r1_synths))
check("送去合成的确实是日语（没把中文送进日语语音）",
      bool(r1_synths) and ai._has_kana(r1_synths[0][1]), str(r1_synths))
check("语音只播一次（整段无缝，不是逐句播）", len(r1_plays) == 1, str(r1_plays))

# ---- 第 1 轮：文字与声音同刻（假播放里含 0.4s「打开设备」耗时）----
b1 = first_begin(ui1)
begin_t = b1[0]
check("合成在 AI 吐完**之前**就开始（真并行，不是等整段写完）",
      bool(r1_synths) and bool(stream_done) and r1_synths[0][0] < stream_done[0],
      f"synth={r1_synths[0][0]:.3f} stream_done={stream_done[0]:.3f}" if r1_synths else "no synth")
check("开场落在中文吐完**之后**（等文字完整才出声 → 不会先出字后出声）",
      bool(r1_plays) and bool(stream_done) and r1_plays[0] >= stream_done[0],
      f"play={r1_plays[0]:.3f} stream_done={stream_done[0]:.3f}")
check("「文字出现」**不早于**「声音开始」（真机的设备打开耗时不得算成文字抢跑）",
      bool(r1_plays) and begin_t >= r1_plays[0] - 0.05,
      f"begin={begin_t:.3f} play={r1_plays[0]:.3f}")
check("「文字出现」也不比声音晚太多（Qt 排队 + 建气泡的固有延迟之内）",
      bool(r1_plays) and begin_t - r1_plays[0] < 0.30,
      f"begin={begin_t:.3f} play={r1_plays[0]:.3f}")
check("气泡出现得比 AI 吐完晚（确实是等到了完整中文）",
      begin_t >= stream_done[0] - 0.05,
      f"begin={begin_t:.3f} stream_done={stream_done[0]:.3f}")

states = [v for _, k, v, *_ in ui1 if k == "status"]
check("状态机走过 聆听 → 思考 → 说话 → 聆听",
      states[:4] == ["listening", "thinking", "speaking", "listening"], str(states))

# ---- 「思考中」不许和回复文字共存（用户报过的 bug）----
check("第 1 轮：开门那一刻没有「正在思考...」气泡",
      b1 is not None and b1[3] is False, str(b1))
check("第 1 轮：开门那一刻左栏不是「思考中…」",
      b1 is not None and b1[4] != "思考中…", str(b1))

b2 = first_begin(ui2)
check("第 2 轮：「思考中」提示确实出现过（否则下一条断言没意义）",
      thought_bubble_seen(t_cmd[1], t_cmd[2]),
      str([(r[1], r[3], r[4]) for r in ui2]))
check("第 2 轮：正常开场时已移除「正在思考...」气泡、切「说话中」",
      b2 is not None and b2[3] is False and b2[4] == "说话中…", str(b2))

b3 = first_begin(ui3)
r3_plays = plays_in(ui3, t_cmd[2], float("inf"))
check("第 3 轮（慢合成）：「思考中」提示出现过（证明走的是兜底那条路）",
      thought_bubble_seen(t_cmd[2], float("inf")),
      str([(r[1], r[3], r[4]) for r in ui3]))
check("第 3 轮：兜底先出字 —— 文字确实早于声音（同步被放弃，救「合成卡住」的代价）",
      b3 is not None and bool(r3_plays) and b3[0] < r3_plays[0],
      f"begin={b3[0]:.3f} play={r3_plays[0]:.3f}" if b3 and r3_plays else "no begin/play")
check("第 3 轮：兜底出字时也移除「正在思考...」气泡、切「说话中」（不能与文字共存）",
      b3 is not None and b3[3] is False and b3[4] == "说话中…", str(b3))
check("第 3 轮：兜底只建一次气泡，语音随后到达不再重建",
      len(begins(ui3)) == 1, str([r[1] for r in ui3]))

for i, rows in enumerate((ui1, ui2, ui3), start=1):
    bs = begins(rows)
    check(f"第 {i} 轮：任何一次建气泡时「正在思考...」都不在屏幕上",
          all(r[3] is False for r in bs) and all(r[4] != "思考中…" for r in bs), str(bs))

# ---- 多轮：聊天记录与喂给 AI 的历史 ----
hists = win._chat_history.get("alice", [])
asst = [h for h in hists if h["role"] == "assistant"]
check("三轮对话各留下一条助手回复（兜底路径不会落两遍）", len(asst) == 3, str(hists))
check("界面聊天记录存的是中文（界面只出中文）",
      all(not ai._has_kana(h["text"]) for h in asst), str(asst))

check("第一轮请求是 persona + 一条用户消息（用户消息不重复）",
      bool(api_calls) and len(api_calls[0]) == 2, str([len(c) for c in api_calls]))
check("第二轮请求带上了历史（persona + 用户 + 助手 + 用户）",
      len(api_calls) >= 2 and len(api_calls[1]) == 4, str([len(c) for c in api_calls]))
check("第三轮也发起了请求（带了历史与本轮用户话）",
      len(api_calls) == 3 and any(mm.get("content") == COMMANDS[2] for mm in api_calls[2]),
      str([len(c) for c in api_calls]))
if len(api_calls) >= 2:
    hist_turn = api_calls[1][2]
    check("历史里的助手回复存的是双语格式（避免模型被带成纯中文）",
          hist_turn.get("role") == "assistant"
          and hist_turn["content"].startswith("日语：")
          and "|||中文：" in hist_turn["content"], str(hist_turn))
    check("历史里的日语与中文都对得上",
          hist_turn["content"].endswith(f"中文：{ZH_FULL}"), str(hist_turn))

# ---- 防回归：兜底定时器必须**按值**捕获本轮 seq ----
# 若 lambda 到点时才读 `stream_ui["seq"]`，上一轮挂下、还没到点的定时器会在下一轮
# 中途醒来、读到的已是**下一轮**的 seq → 守卫形同虚设，把下一轮的文字提前捅出来
# （实测：第 2 轮文字比声音早 ~16.6s 出现）。这里做 AST 校验（与格式无关）。
import ast as _ast

_FALLBACK_IDS = {"REPLY_TEXT_FALLBACK_MS", "reply_text_fallback_ms"}


def _is_fallback_window(node):
    """兜底窗口表达式：常量名（旧写法）或 `reply_text_fallback_ms(ja)`（现写法）。"""
    if isinstance(node, _ast.Name):
        return node.id in _FALLBACK_IDS
    if isinstance(node, _ast.Call):
        _fn = node.func
        return (getattr(_fn, "attr", None) or getattr(_fn, "id", None)) in _FALLBACK_IDS
    return False


_main_src = (BASE / "app" / "main.py").read_text(encoding="utf-8")
_leaked = []
_matched = 0
for _n in _ast.walk(_ast.parse(_main_src)):
    if not isinstance(_n, _ast.Call) or not _n.args:
        continue
    _f = _n.func
    if (getattr(_f, "attr", None) or getattr(_f, "id", None)) != "singleShot":
        continue
    if not _is_fallback_window(_n.args[0]):
        continue
    _matched += 1
    for _sub in _n.args[1:]:
        for _x in _ast.walk(_sub):
            if (isinstance(_x, _ast.Subscript) and isinstance(_x.value, _ast.Name)
                    and _x.value.id == "stream_ui"):
                _leaked.append(_x.value.id)
check("兜底定时器按值捕获本轮 seq（不在触发时读 stream_ui → 防跨轮提前出字）",
      not _leaked, "lambda 里直接读了 stream_ui（跨轮泄漏）")
check("上一条断言真的匹配到了兜底定时器（防「改了写法后断言空跑」）",
      _matched >= 1, f"matched={_matched}")

# ---- 兜底窗口必须**按日语字数自适应** ----
# 固定 20s + 日语不限长 = 70 字（实测最坏 22.58s）就会被误判成「合成卡住」→
# 主动放弃同步 → 回到「先出字、后出声」。这条把这个数量关系钉死。
check("空文本的兜底窗口 = 常量 5s", _orig_fallback_ms("") == 5000,
      str(_orig_fallback_ms("")))
_n70 = _orig_fallback_ms("あ" * 70)
check("70 字兜底窗口 > 实测最坏 22.58s（长回复不会被当成卡死）",
      _n70 > 22580, f"{_n70}ms")
check("兜底窗口随字数单调递增",
      _orig_fallback_ms("あ" * 20) < _orig_fallback_ms("あ" * 40) < _n70,
      f"{_orig_fallback_ms('あ' * 20)} / {_orig_fallback_ms('あ' * 40)} / {_n70}")
check("兜底窗口有上限（极端长回复不干等）",
      _orig_fallback_ms("あ" * 5000) == 90000,
      str(_orig_fallback_ms("あ" * 5000)))

try:
    _tmp_cfg.unlink()
except OSError:
    pass

print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)
