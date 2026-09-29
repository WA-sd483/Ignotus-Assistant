"""GPT-SoVITS 一键下载（**二期**，2026-09-22 夜）：代码体 → venv → 依赖 → 日语词典 → 模型 → 校验。

★**纯逻辑模块：不 import Qt** —— 与 `voice_model.py` 同一条理由（离线可断言、可脱离 QApplication 跑）。
与界面之间只通过**线程安全的快照**往来，快照里**只有 str / int / bool**（项目铁律：跨线程只传这几样）。

需求与判据见 `docs/01` F7、`docs/02` §22.6（含**逐条实测**的源表与「下什么 / 不下什么」）。三条要点：

1. **只下要的**：`sv/`、`g2pw-chinese`、`nltk_data`、`uvr5_weights`、`ffmpeg.exe` **一律不下** ——
   本项目锁日语 + `api.py -d cpu`，那些分支走不到（判据逐条写在 `docs/02` §22.6.2）。
2. **日语词典是必需**（`open_jtalk_dic`，23.6 MB）：`pyopenjtalk` 的词典不在 wheel 里，不预下就会在
   **首次合成时**才去 GitHub 现下，失败即「说不了话」。
3. **「卸载后重装」只跑模型那一段**：探测到代码体 / venv / 依赖都在 ⇒ 跳过前四段（1.15 GB，1~3 分钟）。
   ★判据用**实际探测**（文件在不在、`import torch` 能不能过），**不拿标记文件当唯一依据**。

六段流水线与段权重见 `STAGE_WEIGHTS`；总百分比由**纯函数** `overall_percent()` 折算（可离线断言）。
"""
import json
import os
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import voice_model

# ---------------------------------------------------------------- 源（逐条实测，见 docs/02 §22.6.1）

GITHUB_REPO = "RVC-Boss/GPT-SoVITS"
# ★与本机现有安装同一 commit（`git log -1` 取的真值），保证下出来的代码体和跑通的这套一致
CODE_COMMIT = "48b1a0169a28582a8984402f82cf438d3bfa6aca"
CODE_ZIP_URL = "https://codeload.github.com/%s/zip/%s" % (GITHUB_REPO, CODE_COMMIT)
CODE_ZIP_BYTES = 0          # codeload 是流式响应，不给 Content-Length ⇒ 0 = 不校验大小
# 代码包的**估算**体积，只用来推段内进度（真实大小拿不到）。
# ★codeload 实测只有 **33 KB/s**（2026-09-22 夜，GitHub 直连在国内被限速；镜像候选
#   ghfast / gh-proxy / ghproxy / gitmirror / kkgithub 实测全部更慢或直接不通）
#   ⇒ 这 15 MB 要下 ~7 分钟，所以那一屏**必须显示「已下多少 MB」**，不能只给百分比。
CODE_EST_BYTES = 15 * 1024 * 1024

# 模型 4 个文件走 hf-mirror（逐文件可达且长度齐全）
HF_MODEL_BASE = "https://hf-mirror.com/lj1995/GPT-SoVITS/resolve/main"
# ★`lid.176.bin` **不在 hf 仓库**（实测 404）——它的真源是 `fast_langdetect` 包内置的
#   `FASTTEXT_LARGE_MODEL_URL`（fast_langdetect/infer.py:23）。实测 len 与 voice_model.MODEL_FILES
#   里的 131266198 **逐字节一致**。这条曾经写错过，测试里有断言钉住主机名。
LID176_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin"

# 日语 G2P 词典（pyopenjtalk 用；解压后落到 venv 的 site-packages/pyopenjtalk/ 下）
OPEN_JTALK_DIR_NAME = "open_jtalk_dic_utf_8-1.11"
OPEN_JTALK_URL = ("https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/"
                  "open_jtalk_dic_utf_8-1.11.tar.gz")
OPEN_JTALK_URL_BACKUP = ("https://github.com/r9y9/open_jtalk/releases/download/v1.11.1/"
                         "open_jtalk_dic_utf_8-1.11.tar.gz")
OPEN_JTALK_BYTES = 23646843

# pip 索引。★tuna / ustc 实测 **403**（HEAD 与 GET 都试过）⇒ 不要写进去；测试里有断言钉住。
PIP_INDEX = "https://mirrors.aliyun.com/pypi/simple"
PIP_INDEX_BACKUP = "https://pypi.org/simple"
# torch **CPU 版**专用索引。★2026-09-22 夜**真下 20 s 算平均速度**测出来的：
#   上海交大镜像 **3.0 MB/s** vs 官方 `download.pytorch.org` **0.8 MB/s**
#   —— torch 那 1.23 GB 从「约 26 分钟」压到「约 7 分钟」。⇒ **sjtu 主、官方备**。
#   （tuna / ustc 的 pytorch-wheels 实测 403；aliyun 有但只有 0.35 MB/s。）
TORCH_INDEX = "https://mirror.sjtu.edu.cn/pytorch-wheels/cpu"
TORCH_INDEX_BACKUP = "https://download.pytorch.org/whl/cpu"
TORCH_SPEC = ("torch", "torchaudio")

