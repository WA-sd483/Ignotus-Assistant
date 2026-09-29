"""TTS 语音合成（说）：调用 GPT-SoVITS 本地 API，合成当前角色的日语语音并播放。

GPT-SoVITS 服务由 ensure_running() 自动拉起（端口 9880）。★安装目录**不写死**：
取自设置页的「安装位置」（`voice_model.install_root()`），见 `docs/02` §22.10。
"""
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

# 全局音量（0.0~1.0，1.0 为原始音量）。主程序通过 set_volume 设置，play_wav 播放时应用增益。
_volume = 0.5
# 全局静音开关：静音时播放增益为 0（音量值本身不变，便于点击喇叭图标恢复原音量）。
_muted = False


def set_volume(v: float):
    """设置全局音量（0.0~1.0）。非法值回退到 0.5。"""
    global _volume
    try:
        _volume = max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        _volume = 0.5


def set_muted(m: bool):
    """设置全局静音开关（不影响音量值本身）。"""
    global _muted
    _muted = bool(m)


def is_muted() -> bool:
    """返回是否静音。"""
    return _muted


def _effective_volume() -> float:
    """播放时实际应用的音量：静音时返回 0，否则返回当前音量。"""
    return 0.0 if _muted else _volume


# GPT-SoVITS 服务地址
SOVITS_URL = "http://127.0.0.1:9880"

# 项目根目录（用于定位 voices 目录下的预录制音频）
BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 安装位置（唯一真值）
#
# ★2026-09-27：`SOVITS_DIR` / `SOVITS_PY` 由**常量改成函数** —— 设置页那行「安装位置」是
#   唯一真值，**下载 / 卸载 / 运行时三方必须同源**（`docs/02` §22.10）。改之前这里是硬编码
#   `D:/GPT-SoVITS`，于是「把安装位置改到别处 → 下载/卸载都作用在那边 → 运行时却还去老地方找」
#   ⇒ 表象是「刚下完模型，AI 还是一声不吭」。
#
# ★能安全改成函数的前提是一件**已核实**的事实：`SOVITS_DIR` / `SOVITS_PY` / `ROLE_REF`
#   在**本模块之外没有任何引用**（外部只 `from .tts import synthesize*` / `play_wav` /
#   `set_volume` / `set_muted` / `ensure_running` / `start_in_background`）。
#   ★**动这里之前请重新核一遍** —— 一旦有人 `from .tts import SOVITS_DIR`，改成函数就是 ImportError。

LEGACY_SOVITS_DIR = "D:/GPT-SoVITS"       # 历史固定位置：本机那套环境装在这儿
LEGACY_REFS_DIR = "D:/GPT-SoVITS/refs"    # 参考音频的历史固定位置


def install_dir() -> str:
    """**安装根**（代码体 / `.venv` / 模型所在的那一层）。

    真值来自 `voice_model.install_root(load_config())` —— 用户显式指定的 → 本机已有安装
    （项目内 → `D:\\GPT-SoVITS`）→ 全新装到项目内。

    ★每次现读配置（不缓存）：这样在设置页改完「安装位置」，**下一次合成就会用新位置**。
      读配置文件只有几 KB，相对「合成一次要几秒」可以忽略。
    ★任何异常都**退回历史路径**而不是抛：「TTS 整个不可用」比「路径可能不准」糟得多。
    """
    try:
        from . import voice_model
        from .config import load_config
        return str(voice_model.install_root(load_config()))
    except Exception:  # noqa: BLE001
        return LEGACY_SOVITS_DIR


def sovits_py() -> str:
    """安装根里的 venv 解释器路径。"""
    try:
        from . import voice_model
        return str(voice_model.venv_python(install_dir()))
    except Exception:  # noqa: BLE001
        return LEGACY_SOVITS_DIR + "/.venv/Scripts/python.exe"


# 启动命令。★三条 `-s/-g` 里的是**相对 cwd（= 安装根）**的路径 ⇒ 安装位置怎么变都不用改它。
SOVITS_ARGS = [
    "api.py",
    "-s", "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth",
    "-g", "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
    "-d", "cpu",
    "-fp",
]

# 各角色参考音频配置（零样本克隆）。
# ★这里只存**文件名**，绝对路径由 `role_ref()` 现算（`refs/` 不跟着安装位置走，见下）。
ROLE_REF = {
    "alice": {
        "ref_name": "alice_ref.wav",
        "prompt_text": "ブルーアーカイブ。勇者よ、光があなたと共にあらんことを。ようこそ、先生。",
        "prompt_lang": "ja",
    },
    "ellen": {
        "ref_name": "ellen_ref.wav",
        "prompt_text": "走吧，好累。我出门了。嗯，我尾巴该护理。",
        "prompt_lang": "zh",
    },
}


