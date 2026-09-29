"""冒烟测试：设置区（导航栏「设置」+ 左栏蓝底设置导航 + 通用设置 + 关闭行为）。

跑法（在项目根目录）：
    .venv\\Scripts\\python.exe tests\\smoke_settings.py

说明：全部在 offscreen 平台运行，不弹窗；只读注册表、不写注册表启动项；
配置读写重定向到临时文件，不动项目里的 config.json。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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


# ========== 1. 配置层：general 段 ==========
print("== 1. 配置层 general ==")
import app.config as cfgmod  # noqa: E402

tmp_dir = Path(tempfile.mkdtemp(prefix="ignotus_smoke_"))
tmp_cfg = tmp_dir / "config.json"
cfgmod.CONFIG_PATH = tmp_cfg

cfg = cfgmod.load_config()
check("默认 close_action == tray", cfg["general"]["close_action"] == "tray", str(cfg.get("general")))
check("默认 auto_start is False", cfg["general"]["auto_start"] is False)
check("默认 mute_mode is False（静音模式默认关）", cfg["general"]["mute_mode"] is False,
      str(cfg.get("general")))
check("默认 patpat_mode is False（patpat 模式默认关）", cfg["general"]["patpat_mode"] is False,
      str(cfg.get("general")))

tmp_cfg.write_text(json.dumps({"general": {"close_action": "  QUIT  "}}), encoding="utf-8")
cfg = cfgmod.load_config()
check("close_action 归一化（去空格 + 小写）", cfg["general"]["close_action"] == "quit", str(cfg["general"]))

tmp_cfg.write_text(json.dumps({"general": {"close_action": "boom"}}), encoding="utf-8")
cfg = cfgmod.load_config()
check("非法 close_action 回退 tray", cfg["general"]["close_action"] == "tray")

tmp_cfg.write_text(json.dumps({"general": 1}), encoding="utf-8")
cfg = cfgmod.load_config()
check("general 类型错误时自愈", isinstance(cfg["general"], dict) and cfg["general"]["close_action"] == "tray")

tmp_cfg.write_text(json.dumps({"general": {"auto_start": 1}}), encoding="utf-8")
cfg = cfgmod.load_config()
check("auto_start 强制 bool", cfg["general"]["auto_start"] is True)

# ---- 静音模式：**落盘的偏好**（2026-09-29 用户口径「完全退出后重开要保留开关状态」）----
# ★改口径前它是「纯运行时、每次启动从关开始」（当时的理由是「上次静音着退出 ⇒ 这次一声
#   不吭，用户会以为软件坏了」）；现在与 lock_pet 同类 —— 用户已知情并明确要求持久化。
tmp_cfg.write_text(json.dumps({"general": {"mute_mode": True}}), encoding="utf-8")
cfg = cfgmod.load_config()
check("★★磁盘上的 mute_mode=True **被读回 True**（用户要的「重开保留」就是这一条）",
      cfg["general"]["mute_mode"] is True, str(cfg["general"]))

tmp_cfg.write_text(json.dumps({"general": {"mute_mode": False}}), encoding="utf-8")
cfg = cfgmod.load_config()
check("★磁盘上的 mute_mode=False 读回 False（关着退出 ⇒ 重开还是关）",
      cfg["general"]["mute_mode"] is False, str(cfg["general"]))

# 脏值一律当「关」：★宁可不敢静音，也不能因为磁盘上一个脏值就让软件启动即无声
# （那正是这个字段最容易吓到人的地方）。宽松的 `bool(...)` 会把 "yes" 判成 True。
for _dirty in ("", "yes", 1, [], None):
    tmp_cfg.write_text(json.dumps({"general": {"mute_mode": _dirty}}), encoding="utf-8")
    _got = cfgmod.load_config()["general"]["mute_mode"]
    check("mute_mode 脏值 %r ⇒ False（绝不因脏值变成「开」）" % (_dirty,),
          _got is False, repr(_got))

# 反向：写盘时要**真的写进去**（这正是本次改动的目的），且不能改动传进来的 cfg
_mute_cfg = {"general": {"close_action": "tray", "mute_mode": True}, "volume": 0.5}
cfgmod.save_config(_mute_cfg)
_written = json.loads(tmp_cfg.read_text(encoding="utf-8"))
check("★★save_config 把 mute_mode 写进 config.json（改前被 `_RUNTIME_ONLY_GENERAL` 剔掉）",
      _written["general"].get("mute_mode") is True, str(_written.get("general")))
check("★闭环：写盘后再 load_config，仍是 True（= 真机「关掉软件再打开」的等价路径）",
      cfgmod.load_config()["general"]["mute_mode"] is True)
check("save_config 不改动传进来的 cfg（调用方还要继续用它）",
      _mute_cfg["general"]["mute_mode"] is True, str(_mute_cfg["general"]))

# patpat 模式：★**仍然**是纯运行时（用户口径「与其它模式一样」；重启即关）
# —— 别照着上面静音那条抄「落盘」：2026-09-29 只有静音改了。
tmp_cfg.write_text(json.dumps({"general": {"patpat_mode": True}}), encoding="utf-8")
cfg = cfgmod.load_config()
check("磁盘上的 patpat_mode=True 仍被忽略（重启一律从「关」开始）",
      cfg["general"]["patpat_mode"] is False, str(cfg["general"]))

tmp_cfg.write_text(json.dumps({"general": {"patpat_mode": "yes"}}), encoding="utf-8")
cfg = cfgmod.load_config()
check("patpat_mode 脏值也回 False", cfg["general"]["patpat_mode"] is False, str(cfg["general"]))

_patpat_cfg = {"general": {"close_action": "tray", "mute_mode": True, "patpat_mode": True},
               "volume": 0.5}
cfgmod.save_config(_patpat_cfg)
_written_pp = json.loads(tmp_cfg.read_text(encoding="utf-8"))
check("★save_config：**留** mute_mode、**剔** patpat_mode（两个字段各走各的记忆）",
      _written_pp["general"].get("mute_mode") is True
      and "patpat_mode" not in _written_pp["general"],
      str(_written_pp.get("general")))
check("save_config 不改动传进来的 cfg（patpat_mode 仍是 True）",
      _patpat_cfg["general"]["patpat_mode"] is True, str(_patpat_cfg["general"]))
check("★`_RUNTIME_ONLY_GENERAL` 只剩 patpat_mode（mute_mode 必须已移出 —— "
      "它若还在这张名单里，用户改的静音重启就丢，本次需求等于没实现）",
      tuple(getattr(cfgmod, "_RUNTIME_ONLY_GENERAL", ())) == ("patpat_mode",),
      str(getattr(cfgmod, "_RUNTIME_ONLY_GENERAL", None)))

tmp_cfg.write_text(json.dumps({"general": {"close_action": "tray", "auto_start": False}}), encoding="utf-8")
cfg = cfgmod.load_config()


# ========== 2. autostart 模块（只读，不写注册表）==========
print("== 2. autostart ==")
from app import autostart  # noqa: E402

cmd = autostart.launch_command()
check("启动命令含 run.py", "run.py" in cmd, cmd)
check("启动命令用引号包裹路径", cmd.startswith('"') and cmd.count('"') >= 2, cmd)
if (Path(sys.executable).with_name("pythonw.exe")).exists():
    check("存在 pythonw.exe 时优先用它（避免黑窗）", "pythonw" in cmd, cmd)
check("is_enabled() 返回 bool", isinstance(autostart.is_enabled(), bool))
check("current_command() 返回 str", isinstance(autostart.current_command(), str))


# ========== 3. GUI：导航栏与设置区 ==========
print("== 3. GUI 导航与左栏 ==")
from PySide6.QtCore import QEvent, QEventLoop, QObject, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QCloseEvent, QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QPushButton, QSizePolicy, QWidget)


app = QApplication.instance() or QApplication([])

from app import gui  # noqa: E402

win = gui.MainWindow(cfg)


def settle(ms=500):
    """跑真实事件循环，等入场动画与延迟回调落定。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()

nav_texts = [b.text() for b in (win._nav_chat_btn, win._nav_manage_btn, win._nav_settings_btn)]
check("顶部导航为 聊天/管理/设置", nav_texts == ["聊天", "管理", "设置"], str(nav_texts))
check("右栏页面数 = 3 主页面 + 设置项数",
      win._right_stack.count() == 3 + len(win.SETTINGS_ITEMS), str(win._right_stack.count()))
check("通用设置页索引 = SETTINGS_BASE", win._settings_index["general"] == win.SETTINGS_BASE,
      str(win._settings_index))
check("权限管理页紧随其后", win._settings_index["permissions"] == win.SETTINGS_BASE + 1, str(win._settings_index))
check("权限面板已移入设置区", isinstance(win._settings_panels["permissions"], gui.PermPanel))
check("旧入口 _show_perm_panel 已移除", not hasattr(win, "_show_perm_panel"))
check("左栏默认是角色区", win._left_stack.currentWidget() is win._left_role_page and not win._settings_mode)
check("左栏初始白底", win._left_bg_t == 0.0, str(win._left_bg_t))
check("左栏宽度未变", win._left_panel.width() == 180 or win.LEFT_WIDTH == 180)

# 形态切换（关闭动画，便于断言终值）
win._set_left_mode(win.LEFT_MODE_SETTINGS, animate=False)
check("进设置：左栏切到设置导航", win._left_stack.currentWidget() is win._left_settings_page and win._settings_mode)
check("进设置：底色插值到 1.0", win._left_bg_t == 1.0, str(win._left_bg_t))
check("左栏容器为自绘底色面板", isinstance(win._left_panel, gui._ColorPanel), type(win._left_panel).__name__)
check("页面宿主为 _SlideStack", isinstance(win._left_stack, gui._SlideStack)
      and isinstance(win._right_stack, gui._SlideStack),
      f"{type(win._left_stack).__name__}/{type(win._right_stack).__name__}")
check("设置区底色为浅蓝 #C7E1FB", win._left_panel.bg_rgb() == (199, 225, 251), str(win._left_panel.bg_rgb()))
check("设置区底色比标题栏 #2F74BF 浅",
      sum(win._left_panel.bg_rgb()) > 47 + 116 + 191, str(win._left_panel.bg_rgb()))
check("底色不再走 QSS（无 setStyleSheet 抖动源）", win._left_panel.styleSheet() == "", win._left_panel.styleSheet())
_set_nav_style = win._settings_nav_btns[0][1].styleSheet()
check("设置项未选中为深蓝字", "#0C447C" in _set_nav_style and "transparent" in _set_nav_style)
check("设置项选中为蓝底白字", "#378ADD" in _set_nav_style and "color:#FFFFFF" in _set_nav_style)
check("左栏设置项数 = 设置页数", len(win._settings_nav_btns) == len(win.SETTINGS_ITEMS))

win._apply_left_bg(0.5)
check("底色插值取中值", win._left_panel.bg_rgb() == (227, 240, 253), str(win._left_panel.bg_rgb()))

win._set_left_mode(win.LEFT_MODE_ROLE, animate=False)
check("回角色区：白底 + 角色页",
      win._left_bg_t == 0.0 and win._left_stack.currentWidget() is win._left_role_page and not win._settings_mode)
check("回角色区：底色恢复纯白", win._left_panel.bg_rgb() == (255, 255, 255), str(win._left_panel.bg_rgb()))

# 管理导航：与设置导航同款，用来在「管理 API」「管理唤醒词」之间切换
win._set_left_mode(win.LEFT_MODE_MANAGE, animate=False)
check("进管理：左栏切到管理导航",
      win._left_stack.currentWidget() is win._left_manage_page
      and win._left_mode == win.LEFT_MODE_MANAGE and not win._settings_mode)
check("进管理：底色也是浅蓝 #C7E1FB",
      win._left_panel.bg_rgb() == (199, 225, 251), str(win._left_panel.bg_rgb()))
check("管理导航项数 = 2", len(win._manage_nav_btns) == 2, str(len(win._manage_nav_btns)))
check("管理导航文案 = 管理 API / 管理唤醒词",
      [b.text() for _i, b in win._manage_nav_btns] == ["管理 API", "管理唤醒词"],
      str([b.text() for _i, b in win._manage_nav_btns]))
check("管理导航项索引 = PAGE_API / PAGE_WAKE",
      [i for i, _b in win._manage_nav_btns] == [win.PAGE_API, win.PAGE_WAKE],
      str([i for i, _b in win._manage_nav_btns]))
check("管理导航项指向真实面板（ApiPanel / WakeWordPanel）",
      isinstance(win._right_stack.widget(win.PAGE_API), gui.ApiPanel)
      and isinstance(win._right_stack.widget(win.PAGE_WAKE), gui.WakeWordPanel))
check("管理项样式与设置项逐字一致（同一份皮肤）",
      win._manage_nav_btns[0][1].styleSheet() == _set_nav_style,
      repr(win._manage_nav_btns[0][1].styleSheet()))
check("管理项尺寸与设置项一致（40px 胶囊）",
      win._manage_nav_btns[0][1].maximumHeight() == 40
      and win._settings_nav_btns[0][1].maximumHeight() == 40)
check("角色头像 / 编辑 / 切换角色都在被隐去的角色页里（管理态看不到）",
      win._left_role_page.isHidden()
      and win._left_role_page.isAncestorOf(win._avatar_btn)
      and win._left_role_page.isAncestorOf(win._pencil_btn)
      and win._left_role_page.isAncestorOf(win._switch_btn))

# ---- ★★角色可切换性（2026-09-28 用户拍板；docs/02 §24）：艾莲暂不可切换 ----
# 用户口径：「**主界面左侧头像下的切换**」里的艾莲要成**不可点击**的状态，暂时**仅可使用爱丽丝**。
# ★艾莲**仍在列表里**（不删不藏），只是**灰显 + 选不中**（QComboBox 的标准做法：关 model item 的 enabled）。
check("★★真值：`config.SWITCHABLE_ROLES == ('alice',)` —— ★钉**绝对值**"
      "（只核「下拉里禁用了某项」会被「把元组加回 ellen」绕过）",
      cfgmod.SWITCHABLE_ROLES == ("alice",), repr(cfgmod.SWITCHABLE_ROLES))
_cb31 = win._switch_combo
_i31 = {_cb31.itemData(i): i for i in range(_cb31.count())}
check("下拉里**两个角色都还在**（艾莲不删不藏）", set(_i31) == {"alice", "ellen"}, str(sorted(_i31)))
check("★★下拉里**艾莲那项 `isEnabled() is False`**（灰显 + 选不中）",
      _cb31.model().item(_i31["ellen"]).isEnabled() is False,
      str([(_cb31.itemText(i), _cb31.model().item(i).isEnabled()) for i in range(_cb31.count())]))
check("★正对照：**爱丽丝那项 `isEnabled() is True`**",
      _cb31.model().item(_i31["alice"]).isEnabled() is True)
# ★不是只核字段（「表象」）—— 真调一下看副作用：**兜底闸**（`_on_switch_combo_activated` 里那道）
#   即便有人绕过模型直接发 `activated`，也不许真的切过去。
_rec31 = []
_real_confirm31 = win._confirm_switch
win._confirm_switch = lambda k: _rec31.append(k)
_prev_role31 = win.cfg["current_role"]
win.cfg["current_role"] = "alice"
win._on_switch_combo_activated(_i31["ellen"])
check("★★兜底闸：程序化选中**艾莲** → **不切**（`_confirm_switch` 一次都没被调）",
      _rec31 == [] and win.cfg["current_role"] == "alice",
      f"{_rec31} role={win.cfg['current_role']}")
win._on_switch_combo_activated(_i31["alice"])
check("★正对照：选中**爱丽丝** → **照切**（证明信号路径是通的）", _rec31 == ["alice"], repr(_rec31))
win._confirm_switch = _real_confirm31
win.cfg["current_role"] = _prev_role31

# 结构断言：两个导航页必须都由共用构建器生成（防有人各写一份、样式慢慢分叉）
import ast  # noqa: E402

_gui_src = ast.parse((Path(__file__).resolve().parent.parent / "app" / "gui.py")
                     .read_text(encoding="utf-8"))
