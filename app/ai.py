"""AI 对话（想）：封装 OpenAI 兼容接口，返回中文+日语双语回复。

任何一个 API 条目都可以自带「接口地址 + 模型名」，
因此同一个程序可以接 DeepSeek、通义、Kimi、智谱、本地 Ollama 等任意 OpenAI 兼容服务。
"""
import re
from pathlib import Path

from openai import OpenAI

# 默认端点统一在 config.py 里定义（DeepSeek：模型名 deepseek-flash）
from .config import DEFAULT_BASE_URL, DEFAULT_MODEL  # noqa: E402

# 兼容旧引用
BASE_URL = DEFAULT_BASE_URL
MODEL = DEFAULT_MODEL
MAX_TOKENS = 2048  # 必须同时覆盖「推理思考 token + 中文 + 日语」；320 太小，思考就吃光预算


def load_persona(path: Path) -> str:
    """读取人设文件内容作为 system prompt。文件不存在时返回空串。"""
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


# 双语标签与间隔符。persona 要求「日语在前、中文在后」，但解析必须两个顺序都能吃下
# （模型偶尔会按旧习惯把中文写在前面；写死顺序会静默把中文送进日语语音模型）。
_LABEL_ZH = r"(?:中文|汉语)"
_LABEL_JA = r"(?:日语|日文|日本語|Japanese|ja)"
_RE_ZH_LABEL = re.compile(rf"{_LABEL_ZH}\s*[:：]\s*")
_RE_JA_LABEL = re.compile(rf"{_LABEL_JA}\s*[:：]\s*", re.I)
# 段首（允许前导空白）的标签
_RE_ZH_FIRST = re.compile(rf"^{_LABEL_ZH}\s*[:：]\s*")
_RE_JA_FIRST = re.compile(rf"^{_LABEL_JA}\s*[:：]\s*", re.I)
# 「标签只打到一半」（流式刚好停在「日」「中文：」这种位置）——此时先当正文为空
_RE_JA_LABEL_PARTIAL = re.compile(rf"^\s*(?:日|{_LABEL_JA})?\s*[:：]?\s*$", re.I)
_RE_ZH_LABEL_PARTIAL = re.compile(rf"^\s*(?:中|{_LABEL_ZH})?\s*[:：]?\s*$")
# 日语段与中文段的分界：间隔符，或（模型漏写间隔符时的）**下一段的标签**。
# 分界标志随「谁在前」而不同：日语在前的回复以「中文：」开头下一段，反之亦然。
_RE_BOUNDARY_JA_FIRST = re.compile(rf"\|\|\||{_LABEL_ZH}\s*[:：]")
_RE_BOUNDARY_ZH_FIRST = re.compile(rf"\|\|\||{_LABEL_JA}\s*[:：]", re.I)
_KANA_RE = re.compile(r"[\u3040-\u30ff]")


def _has_kana(text: str) -> bool:
    """含平假名 / 片假名 → 判定为日语（没有标签时用来兜底判定语言）。"""
    return bool(_KANA_RE.search(text or ""))


def _strip_label(text: str, which: str) -> str:
    """去掉开头的「中文：」/「日语：」标签（正则全量版，用于已完整的文本）。"""
    pat = _RE_ZH_LABEL if which == "zh" else _RE_JA_LABEL
    return pat.sub("", (text or "").strip(), count=1).strip()


def _strip_prefix_label(text: str, which: str) -> str:
    """流式版：去掉段首标签；**标签还没打完时返回空串**（别把「日」当成正文）。

    用 startswith 语义而不是 `re.sub(...count=1)`：流式每一帧都会重算，
    必须在「标签只到一半」时稳住不动，否则标签的首字会被当成台词送到 TTS。
    """
    s = (text or "").lstrip()
    pat = _RE_ZH_FIRST if which == "zh" else _RE_JA_FIRST
    m = pat.match(s)
    if m:
        return s[m.end():]
    partial = _RE_ZH_LABEL_PARTIAL if which == "zh" else _RE_JA_LABEL_PARTIAL
    if partial.match(s):
        return ""
    return s


