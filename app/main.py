"""入口：组装主窗口、桌宠、系统托盘，并联动状态。"""
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .autostart import is_autostart_launch, refresh_command
from .config import (SWITCHABLE_ROLES, get_current_api, is_role_switchable,
                     load_config, resolve_persona_text,
                     save_config)   # ★可切换性真值（docs/02 §24）
from .gui import MainWindow
from .pet import PetWindow
from .state import State
from . import stats
from . import health          # ★P2（2026-10-02）：诊断内核（状态条 / 自检 共用同一份判据）
from . import logging_setup
from .logging_setup import get_logger
# ai（openai）与 asr（sherpa_onnx）加载较慢，均改为延迟导入：
# ai 在 _ask_ai 内导入，asr 在后台线程 init_asr 内导入。

# 本模块的 logger。★**在 `logging_setup.setup()` 之前取是安全的**：
# handler 是在 emit 那一刻沿 logger 层级往上找的，不是取 logger 时绑定的。
LOG = get_logger("main")

BASE_DIR = Path(__file__).resolve().parent.parent
ICON_PATH = BASE_DIR / "assets" / "icon" / "app_icon.png"

# 桌宠默认位置：右下角，右侧留出菜单空间、底部稍上移（可调）
MARGIN_RIGHT = 180
MARGIN_BOTTOM = 40

# 唤醒后等待指令的超时时间（毫秒）：1 分钟内没收到指令则回到待机
WAKE_TIMEOUT_MS = 60_000

# 休眠指令：说出这些词后进入待机（睡吧/休息吧 等）
SLEEP_WORDS = ("睡吧", "休息吧", "睡觉", "晚安", "去睡", "睡了", "休眠", "我要睡了")

# 危险级操作的撤销词：只在「确实有待执行的危险操作」时生效，避免闲聊里出现"取消"被误判
CANCEL_WORDS = (
    "取消", "别关", "别关机", "别重启", "不要关", "不要关机", "不要重启",
    "算了", "停下", "停下来", "停止执行", "不执行", "中止", "撤销",
)

# 「立刻关机」：**跳过剩余倒计时**当场执行（与弹窗左边那个按钮同一条路）。
# ⚠️ 与 CANCEL_WORDS 一样**只在确实有排程时**才认 —— 没有排程时说「立刻关机」只当作一次普通
# 「关机」（排进队列 + 弹窗），**绝不直接关机**（防误触发，与「别关机」不被当成指令同一条思路）。
RUN_NOW_WORDS = (
    # 通用说法（与弹窗左边那个「立刻执行」按钮同一个意思）
    "立刻执行", "马上执行", "立即执行", "现在就执行",
    # 点名到具体操作的说法也认：对着还剩下的几秒干等，说「立刻关机」的人不该被忽略
    "立刻关机", "马上关机", "立即关机", "现在就关机",
    "立刻重启", "马上重启", "立即重启", "现在就重启",
)

# 危险级操作排程后的**固定回复**（中文, 日语）：这一轮**不经过 AI**。
# ① 「任务执行中…」是状态通报，不是闲聊，让模型自由发挥只会把语义改掉（甚至和倒计时对不上）；
# ② 短句合成快 —— 静音模式关着时，用户不必等一长句语音念完才能开口说「取消」。
DANGER_REPLY = ("任务执行中...", "ミッション実行中...")

# 静音模式的语音开关（本地识别，**不经过 AI、也不合成语音**）。
# 必须在 `detect_action` 之前拦下：「打开静音模式」会被当成"打开某样东西"，
# 走本地搜索 → Bing 搜索兜底，闹出把「静音模式」当软件名去搜的笑话。
# 只认这些完整说法（不认光秃秃的「静音」二字），避免闲聊里误切。
MUTE_ON_WORDS = (
    "开启静音模式", "打开静音模式", "启动静音模式", "进入静音模式",
    "静音模式打开", "静音模式开启", "静音模式开",
    "把静音模式打开", "把静音打开", "开启静音", "打开静音",
)
MUTE_OFF_WORDS = (
    "关闭静音模式", "退出静音模式", "关掉静音模式", "取消静音模式",
    "静音模式关闭", "静音模式关掉", "静音模式关",
    "把静音模式关掉", "把静音关掉", "关闭静音", "退出静音", "取消静音",
)

# 节能形态（桌宠压扁成扁平待机形态，免得挡住别的软件）的语音开关。
# 同样**必须早于 `detect_action`**：否则「进入节能模式」会被当成「打开某样东西」去搜索兜底。
# 与静音模式不同的一点：这两个判断**只在状态真的需要切换时**才认（见 `on_command`）——
# 「退出」那组里有「恢复正常」这种很泛的说法，只在她确实处于节能态时才允许命中，免得闲聊误切。
POWER_SAVE_ON_WORDS = (
    "进入节能模式", "开启节能模式", "打开节能模式", "启动节能模式", "节能模式打开",
    "节能模式开启", "把节能模式打开", "进入节能", "开启节能", "打开节能",
)
POWER_SAVE_OFF_WORDS = (
    "退出节能模式", "关闭节能模式", "关掉节能模式", "取消节能模式", "节能模式关闭",
    "节能模式关掉", "把节能模式关掉", "退出节能", "关闭节能", "退出节能形态",
    "恢复正常模式", "恢复正常形态", "恢复正常", "恢复原样",
)

# ---- 「打开类」动作：交给 AI 的系统提示（2026-09-30，用户报「说『不清楚』却照样执行」）----
# 背景：`open_path` / `open_url` / `open_app` / `search` 这四类**不在生成回复前执行** ——
# 它们要等语音开场那一刻才执行（`_run_pending_action`，为了让窗口与回复同刻弹出）。
# 于是以前 `action_result` 是 None：模型手里只有老师那句话，就自己发挥了，常答成
# 「爱丽丝不太清楚呢…」，而动作**其实照做** ⇒ 用户看到的正是「说不清楚、却执行了」。
# ⇒ 现在把「这一步会做什么」如实交给模型（前缀 `[将执行]`，含义写在 `ai._ACTION_RESULT_HINT`）。
#    ★权限**没有**放宽：能不能执行仍由 `check_permission` 先判；这里是"已经过了权限"之后
#      的事，只是让她的**嘴上说的**与**手上做的**对得上。
_PENDING_ACTION_HINT = {
    "open_path": "系统马上会帮老师打开「{label}」，与你这句话同时进行。",
    "open_app": "系统马上会帮老师启动软件「{label}」，与你这句话同时进行。",
    "open_url": "系统马上会在浏览器里打开老师收藏的「{label}」，与你这句话同时进行。",
}


def _pending_action_hint(action) -> str:
    """把「打开类」动作翻译成交给 AI 的系统提示（空串 = 不告诉 AI）。

    ★`search` 是**兜底分支**（`tools._resolve_open`：本地、收藏夹里都没找到这个软件 /
      文件夹 / 网址）—— 这时候要的正是用户那句「说不清楚、并说帮老师在浏览器搜索」，
      所以单独写一条、把话**说死**（模型很容易自由发挥成"我不认识这个"）。
    ★其余三类是"确实能打开"，提示模型**别再说做不到 / 不清楚**。
    """
    atype = str((action or {}).get("type") or "")
    if atype == "search":
        kw = str((action or {}).get("keyword") or "").strip()
        return (f"[将执行] 系统在本地和收藏夹里都没有找到「{kw}」这个软件 / 文件夹 / 网址，"
                f"马上会在浏览器里搜索「{kw}」，与你这句话同时进行。"
                "请如实告诉老师你没有找到，并说你会帮老师在浏览器里搜索。")
    tpl = _PENDING_ACTION_HINT.get(atype)
    if not tpl:
        return ""
    label = str((action or {}).get("label") or "")
    return "[将执行] " + tpl.format(label=label) + "请用你的语气确认你这就去做。"


# ---- 唤醒后的「主动打招呼」提示词（2026-09-30，用户报「初次唤醒太单调、老是同一句」）----
# ★为什么要**轮流换角度 + 把上次那句回带**：这条 `_ask_ai` 走 `add_user_to_history=False`
#   （招呼不进历史），所以模型看不见自己上次说了什么 —— 上下文**完全相同**时它会稳定地
#   给出同一句，于是每次唤醒都听见一样的开场。两个保险叠加：
#   ① 角度按**轮转**取（不是随机）：相邻两次唤醒**必然**换一个角度；
#   ② 把上次实际说过的那句回带给它，明确要求换一种说法。
#   （随机也想过，但随机**允许**连着两次撞同一个角度 —— 用户要的正是"别再重复"。）
_WAKE_GREET_ANGLES = (
    "这次请换一个话题开场，别只问好（例如问问老师今天想让你做点什么）。",
    "这次请用游戏里「接到新任务」那样的精神头打一声招呼。",
    "这次请顺口提一件你最近在玩 / 在做的事，再问老师。",
    "这次请先喊一声老师，再问问老师今天过得怎么样。",
    "这次请带点撒娇的味道，说一句你一直想对老师说的话。",
    "这次请装作刚睡醒、伸个懒腰的样子跟老师说话。",
)


def wake_greeting_prompt(last: str = "", index: int = 0) -> str:
    """组装「老师把你唤醒了、主动打个招呼」这一轮的提示词（见 `_WAKE_GREET_ANGLES`）。

    `last` = 上一次**实际说过**的招呼（空串 = 第一次唤醒）；`index` = 轮转号（调用方递增）。
    """
    angle = _WAKE_GREET_ANGLES[index % len(_WAKE_GREET_ANGLES)]
    parts = ["（老师刚刚叫了你的名字把你唤醒，请用你的人设和语气主动向老师打个招呼问好。",
             angle]
    if last:
        parts.append(f"★上一次你是这样打招呼的：「{last[:80]}」—— 这次**换一种完全不同的说法**，"
                     "不要重复上次那句、也不要只改几个字。")
    parts.append("）")
    return "".join(parts)


class _TextBridge(QObject):
    text_ready = Signal(str)


class _ReplyBridge(QObject):
    """AI 回复回传（线程安全）。

    ⚠️ 参数个数必须与 `emit(...)` / `on_ai_reply(...)` 完全一致：
       4 个 str = (role_key, 中文, 日语, 发起请求时的 API 名称)。
       少一个就会在 worker 线程里抛 `TypeError: only accepts 3 argument(s), 4 given`，
       线程直接死掉 → 聊天界面不出中文、也没有日语可合成（AI 像"没回复"）。
    """
    reply_ready = Signal(str, str, str, str)  # (role_key, 中文, 日语, API 名称)