def role_ref(role_key: str):
    """某个角色的参考音频配置（`ref_wav` **现算**）；角色不认识返回 `None`。

    `ref_wav` 解析顺序（`docs/02` §22.10.1）：
    `<安装根>/refs/<名字>` → **`<exe 同级>/refs/<名字>`** → `D:/GPT-SoVITS/refs/<名字>`。

    ★`refs/` **不是下载流水线的产物**（它是用户录好的音色样本，流水线不下它），
      所以它**不能简单跟着安装位置走** —— 逐处试：装到项目内的机器
      照样能用 `D:\\GPT-SoVITS\\refs` 里那份样本，安装根里恰好有 `refs/` 时也不会舍近求远。
    ★★2026-09-29 新增**中间那一级**：打包时把两个 `*_ref.wav` 放进成品包的 `refs/`
      （`IA_build/pack_stage.py` 的 `REFS_SHIP`）⇒ 别人从 Release 解压就自带参考音频，
      **不用手动往 GPT-SoVITS 目录里拷**。
      放**中间**（而非最前）是为了**不动既有语义**：你自己在 GPT-SoVITS 安装根
      换过样本 ⇒ 仍然以你那份为准；安装根没有（全新装的 GPT-SoVITS）⇒ 才用包里的。
    ★三处都没有时**返回默认那个路径**（不返回 `None`）：让上层照旧走「合成失败」，
      而不是在这里表现成「角色不存在」—— 两者的排查方向完全不同。
    """
    spec = ROLE_REF.get(role_key)
    if not spec:
        return None
    name = spec["ref_name"]
    for cand in (Path(install_dir()) / "refs" / name,
                 Path(BASE_DIR) / "refs" / name,    # ★随包带的那份（exe 同级）
                 Path(LEGACY_REFS_DIR) / name):
        if cand.is_file():
            return {"ref_wav": cand.as_posix(),
                    "prompt_text": spec["prompt_text"], "prompt_lang": spec["prompt_lang"]}
    return {"ref_wav": (Path(LEGACY_REFS_DIR) / name).as_posix(),
            "prompt_text": spec["prompt_text"], "prompt_lang": spec["prompt_lang"]}


def _service_alive() -> bool:
    """检测 GPT-SoVITS 服务是否已在运行（根路径会返回 400 但服务在线，需视 HTTPError 为在线）。"""
    try:
        urllib.request.urlopen(SOVITS_URL + "/", timeout=1.5)
        return True
    except urllib.error.HTTPError:
        return True  # 服务响应了（400 仅表示缺参数）
    except Exception:
        return False


