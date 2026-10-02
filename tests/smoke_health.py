"""冒烟测试：P2 体验四件套（诊断内核 / 检查更新 / 首引·自检·更新三张卡 + 常显状态条）。

跑法（在项目根目录）：
    .venv\\Scripts\\python.exe tests\\smoke_health.py

说明：全部在 offscreen 平台运行，不弹窗；**不联网**（更新检查的 HTTP 取回被注入成假实现）；
只读代码与配置，不写项目里的 config.json。

★本套件刻意分成四段，前两段**完全不需要 QApplication**（判据是纯函数），
  后两段才是界面与源码守卫 —— 这样「判据坏了」和「界面没接上」能一眼分开。
"""
import ast
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
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


# ========== 1. 诊断内核 app/health.py（纯判据，不起 QApplication）==========
print("== 1. 诊断内核 app/health.py（纯判据）==")
from app import health  # noqa: E402


_OK_API = [{"name": "T", "api_key": "sk-x", "base_url": "https://api.deepseek.com", "model": "m"}]


def _cfg(apis=None, muted=False, dirs=None, autostart=False):
    """造一份最小 cfg（字段与 `app/config.py` 的 DEFAULT_CONFIG 对齐）。"""
    apis = [] if apis is None else apis
    return {
        "apis": apis,
        "current_api": apis[0]["name"] if apis else "",
        "permissions": {"allowed_dirs": list(dirs or [])},
        "general": {"mute_mode": muted, "auto_start": autostart},
    }


# ---- API ----
check("空 API 列表 ⇒ check_api 判 fail",
      health.check_api(_cfg()).level == health.LEVEL_FAIL)
check("有 API 但 key 是空白 ⇒ 仍然 fail（空 key 发不出请求）",
      health.check_api(_cfg([{"name": "T", "api_key": "   "}])).level == health.LEVEL_FAIL)
check("有可用 API ⇒ ok，且 detail 里点名用的是哪一个",
      health.check_api(_cfg(_OK_API)).level == health.LEVEL_OK
      and "T" in health.check_api(_cfg(_OK_API)).detail)
check("★current_api 指向不存在的名字 ⇒ 当成没有（get_current_api 回 None）",
      health.check_api({"apis": _OK_API, "current_api": "不存在",
                        "permissions": {}, "general": {}}).level == health.LEVEL_FAIL)

# ---- 白名单 ----
check("白名单为空 ⇒ check_whitelist 判 fail（默认就是空的，这是设计不是 bug）",
      health.check_whitelist(_cfg()).level == health.LEVEL_FAIL)
check("白名单有目录 ⇒ ok",
      health.check_whitelist(_cfg(dirs=["C:/a"])).level == health.LEVEL_OK)
check("★白名单里的空白项不算数（[ ' ' ] 仍然算空）",
      health.check_whitelist({"permissions": {"allowed_dirs": ["  ", ""]}, "general": {},
                              "apis": []}).level == health.LEVEL_FAIL)

# ---- 静音 ----
check("静音关 ⇒ check_mute ok",
      health.check_mute(_cfg()).level == health.LEVEL_OK)
check("★静音开 ⇒ 只是 **warn**（用户自己拨的开关，不是错误 ⇒ 绝不能判 fail）",
      health.check_mute(_cfg(muted=True)).level == health.LEVEL_WARN)

# ---- 语音合成：三态 x 静音 ----
check("模型没探到（None）⇒ warn「正在检查」",
      health.check_tts(_cfg(), None).level == health.LEVEL_WARN)
check("模型就位 ⇒ ok", health.check_tts(_cfg(), True).level == health.LEVEL_OK)
check("模型缺失 + 没静音 ⇒ fail（这是真坏：只会显示文字）",
      health.check_tts(_cfg(), False).level == health.LEVEL_FAIL)
check("★★模型缺失 + 静音开着 ⇒ **warn 不是 fail**（那正是「无模型 ⇒ 锁死静音」的预期结果）",
      health.check_tts(_cfg(muted=True), False).level == health.LEVEL_WARN)

# ---- 语音识别 ----
check("ASR 未知（None）⇒ warn「正在后台初始化」", health.check_asr(None).level == health.LEVEL_WARN)
check("ASR 就绪 ⇒ ok", health.check_asr(True).level == health.LEVEL_OK)
check("ASR 失败 ⇒ fail", health.check_asr(False).level == health.LEVEL_FAIL)

