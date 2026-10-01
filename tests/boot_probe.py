"""启动探针：真实跑一次 `app.main.main()`，把启动后的界面状态写成 JSON。

由 `tests/smoke_autostart.py` 以子进程调用（QApplication 一个进程只能建一个，
而「自启启动」与「普通启动」必须各跑一个进程才能对比）。

环境变量：
    BOOT_PROBE_OUT     结果 JSON 的写出路径（必填）
    BOOT_PROBE_SILENT  "1" = 模拟开机自启启动（sys.argv 带 --autostart）
    BOOT_PROBE_STALE   "1" = 模拟注册表里的启动项已过时（验证启动时自愈）

探针**不写注册表**：autostart 的读写函数全部替换为假实现；
同时预置 app.asr / app.tts 的轻量替身，避免拉起 ASR 模型与 GPT-SoVITS 服务。
"""
import json
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

OUT = Path(os.environ["BOOT_PROBE_OUT"])
SILENT = os.environ.get("BOOT_PROBE_SILENT") == "1"
STALE = os.environ.get("BOOT_PROBE_STALE") == "1"


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class _FakeMic:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass

    def stop(self):
        pass


# 轻量替身：语音识别（不加载 sherpa 模型）与语音合成（不拉起 GPT-SoVITS 服务）
_stub("app.asr", MicListener=_FakeMic, Recognizer=lambda *a, **k: object())
_stub(
    "app.tts",
    # ★替身必须与 `app/tts.py` 的**公开名**对齐：`main.py` 的 worker 线程会
    #   `from .tts import DEFAULT_TEXT_LANGUAGE, ...` —— 替身少了这个名字，
    #   线程会**静默死掉**（ImportError 只打在 stderr），表现为「AI 一直不回复」。
    #   2026-09-30 加「回复语言」常量时漏了同步，实测让 smoke_permissions /
    #   smoke_sleep / reply_probe 三套集体假红。
    DEFAULT_TEXT_LANGUAGE="ja",
    TEXT_LANGUAGE_NAMES={"zh": "中文", "en": "英语", "ja": "日语"},
    start_in_background=lambda *a, **k: None,
    set_volume=lambda *a, **k: None,
    set_muted=lambda *a, **k: None,
    is_muted=lambda: False,
    synthesize_with_bang=lambda *a, **k: "",
    play_wav=lambda *a, **k: None,
)

from app import autostart  # noqa: E402

# 注册表只读化（+ 可选的「启动项过时」模拟）
if STALE:
    autostart.current_command = lambda: '"C:\\old\\pythonw.exe" "C:\\old\\run.py"'
else:
    autostart.current_command = lambda: ""
autostart.is_enabled = lambda: bool(autostart.current_command())
autostart.enable = lambda: (True, "已设置开机自启。")
autostart.disable = lambda: (True, "已关闭开机自启。")

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app.main as m  # noqa: E402

captured = {}
messages = []


class _SpyWindow(m.MainWindow):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        captured["win"] = self

    def add_system_message(self, text, *a, **k):
        messages.append(str(text))
        return super().add_system_message(text, *a, **k)


class _SpyPet(m.PetWindow):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        captured["pet"] = self


class _FakeTray(QObject):
    """托盘替身：不带系统托盘（offscreen 平台不可靠），只保证调用链跑通。"""

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


class _ShortApp(QApplication):
    """接管 exec()：跑一小段事件循环就返回，让 main() 正常收尾。"""

    def exec(self):
        loop = QEventLoop()
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        return 0


m.MainWindow = _SpyWindow
m.PetWindow = _SpyPet
m.QSystemTrayIcon = _FakeTray
m.QApplication = _ShortApp

# main() 里 is_autostart_launch() 读 sys.argv —— 这里精确控制它
sys.argv = ["run.py"] + ([autostart.AUTOSTART_FLAG] if SILENT else [])

# ★打点（`flush=True` 必须给）：本探针偶发**挂起**过（父进程 300s 超时强杀）。
#   管道是**块缓冲**，不打点的话超时时只能看到空输出，定位不到挂在哪一步；
#   有这两行就能一眼分辨「挂在 main() 里」还是「挂在 main() 之后」。
print("probe: 即将跑 main()", flush=True)
rc = m.main()
print(f"probe: main() 已返回 rc={rc}", flush=True)

win = captured["win"]
pet = captured["pet"]
data = {
    "rc": rc,
    "silent_boot": SILENT,
    "stale": STALE,
    "win_visible_at_start": win.isVisible(),
    "pet_visible_at_start": pet.isVisible(),
    "pet_state_at_start": pet._state,
    "page_index": win._right_stack.currentIndex(),
    "settings_mode": bool(getattr(win, "_settings_mode", False)),
    "messages": list(messages),
}

# 托盘点一下能把主界面叫回来
win.bring_to_front()
data["win_visible_after_tray_click"] = win.isVisible()
data["page_index_after_tray_click"] = win._right_stack.currentIndex()
data["pet_state_after_tray_click"] = pet._state
data["window_size_after_tray_click"] = [win.width(), win.height()]
data["left_is_role_page_after_tray_click"] = (
    win._left_stack.currentWidget() is win._left_role_page
)

OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("probe done")