def _split_zh_ja_pair(left: str, right: str) -> tuple[str, str]:
    """把间隔符两侧判成 (中文, 日语)。

    先看「哪一侧带标签」；两侧都没标签时用「含不含假名」兜底
    （日语必然含假名，中文基本不含）—— 这样"日语在前"和"中文在前"都吃得下。
    """
    left = (left or "").strip()
    right = (right or "").strip()
    if _RE_ZH_FIRST.match(left):
        return _strip_label(left, "zh"), _strip_label(right, "ja")
    if _RE_JA_FIRST.match(left):
        return _strip_label(right, "zh"), _strip_label(left, "ja")
    if _has_kana(right) and not _has_kana(left):
        return left, right
    if _has_kana(left) and not _has_kana(right):
        return right, left
    return left, right  # 实在分不出来：按旧约定「中文在前」处理


def _parse_zh_ja(text: str) -> tuple[str, str]:
    """从 AI 回复中提取中文和日语。

    优先按间隔符 `|||` 分割，取日语那一侧交给 TTS（确保 TTS 只用纯日语合成，
    避免把中日混合文本送进语音模型产生"胡言乱语"）。**顺序不固定**：
    persona 现在是「日语：xxx|||中文：yyy」，但旧格式「中文：xxx|||日语：yyy」
    以及漏写间隔符的退化情形都要能解析出来。

    仍失败则日语置空（不合成，宁缺毋滥），由调用方用中文兜底。
    """
    text = text or ""
    if "|||" in text:
        left, right = text.split("|||", 1)
        zh, ja = _split_zh_ja_pair(left, right)
        if zh and ja:
            return zh, ja
    # 兜底：没有间隔符（旧格式，或模型漏写）——按标签匹配，两个顺序都试
    m = re.search(rf"{_LABEL_JA}\s*[:：]\s*(.*?)\s*{_LABEL_ZH}\s*[:：]\s*(.*)", text, re.S | re.I)
    if m and m.group(1).strip() and m.group(2).strip():
        return m.group(2).strip(), m.group(1).strip()
    m = re.search(rf"{_LABEL_ZH}\s*[:：]\s*(.*?)\s*{_LABEL_JA}\s*[:：]\s*(.*)", text, re.S | re.I)
    if m and m.group(1).strip() and m.group(2).strip():
        return m.group(1).strip(), m.group(2).strip()
    # 解析失败。若通篇没有中文标签却满是假名，那其实是**只有日语一段**
    # （模型漏写了中文）—— 别把它当中文返回，否则界面会把日语显示出来。
    if not _RE_ZH_LABEL.search(text) and _has_kana(text):
        return "", _strip_label(text, "ja")
    # 否则整体当中文，日语置空（避免把中日混合文本送进语音模型）
    return _strip_label(text, "zh"), ""


def split_sentences(text: str) -> list[str]:
    """按句末标点切句（**保留标点**、丢掉空句）。

    保留标点很重要：TTS 靠标点决定停顿和语调，去掉会让句子读起来一截一截的。
    （当前回复走「整段合成」不再需要它；保留为通用文本工具，供日后按需使用。）
    """
    text = (text or "").strip()
    if not text:
        return []
    return [s.strip() for s in re.split(r"(?<=[。！？!?…])", text) if s.strip()]


def detect_order(raw: str) -> str:
    """看回复开头判定「谁在前」（`"ja_first"` / `"zh_first"`），默认日语在前。

    只在开头认一次标签：中途出现的「中文：」字样不算数（正文里可能正好有这仨字）。
    """
    if _RE_ZH_FIRST.match(raw.lstrip()):
        return "zh_first"
    return "ja_first"