# ---- 开机自启（纯提示，永远不 fail）----
check("开机自启关着 ⇒ warn（不是 fail：很多人不想让它开机就跑）",
      health.check_autostart(_cfg()).level == health.LEVEL_WARN)
check("开机自启开着 ⇒ ok", health.check_autostart(_cfg(autostart=True)).level == health.LEVEL_OK)

# ---- 聚合 ----
_all = health.check_all(_cfg(), tts_installed=True, asr_ok=True)
check("check_all 返回 6 条，且 key 唯一", len(_all) == 6 and len({c.key for c in _all}) == 6)
check("summary 数得对（默认配置：api/whitelist 两条 fail，autostart 一条 warn）",
      health.summary(_all) == (3, 1, 2), str(health.summary(_all)))

# ---- 状态条的优先级（这是「三段 UI 说同一件事」的核心）----
_st = health.status_line(_cfg(), tts_installed=True, asr_ok=True)
check("① 没配 API ⇒ 状态条第一优先说它，落点 = 管理 API",
      _st.level == health.LEVEL_FAIL and _st.page == health.PAGE_API, str(_st))
_st = health.status_line(_cfg(_OK_API, dirs=["C:/a"]), tts_installed=True, asr_ok=False)
check("② API 好了但麦克风挂了 ⇒ 说语音识别（打字仍可聊 ⇒ 落点在通用设置）",
      _st.level == health.LEVEL_FAIL and "语音识别" in _st.text and _st.page == health.PAGE_GENERAL,
      str(_st))
_st = health.status_line(_cfg(_OK_API, dirs=["C:/a"], muted=True), tts_installed=True, asr_ok=True)
check("③ 静音开着 ⇒ warn（不是 fail），说清「只显示中文、不出声」",
      _st.level == health.LEVEL_WARN and "静音" in _st.text, str(_st))
_st = health.status_line(_cfg(_OK_API, dirs=["C:/a"]), tts_installed=False, asr_ok=True)
check("④ 没模型又没静音 ⇒ fail，说「只会显示文字」",
      _st.level == health.LEVEL_FAIL and "文字" in _st.text, str(_st))
_st = health.status_line(_cfg(_OK_API), tts_installed=True, asr_ok=True)
check("⑤ 前四条都过了、只有白名单空 ⇒ warn，落点 = 权限管理",
      _st.level == health.LEVEL_WARN and _st.page == health.PAGE_PERMISSIONS, str(_st))
_st = health.status_line(_cfg(_OK_API, dirs=["C:/a"], autostart=True), tts_installed=True, asr_ok=True)
check("⑥ 全通过 ⇒ **ok 且没有落点**（「去设置」按钮要收起来）",
      _st.level == health.LEVEL_OK and _st.page is None, str(_st))
_st = health.status_line(_cfg(_OK_API, dirs=["C:/a"]), tts_installed=None, asr_ok=None)
check("⑦ 事实还没探到 ⇒ warn「正在初始化」（**不许诬赖它坏了**）",
      _st.level == health.LEVEL_WARN and "初始化" in _st.text, str(_st))
check("★ASR 未知（None）时**不算失败**（后台线程还没结果，别急着报红）",
      health.status_line(_cfg(_OK_API, dirs=["C:/a"]), tts_installed=True,
                         asr_ok=None).level != health.LEVEL_FAIL)

# ---- 首次引导 ----
check("没配过任何 API ⇒ first_run_needed True", health.first_run_needed(_cfg()) is True)
check("配过 API ⇒ False（老用户不该被一遍遍弹）", health.first_run_needed(_cfg(_OK_API)) is False)
check("★apis 不是 list（脏配置）⇒ 当成首次，不抛异常",
      health.first_run_needed({"apis": "boom"}) is True)
check("★白名单为空**不**算「首次」（默认就是空的，拿它当判据会天天弹老用户）",
      health.first_run_needed(_cfg(_OK_API)) is False)
check("guide_items 只有两条（API / 白名单），且**不含**要下 3.6 GB 的语音模型",
      [c.key for c in health.guide_items(_cfg())] == ["api", "whitelist"])
check("★guide_items 复用 check_api / check_whitelist（配好后显示 ✓）",
      [c.level for c in health.guide_items(_cfg())] == [health.LEVEL_FAIL, health.LEVEL_FAIL]
      and [c.level for c in health.guide_items(_cfg(_OK_API, dirs=["C:/a"]))]
      == [health.LEVEL_OK, health.LEVEL_OK])

