"""真机量测：主窗口「唤起」（`bring_to_front()`）在**任务栏最小化**下到底能不能把窗口弄回来。

用法（项目根目录；**不是**离屏，会真的建窗口、屏幕上会闪一下）：
    .venv\\Scripts\\python.exe tools\\window_probe.py

为什么单独留一个真机探针（docs/02 §17）：
  * 这条 bug 的行为在 **离屏平台上也复现**（`tests/smoke_settings.py` §7d 因此能当回归闸），
    但有一档是**平台差异**、离屏量不出来 —— 「先最大化再最小化」之后还原回来还是不是最大化：
    Windows 上 Qt 把最大化位保留在最小化态里（`windowState() == min|max`），`showNormal()` 还原回来
    仍是最大化；离屏上会掉成普通大小。所以这一档只认真机。

不写 config.json（`save_config` 被拦）、不碰注册表、不起麦克风。
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import gui  # noqa: E402
from app.config import load_config  # noqa: E402

gui.save_config = lambda cfg: None          # 不写回真实 config.json

app = QApplication.instance() or QApplication([])
print("platform =", app.platformName())

win = gui.MainWindow(load_config())
win.resize(860, 560)
win.move(80, 80)
win.show()


def settle(ms=600):
    """跑真实事件循环（Windows 上 WM_SIZE 是异步到的，必须真等）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    app.processEvents()


def st():
    return (f"isMinimized={win.isMinimized()} isMaximized={win.isMaximized()} "
            f"isVisible={win.isVisible()} isActive={win.isActiveWindow()} "
            f"state={int(win.windowState().value)}")


REPORT = []


def line(tag, ok, extra=""):
    REPORT.append(f"{'OK  ' if ok else 'FAIL'} {tag}   [{st()}]{('  ' + extra) if extra else ''}")
    print(REPORT[-1])


settle()

# --- 1. 现状（不最小化）：唤起一次，窗口该是正常的 ---
win.showNormal()
settle()
win.bring_to_front()
settle()
line("不最小化时 bring_to_front()：窗口显示着、没最小化",
     win.isVisible() and not win.isMinimized())

# --- 2. 任务栏最小化 → **裸 show()**（旧写法的核心那一句）→ 应当唤不起来（= 那条 bug 的根因） ---
win.showMinimized()
settle(800)
before = win.isMinimized()
win.show()
settle(800)
line("（根因）最小化后裸 show()：isMinimized() 仍为真（窗口没被唤起来）",
     before and win.isMinimized(), "这就是用户报的「点了等于没点」")

# --- 3. 任务栏最小化 → bring_to_front() → 必须真的还原 ---
win.showMinimized()
settle(800)
win.bring_to_front()
settle(800)
line("最小化后 bring_to_front()：isMinimized() 为假（真的还原了）",
     not win.isMinimized() and win.isVisible())

# --- 4. 走菜单那条路：open_nav_page()（右键桌宠「主界面」/「设置」用的就是它） ---
win.showMinimized()
settle(800)
win.open_nav_page(0)                       # 「主界面」
settle(800)
line("最小化后 open_nav_page(0)（「主界面」）：还原 + 落在聊天页",
     not win.isMinimized() and win.is_chat_page())
win.showMinimized()
settle(800)
win.open_nav_page(2)                       # 「设置」
settle(800)
line("最小化后 open_nav_page(2)（「设置」）：还原 + 落在设置区",
     not win.isMinimized() and not win.is_chat_page())

# --- 5. 平台差异那一档：先最大化再最小化 → 还原回来还是最大化吗（Windows 上应当仍是） ---
win.showNormal()
settle()
win.showMaximized()
settle()
was_max = win.isMaximized()
win.showMinimized()
settle(800)
state_while_min = int(win.windowState().value)
win.bring_to_front()
settle(800)
line("先最大化再最小化 → bring_to_front()：还原后**仍是最大化**（Windows 上）",
     was_max and not win.isMinimized() and win.isMaximized(),
     f"最小化期间 state={state_while_min}（7 = WindowMinimized|WindowMaximized，"
     f"Qt 把最大化位保留在最小化态里）；离屏上这一档会掉成普通大小，故不入离屏断言")

# --- 收尾 ---
print()
bad = [r for r in REPORT if r.startswith("FAIL")]
print(f"真机探针：{len(REPORT)} 项，失败 {len(bad)} 项")
print("ALL_OK" if not bad else "FAILED")

win.mark_quitting()                        # 否则 close() 会走「最小化到托盘」被拦下
win.close()
settle(200)
sys.exit(1 if bad else 0)