# 依赖清单用 **cpu 版**：`requirements.txt` 写的是 `onnxruntime-gpu`，而本机 venv 实测装的是
# `onnxruntime==1.19.2` ⇒ 这台机器当初就是按 CPU 清单装的（与 `api.py -d cpu` 一致）。
REQUIREMENTS_FILE = "requirements_cpu.txt"

# ---------------------------------------------------------------- 六段流水线

PHASE_IDLE = "idle"
PHASE_CODE = "code"
PHASE_UNPACK = "unpack"
PHASE_DEPS = "deps"
PHASE_ASSETS = "assets"
PHASE_MODEL = "model"
PHASE_VERIFY = "verify"
PHASE_DONE = "done"

# 段权重（合 100）。`deps` 占 52 是因为它**又大又慢**（2.4 GB + pip 解析）。
STAGE_WEIGHTS = (
    (PHASE_CODE, 3),
    (PHASE_UNPACK, 3),
    (PHASE_DEPS, 52),
    (PHASE_ASSETS, 3),
    (PHASE_MODEL, 32),
    (PHASE_VERIFY, 7),
)

# 段的中文说法（界面 hint 用）
STAGE_LABELS = {
    PHASE_CODE: "正在下载程序主体",
    PHASE_UNPACK: "正在解压并创建运行环境",
    PHASE_DEPS: "正在下载运行依赖（约 2.4 GB）",
    PHASE_ASSETS: "正在下载日语词典",
    PHASE_MODEL: "正在下载音色克隆模型",
    PHASE_VERIFY: "正在校验",
    PHASE_DONE: "下载完成",
}

# pip 包计数式粗进度的分母：本机 venv 实测 187 个包，留点余量。
# ★这是**启发式**，只影响进度条平滑度，不参与任何判据（见 docs/02 §22.6.3）。
DEPS_EXPECTED_PACKAGES = 190

CHUNK = 256 * 1024          # 每块 256 KB
HTTP_TIMEOUT = 60           # 单次连接 / 读超时（大文件靠块级超时兜，不设总时限）
DOWNLOAD_TRIES = 3          # 单个文件的尝试次数（含首次）
PART_SUFFIX = ".part"       # 临时名；下完（且大小吻合）才 os.replace 成正式名
USER_AGENT = "IgnotusAssistant/1.0"

MARKER_NAME = ".ignotus_install.json"   # 安装记录（给人看；**不参与**「模型是否就位」判据）


# ---------------------------------------------------------------- 纯函数（离线可断言）

def overall_percent(phase, frac=1.0) -> int:
    """段 id + 段内完成度(0~1) → 总百分比(0~100)。**纯函数**，不碰任何全局状态。

    性质（测试逐个钉住）：`idle`→0、`done`→100、段内 frac 从 0 到 1 **单调不减**、
    frac 越界（负数 / >1）**收敛**到 [0,1] 而不是算飞、**不认识的 phase 返回 0**。
    """
    if phase == PHASE_DONE:
        return 100
    if phase == PHASE_IDLE:
        return 0
    try:
        f = float(frac)
    except (TypeError, ValueError):
        f = 0.0
    f = 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)
    total = sum(w for _, w in STAGE_WEIGHTS) or 1
    acc = 0
    for sid, w in STAGE_WEIGHTS:
        if sid == phase:
            return int(round((acc + w * f) * 100.0 / total))
        acc += w
    return 0


def resume_offset(dest) -> int:
    """续传起点 = 同名 `.part` 文件现有的字节数（没有就是 0）。

    ★只看 `.part`：正式文件要么完整（外层的「已完成」判断直接跳过它），要么根本不存在
    —— 永远不会留一个「半截的正式文件」在那儿（下完才 `os.replace`）。
    """
    try:
        return Path(str(dest) + PART_SUFFIX).stat().st_size
    except OSError:
        return 0


def file_size(path) -> int:
    """文件字节数；不存在 / 读不到返回 -1（**不要**返回 0 —— 0 是合法的空文件大小）。"""
    try:
        return Path(path).stat().st_size
    except OSError:
        return -1


