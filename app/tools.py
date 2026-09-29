"""工具：让角色能操作电脑（打开文件夹/文件/软件/网页、执行系统命令、查看目录）。

打开 XXX 的分层查找顺序（用户指定）：
1. 明确路径（如 D:\项目）
2. 本地搜索文件夹/文件（桌面/下载/文档等常见目录）
3. 浏览器书签查找（网址）
4. Bing 搜索兜底

仅提供安全/受控操作。安全边界为三级风险模型（详见 docs/01-需求规格说明书.md §5）：
1. 安全级：白名单内且非危险类型 → 直接执行；
2. 危险级：关机/重启/注销/锁屏等 → 延迟 danger_delay 秒执行，期间可语音说「取消」中止；
3. 禁止级：不在白名单、或命中禁止词 → 拒绝执行，由角色说明原因。
"""
import datetime
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

try:
    import winreg            # Windows 注册表（读「用户外壳文件夹」表，见 _resolve_user_dir）
except ImportError:          # 非 Windows：本模块整体是 Windows 专用，这里只是不让 import 就炸
    winreg = None

# 系统操作（关机/重启用延迟，可 shutdown /a 取消）
# 延迟由本模块的危险级队列统一负责（见 schedule_danger），系统层面不再叠加 /t 30
COMMAND_MAP = {
    "关机": ["shutdown", "/s", "/t", "0"],
    "重启": ["shutdown", "/r", "/t", "0"],
    "重新启动": ["shutdown", "/r", "/t", "0"],
    "注销": ["shutdown", "/l"],
    "锁屏": ["rundll32.exe", "user32.dll,LockWorkStation"],
}

# 常用软件名 → Windows 启动命令（系统程序，在 PATH 中可直接启动）
APP_MAP = {
    "记事本": "notepad",
    "记事板": "notepad",
    "计算器": "calc",
    "画图": "mspaint",
    "写字板": "write",
    "任务管理器": "taskmgr",
    "控制面板": "control",
    "文件资源管理器": "explorer",
    "资源管理器": "explorer",
    "命令提示符": "cmd",
    "cmd": "cmd",
    "powershell": "powershell",
    "画图工具": "mspaint",
}

# ★★2026-09-29：原来那行「写死开发机用户目录」的 `USER_DIR` 常量已删 —— 它不只是**隐私**问题，
#   本身就是**功能 bug**：别人机器上多半没有 D 盘 ⇒「打开桌面 / 下载」会指向一个不存在的目录
#   （开发机是「把桌面搬到 D 盘」的特殊机器，那个值正是它的实际位置）。
#   现在改成**问 Windows 自己**：注册表里那张「用户外壳文件夹」表就是资源管理器真正在用的那份，
#   桌面被重定向到 D 盘（开发机就是）或任何别的盘的机器都能答对。
#   ★为什么不用 `Path.home() / "Desktop"`：实测在「搬过家」的机器上，用户主目录下**仍会残留一个
#      同名的空壳 Desktop 目录** ⇒ 用 home 会静默打开那个空目录：能开、但内容是错的，比报错更难发现。
#      注册表那份才是「真的桌面在哪」。
_USER_SHELL_FOLDERS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"

# 六个常见用户目录：文件系统英文名 → 注册表里的**值名**（★值名的大小写与 GUID 都不能改）
_SHELL_FOLDER_VALUES = {
    "Desktop": "Desktop",
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",   # 「下载」只有 GUID，没有好记的名字
    "Documents": "Personal",
    "Pictures": "My Pictures",
    "Music": "My Music",
    "Videos": "My Video",
}


