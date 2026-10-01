"""静音模式「睡下」探针：真实跑一次 `app.main.main()`，按脚本注入语音识别结果。

由 `tests/smoke_sleep.py` 以子进程调用（QApplication 一个进程只能建一个，而
「流式主路径」与「非流式回退路径」必须各跑一个进程才能分别验证）。

环境变量：
    SLEEP_PROBE_OUT   结果 JSON 的写出路径（必填）
    SLEEP_PROBE_MODE  "stream"   = 走流式主路径（`chat_stream`）
                      "fallback" = 走非流式回退路径（`chat_stream` 报 truncated → `chat_once`）
                      "rewake"   = ★「醒着时再喊一次唤醒词」（2026-09-27 修的「反复被唤醒」）

三条路径要分别验的原因（很关键）：
  - 流式路径：`go_idle` 能把在途流水线 `cancel()` 掉，`on_finished` 根本不会发 →
    迟到的 `tts_done` 被掐断在源头；
  - 回退路径：`on_tts_ready` 挂的是**裸 `QTimer.singleShot`**，`cancel()` 管不着它 →
    这条迟到的 `tts_done` 只能靠 `back_to_listening` 里的 `asleep` 守卫挡住。
两种都要验，否则「把守卫删掉」这一类改动会溜过去。
  - `rewake` 路径：要验的是**「已经醒了」这件事必须留痕** —— 她思考/说话那几秒里
    `listening["active"]` 是 `False`，改之前再喊一次唤醒词会**又**唤醒一遍
    （又弹「已唤醒」、又主动打招呼）。★这条**必须在 `active == False` 的窗口里**验，
    所以在 `rewake` 模式里给 AI 加了一段**人为延迟**（`AI_DELAY`）把窗口撑开 ——
    真机这窗口是「AI 延迟 + 合成耗时」（几秒），探针里不撑开就瞬间关闭、复现不出 bug。

探针**不联网、不写真 config、不碰注册表**：`load_config` / `save_config` / `autostart`
全部替换为假实现，`app.asr` / `app.tts` / `app.ai.chat_stream` / `app.ai.chat_once` 用替身。
"""
import json
import os
import sys
import time
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

OUT = Path(os.environ["SLEEP_PROBE_OUT"])
MODE = os.environ.get("SLEEP_PROBE_MODE", "stream")

# ★只有 `rewake` 模式给 AI 加延迟：真机上「想」这一步要好几秒，那段窗口里
#   `listening["active"]` 是 False；不模拟它，「醒着再喊唤醒词」这条路走不到。
#   ★其它模式**必须保持 0**：`stream`/`fallback` 两条路径的脚本是按毫秒卡着写的
#   （「休息吧」要落在说话态还没结束的时候），多一秒延迟会把它们的时序全改掉。
AI_DELAY = 1.0 if MODE == "rewake" else 0.0


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


FEED = {}          # {"cb": 语音识别回调}
CALLS = {"stream": 0, "once": 0}
MSGS = []          # 系统消息


class _FakeMic:
    """ASR 替身：只把 on_text 回调留出来，由脚本按时间注入「识别到的文本」。"""

    def __init__(self, recognizer=None, on_text=None, **k):
        FEED["cb"] = on_text

    def start(self):
        pass

    def stop(self):
        pass


_stub("app.asr", MicListener=_FakeMic, Recognizer=lambda *a, **k: object())
# 语音合成替身：`synthesize_with_bang` 返回空串 = 没有音频（静音模式走的就是这条）
_stub(
    "app.tts",
    # ★替身必须与 `app/tts.py` 的**公开名**对齐（理由见 boot_probe.py 同一处注释）：
    #   少了 `DEFAULT_TEXT_LANGUAGE`，`main.py` 的 worker 线程会静默死于 ImportError。
    DEFAULT_TEXT_LANGUAGE="ja",
    TEXT_LANGUAGE_NAMES={"zh": "中文", "en": "英语", "ja": "日语"},
    start_in_background=lambda *a, **k: None,
    set_volume=lambda *a, **k: None,
    set_muted=lambda *a, **k: None,
    is_muted=lambda: False,
    synthesize_with_bang=lambda *a, **k: "",
    play_wav=lambda *a, **k: None,
)