def size_matches(path, expected) -> bool:
    """文件是否存在且字节数正好等于 `expected`；`expected` 为 0 时只要求存在。"""
    n = file_size(path)
    if n < 0:
        return False
    return n == expected if expected else True


def model_targets():
    """模型全部所需文件的 `[{"rel", "url", "bytes"}]`（权重 + 配套小文件）。

    `rel` / `bytes` **直接取自 `voice_model.required_model_files()`** —— 那是「已下载」判据的
    真值，这里绝不再抄一份（两个真值迟早会漂移）。
    ★★**必须是「全部所需」而不是「5 个大权重」**：2026-09-27 实测，只下 5 个大权重会漏掉
      `chinese-*/config.json`、`tokenizer.json` 这 4 个小文件 ⇒ `api.py` 起来就崩、没有声音，
      但「已下载」判据那边却一直是绿的。两处**同源**才不会再次劈叉。
    """
    out = []
    for rel, n in voice_model.required_model_files().items():
        if rel.endswith("lid.176.bin"):
            url = LID176_URL
        else:
            url = "%s/%s" % (HF_MODEL_BASE, rel)
        out.append({"rel": rel, "url": url, "bytes": n})
    return out


# ---------------------------------------------------------------- 「全量 / 仅模型」与确认文案

# 「全量下载」的总体积（GB）。★**唯一定义在 `voice_model.FULL_INSTALL_GB`**，这里只是引用。
#   （构成明细也写在那儿：代码包 + venv 本体 + 依赖 + 日语词典 + 模型 5 文件 ≈3.7 ⇒ 取 3.6。）
#   为什么必须单选一处：弹窗文案（本模块）与卸载弹窗文案（`voice_model`）报的是**同一批东西**，
#   各写一份 ⇒ 改一处、另一处静默漂移 ⇒ 两个弹窗对用户说两个数。测试里钉住两者相等、
#   且「文案里出现的数字 == 这个常量」。
FULL_DOWNLOAD_GB = voice_model.FULL_INSTALL_GB
FULL_NOTICE = "此次下载为全量下载，共约 %.1f GB" % FULL_DOWNLOAD_GB

# 确认框的头一行与末一行（用户逐字给定，别改写、别合并）
CONFIRM_LEAD = "合成语音时将大幅减缓AI回复速度"
CONFIRM_ASK = "是否下载？"


def confirm_message(is_full: bool) -> str:
    """点「下载」时那条确认文案。**纯函数**（离线可断言，不碰任何全局状态）。

    - 全量（代码体 / venv / 依赖都不在 ⇒ 六段全跑）：**三行**，中间那行报总体积；
    - 仅模型（代码体 / venv / 依赖都在 ⇒ 只跑 ⑤⑥）：**两行**。

    ★中间那行**必须按 `is_full` 决定有无**：「共约 3.6 GB」对「只重下 1.15 GB 模型」的机器
      是**错的**，所以它不能是常量字符串里的固定一段。用户口径（2026-09-27）：
      「将这段提示插入上条命令添加的弹窗提示中间」= 插在头一行与末一行**之间**。
    """
    lines = [CONFIRM_LEAD]
    if is_full:
        lines.append(FULL_NOTICE)
    lines.append(CONFIRM_ASK)
    return "\n".join(lines)


def is_full_install(cfg=None, root=None) -> bool:
    """这次下载要不要**全量** —— 与流水线实际跳不跳段用的是**同一个判据**（`probe_layers().full`）。

    ★不许另算一套：两套判据迟早漂移，就会出现「弹窗说只下 1.15 GB、实际下了 3.6 GB」。
    只 stat 文件，毫秒级，可在 UI 线程里同步调。
    """
    target = Path(root) if root else voice_model.install_root(cfg)
    return bool(probe_layers(target)["full"])


# ---------------------------------------------------------------- 环境探测

def find_system_python():
    """找一个能用来给 GPT-SoVITS 建 venv 的 Python，返回 (exe 路径, 版本串)；找不到返回 (None, "")。

    GPT-SoVITS 的 README 写「3.10~3.12」，但★本机真机这套 venv 是 **3.9.13** 且跑得好好的
    ⇒ 3.9 也在白名单里（「本机已验证可行」优先于文档口号）。顺序：`py -3.9` … `py -3.12`，
    再退化到 `sys.executable`（至少保证有个能建 venv 的解释器）。
    """
    for tag in ("-3.9", "-3.10", "-3.11", "-3.12"):
        exe = _which_py(tag)
        if exe:
            return exe, tag.lstrip("-")
    return None, ""