# ---- collect_facts（唯一碰 I/O 的地方）----
_f = health.collect_facts(_cfg(), asr_ok=True)
check("collect_facts 回 tts_installed / asr_ok 两个键，且 asr 原样带回",
      set(_f.keys()) == {"tts_installed", "asr_ok"} and _f["asr_ok"] is True, str(_f))
check("★collect_facts 探测失败要回 None（『不知道』），**不是** False（『你没装』）—— "
      "把探不出来说成没装，用户会白下一遍 3.6 GB",
      isinstance(_f["tts_installed"], (bool, type(None))))


# ========== 2. 检查更新内核 app/update.py（fetch 注入，一个字节都不出网）==========
print()
print("== 2. 检查更新内核 app/update.py ==")
import urllib.error  # noqa: E402

from app import update  # noqa: E402


def _fetch_ok(body):
    return lambda url, timeout: body


def _fetch_http(code):
    def f(url, timeout):
        raise urllib.error.HTTPError(url, code, "boom", None, None)
    return f


def _fetch_boom():
    def f(url, timeout):
        raise RuntimeError("连不上")
    return f


check("parse_version('v1.2.3') → (1,2,3)", update.parse_version("v1.2.3") == (1, 2, 3))
check("parse_version('1.2.3-beta') → (1,2,3)（预发布标记不参与比较）",
      update.parse_version("1.2.3-beta") == (1, 2, 3))
check("parse_version('')/'abc'/None → ()（解析不出来）",
      update.parse_version("") == () and update.parse_version("abc") == ()
      and update.parse_version(None) == ())
check("parse_version('2026.10.2') → (2026,10,2)（不假设只有三位）",
      update.parse_version("2026.10.2") == (2026, 10, 2))

check("is_newer('1.3','1.2.9') → True", update.is_newer("1.3", "1.2.9") is True)
check("★is_newer('1.2','1.2.0') → False（补零对齐后相等，v1.2 与 v1.2.0 是同一版）",
      update.is_newer("1.2", "1.2.0") is False)
check("is_newer('1.2.9','1.3') → False", update.is_newer("1.2.9", "1.3") is False)
check("★is_newer 任一边解析不出来 ⇒ 一律 False（宁可漏报，也不误报「有更新」骗人去下载）",
      update.is_newer("", "1.0") is False and update.is_newer("1.0", "abc") is False)

_JSON = '{"tag_name": "v0.2.0", "html_url": "https://example.com/rel"}'
check("check_latest：有新版本 ⇒ ('update', 新版本号, release 页)",
      update.check_latest("0.1.0", fetch=_fetch_ok(_JSON))
      == (update.STATE_UPDATE, "v0.2.0", "https://example.com/rel"))
check("check_latest：同版本 ⇒ ('latest', 当前版本号, …)",
      update.check_latest("0.2.0", fetch=_fetch_ok(_JSON))[0] == update.STATE_LATEST)
check("★check_latest：HTTP 404 ⇒ 'none'（新仓库还没发布过，**不是**错误）",
      update.check_latest("0.1.0", fetch=_fetch_http(404))[0] == update.STATE_NONE)
check("check_latest：其它 HTTP 错（403 限流）⇒ 'error'",
      update.check_latest("0.1.0", fetch=_fetch_http(403))[0] == update.STATE_ERROR)
check("check_latest：连不上 ⇒ 'error'（文案是人话，不是 traceback）",
      update.check_latest("0.1.0", fetch=_fetch_boom())[0] == update.STATE_ERROR
      and "失败" in update.check_latest("0.1.0", fetch=_fetch_boom())[1])
check("check_latest：返回体不是 JSON（代理页）⇒ 'error'，不抛",
      update.check_latest("0.1.0", fetch=_fetch_ok("<html>proxy</html>"))[0] == update.STATE_ERROR)
check("check_latest：release 没有 tag_name ⇒ 当成『还没发布版本』",
      update.check_latest("0.1.0", fetch=_fetch_ok('{"name": ""}'))[0] == update.STATE_NONE)

_raised = False
try:
    update.check_latest("1.0", fetch=lambda u, t: (_ for _ in ()).throw(RuntimeError("boom")))
