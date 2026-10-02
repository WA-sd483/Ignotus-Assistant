"""P2 体验四件套的**共用诊断内核**：首次引导 / 启动提示区 / 一键自检 / 检查更新。

★★为什么是**一个**模块、而不是三处各判一遍
------------------------------------------------
    这几处界面对「现在到底能不能用」必须给出**同一份**结论。各写各的 if，
    迟早漂移成「一键自检说没问题、启动提示区却说没配 API Key」——本项目吃过这个亏
    （同一量两处各写一份 ⇒ 静默漂移，见 docs/02 §24 的 `SWITCHABLE_ROLES`）。
    所以判据**全部收在这里**，几段 UI 只负责**呈现**。

★纯度：本模块不 import Qt、不读磁盘、不联网。
    唯一碰 I/O 的是 `collect_facts()`（给生产环境的薄封装，且整体被 try/except 包住），
    它自己什么都不判 —— 只是把「模型装没装」这类**外部事实**取回来交给纯判据。
    ⇒ 全部判据都能离线断言（`tests/smoke_health.py`），不用起 QApplication。
"""
from collections import namedtuple

from .config import get_current_api, has_any_api

# 一个检查项。`level` 只有三档，刻意**不用 bool**：
#   ok   —— 通过（绿）
#   warn —— 能用但有个「你可能是故意的」的状态（黄，例如静音模式开着）
#   fail —— 这条功能现在是坏的（红）
Check = namedtuple("Check", "key title level detail fix")

# 启动提示区里的一行（2026-10-02 改口径）。
#   key      —— "whitelist"（白名单，常显、手动关）/ "voice"（语音，5s 后自动消失）
#   text     —— 要给用户看的那一句话
#   level    —— 决定圆点与文字的颜色（三档同上）
#   auto_ms  —— 多少毫秒后**自动**消失；`0` = 不自动消失，只能手动点 ✕
Notice = namedtuple("Notice", "key text level auto_ms")

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_FAIL = "fail"

# 「去设置」的落点 —— 用**字符串**而不是右栏页索引：
# 页索引（`MainWindow.PAGE_*`）是 gui.py 的内部约定，诊断内核不该依赖它。
# 由 MainWindow 把这三个字符串翻译成自己的页索引。
PAGE_API = "api"
PAGE_GENERAL = "general"
PAGE_PERMISSIONS = "permissions"

# 语音那条提示的存活时间（用户口径：右侧 5s 倒计时 + ✕，倒计时完或点了 ✕ 就消失）。
NOTICE_VOICE_MS = 5000


# ---------------------------------------------------------------- 取值的唯一入口
def allowed_dirs(cfg) -> list:
    """权限白名单里的「可操作目录」（★默认是空的，这是设计不是 bug）。"""
    perms = cfg.get("permissions")
    if not isinstance(perms, dict):
        return []
    raw = perms.get("allowed_dirs")
    if not isinstance(raw, list):
        return []
    return [str(d).strip() for d in raw if str(d).strip()]


def mute_on(cfg) -> bool:
    """静音模式是否开着（AI 只输出中文、不合成语音）。"""
    general = cfg.get("general")
    if not isinstance(general, dict):
        return False
    return bool(general.get("mute_mode", False))


# ---------------------------------------------------------------- 单项判据
def check_api(cfg) -> Check:
    """API 配置：**最致命的一条** —— 没有它她根本不会回复。"""
    cur = get_current_api(cfg)
    if cur is None or not str(cur.get("api_key") or "").strip():
        return Check(
            "api", "API 配置", LEVEL_FAIL,
            "还没有可用的 API Key —— 她说不出话，也不会回复。",
            "点下面「去设置」，在「管理 API」里填入 API Key（默认 DeepSeek 端点）。",
        )
    return Check("api", "API 配置", LEVEL_OK,
                 "正在使用「%s / %s」。" % (cur.get("name"), cur.get("model")), "")


