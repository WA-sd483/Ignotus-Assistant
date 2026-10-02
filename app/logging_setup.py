"""全局日志 + 未捕获异常兜底：把「静默失败」变成「可查的痕迹」。

★这个模块解决什么问题（2026-10-01 第五批）
    此前全项目 `logging` / `sys.excepthook` / `threading.excepthook` / `faulthandler`
    **零命中**。而 5 个后台线程全是 `daemon=True` ⇒ 线程抛异常时**进程照活**，
    用户看到的是「AI 不回复」「没声音」「唤不醒」，而异常对象被 Python 丢进垃圾桶，
    **一个字节都不留**。`print` 也救不了：`pythonw` / `console=False` 下
    `sys.stdout is None`（`run.py:8-15`、`entry.py` 都在给这个兜底）。

★为什么落 %LOCALAPPDATA% 而不是项目根
    ① `pythonw` 没有控制台 ⇒ 落文件是唯一出路；
    ② 项目根可能是只读位置（Program Files / 只读盘），exe 形态下只有用户目录一定可写；
    ③ 放用户目录天然不进 git，不必像 `launch_task.log` 那样再往 `.gitignore` 加一行。

★三条禁令（改了会静默失效）
    ① **不许**去掉 `threading.excepthook` —— `sys.excepthook` **只管主线程**，
       子线程异常从来不经过它。只装前者会给出「我加了兜底」的**假安全感**。
    ② **不许**把 `propagate` 改回 `True` —— 那会让 `sherpa_onnx` / `onnxruntime` /
       `PySide6` 的噪音灌进日志文件（几百 MB 级）。
    ③ **不许**在这里 import 任何本项目其它模块 —— 它必须能被最先导入，
       否则「导入期就崩」这一类失败仍然抓不到。
"""
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 自家日志的根名。子 logger 用 `get_logger("xxx")` ⇒ `ignotus.xxx`。
LOGGER_NAME = "ignotus"

# 单文件上限 1 MB、留 3 个滚动备份 ⇒ 最多占 4 MB。够查一次事故，也不会撑爆磁盘。
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3

# 模块级持有：`faulthandler` 要求文件对象**一直活着**，被 GC 掉就没输出了。
_fault_file = None


def log_dir() -> Path:
    """日志目录。★测试用 `IGNOTUS_LOG_DIR` 指到临时目录，避免污染真实用户目录。"""
    override = os.environ.get("IGNOTUS_LOG_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "IgnotusAssistant" / "logs"


def get_logger(name: str = "") -> logging.Logger:
    """取一个子 logger。**可以在 `setup()` 之前调用** —— handler 是 emit 时才沿层级找的。"""
    return logging.getLogger(LOGGER_NAME + ("." + name if name else ""))


def _attach_file_handler(logger: logging.Logger, level: int) -> Path:
    path = log_dir() / "app.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    handler.setLevel(level)
    logger.addHandler(handler)
    return path


def _install_hooks(logger: logging.Logger) -> None:
    """装上「未捕获异常」的两个钩子。★两个都要，缺一不可（见模块 docstring 禁令①）。"""

    def _uncaught(exc_type, exc, tb, where: str) -> None:
        logger.critical("未捕获异常（%s）", where, exc_info=(exc_type, exc, tb))

    # ① 主线程：默认行为是把 traceback 打到 stderr ⇒ pythonw 下等于丢进 devnull
    sys.excepthook = lambda t, e, tb: _uncaught(t, e, tb, "主线程")

    # ② 子线程：Python 3.8+ 才有这个钩子。★daemon 线程的主要死法就在这里
    def _thread_hook(args) -> None:
        if args.exc_type is SystemExit:      # 线程里正常退出不算异常
            return
        name = args.thread.name if args.thread is not None else "?"
        _uncaught(args.exc_type, args.exc_value, args.exc_traceback, f"线程 {name}")

    threading.excepthook = _thread_hook


def _enable_faulthandler() -> None:
    """原生崩溃（段错误）时 `excepthook` **完全抓不到** —— 要靠 `faulthandler`。

    Qt / onnxruntime / portaudio 都是原生代码，崩起来是「整个进程瞬间消失」，
    没有任何 Python traceback。这条把「所有线程 + 原生栈」落到 `crash.log`。
    """
    global _fault_file
    if _fault_file is not None:
        return
    try:
        import faulthandler
        path = log_dir() / "crash.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        # buffering=0 ⇒ 崩的那一刻已经落盘，不留 OS 缓冲
        _fault_file = open(path, "ab", buffering=0)
        faulthandler.enable(file=_fault_file, all_threads=True)
    except Exception:      # noqa: BLE001  —— 拿不到就算了，绝不能因为它启动不了
        _fault_file = None


def setup(level: int = logging.INFO) -> Path | None:
    """装上文件日志 + 未捕获异常钩子 + faulthandler。**幂等**：重复调用是空操作。

    返回日志文件路径；连目录都建不出来时返回 `None`（此时钩子仍会装上，
    只是写不出去 —— 宁可「没日志」，也绝不「因为日志起不来而开不了机」）。
    """
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_ignotus_ready", False):
        return getattr(logger, "_ignotus_path", None)

    logger.setLevel(level)
    logger.propagate = False            # ★禁令②：别往 root 冒泡

    path = None
    try:
        path = _attach_file_handler(logger, level)
    except OSError:
        pass                            # 目录只读 / 无权限 ⇒ 退化为「只在内存里」

    _install_hooks(logger)
    _enable_faulthandler()

    logger._ignotus_ready = True        # type: ignore[attr-defined]
    logger._ignotus_path = path         # type: ignore[attr-defined]
    return path
