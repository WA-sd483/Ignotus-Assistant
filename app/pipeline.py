"""回复流水线：日语**整段**合成，与中文就绪后**同刻**输出（文字与语音同步）。

为什么从「按句流式」改成「整段」（上一版实测的教训）：

- **按句流式**：日语凑够一句就合成一句、播放一句。每句都要一次 HTTP + 一次 `play_wav`，
  而 `play_wav` 每次都要重开音频流、并在开头补 80ms 前导静音 —— 于是句与句之间
  能听出明显停顿（用户反馈「一顿一顿」）。
- **整段**：日语段一吐完（分界符出现）就**整段一次**送去合成。GPT-SoVITS 服务端会把
  内部按行拆分的文本拼接成同一段音频（`api.py: text.split("\\n")`），所以整段是
  **无缝**的，而且只 `play_wav` 一次。

时序（关键：合成与「中文段的生成」**并行**，所以「无缝」不等于「变慢」）：

    AI 流式：  日语吐完(分界符) ───────────────► 中文吐完(done)
                      │                              │
    合成线程：         └── 合成整段日语 ──┐           │
                                       ▼           ▼
                          两者都就绪 → play_wav ──► on_started() ──► on_finished()

「文字与声音同刻出现」是靠 **play 回调**保证的：开场时刻 = `max(合成完, 中文吐完)`
（`release_text_gate()`），而**界面文字要等到声音真正开始才显示** —— 有音频时
`reveal` 由 `play` 在「设备已打开、人声即将出来」处回调（见 `tts.play_wav`），
绝不能在 `play` 之前调，否则会「先看见字、后听见声」。没有音频（静音 / 合成失败）
时就地回调，文字照常出现，只是没声音。

`synth / play / remove / should_start` 一律以函数注入，本模块**不 import tts**：
避免循环依赖，也让冒烟测试能用假函数把整条时序卡准。
"""
import threading

# 中文迟迟不来时的兜底：不能把合成线程无限期挂在闸门上
_GATE_TIMEOUT = 60.0
# 没有音频可播（静音 / 静音模式 / 合成失败）时，「说话态」该持续多久（秒）。
# **按文本长度自适应**：取实测的「音频时长 ≈ 0.22 s/字（日语）」—— 这样静音与出声两种
# 模式下说话态的持续时间是一致的（原先是固定 1.2s，长回复的说话动画一闪就没了）。
_SILENT_MIN = 1.2
_SILENT_PER_CHAR = 0.22


def silent_hold_seconds(text: str) -> float:
    """没有真实音频时，用文本长度估算「说完这段大约要多久」（秒）。

    标定来自 `devlog/2026-09-16.md` §一：9 个实测样本点拟合出**音频时长 ≈ 0.22·N 秒**
    （N = 日语字数）。短文本保留 `_SILENT_MIN` 下限，别让「嗯。」这种一闪而过。
    """
    n = len((text or "").strip())
    return max(_SILENT_MIN, _SILENT_PER_CHAR * n)


