# -*- coding: utf-8 -*-
"""冒烟测试：TTS 文本处理与长文本切分（不依赖 GPT-SoVITS 服务）。

覆盖：
  - `_preprocess_ja_text`：顿号/换行/空格归一、拉丁字母清理、连读句号、专名替换；
  - `_split_ja_for_sovits`：短文本原样、长文本按句拆行、每行 ≤ 上限、切分无损、无标点长串硬切；
  - `synthesize()` 集成：用假 urlopen 断言「长日语被切成多行后一次请求下发」，
    且每行都不超过单行上限（即不会再触发服务端 54s 静默截断）；
  - `role_ref()` **三级回落**（安装根 → 包内 `refs/` → 历史固定位置）+ 优先级负对照（2026-09-29）。

跑法（在项目根目录）：
    .venv\\Scripts\\python.exe tests\\smoke_tts.py
"""
import math
import shutil
import sys
import tempfile
import wave
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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


from app import tts  # noqa: E402

# ========== 1. 日语预处理 ==========
print("== 1. _preprocess_ja_text 预处理 ==")
check("顿号 → 句号", tts._preprocess_ja_text("あ、い") == "あ。い", tts._preprocess_ja_text("あ、い"))
check("换行 → 句号", tts._preprocess_ja_text("あ\nい") == "あ。い", tts._preprocess_ja_text("あ\nい"))
check("空格 → 句号", tts._preprocess_ja_text("あ い") == "あ。い", tts._preprocess_ja_text("あ い"))
check("连续句号合并", tts._preprocess_ja_text("あ。。い") == "あ。い", tts._preprocess_ja_text("あ。。い"))
check("拉丁字母被删除",
      tts._preprocess_ja_text("abcこんにちはxyz") == "こんにちは",
      tts._preprocess_ja_text("abcこんにちはxyz"))
check("专名 B站 → ビリビリ",
      tts._preprocess_ja_text("B站") == "ビリビリ", tts._preprocess_ja_text("B站"))


# ========== 2. 长文本按句切分 ==========
print("== 2. _split_ja_for_sovits 切分 ==")
check("上限常量为 50", tts._JA_LINE_MAX_CHARS == 50, str(tts._JA_LINE_MAX_CHARS))

SHORT = "こんにちは。"
check("短文本原样返回（无换行）",
      tts._split_ja_for_sovits(SHORT) == SHORT, repr(tts._split_ja_for_sovits(SHORT)))
check("空文本安全", tts._split_ja_for_sovits("") == "", repr(tts._split_ja_for_sovits("")))

LONG = ("先生おはようございます。今日はとてもいい天気ですね。"
        "私は昨日図書館で面白い本を読みました。それは宇宙の話でした。"
        "星の光は何万年も旅をしてやっと私たちのところへ届くそうです。"
        "だから夜空を見上げると昔の時間が見えるんですね。")
assert len(LONG) > tts._JA_LINE_MAX_CHARS, len(LONG)
split = tts._split_ja_for_sovits(LONG)
lines = split.split("\n")
check("长文本被拆成多行", len(lines) > 1, str(len(lines)))
check("每行都不超过单行上限（规避 54s 截断）",
      all(len(ln) <= tts._JA_LINE_MAX_CHARS for ln in lines),
      str([len(ln) for ln in lines]))
check("切分无损（去换行后与原文一致）",
      split.replace("\n", "") == LONG, repr(split.replace("\n", "")[:60]))
check("换行落在句子边界（每行以句号结尾，末行除外）",
      all(ln.endswith("。") for ln in lines[:-1]) and lines[-1].endswith("。"),
      str(lines))

# 无标点长串 → 硬切
NOPUNC = "あ" * 130
np_lines = tts._split_ja_for_sovits(NOPUNC).split("\n")
check("无标点长串被硬切且每行 ≤ 上限",
      len(np_lines) > 1 and all(len(ln) <= tts._JA_LINE_MAX_CHARS for ln in np_lines),
      str([len(ln) for ln in np_lines]))