from app import ai as aimod  # noqa: E402
from app import autostart  # noqa: E402

# 回复文本刻意开短：静音态时长 = max(1.2s, 0.22×字数) → 日语 3 字 ⇒ 恒为下限 1.2s，
# 让脚本节奏短而确定（探针只需保证「睡下」发生在 silent_hold 还没走完的时候）。
REPLY_ZH = "老师好呀！爱丽丝在的哦。"
REPLY_JA = "はい！"


def _fake_chat_stream(api, persona, history, user_text, action_result=None,
                      on_event=None, zh_only=False):
    CALLS["stream"] += 1
    # ★`rewake` 模式：先把「想」这一步拖住 —— 这 1 秒里 `listening["active"]` 是 False，
    #   正是「醒着但不在聆听」那个窗口（脚本要在这个窗口里再喊一次唤醒词）。
    if AI_DELAY:
        time.sleep(AI_DELAY)
    if MODE == "fallback":
        # 模拟「被截断」→ worker 回退到 chat_once（且此刻还没开场，允许回退）
        return {"zh": REPLY_ZH, "ja": REPLY_JA, "truncated": True}
    if on_event:
        on_event("ja", REPLY_JA)          # 日语整段先到 → 提交合成（静音模式下 synth 返回 None）
        on_event("done", {"zh": REPLY_ZH, "ja": REPLY_JA})
    return {"zh": REPLY_ZH, "ja": REPLY_JA, "truncated": False}


def _fake_chat_once(api, persona, history, user_text, action_result=None, zh_only=False):
    CALLS["once"] += 1
    return {"zh": REPLY_ZH, "ja": REPLY_JA}


aimod.chat_stream = _fake_chat_stream
aimod.chat_once = _fake_chat_once

# 注册表只读化
autostart.current_command = lambda: ""
autostart.is_enabled = lambda: False
autostart.enable = lambda: (True, "ok")
autostart.disable = lambda: (True, "ok")

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app.main as m  # noqa: E402

# 受控配置：静音模式**开**、带一个假 API（`_ask_ai` 不配 key 会直接短路）
CFG = {
    "apis": [{"name": "T", "api_key": "sk-test", "base_url": "https://api.deepseek.com",
              "model": "deepseek-flash"}],
    "current_api": "T",
    "current_role": "alice",
    "volume": 0.5,
    "general": {"auto_start": False, "close_action": "tray", "mute_mode": True},
    "permissions": {"allowed_dirs": [], "allowed_apps": [], "allowed_actions": [],
                    "blocked_keywords": [], "danger_delay": 5,
                    "custom_apps": {}, "no_uac": []},
    "roles": {
        "alice": {"name": "爱丽丝", "wake_words": ["爱丽丝"],
                  "persona": "persona/alice.md", "pet_dir": "pet/alice"},
        "ellen": {"name": "艾莲", "wake_words": ["艾莲"],
                  "persona": "persona/ellen.md", "pet_dir": "pet/ellen"},
    },
}
m.load_config = lambda: CFG
m.save_config = lambda cfg: None
m.is_autostart_launch = lambda *a, **k: False
m.refresh_command = lambda *a, **k: (False, "")

captured = {}
STATE = {"user": 0, "assistant": 0, "steps": {}}