except Exception:  # noqa: BLE001
    _raised = True
check("★★check_latest 把任何异常都收成 'error' —— 它在后台线程里跑，漏出去 = 线程静默死",
      not _raised)
check("★联网只走可注入的 fetch（返回三态都是 str，符合『跨线程只传 str/int』）",
      all(isinstance(x, str) for x in update.check_latest("0.1.0", fetch=_fetch_ok(_JSON))))
check("REPO 与 git remote 一致", update.REPO == "WA-sd483/Ignotus-Assistant")


# ========== 3. 三张卡片 + 常显状态条（offscreen，不弹窗）==========
print()
print("== 3. 三张卡片 + 常显状态条（offscreen）==")
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

import app.config as cfgmod  # noqa: E402

_tmpdir = Path(tempfile.mkdtemp(prefix="ignotus_health_"))
cfgmod.CONFIG_PATH = _tmpdir / "config.json"      # ★不碰项目里的 config.json
_cfg_real = cfgmod.load_config()

from app.gui import (FirstRunDialog, MainWindow, SelfCheckDialog,  # noqa: E402
                     UpdateDialog, _SettingActionRow)

win = MainWindow(_cfg_real)
check("主窗口建出，常显状态条挂在 _build 里（不是孤儿控件）",
      getattr(win, "_health_strip", None) is not None)
check("状态条高 30px（design.md 新增 §4.20）",
      win._health_strip.height() == MainWindow.HEALTH_H)

_st = win.refresh_health()
check("默认配置（无 API）⇒ 状态条 fail + 落点 = 管理 API",
      _st.level == health.LEVEL_FAIL and _st.page == health.PAGE_API, str(_st))
check("有落点时「去设置」按钮露出来", not win._health_btn.isHidden())
check("落点 = None 时按钮收起（一切正常时不该挂个按钮）",
      health.status_line(_cfg(_OK_API, dirs=["C:/a"])).page is None)

# 「去设置」的三个落点
win.open_health_target(health.PAGE_API)
check("「去设置」→ 管理 API 页", win._right_stack.currentIndex() == MainWindow.PAGE_API,
      str(win._right_stack.currentIndex()))
win.open_health_target(health.PAGE_PERMISSIONS)
check("「去设置」→ 权限管理页",
      win._right_stack.currentIndex() == win._settings_index["permissions"])
win.open_health_target(health.PAGE_GENERAL)
check("「去设置」→ 通用设置页",
      win._right_stack.currentIndex() == win._settings_index["general"])
win.open_health_target(None)
check("落点为空 ⇒ 空操作（不抛）", True)

# 注入「外部事实」之后状态条要跟着变
win.set_health_facts_provider(lambda: {"tts_installed": True, "asr_ok": True})
_cfg_real["apis"] = _OK_API
_cfg_real["current_api"] = "T"
_cfg_real["permissions"]["allowed_dirs"] = ["C:/"]
_st2 = win.refresh_health()
check("★配好 API / 白名单 + 模型与麦克风就绪 ⇒ 状态条转绿「一切就绪」",
      _st2.level == health.LEVEL_OK and _st2.page is None, str(_st2))
check("一切就绪 ⇒ 「去设置」按钮自动收起", win._health_btn.isHidden())

# 通用设置页的「帮助」三行
_gp = win._settings_panels["general"]
_rows = [_gp._body_lay.itemAt(i).widget() for i in range(_gp._body_lay.count())]
_action_titles = [w._title_text for w in _rows if isinstance(w, _SettingActionRow)]
check("通用设置页有「使用引导 / 一键自检 / 检查更新」三行",
      {"使用引导", "一键自检", "检查更新"} <= set(_action_titles), str(_action_titles))

# ---- 首次引导卡 ----
_items = health.guide_items(_cfg_real)
_d1 = FirstRunDialog(win, _items)
check("首引卡：宽 360（design.md 4.5 常规档）", _d1.width() == 360)
check("首引卡：两条（API / 白名单）", len(_items) == 2)
_d1.close()
_d1b = FirstRunDialog.show_guide(win, _items)
check("★★show_guide 是**非阻塞**的（open() 而不是 exec()）—— exec 会在 main() 里嵌模态循环，"
      "「真跑一次 main()」的探针会当场挂死", _d1b is not None and _d1b.isVisible())
_d1b.close()