check("硬切后内容无损", "".join(np_lines) == NOPUNC, str(len("".join(np_lines))))


# ========== 3. synthesize 集成：长日语切成多行后一次请求下发 ==========
print("== 3. synthesize 集成（假 urlopen）==")


def _tone_wav(sr=32000, sec=0.5, freq=440.0):
    """造一段非静音的正弦波 wav 字节。"""
    n = int(sr * sec)
    buf = BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(0.6 * 32767 * math.sin(2 * math.pi * freq * i / sr))
            frames += int(v).to_bytes(2, "little", signed=True)
        f.writeframes(bytes(frames))
    return buf.getvalue()


_WAV = _tone_wav()
check("测试用 wav 非静音", not tts._wav_is_silent(_WAV))

captured = {}


class _Resp:
    def __init__(self, data):
        self._d = data

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, timeout=None):
    captured["url"] = req.full_url if hasattr(req, "full_url") else str(req)
    return _Resp(_WAV)


_orig_alive = tts._service_alive
_orig_urlopen = tts.urllib.request.urlopen
tts._service_alive = lambda: True          # 视为服务在线，避免真的拉起/等待
tts.urllib.request.urlopen = _fake_urlopen
try:
    out = Path(__file__).resolve().parent / "_tts_smoke_out.wav"
    ok = tts.synthesize("alice", LONG, out)
finally:
    tts._service_alive = _orig_alive
    tts.urllib.request.urlopen = _orig_urlopen

check("synthesize 返回成功", ok is True, str(ok))
q = parse_qs(urlparse(captured.get("url", "")).query)
sent = q.get("text", [""])[0]
check("请求参数 text 含换行（长文本已按句切分后下发）", "\n" in sent, repr(sent[:80]))
check("下发文本每行 ≤ 上限（服务端不会再截断单行）",
      bool(sent) and all(len(ln) <= tts._JA_LINE_MAX_CHARS for ln in sent.split("\n")),
      str([len(ln) for ln in sent.split("\n")]))
check("下发文本与切分结果一致",
      sent == tts._split_ja_for_sovits(tts._preprocess_ja_text(LONG)), repr(sent[:80]))
check("text_language 仍为 ja", q.get("text_language", [""])[0] == "ja",
      str(q.get("text_language")))
check("输出 wav 已写入", out.exists() and out.stat().st_size > 44,
      str(out.stat().st_size if out.exists() else "missing"))
try:
    out.unlink()
except OSError:
    pass


# ========== 4. role_ref 参考音频的**三级回落**（★2026-09-29 新增中间一级）==========
# 背景：GPT-SoVITS 是**零样本克隆** ⇒ 每次合成都必须现场读一段参考音频。
# 真值在 `refs/`，而 `refs/` **不在项目里、也不在流水线里**（见 `docs/02` §22.10.1）。
# 本轮为了「别人从 Release 解压就自带参考音频」，把 `*_ref.wav` 打进成品包，
# 并让 `role_ref()` 多认一级 `<exe 同级>/refs/`。
# ★这节钉的就是：**新增那一级真被读到**，且**优先级没把既有语义搞乱**（安装根仍优先）。
print("== 4. role_ref 参考音频解析（安装根 → 包内 refs/ → 历史固定位置）==")

_ref_tmp = Path(tempfile.mkdtemp(prefix="_tts_ref_"))
_root_dir = _ref_tmp / "sovits"      # 模拟 GPT-SoVITS 安装根
_base_dir = _ref_tmp / "appdir"      # 模拟 BASE_DIR（打包后 = exe 所在目录）
_legacy_dir = _ref_tmp / "legacy"    # 模拟 D:/GPT-SoVITS/refs


def _mk_ref(d, name="alice_ref.wav"):
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(b"RIFF....WAVEfmt ")
    return p