def _resolve_user_dir(folder_en: str) -> Path:
    """问 Windows：某个用户目录（传入文件系统英文名，如 `Desktop`）到底在哪。

    顺序：注册表（用户外壳文件夹表，支持重定向到别的盘）→ 用户主目录下的同名文件夹。
    ★注册表里存的是 `%USERPROFILE%\\Desktop` 这种**可展开**字符串 ⇒ 必须 `expandvars`，
      否则会拿到一个字面量路径（且 `Path` 会把它当成相对路径，静默失效）。
    """
    if winreg is None:                          # 非 Windows
        return Path.home() / folder_en
    value_name = _SHELL_FOLDER_VALUES.get(folder_en)
    if value_name:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _USER_SHELL_FOLDERS_KEY) as k:
                raw, _ = winreg.QueryValueEx(k, value_name)
            d = Path(os.path.expandvars(raw))
            if d.is_dir():
                return d
        except (OSError, ValueError):
            pass                                # 表里没有 / 取不到 / 值坏了 ⇒ 走下面那条回落
    return Path.home() / folder_en


# 常见目录名 → 路径（支持"打开桌面文件夹""打开此电脑"等常用称呼）
DIR_MAP = {
    "桌面": str(_resolve_user_dir("Desktop")),
    "下载": str(_resolve_user_dir("Downloads")),
    "文档": str(_resolve_user_dir("Documents")),
    "图片": str(_resolve_user_dir("Pictures")),
    "音乐": str(_resolve_user_dir("Music")),
    "视频": str(_resolve_user_dir("Videos")),
    "此电脑": "shell:MyComputerFolder",
    "我的电脑": "shell:MyComputerFolder",
    "回收站": "shell:RecycleBinFolder",
}

# 简称/别名 → 标准词（提升搜索和书签匹配准确度）
# 标准词需能匹配 Edge 收藏夹栏里书签的名称（子串匹配）
ALIAS_MAP = {
    # bilibili（哔哩哔哩/B站）
    "b站": "bilibili",
    "bilibili": "bilibili",
    "bilbili": "bilibili",
    "哔哩": "bilibili",
    "哔哩哔哩": "bilibili",
    # pixiv（P站）
    "p站": "pixiv",
    "pixiv": "pixiv",
    # 其他网站
    "leetcode": "力扣",
    "douyin": "抖音",
    "gugu": "咕咕番",
    "agedm": "age动漫",
    "mcmod": "mc百科",
    "deepseek": "deepseek",
    "taobao": "淘宝",
    "jd": "京东",
    "b度": "百度",
}

# ============ 安全边界：白名单 + 危险级延迟执行 ============

# 允许执行的操作类型（detect_action 产出的 type）
DEFAULT_ALLOWED_ACTIONS = (
    "query_info",   # 查时间 / 日期 / IP / 位置
    "list_dir",     # 查看目录内容（结果交给 AI 复述）
    "open_path",    # 打开文件或文件夹
    "open_url",     # 打开书签网址
    "open_app",     # 打开软件
    "search",       # 浏览器搜索兜底
    "run_command",  # 系统操作（关机/重启/注销/锁屏），同时属危险级
)

# 危险级操作类型：延迟执行 + 期间可语音取消
# run_command 覆盖关机/重启/注销/锁屏；file_* 为将来扩展预留，实现时自动继承本机制
DANGER_TYPES = ("run_command", "file_delete", "file_move", "file_overwrite")

# 默认不允许打开的软件（等价于任意命令入口，需在权限面板手动添加才放行）
DEFAULT_DENIED_APPS = ("cmd", "powershell", "命令提示符")

# 默认允许的目录范围：**空**（2026-09-28 用户拍板）。
# ★以前是「开发机用户目录 + 六个常见用户目录」，那会把**打包机自己的路径**带进成品：
#   别人装上后，「可操作目录/文件夹」里列的是开发机的目录 —— 既不可用，又暴露了用户名。
# ⇒ 现在**一律不预设**，由用户自己在 权限管理 →「可操作目录/文件夹」→「添加目录」里加。
# ★空列表的后果是**预期行为**（不是 bug）：`_path_allowed()` 对任何路径都返回 False ⇒
#   没添加之前「打开路径 / 查看目录」一律被拦（并如实回一句 [权限拦截] 交给角色复述）；
#   `shell:` 那几条固定快捷方式（此电脑 / 回收站）走的是 `DIR_MAP` 直通分支，不受影响。
# ★唯一真值就是这一行 —— `apply_permissions({})`（配置里留空 = 沿用内置默认）与权限面板
#   「恢复默认」都读它，**别在别处再写一份目录清单**。
DEFAULT_ALLOWED_DIRS = ()