_mw = next(n for n in _gui_src.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")


def _uses_shared_builder(method_name):
    fn = next(n for n in _mw.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    return any(isinstance(x, ast.Attribute) and x.attr == "_build_left_nav_page"
               for x in ast.walk(fn))


check("管理导航页由共用构建器生成", _uses_shared_builder("_build_left_manage_page"))
check("设置导航页由共用构建器生成", _uses_shared_builder("_build_left_settings_page"))
check("_settings_mode 是只读属性（真值只有 _left_mode）",
      isinstance(gui.MainWindow.__dict__["_settings_mode"], property)
      and gui.MainWindow.__dict__["_settings_mode"].fset is None)
try:
    win._set_left_mode(True, animate=False)
    _bool_rejected = False
except ValueError:
    _bool_rejected = True
check("_set_left_mode 拒绝旧的布尔写法（防左栏形态出现第二个真值）", _bool_rejected)
win._set_left_mode(win.LEFT_MODE_ROLE, animate=False)

# 设置页切换（导航选中态同步）
win._show_settings_page(win._settings_index["permissions"])
check("切到权限管理页", win._right_stack.currentIndex() == win._settings_index["permissions"])
check("左栏选中第 2 项", win._settings_nav_btns[1][1].isChecked() and not win._settings_nav_btns[0][1].isChecked())
check("仍处设置模式（左栏保持蓝底）", win._settings_mode)

win._show_settings_page(win._settings_index["general"])
check("切回通用设置页", win._right_stack.currentIndex() == win._settings_index["general"])
check("左栏选中第 1 项", win._settings_nav_btns[0][1].isChecked() and not win._settings_nav_btns[1][1].isChecked())


# ========== 4. 导航路由 ==========
print("== 4. 导航路由 ==")
win._select_nav(0)
check("点「聊天」回主界面", win._right_stack.currentIndex() == win.PAGE_CHAT and win._nav_chat_btn.isChecked())
check("回主界面时左栏恢复角色区",
      not win._settings_mode and win._left_stack.currentWidget() is win._left_role_page)

win._select_nav(1)
check("点「管理」进管理 API 页",
      win._right_stack.currentIndex() == win.PAGE_API and win._nav_manage_btn.isChecked()
      and not win._nav_settings_btn.isChecked())
check("点「管理」左栏切到管理导航（角色区隐去）",
      win._left_mode == win.LEFT_MODE_MANAGE
      and win._left_stack.currentWidget() is win._left_manage_page
      and win._left_role_page.isHidden() and not win._settings_mode)
check("管理导航选中「管理 API」",
      win._manage_nav_btns[0][1].isChecked() and not win._manage_nav_btns[1][1].isChecked())

# 左栏导航在管理区两页之间切换 + 幂等性
win._show_manage_page(win.PAGE_WAKE)
settle()
check("左栏可切到「管理唤醒词」页", win._right_stack.currentIndex() == win.PAGE_WAKE)
check("管理导航选中「管理唤醒词」",
      win._manage_nav_btns[1][1].isChecked() and not win._manage_nav_btns[0][1].isChecked())
check("唤醒词页标题带当前角色名",
      win._wake_panel.title_label.text()
      == f"管理唤醒词 - {win.cfg['roles'][win._current_role_key]['name']}",
      win._wake_panel.title_label.text())
win._select_nav(1)
check("已在「管理唤醒词」时点「管理」内容不变、不重放动画",
      win._right_stack.currentIndex() == win.PAGE_WAKE
      and win._right_stack._sliding is None and win._left_stack._sliding is None,
      str(win._right_stack.currentIndex()))

win._select_nav(2)
check("从别处点「设置」默认显示「通用设置」",
      win._right_stack.currentIndex() == win._settings_index["general"],
      str(win._right_stack.currentIndex()))
check("点「设置」左栏进入设置模式", win._settings_mode and win._nav_settings_btn.isChecked())

# 已在设置区（通用设置 / 权限管理）时点「设置」→ 内容不变、不重放入场动画
win.show()
for _ in range(4):
    app.processEvents()
win._show_settings_page(win._settings_index["permissions"])
settle()
check("切换到「权限管理」后动画已落定（前置条件）", win._right_stack._sliding is None)
_sig_before = win._right_stack.currentWidget()
win._select_nav(2)
check("已在「权限管理」时点「设置」内容不变",
      win._right_stack.currentIndex() == win._settings_index["permissions"],
      str(win._right_stack.currentIndex()))
check("已在「权限管理」时点「设置」不重放动画",
      win._right_stack._sliding is None and win._right_stack.currentWidget() is _sig_before)
win._show_settings_page(win._settings_index["general"])
settle()
win._select_nav(2)
check("已在「通用设置」时点「设置」内容不变",
      win._right_stack.currentIndex() == win._settings_index["general"],
      str(win._right_stack.currentIndex()))
check("已在「通用设置」时点「设置」不重放动画", win._right_stack._sliding is None)

# 不记忆上次停留的设置页：先停在「权限管理」，离开设置区再回来仍是「通用设置」
win._show_settings_page(win._settings_index["permissions"])
settle()
win._switch_right_panel(win.PAGE_CHAT, animate=False)
win._select_nav(2)
settle()
check("不记忆上次停留页：回设置区仍是「通用设置」",
      win._right_stack.currentIndex() == win._settings_index["general"],
      str(win._right_stack.currentIndex()))

win._select_nav(1)
check("从设置切回管理：左栏退出设置模式、进管理导航",
      win._right_stack.currentIndex() == win.PAGE_API and not win._settings_mode
      and win._left_mode == win.LEFT_MODE_MANAGE
      and win._left_stack.currentWidget() is win._left_manage_page)

# 选中态唯一性
for i in range(win._right_stack.count()):
    win._switch_right_panel(i, animate=False)
    checked = [b.isChecked() for b in (win._nav_chat_btn, win._nav_manage_btn, win._nav_settings_btn)]
    if sum(checked) != 1:
        check(f"页 {i} 导航选中态唯一", False, str(checked))
        break
else:
    check("每页恰有一个导航按钮选中", True)

# 铅笔菜单：只保留两个管理入口（「打开设置」已去除）
win._switch_right_panel(win.PAGE_CHAT, animate=False)
_menu = win._build_pencil_menu()
check("铅笔菜单仅剩 管理 API / 管理唤醒词",
      [a.text() for a in _menu.actions()] == ["管理 API", "管理唤醒词"],
      str([a.text() for a in _menu.actions()]))
check("铅笔菜单已无「打开设置」",
      "打开设置" not in [a.text() for a in _menu.actions()])
check("菜单项仍能唤起管理面板",
      callable(win._show_api_panel) and callable(win._show_wake_panel))
_menu.deleteLater()


# ========== 4b. 切换动画稳定性（防「末尾回弹抽搐」）==========
print("== 4b. 切换动画无回弹 ==")
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402


def sample_move(trigger, page, ms=900, interval=8):
    """跑真实事件循环，逐帧采样 page 的 (x, y)，返回 (xs, ys)。

    回弹的判定标准：序列中出现「后一帧比前一帧更远离终点」的跳变（起点 0 → 负偏移
    那一下不算）。旧实现用 QStackedWidget + QSS 改底色时，布局每帧都会把正在
    平移的页面 geometry 重置回满尺寸，采样序列呈 0/-xx 交替 —— 即肉眼看到的抽搐。
    """
    xs, ys = [], []
    timer = QTimer()
    timer.setInterval(interval)
    timer.timeout.connect(lambda: (xs.append(page.geometry().x()), ys.append(page.geometry().y())))
    timer.start()
    trigger()
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    timer.stop()
    return xs, ys


def back_jumps(seq):
    return [i for i in range(1, len(seq)) if seq[i] < seq[i - 1] - 0.5 and seq[i - 1] < 0]


def real_displacement(seq, slide):
    """是否出现接近完整 slide 距离的真实位移帧（采样从第 1 帧就已衰减，故留 40% 余量）。"""
    return len(seq) > 10 and min(seq) <= -slide * 0.6


win.show()
for _ in range(6):
    app.processEvents()

check("左栏平移距离 = 20px", win.LEFT_SLIDE == 20, str(win.LEFT_SLIDE))
check("右栏平移距离 = 20px", win.RIGHT_SLIDE == 20, str(win.RIGHT_SLIDE))

# 左栏：角色区 → 设置导航（自左向右 20px）
win._switch_right_panel(win.PAGE_CHAT, animate=False)
win._set_left_mode(win.LEFT_MODE_ROLE, animate=False)
for _ in range(4):
    app.processEvents()
xs_left, ys_left = sample_move(lambda: win._select_nav(2), win._left_settings_page)
check("左栏入场有真实位移帧", real_displacement(xs_left, win.LEFT_SLIDE), f"min={min(xs_left)} n={len(xs_left)}")
check("左栏入场单调推进（无回弹）", not back_jumps(xs_left), str(xs_left))
check("左栏入场终点精确归零",
      xs_left[-1] == 0 and win._left_settings_page.geometry().x() == 0,
      f"{xs_left[-1]}/{win._left_settings_page.geometry().x()}")
check("左栏入场只做横向位移（y 恒 0）", set(ys_left) == {0}, str(sorted(set(ys_left))))
check("左栏入场结束后解锁（可再切换）", win._left_stack._sliding is None)

# 右栏：聊天 → 设置页（自上而下 20px；此地原先走横向，现已统一）
win._switch_right_panel(win.PAGE_CHAT, animate=False)
for _ in range(4):
    app.processEvents()
gen_page = win._settings_panels["general"]
xs_right, ys_right = sample_move(lambda: win._show_settings_page(win._settings_index["general"]), gen_page)
check("右栏入场有真实位移帧", real_displacement(ys_right, win.RIGHT_SLIDE), f"min={min(ys_right)} n={len(ys_right)}")
check("右栏入场单调推进（无回弹）", not back_jumps(ys_right), str(ys_right))
check("右栏入场终点精确归零", ys_right[-1] == 0 and gen_page.geometry().y() == 0, str(ys_right[-1]))
check("右栏入场只做纵向位移（x 恒 0）", set(xs_right) == {0}, str(sorted(set(xs_right))))
check("右栏入场结束后解锁", win._right_stack._sliding is None)

# 退出设置：左栏页归位同样不抖（此地右栏也会自上而下平移）
xs_back, _ys_back = sample_move(lambda: win._select_nav(0), win._left_role_page)
check("退出设置：左栏页有真实位移", real_displacement(xs_back, win.LEFT_SLIDE), f"min={min(xs_back)}")
check("退出设置：左栏页归位无回弹",
      not back_jumps(xs_back) and win._left_role_page.geometry().x() == 0, str(xs_back))

# 右栏：聊天 → 管理 API（原「主界面之间」路径，同样自上而下 20px，不再是 10px）
xs_api, ys_api = sample_move(lambda: win._select_nav(1), win._api_panel)
check("主界面之间也为纵向 20px",
      real_displacement(ys_api, win.RIGHT_SLIDE) and set(xs_api) == {0},
      f"min_y={min(ys_api)} xs={sorted(set(xs_api))}")
check("主界面之间无回弹", not back_jumps(ys_api), str(ys_api))


# ========== 4c. 设置区视图细节（左栏无标题 / 恢复默认位置 / 回到顶端）==========
print("== 4c. 设置区视图细节 ==")
from PySide6.QtWidgets import QHBoxLayout, QLabel  # noqa: E402


# 1) 左栏设置导航：已无「设置」标题，两个设置项整体上移且等距
win._show_settings_page(win._settings_index["general"])
settle()
_ls = win._left_settings_page
_gp = win._settings_panels["general"]
check("通用设置页底部不滚动区 == 24px（与右侧间距一致，两个设置页统一）",
      _gp.height() - (_gp._scroll.geometry().bottom() + 1) == 24
      and _gp.width() - (_gp._scroll.geometry().right() + 1) == 24,
      f"bottom={_gp.height() - (_gp._scroll.geometry().bottom() + 1)} "
      f"right={_gp.width() - (_gp._scroll.geometry().right() + 1)}")
_lbl_texts = [w.text() for w in _ls.findChildren(QLabel)]
check("左栏设置页已无「设置」标题", _lbl_texts == [], str(_lbl_texts))
_m = _ls.layout().contentsMargins()
check("左栏设置页上边距仍为 24px", _m.top() == 24, str(_m.top()))
_b0 = win._settings_nav_btns[0][1]
_b1 = win._settings_nav_btns[1][1]
check("首个设置项即贴着上边距（无标题占位）", _b0.y() == _m.top(), f"y={_b0.y()} top={_m.top()}")
check("两个设置项等距排列（间距 6px）",
      _b1.y() - (_b0.y() + _b0.height()) == 6,
      f"gap={_b1.y() - (_b0.y() + _b0.height())}")

# 2) 权限管理：「恢复默认」与标题同行、位于右上角
_perm = win._settings_panels["permissions"]
win._show_settings_page(win._settings_index["permissions"])
settle()
_head = _perm.layout().itemAt(0)
check("权限管理首行即标题行（横向布局）", isinstance(_head, QHBoxLayout))
_head_texts = [
    _head.itemAt(i).widget().text()
    for i in range(_head.count())
    if _head.itemAt(i).widget() is not None and hasattr(_head.itemAt(i).widget(), "text")
]
check("标题行同时含「权限管理」「回到顶部」「恢复默认」",
      _head_texts == ["权限管理", "回到顶部", "恢复默认"], str(_head_texts))
check("「恢复默认」在面板右上角",
      _perm._reset_btn.x() > _perm.width() * 0.5 and _perm._reset_btn.y() < 40,
      f"x={_perm._reset_btn.x()} y={_perm._reset_btn.y()} w={_perm.width()}")
_perm_tail = _perm.layout().itemAt(_perm.layout().count() - 1).layout()
check("已无独立的底部按钮行（末项是「滚动区 + 消息行」底部区）",
      _perm_tail is not None and _perm_tail.itemAt(0).widget() is _perm._scroll
      and _perm_tail.itemAt(_perm_tail.count() - 1).widget() is _perm._msg_label)
# 底部不滚动区（会挡住内容的那一块）必须与「滚动条到窗口最右侧的间距」一致 = 24px
_bottom_band = _perm.height() - (_perm._scroll.geometry().bottom() + 1)
_right_band = _perm.width() - (_perm._scroll.geometry().right() + 1)
check("底部遮挡区高度 == 右侧间距（都是 24px）",
      _bottom_band == 24 and _right_band == 24 and _bottom_band == _right_band,
      f"bottom={_bottom_band} right={_right_band}")
check("底部区 = TAIL_BOTTOM + TAIL_GAP + 消息行高 = 24px",
      gui.TAIL_H == 24
      and gui.TAIL_BOTTOM + gui.TAIL_GAP + _perm._msg_label.minimumHeight() == 24,
      f"TAIL_H={gui.TAIL_H} msg={_perm._msg_label.minimumHeight()}")

# 3) 重新进入设置页回到顶端（不保留上次下拉位置）
_perm._body.setMinimumHeight(4000)  # 造出可滚动的长内容
settle(200)
_sb = _perm._scroll.verticalScrollBar()
check("可构造出非零滚动范围（前置条件）", _sb.maximum() > 0, f"max={_sb.maximum()}")
_sb.setValue(_sb.maximum() // 2)
check("已下拉到中部", _sb.value() > 0, str(_sb.value()))
win._show_settings_page(win._settings_index["general"])
settle()
check("切到通用设置：滚动区在顶端",
      gen_page._scroll.verticalScrollBar().value() == 0,
      str(gen_page._scroll.verticalScrollBar().value()))
win._show_settings_page(win._settings_index["permissions"])
settle()
check("切回权限管理：回到顶端", _sb.value() == 0, str(_sb.value()))
_perm._body.setMinimumHeight(0)
settle(200)


# 3b) 滚动条**恒常驻位**（2026-09-18 用户报的 bug：滚动条一出现，带边框卡片的右边框就退一截）
def _grab_colors(w):
    img = w.grab().toImage()
    return {img.pixelColor(x, y).name().lower()
            for x in range(img.width()) for y in range(img.height())}


check("设置页 / 权限页的垂直滚动条策略都是 AlwaysOn（视口宽度恒定）",
      _perm._scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
      and gen_page._scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn,
      f"{_perm._scroll.verticalScrollBarPolicy()} / {gen_page._scroll.verticalScrollBarPolicy()}")
_vp0 = _perm._scroll.viewport().width()
_body0 = _perm._body.width()
_perm._body.setMinimumHeight(4000)          # 造出滚动量 → 滑块出现
settle(200)
_vp1 = _perm._scroll.viewport().width()
_body1 = _perm._body.width()
check("有滚动量时滑块确实画出来了（前置条件，颜色 #DCDCDC）",
      _sb.maximum() > 0 and "#dcdcdc" in _grab_colors(_sb),
      f"max={_sb.maximum()} {sorted(_grab_colors(_sb))[:6]}")
# 「有没有滚动量」用**独立的 _panel_scroll 实例**验：权限页在小窗口下内容本身就超高
# （四个分组回到 62px 之后内容比视口高 16px），构造不出 maximum == 0 的稳定场景。
from PySide6.QtWidgets import QVBoxLayout  # noqa: E402

_p_holder = QWidget()
_p_holder_lay = QVBoxLayout(_p_holder)
_p_holder_lay.setContentsMargins(0, 0, 0, 0)
_p_scroll, _p_body, _p_body_lay = gui._panel_scroll(_p_holder_lay)
_p_holder.resize(300, 200)
_p_holder.show()
settle(200)
_p_sb = _p_scroll.verticalScrollBar()
check("短页面（无滚动量）：滑块**一根灰条都不画**（只留 8px 空道）",
      _p_sb.maximum() == 0 and "#dcdcdc" not in _grab_colors(_p_sb),
      f"max={_p_sb.maximum()} {sorted(_grab_colors(_p_sb))[:6]}")
_p_vp = _p_scroll.viewport().width()
_p_body.setMinimumHeight(600)               # 造出滚动量
settle(200)
check("长页面（有滚动量）：滑块画出来了（#DCDCDC）",
      _p_sb.maximum() > 0 and "#dcdcdc" in _grab_colors(_p_sb),
      f"max={_p_sb.maximum()} {sorted(_grab_colors(_p_sb))[:6]}")
check("加不加滚动量，滚动区视口宽度完全一样",
      _p_scroll.viewport().width() == _p_vp,
      f"{_p_vp} -> {_p_scroll.viewport().width()}")
_p_holder.close()
check("滚动条出现 / 消失，视口与 body 宽度都不变（卡片右边框不再一进一出）",
      _vp1 == _vp0 == _perm._scroll.viewport().width()
      and _body1 == _body0 == _perm._body.width(),
      f"vp {_vp0}->{_vp1}->{_perm._scroll.viewport().width()} "
      f"body {_body0}->{_body1}->{_perm._body.width()}")
check("body 右内边距仍是 8px（「卡片右边框 → 滑块」的固定呼吸位）",
      _perm._body.layout().contentsMargins().right() == 8,
      str(_perm._body.layout().contentsMargins().right()))

# 4) 「回到顶部」按钮：滚过一定距离才出现；点击 300ms 平滑回顶；且不顶动「恢复默认」
_perm._body.setMinimumHeight(4000)      # 造出足够长的内容
_sb.setValue(0)
settle(250)
_top = _perm._top_btn
check("标题行按钮为「回到顶部」+「恢复默认」，且回到顶部在左侧",
      isinstance(_top, gui._ScrollTopButton) and _top.x() < _perm._reset_btn.x(),
      f"x={_top.x()} reset_x={_perm._reset_btn.x()}")
check("「回到顶部」复用蓝色镂空按钮（outlineBtn）", _top.objectName() == "outlineBtn", _top.objectName())
check("可构造出非零滚动范围（回到顶部的前置条件）",
      _sb.maximum() > _top.SHOW_AT, f"max={_sb.maximum()} show_at={_top.SHOW_AT}")

# 停在顶部 → 不显示
check("停在顶部时「回到顶部」不显示", not _top.is_shown() and not _top.isVisible(),
      f"shown={_top.is_shown()} visible={_top.isVisible()}")

# 阈值边界 —— 这就是「下滑一定距离后再显示」的契约
_sb.setValue(_top.SHOW_AT - 1)
settle(300)
check(f"下滑不到 {_top.SHOW_AT}px 仍不显示", not _top.is_shown())
_sb.setValue(_top.SHOW_AT)
settle(300)
check(f"下滑达到 {_top.SHOW_AT}px 后显示（淡入到位）",
      _top.is_shown() and _top.isVisible() and _top._eff.opacity() > 0.9,
      f"shown={_top.is_shown()} visible={_top.isVisible()} opacity={_top._eff.opacity():.2f}")

# 关键防回归：显隐都不能顶动「恢复默认」（按钮排在 addStretch 右侧）
_reset_x = _perm._reset_btn.x()
_sb.setValue(0)
settle(300)
check("「回到顶部」隐藏后「恢复默认」位置不变",
      _perm._reset_btn.x() == _reset_x and not _top.is_shown(),
      f"x {_reset_x} -> {_perm._reset_btn.x()}")
_sb.setValue(_sb.maximum())
settle(300)
check("「回到顶部」显示后「恢复默认」位置不变",
      _perm._reset_btn.x() == _reset_x, f"x {_reset_x} -> {_perm._reset_btn.x()}")
check("两按钮不重叠且间距 8px",
      _top.x() + _top.width() <= _perm._reset_btn.x()
      and _perm._reset_btn.x() - (_top.x() + _top.width()) == 8,
      f"gap={_perm._reset_btn.x() - (_top.x() + _top.width())}")

# 点击 → 0.3s 平滑回顶（必须有中间帧，不能是瞬间跳）
check("回顶动画 = 300ms / OutCubic",
      _top._anim.duration() == 300
      and _top._anim.easingCurve().type() == gui.QEasingCurve.OutCubic,
      f"{_top._anim.duration()}ms {_top._anim.easingCurve().type()}")
_v0 = _sb.value()
check("点击前确实不在顶部（前置条件）", _v0 > 0, str(_v0))
_top.click()
_frames = []
for _ in range(10):
    settle(30)
    _frames.append(_sb.value())
check("回顶过程有中间帧（不是瞬间跳）",
      any(0 < v < _v0 for v in _frames), str(_frames))
check("回顶过程单调不增（无回弹）",
      all(b <= a for a, b in zip(_frames, _frames[1:])), str(_frames))
settle(400)
check("点击后回到顶部（value == 0）", _sb.value() == 0, str(_sb.value()))
check("回到顶部后按钮自动隐藏", not _top.is_shown() and not _top.isVisible(),
      f"shown={_top.is_shown()} visible={_top.isVisible()}")
_perm._body.setMinimumHeight(0)
settle(250)


# ========== 4d. 权限分组折叠（默认收起 + 动画 + 状态保留）==========
print("== 4d. 权限分组折叠 ==")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from app import tools as toolsmod  # noqa: E402

_perm = win._settings_panels["permissions"]
win._show_settings_page(win._settings_index["permissions"])
settle()

# ★2026-09-28：内置默认目录已清空（`tools.DEFAULT_ALLOWED_DIRS = ()`，见 docs/02 §8.9）。
#   本套此前「可操作目录/文件夹」组里默认就有 7 行，靠的是 `tools._perms` 在 **import 时**
#   取到的那个内置默认值；现在它是空的 ⇒ 该组只剩一条空态提示行（收起→展开只长 30px，
#   而不是 308px）⇒ 下面 §4d 那几条「只有卡片高度在变（max - min > 100）」的几何断言
#   **没料可测**，6 条直接红（实测：不加这句就是 765 项里红 6 项）。
#   ★这里**显式灌一份目录白名单**（= 用户自己添加过目录的那个态），让被测的是**有内容的分组** ——
#   刻意**不**把断言阈值改小：那是在削测试，而不是修测试。
toolsmod.apply_permissions({"allowed_dirs": [
    toolsmod._resolve_user_dir(n).as_posix() for n in
    ("Desktop", "Downloads", "Documents", "Pictures", "Music", "Videos")
]})
_perm._materialize()
_perm._rebuild()
settle(150)

groups = _perm._body.findChildren(gui._CollapsibleGroup)
check("可折叠分组恰为 4 个（目录 / 软件 / 操作类型 / 禁止词）",
      len(groups) == 4, str(len(groups)))
check("四组默认全部为「收起」", all(g.is_collapsed() for g in groups),
      str([g.is_collapsed() for g in groups]))
check("收起态内容区不可见", all(not g._content.isVisible() for g in groups))
check("默认状态表记录为收起", _perm._group_state == _perm.DEFAULT_GROUP_COLLAPSED,
      str(_perm._group_state))

# 结构：添加按钮位于【标题行右端、展开箭头左侧】，不再是卡片外的独立行
groups_with_btn = [g for g in groups if g._add_btn is not None]
check("三个白名单分组各自带添加按钮",
      len(groups_with_btn) == 3, str(len(groups_with_btn)))
check("添加按钮在标题行内（卡片外的独立按钮行已取消）",
      all(g._head.isAncestorOf(g._add_btn) and g._add_btn.parent() is g._head_btns
          for g in groups_with_btn),
      str([g._add_btn.parent() is g._head_btns for g in groups_with_btn]))


def _top_row(g):
    """标题行内的横向布局：文字块（大字+小字）+ 右端按钮容器。

    2026-09-18 起 `hv` 是 `[addStretch, top, addStretch]`（把文字行在 60px 里垂直居中），
    所以不能再写死 `itemAt(0)`，要取「不是 spacer 的那一项」。
    """
    lay = g._head.layout()
    for i in range(lay.count()):
        if lay.itemAt(i).layout() is not None:
            return lay.itemAt(i).layout()
    return None


def _btns_row(g):
    """标题行右端「添加按钮 + 展开箭头」容器内的布局。"""
    return g._head_btns.layout()


# 大字 + 小字必须是**同一个控件**（拆成两个 label 时会被各自 polish/重排 → 小字重渲染）
check("大字与小字是同一个富文本控件（一个整体，标题行内只有 2 个 label）",
      all(g._title_lbl.textFormat() == Qt.RichText
          and len(g._head.findChildren(QLabel)) == 2
          and g._title_lbl in g._head.findChildren(QLabel)
          and g._chevron in g._head.findChildren(QLabel)
          for g in groups),
      str([len(g._head.findChildren(QLabel)) for g in groups]))
check("分组标题**只剩大字**：说明小字已删（标题块里只有一个 <div>）",
      all(g._title_lbl.text().count("<div") == 1 for g in groups),
      str([g._title_lbl.text().count("<div") for g in groups]))
check("四个分组换成新文案（可操作目录/文件夹 · 可启动软件 · 可操作类型 · 禁止关键词）",
      all(name in g._title_lbl.text() for g, name in zip(
          groups, ("可操作目录/文件夹", "可启动软件", "可操作类型", "禁止关键词"))),
      str([g._title_lbl.text()[:60] for g in groups]))
# 说明小字**只留「危险操作延迟」那一条**（2026-09-18 用户口径：权限页其余小字全删）
_perm_gray = [lb.text() for lb in _perm.findChildren(QLabel)
              if lb.isVisible() and lb.text().strip()
              and "#64748B" in (lb.styleSheet() or "")]
check("权限页**全页**可见的灰说明小字只剩「危险操作延迟」那一条（标题下那条也删了）",
      len(_perm_gray) == 1 and "锁屏执行前的等待时间" in _perm_gray[0], str(_perm_gray))
check("留下的那条仍是 12px 灰字（与原来同一副样式，没被顺手改掉）",
      "font-size:12px" in next(lb for lb in _perm.findChildren(QLabel)
                               if lb.text() in _perm_gray).styleSheet(),
      _perm_gray[:1])
check("标题行顺序为 文字块 → 右侧按钮容器（按钮 → 箭头）",
      all(_top_row(g).count() == 2
          and _top_row(g).itemAt(0).widget() is g._title_lbl
          and _top_row(g).itemAt(1).widget() is g._head_btns
          and _btns_row(g).count() == 2
          and _btns_row(g).itemAt(0).widget() is g._add_btn
          and _btns_row(g).itemAt(1).widget() is g._chevron
          for g in groups_with_btn),
      str([(_top_row(g).count(), _btns_row(g).count()) for g in groups_with_btn]))
check("没有添加动作的分组只放箭头",
      all(_btns_row(g).count() == 1 for g in groups if g._add_btn is None),
      str([_btns_row(g).count() for g in groups if g._add_btn is None]))
# 几何：展开（按钮可见）后按钮确实在箭头左侧
_dbg_btn_group = groups_with_btn[0]
_dbg_btn_group.set_collapsed(False, animate=False)
settle(200)
check("添加按钮在展开箭头左侧（仍在标题行右端）",
      _dbg_btn_group._add_btn.x() + _dbg_btn_group._add_btn.width()
      <= _dbg_btn_group._chevron.x(),
      f"{_dbg_btn_group._add_btn.x()}+{_dbg_btn_group._add_btn.width()} "
      f"vs {_dbg_btn_group._chevron.x()}")
check("按钮容器与首行同高（28px），且在 60px 的标题行里垂直居中",
      _dbg_btn_group._head_btns.height() == gui._CollapsibleGroup.HEAD_ROW_H
      and abs((_dbg_btn_group._head_btns.y() + _dbg_btn_group._head_btns.height() / 2)
              - _dbg_btn_group._head.height() / 2) <= 1,
      f"{_dbg_btn_group._head_btns.geometry().getRect()} head={_dbg_btn_group._head.height()}")
_dbg_btn_group.set_collapsed(True, animate=False)
settle(200)
check("淡入淡出时长为 200ms",
      gui._CollapsibleGroup.ADD_FADE_MS == 200,
      str(gui._CollapsibleGroup.ADD_FADE_MS))
check("收起时添加按钮隐藏（透明度 0）",
      all(not g._add_btn.isVisible() and g._add_btn_eff.opacity() == 0.0
          for g in groups_with_btn),
      str([(g._add_btn.isVisible(), g._add_btn_eff.opacity()) for g in groups_with_btn]))

_act_group = next(g for g in groups if g._add_btn is None)
check("「可操作类型」无添加按钮", _act_group._add_btn is None)
check("分组内只有卡片一个子项（按钮不再是独立一段）",
      all(g.layout().count() == 1 and g.layout().itemAt(0).widget() is g._card for g in groups),
      str([g.layout().count() for g in groups]))

# 卡片边框：可折叠项本轮新增的样式（用户要求「加上边框，展开时边框拉长」）
check("卡片带 1px 边框 + 10px 圆角",
      all("border:1px solid #CBD5E1" in g._card.styleSheet()
          and f"border-radius:{gui._CollapsibleGroup.RADIUS}px" in g._card.styleSheet()
          for g in groups))
check("卡片高度随折叠状态变化（= 标题行 + 上下边框）",
      all(g._card.height() <= g._head.height() + 2 * gui._CollapsibleGroup.CARD_BORDER + 1
          for g in groups if g.is_collapsed),
      str([(g._card.height(), g._head.height()) for g in groups]))
check("卡片内首项为标题行、末项为内容区",
      all(g._card.layout().indexOf(g._head) == 0
          and g._card.layout().indexOf(g._content) == g._card.layout().count() - 1
          for g in groups),
      str([g._card.layout().count() for g in groups]))

# 间距与等高（用户确认值：组间 20px、危险区间距 30px）
check("组间间距常量为 20px", gui.PermPanel.GROUP_GAP == 20, str(gui.PermPanel.GROUP_GAP))
check("危险区间距常量为 30px", gui.PermPanel.DELAY_GAP == 30, str(gui.PermPanel.DELAY_GAP))
_group_gaps = [groups[i + 1].y() - (groups[i].y() + groups[i].height())
               for i in range(len(groups) - 1)]
check("相邻分组的实际空隙为 20px", all(x == 20 for x in _group_gaps), str(_group_gaps))
check("四个分组标题行等高（有无添加按钮一致）",
      len({g._head.height() for g in groups}) == 1,
      str([g._head.height() for g in groups]))
# 2026-09-18：小字删掉之后把标题行高度「改回原来的高度」+ 文字在边框内垂直居中
check("标题行最小高度常量 = 60px（小字删除前的老高度）",
      gui._CollapsibleGroup.HEAD_MIN_H == 60, str(gui._CollapsibleGroup.HEAD_MIN_H))
check("四个分组的标题行都是 60px（不再跟着小字一起缩到 40px）",
      all(g._head.height() == gui._CollapsibleGroup.HEAD_MIN_H for g in groups),
      str([g._head.height() for g in groups]))
check("收起态卡片高度 = 62px（60 + 上下各 1px 边框）",
      all(g._card.height() == gui._CollapsibleGroup.HEAD_MIN_H + 2 * gui._CollapsibleGroup.CARD_BORDER
          for g in groups if g.is_collapsed),
      str([(g._card.height(), g._head.height()) for g in groups]))
check("大字在标题行里**垂直居中**（文字块中线 = 标题行中线）",
      all(abs((g._title_lbl.y() + g._title_lbl.height() / 2) - g._head.height() / 2) <= 1
          for g in groups),
      str([(g._title_lbl.y(), g._title_lbl.height(), g._head.height()) for g in groups]))
check("右端「添加按钮 + 箭头」容器也在同一中线上",
      all(abs((g._head_btns.y() + g._head_btns.height() / 2) - g._head.height() / 2) <= 1
          for g in groups),
      str([(g._head_btns.y(), g._head_btns.height()) for g in groups]))
check("居中是靠标题行内**首尾两个 addStretch** 均分空白（不是靠写死 y）",
      all(g._head.layout().count() == 3
          and g._head.layout().itemAt(0).spacerItem() is not None
          and g._head.layout().itemAt(2).spacerItem() is not None
          for g in groups),
      str([g._head.layout().count() for g in groups]))
check("`_head_height()` 有 60px 下限，但 `sizeHint()` 仍是 40px（断言高度别用 sizeHint）",
      all(g._head_height() == 60 and g._head.sizeHint().height() == 40 for g in groups),
      str([(g._head_height(), g._head.sizeHint().height()) for g in groups]))

# 视觉上「看着不居中」的真因：首行写死 line-height 会把字形压到行盒底部（行盒居中 ≠ 墨迹居中）。
# 真机字体实测：28px 行盒里墨迹中心比行盒中心低 5.8px；去掉之后偏差 -0.2px。
_head_html_bare = gui._CollapsibleGroup._head_html("标题", "")
_head_html_hint = gui._CollapsibleGroup._head_html("标题", "提示")
_head_title_div = _head_html_hint.split("</div>")[0]     # 只有标题那一段
check("标题那一行**不写 line-height**（固定行高会把字形贴到行盒底部 → 看着偏下）",
      "line-height" not in _head_title_div
      and "line-height" not in _head_html_bare
      and "line-height:16px" in _head_html_hint,      # 小字那行照旧（字体更小，行高要钉住）
      repr(_head_html_bare) + " | " + repr(_head_title_div))


def _ink_center_off(widget, x1=250, tol=25):
    """墨迹（#334155 附近）的中心相对 widget 中心的偏移，单位=逻辑像素（已按 dpr 归一化）。"""
    img = widget.grab().toImage()
    dpr = img.width() / widget.width()
    rows = []
    for y in range(img.height()):
        n = sum(1 for x in range(int(4 * dpr), min(int(x1 * dpr), img.width()))
                if max(abs(img.pixelColor(x, y).red() - 0x33),
                       abs(img.pixelColor(x, y).green() - 0x41),
                       abs(img.pixelColor(x, y).blue() - 0x55)) <= tol)
        if n >= 2:
            rows.append(y)
    return ((rows[0] + rows[-1]) / 2.0 + 0.5) / dpr - (widget.height() - 1) / 2.0


_ink_offs = [_ink_center_off(g._head) for g in groups]
# 容差 3.5px 是留给**字体度量**的：offscreen 的兜底字体 descent=0，字形天然偏上 ~3px；
# 真机字体栈（Microsoft YaHei UI 13px）实测 -0.2px。改回固定行高会直接顶到 +5.8px（真机）而失败。
check("四个分组的标题墨迹都落在标题行的视觉中心（|偏移| ≤ 3.5px）",
      all(abs(o) <= 3.5 for o in _ink_offs),
      str([round(o, 2) for o in _ink_offs]))
_delay_title = next((l for l in _perm._body.findChildren(QLabel) if l.text() == "危险操作延迟"), None)
_delay_gap = (_delay_title.y() - (groups[-1].y() + groups[-1].height())) if _delay_title else None
check("「危险操作延迟」与上方分组的间距为 30px", _delay_gap == 30, str(_delay_gap))

# 「危险操作延迟」不参与折叠：常显
_delay_rows = [r for r in _perm._body.findChildren(gui._PermRow)
               if r.findChild(QLabel).text().endswith("秒")]
check("「危险操作延迟」的行始终可见（不折叠）",
      len(_delay_rows) == 1 and _delay_rows[0].isVisible(),
      f"n={len(_delay_rows)}")

# 顶部标题行 / 恢复默认按钮保持原状
_head = _perm.layout().itemAt(0)
check("面板标题行仍是横向布局且含「恢复默认」",
      isinstance(_head, QHBoxLayout)
      and any(_head.itemAt(i).widget() is _perm._reset_btn for i in range(_head.count())))


def sample_height(trigger, widget, ms=900, interval=8):
    """跑真实事件循环，逐帧采样 widget 高度（折叠动画必须单调推进）。"""
    hs = []
    timer = QTimer()
    timer.setInterval(interval)
    timer.timeout.connect(lambda: hs.append(widget.height()))
    timer.start()
    trigger()
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    timer.stop()
    return hs


_collapsed_h, _expanded_h = _act_group._measure()
check("收起高度 = 标题行高度（HEAD_MIN_H 兜底后的 60px）+ 卡片上下边框",
      _collapsed_h == _act_group._head_height() + 2 * gui._CollapsibleGroup.CARD_BORDER
      and _act_group._head.height() == _act_group._head_height() == 60
      and _collapsed_h == 62,
      f"{_collapsed_h}/{_act_group._head.sizeHint().height()}/{_act_group._head.height()}")
check("展开高度 > 收起高度（内容有真实高度）", _expanded_h > _collapsed_h + 100,
      f"{_collapsed_h} -> {_expanded_h}")

# 点标题行 → 展开（高度动画与 API 行同款：QTimer 逐帧推进）
_hs = sample_height(lambda: QTest.mouseClick(_act_group._head, Qt.LeftButton), _act_group)
check("展开：高度单调递增（无回弹）",
      all(_hs[i] >= _hs[i - 1] for i in range(1, len(_hs))) and len(_hs) > 5,
      str(_hs[:4] + ["..."] + _hs[-3:]))
check("展开：有中间帧（确实是动画而非瞬间跳变）",
      any(_collapsed_h < h < _expanded_h for h in _hs), f"{_hs[0]}..{_hs[-1]}")
check("展开：终点高度等于测量值",
      abs(_act_group.height() - _expanded_h) <= 2, f"{_act_group.height()}/{_expanded_h}")
check("展开后状态与内容可见",
      not _act_group.is_collapsed() and _act_group._content.isVisible())
check("展开后状态表已更新", _perm._group_state["actions"] is False, str(_perm._group_state))
check("展开后箭头改为向下（与下拉箭头同图）",
      not _act_group._chevron.pixmap().isNull()
      and _act_group._chevron.pixmap().toImage() == gui._chevron_pixmap(False).toImage())

# 添加按钮显隐：随展开淡入显示、随收起淡出后隐藏（200ms）
_dir_group = groups_with_btn[0]
_dir_group.set_collapsed(True, animate=False)          # 先确保收起
settle(300)
check("收起时添加按钮不可见",
      not _dir_group._add_btn.isVisible(), str(_dir_group._add_btn.isVisible()))

# 展开 → 淡入；同时逐帧采样标题行高度（防「展开时文字抽动」回归：
# 卡片高度动画期间布局若压缩标题行，小字提示会被压扁再弹回）
_dir_head_hs = sample_height(
    lambda: _dir_group.set_collapsed(False, animate=True), _dir_group._head)
check("展开动画期间标题行高度恒定（文字不抽动）",
      len(_dir_head_hs) > 5 and len(set(_dir_head_hs)) == 1, str(sorted(set(_dir_head_hs))))
check("标题行高度已钉死（setFixedHeight，硬约束不被布局压缩）",
      _dir_group._head.minimumHeight() == _dir_group._head.maximumHeight()
      == _dir_group._head_height(),
      f"{_dir_group._head.minimumHeight()}/{_dir_group._head.maximumHeight()}")
check("展开后添加按钮显示且完全不透明",
      _dir_group._add_btn.isVisible() and abs(_dir_group._add_btn_eff.opacity() - 1.0) < 0.01,
      f"{_dir_group._add_btn.isVisible()}/{_dir_group._add_btn_eff.opacity()}")
_dir_group.set_collapsed(True, animate=True)           # 收起 → 淡出
settle(400)
check("收起后添加按钮淡出并隐藏",
      not _dir_group._add_btn.isVisible() and _dir_group._add_btn_eff.opacity() == 0.0,
      f"{_dir_group._add_btn.isVisible()}/{_dir_group._add_btn_eff.opacity()}")


# ── 标题（大字+小字）相对**上边框**的位置必须全程不变（展开只把边框向下拉长）──
# 用户要求：可展开控件里的标题（原来还有下方小字）相对上边框位置保持不变。
# 这里把**每一次布局 / 尺寸事件**都抓下来（按 8ms 定时器采样会漏帧），断言标题的
# 纵向位置与尺寸是单一取值，只有卡片高度在变。
class _GeomSpy(QObject):
    def __init__(self, probe):
        super().__init__()
        self._probe = probe
        self.rows = []

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.LayoutRequest, QEvent.Resize):
            self.rows.append(self._probe())
        return False


def _pin_probe(g):
    def f():
        head, card, title, content = g._head, g._card, g._title_lbl, g._content
        return (
            head.mapTo(card, head.rect().topLeft()).y(),     # 标题行相对卡片上边框
            title.mapTo(head, title.rect().topLeft()).y(),   # 文字块相对标题行顶
            head.height(), title.height(), title.width(),    # 尺寸（宽度变了会重新换行）
            card.height(),                                   # 唯一允许变化的量
            # 内容区相对卡片上边框。修复前动画期间会被 QBoxLayout 上移到 0/36/42/48/55
            # → 它那些不透明白底的列表行盖住标题行的小字（标题 / 小字「消失又露出」）。
            # 修法：动画期间把内容区垂直策略临时设为 Ignored，内容区不再有最小高度诉求。
            content.mapTo(card, content.rect().topLeft()).y(),
            # 卡片宽度。2026-09-18 之前滚动条是 AsNeeded：收起末尾滚动条消失会让它 +8px，
            # 所以老断言刻意不看宽度；现在滚动条恒常驻位，宽度也必须是单一取值。
            card.width(),
        )
    return f


def _pin_spy(g, collapsed, ms=700):
    spy = _GeomSpy(_pin_probe(g))
    for w in (g._card, g._head, g._content, g):
        w.installEventFilter(spy)
    g.set_collapsed(collapsed, animate=True)
    settle(ms)
    for w in (g._card, g._head, g._content, g):
        w.removeEventFilter(spy)
    uniq = [len({r[i] for r in spy.rows}) for i in range(len(spy.rows[0]))]
    return spy.rows, uniq


_dir_rows, _dir_uniq = _pin_spy(_dir_group, False)      # 展开
check("展开：标题行 / 文字块相对上边框的位置全程不变（逐次布局采样）",
      len(_dir_rows) > 5 and _dir_uniq[0] == 1 and _dir_uniq[1] == 1,
      f"n={len(_dir_rows)} uniq={_dir_uniq}")
check("展开：标题行 / 文字块高度全程不变（不会中途重新换行）",
      _dir_uniq[2] == 1 and _dir_uniq[3] == 1,
      f"uniq={_dir_uniq}")
check("展开：只有卡片高度在变（边框确实是向下拉长）",
      len({r[5] for r in _dir_rows}) > 5
      and max(r[5] for r in _dir_rows) > min(r[5] for r in _dir_rows) + 100,
      f"card_h={sorted({r[5] for r in _dir_rows})}")
check("展开：标题行贴在上边框内侧（只留 1px 边框）",
      {r[0] for r in _dir_rows} == {gui._CollapsibleGroup.CARD_BORDER},
      str({r[0] for r in _dir_rows}))
check("展开：内容区上沿全程不变（不会被布局上移去盖住标题行）",
      _dir_uniq[6] == 1, f"uniq={_dir_uniq}")
check("展开：内容区上沿恒 = 标题行下沿（内容只从标题行下方长出来）",
      len(_dir_rows) > 5 and all(r[6] == r[0] + r[2] for r in _dir_rows),
      str(sorted({(r[6], r[0] + r[2]) for r in _dir_rows})))
check("展开：**卡片宽度**全程不变（滚动条恒常驻位，不再中途挤掉 8px）",
      len(_dir_rows) > 5 and _dir_uniq[7] == 1,
      f"n={len(_dir_rows)} uniq={_dir_uniq} widths={sorted({r[7] for r in _dir_rows})}")
check("已备份内容区默认垂直策略（供动画结束后原样还原）",
      _dir_group._content_v_policy == QSizePolicy.Preferred,
      str(getattr(_dir_group, "_content_v_policy", None)))

# 收起方向同样成立。**卡片宽度现在也全程不变了**（2026-09-18 起滚动条恒常驻位，
# 不再有「收起末尾滚动条消失 → 可用宽度多出 8px」这回事）—— 见下面第 8 列。
# 文字块**自己的宽度**仍可能出现两个取值：展开时「添加」按钮淡出后才真正 setVisible(False)，
# 那 36px 会回到文字块手里。那是按钮的显隐，不是抖动（高度不变 ⇒ 不换行 ⇒ 位置不动）。
_dir_rows2, _dir_uniq2 = _pin_spy(_dir_group, True)     # 收起
check("收起：标题行 / 文字块相对上边框的位置全程不变",
      len(_dir_rows2) > 5 and _dir_uniq2[0] == 1 and _dir_uniq2[1] == 1,
      f"n={len(_dir_rows2)} uniq={_dir_uniq2}")
check("收起：**卡片宽度**全程不变（滚动条恒常驻位，不再中途让出 8px）",
      len(_dir_rows2) > 5 and _dir_uniq2[7] == 1,
      f"n={len(_dir_rows2)} uniq={_dir_uniq2} widths={sorted({r[7] for r in _dir_rows2})}")
check("收起：标题行 / 文字块高度全程不变（不会中途重新换行）",
      _dir_uniq2[2] == 1 and _dir_uniq2[3] == 1,
      f"uniq={_dir_uniq2}")
check("收起：只有卡片高度在变（边框缩回标题行）",
      len({r[5] for r in _dir_rows2}) > 5
      and min(r[5] for r in _dir_rows2) < max(r[5] for r in _dir_rows2) - 100,
      f"card_h={sorted({r[5] for r in _dir_rows2})}")
check("收起：标题行仍贴在上边框内侧（只留 1px 边框）",
      {r[0] for r in _dir_rows2} == {gui._CollapsibleGroup.CARD_BORDER},
      str({r[0] for r in _dir_rows2}))
check("收起：内容区上沿全程不变（不会被布局上移去盖住标题行）",
      _dir_uniq2[6] == 1, f"uniq={_dir_uniq2}")
check("收起：内容区上沿恒 = 标题行下沿（内容只从标题行下方向上收起）",
      len(_dir_rows2) > 5 and all(r[6] == r[0] + r[2] for r in _dir_rows2),
      str(sorted({(r[6], r[0] + r[2]) for r in _dir_rows2})))
check("收起：动画结束后内容区垂直策略已还原（不是 Ignored）",
      _dir_group._content.sizePolicy().verticalPolicy()
      == _dir_group._content_v_policy == QSizePolicy.Preferred,
      str(_dir_group._content.sizePolicy().verticalPolicy()))


# hover 底色淡入**不得**触发样式 / 布局风暴（底色自绘）。修复前实测：一次 200ms 淡入会让
# 标题行收到 14 次 style + 14 次 layout，里面的文字控件被 polish 28 次 → 「小字重新渲染」。
class _EvCounter(QObject):
    _KEYS = {QEvent.StyleChange: "style", QEvent.LayoutRequest: "layout", QEvent.Paint: "paint"}

    def __init__(self):
        super().__init__()
        self.c = {}

    def eventFilter(self, obj, ev):
        key = self._KEYS.get(ev.type())
        if key:
            self.c[key] = self.c.get(key, 0) + 1
        return False


_c_head, _c_lbl = _EvCounter(), _EvCounter()
_dir_group._head.installEventFilter(_c_head)
_dir_group._title_lbl.installEventFilter(_c_lbl)
_dir_group._head.enterEvent(None)                      # 触发 hover 淡入（200ms）
settle(400)
check("hover 淡入期间标题行不重算样式 / 布局",
      _c_head.c.get("style", 0) == 0 and _c_head.c.get("layout", 0) == 0,
      str(_c_head.c))
check("hover 淡入期间「大字+小字」控件不被重新 polish",
      _c_lbl.c.get("style", 0) == 0, str(_c_lbl.c))
check("hover 淡入确实有逐帧重绘（底色是渐变而非瞬间跳变）",
      _c_head.c.get("paint", 0) > 3, str(_c_head.c))
check("hover 终态底色为淡蓝 #E6F1FB（自绘）",
      _dir_group._head.bg_rgb() == QColor("#E6F1FB").rgb(),
      hex(_dir_group._head.bg_rgb()))
_dir_group._head.leaveEvent(None)
settle(400)
check("hover 离开后底色回到纯白 #FFFFFF（自绘）",
      _dir_group._head.bg_rgb() == QColor("#FFFFFF").rgb(),
      hex(_dir_group._head.bg_rgb()))
check("展开后卡片边框被拉长，包住全部内容行",
      _act_group._card.height()
      >= _act_group._head.height() + _act_group._content.height(),
      f"card={_act_group._card.height()} head={_act_group._head.height()} "
      f"content={_act_group._content.height()}")
check("展开后标题行仍贴在卡片顶部（边框只往下长）",
      _act_group._head.y() <= gui._CollapsibleGroup.CARD_BORDER,
      str(_act_group._head.y()))

# 再点一次 → 收起
_hs2 = sample_height(lambda: QTest.mouseClick(_act_group._head, Qt.LeftButton), _act_group)
check("收起：高度单调递减（无回弹）",
      all(_hs2[i] <= _hs2[i - 1] for i in range(1, len(_hs2))) and len(_hs2) > 5,
      str(_hs2[:4] + ["..."] + _hs2[-3:]))
check("收起：终点回到收起高度",
      abs(_act_group.height() - _collapsed_h) <= 2, f"{_act_group.height()}/{_collapsed_h}")
check("收起后内容区被隐藏",
      _act_group.is_collapsed() and not _act_group._content.isVisible())
check("收起后卡片边框缩回标题行高度",
      _act_group._card.height()
      <= _act_group._head.height() + 2 * gui._CollapsibleGroup.CARD_BORDER + 1,
      f"card={_act_group._card.height()} head={_act_group._head.height()}")
check("收起后标题行下圆角回到内圆角（它是卡片最后一块）",
      isinstance(_act_group._head, gui._HeadFrame)
      and _act_group._head._r_bottom == gui._CollapsibleGroup.INNER_RADIUS
      and _act_group._head._r_top == gui._CollapsibleGroup.INNER_RADIUS,
      f"{type(_act_group._head).__name__} r={_act_group._head._r_top}/{_act_group._head._r_bottom}")
check("标题行底色自绘，不走 QSS（否则 hover 每帧重算样式 → 小字重新渲染）",
      _act_group._head.styleSheet() == "",
      repr(_act_group._head.styleSheet()[:60]))
check("收起后状态表已更新", _perm._group_state["actions"] is True, str(_perm._group_state))

# 展开状态跨 rebuild 保留（删一行这类面板内刷新不会把分组弹回去）
_act_group.set_collapsed(False, animate=False)
_perm._rebuild()
settle(200)
_g2 = _perm._body.findChildren(gui._CollapsibleGroup)
check("rebuild 后仍是 4 个分组", len(_g2) == 4, str(len(_g2)))
check("rebuild 后展开状态被保留（面板内刷新不弹回）",
      [g.is_collapsed() for g in _g2] == [True, True, False, True],
      str([g.is_collapsed() for g in _g2]))

# 页面切换 → 重新进入权限管理必须变回全收起
check("切换前确有分组处于展开", any(not g.is_collapsed() for g in _g2))
win._show_settings_page(win._settings_index["general"])
settle()
check("已离开权限管理页", win._right_stack.currentIndex() == win._settings_index["general"])
win._show_settings_page(win._settings_index["permissions"])
settle()
_g3 = _perm._body.findChildren(gui._CollapsibleGroup)
check("切回权限管理：分组全部回到收起",
      len(_g3) == 4 and all(g.is_collapsed() for g in _g3),
      str([g.is_collapsed() for g in _g3]))
check("切回权限管理：状态表也一并复位", _perm._group_state == _perm.DEFAULT_GROUP_COLLAPSED,
      str(_perm._group_state))
check("切回权限管理：收起态内容区不可见", all(not g._content.isVisible() for g in _g3))

# 离开整块设置区（切到聊天）再回来，同样必须收起
_exp = _perm._body.findChildren(gui._CollapsibleGroup)[0]
_exp.set_collapsed(False, animate=False)
check("（前置）目录分组已展开", not _exp.is_collapsed())
win._switch_right_panel(win.PAGE_CHAT, animate=False)
settle(120)
win._show_settings_page(win._settings_index["permissions"])
settle(200)
check("切到聊天再回权限管理：分组回到收起",
      all(g.is_collapsed() for g in _perm._body.findChildren(gui._CollapsibleGroup)))

# 重复进入同一页不算页面切换，不该把正在展开的分组弹回去
_perm._body.findChildren(gui._CollapsibleGroup)[0].set_collapsed(False, animate=False)
win._show_settings_page(win._settings_index["permissions"])
settle(150)
check("重复进入同一页不重置折叠状态",
      not _perm._body.findChildren(gui._CollapsibleGroup)[0].is_collapsed())

# 复原成展开测试最开始的干净状态
_perm.reset_groups()
_perm._rebuild()
settle(150)
check("复位后回到全收起",
      all(g.is_collapsed() for g in _perm._body.findChildren(gui._CollapsibleGroup)))
check("复位后状态表等于默认值", _perm._group_state == _perm.DEFAULT_GROUP_COLLAPSED,
      str(_perm._group_state))


# ========== 4e. 权限「允许的操作类型」圆形滑块开关 ==========
print("== 4e. 权限操作类型滑块 ==")
from PySide6.QtWidgets import QPushButton  # noqa: E402

_perm = win._settings_panels["permissions"]
win._show_settings_page(win._settings_index["permissions"])
settle()
# 滑块在折叠分组内部，先展开全部分组再测（贴近真实使用路径）
for _g in _perm._body.findChildren(gui._CollapsibleGroup):
    _g.set_collapsed(False, animate=False)
settle(200)

rows = _perm._body.findChildren(gui._PermToggleRow)
check("操作类型行数 = 内置操作类型数",
      len(rows) == len(gui._ACTION_NAMES), f"{len(rows)}/{len(gui._ACTION_NAMES)}")
check("每行的切换控件都是圆形滑块",
      rows and all(isinstance(r._btn, gui._ToggleSwitch) for r in rows),
      str(sorted({type(r._btn).__name__ for r in rows})))
check("滑块尺寸 44×24",
      (gui._ToggleSwitch.WIDTH, gui._ToggleSwitch.HEIGHT) == (44, 24),
      f"{gui._ToggleSwitch.WIDTH}×{gui._ToggleSwitch.HEIGHT}")
check("圆钮直径为圆（18px = 轨道高 - 2×留白）",
      gui._ToggleSwitch.HEIGHT - 2 * gui._ToggleSwitch.PAD == 18)
check("行内已无「允许 / 禁止」文字按钮",
      not any(w.text() in ("允许", "禁止") for r in rows for w in r.findChildren(QPushButton)),
      str([w.text() for r in rows for w in r.findChildren(QPushButton)]))


def _px(switch, x):
    """取滑块内部 (x, 中线) 处的像素颜色，用于验证轨道色与圆钮位置。"""
    return switch.grab().toImage().pixelColor(x, switch.height() // 2).name().upper()


def _hover_row(row, t=1.0):
    """把行置成 hover 终态（截图 / 取样用）。

    删除按钮与滑块都是**仅 hover 该行时显示**的，未 hover 时是「透明但占位」，
    取样前必须先落到 hover 态，否则拿到的是空白。
    """
    row._hover_anim.stop()
    row._apply_bg(t)
    return row


def _row_of(atype):
    """按类型取行（切换操作类型不再重建面板，这里通常就是原来那一行）。"""
    name = gui._ACTION_NAMES[atype]
    for r in _perm._body.findChildren(gui._PermToggleRow):
        lbl = r.findChild(QLabel)
        if lbl is not None and lbl.text() == name:
            return r
    raise AssertionError(f"未找到 {atype} 对应的行")


first = rows[0]
atype = next(k for k, v in gui._ACTION_NAMES.items() if v == first.findChild(QLabel).text())
check("默认全为「开」（允许）", all(r._btn.isChecked() for r in rows))
check("滑块默认隐藏：未 hover 的行 opacity 全为 0",
      all(r._btn._opacity == 0.0 for r in rows),
      str([round(r._btn._opacity, 2) for r in rows]))
check("隐藏时不接收鼠标事件（不会点到隐形滑块）",
      all(r._btn.testAttribute(Qt.WA_TransparentForMouseEvents) for r in rows))

_hover_row(first)
check("hover 后滑块淡入到 opacity=1", first._btn._opacity == 1.0, str(first._btn._opacity))
check("hover 后恢复接收鼠标事件",
      not first._btn.testAttribute(Qt.WA_TransparentForMouseEvents))
check("开态：轨道主蓝 #378ADD", _px(first._btn, 5) == "#378ADD", _px(first._btn, 5))
check("开态：圆钮位于右侧（白色圆）", _px(first._btn, 38) == "#FFFFFF", _px(first._btn, 38))
check("开态：滑块归一化位置 t=1", first._btn._t == 1.0, str(first._btn._t))

# 点击滑块 → 关
QTest.mouseClick(first._btn, Qt.LeftButton)
settle(300)
closed = _row_of(atype)
check("点击后滑块变为「关」", not closed._btn.isChecked())
check("切换操作类型不再整体重建面板（hover 态与淡入不被打断）", closed is first)
check("关态：轨道中性灰 #CBD5E1", _px(closed._btn, 38) == "#CBD5E1", _px(closed._btn, 38))
check("关态：圆钮位于左侧（白色圆）", _px(closed._btn, 5) == "#FFFFFF", _px(closed._btn, 5))
check("关态：滑块归一化位置 t=0", closed._btn._t == 0.0, str(closed._btn._t))
check("关态：写回内存配置",
      atype not in cfg["permissions"]["allowed_actions"], str(cfg["permissions"]["allowed_actions"]))
check("关态：已持久化到磁盘",
      atype not in json.loads(tmp_cfg.read_text(encoding="utf-8"))["permissions"]["allowed_actions"])
check("关态：权限层同步生效",
      atype not in toolsmod.get_permissions()["allowed_actions"])
check("切换后底部消息行有反馈（提示不再丢失）",
      "已禁止" in _perm._msg_label.text(), _perm._msg_label.text())

# 再点一次 → 开（并还原现场）
QTest.mouseClick(closed._btn, Qt.LeftButton)
settle(300)
opened = _row_of(atype)
check("再点一次恢复为「开」", opened._btn.isChecked() and _px(opened._btn, 5) == "#378ADD",
      f"checked={opened._btn.isChecked()} px={_px(opened._btn, 5)}")


# ========== 4f. 分组内容行样式（无边框无缝 + 删除按钮/滑块 hover 淡入）==========
print("== 4f. 分组内容行样式 ==")
from PySide6.QtCore import QEvent, QPointF  # noqa: E402
from PySide6.QtGui import QEnterEvent  # noqa: E402

_groups = _perm._body.findChildren(gui._CollapsibleGroup)
for _g in _groups:
    _g.set_collapsed(False, animate=False)
settle(250)

check("分组内容行之间无间距（body_lay spacing == 0）",
      all(g.body_lay.spacing() == 0 for g in _groups),
      str([g.body_lay.spacing() for g in _groups]))
check("内容行上下紧贴（下一行 y = 上一行底边）",
      all(g.body_lay.itemAt(i).widget().y() ==
          g.body_lay.itemAt(i - 1).widget().y() + g.body_lay.itemAt(i - 1).widget().height()
          for g in _groups for i in range(1, g.body_lay.count())
          if g.body_lay.itemAt(i).widget() is not None
          and g.body_lay.itemAt(i - 1).widget() is not None),
      str([[g.body_lay.itemAt(i).widget().y() for i in range(g.body_lay.count())
            if g.body_lay.itemAt(i).widget() is not None] for g in _groups]))

_all_rows = (_perm._body.findChildren(gui._PermRow)
             + _perm._body.findChildren(gui._PermToggleRow))
_flat_rows = [r for r in _all_rows if r._flat]
check("分组内的行都是 flat 行", len(_flat_rows) >= 15, str(len(_flat_rows)))
check("flat 行已去掉边框（border:none）",
      all("border:none" in r.styleSheet() for r in _flat_rows),
      str([r.styleSheet()[:60] for r in _flat_rows[:2]]))
check("flat 行不再有整体圆角",
      all("border-radius:10px" not in r.styleSheet() for r in _flat_rows))
_groups_with_rows = [
    g for g in _groups
    if isinstance(g.body_lay.itemAt(g.body_lay.count() - 1).widget(),
                  (gui._PermRow, gui._PermToggleRow))
]
check("末行补底部圆角（与外框圆角对齐）",
      bool(_groups_with_rows)
      and all(g.body_lay.itemAt(g.body_lay.count() - 1).widget()._round_bottom
              for g in _groups_with_rows),
      str([[type(g.body_lay.itemAt(g.body_lay.count() - 1).widget()).__name__,
            getattr(g.body_lay.itemAt(g.body_lay.count() - 1).widget(),
                    "_round_bottom", None)] for g in _groups]))
_rounded = [r for r in _flat_rows if r._round_bottom]
check("底部圆角只加在末行（有行的分组各一行）",
      len(_rounded) == len(_groups_with_rows)
      and all("border-bottom-left-radius:9px" in r.styleSheet() for r in _rounded),
      f"{len(_rounded)}/{len(_groups_with_rows)}")
check("空白分组（只有小字提示）不参与圆角逻辑",
      all(getattr(g.body_lay.itemAt(g.body_lay.count() - 1).widget(),
                  "_round_bottom", None) is None
          for g in _groups if g not in _groups_with_rows))
check("非末行没有底部圆角",
      all("border-bottom-left-radius" not in r.styleSheet()
          for r in _flat_rows if not r._round_bottom))

# 「危险操作延迟」不在分组内，保持有边框的老样式（用户要求「保持不变」）
_delay = [r for r in _perm._body.findChildren(gui._PermRow) if not r._flat]
check("「危险操作延迟」行仍保留边框样式",
      len(_delay) == 1 and "border:1px solid #CBD5E1" in _delay[0].styleSheet(),
      str(len(_delay)))

# hover 变色效果保留：白 #FFFFFF ↔ 淡蓝 #E6F1FB
_sample = _flat_rows[0]
_sample._apply_bg(0.0)
check("未 hover：行底色为白", "rgb(255,255,255)" in _sample.styleSheet(),
      _sample.styleSheet()[:70])
_sample._apply_bg(1.0)
check("hover：行底色淡蓝 rgb(230,241,255)", "rgb(230,241,255)" in _sample.styleSheet(),
      _sample.styleSheet()[:70])
_toggle_row = next(r for r in _flat_rows if isinstance(r, gui._PermToggleRow))
_toggle_row._apply_bg(1.0)
check("开关行同样有 hover 变色（原先缺失）",
      "rgb(230,241,255)" in _toggle_row.styleSheet(), _toggle_row.styleSheet()[:70])

# 删除按钮：仅 hover 行时显示，用透明度淡入淡出（不是 setVisible，避免文字重排）
_btn_row = next(r for r in _flat_rows if isinstance(r, gui._PermRow))
_btn_row._apply_bg(0.0)
check("删除按钮未 hover 时 opacity=0", _btn_row._btn_effect.opacity() == 0.0,
      str(_btn_row._btn_effect.opacity()))
check("未 hover 时删除按钮不接收鼠标事件",
      _btn_row._btn.testAttribute(Qt.WA_TransparentForMouseEvents))
check("按钮依然占位（宽度未被隐藏清零，文字不重排）",
      _btn_row._btn.width() == _btn_row._btn.minimumWidth() > 0
      or _btn_row._btn.width() == 56, str(_btn_row._btn.width()))
_btn_row._apply_bg(1.0)
check("hover 后删除按钮 opacity=1 且可点击",
      _btn_row._btn_effect.opacity() == 1.0
      and not _btn_row._btn.testAttribute(Qt.WA_TransparentForMouseEvents))

# 淡入淡出与底色变化同步：同一动画、同一时长、同一插值进度
check("行 hover 动画时长 = 200ms（与底色变化一致）",
      _btn_row._hover_anim.duration() == 200 == _toggle_row._hover_anim.duration() == 200,
      f"{_btn_row._hover_anim.duration()}/{_toggle_row._hover_anim.duration()}")
_sync_ok, _sync_detail = True, []
for _t in (0.0, 0.25, 0.5, 0.75, 1.0):
    _btn_row._apply_bg(_t)
    _toggle_row._apply_bg(_t)
    _r = int(255 + (230 - 255) * _t)
    _g_ = int(255 + (241 - 255) * _t)
    _mid = f"rgb({_r},{_g_},255)" in _btn_row.styleSheet()
    _bo = abs(_btn_row._btn_effect.opacity() - _t) < 1e-6
    _so = abs(_toggle_row._btn._opacity - _t) < 1e-6
    _sync_detail.append((_t, _mid, round(_btn_row._btn_effect.opacity(), 2),
                         round(_toggle_row._btn._opacity, 2)))
    _sync_ok = _sync_ok and _mid and _bo and _so
check("按钮/滑块透明度与底色变化严格同步（同一进度）", _sync_ok, str(_sync_detail))

# 真实 enter / leave：淡入淡出是逐帧动画而非瞬间切换
_btn_row._apply_bg(0.0)
_btn_row.enterEvent(QEnterEvent(QPointF(2, 2), QPointF(2, 2), QPointF(2, 2)))
settle(70)
_mid_op = _btn_row._btn_effect.opacity()
check("进入行：按钮处于淡入中途（0 < opacity < 1）", 0.0 < _mid_op < 1.0, str(_mid_op))
settle(250)
check("进入行：淡入完成 opacity=1", _btn_row._btn_effect.opacity() == 1.0,
      str(_btn_row._btn_effect.opacity()))
_btn_row.leaveEvent(QEvent(QEvent.Leave))
settle(70)
_mid_op2 = _btn_row._btn_effect.opacity()
check("离开行：按钮处于淡出中途（0 < opacity < 1）", 0.0 < _mid_op2 < 1.0, str(_mid_op2))
settle(250)
check("离开行：淡出完成 opacity=0 且不可点击",
      _btn_row._btn_effect.opacity() == 0.0
      and _btn_row._btn.testAttribute(Qt.WA_TransparentForMouseEvents),
      str(_btn_row._btn_effect.opacity()))

# 复原现场
_perm.reset_groups()
_perm._rebuild()
settle(150)


# ========== 4g. 权限删除二次确认 + 自定义软件重命名 ==========
print("== 4g. 权限删除确认 / 软件重命名 ==")

_perm = win._settings_panels["permissions"]
win._show_settings_page(win._settings_index["permissions"])
settle()

# --- 1) 行内「第二个按钮」的结构 ---
_standalone = gui._PermRow("SuperTool", "删除", lambda: None, flat=True,
                           extra_text="重命名", on_extra=lambda: None)
check("传 extra_text 的行会多出一个按钮",
      _standalone._btn_extra is not None and _standalone._btn_extra.text() == "重命名")
check("不传 extra_text 时只有删除按钮（内置软件行）",
      gui._PermRow("记事本", "删除", lambda: None, flat=True)._btn_extra is None)
check("两个按钮各持一个独立的透明度 effect",
      _standalone._btn_effect is not None and _standalone._btn_extra_effect is not None
      and _standalone._btn_effect is not _standalone._btn_extra_effect)
# 蓝（非破坏性）在左、红（破坏性）在右 —— 与 API 行「蓝编辑 / 红删除」同序
_standalone_layout = _standalone.layout()
check("重命名（蓝）排在删除（红）左侧",
      _standalone_layout.indexOf(_standalone._btn_extra) < _standalone_layout.indexOf(_standalone._btn),
      f"{_standalone_layout.indexOf(_standalone._btn_extra)}/{_standalone_layout.indexOf(_standalone._btn)}")
check("重命名=蓝色镂空、删除=红色镂空",
      _standalone._btn_extra.objectName() == "outlineBtn"
      and _standalone._btn.objectName() == "dangerBtn")
check("按钮宽度下限 = 56px（两字文案正好 56）",
      gui._PermRow.BTN_W == 56
      and _standalone._btn_extra.minimumWidth() == gui._PermRow.BTN_W
      and _standalone._btn.minimumWidth() == gui._PermRow.BTN_W)
# 防回归：一旦有人改回 setFixedWidth(56)，三字文案「重命名」会被直接裁掉
check("按钮不再写死 56px（否则三字文案被裁字）",
      _standalone._btn_extra.maximumWidth() > gui._PermRow.BTN_W
      and _standalone._btn.maximumWidth() > gui._PermRow.BTN_W,
      f"max=({_standalone._btn_extra.maximumWidth()}, {_standalone._btn.maximumWidth()})")
_standalone.resize(420, 44)
_standalone.layout().activate()
check("两字文案按钮实际宽度仍是 56px",
      _standalone._btn.width() == 56, str(_standalone._btn.width()))
check("三字「重命名」按钮按文字放宽（宽度 >= sizeHint，不裁字）",
      _standalone._btn_extra.width() >= _standalone._btn_extra.sizeHint().width() > 56,
      f"w={_standalone._btn_extra.width()} hint={_standalone._btn_extra.sizeHint().width()}")

# --- 2) 真实面板：只有「从磁盘添加的软件」行才有重命名 ---
from app import tools as _t  # noqa: E402

_t.apply_permissions({
    "allowed_apps": ["记事本", "SuperTool"],
    "custom_apps": {"SuperTool": "D:/Games/SuperTool.exe"},
    # ★2026-09-28：内置默认目录已清空 ⇒ 这里**显式给一条目录**。下面 §4「删除目录要二次确认」
    #   那三条正是靠 `get_permissions()["allowed_dirs"][0]` 取样的 —— 不给的话直接 IndexError
    #   （表象是整套红，看着像功能坏了，其实是没料可删）。
    "allowed_dirs": [_t._resolve_user_dir("Desktop").as_posix()],
})
_perm._materialize()
_perm._rebuild()
settle(120)


def _row_label(row):
    lbl = row.findChild(QLabel)
    return lbl.text() if lbl is not None else ""


_rows_by_text = {_row_label(r): r for r in _perm._body.findChildren(gui._PermRow)}
check("软件组里能同时看到内置与自定义两行",
      "记事本" in _rows_by_text and "SuperTool" in _rows_by_text,
      str(sorted(_rows_by_text)))
check("自定义软件行有「重命名」按钮", _rows_by_text["SuperTool"]._btn_extra is not None)
check("内置软件行没有「重命名」按钮", _rows_by_text["记事本"]._btn_extra is None)
check("其他行（目录 / 危险延迟）也没有「重命名」按钮",
      all(r._btn_extra is None for r in _perm._body.findChildren(gui._PermRow)
          if _row_label(r) not in ("SuperTool",)),
      str([_row_label(r) for r in _perm._body.findChildren(gui._PermRow) if r._btn_extra is not None]))

# flat 行两个按钮必须「一起」淡入淡出，否则一个亮一个暗
_cr = _rows_by_text["SuperTool"]
_cr._apply_bg(0.0)
check("未 hover：两个按钮都 opacity=0 且都不接收点击",
      _cr._btn_effect.opacity() == 0.0 == _cr._btn_extra_effect.opacity()
      and _cr._btn.testAttribute(Qt.WA_TransparentForMouseEvents)
      and _cr._btn_extra.testAttribute(Qt.WA_TransparentForMouseEvents))
_cr._apply_bg(0.4)
check("t<0.5：两个按钮都还不可点击",
      _cr._btn.testAttribute(Qt.WA_TransparentForMouseEvents)
      and _cr._btn_extra.testAttribute(Qt.WA_TransparentForMouseEvents))
_cr._apply_bg(1.0)
check("hover 后两个按钮都 opacity=1 且都可点击",
      _cr._btn_effect.opacity() == 1.0 == _cr._btn_extra_effect.opacity()
      and not _cr._btn.testAttribute(Qt.WA_TransparentForMouseEvents)
      and not _cr._btn_extra.testAttribute(Qt.WA_TransparentForMouseEvents))
_sync_progress, _sync_pairs = True, []
for _tt in (0.0, 0.25, 0.5, 0.75, 1.0):
    _cr._apply_bg(_tt)
    _a, _b = _cr._btn_effect.opacity(), _cr._btn_extra_effect.opacity()
    _sync_pairs.append((round(_a, 3), round(_b, 3)))
    _sync_progress = _sync_progress and abs(_a - _b) < 1e-9 and abs(_a - _tt) < 1e-9
check("两个按钮全程同进度（不会一亮一暗）", _sync_progress, str(_sync_pairs))
_cr._apply_bg(0.0)

# --- 3) 重命名：改的是匹配用的名字，exe 路径不动 ---
class _StubInput:
    """替掉 InputDialog（不要在 Qt 类型上打补丁，改模块名即可）。"""

    value, ok, last_default = "", False, None

    @staticmethod
    def get_text(parent, title, label, default=""):
        _StubInput.last_default = default
        return _StubInput.value, _StubInput.ok


_orig_input = gui.InputDialog
gui.InputDialog = _StubInput
try:
    _StubInput.ok, _StubInput.value = True, "超级工具"
    _perm._rename_app("SuperTool")
    check("输入框预填当前名字", _StubInput.last_default == "SuperTool", str(_StubInput.last_default))
    _p = _t.get_permissions()
    check("重命名后旧名字从白名单与登记表消失",
          "SuperTool" not in _p["allowed_apps"] and "SuperTool" not in _p["custom_apps"],
          str(_p["allowed_apps"]))
    check("重命名后新名字进入白名单与登记表",
          "超级工具" in _p["allowed_apps"] and "超级工具" in _p["custom_apps"])
    check("重命名不改 exe 路径",
          _p["custom_apps"]["超级工具"] == "D:/Games/SuperTool.exe", str(_p["custom_apps"]))
    _hit = _t.detect_action("打开超级工具")
    check("重命名后语音按新名字匹配到同一个 exe",
          bool(_hit) and _hit.get("target") == "D:/Games/SuperTool.exe", str(_hit))

    _StubInput.ok, _StubInput.value = True, ""
    _perm._rename_app("超级工具")
    check("空名字视为取消（不落盘）",
          _t.get_permissions()["custom_apps"] == {"超级工具": "D:/Games/SuperTool.exe"},
          str(_t.get_permissions()["custom_apps"]))
    _StubInput.value = "超级工具"
    _perm._rename_app("超级工具")
    check("与原名相同视为取消",
          _t.get_permissions()["custom_apps"] == {"超级工具": "D:/Games/SuperTool.exe"})
    _StubInput.ok, _StubInput.value = False, "随便什么名"
    _perm._rename_app("超级工具")
    check("点取消不改动任何数据",
          _t.get_permissions()["custom_apps"] == {"超级工具": "D:/Games/SuperTool.exe"})

    _StubInput.ok, _StubInput.value = True, "cmd"
    _perm._rename_app("超级工具")
    check("重命名成默认禁止项被拒且不改数据",
          "超级工具" in _t.get_permissions()["custom_apps"] and "禁止" in _perm._msg_label.text(),
          _perm._msg_label.text())
    _StubInput.value = "记事本"
    _perm._rename_app("超级工具")
    check("重命名成内置软件名被拒（否则语音匹配会被内置表抢走）",
          "超级工具" in _t.get_permissions()["custom_apps"] and "占用" in _perm._msg_label.text(),
          _perm._msg_label.text())
    _perm._rename_app("记事本")
    check("内置软件不支持重命名", "内置" in _perm._msg_label.text(), _perm._msg_label.text())
finally:
    gui.InputDialog = _orig_input

# --- 4) 删除必须二次确认（目录 / 软件 / 禁止词共用 _remove_item）---
class _StubConfirm:
    calls, answer = [], True

    def __init__(self, *a, **k):
        pass

    @staticmethod
    def confirm(parent, message, *a, **k):
        _StubConfirm.calls.append(message)
        return _StubConfirm.answer


_orig_confirm = gui.ConfirmDialog
gui.ConfirmDialog = _StubConfirm
try:
    _StubConfirm.calls[:] = []
    _StubConfirm.answer = False
    _perm._remove_item("allowed_apps", "超级工具")
    check("取消确认时不删除软件",
          "超级工具" in _t.get_permissions()["allowed_apps"], str(_t.get_permissions()["allowed_apps"]))
    check("删除前弹确认框且文案点明对象 + 不可撤销",
          bool(_StubConfirm.calls)
          and "超级工具" in _StubConfirm.calls[-1]
          and "不可撤销" in _StubConfirm.calls[-1],
          str(_StubConfirm.calls))

    _StubConfirm.answer = True
    _perm._remove_item("allowed_apps", "超级工具")
    check("确认后才真正删除（连同 custom_apps 登记）",
          "超级工具" not in _t.get_permissions()["allowed_apps"]
          and "超级工具" not in _t.get_permissions()["custom_apps"],
          str(_t.get_permissions()))

    _d0 = _t.get_permissions()["allowed_dirs"][0]
    _StubConfirm.answer = False
    _perm._remove_item("allowed_dirs", _d0)
    check("目录删除同样要确认（取消则保留）", _d0 in _t.get_permissions()["allowed_dirs"])
    check("目录确认文案用的是「目录」",
          "删除目录" in _StubConfirm.calls[-1], _StubConfirm.calls[-1])
    _StubConfirm.answer = True
    _perm._remove_item("allowed_dirs", _d0)
    check("目录删除确认后生效", _d0 not in _t.get_permissions()["allowed_dirs"])

    _t.apply_permissions({"blocked_keywords": ["格式化"]})
    _StubConfirm.answer = False
    _perm._remove_item("blocked_keywords", "格式化")
    check("禁止词删除同样要确认（取消则保留）",
          "格式化" in _t.get_permissions()["blocked_keywords"])
    check("禁止词确认文案用的是「禁止词」",
          "删除禁止词" in _StubConfirm.calls[-1], _StubConfirm.calls[-1])
finally:
    gui.ConfirmDialog = _orig_confirm

# ========== 4h. 改动时画面不滑动（焦点 + 滚动位置搬运）==========
print("== 4h. 改动不滑动 ==")

_perm = win._settings_panels["permissions"]
win._show_settings_page(win._settings_index["permissions"])
settle()
_t.apply_permissions({
    "allowed_apps": ["记事本", "SuperTool"],
    "custom_apps": {"SuperTool": "D:/Games/SuperTool.exe"},
})
_perm._materialize()
_perm._rebuild()
settle(150)


def _row_named(name):
    for _r in _perm._body.findChildren(gui._PermRow):
        _lbl = _r.findChild(QLabel)
        if _lbl is not None and _lbl.text() == name:
            return _r
    return None


# 造出可滚动的内容（同 4a 的做法：直接给 body 一个最小高度）
_perm._body.setMinimumHeight(3000)
settle(250)
_sb2 = _perm._scroll.verticalScrollBar()
_sb2.setValue(400)
settle(150)
_base = _sb2.value()
check("前置条件：面板确实可以滚动", _sb2.maximum() > _base > 0, f"{_base}/{_sb2.maximum()}")

# 1) 行内按钮一律 NoFocus
#    点一下就拿焦点的话，重建销毁它时 Qt 会把焦点转走、滚动区随即 ensureWidgetVisible
#    去追新焦点 —— 表现就是「删一行 / 改个名，画面自己滚到别处」。
_btn_row = _row_named("SuperTool")
check("行内按钮不抢键盘焦点（删除 / 重命名都是 NoFocus）",
      _btn_row._btn.focusPolicy() == Qt.NoFocus
      and _btn_row._btn_extra.focusPolicy() == Qt.NoFocus,
      f"{_btn_row._btn.focusPolicy()}/{_btn_row._btn_extra.focusPolicy()}")

# 2) 重建把滚动位置原样搬回来
_perm._rebuild()
settle(250)
check("重建后滚动位置原样保留（不跳回顶部 / 底部）",
      _sb2.value() == min(_base, _sb2.maximum()), f"{_base} -> {_sb2.value()}")

# 3) 重建先收掉「落在待拆内容区里的焦点」
_btn_row = _row_named("SuperTool")
_btn_row._btn.setFocus()
settle(150)
_focused_inside = win.focusWidget() is not None and _perm._body.isAncestorOf(win.focusWidget())
_perm._rebuild()
settle(250)
_fw = win.focusWidget()
check("前置条件：确实把焦点放进了内容区", _focused_inside, str(_focused_inside))
check("重建会把内容区里的焦点先收掉（焦点不再落在 body 内）",
      _fw is None or not _perm._body.isAncestorOf(_fw), str(_fw))

# 4) 焦点在内容区之外时不该被波及
_perm._reset_btn.setFocus()
settle(150)
_perm._rebuild()
settle(250)
check("焦点在内容区外时不受影响（恢复默认仍持有焦点）",
      win.focusWidget() is _perm._reset_btn, str(win.focusWidget()))

# 5) 端到端：焦点在行按钮上 + 真删除 → 画面纹丝不动
class _StubConfirm2:
    answer = True

    def __init__(self, *a, **k):
        pass

    @staticmethod
    def confirm(parent, message, *a, **k):
        return _StubConfirm2.answer


_orig_confirm2 = gui.ConfirmDialog
gui.ConfirmDialog = _StubConfirm2
try:
    _sb2.setValue(_base)
    settle(150)
    _btn_row = _row_named("SuperTool")
    _btn_row._btn.setFocus()
    settle(150)
    _perm._remove_item("allowed_apps", "SuperTool")
    settle(300)
    check("删除软件后滚动位置不变（这是用户报的现象）",
          _sb2.value() == min(_base, _sb2.maximum()), f"{_base} -> {_sb2.value()}")
    check("删除确实生效（不是靠不删来\"保持不动\"）",
          "SuperTool" not in _t.get_permissions()["allowed_apps"],
          str(_t.get_permissions()["allowed_apps"]))
finally:
    gui.ConfirmDialog = _orig_confirm2

# 6) 改名的路径同理
class _StubInput2:
    value, ok = "超级工具", True

    def __init__(self, *a, **k):
        pass

    @staticmethod
    def get_text(parent, title, label, default=""):
        return _StubInput2.value, _StubInput2.ok


_orig_input2 = gui.InputDialog
gui.InputDialog = _StubInput2
try:
    _t.apply_permissions({
        "allowed_apps": ["记事本", "SuperTool"],
        "custom_apps": {"SuperTool": "D:/Games/SuperTool.exe"},
    })
    _perm._materialize()
    _perm._rebuild()
    settle(250)
    _sb2.setValue(_base)
    settle(150)
    _row_named("SuperTool")._btn_extra.setFocus()
    settle(150)
    _perm._rename_app("SuperTool")
    settle(300)
    check("重命名后滚动位置不变（这是用户报的现象）",
          _sb2.value() == min(_base, _sb2.maximum()), f"{_base} -> {_sb2.value()}")
    check("重命名确实生效", "超级工具" in _t.get_permissions()["allowed_apps"],
          str(_t.get_permissions()["allowed_apps"]))
finally:
    gui.InputDialog = _orig_input2

# 7) 分组标题行里的「添加」按钮同样在内容区内 —— 走过同一个 _clear_body
_g_add = next(g for g in _perm._body.findChildren(gui._CollapsibleGroup)
              if g._add_btn is not None)
_sb2.setValue(_base)
settle(150)
_g_add._add_btn.setFocus()
settle(150)
_perm._commit("已添加目录「x」。")
settle(300)
check("走分组「添加」按钮触发的重建也不滑动",
      _sb2.value() == min(_base, _sb2.maximum()), f"{_base} -> {_sb2.value()}")

# 8) 页面切换仍然回到顶端（滚动搬运不能把它破坏掉）
win._show_settings_page(win._settings_index["general"])
settle(250)
win._show_settings_page(win._settings_index["permissions"])
settle(350)
check("切走再回来仍回到顶端（滚动搬运没有破坏它）", _sb2.value() == 0, str(_sb2.value()))

# 复原现场
_perm._body.setMinimumHeight(0)
_t.apply_permissions({})
_perm._materialize()
_perm.reset_groups()
_perm._rebuild()
settle(200)


# ========== 5. 通用设置面板 ==========
print("== 5. 通用设置 ==")
gen = win._settings_panels["general"]
# ★★前提：本节只测「设置行自己的行为」，所以必须把面板置于「**模型已就位**」的前提上。
#   `GeneralPanel._apply_model_state()` 在**没有模型**时会把静音滑块**锁死在「开」**
#   （`docs/01` F7：没有模型就一声都出不来，还留着可关只会让人以为软件坏了）⇒ 那会让下面
#   几条「点滑块开 / 再点一下关」因为**滑块被锁住、点不动**而假红。
#   ★2026-09-27 本机把语音模型卸载之后正是这个情形 —— 那是**环境依赖**，不是回归。
#   把 `voice_model.is_installed` 换成桩，本节就与「硬盘上有没有那 1.15 GB」彻底解耦。
#   （「没有模型 ⇒ 静音锁死在开」由 §5g 与启动门禁两处专门覆盖，不是漏测。）
import app.voice_model as _vm5  # noqa: E402
_orig_installed_s5 = _vm5.is_installed
_vm5.is_installed = lambda cfg: True
cfg["general"]["mute_mode"] = False          # 回到配置默认（关）
gen.refresh()
check("通用设置面板类型", isinstance(gen, gui.GeneralPanel))
kinds = []
for i in range(gen._body_lay.count()):
    w = gen._body_lay.itemAt(i).widget()
    if w is not None:
        kinds.append(type(w).__name__)
check("含「开机自启」开关行", "_SettingToggleRow" in kinds, str(kinds))
check("含「关闭行为」选项行", "_SettingChoiceRow" in kinds, str(kinds))

# ---- 关闭行为：胶囊按钮 → 圆环型单选（2026-09-18 用户口径）----
_row_choice = next(w for w in gen.findChildren(gui._SettingChoiceRow))
check("右侧是两个 _RadioItem，值仍是 tray / quit，且不再有胶囊按钮",
      list(_row_choice._items) == ["tray", "quit"]
      and _row_choice.findChildren(QPushButton) == [],
      str(list(_row_choice._items)))
check("圆环尺寸 18×18，外层控件不吃鼠标事件（点击由整块接管）",
      all(it._dot.width() == it._dot.height() == gui._RadioDot.DOT == 18
          and it._dot.testAttribute(Qt.WA_TransparentForMouseEvents)
          for it in _row_choice._items.values()),
      str([it._dot.size().toTuple() for it in _row_choice._items.values()]))
check("圆环规格（2026-09-18）：边框粗细 1px、内圈外径 7px（内圈半径 3.5px）",
      gui._RadioDot.BORDER == 1 and gui._RadioDot.INNER == 7,
      f"border={gui._RadioDot.BORDER} inner={gui._RadioDot.INNER}")
check("文字也不吃鼠标事件（点文字等同点圆环）",
      all(it._lbl.testAttribute(Qt.WA_TransparentForMouseEvents)
          for it in _row_choice._items.values()))


def _dot_colors(dot):
    img = dot.grab().toImage()
    return {img.pixelColor(x, y).name().lower()
            for x in range(img.width()) for y in range(img.height())}, img


def _ink_radii(img):
    """与 `#0C447C` 足够接近的像素到圆心的距离（用来验「有两层深蓝描边」）。

    1px 边框 + 抗锯齿之后，dpr=1 的画布上**找不到一个纯度 100% 的 #0C447C 像素**
    （实测最接近的是色距 2.45 的 #0D427B —— 1.5px 时代恰好有一个被完全覆盖的像素，
    所以老断言能用等值），所以深蓝一律按"足够接近"判定；填充的蓝环不受影响，仍是精确的 #378ADD。
    """
    def _dist(name):
        a = [int(name[1:3], 16), int(name[3:5], 16), int(name[5:7], 16)]
        z = [int(gui._RadioDot.INK[1:3], 16), int(gui._RadioDot.INK[3:5], 16),
             int(gui._RadioDot.INK[5:7], 16)]
        return sum((p - q) ** 2 for p, q in zip(a, z)) ** 0.5

    cx, cy = img.width() / 2, img.height() / 2
    return [((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
            for x in range(img.width()) for y in range(img.height())
            if _dist(img.pixelColor(x, y).name().lower()) <= 60]


_on_cols, _on_img = _dot_colors(_row_choice._items["tray"]._dot)
_off_cols, _off_img = _dot_colors(_row_choice._items["quit"]._dot)
_on_radii = _ink_radii(_on_img)
_on_inner = [r for r in _on_radii if r < 5.0]      # 内圈：外径 7px ⇒ 描边中心半径 ≈3.5px
_on_outer = [r for r in _on_radii if r > 7.5]      # 外圈：外径 18px ⇒ 描边中心半径 ≈9px
check("选中态（tray）：外圈 / 内圈**两层**深蓝描边都在（内层 ≈3.5px、外层 ≈9px）",
      len(_on_radii) >= 20 and len(_on_inner) >= 6 and len(_on_outer) >= 20
      and 2.5 <= min(_on_inner) < 5.0 and max(_on_outer) > 8.0,
      f"n={len(_on_radii)} inner={len(_on_inner)} outer={len(_on_outer)} "
      f"min_inner={min(_on_inner) if _on_inner else None} "
      f"max_outer={max(_on_outer) if _on_outer else None}")
check("选中态：两条边框之间是蓝色圆环 #378ADD（整片填充，仍是精确值）",
      gui._RadioDot.RING.lower() in _on_cols, sorted(_on_cols)[:6])
check("选中态：圆心留白（白色）",
      _on_img.pixelColor(_on_img.width() // 2, _on_img.height() // 2).name().lower() == "#ffffff",
      _on_img.pixelColor(_on_img.width() // 2, _on_img.height() // 2).name())
check("未选中态（quit）：**只画最外层边框** —— 既没有蓝环、也没有内圈深蓝",
      gui._RadioDot.RING.lower() not in _off_cols
      and gui._RadioDot.INK.lower() not in _off_cols, sorted(_off_cols)[:6])

# 变色必须是**淡入淡出**（2026-09-18 用户口径），不是瞬间跳变
check("变色动画规格：500ms / OutCubic",
      gui._RadioDot.FADE_MS == 500
      and _row_choice._items["tray"]._dot._anim.duration() == 500
      and _row_choice._items["tray"]._dot._anim.easingCurve().type() == gui.QEasingCurve.OutCubic,
      f"{gui._RadioDot.FADE_MS}/{_row_choice._items['tray']._dot._anim.duration()}")
_dot_a = gui._RadioDot(True)
_dot_b = gui._RadioDot(False)
check("点火后进度从终态出发（选中 1.0 / 未选中 0.0）",
      _dot_a._t == 1.0 and _dot_b._t == 0.0, f"{_dot_a._t}/{_dot_b._t}")
_dot_a.setChecked(False)
_dot_b.setChecked(True)
check("切换的瞬间 isChecked 立刻是对的（不等等动画）",
      _dot_a.isChecked() is False and _dot_b.isChecked() is True)
QTest.qWait(150)                      # 500ms 的动画只跑到中段
check("中段：两个圆环的着色进度都在 0~1 之间（确实是逐帧渐变而非瞬变）",
      0.0 < _dot_a._t < 1.0 and 0.0 < _dot_b._t < 1.0,
      f"{_dot_a._t:.2f}/{_dot_b._t:.2f}")
QTest.qWait(700)                      # 补足 500ms，让动画落终态
check("动画结束：进度精确落到 0 / 1",
      _dot_a._t == 0.0 and _dot_b._t == 1.0, f"{_dot_a._t}/{_dot_b._t}")
_dot_c = gui._RadioDot(False)
_dot_c.setChecked(True, animate=False)
check("animate=False 直接落终态（构建期用，省一次无谓动画）",
      _dot_c._t == 1.0 and _dot_c.isChecked(), str(_dot_c._t))
_dot_c.setChecked(False, animate=False)
check("animate=False 取消选中同样是瞬时（进度直接回 0）",
      _dot_c._t == 0.0 and not _dot_c.isChecked(), str(_dot_c._t))

_clicks_choice = []
_old_pick_choice = _row_choice._on_pick
_row_choice._on_pick = _clicks_choice.append
QTest.mouseClick(_row_choice._items["quit"], Qt.LeftButton)
check("点「关闭软件」→ 回调收到 quit，选中态跟着切过去（单选互斥）",
      _clicks_choice == ["quit"] and _row_choice._items["quit"].isChecked()
      and not _row_choice._items["tray"].isChecked(), str(_clicks_choice))
QTest.mouseClick(_row_choice._items["tray"], Qt.LeftButton)
check("点「最小化到托盘」→ 切回来（同一时刻只有一个选中）",
      _clicks_choice == ["quit", "tray"] and _row_choice._items["tray"].isChecked()
      and not _row_choice._items["quit"].isChecked(), str(_clicks_choice))
check("行的当前值一路跟着走（set_current 真的改了 _current）",
      _row_choice._current == "tray", str(_row_choice._current))
_row_choice._on_pick = _old_pick_choice

# ---- 通用设置里的说明小字全删（2026-09-18 用户口径：灰字堆着又挤又乱）----
_gray_lbs = [lb.text() for lb in gen.findChildren(QLabel)
             if lb.text().strip() and "#64748B" in (lb.styleSheet() or "") and lb.isVisible()]
check("通用设置里**没有任何可见的灰色说明小字**（标题下 / 分组下 / 每行里都没有）",
      _gray_lbs == [], str(_gray_lbs))
_rows_all = ([gen._autostart_row, gen._mute_row, gen._patpat_row, gen._lock_row,
              gen._reset_pos_row]
             + [w for w in gen.findChildren(gui._SettingChoiceRow)])
check("五条设置行的说明都是空串、且那一行 `setVisible(False)` 不占位",
      all(r._hint_text == "" and not r._hint.isVisible() for r in _rows_all),
      str([(r._title_text, r._hint_text, r._hint.isVisible()) for r in _rows_all]))
check("去掉说明后行高仍是 58px（不缩水、也不额外加高）",
      all(r.height() == 58 for r in _rows_all), str([r.height() for r in _rows_all]))
_hdr_lbls = [gen._body_lay.itemAt(i).layout().itemAt(0).widget().text()
             for i in range(gen._body_lay.count())
             if gen._body_lay.itemAt(i).layout() is not None]
check("分组标题只剩名字本身（启动 / 语音模型 / 模式切换 / 关闭行为 / 桌宠调整），后面不再跟一行说明",
      _hdr_lbls == ["启动", "语音模型", "模式切换", "关闭行为", "桌宠调整"], str(_hdr_lbls))

gen._set_close_action("quit")
check("close_action 写入内存配置", cfg["general"]["close_action"] == "quit", str(cfg.get("general")))
check("close_action 已持久化", json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"]["close_action"] == "quit")
gen._set_close_action("tray")
check("close_action 可改回 tray",
      json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"]["close_action"] == "tray")

# ---- 静音模式行：同款圆形滑块；点击后改内存 cfg + **落盘**（2026-09-29「重开保留」）----
row_mute = getattr(gen, "_mute_row", None)
check("通用设置含「静音模式」开关行", isinstance(row_mute, gui._SettingToggleRow))
sw_mute = row_mute._switch if row_mute is not None else None
check("静音模式行右侧是圆形滑块 _ToggleSwitch（不是 QPushButton）",
      isinstance(sw_mute, gui._ToggleSwitch) and row_mute.findChildren(QPushButton) == [],
      type(sw_mute).__name__ if sw_mute is not None else "None")
check("静音模式滑块尺寸 = 44x24",
      (sw_mute.width(), sw_mute.height()) == (44, 24), f"{sw_mute.width()}x{sw_mute.height()}")
check("静音模式滑块初始状态 == 配置值（默认关）",
      row_mute.is_enabled() is False and cfg["general"]["mute_mode"] is False,
      f"{row_mute.is_enabled()}/{cfg['general']['mute_mode']}")

QTest.mouseClick(sw_mute, Qt.LeftButton)
check("点击后开启：内存 cfg 立刻是 True",
      cfg["general"]["mute_mode"] is True, str(cfg["general"]))
check("★★开启后**写盘**了（config.json 里出现 mute_mode=True —— 2026-09-29 用户口径）",
      json.loads(tmp_cfg.read_text(encoding="utf-8")).get("general", {}).get("mute_mode") is True,
      str(json.loads(tmp_cfg.read_text(encoding="utf-8")).get("general")))
check("开启后滑块停在「开」", row_mute.is_enabled() is True and sw_mute.isChecked() is True)
check("开启后行内**不再**挂说明小字（「没有声音 / 重启后自动关闭」这些改由开场提示去说）",
      row_mute._hint_text == "" and not row_mute._hint.isVisible(),
      f"{row_mute._hint_text!r} / visible={row_mute._hint.isVisible()}")
check("滑块没被整页重建销毁（同一实例仍在用）", gen._mute_row is row_mute)

QTest.mouseClick(sw_mute, Qt.LeftButton)
check("★再点一次关闭（内存回 False **且磁盘同步写成 False** —— 每次切换都落一次盘）",
      row_mute.is_enabled() is False and cfg["general"]["mute_mode"] is False
      and json.loads(tmp_cfg.read_text(encoding="utf-8")).get("general", {}).get("mute_mode") is False,
      str(cfg["general"]))
check("关闭后行内同样没有说明小字（开关只看滑块）",
      row_mute._hint_text == "", repr(row_mute._hint_text))

# ---- 设置页切静音 → 通知主程序（实跑一遍：回调**只**负责弹提示，别重复落 cfg）----
_mute_calls = []
win.set_mute_mode_cb(lambda on: _mute_calls.append(bool(on)))
check("刚注册时回调一次都没跑（注册 ≠ 触发）", _mute_calls == [], str(_mute_calls))
QTest.mouseClick(sw_mute, Qt.LeftButton)
check("点滑块开：主程序收到 True，且只收到一次", _mute_calls == [True], str(_mute_calls))
check("★回调不影响设置页自己的落地（内存 cfg=True、磁盘也是 True —— 落盘由设置页那条路负责）",
      cfg["general"]["mute_mode"] is True
      and json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"].get("mute_mode") is True)
QTest.mouseClick(sw_mute, Qt.LeftButton)
check("再点一下关：主程序收到 False（顺序也对）", _mute_calls == [True, False], str(_mute_calls))
check("★关回来之后磁盘也同步成 False（不留残值 —— 否则下次启动会莫名是「开」）",
      json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"].get("mute_mode") is False,
      str(json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"]))
win.set_mute_mode_cb(None)
QTest.mouseClick(sw_mute, Qt.LeftButton)
check("没接回调（None）时点滑块照样能用、不报错",
      cfg["general"]["mute_mode"] is True and _mute_calls == [True, False], str(_mute_calls))
QTest.mouseClick(sw_mute, Qt.LeftButton)
check("收尾：拨回「关」，后面的用例接着用", cfg["general"]["mute_mode"] is False and sw_mute.isChecked() is False)
# 本节前提用完了 ⇒ 还原成**真实**安装态（本机没有模型 ⇒ 静音锁死在「开」），别把桩留给后面几节
_vm5.is_installed = _orig_installed_s5
gen._apply_model_state()

# ---- 静音模式的**语音**开关：词表互斥 + 必须早于 detect_action ----
import app.main as _main  # noqa: E402

check("静音词表非空（开 / 关各一组说法）",
      bool(_main.MUTE_ON_WORDS) and bool(_main.MUTE_OFF_WORDS))
_overlap = [(a, b) for a in _main.MUTE_ON_WORDS for b in _main.MUTE_OFF_WORDS
            if (a in b) or (b in a)]
check("「开」与「关」两组说法互不包含（否则同一句话会切到相反状态）",
      not _overlap, str(_overlap[:3]))
check("「开启静音模式」命中开、「关闭静音模式」命中关",
      any(w in "开启静音模式" for w in _main.MUTE_ON_WORDS)
      and any(w in "关闭静音模式" for w in _main.MUTE_OFF_WORDS))
check("光说「静音」不算开关（闲聊里不该被误切）",
      not any(w in "静音" for w in _main.MUTE_ON_WORDS + _main.MUTE_OFF_WORDS))
_mute_all = _main.MUTE_ON_WORDS + _main.MUTE_OFF_WORDS
check("静音说法不与休眠词撞车（「开启静音模式」不应让角色去睡觉）",
      not any((w in o) or (o in w) for w in _mute_all for o in _main.SLEEP_WORDS),
      str([(w, o) for w in _mute_all for o in _main.SLEEP_WORDS if (w in o) or (o in w)][:3]))
# 「取消静音」里含「取消」是有意的（那是自然的说法）；因为静音拦截排在**最前面**，
# 所以它只会切静音、不会被当成危险操作撤销。这里钉住真正的底线：光说「取消」不能变成静音开关。
check("光说「取消」仍是危险操作的撤销词，不会被当成静音开关",
      "取消" not in _mute_all, str([w for w in _mute_all if w == "取消"]))
_src_main = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
_oc = _src_main[_src_main.index("def on_command"):]
check("语音开关写在 detect_action **之前**"
      "（否则「打开静音模式」会被当成打开某样东西 → 本地搜索 → Bing 搜索）",
      _oc.index("in clean_cmd for w in MUTE_ON_WORDS") < _oc.index("detect_action(text)"),
      f"{_oc.index('in clean_cmd for w in MUTE_ON_WORDS')} "
      f"vs {_oc.index('detect_action(text)')}")

# ---- 语音切了静音模式，设置页那一行要跟着动（只同步这一行，不整页重建）----
win.sync_mute_mode(True)
check("sync_mute_mode(True)：设置页滑块拨到「开」",
      gen._mute_row.is_enabled() is True and gen._mute_row._switch.isChecked() is True,
      f"{gen._mute_row.is_enabled()} / {gen._mute_row._switch.isChecked()}")
win.sync_mute_mode(False)
check("sync_mute_mode(False)：拨回「关」",
      gen._mute_row.is_enabled() is False and gen._mute_row._switch.isChecked() is False,
      f"{gen._mute_row.is_enabled()} / {gen._mute_row._switch.isChecked()}")
check("sync_mute_mode 不整页重建面板（同一个行实例还在用）", gen._mute_row is row_mute)

# ---- patpat 模式行（2026-09-20）：与静音模式同款 —— 圆形滑块、纯运行时、只同步这一行 ----
row_pp = getattr(gen, "_patpat_row", None)
check("通用设置 → 模式切换 里含「patpat模式」开关行", isinstance(row_pp, gui._SettingToggleRow))
sw_pp = row_pp._switch if row_pp is not None else None
check("patpat 模式行右侧也是圆形滑块 _ToggleSwitch（不是 QPushButton）",
      isinstance(sw_pp, gui._ToggleSwitch) and row_pp.findChildren(QPushButton) == [],
      type(sw_pp).__name__ if sw_pp is not None else "None")
check("patpat 模式滑块尺寸 = 44x24", (sw_pp.width(), sw_pp.height()) == (44, 24),
      f"{sw_pp.width()}x{sw_pp.height()}")
check("patpat 模式滑块初始状态 == 配置值（默认关）",
      row_pp.is_enabled() is False and cfg["general"]["patpat_mode"] is False,
      f"{row_pp.is_enabled()}/{cfg['general']['patpat_mode']}")
check("「模式切换」组里现在是**两行**（静音模式 + patpat模式，都是纯运行时开关、都要能直接打开）",
      isinstance(gen._mute_row, gui._SettingToggleRow)
      and isinstance(gen._patpat_row, gui._SettingToggleRow)
      and gen._mute_row is not gen._patpat_row)

_gen_pp_before = json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"]
QTest.mouseClick(sw_pp, Qt.LeftButton)
check("点击后开启：内存 cfg 立刻是 True、滑块停在「开」",
      cfg["general"]["patpat_mode"] is True and row_pp.is_enabled() is True
      and sw_pp.isChecked() is True, str(cfg["general"]))
check("开启后**不写盘**（config.json 里不出现 patpat_mode）",
      "patpat_mode" not in json.loads(tmp_cfg.read_text(encoding="utf-8")).get("general", {}),
      str(json.loads(tmp_cfg.read_text(encoding="utf-8")).get("general")))

# 设置页切 patpat → 通知主程序（**状态在桌宠那边**，回调负责 `pet.set_patpat()`）
_pp_calls = []
win.set_patpat_mode_cb(lambda on: _pp_calls.append(bool(on)))
check("刚注册时回调一次都没跑（注册 ≠ 触发）", _pp_calls == [], str(_pp_calls))
QTest.mouseClick(sw_pp, Qt.LeftButton)
check("点滑块关：主程序收到 False，且只收到一次", _pp_calls == [False], str(_pp_calls))
QTest.mouseClick(sw_pp, Qt.LeftButton)
check("再点一下开：主程序收到 True（顺序也对）", _pp_calls == [False, True], str(_pp_calls))
check("整个来回里回调没偷偷改配置（磁盘 general 段没变，且始终没有 patpat_mode）",
      json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"] == _gen_pp_before,
      str(json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"]))
win.set_patpat_mode_cb(None)
QTest.mouseClick(sw_pp, Qt.LeftButton)
check("没接回调（None）时点滑块照样能用、不报错",
      cfg["general"]["patpat_mode"] is False and _pp_calls == [False, True], str(_pp_calls))

# 从右键菜单切了以后，设置页这一行要跟着动（只同步这一行，不整页重建）
win.sync_patpat_mode(True)
check("sync_patpat_mode(True)：设置页滑块拨到「开」",
      gen._patpat_row.is_enabled() is True and gen._patpat_row._switch.isChecked() is True,
      f"{gen._patpat_row.is_enabled()} / {gen._patpat_row._switch.isChecked()}")
win.sync_patpat_mode(False)
check("sync_patpat_mode(False)：拨回「关」；且不整页重建面板（同一个行实例还在用）",
      gen._patpat_row.is_enabled() is False and gen._patpat_row._switch.isChecked() is False
      and gen._patpat_row is row_pp,
      f"{gen._patpat_row.is_enabled()} / {gen._patpat_row._switch.isChecked()}")

# ---- 桌宠固定行（2026-09-22）：滑块在「桌宠调整」组；★★与上面两行**关键区别 = 要落盘** ----
row_lk = getattr(gen, "_lock_row", None)
check("通用设置 → 桌宠调整 里含「桌宠固定」开关行", isinstance(row_lk, gui._SettingToggleRow))
sw_lk = row_lk._switch if row_lk is not None else None
check("桌宠固定行右侧也是圆形滑块 _ToggleSwitch（不是 QPushButton）",
      isinstance(sw_lk, gui._ToggleSwitch) and row_lk.findChildren(QPushButton) == [],
      type(sw_lk).__name__ if sw_lk is not None else "None")
check("桌宠固定滑块尺寸 = 44x24", (sw_lk.width(), sw_lk.height()) == (44, 24),
      f"{sw_lk.width()}x{sw_lk.height()}")
check("★桌宠固定滑块初始状态 == 配置值（默认**开** ＝ 固定，用户口径「默认打开固定」）",
      row_lk.is_enabled() is True and cfg["general"]["lock_pet"] is True,
      f"{row_lk.is_enabled()}/{cfg['general']['lock_pet']}")
check("「桌宠调整」组里现在是三行（桌宠固定 / 音量 / 重置角色位置）",
      isinstance(gen._lock_row, gui._SettingToggleRow)
      and isinstance(gen._volume_row, gui._SettingVolumeRow)
      and isinstance(gen._reset_pos_row, gui._SettingActionRow))

_lk_calls = []
win.set_pet_lock_cb(lambda on: _lk_calls.append(bool(on)))
check("刚注册时回调一次都没跑（注册 ≠ 触发）", _lk_calls == [], str(_lk_calls))
QTest.mouseClick(sw_lk, Qt.LeftButton)
check("点滑块关：内存 cfg 立刻 False、主程序收到一次 False",
      cfg["general"]["lock_pet"] is False and _lk_calls == [False],
      f"{cfg['general']['lock_pet']} / {_lk_calls}")
check("★★与静音 / patpat **相反**：这一项要**落盘** —— config.json 的 general 里出现 lock_pet=False",
      json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"].get("lock_pet") is False,
      str(json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"]))
win.set_pet_lock_cb(None)
QTest.mouseClick(sw_lk, Qt.LeftButton)
check("没接回调（None）时点滑块照样能用、不报错",
      cfg["general"]["lock_pet"] is True and _lk_calls == [False],
      f"{cfg['general']['lock_pet']} / {_lk_calls}")

win.sync_pet_lock(False)
check("sync_pet_lock(False)：设置页滑块拨到「关」",
      gen._lock_row.is_enabled() is False and gen._lock_row._switch.isChecked() is False,
      f"{gen._lock_row.is_enabled()} / {gen._lock_row._switch.isChecked()}")
win.sync_pet_lock(True)
check("sync_pet_lock(True)：拨回「开」；且不整页重建面板（同一个行实例还在用）",
      gen._lock_row.is_enabled() is True and gen._lock_row._switch.isChecked() is True
      and gen._lock_row is row_lk,
      f"{gen._lock_row.is_enabled()} / {gen._lock_row._switch.isChecked()}")

# ---- 开机自启行：右侧必须是「圆形滑块」，不是文字按钮 ----
row0 = getattr(gen, "_autostart_row", None)
check("开机自启行是 _SettingToggleRow", isinstance(row0, gui._SettingToggleRow))
sw0 = row0._switch if row0 is not None else None
check("自启行右侧是圆形滑块 _ToggleSwitch（不是 QPushButton）",
      isinstance(sw0, gui._ToggleSwitch) and row0.findChildren(QPushButton) == [],
      type(sw0).__name__ if sw0 is not None else "None")
check("滑块初始状态 == 注册表实际状态",
      bool(sw0.isChecked()) == autostart.is_enabled(),
      f"{sw0.isChecked()} vs {autostart.is_enabled()}")
check("滑块尺寸 = 44x24", (sw0.width(), sw0.height()) == (44, 24), f"{sw0.width()}x{sw0.height()}")

# ---- 点击滑块：写注册表 → 只同步这一行（不整页重建）；写失败必须回弹 ----
# 全程用假的 autostart 函数，**绝不触碰真实注册表启动项**
_real_as = (autostart.is_enabled, autostart.enable, autostart.disable, autostart.current_command)
_fake = {"on": False}
try:
    autostart.is_enabled = lambda: _fake["on"]
    autostart.enable = lambda: (_fake.__setitem__("on", True), (True, "已设置开机自启。"))[1]
    autostart.disable = lambda: (_fake.__setitem__("on", False), (True, "已关闭开机自启。"))[1]
    autostart.current_command = lambda: ('"C:\\fake\\pythonw.exe" "C:\\fake\\run.py"' if _fake["on"] else "")

    gen.refresh()
    row = gen._autostart_row
    check("假注册表：滑块初始为关", row.is_enabled() is False and row._switch.isChecked() is False)
    sw = row._switch

    QTest.mouseClick(sw, Qt.LeftButton)          # 真点击：press 里滑块自行切换 + emit
    check("点击后开启：cfg.auto_start 已持久化",
          cfg["general"]["auto_start"] is True
          and json.loads(tmp_cfg.read_text(encoding="utf-8"))["general"]["auto_start"] is True,
          str(cfg["general"]))
    check("点击后滑块停在「开」，行内记录同步",
          row.is_enabled() is True and sw.isChecked() is True, f"{row.is_enabled()}/{sw.isChecked()}")
    check("开启后**不再**写「登录 Windows 后自动启动（命令）」那种说明小字",
          row._hint_text == "" and not row._hint.isVisible(), repr(row._hint_text))
    check("滑块没被整页重建销毁（同一实例仍在用）", gen._autostart_row is row)

    QTest.mouseClick(sw, Qt.LeftButton)
    check("再点一次关闭并回拨",
          row.is_enabled() is False and cfg["general"]["auto_start"] is False, str(cfg["general"]))
    check("关闭后同样没有说明小字（挂 / 摘都只看滑块）", row._hint_text == "", repr(row._hint_text))

    # 写失败：滑块已经先切了视觉状态，必须按真实状态回弹
    autostart.enable = lambda: (False, "设置失败：模拟")
    autostart.is_enabled = lambda: False
    gen.refresh()
    row_fail = gen._autostart_row
    QTest.mouseClick(row_fail._switch, Qt.LeftButton)
    check("写失败时滑块回弹为「关」",
          row_fail.is_enabled() is False and row_fail._switch.isChecked() is False,
          f"{row_fail.is_enabled()}/{row_fail._switch.isChecked()}")
    check("写失败时 cfg.auto_start 不被写脏", cfg["general"]["auto_start"] is False)
finally:
    (autostart.is_enabled, autostart.enable,
     autostart.disable, autostart.current_command) = _real_as
    gen.refresh()
check("自启假函数已复原（真实状态可读）", isinstance(autostart.is_enabled(), bool))

# 反复重建不应报错（验证 _clear_body 对分组子布局的清理）
for _ in range(3):
    gen.refresh()
check("连续 refresh 3 次不报错", True)


# ---- 「桌宠」分组：重置角色位置（动作行；真正落位由 main.py 注入）----
print("== 5b. 通用设置·桌宠：重置角色位置 ==")
gen.refresh()


def _body_group_names(lay):
    """滚动区里的分组小标题（它们排在 _group_header 造的那个横向子布局里）。"""
    names = []
    for _i in range(lay.count()):
        _h = lay.itemAt(_i).layout()
        if _h is not None and _h.count() and isinstance(_h.itemAt(0).widget(), QLabel):
            names.append(_h.itemAt(0).widget().text())
    return names


check("分组依次是 启动 / 语音模型 / 模式切换 / 关闭行为 / 桌宠调整（前两轮改名；2026-09-22 增「语音模型」）",
      _body_group_names(gen._body_lay) == ["启动", "语音模型", "模式切换", "关闭行为", "桌宠调整"],
      str(_body_group_names(gen._body_lay)))
row_reset = getattr(gen, "_reset_pos_row", None)
check("通用设置里有「重置角色位置」动作行", isinstance(row_reset, gui._SettingActionRow))
check("动作行继承设置行基类（58px 高 / 圆角 10 / 边框）",
      isinstance(row_reset, gui._SettingRow) and row_reset.height() == 58,
      str(row_reset.height() if row_reset is not None else None))
check("行标题在、说明已删（只剩标题时垂直居中）",
      row_reset._title_text == "重置角色位置" and row_reset._hint_text == ""
      and not row_reset._hint.isVisible(),
      f"{row_reset._title_text} / {row_reset._hint_text!r}")
_btn_reset = getattr(row_reset, "_button", None)
check("右侧是蓝色镂空按钮（#outlineBtn、高 28px、文案「重置位置」）",
      isinstance(_btn_reset, QPushButton) and _btn_reset.objectName() == "outlineBtn"
      and _btn_reset.height() == 28 and _btn_reset.text() == "重置位置",
      f"{_btn_reset.objectName()}/{_btn_reset.height()}/{_btn_reset.text()}")
check("按钮是手型光标", _btn_reset.cursor().shape() == Qt.PointingHandCursor)
check("动作行右侧是按钮，没有滑块（它没有状态）",
      row_reset.findChildren(gui._ToggleSwitch) == [])
check("动作行本体不含任何可切换状态（is_enabled 之类都没有）",
      not hasattr(row_reset, "is_enabled"))

_calls_reset = []
check("主窗口提供 set_reset_pet_pos 注入点（桌宠不归设置面板管）",
      hasattr(win, "set_reset_pet_pos"))
win.set_reset_pet_pos(lambda: _calls_reset.append(1))
check("还没人点过时：动作没跑", _calls_reset == [])
check("reset_pet_pos() 真的会跑注入的动作", win.reset_pet_pos() is True and _calls_reset == [1])
QTest.mouseClick(_btn_reset, Qt.LeftButton)
check("点按钮 → 走的就是主窗口注入的那条动作", _calls_reset == [1, 1], str(_calls_reset))
check("点完在面板底部给出反馈（与其他设置行一致）",
      "默认位置" in gen._msg_label.text(), gen._msg_label.text())
check("重置是**一次性动作**：没有动画在跑（不是翻转那种平移）",
      not hasattr(row_reset, "_anim"))
_old_cb = win._reset_pet_pos_cb
win._reset_pet_pos_cb = None
check("main.py 还没接上时：不报错、返回 False（按钮依然点得动）",
      win.reset_pet_pos() is False)
win._reset_pet_pos_cb = _old_cb
QTest.mouseClick(_btn_reset, Qt.LeftButton)
check("接回来后继续可用", _calls_reset == [1, 1, 1], str(_calls_reset))

# ---- 默认位置：主屏可用区右下角；启动落位与「重置」共用这一处计算 ----
print("== 5c. 桌宠默认位置 ==")
_probe_pos = QWidget()
_probe_pos.resize(150, 250)
_geo = app.primaryScreen().availableGeometry()
check("pet_default_pos() = 主屏可用区右下角（右留 MARGIN_RIGHT、下留 MARGIN_BOTTOM）",
      _main.pet_default_pos(_probe_pos) == (_geo.x() + _geo.width() - 150 - _main.MARGIN_RIGHT,
                                           _geo.y() + _geo.height() - 250 - _main.MARGIN_BOTTOM),
      str(_main.pet_default_pos(_probe_pos)))
_probe_ps = QWidget()
_probe_ps.resize(150, 100)
check("按**当前**贴图尺寸算（节能形态更矮 → 默认位置随之降低）",
      _main.pet_default_pos(_probe_ps)[1] == _geo.y() + _geo.height() - 100 - _main.MARGIN_BOTTOM,
      str(_main.pet_default_pos(_probe_ps)))
_src_reset = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
check("启动落位与「重置角色位置」共用同一个 pet_default_pos（不各写一份）",
      _src_reset.count("pet.move(*pet_default_pos(pet))") == 2,
      str(_src_reset.count("pet.move(*pet_default_pos(pet))")))
_boot = _src_reset[_src_reset.index("# 先显示窗口和桌宠"):
                 _src_reset.index("pet.show()")]
check("main.py 启动落位改调 pet_default_pos，不再自己算右下角",
      "pet.move(*pet_default_pos(pet))" in _boot and "availableGeometry" not in _boot,
      _boot)
check("main.py 把重置动作注入主窗口",
      "win.set_reset_pet_pos(reset_pet_pos)" in _src_reset)
check("重置走的是**直接落位**（reset_pet_pos 里没有任何动画）",
      "def reset_pet_pos():" in _src_reset
      and "Animation" not in _src_reset[_src_reset.index("def reset_pet_pos():"):
                                        _src_reset.index("win.set_reset_pet_pos")],
      _src_reset[_src_reset.index("def reset_pet_pos():"):
                 _src_reset.index("win.set_reset_pet_pos")][:120])


# ========== 5d. 通用设置·桌宠调整·音量（2026-09-19）==========
print("== 5d. 通用设置·音量行 ==")
from PySide6.QtCore import QEasingCurve, QSize, QVariantAnimation  # noqa: E402

gen.refresh()
row_vol = getattr(gen, "_volume_row", None)
check("通用设置里有「音量」行", isinstance(row_vol, gui._SettingVolumeRow))
check("它继承设置行基类（高 58px / 与别的行同一副长相）",
      isinstance(row_vol, gui._SettingRow) and row_vol.height() == 58,
      str(row_vol.height() if row_vol is not None else None))
check("左侧文字**只有「音量」二字**、没有说明小字",
      row_vol._title_text == "音量" and row_vol._hint_text == ""
      and not row_vol._hint.isVisible(),
      f"{row_vol._title_text} / {row_vol._hint_text!r}")

_groups_vol = _body_group_names(gen._body_lay)
check("分组名没被这一轮改动（启动 / 语音模型 / 模式切换 / 关闭行为 / 桌宠调整）",
      _groups_vol == ["启动", "语音模型", "模式切换", "关闭行为", "桌宠调整"], str(_groups_vol))
_idx_vol = gen._body_lay.indexOf(row_vol)
_idx_reset = gen._body_lay.indexOf(gen._reset_pos_row)
check("音量排在「重置角色位置」**之上**（常驻设置在前、一次性动作在后）",
      0 <= _idx_vol < _idx_reset, f"{_idx_vol} vs {_idx_reset}")

# ---- 右侧是 [−] ──── [+] ----
check("右侧是音量条 + 左右两颗圆形微调按钮（− / +）",
      isinstance(row_vol._minus, gui.VolumeStepButton)
      and isinstance(row_vol._slider, gui.VolumeSlider)
      and isinstance(row_vol._plus, gui.VolumeStepButton)
      and row_vol._minus.sign == -1 and row_vol._plus.sign == 1,
      f"{type(row_vol._minus).__name__} / {type(row_vol._slider).__name__}"
      f" / {type(row_vol._plus).__name__}")
check("两颗按钮都是 22×22 的正圆（setFixedSize 钉死，不会被行高挤扁）",
      row_vol._minus.size() == row_vol._plus.size() == QSize(22, 22),
      f"{row_vol._minus.size()} / {row_vol._plus.size()}")
check("音量条宽 138、高 22（高与桌宠那条同高；宽是「整组 90%」换算出来的）",
      (row_vol._slider.width(), row_vol._slider.height()) == (138, 22),
      f"{row_vol._slider.width()}x{row_vol._slider.height()}")
check("**整组宽度 = 原来的 90%**：22+8+138+8+22 = 198px（原来是 220px）",
      row_vol._slider.parent().sizeHint().width() == 198
      == 22 + 8 + row_vol._slider.width() + 8 + 22
      and row_vol.SLIDER_W == 138,
      f"{row_vol._slider.parent().sizeHint().width()} / SLIDER_W={row_vol.SLIDER_W}")
gen._body_lay.activate()      # 这一页此刻不是当前页、布局没激活过：几何断言前先跑一遍
row_vol._row.activate()
row_vol._slider.parent().layout().activate()
check("控件顺序：− 在音量条左边、+ 在右边",
      row_vol._minus.x() < row_vol._slider.x() < row_vol._plus.x(),
      f"{row_vol._minus.x()} / {row_vol._slider.x()} / {row_vol._plus.x()}")

# ---- 「这里的音量条不需要另外加边框」----
check("音量条**不带容器边框**：没有桌宠那层 #volBox 壳（白底 + #7DD3FC 边）",
      row_vol._slider.parent().objectName() != "volBox"
      and "#7DD3FC" not in row_vol._slider.styleSheet(),
      row_vol._slider.parent().objectName())
check("只画轨道 / 已填充 / 圆钮三件（与桌宠那条同一颗 `volume.VolumeSlider`）",
      "QSlider::groove:horizontal" in row_vol._slider.styleSheet()
      and "sub-page" in row_vol._slider.styleSheet()
      and "handle" in row_vol._slider.styleSheet(), row_vol._slider.styleSheet())

# ---- hover 颜色渐变（自绘圆底：白 → 浅蓝）----
_bv = row_vol._plus
check("hover 走的是自绘 + QVariantAnimation 插值（**不是** QSS :hover 的瞬间变色 —— "
      "QSS 的 :hover 不支持过渡）",
      isinstance(_bv._anim, QVariantAnimation))
check("渐变时长 200ms、线性（与全项目 hover 同一档）",
      _bv._anim.duration() == 200 and _bv._anim.easingCurve().type() == QEasingCurve.Linear,
      f"{_bv._anim.duration()}/{_bv._anim.easingCurve().type()}")


def _btn_px(btn):
    """按钮圆内靠上一点的像素（避开中间的 `−`/`+` 线段）——直接量圆底的底色。"""
    return btn.grab().toImage().pixelColor(11, 4).name().lower()


_bv._anim.stop()
_bv._t = 0.0
_bv.update()
check("静止底色 = 界面底色白 #FFFFFF（无边框，与行底融为一体）",
      _btn_px(_bv) == "#ffffff", _btn_px(_bv))
_bv._animate_to(1.0)
# ★**手动把动画推到 80ms 处**（200ms 的 0.4），别用固定等待 `settle(80)`：
#   机器负载高时那 80ms 里动画可能一帧都没推进 ⇒ `t=0.00` **偶发假红**
#   （2026-09-22 实测：rev26 连着跑 11 次 smoke_settings，命中过 1 次；run_all 并发跑 9 套时也红过）。
#   `setCurrentTime()` 会**同步**触发 valueChanged ⇒ 结果确定，与机器忙不忙无关。
_bv._anim.setCurrentTime(80)
_bv.update()
_mid_px = _btn_px(_bv)
check("渐变**中途**确实是中间色（不是一步跳到位 —— 那就成了瞬间变色）",
      _mid_px not in ("#ffffff", "#e6f1fb") and 0.0 < _bv._t < 1.0, f"{_mid_px} t={_bv._t:.2f}")
_bv._anim.setCurrentTime(200)
_bv.update()
check("鼠标移入 → 底色渐变到浅蓝 #E6F1FB", _btn_px(_bv) == "#e6f1fb", _btn_px(_bv))
_bv._animate_to(0.0)
_bv._anim.setCurrentTime(80)          # 同上：不由事件循环的快慢决定
_bv.update()
_mid_px2 = _btn_px(_bv)
check("移出方向同样有中间态（两个方向都是渐变）",
      _mid_px2 not in ("#ffffff", "#e6f1fb") and 0.0 < _bv._t < 1.0, f"{_mid_px2} t={_bv._t:.2f}")
_bv._anim.setCurrentTime(200)
_bv.update()
check("鼠标移出 → 渐变回白 #FFFFFF",
      _btn_px(_bv) == "#ffffff" and _bv._t == 0.0, f"{_btn_px(_bv)} t={_bv._t}")
check("`−` / `+` 线段画在主蓝 #378ADD 上（抓按钮正中心的像素）",
      _bv.grab().toImage().pixelColor(11, 11).name().lower() == "#378add",
      _bv.grab().toImage().pixelColor(11, 11).name())
check("`−` 按钮只有一条横线（中心之外的上方没有竖线）",
      row_vol._minus.grab().toImage().pixelColor(11, 4).name().lower() == "#ffffff")

# ---- 步进：单击 ±5%，钳在 0~100 ----
_vol_calls = []
win.set_volume_cb(lambda v: _vol_calls.append(v))
row_vol.set_value(0.5, notify=False)
check("构建 / 反向同步用的 set_value(notify=False) 不回调", _vol_calls == [], str(_vol_calls))
QTest.mouseClick(row_vol._plus, Qt.LeftButton)
check("点一次 + ：音量 +5%（不是 1% —— 1% 要点十几次才听得出差别）",
      row_vol._slider.value() == 55 and row_vol.value() == 0.55 and _vol_calls == [0.55],
      f"{row_vol._slider.value()} / {_vol_calls}")
check("改完落进 cfg（这条音量与桌宠那条共用一份配置）",
      abs(cfg["volume"] - 0.55) < 1e-9, str(cfg.get("volume")))
check("并且写盘了（重开软件还是这个音量）",
      abs(json.loads(tmp_cfg.read_text(encoding="utf-8"))["volume"] - 0.55) < 1e-9)
QTest.mouseClick(row_vol._minus, Qt.LeftButton)
QTest.mouseClick(row_vol._minus, Qt.LeftButton)
check("点两次 − ：55 → 45，回调按次数一次一条",
      row_vol._slider.value() == 45 and _vol_calls == [0.55, 0.5, 0.45], str(_vol_calls))
row_vol.set_value(1.0, notify=False)
QTest.mouseClick(row_vol._plus, Qt.LeftButton)
check("到顶了再点 + ：钳在 100（不会溢出成 105）", row_vol._slider.value() == 100)
row_vol.set_value(0.0, notify=False)
QTest.mouseClick(row_vol._minus, Qt.LeftButton)
check("到底了再点 − ：钳在 0", row_vol._slider.value() == 0)
_n_before = len(_vol_calls)
row_vol._slider.setValue(70)
check("拖动音量条也走同一条出口（不是按钮一套、滑块另一套）",
      len(_vol_calls) == _n_before + 1 and _vol_calls[-1] == 0.7, str(_vol_calls[-2:]))

# ---- 反向同步：别处改了音量 → 只同步这一行、不回调 ----
_n_before = len(_vol_calls)
win.sync_volume(0.33)
check("win.sync_volume(0.33) → 只看这一行跟着动，**不回调**（否则回环）",
      row_vol._slider.value() == 33 and len(_vol_calls) == _n_before, str(_vol_calls[-2:]))
check("sync_volume 不整页重建（行对象还是同一个）",
      gen._volume_row is row_vol)
_old_cb_vol = win._on_volume
win.set_volume_cb(None)
check("main.py 还没接上时：notify_volume 什么也不做、不报错",
      win.notify_volume(0.5) is None)
win.set_volume_cb(_old_cb_vol)
check("主窗口提供 set_volume_cb / notify_volume / sync_volume 三个注入点",
      all(hasattr(win, _n) for _n in ("set_volume_cb", "notify_volume", "sync_volume")))

# ---- main.py 侧：三条入口收敛到同一个函数 ----
_src_vol = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
_src_gui_vol = (Path(__file__).resolve().parent.parent / "app" / "gui.py").read_text(encoding="utf-8")
_ovc = _src_vol[_src_vol.index("def on_volume_changed"):_src_vol.index("pet.set_on_volume")]
check("main.py：桌宠那条音量条与设置页那一行**收敛到同一个 on_volume_changed**",
      "pet.set_on_volume(on_volume_changed)" in _src_vol
      and "win.set_volume_cb(on_volume_changed)" in _src_vol
      and _src_vol.index("win.set_volume_cb(on_volume_changed)")
      > _src_vol.index("def on_volume_changed"), "回调先定义、后注册")
check("on_volume_changed 里：落 cfg + 同步 TTS + 回同步桌宠与设置页两处 UI",
      "cfg[\"volume\"] = round(v, 2)" in _ovc and "save_config(cfg)" in _ovc
      and "set_tts_volume(v)" in _ovc and "pet.set_volume(v)" in _ovc
      and "win.sync_volume(v)" in _ovc, _ovc[:200])
check("设置页改音量**不往底部消息行写字**（音量条本身就是反馈，拖一次写一行会刷屏）",
      "_set_volume" in _src_gui_vol
      and "_msg(" not in _src_gui_vol[_src_gui_vol.index("def _set_volume"):
                                      _src_gui_vol.index("def _reset_pet_pos")])
row_vol.set_value(0.5, notify=False)          # 收尾：别把音量留在 0.33 影响后面
win.set_volume_cb(None)
cfg["volume"] = 0.5


# ========== 5e. 通用设置·语音模型（音色克隆模型下载 + 安装位置，2026-09-22）==========
print("== 5e. 通用设置·语音模型 ==")
import app.voice_model as _vm  # noqa: E402

_src_vm = (Path(__file__).resolve().parent.parent / "app" / "voice_model.py").read_text(encoding="utf-8")

row_m = getattr(gen, "_model_row", None)
row_d = getattr(gen, "_model_dir_row", None)
check("通用设置里有「音色克隆模型下载」下载行（_SettingDownloadRow）",
      isinstance(row_m, gui._SettingDownloadRow), type(row_m).__name__)
check("通用设置里有「安装位置」路径行（_SettingPathRow）",
      isinstance(row_d, gui._SettingPathRow), type(row_d).__name__)
check("两行都是设置行：高 58px + 无说明小字（hint 为空且不占位）",
      row_m.height() == 58 and row_d.height() == 58
      and row_m._hint_text == "" and row_d._hint_text == ""
      and not row_m._hint.isVisible() and not row_d._hint.isVisible())

# ---- 分组位置：启动 → 语音模型 → 模式切换（**紧贴**它要锁死的静音模式，因果才看得见）----
_group_at = {}
for _i in range(gen._body_lay.count()):
    _lay = gen._body_lay.itemAt(_i).layout()
    if _lay is not None and _lay.itemAt(0) is not None:
        _h = _lay.itemAt(0).widget()
        if _h is not None and hasattr(_h, "text"):
            _group_at[_h.text()] = _i
check("新增「语音模型」分组，排在「启动」之后、「模式切换」之前",
      _group_at.get("启动", 99) < _group_at.get("语音模型", -1) < _group_at.get("模式切换", -1),
      str(_group_at))
_i_start = gen._body_lay.indexOf(gen._autostart_row)
_i_model = gen._body_lay.indexOf(row_m)
_i_mute = gen._body_lay.indexOf(gen._mute_row)
check("★下载行紧贴静音模式之上（中间只隔一个分组标题）—— 没模型就锁死静音，因果要看得见",
      _i_start < _i_model < _i_mute, f"{_i_start} < {_i_model} < {_i_mute}")

# ---- 两颗按钮：蓝色镂空、28px、文案、间距 8px ----
_bd, _bu = row_m._download_btn, row_m._uninstall_btn
check("下载行右侧是两颗蓝色镂空按钮（#outlineBtn、高 28px）",
      isinstance(_bd, QPushButton) and isinstance(_bu, QPushButton)
      and _bd.objectName() == "outlineBtn" and _bu.objectName() == "outlineBtn"
      and _bd.height() == 28 and _bu.height() == 28,
      f"{_bd.objectName()}/{_bd.height()}  {_bu.objectName()}/{_bu.height()}")
check("两颗按钮文案是「下载」「卸载」，间距 8px（与 4.11 标题行右侧那两颗同规格）",
      _bd.text() == "下载" and _bu.text() == "卸载" and row_m.BTN_GAP == 8,
      f"{_bd.text()}/{_bu.text()}/{row_m.BTN_GAP}")
check("状态文字宽度钉死（从「未下载」变「下载中 42%」时按钮不位移）",
      row_m._state.width() == row_m.STATE_W, str(row_m._state.width()))
# ★同 PATH_W：`宽度 == 自己的 STATE_W` 自洽 ⇒ 一起改大也绿，另钉绝对值。
check("状态文字区宽度钉死 100px（自洽式之外再钉一个绝对数）",
      row_m.STATE_W == 100 and row_m.BTN_GAP == 8, f"{row_m.STATE_W}/{row_m.BTN_GAP}")
# ★行为层：**自己造最长的那一态**去量 —— 钉数字只能防「改小」，这条能防「文字变长 / 字体变宽」
#   把 `%` 裁掉（二期加「下载中　NN%」时实测过：84px 时 `下载中　100%` 的 96px 会被裁）。
check("★最宽的一态（「下载中　100%」）也放得下 —— 不会被裁",
      row_m._state.fontMetrics().horizontalAdvance("下载中　100%") <= row_m.STATE_W,
      f"{row_m._state.fontMetrics().horizontalAdvance('下载中　100%')} > {row_m.STATE_W}")
check("「安装位置」右侧是路径文字 + 「更改」按钮（#outlineBtn、高 28px）",
      row_d._button.text() == "更改" and row_d._button.objectName() == "outlineBtn"
      and row_d._button.height() == 28)
# ★单独钉 PATH_W 的**绝对值**：截断断言是「宽度 == 自己的 PATH_W」，那是个自洽式 ——
#   把 PATH_W（连同标签宽）一起改大，它照样绿，长路径又会顶宽整行 ⇒ 必须另钉一个绝对数。
check("路径区宽度钉死 240px（截断断言是自洽式，不另钉绝对值就抓不住「一起改大」）",
      row_d.PATH_W == 240 and row_d._path.width() == 240, str(row_d.PATH_W))

# ---- ★接线核**回调身份**（不是核文字 / 行序）----
check("★「下载」按钮接的是 GeneralPanel._download_model（核身份 + 后面真点一次）",
      row_m._on_download.__func__ is gui.GeneralPanel._download_model)
check("★「卸载」按钮接的是 GeneralPanel._uninstall_model（核身份；真点会删 4.6 GB，所以只核身份）",
      row_m._on_uninstall.__func__ is gui.GeneralPanel._uninstall_model)
check("「更改」按钮接的是 GeneralPanel._change_model_dir",
      row_d._on_click.__func__ is gui.GeneralPanel._change_model_dir)

# ---- 模型清单与判据（**常量层钉绝对值**：被下游拿去做判据 / 文案的数字必须单独钉死）----
check("大权重清单就是那 5 个文件，字节数逐个钉死（与真机实文件核过）",
      _vm.MODEL_FILES == {
          "chinese-hubert-base/pytorch_model.bin": 188811417,
          "chinese-roberta-wwm-ext-large/pytorch_model.bin": 651225145,
          "fast_langdetect/lid.176.bin": 131266198,
          "gsv-v2final-pretrained/s2G2333k.pth": 106035259,
          "gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt": 155315150,
      }, str(sorted(_vm.MODEL_FILES)))
check("★★配套小文件清单就是那 4 个（共 271,586 B；缺任何一个 api.py 都起不来）",
      _vm.MODEL_AUX_FILES == {
          "chinese-hubert-base/config.json": 1449,
          "chinese-hubert-base/preprocessor_config.json": 212,
          "chinese-roberta-wwm-ext-large/config.json": 963,
          "chinese-roberta-wwm-ext-large/tokenizer.json": 268962,
      }, str(sorted(_vm.MODEL_AUX_FILES)))
check("★required_model_files() = 大权重 + 配套（判据/下载唯一真值；9 个文件）",
      _vm.required_model_files() == {**_vm.MODEL_FILES, **_vm.MODEL_AUX_FILES}
      and len(_vm.required_model_files()) == 9, str(len(_vm.required_model_files())))
check("MODEL_TOTAL_BYTES == 所需文件之和 == 1,232,924,755（卸载确认框里的「约 1.15 GB」就是它）",
      _vm.MODEL_TOTAL_BYTES == sum(_vm.required_model_files().values()) == 1232924755,
      str(_vm.MODEL_TOTAL_BYTES))
check("模型子目录是 GPT_SoVITS/pretrained_models（tts.py 与 api.py 用的就是它）",
      _vm.MODEL_SUBDIR == "GPT_SoVITS/pretrained_models", _vm.MODEL_SUBDIR)

# ---- 「已下载」判据：**所需文件**齐 **且大小逐个相等**（半截文件也算「在」，不能只看存在）----
# ★判据是**两批**：5 个大权重 + 4 个配套小文件。2026-09-27 实测踩过：只核大权重时，
#   「权重齐、配套缺」的目录会被判「已下载」，而服务根本起不来（AutoTokenizer 崩）。
_fake = tmp_dir / "fakemodel"
_fake_files = {"a/one.bin": 10, "a/two.bin": 20, "b/three.bin": 30, "c/four.bin": 40, "five.bin": 50}
_fake_aux = {"a/aux.json": 11, "b/aux2.json": 22}
for _rel, _sz in {**_fake_files, **_fake_aux}.items():
    _p = _fake / _rel
    _p.parent.mkdir(parents=True, exist_ok=True)
    _p.write_bytes(b"x" * _sz)
_real_files, _real_aux = _vm.MODEL_FILES, _vm.MODEL_AUX_FILES
_vm.MODEL_FILES = dict(_fake_files)
_vm.MODEL_AUX_FILES = dict(_fake_aux)
check("所需文件齐 + 大小逐个相等 ⇒ 判「已下载」", _vm.is_model_dir_ok(_fake) is True)
(_fake / "a" / "two.bin").write_bytes(b"x" * 7)
check("★大小不等（下载中断的半截文件）⇒ 仍判「未下载」（只核「存在」会被它骗过）",
      _vm.is_model_dir_ok(_fake) is False)
(_fake / "a" / "two.bin").write_bytes(b"x" * 20)
(_fake / "five.bin").unlink()
check("缺一个大权重 ⇒ 判「未下载」", _vm.is_model_dir_ok(_fake) is False)
(_fake / "five.bin").write_bytes(b"x" * 50)
check("补回来 ⇒ 又判「已下载」", _vm.is_model_dir_ok(_fake) is True)
# ★★本次修的坑：**大权重一个不少、只缺配套小文件**，也必须判「未下载」
(_fake / "a" / "aux.json").unlink()
check("★★只缺配套小文件（大权重全在）⇒ 也必须判「未下载」（否则界面说装好了、她却一声不吭）",
      _vm.is_model_dir_ok(_fake) is False)
(_fake / "a" / "aux.json").write_bytes(b"x" * 11)
check("配套补回来 ⇒ 又判「已下载」", _vm.is_model_dir_ok(_fake) is True)
_vm.MODEL_FILES, _vm.MODEL_AUX_FILES = _real_files, _real_aux

# ---- 安装目录的三级探测顺序（★「自动沿用已有安装」这条用户口径就锚在这里）----
check("探测顺序 = 自定义目录 → 项目内 runtime/GPT-SoVITS → D:\\GPT-SoVITS（历史路径）",
      [str(p) for p in _vm.candidate_dirs({})]
      == [str(_vm.BASE_DIR / _vm.DEFAULT_DIR_NAME), r"D:\GPT-SoVITS"],
      str([str(p) for p in _vm.candidate_dirs({})]))
check("设置页指定的目录**优先于**另外两条",
      [str(p) for p in _vm.candidate_dirs({"general": {"model_dir": r"E:\custom"}})]
      == [r"E:\custom", str(_vm.BASE_DIR / _vm.DEFAULT_DIR_NAME), r"D:\GPT-SoVITS"])
check("★历史路径 D:\\GPT-SoVITS 必须在候选里（少了它，本机这套能用环境会被判成「未下载」⇒ 静音锁死）",
      r"D:\GPT-SoVITS" in [str(p) for p in _vm.candidate_dirs({})])
check("model_dir 为空串 / None / 纯空格时都不产生候选", 
      len(_vm.candidate_dirs({"general": {"model_dir": ""}})) == 2
      and len(_vm.candidate_dirs({"general": {"model_dir": None}})) == 2
      and len(_vm.candidate_dirs({"general": {"model_dir": "   "}})) == 2)
check("disk_free_gb 对存在的盘给正数、对不存在的盘给 -1（二期磁盘预检用）",
      _vm.disk_free_gb(str(tmp_dir)) > 0 and _vm.disk_free_gb(r"Z:\nope\deep") == -1.0,
      "%s / %s" % (_vm.disk_free_gb(str(tmp_dir)), _vm.disk_free_gb(r"Z:\nope\deep")))

# ---- 三态：用 monkeypatch 造「未下载」，不依赖真机上到底装没装（用户随时可以卸载）----
_orig_installed = _vm.is_installed
_orig_model_dir = _vm.model_dir
_prev_mute = cfg["general"].get("mute_mode")

_vm.is_installed = lambda c: True
gen._apply_model_state()
check("已下载：状态文字「已下载」+ 下载禁用 + 卸载可用",
      row_m.state_text() == "已下载" and _bd.isEnabled() is False and _bu.isEnabled() is True,
      f"{row_m.state_text()} / 下载{_bd.isEnabled()} / 卸载{_bu.isEnabled()}")
check("已下载：静音滑块**不锁**", gen._mute_row.is_locked() is False)

_vm.is_installed = lambda c: False
_vm.model_dir = lambda c: None          # 未下载时自然也没有模型目录
gen._apply_model_state()
check("未下载：状态文字「未下载」+ 下载可用 + 卸载禁用",
      row_m.state_text() == "未下载" and _bd.isEnabled() is True and _bu.isEnabled() is False,
      f"{row_m.state_text()} / 下载{_bd.isEnabled()} / 卸载{_bu.isEnabled()}")
check("未下载：禁用的「卸载」按钮光标回到箭头（灰按钮还带手型会误导）",
      _bu.cursor().shape() == Qt.ArrowCursor)
check("★未下载 ⇒ 静音滑块**锁死**，且被强制拨到「开」",
      gen._mute_row.is_locked() is True and gen._mute_row.is_enabled() is True
      and gen._mute_row._switch.is_locked() is True)
check("★未下载 ⇒ 静音模式真的生效（写进 cfg —— main.mute_mode_on() 每轮现读）",
      cfg["general"].get("mute_mode") is True)
check("锁死的滑块光标改成箭头（不再有手型）",
      gen._mute_row._switch.cursor().shape() == Qt.ArrowCursor)

_sw = gen._mute_row._switch
_before_ck = _sw.isChecked()
# ★**只点一下**：点两下在「翻转型」控件上是**奇偶抵消** —— 坏掉（守卫被删）时两次点击把值翻回原样，
#   断言照样绿（`rev25` 的 G2 就是这样 0 红的）。而且必须配**正对照**（下面解锁后再点一下必须真翻），
#   否则「点不动」也可能只是「事件根本没送到」的假绿。
QTest.mouseClick(_sw, Qt.LeftButton)
check("★锁死时**真的点一下** = 点不动（值不变、cfg 也不变）",
      _sw.isChecked() == _before_ck and gen._mute_row.is_enabled() is True
      and cfg["general"].get("mute_mode") is True,
      f"checked={_sw.isChecked()} cfg={cfg['general'].get('mute_mode')}")

# ---- ★这里**不真点「下载」** ----
# 一期时点它只会弹一句「下一期的提示」，二期它改成**真起下载线程**了：在测试里点一下
# 会往磁盘写东西，还会让 `voice_download.is_running()` 一直为真 ⇒ **后面所有「未下载态」的
# 断言全部崩掉**（本轮实测：静音解锁那几条连着 5 条红）。接线与副作用放到 5g，
# 那里用 patch 过的 `voice_download.start` 去验（不产生任何真实副作用）。
#
# ---- 未下载时点「卸载」：必须只提示、不弹确认框、不删任何东西 ----
gen._msg_label.setText("")
gen._uninstall_model()
check("未下载时点「卸载」→ 只提示「没有找到可卸载的模型」（不弹确认、不删东西）",
      "没有找到" in gen._msg_label.text(), gen._msg_label.text())

# ---- 解锁：模型就位 ⇒ 解锁但**保持原值**（不突然出声，由用户自己关）----
_vm.is_installed = lambda c: True
_vm.model_dir = _orig_model_dir
gen._apply_model_state()
check("模型就位 ⇒ 解锁（滑块可点），且值**保持「开」**",
      gen._mute_row.is_locked() is False and gen._mute_row.is_enabled() is True)
QTest.mouseClick(_sw, Qt.LeftButton)
check("解锁后点一下能正常切换，并写回 cfg",
      gen._mute_row.is_enabled() is False and cfg["general"].get("mute_mode") is False,
      f"{gen._mute_row.is_enabled()} / {cfg['general'].get('mute_mode')}")
check("★正对照：解锁态下**同一次点击真的把值翻过去了** —— 证明上面那条「点不动」不是"
      "「事件根本没送到」的假绿",
      _sw.isChecked() != _before_ck, f"{_before_ck} → {_sw.isChecked()}")

# ---- 「安装位置」：落盘 + **不许谎报**（探测顺序里有兜底路径，指定目录不存在时不能报「已就位」）----
gen._msg_label.setText("")
gen.set_model_dir(r"Z:\no-such-dir")
check("★指定一个不存在的目录：不许谎报「该目录下模型已就位」（兜底路径会命中，界面照旧「已下载」）",
      "已就位" not in gen._msg_label.text(), gen._msg_label.text())
check("没找到 ≠ 装上了：底部提示必须点明「没有完整模型」",
      "没有完整模型" in gen._msg_label.text(), gen._msg_label.text())
check("改安装位置**落盘**进 cfg.general.model_dir",
      cfg["general"].get("model_dir") == r"Z:\no-such-dir", str(cfg["general"].get("model_dir")))
check("set_model_dir('') 直接返回 None、不改动 cfg",
      gen.set_model_dir("") is None and cfg["general"].get("model_dir") == r"Z:\no-such-dir")
# ★别拿「真机路径够不够长」当判据：本机 D:\GPT-SoVITS（13 字符）刚好卡在阈值上，
#   换台机器 / 用户改了安装位置，这条断言就会随环境忽红忽绿 ⇒ 自己塞一条超长路径进去量。
_prev_path_text = row_d.path_text()
row_d.set_path(r"E:\some\very\long\custom\dir\GPT-SoVITS\GPT_SoVITS\pretrained_models")
check("路径超长时用 `…` 中段截断（不顶宽整行 ⇒ 行的右边框不会被裁掉）",
      "…" in row_d.shown_text() and row_d.shown_text() != row_d.path_text()
      and row_d._path.width() == row_d.PATH_W,
      row_d.shown_text())
check("★截断只影响「显示」：path_text() 仍是完整路径（改目录时不能把 `…` 写进 cfg）",
      row_d.path_text().endswith("pretrained_models"), row_d.path_text())
row_d.set_path(_prev_path_text)          # 收尾：还原成真机上那条

# ---- 收尾：还原 monkeypatch 与 cfg，别影响后面的用例 ----
_vm.is_installed = _orig_installed
_vm.model_dir = _orig_model_dir
cfg["general"]["model_dir"] = ""
cfg["general"]["mute_mode"] = _prev_mute
gen._apply_model_state()
cfgmod.save_config(cfg)


# ========== 5f. 语音模型：卸载必须「送回收站」而不是永久删除（结构层）==========
print("== 5f. 语音模型·卸载走回收站 ==")
_tree_vm = ast.parse(_src_vm)
_fn_names = {n.name for n in ast.walk(_tree_vm) if isinstance(n, ast.FunctionDef)}
check("voice_model 里有 to_recycle_bin() 与 uninstall()",
      {"to_recycle_bin", "uninstall"} <= _fn_names, str(sorted(_fn_names)))

_un_fn = next(n for n in ast.walk(_tree_vm)
              if isinstance(n, ast.FunctionDef) and n.name == "uninstall")
_un_names = {c.func.id for c in ast.walk(_un_fn)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
check("★uninstall() 走的是 to_recycle_bin（送回收站，用户可还原）",
      "to_recycle_bin" in _un_names, str(sorted(_un_names)))

# ★只查 AST、**不查字符串**：注释里恰好也写了 `Windll` / `FOF_SILENT`，用 `in _src` 会误伤
_attr_calls = {c.func.attr for c in ast.walk(_tree_vm)
               if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
check("★模块里没有任何永久删除调用（rmtree / unlink / remove / rmdir）—— 4.6 GB 必须能还原",
      not (_attr_calls & {"rmtree", "unlink", "remove", "rmdir"}), str(sorted(_attr_calls)))
_used_names = {n.id for n in ast.walk(_tree_vm) if isinstance(n, ast.Name)}
check("★回收站 flags 用了 FOF_ALLOWUNDO（进回收站），且**没有用到** FOF_SILENT",
      "FOF_ALLOWUNDO" in _used_names and "FOF_SILENT" not in _used_names,
      str(sorted(n for n in _used_names if n.startswith("FOF"))))
_defined = {t.id for n in ast.walk(_tree_vm) if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)}
check("★模块里根本没有定义 FOF_SILENT（它与 FOF_ALLOWUNDO 同现会让文件被永久删除）",
      "FOF_SILENT" not in _defined, str(sorted(n for n in _defined if n.startswith("FOF"))))
_has_upper = any(isinstance(n, ast.Attribute) and n.attr == "Windll" for n in ast.walk(_tree_vm))
_windll_strs = [n.value for n in ast.walk(_tree_vm)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value.lower() == "windll"]
check("★ctypes 开关用的是小写 `windll`（AST 里没有 `.Windll`；写成大写会恒为 False 且不报错）",
      (not _has_upper) and _windll_strs == ["windll"], str(_windll_strs))
check("★平台不可用时 to_recycle_bin 返回 False（失败的结果必须是「文件还在」，不是静默删掉）",
      "if not _HAS_WIN32:" in _src_vm)
_un_ret_not_exists = any(
    isinstance(n, ast.Return) and isinstance(n.value, ast.UnaryOp)
    and isinstance(n.value.op, ast.Not)
    and isinstance(n.value.operand, ast.Call)
    and isinstance(n.value.operand.func, ast.Attribute)
    and n.value.operand.func.attr == "exists"
    for n in ast.walk(_un_fn))
check("★uninstall() 的判据是「原路径**还在不在**」（`return not md.exists()`，不看 SHFileOperationW 的返回值，它不可信）",
      _un_ret_not_exists)
check("★uninstall() 的三条早退分支都返回 True（清单为空 / 本来没有 / 不是目录 ⇒ 已达成「未下载」，不当作失败）",
      sum(1 for n in ast.walk(_un_fn)
          if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
          and n.value.value is True) == 3)
# ★★2026-09-27：卸载从「一问一答」升级成**两档**（用户口径「仅模型卸载 / 全部卸载」），
#   所以上面那条「早退分支数」也从 2 变成 3。结构层再加四条把两档钉住。
check("★uninstall() 两档常量都在（model / all）",
      _vm.UNINSTALL_MODEL == "model" and _vm.UNINSTALL_ALL == "all",
      "%r / %r" % (_vm.UNINSTALL_MODEL, _vm.UNINSTALL_ALL))
_un_defaults = list(_un_fn.args.defaults)
check("★uninstall() 默认档 = 仅模型（推荐档）—— 「全删」必须**显式**传 mode，不许是默认值",
      len(_un_defaults) == 1 and isinstance(_un_defaults[0], ast.Name)
      and _un_defaults[0].id == "UNINSTALL_MODEL",
      str([getattr(d, "id", d) for d in _un_defaults]))
_un_named = {c.func.id for c in ast.walk(_un_fn)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
check("★「全部卸载」那一支走 purge_paths()（清单式删除），不是再删一次模型目录",
      "purge_paths" in _un_named, str(sorted(_un_named)))
check("★两档各调一次 to_recycle_bin（两条路都送回收站，**没有**任何永久删的分支）",
      sum(1 for c in ast.walk(_un_fn)
          if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
          and c.func.id == "to_recycle_bin") == 2,
      str(sorted(_un_named)))
check("★「全部卸载」的判据也是「清单里还有没有活着的」（`return not any(p.exists() ...)`）",
      any(isinstance(n, ast.Return) and isinstance(n.value, ast.UnaryOp)
          and isinstance(n.value.op, ast.Not)
          and isinstance(n.value.operand, ast.Call)
          and isinstance(n.value.operand.func, ast.Name)
          and n.value.operand.func.id == "any"
          for n in ast.walk(_un_fn)))

# ---- PURGE_TARGETS：「全部卸载」到底删什么（★清单式，**不是**白名单式，见 docs/02 §22.11）----
#   白名单式（「目录下除了这几个都删」）**漏一项 = 永久删掉用户资产**（refs/ 之类）；
#   清单式漏一项只是**少删** ⇒ 最坏结果是把「全部卸载」降级成「部分卸载」，用户重来一次即可。
check("★PURGE_TARGETS 共 52 项（跟着 voice_download.CODE_COMMIT 锁死的那份清单；"
      "改它必须同步 docs/02 §22.11）",
      len(_vm.PURGE_TARGETS) == 52, str(len(_vm.PURGE_TARGETS)))
check("★清单无重复项（重复会让 purge_paths 里同一个路径出现两次）",
      len(set(_vm.PURGE_TARGETS)) == len(_vm.PURGE_TARGETS),
      str(sorted(p for p in set(_vm.PURGE_TARGETS) if _vm.PURGE_TARGETS.count(p) > 1)))
check("★清单覆盖「代码体 + venv + 模型」三样（缺一样「全部卸载」就名不副实）",
      {"api.py", ".venv", "GPT_SoVITS/pretrained_models"} <= set(_vm.PURGE_TARGETS),
      str(sorted(set(_vm.PURGE_TARGETS))))
# ★★反向断言：这些**必须不在**清单里。删了它们只能在回收站里找，而「非下载所得」的
#   用户资产一旦被清空回收站的用户顺手清掉，就是不可逆的。
for _keep in ("refs", "ffmpeg.exe", ".git", "requirements_cpu.txt", "start_api.bat",
              "recognize_ref.py", "api_log.txt", "_playtest.wav"):
    check("★★清单里**没有** %s（非下载所得的用户资产，删了只能在回收站里找）" % _keep,
          _keep not in _vm.PURGE_TARGETS)
check("★★清单**整目录跳过** GPT_SoVITS/text —— 下面躺着 G2PWModel(607 MB) 与 "
      "ja_userdic(36.8 MB) 两个用户资产（只删 text 里别的文件也不许：路径前缀都不许出现）",
      not any(t == "GPT_SoVITS/text" or t.startswith("GPT_SoVITS/text/")
              for t in _vm.PURGE_TARGETS),
      str([t for t in _vm.PURGE_TARGETS if t.startswith("GPT_SoVITS/text")]))

# ---- main.py 的启动门禁（AST 取**写死的 True**，注释 / 变量名骗不了它）----
_src_main_vm = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
_tree_main = ast.parse(_src_main_vm)
_gate = next((n for n in ast.walk(_tree_main)
              if isinstance(n, ast.FunctionDef) and n.name == "_apply_model_gate"), None)
check("main.py 有启动门禁 _apply_model_gate()", _gate is not None)
_gate_attr = {c.func.attr for c in ast.walk(_gate)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
check("★门禁：没模型 ⇒ 查 is_installed + 同步设置页滑块 + 落一条系统消息",
      {"is_installed", "sync_mute_mode", "add_system_message"} <= _gate_attr,
      str(sorted(_gate_attr)))
check("★门禁把 mute_mode **写死成 True**（不是从别处读变量 —— 那样可能被改成 False）",
      any(isinstance(n, ast.Assign)
          and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                  and t.slice.value == "mute_mode" for t in n.targets)
          and isinstance(n.value, ast.Constant) and n.value.value is True
          for n in ast.walk(_gate)))
check("门禁在 app.exec() 之前跑（否则启动完才判，第一轮回复可能漏）",
      _src_main_vm.rindex("_apply_model_gate()") < _src_main_vm.index("return app.exec()"))
# ★★2026-09-29：静音模式改成「落盘偏好」之后，门禁**不许**跟着写盘 ——
#   门禁置的 True 是**派生状态**（「没模型 ⇒ 现在出不了声」），不是用户的偏好；
#   它一旦落盘，用户装好模型后首次启动就会莫名是静音。用户偏好只由两条显式切换路写盘。
check("★★启动门禁**不**主动落盘（门禁的 True 是派生状态，不是用户偏好 —— "
      "落盘会让「装好模型后首次启动」莫名是静音）—— ★AST 查真实 Call，注释里提一句不算",
      not any(isinstance(c, ast.Call) and (
                  (isinstance(c.func, ast.Name) and c.func.id == "save_config")
                  or (isinstance(c.func, ast.Attribute) and c.func.attr == "save_config"))
              for c in ast.walk(_gate)),
      str([n.lineno for n in ast.walk(_gate) if isinstance(n, ast.Call)]))

# ---- 配置层：model_dir 默认空串、**要落盘**（与 lock_pet 同类；静音 2026-09-29 起也是同类）----
check("DEFAULT_CONFIG 里 general.model_dir 默认空串（= 按探测顺序自动找）",
      cfgmod.DEFAULT_CONFIG["general"]["model_dir"] == "",
      repr(cfgmod.DEFAULT_CONFIG["general"].get("model_dir")))
check("★model_dir **要落盘**：不在 _RUNTIME_ONLY_GENERAL 里（否则改了安装位置重启就丢）",
      "model_dir" not in cfgmod._RUNTIME_ONLY_GENERAL, str(cfgmod._RUNTIME_ONLY_GENERAL))
tmp_cfg.write_text(json.dumps({"general": {"model_dir": "   "}}), encoding="utf-8")
check("model_dir 归一化：纯空格 → 空串", cfgmod.load_config()["general"]["model_dir"] == "")
tmp_cfg.write_text(json.dumps({"general": {"model_dir": r"E:\custom"}}), encoding="utf-8")
check("model_dir 用户值原样读回", cfgmod.load_config()["general"]["model_dir"] == r"E:\custom")
cfgmod.save_config({"general": {"model_dir": r"E:\custom", "mute_mode": True,
                                "patpat_mode": True, "lock_pet": False}})
_saved_g = json.loads(tmp_cfg.read_text(encoding="utf-8")).get("general", {})
check("★save_config：model_dir / lock_pet / mute_mode 都落盘，**只有 patpat_mode 被剔掉**",
      _saved_g.get("model_dir") == r"E:\custom" and _saved_g.get("lock_pet") is False
      and _saved_g.get("mute_mode") is True and "patpat_mode" not in _saved_g,
      json.dumps(_saved_g, ensure_ascii=False))
cfgmod.save_config(cfg)     # 收尾：把上面的假配置覆盖回去，别影响后面


# ========== 5g. 语音模型·下载流水线（二期）==========
print("== 5g. 语音模型·下载流水线（二期）==")
import app.voice_download as _vd  # noqa: E402

_src_vd = (Path(__file__).resolve().parent.parent / "app" / "voice_download.py").read_text(encoding="utf-8")
_tree_vd = ast.parse(_src_vd)
_tree_g = ast.parse(_src_gui_vol)


def _method_of(tree, cls, name):
    """在**指定类**里找方法。★不按名字裸找：跨类同名方法会撞车（本项目踩过）。"""
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == cls:
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == name:
                    return m
    return None


# ---- 模块性质：纯逻辑，不许 import Qt ----
_vd_imports = set()
for _n in ast.walk(_tree_vd):
    if isinstance(_n, ast.Import):
        _vd_imports |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _vd_imports.add(_n.module.split(".")[0])
check("★voice_download 是纯逻辑模块（不 import Qt / PySide6）—— 否则没法脱离 QApplication 断言",
      not (_vd_imports & {"PySide6", "PyQt5", "PyQt6"}), str(sorted(_vd_imports)))

# ---- 总进度：纯函数 ----
check("idle -> 0，done -> 100", _vd.overall_percent(_vd.PHASE_IDLE) == 0
      and _vd.overall_percent(_vd.PHASE_DONE) == 100)
check("末段（verify）跑满 = 100", _vd.overall_percent(_vd.PHASE_VERIFY, 1.0) == 100,
      _vd.overall_percent(_vd.PHASE_VERIFY, 1.0))
check("★不认识的 phase -> 0（宁可停在 0 也不乱跳）", _vd.overall_percent("zzz", 1.0) == 0)
check("★frac 越界收敛（-1 同 0、9 同 1）",
      _vd.overall_percent(_vd.PHASE_MODEL, -1) == _vd.overall_percent(_vd.PHASE_MODEL, 0)
      and _vd.overall_percent(_vd.PHASE_MODEL, 9) == _vd.overall_percent(_vd.PHASE_MODEL, 1))
_prev, _mono = -1, True
for _sid, _w in _vd.STAGE_WEIGHTS:
    for _f in (0.0, 0.3, 1.0):
        _v = _vd.overall_percent(_sid, _f)
        if _v < _prev:
            _mono = False
        _prev = _v
check("★全程单调不减（逐段采样 18 个点）", _mono and _prev == 100, str(_prev))
check("段权重合 100", sum(w for _, w in _vd.STAGE_WEIGHTS) == 100)

# ---- 源表：把本轮实测纠出来的三处错钉死 ----
_tg = _vd.model_targets()
check("模型目标 = 5 个大权重 + 4 个配套小文件 = 9 个", len(_tg) == 9, str(len(_tg)))
_lid = [t for t in _tg if t["rel"].endswith("lid.176.bin")]
check("★lid.176.bin 走 dl.fbaipublicfiles.com（hf-mirror 上实测 404，曾经写错过）",
      bool(_lid) and _lid[0]["url"].startswith("https://dl.fbaipublicfiles.com/"), str(_lid))
check("★除 lid.176.bin 外其余 8 个全走 hf-mirror（配套小文件与权重在同一个仓库，逐文件可达）",
      len([t for t in _tg if t["url"].startswith(_vd.HF_MODEL_BASE)]) == 8,
      str(len([t for t in _tg if t["url"].startswith(_vd.HF_MODEL_BASE)])))
check("★模型清单与 voice_model.required_model_files() **同源**（rel 集合与总字节都要一致，不许抄两份）",
      {t["rel"] for t in _tg} == set(_vm.required_model_files())
      and sum(t["bytes"] for t in _tg) == _vm.MODEL_TOTAL_BYTES)
check("★★配套小文件必须真的在**下载清单**里 —— 2026-09-27 实测：漏了它们 ⇒ api.py 起不来、"
      "一声不吭，而「已下载」判据却一直是绿的",
      {"chinese-hubert-base/config.json", "chinese-hubert-base/preprocessor_config.json",
       "chinese-roberta-wwm-ext-large/config.json",
       "chinese-roberta-wwm-ext-large/tokenizer.json"} <= {t["rel"] for t in _tg})
check("★pip 索引不含 tuna / ustc（实测 403；首版定稿写的「全通」是错的）",
      all(s not in _vd.PIP_INDEX and s not in _vd.PIP_INDEX_BACKUP for s in ("tuna", "ustc")),
      "%s / %s" % (_vd.PIP_INDEX, _vd.PIP_INDEX_BACKUP))
check("★torch 走 CPU 版索引：主源是 sjtu 镜像（真下 20s 实测 3.0 MB/s，官方只有 0.8 MB/s）",
      "mirror.sjtu.edu.cn/pytorch-wheels/cpu" in _vd.TORCH_INDEX, _vd.TORCH_INDEX)
check("★torch 有官方备用索引（主源挂了要能降级，别把 1.23 GB 卡死在一个源上）",
      _vd.TORCH_INDEX_BACKUP.endswith("/whl/cpu") and _vd.TORCH_INDEX_BACKUP != _vd.TORCH_INDEX,
      _vd.TORCH_INDEX_BACKUP)
_dd = _method_of(_tree_vd, "_Job", "_do_deps")
_dd_names = {n.id for n in ast.walk(_dd) if isinstance(n, ast.Name)}
check("★依赖段真的实现了「主源失败 → 换备用源重试」（两个 BACKUP 常量都要被用到）",
      {"PIP_INDEX_BACKUP", "TORCH_INDEX_BACKUP"} <= _dd_names, str(sorted(_dd_names)))
check("★代码包那段的提示带**已下多少 MB**（codeload 只有 33 KB/s、这段要 ~7 分钟，"
      "只给总百分比会一直停在 0% 像卡死）",
      "已下 %.1f MB" in _src_vd)
check("★依赖清单用 requirements_cpu.txt（requirements.txt 里是 onnxruntime-gpu，本机装的是 cpu 版）",
      _vd.REQUIREMENTS_FILE == "requirements_cpu.txt", _vd.REQUIREMENTS_FILE)
check("★日语 G2P 词典：预期字节 23646843 + URL 指向 open_jtalk_dic（不在 wheel 里，不预下就说不了话）",
      _vd.OPEN_JTALK_BYTES == 23646843 and "open_jtalk_dic" in _vd.OPEN_JTALK_URL
      and "open_jtalk_dic" in _vd.OPEN_JTALK_URL_BACKUP,
      "%s / %s" % (_vd.OPEN_JTALK_BYTES, _vd.OPEN_JTALK_URL))

# ---- 断点续传判据（自己造输入，不联网）----
_t = Path(tempfile.gettempdir()) / "smoke_vd_part.bin"
_t.unlink(missing_ok=True)
Path(str(_t) + _vd.PART_SUFFIX).unlink(missing_ok=True)
check("没有 .part 时续传起点 = 0", _vd.resume_offset(_t) == 0)
Path(str(_t) + _vd.PART_SUFFIX).write_bytes(b"x" * 1234)
check("★有 .part 时续传起点 = 它的现有字节数", _vd.resume_offset(_t) == 1234, str(_vd.resume_offset(_t)))
check("★file_size 对不存在的文件返回 -1（**不是 0** —— 0 是合法的空文件大小）",
      _vd.file_size(_t) == -1)
check("★文件不存在时 size_matches 一律 False（expected=0 也不放过）——「存在且大小对」是**两个**条件",
      _vd.size_matches(_t, 0) is False and _vd.size_matches(_t, 10) is False)
_t.write_bytes(b"y" * 20)
check("★size_matches：字节不等 = 不匹配（下载中断留下的半截文件骗不过去）",
      _vd.size_matches(_t, 10) is False)
check("size_matches：字节相等 = 匹配；expected=0 退化成「只要求存在」",
      _vd.size_matches(_t, 20) and not _vd.size_matches(_t, 21) and _vd.size_matches(_t, 0))
check("★.part 后缀常量是 .part（改名成别的会让「已完成」判断漏掉半截文件）",
      _vd.PART_SUFFIX == ".part")
_t.unlink(missing_ok=True)
Path(str(_t) + _vd.PART_SUFFIX).unlink(missing_ok=True)

# ---- 磁盘预检（两种拒绝都要给话）----
_vd.reset()
_ok1, _m1 = _vd.start({}, root=Path(tempfile.gettempdir()) / "smoke_vd_nope", free_gb=0.1)
check("★空间不足 -> **不启动**并说清还差多少（不让用户等十分钟才失败）",
      _ok1 is False and "空间不足" in _m1, _m1)
_ok2, _m2 = _vd.start({}, root=Path(tempfile.gettempdir()) / "smoke_vd_nope", free_gb=-1)
check("★读不到剩余空间 -> **也拦住**（不把 3.6 GB 写进一个容量未知的盘）",
      _ok2 is False and "读不到" in _m2, _m2)
check("两次拒绝都没有真的起任务", _vd.is_running() is False)
_vd.reset()

# ---- 装机目录：装到「用户指定 → 项目内」，不是历史路径 ----
check("★default_install_dir = 用户目录 → 项目内 runtime/GPT-SoVITS，**不含**历史路径 D:\\GPT-SoVITS"
      "（语义是「全新安装装哪」；取「下载目标」要用 install_root）",
      _vm.default_install_dir({}) == _vm.BASE_DIR / _vm.DEFAULT_DIR_NAME
      and _vm.default_install_dir({}) != Path(_vm.LEGACY_DIRS[0])
      and _vm.default_install_dir({"general": {"model_dir": r"E:\x"}}) == Path(r"E:\x"),
      str(_vm.default_install_dir({})))

# ---- ★★install_root：下载 / 卸载 / 运行时三方的**唯一真值**（用户口径 2026-09-27）----
#   口径原文：「未手动修改过安装位置时默认下载到项目内 runtime\GPT-SoVITS，但本机已在
#   D:\GPT-SoVITS 内安装过，则保留这个位置」。★两半都得测到 —— 只测「项目内」，就会漏掉
#   「D 盘明明能用、点下载却在项目内又造一套」这个**真实故障**（2026-09-27 那次目录混乱的起点）。
_ir_auto = _vm.install_root({})
check("★install_root() 无自定义时只在「项目内 / 历史路径」里挑",
      _ir_auto in [_vm.BASE_DIR / _vm.DEFAULT_DIR_NAME]
      + [Path(x) for x in _vm.LEGACY_DIRS], str(_ir_auto))
check("★★install_root() 若挑中了历史路径，那它必须**真的像安装根**（绝不指到一个空壳目录）",
      _ir_auto == _vm.BASE_DIR / _vm.DEFAULT_DIR_NAME or _vm.looks_like_install_root(_ir_auto),
      "%s / looks_like=%s" % (_ir_auto, _vm.looks_like_install_root(_ir_auto)))
check("★install_root：用户显式指定**无条件优先**，哪怕那儿还没装东西（那正是「我想装到这儿」）",
      _vm.install_root({"general": {"model_dir": r"E:\x"}}) == Path(r"E:\x"))
check("★install_root 与 default_install_dir 在「有自定义」时必须同值（否则下载 / 卸载是两处）",
      _vm.install_root({"general": {"model_dir": r"E:\x"}})
      == _vm.default_install_dir({"general": {"model_dir": r"E:\x"}}))
check("★venv_python / VENV_PY_REL = Windows venv 布局（.venv/Scripts/python.exe）",
      _vm.VENV_PY_REL == ".venv/Scripts/python.exe"
      and _vm.venv_python(r"D:\x") == Path(r"D:\x") / ".venv" / "Scripts" / "python.exe")
check("★下载侧的 venv_python 就是 voice_model 那一份（同一条路径别各写一遍）",
      _vd.venv_python(r"D:\x") == _vm.venv_python(r"D:\x"))

# ---- looks_like_install_root：三条正向证据 + 一条**否定**指纹（拿真目录测，不靠假想）----
import shutil  # noqa: E402  （块末清理临时目录用）
_smk = Path(tempfile.mkdtemp(prefix="ignotus_smoke_root_"))
_full = _smk / "full"            # 代码体 + venv 都在 ⇒ 「卸载后重装」的常态
(_full / "GPT_SoVITS").mkdir(parents=True)
(_full / "api.py").write_text("x", encoding="utf-8")
(_full / ".venv" / "Scripts").mkdir(parents=True)
(_full / ".venv" / "Scripts" / "python.exe").write_text("x", encoding="utf-8")
_bare = _smk / "bare"            # 只有 api.py
_bare.mkdir()
(_bare / "api.py").write_text("x", encoding="utf-8")
_venv_only = _smk / "venvonly"   # 只有 venv（没 api.py）
(_venv_only / ".venv" / "Scripts").mkdir(parents=True)
(_venv_only / ".venv" / "Scripts" / "python.exe").write_text("x", encoding="utf-8")
_empty = _smk / "empty"
_empty.mkdir()
_nest = _smk / "nested"          # ★「装机装错」的那一种：位置被指到了仓库子目录
(_nest / "GPT_SoVITS" / "GPT_SoVITS").mkdir(parents=True)
(_nest / "api.py").write_text("x", encoding="utf-8")
(_nest / ".venv" / "Scripts").mkdir(parents=True)
(_nest / ".venv" / "Scripts" / "python.exe").write_text("x", encoding="utf-8")

check("★有 api.py ⇒ 像安装根", _vm.looks_like_install_root(_bare) is True)
check("★只有 .venv/Scripts/python.exe（没 api.py）⇒ 也算安装根"
      "（「模型装在 A、代码体在 B」的半拉子状态真机上出现过）",
      _vm.looks_like_install_root(_venv_only) is True)
check("★代码体 + venv 齐 ⇒ 像安装根", _vm.looks_like_install_root(_full) is True)
check("★空目录**不算**安装根（否则随便一个目录都能把下载目标骗走）",
      _vm.looks_like_install_root(_empty) is False)
check("★不存在的目录不算安装根", _vm.looks_like_install_root(_smk / "nope") is False)
check("★嵌套指纹常量 = GPT_SoVITS/GPT_SoVITS（改了这个判据就废）",
      _vm.NESTED_MARK_REL == "GPT_SoVITS/GPT_SoVITS", _vm.NESTED_MARK_REL)
check("★★「装机装错」的目录**不算**安装根 —— 指纹 `GPT_SoVITS/GPT_SoVITS` 存在即否。"
      "不带这条的话，误装目录因为同时有 api.py 与 .venv 会一路假绿到底",
      _vm.looks_like_install_root(_nest) is False)
check("★install_root：用户把位置指到装错的目录上时**原样返回、不静默改道**"
      "（界面上那一行就写着这个错目录 ⇒ 用户看得出来，自己改掉）",
      _vm.install_root({"general": {"model_dir": str(_nest)}}) == _nest)

# ---- 下载确认框文案：全量 **3 行** / 仅模型 **2 行**（用户口径 2026-09-27）----
check("★voice_download.py 里**没有** 3.6 这个浮点字面量"
      "（体积常量只许引用 voice_model 的，各写一份就会静默漂移）",
      [n.value for n in ast.walk(_tree_vd)
       if isinstance(n, ast.Constant) and isinstance(n.value, float)
       and n.value == 3.6] == [],
      str([n.value for n in ast.walk(_tree_vd)
           if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value == 3.6]))
check("★voice_download.FULL_DOWNLOAD_GB == voice_model.FULL_INSTALL_GB == 3.6"
      "（唯一定义在 voice_model）",
      _vd.FULL_DOWNLOAD_GB == _vm.FULL_INSTALL_GB == 3.6,
      "%s / %s" % (_vd.FULL_DOWNLOAD_GB, _vm.FULL_INSTALL_GB))
_full_msg = _vd.confirm_message(True)
_lean_msg = _vd.confirm_message(False)
check("★★全量确认框 = 三行，**中间那行**就是用户逐字给的「此次下载为全量下载，共约 3.6 GB」",
      _full_msg == "合成语音时将大幅减缓AI回复速度\n此次下载为全量下载，共约 3.6 GB\n是否下载？",
      repr(_full_msg))
check("★★只下模型时 = 两行，中间那行**不出现**（否则用户会以为又要下 3.6 GB 的东西）",
      _lean_msg == "合成语音时将大幅减缓AI回复速度\n是否下载？" and "全量" not in _lean_msg,
      repr(_lean_msg))
check("★文案里的体积数字与常量同源（改常量不改文案 ⇒ 弹窗对用户说假话）",
      ("%.1f GB" % _vd.FULL_DOWNLOAD_GB) in _full_msg)
check("★FULL_NOTICE 就是中间那一行（单独成常量，别在别处再拼一遍）",
      _vd.FULL_NOTICE == "此次下载为全量下载，共约 3.6 GB", repr(_vd.FULL_NOTICE))
check("★confirm_message 是纯函数：连调两次结果一致（没有隐藏状态）",
      _vd.confirm_message(True) == _full_msg and _vd.confirm_message(False) == _lean_msg)

# ---- is_full_install：必须跟下载流水线**实际跳不跳段**用同一个判据（probe_layers 的 full）----
check("★空目录 ⇒ 全量（代码 / venv / 依赖 / 模型一起下）",
      _vd.is_full_install(root=_empty) is True)
check("★代码体 + venv 都在 ⇒ **不是**全量（只补模型那 1.15 GB）",
      _vd.is_full_install(root=_full) is False)
check("★只给 cfg 不给 root 时，看的是 install_root(cfg)",
      _vd.is_full_install({"general": {"model_dir": str(_full)}}) is False
      and _vd.is_full_install({"general": {"model_dir": str(_empty)}}) is True)
check("★is_full_install 与 probe_layers 的 full 同源（不是另算一套判据）",
      _vd.is_full_install(root=_empty) == bool(_vd.probe_layers(_empty)["full"])
      and _vd.is_full_install(root=_full) == bool(_vd.probe_layers(_full)["full"]))

# ---- ★★「沿用本机已有安装」必须**真的验一次**（不然这条需求一条断言都没钉住）----
#   上面那两条只证明「挑中的那个在候选集合里」—— 而 `install_root` 直接 return 项目内也满足
#   那个集合 ⇒ 改坏了照样绿。这里把历史路径**临时指到我们造的那个安装根**上真跑一遍。
_orig_legacy, _orig_base = _vm.LEGACY_DIRS, _vm.BASE_DIR
try:
    _vm.LEGACY_DIRS = (str(_full),)
    _vm.BASE_DIR = _smk                 # 项目内候选 = _smk/runtime/GPT-SoVITS → 不存在
    check("★★「本机已有可用安装」时 install_root **沿用那一份**（用户口径：已在 D:\\GPT-SoVITS "
          "装过就保留这个位置；不会去项目内另造一套）",
          _vm.install_root({}) == _full, str(_vm.install_root({})))
    _vm.LEGACY_DIRS = (str(_empty),)    # 历史路径是个**空壳**
    check("★★历史路径是个空壳目录时**不许挑**（否则一台从没装过的机器会被指到 D:\\GPT-SoVITS "
          "去建一套出来）—— 落到全新安装的目标（项目内）",
          _vm.install_root({}) == _smk / _vm.DEFAULT_DIR_NAME, str(_vm.install_root({})))
    _vm.LEGACY_DIRS = (str(_nest),)     # 历史路径是那个**装错**的目录
    check("★★历史路径带着嵌套指纹时也不挑（装错的那一份不算「已有可用安装」）",
          _vm.install_root({}) == _smk / _vm.DEFAULT_DIR_NAME, str(_vm.install_root({})))
finally:
    _vm.LEGACY_DIRS, _vm.BASE_DIR = _orig_legacy, _orig_base
shutil.rmtree(_smk, ignore_errors=True)

# ---- 三态文字 ----
check("状态文字三态：未下载 / 下载中　42% / 已下载",
      _vd.progress_text({"running": False, "done": False}) == "未下载"
      and _vd.progress_text({"running": True, "done": False, "percent": 42}) == "下载中　42%"
      and _vd.progress_text({"running": False, "done": True}) == "已下载")

# ---- 接线：核**身份** + AST（注释骗不了 AST）----
_row = gen._model_row
check("★「下载」按钮回调身份就是 GeneralPanel._download_model",
      _row._on_download.__func__ is gui.GeneralPanel._download_model)
check("★「卸载」按钮回调身份就是 GeneralPanel._uninstall_model",
      _row._on_uninstall.__func__ is gui.GeneralPanel._uninstall_model)
check("轮询间隔 = 200ms（GeneralPanel.DOWNLOAD_POLL_MS）",
      gen._dl_timer.interval() == gui.GeneralPanel.DOWNLOAD_POLL_MS == 200,
      "%s / %s" % (gen._dl_timer.interval(), gui.GeneralPanel.DOWNLOAD_POLL_MS))
_gp_init = _method_of(_tree_g, "GeneralPanel", "__init__")
check("★__init__ 把 timeout 接到了 _poll_download（不是别的开关）",
      _gp_init is not None
      and "_poll_download" in {n.attr for n in ast.walk(_gp_init) if isinstance(n, ast.Attribute)})
_dm = _method_of(_tree_g, "GeneralPanel", "_download_model")
_dm_calls = {(c.func.value.id, c.func.attr) for c in ast.walk(_dm)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
             and isinstance(c.func.value, ast.Name)}
check("★_download_model 真的调 voice_download.start(...)（AST 按「模块.方法」精确匹配）",
      ("voice_download", "start") in _dm_calls, str(sorted(_dm_calls)))
check("★_download_model 先看 is_running（下载中再点 = 分流去「取消」，不会起第二次下载）",
      ("voice_download", "is_running") in _dm_calls and ("self", "_cancel_download") in _dm_calls,
      str(sorted(_dm_calls)))
# ★★下载前的确认框（2026-09-27 用户要求「点击确认后才正式开始下载」）。
#   两条断言都得有：**过没过确认框** + **确认框在 start 之前**。
#   ★后者按 `lineno` 比，不按「写法出现的先后」——注释里也写着 `voice_download.start`，
#     拿字符串 / 行序核一律假绿（docs/04 §4 硬清单）。
_dm_ln = {}
for _n in ast.walk(_dm):
    if isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute) \
            and isinstance(_n.func.value, ast.Name):
        _dm_ln.setdefault((_n.func.value.id, _n.func.attr), _n.lineno)
check("★_download_model 里真的过 ConfirmDialog.confirm（AST 按「类.方法」精确匹配）",
      ("ConfirmDialog", "confirm") in _dm_ln, str(sorted(_dm_ln)))
check("★确认框排在 voice_download.start **之前**（按 lineno 比；插在 start 之后等于没拦）",
      _dm_ln.get(("ConfirmDialog", "confirm"), 9999) < _dm_ln.get(("voice_download", "start"), 0),
      str({k: v for k, v in _dm_ln.items() if k[1] in ("confirm", "start")}))
_cd = _method_of(_tree_g, "GeneralPanel", "_cancel_download")
_cd_calls = {(c.func.value.id, c.func.attr) for c in ast.walk(_cd)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
             and isinstance(c.func.value, ast.Name)}
check("★_cancel_download 里真的调 voice_download.cancel()",
      ("voice_download", "cancel") in _cd_calls, str(sorted(_cd_calls)))
_ams = _method_of(_tree_g, "GeneralPanel", "_apply_model_state")
check("★_apply_model_state 先看下载中（voice_download.snapshot），下载期间不显示「已下载」",
      ("voice_download", "snapshot") in
      {(c.func.value.id, c.func.attr) for c in ast.walk(_ams)
       if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
       and isinstance(c.func.value, ast.Name)})
_ads = _method_of(_tree_g, "GeneralPanel", "_apply_download_state")
_ads_kw = {(k.arg, getattr(k.value, "value", None)) for c in ast.walk(_ads)
           if isinstance(c, ast.Call) for k in c.keywords}
_ads_strs = [n.value for n in ast.walk(_ads) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
check("★下载中把「下载」按钮文字改成「取消」、并传 `download=True` 让它**保持可用**",
      "取消" in _ads_strs and ("download", True) in _ads_kw, "%s / %s" % (_ads_strs, sorted(_ads_kw)))
check("★下载中「卸载」按钮必须禁用（传 download/uninstall 两个关键字）",
      ("uninstall", False) in _ads_kw, str(sorted(_ads_kw)))
_um = _method_of(_tree_g, "GeneralPanel", "_uninstall_model")
_um_ln = {n.func.attr: n.lineno for n in ast.walk(_um)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check("★_uninstall_model 的「下载中」守卫排在取模型目录**之前**（否则可能删到正在下的目录）",
      _um_ln.get("is_running", 9999) < _um_ln.get("model_dir", 0),
      str({k: v for k, v in _um_ln.items() if k in ("is_running", "model_dir")}))

# ★★2026-09-27：卸载弹窗换成**三选一**。三条硬要求：
#   ① 必须走 `ChoiceDialog.choose`（`ConfirmDialog` 只回两值，「用户选了哪一档」在类型上
#      就表达不出来）；② 弹窗必须排 `voice_model.uninstall` **之前**；③ 删完必须刷新界面。
_um_calls = {(c.func.value.id, c.func.attr) for c in ast.walk(_um)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
             and isinstance(c.func.value, ast.Name)}
check("★★_uninstall_model 走 ChoiceDialog.choose（**三选一**），不再用 ConfirmDialog"
      "（它只回「接受/拒绝」，表达不了三档）",
      ("ChoiceDialog", "choose") in _um_calls
      and ("ConfirmDialog", "confirm") not in _um_calls,
      str(sorted(_um_calls)))
check("★弹窗文案来自 voice_model.uninstall_message(cfg)（纯函数；不在 gui 里拼字符串）",
      ("voice_model", "uninstall_message") in _um_calls, str(sorted(_um_calls)))
check("★卸载后真的调 _apply_model_state()（否则行上还写着「已下载」）",
      ("self", "_apply_model_state") in _um_calls, str(sorted(_um_calls)))
_um_ln2 = {}
for _n in ast.walk(_um):
    if isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute) \
            and isinstance(_n.func.value, ast.Name):
        _um_ln2.setdefault((_n.func.value.id, _n.func.attr), _n.lineno)
check("★弹窗排在 voice_model.uninstall **之前**（按 lineno 比；插在 uninstall 后面等于没拦）",
      _um_ln2.get(("ChoiceDialog", "choose"), 9999)
      < _um_ln2.get(("voice_model", "uninstall"), 0),
      str({k: v for k, v in _um_ln2.items() if k[1] in ("choose", "uninstall")}))
# ★三条：`chosen` 必须**原样**转交给 `uninstall()`，且档位判定用的是**常量**属性访问
#   （不是 gui 里写死的 `'model'` / `'all'` 字面量 —— 那样常量改了它不知道）。
_um_attrs = {(n.value.id, n.attr) for n in ast.walk(_um)
             if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
check("★★档位用的是 voice_model 的常量属性（UNINSTALL_MODEL / UNINSTALL_ALL），"
      "gui 里不许再写 'model' / 'all' 字面量",
      ("voice_model", "UNINSTALL_MODEL") in _um_attrs
      and ("voice_model", "UNINSTALL_ALL") in _um_attrs,
      str(sorted(_um_attrs)))
_um_strs = sorted(n.value for n in ast.walk(_um)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str))
check("★gui 里**没有** 'model' / 'all' 这两个字符串字面量"
      "（它们在 gui 里出现就说明又多了一份「字符串 key ↔ 常量」的翻译）",
      "model" not in _um_strs and "all" not in _um_strs,
      str([s for s in _um_strs if s in ("model", "all")]))
check("★三按钮文案 = 「仅模型卸载」「全部卸载」（取消那颗由 ChoiceDialog 统一给「取消」）",
      "仅模型卸载" in _um_strs and "全部卸载" in _um_strs,
      str([s for s in _um_strs if "卸载" in s]))
check("★ChoiceDialog 卡片宽 440 > ConfirmDialog 的 360（用户口径「弹窗的宽度可以适当加宽」）",
      gui.ChoiceDialog.CARD_W == 440 and gui.ConfirmDialog.CARD_W == 360
      and gui.ChoiceDialog.CARD_W > gui.ConfirmDialog.CARD_W,
      "%s / %s" % (gui.ChoiceDialog.CARD_W, gui.ConfirmDialog.CARD_W))
check("★ChoiceDialog 的入口是**静态方法** choose()（回 key 或 None），别写成实例方法",
      isinstance(gui.ChoiceDialog.__dict__.get("choose"), staticmethod)
      and isinstance(gui.ConfirmDialog.__dict__.get("confirm"), staticmethod))
check("★ChoiceDialog 也是 QDialog 子类（`exec()` 才拦得住模态交互）",
      issubclass(gui.ChoiceDialog, gui.QDialog))
_choice_src = _src_gui_vol[_src_gui_vol.index("class ChoiceDialog"):
                           _src_gui_vol.index("class InputDialog")]
check("★ChoiceDialog 的按钮 key 用默认参数钉住（`lambda _=False, k=key: ...`）"
      "—— 闭包直接捕获 `key` 会让三颗按钮全指向最后一个",
      "k=key" in _choice_src, str("k=key" in _choice_src))

# ---- 行为层：真的切到「下载中」，看行上呈现什么 ----
_orig_snap, _orig_cancel, _orig_start = _vd.snapshot, _vd.cancel, _vd.start
_orig_installed = _vm.is_installed
_vd_cancel_calls, _vd_start_calls = [], []
_START_RET = [(True, "开始下载。")]


def _fake_start(*a, **k):
    """替身 `voice_download.start`：记下 (args, kwargs) 并返回可切换的结果。

    ★统一用「一个可变的返回值容器」而不是每次重新赋一个 lambda —— 前面就踩过：
    两处 patch 各写一个 lambda，一处 `append(a)`、一处 `append((a, k))`，
    后面按 `[0][1]` 取 kwargs 就炸 `IndexError`。
    ★成功时**必须把快照改成 running**：真的 `start()` 会起线程，紧接着的 `snapshot()`
    就是「下载中」。替身少了这一步 ⇒ `_download_model` 里那句「立刻进下载中态」
    永远看到 idle（本轮实测：会留下一条假绿）。
    """
    global _fake
    _vd_start_calls.append((a, k))
    ok, msg = _START_RET[0]
    if ok:
        _fake = {"running": True, "done": False, "error": "", "cancelled": False,
                 "phase": "code", "percent": 0, "message": "正在下载程序主体",
                 "skipped": "", "root": str(k.get("root") or "")}
    return ok, msg
_fake = {"running": True, "done": False, "error": "", "cancelled": False,
         "phase": "model", "percent": 42,
         "message": "正在下载音色克隆模型（3/5）：s2G2333k.pth", "skipped": "", "root": ""}

# ★★下载/卸载前的确认框都必须**换成桩**：`ConfirmDialog.confirm` 与 `ChoiceDialog.choose`
#   都是**模态 `exec()`**，不换的话这一段会卡在弹窗上永远不返回 —— 在 `run_all` 里表现成
#   「这套超时 300s 被强杀」，看着像逻辑挂了（和 `smoke_pet` 那处已知时序赛跑同一种表象，
#   别混淆）。桩顺手把「用户实际看到的文案」记下来，供下面做行为层断言（比断言源码里写了
#   什么强）。
class _StubConfirmDl:
    calls, answer = [], True

    def __init__(self, *a, **k):
        pass

    @staticmethod
    def confirm(parent, message, *a, **k):
        _StubConfirmDl.calls.append(message)
        return _StubConfirmDl.answer


class _StubChoiceDl:
    """`ChoiceDialog` 的替身 —— **必须跟 `ConfirmDialog` 一起换掉**。

    它同理是**模态 `exec()`**：不换的话，`_uninstall_model` 那条路一旦走到弹窗就会永远
    不返回（`run_all` 里表现成「这套超时 300s 被强杀」，看着像逻辑挂了）。
    ★这一段里 `_uninstall_model()` 本来被「下载中」守卫提前拦住、走不到弹窗 —— 但那依赖
      「守卫排在前面」这个**实现细节**。桩先换好，以后谁调整顺序都不会把测试挂死。
    """

    calls, answer = [], None

    def __init__(self, *a, **k):
        pass

    @staticmethod
    def choose(parent, message, choices, cancel_text="取消"):
        _StubChoiceDl.calls.append((message, choices, cancel_text))
        return _StubChoiceDl.answer


# ★这次点「下载」应当看到**哪一版**文案 —— 按当前真机的全量判据**现算**，别在断言里写死
#   「两行」：本机 `D:\GPT-SoVITS` 是一份可用安装 ⇒ 只需补模型 ⇒ 两行；换一台从没装过的
#   机器就是三行。写死任一种都是「换机即假红 / 掩盖回归后仍假绿」。
def _expected_confirm(cfg):
    return _vd.confirm_message(_vd.is_full_install(cfg, _vm.install_root(cfg)))


_orig_confirm_dl = gui.ConfirmDialog
_orig_choice_dl = gui.ChoiceDialog
gui.ConfirmDialog = _StubConfirmDl
gui.ChoiceDialog = _StubChoiceDl
try:
    _vd.snapshot = lambda: dict(_fake)
    _vd.cancel = lambda: _vd_cancel_calls.append(1)
    _vd.start = _fake_start
    gen._apply_model_state()
    check("下载中：状态文字变成 `下载中　42%`", _row.state_text() == "下载中　42%", _row.state_text())
    check("★下载中：「下载」按钮文字变「取消」且**仍可用**（3.5 GB 要能停）",
          _row.download_text() == "取消" and _row.download_enabled() is True,
          "%s / %s" % (_row.download_text(), _row.download_enabled()))
    check("下载中：「卸载」按钮禁用", _row.uninstall_enabled() is False)
    check("下载中：hint 显示当前阶段（不再是空串、也不隐藏）",
          "音色克隆模型" in _row._hint_text and not _row._hint.isHidden(), _row._hint_text)
    check("★下载中静音滑块照样锁死在开（模型还没落地）",
          gen._mute_row.is_locked() is True and cfg["general"].get("mute_mode") is True)
    check("★下载中 `_apply_model_state()` 返回 False（不当作「已安装」）",
          gen._apply_model_state() is False)
    check("切页面回来能补启动轮询表", gen._dl_timer.isActive() is True)

    # 真的点一下那颗按钮 = 调 cancel（不是又起一次下载）
    _row._download_btn.click()
    check("★下载中点那颗按钮 -> voice_download.cancel() 被调 1 次",
          _vd_cancel_calls == [1], str(_vd_cancel_calls))
    check("★没有误启动第二次下载", _vd_start_calls == [], str(_vd_start_calls))
    # ★这颗按钮此刻的文字是「取消」⇒ 它**必须不弹**确认框。若哪天有人把确认框提到
    #   `is_running()` 分流**之前**，用户点「取消」就会被问「是否下载？」，荒谬但很容易写错。
    check("★下载中那颗「取消」不弹确认框（确认框只拦「真正要开始下载」这一支）",
          _StubConfirmDl.calls == [], str(_StubConfirmDl.calls))

    # 下载中点「卸载」要被拦住
    _before_msg = gen._msg_label.text()
    gen._uninstall_model()
    check("★下载中点「卸载」被拦下并说明原因（不会真去删目录）",
          "取消" in gen._msg_label.text() and gen._msg_label.text() != _before_msg,
          gen._msg_label.text())
    check("★被拦住时**根本没弹**卸载弹窗（守卫先于 ChoiceDialog；否则等于拿用户在下载中的目录去问三选一）",
          _StubChoiceDl.calls == [], str(_StubChoiceDl.calls))

    # 跑完 -> 回落「已下载」并解锁
    _fake = {"running": False, "done": True, "error": "", "cancelled": False,
             "phase": "done", "percent": 100, "message": "下载完成", "skipped": "", "root": ""}
    _vm.is_installed = lambda cfg: True
    gen._poll_download()
    check("★下载完：状态「已下载」+ 下载禁用 / 卸载可用 + 按钮文字回到「下载」",
          _row.state_text() == "已下载" and _row.download_enabled() is False
          and _row.uninstall_enabled() is True and _row.download_text() == "下载",
          "%s/%s/%s/%s" % (_row.state_text(), _row.download_enabled(),
                           _row.uninstall_enabled(), _row.download_text()))
    check("★下载完：静音**解锁但值仍是「开」**（不突然出声，由用户自己关）",
          gen._mute_row.is_locked() is False and cfg["general"].get("mute_mode") is True)
    check("下载完：轮询表停掉", gen._dl_timer.isActive() is False)
    check("下载完：hint 清空", _row._hint_text == "", _row._hint_text)

    # 失败 -> 回「未下载」并重新锁死
    _vm.is_installed = lambda cfg: False
    _fake = {"running": False, "done": False, "error": "下载模型文件失败：s2G2333k.pth",
             "cancelled": False, "phase": "model", "percent": 50, "message": "",
             "skipped": "", "root": ""}
    gen._poll_download()
    check("★失败：回「未下载」+ 静音重新锁死 + 按钮文字回「下载」",
          _row.state_text() == "未下载" and gen._mute_row.is_locked() is True
          and _row.download_text() == "下载")

    # 取消 -> 提示文案不含「error」色
    _fake = {"running": False, "done": False, "error": "", "cancelled": True,
             "phase": "idle", "percent": 0, "message": "", "skipped": "", "root": ""}
    gen._poll_download()
    check("取消：提示「已取消」而不是错误", "已取消" in gen._msg_label.text(), gen._msg_label.text())

    # ★★点「下载」先弹确认框 —— **点「取消」⇒ 一个字都没开始**（2026-09-27 用户要求）
    _vd_start_calls.clear()
    _StubConfirmDl.calls[:] = []
    _StubConfirmDl.answer = False
    _fake = {"running": False, "done": False, "error": "", "cancelled": False,
             "phase": "idle", "percent": 0, "message": "", "skipped": "", "root": ""}
    gen._dl_timer.stop()
    gen._apply_model_state()
    _row_before = (_row.state_text(), _row.download_text())
    gen._download_model()
    _dl_msg = _expected_confirm(cfg)
    check("★确认框文案 = 按**当前装机目录的全量判据**生成的那一版"
          "（换行是文案里写死的 `\\n`，不是自动折行；全量三行 / 仅模型两行）",
          _StubConfirmDl.calls == [_dl_msg],
          "%s / %s" % (str(_StubConfirmDl.calls), repr(_dl_msg)))
    check("★这一版文案**必须是两个合法变体之一**（不许出现第三种随手拼的串）",
          _dl_msg in (_vd.confirm_message(True), _vd.confirm_message(False)), repr(_dl_msg))
    check("★点「取消」⇒ 完全不启动下载（不调 voice_download.start）",
          _vd_start_calls == [], str(_vd_start_calls))
    check("★点「取消」⇒ 不起轮询表、行上状态一个字不改（仍是「未下载」）",
          gen._dl_timer.isActive() is False
          and (_row.state_text(), _row.download_text()) == _row_before
          and _row.state_text() == "未下载",
          "%s / %s" % (gen._dl_timer.isActive(), (_row.state_text(), _row.download_text())))

    # 后面两条要的是「确认之后」这一支
    _StubConfirmDl.answer = True

    # 点「下载」-> 真的调 voice_download.start（**装机目录**必须是 install_root）
    _vd_start_calls.clear()
    _fake = {"running": False, "done": False, "error": "", "cancelled": False,
             "phase": "idle", "percent": 0, "message": "", "skipped": "", "root": ""}
    gen._dl_timer.stop()
    gen._msg_label.setText("")
    _START_RET[0] = (False, "磁盘空间不足：还剩 0.5 GB，这次需要约 6.0 GB。")
    gen._download_model()
    check("★点「下载」真的调了 voice_download.start()（不是只弹提示）",
          len(_vd_start_calls) == 1, str(_vd_start_calls))
    check("★★装机目录来自 install_root(cfg)（用户指定 → 本机已有安装 → 项目内），"
          "**不是** default_install_dir —— 后者不含历史路径，会出现"
          "「D:\\GPT-SoVITS 明明能用、点下载却在项目内又造一套」",
          bool(_vd_start_calls)
          and str(_vd_start_calls[0][1].get("root")) == str(_vm.install_root(cfg)),
          str(_vd_start_calls[0][1] if _vd_start_calls else None))
    check("★预检失败 -> 用错误色提示，且**不启动轮询表**",
          "空间不足" in gen._msg_label.text() and gen._dl_timer.isActive() is False,
          "%s / %s" % (gen._msg_label.text(), gen._dl_timer.isActive()))

    # 预检通过 -> 起表 + 立刻进「下载中」态
    # ★调用前 `_fake` 必须是 **idle**：「正在下载时点『下载』= 走取消」是另一条断言；
    #   这里要的是「从静止态点下载」。running 由 `_fake_start` 在成功后自己切过去
    #   （模拟真 start() 起线程）—— 本轮先设成 running 再点，正好踩了这个坑。
    _START_RET[0] = (True, "开始下载。")
    _fake = {"running": False, "done": False, "error": "", "cancelled": False,
             "phase": "idle", "percent": 0, "message": "", "skipped": "", "root": ""}
    _StubConfirmDl.calls[:] = []      # 只数这一次
    _vd_start_calls.clear()           # ★上一条（预检失败）也调过 start，不清就数成 2
    gen._download_model()
    check("★预检通过 -> 启动轮询表并**立刻**进「下载中」态（不等第一次 tick）",
          gen._dl_timer.isActive() is True and _row.state_text().startswith("下载中"),
          "%s / %s" % (gen._dl_timer.isActive(), _row.state_text()))
    check("★这一支（静止态点「下载」）确实**先问过**确认框，才去调 start",
          _StubConfirmDl.calls == [_dl_msg] and len(_vd_start_calls) == 1,
          "%s / %s" % (str(_StubConfirmDl.calls), str(_vd_start_calls)))
finally:
    _vd.snapshot, _vd.cancel, _vd.start = _orig_snap, _orig_cancel, _orig_start
    _vm.is_installed = _orig_installed
    gui.ConfirmDialog = _orig_confirm_dl
    gui.ChoiceDialog = _orig_choice_dl
    _StubConfirmDl.answer = True       # 桩是类属性：别把 False 留给后面几段
    _StubConfirmDl.calls[:] = []
    _StubChoiceDl.answer = None        # 同上：默认「取消」，别把档位留给后面几段
    _StubChoiceDl.calls[:] = []
    gen._dl_timer.stop()
    gen.refresh()          # 把面板恢复成真实状态，别把假快照留给后面几段


# ========== 5h. 语音模型·卸载三选一（两档各自走通）==========
#   ★5g 里那一下 `_uninstall_model()` 被「下载中」守卫挡掉了 ⇒ 三选一弹窗**一次都没真跑过**。
#     这一段补上：三颗按钮分别对应什么行为、每档各删什么、文案从哪来。
print("== 5h. 语音模型·卸载三选一 ==")
_orig_ir, _orig_md, _orig_un, _orig_inst = (
    _vd.is_running, _vm.model_dir, _vm.uninstall, _vm.is_installed)
_orig_confirm_5h, _orig_choice_5h = gui.ConfirmDialog, gui.ChoiceDialog
_un_calls = []
# ★★**两个**对话框都要换桩，不是只换 `ChoiceDialog`：这一段真的会在弹窗上跑，而「实现里到底
#   弹哪一个」正是它要验的事 —— 只桩 `ChoiceDialog` 的话，若哪天这段代码改用 `ConfirmDialog`
#   （`rev28` 的 N1 就是照着这个改的），本节不会给出「换了弹窗」的**红**，而是**卡在模态
#   `exec()` 上永不返回** ⇒ 在 runner 里表现成「这套超时 300s 被强杀」，看着像逻辑挂了。
#   ★这是 `docs/04` §4 那条「多选一弹窗先换桩」的**反面**：不是「只换 ConfirmDialog 不够」，
#     而是「只换 ChoiceDialog 同样不够」—— 一句话：**这一段可能碰到的弹窗，一个都不能漏**。
gui.ConfirmDialog = _StubConfirmDl
gui.ChoiceDialog = _StubChoiceDl
try:
    check("（前提）5h 段里**两个**对话框都换成了桩 —— 漏一个的话，那段改动只会「挂着不动」"
          "而不是「变红」（反向验证时真踩过）",
          gui.ConfirmDialog is _StubConfirmDl and gui.ChoiceDialog is _StubChoiceDl)
    _vd.is_running = lambda: False                      # 守卫放行
    _vm.model_dir = lambda cfg: Path(r"D:\fake\GPT_SoVITS\pretrained_models")   # 非 None
    _vm.uninstall = lambda cfg, mode: (_un_calls.append(mode), True)[1]
    _vm.is_installed = lambda cfg: False                # 卸载完 → 回「未下载」
    gen._apply_model_state()

    # ①（前置）model_dir 为 None ⇒ 不弹窗、直接说「没有可卸载的模型」
    _vm.model_dir = lambda cfg: None
    _StubChoiceDl.calls[:] = []
    _un_calls.clear()
    gen._uninstall_model()
    check("★探测不到模型 ⇒ **不弹窗**、不调 uninstall，直接说「没有找到可卸载的模型」",
          _StubChoiceDl.calls == [] and _un_calls == []
          and "没有找到可卸载的模型" in gen._msg_label.text(),
          "%s / %s / %s" % (str(_StubChoiceDl.calls), str(_un_calls), gen._msg_label.text()))
    _vm.model_dir = lambda cfg: Path(r"D:\fake\GPT_SoVITS\pretrained_models")

    # ②点「取消」⇒ 一个字都不动
    _StubChoiceDl.calls[:] = []
    _un_calls.clear()
    _StubChoiceDl.answer = None
    gen._uninstall_model()
    check("★弹窗文案来自 voice_model.uninstall_message(cfg)（纯函数，不是 gui 里拼的）",
          len(_StubChoiceDl.calls) == 1
          and _StubChoiceDl.calls[0][0] == _vm.uninstall_message(cfg),
          str(_StubChoiceDl.calls[0][0] if _StubChoiceDl.calls else None))
    check("★三颗按钮 = 取消(隐含) + 仅模型卸载 + 全部卸载，且 key **就是**档位常量",
          bool(_StubChoiceDl.calls)
          and _StubChoiceDl.calls[0][1] == [(_vm.UNINSTALL_MODEL, "仅模型卸载", "primary"),
                                            (_vm.UNINSTALL_ALL, "全部卸载", "danger")]
          and _StubChoiceDl.calls[0][2] == "取消",
          str(_StubChoiceDl.calls[0][1] if _StubChoiceDl.calls else None))
    check("★★点「取消」（回 None）⇒ **完全不调 uninstall**，并提示「已取消卸载」",
          _un_calls == [] and "已取消卸载" in gen._msg_label.text(),
          "%s / %s" % (str(_un_calls), gen._msg_label.text()))

    # ③选「仅模型卸载」⇒ mode 原样传 UNINSTALL_MODEL
    _un_calls.clear()
    _StubChoiceDl.answer = _vm.UNINSTALL_MODEL
    gen._uninstall_model()
    check("★选「仅模型卸载」⇒ 调用 voice_model.uninstall(cfg, UNINSTALL_MODEL)（原样转交，不翻译）",
          _un_calls == [_vm.UNINSTALL_MODEL], str(_un_calls))
    check("★仅模型档的完成提示说的是「模型已卸载」",
          "模型已卸载" in gen._msg_label.text(), gen._msg_label.text())

    # ④选「全部卸载」⇒ mode 原样传 UNINSTALL_ALL，且提示里点出**保留了什么**
    _un_calls.clear()
    _StubChoiceDl.answer = _vm.UNINSTALL_ALL
    gen._uninstall_model()
    check("★选「全部卸载」⇒ 调用 voice_model.uninstall(cfg, UNINSTALL_ALL)",
          _un_calls == [_vm.UNINSTALL_ALL], str(_un_calls))
    check("★★全部卸载的完成提示**明确告诉用户 refs / ffmpeg.exe / .git 被保留了**"
          "（两档都叫「卸载」，不点出来用户不知道自己的东西还在不在）",
          "已全部卸载" in gen._msg_label.text() and "refs" in gen._msg_label.text()
          and "ffmpeg.exe" in gen._msg_label.text() and ".git" in gen._msg_label.text(),
          gen._msg_label.text())

    # ⑤两个档位都删不掉（被占用）⇒ 说清「可稍后重试」，不当成功
    _un_calls.clear()
    _vm.uninstall = lambda cfg, mode: (_un_calls.append(mode), False)[1]
    gen._uninstall_model()
    check("★uninstall 返回 False ⇒ 提示「卸载没有完成 … 可稍后重试」并用错误色，不谎报成功",
          "卸载没有完成" in gen._msg_label.text() and gen._msg_label.text() != "",
          gen._msg_label.text())

    # ⑥非预期返回值（比如将来有人多加一颗按钮忘了接）⇒ 按「取消」处理，绝不默认去删
    _un_calls.clear()
    _vm.uninstall = lambda cfg, mode: (_un_calls.append(mode), True)[1]
    _StubChoiceDl.answer = "bogus"
    gen._uninstall_model()
    check("★★弹窗回了个**非预期值** ⇒ 按取消处理（一个字都不删）—— 绝不能「不是取消就当全删」",
          _un_calls == [] and "已取消卸载" in gen._msg_label.text(),
          "%s / %s" % (str(_un_calls), gen._msg_label.text()))
finally:
    _vd.is_running, _vm.model_dir, _vm.uninstall, _vm.is_installed = (
        _orig_ir, _orig_md, _orig_un, _orig_inst)
    gui.ConfirmDialog, gui.ChoiceDialog = _orig_confirm_5h, _orig_choice_5h
    _StubConfirmDl.answer = True       # 桩是类属性：别把答案留给后面几段
    _StubConfirmDl.calls[:] = []
    _StubChoiceDl.answer = None
    _StubChoiceDl.calls[:] = []
    gen.refresh()


print("== 6. 关闭行为 ==")
calls = {"tray": 0, "quit": 0}
win.set_hide_to_tray(lambda: calls.__setitem__("tray", calls["tray"] + 1))
win.set_quit_app(lambda: calls.__setitem__("quit", calls["quit"] + 1))

cfg["general"]["close_action"] = "tray"
win.show()
e1 = QCloseEvent()
win.closeEvent(e1)
check("托盘模式：事件被忽略并触发托盘回调",
      (not e1.isAccepted()) and calls["tray"] == 1 and calls["quit"] == 0, str(calls) + f" accepted={e1.isAccepted()}")
check("托盘模式：窗口已隐藏", win.isHidden())

# 无托盘回调时（兜底）：直接放行关闭
cfg["general"]["close_action"] = "tray"
win.set_hide_to_tray(None)
win.show()
e2 = QCloseEvent()
win.closeEvent(e2)
check("无托盘回调时允许关闭（兜底）", e2.isAccepted())

# 关闭软件：必须放行事件。
# （历史 bug：这里原来 event.ignore()，而 app.quit() 会关闭所有顶层窗口再次进入 closeEvent，
#   形成 closeEvent → quit → closeEvent 死循环，导致「只关掉桌宠、主窗口还在且退不掉」。）
win.show()
cfg["general"]["close_action"] = "quit"
win._quitting = False
e3 = QCloseEvent()
win.closeEvent(e3)
check("关闭软件模式：触发退出回调且放行事件（不再死循环）",
      calls["quit"] == 1 and e3.isAccepted(), str(calls) + f" accepted={e3.isAccepted()}")
check("关闭软件模式：已标记正在退出", win._quitting is True)

# 退出过程中（app.quit 触发的关闭）再来 closeEvent，必须继续放行且不再重复回调
e4 = QCloseEvent()
win.closeEvent(e4)
check("退出流程中重复 closeEvent 放行且不再回调",
      e4.isAccepted() and calls["quit"] == 1, str(calls) + f" accepted={e4.isAccepted()}")

cfg["general"] = {"close_action": "xx"}
check("close_action() 归一化非法值", win.close_action() == "tray")

# ========== 7. 桌宠气泡的出现条件（main.py 源码断言）==========
# 气泡「只要主界面**不在聊天界面**就出现」（关着 / 开着但停在管理·设置页），而且
# **条件不满足时要主动收起**。这些判定散落在若干触发点上，只能靠源码断言守住
# （真跑 main() 要起麦克风与 AI，冒烟不跑它）。
print("== 7. 桌宠气泡的出现条件（主界面不在聊天界面）==")
_src_b = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
_seg = _src_b[_src_b.index("def show_pet_bubble"):]
_seg = _seg[:_seg.index("def _enter_speaking_ui")]
check("出现条件收敛成一个判定函数 pet_bubble_allowed()（判定只此一处）",
      "def pet_bubble_allowed" in _src_b and "if zh and pet_bubble_allowed()" in _seg, _seg[:160])
_allowed = _src_b[_src_b.index("def pet_bubble_allowed"):_src_b.index("def refresh_pet_bubble")]
check("判定收敛成 is_chat_visible() 的反面（关着 / 停在管理·设置页 / 停在聊天页但**最小化** 都算出气泡）；**静音模式不参与**",
      "not win.is_chat_visible()" in _allowed
      and "not win.isVisible()" not in _allowed and "not win.is_chat_page()" not in _allowed
      and "mute_mode" not in _allowed, _allowed[:240])
check("条件不满足时是**主动收起**（else 分支调 hide_bubble），不是只「不弹」",
      "pet.hide_bubble()" in _seg, _seg[:160])
check("气泡内容 = 这一轮的中文全文（show_bubble 收到的是 zh）",
      "pet.show_bubble(zh)" in _seg, _seg[:160])
check("气泡挂在「说话态」这个唯一入口上（_enter_speaking_ui 里叫出来）",
      "show_pet_bubble(zh)" in _src_b, "没接到 _enter_speaking_ui")
check("两个开场路径（正常 / 兜底出字）都带中文调 _enter_speaking_ui",
      "_enter_speaking_ui(zh)" in _src_b and '_enter_speaking_ui(stream_ui["zh"])' in _src_b,
      "有开场路径漏了中文参数")
_bl = _src_b[_src_b.index("def back_to_listening"):_src_b.index("# ---- AI 对话")]
check("这一轮结束（back_to_listening）收气泡", "pet.hide_bubble()" in _bl, _bl[:120])
_gi = _src_b[_src_b.index("def go_idle"):_src_b.index("wake_timer.timeout.connect")]
check("睡下（go_idle）收气泡", "pet.hide_bubble()" in _gi, _gi[:120])

# 三条**重判**路径：条件变了（主界面露出 / 换页 / 菜单跳转）就重算，不满足立刻收掉。
_ref = _src_b[_src_b.index("def refresh_pet_bubble"):_src_b.index("def show_pet_bubble")]
check("重判函数 refresh_pet_bubble()：**只收不补弹**（不满足才 hide，绝不 show）",
      "pet.hide_bubble()" in _ref and "show_bubble" not in _ref and "set_state" not in _ref, _ref[:240])
_smw = _src_b[_src_b.index("def show_main_window"):_src_b.index("def quit_app")]
check("主界面被打开（show_main_window）走重判", "refresh_pet_bubble()" in _smw, _smw[:200])
check("重判**排在 bring_to_front() 之后**（isVisible() 那一刻才变 True，反了会把「该收」判成「还关着」）",
      _smw.index("win.bring_to_front()") < _smw.index("refresh_pet_bubble()"), _smw[:240])
_opn = _src_b[_src_b.index("def open_pet_nav"):_src_b.index("pet.set_on_home")]
check("桌宠右键菜单跳转（open_pet_nav）自己再重判一次（目标页 == 当前页时不会发换页回调）",
      "refresh_pet_bubble()" in _opn, _opn[:240])
check("两处菜单跳转都统一走 open_pet_nav（不再直接调 win.open_nav_page）",
      "lambda: open_pet_nav(0)" in _src_b and "lambda: open_pet_nav(2)" in _src_b)
check("右栏换页回调已注册到重判函数（切回聊天页立刻收）",
      "win.set_page_change_cb(lambda: refresh_pet_bubble())" in _src_b)
_smm = _src_b[_src_b.index("def set_mute_mode"):_src_b.index("def on_command")]
check("**关掉静音模式不再收气泡**（出现条件里已经没有静音模式了）",
      "pet.hide_bubble()" not in _smm, _smm[:240])
# ★★2026-09-29：静音改成「落盘偏好」后，**两条切换路都必须写盘** ——
#   设置页那条（`gui._toggle_mute_mode`）本来就有 `save_config`（之前被剔字段架空，现在真生效）；
#   语音这条路以前只改内存，本次补上。只补一边 = 「用语音开的静音重启就丢」，最难查的那种不一致。
_smm_node = next(n for n in ast.walk(_tree_main)
                 if isinstance(n, ast.FunctionDef) and n.name == "set_mute_mode")
_smm_calls = [c for c in ast.walk(_smm_node)
              if isinstance(c, ast.Call) and (
                  (isinstance(c.func, ast.Name) and c.func.id == "save_config")
                  or (isinstance(c.func, ast.Attribute) and c.func.attr == "save_config"))]
_smm_writes = [n.lineno for n in ast.walk(_smm_node)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Subscript) for t in n.targets)]
check("★★语音那条路（set_mute_mode）函数体里**真有一次** save_config(...) 调用",
      len(_smm_calls) == 1, f"calls={[c.lineno for c in _smm_calls]}")
check("★★顺序：**先**写内存 cfg、**再** save_config（反了就是把旧值存盘 = 改了却没记住）"
      "—— ★用 AST 真实的 lineno 比，注释 / 文档串里的 `save_config(cfg)` 骗不过它",
      bool(_smm_calls) and bool(_smm_writes)
      and _smm_calls[0].lineno > min(_smm_writes),
      f"calls={[c.lineno for c in _smm_calls]} writes={_smm_writes}")
check("★语音那条路的系统消息不再说「本次运行有效 / 重启后自动关闭」（口径已反转）",
      "本次运行有效" not in _smm and "重启后自动关闭" not in _smm, _smm[:400])
check("收起点至少 5 个（go_idle / back_to_listening / 重判 / show_pet_bubble else / 预览开关）",
      _src_b.count("pet.hide_bubble()") >= 5, str(_src_b.count("pet.hide_bubble()")))

# ========== 7b. 桌宠状态提示气泡的触发点（main.py / gui.py 源码断言）==========
# 关掉主界面只剩贴图（节能形态更是一张不换帧的扁平图）时，分不清「等指令 / 睡着 / 静音」
# —— 所以把这些状态顶到她脑袋上方（design.md 4.17，docs/02 §15.4）。触发点同样散落在多个
# 函数里，继续用源码断言守住。真跑 main() 要起麦克风与 AI，冒烟不跑它。
print("== 7b. 桌宠状态提示气泡的触发点 ==")
_ot_all = _src_b[_src_b.index("def on_text"):]
_wake = _ot_all[:_ot_all.index("# 已唤醒（聆听中）")]
check("唤醒词唤醒：事件提示「已唤醒」", 'pet.flash_toast("已唤醒")' in _wake, _wake[-400:])
check("唤醒词唤醒：同时把常驻状态挂成「待机中」+ 点动画（事件淡出后自然露出来）",
      'pet.set_state_toast("待机中", dots=True)' in _wake, _wake[-400:])
check("两层顺序：先挂常驻状态、后弹事件（反了的话露出来的是空的）",
      _wake.index("pet.set_state_toast") < _wake.index("pet.flash_toast"))
check("只喊了唤醒词 → 转思考：收掉常驻提示（她开始答话了）",
      "pet.clear_state_toast()" in _ot_all, _ot_all[:200])
_oc = _src_b[_src_b.index("def on_command"):_src_b.index("def on_text")]
check("普通指令 → 思考：收掉常驻提示", "pet.clear_state_toast()" in _oc, _oc[:200])
check("本地指令（静音 / 节能开关）**不**收提示：它们 return 在收提示之前，仍留在聆听态",
      _oc.index("pet.clear_state_toast()") > _oc.index("POWER_SAVE_OFF_WORDS"))
check("休眠（go_idle）：常驻提示换成「休眠中」",
      'pet.set_state_toast("休眠中")' in _gi, _gi[:200])
check("回到聆听（back_to_listening）：常驻提示挂回「待机中」+ 点动画",
      'pet.set_state_toast("待机中", dots=True)' in _bl, _bl[:200])
check("静音切换（语音那条路）：弹「已进入 / 已退出静音模式」",
      'pet.flash_toast("已进入静音模式" if on else "已退出静音模式")' in _smm, _smm[:200])
_ps = _src_b[_src_b.index("def on_power_save_changed"):_src_b.index("pet.set_on_power_save")]
check("节能切换：桌宠弹「已进入 / 已退出节能模式」",
      'text = "已进入节能模式" if on else "已退出节能模式"' in _ps
      and "pet.flash_toast(text)" in _ps, _ps[:420])
check("节能提示**只有这一句**：不再解释「压扁待机 / 恢复站姿 / 右键桌宠」",
      "压扁" not in _ps and "站姿" not in _ps and "右键桌宠" not in _ps, _ps[:420])
check("节能切换：聊天区落的也是同一句（win.add_system_message(text)）",
      "win.add_system_message(text)" in _ps, _ps[:420])
check("静音切换（设置页那条路）：主程序注册了 win.set_mute_mode_cb",
      "win.set_mute_mode_cb(" in _src_b, "没注册回调 → 设置页切静音时桌宠不弹提示")
check("冷启动 / 开机自启**不**挂「休眠中」（那是「用户让她睡下」才有的那一刻）",
      "pet.set_state(State.IDLE.value)" in _src_b[_src_b.rindex("pet.move(*pet_default_pos(pet))"):][:2000]
      and "set_state_toast" not in _src_b[_src_b.rindex("pet.move(*pet_default_pos(pet))"):][:2000],
      "开机就顶一个提示反而吵")
check("挂常驻提示只有两处（唤醒 / 回到聆听），收常驻提示只有两处（两个「转思考」入口）",
      _src_b.count('pet.set_state_toast("待机中", dots=True)') == 2
      and _src_b.count("pet.clear_state_toast()") == 2,
      f"{_src_b.count('pet.set_state_toast(\"待机中\", dots=True)')} / {_src_b.count('pet.clear_state_toast()')}")
_src_gui = (Path(__file__).resolve().parent.parent / "app" / "gui.py").read_text(encoding="utf-8")
# ⚠️ 切片右端用 `def _toggle_patpat_mode`、**不能**用 `def _set_close_action`：
# 2026-09-20 十八改把 `_toggle_patpat_mode` 插在 `_toggle_mute_mode` 与 `_set_close_action`
# 之间，用后者当边界会把它的 `save_config(self.cfg)` 也圈进来（计数 1 → 2，误报）。
_tg = _src_gui[_src_gui.index("def _toggle_mute_mode"):_src_gui.index("def _toggle_patpat_mode")]
check("设置页切静音后通知主程序（self._win.notify_mute_mode(on)）",
      "self._win.notify_mute_mode(on)" in _tg, _tg[:300])
# ★2026-09-29 改成 AST 数真实 Call：原先用 `_tg.count("save_config(self.cfg)")` 子串计数，
#   结果被**这段自己的 docstring** 里那句「`save_config(self.cfg)` 从 2026-09-29 起真的写进
#   文件了」算成第二次 ⇒ 假红（计数 1 → 2）。注释/文档串里的同名文字不该参与结构计数。
_tg_node = next(n for n in ast.walk(ast.parse(_src_gui))
                if isinstance(n, ast.FunctionDef) and n.name == "_toggle_mute_mode")
_tg_calls = [c for c in ast.walk(_tg_node)
             if isinstance(c, ast.Call)
             and ((isinstance(c.func, ast.Attribute) and c.func.attr == "save_config")
                  or (isinstance(c.func, ast.Name) and c.func.id == "save_config"))]
check("设置页切静音自己只落一次 cfg（回调里别再重复写盘）"
      "—— ★AST 数真实 Call，注释 / 文档串里的同名文字不算",
      len(_tg_calls) == 1, f"calls={[c.lineno for c in _tg_calls]}")
check("★设置页那条路的提示文案也不再说「本次运行有效 / 重启后自动关闭」（口径已反转）",
      "本次运行有效" not in _tg and "重启后自动关闭" not in _tg, _tg[:400])
check("主窗口提供 set_mute_mode_cb / notify_mute_mode 两个接口",
      "def set_mute_mode_cb" in _src_gui and "def notify_mute_mode" in _src_gui)
check("main.py 侧的回调**只**弹提示：不写 cfg、不重复页面提示",
      _src_b[_src_b.index("win.set_mute_mode_cb("):][:300].count("save_config") == 0
      and _src_b[_src_b.index("win.set_mute_mode_cb("):][:300].count("add_system_message") == 0)

# ---- patpat 模式（2026-09-20）：两个入口、一个落地点 ----
# ★切片终点**不能**用「下一个已知方法名」：那等于假设两方法一直相邻，中间一旦插入新方法
#   （实测插了 `_toggle_pet_lock`），它的 `save_config(self.cfg)` 就被圈进来 ⇒ 计数 1→2 误报。
#   终点改成「下一个 4 空格缩进的 def」，与插不插新方法无关。
_tp_start = _src_gui.index("def _toggle_patpat_mode")
_tp = _src_gui[_tp_start:_src_gui.index("\n    def ", _tp_start + 1)]
check("设置页切 patpat 后通知主程序（self._win.notify_patpat_mode(on)）",
      "self._win.notify_patpat_mode(on)" in _tp, _tp[:300])
check("设置页切 patpat 自己只落一次 cfg（纯运行时项，回调里不重复写盘）",
      _tp.count("save_config(self.cfg)") == 1, str(_tp.count("save_config(self.cfg)")))
check("主窗口提供 set_patpat_mode_cb / notify_patpat_mode / sync_patpat_mode 三个接口"
      "（与静音模式那一套一一对应）",
      all(s in _src_gui for s in ("def set_patpat_mode_cb", "def notify_patpat_mode",
                                  "def sync_patpat_mode")))
check("main.py 两条入口都接上了：`pet.set_on_patpat(on_patpat_changed)`（右键菜单那条）"
      "与 `win.set_patpat_mode_cb(pet.set_patpat)`（设置页那条）—— 状态只有桌宠那一份",
      "pet.set_on_patpat(" in _src_b and "win.set_patpat_mode_cb(pet.set_patpat)" in _src_b)
_opp = _src_b[_src_b.index("def on_patpat_changed"):][:500]
check("main.py 的落地点做三件事：弹提示（用户口径那两句）+ 同步 cfg + 同步设置页滑块；"
      "且**不写盘**（纯运行时）",
      "pet.flash_toast(text)" in _opp and 'cfg.setdefault("general", {})["patpat_mode"]' in _opp
      and "win.sync_patpat_mode(on)" in _opp and _opp.count("save_config(") == 0,
      _opp[:300])
check("提示落点是**贴图上方那条状态气泡**（flash_toast），文案就是「patpat模式启动 / 关闭」",
      'text = "patpat模式启动" if on else "patpat模式关闭"' in _opp
      and "pet.flash_toast(text)" in _opp, _opp[:200])

# ========== 7c. 换页回调（gui.py 侧）：is_chat_page / 通知排在 setCurrentIndex 之后 ==========
# main.py 的重判靠 gui 在**换页之后**回调一次；顺序错了回调里读到的还是旧页面。
print("== 7c. 换页回调（gui.py 侧）==")
_src_gui_b = (Path(__file__).resolve().parent.parent / "app" / "gui.py").read_text(encoding="utf-8")
check("MainWindow 提供 is_chat_page()（右栏当前页 == PAGE_CHAT）",
      "def is_chat_page(self)" in _src_gui_b
      and "self._right_stack.currentIndex() == self.PAGE_CHAT" in _src_gui_b)
check("MainWindow 提供 set_page_change_cb()（main.py 注入重判）",
      "def set_page_change_cb(self, cb)" in _src_gui_b
      and "self._page_change_cb = cb" in _src_gui_b)
check("MainWindow 提供 is_chat_visible()（显示着 + **没最小化** + 停在聊天页，三档合一）",
      "def is_chat_visible(self)" in _src_gui_b
      and "self.isVisible() and not self.isMinimized() and self.is_chat_page()" in _src_gui_b)
_ce = _src_gui_b[_src_gui_b.index("def changeEvent(self, event)"):]
_ce = _ce[:_ce.index("def set_page_change_cb")]
check("窗口状态变化（最小化 / 还原，**不是** hide 到托盘）也要重判一次：changeEvent 里 WindowStateChange -> _notify_page_change()",
      "super().changeEvent(event)" in _ce and "QEvent.WindowStateChange" in _ce
      and "_notify_page_change()" in _ce
      and _ce.index("QEvent.WindowStateChange") < _ce.index("_notify_page_change()"),
      _ce[:240])
_tree_g = ast.parse(_src_gui_b)
_sw_fn = next(n for n in ast.walk(_tree_g)
              if isinstance(n, ast.FunctionDef) and n.name == "_switch_right_panel")
_notifies = [n for n in ast.walk(_sw_fn)
             if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and getattr(n.value.func, "attr", "") == "_notify_page_change"]
check("两条 setCurrentIndex 分支之后各通知一次（同一页时早返回 → 不发回调，调用方自己重判）",
      len(_notifies) == 2, str(len(_notifies)))
check("每条通知都排在某个 setCurrentIndex **之后**（回调里读到的必须是新页面）",
      all(any(isinstance(m, ast.Call) and getattr(m.func, "attr", "") == "setCurrentIndex"
              and m.lineno < nt.lineno
              for m in ast.walk(_sw_fn) if isinstance(m, ast.Call))
          for nt in _notifies),
      str(sorted(nt.lineno for nt in _notifies)))
check("PAGE_CHAT == 0（聊天页就是右栏第一页）", win.PAGE_CHAT == 0)

# 真跑一次换页：进管理页 → 不是聊天页（气泡条件成立）；切回聊天页 → 是，且回调被叫到
win.set_page_change_cb(None)
win._switch_right_panel(win.PAGE_API, animate=False)
check("切到「管理 API」后 is_chat_page() 为假（气泡该出现）", win.is_chat_page() is False)
_cb_hits = []
win.set_page_change_cb(lambda: _cb_hits.append(win.is_chat_page()))
win._switch_right_panel(win.PAGE_CHAT, animate=False)
check("切回聊天页：is_chat_page() 为真，且回调**在换页后**被叫到（回调里读到的也是新页面）",
      win.is_chat_page() is True and _cb_hits == [True], str(_cb_hits))
_skip_hits = []
win.set_page_change_cb(lambda: _skip_hits.append(1))
win._switch_right_panel(win.PAGE_CHAT, animate=False)
check("已经在聊天页再切聊天页：早返回、**不发回调**（所以 open_pet_nav 要自己补一次重判）",
      _skip_hits == [], str(_skip_hits))

# 真跑「停在聊天页但最小化到任务栏」这一档：`isVisible()` 仍是 True（没有 hide 到托盘），
# 旧口径「没显示或不在聊天页」会把它判成「能看见聊天区」→ 漏掉气泡。
win.showNormal()
app.processEvents()
check("显示着且停在聊天页：is_chat_visible() 为真（气泡该收）", win.is_chat_visible() is True)
_hits_ws = []
win.set_page_change_cb(lambda: _hits_ws.append(win.is_chat_visible()))
win.showMinimized()
app.processEvents()
check("最小化到**任务栏**（不是系统托盘）：isVisible() 仍为真、isMinimized() 为真",
      win.isVisible() is True and win.isMinimized() is True,
      f"visible={win.isVisible()} minimized={win.isMinimized()}")
check("最小化后 is_chat_visible() 为假（用户看不到聊天区 → 该出气泡）", win.is_chat_visible() is False)
check("最小化会发 WindowStateChange → 重判回调被叫到，回调里读到的正是「不可见」",
      _hits_ws == [False], str(_hits_ws))
win.showNormal()
app.processEvents()
check("还原回来：is_chat_visible() 为真，回调再被叫一次",
      win.is_chat_visible() is True and _hits_ws == [False, True], str(_hits_ws))
win.set_page_change_cb(None)

# ========== 7d. 主窗口的「唤起」：任务栏最小化下 show() 是空操作（docs/02 §17，十五改）==========
# 用户报的遗留问题：窗口**最小化到任务栏**时，右键桌宠 → 点「主界面」/「设置」唤不起窗口。
# 根因：最小化态下 isVisible() 本来就是 True（见上面 §7c 那几条），show() = setVisible(True) 什么都不做，
# 窗口继续躺在任务栏里。修法：isMinimized() 时改走 showNormal()。
# ★ 离屏平台**如实复现**这个 bug（实测：最小化后 show() → isMinimized() 仍为真），所以回归闸能留在这里。
print("== 7d. 主窗口唤起（任务栏最小化）==")


def _self_calls(node):
    """`node`（一个 FunctionDef 或语句列表）里按源码顺序出现的 `self.xxx()` 方法名。

    走 AST 而不是扫源码 —— docstring / 注释里提到 `showNormal()` 不算数，
    而且找不到下标时会得到空列表，不会像 `str.index()` 那样把整个套件炸掉
    （反向验证时真踩过：改回旧写法后 `index()` 抛 ValueError，后面的断言全没了）。
    """
    stmts = node.body if isinstance(node, ast.FunctionDef) else node
    found = []
    for st in stmts:
        for c in ast.walk(st):
            if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and isinstance(c.func.value, ast.Name) and c.func.value.id == "self"):
                found.append((c.lineno, c.func.attr))
    return [name for _ln, name in sorted(found)]


_b2f_fn = next(n for n in _mw.body
               if isinstance(n, ast.FunctionDef) and n.name == "bring_to_front")
# 顶层语句（剔掉开头的 docstring），应当是：1 个 If + 四条 `self.xxx()` 语句
_b2f_top = [s for s in _b2f_fn.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
_b2f_if = _b2f_top[0] if _b2f_top else None
_t = getattr(_b2f_if, "test", None)
check("bring_to_front() 的**第一条**语句就是 `if self.isMinimized():`（判据恰好是「最小化」这一档）",
      isinstance(_b2f_if, ast.If) and isinstance(_t, ast.Call)
      and isinstance(_t.func, ast.Attribute) and _t.func.attr == "isMinimized"
      and isinstance(_t.func.value, ast.Name) and _t.func.value.id == "self",
      ast.dump(_b2f_if) if _b2f_if is not None else "(空)")
check("...而且只有这一个 If（别再加第二套条件 / 别用 try 试）",
      sum(isinstance(s, ast.If) for s in _b2f_top) == 1,
      str([type(s).__name__ for s in _b2f_top]))
check("真分支 = showNormal()（任务栏最小化必须还原），假分支 = show()（hide 到托盘 / 本来没显示）",
      isinstance(_b2f_if, ast.If)
      and "showNormal" in _self_calls(_b2f_if.body)
      and "show" in _self_calls(_b2f_if.orelse),
      f"body={_self_calls(_b2f_if.body) if isinstance(_b2f_if, ast.If) else None} "
      f"else={_self_calls(_b2f_if.orelse) if isinstance(_b2f_if, ast.If) else None}")
check("前置三件套仍在 If **之后**、顺序不变（raise_ → activateWindow → setFocus）",
      _self_calls(_b2f_top[1:]) == ["raise_", "activateWindow", "setFocus"],
      str(_self_calls(_b2f_top[1:])))
check("⚠️ 不许自己造「先记最大化位再 showMaximized()」那套（多余，且会把「最大化着点托盘」弄乱）",
      "showMaximized" not in _self_calls(_b2f_fn), str(_self_calls(_b2f_fn)))

# 前提断言：这条修法依赖「裸 show() 对最小化窗口无效」这个 Qt 行为 ——
# 万一哪天 Qt / 平台变了（show() 会自己还原），这条红，提醒回来重看 docs/02 §17.2 还需不需要。
win.showNormal()
app.processEvents()
win.showMinimized()
app.processEvents()
check("（前提）已最小化到任务栏：isMinimized() 为真", win.isMinimized() is True)
win.show()
app.processEvents()
check("（前提）裸 show() **唤不起来** —— isMinimized() 仍为真（这正是遗留 bug 的根因）",
      win.isMinimized() is True, f"minimized={win.isMinimized()}")

# 行为层：真跑 bring_to_front()
win.bring_to_front()
app.processEvents()
check("bring_to_front() 把任务栏最小化的窗口**真的还原**了（isMinimized() 为假、仍可见）",
      win.isMinimized() is False and win.isVisible() is True,
      f"minimized={win.isMinimized()} visible={win.isVisible()}")

# 真跑菜单那条路：open_nav_page() —— 右键桌宠的「主界面」/「设置」用的就是它（经 main.open_pet_nav）
win._switch_right_panel(win.PAGE_CHAT, animate=False)
win.showMinimized()
app.processEvents()
check("（复现）最小化态：停在聊天页但 is_chat_visible() 为假（用户看不到聊天区）",
      win.is_chat_visible() is False)
_hits_bf = []
win.set_page_change_cb(lambda: _hits_bf.append(win.is_chat_visible()))
win.open_nav_page(win.PAGE_CHAT)                      # 「主界面」
app.processEvents()
check("open_nav_page(PAGE_CHAT)（「主界面」那条路）也一并还原",
      win.isMinimized() is False, f"minimized={win.isMinimized()}")
check("还原发 WindowStateChange → 重判回调被叫到，回调里读到「聊天区可见」",
      bool(_hits_bf) and _hits_bf[-1] is True, str(_hits_bf))
check("还原后停在聊天页：is_chat_visible() 为真（气泡该收）", win.is_chat_visible() is True)

win.showMinimized()
app.processEvents()
win.open_nav_page(2)                                  # 「设置」
app.processEvents()
check("open_nav_page(2)（「设置」那条路）同样还原，并落到设置区",
      win.isMinimized() is False and win.is_chat_page() is False,
      f"minimized={win.isMinimized()} chat={win.is_chat_page()}")
win.set_page_change_cb(None)
win._switch_right_panel(win.PAGE_CHAT, animate=False)
win.showNormal()
app.processEvents()

print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)