def _stream_regions(raw: str, order: str = "ja_first") -> tuple[str, str, bool]:
    """把「当前已收到的文本」切成 (日语段, 中文段, 是否已到分界)。

    流式每一步都会重算，所以必须容忍半截文本：标签只打了一半时对应段返回空串
    （宁可先不显示，也不要把标签的半个字当台词）；间隔符只到一半时 `rstrip("|")`。
    """
    pat = _RE_BOUNDARY_JA_FIRST if order == "ja_first" else _RE_BOUNDARY_ZH_FIRST
    m = pat.search(raw)
    if m is None:
        head, tail, closed = raw, "", False
    else:
        head, tail, closed = raw[:m.start()], raw[m.end():], True
    if order == "zh_first":
        # 中文在前的回复：head 是中文段、tail 是日语段
        zh = _strip_prefix_label(head, "zh")
        ja = _strip_prefix_label(tail, "ja")
    else:
        ja = _strip_prefix_label(head, "ja")
        zh = _strip_prefix_label(tail, "zh")
        if not _has_kana(ja) and _has_kana(zh) and not _RE_JA_FIRST.match(head.lstrip()):
            # 没有任何标签时按假名兜底：日语那侧连一个假名都没有、另一侧有 → 其实反了
            ja, zh = zh, ja
    if not closed:
        # 间隔符可能只收到一半（`|` / `||`），别把它显示出来
        ja, zh = ja.rstrip("|"), zh.rstrip("|")
    return ja, zh, closed


def resolve_endpoint(api) -> tuple[str, str, str]:
    """把 API 配置解析成 (api_key, base_url, model)。

    api 既可以是 config 里的条目 dict（含 api_key/base_url/model），
    也可以直接是字符串形式的 api_key（向后兼容旧调用）。
    未填 base_url/model 时回退到 DeepSeek 默认值。
    """
    if isinstance(api, dict):
        key = str(api.get("api_key", "") or "")
        base = str(api.get("base_url", "") or "").strip() or DEFAULT_BASE_URL
        model = str(api.get("model", "") or "").strip() or DEFAULT_MODEL
        return key, base, model
    return str(api or ""), DEFAULT_BASE_URL, DEFAULT_MODEL


def _thinking_disabled_kwargs(base_url: str) -> dict:
    """对 DeepSeek 端点显式关闭「思考模式」。

    DeepSeek 新模型（如 deepseek-flash / V4-Flash）默认开启思考：思考 token 计入
    max_tokens 输出预算，会把预算吃光 → 正文为空、或日语（排在末尾）被截断，
    表现为「聊天界面中文完整、但克隆语音只念一半」甚至「AI 没回复」。
    角色扮演闲聊并不需要思考，关闭后响应更快、更省 token。

    其它 OpenAI 兼容服务（Kimi/通义/Ollama 等）不认该参数，故只对 deepseek 端点启用。
    """
    if "deepseek" in (base_url or "").lower():
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def _usage_kwargs(base_url: str) -> dict:
    """流式请求里**要求把用量也返回**（只对 DeepSeek 端点加）。

    非流式响应本来就带 `usage`；`stream=True` 时 OpenAI 协议**默认不发** —— 必须显式要
    `stream_options.include_usage`（此时最后一帧 `choices` 为空、只带 `usage`）。
    ★它只改变**响应的形状**，不延长生成、也不额外耗 token（用户 2026-09-21 的口径：
    对 token 消耗没影响才做）。其它 OpenAI 兼容服务不一定认这个参数，故与
    `_thinking_disabled_kwargs` 同一判据，只对 deepseek 端点启用。
    """
    if "deepseek" in (base_url or "").lower():
        return {"stream_options": {"include_usage": True}}
    return {}


# ---- 用量出口（二十三改）----
# **默认 None = 完全零副作用**：冒烟测试与其它调用方原样不受影响。
# 主程序（`main.py`）把它接到 `app.stats.record_tokens`，「今日 Token 用量」就自己累计起来了。
# ★读的是**本来就会返回**的字段 ⇒ 不发新请求、不额外耗 token。
_USAGE_SINK = None


def set_usage_sink(fn):
    """设置「一次对话用掉多少 token」的出口（参数 = `int` total_tokens）；`None` = 关掉。"""
    global _USAGE_SINK
    _USAGE_SINK = fn


def _report_usage(total):
    """把一次请求的 `usage.total_tokens` 交出去。★出口出错绝不许把对话带崩。"""
    if _USAGE_SINK is None or total is None:
        return
    try:
        n = int(total)
    except (TypeError, ValueError):
        return
    if n <= 0:
        return
    try:
        _USAGE_SINK(n)
    except Exception:  # noqa: BLE001
        pass