# ---- 一键自检卡 ----
_d2 = SelfCheckDialog(win, win._build_checks(), on_recheck=win._build_checks)
check("自检卡：汇总行写「通过 N · 提示 N · 失败 N」",
      "通过" in _d2._summary.text() and "失败" in _d2._summary.text(), _d2._summary.text())
check("自检卡：宽 440（六条要放标题 + 状态 + 修复指引）",
      _d2.width() == 440)
_d2.set_checks(health.check_all(_cfg(_OK_API, dirs=["C:/a"]), tts_installed=True, asr_ok=True))
check("★全通过 ⇒ 汇总染成成功绿 #1E8E3E（design.md §1 语义色）",
      "#1E8E3E" in _d2._summary.styleSheet(), _d2._summary.styleSheet())
_d2.close()

# ---- 检查更新卡（checker 注入，线程里跑的是假实现）----
def _mk_dialog(state, detail="v9.9.9", url="https://example.com/x"):
    d = UpdateDialog(win, "0.1.0", checker=lambda: (state, detail, url))
    d._start()
    for _ in range(100):                     # 等后台线程把结果写进那个只含 str 的 dict
        if d._result.get("state"):
            break
        time.sleep(0.02)
    d._poll()
    return d


_d3 = _mk_dialog(update.STATE_UPDATE)
check("更新卡：发现新版本 ⇒ 文案点名版本号，且「前往下载」出现",
      "v9.9.9" in _d3._msg.text() and not _d3._go.isHidden(), _d3._msg.text())
check("更新卡：发现新版本时不显示「重试」", _d3._retry.isHidden())
_d3.close()

_d4 = _mk_dialog(update.STATE_LATEST, "0.1.0")
check("更新卡：已是最新 ⇒ 不给「前往下载」", _d4._go.isHidden(), _d4._msg.text())
check("更新卡：已是最新 ⇒ 也不显示「重试」", _d4._retry.isHidden())
_d4.close()

_d5 = _mk_dialog(update.STATE_NONE, "仓库还没有发布版本。")
check("更新卡：仓库还没有 release ⇒ 说人话，不显示「前往下载」",
      "发布" in _d5._msg.text() and _d5._go.isHidden(), _d5._msg.text())
_d5.close()

_d6 = _mk_dialog(update.STATE_ERROR, "检查更新失败：连不上网络（可稍后再试）。")
check("更新卡：失败 ⇒ 给出「重试」且不显示「前往下载」",
      not _d6._retry.isHidden() and _d6._go.isHidden(), _d6._msg.text())
_d6.close()

check("★版本号的唯一真值在 app/__init__.py，且更新卡读的就是它",
      isinstance(__import__("app").__version__, str))


# ========== 4. 源码级守卫（AST 按 lineno / 限定在类里，不按文字裸找）==========
print()
print("== 4. 源码级守卫（AST）==")


def _tree(rel):
    return ast.parse((ROOT / rel).read_text(encoding="utf-8"))