class _TtsDoneBridge(QObject):
    """TTS 播放完成回传（线程安全），用于切回主线程回到聆听状态。"""
    done = Signal()


class _TtsReadyBridge(QObject):
    """TTS 合成完成回传（线程安全），携带音频路径，用于「文字显示 + 声音播放」同步。"""
    ready = Signal(str, str, str, str)  # (role_key, 中文, 日语, 音频临时路径)


class _SpeakStartBridge(QObject):
    """整段语音即将出声（线程安全）：文字与声音**同刻**出现的那一刻。

    回复在「日语整段合成完」+「中文吐完」两者都就绪时才开场，所以气泡要在这一刻
    才建、并且**一次性**写入完整中文 —— 这样「界面出现文字」与「听到声音」是同一
    时刻（项目里的既有不变式）。信号只带 str（跨线程只能传基本类型）。
    """
    started = Signal(str, str)  # (role_key, 完整中文)


class _ReplyDoneBridge(QObject):
    """整段回复已完整（线程安全）：写聊天记录，并放行播放（中文吐完是开场的条件之一）。

    ⚠️ 参数个数必须与 `emit(...)` 一致，理由同 `_ReplyBridge`。
    """
    done = Signal(str, str, str, str)  # (role_key, 中文, 日语, API 名称)


# 语音迟迟就绪不了（合成服务异常 / 卡住）时的**最后兜底**：中文吐完后超过这个时间还没开场，
# 就先把文字显示出来（并关掉「思考中」提示），不让界面一直停在「正在思考...」。
#
# ★这个窗口必须**晚于正常合成耗时** —— 它一触发就等于**放弃同步**（文字先出、声音后到）。
#   若窗口比正常合成还短，那么「正常但慢」的长回复也会被误判成「卡住」，反而制造出
#   「先出字、后出声」。原先固定 20s，而日语已改为不限长：**70 字就实测到 22.6s**，
#   于是长回复必然踩中 → 必须按字数自适应。
#   本机实测 `t_gsv(N) = 2.70 + 0.2748·N` 秒（N = 日语字数，±20% 抖动，9 个样本点，
#   见 `devlog/2026-09-16.md` §一），所以取 **0.45 s/字（≈ 斜率的 1.6 倍）+ 5s 常量**。
REPLY_TEXT_FALLBACK_BASE_MS = 5000
REPLY_TEXT_FALLBACK_PER_CHAR_MS = 450
# 上限：极端长的回复也不至于让用户干等太久（按上式 160 字才 77s，一般不触顶）
REPLY_TEXT_FALLBACK_MAX_MS = 90000


def reply_text_fallback_ms(ja_text: str) -> int:
    """兜底窗口（毫秒）：**按日语字数自适应**（标定与理由见上面的注释）。"""
    n = len((ja_text or "").strip())
    return min(REPLY_TEXT_FALLBACK_BASE_MS + REPLY_TEXT_FALLBACK_PER_CHAR_MS * n,
               REPLY_TEXT_FALLBACK_MAX_MS)


# 「显示聊天气泡」（检验用；★2026-09-28 右键菜单那一行已下架，API 仍可用）的预览文本：
# 故意写**长**（够切三段以上）—— 开一下就能看清
# 圆角 / 2px 深蓝边 / 尾巴 a·b / 「高度随文字量变化」，以及**四改的分段换字**（看完全程要十几秒，
# 不想等就把开关关了再开）。正式回复走的仍然是那一轮的中文全文（`show_pet_bubble`），这句只管检验。
BUBBLE_PREVIEW_TEXT = (
    "气泡预览：把桌宠拖到屏幕左边或上边试试～"
    "回复太长的时候，气泡会一段一段地显示，不会一直往上长："
    "前面这一段看完了就淡出，再把后面的一段淡进来，一直到最后一段为止。"
)


def pet_default_pos(pet) -> tuple:
    """桌宠的默认位置：**主屏**可用区右下角。

    右侧留 `MARGIN_RIGHT`（右键菜单展开要的空间）、底部留 `MARGIN_BOTTOM`。
    启动落位与「设置 → 通用设置 → 重置角色位置」**共用这一处计算**：两边各写一份迟早会漂移，
    而用户点「重置」时期待的就是「回到刚启动时那个位置」。
    """
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return (pet.x(), pet.y())
    geo = screen.availableGeometry()
    return (geo.x() + geo.width() - pet.width() - MARGIN_RIGHT,
            geo.y() + geo.height() - pet.height() - MARGIN_BOTTOM)