def _which_py(tag):
    """用 `py <tag> -c "import sys;print(sys.executable)"` 问出该版本的真实路径。"""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(["py", tag, "-c", "import sys;print(sys.executable)"],
                           capture_output=True, text=True, timeout=20, creationflags=flags)
        if r.returncode == 0:
            p = (r.stdout or "").strip().splitlines()
            if p and Path(p[-1]).is_file():
                return p[-1]
    except Exception:  # noqa: BLE001
        pass
    return None


def venv_python(root):
    """安装目录里的 venv 解释器路径。

    ★实现**只此一处**（在 `voice_model.VENV_PY_REL`）—— 下载侧与 `voice_model` 的
    「像不像安装根」判据必须指向同一个文件，两边各写一遍迟早漂移。
    """
    return voice_model.venv_python(root)


def probe_layers(root) -> dict:
    """**轻量**探测（只 stat 文件，毫秒级，可在 UI 线程里同步调）：

    返回 `{"code": bool, "venv": bool, "deps": bool, "model": bool, "full": bool}`。
    `deps` 这里只代表「venv 在」（真正能不能 `import torch` 要起子进程，放下载线程里复核）。
    """
    root = Path(root)
    code = (root / "api.py").is_file() and (root / "GPT_SoVITS").is_dir()
    venv = venv_python(root).is_file()
    model = voice_model.is_model_dir_ok(root / voice_model.MODEL_SUBDIR)
    # 代码体 + venv 都在 ⇒ 大概率只需重下模型（「卸载后重装」的常态）
    return {"code": code, "venv": venv, "deps": venv, "model": model,
            "full": not (code and venv)}


def can_import_torch(py_exe, cwd=None) -> bool:
    """venv 里 `import torch` 能不能过（真起子进程；约 2~6 s，**只在下载线程里调**）。"""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run([str(py_exe), "-c", "import torch,sys;print(torch.__version__)"],
                           capture_output=True, text=True, timeout=180, creationflags=flags,
                           cwd=str(cwd) if cwd else None,
                           env=os.environ.copy())
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 下载核心

def _request(url, offset=0):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    if offset:
        req.add_header("Range", "bytes=%d-" % offset)
    return urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)


def download_file(url, dest, expected_bytes=0, on_bytes=None, should_cancel=None,
                  tries=DOWNLOAD_TRIES) -> bool:
    """把 `url` 下到 `dest`，支持**按文件断点续传**。

    - 目标已存在且大小吻合 ⇒ 直接返回 True（`on_bytes` 会补报它的字节数，让总进度不倒退）；
    - 否则先写 `<dest>.part`，带 `Range` 续传；**大小吻合才 `os.replace`** 成正式名；
    - 服务器忽略 `Range`（回 200 而不是 206）⇒ 从头写，不叠加；
    - `on_bytes(delta)` 报的是**本次新读到的字节**，累计口径由调用方维护；
    - 取消 / 失败都**保留 `.part`**（下次接着走，不白下）。

    ★断网、超时、404 都只是返回 False，**绝不抛**：调用方按「这一段落失败」处理。
    """
    dest = Path(dest)
    if size_matches(dest, expected_bytes):
        if on_bytes:
            on_bytes(file_size(dest))
        return True
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    part = Path(str(dest) + PART_SUFFIX)

    for attempt in range(max(1, tries)):
        if should_cancel and should_cancel():
            return False
        offset = resume_offset(dest)
        try:
            with _request(url, offset) as r:
                status = getattr(r, "status", 200)
                if offset and status != 206:   # 服务器不认 Range ⇒ 从头来
                    offset = 0
                mode = "ab" if offset else "wb"
                with open(part, mode) as f:
                    while True:
                        if should_cancel and should_cancel():
                            return False
                        chunk = r.read(CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)
                        if on_bytes:
                            on_bytes(len(chunk))
            if expected_bytes and file_size(part) != expected_bytes:
                # 大小不对（多半是断了）⇒ 丢掉重来；还有机会就再试一次
                if attempt + 1 < max(1, tries):
                    _unlink(part)
                    continue
                return False
            os.replace(str(part), str(dest))
            return True
        except Exception:  # noqa: BLE001  （URLError / TimeoutError / OSError …）
            if attempt + 1 >= max(1, tries):
                return False
            time.sleep(1.0 + attempt)
    return False


def _unlink(path):
    try:
        os.remove(str(path))
    except OSError:
        pass


# ---------------------------------------------------------------- 子进程

def _popen(cmd, cwd=None):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [str(c) for c in cmd], cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=flags,
        # ★必须从 os.environ 起手复制：缺 TEMP / SYSTEMROOT 会让子进程的 tempfile 退到当前目录
        env=os.environ.copy(),
    )


