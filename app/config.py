"""配置加载与保存。"""
import copy
import json
import os
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # IgnotusAssistant/
CONFIG_PATH = BASE_DIR / "config.json"

# 默认 AI 服务端点（每个 API 条目都可各自覆盖，从而兼容任何 OpenAI 兼容模型）
# DeepSeek 官方文档：模型名请使用 deepseek-flash（旧名 deepseek-chat / deepseek-v4-flash
# 对应模型已下线，新名由 DeepSeek-V4.1-Flash 提供服务）
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"

DEFAULT_CONFIG = {
    # ★★2026-10-02（用户口径「每个角色用独立的列表，可以用同个 key，但命名是分开显示的」）：
    #   **每个角色一份完全独立的 API 列表** —— 结构 {角色key: [条目, …]}，
    #   条目 = {"name": str, "api_key": str, "base_url": str, "model": str}
    #   （base_url / model 留空即用 DEFAULT_BASE_URL / DEFAULT_MODEL）。
    #   ★同一个 key 可以在两个角色下各录一次、**命名也可以各不相同**，互相看不见、删一个
    #     不影响另一个。这就是「独立列表」与「共用一份、各自选一个」的分野 —— 后者做不到
    #     「同一个 key 在两边显示成不同名字」。
    #   ★这里留**空 dict**：真正的角色键由 `load_config` 按 `cfg["roles"]` 补齐 ——
    #     将来加角色（艾莲贴图做完时）不用回来改这里，也就不会出现「新角色没有 apis 键」。
    "apis": {},
    # 每个角色**当前生效**的那一个 API 的名字（各自独立；空串 = 该角色还没有可用 API）。
    # ★与 `apis` 一样是 {角色key: 名字}；老配置里那个字符串由 `_normalize_apis` 迁移。
    "current_api": {},
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
            # ★`persona` = **当前使用的那套设定**，值就是**人设全文**（就是喂给模型的
            #   system prompt），它同时是「设定卡」页里「哪张预设是选中的」的**唯一判据** ——
            #   presets 里哪一项的 `persona` 等于它，哪一项就是当前预设。不另设
            #   `current_preset` 指针：两个字段一旦漂移，页面上「显示的是这一份、实际用的是
            #   那一份」会静默发生（本项目吃过的亏）。
            # 2026-09-30 晚（设定卡可切换）：这个字段的**载体**从「人设文件路径」改成
            #   「人设文本本身」—— 原因见 docs/02 §25.17。**这里仍写路径**：它是
            #   `resolve_persona_text` 认得的「素材」，`load_config` 会就地解析成全文；
            #   ★用户切换过一次后 `save_config` 落盘的就是全文，此后**不再碰这些 md**
            #   （即：md 从"真值"退化成"一次性素材"，改它们不再生效）。
            "persona": "persona/alice.md",
            "pet_dir": "pet/alice",
            # 「设定卡」（管理 → 设定卡）的「预设」区块（2026-09-30 新增）。
            # 元素 = {"name": 预设命名（显示在卡片上）, "persona": 该预设的人设**全文**}。
            # ★列表顺序 = 卡片从上到下的顺序；**选中的那张不会因为新增而挪位置**。
            # ★内置项这里写**素材路径**，加载时被 `resolve_persona_text` 解析成全文；
            #   一旦用户切换过、配置落盘，之后以 `config.json` 里那份为准（用户自己的改动优先）。
            # 爱丽丝两张 —— 第一张是 wiki 版（默认**当前生效**：上面的 `persona` 与它解析后
            #   相等 ⇒ 卡片自动显示为选中），第二张是从游戏内聊天记录统计出来的另一套。
            #   ★两张都点得动：**点卡片（或圆点）即切过去**（用户 2026-09-30 口径）。
            "presets": [
                {"name": "天童爱丽丝（wiki）", "persona": "persona/alice.md"},
                {"name": "天童爱丽丝（局内聊天记录统计）", "persona": "persona/alice_chatlog.md"},
            ],
        },
        "ellen": {
            "name": "艾莲",
            "wake_words": ["艾莲"],
            "persona": "persona/ellen.md",
            "pet_dir": "pet/ellen",
            "presets": [
                {"name": "艾莲（wiki）", "persona": "persona/ellen.md"},
            ],
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


# `.md` 结尾才当成素材路径（见下面的 `resolve_persona_text`：这条只在**没有换行**时才轮到）
_PERSONA_PATH_SUFFIX = ".md"


def resolve_persona_text(value) -> str:
    """把「人设字段的值」统一成**人设全文** —— ★人设取值的**唯一入口**（2026-09-30 晚）。

    这个字段有两态（「设定卡」从"只可查看"变成"可切换"时引入）：
      - **人设全文**：卡里自带的那份文本（`save_config` 落盘后就是它）；
      - **素材路径**：`DEFAULT_CONFIG` 里写的单行路径（`persona/alice.md`），
        以及**老 `config.json`** 里存的路径。

    ★判据 = **有没有换行**：路径不可能含换行，而两份内置人设都是多行 markdown。
      ★**别改成"看结尾是不是 `.md`"** —— 那会把「真正在用的全文」误判成路径；
      下面确实还有一条 `.md` 分支，但它只在**没有换行**时才轮到（即真的像路径了）。
      ★**逐字返回，一个字符都不动**：这份文本就是喂给模型的 system prompt，
        顺手"清理一下 markdown"会静默改掉回复内容与时长（用户口径：输出不要有太大变化）。

    两条口径与旧 `ai.load_persona` 完全一致、别改：
      - 路径读不到 ⇒ **空串**（宁可不带设定，也不把 `persona/alice.md` 这个**路径字符串**
        当成人设喂给模型 —— 那会让模型收到一句莫名其妙的指令）；
      - 全文原样返回（含 `# 一级标题`：旧路径也是把整个文件原文喂进去的，去掉就变了）。

    细则与取舍（为什么 md 会从"真值"退化成"素材"）见 docs/02 §25.17。
    """
    text = str(value if value is not None else "")
    if not text.strip():
        return ""
    if "\n" in text:
        return text                      # 已经是全文
    if text.endswith(_PERSONA_PATH_SUFFIX):
        p = BASE_DIR / text
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except OSError:
            pass
        return ""                        # 路径存在但读不出来 / 文件不在了
    return text                          # 真就是一小段单行自定义人设


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _merge_presets(defaults, saved) -> list:
    """把**内置预设**并回从 `config.json` 读到的那一份（2026-09-30，加第二张预设时踩到）。

    ★**为什么必须做**：`_deep_merge` 对**列表是整段替换**，而 `save_config` 会把 `roles`
      整段写进 `config.json` ⇒ 配置文件里那份「上次保存时的预设快照」会把默认配置里**新加的内置
      预设盖掉**。现象是「代码里明明加了一张卡，页面上就是不出现」，而且**完全不报错**。
    ★**骨架用默认顺序**：内置项在前（顺序跟着 `DEFAULT_CONFIG` 走），配置文件里有、默认里没有的
      项（将来的用户自定义预设）按原顺序追加在后 —— 与「新预设排在下面」的既有口径一致。
    ★**同名项以配置文件里的那份为准**：尊重用户改动的人设内容（`persona` 值此时可能已是**全文**，
      见 `resolve_persona_text`）—— 这也正是「用户切换过之后，内置定义不再覆盖用户那份」的实现点。
    ★**副作用**：用户**删不掉**内置预设 —— 但内置项是随 `persona/*.md` 一起来的素材，本就不该由
      用户删；将来做「删除」功能时，要删的是用户自定义项。
    ★**纯函数**：两个入参都**假定已被 `resolve_persona_text` 解析过**（本函数只按 `name` 做归并，
      不碰值的内容、也不读文件）—— 保持这样测试才好写、也不会有隐藏的 I/O。
    ★★**人设值一律原样搬运，绝对不许 `.strip()`**（2026-09-30 晚踩到）：值现在是**人设全文**，
      而人设文件末尾那个换行是它的一部分 —— 这里 strip 一下，内置卡的文本就比
      `roles[*].persona` **少一个字符**，`presets[*].persona == role["persona"]` 不再成立
      ⇒ 页面上那张卡**显示成"未选中"**（而且不报错）；点它还会被判成"换了张卡"而白写一次盘。
      `strip()` 只用来**判空**（`text.strip()`），搬运用的是原串。
    """
    out, used = [], set()
    for item in defaults or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        raw = item.get("persona")
        text = str(raw) if raw is not None else ""
        if not name or not text.strip():          # ★只判空才 strip
            continue
        for cand in saved:
            if cand["name"] == name:
                out.append(cand)          # 配置里有同名 ⇒ 用配置里那份（尊重用户改动）
                break
        else:
            out.append({"name": name, "persona": text})
        used.add(name)
    out.extend(item for item in saved if item["name"] not in used)
    return out


# 旧版（只有一份全局 API 列表）迁移落点 —— **永远是 alice**，见 `_normalize_apis`。
LEGACY_API_ROLE = "alice"


def _norm_api_entries(raw) -> list:
    """把一段 API 列表清洗成规范条目：名称/密钥转字符串、补全 base_url 与 model。

    ★无名条目直接丢（一个没有名字的条目在界面上是点不动、也选不中的幽灵行），
      非 dict 的脏项同理 —— 与旧实现逐字一致，别改口径。
    """
    out = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        out.append({
            "name": name,
            "api_key": str(entry.get("api_key", "") or "").strip(),
            "base_url": str(entry.get("base_url", "") or "").strip() or DEFAULT_BASE_URL,
            "model": str(entry.get("model", "") or "").strip() or DEFAULT_MODEL,
        })
    return out


def _normalize_apis(cfg) -> tuple:
    """API 段归一化：**每个角色一份独立列表**（2026-10-02 用户口径）。

    返回 `(apis, current_api)` 两个 dict，键都是角色 key。

    三件事：
      ① **迁移**：旧结构是**一份全局列表**（`"apis": [...]` + `"current_api": "名字"`），
         更老的还有单 key 的 `"api_key": "sk-…"`。一律搬进 **alice**。
         ★**不能**按 `cfg["current_role"]` 落 —— 老配置里那个字段可能是 `"ellen"`
         （用户以前切过去过，见 `SWITCHABLE_ROLES`），那样会把老师唯一的那把 key
         塞进一个**当前根本切不过去**的角色里，等于配置凭空消失、界面显示「没配 API」。
      ② **补齐**：每个角色都要有 `apis` / `current_api` 键（缺了就补空）——
         将来 `roles` 里加角色时自动获得，不用回来改 `DEFAULT_CONFIG`。
      ③ **校验**：`current_api[角色]` 必须真的在那个角色的列表里，否则回落到该列表第一项
         （列表空 ⇒ 空串）。★与旧的单角色逻辑同一个口径，只是按角色各来一遍。
    """
    raw = cfg.get("apis")
    raw_cur = cfg.get("current_api")
    apis, currents = {}, {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            apis[str(k)] = _norm_api_entries(v)
        if isinstance(raw_cur, dict):
            for k, v in raw_cur.items():
                currents[str(k)] = str(v or "").strip()
        # ★更老的「单 key」结构：此时 `apis` 是**新默认值那个空 dict**（`_deep_merge` 把
        #   盘上的 `api_key` 合了进来，而它压根不认识 apis 这个键）⇒ 只有「一份条目都没有」
        #   时才认它，免得把用户后来真配好的列表又糊上一条「默认」。
        if not any(apis.values()):
            old_key = str(cfg.get("api_key") or "").strip()
            if old_key:
                apis[LEGACY_API_ROLE] = [{
                    "name": "默认", "api_key": old_key,
                    "base_url": DEFAULT_BASE_URL, "model": DEFAULT_MODEL,
                }]
                currents[LEGACY_API_ROLE] = "默认"
    else:
        legacy = _norm_api_entries(raw)
        if not legacy:
            old_key = str(cfg.get("api_key") or "").strip()
            if old_key:
                legacy = [{"name": "默认", "api_key": old_key,
                           "base_url": DEFAULT_BASE_URL, "model": DEFAULT_MODEL}]
                raw_cur = "默认"
        apis[LEGACY_API_ROLE] = legacy
        currents[LEGACY_API_ROLE] = str(raw_cur or "").strip()
    cfg.pop("api_key", None)      # 迁移完就不该再留着（留着只会在下次写盘时复活）

    keys = role_keys(cfg)
    for rk in keys:
        apis.setdefault(rk, [])
        names = [a["name"] for a in apis[rk]]
        if currents.get(rk) not in names:
            currents[rk] = names[0] if names else ""
    # 配置里有、`roles` 里没有的脏键（角色被删掉 / 手改出来的名字）：丢。留着它只会
    # 「永远显示不出来、却一直跟着写盘」，属于最难查的一类不一致。
    return ({k: v for k, v in apis.items() if k in keys},
            {k: v for k, v in currents.items() if k in keys})


def role_keys(cfg) -> list:
    """配置里有哪些角色（`roles` 的键，保序）。**角色列表的唯一入口**。"""
    roles = cfg.get("roles")
    keys = [str(k) for k in roles] if isinstance(roles, dict) and roles else []
    return keys or [LEGACY_API_ROLE]


def apis_for(cfg, role_key=None) -> list:
    """**某个角色**的 API 列表（`role_key` 省略 ⇒ 当前角色）。取值的唯一入口。"""
    rk = str(role_key or cfg.get("current_role") or LEGACY_API_ROLE)
    apis = cfg.get("apis")
    if not isinstance(apis, dict):
        return []
    out = apis.get(rk)
    return out if isinstance(out, list) else []


def current_api_name(cfg, role_key=None) -> str:
    """**某个角色**当前生效的 API 名字（空串 = 还没选 / 列表是空的）。"""
    rk = str(role_key or cfg.get("current_role") or LEGACY_API_ROLE)
    cur = cfg.get("current_api")
    if not isinstance(cur, dict):
        return ""
    return str(cur.get(rk) or "")


def set_current_api(cfg, name, role_key=None) -> None:
    """把**某个角色**的「当前 API」改成 `name`（就地改，不重写整个 dict）。"""
    rk = str(role_key or cfg.get("current_role") or LEGACY_API_ROLE)
    cur = cfg.get("current_api")
    if not isinstance(cur, dict):
        cur = {}
        cfg["current_api"] = cur
    cur[rk] = str(name or "")


def has_any_api(cfg) -> bool:
    """**任意一个角色**配过任意一个 API —— 判「老用户 / 新用户」用。"""
    return any(apis_for(cfg, rk) for rk in role_keys(cfg))


def load_config() -> dict:
    # ★★必须 **deepcopy**，不能只 `_deep_merge(DEFAULT_CONFIG, {})`。
    #   `_deep_merge` 是**浅拷贝**：`out = dict(base)`，遇到 dict 递归、遇到 **list 直接沿用同一个
    #   对象** ⇒ 没有配置文件时 `cfg["roles"] is DEFAULT_CONFIG["roles"]`，`cfg["roles"]["alice"]`
    #   就是**默认配置里那个 dict 本身**。而下面的角色段归一化会**就地写** `_role["persona"]` /
    #   `_role["presets"]` ⇒ **默认配置被加载过程改掉**。
    #   以前那几行恰好是幂等的（写回等值），所以没暴出来；2026-09-30 晚把 `persona` 从"路径"
    #   解析成"全文"之后就不幂等了 —— `DEFAULT_CONFIG` 会被第一次 `load_config()` 灌满人设全文，
    #   之后测试里凡是拿默认配置当基准的断言都在跟一份"被污染过的"数据比。
    #   ★这类 bug 不报错、只让后来的断言莫名其妙（本项目最怕的一种）。
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            override = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = _deep_merge(cfg, override)
        except Exception:
            pass
    # API 段：**每个角色一份独立列表**（2026-10-02）。迁移 + 补齐 + 校验全在下面这个纯函数里。
    cfg["apis"], cfg["current_api"] = _normalize_apis(cfg)
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
    # 角色段归一化（2026-09-30，「设定卡」页依赖它）：
    # ① `persona` / `presets[*].persona` 一律**解析成人设全文**（见 `resolve_persona_text`）：
    #    默认配置与老 `config.json` 里存的是**素材路径**，这里就地换成文件原文；
    #    已经落盘成全文的（用户切换过一次之后）原样留着、**不再碰 md**。
    #    ★★两边**必须走同一个函数**：页面上「哪张预设选中」靠
    #      `presets[*].persona == role["persona"]` 两串**逐字相等**，一个路径一个全文
    #      ⇒ 一张都不选中（页面看着像"没选"，而且不报错）。
    #    ★拿到非字符串会静默「一张都不选中」，所以入口处一律 `str()` 兜一下。
    # ② `presets` 逐项清洗（必须有非空 name + 解析后非空的人设），**脏项直接丢**；
    # ③ 清洗完为空 ⇒ 兜底造一张卡，指向**当前人设**，否则「设定卡」页会一片空白 ——
    #    而空白页说不清「当前到底在用哪套设定」，比一张名字不好看的卡更难排查。
    # ★方向与权限白名单一致：宁可显示一张兜底卡，也不能让页面显示不出「正在用的东西」。
    roles = cfg.get("roles")
    if not isinstance(roles, dict):
        roles = {}
        cfg["roles"] = roles
    for _role_key, _role in roles.items():
        if not isinstance(_role, dict):
            continue
        _role["persona"] = resolve_persona_text(_role.get("persona"))
        _raw = _role.get("presets")
        _clean = []
        if isinstance(_raw, list):
            for _item in _raw:
                if not isinstance(_item, dict):
                    continue
                _name = str(_item.get("name", "")).strip()
                _text = resolve_persona_text(_item.get("persona"))
                if _name and _text:
                    _clean.append({"name": _name, "persona": _text})
        # ④ 把**内置预设**并回来（见 `_merge_presets` 的 docstring：配置文件里那份旧快照
        #    会把默认配置新加的内置预设整段盖掉，且不报错）。内置项也要先解析成全文，
        #    否则并回来的会是一条路径 —— 与 `role["persona"]` 比不相等 ⇒ 卡片显示"没选中"。
        _drole = DEFAULT_CONFIG.get("roles")
        _drole = _drole.get(_role_key) if isinstance(_drole, dict) else None
        _builtin = _drole.get("presets") if isinstance(_drole, dict) else None
        _builtin_clean = []
        for _bitem in _builtin or []:
            if not isinstance(_bitem, dict):
                continue
            _bname = str(_bitem.get("name", "")).strip()
            _btext = resolve_persona_text(_bitem.get("persona"))
            if _bname and _btext:
                _builtin_clean.append({"name": _bname, "persona": _btext})
        _clean = _merge_presets(_builtin_clean, _clean)
        if not _clean and _role["persona"]:
            _fallback_name = str(_role.get("name") or _role_key).strip()
            _clean = [{"name": f"{_fallback_name}（默认）", "persona": _role["persona"]}]
        _role["presets"] = _clean
    return cfg


def get_current_api(cfg: dict, role_key: str | None = None) -> dict | None:
    """返回**该角色**当前使用的 API（条目 dict），无则 None。

    ★`role_key` 省略 ⇒ 当前角色（`cfg["current_role"]`）。2026-10-02 起 API 是**每个角色
      一份独立列表**，所以「当前 API」这个问题必须回答清楚是**谁的** —— 这也是本函数唯一
      的取值入口（判据、界面、AI 调用都走它，别在别处直接翻 `cfg["apis"]`）。
    """
    name = current_api_name(cfg, role_key)
    for a in apis_for(cfg, role_key):
        if a.get("name") == name:
            return a
    return None


def is_first_launch() -> bool:
    """本机是否**初次**打开（= `config.json` 还不存在）。

    ★真值就是**文件在不在**：`load_config` 从不创建它，只有 `save_config` 才写。
    ★★调用时机：必须在**任何 `save_config` 之前**取（`main()` 一进来就取），
      否则「退出时存过一次盘」之后再问就永远是 False 了。
    ★它与「有没有配过 API」是**两件事**：老用户（有 config.json）换新版本、想要
      首启的模型安装引导时，不该再被弹一次；反过来，配置文件在、但没配 API 的人，
      由聊天区的灰字提示兜住（见 main.py）。
    """
    return not CONFIG_PATH.exists()


# 只在本次运行内有效、**不写进 config.json** 的字段（写了反而误导：读回来会被忽略）。
# ★★2026-09-29 起 `mute_mode` **已移出这张名单** —— 它改成落盘的偏好（用户要求记住开关状态）。
#   现在只剩 `patpat_mode` 一个纯运行时项；**新增纯运行时项必须同时登记到这里 + `load_config`
#   里压回 False**，否则用户会看到「改了却没生效」的假持久化。
_RUNTIME_ONLY_GENERAL = ("patpat_mode",)


def save_config(cfg: dict) -> None:
    """把配置落盘。★**原子写**（2026-10-01）—— 为什么必须这样写见下方长注释。"""
    data = dict(cfg)
    general = data.get("general")
    if isinstance(general, dict):
        data["general"] = {
            k: v for k, v in general.items() if k not in _RUNTIME_ONLY_GENERAL
        }
    text = json.dumps(data, ensure_ascii=False, indent=2)

    # ★★原子写（2026-10-01 第三批）：**先写同目录临时文件，写完整了再 `os.replace` 改名顶上。**
    #
    # 原来是一句 `CONFIG_PATH.write_text(...)` —— 那是**边写边覆盖原文件**：
    # 写到一半崩溃 / 断电 ⇒ `config.json` 被截断 ⇒ **人设全文、API key、权限白名单一起丢**。
    # 而人设自 2026-09-30 起存的是**全文本身**（不再是 `persona/*.md` 路径，见 docs/02 §25.17）
    # ⇒ 那份 `.md` 素材**救不回来** —— 这是**不可逆**的数据丢失。
    #
    # 三个「必须这样写」的点（改这个函数前先读）：
    #   ① 临时文件**必须与 config.json 同目录**（`dir=CONFIG_PATH.parent`）——
    #      `os.replace` 只在**同一分区**内才是原子的；跨盘会退化成「复制 + 删除」，
    #      等于白改。**别图省事改到 `%TEMP%` 去。**
    #   ② **必须 `os.fsync`** —— 否则「改名」这个元数据操作可能**先于**文件内容落盘，
    #      断电会得到一个「名字对、内容却是空的」config.json。
    #   ③ 失败要**清掉临时文件**再抛（不能留 `.tmp` 垃圾），且兜 `BaseException`
    #      （Ctrl+C / 进程被杀也要清）。
    #
    # 行为契约**没变**：成功时 `config.json` 里就是新内容；失败时照旧抛异常
    #   （调用方一行都不用改；2026-10-01 实测 22 处 = `gui.py` 17 + `main.py` 5）。
    #   唯一的区别是**失败时原文件完好无损**。
    fd, tmp = tempfile.mkstemp(
        prefix="config.", suffix=".tmp", dir=str(CONFIG_PATH.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)          # ★一步换名：要么全成、要么不变
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