def _usage_of(resp):
    """从响应（或流的某一帧）里取 `usage.total_tokens`；没有 ⇒ `None`。"""
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    return getattr(usage, "total_tokens", None)


_ACTION_RESULT_HINT = (
    "[系统提示] 系统返回的执行结果如下：{result}\n"
    "请据此自然地告知用户（保持你的人设、口癖和语气）。"
    "注意：以「[已排程]」开头表示操作尚未执行、正在倒计时等待，"
    "要提醒用户可以说「取消」来中止；以「[权限拦截]」开头表示操作被安全设置"
    "拒绝、没有执行，请如实说明原因，不要假装已经完成。"
)

# 静音模式（`zh_only=True`）：本轮只要中文。
#
# 放在**最后一条 system**（紧挨用户消息）：人设要求双语、格式规则也写双语，而历史里
# 全是双语样例 —— 靠「最近的一条指令」才压得住。用词要显式否定（不要日语 / 不要标签 /
# 不要间隔符），只说「用中文」模型仍可能按人设补一段日语。
#
# ★ 还必须同时给**篇幅**：平时中文是「日语那一句的翻译」，长度被日语**锚住**；
#   一旦只说「只输出中文」，锚就没了，模型会自由展开。实测（真实 DeepSeek，
#   6 个用例 × 多轮，`tools/_mute_len_probe*.py` 跑完即删）：
#
#     | 提示词 | 平均字数 | 最大 |
#     |---|---|---|
#     | 平时（双语，只看中文那半） | 21.5 | 44 |
#     | 旧提示（只说「只输出中文」） | **53.5** | **105**（约 2.5 倍）|
#     | 本提示 | **22.4** | **38** |
#
#   用户的要求就是「控制在与平时相当」。所以这里明写「先在心里按平时的格式想好、
#   只输出中文那一半」+ 一个字数区间。**字数区间只属于这个模式**，不写进人设 ——
#   人设必须保持「不限长」（`smoke_api` 有反向断言钉着），否则会静默把语速拖慢。
_MUTE_MODE_HINT = (
    "[静音模式已开启] 本轮**只输出中文**：不要输出日语，不要写「日语：」「中文：」"
    "这类标签，也不要用 ||| 间隔符。\n"
    "写法：先在心里像平时一样用日语组织好这一句，然后**只输出它的中文翻译**。"
    "平时中文通常 20 字上下、最多 40 字 —— 保持这个篇幅，"
    "不要因为省掉日语就把内容展开、补充解释或罗列。"
)


def _build_messages(persona: str, history: list[dict], user_text: str,
                    action_result: str | None = None, zh_only: bool = False) -> list[dict]:
    """组装 messages（流式 / 非流式共用，避免两条路径的提示词走偏）。

    注意：调用方（`main.py::_ask_ai`）**已经把本轮用户消息塞进 `history`** 了
    （历史要留给下一轮），所以这里要判断一次、不要重复追加 ——
    否则模型会看到同一句话出现两遍，白烧 token 还可能带偏语气。

    `zh_only=True`（静音模式）会在用户消息**之前**追加一条 system，要求本轮只出中文。
    """
    hist = list(history)
    already = bool(hist) and hist[-1].get("role") == "user" and hist[-1].get("content") == user_text
    messages = [{"role": "system", "content": persona}]
    messages += hist
    if action_result:
        messages.append({"role": "system",
                         "content": _ACTION_RESULT_HINT.format(result=action_result)})
    if zh_only:
        messages.append({"role": "system", "content": _MUTE_MODE_HINT})
    if not already:
        messages.append({"role": "user", "content": user_text})
    return messages


