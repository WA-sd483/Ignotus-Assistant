"""冒烟测试：诊断内核（app/health.py）+ 检查更新内核（app/update.py）
+ 首引·自检·更新·API 说明·模型安装五张卡 + 启动提示区 + 每角色独立 API。

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


_ALICE_API = [{"name": "T", "api_key": "sk-x", "base_url": "https://api.deepseek.com", "model": "m"}]


def _cfg(apis=None, muted=False, dirs=None, autostart=False, role="alice"):
    """造一份最小 cfg（字段与 `app/config.py` 的 DEFAULT_CONFIG 对齐）。

    ★2026-10-02 起 API 是**每个角色一份独立列表**，所以这里也按角色造。
    """
    apis = [] if apis is None else apis
    return {
        "apis": {"alice": list(apis), "ellen": []},
        "current_api": {"alice": apis[0]["name"] if apis else "", "ellen": ""},
        "current_role": role,
        "roles": {"alice": {"name": "爱丽丝"}, "ellen": {"name": "艾莲"}},
        "permissions": {"allowed_dirs": list(dirs or [])},
        "general": {"mute_mode": muted, "auto_start": autostart},
    }


# ---- API（★按角色取）----
check("空 API 列表 ⇒ check_api 判 fail",
      health.check_api(_cfg()).level == health.LEVEL_FAIL)
check("有 API 但 key 是空白 ⇒ 仍然 fail（空 key 发不出请求）",
      health.check_api(_cfg([{"name": "T", "api_key": "   "}])).level == health.LEVEL_FAIL)
check("有可用 API ⇒ ok，且 detail 里点名用的是哪一个",
      health.check_api(_cfg(_ALICE_API)).level == health.LEVEL_OK
      and "T" in health.check_api(_cfg(_ALICE_API)).detail)
check("★current_api 指向不存在的名字 ⇒ 当成没有（get_current_api 回 None）",
      health.check_api({"apis": {"alice": _ALICE_API}, "current_api": {"alice": "不存在"},
                        "permissions": {}, "general": {}}).level == health.LEVEL_FAIL)
check("★★check_api 只看**当前角色**那一份：艾莲配了 key、爱丽丝没配 ⇒ 仍然 fail",
      health.check_api({"apis": {"alice": [], "ellen": _ALICE_API},
                        "current_api": {"alice": "", "ellen": "T"},
                        "current_role": "alice", "permissions": {}, "general": {}})
      .level == health.LEVEL_FAIL)

# ---- 白名单 ----
check("白名单为空 ⇒ check_whitelist 判 fail（默认就是空的，这是设计不是 bug）",
      health.check_whitelist(_cfg()).level == health.LEVEL_FAIL)
check("白名单有目录 ⇒ ok",
      health.check_whitelist(_cfg(dirs=["C:/a"])).level == health.LEVEL_OK)
check("★白名单里的空白项不算数（[ ' ' ] 仍然算空）",
      health.check_whitelist({"permissions": {"allowed_dirs": ["  ", ""]}, "general": {},
                              "apis": {}}).level == health.LEVEL_FAIL)

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

# ---- ★启动提示区（2026-10-02 改口径：白名单常显 + 语音只启动说一次）----
# 文案是**用户逐字给的**，这里钉死，防以后被"顺手润色"掉。
_WL_TEXT = "可操作目录为空 —— 「打开文件 / 查看目录」指令会被拒绝。可在权限管理内添加"
check("★白名单那个 Notice 的文案与用户口径逐字一致",
      health.whitelist_notice(_cfg()).text == _WL_TEXT, health.whitelist_notice(_cfg()).text)
check("★白名单那条**不自动消失**（auto_ms=0 ⇒ 只能手动点 ✕）",
      health.whitelist_notice(_cfg()).auto_ms == 0)
check("★白名单不空 ⇒ 那条 Notice 是 None（没话说就别占屏幕）",
      health.whitelist_notice(_cfg(dirs=["C:/a"])) is None)
check("★白名单那条是 warn 档（黄，不是红 —— 默认就是空的，这是设计）",
      health.whitelist_notice(_cfg()).level == health.LEVEL_WARN)

check("★没装模型 ⇒ 「当前未安装音色克隆模型，默认开启静音模式」",
      health.voice_notice(_cfg(), False).text == "当前未安装音色克隆模型，默认开启静音模式",
      str(health.voice_notice(_cfg(), False)))
check("★有模型 + 静音开着 ⇒ 「当前为静音模式，无语音输出」",
      health.voice_notice(_cfg(muted=True), True).text == "当前为静音模式，无语音输出",
      str(health.voice_notice(_cfg(muted=True), True)))
check("★有模型 + 静音关着 ⇒ 「静音模式已关闭，输出时间可能较慢」",
      health.voice_notice(_cfg(), True).text == "静音模式已关闭，输出时间可能较慢",
      str(health.voice_notice(_cfg(), True)))
check("★★事实还没探到（None）⇒ **不出**语音那条（宁可不提示，也不说假话）",
      health.voice_notice(_cfg(), None) is None)
check("★语音那条的存活时间 = 5s（用户口径：右侧 5s 倒计时）",
      health.voice_notice(_cfg(), True).auto_ms == health.NOTICE_VOICE_MS == 5000)
check("★语音那条：没装模型时不因静音开着而改口径（模型优先）",
      health.voice_notice(_cfg(muted=True), False).text
      == "当前未安装音色克隆模型，默认开启静音模式")

_notes = health.startup_notices(_cfg(), tts_installed=True)
check("★startup_notices 的顺序 = **白名单在前、语音在其下**（用户口径）",
      [n.key for n in _notes] == ["whitelist", "voice"], str([n.key for n in _notes]))
check("白名单不空时 startup_notices 只剩语音那条",
      [n.key for n in health.startup_notices(_cfg(dirs=["C:/a"]), tts_installed=True)] == ["voice"])
check("★没配 API / 麦克风坏掉**都不在**提示区里（只走聊天灰字，用户 2026-10-02 口径）",
      "api" not in {n.key for n in health.startup_notices(_cfg(), tts_installed=True)})

# ---- 首次引导 / 新手判据 ----
check("没配过任何 API ⇒ first_run_needed True", health.first_run_needed(_cfg()) is True)
check("配过 API ⇒ False（老用户不该被一遍遍弹）", health.first_run_needed(_cfg(_ALICE_API)) is False)
check("★任一角色配过就算配过（艾莲配了、爱丽丝没配 ⇒ 不算新手）",
      health.first_run_needed({"apis": {"alice": [], "ellen": _ALICE_API},
                               "current_api": {"alice": "", "ellen": "T"},
                               # ★★这份 cfg **必须**带 `roles`：`role_keys` 读不到 roles 时会
                               #   回落到只含 LEGACY_API_ROLE（=alice）的默认 —— 那样 ellen 那份
                               #   压根不在遍历范围里，「任一角色配过就算配过」就测不到了
                               "roles": {"alice": {"name": "爱丽丝"}, "ellen": {"name": "艾莲"}}})
      is False)
check("★apis 是脏类型（字符串）⇒ 当成首次，不抛异常",
      health.first_run_needed({"apis": "boom"}) is True)
check("★白名单为空**不**算「首次」（默认就是空的，拿它当判据会天天弹老用户）",
      health.first_run_needed(_cfg(_ALICE_API)) is False)
check("guide_items 只有两条（API / 白名单），且**不含**要下 3.6 GB 的语音模型",
      [c.key for c in health.guide_items(_cfg())] == ["api", "whitelist"])
check("★guide_items 复用 check_api / check_whitelist（配好后显示 ✓）",
      [c.level for c in health.guide_items(_cfg())] == [health.LEVEL_FAIL, health.LEVEL_FAIL]
      and [c.level for c in health.guide_items(_cfg(_ALICE_API, dirs=["C:/a"]))]
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


# ========== 3. 五张卡片 + 启动提示区（offscreen，不弹窗）==========
print()
print("== 3. 五张卡片 + 启动提示区（offscreen）==")
from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

_app = QApplication.instance() or QApplication([])

import app.config as cfgmod  # noqa: E402

_tmpdir = Path(tempfile.mkdtemp(prefix="ignotus_health_"))
cfgmod.CONFIG_PATH = _tmpdir / "config.json"      # ★不碰项目里的 config.json
_cfg_real = cfgmod.load_config()

from app.gui import (ApiHelpDialog, FirstRunDialog, MainWindow,  # noqa: E402
                     ModelSetupDialog, SelfCheckDialog, UpdateDialog,
                     _SettingActionRow)

win = MainWindow(_cfg_real)
win.show()
_app.processEvents()

# ---- 启动提示区（2026-10-02 改口径：**浮层**，不进布局 + 阴影）----
check("主窗口建出，提示区挂在 _build 里（不是孤儿控件）",
      getattr(win, "_notice_area", None) is not None)
_na = win._notice_area
check("★★提示区是**浮层**：parent = 主窗口、**不在布局里**（2026-10-02 用户点："
      "关掉提示时下方界面会整体上移）—— 挂在布局里就占着 30px 的布局高度，一关就整屏上跳；"
      "不进布局 ⇒ 它的显隐**完全不参与布局计算**",
      _na.parentWidget() is win
      and win.layout().indexOf(_na) == -1
      and all(win.layout().itemAt(i).widget() is not _na
              for i in range(win.layout().count())),
      "parent_ok=%r in_layout=%r" % (_na.parentWidget() is win,
                                     win.layout().indexOf(_na) != -1))
check("★提示区摆到「标题栏正下方、整窗宽」（**位置自己算**：`_position_notice_area`）",
      hasattr(win, "_titlebar")
      and _na.x() == 0 and _na.y() == win._titlebar.height() and _na.width() == win.width(),
      "geom=%r titlebar_h=%d win_w=%d" % (_na.geometry(), win._titlebar.height(), win.width()))
check("★★提示区有**阴影**（第五批用户口径「要加点阴影」）—— 没有影子的话，「浮在上层」这件事"
      "在浅蓝底 / 白底之间根本看不出来，看着就是一条普通的分隔条",
      _na.graphicsEffect() is not None
      and win.NOTICE_SHADOW_BLUR > 0 and win.NOTICE_SHADOW_DY >= 0,
      repr(_na.graphicsEffect()))
check("★阴影**已调淡**（第六批用户口径「把阴影改得更淡一点」）：α=45 / blur=16 / dy=4 ——"
      "真机抓像素 α=70 ⇒ `#C5CCD5`，α=45 ⇒ `#DADDE3`（淡约 1/3）。α 一旦回到 70 这条就红",
      win.NOTICE_SHADOW_RGBA == (15, 42, 80, 45)
      and win.NOTICE_SHADOW_BLUR == 16 and win.NOTICE_SHADOW_DY == 4,
      "rgba=%r blur=%r dy=%r" % (win.NOTICE_SHADOW_RGBA, win.NOTICE_SHADOW_BLUR,
                                 win.NOTICE_SHADOW_DY))
check("★每行高 30px（design.md 新增 §4.20 那一档）",
      win.NOTICE_ROW_H == 30 and win._perm_row[0].height() == 30)
check("★启动前两行都收着（`_notice_on` 是空 ⇒ 不占屏幕）",
      win._notice_on == {} and not _na.isVisible(), str(win._notice_on))

win.set_health_facts_provider(lambda: {"tts_installed": True, "asr_ok": True})
win.refresh_health()
_app.processEvents()
check("★白名单为空 ⇒ 那一行立刻显示，文案与用户口径逐字一致",
      win._notice_on.get("whitelist") is True and win._perm_row[2].text() == _WL_TEXT,
      win._perm_row[2].text())
check("★提示区高度按行数收放（1 行 = 30px）",
      win._notice_area.height() == 30 and win._notice_area.isVisible(),
      str(win._notice_area.height()))
check("★那一行的右侧有一颗 ✕（白名单那条**没有**倒计时）",
      isinstance(win._perm_row[4], QPushButton) and win._perm_row[4].text() == "✕"
      and not win._perm_row[3].isVisible())

win.show_startup_notices()
_app.processEvents()
check("★有模型 + 静音关着 ⇒ 启动时那条语音提示 =「静音模式已关闭，输出时间可能较慢」",
      win._voice_row[2].text() == "静音模式已关闭，输出时间可能较慢", win._voice_row[2].text())
check("★语音那条右侧带 5s 倒计时（起手就是 5s）",
      win._voice_row[3].isVisible() and win._voice_row[3].text() == "5s",
      win._voice_row[3].text())
check("★两行都在 ⇒ 提示区 60px，且**系统顺序**是白名单在上、语音在下",
      win._notice_area.height() == 60
      and win._perm_row[0].parentWidget() is win._voice_row[0].parentWidget(),
      str(win._notice_area.height()))

# 倒计时走完 ⇒ 自动消失
for _ in range(5):
    win._tick_voice_notice()
_app.processEvents()
check("★★倒计时走完语音那条自动消失（只剩白名单那一行）",
      win._notice_on == {"whitelist": True} and win._notice_area.height() == 30,
      str(win._notice_on))
win.refresh_health(recompute_facts=False)
_app.processEvents()
check("★★语音那条**不会**被 refresh_health 复活（启动只显示一次）",
      win._notice_on == {"whitelist": True}, str(win._notice_on))

# 白名单加上目录 ⇒ 那一行当场消失
_cfg_real["permissions"]["allowed_dirs"] = ["C:/"]
win.refresh_health(recompute_facts=False)
_app.processEvents()
check("★白名单加了目录 ⇒ 那一行当场消失、整块提示区收起来（高度 0）",
      win._notice_on == {} and win._notice_area.height() == 0
      and not win._notice_area.isVisible(), str(win._notice_on))
_cfg_real["permissions"]["allowed_dirs"] = []
win.refresh_health(recompute_facts=False)
_app.processEvents()

# ✕ 关掉白名单那条
win._perm_row[4].click()
_app.processEvents()
check("★点 ✕ 关掉白名单那条 ⇒ 本次运行不再显示",
      win._notice_on == {} and not win._notice_area.isVisible(), str(win._notice_on))
win.refresh_health(recompute_facts=False)
_app.processEvents()
check("★✕ 关过之后 refresh_health 不许把它弄回来（`_perm_dismissed` 记忆）",
      win._notice_on == {} and win._perm_dismissed is True, str(win._notice_on))

# 语音那三档（重新开一个窗口，逐个换事实）
def _fresh_win(facts):
    w = MainWindow(cfgmod.load_config())
    w.set_health_facts_provider(lambda: dict(facts))
    w.show()
    w.refresh_health()
    w.show_startup_notices()
    _app.processEvents()
    return w


_w1 = _fresh_win({"tts_installed": False, "asr_ok": True})
check("★没装模型 ⇒ 提示区说「当前未安装音色克隆模型，默认开启静音模式」",
      _w1._voice_row[2].text() == "当前未安装音色克隆模型，默认开启静音模式",
      _w1._voice_row[2].text())
_w1.deleteLater()

_cfg_mute = cfgmod.load_config()
_cfg_mute["general"]["mute_mode"] = True
_w2 = MainWindow(_cfg_mute)
_w2.set_health_facts_provider(lambda: {"tts_installed": True, "asr_ok": True})
_w2.show()
_w2.refresh_health()
_w2.show_startup_notices()
_app.processEvents()
check("★有模型 + 静音开着 ⇒ 提示区说「当前为静音模式，无语音输出」",
      _w2._voice_row[2].text() == "当前为静音模式，无语音输出", _w2._voice_row[2].text())
_w2.deleteLater()

_w3 = _fresh_win({"tts_installed": None, "asr_ok": None})
check("★事实还没探到（None）⇒ 语音那条根本不出现（不说假话）",
      "voice" not in _w3._notice_on, str(_w3._notice_on))
_w3.deleteLater()

# ---- ★★浮层存在的**全部意义**：关掉提示时下方界面一个像素都不许动（2026-10-02 用户点）----
from PySide6.QtCore import QPoint  # noqa: E402

_wn = MainWindow(cfgmod.load_config())
_wn.set_health_facts_provider(lambda: {"tts_installed": False, "asr_ok": True})
_wn.show()
_wn.refresh_health()
_wn.show_startup_notices()
_app.processEvents()
check("★两行都在 ⇒ 提示区 60px（浮层高度 = 行数 × 30；位置由 `_position_notice_area` 给）",
      _wn._notice_area.height() == 60, str(_wn._notice_area.height()))
_y0 = _wn._chat_view.mapTo(_wn, QPoint(0, 0)).y()
_h0 = _wn._chat_view.height()
_wn._perm_row[4].click()
_wn._voice_row[4].click()
_app.processEvents()
_y1 = _wn._chat_view.mapTo(_wn, QPoint(0, 0)).y()
_h1 = _wn._chat_view.height()
check("★★关掉两条提示 ⇒ 下方界面**纹丝不动**（dy == 0 且 dh == 0）—— 提示区要是还挂在"
      "布局里，这里会量到 dy == 60（整屏上跳），正是用户报的那个「内容出现上移」",
      (_y1 - _y0, _h1 - _h0) == (0, 0),
      "dy=%d dh=%d（chat_view y %d→%d / h %d→%d）" % (_y1 - _y0, _h1 - _h0, _y0, _y1, _h0, _h1))
_wn.resize(1000, 640)
_app.processEvents()
check("★窗口变宽 ⇒ 浮层跟着长到整窗宽（它不归布局管，只能自己在 `resizeEvent` 里重摆）",
      _wn._notice_area.width() == 1000 and _wn._notice_area.x() == 0
      and _wn._notice_area.y() == _wn._titlebar.height(),
      str(_wn._notice_area.geometry()))
_wn.resize(860, 640)
_app.processEvents()
_wn.deleteLater()

# ---- 权限被拒的「出路」（用户点三）----
win.open_nav_page(0)                      # 先回聊天页
_app.processEvents()
_hint = win.notify_permission_denied()
check("★权限被拒 ⇒ 出一条**带链接**的灰字（正文 + 可点的「去添加」）",
      _hint is not None and "去添加" in _hint.text() and "href" in _hint.text(),
      _hint.text() if _hint is not None else "None")
_hint.linkActivated.emit("#go")
_app.processEvents()
check("★★点「去添加」真的跳到权限管理页",
      win._right_stack.currentIndex() == win._settings_index["permissions"],
      str(win._right_stack.currentIndex()))
win.open_nav_page(0)
_app.processEvents()

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

# ---- API 说明卡（用户点一：标题旁的 ? ；2026-10-02 用户再点：**去掉标题**）----
_dh = ApiHelpDialog(win)
check("API 说明卡：宽 360", _dh.width() == 360)
# ★★2026-10-02 用户点：「弹窗高度需要与文本适配，现在有大量多余空白」。
#   正文那行是 `wordWrap` + 横向 `Ignored` 的 QLabel ⇒ 布局在**还不知道最终宽度**时算出的
#   `sizeHint` 是按最窄宽（138px）算的（实测 138×257），卡片宽 360 时正文其实只要 60px。
#   ⇒ **不许**用 `adjustSize()` / `sizeHint`，必须按 `heightForWidth(内容宽)` 钉死。
_body_lbl = _dh.findChildren(QLabel)[0]
check("★★说明卡高度 == `_card_height(正文)`（**按正文实际换行高度钉死**，不是 "
      "`adjustSize()`/`sizeHint`）—— 正文可用宽 = 卡片宽 − 左右内边距 − **左右边框**"
      "（那个 1px 边框最容易漏）",
      _dh.height() == ApiHelpDialog._card_height(_body_lbl)
      and ApiHelpDialog._content_w() == 360 - 24 * 2 - 1 * 2,
      "h=%d expect=%d content_w=%d" % (_dh.height(),
                                       ApiHelpDialog._card_height(_body_lbl),
                                       ApiHelpDialog._content_w()))
check("★★说明卡的高度**远小于**旧值 257（旧写法把 360 宽的卡按 138 宽算 ⇒ 高出一倍，"
      "多出来的空间还被布局塞给了正文那行）",
      _dh.height() < 200 and _dh.height() > 60,
      "h=%d 正文 heightForWidth=%d sizeHint=%d" % (
          _dh.height(), _body_lbl.heightForWidth(ApiHelpDialog._content_w()),
          _body_lbl.sizeHint().height()))
check("★说明卡里给了 DeepSeek 平台的地址（可点链接的 href）",
      ApiHelpDialog.HELP_URL in ApiHelpDialog._body_html()
      and "href" in ApiHelpDialog._body_html())
check("★★说明卡**没有标题行**（用户口径：删掉标题，一句话 + 链接 + 回执就够）",
      not any("font-size:15px" in w.styleSheet() for w in _dh.findChildren(QLabel)),
      str([w.text() for w in _dh.findChildren(QLabel)]))
check("★说明卡正文逐字对（用户口径，不许顺手润色：`Key需要` 中间没空格、`Deepseek` 就这么拼）",
      "API Key需要从各模型的开放平台获取。" in ApiHelpDialog._body_html()
      and "例如Deepseek：" in ApiHelpDialog._body_html()
      and "获取后返回该界面，自行添加即可。" in ApiHelpDialog._body_html(),
      ApiHelpDialog._body_html())
_opened = []
_orig_open = QDesktopServices.openUrl
QDesktopServices.openUrl = staticmethod(lambda url: _opened.append(str(url.toString())))
try:
    _dh._open_link(ApiHelpDialog.HELP_URL)
finally:
    QDesktopServices.openUrl = _orig_open
check("★说明卡里的链接**真的会去开浏览器**（不是一段死文本）",
      _opened == [ApiHelpDialog.HELP_URL], str(_opened))
_dh.close()

# ---- 首启模型安装卡（用户点六）----
_dm = ModelSetupDialog(win)
check("模型安装卡：宽 400（正文四行，360 会挤成窄柱）", _dm.width() == 400)
_btn_texts = [b.text() for b in _dm.findChildren(QPushButton)]
check("★模型安装卡有两个按钮：「先不安装」「立即安装」",
      {"先不安装", "立即安装"} <= set(_btn_texts), str(_btn_texts))
_dm.close()

_fired = []
_dm2 = ModelSetupDialog.show_setup(win, on_install=lambda: _fired.append(1))
check("★★模型安装卡也是**非阻塞**的（open()，不是 exec()）", _dm2 is not None and _dm2.isVisible())
check("★没点「立即安装」就不该开始下载（回调不许自己跑）", _fired == [], str(_fired))
_dm2.accept()
_app.processEvents()
check("★点「立即安装」⇒ 回调被调用（main.py 接的是「开始下载 + 跳通用设置」）",
      _fired == [1], str(_fired))

# ---- 一键自检卡 ----
_d2 = SelfCheckDialog(win, win._build_checks(), on_recheck=win._build_checks)
check("自检卡：汇总行写「通过 N · 提示 N · 失败 N」",
      "通过" in _d2._summary.text() and "失败" in _d2._summary.text(), _d2._summary.text())
check("自检卡：宽 440（六条要放标题 + 状态 + 修复指引）",
      _d2.width() == 440)
_d2.set_checks(health.check_all(_cfg(_ALICE_API, dirs=["C:/a"]), tts_installed=True, asr_ok=True))
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


def _const_strs(node):
    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _names(node):
    """源码里出现过的**标识符**名（`PERMISSION_DENIED_HINT` 这类是 Name，不是字符串常量
    —— 用 `_const_strs` 找它永远找不到）。"""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _self_attrs(func_node):
    """方法体里 `self.xxx = ...` 赋出来（或标注声明）的属性名。"""
    out = set()
    for n in ast.walk(func_node):
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, ast.AnnAssign):
            targets = [n.target]
        else:
            continue
        for t in targets:
            if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                    and t.value.id == "self"):
                out.add(t.attr)
    return out


_gui_tree = _tree("app/gui.py")
_main_tree = _tree("app/main.py")
_health_tree = _tree("app/health.py")
_update_tree = _tree("app/update.py")
_config_tree = _tree("app/config.py")

# ---- 非阻塞（探针的生死线）----
for _cls, _m in (("FirstRunDialog", "show_guide"), ("ModelSetupDialog", "show_setup")):
    _sg = _class_func(_gui_tree, _cls, _m)
    _cn = _called(_sg) if _sg is not None else set()
    check("★★%s.%s 必须**非阻塞**：不许有 exec()（嵌了模态循环 ⇒ 跑真 main() 的探针挂死）"
          % (_cls, _m), _sg is not None and "exec" not in _cn and "open" in _cn, str(sorted(_cn)))

# ---- main.py 的启动触发点 ----
_shown = [n.lineno for n in ast.walk(_main_tree)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
          and n.func.attr == "show" and isinstance(n.func.value, ast.Name)
          and n.func.value.id == "win"]


def _test_names(node):
    """一个表达式里出现过的名字（Call 取函数名、Name 取值）。

    ★`if first_launch:` 这种 test 只是个 **Name**，不是 `if is_first_launch():` ——
     只找 Call 会一个都找不到（这正是上一版断言假红的原因）。
    """
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = n.func
            out.add(fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", ""))
        elif isinstance(n, ast.Name):
            out.add(n.id)
    return out


def _if_calling(tree, fname):
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and fname in _test_names(n.test):
            return n
    return None


# ★模型安装卡那个 if 的判据是**局部变量** `first_launch`（文件开头 `first_launch = is_first_launch()`），
#   不是当场调 `is_first_launch()`。文件里 `singleShot` 不止一处（`rearm_listening` 那条兜底
#   定时器也用），所以**不能**只看「body 里有没有 singleShot」—— 必须认回调本身是
#   `win.show_model_setup` 的那一处。
def _if_scheduling(tree, callback_dotted):
    """「用 QTimer.singleShot 排 `obj.meth` 的那个 if」——**取最内层**那个。

    ★main.py 里 `if first_launch: QTimer.singleShot(600, win.show_model_setup)` 是**嵌在**
      `else:` 分支里的（外层是 `if silent_boot:`），所以 `ast.walk` 会先命中外层那个 If。
      按「行跨度最小」挑，才能拿到真正做这件事的那一层。
    """
    obj, _, meth = callback_dotted.partition(".")
    hits = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        for c in ast.walk(n):
            if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "singleShot"):
                continue
            for a in c.args:
                if (isinstance(a, ast.Attribute) and a.attr == meth
                        and isinstance(a.value, ast.Name) and a.value.id == obj):
                    hits.append(n)
                    break
    if not hits:
        return None
    return min(hits, key=lambda n: (n.end_lineno or n.lineno) - n.lineno)


_fi = _if_scheduling(_main_tree, "win.show_model_setup")
_fi_body = set()
if _fi is not None:
    for _st in _fi.body:
        _fi_body |= _called(_st)
_fi_cond = _test_names(_fi.test) if _fi is not None else set()
_fi_direct = ([n.lineno for n in ast.walk(_fi) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute) and n.func.attr == "show_model_setup"]
              if _fi is not None else [])
check("★★main.py 的模型安装卡必须**延后触发**（QTimer.singleShot 转交 win.show_model_setup），"
      "不许当场直接调 win.show_model_setup()",
      _fi is not None and "singleShot" in _fi_body and not _fi_direct,
      f"cond={sorted(_fi_cond)} body={sorted(_fi_body)} direct={_fi_direct}")
check("★首次引导的触发点：判据 =「初次启动」局部变量，且排在 `win.show()` **之后**"
      "（先出窗口、再弹引导）",
      _fi is not None and ({"first_launch", "is_first_launch"} & _fi_cond)
      and bool(_shown) and _fi.lineno > min(_shown),
      f"cond={sorted(_fi_cond)} if@{getattr(_fi, 'lineno', '?')} vs show@{min(_shown) if _shown else '?'}")
_main_fn = _module_func(_main_tree, "main")
check("★「初次启动」判据走 config.is_first_launch（= config.json 在不在），"
      "不再用 first_run_needed（那是「配过 API 没」，老用户也会中招）",
      _if_calling(_main_tree, "first_run_needed") is None
      and "is_first_launch" in (_called(_main_fn) if _main_fn is not None else set()))

_show_ln = [n.lineno for n in ast.walk(_main_tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "show_startup_notices"]
_gate_ln = [n.lineno for n in ast.walk(_main_tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_apply_model_gate"]
check("★★show_startup_notices 排在 `_apply_model_gate()` **之后**"
      "（那一步没装模型时会就地切静音，先摆提示就会摆出与现状不符的话）",
      bool(_show_ln) and bool(_gate_ln) and min(_show_ln) > min(_gate_ln),
      f"{_show_ln} vs {_gate_ln}")

# ---- 权限给出路（点三）----
_npd = _class_func(_gui_tree, "MainWindow", "notify_permission_denied")
_npd_cn = _called(_npd) if _npd is not None else set()
check("★notify_permission_denied 走 add_system 的**带链接**那一支（link_text / on_link）",
      _npd is not None and "add_system" in _npd_cn
      and {"link_text", "on_link"} <= {k.arg for c in ast.walk(_npd)
                                       if isinstance(c, ast.Call) for k in c.keywords},
      str(sorted(_npd_cn)))
check("★提示文案里有「去添加」三个字（就是用户点三要求的那个链接文字）",
      "去添加" in _const_strs(_npd) if _npd is not None else False)

_hint_calls = [n.lineno for n in ast.walk(_main_tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "notify_permission_denied"]
check("★main.py 在权限被拒那条路上真的调了它", bool(_hint_calls), str(_hint_calls))
check("★★被拒时喂给模型的是去技术化的人话（PERMISSION_DENIED_HINT），"
      "不是 `[权限拦截] …` 原文（原文只进日志）",
      # ★它是模块级常量**标识符**，用 `_const_strs`（只收字符串字面量）找是找不到的。
      #   真正要核的是：那句人话被**赋给了 action_result**（= 模型唯一能看到的那个出口）。
      any(isinstance(n, ast.Assign)
          and any(isinstance(t, ast.Name) and t.id == "action_result" for t in n.targets)
          and isinstance(n.value, ast.Name) and n.value.id == "PERMISSION_DENIED_HINT"
          for n in ast.walk(_main_tree))
      and "PERMISSION_DENIED_HINT" in _names(_main_tree))

# ---- health.py 的纯度与单一真值 ----
_h_imports = set()
for _n in ast.walk(_health_tree):
    if isinstance(_n, ast.Import):
        _h_imports |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _h_imports.add(_n.module.split(".")[0])
check("★health.py 保持**纯**：不 import PySide6（判据要能离线跑，不用起 QApplication）",
      "PySide6" not in _h_imports, str(sorted(_h_imports)))

_wn = _module_func(_health_tree, "whitelist_notice")
_vn = _module_func(_health_tree, "voice_notice")
_sns = _module_func(_health_tree, "startup_notices")
check("★★提示区的三条判据全在 health.py 里（白名单 / 语音 / 合起来）",
      _wn is not None and _vn is not None and _sns is not None)
check("★startup_notices 复用 whitelist_notice / voice_notice，不另写一套",
      _sns is not None and {"whitelist_notice", "voice_notice"} <= _called(_sns),
      str(sorted(_called(_sns))) if _sns is not None else "")
check("★语音那条复用静音判据（mute_on），不自己翻 cfg",
      _vn is not None and "mute_on" in _called(_vn), str(sorted(_called(_vn))))
check("★白名单那条复用 allowed_dirs（权限白名单的唯一取值入口）",
      _wn is not None and "allowed_dirs" in _called(_wn))

_note_ln = {n.lineno for n in ast.walk(_health_tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "Notice"}
check("★两条 Notice 都在 health.py 里造（gui 只搬不造 ⇒ 文案只有一处真值）",
      len(_note_ln) >= 3, str(sorted(_note_ln)))

# ---- gui.py：提示区接上了没有 ----
_build = _class_func(_gui_tree, "MainWindow", "_build")
_cn_build = _called(_build) if _build is not None else set()
check("★★主窗口 `_build` 里真的挂了提示区（`_build_notice_area`）—— 漏了它，"
      "提示区就是个永远不显示的孤儿控件，而且**不报错**",
      "_build_notice_area" in _cn_build, str(sorted(_cn_build)))

_bna = _class_func(_gui_tree, "MainWindow", "_build_notice_area")
_cn_bna = _called(_bna) if _bna is not None else set()
check("★提示区用 setVisible 收放（两行都没有时整块藏起来，不是 hide() 硬藏）",
      "setVisible" in _cn_bna and "hide" not in _cn_bna, str(sorted(_cn_bna)))
check("★★提示区两行初始都收着（QWidget 默认「可见」，不关掉就多一行空白）",
      _bna is not None
      and sum(1 for n in ast.walk(_bna) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "setVisible") >= 3,
      str(sorted(_cn_bna)))

# ★★2026-10-02 用户点：提示区改成**浮层**（不进布局 + 阴影 + 自己摆位）。
#   这一组 AST 断言与上面「运行期量 dy / dh == 0」那条**成对**：
#   AST 说"没人把它塞进布局"，运行期说"关掉之后底下真的一动不动" —— 缺一个都守不住。
def _puts_in_layout(func_node):
    """方法体里有没有 `xxx.addWidget/addLayout/insertWidget(... self._notice_area ...)`。"""
    if func_node is None:
        return None
    out = []
    for n in ast.walk(func_node):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("addWidget", "addLayout", "insertWidget", "addStretch")):
            continue
        if any(isinstance(a, ast.Attribute) and a.attr == "_notice_area" for a in n.args):
            out.append(n.lineno)
    return out


_laid = (_puts_in_layout(_build) or []) + (_puts_in_layout(_bna) or [])
check("★★提示区**绝不进布局**（`_build` / `_build_notice_area` 里没有任何一句把 "
      "`_notice_area` 塞进布局）—— 塞进去就占着 30px 的布局高度，一关整屏上跳",
      _laid == [], str(_laid))
check("★提示区的 parent 是主窗口（`QFrame(self)`）—— 浮层得挂在窗口上，"
      "挂错了就没有 `raise_()` 的对象",
      _bna is not None
      and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "QFrame"
              and any(isinstance(a, ast.Name) and a.id == "self" for a in n.args)
              for n in ast.walk(_bna)))
check("★★提示区挂了 `QGraphicsDropShadowEffect`（用户口径「要加点阴影」——"
      "没有影子就看不出「浮在上层」）★`setGraphicsEffect` 也要查：只建不挂等于没挂",
      _bna is not None and "QGraphicsDropShadowEffect" in _called(_bna)
      and "setGraphicsEffect" in _called(_bna), str(sorted(_cn_bna)))

_pos = _class_func(_gui_tree, "MainWindow", "_position_notice_area")
check("★浮层位置**自己算**（`_position_notice_area` 存在，且真的调 `setGeometry`）",
      _pos is not None and "setGeometry" in _called(_pos),
      str(sorted(_called(_pos))) if _pos is not None else "None")
_anl = _class_func(_gui_tree, "MainWindow", "_apply_notice_layout")
check("★★`_apply_notice_layout` 里调 `raise_()` —— 浮层建得比正文早，"
      "不 raise 就会被正文盖住（**不报错，就是看不见**）",
      _anl is not None and "raise_" in _called(_anl),
      str(sorted(_called(_anl))) if _anl is not None else "None")
_re_ev = _class_func(_gui_tree, "MainWindow", "resizeEvent")
check("★★`resizeEvent` 里重摆浮层（不调 ⇒ 改窗口大小后提示区停在旧宽度上）",
      _re_ev is not None and "_position_notice_area" in _called(_re_ev),
      str(sorted(_called(_re_ev))) if _re_ev is not None else "None")

_rh = _class_func(_gui_tree, "MainWindow", "refresh_health")
_rh_args = {a.arg for a in (_rh.args.args + _rh.args.kwonlyargs)} if _rh is not None else set()
check("★`refresh_health` 带 `recompute_facts` 开关（翻页复用缓存、别每次 stat 模型目录）",
      "recompute_facts" in _rh_args, str(sorted(_rh_args)))
_rh_cn = _called(_rh)
check("★★refresh_health **只**碰白名单那条（`_refresh_perm_notice`）—— "
      "碰了 voice_notice / show_startup_notices，语音那条就会在每次翻页时复活",
      "_refresh_perm_notice" in _rh_cn
      and "voice_notice" not in _rh_cn and "show_startup_notices" not in _rh_cn,
      str(sorted(_rh_cn)))

_ssn = _class_func(_gui_tree, "MainWindow", "show_startup_notices")
check("★show_startup_notices 里调 voice_notice + 起倒计时",
      _ssn is not None and "voice_notice" in _called(_ssn), str(sorted(_called(_ssn))))

_notify = _class_func(_gui_tree, "MainWindow", "_notify_page_change")
check("★翻页时提示区重算一次（`recompute_facts=False`）—— 否则用户在权限页加完目录、"
      "切回聊天页看到的还是那条「可操作目录为空」",
      "_health_facts" in ast.dump(_notify) or "refresh_health" in _called(_notify))

check("★提示区的显隐判据用的是自己记的 `_notice_on`，不是 `isVisible()`"
      "（整块隐藏后子控件的 isVisible 恒为 False ⇒ 永远算成 0 行、提示区再也露不出来）",
      "_notice_on" in ast.dump(_gui_tree))

# ---- 每角色独立 API：取值入口只在 config.py ----
_apis_for = _module_func(_config_tree, "apis_for")
_cur_name = _module_func(_config_tree, "current_api_name")
_get_cur = _module_func(_config_tree, "get_current_api")
_norm = _module_func(_config_tree, "_normalize_apis")
check("★★config.py 提供按角色取值的三个入口 + 归一化（apis_for / current_api_name / "
      "get_current_api / _normalize_apis）",
      all(f is not None for f in (_apis_for, _cur_name, _get_cur, _norm)))
check("★get_current_api 复用 current_api_name + apis_for（不自己翻 cfg）",
      _get_cur is not None
      and {"current_api_name", "apis_for"} <= _called(_get_cur), str(sorted(_called(_get_cur))))
check("★★归一化里把**旧结构搬进 alice**（不按 current_role 落 —— 老配置里它可能是 ellen，"
      "那会把老师唯一那把 key 塞进一个当前根本切不过去的角色）",
      _norm is not None and "LEGACY_API_ROLE" in ast.dump(_norm))

# gui.py / main.py 里不许再直接读 `cfg["current_api"]` 去当字符串比
_raw = [n.lineno for n in ast.walk(_main_tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "get" and n.args
        and isinstance(n.args[0], ast.Constant) and n.args[0].value == "current_api"]
check("★★main.py 里没有 `cfg.get(\"current_api\")` 裸取（那拿到的是 dict，与 api_name 比"
      "**永远不等** ⇒ 每条回复都被当成「API 被切走」丢掉、她一声不吭）",
      not _raw, str(_raw))

_sub = _class_func(_gui_tree, "ChatView", "add_system")
check("★ChatView.add_system 支持可点链接（link_text / on_link），其余调用点走纯文本老路",
      _sub is not None
      and {"link_text", "on_link"} <= {a.arg for a in _sub.args.args + _sub.args.kwonlyargs},
      str([a.arg for a in _sub.args.args]))
check("★★可点链接的正文要过 html.escape（目录名里一个 < 就能把这条消息渲染乱）",
      _sub is not None and "escape" in _called(_sub), str(sorted(_called(_sub))))

_ap_init = _class_func(_gui_tree, "ApiPanel", "__init__")
check("★ApiPanel 有「正在编辑哪个角色」的状态（_role_key）",
      _ap_init is not None and "_role_key" in ast.dump(_ap_init))
_build_ap = _class_func(_gui_tree, "ApiPanel", "_build")
_build_ap_attrs = _self_attrs(_build_ap) if _build_ap is not None else set()
check("★ApiPanel 标题旁有问号按钮（help_btn），且**不再有**「配置哪个角色」下拉"
      "（2026-10-02 用户点二：页内不切角色，_role_key 固定为进来时的当前角色）",
      # ★`help_btn` 是 `self.xxx =` 赋出来的**属性**，不是字符串字面量
      {"help_btn"} <= _build_ap_attrs
      and "role_combo" not in _build_ap_attrs
      and "配置哪个角色" not in _const_strs(_build_ap)
      and "ApiHelpDialog" not in _names(_build_ap)   # 建卡交给 _show_help，_build 里别自己建
      and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "connect"
              and any(isinstance(a, ast.Attribute) and a.attr == "_show_help" for a in n.args)
              for n in ast.walk(_build_ap)),
      str(sorted(_build_ap_attrs)))
_head_bg = ([n.lineno for n in ast.walk(_build_ap)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "setStyleSheet"
             and isinstance(n.func.value, ast.Attribute)
             and n.func.value.attr == "_cur_head"
             and any(isinstance(a, ast.Constant) and isinstance(a.value, str)
                     and "transparent" in a.value for a in n.args)]
            if _build_ap is not None else [])
check("★「当前 API」这一行**必须显式透明背景** —— 面板级样式里的 "
      "`QWidget { background:#FFFFFF; }` 会命中卡片里的每个 QLabel，把它染成一条白带，"
      "而卡片（跟下面那个 Key 文本框同色）是 #F6FAFF",
      "_cur_head" in _build_ap_attrs and bool(_head_bg), str(_head_bg))
# ★★2026-10-02 用户点：「『当前使用的 API』改为『当前 API』」。★这条按 **AST 常量**查，
#   不按文本查（`_const_strs` 收的是 `ast.Constant`，引号/换行怎么变都逃不掉）。
check("★文案 =「当前 API」（2026-10-02 用户口径：从「当前使用的 API」改短；"
      "「管理 API / 已有 API」都留了那个空格，这里同款）",
      _build_ap is not None and "当前 API" in _const_strs(_build_ap)
      and "当前使用的 API" not in _const_strs(_build_ap),
      str(sorted(s for s in _const_strs(_build_ap) if "API" in s)))
# ★★★2026-10-02 本批最贵的一条：`page.setStyleSheet("background:transparent;")` **必须不在**。
#   Qt 的规矩是「样式表设在某个控件上 ⇒ 对它自己、以及**它的全部子孙**生效」—— 那一句会把
#   整棵子树的 `background` 压平：卡片 `QFrame#card{#F6FAFF}` 变**白**、主按钮
#   `QPushButton{#378ADD}` 成「白底白字」（**整个按钮看不见**）。
#   ★而且 `_apply_style` 里那条 `QFrame#card` 还好端端写着、**只是不生效** ⇒
#     「样式表里有这句吗」型的断言 100% 会绿 ⇒ 这条 AST 断言 + smoke_api 的**像素**断言
#     必须成对存在，缺一个都守不住。
_page_qss = ([n.lineno for n in ast.walk(_build_ap)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "setStyleSheet"
              and isinstance(n.func.value, ast.Name)
              and n.func.value.id == "page"]
             if _build_ap is not None else None)
check("★★`page` 上**不许**设样式表（本批「卡片变白 + 添加按钮隐形」的唯一真因；"
      "重设面板样式 / 把那句挪到最后 / 改写成 `QWidget{background:transparent}` **都无效**）",
      _page_qss == [], str(_page_qss))
_refresh_ap = _class_func(_gui_tree, "ApiPanel", "refresh")
check("★refresh() 不再重写标题（文案是常量，只在 _build 里设一次）",
      _refresh_ap is not None
      and not any(isinstance(n, ast.Attribute) and n.attr == "_cur_head"
                  for n in ast.walk(_refresh_ap)))
check("★★「配置哪个角色」的槽函数已删干净（`_on_role_select` 不许留在类里）",
      _class_func(_gui_tree, "ApiPanel", "_on_role_select") is None)
check("★★整页滚动（2026-10-02 用户点三）：`_build` 里**只建一个** QScrollArea，"
      "标题 / 卡片 / 按钮 / 列表 / 提示全挂在它的内容层上 —— 原来那个「只有列表能滑」的"
      "列表自带滚动区必须已经删掉",
      _build_ap is not None
      and sum(1 for n in ast.walk(_build_ap)
              if isinstance(n, ast.Call)
              and getattr(n.func, "id", getattr(n.func, "attr", "")) == "QScrollArea") == 1
      and {"_scroll", "_list_container"} <= _build_ap_attrs,
      str(sorted(_build_ap_attrs)))
_sh = _class_func(_gui_tree, "ApiPanel", "_show_help")
check("★问号按钮真的弹说明卡（ApiHelpDialog.show_help）",
      # ★`ApiHelpDialog.show_help(self)`：被调的名字是 `show_help`，`ApiHelpDialog` 是它的
      #   **取值对象**（一个 Name）—— 只查 `_called` 会漏掉它。
      _sh is not None and "ApiHelpDialog" in _names(_sh) and "show_help" in _called(_sh),
      str(sorted(_called(_sh))))

# ---- update.py 的联网面 ----
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

# ---- 菜单 / 设置页入口 ----
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

# ---- 「立即安装」= 开始下载 + 跳通用设置 ----
_smd = _class_func(_gui_tree, "MainWindow", "start_model_download")
_smd_cn = _called(_smd) if _smd is not None else set()
check("★★「立即安装」= 先跳通用设置页、再开始下载（`_show_settings_page` + `start_download`）",
      _smd is not None
      and {"_show_settings_page", "start_download"} <= _smd_cn, str(sorted(_smd_cn)))
check("★跳页排在开始下载**之前**（反了的话用户在切页那一帧看不到进度）",
      _smd is not None
      and min(n.lineno for n in ast.walk(_smd) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "_show_settings_page")
      < min(n.lineno for n in ast.walk(_smd) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "start_download"))
_sd = _class_func(_gui_tree, "GeneralPanel", "start_download")
check("★start_download 带 `confirm` 开关（首启那张卡要跳过二次确认）",
      _sd is not None and "confirm" in {a.arg for a in _sd.args.args + _sd.args.kwonlyargs},
      str([a.arg for a in _sd.args.args]) if _sd is not None else "")
check("★首启那条路调的是 `confirm=False`（用户刚按过「立即安装」，别再问一遍）",
      _smd is not None and False in _const_strs(_smd) or _smd is not None
      and any(isinstance(kw.value, ast.Constant) and kw.value.value is False
              for n in ast.walk(_smd) if isinstance(n, ast.Call) for kw in n.keywords))

print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)