def run_stream(cmd, cwd=None, on_line=None, should_cancel=None) -> int:
    """跑一个子进程并把输出**逐行**喂给 `on_line`；被取消返回 **-1**。"""
    try:
        proc = _popen(cmd, cwd)
    except Exception:  # noqa: BLE001
        return -2
    try:
        for line in proc.stdout:
            if should_cancel and should_cancel():
                _kill(proc)
                return -1
            if on_line:
                on_line(line.rstrip())
        try:
            proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            _kill(proc)
            return -3
    finally:
        try:
            proc.stdout.close()
        except Exception:  # noqa: BLE001
            pass
    return proc.returncode


def _kill(proc):
    try:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 解压

def unzip_strip_top(zip_path, dest, on_progress=None, should_cancel=None) -> bool:
    """解压 GitHub 源码 zip，**剥掉顶层目录**（zip 里是 `<repo>-<commit>/…`）。"""
    dest = Path(dest)
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if n and not n.startswith("__MACOSX/")]
            top = ""
            if names:
                head = names[0].split("/")[0]
                if head and all(n.startswith(head + "/") or n == head for n in names):
                    top = head + "/"
            total = max(1, len(names))
            for i, n in enumerate(names):
                if should_cancel and should_cancel():
                    return False
                rel = n[len(top):] if top and n.startswith(top) else n
                if not rel:
                    continue
                target = dest / rel
                if n.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(n) as src, open(target, "wb") as f:
                        shutil.copyfileobj(src, f, 1024 * 256)
                if on_progress and i % 50 == 0:
                    on_progress((i + 1) / total)
        if on_progress:
            on_progress(1.0)
        return True
    except Exception:  # noqa: BLE001
        return False


def untar_gz(tar_path, dest, on_progress=None, should_cancel=None) -> bool:
    """解压 `.tar.gz` 到 `dest`，**带头路径穿越防护**（成员路径必须落在 dest 内）。"""
    dest = Path(dest)
    base = dest.resolve()
    try:
        with tarfile.open(tar_path, "r:gz") as t:
            members = t.getmembers()
            total = max(1, len(members))
            for i, m in enumerate(members):
                if should_cancel and should_cancel():
                    return False
                target = (dest / m.name).resolve()
                if not str(target).startswith(str(base)):
                    continue                      # 穿越 ⇒ 跳过（不报错，也不写出去）
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif m.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = t.extractfile(m)
                    if src is None:
                        continue
                    with src, open(target, "wb") as f:
                        shutil.copyfileobj(src, f, 1024 * 256)
                if on_progress and i % 50 == 0:
                    on_progress((i + 1) / total)
        if on_progress:
            on_progress(1.0)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 安装记录

