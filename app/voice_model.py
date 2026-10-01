"""音色克隆模型（GPT-SoVITS 权重）的状态检测与卸载。

★**纯逻辑模块：不 import Qt** —— 便于离线断言（`tests/smoke_settings.py` 直接 import 本模块跑，
不需要起 QApplication）。界面（`app/gui.py::_SettingDownloadRow`）只负责显示，
**真实状态一律现算**（原因见 `docs/02` §22.1：设置面板 `refresh()` 会把行全部重建，状态存行里会丢）。

本期（2026-09-22）只做 **状态检测 + 卸载（送回收站）**。
真下载流水线（代码包 / venv / 依赖 / 模型，含进度百分比）是**第二期**，方案见 `docs/02` §22.6。
"""
import ctypes
import shutil
from ctypes import wintypes
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 项目内默认安装位置（可随项目整体搬移）
DEFAULT_DIR_NAME = "runtime/GPT-SoVITS"

# 历史路径。★这是**必需**的一条而不是兼容：本机这套完全能用的环境装在这里。
# 只认项目内那条的话，它会被判成「未下载」⇒ 静音锁死 ⇒ AI 明明能说话却一声不吭。
# （2026-09-22 用户拍板：「自动沿用已有安装」。）
LEGACY_DIRS = (r"D:\GPT-SoVITS",)

# 模型权重在安装目录内的相对位置
MODEL_SUBDIR = "GPT_SoVITS/pretrained_models"

# venv 解释器在安装根内的相对位置（下载 / 运行两边都用同一份，别各写一遍）
VENV_PY_REL = ".venv/Scripts/python.exe"

# ★「已下载」的判据 = 下面**两批文件全在**、且**字节数逐个相等**。
#   - 只核「存在」不够：下载中断留下的**半截文件也在**；
#   - 不取 md5：1 GB 级文件每轮算哈希代价太大，而这 5 个文件大小两两不同，半截必然不等。
#   字节数与真机实文件**逐一核对过**（不是从网页抄的），见 `docs/02` §22.2。
#
# 第一批 = 5 个大权重（体积估算、下载量都看它）
MODEL_FILES = {
    "chinese-hubert-base/pytorch_model.bin": 188811417,
    "chinese-roberta-wwm-ext-large/pytorch_model.bin": 651225145,
    "fast_langdetect/lid.176.bin": 131266198,
    "gsv-v2final-pretrained/s2G2333k.pth": 106035259,
    "gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt": 155315150,
}

# ★★第二批 = 4 个**配套小文件**（共约 271 KB）。2026-09-27 **实测踩过**：
#   只核第一批的 5 个大权重是不够的 —— 权重齐、配套缺，照样被判「已下载」，
#   而 `api.py` 启动时 `AutoTokenizer.from_pretrained(bert_path)` 会**当场崩**：
#     TypeError: expected str, bytes or os.PathLike object, not NoneType
#   （`chinese-roberta-wwm-ext-large` 里没有 `config.json` / `tokenizer.json`）
#   ⇒ 表象就是「下载显示完成、界面说已装好、她却一声不吭」——**静默失败，最难查**。
#   `chinese-hubert-base` 同理：只有 `pytorch_model.bin` 时 `cnhubert.get_model()` 也会缺 config。
#
# ★清单真值来源（别凭记忆加文件）：HF 仓库的文件树 API ——
#     https://hf-mirror.com/api/models/lj1995/GPT-SoVITS/tree/main/<目录>
#   实测该仓库把这几个目录**逐文件**暴露出来（所以能逐文件下，不必拉整个 pretrained_models.zip）。
#   ★`gsv-v2final-pretrained/` 里还有一个 `s2D2333k.pth`(判别器)，推理**用不到**，刻意不列。
MODEL_AUX_FILES = {
    "chinese-hubert-base/config.json": 1449,
    "chinese-hubert-base/preprocessor_config.json": 212,
    "chinese-roberta-wwm-ext-large/config.json": 963,
    "chinese-roberta-wwm-ext-large/tokenizer.json": 268962,
}


def required_model_files():
    """「能出声」所需的**全部**文件（权重 + 配套）：`{相对路径: 字节数}`。

    ★**每次现读模块级字典**（不预先合并成常量）：这样测试里换桩 `MODEL_FILES` /
      `MODEL_AUX_FILES` 依然生效，判据也**只有一份**。
    """
    return {**MODEL_FILES, **MODEL_AUX_FILES}