def check_whitelist(cfg) -> Check:
    """权限白名单：空 ⇒ 「打开文件 / 查看目录」一律被拒（docs/02 §8.9）。"""
    dirs = allowed_dirs(cfg)
    if not dirs:
        return Check(
            "whitelist", "权限白名单", LEVEL_FAIL,
            "可操作目录是空的 —— 「打开文件 / 查看目录」会一律被拒绝。",
            "点下面「去设置」，在「权限管理 → 可操作目录」里添加一个目录。",
        )
    return Check("whitelist", "权限白名单", LEVEL_OK, "已允许 %d 个目录。" % len(dirs), "")


def check_mute(cfg) -> Check:
    """静音模式。★它**不是错误** —— 是用户自己拨的开关，所以永远不判 fail。"""
    if mute_on(cfg):
        return Check("mute", "静音模式", LEVEL_WARN,
                     "已开启：回复只显示中文，不出声。", "")
    return Check("mute", "静音模式", LEVEL_OK, "已关闭：回复会念出来。", "")


def check_tts(cfg, tts_installed) -> Check:
    """语音合成（音色克隆模型 / GPT-SoVITS）。

    `tts_installed` 三态：`True` / `False` / `None`（还不知道，正在探测）。
    ★静音模式开着时，没有模型**不算失败** —— 那正是「没有模型 ⇒ 锁死静音」这条
      设计的预期结果（docs/01 F7）。判 fail 会让自检对着一台按设计工作的机器报红。
    """
    if tts_installed is None:
        return Check("tts", "语音合成", LEVEL_WARN, "正在检查音色克隆模型…", "")
    if tts_installed:
        return Check("tts", "语音合成", LEVEL_OK, "音色克隆模型已就位，可以出声。", "")
    if mute_on(cfg):
        return Check("tts", "语音合成", LEVEL_WARN,
                     "没找到音色克隆模型 —— 但当前是静音模式，不出声符合预期。", "")
    return Check(
        "tts", "语音合成", LEVEL_FAIL,
        "没找到音色克隆模型 —— 她只会显示文字，不会出声。",
        "「设置 → 通用设置 → 语音模型」点「下载」，或在「安装位置」里指定已有的 GPT-SoVITS 目录。",
    )


def check_asr(asr_ok) -> Check:
    """语音识别（麦克风）。`asr_ok` 三态：`True` / `False` / `None`（后台线程还没结果）。"""
    if asr_ok is None:
        return Check("asr", "语音识别", LEVEL_WARN, "正在后台初始化…（喊不醒是正常的，稍等）", "")
    if asr_ok:
        return Check("asr", "语音识别", LEVEL_OK, "麦克风已就绪，可以喊唤醒词。", "")
    return Check(
        "asr", "语音识别", LEVEL_FAIL,
        "初始化失败 —— 喊唤醒词没有反应（打字聊天不受影响）。",
        "检查麦克风是否被别的程序占用；详细原因见日志 app.log。",
    )


def check_autostart(cfg) -> Check:
    """开机自启。**纯提示**：没开不是问题（很多人不想让它开机就跑）。"""
    general = cfg.get("general")
    on = bool(general.get("auto_start", False)) if isinstance(general, dict) else False
    if on:
        return Check("autostart", "开机自启", LEVEL_OK, "已开启。", "")
    return Check("autostart", "开机自启", LEVEL_WARN, "未开启（想开机就在，去通用设置里打开）。", "")


# ---------------------------------------------------------------- 聚合
def check_all(cfg, *, tts_installed=None, asr_ok=None) -> list:
    """一键自检的完整清单（顺序 = 界面上从上到下的顺序，**按「坏了最耽误事」排**）。"""
    return [
        check_api(cfg),
        check_asr(asr_ok),
        check_tts(cfg, tts_installed),
        check_mute(cfg),
        check_whitelist(cfg),
        check_autostart(cfg),
    ]


def summary(checks) -> tuple:
    """数一下 (通过, 提示, 失败) —— 给自检弹窗的标题行用。"""
    ok = sum(1 for c in checks if c.level == LEVEL_OK)
    warn = sum(1 for c in checks if c.level == LEVEL_WARN)
    fail = sum(1 for c in checks if c.level == LEVEL_FAIL)
    return ok, warn, fail


