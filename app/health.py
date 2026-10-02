"""P2 体验三件套的**共用诊断内核**：首次使用引导 / 常显状态条 / 一键自检。

★★为什么是**一个**模块、而不是三处各判一遍
------------------------------------------------
    这三处界面对「现在到底能不能用」必须给出**同一份**结论。各写各的 if，
    迟早漂移成「一键自检说没问题、状态条却说没配 API Key」——本项目吃过这个亏
    （同一量两处各写一份 ⇒ 静默漂移，见 docs/02 §24 的 `SWITCHABLE_ROLES`）。
    所以判据**全部收在这里**，三段 UI 只负责**呈现**。

★纯度：本模块不 import Qt、不读磁盘、不联网。
    唯一碰 I/O 的是 `collect_facts()`（给生产环境的薄封装，且整体被 try/except 包住），
    它自己什么都不判 —— 只是把「模型装没装」这类**外部事实**取回来交给纯判据。
    ⇒ 全部判据都能离线断言（`tests/smoke_health.py`），不用起 QApplication。
"""
from collections import namedtuple

from .config import get_current_api

# 一个检查项。`level` 只有三档，刻意**不用 bool**：
#   ok   —— 通过（绿）
#   warn —— 能用但有个「你可能是故意的」的状态（黄，例如静音模式开着）
#   fail —— 这条功能现在是坏的（红）
Check = namedtuple("Check", "key title level detail fix")

# 常显状态条要显示的那一行。`page` 是「去设置」的落点（**字符串**，见下）。
Status = namedtuple("Status", "text level page")

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_FAIL = "fail"

# 「去设置」的落点 —— 用**字符串**而不是右栏页索引：
# 页索引（`MainWindow.PAGE_*`）是 gui.py 的内部约定，诊断内核不该依赖它。
# 由 MainWindow 把这三个字符串翻译成自己的页索引。
PAGE_API = "api"
PAGE_GENERAL = "general"
PAGE_PERMISSIONS = "permissions"


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
    """该不该弹「首次使用引导」：**还没配过任何 API** 就算首次。

    ★判据刻意只认「apis 为空」—— 白名单为空是**已知的设计**（README 也写着「默认是空的」），
      拿它当「首次」会把老用户一遍遍弹；而一个 API 都没有时，她是**彻底不工作**的。
    ★另一个入口是托盘菜单 / 设置页，用户随时可以重新打开引导（那时会显示各自的✓/✗）。
    """
    apis = cfg.get("apis")
    if not isinstance(apis, list):
        return True
    return not [a for a in apis if isinstance(a, dict) and str(a.get("name") or "").strip()]


def status_line(cfg, *, tts_installed=None, asr_ok=None) -> Status:
    """常显状态条要显示的那一行 —— **取「最耽误事」的那一条**。

    优先级（从上往下第一个不通过的胜出）：
        ① API 没配 —— 她根本不回复（最致命）
        ② 语音识别挂了 —— 喊不醒（说不了话；打字仍可）
        ③ 静音模式开着 —— 能用，但不出声
        ④ 语音合成没就绪 —— 能用，但不出声
        ⑤ 白名单为空 —— 对话没问题，但「打开文件」会被拒
        全部通过 ⇒ 绿色「一切就绪」。
    """
    # ① API
    c = check_api(cfg)
    if c.level == LEVEL_FAIL:
        return Status("还没配置 API Key —— 她收不到你的话，也不会回复。",
                      LEVEL_FAIL, PAGE_API)
    # ② ASR（只在**确定失败**时才顶上来；还在初始化就不吵用户）
    if asr_ok is False:
        return Status("语音识别未就绪 —— 喊唤醒词没反应（打字仍可聊天）。",
                      LEVEL_FAIL, PAGE_GENERAL)
    # ③ 静音模式（用户自己的选择，所以是 warn 不是 fail）
    if mute_on(cfg):
        return Status("静音模式已开启：回复只显示中文、不出声。",
                      LEVEL_WARN, PAGE_GENERAL)
    # ④ 语音合成
    if tts_installed is False:
        return Status("没找到音色克隆模型 —— 她只会显示文字，不会出声。",
                      LEVEL_FAIL, PAGE_GENERAL)
    # ⑤ 白名单
    if not allowed_dirs(cfg):
        return Status("可操作目录为空 —— 「打开文件 / 查看目录」会被拒绝。",
                      LEVEL_WARN, PAGE_PERMISSIONS)
    # ⑥ 还在初始化（清单还没跑完）：说得轻一点，别让人以为坏了
    if asr_ok is None or tts_installed is None:
        return Status("正在初始化（语音识别 / 语音合成）…", LEVEL_WARN, None)
    return Status("一切就绪：喊一声唤醒词就能聊。", LEVEL_OK, None)


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