MODEL_TOTAL_BYTES = sum(required_model_files().values())

# 二期磁盘预检门槛（安装四层约需这么多剩余空间）
REQUIRED_FREE_GB = 6.0


# ---------------------------------------------------------------- 目录解析


def _general(cfg):
    if isinstance(cfg, dict) and isinstance(cfg.get("general"), dict):
        return cfg["general"]
    return {}


def candidate_dirs(cfg):
    """按**探测顺序**返回候选安装目录：自定义 → 项目内 → 历史路径。

    顺序即优先级（`docs/02` §22.3）；第一个「5 个文件齐且大小对」的胜出。
    """
    out = []
    custom = str(_general(cfg).get("model_dir") or "").strip()
    if custom:
        out.append(Path(custom))
    out.append(BASE_DIR / DEFAULT_DIR_NAME)
    out.extend(Path(d) for d in LEGACY_DIRS)
    return out


def is_model_dir_ok(model_dir) -> bool:
    """模型目录是否「完整」：所需文件（权重 + 配套）全在且大小逐个相等。

    ★判据读的是 `required_model_files()`（**权重 + 配套小文件**），不是只看那 5 个大权重 ——
      配套文件缺失时服务根本起不来，只核权重的判据会一路假绿（2026-09-27 实测，见上面的注释）。
    """
    md = Path(model_dir)
    for rel, size in required_model_files().items():
        try:
            if (md / rel).stat().st_size != size:
                return False
        except OSError:
            return False
    return True


def model_dir(cfg):
    """返回可用的**模型目录**（`<安装目录>/GPT_SoVITS/pretrained_models`）；找不到返回 None。"""
    for d in candidate_dirs(cfg):
        md = Path(d) / MODEL_SUBDIR
        if is_model_dir_ok(md):
            return md
    return None


def resolve_install_dir(cfg):
    """返回可用的**安装目录**（模型目录的上两级）；找不到返回 None。

    ★注意它和 `install_root()` 的差别：这里**要求模型完整**（`is_model_dir_ok`）。
    模型一卸载它就返回 `None` —— 所以**不能用它来回答「装到哪 / 删哪」**，那是 `install_root()`
    的活。两者分工见 `docs/02` §22.3.1。
    """
    md = model_dir(cfg)
    return md.parent.parent if md is not None else None


def venv_python(root):
    """安装根里的 venv 解释器路径。"""
    return Path(root) / VENV_PY_REL


# 嵌套装错的指纹：`<安装根>/GPT_SoVITS/GPT_SoVITS` 存在 ⇒ 说明曾经把「安装位置」指到了
# 仓库的**子目录**上，下载流水线往里解压出了第三层（2026-09-27 实际踩过，`docs/02` §22.10.2）。
# ★这条判据的价值：它让「装错的目录」**不再被当成安装根**，从而在界面上暴露出来；
#   不带这条的话，误装的目录因为同时有 `api.py` 和 `GPT_SoVITS/`，会一路假绿到底。
NESTED_MARK_REL = "GPT_SoVITS/GPT_SoVITS"


def looks_like_install_root(root) -> bool:
    """这个目录**像不像一个 GPT-SoVITS 安装根**（= 代码体 / 运行环境 / 模型所在的那一层）。

    ★**故意不看 `.git`、`ffmpeg.exe` 这些** —— 它们只是「用户还往这儿放过东西」的旁证，
    不是「这儿装过」的证据；看它们会把随便一个目录都判成安装根。

    三条正向证据**任一**成立即可：`api.py`（代码体）、`.venv/Scripts/python.exe`（运行环境）、
    或 `<root>/GPT_SoVITS/pretrained_models` 里 5 个文件齐且字节对（模型完整）。
    ★第三条不是多余的：模型装在这儿而代码体不在（或反过来）的**半拉子状态**在真机上出现过，
      「模型在哪」和「安装根在哪」必须指向同一处，否则卸载会删空气。
    """
    root = Path(root)
    if not root.is_dir():
        return False
    if (root / NESTED_MARK_REL).exists():
        return False                       # 嵌套装错的目录 ⇒ 不是合法安装根
    return ((root / "api.py").is_file()
            or venv_python(root).is_file()
            or is_model_dir_ok(root / MODEL_SUBDIR))


