"""配置加载与保存。"""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # IgnotusAssistant/
CONFIG_PATH = BASE_DIR / "config.json"

# 默认 AI 服务端点（每个 API 条目都可各自覆盖，从而兼容任何 OpenAI 兼容模型）
# DeepSeek 官方文档：模型名请使用 deepseek-flash（旧名 deepseek-chat / deepseek-v4-flash
# 对应模型已下线，新名由 DeepSeek-V4.1-Flash 提供服务）
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"

DEFAULT_CONFIG = {
    # [{"name": str, "api_key": str, "base_url": str, "model": str}]  名称与 key 绑定
    # base_url / model 留空即用 DEFAULT_BASE_URL / DEFAULT_MODEL
    "apis": [],
    "current_api": "",    # 当前使用的 API 名称（同一时刻只有这一个生效）
    "current_role": "alice",
    "volume": 0.5,        # 音量 0.0~1.0，默认 50%；0 表示静音（静音时跳过合成加快回复）
    # 通用设置（设置 → 通用设置）
    # auto_start 仅作缓存，界面以注册表实际状态为准；close_action 决定标题栏「×」的行为
    "general": {
        "auto_start": False,       # 开机自启（写 HKCU\\...\\Run，见 app/autostart.py）
        "close_action": "tray",    # tray=最小化到托盘（默认） | quit=关闭软件
        # 静音模式：AI 只输出中文、不做语音合成与播放 —— 去掉「生成日语 + 合成日语」两段时间，
        # 文字在中文吐完的那一刻立即出现（代价是没有声音）。详见 docs/01 §F3/F4。
        # ★★2026-09-29 改口径：**落盘持久化**（用户要求「完全退出后重开要保留开关状态」）——
        #   与 lock_pet 同类：它是用户的**偏好**，`load_config` 照样读它、`save_config` 不剔它
        #   ⇒ 重开 / 开机自启后保持上次选择（`config.json` 的 `general.mute_mode`）。
        # ★改之前它刻意**不落盘**（每次启动从「关」开始），理由是「上次静音着退出 ⇒ 这次一声
        #   不吭，用户会以为软件坏了」；现在用户**已知情并明确要求持久化**，故反转 ——
        #   沿革与边界见 docs/02 §9.7。
        # ⚠️与下面 patpat_mode 的差别只剩这一条：那一个仍是纯运行时（重启即关）。
        "mute_mode": False,
        # patpat 模式（2026-09-20）：左键点角色贴图 → 叠一只手做「抬起 → 下压」+ 随机一段摸摸音效。
        # 开关在「通用设置 → 模式切换」与「右键角色贴图的菜单」两处，**与其他模式不冲突**（可直接打开）。
        # ★二十一改：这一档**只管「有没有那只手 + 有没有声音」** —— 关着时单击**照样让贴图形变**。
        # ★ **纯运行时状态**：不读磁盘、不落盘，每次启动都从「关」开始。
        # ⚠️★别照着上面那个静音模式抄「落盘」—— 2026-09-29 只有静音改成了持久化，
        #   patpat 仍是「重启即关」（用户 2026-09-20 的口径就是「与其它模式一样」）。
        "patpat_mode": False,
        # 桌宠固定（2026-09-22）：**开着 = 贴图不能被拖动**（只锁「拖」，单击抚摸 / 思考气泡照旧）。
        # 开关在「通用设置 → 桌宠调整」与「右键角色贴图的菜单」两处。
        # ★与静音 / patpat 那两项**不同**：这一项是用户的**偏好**，**落盘持久化**（默认「开」= 固定）。
        "lock_pet": True,
        # 音色克隆模型的**安装位置**（2026-09-22，通用设置 → 语音模型 → 安装位置）。
        # ★落盘持久化（与 lock_pet 同类）。**空串 = 按探测顺序自动找**（见 app/voice_model.py）：
        #   用户指定的目录 → 项目内 runtime/GPT-SoVITS → D:\GPT-SoVITS（历史路径）。
        "model_dir": "",
    },
    # 安全边界：白名单 + 危险级延迟执行（详见 docs/01-需求规格说明书.md §5）
    # 四个列表留空 = 使用 tools.py 中的内置默认范围：
    #   ★allowed_dirs **默认是空的**（2026-09-28 用户拍板：不把打包机自己的目录带进成品，
    #     由用户自己在权限面板里添加；后果与恢复方式见 docs/02 §8.9）
    #   allowed_apps = APP_MAP 除 cmd / powershell；allowed_actions = 七类全开；blocked_keywords 空
    "permissions": {
        "allowed_dirs": [],       # 允许操作的目录范围（打开/查看文件与文件夹）
        "allowed_apps": [],       # 允许打开的软件（APP_MAP 中的名称，或 custom_apps 里的自定义名称）
        "allowed_actions": [],    # 允许执行的操作类型（query_info/open_path/open_app/...）
        "blocked_keywords": [],   # 命中即拒绝的关键词
        "danger_delay": 30,       # 危险级操作延迟执行的秒数，期间可语音取消
        # 用户从磁盘选进来的软件：{"软件名": "可执行文件绝对路径"}
        # 区别于 APP_MAP（系统自带、在 PATH 里），这些只有路径，启动时直接 Popen 该路径
        "custom_apps": {},
        # 开启了「免 UAC 启动」的软件名（默认空 = 全部按普通方式启动，会弹 UAC）。
        # 开启时会在任务计划里建一个「最高权限、无触发器」的同名任务，之后用
        # `schtasks /run` 启动 ⇒ 不再弹 UAC。详见 app/launch_task.py。
        "no_uac": [],
    },
    "roles": {
        "alice": {
            "name": "爱丽丝",
            "wake_words": ["爱丽丝"],
            "persona": "persona/alice.md",
            "pet_dir": "pet/alice",
        },
        "ellen": {
            "name": "艾莲",
            "wake_words": ["艾莲"],
            "persona": "persona/ellen.md",
            "pet_dir": "pet/ellen",
        },
    },
}