def _wait_service_ready(timeout: float = 180.0) -> bool:
    """等待服务就绪（首次启动需加载模型约 1-2 分钟），超时返回 False。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _service_alive():
            return True
        time.sleep(2)
    return _service_alive()


# 记录服务上次拉起时间，避免加载模型期间被重复 Popen；超时未就绪则允许重新拉起
_sovits_launched = {"ts": 0.0}


def ensure_running() -> bool:
    """检测 GPT-SoVITS 服务，未运行则后台拉起（隐藏窗口）。返回是否已就绪/已拉起。"""
    if _service_alive():
        _sovits_launched["ts"] = time.time()
        return True
    now = time.time()
    # 已在启动中（5 分钟内拉起过且仍在加载模型）则不重复拉起
    if _sovits_launched["ts"] and now - _sovits_launched["ts"] < 300:
        return True
    py = sovits_py()
    if not Path(py).exists():
        return False
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [py] + SOVITS_ARGS,
            cwd=install_dir(),
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _sovits_launched["ts"] = now
        return True
    except Exception:
        return False


def start_in_background():
    """后台线程拉起服务（避免阻塞主程序启动）。"""
    def worker():
        ensure_running()

    threading.Thread(target=worker, daemon=True).start()


# 常见中英混排专有名词 → 日文（GPT-SoVITS 日语模式无法处理中文/英文，会导致合成失败）
_CN_EN_TO_JA = {
    "哔哩哔哩": "ビリビリ", "bilibili": "ビリビリ", "Bilibili": "ビリビリ",
    "B站": "ビリビリ", "b站": "ビリビリ",
    "pixiv": "ピクシブ", "Pixiv": "ピクシブ", "P站": "ピクシブ", "p站": "ピクシブ",
    "抖音": "ティックトック", "douyin": "ティックトック", "Douyin": "ティックトック",
    "力扣": "リートコード", "leetcode": "リートコード", "LeetCode": "リートコード",
    "MC百科": "エムシー百科", "mcmod": "エムシーモッド", "Mcmod": "エムシーモッド",
    "咕咕番": "ググ番", "gugu": "ググ", "Gugu": "ググ",
    "AGE动漫": "エージーアニメ", "agedm": "エージーディーエム", "Agedm": "エージーディーエム",
    "DeepSeek": "ディープシーク", "deepseek": "ディープシーク",
}


def _preprocess_ja_text(text: str) -> str:
    """预处理日语文本：
    - 顿号"、"和空格会导致 GPT-SoVITS 合成静音，替换成句号；
    - 中英混排专有名词（B站/pixiv 等）换成日文，避免合成失败；
    - 删除残留的拉丁字母（GPT-SoVITS 日语模式无法处理英文）。
    """
    text = text.replace("、", "。")
    text = text.replace("\n", "。")  # 换行归一为句末，便于后续按句切分
    text = re.sub(r"[ \t]+", "。", text)
    for cn, ja in _CN_EN_TO_JA.items():
        text = text.replace(cn, ja)
    text = re.sub(r"[A-Za-z]+", "", text)  # 删除残留拉丁字母
    text = re.sub(r"。+", "。", text)
    return text


# GPT-SoVITS 对「单行」文本有硬上限：early_stop_num = hz * max_sec = 50 × 54 ≈ 2700
# 语义 token（约 54 秒），超长单行会被服务端**静默截断**（只合成前半段，不报错）。
# 而服务端 api.py 里 `texts = text.split("\n")` 会逐行合成、拼接成同一段音频，
# 因此把长文本按句拆成多行（每行 ≤ _JA_LINE_MAX_CHARS）即可拿到完整语音。
_JA_LINE_MAX_CHARS = 50


def _split_ja_for_sovits(text: str, max_chars: int = _JA_LINE_MAX_CHARS) -> str:
    """把长日语文本按句末标点拆成多行（每行 ≤ max_chars 字），用换行连接。

    目的：规避 GPT-SoVITS 单行 54s（约 2700 语义 token）的静默截断，保证整段日语
    都被合成；多行会由服务端逐行合成并拼接为同一段音频（api.py: text.split("\\n")）。
    短文本（≤ max_chars）原样返回，不引入换行，保持原有行为。
    """
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    # 按句末标点分句（保留标点），尽量让换行落在句子边界，听感更自然
    sentences = [s for s in re.split(r"(?<=[。！？!?])", text) if s]
    lines: list[str] = []
    cur = ""
    for s in sentences:
        # 单句本身超长（整段无标点的长串）→ 按 max_chars 硬切
        while len(s) > max_chars:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(s[:max_chars])
            s = s[max_chars:]
        if not s:
            continue
        if len(cur) + len(s) <= max_chars:
            cur += s
        else:
            if cur:
                lines.append(cur)
            cur = s
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def _wav_is_silent(data: bytes, threshold: float = 0.005) -> bool:
    """检测 wav 字节数据是否静音（RMS < 阈值），静音视为合成失败。"""
    try:
        import io
        with wave.open(io.BytesIO(data)) as f:
            n = f.getnframes()
            if n == 0:
                return True
            samples = np.frombuffer(f.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
        return float(np.sqrt(np.mean(samples ** 2))) < threshold
    except Exception:
        return True


def synthesize(role_key: str, text: str, out_path, retries: int = 3, text_language: str = "ja") -> bool:
    """调用 GPT-SoVITS 合成 text，保存 wav 到 out_path。返回是否成功。

    首次启动服务需加载模型（约 1-2 分钟），合成前会等待服务就绪（最多 180s）。
    合成结果会检测静音（GPT-SoVITS 偶发静音），静音则重试。
    """
    ref = role_ref(role_key)
    if not ref or not ref["ref_wav"]:
        return False
    # 空文本不合成
    if not text or not text.strip():
        return False
    # 日语文本预处理：顿号/空格 → 句号（避免 GPT-SoVITS 合成静音）
    if text_language == "ja":
        text = _preprocess_ja_text(text)
        # 长文本按句拆行，规避服务端单行 54s 静默截断（否则只念出一部分）
        text = _split_ja_for_sovits(text)
    # 确保服务已启动并等待就绪
    if not _service_alive():
        ensure_running()
        if not _wait_service_ready():
            return False
    params = {
        "refer_wav_path": ref["ref_wav"],
        "prompt_text": ref["prompt_text"],
        "prompt_language": ref["prompt_lang"],
        "text": text,
        "text_language": text_language,
        "top_k": 15,
        "top_p": 1.0,
        "temperature": 1.0,
        "speed": 1.0,
    }
    url = SOVITS_URL + "/?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()
            # 有效 wav 且非静音才算成功
            if len(data) > 44 and not _wav_is_silent(data):
                Path(out_path).write_bytes(data)
                return True
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(1)
    return False


def _trim_leading_silence(audio: np.ndarray, sr: int, threshold: float = 0.01, keep_before: float = 0.02) -> np.ndarray:
    """去除开头静音段（GPT-SoVITS 合成结果开头有约 0.5-0.6s 静音）。"""
    frame = max(1, int(sr * 0.01))  # 10ms 帧
    for i in range(0, len(audio) - frame, frame):
        if float(np.sqrt(np.mean(audio[i:i + frame] ** 2))) > threshold:
            start = max(0, i - int(sr * keep_before))
            return audio[start:]
    return audio  # 全静音，保持原样


def _fire_started(on_started):
    """触发「声音真正开始」回调；回调里出错不能连带把播放搞崩。"""
    if on_started is not None:
        try:
            on_started()
        except Exception:  # noqa: BLE001
            pass


def play_wav(path, on_started=None) -> float:
    """播放 wav（去开头静音后），返回时长（秒）。

    优先用 sounddevice 流式分块播放：每块写入前应用最新音量，实现播放中拖动滑块实时调音量；
    sounddevice 不可用（设备异常等）时回退 winsound 一次性播放。

    `on_started`：**声音真正开始**的那一刻回调（可选）。调用方靠它把「界面显示文字」
    与「听到声音」对齐 —— 打开设备（`sd.OutputStream`）、读文件等耗时都发生在那之前，
    若在调用本函数**之前**就显示文字，真机上会「先看见字、后听见声」（实测差 0.5s 以上）。
    所以界面文字必须挂在这个回调上，而不是 play 之前。
    """
    with wave.open(str(path), "rb") as f:
        sr = f.getframerate()
        n = f.getnframes()
        data = f.readframes(n)
    audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    # 去掉合成结果开头的静音，避免"开头丢字"（用原始振幅判断，避免音量小影响裁剪）
    audio = _trim_leading_silence(audio, sr)
    # 开头补 80ms 静音，兜底设备启动延迟（先于 on_started 送进缓冲 = 设备暖机，
    # 于是 on_started 之后紧接着就是人声，不会把这段静音算成额外的「文字先行」）
    lead = np.zeros(int(sr * 0.08), dtype=np.float32)
    duration = (len(lead) + len(audio)) / sr if sr else 0.0  # 实际播放时长（trim + lead 后）

    # 流式分块播放：每块实时应用当前音量（音量 > 0 时始终有声，只是轻重不同）
    CHUNK_SEC = 0.1  # 每 100ms 一块，音量变化约 100ms 内生效
    chunk = max(1, int(sr * CHUNK_SEC))
    try:
        import sounddevice as sd
        stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32", blocksize=chunk)
        stream.start()
        try:
            # 前导静音先入缓冲（此时设备已在跑），随后立刻回调「声音开始」——
            # 这一刻之后紧接着就是人声，界面文字此刻出现才叫「同刻」。
            stream.write((lead * _effective_volume()).astype(np.float32))
            _fire_started(on_started)
            for start in range(0, len(audio), chunk):
                seg = audio[start:start + chunk]
                # 实时读取最新音量/静音状态（拖动滑块或点击喇叭时下一块立即生效）
                seg = (seg * _effective_volume()).astype(np.float32)
                stream.write(seg)
        finally:
            stream.stop()
            stream.close()
        return duration
    except Exception:
        pass

    # 回退：winsound 一次性播放（异步 + 按时长等待，避免同步播放被拖动打断）
    import winsound
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        _write_wav_mono(tmp, np.concatenate([lead, audio]) * _effective_volume(), sr)
        winsound.PlaySound(tmp, winsound.SND_FILENAME | winsound.SND_ASYNC)
        _fire_started(on_started)  # 异步播放已下发 → 声音从这里开始
        time.sleep(duration + 0.15)  # 略加余量，覆盖异步启动延迟
    finally:
        try:
            winsound.PlaySound(None, 0)
        except Exception:
            pass
        try:
            os.remove(tmp)
        except OSError:
            pass
    return duration


def synthesize_to_file(role_key: str, text: str, text_language: str = "ja", target_rms=None):
    """合成到临时文件，返回路径；失败返回 None。调用方负责删除文件。

    target_rms 非空时，把合成音频响度（RMS）对齐到该值，用于与预录制音频（邦邦卡邦）响度统一。
    """
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    if synthesize(role_key, text, tmp, text_language=text_language):
        if target_rms and target_rms > 0:
            try:
                samples, sr = _read_wav_mono(tmp)
                samples = _normalize_to_rms(samples, target_rms)
                _write_wav_mono(tmp, samples, sr)
            except Exception:
                pass
        return tmp
    try:
        os.remove(tmp)
    except OSError:
        pass
    return None


def _read_wav_mono(path):
    """读 wav，返回 (float32 单声道 samples, 采样率)。"""
    with wave.open(str(path), "rb") as f:
        sr = f.getframerate()
        ch = f.getnchannels()
        data = f.readframes(f.getnframes())
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        samples = samples.reshape(-1, ch).mean(axis=1)
    return samples, sr


def _normalize_to_rms(audio: np.ndarray, target_rms: float) -> np.ndarray:
    """把音频响度（RMS）按比例缩放到 target_rms，用于让合成音频与预录制音频响度一致。"""
    if not target_rms or target_rms <= 0:
        return audio
    cur = float(np.sqrt(np.mean(audio ** 2)))
    if cur <= 0:
        return audio
    gain = target_rms / cur
    return (audio * gain).astype(np.float32)


# 邦邦卡邦预录制音频响度（RMS）缓存：{role_key: float | None}
_bang_rms_cache = {}


def _bang_loudness_rms(role_key: str):
    """计算 voices/{role_key}/邦邦卡邦/ 下预录制音频的平均 RMS，作为响度对齐基准。

    无预录制音频（如艾莲）返回 None，表示不做响度归一化。结果缓存，避免每次播放都读文件。
    """
    if role_key in _bang_rms_cache:
        return _bang_rms_cache[role_key]
    import glob
    files = glob.glob(str(BASE_DIR / "voices" / role_key / "邦邦卡邦" / "*.wav"))
    rms_list = []
    for f in files:
        try:
            samples, _sr = _read_wav_mono(f)
            rms = float(np.sqrt(np.mean(samples ** 2)))
            if rms > 0:
                rms_list.append(rms)
        except Exception:
            continue
    target = float(np.mean(rms_list)) if rms_list else None
    _bang_rms_cache[role_key] = target
    return target


def _resample(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """线性插值重采样到目标采样率。"""
    if src_sr == dst_sr:
        return samples
    n_out = max(1, int(len(samples) * dst_sr / src_sr))
    x_old = np.linspace(0.0, 1.0, len(samples), endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


def _write_wav_mono(path, samples: np.ndarray, sr: int):
    """写 float32 单声道 samples 到 wav。"""
    audio16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(audio16.tobytes())


def synthesize_with_bang(role_key: str, text: str, text_language: str = "ja"):
    """合成日语语音；若含"ばんばかばん"（邦邦卡邦），该部分用 voices/邦邦卡邦/ 下随机预录制音频替换。

    返回临时文件路径或 None（调用方负责删除）。
    """
    BANG = "ばんばかばん"
    # 响度对齐基准：合成音频对齐到邦邦卡邦预录制音频的 RMS（无则 None，不归一化）
    target_rms = _bang_loudness_rms(role_key)
    if BANG not in text:
        return synthesize_to_file(role_key, text, text_language, target_rms=target_rms)
    import glob
    import random
    bang_files = glob.glob(str(BASE_DIR / "voices" / role_key / "邦邦卡邦" / "*.wav"))
    bang_path = random.choice(bang_files) if bang_files else None
    TARGET_SR = 32000
    audio_segments = []
    parts = text.split(BANG)
    for i, part in enumerate(parts):
        if part.strip():
            tmp = synthesize_to_file(role_key, part, text_language, target_rms=target_rms)
            if tmp:
                seg, sr = _read_wav_mono(tmp)
                audio_segments.append(_resample(seg, sr, TARGET_SR))
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        if i < len(parts) - 1 and bang_path:
            # 邦邦卡邦段保持原响度（它本身就是基准，不再归一化）
            seg, sr = _read_wav_mono(bang_path)
            audio_segments.append(_resample(seg, sr, TARGET_SR))
    if not audio_segments:
        return None
    audio = np.concatenate(audio_segments)
    fd, out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    _write_wav_mono(out, audio, TARGET_SR)
    return out


def speak(role_key: str, text: str, on_done=None):
    """后台线程：合成日语语音并播放。on_done(ok, duration_seconds)。"""
    def worker():
        fd, tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            ok = synthesize(role_key, text, tmp)
            if not ok:
                if on_done:
                    on_done(False, 0.0)
                return
            duration = play_wav(tmp)
            if on_done:
                on_done(True, duration)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    threading.Thread(target=worker, daemon=True).start()