def main() -> int:
    # ★第一件事（2026-10-01 第五批）：把日志与「未捕获异常」钩子装上。
    #   放在 QApplication 之前 —— 之后任何一步崩了都留痕；幂等，重复调用是空操作。
    #   ★★必须挂在 main() 里，不能只挂 run.py：exe 走的是 `make_stage.py` 生成的
    #   `entry.py`，它**不经过 run.py** ⇒ 只挂 run.py 会让打包形态完全没有日志。
    logging_setup.setup()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Microsoft YaHei UI", 10))  # 统一字体，消除 QFont 点大小告警
    # 全局 tooltip 样式：黑色文字 + 白底 + 灰边框（避免默认黑背景闪烁）
    app.setStyleSheet(
        "QToolTip { color:#000000; background:#FFFFFF; border:1px solid #CBD5E1; border-radius:6px; padding:4px 8px; }"
    )

    cfg = load_config()
    role_key = cfg.get("current_role", "alice")
    # ★角色不可切换时兜底（2026-09-28；docs/02 §24）：历史 config 可能把 `current_role`
    #   留在艾莲（用户此前切过去过）⇒ 否则会「开局就停在一个不可切换的角色上」（虽然还能靠
    #   下拉逃回爱丽丝，但状态本身就是错的）。就地回落到第一个可切换的角色。
    if not is_role_switchable(role_key):
        role_key = SWITCHABLE_ROLES[0]
        cfg["current_role"] = role_key

    # 本次启动是否来自「开机自启」（命令行带 --autostart）：
    # 自启拉起时不显示主界面，直接待在托盘，桌宠照常在桌面待机。
    silent_boot = is_autostart_launch()

    # 启动项自愈：注册表里存的是绝对路径，项目目录被移动 / 改名 / 重建虚拟环境后
    # 旧命令行会静默失效（开机时什么都不会发生）。这里比对一次，过时就地改写。
    healed, healed_cmd = refresh_command()

    # 安全边界：把 config 中的 permissions 段生效（白名单 + 危险级延迟秒数）
    from .tools import apply_permissions
    apply_permissions(cfg.get("permissions"))

    def mute_mode_on() -> bool:
        """静音模式：AI 只输出中文、不做语音合成与播放（通用设置里可切换）。

        **每轮现读现用、不做缓存** —— 设置面板写的就是同一个 cfg 字典，
        开关一拨，下一轮回复立即生效，不需要重启。
        """
        return bool((cfg.get("general") or {}).get("mute_mode", False))

    # ★P2：语音识别是在**后台线程**里初始化的（见下面的 init_asr），而状态条 / 自检
    #   随时可能来问「起来了没」。用一个普通 dict 当跨线程信箱 —— 只存 True / False / None
    #   （初始 None = 还不知道，状态条那时会说「正在初始化…」而不是诬赖它坏了）。
    asr_state = {"ok": None}

    win = MainWindow(cfg)
    # ★P2（2026-10-02）：把「外部事实」的取值回调交给主窗口。
    #   **只有这里知道麦克风 / 语音识别到底起没起来**（它在后台线程里初始化，见下方 init_asr），
    #   所以状态条与「一键自检」都得从这里拿 —— 别让它们各自去猜。
    #   `asr_state` 是个普通 dict：跨线程只传 bool/None（本项目铁律）。
    win.set_health_facts_provider(lambda: health.collect_facts(cfg, asr_ok=asr_state["ok"]))
    win.refresh_health()
    pet = PetWindow(BASE_DIR / cfg["roles"][role_key]["pet_dir"])

    # 把主窗口带到最前面（托盘点击 / 桌宠右键菜单时调用）
    def show_main_window():
        # 主界面一露头就**重判**桌宠气泡（**必须排在 bring_to_front() 之后**：isVisible() 是那一刻
        # 才变 True 的，顺序反了会把「开到聊天页该收」判成「还关着 → 允许」）：落到聊天页就收掉
        # （那句话已经在聊天区里了），停在管理 / 设置页则留着（用户仍然看不到聊天区）。
        win.bring_to_front()
        refresh_pet_bubble()

    # 系统托盘
    tray = QSystemTrayIcon(QIcon(str(ICON_PATH)), app)
    tray.setToolTip("Ignotus Assistant")
    tray_menu = QMenu()
    tray_menu.addAction("打开主界面", show_main_window)
    # ★P2（2026-10-02）：托盘里也能拿到「使用引导 / 一键自检 / 检查更新」——
    #   这三件正是「感觉它不太对劲」时最先想找的东西，只藏在设置页里没人想得到。
    tray_menu.addSeparator()
    tray_menu.addAction("使用引导", lambda: win.show_first_run())
    tray_menu.addAction("一键自检", lambda: win.self_check())
    tray_menu.addAction("检查更新", lambda: win.check_update())
    tray_menu.addSeparator()

    # 彻底退出：停麦克风、放行关闭拦截、收起桌宠与托盘、重置当前角色、退出
    def quit_app():
        # 先标记「正在退出」：此后 closeEvent 一律放行，避免 app.quit() 关闭窗口时
        # 再次走到「关闭软件」分支造成死循环（详见 MainWindow.closeEvent 注释）。
        win.mark_quitting()
        if listener is not None:
            listener.stop()
        win.set_hide_to_tray(None)
        try:
            pet.close()
        except Exception:
            pass
        tray.hide()
        cfg["current_role"] = "alice"
        save_config(cfg)
        QTimer.singleShot(0, app.quit)

    tray_menu.addAction("退出", quit_app)
    tray.setContextMenu(tray_menu)

    def on_tray(reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            show_main_window()

    tray.activated.connect(on_tray)
    tray.show()

    # 角色切换：更新 cfg，并由 win.set_current_role 触发 _role_change_cb 同步桌宠贴图
    def switch_role(key: str):
        # ★不可切换的角色（艾莲）**不落盘、不切换**（2026-09-28；docs/02 §24）——
        #   桌宠菜单那边已经把它灰掉、点不动了，这里是**显式失败**兜底：
        #   万一将来有别的调用方直接调 `pet._on_switch("ellen")`，也不会真的切过去。
        if not is_role_switchable(key):
            return
        cfg["current_role"] = key
        save_config(cfg)
        win.set_current_role(key)

    pet.set_roles([(r["name"], k) for k, r in cfg["roles"].items()])
    pet.set_current_role(role_key)
    # 第二款气泡的「第一类内容」**只在当前 API 是 DeepSeek 时才显示**（用户口径）——
    # 注入**取值回调**（每次要用时现读 cfg），所以设置界面里怎么切 API 都不用再通知桌宠。
    pet.set_thinking_api_provider(lambda: get_current_api(cfg))
    # 启动就把余额后台预取一次：等用户单击贴图时已经有得显示了（60s 内不会重复打网络）。
    stats.prefetch_balance(get_current_api(cfg), force=True)
    pet.set_on_switch(switch_role)
    # 桌宠右键菜单：主界面 → 聊天界面；设置 → 设置界面（都同时把主窗口带到最前面）
    def open_pet_nav(index: int):
        """桌宠右键菜单的跳转：**跳完再按新页面重判气泡**（到聊天页就收、到设置页就留着）。

        这里必须自己重判一次：跳转目标就是当前页时 `_switch_right_panel()` 会早返回、
        不发换页回调（「主界面」= 聊天页，正好是最常见的那种）。
        """
        win.open_nav_page(index)
        refresh_pet_bubble()

    pet.set_on_home(lambda: open_pet_nav(0))
    pet.set_on_settings(lambda: open_pet_nav(2))
    pet.set_on_quit(quit_app)

    # 音量：初始化滑块位置；改动时持久化并同步 TTS 播放增益
    pet.set_volume(float(cfg.get("volume", 0.5)))

    def on_volume_changed(v: float):
        """**音量变化的唯一落地点**（桌宠菜单里那条音量条 / 通用设置那一行，都汇到这里）。

        落 cfg + 写 TTS 增益 + 把两处 UI 都同步过去：
          * `pet.set_volume()`：桌宠侧（记下值；菜单正开着就顺手把那条音量条拨过去）；
          * `win.sync_volume()`：通用设置那一行（`notify=False`，不会回环）。
        """
        v = max(0.0, min(1.0, float(v)))
        cfg["volume"] = round(v, 2)
        save_config(cfg)
        try:
            from .tts import set_volume as set_tts_volume
            set_tts_volume(v)
        except Exception:
            pass
        pet.set_volume(v)
        win.sync_volume(v)

    pet.set_on_volume(on_volume_changed)
    # 「通用设置 → 桌宠调整 → 音量」那条路：与桌宠菜单里那条音量条**收敛到同一个函数**
    win.set_volume_cb(on_volume_changed)

    # 静音：点击喇叭图标时同步 TTS 静音开关（不影响音量值，便于恢复）
    def on_mute_changed(muted: bool):
        try:
            from .tts import set_muted
            set_muted(bool(muted))
        except Exception:
            pass

    pet.set_on_mute(on_mute_changed)

    # 节能形态：**语音入口与右键菜单共用这一条回调** —— 弹一条状态提示 + 落一条系统消息。
    # 回调只在「真的发生切换」时触发一次，所以语音和菜单两条路都不会漏提示、也不会重复。
    # 2026-09-18 用户口径：提示**只要「已进入 / 已退出节能模式」这一句** —— 原来那两句解释
    # 压扁 / 恢复细节的长文案已删（和静音模式那条提示同一副长相、同一个落点）。
    def on_power_save_changed(on: bool):
        text = "已进入节能模式" if on else "已退出节能模式"
        pet.flash_toast(text)
        win.add_system_message(text)

    pet.set_on_power_save(on_power_save_changed)

    # 「显示聊天气泡」（检验用；★2026-09-28 右键菜单那一行已下架）：开 = 强制叫出来并**钉住**
    # （不再看静音模式 / 主界面），关 = 立刻淡出。开关本身记在 pet 里，这里只管「开的时候写什么文字」。
    def on_bubble_preview(on: bool):
        if on:
            pet.show_bubble(BUBBLE_PREVIEW_TEXT)
        else:
            pet.hide_bubble()

    pet.set_on_bubble_preview(on_bubble_preview)

    # 角色切换时同步更新桌宠贴图（由 win.set_current_role 触发）
    def on_role_changed(key: str):
        role = cfg["roles"][key]
        pet.set_pet_dir(BASE_DIR / role["pet_dir"])
        pet.set_current_role(key)

    win.set_role_change_cb(on_role_changed)

    # 右栏换页（进管理 / 设置页、切回聊天页）之后重判桌宠气泡：切回聊天页时收掉，其余情况留着。
    win.set_page_change_cb(lambda: refresh_pet_bubble())

    # 关闭主窗口 → 隐藏到托盘
    def hide_to_tray():
        tray.showMessage("Ignotus Assistant", "已最小化到托盘，小人继续陪伴你～")

    win.set_hide_to_tray(hide_to_tray)

    # 「设置 → 通用设置 → 重置角色位置」：点一下把桌宠送回默认位置。
    # **直接落位、不做过渡动画** —— 与气泡翻转那种 0.5s 平移不同，重置是一次性动作。
    # 气泡不用在这里管：`PetWindow.moveEvent → _sync_bubble` 会把它带到新位置，
    # 并按新空间重算朝向（空间不够就自己翻过去）。
    def reset_pet_pos():
        pet.move(*pet_default_pos(pet))

    win.set_reset_pet_pos(reset_pet_pos)

    # 「设置 → 通用设置 → 静音模式」这条路的桌宠提示：设置页自己已经落过 cfg、
    # 也提示过用户了，所以这里**只弹一下状态提示气泡**（别重复写 cfg / 页面提示）。
    # 语音那条路（「开启静音模式」）走 `set_mute_mode()`，两条路各弹各的、不会重叠。
    win.set_mute_mode_cb(
        lambda on: pet.flash_toast("已进入静音模式" if on else "已退出静音模式")
    )

    # ---- patpat 模式（2026-09-20）：**模式开着**时左键点贴图 → 叠一只手（抬起/下压）+ 摸摸音效 ----
    # ★二十一改：模式关着单击也**照样形变**，只是没有手、没有声音 —— 模式这一档只管「手 + 声」。
    # ★★二十二改：音效**分两套、各自独立**（用户口径「互不影响，相互独立」），一次点击只响一套 ——
    #   `voices/patpat/`（模式**开着**）/ `voices/normal_pet/`（模式**关着**，`bibu.mp3`）。
    # 两个目录都只有这里知道，分别注入给桌宠（pet.py 不认识项目根）。
    # 两套都是**原声**播放（不跟音量滑块、静音模式也不影响）—— 用户口径「总是原声」。
    pet.set_patpat_sound_dir(BASE_DIR / "voices" / "patpat")
    pet.set_normal_pet_sound_dir(BASE_DIR / "voices" / "normal_pet")

    def on_patpat_changed(on: bool):
        """patpat 模式切换的**唯一落地点**（右键菜单 / 通用设置两个入口都汇到这里）。

        做三件事：① 弹提示（文案按用户口径，落点 = 贴图上方那条状态气泡）；
        ② 把 cfg 里的值同步过去（设置页那一行是按 cfg 初始化的，不同步的话整页重建时会显示旧值）；
        ③ 同步设置页那一行的滑块（右键菜单切的，设置页也要跟着动）。
        cfg 是纯运行时的（`save_config` 会剔掉），所以写它不会落盘。
        """
        text = "patpat模式启动" if on else "patpat模式关闭"
        pet.flash_toast(text)
        cfg.setdefault("general", {})["patpat_mode"] = bool(on)
        win.sync_patpat_mode(on)

    pet.set_on_patpat(on_patpat_changed)
    # 「设置 → 通用设置 → 模式切换 → patpat模式」这条路：设置页自己已经落过 cfg、
    # 也提示过用户了，这里只把桌宠侧的状态切过去（提示由上面那条回调统一弹，不会重叠）。
    win.set_patpat_mode_cb(pet.set_patpat)

    # ---- 桌宠固定（2026-09-22）：开着 = 贴图**不能被拖动**（只锁「拖」，抚摸 / 思考气泡照旧）----
    # 与 patpat 同一套「唯一落地点」写法：右键菜单 / 通用设置两个入口都汇到 on_pet_lock_changed。
    # ★它是**落盘的偏好**（用户口径「记住选择」）⇒ 回调里 `save_config`；提示文案也就不带
    #   「本次运行有效」那半句。★2026-09-29 起静音模式也是同类（落盘），这类对比现在只剩 patpat。
    # ⚠️ 初始值必须在**挂回调之前**注入：`set_locked()` 会往 `_on_lock` 发一次通知，挂上回调之后
    #    再调就会在启动时弹一条「桌宠已固定」的提示气泡（不该有）。此处 `_on_lock` 还是默认空函数。
    # ⚠️ pet 里那个默认是 **False**（可拖，好让单测不受影响）⇒ 真值只能由这里注入，别忘了。
    pet.set_locked(bool(cfg.get("general", {}).get("lock_pet", True)))

    def on_pet_lock_changed(on: bool):
        """「桌宠固定」切换的**唯一落地点**（右键菜单 / 通用设置两个入口都汇到这里）。

        做三件事：① 弹提示；② 把 cfg 里的值同步过去（设置页那一行是按 cfg 初始化的，
        不同步的话整页重建时会显示旧值）；③ 同步设置页那一行的滑块（右键菜单切的，那一行也要动）。
        ★这一项**要落盘**（它是用户的偏好 —— 与 `patpat` 那种纯运行时状态不同；
        ★2026-09-29 起 `mute_mode` 也已经改成落盘，别再写成「静音 / patpat」）。
        """
        pet.flash_toast("桌宠已固定，不会被拖动" if on else "桌宠已解除固定，可以拖动")
        cfg.setdefault("general", {})["lock_pet"] = bool(on)
        save_config(cfg)
        win.sync_pet_lock(on)

    pet.set_on_lock(on_pet_lock_changed)
    # 「设置 → 通用设置 → 桌宠调整 → 桌宠固定」这条路：设置页自己已经落过 cfg、也提示过用户了，
    # 这里只把桌宠侧的状态切过去（提示由上面那条回调统一弹，不会重叠）。
    win.set_pet_lock_cb(pet.set_locked)

    # 「设置 → 通用设置」里选「关闭软件」时走完全退出（含托盘、麦克风清理）
    win.set_quit_app(quit_app)

    # ---- 语音识别与唤醒（本地离线）----
    listening = {"active": False}
    # 是否已经「睡下」（待机 / 说了「休息吧」）。**这是聆听的唯一否决票**：
    # 一旦睡下，任何迟到的回复收尾都不许再把聆听接回来（否则用户会看到
    # 「说了休息吧，她还在听、还在答」—— 静音模式下必现，原因见 `go_idle`）。
    asleep = {"v": False}
    # ★是否**已经醒着**（被唤醒过、且还没睡下）。**只有 `go_idle()` 才解除**。
    #
    # ★★它解决的是「反复被唤醒」：`listening["active"]` 只表示「**这一刻**在等指令」——
    #   她思考 / 说话的整段时间里它是 `False`。于是用户在那几秒里再喊一次唤醒词，
    #   会**又**走一遍唤醒流程：**又**弹「已唤醒」、**又**系统消息、**又**主动打招呼
    #   （2026-09-27 用户报「叫出角色名唤醒后如果再喊唤醒词会显示反复被唤醒」）。
    #   ⇒ 有了 `awake`，唤醒流程的成立条件就从「不在聆听」收紧成「**还没醒**」；
    #     醒着时再喊唤醒词 = 一句普通的话，走正常交流（用户 2026-09-27 拍板）。
    awake = {"v": False}
    # 「唤醒主动打招呼」这一轮的状态（2026-09-30，见 `wake_greeting_prompt`）：
    #   pending = 当前这一轮回复就是唤醒招呼（`on_reply_done` 据此把它记下来）；
    #   last    = 上一次**实际说过**的招呼原文（回带给模型，要求换一种说法）；
    #   index   = 轮转号，每唤醒一次 +1（保证相邻两次换角度）。
    # ★只活在内存里、**不落盘**：重启后从"第一次唤醒"重新开始，符合直觉。
    greet_ui = {"pending": False, "last": "", "index": 0}
    listener = None  # 退出时用于停止麦克风监听

    def strip_punct(text: str) -> str:
        """去掉标点与空白，只保留文字，用于判断是否真的有指令内容。"""
        import re
        return re.sub(r"[\s\W]+", "", text, flags=re.UNICODE)

    def match_wake_word(text: str):
        # 用去标点后的文本比对，避免"爱丽丝。"这类带标点识别结果匹配不到
        clean = strip_punct(text)
        for key, role in cfg["roles"].items():
            for w in role.get("wake_words", []):
                wc = strip_punct(w)
                if wc and wc in clean:
                    return key, w
        return None, None

    # 唤醒超时定时器：唤醒后启动，收到指令或超时都会取消
    wake_timer = QTimer()
    wake_timer.setSingleShot(True)

    def go_idle(reason: str = ""):
        # ★ 睡下之后，**在途的那条回复流水线必须掐掉** —— 它的收尾会 `emit tts_done`
        #   → `back_to_listening()`，把刚睡下的她重新叫回聆听。静音模式里这条路**必踩**：
        #   没有音频，文字一显示就恢复聆听了（见 `rearm_listening`），于是用户完全可以在
        #   「说话态」还没结束（`silent_hold` 窗口）时就说出「休息吧」—— 此时旧流水线还在
        #   `_interruptible_sleep` 里没走完，走完就把聆听接回来了（现象：说了休息吧，
        #   她还在听、还在答）。
        asleep["v"] = True
        # ★睡下**同时**清掉「已经醒着」：唤醒流程的成立条件是「还没醒」，所以
        #   `awake` 必须跟着 `asleep` 一起翻 —— 否则她睡下之后再喊唤醒词会被
        #   「醒着」那条守卫拦住，变成「叫也叫不醒」（`smoke_sleep` 那条
        #   「喊一声能重新唤醒（wake_msgs == 2）」正是守这个的）。
        awake["v"] = False
        # 顺手让上一轮挂下的「文字兜底」定时器作废（seq 一变，`_reply_text_fallback` 就丢弃）
        stream_ui["seq"] += 1
        # 用户已经点名的「打开类」动作**不该因为一句「休息吧」被悄悄吞掉**：它已经过了
        # 权限校验，只是原计划等语音开场时才执行（`_run_pending_action`）。这里先把它落掉，
        # 免得「掐掉在途回复」顺带变成一个『说了打开却没打开』的回归。
        _run_pending_action()
        pipe = pipeline_state.get("pipe")
        if pipe is not None:
            pipe.cancel()
        listening["active"] = False
        wake_timer.stop()
        pet.hide_bubble()          # 睡下之后不许在桌上留一个气泡
        # 常驻提示换成「休眠中」：关掉主界面后光看贴图（尤其节能形态那张不换帧的
        # 扁平图）也能一眼看出她是睡着了，而不是还在等指令。
        pet.set_state_toast("休眠中")
        pet.set_state(State.IDLE.value)
        win.set_status(State.IDLE)
        if reason:
            win.add_system_message(reason)

    wake_timer.timeout.connect(lambda: go_idle("已超过 1 分钟未收到指令，进入待机"))

    def is_sleep_word(text: str) -> bool:
        clean = strip_punct(text)
        return any(strip_punct(w) in clean for w in SLEEP_WORDS)

    def rearm_listening():
        """只把「继续聆听」接回来，**不动桌宠姿态**。

        静音模式没有真实音频，说话态时长是**估算**出来的（见 `pipeline.silent_hold_seconds`）。
        若因此把「继续聆听」也一起拖住，就等于凭空禁止用户接着下指令 —— 那才是真的影响
        回应速度。所以**没有音频时**：文字一显示就恢复聆听，桌宠姿态该停多久停多久。

        ★ 但她**已经睡下**时一律不许接回来：这是「休息吧」之后还答话的根因所在
        （迟到的回复收尾会走到这里）。睡下的唯一解除方式是唤醒词，见 `on_text`。
        """
        if asleep["v"]:
            return
        listening["active"] = True
        wake_timer.start(WAKE_TIMEOUT_MS)

    def back_to_listening():
        """收到指令并处理完后，回到聆听状态，继续等待下一条指令。"""
        if asleep["v"]:
            return      # 睡下之后不许被「迟到的回复收尾」叫醒（连桌宠姿态一起挡住）
        rearm_listening()
        pet.hide_bubble()          # 这一轮说完了 -> 气泡淡出（就是「对话结束」那个点）
        # 又能等指令了：常驻提示挂回「待机中」，点动画（1s 一个点）自己走。
        pet.set_state_toast("待机中", dots=True)
        pet.set_state(State.LISTENING.value)
        win.set_status(State.LISTENING)

    # ---- AI 对话（想）----
    ai_history = {}  # {role_key: [{"role", "content"}]}
    # 思考提示延迟显示协调：pending=True 表示"1.5s 后仍需显示思考提示"
    thinking_ui = {"pending": False}
    # 待执行的动作（打开类），在语音开始播放时同步执行
    pending_action = {"action": None}
    # 危险级操作倒计时的界面状态：label = 当前正在倒计时的排程名（None 表示无排程）；
    # card = 屏幕正中央那张弹窗**已经放出来了**（它要等回复开口才弹，见 `sync_danger_card`）
    danger_ui = {"label": None, "card": False}

    # 倒计时弹窗的两个按钮：点击 → 与语音那条路**共用同一个函数**（GUI 不认识 tools）
    def on_danger_run_now():
        from .tools import run_pending_danger_now
        label = run_pending_danger_now()
        if not label:
            return                      # 排程已经没了（到点 / 被取消）：什么都不做
        danger_ui["label"] = None
        win.set_notice("")
        win.hide_danger_countdown()     # 排队都执行了：弹窗当场淡出
        win.add_system_message(f"已立刻执行「{label}」，不再等待倒计时。")

    def on_danger_cancel():
        from .tools import cancel_pending_danger
        label = cancel_pending_danger()
        if not label:
            return
        danger_ui["label"] = None
        win.set_notice("")
        # 点按钮取消 = 语音取消：弹窗也要转**红色取消态**（保持 1.5s 再自己淡出），
        # 不能只在下一秒被 tick 当成「队列空了」白白收掉。
        win.cancel_danger_countdown()
        win.add_system_message(f"已中止「{label}」，没有执行。")

    win.set_danger_callbacks(on_danger_run_now, on_danger_cancel)
    # 正在跑的那条回复流水线（工作线程里创建；主线程只用它 cancel）
    pipeline_state = {"pipe": None}
    # 回复的界面状态（**只在主线程读写**）：
    #   bubble 气泡是否已建；saved 聊天记录是否已落；zh 已到的完整中文；key 角色；
    #   seq 请求序号（过期的兜底定时器靠它丢弃）
    stream_ui = {"bubble": False, "saved": False, "zh": "", "key": "", "seq": 0}
    # 这一轮是不是「没有音频」（静音 / 静音模式 / 合成失败）：文字显示后要立刻恢复聆听 ——
    # 因为此时并没有声音在播，把「继续聆听」一起拖住是凭空降低响应性。
    reply_silent = {"v": False}

    def _show_thinking_delayed(name: str):
        """延迟回调：若思考提示仍待显示（AI 尚未回复），则显示。"""
        if thinking_ui["pending"]:
            win.show_thinking(name)

    def on_ai_reply(key: str, zh: str, ja: str, api_name: str = ""):
        # 回复回来后若当前 API 已经换人，直接丢弃这条回复：
        # 保证同一时刻只有「当前 API」在参与对话，被换下去的 API 立即停止使用，
        # 不会出现旧 API 的回复和新 API 的回复同时冒出来的情况。
        if api_name and api_name != cfg.get("current_api"):
            thinking_ui["pending"] = False
            win.hide_thinking()
            back_to_listening()
            return
        if not zh and not ja:
            thinking_ui["pending"] = False
            win.hide_thinking()
            win.add_system_message("（AI 回复失败，请检查 API 配置或网络）")
            back_to_listening()
            return
        # 历史存完整双语格式（含间隔符），保持格式一致性，避免 AI 后续模仿纯中文导致日语缺失
        if ja:
            history_content = f"中文：{zh}|||日语：{ja}"
        else:
            history_content = zh
        ai_history.setdefault(key, []).append({"role": "assistant", "content": history_content})
        # 只保留最近 6 条（3 轮），避免历史过长拖慢生成
        if len(ai_history[key]) > 6:
            del ai_history[key][:-6]
        # 保持 thinking 状态（合成语音期间仍显示「正在思考...」），不提前切 speaking
        # 后台合成日语语音；合成完成后（经信号切回主线程）再切说话态、同步显示文字 + 播放声音
        try:
            from .tts import DEFAULT_TEXT_LANGUAGE, synthesize_with_bang, is_muted

            def synth_worker():
                # 静音（点击喇叭 / 音量=0）或「静音模式」时跳过合成，加快回复速度；否则一定走合成
                if mute_mode_on() or is_muted() or float(cfg.get("volume", 0.5)) <= 0.0:
                    tts_ready_bridge.ready.emit(key, zh, ja, "")
                    return
                if ja:
                    # ★主语言取自 `tts.DEFAULT_TEXT_LANGUAGE`（= 「回复语言」的唯一真值），
                    #   别在这儿再写一次 "ja" —— 那会让「设定卡」页显示的语言与实际合成的不一致。
                    tmp = synthesize_with_bang(key, ja, text_language=DEFAULT_TEXT_LANGUAGE)
                else:
                    # 日语缺失（AI 输出纯中文）：用中文兜底合成，保证有声音
                    tmp = synthesize_with_bang(key, zh, text_language="zh")
                tts_ready_bridge.ready.emit(key, zh, ja, tmp or "")

            threading.Thread(target=synth_worker, daemon=True).start()
        except Exception:
            tts_ready_bridge.ready.emit(key, zh, ja, "")

    def _run_pending_action():
        """待执行的「打开类」动作：与语音播放同步执行（先出字 / 先出声两条路都调它）。

        ★定义在 `on_tts_ready` **之前**：它会被 `on_tts_ready` 引用，先定义后使用，
        免掉「事件在定义之前就被驱动到」的隐患。
        """
        action = pending_action.get("action")
        if not action:
            return
        pending_action["action"] = None

        def exec_worker():
            try:
                from .tools import execute_action
                execute_action(action)
            except Exception:
                pass

        threading.Thread(target=exec_worker, daemon=True).start()

    def on_tts_ready(key: str, zh: str, ja: str, tmp: str):
        # 已经睡下（说了「休息吧」/ 待机超时）：这是一条**迟到的回复**，别再出声、别再冒字。
        # 不拦的话，她「休息」之后还会在聊天区冒出一句回复（用户报的就是这类现象）。
        if asleep["v"]:
            if tmp:
                try:
                    import os as _os
                    _os.remove(tmp)      # 别把已经用不上的临时 wav 留在磁盘上
                except OSError:
                    pass
            return
        # 合成完成：移除思考提示、切说话态，显示文字与开始播放声音保持同步
        thinking_ui["pending"] = False
        win.hide_thinking()
        pet.set_state(State.SPEAKING.value)
        win.set_status(State.SPEAKING)
        name = cfg["roles"][key]["name"]
        win.add_assistant_message(key, name, zh)
        # 执行待执行的动作（打开类），与语音播放同步进行 —— 与 `_run_pending_action`
        # 是同一件事（先出字 / 先出声两条路都要执行），只留一份实现。
        _run_pending_action()
        if not tmp:
            # 没有音频可播（静音 / 静音模式 / 合成失败）：文字此刻**已经**显示，接下来只是
            # 「说话态」该停多久的问题。按文本长度估算（音频时长 ≈ 0.22 s/字），让静音与
            # 出声两种模式的说话态时长一致 —— 原先静音写死 ≤1.5s，长回复的动画一闪就没了。
            from .pipeline import silent_hold_seconds
            reply_silent["v"] = True
            rearm_listening()      # 并没有声音在播，别把「继续聆听」也一起拖住
            QTimer.singleShot(int(silent_hold_seconds(ja or zh) * 1000),
                              tts_done_bridge.done.emit)
            return
        # 后台播放声音，播放完成后回到聆听状态
        def play_worker():
            from .tts import play_wav
            import os
            try:
                play_wav(tmp)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                tts_done_bridge.done.emit()

        threading.Thread(target=play_worker, daemon=True).start()

    # ---- 流式回复的三个回传（第一句出声 / 中文陆续到达 / 整段完整）----

    def _finish_stream_message(key: str, zh: str):
        """把这条回复落进聊天记录（**只落一次**：兜底先出字、随后语音才就绪时别落两遍）。"""
        if stream_ui["saved"] or not zh:
            return
        stream_ui["saved"] = True
        win.finish_assistant_message(key, zh)

    def pet_bubble_allowed() -> bool:
        """桌宠聊天气泡的出现条件（**只此一条**）：**用户现在看不到聊天区**。

        ① 主界面关着（关闭到托盘 / 开机自启的静默启动）；② 主界面开着但当前不是聊天页
        （停在各管理页 / 设置页）；③ 停在聊天页但**最小化到任务栏**（`isVisible()` 仍是 True，
        可聊天区同样在屏幕上看不见）。三种情况下这一轮的回复就只剩声音 —— 静音模式下连声音也没有。
        **静音模式不参与判定**（2026-09-18 起），见 docs/01 F6、design.md 4.16。
        """
        return not win.is_chat_visible()

    def refresh_pet_bubble() -> None:
        """条件变了（换页 / 主界面显示 / 菜单跳转）之后重判一次：**不满足就立刻收起**。

        **不做「补弹」** —— 出现只在回复开场那一刻判（`_enter_speaking_ui`）：主界面停在管理 / 设置页
        时切页不会把上一轮的气泡补出来；反过来，条件变得不成立一定立刻收掉。
        """
        if not pet_bubble_allowed():
            pet.hide_bubble()

    def show_pet_bubble(zh: str) -> None:
        """桌宠聊天气泡：**出现条件只在这一处判** —— 主界面不在聊天界面（关着 / 停在管理·设置页）。

        用户看不到聊天区时，这一轮的回复就只剩声音（静音模式下连声音也没有）—— 气泡把这一轮的
        中文回复搬到贴图旁边（见 docs/01 F6 小节、design.md 4.16）。

        条件不满足时是**主动收起**（不是「只是不弹」）：否则「先冒气泡、后打开主界面」会在桌上
        留一个孤儿气泡。收起点：`back_to_listening` / `go_idle` / 兜底那一处，以及
        `show_main_window()` / `open_pet_nav()` / 换页回调这三条**重判**路径（`refresh_pet_bubble()`）。
        """
        if zh and pet_bubble_allowed():
            pet.show_bubble(zh)
        else:
            pet.hide_bubble()

    def sync_danger_card() -> None:
        """危险操作排程中 -> 把**屏幕正中央**的倒计时弹窗亮出来（回复开口的那一刻调）。

        用户口径：弹窗要**等语音和文字回复输出时同步弹出**，而不是排程一落地就抢在回复前面跳出来。
        所以「弹出」这个动作挂在这里（`_enter_speaking_ui` 是「文字与声音同刻出现」的唯一入口），
        每秒的 `_tick_danger` 只负责**改数字**（它那边有一条 `danger_ui["card"]` 守卫）。
        """
        from .tools import pending_danger
        pd = pending_danger()
        if not pd:
            return
        danger_ui["label"] = pd["label"]
        danger_ui["card"] = True
        win.set_notice(f"{pd['label']}将在 {pd['remaining']} 秒后执行 · 说「取消」可中止")
        win.show_danger_countdown(pd["label"], pd["remaining"])

    def _enter_speaking_ui(zh: str = ""):
        """切到「说话」界面态：关掉「思考中」提示与状态、桌宠转说话、按需冒气泡。

        开场有两条路径（正常开场 / 兜底先出字），**都要走这里** —— 漏一处就会出现
        「状态栏还写着『思考中…』、回复文字却已经显示」的错位（真机报过的 bug）。
        气泡也挂在这里：它是「说话」这个界面态的一部分，不该另开第二个入口。
        """
        thinking_ui["pending"] = False
        win.hide_thinking()
        pet.set_state(State.SPEAKING.value)
        win.set_status(State.SPEAKING)
        show_pet_bubble(zh)
        # 危险操作排程中：倒计时弹窗与这一句回复**同刻**亮出来（排在气泡后面，互不相干）
        sync_danger_card()

    def on_speak_started(key: str, zh: str):
        """整段语音要出声了：切说话态、建气泡（**一次性**写入完整中文）。

        这一刻就是「文字与声音同刻出现」的时刻 —— 中文已经吐完（闸门才放行），
        而且 `play_wav` 已经把音频设备跑起来了（开场回调就是它发的），所以这里
        写进去的就是完整文本，不再有「先出字、后出声」的错位。
        """
        # 已经睡下：这条回复是「休息吧」之前发出的，属于迟到 → 不出字、不出声、不执行动作
        if asleep["v"]:
            return
        _enter_speaking_ui(zh)
        stream_ui["key"] = key
        if zh and not stream_ui["bubble"]:
            win.begin_assistant_message(key, cfg["roles"][key]["name"], zh)
            stream_ui["bubble"] = True
        _finish_stream_message(key, zh)
        _run_pending_action()
        # 没有音频在播（静音 / 静音模式）：文字已经出来了，就别再占着「聆听」——
        # 说话态只管桌宠的姿态多久收回，不该挡住用户接着下一条指令。
        if reply_silent["v"]:
            rearm_listening()

    def _reply_text_fallback(seq: int):
        """最后兜底：中文已到、但语音迟迟不就绪（合成线程卡住）时，先把文字显示出来。

        它**放弃了同步**（文字先出、声音后到），所以必须同时切到「说话」界面态 ——
        否则「思考中」提示会与回复文字同时留在屏幕上。
        """
        if asleep["v"]:
            return      # 已经睡下：迟到的回复不冒字（go_idle 也已让 seq 作废）
        if seq != stream_ui["seq"] or stream_ui["bubble"] or not stream_ui["zh"]:
            return
        key = stream_ui["key"] or cfg["current_role"]
        _enter_speaking_ui(stream_ui["zh"])
        stream_ui["bubble"] = True
        win.begin_assistant_message(key, cfg["roles"][key]["name"], stream_ui["zh"])
        _finish_stream_message(key, stream_ui["zh"])

    def on_reply_done(key: str, zh: str, ja: str, api_name: str = ""):
        """整段回复已完整：存下完整中文、写 API 历史。**不建气泡** —— 气泡留给
        `on_speak_started`（文字要与声音同刻出现）；这里只备好文字，并挂一道兜底。"""
        # 这一轮若是「唤醒打招呼」：把**实际说出**的话记下来（供下次唤醒避免重复）。
        # ★放在最前面（连下面「API 被切走」那条提前 return 之前）—— 否则标记会一直挂着，
        #   下一条完全不相干的回复会被当成"招呼"记进去，反而让下次唤醒躲错句子。
        if greet_ui["pending"]:
            greet_ui["pending"] = False
            if zh:
                greet_ui["last"] = zh
        # 回复回来后若当前 API 已经换人，直接丢弃这条回复（同一时刻只有「当前 API」参与对话）
        if api_name and api_name != cfg.get("current_api"):
            thinking_ui["pending"] = False
            win.hide_thinking()
            back_to_listening()
            return
        if not zh:
            # 只有日语、没有中文 → 界面只显示中文，这条就没得显示（别把日语摆上去）
            win.add_system_message("（本次回复缺少中文版本，已跳过文字显示）")
            return
        stream_ui["zh"] = zh
        stream_ui["key"] = key
        # 历史存完整双语格式（含间隔符），保持格式一致性，避免 AI 后续模仿纯中文导致日语缺失
        history_content = f"日语：{ja}|||中文：{zh}" if ja else zh
        ai_history.setdefault(key, []).append({"role": "assistant", "content": history_content})
        if len(ai_history[key]) > 6:
            del ai_history[key][:-6]
        # 中文已到、就差语音 → 过了这段时间还没开场就先把文字显示出来（最后兜底）。
        # **窗口按日语字数自适应**（见 `reply_text_fallback_ms` 的标定）：固定 20s 会把
        # 「正常但慢」的长回复误判成卡死，反而制造出「先出字、后出声」。
        # **必须把本轮 seq 按值抓下来**：若让 lambda 到点时才读 stream_ui["seq"]，上一轮
        # 挂下、还没到点的定时器会在**下一轮中途**醒来，读到的已是下一轮的 seq → 守卫
        # 形同虚设，会把下一轮的文字提前捅出来（实测：第 2 轮文字比声音早 ~16.6s 出现）。
        seq_now = stream_ui["seq"]
        QTimer.singleShot(reply_text_fallback_ms(ja),
                          lambda: _reply_text_fallback(seq_now))

    def _ask_ai(key: str, text: str, add_user_to_history: bool = True,
                action_result: str | None = None, canned: tuple[str, str] | None = None):
        """开一轮回复。

        `canned=(中文, 日语)` = **不经过 AI**：直接把这两句丢进同一条流水线（危险操作排程用，
        见 `DANGER_REPLY`）。所以这一条**不需要 API Key**，也不受「API 被切走」那条守卫影响。
        """
        from .ai import chat_once, chat_stream, set_usage_sink  # 延迟导入 openai
        # 把「一次对话用掉多少 token」接到本地累计上（落 `stats.json`）。
        # ★读的是响应里**本来就会返回**的 usage，不发新请求、不额外耗 token；
        #   重复设置同一个出口是幂等的（每次回复设一遍，省掉「只在启动时装一次」的时序问题）。
        # ★2026-09-27：气泡里的「今日 Token 用量」已按用户要求**去掉显示**（数字不准），
        #   但**这条接线刻意保留** —— 底层累计照旧在跑（要彻底停掉统计需另行拍板；`stats.py` 没动）。
        set_usage_sink(stats.record_tokens)
        api = get_current_api(cfg)
        if canned is None and (not api or not api.get("api_key")):
            win.add_system_message("（未配置 API Key，请先在左侧点击铅笔 → 管理 API）")
            back_to_listening()
            return
        # ★人设在这里**不再读文件**（2026-09-30 晚，「设定卡」可切换）：取值统一走
        #   `config.resolve_persona_text` —— `load_config` 已经把该字段解析成人设**全文**，
        #   这里再过一遍是**兜底**（探针/测试会直接塞一份带路径的 cfg 进来，不该因此拿到
        #   一句「persona/alice.md」当 system prompt）。★唯一入口，别在别处再写第二份读法。
        #   切换即时生效：每轮回复都重新读一次 cfg，**下一句就用新设定**。
        persona = None if canned else resolve_persona_text(cfg["roles"][key]["persona"])
        history = ai_history.setdefault(key, [])
        if add_user_to_history:
            history.append({"role": "user", "content": text})
            # 只保留最近 6 条（3 轮），避免历史过长拖慢生成
            if len(history) > 6:
                del history[:-6]

        # 记录发起请求时用的是哪个 API：回复回来时若已被切换，则丢弃（不参与当前对话）。
        # 固定回复与 API 无关 -> `api_name` 留空，别让「切了 API」那条守卫把我们的通报吞掉。
        api_name = "" if canned is not None else str(api.get("name", "") or "")

        # 发起新一轮回复：重置界面状态。兜底定时器到 `on_reply_done`（拿到中文）时才挂 ——
        # 在那之前没有可显示的文字，挂了也无事可做。
        stream_ui["bubble"] = False
        stream_ui["saved"] = False
        stream_ui["zh"] = ""
        stream_ui["key"] = key
        stream_ui["seq"] += 1

        def worker():
            from .pipeline import SpeakPipeline
            from .tts import DEFAULT_TEXT_LANGUAGE, is_muted, play_wav, synthesize_with_bang

            # 上一条还在播 → 先掐掉，避免两段语音叠在一起
            prev = pipeline_state.get("pipe")
            if prev is not None:
                prev.cancel()
            muted = False
            try:
                muted = is_muted() or float(cfg.get("volume", 0.5)) <= 0.0
            except Exception:
                pass
            # 静音模式：AI 只出中文，且**完全不做合成**（连「中文兜底合成」也跳过）。
            # 于是文字在中文吐完（`done` → 放行闸门）的那一刻就出现，不必再等语音。
            # 注意仍要走同一条流水线：`reveal` / `_enter_speaking_ui` 是唯一入口，
            # 合成返回 None 时流水线会**就地**放行 —— 这是既有的「静音」行为，不是新分支。
            zh_only = mute_mode_on()
            silent = muted or zh_only
            # 告诉主线程「这一轮没有音频」：文字一显示就恢复聆听（见 on_speak_started）。
            # 只是个 bool 标志，而且**必定**在 reveal 之前写、由主线程在 reveal 时读，
            # 所以不需要更重的同步手段。
            reply_silent["v"] = silent

            zh_holder = {"zh": ""}       # 中文吐完后的完整文本（on_started 拿它建气泡）
            lang = {"v": DEFAULT_TEXT_LANGUAGE}   # 日语缺失时翻成 "zh" 走中文兜底合成
            ja_issued = {"v": False}     # 日语整段是否已经提交合成
            done_seen = {"v": False}

            def synth(t):
                # 静音 / 静音模式：跳过合成（文字照常显示），省掉一次无用的推理
                if silent:
                    return None
                return synthesize_with_bang(key, t, text_language=lang["v"])

            def play(path, on_started):
                # 界面文字挂到「声音真正开始」那一刻：打开音频设备、读文件都在那之前，
                # 若在 play 之前就显示文字，真机上会「先看见字、后听见声」。
                play_wav(path, on_started=on_started)

            def remove(path):
                import os
                try:
                    os.remove(path)
                except OSError:
                    pass

            def should_start():
                # 开场前核一次 API 是否已被切走（切走了就当这条回复作废：不出字、不出声）
                return not (api_name and api_name != cfg.get("current_api"))

            def on_started():
                speak_start_bridge.started.emit(key, zh_holder["zh"])

            def on_finished():
                tts_done_bridge.done.emit()

            pipe = SpeakPipeline(synth=synth, play=play, remove=remove,
                                 on_started=on_started, on_finished=on_finished,
                                 should_start=should_start)
            pipeline_state["pipe"] = pipe

            if canned is not None:
                # 固定回复：不进 AI、不等模型。走**同一条流水线**（`speak` 起合成线程、
                # `release_text_gate` 放行开场）—— 于是「文字与声音同刻出现」这条既有保证原样成立，
                # 而屏幕正中央那张倒计时弹窗就挂在这一刻亮起来（见 `_enter_speaking_ui`）。
                zh_canned, ja_canned = canned
                zh_holder["zh"] = zh_canned
                reply_done_bridge.done.emit(key, zh_canned, ja_canned, api_name)
                pipe.speak(ja_canned)
                pipe.release_text_gate()
                return

            def on_event(kind, payload):
                """AI 流式线程的回调：日语整段一到就送去合成；中文吐完才放行开场。"""
                if kind == "ja":
                    # 分界符出现 → 日语已完整。整段**一次**提交：合成与「中文段的生成」并行，
                    # 于是既无缝、又不比逐句慢多少。
                    if not ja_issued["v"]:
                        ja_issued["v"] = True
                        pipe.speak(payload)
                elif kind == "done":
                    payload = payload or {}
                    zh_holder["zh"] = (payload.get("zh") or zh_holder["zh"]).strip()
                    done_seen["v"] = True
                    reply_done_bridge.done.emit(key, payload.get("zh", ""),
                                                payload.get("ja", ""), api_name)
                    # 中文吐完 → 放行开场（合成若也已就绪，文字与声音此刻同时出现）
                    pipe.release_text_gate()

            failure = False
            reply = None
            try:
                # 直接把整个 API 条目交给 chat_stream：其中含 base_url / model，
                # 每个 API 可以用不同的服务与模型（兼容任意 OpenAI 兼容接口）
                reply = chat_stream(api, persona, history, text,
                                    action_result=action_result, on_event=on_event,
                                    zh_only=zh_only)
                failure = bool(reply.get("truncated"))
            except Exception:  # noqa: BLE001
                # ★2026-10-01：这里以前是**光秃秃的 `failure = True`** —— 整个 API 异常
                #   零痕迹地消失，用户看到的就是「AI 不回复」。现在留完整调用栈。
                #   ★只加这一行，控制流（置 failure、走回退）一个字没改。
                LOG.exception("流式回复失败（api=%s）⇒ 回退非流式", api_name)
                failure = True

            if failure and not pipe.has_started:
                # **还没开场**才值得回退：回退到非流式路径（带"被截断 / 缺日语"的重试保障）。
                # 已经开场就不能重来，否则同一段会被念两遍。
                pipe.cancel()
                try:
                    reply = chat_once(api, persona, history, text,
                                      action_result=action_result, zh_only=zh_only)
                except Exception:  # noqa: BLE001
                    # ★同上的第二处：非流式回退也失败 ⇒ 这条回复变成空字符串。
                    LOG.exception("非流式回退也失败（api=%s）⇒ 本条回复为空", api_name)
                    reply = {"zh": "", "ja": ""}
                reply_bridge.reply_ready.emit(key, reply["zh"], reply["ja"], api_name)
                return      # 余下交给非流式路径（on_ai_reply → on_tts_ready）
            if not done_seen["v"]:
                # 没走到 done（流式中断）→ 用手上最好的结果收尾
                reply_done_bridge.done.emit(key, (reply or {}).get("zh") or zh_holder["zh"],
                                            (reply or {}).get("ja", ""), api_name)
            # 整条流都没拿到日语（模型没按人设输出）→ 现在补一次：
            # 有日语就合成日语；没有就用**中文兜底合成**，保证「一定有声音」（沿用原行为）。
            if not ja_issued["v"]:
                zh_final = ((reply or {}).get("zh") or zh_holder["zh"] or "").strip()
                ja_final = ((reply or {}).get("ja") or "").strip()
                if ja_final:
                    pipe.speak(ja_final)
                elif zh_final:
                    zh_holder["zh"] = zh_final
                    lang["v"] = "zh"
                    pipe.speak(zh_final)
                else:
                    pipe.speak("")      # 什么都没有：只走节拍（界面那边会提示回复失败）
            # 兜底：中文若没到也放行闸门，免得合成线程干等（已放行过就是幂等空操作）
            pipe.release_text_gate()

        threading.Thread(target=worker, daemon=True).start()

    def set_mute_mode(on: bool) -> None:
        """切换静音模式（通用设置里的滑块与语音开关共用这条落地逻辑）。

        ★★2026-09-29 起静音模式是**落盘的偏好**（用户口径「完全退出后重开要保留开关状态」）：
        改内存 cfg 之后**必须 `save_config(cfg)`**。两条路各写各的、都要写盘 —— 设置页那条
        （`gui._toggle_mute_mode`）自己会存；**语音这条路**以前只改内存（因为当时 `save_config`
        会把它剔掉），本次一并补上。只补一边的话会变成「用语音开的静音重启就丢、用滑块开的
        就记得住」—— 同一个开关两种记性，是最难查的那类不一致。
        """
        on = bool(on)
        cfg.setdefault("general", {})["mute_mode"] = on
        save_config(cfg)          # ★★ 两条路都落盘（唯一真值仍是 cfg["general"]["mute_mode"]）
        win.sync_mute_mode(on)    # 通用设置里那一行跟着动（只同步这一行，不整页重建）
        # 桌宠提示：这条路是**语音**开关（「开启 / 关闭静音模式」）；通用设置里点滑块那条
        # 路走 gui.notify_mute_mode 的回调。两条路各弹各的，不会重叠。
        pet.flash_toast("已进入静音模式" if on else "已退出静音模式")
        # 注意：这里**不再**收聊天气泡 —— 2026-09-18 起出现条件里没有静音模式了
        # （只看「主界面在不在聊天界面」），关掉静音不会让正在显示的气泡失去理由。
        win.add_system_message(
            "已开启静音模式：之后的回复只输出中文、不再合成语音，速度会快很多。"
            "（已记住该设置，重启后仍是开启）"
            if on else
            "已关闭静音模式：恢复日语语音。（已记住该设置）"
        )

    def on_command(text: str):
        # 静音模式的语音开关：本地识别、直接切换（不经过 AI、也不合成语音 ——
        # 否则「开启静音模式」还得先合成一句日语说出来，本末倒置）。
        # **必须早于 `detect_action`**：见 MUTE_ON_WORDS 的注释。
        clean_cmd = strip_punct(text)
        if any(w in clean_cmd for w in MUTE_ON_WORDS):
            win.add_user_message(text)
            set_mute_mode(True)
            wake_timer.start(WAKE_TIMEOUT_MS)  # 保持聆听，接着还能继续下指令
            return
        if any(w in clean_cmd for w in MUTE_OFF_WORDS):
            win.add_user_message(text)
            set_mute_mode(False)
            wake_timer.start(WAKE_TIMEOUT_MS)
            return
        # 节能形态的语音开关：同样本地识别、直接切换（不经 AI）。与静音模式的区别是
        # **只在状态真的需要变时才认** —— 「退出」那组含「恢复正常」这类很泛的词，
        # 只有她确实处于节能态时才允许命中，免得闲聊里一句「恢复正常了吗」把模式切了。
        ps_on = pet.is_power_save()
        if not ps_on and any(w in clean_cmd for w in POWER_SAVE_ON_WORDS):
            win.add_user_message(text)
            pet.set_power_save(True)          # 提示由 pet 的切换回调统一落
            wake_timer.start(WAKE_TIMEOUT_MS)
            return
        if ps_on and any(w in clean_cmd for w in POWER_SAVE_OFF_WORDS):
            win.add_user_message(text)
            pet.set_power_save(False)
            wake_timer.start(WAKE_TIMEOUT_MS)
            return
        # 撤销窗口优先：仅当确实有排程中的危险操作时，「取消」类词才被当作中止指令
        from .tools import (
            cancel_pending_danger,
            check_permission,
            detect_action,
            execute_action,
            is_danger,
            pending_danger,
        )

        cancelled = None
        canned = None
        pd = pending_danger()
        # 「立刻关机」优先：**有排程**才跳过倒计时当场执行（与弹窗左边那个按钮同一条路）。
        # 没有排程时这里什么都不做 —— 让它落进下面的普通「关机」分支（检测 → 排程 → 弹窗），
        # 这正是「没进倒计时时说立刻关机，只跳出弹窗、不直接关机」。
        if pd and any(w in clean_cmd for w in RUN_NOW_WORDS):
            from .tools import run_pending_danger_now
            label = run_pending_danger_now() or pd["label"]
            danger_ui["label"] = None   # 防止 tick 的「已执行」收尾提示误报
            win.set_notice("")
            win.hide_danger_countdown()  # 当场淡出（不等下一秒 tick）
            win.add_user_message(text)
            win.add_system_message(f"已立刻执行「{label}」，不再等待倒计时。")
            wake_timer.start(WAKE_TIMEOUT_MS)
            return
        if pd and any(w in text for w in CANCEL_WORDS):
            cancelled = pd["label"]
            cancel_pending_danger()
            danger_ui["label"] = None  # 防止 tick 的「已执行」收尾提示误报
            win.set_notice("")
            win.cancel_danger_countdown()  # 弹窗转**红色取消态**（保持 1.5s 再自己淡出）
            win.hide_danger_countdown()    # 红色态下是空操作：别让下面这行把它当场收掉
            win.add_system_message(f"已中止「{cancelled}」，没有执行。")
        # 休眠指令：睡吧/休息吧 等 → 进入待机
        elif is_sleep_word(text):
            go_idle("好的，我先休息了～")
            return
        # 普通指令：进入思考，异步调用 DeepSeek
        wake_timer.stop()
        listening["active"] = False
        # 她开始答话了 = 不再「等指令」，常驻提示收掉（「已唤醒」那种事件提示还留着，
        # 这一轮说完由 back_to_listening() 把「待机中」挂回来）。
        pet.clear_state_toast()
        pet.set_state(State.THINKING.value)
        win.set_status(State.THINKING)
        # 先弹出用户消息
        win.add_user_message(text)
        # 分流：撤销 → 取消说明；查询类先执行取结果；危险级排入延迟队列；打开类暂存等语音同步执行
        action_result = None
        pending_action["action"] = None
        try:
            if cancelled:
                action_result = (
                    f"[已取消] 老师要求中止，原定要执行的「{cancelled}」已撤销、没有执行。"
                )
            else:
                action = detect_action(text)
                if action:
                    ok, reason = check_permission(action, text)
                    if not ok:
                        # 被白名单挡住：把拒绝原因交给 AI，由角色如实说明（不静默失败）
                        action_result = reason
                    elif is_danger(action):
                        # 危险级：排入延迟队列，期间可说「取消」中止。回复**走固定文案**（不经 AI）——
                        # 「任务执行中…」/「ミッション実行中…」既快又不会被模型改写语义；
                        # 倒计时弹窗会跟着这句回复**同刻**弹出来（见 `sync_danger_card`）。
                        execute_action(action, text)
                        canned = DANGER_REPLY
                    elif action.get("type") in ("list_dir", "query_info"):
                        # 查询类：先执行，结果交给 AI 回应（如"桌面上有XX文件"）
                        action_result = execute_action(action, text)
                    else:
                        # 打开类：暂存，等语音开始播放时同步执行
                        pending_action["action"] = action
                        # ★★2026-09-30（用户报「打开文件夹/网站时会说『不清楚』却照样执行」）：
                        #   这一支**现在还没执行**，所以以前 `action_result` 是 None —— 模型手里
                        #   只有老师那句话，就自己发挥（常答成"爱丽丝不太清楚…"），而动作其实
                        #   照做（`_run_pending_action` 在语音开场时执行）⇒ **言行不一致**。
                        #   这里把"马上要做什么"如实交给模型（见 `_pending_action_hint`）。
                        #   ★执行时机**没有变**（仍是语音开场时同步执行），也不是放宽权限。
                        action_result = _pending_action_hint(action)
                        # 「打开软件」→ 桌宠进入节能形态待机，免得压住刚打开的窗口
                        # （用户要求）。权限已在上一步校验通过，这里只是提前把桌宠让开。
                        if action.get("type") == "open_app":
                            pet.set_power_save(True)
        except Exception:
            action_result = None
            pending_action["action"] = None
        # 「正在思考...」提示延迟 1.5 秒后出现（微信式：先消息、后提示）；若 AI 已回复则跳过
        name = cfg["roles"][cfg["current_role"]]["name"]
        thinking_ui["pending"] = True
        QTimer.singleShot(1500, lambda: _show_thinking_delayed(name))
        _ask_ai(cfg["current_role"], text, action_result=action_result, canned=canned)

    def on_text(text: str):
        text = (text or "").strip()
        if not text:
            return
        key, word = match_wake_word(text)
        # ★★★唤醒流程成立的条件是「**还没醒**」（`awake` 的含义见它的定义处），
        #   而**不是**「此刻不在聆听」。两者差别就是「反复被唤醒」这个 bug：
        #   她思考 / 说话的整段时间里 `listening["active"]` 都是 False，改之前
        #   那几秒里再喊一次唤醒词就会**又**走一遍下面这一整套（又弹「已唤醒」、
        #   又落系统消息、又主动打招呼）。
        if key and not awake["v"]:
            switch_role(key)
            # 唤醒 = 解除「睡下」。**必须先于 `on_command`** —— 否则她醒来后
            # 第一轮回复的收尾会被 `rearm_listening` 的 asleep 守卫吃掉，
            # 变成「叫醒了却只答一句、之后又聋了」。
            asleep["v"] = False
            awake["v"] = True
            listening["active"] = True
            # 两层一起下：事件先盖在常驻状态上，2s 后淡出、自然露出「待机中…」。
            # （她要是接着就答话，on_command / back_to_listening() 会接管这两层。）
            pet.set_state_toast("待机中", dots=True)
            pet.flash_toast("已唤醒")
            pet.set_state(State.LISTENING.value)
            win.set_status(State.LISTENING)
            win.add_system_message(f"已唤醒：{cfg['roles'][key]['name']}")
            # 去掉唤醒词本身后，剩余内容去标点判断是否真有指令
            rest = strip_punct(text.split(word, 1)[-1])
            if rest:
                on_command(text)
            else:
                # 只喊了唤醒词：角色主动打招呼
                wake_timer.stop()
                # （`listening["active"]` 这里要置回 False：她转入思考，不再「等指令」）
                listening["active"] = False
                pet.clear_state_toast()   # 转思考：常驻提示收掉（「已唤醒」事件还留着）
                pet.set_state(State.THINKING.value)
                win.set_status(State.THINKING)
                # 「思考中」提示延迟 1.5 秒出现（先"已唤醒"消息，后思考提示）
                gname = cfg["roles"][key]["name"]
                thinking_ui["pending"] = True
                QTimer.singleShot(1500, lambda: _show_thinking_delayed(gname))
                # 唤醒招呼：提示词**轮转换角度 + 回带上次那句**（见 `wake_greeting_prompt`）。
                # 修的是用户 2026-09-30 报的「初次唤醒太单调、出现重复同一句话」——
                # 招呼不进历史（`add_user_to_history=False`），所以必须**主动把上次那句喂回去**，
                # 否则模型在完全相同的上下文里会稳定地给出同一句。
                greet_ui["pending"] = True
                _ask_ai(
                    key,
                    wake_greeting_prompt(greet_ui["last"], greet_ui["index"]),
                    add_user_to_history=False,
                )
                greet_ui["index"] += 1
            return
        # 已唤醒（聆听中）：唤醒词**不再有特殊含义**，一律当普通说话。
        # ★两条路都走 `on_command`，但**进入条件不同**，别图省事合并成只看 `awake`：
        #   · 在聆听（`listening["active"]`）：**任何**话都当普通说话 —— 含只喊唤醒词。
        #     ★改之前这一支会把「纯唤醒词回声」**吞掉**（只把超时重新计时）。用户
        #       2026-09-27 明确要求「再识别到唤醒词则正常交流」，所以现在连只喊名字也发出去。
        #   · 不在聆听、但醒着（她正在思考 / 说话）：**只有唤醒词**当普通话说，其余照旧
        #     丢弃 —— 那几秒是她的「说话时间」，不能变成谁出声都插一嘴。
        if listening["active"] or key:
            on_command(text)

    bridge = _TextBridge()
    bridge.text_ready.connect(on_text)
    reply_bridge = _ReplyBridge()
    reply_bridge.reply_ready.connect(on_ai_reply)
    tts_ready_bridge = _TtsReadyBridge()
    tts_ready_bridge.ready.connect(on_tts_ready)
    tts_done_bridge = _TtsDoneBridge()
    tts_done_bridge.done.connect(back_to_listening)
    # 整段回复（流水线）两条回传：开场（文字与声音同刻出现）+ 整段就绪（写历史）
    speak_start_bridge = _SpeakStartBridge()
    speak_start_bridge.started.connect(on_speak_started)
    reply_done_bridge = _ReplyDoneBridge()
    reply_done_bridge.done.connect(on_reply_done)

    # 先显示窗口和桌宠（不等语音识别初始化，避免启动慢）
    if silent_boot:
        # 开机自启：**不弹主界面**，只把桌宠放到桌面上（托盘点一下才打开窗口）
        win.hide()
    else:
        win.show()
        # ★P2（2026-10-02）：首次使用引导 —— 只在这台机器上**一个 API 都还没配**时才弹。
        #   ★★引导是**非阻塞**的（`FirstRunDialog.show_guide` 走 `open()` 而不是 `exec()`）：
        #     `exec()` 会在这里嵌一个模态事件循环，`main()` 就再也回不去了 ——
        #     那些「真跑一次 main()」的探针（boot_probe / reply_probe…）会直接挂到硬超时。
        #   ★延后 600ms：先把主窗口画出来，别一开机就糊一张弹窗在屏幕上。
        if health.first_run_needed(cfg):
            QTimer.singleShot(600, win.show_first_run)

    pet.move(*pet_default_pos(pet))

    pet.show()
    # ★ 开机自启这条路：登录早期桌面 / 外壳还没稳定，Qt 可能只把 `WS_EX_TOPMOST`「位」挂上、
    #   却没把窗口放进「置顶带」⇒ 之后任何窗口（浏览器）一激活就盖住她（2026-09-21 实测定位）。
    #   `show()` 已在 showEvent 里兜过一次，这里再补一次（此刻窗户已真在屏上），
    #   剩下的交给 PetWindow 那张看门狗表。
    pet.ensure_topmost_band()

    # **刻意不挂「休眠中」提示**：冷启动 / 开机自启不是「用户让她睡下」，一上来就顶个
    # 提示反而吵。「休眠中」只在 go_idle()（说了「休息吧」/ 唤醒超时）那一刻弹。
    # 桌宠进入休眠（待机）状态：只播待机帧，等唤醒词把它叫醒；麦克风仍在监听唤醒词
    if silent_boot:
        pet.set_state(State.IDLE.value)
        win.set_status(State.IDLE)
        win.add_system_message(
            "已开机自启：主界面收在托盘里（点托盘图标可打开），"
            f"喊「{cfg['roles'][role_key]['name']}」唤醒我～"
        )
    if healed:
        win.add_system_message(f"开机自启的启动路径已自动更新为新位置：{healed_cmd}")

    # 后台自动拉起 GPT-SoVITS 语音合成服务（不在则启动，避免手动开 start_api）
    try:
        from .tts import start_in_background as start_tts, set_volume as set_tts_volume
        set_tts_volume(float(cfg.get("volume", 0.5)))
        start_tts()
    except Exception:
        # ★「没声音」的第一现场：以前这里是 `pass`，真因完全无从查起。
        LOG.exception("后台拉起语音合成服务失败（不影响窗口显示）")

    # 语音识别初始化放到后台线程（加载模型约 1s+，不阻塞窗口显示）
    def init_asr():
        from .asr import MicListener, Recognizer  # 延迟导入 sherpa_onnx
        nonlocal listener
        try:
            recognizer = Recognizer()
            mic = MicListener(recognizer, on_text=bridge.text_ready.emit)
            mic.start()
            listener = mic
            asr_state["ok"] = True

            def _report_asr_ok():
                win.add_system_message("语音识别已就绪，喊「爱丽丝」或「艾莲」试试")
                # ★P2：状态条「正在初始化…」→「一切就绪」（要重探事实才敢说"就绪"）。
                #   ★这个回调跑在**主线程**（QTimer），碰 Qt 是安全的。
                win.refresh_health()

            QTimer.singleShot(0, _report_asr_ok)
        except Exception as e:  # noqa: BLE001
            # ★界面那条灰字里只有 `str(e)`（常常就一句 `[Errno 2] ...`，指不出任何位置）；
            #   完整的调用栈进日志。用户看的和你看的，从此是两份东西。
            LOG.exception("语音识别初始化失败")
            listener = None
            asr_state["ok"] = False
            # ★★必须在 except 块内先把原因取成局部变量：`except ... as e` 在**块结束时会 `del e`**
            #   （连闭包里的 cell 一起清空）⇒ 这个内层函数是 QTimer 稍后在主线程才调的，
            #   那一刻 `e` 已经没了，会抛 NameError —— 而 stderr 早已被兜到 devnull ⇒ 静默。
            #   （2026-10-02 ruff 的 F821 抓出来的：这条灰字此前**从来没成功显示过**。）
            reason = str(e)

            def _report_asr_fail():
                win.add_system_message(f"语音识别未就绪：{reason}")
                win.refresh_health()      # ★P2：状态条当场说明「喊不醒」

            QTimer.singleShot(0, _report_asr_fail)

    threading.Thread(target=init_asr, daemon=True).start()

    # 危险级操作倒计时：左栏提示 + **屏幕正中央的倒计时弹窗**，到点执行后补一条「已执行」提示
    def _danger_elapsed(pd) -> int:
        """排程已经过去几秒（「设定的延迟 − 剩余」）——只给下面那条兜底用。"""
        try:
            from .tools import get_permissions
            return max(0, int(get_permissions().get("danger_delay", 0)) - int(pd["remaining"]))
        except Exception:  # noqa: BLE001
            return 0

    def _tick_danger():
        from .tools import pending_danger
        pd = pending_danger()
        if pd:
            danger_ui["label"] = pd["label"]
            win.set_notice(f"{pd['label']}将在 {pd['remaining']} 秒后执行 · 说「取消」可中止")
            # **弹窗与回复同刻出现**：回复还没开口就先不弹（`sync_danger_card` 会在开口那一刻弹）。
            # 兜底：万一那一轮回复没开成（合成线程挂了 / 流水线被掐掉），排程过了 2 秒也把弹窗放出来 ——
            # 宁可晚一点，也不能让「倒计时正在跑」这件事没有界面。
            if danger_ui["card"] or _danger_elapsed(pd) >= 2:
                danger_ui["card"] = True
                win.show_danger_countdown(pd["label"], pd["remaining"])
            return
        # 队列空了**无条件**收弹窗：执行、语音取消、被新排程顶掉都算
        #（取消那条路会把 danger_ui["label"] 提前置 None，所以不能放进下面的 if 里）
        danger_ui["card"] = False
        win.hide_danger_countdown()
        if danger_ui["label"]:
            label = danger_ui["label"]
            danger_ui["label"] = None
            win.set_notice("")
            win.add_system_message(f"已执行「{label}」")

    danger_timer = QTimer()
    danger_timer.setInterval(1000)
    danger_timer.timeout.connect(_tick_danger)
    danger_timer.start()

    # ---- 音色克隆模型缺失 ⇒ 启动即静音（2026-09-22）----
    # 与设置页里那条「静音滑块锁死在开」是**同一个规则**（docs/01 F7 / docs/02 §22.5），
    # 这里只是让它在「从没打开过设置页」的情况下也生效：没有模型时合成必然失败，
    # 与其让她默默一声不出（用户只会以为软件坏了），不如直接进静音模式 ——
    # 回复更快，界面上也说得清。模型就位时这一段什么都不做（静音仍按老规则从「关」开始）。
    def _apply_model_gate():
        from . import voice_model
        if voice_model.is_installed(cfg):
            win.refresh_health()          # ★P2：让状态条拿到「模型就位」这个事实
            return
        cfg.setdefault("general", {})["mute_mode"] = True
        win.sync_mute_mode(True)
        win.add_system_message(
            "没有找到音色克隆模型，已自动进入静音模式（回复只输出中文、不出声）。"
            "可在「设置 → 通用设置 → 语音模型」里查看状态。"
        )
        win.refresh_health()              # ★P2：刚被判进静音 ⇒ 状态条要跟着说这一条

    _apply_model_gate()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
