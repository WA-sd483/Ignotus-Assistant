"""冒烟测试：多 API 管理（添加/编辑/切换）+ 每 API 可配接口地址与模型 + 配置归一化。

跑法（在项目根目录）：
    .venv\\Scripts\\python.exe tests\\smoke_api.py

全部在 offscreen 平台运行，不弹窗；配置读写重定向到临时文件，不动项目里的 config.json。
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:  # 控制台重定向时保证中文输出可读
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

fails = []
total = [0]


def check(name, ok, detail=""):
    total[0] += 1
    print(("OK   " if ok else "FAIL ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


# ========== 1. 配置层：apis 归一化 ==========
print("== 1. 配置层 apis 归一化 ==")
import app.config as cfgmod  # noqa: E402

tmp_dir = Path(tempfile.mkdtemp(prefix="ignotus_api_smoke_"))
tmp_cfg = tmp_dir / "config.json"
cfgmod.CONFIG_PATH = tmp_cfg

check("默认模型名为 deepseek-flash", cfgmod.DEFAULT_MODEL == "deepseek-flash", cfgmod.DEFAULT_MODEL)

cfg = cfgmod.load_config()
check("默认 apis 为空列表", cfg["apis"] == [], str(cfg["apis"]))
check("默认 current_api 为空串", cfg["current_api"] == "", repr(cfg["current_api"]))

# 旧配置（只有 name + api_key）应自动补全 base_url / model
tmp_cfg.write_text(json.dumps({
    "apis": [
        {"name": "旧配置", "api_key": "sk-old"},
        {"name": "自定义", "api_key": "sk-custom",
         "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
        {"name": "  ", "api_key": "sk-noname"},      # 空名应被丢弃
        "not-a-dict",                                 # 非 dict 应被丢弃
    ],
    "current_api": "旧配置",
}), encoding="utf-8")
cfg = cfgmod.load_config()
check("无名/非 dict 条目被丢弃", [a["name"] for a in cfg["apis"]] == ["旧配置", "自定义"],
      str(cfg["apis"]))
check("缺 base_url 自动补默认值", cfg["apis"][0]["base_url"] == cfgmod.DEFAULT_BASE_URL,
      cfg["apis"][0]["base_url"])
check("缺 model 自动补默认值", cfg["apis"][0]["model"] == "deepseek-flash",
      cfg["apis"][0]["model"])
check("已有 base_url/model 不被覆盖",
      cfg["apis"][1]["base_url"] == "https://api.moonshot.cn/v1"
      and cfg["apis"][1]["model"] == "moonshot-v1-8k")

# 迁移：旧版单 key 结构
tmp_cfg.write_text(json.dumps({"api_key": "sk-legacy"}), encoding="utf-8")
cfg = cfgmod.load_config()
check("旧版 api_key 迁移为 apis 列表",
      len(cfg["apis"]) == 1 and cfg["apis"][0]["api_key"] == "sk-legacy",
      str(cfg["apis"]))
check("迁移条目也补全 model", cfg["apis"][0]["model"] == "deepseek-flash")

# current_api 无效时回落到第一个
tmp_cfg.write_text(json.dumps({
    "apis": [{"name": "A", "api_key": "sk-a"}, {"name": "B", "api_key": "sk-b"}],
    "current_api": "不存在",
}), encoding="utf-8")
cfg = cfgmod.load_config()
check("current_api 无效时回落到第一个", cfg["current_api"] == "A", cfg["current_api"])


# ========== 2. ai.resolve_endpoint / 模型名 ==========
print("== 2. ai 端点解析 ==")
from app import ai  # noqa: E402

check("ai.DEFAULT_MODEL == deepseek-flash", ai.DEFAULT_MODEL == "deepseek-flash", ai.DEFAULT_MODEL)
check("ai.MODEL 兼容别名指向新模型", ai.MODEL == "deepseek-flash", ai.MODEL)

k, b, m = ai.resolve_endpoint({"name": "X", "api_key": "sk-1",
                               "base_url": "https://example.com/v1", "model": "my-model"})
check("dict 条目解析正确", (k, b, m) == ("sk-1", "https://example.com/v1", "my-model"),
      str((k, b, m)))

k, b, m = ai.resolve_endpoint({"name": "X", "api_key": "sk-2"})
check("缺 base_url/model 回退默认",
      (k, b, m) == ("sk-2", ai.DEFAULT_BASE_URL, ai.DEFAULT_MODEL), str((k, b, m)))

k, b, m = ai.resolve_endpoint("sk-plain")
check("字符串 api_key 向后兼容",
      (k, b, m) == ("sk-plain", ai.DEFAULT_BASE_URL, ai.DEFAULT_MODEL), str((k, b, m)))

# 输出预算必须同时覆盖「思考 token + 中文 + 日语」：太小会导致日语（排末尾）被截断
check("MAX_TOKENS 足够覆盖思考+双语（≥1024）", ai.MAX_TOKENS >= 1024, str(ai.MAX_TOKENS))
check("DeepSeek 端点关闭思考模式（避免思考吃光输出预算）",
      ai._thinking_disabled_kwargs("https://api.deepseek.com")
      == {"extra_body": {"thinking": {"type": "disabled"}}},
      str(ai._thinking_disabled_kwargs("https://api.deepseek.com")))
check("非 DeepSeek 端点不注入 thinking 参数（保持第三方兼容）",
      ai._thinking_disabled_kwargs("https://api.moonshot.cn/v1") == {},
      str(ai._thinking_disabled_kwargs("https://api.moonshot.cn/v1")))


# ========== 2b. 双语解析（中文 + 间隔符 ||| + 日语） ==========
print("== 2b. 双语解析 ===")

zh, ja = ai._parse_zh_ja("中文：老师早上好|||日语：先生、おはようございます")
check("标准格式按 ||| 拆分出中日双语",
      (zh, ja) == ("老师早上好", "先生、おはようございます"), str((zh, ja)))

zh, ja = ai._parse_zh_ja("中文：你好|||日语：こんにちは")
check("去掉「中文：/日语：」前缀", (zh, ja) == ("你好", "こんにちは"), str((zh, ja)))

zh, ja = ai._parse_zh_ja("中文：你好 日语：こんにちは")
check("兼容旧的无间隔符格式", (zh, ja) == ("你好", "こんにちは"), str((zh, ja)))

zh, ja = ai._parse_zh_ja("只有一句中文")
check("无日语时整体当中文、日语留空（宁缺毋滥，不把混排送进 TTS）",
      (zh, ja) == ("只有一句中文", ""), str((zh, ja)))

# ---- chat_once 全链路（用假 OpenAI 客户端，不联网）----
_FAKE_CONTENT = "中文：早上好|||日语：おはようございます"


class _FakeMsg:
    def __init__(self, c):
        self.content = c


class _FakeChoice:
    def __init__(self, c):
        self.message = _FakeMsg(c)


class _FakeResp:
    def __init__(self, c):
        self.choices = [_FakeChoice(c)]


class _FakeCompletions:
    def __init__(self, c, sink):
        self._c, self._sink = c, sink

    def create(self, **kw):
        self._sink.append(kw)
        return _FakeResp(self._c)


class _FakeChat:
    def __init__(self, c, sink):
        self.completions = _FakeCompletions(c, sink)


class _FakeClient:
    def __init__(self, c, sink):
        self.chat = _FakeChat(c, sink)


_client_kw = {}
_create_kw = []


def _fake_openai(**kw):
    _client_kw.update(kw)
    return _FakeClient(_FAKE_CONTENT, _create_kw)


_orig_openai = ai.OpenAI
ai.OpenAI = _fake_openai
try:
    out = ai.chat_once(
        {"api_key": "sk-x", "base_url": "https://example.com/v1", "model": "my-model"},
        "persona", [], "你好",
    )
finally:
    ai.OpenAI = _orig_openai

check("chat_once 返回中文+日语（界面出中文、日语拿去合成）",
      out == {"zh": "早上好", "ja": "おはようございます"}, str(out))
check("chat_once 把条目 base_url 传给客户端",
      _client_kw.get("base_url") == "https://example.com/v1", str(_client_kw))
check("chat_once 把条目 model 传给请求",
      bool(_create_kw) and _create_kw[0].get("model") == "my-model", str(_create_kw[:1]))

# DeepSeek 端点：请求必须带 thinking disabled
_create_kw.clear()
_orig_openai2 = ai.OpenAI
ai.OpenAI = _fake_openai
try:
    ai.chat_once({"api_key": "sk-x", "base_url": "https://api.deepseek.com",
                  "model": "deepseek-flash"}, "p", [], "hi")
finally:
    ai.OpenAI = _orig_openai2
check("chat_once 对 DeepSeek 端点关闭思考（extra_body.thinking.disabled）",
      bool(_create_kw) and _create_kw[0].get("extra_body") == {"thinking": {"type": "disabled"}},
      str(_create_kw[:1]))

# ---- 静音模式（zh_only）：只要中文，且**绝不因「缺日语」重试** ----
# 提示词层：人设要求双语、历史里也全是双语样例，所以只能靠**最后一条 system** 压住。
_msgs_mute = ai._build_messages("PERSONA", [], "你好", zh_only=True)
check("zh_only：追加「只输出中文」的 system 提示",
      any(m["role"] == "system" and "只输出中文" in m["content"] for m in _msgs_mute),
      str(_msgs_mute))
check("zh_only：该提示紧挨用户消息（最近的指令才压得住双语人设）",
      _msgs_mute[-1]["role"] == "user" and "静音模式" in _msgs_mute[-2].get("content", ""),
      str([m["role"] for m in _msgs_mute]))
_msgs_plain = ai._build_messages("PERSONA", [], "你好")
check("未开静音模式时不加该提示（默认行为不变）",
      not any("静音模式" in m.get("content", "") for m in _msgs_plain))

# 篇幅：只写「只输出中文」是不够的 —— 平时中文的长度是被**日语那一句**锚住的，
# 锚一撤模型就会自由展开（实测 21.5 字 → 53.5 字，最坏 105 字，约 2.5 倍）。
# 所以提示里必须同时给出「先在心里按平时格式想好 + 只输出中文那一半 + 字数区间」。
check("zh_only：提示要求「先按平时格式组织、只输出中文那一半」（补回被撤掉的长度锚）",
      "只输出它的中文翻译" in ai._MUTE_MODE_HINT, ai._MUTE_MODE_HINT)
check("zh_only：提示带字数区间（20~40 字，与平时的 21.5 字量级一致）",
      "20 字上下" in ai._MUTE_MODE_HINT and "最多 40 字" in ai._MUTE_MODE_HINT,
      ai._MUTE_MODE_HINT)
check("zh_only：提示显式禁止「因为省了日语就展开/罗列」",
      "不要因为省掉日语就把内容展开" in ai._MUTE_MODE_HINT, ai._MUTE_MODE_HINT)
check("zh_only：这条字数要求**只**出现在静音提示里（人设必须保持不限长）",
      "字以内" not in ai._MUTE_MODE_HINT and "字以内" not in ai._build_messages(
          "PERSONA", [], "你好")[0]["content"],
      ai._MUTE_MODE_HINT)

# 请求层：只回中文的模型回复要被正常接受，且**只请求一次**（重试会白烧两次 API）
_mute_calls = {"n": 0}


class _MuteCompletions(_FakeCompletions):
    def create(self, **kw):
        _mute_calls["n"] += 1
        self._sink.append(kw)
        return _FakeResp("老师，早上好呀！")      # 只有中文，没有日语


class _MuteChat(_FakeChat):
    def __init__(self, c, sink):
        self.completions = _MuteCompletions(c, sink)


class _MuteClient(_FakeClient):
    def __init__(self, c, sink):
        self.chat = _MuteChat(c, sink)


_mute_kw = []
_orig_openai3 = ai.OpenAI
ai.OpenAI = lambda **kw: _MuteClient(None, _mute_kw)
try:
    out_mute = ai.chat_once({"api_key": "sk-x"}, "p", [], "你好", zh_only=True)
finally:
    ai.OpenAI = _orig_openai3
check("zh_only：中文-only 回复被接受，ja 恒为空串",
      out_mute == {"zh": "老师，早上好呀！", "ja": ""}, str(out_mute))
check("zh_only：不因「缺日语」重试（只请求 1 次 —— 静音模式本来就是为了快）",
      _mute_calls["n"] == 1, f"create 调用了 {_mute_calls['n']} 次")


# ========== 2c. 双语解析：顺序不固定（日语在前 / 中文在前都能吃下） ==========
print("== 2c. 解析顺序容错 ==")

zh, ja = ai._parse_zh_ja("日语：おはよう。|||中文：早上好。")
check("新格式「日语在前」解析正确", (zh, ja) == ("早上好。", "おはよう。"), str((zh, ja)))

zh, ja = ai._parse_zh_ja("中文：你好。|||日语：こんにちは。")
check("旧格式「中文在前」仍然解析正确（向后兼容）",
      (zh, ja) == ("你好。", "こんにちは。"), str((zh, ja)))

zh, ja = ai._parse_zh_ja("こんにちは。|||你好。")
check("两侧都没标签时按假名判断语言（日语那侧含假名）",
      (zh, ja) == ("你好。", "こんにちは。"), str((zh, ja)))

zh, ja = ai._parse_zh_ja("你好。|||こんにちは。")
check("无标签且顺序反了也能纠正", (zh, ja) == ("你好。", "こんにちは。"), str((zh, ja)))

zh, ja = ai._parse_zh_ja("日语：おはよう。")
check("只有日语一段：不能当中文返回（否则界面会把日语显示出来）",
      (zh, ja) == ("", "おはよう。"), str((zh, ja)))

zh, ja = ai._parse_zh_ja("中文：只有中文。")
check("只有中文一段：剥掉标签、日语留空", (zh, ja) == ("只有中文。", ""), str((zh, ja)))

# ★★2026-09-30 新增（用户报「让爱丽丝打开B站时出现『无中文输出』、她没有输出」）：
#   人设要求**专有名词用日文写法**，所以中文回复里会正经出现片假名站名（ビリビリ / ピクシブ…）。
#   而语言兜底判据原来用的是「含不含**假名**」（片假名也认）⇒ 整句中文被误判成"只有日语一段"
#   ⇒ 中文被丢掉（界面弹「（本次回复缺少中文版本，已跳过文字显示）」＝用户看到的「无中文输出」），
#   静音模式下更会把中文当日语送去合成。判据已细化为「含不含**平假名**」（中文不会有平假名）。
_ZH_SITE = "好的老师！爱丽丝这就帮你打开ビリビリ，请稍等哦！"
check("★片假名站名不再把中文误判成日语（否则中文整段丢）",
      ai._parse_zh_ja(_ZH_SITE) == (_ZH_SITE, ""), str(ai._parse_zh_ja(_ZH_SITE)))
check("★无标签双语：中文侧含片假名时不会左右颠倒",
      ai._parse_zh_ja("ビリビリを開きます。|||好的，帮你打开ビリビリ！")
      == ("好的，帮你打开ビリビリ！", "ビリビリを開きます。"),
      str(ai._parse_zh_ja("ビリビリを開きます。|||好的，帮你打开ビリビリ！")))
check("判据细化：平假名算日语、片假名不算（`_has_kana` 保留旧语义）",
      ai._has_hiragana("こんにちは") and not ai._has_hiragana("ビリビリ")
      and ai._has_kana("ビリビリ"))
check("回归：只有日语一段仍不被当中文返回（别把日语摆到界面上）",
      ai._parse_zh_ja("日语：ビリビリを開きますね。") == ("", "ビリビリを開きますね。"),
      str(ai._parse_zh_ja("日语：ビリビリを開きますね。")))

check("分句保留句末标点（TTS 靠标点定停顿）",
      ai.split_sentences("喂。你好！在吗？") == ["喂。", "你好！", "在吗？"],
      str(ai.split_sentences("喂。你好！在吗？")))
check("空文本分句安全", ai.split_sentences("") == [], str(ai.split_sentences("")))

check("detect_order：日语标签在前 → ja_first",
      ai.detect_order("日语：おはよう。|||中文：早。") == "ja_first",
      ai.detect_order("日语：おはよう。|||中文：早。"))
check("detect_order：中文标签在前 → zh_first",
      ai.detect_order("中文：早。|||日语：おはよう。") == "zh_first",
      ai.detect_order("中文：早。|||日语：おはよう。"))

# 流式分段必须容忍半截文本：标签只打到「日」时不能把「日」当成台词
_ja, _zh, _closed = ai._stream_regions("日", "ja_first")
check("标签还没打完时日语段为空（半个标签不会被当成台词）", (_ja, _zh) == ("", ""), str((_ja, _zh)))
_ja, _zh, _closed = ai._stream_regions("日语：こんにちは。|", "ja_first")
check("间隔符只到一半时不会被显示出来",
      (_ja, _zh, _closed) == ("こんにちは。", "", False), str((_ja, _zh, _closed)))


# ========== 2d. chat_stream：事件顺序 + 流式边界 ==========
print("== 2d. chat_stream 流式 ==")


class _SDelta:
    def __init__(self, c):
        self.content = c


class _SChoice:
    def __init__(self, c, fr=None):
        self.delta = _SDelta(c)
        self.finish_reason = fr


class _SChunk:
    def __init__(self, c, fr=None):
        self.choices = [_SChoice(c, fr)]


class _FakeStream:
    """逐字吐的假流（真流式是按 token 来的，逐字最苛刻）。

    可选 `on_char(i, ch)`：在「吐出第 i 个字**之前**」回调，用来探到「事件发得有多早」。
    """

    def __init__(self, text, finish="stop", on_char=None):
        self._text, self._finish, self._on_char = text, finish, on_char

    def __iter__(self):
        for i, ch in enumerate(self._text):
            if self._on_char:
                self._on_char(i, ch)
            fr = self._finish if i == len(self._text) - 1 else None
            yield _SChunk(ch, fr)


class _StreamCompletions:
    def __init__(self, text, finish, sink, on_char):
        self._text, self._finish, self._sink, self._on_char = text, finish, sink, on_char

    def create(self, **kw):
        self._sink.append(kw)
        return _FakeStream(self._text, self._finish, self._on_char)


class _StreamClient:
    def __init__(self, text, finish, sink, on_char):
        self.chat = type("C", (), {})()
        self.chat.completions = _StreamCompletions(text, finish, sink, on_char)


def run_stream(text, finish="stop", events=None, on_char=None, zh_only=False):
    """跑一遍 chat_stream，返回 (结果, 事件列表, 请求参数)。events 可外部传入以便边跑边看。"""
    sink = []
    if events is None:
        events = []
    orig = ai.OpenAI
    ai.OpenAI = lambda **kw: _StreamClient(text, finish, sink, on_char)
    try:
        out = ai.chat_stream({"api_key": "k", "base_url": "https://example.com/v1",
                              "model": "m"}, "p", [], "hi",
                             on_event=lambda k, p: events.append((k, p)),
                             zh_only=zh_only)
    finally:
        ai.OpenAI = orig
    return out, events, sink


out, ev, sink = run_stream("日语：おはよう。元気？|||中文：早上好。还好吗？")
kinds = [k for k, _ in ev]
check("chat_stream 开了流式（stream=True）", bool(sink) and sink[0].get("stream") is True, str(sink[:1]))
check("日语**整段一次**送出（不再按句拆）",
      [p for k, p in ev if k == "ja"] == ["おはよう。元気？"], str(ev))
check("不再有中文分句事件（界面只在开场时一次拿到完整中文）",
      all(k != "zh" for k in kinds), str(kinds))
check("结尾必发一次 done（写聊天记录 + 放行播放用）", kinds[-1] == "done", str(kinds))
check("done 里带权威双语",
      ev[-1][1] == {"zh": "早上好。还好吗？", "ja": "おはよう。元気？"}, str(ev[-1]))
check("返回值与非流式路径同构（zh/ja）",
      (out["zh"], out["ja"]) == ("早上好。还好吗？", "おはよう。元気？"), str(out))
check("未截断时 truncated 为 False", out.get("truncated") is False, str(out))

# 静音模式下的流式：整段都是中文 → 既不该发 ja 事件（没有日语可合成），也不该少发 done
out, ev, sink = run_stream("老师，早上好呀！", zh_only=True)
check("zh_only：不发 ja 事件（不把中文送去日语合成）",
      [k for k, _ in ev if k == "ja"] == [], str(ev))
check("zh_only：整段当中文返回、ja 为空串",
      (out["zh"], out["ja"]) == ("老师，早上好呀！", ""), str(out))
check("zh_only：done 仍照发（界面靠它放行出字与写聊天记录）",
      [k for k, _ in ev][-1:] == ["done"], str([k for k, _ in ev]))
check("zh_only：请求里带上了「只输出中文」的 system 提示",
      any(m.get("role") == "system" and "只输出中文" in m.get("content", "")
          for m in sink[0].get("messages", [])), str(sink[:1]))

# 日语必须**一吐完就送**：日语段只占整条回复的前半，事件必须在那之前发出来，
# 否则「合成与中文生成并行」就是空的（等于退回整段串行）。
TEXT2 = "日语：おはよう。元気？|||中文：早上好。还好吗？"
ev2 = []
probe = {"n": 0, "ja_at": None}


def _on_char(i, _ch):
    probe["n"] = i + 1
    if probe["ja_at"] is None and any(k == "ja" for k, _ in ev2):
        probe["ja_at"] = probe["n"]


run_stream(TEXT2, events=ev2, on_char=_on_char)
check("日语在「分界符一出现」就送出（不是等整段回复写完）",
      probe["ja_at"] is not None and probe["ja_at"] < len(TEXT2),
      f"{probe} len={len(TEXT2)}")
check("送出时刻落在整条回复的前 70%（确实提前了）",
      probe["ja_at"] is not None and probe["ja_at"] <= len(TEXT2) * 0.7,
      f"{probe} len={len(TEXT2)}")

# 模型没按人设、把中文写在前面：顺序要自动纠正，别把中文送进日语语音
out, ev, _ = run_stream("中文：早上好。还好吗？|||日语：おはよう。元気？")
check("中文在前时也能切出正确的日语（整段一次）",
      [p for k, p in ev if k == "ja"] == ["おはよう。元気？"], str(ev))
check("中文在前时界面拿到的是纯中文（不含日语）", out["zh"] == "早上好。还好吗？", str(out))

# 漏写间隔符：用「中文：」标签兜底，否则中文会被当成日语合成
out, ev, _ = run_stream("日语：おはよう。中文：早上好。")
check("漏写 ||| 时用「中文：」兜底切分",
      (out["zh"], out["ja"]) == ("早上好。", "おはよう。"), str(out))
check("兜底切分时日语同样整段一次送出",
      [p for k, p in ev if k == "ja"] == ["おはよう。"], str(ev))

# 只有日语：不能把整串当中文（也不该当日语）；由调用方决定兜底
out, ev, _ = run_stream("日语：おはよう。")
check("只有日语时 zh 为空（调用方据此提示，而不是把日语摆到界面上）",
      (out["zh"], out["ja"]) == ("", "おはよう。"), str(out))
check("只有日语时仍把日语整段送去合成",
      [p for k, p in ev if k == "ja"] == ["おはよう。"], str(ev))

# 模型完全没按人设、只输出中文：**别把中文当日语念**，交给调用方用中文兜底
out, ev, _ = run_stream("今天天气不错，出去走走吧。")
check("只输出中文时 ja 为空（不把中文送进日语语音模型）",
      out["ja"] == "" and out["zh"] == "今天天气不错，出去走走吧。", str(out))
check("只输出中文时不发 ja 事件（由调用方改用中文兜底合成）",
      all(k != "ja" for k, _ in ev), str([k for k, _ in ev]))

# 被 max_tokens 截断：不发 done，标记 truncated 交给调用方决定是否回退
out, ev, _ = run_stream("日语：おはよう。|||中文：早上好", finish="length")
check("截断时不发 done（避免先写了记录、又回退重来）",
      all(k != "done" for k, _ in ev), str([k for k, _ in ev]))
check("截断时 truncated 为 True", out.get("truncated") is True, str(out))


# ========== 3. ApiPanel：添加 / 编辑 / 切换 ==========
print("== 3. ApiPanel 添加/编辑/切换 ==")
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import gui  # noqa: E402

qapp = QApplication.instance() or QApplication(sys.argv)

tmp_cfg.write_text(json.dumps({"apis": [], "current_api": ""}), encoding="utf-8")
cfg = cfgmod.load_config()
panel = gui.ApiPanel(cfg)
check("空列表时下拉菜单无项", panel.api_combo.count() == 0, str(panel.api_combo.count()))


class FakeForm:
    """替身：绕过真实弹窗，只验证 ApiPanel 的数据流。"""
    next_values = {}
    next_confirm = True
    last_title = None

    def __init__(self, title, fields, parent=None):
        FakeForm.last_title = title
        self.fields = fields
        self.confirm_btn = object()          # 模拟按钮对象

    def exec(self):
        return 1

    def confirmed(self):
        return FakeForm.next_confirm

    def get(self, attr):
        return FakeForm.next_values.get(attr, "")


_gui_form = gui.ApiFormDialog
gui.ApiFormDialog = FakeForm

# --- 添加 1：DeepSeek 默认 ---
FakeForm.next_confirm = True
FakeForm.next_values = {"name": "爱丽丝", "api_key": "sk-alice",
                        "base_url": "", "model": ""}
panel._add_api()
check("添加成功（不再 AttributeError）",
      len(cfg["apis"]) == 1 and cfg["apis"][0]["name"] == "爱丽丝", str(cfg["apis"]))
check("添加对话框标题为「添加 API」", FakeForm.last_title == "添加 API", str(FakeForm.last_title))
check("空白 base_url/model 回退默认",
      cfg["apis"][0]["base_url"] == cfgmod.DEFAULT_BASE_URL
      and cfg["apis"][0]["model"] == "deepseek-flash", str(cfg["apis"][0]))
check("新添加的成为当前 API", cfg["current_api"] == "爱丽丝", cfg["current_api"])
check("下拉菜单同步 1 项", panel.api_combo.count() == 1, str(panel.api_combo.count()))

# --- 添加 2：自定义服务与模型 ---
FakeForm.next_values = {"name": "Kimi", "api_key": "sk-kimi",
                        "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"}
panel._add_api()
check("可添加第二个 API", len(cfg["apis"]) == 2, str(cfg["apis"]))
check("第二个 API 保留自定义端点",
      cfg["apis"][1]["base_url"] == "https://api.moonshot.cn/v1"
      and cfg["apis"][1]["model"] == "moonshot-v1-8k", str(cfg["apis"][1]))
check("当前 API 切到新添加的", cfg["current_api"] == "Kimi", cfg["current_api"])

# --- 重名：应被拒绝 ---
FakeForm.next_values = {"name": "Kimi", "api_key": "sk-dup",
                        "base_url": "", "model": ""}
panel._add_api()
check("重名被拒绝", len(cfg["apis"]) == 2, str(cfg["apis"]))

# --- 缺 key：应被拒绝 ---
FakeForm.next_values = {"name": "缺key", "api_key": "", "base_url": "", "model": ""}
panel._add_api()
check("缺 API Key 被拒绝", len(cfg["apis"]) == 2, str(cfg["apis"]))

# --- 取消：不应新增 ---
FakeForm.next_confirm = False
FakeForm.next_values = {"name": "取消的", "api_key": "sk-x", "base_url": "", "model": ""}
panel._add_api()
check("取消添加不产生新条目", len(cfg["apis"]) == 2, str(cfg["apis"]))
FakeForm.next_confirm = True

# --- 下拉切换：切走旧 API，当前 API 立即变为新选中的 ---
panel.api_combo.setCurrentIndex(0)          # 0 → 爱丽丝
qapp.processEvents()
check("下拉切换后 current_api == 爱丽丝", cfg["current_api"] == "爱丽丝", cfg["current_api"])
check("被切走的 API 仍保留在列表（仅停用不删除）",
      [a["name"] for a in cfg["apis"]] == ["爱丽丝", "Kimi"], str(cfg["apis"]))
check("切换已持久化到磁盘",
      json.loads(tmp_cfg.read_text(encoding="utf-8"))["current_api"] == "爱丽丝")

# --- 编辑：改模型名 ---
entry = cfg["apis"][1]
FakeForm.next_values = {"name": "Kimi", "base_url": "https://api.moonshot.cn/v1",
                        "model": "moonshot-v1-32k"}
panel._edit_row(entry, None)
check("编辑对话框标题为「编辑 API」", FakeForm.last_title == "编辑 API", str(FakeForm.last_title))
check("编辑改掉模型名", entry["model"] == "moonshot-v1-32k", entry["model"])
check("编辑不丢失 base_url", entry["base_url"] == "https://api.moonshot.cn/v1", entry["base_url"])

# --- 编辑改名：若改的是当前 API，current_api 跟随 ---
cur = cfg["current_api"]
cur_entry = next(a for a in cfg["apis"] if a["name"] == cur)
FakeForm.next_values = {"name": cur + "改", "base_url": cur_entry["base_url"],
                        "model": cur_entry["model"]}
panel._edit_row(cur_entry, None)
check("改名后 current_api 跟随", cfg["current_api"] == cur + "改", cfg["current_api"])

# --- 编辑重名：应被拒绝 ---
names_before = [a["name"] for a in cfg["apis"]]
FakeForm.next_values = {"name": names_before[0], "base_url": "", "model": "x"}
panel._edit_row(cfg["apis"][1], None)
check("编辑重名被拒绝", [a["name"] for a in cfg["apis"]] == names_before, str(cfg["apis"]))

gui.ApiFormDialog = _gui_form


# ========== 4. 真实对话框结构（防回归） ==========
# 2026-09-17：用户报「添加 / 编辑 API 的弹窗不符合规范」—— 旧实现是 QMessageBox（系统标题栏 +
# 自带按钮布局，QSS 管不到，取消按钮跟着确认一起变蓝底）。这里把「必须是自绘卡片弹窗」钉死。
print("== 4. ApiFormDialog 结构 ==")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QFrame, QMessageBox, QPushButton  # noqa: E402

dlg = gui.ApiFormDialog("测试", [
    ("name", "名称：", "ph", "初值", False),
    ("api_key", "Key：", "sk-...", "", True),
])
check("有 confirm_btn 属性", hasattr(dlg, "confirm_btn"))
check("未点击时 confirmed() 为 False", dlg.confirmed() is False)
check("get() 读回初始值", dlg.get("name") == "初值", dlg.get("name"))
check("不是 QMessageBox（没有 clickedButton / addButton 那套旧 API）",
      not isinstance(dlg, QMessageBox) and not hasattr(dlg, "clickedButton"))
check("是 QDialog（与确认 / 输入弹窗同族）", isinstance(dlg, gui.QDialog))
check("无边框 + 透明底（自绘卡片的前提）",
      bool(dlg.windowFlags() & Qt.FramelessWindowHint) and dlg.testAttribute(Qt.WA_TranslucentBackground),
      str(dlg.windowFlags()))
check("宽度固定 360px", dlg.width() == 360, str(dlg.width()))
check("卡片是 #confirmCard（16px 圆角 + 淡蓝边框）",
      dlg.findChild(QFrame, "confirmCard") is not None
      and "QFrame#confirmCard { background:#FFFFFF; border:1px solid #E6F1FB; border-radius:16px; }"
      in dlg.styleSheet())
_cancel = dlg.findChild(QPushButton, "cancelBtn")
_confirm = dlg.findChild(QPushButton, "confirmBtn")
check("取消 / 确认两个按钮都在，且各自 88×34",
      _cancel is not None and _confirm is not None
      and (_cancel.width(), _cancel.height()) == gui.ApiFormDialog.BTN_SIZE
      and (_confirm.width(), _confirm.height()) == gui.ApiFormDialog.BTN_SIZE,
      f"{_cancel} {_confirm}")
check("confirm_btn 就是卡片里的确认按钮", dlg.confirm_btn is _confirm)
check("取消是灰边、确认是蓝底（不再两个都是蓝底）",
      "color:#64748B" in dlg.styleSheet() and "border:1px solid #CBD5E1" in dlg.styleSheet()
      and "background:#378ADD" in dlg.styleSheet())
check("输入框不写死最小宽（旧 bug：min-width 把 360px 卡片撑破）",
      "min-width" not in dlg.styleSheet(), dlg.styleSheet())
check("密码字段走 Password 回显", dlg.edits["api_key"].echoMode() == gui.QLineEdit.Password)
check("标签独占一行时去掉尾冒号",
      dlg.findChildren(gui.QLabel)[1].text() == "名称",
      dlg.findChildren(gui.QLabel)[1].text())
check("字段数与 fields 数一致", len(dlg.edits) == 2, str(list(dlg.edits)))
dlg.accept()
check("accept 后 confirmed() 为 True", dlg.confirmed() is True)
dlg.deleteLater()

# 回车 = 确认（不弹真窗口，用 QTest 往输入框发一个 Return）
dlg_ret = gui.ApiFormDialog("回车", [("name", "名称：", "ph", "初值", False)])
dlg_ret.show()
qapp.processEvents()
QTest.keyClick(dlg_ret.edits["name"], Qt.Key_Return)
qapp.processEvents()
check("输入框回车 = 确认", dlg_ret.confirmed() is True, str(dlg_ret.result()))
dlg_ret.deleteLater()


# 三个弹窗必须共用同一张皮肤（防有人只改其中一个，慢慢分叉）
def _rule(sheet, selector):
    """从样式表里取出某个选择器的声明体（按片段匹配，够用且不依赖 QSS 解析）。"""
    for chunk in sheet.split("}"):
        if selector in chunk:
            return chunk.split("{", 1)[1].strip()
    return ""


_dialogs = [
    gui.ConfirmDialog(None, "x"),
    gui.InputDialog(None, "标题", "标签", ""),
    gui.ApiFormDialog("标题", [("name", "名称：", "ph", "", False)]),
]
_cards = {_rule(d.styleSheet(), "QFrame#confirmCard") for d in _dialogs}
_cancels = {_rule(d.styleSheet(), "QPushButton#cancelBtn {") for d in _dialogs}
_confirms = {_rule(d.styleSheet(), "QPushButton#confirmBtn {") for d in _dialogs}
check("三个弹窗共用同一张卡片皮肤",
      len(_cards) == 1 and "border-radius:16px" in sorted(_cards)[0], str(sorted(_cards)))
check("三个弹窗的「取消」同为灰边",
      len(_cancels) == 1 and "#CBD5E1" in sorted(_cancels)[0], str(sorted(_cancels)))
check("三个弹窗的「确认」同为蓝底",
      len(_confirms) == 1 and "#378ADD" in sorted(_confirms)[0], str(sorted(_confirms)))
for _d in _dialogs:
    _d.deleteLater()


# ========== 5. 关闭行为回归：api.quit 不会死循环 ==========
print("== 5. 关闭行为（quit 分支放行） ==")
from PySide6.QtGui import QCloseEvent  # noqa: E402

cfg["general"] = {"close_action": "quit"}
hit = {"n": 0}
win = gui.MainWindow(cfg)
win.set_quit_app(lambda: hit.__setitem__("n", hit["n"] + 1))
win.set_hide_to_tray(lambda: None)
win.show()
ev = QCloseEvent()
win.closeEvent(ev)
check("quit 模式：放行事件 + 回调一次", ev.isAccepted() and hit["n"] == 1,
      f"accepted={ev.isAccepted()} n={hit['n']}")
ev2 = QCloseEvent()
win.closeEvent(ev2)
check("quit 过程中的再次关闭仍放行且不重复回调", ev2.isAccepted() and hit["n"] == 1,
      f"accepted={ev2.isAccepted()} n={hit['n']}")
win.mark_quitting()
win.deleteLater()


# ========== 6. AI 回复回传桥：参数个数必须与 emit 一致 ==========
# 历史 bug：_ReplyBridge 仍是 Signal(str,str,str) 而 worker emit 了 4 个参数
# → worker 线程抛 TypeError 直接死掉 → 聊天界面不出中文、也没有日语可合成（看起来像"AI 没回复"）。
print("== 6. AI 回复回传桥 ==")
import ast  # noqa: E402

from app import main as appmain  # noqa: E402

rb = appmain._ReplyBridge()
got = []
rb.reply_ready.connect(lambda *a: got.append(a))
try:
    rb.reply_ready.emit("alice", "中文", "日语", "爱丽丝")
    qapp.processEvents()
    emit_err = ""
except TypeError as e:  # noqa: BLE001
    emit_err = str(e)
check("_ReplyBridge 能接收 4 个参数（与 worker 的 emit 一致）",
      not emit_err and got == [("alice", "中文", "日语", "爱丽丝")], emit_err or str(got))

# 静态校验：main.py 里所有 xxx.emit(...) 的实参个数，都必须等于对应 Signal(...) 的声明个数
_main_src = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
_tree = ast.parse(_main_src)
# 信号声明按「类名.信号名」记 —— `done` 这个名字在多个桥里都有，
# 只按信号名做键会互相串味，把合法的 emit 判成不匹配。
sig_arity = {}
class_names = {n.name for n in ast.walk(_tree) if isinstance(n, ast.ClassDef)}
for _node in ast.walk(_tree):
    if isinstance(_node, ast.ClassDef):
        for _stmt in _node.body:
            if isinstance(_stmt, ast.Assign) and isinstance(_stmt.value, ast.Call) \
                    and isinstance(_stmt.value.func, ast.Name) and _stmt.value.func.id == "Signal":
                for _t in _stmt.targets:
                    if isinstance(_t, ast.Name):
                        sig_arity[f"{_node.name}.{_t.id}"] = len(_stmt.value.args)
# 桥实例变量 → 类名
var_class = {}
for _node in ast.walk(_tree):
    if isinstance(_node, ast.Assign) and isinstance(_node.value, ast.Call) \
            and isinstance(_node.value.func, ast.Name) and _node.value.func.id in class_names:
        for _t in _node.targets:
            if isinstance(_t, ast.Name):
                var_class[_t.id] = _node.value.func.id
mismatch = []
for _node in ast.walk(_tree):
    if isinstance(_node, ast.Call) and isinstance(_node.func, ast.Attribute) \
            and _node.func.attr == "emit" \
            and isinstance(_node.func.value, ast.Attribute) \
            and isinstance(_node.func.value.value, ast.Name):
        cls = var_class.get(_node.func.value.value.id)
        if cls is None:
            continue
        key = f"{cls}.{_node.func.value.attr}"
        if key not in sig_arity:
            continue
        if len(_node.args) != sig_arity[key]:
            mismatch.append(f"{key}: emit {len(_node.args)} 个 vs Signal {sig_arity[key]} 个")
check("main.py 中所有 emit 的参数个数与 Signal 声明一致", not mismatch, str(mismatch))
check("_ReplyBridge.reply_ready 声明为 4 个参数",
      sig_arity.get("_ReplyBridge.reply_ready") == 4,
      str(sig_arity.get("_ReplyBridge.reply_ready")))
check("整段回复两桥的参数个数（started 2 / done 4）",
      (sig_arity.get("_SpeakStartBridge.started"),
       sig_arity.get("_ReplyDoneBridge.done")) == (2, 4), str(sig_arity))
rb.deleteLater()


# ========== 人设：日语**不设长度上限**（docs/01 F3/F4）==========
# 沿革：09-16 一度试行「限 30 字 → 放宽 50 字」，同日**撤销**、回到不限长；
# 提速改由「静音模式」承担（见上面 zh_only 那组断言）。
# 这条需求同样**没有代码实现**，完全靠人设文本承载 —— 所以这里**反向**钉住：
# 一旦有人把长度规则写回人设，就报红，免得它在没人察觉的情况下削掉角色的话。
PERSONA_DIR = Path(__file__).resolve().parent.parent / "persona"
_LENRULE_RE = re.compile(r"日语版本.{0,10}?控制|\d+\s*字以内")
for _role in ("alice", "ellen"):
    _txt = (PERSONA_DIR / f"{_role}.md").read_text(encoding="utf-8")
    _hit = _LENRULE_RE.search(_txt)
    check(f"人设 {_role}：没有日语长度上限（限长已撤销，提速改由静音模式承担）",
          _hit is None, f"命中了长度规则：{_hit.group(0) if _hit else ''}")


print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)
