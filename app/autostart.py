"""开机自启：写当前用户注册表 Run 项（不需要管理员权限）。

写入位置：HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
值名：IgnotusAssistant，值数据：启动命令行。

命令行优先用 pythonw.exe（无控制台黑窗），冻结打包后直接用 exe 本身；
末尾带 `--autostart` 标记，程序据此**静默启动**（不显示主界面，直接待在托盘）。

⚠️ 注册表里存的是**绝对路径**，项目目录一旦移动 / 改名就会失效（开机时啥也不会发生）。
因此提供 `refresh_command()`：启动时比对「注册表里的命令」与「当前应当写入的命令」，
不一致就地改写，等于把失效的启动项自愈掉。
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "IgnotusAssistant"

# 开机自启专用标记：程序看到它就不显示主界面，直接进托盘、桌宠在桌面待机
AUTOSTART_FLAG = "--autostart"


def launch_command() -> str:
    """返回写入注册表的启动命令行（带引号，路径含空格也安全）。"""
    if getattr(sys, "frozen", False):          # PyInstaller 等冻结打包
        return f'"{sys.executable}" {AUTOSTART_FLAG}'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")          # 同目录下的无控制台解释器
    if pyw.exists():
        exe = pyw
    return f'"{exe}" "{BASE_DIR / "run.py"}" {AUTOSTART_FLAG}'


def is_autostart_launch(argv=None) -> bool:
    """本次启动是否来自开机自启（命令行带 `--autostart`）。"""
    args = sys.argv if argv is None else argv
    return AUTOSTART_FLAG in [str(a) for a in args]


def _norm(cmd: str) -> str:
    """命令行的比较用规范化：统一分隔符 / 大小写 / 连续空白。

    Windows 路径大小写不敏感、`\\` 与 `/` 等价，直接比字符串会把"同一件事"
    误判成"变了"从而每次都改写注册表。
    """
    return " ".join(str(cmd or "").replace("/", "\\").split()).lower()


def current_command() -> str:
    """返回注册表里已登记的命令（无则空串），用于界面展示实际值。"""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except OSError:
        return ""


def is_enabled() -> bool:
    """开机自启是否已开启（以注册表实际状态为准）。"""
    return bool(current_command())


def enable() -> tuple[bool, str]:
    """开启开机自启，返回 (是否成功, 提示文案)。"""
    try:
        import winreg
    except ImportError:
        return False, "当前系统不支持注册表自启（仅 Windows）。"
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        return True, "已设置开机自启。"
    except OSError as e:                        # noqa: BLE001
        return False, f"设置失败：{e}"


def disable() -> tuple[bool, str]:
    """关闭开机自启，返回 (是否成功, 提示文案)。"""
    try:
        import winreg
    except ImportError:
        return False, "当前系统不支持注册表自启（仅 Windows）。"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True, "已关闭开机自启。"
    except FileNotFoundError:
        return True, "开机自启本来就是关闭状态。"
    except OSError as e:                        # noqa: BLE001
        return False, f"取消失败：{e}"


def refresh_command() -> tuple[bool, str]:
    """已开启自启但登记的命令已过时 → 就地改写为当前命令行（自愈）。

    什么时候会过时：项目目录被移动 / 改名（`run.py`、`.venv` 的绝对路径都变了）、
    重新建了虚拟环境（解释器换了）、旧版本写的是不带 `--autostart` 的命令。

    返回 `(是否改写了, 说明)`：
    - 没开自启 → `(False, "")`，**不会**顺手把自启打开；
    - 已开启且命令一致 → `(False, "")`，什么都不做；
    - 已开启但过时 → 改写成功返回 `(True, 新命令)`；失败返回 `(False, 错误说明)`。
    """
    reg = current_command()
    if not reg:
        return False, ""
    want = launch_command()
    if _norm(reg) == _norm(want):
        return False, ""
    ok, msg = enable()                      # enable() 写的就是当前命令行
    if not ok:
        return False, msg
    return True, want

