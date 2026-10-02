"""各家大模型服务的**接口地址**与**常用模型**清单。

「添加 API / 编辑 API」弹窗里那两个下拉框（接口地址 / 模型名）的数据源 ——
用户从「接口地址」挑一家，模型下拉的候选项就跟着换成这一家的（联动实现在
`app/gui.py::ApiFormDialog._refill_models`）。

★★两条硬口径（2026-10-02 用户拍板，**改这个表之前先读**）：

1. **每家只放最新 / 主力**，3~5 个 —— 不把官网模型全抄一遍（下拉要短、好选）。
   用户原话：「现在暂时先加入 deepseek、千问、豆包、GLM、Kimi、Openai 这几类」。

2. ★★**这不是白名单**：两个下拉框都**可编辑**，用户照样能手输别的地址 / 模型名
   （豆包方舟的「接入点 ID」`ep-xxxx`、第三方中转站、公司内网地址全靠这条路）。
   所以下面几个查询函数**查不到一律返回空**（由调用方保持原样），
   **绝不要**把它们写成校验 / 拦截。细则见 `docs/02` §33.12、`TECH-GOTCHAS` §28.1。

- 每个 `base_url` 都是各家**官方直连**的 OpenAI 兼容端点，写法照抄官方文档
  （有的带 `/v1`、GLM 带 `/api/paas/v4`、方舟带 `/api/v3`，**不要**自作主张补齐或删掉）。
"""

# 「接口地址」下拉每一项的显示形式：`服务商名 · 地址`
# ★中间那个分隔符是**唯一的还原锚点**（`base_url_of` 按它把显示文本剥成纯地址）——
#   改它等于改协议，别随手动。
SEP = " · "

# 供应商表。字段：
#   name     —— 显示名（用户口径里的叫法，中英混排的那几个照抄）
#   base_url —— 官方直连地址（OpenAI 兼容）
#   models   —— 该家**最新 / 主力**模型的 `model` 参数值，**第一个 = 切到这家时的默认**
PROVIDERS = (
    {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        # deepseek-flash = DeepSeek-V4.1-Flash（2026-09 GA，官方现役默认，也是本项目的
        # DEFAULT_MODEL）；deepseek-v4-pro = V4-Pro-0813（贵约 3 倍，按需选）。
        # ★旧名 deepseek-chat / deepseek-reasoner 已于 2026-07-24 彻底下线，**别再放回来**
        #   （放进去 = 用户一点就报错）。
        "models": ("deepseek-flash", "deepseek-v4-pro"),
    },
    {
        "name": "千问 Qwen",
        # 阿里百炼（DashScope）的 OpenAI 兼容端点。★末尾的 `/v1` 是必须的。
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ("qwen3.8-max", "qwen3.8-flash", "qwen3.7-max", "qwen-plus", "qwen-turbo"),
    },
    {
        "name": "豆包 Doubao",
        # 火山方舟。★注意：方舟的 model 既能填下面的**模型 ID**，也能填用户在控制台
        #   自建的**接入点 ID**（形如 `ep-2026xxxx-xxxxx`，人人不同）—— 后者只能手输，
        #   这正是「下拉必须可编辑」的主要理由。
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": (
            "doubao-seed-2-1-pro-260628",
            "doubao-seed-2-1-turbo-260628",
            "doubao-seed-1.6",
            "doubao-seed-1.6-thinking",
        ),
    },
    {
        "name": "GLM",
        # 智谱开放平台。国际版是 https://api.z.ai/api/paas/v4（没进表：用户口径里没提）。
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ("glm-5.3", "glm-5.3-flash", "glm-5.1", "glm-4.7", "glm-4.6"),
    },
    {
        "name": "Kimi",
        # 月之暗面（Moonshot）中国站。全球站是 https://api.moonshot.ai/v1，**两站 key 不通用**。
        "base_url": "https://api.moonshot.cn/v1",
        "models": ("kimi-k2.5", "kimi-k2-0905-preview", "moonshot-v1-128k"),
    },
    {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ("gpt-5.2", "gpt-5.1", "gpt-5-mini", "gpt-4.1", "gpt-4o"),
    },
)


def _norm(url) -> str:
    """比地址用的归一形：去空白、去末尾 `/`、统一小写。

    （`https://API.DeepSeek.com/` 与 `https://api.deepseek.com` 算同一家 ——
    用户手输时带不带尾斜杠、大小写随便。）
    """
    return str(url or "").strip().rstrip("/").lower()


def label(provider) -> str:
    """一家供应商在下拉里的显示文本。"""
    return f"{provider['name']}{SEP}{provider['base_url']}"


def address_items() -> list:
    """「接口地址」下拉的候选项：`[(显示文本, 纯地址), …]`。

    ★**纯地址必须挂在 userData 上**：显示文本是 `DeepSeek · https://…` 这种给人看的，
      而 `config` 里的 `base_url` 要的是**能直接拼 `/chat/completions` 的纯地址**
      （`app/ai.py::resolve_endpoint`）。`ApiFormDialog.get()` 优先取 userData 就是为了
      这一条 —— 少了它，用户从下拉一选就会把带前缀的文本存进配置，**请求全挂**。
    """
    return [(label(p), p["base_url"]) for p in PROVIDERS]


def base_url_of(text) -> str:
    """把下拉显示的一行文本还原成**纯地址**。

    - 带分隔符（= 从列表里选的显示文本）⇒ 取后半段；
    - 不带（= 用户手输的地址原文）⇒ 原样返回（去空白）。
    """
    t = str(text or "").strip()
    if SEP in t:
        return t.split(SEP, 1)[1].strip()
    return t


def label_for(base_url) -> str:
    """回显用：地址在表里 ⇒ `名 · 地址`；不在表里（自定义）⇒ 原样返回地址。

    （编辑一条老条目时要按存的**纯地址**反查回下拉的显示文本，否则下拉看着是空的。）
    """
    key = _norm(base_url)
    for p in PROVIDERS:
        if _norm(p["base_url"]) == key:
            return label(p)
    return str(base_url or "").strip()


def models_for(base_url) -> list:
    """按地址取这一家的模型清单。

    ★**不在表里（自定义地址）⇒ 返回空列表** —— 调用方拿到空列表必须**什么都不做**，
      把用户已经填好的模型名原样留着（别清空、别替换）。见模块抬头第 2 条。
    """
    key = _norm(base_url)
    for p in PROVIDERS:
        if _norm(p["base_url"]) == key:
            return list(p["models"])
    return []


def default_model_for(base_url) -> str:
    """这一家的默认模型 = 清单里第一个；查不到 ⇒ 空串（调用方自便）。"""
    models = models_for(base_url)
    return models[0] if models else ""