# 默认允许的软件：APP_MAP 中排除默认禁止项（按名称与启动命令双重排除）
DEFAULT_ALLOWED_APPS = tuple(
    name for name, cmd in APP_MAP.items()
    if cmd.lower() not in DEFAULT_DENIED_APPS and name.lower() not in DEFAULT_DENIED_APPS
)

_perms = {
    "allowed_dirs": list(DEFAULT_ALLOWED_DIRS),
    "allowed_apps": list(DEFAULT_ALLOWED_APPS),
    "allowed_actions": list(DEFAULT_ALLOWED_ACTIONS),
    "blocked_keywords": [],
    "danger_delay": 30,
    # 用户从磁盘选进来的软件：软件名 → 可执行文件绝对路径（来自 config.permissions.custom_apps）。
    # 与 APP_MAP 的区别：APP_MAP 是「系统自带、在 PATH 里能直接起」的命令，
    # 这些只有绝对路径，启动时直接 Popen 那个路径。
    "custom_apps": {},
    # 开启了「免 UAC 启动」的软件名（来自 config.permissions.no_uac）。
    # 命中的软件改走计划任务启动（schtasks /run），不再弹 UAC —— 见 app/launch_task.py。
    "no_uac": [],
}

# 待执行的危险级操作（同一时间只保留一个，新的排程会顶掉旧的）
_danger = {"action": None, "label": "", "deadline": 0.0, "timer": None}


def _pick_list(raw, key, default):
    """配置项为空的列表表示「沿用内置默认」，非空则完全以配置为准。"""
    val = raw.get(key) if isinstance(raw, dict) else None
    if isinstance(val, list) and val:
        return [str(x) for x in val]
    return list(default)


def apply_permissions(raw) -> dict:
    """把 config 中的 permissions 段生效（启动时与权限面板保存后各调一次）。"""
    raw = raw if isinstance(raw, dict) else {}
    _perms["allowed_dirs"] = _pick_list(raw, "allowed_dirs", DEFAULT_ALLOWED_DIRS)
    _perms["allowed_apps"] = _pick_list(raw, "allowed_apps", DEFAULT_ALLOWED_APPS)
    _perms["allowed_actions"] = _pick_list(raw, "allowed_actions", DEFAULT_ALLOWED_ACTIONS)
    blocked = raw.get("blocked_keywords")
    _perms["blocked_keywords"] = (
        [str(x).strip() for x in blocked if str(x).strip()] if isinstance(blocked, list) else []
    )
    try:
        delay = int(raw.get("danger_delay", 30))
    except (TypeError, ValueError):
        delay = 30
    _perms["danger_delay"] = max(5, min(120, delay))
    # 自定义软件（从磁盘添加的 exe）：只收「非空字符串 → 非空字符串」
    custom = raw.get("custom_apps")
    apps = {}
    if isinstance(custom, dict):
        for k, v in custom.items():
            name, path = str(k).strip(), str(v).strip()
            if name and path:
                apps[name] = path
    _perms["custom_apps"] = apps
    # 开了「免 UAC」的软件名：只收真正非空的**字符串**（数字之类直接丢，
    # 反正 str() 出来的假名字永远匹配不上任何软件）。是否有 exe 由 app_exe_path 判定。
    no_uac = raw.get("no_uac")
    _perms["no_uac"] = (
        [x.strip() for x in no_uac if isinstance(x, str) and x.strip()]
        if isinstance(no_uac, list) else []
    )
    return _perms


def get_permissions() -> dict:
    """当前生效的权限（权限面板读取用）。"""
    return _perms