def chat_once(api, persona: str, history: list[dict], user_text: str,
              action_result: str | None = None, zh_only: bool = False) -> dict:
    """单次对话，返回 {"zh": 中文, "ja": 日语}。

    api 可以是 API 配置 dict（推荐，可指定接口地址与模型）或 api_key 字符串。
    解析失败（缺少日语）会自动附加格式要求重试，确保每次都有双语；重试仍失败则日语置空，
    由调用方（main.py）用中文兜底合成，保证一定有声音。

    `zh_only=True`（静音模式）：只要中文，`ja` 恒为空串 —— 且**不因「缺日语」重试**
    （那会白白多烧两次 API）。见 `_MUTE_MODE_HINT`。

    ⚠️ 这是**非流式**路径：要等整段生成完才返回。日常走 `chat_stream`（见下），
    本函数作为它的**回退**保留（带"被截断 / 缺日语"的重试保障）。
    """
    api_key, base_url, model = resolve_endpoint(api)
    client = OpenAI(api_key=api_key, base_url=base_url)
    extra = _thinking_disabled_kwargs(base_url)
    messages = _build_messages(persona, history, user_text, action_result, zh_only=zh_only)

    zh, ja = "", ""
    content = ""
    for attempt in range(3):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5,
            max_tokens=MAX_TOKENS,
            **extra,
        )
        choice = resp.choices[0]
        content = choice.message.content or ""
        finish = getattr(choice, "finish_reason", None)
        # ★每一次尝试都记一次用量：重试的失败轮**也真的烧了 token**，不记就会低估。
        _report_usage(_usage_of(resp))
        if zh_only:
            # 静音模式：只要中文。**绝不能**落到下面「缺日语」的重试分支 ——
            # 那会为了一个我们根本不需要的日语版本白烧两次 API（静音模式本来就是为了快）。
            if finish == "length":
                messages.append({
                    "role": "user",
                    "content": "注意：你上一条回复超出了长度限制、被截断了。请更简短地用中文重新完整回答。",
                })
                continue
            # 万一模型仍按人设输出双语，这里也顺手切一刀，只留中文
            zh, _ja = _parse_zh_ja(content)
            zh = zh or content.strip()
            if zh:
                return {"zh": zh, "ja": ""}
            continue
        zh, ja = _parse_zh_ja(content)
        # 被长度上限截断（推理模型的「思考 token」也计入 max_tokens）：
        # 排在末尾的那一段（现在是中文）会最先被砍 → 表现为「日语完整、中文缺一半」。
        # 此时不能直接用，要求精简后重试。
        if finish == "length":
            messages.append({
                "role": "user",
                "content": (
                    "注意：你上一条回复超出了长度限制、被截断了（排在后面的中文往往会缺失或只剩一半）。"
                    "请把日语和中文都压缩得更简短（各自控制在 60 字以内），"
                    "并按格式完整输出：日语：<简短日语>|||中文：<简短中文>"
                ),
            })
            continue
        if zh and ja:
            return {"zh": zh, "ja": ja}
        # 解析失败（缺少日语/间隔符）：附加格式要求，重试
        messages.append({
            "role": "user",
            "content": (
                "注意：你上一次的回复缺少日语版本或间隔符。请严格按以下格式重新完整输出，"
                "务必同时包含日语和中文两个版本，**日语在前**，中间用三个竖线 ||| 分隔："
                "日语：<日语回复>|||中文：<中文回复>"
            ),
        })
    # 重试仍失败：日语置空，交给调用方用中文兜底合成（保证有声音）
    return {"zh": zh or content.strip(), "ja": ""}


# ========== 流式对话（回应流水线的第一段） ==========


