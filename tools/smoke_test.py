"""冒烟测试：离屏渲染验证 GUI、桌宠、角色切换、托盘。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import load_config  # noqa: E402
from app.gui import MainWindow  # noqa: E402
from app.pet import PetWindow  # noqa: E402
from app.state import State  # noqa: E402


def main():
    app = QApplication([])
    cfg = load_config()
    original_role = cfg.get("current_role", "alice")
    role_key = original_role
    pet_dir = ROOT / cfg["roles"][role_key]["pet_dir"]

    win = MainWindow(cfg)
    pet = PetWindow(pet_dir)
    pet.set_roles([(r["name"], k) for k, r in cfg["roles"].items()])
    pet.set_current_role("alice")
    assert pet._current_key == "alice", "set_current_role 失效"

    for state in State:
        pet.set_state(state.value)
        win.set_status(state)
        app.processEvents()

    loaded = {s: len(pet._frames_for(s.value)) for s in State}
    assert all(n > 0 for n in loaded.values()), f"存在状态无图片: {loaded}"

    # 角色切换：切到艾莲，验证贴图加载
    pet.set_pet_dir(ROOT / cfg["roles"]["ellen"]["pet_dir"])
    app.processEvents()
    assert len(pet._frames_for("idle")) > 0, "艾莲贴图加载失败"

    # 验证主窗口切换角色会联动换贴图（经 role_change_cb）
    pet.set_pet_dir(ROOT / cfg["roles"]["alice"]["pet_dir"])
    calls = []
    win.set_role_change_cb(
        lambda k: (calls.append(k), pet.set_pet_dir(ROOT / cfg["roles"][k]["pet_dir"]))
    )
    win.set_current_role("ellen")
    app.processEvents()
    assert "ellen" in calls and pet.pet_dir == ROOT / cfg["roles"]["ellen"]["pet_dir"], (
        "窗口切换未联动换贴图"
    )
    print("switch_cb_ok")

    # 测试嵌入面板切换（聊天 ↔ API ↔ 唤醒词）
    win._switch_right_panel(1)  # API 面板
    app.processEvents()
    assert win._right_stack.currentIndex() == 1, "API 面板切换失败"
    win._switch_right_panel(2)  # 唤醒词面板
    app.processEvents()
    assert win._right_stack.currentIndex() == 2, "唤醒词面板切换失败"
    win._switch_right_panel(0)  # 聊天面板
    app.processEvents()
    print("panel_switch_ok")

    # 托盘（离屏环境可能不可用，做容错）
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QSystemTrayIcon
        tray = QSystemTrayIcon(QIcon(str(ROOT / "assets" / "icon" / "app_icon.png")), app)
        tray.show()
        print("tray_ok")
    except Exception as e:
        print("tray_skip:", e)

    print("SMOKE_OK")
    print("各状态帧数：", loaded)

    # 恢复 config 的 current_role，避免污染真实配置
    from app.config import save_config
    cfg["current_role"] = original_role
    save_config(cfg)


if __name__ == "__main__":
    main()
