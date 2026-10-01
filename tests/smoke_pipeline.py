# -*- coding: utf-8 -*-
"""冒烟测试：回复流水线（**整段**合成 + 与中文就绪后同刻输出）。

覆盖两块，都不联网、不发声：
  1. `app.pipeline.SpeakPipeline` —— 时序用假函数卡准（合成 / 播放 / 清理全是记录器）；
  2. 回复气泡的界面部分（`MainWindow.begin/finish_assistant_message`）。

重点盯的是「会静默坏掉、肉眼不易发现」的那些行为：
  - 日语必须**整段一次**提交合成（一旦退回逐句，就会重新出现句间停顿）；
  - 合成不许等闸门（否则就退回成"整段串行"，白做流水线）；
  - 开场必须等「中文吐完」（闸门），否则「先听见声音、过一会儿才看见字」；
  - 开场时刻必须是 max(合成完, 闸门开) —— 两个方向都要验；
  - 「揭示文字」必须由 `play` 在**声音真正开始**处回调，绝不能在 play 之前 ——
    否则真机上就是「先看见字、后听见声」（设备打开耗时被算成了文字抢跑）；
  - `play` 异常 / 忘了回调时也必须把文字揭示出来（回复不能被吞掉）；
  - `should_start` 说不许开场（API 被切走）时不出字、不出声、不收尾，但文件要清掉；
  - 没有任何音频时 started / finished 也必须触发，否则状态永远停在「思考中」；
  - 中止后不许再回调（否则两条回复同时改界面状态）；
  - 气泡宽度必须「短文本单行紧贴、长文本撑到上限（聊天区一半）就换行」，
    且**窗口变宽时已有气泡要跟着放宽** —— 不能停在旧宽度上（Qt 对换行标签的
    sizeHint 会猜一个很窄的宽度，长文本永远撑不到上限，所以实际宽度是钉死的）。
  - **系统消息必须换行且不参与「最小宽度」诉求**：否则它那条单行宽会把滚动区内容顶到
    视口之外，水平滚动条又是关的 ⇒ 靠右的用户气泡右端被裁掉（看着像「向右偏移、只剩左半」）。

跑法（在项目根目录）：
    .venv\\Scripts\\python.exe tests\\smoke_pipeline.py
"""
import ast
import os
import sys
import tempfile
import threading
import time
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