def guide_items(cfg, *, tts_installed=None) -> list:
    """首次使用引导的「要做的两件事」——★**复用上面的判据**，不另写一套。

    只取「用户必须自己动手」的两条（API Key / 白名单）：它们各自对应用户能做的
    一个具体动作，而且**不复用 `check_tts`** —— 下载 3.6 GB 的模型不该拦在引导里。
    """
    return [check_api(cfg), check_whitelist(cfg)]


def first_run_needed(cfg) -> bool:
    """本机**还没配过任何角色的任何 API** —— 「新用户」的判据（★与「初次启动」是两件事）。

    ★`config.json` 在不在才是「初次启动」（见 `config.is_first_launch`）；这里问的是
      「配过了没有」。老用户（`config.json` 早就在）也可能一次都没配过 API。
    ★白名单为空**不算**（默认就是空的，README 也写着），拿它当判据会天天把人当新人。
    """
    return not has_any_api(cfg)


# ---------------------------------------------------------------- 启动提示区（2026-10-02 改口径）
def whitelist_notice(cfg) -> Notice | None:
    """白名单为空时**每次启动都常显**的那一行；不空则 None（没什么好说的）。

    ★文案是**用户逐字给的**，别再"优化"它 —— 他说过要优化这类灰字时再动。
    ★它 `auto_ms=0`：不自动消失，只能手动点 ✕（用户口径）。
    """
    if allowed_dirs(cfg):
        return None
    return Notice(
        "whitelist",
        "可操作目录为空 —— 「打开文件 / 查看目录」指令会被拒绝。可在权限管理内添加",
        LEVEL_WARN,
        0,
    )


def voice_notice(cfg, tts_installed) -> Notice | None:
    """**只能在启动时说一次**的那一行「为什么她现在会不会出声」。

    三档（用户逐字给的文案，别再改）：
        · 没装模型                ⇒ 「当前未安装音色克隆模型，默认开启静音模式」
        · 有模型 + 静音开着        ⇒ 「当前为静音模式，无语音输出」
        · 有模型 + 静音关着        ⇒ 「静音模式已关闭，输出时间可能较慢」
    ★`tts_installed is None`（还没探到）⇒ **不出这一行**：宁可不说，也不能说假话。
    """
    if tts_installed is False:
        return Notice("voice", "当前未安装音色克隆模型，默认开启静音模式",
                      LEVEL_WARN, NOTICE_VOICE_MS)
    if tts_installed is not True:
        return None
    if mute_on(cfg):
        return Notice("voice", "当前为静音模式，无语音输出", LEVEL_WARN, NOTICE_VOICE_MS)
    return Notice("voice", "静音模式已关闭，输出时间可能较慢", LEVEL_OK, NOTICE_VOICE_MS)


def startup_notices(cfg, *, tts_installed=None) -> list:
    """启动时提示区要显示的全部行：**白名单那条在前、语音那条在其下**（用户口径）。

    顺序在这里定，界面只照单摆 —— 顺序若各写各的，两处迟早不一样。
    ★没配 API / 麦克风坏掉**都不在这里**：它们只走聊天区的灰字提示（用户 2026-10-02 口径）。
    """
    return [n for n in (whitelist_notice(cfg), voice_notice(cfg, tts_installed)) if n is not None]


# ---------------------------------------------------------------- 唯一碰 I/O 的地方
def collect_facts(cfg, asr_ok=None) -> dict:
    """生产环境用：把「外部事实」取回来交给纯判据。**这是本模块唯一做 I/O 的函数。**

    ★它自己**什么都不判**（不 ok/fail），只返回事实 ⇒ 判据仍全在纯函数里。
    ★模型探测走 `voice_model.is_installed`（会 stat 几百 MB 的目录树），所以外面
      套了 try/except：探测本身炸了应当算「不知道」（None），**不是**「没装」——
      把「探不出来」说成「你没下载」会让用户白下一遍 3.6 GB。
    """
    tts_installed = None
    try:
        from . import voice_model
        tts_installed = bool(voice_model.is_installed(cfg))
    except Exception:  # noqa: BLE001
        tts_installed = None
    return {"tts_installed": tts_installed, "asr_ok": asr_ok}