def default_permissions() -> dict:
    """内置默认权限（权限面板「恢复默认」用）。"""
    return {
        "allowed_dirs": list(DEFAULT_ALLOWED_DIRS),
        "allowed_apps": list(DEFAULT_ALLOWED_APPS),
        "allowed_actions": list(DEFAULT_ALLOWED_ACTIONS),
        "blocked_keywords": [],
        "danger_delay": 30,
        "custom_apps": {},
        "no_uac": [],
    }


def app_exe_path(name: str) -> str | None:
    """软件的 exe 绝对路径；拿不到就返回 None。

    只有「从磁盘添加的软件」（`custom_apps`）才有路径 —— 内置 `APP_MAP` 存的是
    PATH 命令（notepad / calc …），不能用于建计划任务，也就无法免 UAC。
    """
    return (_perms.get("custom_apps") or {}).get(str(name or "")) or None


def no_uac_apps() -> list:
    """当前开了「免 UAC 启动」的软件名（权限面板与启动分支共用）。"""
    return list(_perms.get("no_uac") or [])


def known_app_names() -> list:
    """所有已登记的软件名（内置 APP_MAP + 用户从磁盘添加的）。"""
    return sorted(set(APP_MAP) | set(_perms.get("custom_apps", {})))


def is_denied_app(name: str) -> bool:
    """是否是默认禁止的「任意命令入口」（cmd / powershell / 命令提示符）。

    权限面板「添加软件」现在是从磁盘选 exe，直接挑一个 `cmd.exe` 就等于绕过
    默认黑名单，所以添加前要用它拦一道（按文件名 basename 判断）。
    """
    return str(name or "").strip().lower() in DEFAULT_DENIED_APPS


def _path_allowed(target: str) -> bool:
    """目标路径是否落在允许目录内（含子目录）。shell: 固定快捷方式按预定义表放行。"""
    if not target:
        return False
    if target.startswith("shell:"):
        return target in DIR_MAP.values()
    try:
        p = Path(os.path.abspath(os.path.expanduser(target))).resolve()
    except (OSError, ValueError):
        return False
    for d in _perms["allowed_dirs"]:
        try:
            base = Path(os.path.abspath(os.path.expanduser(d))).resolve()
        except (OSError, ValueError):
            continue
        if p == base or base in p.parents:
            return True
    return False


def check_permission(action, text: str = "") -> tuple[bool, str]:
    """白名单校验。返回 (是否放行, 拒绝说明)。

    拒绝说明带 [权限拦截] 前缀，会作为 action_result 交给 AI，由角色用自己的语气
    告知老师「这个操作被安全设置挡住了」，而不是静默失败。
    """
    if not action:
        return True, ""
    haystack = f"{text} {action.get('label', '')}"
    for kw in _perms["blocked_keywords"]:
        if kw and kw in haystack:
            return False, f"[权限拦截] 禁止词「{kw}」命中了这条指令，已拒绝执行。"
    atype = action.get("type")
    if atype not in _perms["allowed_actions"]:
        return False, f"[权限拦截] 权限设置里没有开启「{atype}」这类操作，已拒绝执行。"
    if atype == "open_app":
        label = str(action.get("label", ""))
        target = str(action.get("target", "")).lower()
        if label not in _perms["allowed_apps"] or target in DEFAULT_DENIED_APPS:
            return False, (
                f"[权限拦截] 软件「{label}」不在允许打开的列表里"
                "（需要在权限管理中手动添加），已拒绝执行。"
            )
    if atype == "open_path" and not _path_allowed(str(action.get("target", ""))):
        return False, (
            f"[权限拦截] 路径「{action.get('target', '')}」不在允许操作的目录范围内，已拒绝执行。"
        )
    return True, ""


def is_danger(action) -> bool:
    """是否为危险级操作（需延迟执行 + 可语音取消）。"""
    return bool(action) and action.get("type") in DANGER_TYPES


