"""危险操作倒计时弹窗探针：真实跑一次 `app.main.main()`，按脚本注入语音识别结果。

由 `tests/smoke_permissions.py` 以子进程调用（`QApplication` 一个进程只能建一个）。

环境变量：
    DANGER_PROBE_OUT  结果 JSON 的写出路径（必填）

验的是**行为**（不是源码长相）：
  1. **没排程**时说「立刻关机」-> 只「排程 + 弹倒计时弹窗」，**绝不**直接执行；
  2. 有排程时再说「立刻关机」-> 跳过剩余倒计时，当场执行（走 `tools.run_pending_danger_now()`）；
  3. 语音说「取消」-> 排程撤掉、弹窗转**红色取消态**（1.5s 后自己淡出）；
  4. 点弹窗右边那个**「取消」按钮** -> 与语音同一条路（撤排程 + 转红）；
  5. 点左边那个**「立刻执行」按钮** -> 跳过倒计时当场执行；
  6. 危险操作的回复是**固定文案**「任务执行中...」/「ミッション実行中...」（**不经过 AI**）；
  7. 倒计时弹窗**等回复开口**才出现（合成慢一点时，命令刚说完的那一刻还没有弹窗）。

探针**不联网、不写真 config、不碰注册表、绝不真的关机**：
    `load_config` / `save_config` / `autostart` / `app.asr` / `app.tts` / `app.ai` 全用替身；
    `tools._run_action_now` 只记一笔就返回（**不 Popen**）；`tools._abort_native_shutdown` 置空
    （别真去调系统的 `shutdown /a`）。
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

OUT = Path(os.environ["DANGER_PROBE_OUT"])


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


FEED = {}          # {"cb": 语音识别回调}
MSGS = []          # 系统消息
ASSISTANT = []     # 助手回复文本（聊天区里真正显示出来的）
CALLS = {"stream": 0, "once": 0}   # AI 调用次数
AI_ARGS = []                       # 每次**真去问 AI** 时带上的用户文本（危险操作那几轮里不该出现）
RAN = []           # 真被执行的动作名（替身记的）

# 顺序有讲究：`app.tools` 会在下面被 import，替身必须**先**装好（同一模块对象，改属性即可）


class _FakeMic:
    def __init__(self, recognizer=None, on_text=None, **k):
        FEED["cb"] = on_text

    def start(self):
        pass

    def stop(self):
        pass


_stub("app.asr", MicListener=_FakeMic, Recognizer=lambda *a, **k: object())
def _fake_synth(*a, **k):
    """合成替身：**慢 0.4 秒**再交回一个假路径。

    慢，是为了把「回复开口」推后，好验「弹窗要等回复开口才出现」；
    返回真值路径（而不是空串），是为了走「有音频」那条分支（`play` 没回调 `on_started` 时
    流水线会在 `finally` 里补一次 reveal），与真机静音模式关掉时的路径一致。
    """
    time.sleep(0.4)
    return str(BASE / "tests" / "_fake_tts.wav")


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
    synthesize_with_bang=_fake_synth,
    play_wav=lambda *a, **k: None,
)

from app import ai as aimod  # noqa: E402
from app import autostart  # noqa: E402
from app import tools  # noqa: E402

REPLY_ZH = "好的老师，爱丽丝在的哦。"
REPLY_JA = "はい！"


def _fake_chat_stream(api, persona, history, user_text, action_result=None,
                      on_event=None, zh_only=False):
    CALLS["stream"] += 1
    AI_ARGS.append(str(user_text))
    if on_event:
        on_event("ja", REPLY_JA)
        on_event("done", {"zh": REPLY_ZH, "ja": REPLY_JA})
    return {"zh": REPLY_ZH, "ja": REPLY_JA, "truncated": False}


def _fake_chat_once(api, persona, history, user_text, action_result=None, zh_only=False):
    CALLS["once"] += 1
    AI_ARGS.append(str(user_text))
    return {"zh": REPLY_ZH, "ja": REPLY_JA}


aimod.chat_stream = _fake_chat_stream
aimod.chat_once = _fake_chat_once

autostart.current_command = lambda: ""
autostart.is_enabled = lambda: False
autostart.enable = lambda: (True, "ok")
autostart.disable = lambda: (True, "ok")

# ★ 绝不真的关机：执行替身只记账，系统层面的 `shutdown /a` 也不许真调
tools._run_action_now = lambda a: (RAN.append(a.get("label")), "stub")[1]
tools._abort_native_shutdown = lambda: None

from PySide6.QtCore import QEvent, QEventLoop, QObject, QPointF, Qt, QTimer, Signal  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app.main as m  # noqa: E402

CFG = {
    "apis": [{"name": "T", "api_key": "sk-test", "base_url": "https://api.deepseek.com",
              "model": "deepseek-flash"}],
    "current_api": "T",
    "current_role": "alice",
    "volume": 0.5,
    # 静音模式**关**：这一条很关键 —— 走合成路径时「文字与声音同刻出现」才是真的，
    # 「弹窗等回复开口」也才有意义（静音模式下回复是立刻出的，验不出同步）
    "general": {"auto_start": False, "close_action": "tray", "mute_mode": False},
    # `run_command` 要在白名单里，否则「关机」会被权限挡在排程之前
    "permissions": {"allowed_dirs": [], "allowed_apps": [],
                    "allowed_actions": ["run_command", "open_app", "open_path", "query_info"],
                    "blocked_keywords": [], "danger_delay": 30,
                    "custom_apps": {}, "no_uac": []},
    "roles": {
        "alice": {"name": "爱丽丝", "wake_words": ["爱丽丝"],
                  "persona": "persona/alice.md", "pet_dir": "pet/alice"},
    },
}
m.load_config = lambda: CFG
m.save_config = lambda cfg: None
m.is_autostart_launch = lambda *a, **k: False
m.refresh_command = lambda *a, **k: (False, "")

# ★★2026-09-27：把「模型已就位」**钉死**，否则上面 CFG 里那句「静音模式**关**」会被
#   `main._apply_model_gate()` 推翻 —— 它的设计就是「没模型 ⇒ `mute_mode` 锁死在开」
#   （`docs/01` F7），而静音下回复是**立刻**出的 ⇒ 「弹窗等回复开口」这条同步关系就验不出来了。
#   ★本机现在**没有**模型（用户刚卸载干净），于是这一套会**确定性地**红在那条采样上，
#     而不是偶发 —— 与契约无关，纯粹是「本探针依赖硬盘上有没有那 1.15 GB」。
#   ⇒ 显式声明前置条件，让探针**只测它要测的东西**（关机确认卡片），与模型在不在解耦。
#   （同理 `gui.GeneralPanel._apply_model_state()` 也会因为没模型把静音锁死 ⇒ 只桩门禁不够。）
import app.voice_model as _vm_mod  # noqa: E402
_vm_mod.is_installed = lambda cfg: True

captured = {}
STATE = {"steps": {}}


class _SpyWindow(m.MainWindow):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        captured["win"] = self

    def add_assistant_message(self, role_key, name, text, *a, **k):
        ASSISTANT.append(str(text))
        return super().add_assistant_message(role_key, name, text, *a, **k)

    def begin_assistant_message(self, role_key, name, text, *a, **k):
        ASSISTANT.append(str(text))
        return super().begin_assistant_message(role_key, name, text, *a, **k)

    def add_system_message(self, text, *a, **k):
        MSGS.append(str(text))
        return super().add_system_message(text, *a, **k)


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
    dlg = getattr(captured["win"], "_danger_dlg", None)
    pd = tools.pending_danger()
    STATE["steps"][tag] = {
        "pending": (pd or {}).get("label"),
        "ran": list(RAN),
        "dlg_visible": bool(dlg is not None and dlg.isVisible()),
        "dlg_cancelled": bool(dlg is not None and dlg.cancelled),
        "dlg_title": (dlg.title_text if dlg is not None else ""),
        "dlg_number": (dlg.number_text if dlg is not None else ""),
        "notice": captured["win"]._notice_label.text(),
        "messages": list(MSGS),
    }


def _feed(text):
    cb = FEED.get("cb")
    assert cb is not None, "语音识别替身还没把回调交出来"
    cb(text)


class _ScriptedApp(QApplication):
    """接管 exec()：按脚本注入识别文本 / 点按钮，跑完就返回，让 main() 正常收尾。

    脚本是一张**按状态推进**的步骤表 —— 每个「等她回到聆听态 / 等弹窗显示出来」都是**轮询条件**，
    不是写死的时刻。上一版用固定毫秒掐表，合成慢 0.4 秒就把整条时间线错开了（命令落在「她还在说话」
    的窗口里，直接被忽略），排障花的时间比写探针还多。
    """

    def exec(self):
        loop = QEventLoop()
        action = {"type": "run_command", "label": "关机",
                  "target": ["shutdown", "/s", "/t", "0"]}
        LISTENING = "listening"

        def _dialog():
            d = getattr(captured["win"], "_danger_dlg", None)
            if d is not None and d.isVisible() and not d.cancelled:
                return d
            return None

        def _listening():
            return str(captured["pet"]._state) == LISTENING

        def _click(dlg, pt):
            for _t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                QApplication.sendEvent(
                    dlg, QMouseEvent(_t, QPointF(pt), QPointF(pt),
                                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

        # ("sleep", 秒) / ("feed", 文本) / ("snap", 名) / ("listen", None) /
        # ("dlg", None) / ("click", 按钮下标) / ("async", 条件) / ("do", 函数) / ("done", None)
        plan = [
            ("sleep", 0.15),
            ("feed", "爱丽丝你好"),          # 唤醒 + 一句闲聊
            ("listen", None),
            ("feed", "立刻关机"),            # 没排程 -> 普通「关机」分支：排程 + 固定回复 + 弹窗
            ("sleep", 0.1),                  # 命令刚落地的瞬间
            ("snap", "just_after_cmd"),      # -> 排程已经有了，但回复还没开口
            ("dlg", None),                   # 回复开口 -> 弹窗与它同刻出现
            ("snap", "card_appeared"),
            ("listen", None),
            ("feed", "立刻关机"),            # 有排程 -> 跳过倒计时当场执行
            ("async", lambda: bool(RAN)),
            ("sleep", 0.7),                  # 等淡出（0.5s）跑完
            ("snap", "run_now"),
            ("listen", None),
            ("feed", "关机"),                # 重新排一个
            ("dlg", None),
            ("snap", "before_cancel"),
            ("feed", "取消"),                # 语音取消 -> 红色取消态
            ("sleep", 0.3),
            ("snap", "cancelled"),
            ("listen", None),
            ("feed", "关机"),
            ("dlg", None),
            ("snap", "before_click_cancel"),
            ("click", 1),                    # 点右边「取消」
            ("sleep", 0.2),
            ("snap", "click_cancel"),
            ("listen", None),
            ("feed", "关机"),
            ("dlg", None),
            ("click", 0),                    # 点左边「立刻执行」
            ("sleep", 0.4),
            ("snap", "click_run_now"),
            ("done", None),
        ]
        idx = {"i": 0}
        until = {"t": 0.0}
        moved = {"t": time.monotonic()}

        tick = QTimer(captured["win"])
        tick.setInterval(50)

        def _pump():
            now = time.monotonic()
            if idx["i"] >= len(plan) or now - moved["t"] > 15:
                tick.stop()
                loop.quit()          # 走完（或某一步卡住超时）-> 收尾
                return
            kind, arg = plan[idx["i"]]
            step_done = False
            if kind == "sleep":
                if until["t"] == 0.0:
                    until["t"] = now + float(arg)
                step_done = now >= until["t"]
                if step_done:
                    until["t"] = 0.0
            elif kind == "feed":
                _feed(arg)
                step_done = True
            elif kind == "snap":
                _snap(arg)
                step_done = True
            elif kind == "do":
                arg()
                step_done = True
            elif kind == "listen":
                step_done = _listening()
            elif kind == "dlg":
                step_done = _dialog() is not None
            elif kind == "click":
                dlg = _dialog()
                if dlg is not None:
                    _click(dlg, dlg.buttons[arg].center())
                    step_done = True
            elif kind == "async":
                step_done = bool(arg())
            elif kind == "done":
                tick.stop()
                loop.quit()
                return
            if step_done:
                idx["i"] += 1
                moved["t"] = now

        tick.timeout.connect(_pump)
        tick.start()
        loop.exec()
        return 0


m.MainWindow = _SpyWindow
m.PetWindow = _SpyPet
m.QSystemTrayIcon = _FakeTray
m.QApplication = _ScriptedApp

sys.argv = ["run.py"]
rc = m.main()

OUT.write_text(json.dumps({
    "rc": rc,
    "steps": STATE["steps"],
    "assistant": list(ASSISTANT),
    "ai_calls": dict(CALLS),
    "ai_args": list(AI_ARGS),
    "feed_ready": FEED.get("cb") is not None,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print("probe done")
