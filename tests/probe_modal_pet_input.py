"""量测：弹窗的**窗口模态**会不会连坐桌宠窗（真机端到端证据）。

**为什么要单独一个脚本、且不进 `run_all`**：
  `run_all` 全部套件都跑 `QT_QPA_PLATFORM=offscreen`，而「被拦」这件事在 offscreen 上**根本没有印记**
  （`QPlatformWindow::setBlockedByModal` 是空实现）。本脚本必须用**真 windows 平台**、造**真 HWND**，
  会弹几个小窗口出来 —— 所以只做**手动量测**用，别挂进自动套件。

**判据**：窗口被模态拦住时，Qt（Windows 平台）会对它 `EnableWindow(hwnd, FALSE)` ——
  用 `IsWindowEnabled` 就能读到，这是 Python 侧唯一能观测到「拦没拦住」的印记
  （`QWidget.isEnabled()` **不变**，别拿它当判据；`QTest` 的合成点击也**绕不过**模态）。

**量的是项目真货**：`dlg` 直接用 `app.gui.ConfirmDialog`（父窗 = 主窗），所以这份输出同时证明
  ①我们的弹窗确实设成了 WindowModal；②WindowModal 在这台机器上真的只锁父窗。

跑法：
    .venv\\Scripts\\python.exe tests\\probe_modal_pet_input.py
退出码：0 = 与预期一致；1 = 不符（Qt 语义变了，`app/gui.py` 的 `_CardDialog.MODALITY` 要重看）。
"""
import ctypes
import os
import sys
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)      # ★必须真平台；offscreen 读不到 IsWindowEnabled

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt                                    # noqa: E402
from PySide6.QtTest import QTest                                 # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget              # noqa: E402

u32 = ctypes.windll.user32


def enabled(win) -> bool:
    """真 HWND 上问「这个窗口还是 enabled 吗」—— 被拦 ⇒ False。"""
    return bool(u32.IsWindowEnabled(int(win.winId())))


def measure(dlg):
    """返回 (主窗被拦, 桌宠窗被拦)。"""
    return (not enabled(dlg.parentWidget()), not enabled(dlg._probe_pet))


def run(app, mode_name, make_dlg):
    main = QWidget()
    main.resize(320, 220)
    main.move(60, 60)
    main.show()

    # ★与 app/pet.py::PetWindow 完全同款：无 parent + 这三个窗口标志
    pet = QWidget()
    pet.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    pet.resize(110, 110)
    pet.move(560, 60)
    pet.show()

    dlg = make_dlg(main)
    dlg._probe_pet = pet                 # 只给量测用，不进生产代码
    dlg.show()

    QTest.qWaitForWindowExposed(main, 2000)
    QTest.qWaitForWindowExposed(pet, 2000)
    QTest.qWaitForWindowExposed(dlg, 2000)
    QTest.qWait(400)

    got = measure(dlg)
    info = (dlg.windowModality(),
            pet.windowHandle().transientParent(),
            dlg.windowHandle().transientParent() is main.windowHandle())

    dlg.close(); dlg.deleteLater()
    pet.close(); pet.deleteLater()
    main.close(); main.deleteLater()
    QTest.qWait(200)
    return got, info


def main_() -> int:
    app = QApplication(sys.argv)
    print("platform =", app.platformName())
    if app.platformName() != "windows":
        print("!! 需要真 windows 平台（当前 %s）⇒ 无法量测，退出" % app.platformName())
        return 2

    import app.gui as gui

    # (名字, 造弹窗的函数, 期望 (主窗应被拦, 桌宠窗应被拦))
    cases = [
        ("现役 ConfirmDialog", lambda p: gui.ConfirmDialog(p, "确定要卸载吗？"), (True, False)),
        # 对照：ApplicationModal（= 2026-10-01 之前 setModal(True) 的等价物）
        ("对照 ApplicationModal", _old_style(gui), (True, True)),
    ]

    bad = []
    for name, make_dlg, exp in cases:
        (main_blocked, pet_blocked), (modality, pet_par, dlg_par_ok) = run(app, name, make_dlg)
        ok = (main_blocked, pet_blocked) == exp
        print("%-22s 模态=%-26s 主窗被拦=%-5s 桌宠被拦=%-5s  期望(主窗=%s/桌宠=%s)  %s"
              % (name, modality, main_blocked, pet_blocked, exp[0], exp[1],
                 "OK" if ok else "!! 不符"))
        print("    pet.transientParent()=%s   dlg.transientParent() is mainWin=%s"
              % (pet_par, dlg_par_ok))
        if not ok:
            bad.append(name)

    if bad:
        print("\n结论：与预期不符（%s）—— Qt 的模态语义变了？"
              " 复核 app/gui.py 的 `_CardDialog.MODALITY` 与 docs/02 §28。" % ", ".join(bad))
        return 1
    print("\n结论：现役弹窗 = WindowModal ⇒ **主窗照旧拦住、桌宠窗仍 enabled**（可点 / 可右键）；"
          "\n      旧写法 ApplicationModal ⇒ 桌宠窗一起被禁（= 用户报的「一弹窗就点不动桌宠」）。")
    return 0


def _old_style(gui):
    """对照：把弹窗设成 **ApplicationModal**（2026-10-01 之前 `setModal(True)` 的等价物）。

    ★这里**不能**用 `dlg.setModal(True)` 来复现旧行为：`setModal()` 里有一句
      「`modal == isModal()` 就提前 return」，而 `isModal()` = `windowModality() != NonModal`
      —— 基类已经把它设成 WindowModal（也算「模态」）⇒ `setModal(True)` 是**空操作**，
      模态值原地不动（实测：`windowModality()` 仍报 WindowModal）。
      所以要直改 `windowModality` 才能拿到 ApplicationModal 的效果。
    """
    def make(parent):
        dlg = gui.ConfirmDialog(parent, "确定要卸载吗？")
        dlg.setWindowModality(Qt.ApplicationModal)
        return dlg
    return make


if __name__ == "__main__":
    sys.exit(main_())