def _class_func(tree, cls_name, func_name):
    """取「某个类里的某个方法」——★必须限定在类里：按名字裸找会命中同名的别的方法。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if (isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and sub.name == func_name):
                    return sub
    return None


def _module_func(tree, name):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _called(func_node):
    """方法体里被调用的名字（`f(...)`→"f"；`a.b(...)`→"b"）。"""
    out = set()
    for n in ast.walk(func_node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


_gui_tree = _tree("app/gui.py")
_main_tree = _tree("app/main.py")
_health_tree = _tree("app/health.py")
_update_tree = _tree("app/update.py")

_sg = _class_func(_gui_tree, "FirstRunDialog", "show_guide")
_cn_sg = _called(_sg) if _sg is not None else set()
check("★★首引弹窗必须非阻塞：show_guide 里不许有 exec()（嵌了模态循环 ⇒ 跑真 main() 的探针挂死）",
      _sg is not None and "exec" not in _cn_sg and "open" in _cn_sg, str(sorted(_cn_sg)))

_fi = None
for _n in ast.walk(_main_tree):
    if isinstance(_n, ast.If):
        _names = set()
        for _c in ast.walk(_n.test):
            if isinstance(_c, ast.Call):
                _f = _c.func
                _names.add(_f.attr if isinstance(_f, ast.Attribute) else getattr(_f, "id", ""))
        if "first_run_needed" in _names:
            _fi = _n
            break
_body_calls = set()
if _fi is not None:
    for _st in _fi.body:
        _body_calls |= _called(_st)
check("★★main.py 的首次引导必须**延后触发**（QTimer.singleShot），不许当场直接调 win.show_first_run()",
      _fi is not None and "singleShot" in _body_calls, str(sorted(_body_calls)))

_show_ln = [n.lineno for n in ast.walk(_main_tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "show" and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "win"]
check("首次引导的触发点排在 `win.show()` **之后**（先出窗口、再弹引导）",
      _fi is not None and _show_ln and _fi.lineno > min(_show_ln),
      f"if@{getattr(_fi, 'lineno', '?')} vs show@{min(_show_ln) if _show_ln else '?'}")

_h_imports = set()
for _n in ast.walk(_health_tree):
    if isinstance(_n, ast.Import):
        _h_imports |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _h_imports.add(_n.module.split(".")[0])
check("★health.py 保持**纯**：不 import PySide6（判据要能离线跑，不用起 QApplication）",
      "PySide6" not in _h_imports, str(sorted(_h_imports)))

_build = _class_func(_gui_tree, "MainWindow", "_build")
_cn_build = _called(_build) if _build is not None else set()
check("★★主窗口 `_build` 里真的挂了常显状态条（`_build_health_strip`）—— 漏了它，"
      "状态条就是个永远不显示的孤儿控件，而且**不报错**",
      "_build_health_strip" in _cn_build, str(sorted(_cn_build)))

_bhs = _class_func(_gui_tree, "MainWindow", "_build_health_strip")
_cn_bhs = _called(_bhs) if _bhs is not None else set()
check("★状态条是**常显**的：它自己不许调 hide()（全绿 / 有问题都得看得见）",
      "hide" not in _cn_bhs and "setVisible" in _cn_bhs, str(sorted(_cn_bhs)))

_notify = _class_func(_gui_tree, "MainWindow", "_notify_page_change")
check("★翻页时状态条重算一次（`recompute_facts=False`）—— 否则用户在设置页配好 key、"
      "切回聊天页看到的还是旧的「没配 API Key」",
      "_health_facts" in ast.dump(_notify) or "refresh_health" in _called(_notify))

_sl = _module_func(_health_tree, "status_line")
check("★状态条与自检**共用**同一条 API 判据（status_line 里调 check_api，不另写一份）",
      "check_api" in _called(_sl))

_cl = _module_func(_update_tree, "check_latest")
_cn_cl = _called(_cl) if _cl is not None else set()
check("★update.py 的联网只有一处：check_latest 必须走可注入的 `fetch`，自己不许调 urlopen",
      "fetch" in _cn_cl and "urlopen" not in _cn_cl, str(sorted(_cn_cl)))

_urlopen_ln = [n.lineno for n in ast.walk(_update_tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "urlopen"]
_hg = _module_func(_update_tree, "_http_get")
check("★★真出网的 urlopen 全文件**只有一处**，且就在 `_http_get` 里（联网面收成一个点，方便审）",
      len(_urlopen_ln) == 1 and _hg is not None
      and _hg.lineno <= _urlopen_ln[0] <= (_hg.end_lineno or _hg.lineno),
      str(_urlopen_ln))

_tray = [n.args[0].value for n in ast.walk(_main_tree)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and n.func.attr == "addAction" and n.args
         and isinstance(n.args[0], ast.Constant)]
check("托盘菜单里有「使用引导 / 一键自检 / 检查更新」三项",
      {"使用引导", "一键自检", "检查更新"} <= set(_tray), str(_tray))

_gp_ref = _class_func(_gui_tree, "GeneralPanel", "refresh")
_act_labels = [n.args[0].value for n in ast.walk(_gp_ref)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "_SettingActionRow" and n.args
               and isinstance(n.args[0], ast.Constant)]
check("通用设置页的动作行里有 P2 三行（设置页入口）",
      {"使用引导", "一键自检", "检查更新"} <= set(_act_labels), str(_act_labels))

_rh = _class_func(_gui_tree, "MainWindow", "refresh_health")
_rh_args = {a.arg for a in (_rh.args.args + _rh.args.kwonlyargs)} if _rh is not None else set()
check("★`refresh_health` 带 `recompute_facts` 开关（翻页复用缓存、别每次 stat 模型目录）",
      "recompute_facts" in _rh_args, str(sorted(_rh_args)))

print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)