class SpeakPipeline:
    """把「一整段日语」变成「一段无缝语音」，并与中文**同刻**输出。

    用法（生成侧，通常是 AI 流式回调）：

        pipe = SpeakPipeline(synth=..., play=..., on_started=..., on_finished=...)
        pipe.speak("おはよう。今日はいい天気ですね。")   # 分界符一到就整段提交（只调一次）
        pipe.release_text_gate()                        # 中文吐完时调（幂等）

    `play` 的契约是 `play(path, on_started)`：**必须**在声音真正开始处调用
    `on_started()`（`tts.play_wav` 已经这么做）。若不回调，流水线会在 `play`
    返回后补一次 —— 宁可文字晚一点，也不能把回复吞掉。

    回调都在**工作线程**里调用，实现方要自己保证跨线程安全（本项目里是往 Qt 信号里 emit）。
    """

    def __init__(self, synth, play, remove=None, on_started=None, on_finished=None,
                 should_start=None, gate_timeout: float = _GATE_TIMEOUT,
                 silent_hold=silent_hold_seconds):
        self._synth = synth                    # (text) -> wav 路径 | None
        self._play = play                      # (path, on_started) -> None
        self._remove = remove or (lambda p: None)   # (path) -> None，清理临时文件
        self._on_started = on_started          # 「文字与声音同刻出现」的那一刻（只调一次）
        self._on_finished = on_finished        # 播放结束（或本来就没有声音可播）
        self._should_start = should_start      # () -> bool，开场前最后一道许可（可空）
        self._gate_timeout = gate_timeout
        # silent_hold：没有音频时的说话态时长。可以是**秒数**（测试注入固定值），
        # 也可以是 `(text) -> 秒数` 的函数（默认 `silent_hold_seconds`，按文本长度自适应）。
        self._silent_hold = silent_hold
        self._gate = threading.Event()         # 开场闸门：中文吐完才放行
        self._cancel = threading.Event()
        self._started = threading.Event()
        self._thread = None

    # ---------- 生产侧（AI 流式线程 / 主线程）----------

    def speak(self, text):
        """提交**整段**日语并起合成线程（分界符出现时调一次；空文本 → 只走节拍、不出声）。

        重复调用只认第一次 —— 一条回复只会有一段语音。
        """
        if self._thread is not None:
            return
        t = (text or "").strip()
        self._thread = threading.Thread(target=self._run, args=(t,), daemon=True)
        self._thread.start()

    def release_text_gate(self):
        """中文已吐完 → 放行开场（保证「文字与声音同时出现」）。幂等。"""
        self._gate.set()

    def cancel(self):
        """中止这一条流水线（换了一条新回复 / 回退到非流式路径）。

        中止后不再触发 `on_started` / `on_finished` —— 界面交给接替者去管，
        免得两个来源同时改状态。
        """
        if self._cancel.is_set():
            return
        self._cancel.set()
        self._gate.set()        # 别让合成线程卡在闸门上

    @property
    def has_started(self) -> bool:
        """是否已经开场（用于判断「回退重试会不会把同一段念两遍」）。"""
        return self._started.is_set()

    # ---------- 合成线程 ----------

    def _run(self, text):
        path = None
        if text and not self._cancel.is_set():
            try:
                path = self._synth(text)
            except Exception:  # noqa: BLE001
                path = None     # 合成失败不该把线程带崩：文字照常显示，只是没声音
        if self._cancel.is_set():
            self._cleanup(path)
            return
        # 等「中文吐完」：合成已跑完就候在这里；中文先到则这里立刻返回。
        # 超时是兜底：万一 release_text_gate() 永远不来，也不能把线程挂死。
        self._gate.wait(self._gate_timeout)
        if self._cancel.is_set() or not self._allowed():
            self._cleanup(path)
            return

        def reveal():
            """「文字与声音同刻出现」的那一刻（只生效一次）。

            有音频时由 `play` 在**声音真正开始**处回调 —— 打开设备、读文件都发生在
            那之前，提前显示文字就会「先看见字、后听见声」。没有音频时立刻显示。
            """
            if self._started.is_set():
                return
            self._started.set()
            if self._on_started:
                self._safe(self._on_started)

        if path:
            try:
                self._play(path, reveal)
            except Exception:  # noqa: BLE001
                pass
            finally:
                # 保险：play 没回调（异常 / 老实现）也必须把文字放出来，不能把回复吞掉
                reveal()
                self._cleanup(path)
        else:
            # 没有音频：文字就地显示，再按「她说完这段大概要多久」留够说话态
            reveal()
            self._interruptible_sleep(self._hold_for(text))
        if self._cancel.is_set():
            return
        if self._on_finished:
            self._safe(self._on_finished)

    # ---------- 小工具 ----------

    def _hold_for(self, text) -> float:
        """没有音频时的「说话态」秒数。

        `silent_hold` 允许是**固定秒数**（测试注入，保证时序可预测）或
        **`(text) -> 秒数` 的函数**（默认按文本长度自适应，见 `silent_hold_seconds`）。
        函数抛异常时退回 `_SILENT_MIN`，绝不能因为算时长把收尾也带崩。
        """
        hold = self._silent_hold
        if callable(hold):
            try:
                return float(hold(text))
            except Exception:  # noqa: BLE001
                return _SILENT_MIN
        return float(hold)

    def _allowed(self) -> bool:
        """开场前的最后一道许可（`should_start` 为空时恒为真）。

        返回 False → 整条流水线静默作废：不显示文字、不出声、不回调 finished
        （界面交给接替者管）。判断本身抛异常时按「允许」走，别把回复吞掉。
        """
        if self._should_start is None:
            return True
        try:
            return bool(self._should_start())
        except Exception:  # noqa: BLE001
            return True

    def _cleanup(self, path):
        if path:
            self._safe(self._remove, path)

    def _interruptible_sleep(self, seconds):
        """可被 cancel 立刻打断的等待（取消后不必干等）。"""
        if seconds > 0:
            self._cancel.wait(seconds)

    @staticmethod
    def _safe(fn, *args):
        """回调 / 清理动作出错不能把工作线程带崩。"""
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            pass