def write_marker(root, info) -> bool:
    """写一份给人看的安装记录（**不参与**任何判据 —— 用户手删目录时它可能还在）。"""
    try:
        p = Path(root) / MARKER_NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {"installed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "commit": CODE_COMMIT}
        data.update({k: v for k, v in (info or {}).items() if isinstance(v, (str, int, bool))})
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 任务（跑在后台线程里）

class _Job:
    """一次下载任务。所有可变状态都在 `_st` 里，读写都过 `_lock`。

    `snapshot()` 返回**只含 str / int / bool** 的扁平 dict —— 界面直接拿去用，
    不需要（也不许）把 Qt 对象塞进来。
    """

    def __init__(self, cfg, root):
        self.cfg = cfg
        self.root = Path(root)
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._skipped = []          # 跳过的段（「只下模型」这条近路）
        self._st = {
            "running": True, "done": False, "error": "", "cancelled": False,
            "phase": PHASE_CODE, "percent": 0, "message": STAGE_LABELS[PHASE_CODE],
        }

    # ---- 状态 ----

    def _set(self, **kw):
        with self._lock:
            self._st.update(kw)

    def _stage(self, sid, frac=0.0, message=None):
        self._set(phase=sid, percent=overall_percent(sid, frac),
                  message=message or STAGE_LABELS.get(sid, ""))

    def snapshot(self) -> dict:
        with self._lock:
            d = dict(self._st)
        d["skipped"] = ",".join(self._skipped)
        d["root"] = str(self.root)
        return d

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._st["running"])

    def cancel(self):
        self._cancel.set()

    def _cancelled(self) -> bool:
        return self._cancel.is_set()

    # ---- 六段 ----

    def run(self):
        try:
            layers = probe_layers(self.root)
            if layers["venv"] and not can_import_torch(venv_python(self.root), self.root):
                layers["deps"] = False        # venv 在但依赖不全 ⇒ 还得装
            if layers["code"] and layers["deps"]:
                # ★「卸载后重装」的近路：前四段全跳，只下模型
                self._skipped = [PHASE_CODE, PHASE_UNPACK, PHASE_DEPS, PHASE_ASSETS]
            if not self._do_code(layers):
                return
            if not self._do_unpack(layers):
                return
            if not self._do_deps(layers):
                return
            if not self._do_assets(layers):
                return
            if not self._do_model():
                return
            if not self._do_verify():
                return
            self._set(running=False, done=True, cancelled=False, error="",
                      phase=PHASE_DONE, percent=100, message=STAGE_LABELS[PHASE_DONE])
        except Exception as e:  # noqa: BLE001 —— 任何意外都要落成「失败」，不能让线程静默死
            self._finish_error("下载出错：%s" % e)

    def _finish_error(self, msg):
        self._set(running=False, error=str(msg), message=str(msg))

    def _finish_cancel(self):
        self._set(running=False, cancelled=True, error="", message="已取消下载")

    def _skip(self, sid) -> bool:
        """该段是否已跳过（近路上层都齐了）。"""
        return sid in self._skipped

    # ① 代码体
    def _do_code(self, layers) -> bool:
        if self._skip(PHASE_CODE) or layers["code"]:
            return True
        self._stage(PHASE_CODE, 0.0)
        dest = self.root / "_code.zip"
        got = [0]

        def on_bytes(delta):
            got[0] += delta
            # 代码包不给总长（流式）⇒ 段内用「已下 MB」推一条**有上限的**渐近进度：
            # 按 15 MB 估到 0.9，剩下 0.1 留给「下完但还没解压」那一瞬。
            frac = min(0.9, got[0] / float(CODE_EST_BYTES) * 0.9)
            # ★把**已下多少 MB** 显出来：这一段要下 ~7 分钟（codeload 只有 33 KB/s），
            #   而代码包只占总进度 3% ⇒ 只给百分比的话整段都停在 0%，看着像卡死。
            self._stage(PHASE_CODE, frac,
                        "正在下载程序主体（已下 %.1f MB）" % (got[0] / 1024.0 / 1024.0))

        ok = download_file(CODE_ZIP_URL, dest, CODE_ZIP_BYTES, on_bytes, self._cancelled)
        if self._cancelled():
            self._finish_cancel()
            return False
        if not ok or not dest.is_file():
            self._finish_error("程序主体下载失败（%s）。可稍后重试 —— 已下好的部分会保留。" % GITHUB_REPO)
            return False
        return True

    # ② 解压 + venv
    def _do_unpack(self, layers) -> bool:
        if self._skip(PHASE_UNPACK) or layers["code"]:
            return True
        self._stage(PHASE_UNPACK, 0.0)
        zip_path = self.root / "_code.zip"
        if zip_path.is_file():
            ok = unzip_strip_top(zip_path, self.root,
                                 on_progress=lambda f: self._stage(PHASE_UNPACK, f * 0.7),
                                 should_cancel=self._cancelled)
            if not ok:
                self._finish_error("解压失败：下载到的压缩包可能不完整，请重试。")
                return False
            _unlink(zip_path)
        else:
            self._finish_error("找不到刚下载的程序主体压缩包。")
            return False
        if self._cancelled():
            self._finish_cancel()
            return False

        # 建 venv
        self._stage(PHASE_UNPACK, 0.75, "正在创建运行环境")
        py, ver = find_system_python()
        if not py:
            self._finish_error("没找到可用的 Python（需要 3.9~3.12）来创建运行环境。")
            return False
        vd = self.root / ".venv"
        if not venv_python(self.root).is_file():
            rc = run_stream([py, "-m", "venv", str(vd)], cwd=self.root,
                            on_line=lambda s: self._set(message="正在创建运行环境（Python %s）" % ver),
                            should_cancel=self._cancelled)
            if rc == -1:
                self._finish_cancel()
                return False
            if rc != 0 or not venv_python(self.root).is_file():
                self._finish_error("创建运行环境失败（Python %s）。" % ver)
                return False
        self._stage(PHASE_UNPACK, 1.0)
        return True

    # ③ pip 依赖
    def _do_deps(self, layers) -> bool:
        if self._skip(PHASE_DEPS) or layers["deps"]:
            return True
        self._stage(PHASE_DEPS, 0.0)
        py = venv_python(self.root)
        if not py.is_file():
            self._finish_error("运行环境不存在，无法安装依赖。")
            return False
        collected = [0]

        def on_line(line):
            s = line.strip()
            if s.startswith("Collecting "):
                collected[0] += 1
                frac = min(0.95, collected[0] / float(DEPS_EXPECTED_PACKAGES))
                self._stage(PHASE_DEPS, frac,
                            "%s（已装 %d 个包）" % (STAGE_LABELS[PHASE_DEPS], collected[0]))
            elif "Installing collected packages" in s or "Building wheel" in s:
                self._set(message="正在安装依赖…")

        def _alt_index(cmd):
            """把主索引换成备用索引；本来就都是备用的则返回 None（别死循环）。"""
            m = {PIP_INDEX: PIP_INDEX_BACKUP, TORCH_INDEX: TORCH_INDEX_BACKUP}
            out = [m.get(c, c) for c in cmd]
            return out if out != cmd else None

        steps = [
            [py, "-m", "pip", "install", "--upgrade", "pip", "-i", PIP_INDEX],
            [py, "-m", "pip", "install", *TORCH_SPEC, "--index-url", TORCH_INDEX],
            [py, "-m", "pip", "install", "-r", self.root / REQUIREMENTS_FILE, "-i", PIP_INDEX],
        ]
        for cmd in steps:
            rc = run_stream(cmd, cwd=self.root, on_line=on_line, should_cancel=self._cancelled)
            if rc == -1:
                self._finish_cancel()
                return False
            if rc != 0:
                alt = _alt_index(cmd)      # 主索引挂了 ⇒ 换备用索引再试一次
                if alt is not None:
                    self._set(message="主源不可用，正在换备用源重试…")
                    rc = run_stream(alt, cwd=self.root, on_line=on_line,
                                    should_cancel=self._cancelled)
                    if rc == -1:
                        self._finish_cancel()
                        return False
                if rc != 0:
                    self._finish_error("安装依赖失败（pip 返回 %s）—— 多半是网络问题，重试即可接着走。" % rc)
                    return False
        self._stage(PHASE_DEPS, 1.0)
        return True

    # ④ 日语词典
    def _do_assets(self, layers) -> bool:
        if self._skip(PHASE_ASSETS):
            return True
        pkg = _pyopenjtalk_dir(self.root / ".venv")
        if pkg is not None and (pkg / OPEN_JTALK_DIR_NAME).is_dir():
            return True                                  # 已经有了
        self._stage(PHASE_ASSETS, 0.0)
        if pkg is None:
            self._finish_error("找不到 pyopenjtalk 包目录，无法放置日语词典。")
            return False
        tgz = self.root / "_open_jtalk.tar.gz"
        got = [0]

        def on_bytes(delta):
            got[0] += delta
            self._stage(PHASE_ASSETS, min(1.0, got[0] / float(OPEN_JTALK_BYTES or 1)))

        ok = download_file(OPEN_JTALK_URL, tgz, OPEN_JTALK_BYTES, on_bytes, self._cancelled)
        if self._cancelled():
            self._finish_cancel()
            return False
        if not ok:
            ok = download_file(OPEN_JTALK_URL_BACKUP, tgz, OPEN_JTALK_BYTES,
                               on_bytes, self._cancelled)
        if not ok:
            self._finish_error("日语词典下载失败（不定日语的发音词典，语音就出不来）。")
            return False
        self._set(message="正在解压日语词典…")
        if not untar_gz(tgz, pkg, should_cancel=self._cancelled):
            self._finish_error("日语词典解压失败。")
            return False
        _unlink(tgz)
        self._stage(PHASE_ASSETS, 1.0)
        return True

    # ⑤ 模型
    def _do_model(self) -> bool:
        md = self.root / voice_model.MODEL_SUBDIR
        targets = model_targets()
        total = sum(t["bytes"] for t in targets) or 1
        # 已完成的先算进去（续传 / 重下都要对）
        done = [sum(t["bytes"] for t in targets if size_matches(md / t["rel"], t["bytes"]))]
        self._stage(PHASE_MODEL, done[0] / float(total))

        for i, t in enumerate(targets):
            if self._cancelled():
                self._finish_cancel()
                return False
            name = t["rel"].split("/")[-1]
            label = "%s（%d/%d）" % (STAGE_LABELS[PHASE_MODEL], i + 1, len(targets))

            def on_bytes(delta, _d=done):
                _d[0] += delta
                self._stage(PHASE_MODEL, min(1.0, _d[0] / float(total)),
                            "%s：%s" % (label, name))

            self._set(message="%s：%s" % (label, name))
            if not download_file(t["url"], md / t["rel"], t["bytes"], on_bytes, self._cancelled):
                if self._cancelled():
                    self._finish_cancel()
                    return False
                self._finish_error("下载模型文件失败：%s。重试会从已下好的部分接着走。" % name)
                return False
        self._stage(PHASE_MODEL, 1.0)
        return True

    # ⑥ 校验
    def _do_verify(self) -> bool:
        self._stage(PHASE_VERIFY, 0.0, "正在校验模型完整性")
        if not voice_model.is_model_dir_ok(self.root / voice_model.MODEL_SUBDIR):
            self._finish_error("校验没通过：模型文件不完整，请重试（会自动续传）。")
            return False
        self._stage(PHASE_VERIFY, 0.5, "正在检查运行环境")
        py = venv_python(self.root)
        if not py.is_file() or not can_import_torch(py, self.root):
            self._finish_error("校验没通过：运行环境里装不上 torch，语音服务起不来。")
            return False
        if (self.root / "api.py").is_file():
            pass
        else:
            self._finish_error("校验没通过：程序主体不完整。")
            return False
        write_marker(self.root, {"skipped": ",".join(self._skipped)})
        self._stage(PHASE_VERIFY, 1.0, "校验通过")
        return True