def install_root(cfg):
    """**安装根 = 唯一真值**：下载往哪儿装、卸载删哪儿、运行时从哪儿拉起服务，三方都用它。

    顺序（用户口径 2026-09-27：「没手动改过 + 本机已有可用安装 ⇒ 自动沿用那一份」）：

    1. `cfg.general.model_dir`（用户**显式**指定的，非空即用 —— 哪怕那儿还没装东西，
       因为那正是「我想装到这儿」的意思）；
    2. 项目内 `runtime/GPT-SoVITS`（若 `looks_like_install_root`）；
    3. `D:\\GPT-SoVITS`（历史路径；若 `looks_like_install_root`）；
    4. 都没有 ⇒ **回落项目内** `runtime/GPT-SoVITS`（= 全新安装的目标）。

    ★第 3 条**只认「像安装根」的**，不像 `candidate_dirs()` 那样无条件列出 —— 否则一台
    从没装过的机器会把「点下载」的目标莫名其妙指到 `D:\\GPT-SoVITS`（在那儿建一套出来）。
    """
    custom = str(_general(cfg).get("model_dir") or "").strip()
    if custom:
        return Path(custom)
    for d in (BASE_DIR / DEFAULT_DIR_NAME, *(Path(x) for x in LEGACY_DIRS)):
        if looks_like_install_root(d):
            return Path(d)
    return BASE_DIR / DEFAULT_DIR_NAME


def default_install_dir(cfg):
    """**全新安装**该装到哪：项目内 `runtime/GPT-SoVITS`（即 `install_root()` 的第 4 条）。

    ★保留它是为了语义清楚：「用户显式指定的目录 or 全新装的目标」。
      ★实际取「下载目标」请用 `install_root(cfg)` —— 它才会**沿用本机已有的那份安装**
      （`default_install_dir()` 不含历史路径，直接拿它当下载目标会导致
      「`D:\\GPT-SoVITS` 明明能用，点下载却又在项目内造一套」）。
    """
    custom = str(_general(cfg).get("model_dir") or "").strip()
    return Path(custom) if custom else (BASE_DIR / DEFAULT_DIR_NAME)


def is_installed(cfg) -> bool:
    """音色克隆模型是否已就位。界面那一行的状态完全由它决定。"""
    return model_dir(cfg) is not None


def state(cfg) -> str:
    """给界面用的状态串：`installed` / `missing`（二期再加 `downloading`）。"""
    return "installed" if is_installed(cfg) else "missing"


def disk_free_gb(path) -> float:
    """`path` 所在卷的剩余空间（GB）。路径还不存在时向上找最近的已存在祖先；失败返回 -1。"""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(str(p)).free / (1024 ** 3)
    except Exception:  # noqa: BLE001
        return -1.0


# ---------------------------------------------------------------- 卸载（送回收站）

FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040        # 进回收站（关键）
FOF_NOCONFIRMATION = 0x0010   # 不弹系统确认框（我们自己弹二次确认）
FOF_NOERRORUI = 0x0400        # 失败也不弹错误框 —— 失败就「文件还在」，绝不退化成静默永久删除
# ★刻意**不加** FOF_SILENT(0x0004)：有资料指出它与 FOF_ALLOWUNDO 同现会让文件**被永久删除**。
#   把「失败」的默认结果设计成「文件还在」才安全。

try:
    # ★必须是小写 `windll`：写成 `Windll` 会让这个开关**恒为 False**（真机也一样），
    #   整套逻辑一字节不跑，而且不报错 —— 离屏 / 真机互相掩护。测试里有 AST 断言钉住拼写。
    _HAS_WIN32 = hasattr(ctypes, "windll")
except Exception:  # noqa: BLE001
    _HAS_WIN32 = False


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),   # FILEOP_FLAGS 是 WORD，别写成 UINT
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def to_recycle_bin(paths) -> bool:
    """把一批文件 / 目录送进**回收站**（可还原，不永久删除）。

    ⚠️ 返回 `True` 只表示「调用已发出」，**不表示删成功**：`SHFileOperationW` 返回非 0
    ≠ 失败（实测遇到过 `rc = 2` 但文件确实躺在回收站里）⇒ **判据只看原路径还在不在**，
    见 `uninstall()`。可执行形态与核验方法见 `windows-safe-file-cleanup` skill。
    """
    if not _HAS_WIN32:
        return False
    items = [str(p) for p in paths if p]
    if not items:
        return False
    # pFrom 必须是「双 NUL 结尾」的多字符串
    buf = "\0".join(items) + "\0\0"
    op = _SHFILEOPSTRUCTW(None, FO_DELETE, buf, None,
                          FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI,
                          False, None, None)
    try:
        ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception:  # noqa: BLE001
        return False
    return True