def wait_until(pred, timeout=3.0, step=0.01):
    """轮询等待条件成立（流水线是异步的，只能等）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return pred()


from app.pipeline import SpeakPipeline  # noqa: E402


class Recorder:
    """假 synth / play / remove：把调用记下来，并可控地失败或变慢。"""

    def __init__(self, delays=None):
        self.events = []
        self.synths = []
        self.plays = []
        self.removed = []
        self._delays = delays or {}
        self.lock = threading.Lock()

    def synth(self, text):
        with self.lock:
            self.synths.append(text)
        delay = self._delays.get(text, 0.0)
        if delay:
            time.sleep(delay)
        return f"wav::{text}"

    def play(self, path, on_started=None):
        """假播放：契约是「在声音真正开始处回调 on_started」。"""
        with self.lock:
            self.plays.append(path)
        if on_started is not None:
            on_started()

    def remove(self, path):
        with self.lock:
            self.removed.append(path)


def boom(_path, _on_started=None):
    raise RuntimeError("设备炸了")


# ========== 1. 整段一次合成，且合成不等闸门 ==========
print("== 1. 整段一次合成；合成照跑、播放等闸门 ==")
rec = Recorder()
pipe = SpeakPipeline(synth=rec.synth, play=rec.play, remove=rec.remove)
TEXT = "おはよう。今日はいい天気ですね。"
pipe.speak(TEXT)
check("只提交一次合成", wait_until(lambda: len(rec.synths) == 1), str(rec.synths))
check("合成的是**整段**（没有被拆成一句句）", rec.synths == [TEXT], str(rec.synths))
time.sleep(0.1)
check("闸门没开 → 一次都不播（合成照跑）", rec.plays == [], str(rec.plays))
pipe.release_text_gate()
check("闸门一开就播", wait_until(lambda: len(rec.plays) == 1), str(rec.plays))
check("**只播一次**（整段无缝，不是逐句播）", rec.plays == [f"wav::{TEXT}"], str(rec.plays))
check("播完清理临时文件", rec.removed == rec.plays, str(rec.removed))


# ========== 2. 开场被闸门挡住（同步不变式）==========
print("== 2. on_started 被闸门挡住（文字与声音同刻）==")
rec = Recorder()
started, finished = [], []
pipe = SpeakPipeline(synth=rec.synth, play=rec.play, remove=rec.remove,
                     on_started=lambda: started.append(time.monotonic()),
                     on_finished=lambda: finished.append(1))
pipe.speak("一整段日语。")
check("合成已完成", wait_until(lambda: len(rec.synths) == 1), str(rec.synths))
time.sleep(0.2)
check("闸门未开：不开场、不播放（等于界面不出字）",
      started == [] and rec.plays == [], str((started, rec.plays)))
check("has_started 仍是 False（回退判断要用）", pipe.has_started is False)
pipe.release_text_gate()
check("闸门一开立刻开场", wait_until(lambda: len(started) == 1), str(started))
check("has_started 变 True", wait_until(lambda: pipe.has_started), str(pipe.has_started))
check("on_started 只触发一次", len(started) == 1, str(started))
check("播完会收尾 finished", wait_until(lambda: len(finished) == 1), str(finished))


# ========== 3. 开场时刻 = max(合成完, 闸门开) ==========
print("== 3. 开场时刻 = max(合成完, 闸门开) ==")
# 3a. 合成慢（0.30s）、闸门立刻开 → 必须等合成
rec = Recorder(delays={"慢段。": 0.30})
started = []
pipe = SpeakPipeline(synth=rec.synth, play=rec.play, remove=rec.remove,
                     on_started=lambda: started.append(time.monotonic()))
t0 = time.monotonic()
pipe.speak("慢段。")
pipe.release_text_gate()
ok = wait_until(lambda: len(started) == 1, 1.5)
dt = (started[0] - t0) if started else None
check("合成慢 → 等合成完才开场（>= 0.25s）", ok and dt is not None and dt >= 0.25, str(dt))

# 3b. 合成快、闸门晚到（0.30s）→ 必须等闸门
rec = Recorder()
started = []
pipe = SpeakPipeline(synth=rec.synth, play=rec.play, remove=rec.remove,
                     on_started=lambda: started.append(time.monotonic()))
t0 = time.monotonic()
pipe.speak("快段。")
timer = threading.Timer(0.30, pipe.release_text_gate)
timer.start()
ok = wait_until(lambda: len(started) == 1, 1.5)
dt = (started[0] - t0) if started else None
check("合成快 → 等中文（闸门）才开场（>= 0.25s）", ok and dt is not None and dt >= 0.25, str(dt))
check("合成确实早于开场完成（真并行，不是串行）", rec.synths == ["快段。"], str(rec.synths))
timer.cancel()


# ========== 4. 揭示文字的时机 = play 回调（不能抢在声音前面）==========
print("== 4. 文字在「声音开始」那一刻才揭示（不能抢跑）；should_start 闸门 ==")
order = []


def play_with_cb(path, on_started=None):
    order.append("play_enter")
    if on_started:
        on_started()
    order.append("play_exit")


pipe = SpeakPipeline(synth=lambda t: "wav", play=play_with_cb, remove=lambda p: None,
                     on_started=lambda: order.append("reveal"))
pipe.speak("一整段。")
pipe.release_text_gate()
check("揭示发生在 play **内部**（= 声音开始时，不会先出字后出声）",
      wait_until(lambda: order[:3] == ["play_enter", "reveal", "play_exit"]), str(order))

# play 忘了回调 → 流水线必须在 play 返回后补一次（宁可文字晚一点，也不能把回复吞掉）
order2 = []
pipe = SpeakPipeline(synth=lambda t: "wav", play=lambda p, on_started=None: order2.append("play_enter"),
                     remove=lambda p: None, on_started=lambda: order2.append("reveal"))
pipe.speak("一整段。")
pipe.release_text_gate()
check("play 没回调时补一次揭示（回复不会被吞掉）",
      wait_until(lambda: order2 == ["play_enter", "reveal"]), str(order2))

# API 被切走 / 回退重试：should_start 说不许开场 → 不出字、不出声、不收尾
rec = Recorder()
hit = {"started": 0, "finished": 0}
pipe = SpeakPipeline(synth=rec.synth, play=rec.play, remove=rec.remove,
                     on_started=lambda: hit.__setitem__("started", hit["started"] + 1),
                     on_finished=lambda: hit.__setitem__("finished", hit["finished"] + 1),
                     should_start=lambda: False)
pipe.speak("一整段。")
pipe.release_text_gate()
time.sleep(0.2)
check("should_start=False → 不出字、不出声",
      hit["started"] == 0 and rec.plays == [], str((hit, rec.plays)))
check("should_start=False → 不触发 finished（界面交给接替者）", hit["finished"] == 0, str(hit))
check("should_start=False → 合成出的文件仍被清理", rec.removed == ["wav::一整段。"], str(rec.removed))

# should_start 自己抛异常 → 按「允许」处理（判断出错不能把回复吞掉）
rec = Recorder()
hit = {"started": 0}
pipe = SpeakPipeline(synth=rec.synth, play=rec.play, remove=rec.remove,
                     on_started=lambda: hit.__setitem__("started", hit["started"] + 1),
                     should_start=lambda: 1 / 0)
pipe.speak("一整段。")
pipe.release_text_gate()
check("should_start 抛异常时按允许处理（不吞回复）",
      wait_until(lambda: hit["started"] == 1), str(hit))


# ========== 5. 一句音频都没有时也要开场 / 收尾 ==========
print("== 5. 没有音频（静音 / 合成失败）==")
rec = Recorder()
hit = {"started": 0, "finished": 0}
pipe = SpeakPipeline(synth=lambda t: None, play=rec.play, remove=rec.remove,
                     on_started=lambda: hit.__setitem__("started", hit["started"] + 1),
                     on_finished=lambda: hit.__setitem__("finished", hit["finished"] + 1),
                     silent_hold=0.05)
pipe.speak("有字但不出声。")
time.sleep(0.15)
check("闸门没开时不算开场（不能抢在文字前面）", hit["started"] == 0, str(hit))
pipe.release_text_gate()
check("闸门开后照样触发 started", wait_until(lambda: hit["started"] == 1), str(hit))
check("并且会收尾 finished（否则状态永远停在思考中）",
      wait_until(lambda: hit["finished"] == 1), str(hit))
check("没有声音可播 → 一次播放都没有", rec.plays == [], str(rec.plays))


# ========== 6. 中止：不再回调、不再播放、合成出的文件要清掉 ==========
print("== 6. cancel 中止 ==")
rec = Recorder(delays={"慢段。": 0.4})
hit = {"started": 0, "finished": 0}
pipe = SpeakPipeline(synth=rec.synth, play=rec.play, remove=rec.remove,
                     on_started=lambda: hit.__setitem__("started", hit["started"] + 1),
                     on_finished=lambda: hit.__setitem__("finished", hit["finished"] + 1))
pipe.speak("慢段。")
wait_until(lambda: len(rec.synths) == 1)
pipe.cancel()                      # 合成还在飞的时候中止
check("中止后不触发 started",
      wait_until(lambda: len(rec.removed) >= 1, 1.0) and hit["started"] == 0, str(hit))
check("中止后不触发 finished", hit["finished"] == 0, str(hit))
check("中止后不播放", rec.plays == [], str(rec.plays))
check("飞在半路的合成结果被清理（不留临时文件）", rec.removed == ["wav::慢段。"], str(rec.removed))

# 等在闸门上的合成线程要被 cancel **立刻**唤醒（而不是干等 gate_timeout）
rec = Recorder()
hit = {"started": 0}
pipe = SpeakPipeline(synth=rec.synth, play=rec.play, remove=rec.remove,
                     on_started=lambda: hit.__setitem__("started", hit["started"] + 1),
                     gate_timeout=30.0)
pipe.speak("等着。")
wait_until(lambda: len(rec.synths) == 1)
pipe.cancel()
check("cancel 能立刻叫醒等闸门的线程（不干等 30s 超时）",
      wait_until(lambda: rec.removed == ["wav::等着。"], 1.0) and hit["started"] == 0,
      str((rec.removed, hit)))


# ========== 7. 边界：空文本 / 重复 speak / 播放失败 / 幂等 ==========
print("== 7. 边界行为 ==")
rec = Recorder()
hit = {"started": 0, "finished": 0}
pipe = SpeakPipeline(synth=rec.synth, play=rec.play, remove=rec.remove,
                     on_started=lambda: hit.__setitem__("started", hit["started"] + 1),
                     on_finished=lambda: hit.__setitem__("finished", hit["finished"] + 1),
                     silent_hold=0.02)
pipe.speak("   ")
check("空文本不合成", rec.synths == [], str(rec.synths))
pipe.release_text_gate()
check("空文本仍会开场 + 收尾（界面不会卡在思考中）",
      wait_until(lambda: hit["started"] == 1 and hit["finished"] == 1), str(hit))

rec = Recorder()
pipe = SpeakPipeline(synth=rec.synth, play=rec.play, remove=rec.remove)
pipe.speak("第一次。")
pipe.speak("第二次。")
pipe.release_text_gate()
wait_until(lambda: len(rec.plays) == 1)
time.sleep(0.1)
check("一条回复只合成 / 播放一次（重复 speak 被忽略）",
      rec.synths == ["第一次。"] and rec.plays == ["wav::第一次。"], str((rec.synths, rec.plays)))

rec2 = Recorder()
hit2 = {"finished": 0, "started": 0}
pipe2 = SpeakPipeline(synth=rec2.synth, play=boom, remove=rec2.remove,
                      on_started=lambda: hit2.__setitem__("started", hit2["started"] + 1),
                      on_finished=lambda: hit2.__setitem__("finished", hit2["finished"] + 1))
pipe2.speak("一。")
pipe2.release_text_gate()
check("播放抛异常仍会收尾", wait_until(lambda: hit2["finished"] == 1), str(hit2))
check("播放抛异常时文字照样揭示（回复不会被吞掉）", hit2["started"] == 1, str(hit2))
check("播放抛异常仍会清理临时文件", rec2.removed == ["wav::一。"], str(rec2.removed))

pipe3 = SpeakPipeline(synth=rec2.synth, play=rec2.play, remove=rec2.remove)
pipe3.release_text_gate()
pipe3.release_text_gate()
pipe3.cancel()
pipe3.cancel()
check("release / cancel 幂等，不抛异常", True)


# ========== 8. 回复气泡：一次性出现 + 聊天记录 ==========
print("== 8. 界面：回复气泡一次性出现 + 聊天记录 ==")
import app.config as cfgmod  # noqa: E402

tmp_dir = Path(tempfile.mkdtemp(prefix="ignotus_pipeline_smoke_"))
cfgmod.CONFIG_PATH = tmp_dir / "config.json"
cfg = cfgmod.load_config()

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import gui  # noqa: E402

qapp = QApplication.instance() or QApplication(sys.argv)

win = gui.MainWindow(cfg)
win.show()
qapp.processEvents()
role = cfg.get("current_role", "alice")

FULL = "今天天气不错，要不要一起出去走走？"
win.begin_assistant_message(role, "爱丽丝", FULL)
qapp.processEvents()
qapp.processEvents()
bubbles = win._chat_view._container.findChildren(gui._Bubble)
check("气泡里一次就是完整文本（不再逐段回填）",
      bool(bubbles) and bubbles[-1]._lbl.text() == FULL, [b._lbl.text() for b in bubbles][-1:])
check("气泡已按完整文本撑开（不是半截高度）", bool(bubbles) and bubbles[-1].height() > 20,
      str(bubbles[-1].height() if bubbles else None))

before = len(win._chat_history.get(role, []))
win.finish_assistant_message(role, FULL)
hist = win._chat_history.get(role, [])
check("收尾时以完整中文写进聊天记录",
      len(hist) == before + 1 and hist[-1]["role"] == "assistant" and hist[-1]["text"] == FULL,
      str(hist[-1:]))
win.finish_assistant_message(role, "   ")
check("空白最终文字不写进聊天记录", len(win._chat_history.get(role, [])) == before + 1,
      str(win._chat_history.get(role, [])[-1:]))

# 非流式 / 回退路径：`add_assistant_message` 建气泡并落记录（等价于「建 + 收尾」）
n_before = len(win._chat_view._container.findChildren(gui._Bubble))
win.add_assistant_message(role, "爱丽丝", "回退路径的整段回复。")
qapp.processEvents()
qapp.processEvents()
n_after = len(win._chat_view._container.findChildren(gui._Bubble))
check("非流式路径也建气泡", n_after == n_before + 1, f"{n_before} -> {n_after}")
check("非流式路径也落聊天记录",
      win._chat_history.get(role, [])[-1]["text"] == "回退路径的整段回复。",
      str(win._chat_history.get(role, [])[-1:]))


# ========== 9. 气泡宽度：短文本单行紧贴、长文本撑到聊天区中线 ==========
print("== 9. 气泡宽度：单行紧贴 / 长文本撑到中线 ==")
cv = win._chat_view
qapp.processEvents()

SHORT_TXT = "收到，老师。"
LONG_TXT = ("今天天气不错，要不要一起出去走走？顺路可以看看新开的那家书店，"
            "听说里面有一整面墙的推理小说。")

half = cv._content_width() // 2
check("用户侧上限 = 聊天区可用宽的一半（左右平分）",
      cv.bubble_max_width("user") == max(cv.MIN_BUBBLE_W, half),
      f"{cv.bubble_max_width('user')} vs {max(cv.MIN_BUBBLE_W, half)}")
check("角色侧上限再扣掉头像占位（36+10），两侧气泡内边缘才都落在中线上",
      cv.bubble_max_width("assistant")
      == max(cv.MIN_BUBBLE_W, half - cv.AVATAR_W - cv.AVATAR_GAP),
      str(cv.bubble_max_width("assistant")))

b_us = cv.add_bubble("user", "你", SHORT_TXT)
b_ul = cv.add_bubble("user", "你", LONG_TXT)
b_as = cv.add_bubble("assistant", "爱丽丝", SHORT_TXT, role_key=role)
b_al = cv.add_bubble("assistant", "爱丽丝", LONG_TXT, role_key=role)
for _ in range(3):
    qapp.processEvents()

check("短文本：气泡宽度 = 单行自然宽（紧贴文字，没被撑到上限）",
      b_us.fit_width_value == cv._natural_width(SHORT_TXT)
      and b_us.fit_width_value < cv.bubble_max_width("user"),
      f"{b_us.fit_width_value} / nat {cv._natural_width(SHORT_TXT)} / max {cv.bubble_max_width('user')}")
check("短文本：真的渲染成一行（高度 < 长文本气泡）",
      b_us._lbl.height() < b_ul._lbl.height(),
      f"{b_us._lbl.height()} vs {b_ul._lbl.height()}")
check("长文本：气泡撑到上限才换行（用户侧）",
      b_ul.fit_width_value == cv.bubble_max_width("user"), str(b_ul.fit_width_value))
check("长文本：气泡撑到上限才换行（角色侧，上限已扣头像）",
      b_al.fit_width_value == cv.bubble_max_width("assistant"), str(b_al.fit_width_value))
check("两侧气泡的「内边缘」对齐同一条中线（左边缘宽度差 = 头像占位）",
      b_ul.fit_width_value - b_al.fit_width_value == cv.AVATAR_W + cv.AVATAR_GAP,
      f"{b_ul.fit_width_value} - {b_al.fit_width_value}")
cv.show_thinking("爱丽丝", role_key=role)
qapp.processEvents()
think = cv._thinking_row.findChildren(gui._Bubble)[-1] if cv._thinking_row else None
check("「正在思考...」气泡短文本单行紧贴、不超过上限",
      think is not None and think.fit_width_value <= cv.bubble_max_width("assistant"),
      str(think.fit_width_value if think else None))
cv.hide_thinking()
qapp.processEvents()

# 窗口变宽 → 已有气泡跟着放宽（而不是停在旧宽度上）
wide_before = b_ul.fit_width_value
win.resize(1200, 540)
for _ in range(3):
    qapp.processEvents()
check("窗口变宽后，已有气泡的上限与宽度一起更新",
      b_ul.fit_width_value == cv.bubble_max_width("user")
      and b_ul.fit_width_value > wide_before,
      f"{wide_before} -> {b_ul.fit_width_value}")
check("窗口变宽后短文本气泡仍紧贴文字（不会被拉宽）",
      b_us.fit_width_value == cv._natural_width(SHORT_TXT), str(b_us.fit_width_value))
win.resize(820, 540)
for _ in range(3):
    qapp.processEvents()

# 极窄窗口：上限不能塌成 0（有 MIN 兜底）
win.resize(360, 540)
for _ in range(3):
    qapp.processEvents()
check("极窄窗口时上限有兜底（不塌成 0）",
      cv.bubble_max_width("user") == cv.MIN_BUBBLE_W
      and cv.bubble_max_width("assistant") == cv.MIN_BUBBLE_W,
      f"{cv.bubble_max_width('user')} / {cv.bubble_max_width('assistant')}")
win.resize(820, 540)
for _ in range(3):
    qapp.processEvents()

# ---- 系统消息不能把内容区「顶宽」（否则靠右的用户气泡右端被裁掉）----
# 真实现象：进入节能模式后落了一条较长的系统消息，用户自己的气泡「向右偏移、只剩左半截」，
# 退出节能也不恢复。根因是 `add_system()` 的 QLabel **没换行** → `minimumSizeHint` = 整段
# 单行宽 → 滚动区 `_container` 最小宽被顶到视口之外；水平滚动条关闭 ⇒ 直接裁右边。
# 靠右的 user 气泡首当其冲（assistant 靠左，所以只有「我的消息」看着坏了）。
from PySide6.QtCore import QPoint  # noqa: E402

LONG_SYS = ("已进入节能模式：桌宠压扁待机、不再动画，避免挡住其他软件。"
            "说「退出节能模式」或右键桌宠选「节能模式」可恢复。")
cv.add_system(LONG_SYS)
b_sys_user = cv.add_bubble("user", "你", "进入节能模式")
for _ in range(5):
    qapp.processEvents()

vp = cv._scroll.viewport()
check("长系统消息不会把内容区最小宽顶到视口之外",
      cv._container.width() <= vp.width(),
      f"container {cv._container.width()} vs viewport {vp.width()}")
check("长系统消息之后，用户气泡右边缘仍落在视口内（没有被裁）",
      b_sys_user.mapTo(vp, QPoint(0, 0)).x() + b_sys_user.width() <= vp.width(),
      f"right {b_sys_user.mapTo(vp, QPoint(0, 0)).x() + b_sys_user.width()} vs {vp.width()}")

sys_lbls = [lb for lb in cv._container.findChildren(gui.QLabel) if lb.text() == LONG_SYS]
sys_lbl = sys_lbls[0] if sys_lbls else None
check("系统消息标签已开启自动换行", sys_lbl is not None and sys_lbl.wordWrap())
check("系统消息标签的最小宽度诉求很小（不参与顶宽）",
      sys_lbl is not None and sys_lbl.minimumSizeHint().width() < 100,
      str(sys_lbl.minimumSizeHint().width() if sys_lbl else None))
check("系统消息换行后高度按真实宽度算（文字不被纵向裁）",
      sys_lbl is not None
      and abs(sys_lbl.height() - sys_lbl.heightForWidth(sys_lbl.width())) <= 1
      and sys_lbl.sizePolicy().hasHeightForWidth(),
      f"h={sys_lbl.height() if sys_lbl else None} hfw="
      f"{sys_lbl.heightForWidth(sys_lbl.width()) if sys_lbl else None}")

win.mark_quitting()
win.deleteLater()
qapp.processEvents()

# ---- 探针替身的「公开名」必须与真实模块对齐（2026-09-30 新增）----
# 4 个端到端探针（boot / danger / reply / sleep）用 `types.ModuleType` 造 `app.tts` / `app.asr` 替身，
# 再真的跑一次 `app.main.main()`。
# ★★**替身少一个名字 = `main.py` 的 worker 线程 `from .tts import X` 抛 ImportError** ⇒
#   线程**静默死掉**（异常只打在 stderr）⇒ 现象是「AI 一直不回复」，用例**级联**失败。
#   2026-09-30 实测踩过：新加的 `DEFAULT_TEXT_LANGUAGE` 没同步进替身，
#   `smoke_permissions` / `smoke_sleep` / `reply_probe` **三套集体假红** —— 而报错长这样：
#   `ImportError: cannot import name 'DEFAULT_TEXT_LANGUAGE' from 'app.tts' (unknown location)`
#   （`unknown location` 就是"这是个内存里造的替身、没有 __file__"的指纹）。
# 所以这里按 **AST** 把两边比一遍，让「加了新公开名、忘了同步替身」在**秒级**暴露，
# 而不是等到跑完整套才看到一堆莫名其妙的失败。
print()
print("== 10. 探针替身 ⊆ 真实模块：公开名不许漏 ==")


def _imported_names(modname: str) -> set:
    """`app/*.py` 里所有 `from .<modname> import a, b` 的**被导入名**。"""
    names = set()
    for src in (Path(__file__).resolve().parent.parent / "app").glob("*.py"):
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").lstrip(".") == modname:
                names.update(a.name for a in node.names)
    return names


def _stubbed_names(path: Path, modname: str) -> set:
    """探针里 `_stub("<modname>", **kwargs)` 提供的名字（只认**字面量**第一个参数）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_stub" and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == modname):
            found.update(kw.arg for kw in node.keywords if kw.arg)
    return found


_TESTS = Path(__file__).resolve().parent
for _probe in sorted(_TESTS.glob("*_probe.py")):
    for _mod in ("tts", "asr"):
        _want = _imported_names(_mod)
        if not _want:
            continue
        _have = _stubbed_names(_probe, f"app.{_mod}")
        if not _have:
            continue          # 这个探针没替身该模块（比如 danger_probe 不替 asr 的某几个名）
        _miss = sorted(_want - _have)
        check(f"{_probe.name} 的 app.{_mod} 替身覆盖了 app 代码导入的全部名字",
              not _miss, f"缺 {_miss}")

print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)