def chat_stream(api, persona: str, history: list[dict], user_text: str,
                action_result: str | None = None, on_event=None,
                zh_only: bool = False) -> dict:
    """**流式**对话：边生成边把结果交出去，返回 {"zh","ja"}（与 chat_once 一致）。

    人设要求「日语在前」，所以**日语段会先吐完** —— 分界符一出现日语就完整了，
    调用方可以立刻把它**整段**送去合成（与后面「中文段」的生成**并行**）：
    既拿到无缝的整段语音，又不必等中文写完才开始合成。

    `on_event(kind, payload)`（从**生成线程**调用，实现方要注意跨线程安全）：

    | kind | payload | 含义 |
    |---|---|---|
    | `"ja"` | `str` | 日语段**整段**已完整（分界符出现 / 流结束）→ 立刻送去合成（**只发一次**）|
    | `"done"` | `{"zh","ja"}` | 整段已完整（权威结果，用它写聊天记录、放行播放）|

    为什么**不再**「按句」回调（上一版的教训）：逐句合成会一句一次 HTTP + 一次
    `play_wav`，而 `play_wav` 每次都要重开音频流并补 80ms 前导静音 —— 句与句之间能听出
    明显停顿。整段一次合成由服务端按行拼接（`api.py: text.split("\\n")`），是**无缝**的；
    代价只是「要等整段日语吐完」，而日语本来就在最前面，等不了多久。

    `zh_only=True`（静音模式）：提示词要求本轮只出中文，所以通常**不会**有 `"ja"` 事件 ——
    没有间隔符 → 整段被当成中文；而中文不含假名，`pump()` 的假名判据也不会把它误当日语
    送去合成。返回的 `ja` 同样是空串（调用方据此不合成语音）。

    返回值比 `chat_once` 多一个 `"truncated"`：为 `True` 表示被 `max_tokens` 截断
    （此时**不会**发 `done`）—— 调用方据此决定要不要在"尚未出声"的前提下回退重试。
    """
    api_key, base_url, model = resolve_endpoint(api)
    client = OpenAI(api_key=api_key, base_url=base_url)
    extra = _thinking_disabled_kwargs(base_url)
    # ★流式必须额外要 `include_usage`，否则整条流一帧 `usage` 都没有（见 `_usage_kwargs`）。
    extra.update(_usage_kwargs(base_url))
    messages = _build_messages(persona, history, user_text, action_result, zh_only=zh_only)

    def emit(kind, payload=None):
        if on_event is None:
            return
        try:
            on_event(kind, payload)
        except Exception:  # noqa: BLE001
            # 回调（往 TTS 流水线喂句子 / 发跨线程信号）出错不能把生成线程带崩，
            # 否则整条回复都会丢，用户看到的是"AI 没回复"。
            pass

    raw = ""
    ja_sent = False    # 日语整段是否已送出（只送一次）

    def pump(final: bool = False):
        nonlocal ja_sent
        if ja_sent:
            return
        order = detect_order(raw)
        ja, _zh, closed = _stream_regions(raw, order)
        # 日语段「结束」的时刻：日语在前 → 分界符一出现就完整；**或者**整条流已经吐完
        # （模型漏写间隔符时，日语段只能到收尾才认定完整）；中文在前 → 只能等收尾。
        ja_ended = final or (order == "ja_first" and closed)
        # 别把中文当日语念：整段没有一个假名、段首也没有「日语：」标签 → 不认为是日语
        # （此时宁可不出声，由调用方改用中文兜底合成）。
        if ja_ended and ja and (_has_kana(ja) or bool(_RE_JA_FIRST.match(raw.lstrip()))):
            ja_sent = True
            emit("ja", ja)

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.5,
        max_tokens=MAX_TOKENS,
        stream=True,
        **extra,
    )
    finish = None
    usage_total = None
    for chunk in stream:
        # 带 `include_usage` 时，最后一帧 `choices` 是空的、只挂 `usage`；
        # ★先取用量再取 choice —— 那一帧进不了下面，漏取就整轮都不记。
        got = _usage_of(chunk)
        if got is not None:
            usage_total = got
        try:
            choice = chunk.choices[0]
            delta = choice.delta
        except (AttributeError, IndexError):
            continue
        piece = getattr(delta, "content", None)
        if piece:
            raw += piece
            pump()
        fr = getattr(choice, "finish_reason", None)
        if fr:
            finish = fr
    _report_usage(usage_total)
    pump(final=True)
    # 分界明确时，以「流式分段」的结果为准：它已经去掉了标签、判过了顺序，
    # 而 `_parse_zh_ja` 在「只有日语一段」（`日语：xxx|||` 后面没东西）时
    # 会把整串当中文返回 —— 那会让界面显示出日语。
    ja_stream, zh_stream, closed = _stream_regions(raw, detect_order(raw))
    zh, ja = _parse_zh_ja(raw)
    if closed:
        zh, ja = zh_stream, ja_stream
    if finish == "length":
        # 被长度上限截断：**不**发 done，把决定权交给调用方 ——
        # 它知道此刻有没有已经出声，只有"还没出声"才值得回退重试（否则同一句会念两遍）。
        return {"zh": zh, "ja": ja, "truncated": True}
    emit("done", {"zh": zh, "ja": ja})
    return {"zh": zh, "ja": ja, "truncated": False}
