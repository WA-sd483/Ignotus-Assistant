"""测试语音识别：把 voices 里的一个语音样本转 wav 并识别。"""
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.asr import Recognizer  # noqa: E402


def main():
    candidates = (
        sorted(ROOT.glob("voices/*/*.mp3"))
        + sorted(ROOT.glob("voices/*/*.wav"))
        + sorted(ROOT.glob("voices/*/*.flac"))
        + sorted(ROOT.glob("voices/*/*.m4a"))
    )
    if not candidates:
        print("未找到语音样本（voices/ 下）")
        return

    for src in candidates[:3]:
        out = ROOT / "models" / "_test.wav"
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [ffmpeg, "-y", "-i", str(src), "-ar", "16000", "-ac", "1", "-f", "wav", str(out)],
            check=True, capture_output=True,
        )
        rec = Recognizer()
        text = rec.transcribe_file(out)
        print(f"[{src.parent.name}/{src.name}] -> {text}")


if __name__ == "__main__":
    main()