# ★临时（2026-09-28，用户拍板）：艾莲的角色贴图**尚未制作完成**（现仅简单占位）⇒ 暂不可切换，
#   暂时只能用爱丽丝。她是**灰掉、点不动**，不是从列表里删掉。
# ★★**唯一真值就是这一行** —— 两处切换入口（① 主界面左栏头像下拉 ② 桌宠右键「切换」二级）
#   都调 `is_role_switchable()`，**不各写一份**（本项目吃过「同一量两处各写一份 ⇒ 静默漂移」的亏）。
# ★**恢复方式**：贴图做完后把 "ellen" 加回这个元组即可（两处入口同时恢复，不可能只恢复一半）；
#   细则与恢复步骤见 docs/02 §24。
SWITCHABLE_ROLES = ("alice",)


def is_role_switchable(key) -> bool:
    """该角色当前是否**可被切换**（★唯一真值 = `SWITCHABLE_ROLES`；见 docs/02 §24）。"""
    return str(key) in SWITCHABLE_ROLES


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict:
    cfg = _deep_merge(DEFAULT_CONFIG, {})
    if CONFIG_PATH.exists():
        try:
            override = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = _deep_merge(cfg, override)
        except Exception:
            pass
    # 迁移旧版单 key 结构：api_key -> apis 列表
    if not cfg.get("apis") and cfg.get("api_key"):
        cfg["apis"] = [{"name": "默认", "api_key": cfg["api_key"]}]
        cfg["current_api"] = "默认"
        cfg.pop("api_key", None)
    # 归一化每个 API 条目：名称/密钥必须为字符串；补全 base_url 与 model（留空即默认值）。
    # 这样旧配置（只有 name+api_key）也能自动获得 DeepSeek 默认端点，不会因缺字段报错。
    raw_apis = cfg.get("apis")
    if not isinstance(raw_apis, list):
        raw_apis = []
        cfg["apis"] = raw_apis
    norm_apis = []
    for entry in raw_apis:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        base = str(entry.get("base_url", "") or "").strip() or DEFAULT_BASE_URL
        model = str(entry.get("model", "") or "").strip() or DEFAULT_MODEL
        norm_apis.append({
            "name": name,
            "api_key": str(entry.get("api_key", "") or "").strip(),
            "base_url": base,
            "model": model,
        })
    cfg["apis"] = norm_apis
    # 保证 current_api 有效：为空或不在列表时指向第一个
    names = [a["name"] for a in norm_apis]
    if cfg.get("current_api") not in names:
        cfg["current_api"] = names[0] if names else ""
    # 音量：默认 0.5，兼容缺失/类型错误，限制在 0.0~1.0
    try:
        vol = float(cfg.get("volume", 0.5))
    except (TypeError, ValueError):
        vol = 0.5
    cfg["volume"] = max(0.0, min(1.0, vol))
    # 权限段归一化：列表字段去空、只留字符串；danger_delay 钳制在 5~120 秒
    perms = cfg.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
        cfg["permissions"] = perms
    for key in ("allowed_dirs", "allowed_apps", "allowed_actions", "blocked_keywords"):
        val = perms.get(key)
        if not isinstance(val, list):
            perms[key] = []
        else:
            perms[key] = [str(x).strip() for x in val if str(x).strip()]
    try:
        delay = int(perms.get("danger_delay", 30))
    except (TypeError, ValueError):
        delay = 30
    perms["danger_delay"] = max(5, min(120, delay))
    # custom_apps：{"软件名": "exe 绝对路径"}，去空、只留字符串键值对
    custom = perms.get("custom_apps")
    if not isinstance(custom, dict):
        custom = {}
    perms["custom_apps"] = {
        str(k).strip(): str(v).strip()
        for k, v in custom.items()
        if str(k).strip() and str(v).strip()
    }
    # no_uac：开启「免 UAC 启动」的软件名列表，去空、去重且保序（顺序即用户添加顺序）。
    # **非字符串一律丢掉**（不 str() 转换）：软件名只能是字符串，把 7 变成 "7"
    # 只会得到一个永远匹配不到任何软件的假条目。
    no_uac = perms.get("no_uac")
    if not isinstance(no_uac, list):
        no_uac = []
    seen, clean = set(), []
    for x in no_uac:
        if not isinstance(x, str):
            continue
        name = x.strip()
        if name and name not in seen:
            seen.add(name)
            clean.append(name)
    perms["no_uac"] = clean
    # 通用设置归一化：close_action 只允许 tray / quit，非法值回退托盘
    general = cfg.get("general")
    if not isinstance(general, dict):
        general = {}
        cfg["general"] = general
    action = str(general.get("close_action", "tray")).strip().lower()
    general["close_action"] = action if action in ("tray", "quit") else "tray"
    general["auto_start"] = bool(general.get("auto_start", False))
    # 静音模式（2026-09-29 起）：**落盘的偏好** —— 用户口径「完全退出后重开要保留开关状态」。
    # ★**只认真正的 bool**：非 bool 的脏值（`""` / `"yes"` / `1` / `[]`…）一律当「关」。
    #   方向是刻意的 —— 宁可不敢静音，也不能因为磁盘上一个脏值就让软件启动即无声
    #   （「启动后一声不吭」正是这个字段最容易吓到人的地方）。对照：`auto_start` / `lock_pet`
    #   用的是宽松的 `bool(...)`，那是因为它们的默认值本身就是「安全侧」。
    _mute_disk = general.get("mute_mode", False)
    general["mute_mode"] = _mute_disk if isinstance(_mute_disk, bool) else False
    # patpat 模式：★与静音**不同** —— 它仍是**纯运行时状态**，每次启动从「关」开始
    # （磁盘上的值一律忽略；用户 2026-09-20 的口径就是「与其它模式一样，重启即关」）。
    general["patpat_mode"] = False
    # 桌宠固定：**与上面两项不同，它是落盘的偏好**（不是运行时状态）⇒ 只做类型归一，
    # 缺键即取默认「开」＝ 固定（用户口径「默认打开固定」）。
    general["lock_pet"] = bool(general.get("lock_pet", True))
    # 音色克隆模型的**安装位置**（2026-09-22）：落盘的偏好。空串 = 按探测顺序自动找
    # （见 app/voice_model.py：自定义目录 → 项目内 runtime/GPT-SoVITS → D:\GPT-SoVITS）。
    general["model_dir"] = str(general.get("model_dir") or "").strip()
    return cfg


def get_current_api(cfg: dict) -> dict | None:
    """返回当前使用的 API（名称+key），无则 None。"""
    name = cfg.get("current_api")
    for a in cfg.get("apis", []):
        if a.get("name") == name:
            return a
    return None


# 只在本次运行内有效、**不写进 config.json** 的字段（写了反而误导：读回来会被忽略）。
# ★★2026-09-29 起 `mute_mode` **已移出这张名单** —— 它改成落盘的偏好（用户要求记住开关状态）。
#   现在只剩 `patpat_mode` 一个纯运行时项；**新增纯运行时项必须同时登记到这里 + `load_config`
#   里压回 False**，否则用户会看到「改了却没生效」的假持久化。
_RUNTIME_ONLY_GENERAL = ("patpat_mode",)


def save_config(cfg: dict) -> None:
    data = dict(cfg)
    general = data.get("general")
    if isinstance(general, dict):
        data["general"] = {
            k: v for k, v in general.items() if k not in _RUNTIME_ONLY_GENERAL
        }
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