# 「全部卸载」的删除面（**显式枚举要删的，而不是「除了白名单都删」**，理由见 `docs/02` §22.11）。
# 来源：`git ls-tree --name-only HEAD` @ `voice_download.CODE_COMMIT`（48b1a016）的真机输出 ——
#   ① 根那一段 = 仓库根的 tracked 顶层条目，去掉 `GPT_SoVITS`（下面单独展开，不能整删）；
#   ② `GPT_SoVITS/` 那段 = 该子目录的 tracked 顶层条目，去掉 `text` 与 `pretrained_models`
#      （`text/` 里躺着 `G2PWModel/` 607 MB 与 `ja_userdic/` 36.8 MB 两个**用户资产**，整目录跳过）；
#   ③ `.venv`（含 pip 依赖与日语词典）与 `pretrained_models`（模型）另外单列。
# ★commit 锁死 ⇒ 这份清单**不会漂移**；测试里钉住项数（52）与关键项。
# ★反向要记住：**没列进来的东西一律保留** —— `refs/`、`ffmpeg.exe`、`.git/`、`requirements_cpu.txt`、
#   `start_api.bat`、`recognize_ref.py`、`api_log.txt`、`_playtest.wav` 都在这一类里。
PURGE_TARGETS = (
    # ③ venv（依赖 + 日语词典都在它下面）与模型
    ".venv",
    "GPT_SoVITS/pretrained_models",
    # 流水线自己写的安装标记（不参与判据，但属于「装出来的东西」）
    ".ignotus_install.json",
    # ① 根：仓库根 tracked、且不是 GPT_SoVITS（24 项）
    ".dockerignore", ".github", ".gitignore", ".pre-commit-config.yaml",
    "Colab-Inference.ipynb", "Colab-WebUI.ipynb", "Docker", "Dockerfile",
    "LICENSE", "README.md", "api.py", "api_v2.py", "config.py",
    "docker-compose.yaml", "docker_build.sh", "docs", "extra-req.txt",
    "go-webui.bat", "go-webui.ps1", "install.ps1", "install.sh",
    "requirements.txt", "tools", "webui.py",
    # ② GPT_SoVITS/ 下：tracked、去掉 text 与 pretrained_models（25 项）
    "GPT_SoVITS/AR", "GPT_SoVITS/BigVGAN", "GPT_SoVITS/TTS_infer_pack",
    "GPT_SoVITS/configs", "GPT_SoVITS/download.py", "GPT_SoVITS/eres2net",
    "GPT_SoVITS/export_torch_script.py", "GPT_SoVITS/export_torch_script_v3v4.py",
    "GPT_SoVITS/f5_tts", "GPT_SoVITS/feature_extractor",
    "GPT_SoVITS/inference_cli.py", "GPT_SoVITS/inference_gui.py",
    "GPT_SoVITS/inference_webui.py", "GPT_SoVITS/inference_webui_fast.py",
    "GPT_SoVITS/module", "GPT_SoVITS/onnx_export.py", "GPT_SoVITS/prepare_datasets",
    "GPT_SoVITS/process_ckpt.py", "GPT_SoVITS/s1_train.py", "GPT_SoVITS/s2_train.py",
    "GPT_SoVITS/s2_train_v3.py", "GPT_SoVITS/s2_train_v3_lora.py",
    "GPT_SoVITS/stream_v2pro.py", "GPT_SoVITS/sv.py", "GPT_SoVITS/utils.py",
)

UNINSTALL_MODEL = "model"     # 只删模型权重（推荐档）
UNINSTALL_ALL = "all"         # 代码体 + venv + 模型

# 「整套安装」的体积估算（GB）：**全量下载会下多少 ≈ 全套卸载会删多少**（代码体 + venv + 依赖 + 模型）。
# 构成（逐段来自 `docs/02` §22.6.3 的表）：代码包 ≈0.015 + venv 本体 ≈0.03 +
#   依赖（torch 1.23 + `requirements_cpu` ≈1.2）≈2.4 + 日语词典 ≈0.024 + 模型 5 文件 ≈1.23
#   ⇒ 合计 ≈3.7 GB ⇒ 取「约 3.6」（与 `docs/01` F7 / `docs/02` §22.6.6-7 使用的数一致）。
# ★**唯一定义在这里**：`voice_download.FULL_DOWNLOAD_GB` 直接引用它。各写一份的后果是
#   改了一处、另一个弹窗里的数字静默漂移 ⇒ 两个弹窗对用户说两个数。测试里钉住两者相等。
FULL_INSTALL_GB = 3.6


