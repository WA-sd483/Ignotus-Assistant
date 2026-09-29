"""安全边界回归测试：白名单 + 危险级延迟撤销。

运行（在 IgnotusAssistant 目录下）：
    .venv\\Scripts\\python.exe tests\\smoke_permissions.py
全部通过时退出码为 0，并打印 ALL_OK；失败时列出失败项并以 1 退出。
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:  # 控制台重定向时保证中文输出可读
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from app import tools  # noqa: E402
from app.config import load_config  # noqa: E402

# ★2026-09-29：本套原来把「开发机的桌面路径」写死在十几处 —— 换台机器就找不到、跑不过。
#   （`tools.USER_DIR` 的遗留）。换成换台机器就找不到、跑不过。
#   ⇒ 现在**问被测代码本人**要「本机桌面在哪」，再用它构造白名单/穿越/兄弟路径等用例，
#     语义与被测口径同源（`as_posix()` 是为了保持 `D:/x` 这种正斜杠写法，与断言里的旧串一致）。
_DESKTOP = tools._resolve_user_dir("Desktop").as_posix()

fails = []
total = [0]


def check(name, cond, extra=""):
    total[0] += 1
    print(("  OK   " if cond else "  FAIL ") + name + (f"  <{extra}>" if extra else ""))
    if not cond:
        fails.append(name)


print("== 1. 默认白名单 ==")
tools.apply_permissions({})
p = tools.get_permissions()
# ★2026-09-28 用户拍板：内置默认**不再预设任何目录**。旧口径是「开发机用户目录 + 六个常见用户目录」，
#   但那会把打包机自己的路径带进成品（别人装上看到的是开发机的目录、还暴露用户名）。
# 这里钉两个方向 —— 「列表真的空」+「空的时候真的什么都拦得住」：
check("默认目录为空（不再预设打包机路径）", p["allowed_dirs"] == [], str(p["allowed_dirs"]))
check("default_permissions() 的目录同样为空（面板「恢复默认」读的是它）",
      tools.default_permissions()["allowed_dirs"] == [], str(tools.default_permissions()["allowed_dirs"]))
_ok1, _why1 = tools.check_permission(
    {"type": "open_path", "label": "桌面", "target": _DESKTOP}, "打开桌面")
check("默认不放行任何路径（没添加目录前 open_path 一律被拦）", not _ok1, _why1)
check("默认软件不含 cmd", "cmd" not in p["allowed_apps"])
check("默认操作含 run_command", "run_command" in p["allowed_actions"])
check("危险类型含 run_command", tools.is_danger({"type": "run_command"}))
check("危险类型含 file_delete", tools.is_danger({"type": "file_delete"}))
check("open_app 非危险", not tools.is_danger({"type": "open_app"}))

print("== 1b. 用户目录解析：真值问 Windows，不是写死的常量 ==")
# ★2026-09-29：原 `tools.USER_DIR = Path("<开发机用户目录>")` 已删 —— 那是**开发机私有路径**，
#   别人机器上多半没有 D 盘 ⇒「打开桌面 / 下载」会指向不存在的目录（功能 bug，不只是隐私）。
#   现在改成读注册表「用户外壳文件夹」表（`app/tools.py::_resolve_user_dir`）。
# ★★这里**不能**只断言「`DIR_MAP['桌面']` == 本机桌面」：在开发机上旧常量**恰好等于**真实桌面
#   ⇒ 就算有人把硬编码改回去，那条也照样绿（**自洽式假绿**，本项目的老毛病）。
#   ⇒ 强判据 = 「把注册表桩成**假路径**，解析必须跟着假路径走」：写死的实现过不了这一条。
#     （已做变异检查：把实现换回 `Path("<开发机用户目录>") / folder_en` ⇒ 第 1 条确实变红。）
import winreg as _wr  # noqa: E402

_FAKE_DIR = str(Path(__file__).resolve().parent.parent)          # 项目根：一定存在（is_dir 会筛）
_FAKE_DL = str(Path(__file__).resolve().parent.parent / "app")
_GUID_DL = "{374DE290-123F-4565-9164-39C4925E467B}"              # 「下载」在注册表里的值名


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeReg:
    """假的注册表：说「桌面」在项目根、「下载」在 app/ —— 与真值故意不同。"""

    HKEY_CURRENT_USER = _wr.HKEY_CURRENT_USER

    @staticmethod
    def OpenKey(*_a, **_k):
        return _FakeKey()

    @staticmethod
    def QueryValueEx(_k, name):
        return (_FAKE_DL, 1) if name == _GUID_DL else (_FAKE_DIR, 1)


class _BoomReg:
    """取不到值（表缺失 / 权限）—— 用来验回落分支。"""

    HKEY_CURRENT_USER = _wr.HKEY_CURRENT_USER

    @staticmethod
    def OpenKey(*_a, **_k):
        raise OSError("模拟注册表读不到")


_real_reg = tools.winreg
try:
    tools.winreg = _FakeReg
    _got = tools._resolve_user_dir("Desktop")
    check("注册表说桌面在哪就返回哪（★写死的实现过不了这条）",
          _got == Path(_FAKE_DIR), str(_got))
    _got_dl = tools._resolve_user_dir("Downloads")
    check("『下载』按 GUID 值名去查", _got_dl == Path(_FAKE_DL), str(_got_dl))
    tools.winreg = _BoomReg
    check("注册表读不到 ⇒ 回落「用户主目录/Desktop」",
          tools._resolve_user_dir("Desktop") == Path.home() / "Desktop")
    tools.winreg = None
    check("完全没有 winreg ⇒ 同样回落（不抛异常）",
          tools._resolve_user_dir("Desktop") == Path.home() / "Desktop")
    check("未知目录名 ⇒ 也回落而不是抛",
          tools._resolve_user_dir("NoSuchFolder") == Path.home() / "NoSuchFolder")
finally:
    tools.winreg = _real_reg          # ★必须还原：不还原，后面所有用例都会读到假注册表
check("还原后回到注册表真值（本机桌面）",
      tools._resolve_user_dir("Desktop") == Path(tools.DIR_MAP["桌面"]), tools.DIR_MAP["桌面"])
check("六个用户目录都解析成绝对路径", all(
    Path(tools.DIR_MAP[k]).is_absolute() for k in ("桌面", "下载", "文档", "图片", "音乐", "视频")),
    str({k: tools.DIR_MAP[k] for k in ("桌面", "下载")}))
check("旧常量 USER_DIR 已删（不再夹带开发机路径）", not hasattr(tools, "USER_DIR"))
check("_DIR_NAMES 死代码已删", not hasattr(tools, "_DIR_NAMES"))

print("== 2. 放行路径 ==")
ok, why = tools.check_permission({"type": "open_app", "label": "记事本", "target": "notepad"}, "打开记事本")
check("允许打开记事本", ok, why)
# ★内置默认已是空的（见 §1）⇒ 「放行」和下面 §3 的那些拦截必须**自己钉一份白名单**：
#   否则空名单会把一切都拦掉，§3 就成了「拦得住」的空转假绿（看着对，其实一条逻辑都没验到）。
#   这一句同时也是 §1 那条「默认被拦」的**正对照**：同样一条指令，加了白名单就放行。
tools.apply_permissions({"allowed_dirs": [_DESKTOP]})
ok, why = tools.check_permission({"type": "open_path", "label": "桌面", "target": _DESKTOP}, "打开桌面")
check(f"显式加入白名单后放行 {_DESKTOP}", ok, why)
ok, why = tools.check_permission({"type": "query_info", "kind": "time"}, "现在几点")
check("允许查询时间", ok, why)

print("== 3. 拦截 ==")
ok, why = tools.check_permission({"type": "open_app", "label": "cmd", "target": "cmd"}, "打开cmd")
check("拒绝 cmd", not ok, why)
ok, why = tools.check_permission({"type": "open_app", "label": "powershell", "target": "powershell"}, "打开powershell")
check("拒绝 powershell", not ok, why)
ok, why = tools.check_permission({"type": "open_path", "label": "x", "target": "C:/Windows/System32"}, "打开 System32")
check("拒绝 C:/Windows/System32", not ok, why)
ok, why = tools.check_permission({"type": "open_path", "label": "x", "target": _DESKTOP + "/../../Windows"}, "路径穿越")
check("拒绝路径穿越 ../../Windows", not ok, why)
ok, why = tools.check_permission({"type": "open_path", "label": "x", "target": _DESKTOP + "abc"}, "前缀相似目录")
check("拒绝白名单目录的**兄弟路径**（前缀相似不算命中）", not ok, why)

print("== 4. 操作类型开关 / 禁止词 ==")
tools.apply_permissions({"allowed_actions": ["query_info", "open_path"]})
ok, why = tools.check_permission({"type": "run_command", "label": "关机", "target": ["shutdown"]}, "关机")
check("关掉 run_command 后关机被拒", not ok, why)
tools.apply_permissions({"blocked_keywords": ["格式化"]})
ok, why = tools.check_permission(
    {"type": "open_path", "label": "x", "target": _DESKTOP}, "帮我格式化 C 盘"
)
check("命中禁止词被拒", not ok, why)

print("== 5. 显式目录白名单覆盖默认 ==")
tools.apply_permissions({"allowed_dirs": [_DESKTOP + "/new-proj"], "danger_delay": 5})
ok, _ = tools.check_permission({"type": "open_path", "label": "x", "target": _DESKTOP}, "x")
check("白名单收窄后 Desktop 被拒", not ok)
ok, _ = tools.check_permission(
    {"type": "open_path", "label": "x", "target": _DESKTOP + "/new-proj/IgnotusAssistant"}, "x"
)
check("白名单内子目录放行", ok)

print("== 6. 危险级延迟 + 撤销 ==")
tools.apply_permissions({"danger_delay": 5})
check("初始无待执行", tools.pending_danger() is None)
hit = []
orig = tools._run_action_now
tools._run_action_now = lambda a: hit.append(a.get("label"))  # 拦截真正执行
msg = tools.schedule_danger({"type": "run_command", "label": "关机", "target": ["shutdown"]})
check("排程返回文案含秒数与取消提示", ("5 秒后执行" in msg) and ("取消" in msg), msg)
pd = tools.pending_danger()
check("待执行状态可读", bool(pd) and pd["label"] == "关机" and 0 < pd["remaining"] <= 5, str(pd))
check("危险操作未立即执行", hit == [], str(hit))
cancelled = tools.cancel_pending_danger()
check("撤销返回操作名", cancelled == "关机", str(cancelled))
check("撤销后队列已清空", tools.pending_danger() is None)
time.sleep(6)
check("撤销后到点也未执行", hit == [], str(hit))

print("== 7. 到点自动执行 ==")
tools.schedule_danger({"type": "run_command", "label": "重启", "target": ["shutdown"]})
time.sleep(6)
check("未撤销则到点执行", hit == ["重启"], str(hit))
tools._run_action_now = orig

print("== 8. execute_action 走安全边界 ==")
tools.apply_permissions({})
out = tools.execute_action({"type": "open_app", "label": "cmd", "target": "cmd"}, "打开cmd")
check("execute_action 拦截 cmd 并返回说明", out.startswith("[权限拦截]"), out)
out = tools.execute_action({"type": "run_command", "label": "锁屏", "target": ["x"]}, "锁屏")
check("execute_action 对危险级只排程不执行", out.startswith("[已排程]"), out)
tools.cancel_pending_danger()

print("== 9. 配置归一化 ==")
from app.config import DEFAULT_CONFIG  # noqa: E402
from app import config as cfgmod  # noqa: E402
raw = dict(DEFAULT_CONFIG)
raw["permissions"] = {"allowed_dirs": "bad", "danger_delay": "9999"}
merged = cfgmod._deep_merge(DEFAULT_CONFIG, raw)
cfgmod.CONFIG_PATH = Path("__nope__.json")
loaded = cfgmod.load_config()
check("真实配置可加载", isinstance(loaded.get("permissions"), dict))
check("danger_delay 被钳制", 5 <= int(loaded["permissions"]["danger_delay"]) <= 120, str(loaded["permissions"]["danger_delay"]))

print("== 10. GUI 构造（主界面 3 页 + 设置页）==")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent, QEventLoop, Qt, QPointF, QTimer  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from app import gui as g  # noqa: E402

g.save_config = lambda cfg: None  # 防止测试写回真实 config.json
app = QApplication.instance() or QApplication([])
cfg = load_config()
cfg["permissions"] = {"allowed_dirs": [], "allowed_apps": [], "allowed_actions": [],
                      "blocked_keywords": [], "danger_delay": 30}
win = g.MainWindow(cfg)
win.show()  # offscreen 下也要 show，否则 isVisible 恒为假
check("右栏面板数 = 主界面 3 + 设置页数",
      win._right_stack.count() == 3 + len(win.SETTINGS_ITEMS), str(win._right_stack.count()))
_perm_idx = win._settings_index["permissions"]
check("权限面板类型正确", isinstance(win._right_stack.widget(_perm_idx), g.PermPanel))
win._show_settings_page(_perm_idx)
check("切到权限管理页（设置区）", win._right_stack.currentIndex() == _perm_idx)
check("导航态把权限页归入设置", win._nav_settings_btn.isChecked())
check("左栏进入设置模式（蓝底导航）", win._settings_mode)
win.set_notice("关机将在 12 秒后执行 · 说「取消」可中止")
check("倒计时提示可见", win._notice_label.isVisible() and "12 秒" in win._notice_label.text(),
      win._notice_label.text())
win.set_notice("")
check("清空后提示隐藏", not win._notice_label.isVisible())
panel = win._perm_panel
panel._materialize()
panel._rebuild()
# 四个白名单分组已折叠（各自是一个分组 widget），外层只剩「分组 + 危险延迟」若干项；
# 行都挂在分组的内容区里，所以要递归找。
_items = panel._body_lay.count()
_rows = panel._body.findChildren(g._PermRow)
_groups = panel._body.findChildren(g._CollapsibleGroup)
check("权限面板可重建",
      _items >= 7 and len(_rows) > 6 and len(_groups) == 4,
      f"items={_items} rows={len(_rows)} groups={len(_groups)}")
check("重建后四个分组仍默认收起", all(grp.is_collapsed() for grp in _groups))

print("== 10b. 危险操作倒计时弹窗（屏幕正中央；卡片 200×150，窗口 200×165）==")


def _click_at(widget, pt):
    """在控件上发一对「按下 + 抬起」：按钮回调挂在释放且落在同一按钮上（自绘按钮没有 clicked）。"""
    for _t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        QApplication.sendEvent(
            widget, QMouseEvent(_t, QPointF(pt), QPointF(pt),
                                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


check("尺寸口径写死在类上：卡片 (200,150)、窗口 (200,165) = 卡片 + 15px 弹出位移",
      g.DangerCountdownDialog.SIZE == (200, 150)
      and g.DangerCountdownDialog.WINDOW_SIZE == (200, 165)
      and g.DLG_CARD_H + g.DLG_POP_DY == 165)
win.show_danger_countdown("关机", 12)
_dlg = win._danger_dlg
check("排程期间弹窗可见", _dlg.isVisible())
check("固定 200×165（min == max，撑不大也缩不小）",
      (_dlg.width(), _dlg.height()) == (200, 165) and _dlg.minimumSize() == _dlg.maximumSize(),
      str(_dlg.size()))
_loop = QEventLoop()
QTimer.singleShot(600, _loop.quit)      # 等淡入（50%->100% / 0.5s）落位
_loop.exec()
_geo = app.primaryScreen().availableGeometry()
# 卡片本体在窗口**顶部**（多出来的 15px 全在下方给弹出位移用）-> 卡片中心 = 窗口 y + 卡片高的一半
_ccx, _ccy = _dlg.x() + g.DLG_CARD_W / 2, _dlg.y() + g.DLG_CARD_H / 2
check("摆到**屏幕正中央**（主屏可用区中心；卡片几何中心对屏幕中心）",
      _ccx == _geo.x() + _geo.width() / 2 and _ccy == _geo.y() + _geo.height() / 2,
      f"卡片中心=({_ccx},{_ccy}) 屏幕中心=({_geo.x() + _geo.width() / 2},{_geo.y() + _geo.height() / 2})")
check("落位后 = 到位态：pop == 1（100% 大小 / 不透明 / 位移归零）、不在淡出",
      _dlg.pop == 1.0 and not _dlg.is_fading_out(), str(_dlg.pop))
check("标题 =「{操作}倒计时」、数字 = 剩余秒数（「说取消可中止」那行已换成两个按钮）",
      (_dlg.title_text, _dlg.number_text) == ("关机倒计时", "12")
      and not hasattr(_dlg, "hint_lbl"), f"{_dlg.title_text}/{_dlg.number_text}")
check("**不是**确认框：非模态（`exec()` / `setModal(True)` 会把整个软件连语音一起卡住）",
      _dlg.isModal() is False)
_run_r, _cancel_r = _dlg.buttons
check("两个按钮：各 80×30、同一行、都在卡片内、左「立刻关机」右「取消」",
      (_run_r.width(), _run_r.height()) == (g.DLG_BTN_W, g.DLG_BTN_H)
      and (_cancel_r.width(), _cancel_r.height()) == (g.DLG_BTN_W, g.DLG_BTN_H)
      and _run_r.top() == _cancel_r.top()
      and _run_r.left() >= 0 and _cancel_r.right() <= g.DLG_CARD_W
      and _run_r.right() < _cancel_r.left(),
      f"{_run_r} {_cancel_r}")
check("按钮文案口径：左边是**通用**的「立刻执行」（关机 / 重启都用它）、右边「取消」",
      (g.DLG_BTN_RUN_TEXT, g.DLG_BTN_CANCEL_TEXT) == ("立刻执行", "取消"))
check("命中测试：左 -> run、右 -> cancel、标题那一带 -> None",
      _dlg.button_at(_run_r.center().toPoint()) == "run"
      and _dlg.button_at(_cancel_r.center().toPoint()) == "cancel"
      and _dlg.button_at(QPointF(100.0, 20.0).toPoint()) is None)
_clicks = []
_dlg.set_callbacks(lambda: _clicks.append("run"), lambda: _clicks.append("cancel"))
_click_at(_dlg, _run_r.center())
check("点「立刻执行」-> 回调被叫到（真正执行在 main.py 注册的回调里）", _clicks == ["run"], str(_clicks))
_click_at(_dlg, QPointF(100.0, 20.0))
check("点空白处不触发任何回调（它没有「点外部关闭」这种语义）", _clicks == ["run"], str(_clicks))
_img = _dlg.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
_dpr = _img.devicePixelRatio() or 1.0


def _px(x, y):
    c = _img.pixelColor(round(x * _dpr), round(y * _dpr))
    return (c.red(), c.green(), c.blue(), c.alpha())


check("四角透明 = 16px 圆角（不是方角白块）", _px(0, 0)[3] == 0 and _px(2, 2)[3] == 0, str(_px(0, 0)))
check("卡片内部白底", _px(12, 40) == (255, 255, 255, 255), str(_px(12, 40)))
check("四条边中点都是 1px #E6F1FB 边框（与另外三款同一条皮肤）",
      all(_px(x, y)[:3] == (230, 241, 251) for x, y in ((100, 0), (0, 75), (199, 75), (100, 149))),
      f"{_px(100, 0)} {_px(0, 75)}")
check("窗口底部那 15px（弹出位移用）在到位态是透明的", _px(100, 160)[3] == 0, str(_px(100, 160)))
_cs = {}
for _y in range(_img.height()):
    for _x in range(_img.width()):
        _c = _img.pixelColor(_x, _y)
        _cs[(_c.red(), _c.green(), _c.blue())] = _cs.get((_c.red(), _c.green(), _c.blue()), 0) + 1
check("主蓝 #378ADD 大面积出现（大号秒数 + 「立刻关机」按钮底色）",
      _cs.get((55, 138, 221), 0) > 1200, str(_cs.get((55, 138, 221), 0)))
check("标题深蓝 #0C447C + 「秒」/「取消」灰 #64748B 都在",
      _cs.get((12, 68, 124), 0) > 20 and _cs.get((100, 116, 139), 0) > 20,
      f"{_cs.get((12, 68, 124), 0)}/{_cs.get((100, 116, 139), 0)}")
check("「取消」是白底灰边（#CBD5E1 也在）", _cs.get((203, 213, 225), 0) > 30, str(_cs.get((203, 213, 225), 0)))
_pid, _pos = id(_dlg), _dlg.pos()
win.show_danger_countdown("关机", 11)
check("每秒刷新**只改数字**：不重建窗口、位置也不动、不重放动画",
      id(win._danger_dlg) == _pid and _dlg.number_text == "11" and _dlg.pos() == _pos,
      f"{_dlg.number_text} {_dlg.pos()} vs {_pos}")
win.show_danger_countdown("重启", 7)
check("换操作：标题跟着改（重启倒计时）、数字跟着换",
      _dlg.title_text == "重启倒计时" and _dlg.number_text == "7")
check("弹出三件套算式：v=0 -> 全透明 / 下移 15px / 50% 大小；v=1 -> 到位态；时长 500ms",
      _dlg._pop_frame(0.0) == (0.0, float(g.DLG_POP_DY), g.DLG_MIN_SCALE)
      and _dlg._pop_frame(1.0) == (1.0, 0.0, 1.0)
      and g.DLG_ANIM_MS == 500,
      f"{_dlg._pop_frame(0.0)} {_dlg._pop_frame(1.0)}")

win.hide_danger_countdown()
check("淡出中：is_fading_out() 为真（不是「啪」地消失）", _dlg.is_fading_out())
_loop = QEventLoop()
QTimer.singleShot(700, _loop.quit)
_loop.exec()
check("淡出 0.5s 后隐藏 + pop 归零", not _dlg.isVisible() and _dlg.pop == 0.0,
      f"{_dlg.isVisible()} pop={_dlg.pop}")
win.show_danger_countdown("关机", 30)
_loop = QEventLoop()
QTimer.singleShot(120, _loop.quit)
_loop.exec()
check("淡入是**动画**：跑到一半时还没到位（0 < pop < 1）", 0.0 < _dlg.pop < 1.0, str(_dlg.pop))
_loop = QEventLoop()
QTimer.singleShot(600, _loop.quit)
_loop.exec()
check("淡入 0.5s 后到位：pop == 1", _dlg.pop == 1.0, str(_dlg.pop))

_num_before_cancel = _dlg.number_text
win.cancel_danger_countdown()
check("「取消」-> 红色取消态：标题改「已取消关机」、**读数停在取消那一刻**、仍然可见",
      _dlg.cancelled and _dlg.title_text == "已取消关机"
      and _dlg.number_text == _num_before_cancel == "30" and _dlg.isVisible(),
      f"{_dlg.cancelled} {_dlg.title_text} {_dlg.number_text!r}")
_loop = QEventLoop()
QTimer.singleShot(200, _loop.quit)
_loop.exec()
_img_r = _dlg.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
_rs = {}
for _y in range(_img_r.height()):
    for _x in range(_img_r.width()):
        _c = _img_r.pixelColor(_x, _y)
        _rs[(_c.red(), _c.green(), _c.blue())] = _rs.get((_c.red(), _c.green(), _c.blue()), 0) + 1
check("红态真像素：边框 #FCA5A5 + 标题 #991B1B + **大号读数也还在**（#DC2626，只是换成红的）",
      _rs.get((252, 165, 165), 0) > 100 and _rs.get((153, 27, 27), 0) > 20
      and _rs.get((220, 38, 38), 0) > 100,
      f"{_rs.get((252, 165, 165), 0)}/{_rs.get((153, 27, 27), 0)}/{_rs.get((220, 38, 38), 0)}")
check("红态里**主蓝一个像素都不剩**（按钮真的没了、读数也换成红色了）",
      _rs.get((55, 138, 221), 0) == 0, str(_rs.get((55, 138, 221), 0)))
win.hide_danger_countdown()
check("取消态里 hide_danger_countdown() 是**空操作**（否则下一秒 tick 会把红态当场抹掉）",
      _dlg.isVisible() and _dlg.cancelled)
_loop = QEventLoop()
QTimer.singleShot(1100, _loop.quit)      # 距 show_cancelled() 约 1.4s < 1.5s
_loop.exec()
check("红色态撑满 1.5s（DLG_CANCEL_HOLD_MS）还没自己收", _dlg.isVisible() and _dlg.cancelled)
_loop = QEventLoop()
QTimer.singleShot(900, _loop.quit)       # 累计约 2.3s > 1.5s + 0.5s 淡出
_loop.exec()
check("1.5s 之后自己淡出（0.5s）-> 隐藏", not _dlg.isVisible(), str(_dlg.isVisible()))
win.show_danger_countdown("关机", 30)
check("红色态之后**新排程**：复用同一个窗口、复位回蓝态（按钮回来）",
      id(win._danger_dlg) == _pid and _dlg.isVisible() and not _dlg.cancelled
      and _dlg.number_text == "30",
      f"{_dlg.cancelled} {_dlg.number_text}")
win.hide_danger_countdown()
_loop = QEventLoop()
QTimer.singleShot(700, _loop.quit)
_loop.exec()

# main.py / gui.py 源码断言：弹窗挂在倒计时那条链上
_root = Path(__file__).resolve().parent.parent
_src_m = (_root / "app" / "main.py").read_text(encoding="utf-8")
_tick = _src_m[_src_m.index("def _tick_danger"):_src_m.index("danger_timer = QTimer()")]
check("main.py：排程中把 (label, remaining) 交给弹窗",
      'win.show_danger_countdown(pd["label"], pd["remaining"])' in _tick, _tick[:200])
check('main.py：队列空了**无条件**收弹窗（不在 `if danger_ui["label"]` 里，取消那条路才收得到）',
      "win.hide_danger_countdown()" in _tick.split('if danger_ui["label"]')[0], _tick[:200])
check('main.py：每秒 tick 只**改数字** —— 弹窗首次弹出要等回复开口（`danger_ui["card"]` 守卫 + 2 秒兜底）',
      'if danger_ui["card"] or _danger_elapsed(pd) >= 2:' in _tick
      and 'danger_ui["card"] = True' in _tick, _tick[:200])
_cancel = _src_m[_src_m.index('cancelled = pd["label"]'):_src_m.index("elif is_sleep_word")]
check("main.py：语音取消把弹窗**转红**（再调 hide，红色态下那是空操作）",
      "win.cancel_danger_countdown()" in _cancel and "win.hide_danger_countdown()" in _cancel,
      _cancel[:300])
_run_now_src = _src_m[_src_m.index("if pd and any(w in clean_cmd for w in RUN_NOW_WORDS):")
                    :_src_m.index('if pd and any(w in text for w in CANCEL_WORDS):')]
check("main.py：语音「立刻关机」**只在有排程时**（if pd and ...）执行 + 与按钮共用 run_pending_danger_now()",
      "if pd and" in _run_now_src and "run_pending_danger_now()" in _run_now_src
      and "return" in _run_now_src and "RUN_NOW_WORDS" in _run_now_src,
      _run_now_src[:200])
import ast as _ast  # noqa: E402
_rn_words = next(_ast.literal_eval(_n.value) for _n in _ast.parse(_src_m).body
                 if isinstance(_n, _ast.Assign)
                 and any(getattr(_t, "id", "") == "RUN_NOW_WORDS" for _t in _n.targets))
check("main.py：RUN_NOW_WORDS 含用户口径的「立刻关机」",
      "立刻关机" in _rn_words, str(_rn_words))
_rn_specific = [w for w in _rn_words if ("关机" in w or "重启" in w)]
check("main.py：RUN_NOW_WORDS 里有**通用**说法（「立刻执行」这些，与按钮同文案）",
      all(w in _rn_words for w in ("立刻执行", "马上执行", "立即执行")), str(_rn_words))
check("main.py：点名操作的说法 detect_action 都认（没排程时才落得回普通「关机」/「重启」那条路）",
      bool(_rn_specific) and all(tools.detect_action(w) for w in _rn_specific),
      str([w for w in _rn_specific if not tools.detect_action(w)]))
_danger_reply = next(_ast.literal_eval(_n.value) for _n in _ast.parse(_src_m).body
                     if isinstance(_n, _ast.Assign)
                     and any(getattr(_t, "id", "") == "DANGER_REPLY" for _t in _n.targets))
check("main.py：危险操作的回复是**固定文案**（用户口径：任务执行中... / ミッション実行中...）",
      _danger_reply == ("任务执行中...", "ミッション実行中..."), str(_danger_reply))
check("main.py：危险级分支排完程就 `canned = DANGER_REPLY`（不再把 action_result 交给 AI 自由发挥）",
      "execute_action(action, text)" in _src_m and "canned = DANGER_REPLY" in _src_m
      and "canned=canned" in _src_m)
check("main.py：_ask_ai 支持 canned（跳过 AI、也不要求 API Key）",
      "canned: tuple[str, str] | None = None" in _src_m
      and "persona = None if canned" in _src_m
      and 'if canned is None and (not api or not api.get("api_key"))' in _src_m)
check("main.py：固定回复走**同一条流水线**（speak + release_text_gate = 文字与声音同刻出现）",
      "zh_canned, ja_canned = canned" in _src_m and "pipe.release_text_gate()" in _src_m)
check("main.py：倒计时弹窗挂在与回复同刻的那一处（`sync_danger_card()` 由 `_enter_speaking_ui` 调）",
      "def sync_danger_card" in _src_m
      and "sync_danger_card()" in _src_m.split("def _enter_speaking_ui")[1][:1200], "见 _enter_speaking_ui")
check("main.py：弹窗两个按钮已注册（set_danger_callbacks + 两条回调）",
      "win.set_danger_callbacks(on_danger_run_now, on_danger_cancel)" in _src_m
      and "def on_danger_run_now" in _src_m and "def on_danger_cancel" in _src_m)
_src_g = (_root / "app" / "gui.py").read_text(encoding="utf-8")
_dlg_src = _src_g[_src_g.index("class DangerCountdownDialog"):_src_g.index("class _Segment")]
check("**禁止**改回模态 / exec（会把整个软件连语音一起卡住）",
      "setModal(False)" in _dlg_src and ".exec()" not in _dlg_src)
check("自绘缩放三件套：_pop_frame + QVariantAnimation + DLG_ANIM_MS（整卡缩放，QSS 做不到）",
      "def _pop_frame" in _dlg_src and "QVariantAnimation" in _dlg_src
      and "DLG_ANIM_MS" in _dlg_src and "def paintEvent" in _dlg_src)
check("色值常量与三款弹窗 QSS 的字面值逐条一致（防两边漂移）",
      g.DLG_CARD_BORDER == "#E6F1FB" and g.DLG_CARD_RADIUS == 16
      and g.DLG_TITLE_INK == "#0C447C" and g.DLG_NUM_BLUE == "#378ADD"
      and g.DLG_MUTED == "#64748B" and g.DLG_BTN_PRIMARY == "#378ADD"
      and g.DLG_BTN_PRIMARY_HOVER == "#2F74BF" and g.DLG_BTN_GHOST_BORDER == "#CBD5E1"
      and g.DLG_BTN_GHOST_HOVER == "#F1F5F9"
      and "border:1px solid #E6F1FB; border-radius:16px;" in _src_g
      and "background:#378ADD;" in _src_g and "background:#2F74BF;" in _src_g
      and "border:1px solid #CBD5E1;" in _src_g and "background:#F1F5F9;" in _src_g
      and "color:#64748B;" in _src_g and "color:#0C447C;" in _src_g)
win.close()

print("== 10c. 「立刻关机」：有排程才跳过倒计时 ==")
tools.apply_permissions({"danger_delay": 30})
_ran = []
_orig_run, _orig_abort = tools._run_action_now, tools._abort_native_shutdown
tools._run_action_now = lambda a: (_ran.append(a.get("label")), "stub")[1]
tools._abort_native_shutdown = lambda: None       # 别真去调系统的 shutdown /a
try:
    check("**没排程**时 run_pending_danger_now() 返回 None（调用方据此落回普通「关机」：排程 + 弹窗）",
          tools.run_pending_danger_now() is None)
    tools.schedule_danger({"type": "run_command", "label": "关机",
                           "target": ["shutdown", "/s", "/t", "0"]})
    check("排好程：pending_danger() 有货（倒计时在跑）", bool(tools.pending_danger()))
    _label = tools.run_pending_danger_now()
    for _ in range(30):                           # 执行在后台线程里，等它落地
        if _ran:
            break
        time.sleep(0.02)
    check("有排程时说「立刻关机」：跳过倒计时当场执行 + 返回操作名 + 队列清空",
          _label == "关机" and _ran == ["关机"] and tools.pending_danger() is None,
          f"{_label} {_ran}")
    check("执行过之后队列是空的（同一句再说一次不会又执行一遍）",
          tools.run_pending_danger_now() is None and _ran == ["关机"], str(_ran))
finally:
    tools._run_action_now, tools._abort_native_shutdown = _orig_run, _orig_abort
    tools.cancel_pending_danger()

print("== 10d. 「立刻关机」/「取消」的真实行为（子进程真跑一次 app.main.main()）==")
import json as _json2  # noqa: E402
import subprocess as _sp  # noqa: E402
import tempfile as _tf  # noqa: E402

_probe_out = Path(_tf.mkdtemp(prefix="danger_probe_")) / "out.json"
_proc = _sp.run([sys.executable, str(_root / "tests" / "danger_probe.py")],
                capture_output=True, text=True, timeout=180,
                env=dict(os.environ, QT_QPA_PLATFORM="offscreen",
                         DANGER_PROBE_OUT=str(_probe_out), PYTHONIOENCODING="utf-8"))
check("探针跑完（退出码 0；它不联网、不写真 config、**绝不真的关机**）",
      _proc.returncode == 0, (_proc.stderr or _proc.stdout or "")[-400:])
_data = _json2.loads(_probe_out.read_text(encoding="utf-8")) if _probe_out.exists() else {}
_st = _data.get("steps", {})
_just = _st.get("just_after_cmd", {})
check("**没排程**时说「立刻关机」-> 只排程（绝不直接执行）：命令刚落地时**只有排程、还没有弹窗**",
      _just.get("pending") == "关机" and _just.get("ran") == []
      and _just.get("dlg_visible") is False, str(_just))
_ns = _st.get("card_appeared", {})
check("回复开口那一刻：倒计时弹窗**与它同刻**出现（`dlg_visible` 转真 + 标题「关机倒计时」）",
      _ns.get("pending") == "关机" and _ns.get("ran") == []
      and _ns.get("dlg_visible") is True and _ns.get("dlg_title") == "关机倒计时", str(_ns))
check("危险操作的回复是**固定文案**「任务执行中...」（聊天区里真的显示了这句）",
      "任务执行中..." in _data.get("assistant", []), str(_data.get("assistant")))
check("危险操作那几轮**一次都没问 AI**（`ai_args` 里没有关机 / 重启）",
      not any(("关机" in _t or "重启" in _t) for _t in _data.get("ai_args", [])),
      str(_data.get("ai_args")))
_rn = _st.get("run_now", {})
check("有排程时再说「立刻关机」-> 跳过倒计时当场执行（队列清空 + 弹窗收掉 + 消息）",
      _rn.get("ran") == ["关机"] and _rn.get("pending") is None
      and _rn.get("dlg_visible") is False
      and any("已立刻执行「关机」" in x for x in _rn.get("messages", [])), str(_rn))
_bc = _st.get("before_cancel", {})
check("重新排一个：弹窗又亮起来（蓝态、还在倒计时）",
      _bc.get("pending") == "关机" and _bc.get("dlg_visible") is True
      and _bc.get("dlg_cancelled") is False and _bc.get("dlg_title") == "关机倒计时", str(_bc))
_cn = _st.get("cancelled", {})
check("语音「取消」-> 撤排程（**ran 没有增加**，一个动作都没多执行）+ 弹窗转**红色取消态**",
      _cn.get("pending") is None and _cn.get("ran") == _bc.get("ran")
      and _cn.get("dlg_cancelled") is True
      and _cn.get("dlg_title") == "已取消关机"
      and any("已中止「关机」" in x for x in _cn.get("messages", [])), str(_cn))
check("取消态**保留取消时的读数**（= 取消前那一帧显示的秒数，而不是清空）",
      _cn.get("dlg_number") == _bc.get("dlg_number") != "",
      f"{_bc.get('dlg_number')!r} -> {_cn.get('dlg_number')!r}")
_bcc = _st.get("before_click_cancel", {})
_cc = _st.get("click_cancel", {})
check("点弹窗**右边「取消」按钮** -> 与语音同一条路（撤排程 + 转红色取消态 + 不新增执行）",
      _bcc.get("pending") == "关机" and _bcc.get("dlg_cancelled") is False
      and _cc.get("pending") is None and _cc.get("dlg_cancelled") is True
      and _cc.get("ran") == _bcc.get("ran"), str(_cc))
_cr = _st.get("click_run_now", {})
check("点弹窗**左边「立刻执行」按钮** -> 跳过倒计时当场执行（ran 正好多一条）",
      _cr.get("pending") is None and _cr.get("ran") == _bcc.get("ran") + ["关机"], str(_cr))

print("== 11. 否定词不误触发系统操作 ==")
tools.apply_permissions({})
a = tools.detect_action("关机")
check("「关机」识别为系统操作", bool(a) and a.get("type") == "run_command", str(a))
a = tools.detect_action("别关机")
check("「别关机」不识别为操作", a is None, str(a))
a = tools.detect_action("不要重启")
check("「不要重启」不识别为操作", a is None, str(a))
a = tools.detect_action("帮我把计算器关掉算了")
check("「……算了」不识别为关机", (a is None) or a.get("type") != "run_command", str(a))
a = tools.detect_action("现在几点")
check("查询类不受影响", bool(a) and a.get("kind") == "time", str(a))

print("== 12. 自定义软件（从磁盘添加的 exe）==")
tools.apply_permissions({})
check("默认无自定义软件", tools.get_permissions()["custom_apps"] == {},
      str(tools.get_permissions()["custom_apps"]))
check("default_permissions 含 custom_apps 且为空", tools.default_permissions()["custom_apps"] == {})

tools.apply_permissions({
    "allowed_apps": ["记事本", "SuperTool"],
    "custom_apps": {"SuperTool": "D:/Games/SuperTool.exe", "": "x", "Bad": ""},
})
p12 = tools.get_permissions()
check("custom_apps 只留非空键值对",
      p12["custom_apps"] == {"SuperTool": "D:/Games/SuperTool.exe"}, str(p12["custom_apps"]))
check("known_app_names 含自定义软件", "SuperTool" in tools.known_app_names())
a12 = tools.detect_action("打开SuperTool")
check("自定义软件可被识别为 open_app",
      bool(a12) and a12["label"] == "SuperTool" and a12["target"] == "D:/Games/SuperTool.exe", str(a12))
ok, why = tools.check_permission(a12, "打开SuperTool")
check("白名单内的自定义软件放行", ok, why)

# 只登记了 custom_apps、没进 allowed_apps → 识别得到但被拦（权限仍以 allowed_apps 为准）
tools.apply_permissions({"allowed_apps": ["记事本"], "custom_apps": {"Other": "D:/o.exe"}})
a12b = tools.detect_action("打开Other")
check("未加入白名单的自定义软件被拦截",
      bool(a12b) and not tools.check_permission(a12b, "打开Other")[0], str(a12b))

check("is_denied_app 命中默认黑名单（大小写 / 中文名都算）",
      tools.is_denied_app("cmd") and tools.is_denied_app("PowerShell")
      and tools.is_denied_app("命令提示符"))
check("is_denied_app 不误伤普通软件",
      not tools.is_denied_app("SuperTool") and not tools.is_denied_app(""))
tools.apply_permissions({})

# ========== 位置查询：输出粒度只到「国家、省/地区」==========
print("== 位置查询：只到省 / 地区 ==")
# IP 库的城市名不可信（运营商 IP 池大量挂在省会 —— 实测浙江某地的 IP 被标成杭州），
# 所以对外一律只说「国家、省/地区」，city 一概丢掉：宁可粗一点，也不要报错城市。
_r1 = tools._format_region({"country": "中国", "regionName": "浙江", "city": "杭州"})
check("定位输出 = 国家、省/地区，**丢掉城市**", _r1 == "中国、浙江", _r1)
check("没给省/地区时退回只报国家",
      tools._format_region({"country": "日本", "city": "东京"}) == "日本",
      tools._format_region({"country": "日本", "city": "东京"}))
check("全空时给「未知位置」而不是空串", tools._format_region({}) == "未知位置")
check("定位接口不再请求公网 IP（免得角色把 IP 念出来）",
      "query" not in tools._GEO_API, tools._GEO_API)

for _q in ("我在哪", "我在哪个城市", "这里是哪个省", "我在什么地方", "当前定位是哪里"):
    _a = tools.detect_action(_q)
    check(f"「{_q}」命中定位查询（漏了就会退回让模型自己猜）",
          bool(_a) and _a.get("type") == "query_info" and _a.get("kind") == "location",
          str(_a))

# ========== 免 UAC 启动（计划任务代替启动，绕开 UAC 提示）==========
# UAC 提示跑在安全桌面上，普通程序无法代点「是」——只能让进程一开始就带提升权限启动。
# 做法：给软件的 exe 建一个「最高权限、无触发器」的计划任务，之后 schtasks /run 点名启动。
# 本机沙箱把 schtasks.exe 列进了黑名单，所以**真实建任务/启动**不在这里跑，
# 只钉住「命令与脚本生成」「退出码映射」「权限配置归一化」「启动分支选择」。
print("== 免 UAC：模块与脚本生成 ==")
from app import launch_task as lt  # noqa: E402

check("本机支持该能力（Windows）", lt.available())
_n1 = lt.task_name("D:/Games/SuperTool.exe")
check("任务名带固定前缀（便于批量清理）", _n1.startswith(lt.TASK_PREFIX), _n1)
check("任务名同路径恒定、大小写不敏感", _n1 == lt.task_name("d:/games/supertool.EXE"), _n1)
check("任务名不同路径不同", _n1 != lt.task_name("D:/Games/Other.exe"))
check("任务名纯 ASCII（避开中文路径在命令行下的编码坑）", _n1.isascii(), _n1)
check("任务名长度可控", len(_n1) == len(lt.TASK_PREFIX) + 12, str(len(_n1)))

_sc = lt.create_script("D:/Games/SuperTool.exe")
check("建任务脚本指向该 exe", "SuperTool.exe" in _sc)
check("建任务脚本带工作目录（有些软件依赖 exe 同级目录）",
      "SuperTool.exe" in _sc and "-WorkingDirectory" in _sc)
check("主体等级 = 最高权限（这才是免 UAC 的关键）", "RunLevel Highest" in _sc)
check("只在用户登录时运行（否则进 session 0、窗口看不见）",
      "LogonType Interactive" in _sc)
check("**不传 -Trigger**：任务无触发器，只能被点名启动", "-Trigger" not in _sc)
check("不是以 SYSTEM 身份运行（SYSTEM 启动的 GUI 会进 session 0 不可见）",
      "SYSTEM" not in _sc)
check("建任务脚本里嵌的是本软件的任务名", _n1 in _sc)
check("PowerShell 单引号转义（路径带 ' 也不会破脚本）", lt._ps_sq("a'b") == "'a''b'")
_dsc = lt.delete_script(_n1)
check("删任务脚本按名字注销", _n1 in _dsc and "Unregister-ScheduledTask" in _dsc)
check("批量清理脚本按前缀通配", lt.TASK_PREFIX + "*" in lt.cleanup_script())
check("脚本走 -EncodedCommand（UTF-16LE + Base64，不落临时文件）",
      len(lt._b64("abc")) >= 8)

check("建任务脚本带 SID 兜底（微软账户下用户名可能映射不到 SID）",
      "WindowsIdentity" in _sc and "$users += $sid" in _sc)
check("提权脚本把真实报错写进临时结果文件（否则用户只看到一个「退出码 1」）",
      "Set-Content" in lt._INNER_TEMPLATE and "$_.Exception.Message" in lt._INNER_TEMPLATE)
check("外层用 RunAs 提权并回读结果文件",
      "RunAs" in lt._OUTER_TEMPLATE and "<<LOG>>" in lt._OUTER_TEMPLATE)
check("用户点「否」的退出码单独识别，不报成普通失败",
      lt._ERR_CANCELLED == 1223)
check("查询兜底脚本走 Get-ScheduledTask 且带任务名占位符",
      "Get-ScheduledTask" in lt._QUERY_SCRIPT and "<<NAME>>" in lt._QUERY_SCRIPT)
check("启动兜底脚本走 Start-ScheduledTask 且带任务名占位符",
      "Start-ScheduledTask" in lt._START_SCRIPT and "<<NAME>>" in lt._START_SCRIPT)

_real_schtasks = lt._schtasks
_real_ps_raw = lt._run_ps_raw
lt._schtasks = lambda args: 0
check("schtasks 退出码 0 → 任务存在 / 启动成功",
      lt.has_task("D:/t.exe") and lt.run_task("D:/t.exe"))

# **回归钉**：schtasks.exe 被企业策略 / 沙箱拉黑时退出码恒 -1，若只看它就等于
# 「任务其实建好了却报失败」—— 这正是「点了『是』之后显示失败」的成因之一。
lt._schtasks = lambda args: -1
lt._run_ps_raw = lambda script, timeout=0: (0, "", "")
check("schtasks 被拉黑（-1）→ 退回 Get-ScheduledTask 仍判为存在",
      lt.has_task("D:/t.exe"))
check("schtasks 被拉黑（-1）→ 退回 Start-ScheduledTask 仍能启动",
      lt.run_task("D:/t.exe"))
lt._run_ps_raw = lambda script, timeout=0: (1, "", "No MSFT_ScheduledTask objects found.")
check("schtasks 被拉黑且 cmdlet 也查不到 → 才算不存在 / 失败",
      not lt.has_task("D:/t.exe") and not lt.run_task("D:/t.exe"))
lt._run_ps_raw = _real_ps_raw

lt._schtasks = lambda args: 1
check("schtasks 失败 + 查不到 → 任务不存在 / 启动失败",
      not lt.has_task("D:/t.exe") and not lt.run_task("D:/t.exe"))
lt._schtasks = _real_schtasks
check("exe 不存在时先拦下（不去碰 schtasks）",
      lt.ensure_task("C:/nope/definitely_missing.exe")[0] is False)
check("空路径直接拒绝", lt.ensure_task("")[0] is False)

print("== 免 UAC：no_uac 配置归一化 ==")
import json as _json  # noqa: E402
import tempfile  # noqa: E402

check("默认配置含 no_uac 且为空", DEFAULT_CONFIG["permissions"]["no_uac"] == [])
check("default_permissions 含 no_uac 且为空", tools.default_permissions()["no_uac"] == [])
_old_path = cfgmod.CONFIG_PATH
_tmpd = Path(tempfile.mkdtemp())
cfgmod.CONFIG_PATH = _tmpd / "config.json"
cfgmod.CONFIG_PATH.write_text(_json.dumps({
    "permissions": {"no_uac": ["A", "A", " B ", "", 3, None], "custom_apps": {"A": "D:/a.exe"}},
}), encoding="utf-8")
_lc = cfgmod.load_config()
check("no_uac 去空、去重且保序（非字符串直接丢，不 str() 造假名字）",
      _lc["permissions"]["no_uac"] == ["A", "B"], str(_lc["permissions"]["no_uac"]))
cfgmod.CONFIG_PATH.write_text(_json.dumps({"permissions": {"no_uac": "bad"}}), encoding="utf-8")
check("no_uac 类型非法 → 回落空列表",
      cfgmod.load_config()["permissions"]["no_uac"] == [])
cfgmod.CONFIG_PATH = _old_path

tools.apply_permissions({})
check("未配置时 tools 的 no_uac 为空", tools.get_permissions()["no_uac"] == [])
tools.apply_permissions({"allowed_apps": ["T"], "custom_apps": {"T": "D:/t.exe"},
                         "no_uac": ["T", "", 7]})
check("tools 只收非空字符串", tools.get_permissions()["no_uac"] == ["T"],
      str(tools.get_permissions()["no_uac"]))
check("app_exe_path 取自定义软件的路径", tools.app_exe_path("T") == "D:/t.exe")
check("app_exe_path 对内置软件 / 未知名返回 None",
      tools.app_exe_path("记事本") is None and tools.app_exe_path("Nope") is None)
check("no_uac_apps 可读", tools.no_uac_apps() == ["T"])

print("== 免 UAC：打开软件时的分支选择 ==")
_calls = []
_orig_run_task = lt.run_task
_orig_popen = tools.subprocess.Popen
tools.subprocess.Popen = lambda args, **k: _calls.append(("popen", args))
lt.run_task = lambda exe: (_calls.append(("task", exe)), False)[1]
_out = tools._run_action_now({"type": "open_app", "label": "T", "target": "D:/t.exe"})
check("免 UAC 命中但任务启动失败 → **仍要打开**（退回普通方式）",
      _calls == [("task", "D:/t.exe"), ("popen", ["D:/t.exe"])], str(_calls))
check("回退时如实告知用户免 UAC 没生效", "免 UAC 启动未生效" in _out, _out)

_calls.clear()
lt.run_task = lambda exe: (_calls.append(("task", exe)), True)[1]
_out = tools._run_action_now({"type": "open_app", "label": "T", "target": "D:/t.exe"})
check("免 UAC 命中且任务启动成功 → 只走任务、不再 Popen",
      _calls == [("task", "D:/t.exe")], str(_calls))
check("成功时说明里点出「免 UAC」", "免 UAC" in _out, _out)

_calls.clear()
tools.apply_permissions({"allowed_apps": ["T"], "custom_apps": {"T": "D:/t.exe"}})
_out = tools._run_action_now({"type": "open_app", "label": "T", "target": "D:/t.exe"})
check("没开免 UAC 时照旧 Popen",
      _calls == [("popen", ["D:/t.exe"])] and _out == "已打开软件「T」", str(_calls) + _out)
tools.subprocess.Popen = _orig_popen
lt.run_task = _orig_run_task

print("== 免 UAC：权限面板开关 ==")
_perms13 = {
    "allowed_dirs": [], "allowed_apps": ["SuperTool", "记事本"],
    "allowed_actions": list(tools.DEFAULT_ALLOWED_ACTIONS),
    "blocked_keywords": [], "danger_delay": 30,
    "custom_apps": {"SuperTool": "D:/Games/SuperTool.exe"}, "no_uac": [],
}
tools.apply_permissions(_perms13)
cfg13 = {"permissions": dict(_perms13, custom_apps={"SuperTool": "D:/Games/SuperTool.exe"},
                             no_uac=[])}
panel13 = g.PermPanel(cfg13)
_rows13 = panel13._app_rows
check("软件分组为自定义软件建了行", "SuperTool" in _rows13, str(list(_rows13)))
_sw_row = _rows13["SuperTool"]
check("自定义软件行有「免 UAC」开关", _sw_row._switch is not None)
check("开关文案是「免 UAC」", _sw_row._switch_lbl.text() == "免 UAC",
      _sw_row._switch_lbl.text())
check("行本身不挂 tooltip（默认深色 QToolTip 在本机会渲染成一条黑条）",
      _sw_row.toolTip() == "", _sw_row.toolTip())
_hint_lbs = [lb for lb in _sw_row.parentWidget().findChildren(g.QLabel)
             if "免 UAC" in lb.text() and lb is not _sw_row._switch_lbl]
check("展开内容区不再有常驻的 UAC 说明提示行（用户要求删掉）",
      not _hint_lbs, str([lb.text() for lb in _hint_lbs]))
check("**悬停说明已删除**（2026-09-16 用户要求：说明只在开启前的确认弹窗里）",
      not hasattr(_sw_row, "_switch_tip_text")
      and not hasattr(_sw_row, "_switch_tip")
      and not hasattr(_sw_row, "_show_switch_tip"))
check("默认关闭（不主动提权）", not _sw_row._switch.isChecked())
check("开关**仅悬停时显示**：静止态 opacity 0 + 鼠标穿透（与「重命名 / 删除」一致）",
      _sw_row._switch._opacity == 0.0
      and _sw_row._switch.testAttribute(Qt.WA_TransparentForMouseEvents))
check("开关旁的小字同样默认透明（否则会「文字还在、开关没了」）",
      _sw_row._switch_lbl_effect is not None
      and _sw_row._switch_lbl_effect.opacity() == 0.0)

# 悬停「免 UAC」字样 / 滑块 → **什么都不弹**（悬停气泡整体移除，只留确认弹窗）
QApplication.sendEvent(_sw_row._switch_lbl, QEvent(QEvent.Enter))
QApplication.sendEvent(_sw_row._switch, QEvent(QEvent.Enter))
check("悬停后行上没有任何 tooltip（Qt 的 QToolTip 与自绘气泡都不用）",
      not [w for w in _sw_row.findChildren(g.QWidget) if w.toolTip()],
      str([(w.__class__.__name__, w.toolTip())
           for w in _sw_row.findChildren(g.QWidget) if w.toolTip()]))
check("「免 UAC」标签只保留「点它 = 点开关」这一个职责",
      _sw_row._switch_lbl.text() == "免 UAC")
check("`_ToolTip` 已收敛回「小提示」单一定位（只服务左侧悬浮按钮）",
      not hasattr(g._ToolTip, "show_above")
      and not hasattr(g._ToolTip, "cancel_hide"))

_sw_row._apply_bg(1.0)   # 行 hover 终态
check("hover 终态：开关与小字一起淡入到 1、且恢复可点",
      _sw_row._switch._opacity == 1.0
      and not _sw_row._switch.testAttribute(Qt.WA_TransparentForMouseEvents)
      and _sw_row._switch_lbl_effect.opacity() == 1.0)
check("开关底色跟着行底色走（否则 hover 变淡蓝时开关周围留一块白）",
      (_sw_row._switch._bg.red(), _sw_row._switch._bg.green(), _sw_row._switch._bg.blue())
      == (230, 241, 255),
      str((_sw_row._switch._bg.red(), _sw_row._switch._bg.green(), _sw_row._switch._bg.blue())))
_sw_row._apply_bg(0.0)
check("内置软件行没有开关（只有 PATH 命令、建不出任务）",
      _rows13["记事本"]._switch is None)
check("自定义软件行仍有「重命名」按钮", _sw_row._btn_extra is not None)

# 开启前必须**先弹确认窗**：offscreen 下 exec() 会阻塞，这里把它仿掉，
# 并记下它收到的文案，验证确实弹了、文案也对。
_confirm_calls = []
g.ConfirmDialog.confirm = staticmethod(
    lambda parent, msg, *a, **k: (_confirm_calls.append(msg), True)[1])

# 失败路径：用户取消授权 / 建任务失败 → 开关必须自己弹回去，不能显示成「已开启」
lt.ensure_task = lambda exe: (False, "已取消管理员授权")
_sw = _sw_row._switch
_sw.toggle()
_sw.clicked.emit()
check("开启前**先弹确认窗**（用户要求「需点击确认后才能打开」）",
      len(_confirm_calls) == 1, str(len(_confirm_calls)))
check("确认窗文案讲清「会弹 UAC 授权框、只需一次授权」",
      bool(_confirm_calls) and "UAC 授权框" in _confirm_calls[0]
      and "一次管理员授权" in _confirm_calls[0],
      _confirm_calls[0] if _confirm_calls else "（未弹窗）")
check("确认窗文案**不再夹带括注**（「（点确认后…请选是）」已按用户要求去掉）",
      bool(_confirm_calls) and "（" not in _confirm_calls[0]
      and "请选" not in _confirm_calls[0],
      _confirm_calls[0] if _confirm_calls else "（未弹窗）")
check("建任务失败 → 开关回弹到关", not _sw.isChecked())
check("建任务失败 → 不写进 no_uac", "SuperTool" not in cfg13["permissions"]["no_uac"])
check("建任务失败 → 底部消息说清原因",
      "免 UAC 设置失败" in panel13._msg_label.text() and "取消" in panel13._msg_label.text(),
      panel13._msg_label.text())

lt.ensure_task = lambda exe: (True, "已创建")
_sw.toggle()
_sw.clicked.emit()
check("建任务成功 → 开关保持开", _sw.isChecked())
check("建任务成功 → no_uac 记下软件名",
      cfg13["permissions"]["no_uac"] == ["SuperTool"],
      str(cfg13["permissions"]["no_uac"]))
check("建任务成功 → tools 侧同步生效",
      "SuperTool" in tools.get_permissions()["no_uac"])
check("建任务成功 → 底部消息确认为「开启」",
      "开启" in panel13._msg_label.text(), panel13._msg_label.text())

# 关闭：只摘配置、**不删任务**（任务无触发器、留着还省下次再授权）
_sw.toggle()
_sw.clicked.emit()
check("关闭 → 开关回到关", not _sw.isChecked())
check("关闭 → no_uac 摘掉该软件", cfg13["permissions"]["no_uac"] == [],
      str(cfg13["permissions"]["no_uac"]))
check("关闭 → 提示里点明下次会照常请求授权",
      "照常请求授权" in panel13._msg_label.text(), panel13._msg_label.text())

# 点「免 UAC」字样 = 点滑块（用户要求）：同一条「确认 → 落地」链路，手型光标已给出暗示
_confirm_calls.clear()
panel13._msg_label.setText("")
QApplication.sendEvent(
    _sw_row._switch_lbl,
    QMouseEvent(QEvent.MouseButtonPress, QPointF(1, 1), QPointF(1, 1),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
check("点「字样」也会弹确认窗（与点滑块同一语义）",
      len(_confirm_calls) == 1, str(len(_confirm_calls)))
check("点「字样」能把开关打开（不再只是滑块能点）", _sw.isChecked())
check("点「字样」确实走了面板落地（no_uac 记下软件名）",
      cfg13["permissions"]["no_uac"] == ["SuperTool"],
      str(cfg13["permissions"]["no_uac"]))
_sw.toggle()   # 收回关闭态，给下面的取消用例一个干净起点
_sw.clicked.emit()
check("（前置）已回到关闭态", not _sw.isChecked() and cfg13["permissions"]["no_uac"] == [])

# 确认窗点「取消」→ 不开、开关自己弹回、并给出提示
g.ConfirmDialog.confirm = staticmethod(lambda *a, **k: False)
_sw.toggle()
_sw.clicked.emit()
check("确认窗点「取消」→ 开关回弹到关", not _sw.isChecked())
check("确认窗点「取消」→ 不写进 no_uac", cfg13["permissions"]["no_uac"] == [],
      str(cfg13["permissions"]["no_uac"]))
check("确认窗点「取消」→ 底部消息说明「已取消开启」",
      "已取消开启" in panel13._msg_label.text(), panel13._msg_label.text())
g.ConfirmDialog.confirm = staticmethod(lambda *a, **k: True)

# 重命名：靠显示名匹配的 no_uac 必须跟着改（任务名由 exe 路径推出，与显示名无关）
_sw.toggle()
_sw.clicked.emit()
check("重命名前：no_uac 记的是旧名", cfg13["permissions"]["no_uac"] == ["SuperTool"])
_orig_get_text = g.InputDialog.get_text
g.InputDialog.get_text = staticmethod(lambda *a, **k: ("超级工具", True))
panel13._rename_app("SuperTool")
check("重命名后 no_uac 跟着改名（否则开关会凭空消失）",
      cfg13["permissions"]["no_uac"] == ["超级工具"],
      str(cfg13["permissions"]["no_uac"]))
check("重命名后 allowed_apps 也改了",
      cfg13["permissions"]["allowed_apps"] == ["超级工具", "记事本"],
      str(cfg13["permissions"]["allowed_apps"]))
check("重命名后 custom_apps 的 exe 路径不动",
      cfg13["permissions"]["custom_apps"] == {"超级工具": "D:/Games/SuperTool.exe"},
      str(cfg13["permissions"]["custom_apps"]))
g.InputDialog.get_text = _orig_get_text

# 删除软件：一并摘掉 no_uac 并尽力删任务（用户取消授权也不影响使用）
_deleted = []
_orig_remove_task = lt.remove_task
_orig_remove_all = lt.remove_all_tasks
lt.remove_task = lambda exe: (_deleted.append(exe), (True, "已删除"))[1]
g.ConfirmDialog.confirm = staticmethod(lambda *a, **k: True)
panel13._remove_item("allowed_apps", "超级工具")
check("删除软件时连同它的免 UAC 任务一起删",
      _deleted == ["D:/Games/SuperTool.exe"], str(_deleted))
check("删除软件后 no_uac 清空", cfg13["permissions"]["no_uac"] == [],
      str(cfg13["permissions"]["no_uac"]))

# 恢复默认：做一次批量清理（一次授权清掉所有 IgnotusLaunch_*）
_batch = []
lt.remove_all_tasks = lambda: (_batch.append(1), (True, "已清理"))[1]
panel13.cfg["permissions"]["no_uac"] = ["X"]
panel13._restore_defaults()
check("恢复默认时批量清理免 UAC 任务", _batch == [1], str(_batch))
check("恢复默认后 no_uac 为空", panel13.cfg["permissions"]["no_uac"] == [],
      str(panel13.cfg["permissions"]["no_uac"]))
lt.remove_task = _orig_remove_task
lt.remove_all_tasks = _orig_remove_all
tools.apply_permissions({})

print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)