def _abort_native_shutdown() -> None:
    """双保险：中止系统层面可能存在的等待中关机计划（无计划时仅静默失败）。"""
    try:
        subprocess.run(["shutdown", "/a"], capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def _clear_danger(abort_native: bool = False) -> str | None:
    """内部：清空待执行队列，返回被清掉的操作名（无则 None）。"""
    timer = _danger.get("timer")
    if timer is not None:
        try:
            timer.cancel()
        except Exception:  # noqa: BLE001
            pass
    label = _danger.get("label") or None
    _danger.update({"action": None, "label": "", "deadline": 0.0, "timer": None})
    if abort_native:
        _abort_native_shutdown()
    return label


def schedule_danger(action) -> str:
    """把危险级操作排入延迟队列，返回给 AI 复述的结果说明。"""
    delay = int(_perms["danger_delay"])
    _clear_danger(abort_native=True)  # 同一时间只保留一个待执行操作
    label = action.get("label") or action.get("type") or "操作"
    _danger["action"] = action
    _danger["label"] = label
    _danger["deadline"] = time.time() + delay
    timer = threading.Timer(delay, _run_pending_danger)
    timer.daemon = True
    _danger["timer"] = timer
    timer.start()
    return f"[已排程] 「{label}」将在 {delay} 秒后执行，期间说「取消」可以中止。"


def pending_danger():
    """返回待执行危险操作的 {label, remaining}；无则 None。"""
    if not _danger.get("action"):
        return None
    return {
        "label": _danger["label"],
        "remaining": max(0, int(round(_danger["deadline"] - time.time()))),
    }


def cancel_pending_danger() -> str | None:
    """语音撤销：中止已排程的危险操作，返回被取消的操作名（无则 None）。"""
    if not _danger.get("action"):
        return None
    return _clear_danger(abort_native=True)


def run_pending_danger_now() -> str | None:
    """「立刻关机」：**跳过剩余倒计时**，把排队中的危险操作当场执行；返回操作名（没排程则 None）。

    与语音「取消」是一对：取消是「不执行」，它是「不等了」。**只在确实有排程时才干活** ——
    调用方（`main.py`）负责守「没排程时语音说『立刻关机』只当作普通关机」这条线。
    """
    action = _danger.get("action")
    if not action:
        return None
    label = _clear_danger()          # 停掉定时器 + 清空队列（**不** abort_native：马上要自己执行）
    threading.Thread(target=_run_action_now, args=(action,), daemon=True).start()
    return label or action.get("label") or ""


def _run_pending_danger() -> None:
    """延迟结束：真正执行（在 Timer 线程中运行）。"""
    action = _danger.get("action")
    _danger.update({"action": None, "label": "", "deadline": 0.0, "timer": None})
    if action:
        try:
            _run_action_now(action)
        except Exception:  # noqa: BLE001
            pass


# 打开/启动类动词
_OPEN_VERBS = ("打开", "启动", "运行", "开一下", "帮我打开", "给我打开", "开个")
# 搜索/访问类动词
_SEARCH_VERBS = ("搜索", "搜一下", "查一下", "查询", "查查", "访问", "浏览", "上一下", "帮我查", "帮我搜", "搜搜", "搜", "查")
# 查看/列出类动词
_LIST_VERBS = ("看看", "查看", "列出", "有什么", "有哪些", "看下")

# 系统操作的否定词：说「别关机」「不要重启」时不能当成执行指令（否则会误触发关机）
_NEGATE_WORDS = ("别", "不要", "不用", "不允许", "不许", "不准", "禁止", "取消", "算了", "停止", "我不想")

# 查询类关键词：位置 / 日期 / 时间 / IP（位置需联网定位，其余本地查询）
# 「哪个城市 / 哪个省 / 什么地方」这类问法也要命中 —— 漏掉就会退回让模型自己猜，
# 猜出来的多半是它自己「家乡」（模型长期关联的那座城市），而不是设备所在地。
_LOCATION_WORDS = (
    "在哪", "位置", "定位", "地理位置", "我在哪",
    "哪个城市", "哪个省", "哪个地区", "哪个市", "什么地方", "所在地",
)
_IP_WORDS = ("ip",)
_TIME_WORDS = ("几点", "时间", "几点了", "现在几点")
_DATE_WORDS = ("几号", "日期", "星期", "周几", "几月几号")

# 提取关键词时要去掉的词（长词在前，避免残留）
_STRIP_WORDS = (
    "帮我搜索一下", "帮我打开一下", "帮我搜索", "帮我打开", "帮我查询", "帮我查", "帮我搜", "给我打开", "给我搜索",
    "搜索一下", "打开一下", "搜一下", "查一下", "查询一下", "开一下",
    "打开", "启动", "运行", "搜索", "查询", "访问", "浏览", "搜", "查",
    "帮我", "给我", "请", "麻烦", "麻烦你",
    "一下", "网页", "网站",
)


def normalize_keyword(keyword: str) -> str:
    """规范化关键词：简称/别名 → 标准词（忽略大小写）。"""
    kw = keyword.strip().lower()
    return ALIAS_MAP.get(kw, keyword)


def extract_keyword(text: str) -> str:
    """从指令中提取关键词（去掉动词/助词/位置词）。"""
    kw = text
    for w in _STRIP_WORDS:
        kw = kw.replace(w, "")
    # 去掉"XX上的/里的/内的"位置修饰词（如"桌面上的报告"→"报告"）
    kw = re.sub(r"[A-Za-z0-9\u4e00-\u9fa5]+[上的里内]", "", kw)
    return kw.strip(" 的呀啊吧了吗呢。，！？、,.!? \t")


def is_path(s: str) -> bool:
    """判断是否为本地路径（含盘符或路径分隔符，排除网址）。"""
    s = s.strip()
    if s.lower().startswith(("http://", "https://")):
        return False
    return ":" in s or "\\" in s or "/" in s


def _search_local(keyword: str):
    """在常见目录里搜索匹配关键词的文件夹/文件，返回 Path 或 None。"""
    kw = keyword.lower()
    search_dirs = [
        _resolve_user_dir("Desktop"),
        _resolve_user_dir("Downloads"),
        _resolve_user_dir("Documents"),
        _resolve_user_dir("Pictures"),
        _resolve_user_dir("Music"),
        _resolve_user_dir("Videos"),
    ]
    for d in search_dirs:
        if not d.exists():
            continue
        try:
            for item in d.iterdir():
                if kw and kw in item.name.lower():
                    return item
        except Exception:  # noqa: BLE001
            continue
    return None


def _bookmark_files() -> list:
    """常见浏览器书签文件路径列表。"""
    local = os.environ.get("LOCALAPPDATA", "")
    return [
        os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Bookmarks"),
        os.path.join(local, "Google", "Chrome", "User Data", "Default", "Bookmarks"),
    ]


def _walk_bookmarks(node):
    """递归遍历书签树，yield (name, url)。兼容 roots 的键值对结构（bookmark_bar/other/synced...）。"""
    if isinstance(node, dict):
        url = node.get("url")
        if url:
            yield node.get("name", ""), url
        for child in node.get("children", []) or []:
            yield from _walk_bookmarks(child)
        # roots 结构：键是 folder 名（bookmark_bar 等），值是 folder dict
        for key, value in node.items():
            if key in ("url", "name", "children", "type", "date_added", "date_modified", "id", "guid"):
                continue
            if isinstance(value, (dict, list)):
                yield from _walk_bookmarks(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_bookmarks(item)


def find_in_bookmarks(keyword: str):
    """在浏览器收藏夹中查找关键词对应的网址。返回 URL 或 None。"""
    kw = keyword.lower()
    for bf in _bookmark_files():
        if not os.path.exists(bf):
            continue
        try:
            with open(bf, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name, url in _walk_bookmarks(data.get("roots", {})):
                if kw and kw in name.lower():
                    return url
        except Exception:  # noqa: BLE001
            continue
    return None


def _open_in_edge(target: str) -> bool:
    """用 Edge 打开 URL。"""
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for ep in edge_paths:
        if os.path.exists(ep):
            subprocess.Popen([ep, target])
            return True
    webbrowser.open(target)
    return True


def _search_in_edge(keyword: str) -> bool:
    """在 Edge 用 Bing 搜索关键词（URL 编码，避免中文被补"/"）。"""
    search_url = f"https://www.bing.com/search?q={urllib.parse.quote(keyword)}"
    return _open_in_edge(search_url)


def detect_action(text: str):
    """从用户文本检测操作意图。返回动作 dict 或 None。"""
    if not text:
        return None
    # 0. 查询位置/日期/时间/IP（位置联网定位，其余本地，优先级最高）
    tl = text.lower()
    if any(w in text for w in _LOCATION_WORDS):
        return {"type": "query_info", "kind": "location"}
    if any(w in tl for w in _IP_WORDS):
        return {"type": "query_info", "kind": "ip"}
    if any(w in text for w in _TIME_WORDS):
        return {"type": "query_info", "kind": "time"}
    if any(w in text for w in _DATE_WORDS):
        return {"type": "query_info", "kind": "date"}
    # 1. 系统命令（关机/重启等，无需动词）；带否定词（别关机）时不视为执行指令
    for name, cmd in COMMAND_MAP.items():
        if name in text:
            idx = text.find(name)
            if any(w in text[max(0, idx - 6):idx] for w in _NEGATE_WORDS):
                return None
            return {"type": "run_command", "label": name, "target": cmd}
    # 2. 打开软件（软件名 + 打开/启动动词）；含用户从磁盘添加的自定义软件
    for name, cmd in list(APP_MAP.items()) + list(_perms.get("custom_apps", {}).items()):
        if name in text and any(v in text for v in _OPEN_VERBS):
            return {"type": "open_app", "label": name, "target": cmd}
    # 3. 目录：查看（看看/查看）或打开（打开 + 目录名，兼容"打开桌面文件夹"等称呼）
    for name, path in DIR_MAP.items():
        # 查看目录：看看/查看/列出 + 目录名
        if name in text and any(v in text for v in _LIST_VERBS):
            return {"type": "list_dir", "label": name, "target": path}
        # 打开目录：打开 + 目录名（若后面紧跟"上/里/内/中"表示子项，则走通用查找，如"打开桌面上的报告"）
        if name in text and any(v in text for v in _OPEN_VERBS):
            idx = text.find(name)
            after = text[idx + len(name):]
            if not after.startswith(("上", "里", "内", "中")):
                return {"type": "open_path", "label": name, "target": path}
    # 4. 打开/搜索 XXX（通用分层查找）
    if any(v in text for v in _OPEN_VERBS) or any(v in text for v in _SEARCH_VERBS):
        keyword = extract_keyword(text)
        if keyword:
            return _resolve_open(keyword)
    return None


def _resolve_open(keyword: str):
    """打开 XXX 的分层查找：路径 → 本地文件/文件夹 → 书签 → Bing 搜索。"""
    # 明确路径
    if is_path(keyword):
        return {"type": "open_path", "label": keyword, "target": keyword}
    # 本地搜索（文件夹/文件）
    local = _search_local(keyword)
    if local:
        return {"type": "open_path", "label": keyword, "target": str(local)}
    # 书签查找
    kw = normalize_keyword(keyword)
    url = find_in_bookmarks(kw)
    if url:
        return {"type": "open_url", "label": kw, "target": url}
    # Bing 搜索兜底
    return {"type": "search", "keyword": kw}


def _get_local_ip() -> str:
    """获取本机局域网 IP（UDP 连接外部地址取得路由出口 IP，不实际发包）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "未知"
    finally:
        s.close()


# 公网 IP 定位接口
_GEO_API = "http://ip-api.com/json?lang=zh-CN&fields=status,country,regionName,city"


def _format_region(data: dict) -> str:
    """把 IP 库返回整理成「国家、省/地区」。

    **刻意丢掉 `city`**：运营商（尤其电信）的 IP 池大量挂在省会，实测浙江某地的
    IP 会被标成杭州 —— 城市级基本不可信。只说到省/地区一级，宁可粗一点，
    也不要报一个错的城市（用户会以为 AI 在说它自己所在的城市）。
    """
    country = str(data.get("country") or "").strip()
    region = str(data.get("regionName") or "").strip()
    if country and region:
        return f"{country}、{region}"
    return country or region or "未知位置"


def _get_geo_location() -> str:
    """通过公网 IP 获取**设备**所在地区（国家、省/地区），不是 API 服务器的位置。

    这是网络出口 IP 的归属地：换代理/VPN 会跟着变，城市级不可信（见 `_format_region`）。
    """
    import json
    import urllib.request
    try:
        req = urllib.request.Request(_GEO_API)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "success":
            return _format_region(data)
    except Exception:
        pass
    return "无法联网定位"


def _query_info(kind: str) -> str:
    """查询位置/日期/时间/IP，返回结果描述（供 AI 回应用户）。"""
    now = datetime.datetime.now()
    if kind == "location":
        return _get_geo_location()
    if kind == "time":
        return f"现在是 {now.hour} 点 {now.minute} 分 {now.second} 秒"
    if kind == "date":
        weekday = "一二三四五六日"[now.weekday()]
        return f"今天是 {now.year} 年 {now.month} 月 {now.day} 日，星期{weekday}"
    if kind == "ip":
        return f"本机 IP 地址是 {_get_local_ip()}"
    return "未知查询"


def execute_action(action, text: str = "") -> str:
    """执行动作（唯一入口，先过安全边界），返回结果描述（供 AI 回应用户）。

    三级分流：白名单拦截 → 拒绝；危险级 → 排入延迟队列（可语音取消）；安全级 → 立即执行。
    """
    ok, reason = check_permission(action, text)
    if not ok:
        return reason
    if is_danger(action):
        return schedule_danger(action)
    return _run_action_now(action)


def _run_action_now(action) -> str:
    """真正执行动作（危险级操作由延迟队列在到点后调用）。"""
    t = action.get("type")
    label = action.get("label", "")
    try:
        if t == "query_info":
            return _query_info(action.get("kind"))
        if t == "run_command":
            subprocess.Popen(action["target"])
            return f"已执行「{label}」"
        if t == "open_app":
            # 免 UAC：开了开关的软件改走「最高权限计划任务」，由任务计划服务代为启动
            # → 不再弹 UAC（详见 app/launch_task.py）。任务没建好/启动失败则退回普通方式，
            # 绝不因为免 UAC 没生效而打不开软件。
            note = ""
            if label in _perms.get("no_uac", []):
                exe = app_exe_path(label)
                if exe:
                    from . import launch_task
                    if launch_task.run_task(exe):
                        return f"已打开软件「{label}」（已按管理员权限免 UAC 启动）"
                note = "（免 UAC 启动未生效，已按普通方式打开）"
            subprocess.Popen([action["target"]])
            return f"已打开软件「{label}」{note}"
        if t == "open_path":
            target = action["target"]
            os.startfile(target)
            return f"已打开「{label}」"
        if t == "open_url":
            _open_in_edge(action["target"])
            return f"已在 Edge 打开你收藏的「{label}」"
        if t == "search":
            _search_in_edge(action["keyword"])
            return f"已在 Edge 搜索「{action['keyword']}」"
        if t == "list_dir":
            p = Path(action["target"])
            if not p.exists():
                return f"目录「{label}」不存在"
            items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            if not items:
                return f"「{label}」目录是空的"
            lines = [("文件 " if x.is_file() else "文件夹 ") + x.name for x in items[:20]]
            more = f"（共 {len(items)} 项，仅显示前 20 项）" if len(items) > 20 else f"（共 {len(items)} 项）"
            return f"「{label}」目录内容：\n" + "\n".join(lines) + "\n" + more
    except Exception as e:  # noqa: BLE001
        return f"执行「{label}」时出错：{e}"
    return f"未知操作：{t}"
