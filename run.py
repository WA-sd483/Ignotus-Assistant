"""启动入口：python run.py（开机自启用 pythonw.exe 调用，无控制台窗口）。"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 开机自启走 pythonw.exe 时没有控制台，sys.stdout/stderr 为 None：
# print() 本身安全，但部分库会直接写 stream，这里兜底到 devnull。
for _name in ("stdout", "stderr"):
    if getattr(sys, _name, None) is None:
        try:
            setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))
        except OSError:
            pass

# 注册表启动项无法指定工作目录，这里固定到项目根，保证相对路径一致
os.chdir(BASE_DIR)

# ★日志与「未捕获异常」钩子必须在 `import app.main` **之前**装好：
#   否则 `from app.main import main` 本身失败（缺依赖 / 语法错）时没有任何痕迹。
#   ★幂等 —— `main()` 里还会再调一次；那一次是给**打包形态**兜底的：
#   exe 走的是 `make_stage.py` 生成的 `entry.py`，它不经过本文件。
from app.logging_setup import setup as _setup_logging  # noqa: E402
_setup_logging()

from app.main import main  # noqa: E402  （需在 chdir 之后导入，保证路径基于项目根）

if __name__ == "__main__":
    raise SystemExit(main())