def uninstall_message(cfg=None) -> str:
    """卸载弹窗的正文。**纯函数**（不弹窗、不删任何东西 ⇒ 离线可断言）。

    必须把**两档各删什么、各多大**写清楚：这两档的代价差 3 倍以上，
    而「全都删了」和「只删模型」在用户眼里都只是「卸载」两个字。

    ★2026-10-01 用户口径：「弹窗里文字过多」⇒ 压成「**一行一档 + 一行收尾**」，
      每档只在括号里点明删的是什么（原版是四句长句，还夹着安装位置与重装时长）。
    ★2026-10-01 二次（同一个「字太多」口径的续）：**「两档都会保留 refs…」那一整行也删掉**
      ⇒ 正文只剩「标题 + 一档一行 + 空行 + 一行收尾」。
      ★代价：弹窗里不再出现「送进回收站、可还原」这句兜底说明 —— 但**行为没变**
        （两档都走回收站，见 `purge_paths` / `docs/02` §22.4），只是不再写在弹窗里。
        ★**别再把它加回来**：用户两次都是嫌字多。
    ★**「安装位置：…」那一行已去掉**：按钮上方那行「安装位置」本来就写着同一个路径，
      弹窗里再贴一遍既重复又最占高度（长路径要换行）。
      ⇒ 本函数**不再需要 `cfg`**；形参保留只为不改调用方（`gui._uninstall_model` 与
        `tests/smoke_settings.py` 都按 `uninstall_message(cfg)` 调）。
    ★两档的体积数字**必须取自常量**（`MODEL_TOTAL_BYTES` / `FULL_INSTALL_GB`），
      不许写死 —— 常量改了文案不改，就是弹窗对用户说假话。
    """
    gb_model = MODEL_TOTAL_BYTES / 1024 ** 3
    return (
        "确定要卸载音色克隆模型吗？\n\n"
        "仅模型卸载：删除约 %.1f GB（模型权重）。\n"
        "全部卸载：删除约 %.1f GB（含程序本体与运行环境）。\n\n"
        "卸载后 AI 将没有任何语音输出（静音模式会锁死在开）。"
        % (gb_model, FULL_INSTALL_GB)
    )


def purge_paths(cfg) -> list:
    """「全部卸载」要删的**绝对路径**（已滤掉不存在的）。

    ★额外兜一条：若探测到的**模型目录不在安装根下**（半拉子的错位状态），也一并删 ——
    否则「全部卸载」名不副实，且那种错位状态正是这次要清掉的东西之一。
    """
    root = install_root(cfg)
    out = [root / rel for rel in PURGE_TARGETS]
    md = model_dir(cfg)
    if md is not None:
        low_root = str(root).lower()
        if not str(md).lower().startswith(low_root):
            out.append(md)
    return [p for p in out if p.exists()]


def uninstall(cfg, mode: str = UNINSTALL_MODEL) -> bool:
    """卸载（两档），一律**送回收站**、不永久删。

    - `mode="model"`（默认）：只删**探测到的模型目录**（`<安装根>/GPT_SoVITS/pretrained_models`）。
      与全删在「能不能说话」上完全等价（缺这 5 个文件 `api.py` 根本起不来），
      但重装只需重下 1.15 GB 而不是 15~40 分钟。★删的是 `model_dir()` 探测到的那一份，
      **不是**拿安装根去拼 —— 探测到哪儿删哪儿，最不容易误删。
    - `mode="all"`：按 `PURGE_TARGETS` 删「代码体 + venv + 依赖 + 模型」，
      **保留** `refs/`（角色参考音频）等用户资产（清单与理由见 `docs/02` §22.11）。

    返回「目标是否确实已不在」——**不看 `SHFileOperationW` 的返回值**（它不可信，见上）。
    """
    if mode == UNINSTALL_ALL:
        paths = purge_paths(cfg)
        if not paths:
            return True
        to_recycle_bin([str(p) for p in paths])
        return not any(p.exists() for p in paths)

    md = model_dir(cfg)
    if md is None:
        # 本来就没有 → 视为已达成「未下载」
        return True
    if not md.is_dir():
        return True
    to_recycle_bin([str(md)])
    return not md.exists()
