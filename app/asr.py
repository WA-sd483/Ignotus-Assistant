"""本地语音识别：sherpa-onnx SenseVoice（离线）+ silero VAD + 麦克风监听。"""
import threading
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx
import sounddevice as sd

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / "models"
SAMPLE_RATE = 16000


def find_model_dir(base: Path = MODEL_DIR) -> Path:
    """在 models 目录里定位含 model.int8.onnx 与 tokens.txt 的目录。"""
    if (base / "model.int8.onnx").exists() and (base / "tokens.txt").exists():
        return base
    for d in sorted(base.glob("*")):
        if d.is_dir() and (d / "model.int8.onnx").exists() and (d / "tokens.txt").exists():
            return d
    raise FileNotFoundError(f"未找到识别模型（model.int8.onnx / tokens.txt）于 {base}")


def read_wav(wav_path) -> tuple[np.ndarray, int]:
    """读取 wav，返回 (float32 样本, 采样率)。"""
    with wave.open(str(wav_path), "rb") as f:
        sr = f.getframerate()
        channels = f.getnchannels()
        data = f.readframes(f.getnframes())
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, sr


class Recognizer:
    """SenseVoice 离线识别。"""

    def __init__(self, model_dir: Path | None = None, language: str = "zh"):
        d = Path(model_dir) if model_dir else find_model_dir()
        self._rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(d / "model.int8.onnx"),
            tokens=str(d / "tokens.txt"),
            num_threads=4,
            use_itn=True,
            language=language,  # 强制中文识别，避免误识别成日文
        )

    def transcribe_samples(self, samples: np.ndarray, sample_rate: int) -> str:
        stream = self._rec.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self._rec.decode_stream(stream)
        return stream.result.text.strip()

    def transcribe_file(self, wav_path) -> str:
        samples, sr = read_wav(wav_path)
        return self.transcribe_samples(samples, sr)


class MicListener:
    """麦克风监听：VAD 分段 + SenseVoice 识别，识别结果经 on_text 回调（后台线程）。"""

    def __init__(self, recognizer: Recognizer, on_text, vad_model: Path | None = None):
        self.recognizer = recognizer
        self.on_text = on_text
        self._vad_model = Path(vad_model) if vad_model else (MODEL_DIR / "silero_vad.onnx")
        self._running = False
        self._thread: threading.Thread | None = None
        self._stream = None
        self._vad = self._create_vad()

    def _create_vad(self):
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(self._vad_model)
        config.silero_vad.threshold = 0.5
        config.silero_vad.min_silence_duration = 0.35  # 静音判定缩短，更快识别"说完了"
        config.silero_vad.min_speech_duration = 0.25
        config.sample_rate = SAMPLE_RATE
        return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        # 主动中断阻塞中的 stream.read，让线程尽快退出
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None

    def _run(self):
        samples_per_read = int(0.1 * SAMPLE_RATE)  # 每次读 100ms
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                blocksize=samples_per_read,
            )
            self._stream.start()
            while self._running:
                samples, _ = self._stream.read(samples_per_read)
                samples = samples.reshape(-1).astype(np.float32)
                self._vad.accept_waveform(samples)
                while not self._vad.empty():
                    seg = self._vad.front
                    text = self.recognizer.transcribe_samples(seg.samples, SAMPLE_RATE)
                    self._vad.pop()
                    if text:
                        self.on_text(text)
        except Exception as e:  # noqa: BLE001
            # 主动退出导致的异常不打印，避免"关闭软件后显示麦克风出错"
            if self._running:
                print("麦克风监听出错：", e)
        finally:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:  # noqa: BLE001
                    pass
                self._stream = None