_o_install, _o_base, _o_legacy = tts.install_dir, tts.BASE_DIR, tts.LEGACY_REFS_DIR
tts.install_dir = lambda: str(_root_dir)
tts.BASE_DIR = _base_dir
tts.LEGACY_REFS_DIR = str(_legacy_dir)
try:
    check("未知角色 ⇒ None（不是「随便给个路径」）",
          tts.role_ref("nobody") is None, str(tts.role_ref("nobody")))

    # ① 三处都没有 ⇒ 回落到历史默认路径，**不返回 None**
    _legacy_expected = (_legacy_dir / "alice_ref.wav").as_posix()
    _r1 = tts.role_ref("alice")
    check("★三处都没有 ⇒ 仍返回配置（回落到历史路径，**不返回 None** —— 上层照旧走「合成失败」，"
          "而不是被误导成「角色不存在」）",
          isinstance(_r1, dict) and _r1.get("ref_wav") == _legacy_expected, str(_r1))
    check("★回落出来的配置带齐 prompt_text / prompt_lang（上层能直接发请求）",
          _r1.get("prompt_lang") == "ja" and bool(_r1.get("prompt_text")), str(_r1))

    # ② 只有「历史固定位置」有
    _mk_ref(_legacy_dir)
    check("只有历史固定位置有 ⇒ 用它的",
          tts.role_ref("alice")["ref_wav"] == _legacy_expected, tts.role_ref("alice")["ref_wav"])

    # ③ ★只有「包内 refs/」（exe 同级）有 ⇒ 必须用包内的（本轮新增的那一级）
    _mk_ref(_base_dir / "refs")
    _base_expected = (_base_dir / "refs" / "alice_ref.wav").as_posix()
    check("★★只有包内 `refs/` 有 ⇒ 用包内的 —— 新增的中间一级**真被读到**"
          "（「解压即用、不用手动往 GPT-SoVITS 里拷」全靠它）",
          tts.role_ref("alice")["ref_wav"] == _base_expected, tts.role_ref("alice")["ref_wav"])

    # ④ ★★负对照：安装根也有 ⇒ 必须用**安装根**的（优先级没被新增那一级搞乱）
    _mk_ref(_root_dir / "refs")
    _root_expected = (_root_dir / "refs" / "alice_ref.wav").as_posix()
    check("★★三处都有时 ⇒ **安装根优先**（既有语义不变：你自己在 GPT-SoVITS 里换过样本，"
          "仍然以你那份为准；全新装的没有 refs/ 才用包里的）",
          tts.role_ref("alice")["ref_wav"] == _root_expected, tts.role_ref("alice")["ref_wav"])

    # ⑤ 角色之间互不串 / 路径格式 / prompt_* 与配置一致
    _mk_ref(_root_dir / "refs", "ellen_ref.wav")
    check("两个角色各取各的文件（不会串）",
          tts.role_ref("ellen")["ref_wav"].endswith("ellen_ref.wav")
          and tts.role_ref("alice")["ref_wav"].endswith("alice_ref.wav"),
          str((tts.role_ref("ellen")["ref_wav"], tts.role_ref("alice")["ref_wav"])))
    _rp = tts.role_ref("alice")["ref_wav"]
    check("返回的 ref_wav 用**正斜杠**（原样进 URL / 命令行都安全）",
          "/" in _rp and "\\" not in _rp, _rp)
    check("★prompt_lang / prompt_text 与 ROLE_REF 表一致（ellen=zh、alice=ja）",
          tts.role_ref("ellen")["prompt_lang"] == "zh"
          and tts.role_ref("alice")["prompt_lang"] == "ja"
          and tts.role_ref("alice")["prompt_text"] == tts.ROLE_REF["alice"]["prompt_text"],
          str(tts.role_ref("alice")))
finally:
    tts.install_dir, tts.BASE_DIR, tts.LEGACY_REFS_DIR = _o_install, _o_base, _o_legacy
    shutil.rmtree(_ref_tmp, ignore_errors=True)


print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)