class _SpyWindow(m.MainWindow):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        captured["win"] = self

    def add_system_message(self, text, *a, **k):
        MSGS.append(str(text))
        return super().add_system_message(text, *a, **k)

    def add_user_message(self, *a, **k):
        STATE["user"] += 1
        return super().add_user_message(*a, **k)

    def begin_assistant_message(self, *a, **k):
        STATE["assistant"] += 1
        return super().begin_assistant_message(*a, **k)

    def add_assistant_message(self, *a, **k):
        STATE["assistant"] += 1
        return super().add_assistant_message(*a, **k)


class _SpyPet(m.PetWindow):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        captured["pet"] = self


class _FakeTray(QObject):
    activated = Signal(object)
    Trigger = "trigger"
    DoubleClick = "double"

    def __init__(self, *a, **k):
        super().__init__()

    def setToolTip(self, *a, **k):
        pass

    def setContextMenu(self, *a, **k):
        pass

    def show(self):
        pass

    def hide(self):
        pass

    def showMessage(self, *a, **k):
        pass


def _snap(tag):
    STATE["steps"][tag] = {
        "pet": captured["pet"]._state,
        "assistant": STATE["assistant"],
        "user": STATE["user"],
        "wake_msgs": sum(1 for x in MSGS if "已唤醒" in x),
        "stream_calls": CALLS["stream"],
        "once_calls": CALLS["once"],
    }


def _feed(text):
    cb = FEED.get("cb")
    assert cb is not None, "语音识别替身还没把回调交出来"
    cb(text)


class _ScriptedApp(QApplication):
    """接管 exec()：按脚本注入识别文本，跑完就返回，让 main() 正常收尾。"""

    def exec(self):
        loop = QEventLoop()
        if MODE == "rewake":
            # ★「醒着时再喊一次唤醒词」：第一次唤醒 → 主动打招呼；趁她还在「想」
            #   （`ai_delay` 撑开的那个窗口、`listening["active"]` 仍是 False）**再喊一次**。
            #   期望：**不再唤醒**（「已唤醒」只出现 1 次），第二次被当成一句普通的话 →
            #   多一条用户消息 + 多一条回复。改之前这里会 wake_msgs=2 且 user 还是 0。
            QTimer.singleShot(150, lambda: _feed("爱丽丝"))        # 第一次唤醒（只有名字）
            QTimer.singleShot(500, lambda: _snap("after_first_wake"))
            QTimer.singleShot(600, lambda: _feed("爱丽丝"))        # ★窗口内再喊一次
            QTimer.singleShot(900, lambda: _snap("after_second_wake"))
            QTimer.singleShot(2600, lambda: _snap("settled"))
            QTimer.singleShot(2900, loop.quit)
            loop.exec()
            return 0
        QTimer.singleShot(150, lambda: _feed("爱丽丝你好"))    # 唤醒 + 指令 → 静音回复
        QTimer.singleShot(600, lambda: _feed("休息吧"))         # 睡下（此刻说话态还没结束）
        QTimer.singleShot(1500, lambda: _snap("before_probe"))  # 基准：迟到的收尾早该发生
        QTimer.singleShot(1600, lambda: _feed("现在几点了"))     # 睡下后 → 必须被忽略
        QTimer.singleShot(2100, lambda: _snap("after_sleep"))
        if MODE == "stream":
            QTimer.singleShot(2300, lambda: _feed("爱丽丝"))     # 唤醒 → 应当解除「睡下」
            QTimer.singleShot(3000, lambda: _snap("after_wake"))
            QTimer.singleShot(3300, loop.quit)
        else:
            QTimer.singleShot(2300, loop.quit)
        loop.exec()
        return 0


m.MainWindow = _SpyWindow
m.PetWindow = _SpyPet
m.QSystemTrayIcon = _FakeTray
m.QApplication = _ScriptedApp

sys.argv = ["run.py"]
rc = m.main()

data = {
    "rc": rc,
    "mode": MODE,
    "steps": STATE["steps"],
    "messages": list(MSGS),
    "feed_ready": FEED.get("cb") is not None,
    "calls": dict(CALLS),
}
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("probe done")