def _pyopenjtalk_dir(venv_dir):
    """venv 里 `pyopenjtalk` 的包目录（词典要解压到它下面）；找不到返回 None。"""
    sp = Path(venv_dir) / "Lib" / "site-packages" / "pyopenjtalk"
    return sp if sp.is_dir() else None


# ---------------------------------------------------------------- 模块级入口（界面只碰这几个）

_JOB = {"job": None, "lock": threading.Lock()}


def _idle_snapshot():
    return {"running": False, "done": False, "error": "", "cancelled": False,
            "phase": PHASE_IDLE, "percent": 0, "message": "", "skipped": "", "root": ""}


def start(cfg, root=None, free_gb=None) -> tuple:
    """启动下载。返回 `(ok, 提示语)` —— 不 ok 的原因（磁盘不够 / 已经在跑）直接拿去显示。

    ★目标目录默认取 `voice_model.install_root(cfg)`（**安装根 = 唯一真值**）：
      用户显式指定的 → 本机已有安装（项目内 → `D:\\GPT-SoVITS`）→ 全新装到项目内。
      **不再用 `default_install_dir()`** —— 那条不含历史路径，会出现「`D:\\GPT-SoVITS`
      明明能用、点下载却在项目内又造一套」。
    ★磁盘预检**在这里同步做**（只看 stat，毫秒级）：要全跑按 `REQUIRED_FREE_GB`（6 GB）算，
    「只下模型」那条近路只按 2 GB 算 —— 否则明明只需 1.15 GB 也会被 6 GB 门槛拦住。
    """
    target = Path(root) if root else voice_model.install_root(cfg)
    with _JOB["lock"]:
        cur = _JOB["job"]
        if cur is not None and cur.is_running():
            return False, "已经在下载了。"
    layers = probe_layers(target)
    need = voice_model.REQUIRED_FREE_GB if layers["full"] else 2.0
    free = voice_model.disk_free_gb(target) if free_gb is None else float(free_gb)
    if free < 0:
        # ★取不到剩余空间时**按「不够」处理**：宁可拦住，也不要把 3.6 GB 写进一个容量未知的盘
        return False, "读不到「%s」所在磁盘的剩余空间，为安全起见先不下载。" % target
    if free < need:
        return False, ("磁盘空间不足：%s 所在盘还剩 %.1f GB，这次需要约 %.1f GB。"
                       % (target, free, need))
    job = _Job(cfg, target)
    with _JOB["lock"]:
        _JOB["job"] = job
    threading.Thread(target=job.run, daemon=True, name="voice-download").start()
    return True, "开始下载。"


def snapshot() -> dict:
    """当前进度快照（**只含 str / int / bool**）。没有任务时返回 idle 快照。"""
    with _JOB["lock"]:
        job = _JOB["job"]
    return job.snapshot() if job is not None else _idle_snapshot()


def is_running() -> bool:
    return bool(snapshot()["running"])


def cancel():
    """请求取消。**已下好的文件保留**，下次点「下载」接着走。"""
    with _JOB["lock"]:
        job = _JOB["job"]
    if job is not None:
        job.cancel()


def reset():
    """丢掉当前任务对象（**测试用**：让下一次 `start()` 能重新开始）。"""
    with _JOB["lock"]:
        _JOB["job"] = None


def progress_text(snap=None) -> str:
    """下载行的状态文字：`下载中　42%`（**全角空格**，与「未下载 / 已下载」的节奏一致）。"""
    s = snapshot() if snap is None else snap
    if s.get("done"):
        return "已下载"
    if s.get("running"):
        return "下载中　%d%%" % int(s.get("percent") or 0)
    return "未下载"
