"""桌宠悬浮窗：透明、置顶、可拖动，按状态播放 PNG 帧序列，并按图片实际比例显示。"""
import ctypes
import math
import random
import re
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QEvent, QEventLoop, QPoint, QPointF, QRect, QRectF, QSize,
    Qt, QTimer, QVariantAnimation,
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QImage, QPainter, QPainterPath, QPen,
    QPixmap, QPolygonF, QRegion, QTextCharFormat, QTextCursor, QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QLabel, QWidget,
)

from .patpat import (
    PATPAT_CLICK_SLOP,
    PATPAT_F1_MS,
    PATPAT_F2_MS,
    PATPAT_SEQ,
    PATPAT_SQUASH_MS,
    PATPAT_TOTAL_MS,
    PatPatSound,
    patpat_frames,
    patpat_pos,
    patpat_size,
    patpat_squash_drop,
    patpat_squash_size,
)
# ⚠️ 这里**不**导入 thinking 的 `SIDE_*` / `FACE_*`：pet.py 自己那份常量（下面几行）就是同一个
#    口径，两边是同一组字符串；各留一份、互不覆盖，免得出现「谁盖了谁」的困惑。
from .thinking import (
    THINKING_CANVAS,
    THINKING_FLIP_MS,
    THINKING_HOLD_MS,
    THINKING_IN_TOTAL_MS,
    THINKING_LABEL_COLOR,
    THINKING_LABEL_PX,
    THINKING_LINE_GAP,
    THINKING_MASH_MS,
    THINKING_OFFSETS,
    THINKING_OUT_MS,
    THINKING_SWITCH_MS,
    THINKING_TEXT_FADE_MS,
    THINKING_TEXT_FONT,
    THINKING_VALUE_COLOR,
    THINKING_VALUE_PX,
    pick_content,
    thinking_canvas_size,
    thinking_face,
    thinking_frame_opacity,
    thinking_frame_rect,
    thinking_frames,
    thinking_pool,
    thinking_pos,
    thinking_scale,
    thinking_side,
    thinking_text_rect,
)
from . import stats
from .config import is_role_switchable    # ★角色的「可切换性」唯一真值（docs/02 §24）
from .volume import VolumeSlider

STATES = ("idle", "listening", "thinking", "speaking", "working")
DISPLAY_HEIGHT = 250  # 桌宠固定显示高度（px），宽度按原图比例缩放

# ---- 节能形态（桌宠「压扁」成扁平待机形态）----
# 文件名带这个标记的贴图（如 `爱丽丝_节能.png`）**不参与普通帧循环** —— 否则它会和站姿
# 交替闪烁；它只在节能模式下单独显示。
POWER_SAVE_MARK = "_节能"
# 进入 / 退出节能形态的**整体**动画时长（ms）：前半段压扁 + 变淡，后半段淡回来。
POWER_SAVE_MS = 600
# 交换贴图发生的那个不透明度（用户指定 30%）：降到 30% 时换图，再从这里升回 100%。
POWER_SAVE_SWAP_OPACITY = 0.30

# ---- 聊天气泡（静音模式 + 主界面关闭时才出现）----
# 规格见 design.md 4.16、实现说明见 docs/02 第 14 节。**出现条件不在这里判**：pet.py 只管画，
# 「静音模式开 + 主界面关」由 main.show_pet_bubble() 一处判定。
# 2026-09-17 二改：边框 4 → 2（原来的一半）、弹出 45° → 15°、新增左右 / 上下翻转（平移 500ms）。
# 2026-09-17 三改：圆角 12 → 3；尾巴改成「同款描边 + 底」的**圆角**三角，
#   并且面朝下那种朝向也翻过来（两种朝向自此互为上下镜像，尾巴尖一律朝贴图那一侧）。
# 2026-09-17 四改：超长回复**分段显示** —— 单段正文块高上限 96px（≈6 行），超出的部分进下一段；
#   段间**只淡文字**（各 200ms），本体与尾巴全程不动。
BUBBLE_W = 120               # 气泡本体固定宽（px），不随文字变宽
BUBBLE_BORDER = 2            # 边框厚度（px）
BUBBLE_RADIUS = 3            # 圆角（本体与尾巴共用；2026-09-17 三改：12 → 3）
BUBBLE_PAD = 8               # 文字距边框**内沿**（px）
BUBBLE_FONT_PX = 13          # 文字字号（与正文一致）
BUBBLE_TAIL_LEG = 15         # 尾巴：等腰直角三角形直角边长（px）
BUBBLE_TAIL_GAP = 4          # 尾巴 a 边与**下**边框的间隔（面朝下时）
BUBBLE_TAIL_GAP_UP = 5       # 尾巴 a 边与**上**边框的间隔（面朝上时）
BUBBLE_GAP_X = 5             # 尾巴 b 边与贴图的横向间隔（px）
BUBBLE_ANCHOR_RATIO = 5 / 7  # 锚点高度 = 贴图高度的 5/7（**自贴图底边往上量**）
BUBBLE_FLIP_RATIO = 2 / 7    # 上翻转后的锚点高度 = 2/7（同口径，5/7 的镜像）
BUBBLE_POP_MS = 300          # 弹出动画时长（ms）
BUBBLE_FADE_MS = 200         # 整条气泡淡出时长（ms）
BUBBLE_MAX_TEXT_H = 96       # 单段正文块高上限（px）：真机 16px 行高 → 6 行；超出的部分进下一段
BUBBLE_TEXT_FADE_MS = 200    # 分段换字：文字淡出 / 淡入各 200ms（**只淡文字**，本体尾巴不动）
BUBBLE_PAGE_MIN_MS = 1200    # 单段最短停留（与 pipeline._SILENT_MIN 同值）
BUBBLE_PAGE_PER_CHAR_MS = 220  # 单段停留 = max(下限, 220ms × 本段字数)，与说话态同一条标定
BUBBLE_PAGE_BREAK_BACK = 6   # 段边界往回让到最近句读的最大字数（让本段尽量以句读收尾）
BUBBLE_PAGE_BREAK_BACK_LONG = 14  # 切点被标点卡住（带不进本段）时的回让上限：不把「，。」甩到下一段开头
BUBBLE_PAGE_MIN_TAIL = 12    # 尾段不足这么多字时，把「本段 + 尾巴」对半分（别切出「方。」那样的碎段）
BUBBLE_FLIP_MS = 500         # 翻转（左右 / 上下让位）的平移动画时长（ms）
BUBBLE_FLIP_HYST = 20        # 翻转迟滞（px）：贴边来回拖不许来回翻
BUBBLE_POP_ANGLE = 15.0      # 起始旋转（视觉**逆时针** 15 度；Qt 正角是顺时针，所以取负）
BUBBLE_POP_SCALE = 0.30      # 起始缩放
BUBBLE_COLOR_BORDER = "#0C447C"
BUBBLE_COLOR_FILL = "#E6F1FB"
BUBBLE_COLOR_TEXT = "#334155"
_BUBBLE_BBOX_STEPS = 40      # 并集包围盒的采样段数

# ---- 状态提示气泡（贴图**正上方**的那条「待机中… / 休眠中 / 已唤醒」）----
# 规格见 design.md 4.17、实现说明见 docs/02 §15。**只看状态**：不看静音模式、也不看主界面开不开
# （她是「脑袋上顶着一条状态」，任何显示场景都成立）。
# 与聊天气泡的正相反：那个是「宽钉死、高随文字」，这个是「**高钉死、宽随文字**」。
TOAST_H = 30             # 本体固定高（px）：略高于一行文字（真机 17 / 离屏 15）
TOAST_PAD_X = 9          # 文字左右各留的内边距（px）
TOAST_GAP = 5            # 气泡**下沿**距贴图**顶边**（px）
TOAST_RADIUS = 3         # 小圆角（与聊天气泡共用同一个值）
TOAST_BORDER = 2         # 边框厚度（px，与聊天气泡同款）
TOAST_HOLD_MS = 2000     # 瞬态提示（一闪事件 / `休眠中`）**淡入结束后**停留多久（ms），到点淡出
TOAST_DOT_MS = 1000      # 「待机中」点动画：1s 加一个点
TOAST_DOT_MAX = 3        # 加到 3 个点就清空重来
TOAST_POP_MS = 500       # 弹出 / 收起时长（ms，两者同长）
TOAST_POP_DY = 5         # 上下平移量（px）：弹出从下方 5px 上来、收起再往上走 5px
TOAST_MIN_SCALE = 0.5    # 缩放的起止档：弹出 50%→100%、收起 100%→50%
TOAST_FLIP_MS = 500      # 上方放不下 -> 让到贴图**下方**的平移动画（ms，与聊天气泡翻转同一个值）
TOAST_FLIP_HYST = 20     # 让位迟滞（px）：贴屏幕上沿来回拖不许来回跳

# 朝向：side = 气泡在贴图的哪一侧；face = 尾巴朝下（气泡挂在锚点上方）还是朝上（挂在下方）
SIDE_LEFT = "left"
SIDE_RIGHT = "right"
FACE_DOWN = "down"
FACE_UP = "up"

# ---- 置顶「入带」看门狗（2026-09-21 实测：`WS_EX_TOPMOST` 位在、带不在）----
# ★ 症状：**开机自启**后给「打开xxx」，桌宠被随后打开的普通窗口（Edge）盖住；
#   同进程的气泡 / 状态提示却正常。手动启动**从不**复现。
# ★ 根因（登录期记录器 + `GetWindow(GW_HWNDPREV)` 权威 z 链取证）：
#   桌宠窗口的 `WS_EX_TOPMOST` 位**全程为真、一次没掉**，但沿 z 链往上走，
#   第一个可见的外来窗口竟是**非置顶**的 Edge —— 一个 topmost 窗口不该被非置顶窗口压住。
#   ⇒ Qt 在**登录早期**只把「位」挂上了，**没把窗口放进「置顶带」**，它实际是个普通窗口，
#     任何被激活的窗口都会排到它前面。
#   ⚠️ 关键教训：`GWL_EXSTYLE & WS_EX_TOPMOST` **查不出这个 bug**（它报 True）。
#   ★ 修法（同机实测：调用后上方可见窗立刻清空、3s 后仍保持）：
#     `SetWindowPos(hwnd, HWND_TOPMOST, …)` 显式重新入带。
#   ⚠️⚠️ **拼写就是坑**：`ctypes` 里那个加载器叫 **`windll`（全小写）**，
#     **不存在 `Windll`（大写 W）**。2026-09-21 一度按 `ctypes.Windll` 写 ⇒
#     `_HAS_WIN32` **恒为 False**（真机也 False）⇒ 整套看门狗**一个字节都没执行**，
#     而离屏/真机「都 False」把这件事完全掩盖了（当时误以为只是离屏没有）。
#     教训：平台开关不能靠"记忆里的名字"，要 `hasattr` 之后**在真机上打一行日志验证**。
#   ⚠️ 非 Windows（`sys.platform`）或真没有 `windll` ⇒ `_HAS_WIN32` 为假，整套空转。
PETS_TOP_BAND_MS = 1500      # 看门狗周期（ms）：登录时序是随机漏的，一次重设不够，得盯着
PETS_TOP_BAND_PS_MS = 400    # 节能态那只手亮着时的周期：手压在贴图上，掉带窗口一冒头就得抢回
_HAS_WIN32 = sys.platform == "win32" and hasattr(ctypes, "windll")

if _HAS_WIN32:
    _u32 = ctypes.windll.user32
    _k32 = ctypes.windll.kernel32
    # ⚠️⚠️ `argtypes` 仍要显式声明，但要**准确**理解它防的是什么（2026-09-21 实测对照）：
    #   64 位下 `HWND` 是 8 字节指针。**不声明 argtypes 且传裸整数 `-1`** 时，ctypes 按
    #   C `int` 传 ⇒ 实际是 `0x00000000FFFFFFFF`（**非法句柄**）⇒ `SetWindowPos`
    #   **静默返回 False、窗口一动不动** —— 实测 `-> False, exstyle=0x0`，极易误判成「这招没用」。
    #   ★但若参数已用 `wintypes.HWND(-1)` **包了一层**，ctypes 会按该类型传 ⇒ 实测
    #   `-> True, exstyle=0x8`（**不声明也对**）。本模块两处都包了，所以线上并不因此出错。
    #   声明 `argtypes` 的价值在**防以后有人改成裸整数**，以及让意图显式可读。
    _u32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    _u32.SetWindowPos.restype = wintypes.BOOL
    _u32.GetWindow.restype = ctypes.c_void_p
    _u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]

GWL_EXSTYLE = -20
GWL_HWNDPARENT = -8
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
GW_HWNDPREV = 3                  # 沿 z 链**往上**（前一个窗口）
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


def _hwnd_of(widget):
    """QWidget → 原生 HWND（整数值）；取不到返回 0。"""
    try:
        return int(widget.winId())
    except Exception:                        # noqa: BLE001 —— 窗口还没创建 / 平台不支持
        return 0


def _is_visible_window(hwnd) -> bool:
    try:
        return bool(_u32.IsWindowVisible(int(hwnd)))
    except Exception:                        # noqa: BLE001
        return False


def _first_window_above(hwnd):
    """沿**真实 z 链**往上找，返回第一个**可见的**外来窗口句柄；到顶返回 `None`。

    ⚠️ 只认 `GW_HWNDPREV`：`EnumWindows` 的顺序把隐藏窗口也排进去，在「带」的边界上不可靠。
    ⚠️ 必须跳过隐藏窗：隐藏窗（`Default IME` / `_q_titlebar` / 各种 message window）的
       z 位置是**残留**的，不代表视觉层级。
    """
    w = int(hwnd)
    for _ in range(12):
        try:
            w = int(_u32.GetWindow(wintypes.HWND(w), GW_HWNDPREV) or 0)
        except Exception:                    # noqa: BLE001
            return None
        if not w:
            return None
        if _is_visible_window(w):
            return w
    return None


def _win_set_topmost(hwnd) -> bool:
    """把 `hwnd` 推入置顶带（`SetWindowPos(HWND_TOPMOST, …)`）。

    ⚠️ 这里**每次现取 `_u32`**（`_u32.SetWindowPos(...)`）而**不是**把 `SetWindowPos`
    绑成模块级引用：绑了之后替身 / 重新初始化 `_u32` 都不会被看见，
    测试里注入假的 user32 会静默失效（2026-09-21 实测踩过：断言拿到「0 次调用」的假绿）。
    """
    try:
        return bool(_u32.SetWindowPos(
            wintypes.HWND(int(hwnd)), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        ))
    except Exception:                        # noqa: BLE001 —— 抢不回来也不该把桌宠搞崩
        return False


def _band_verdict(first_above) -> bool:
    """置顶带判据的**纯函数**部分（好单测）：

    `first_above` 是「往上第一个**可见**窗口」的三元组/四元组
    `(hwnd, exstyle, is_self_…, …)` —— 这里只吃前两项，None 表示「到顶了」。

    返回「桌宠是否掉带」：
      - 到顶 / 没有可见的上方窗 → **没掉**（比所有窗口都高）；
      - 上方窗带 `WS_EX_TOOLWINDOW` → **没掉**（那是我们自己的手 / 气泡 / 提示，设计就该在上面）；
      - 上方窗**不是**置顶的 → **掉了**；
      - 上方窗是置顶的（任务栏 / 输入法候选 / SAO Utils…）→ **没掉**。
    """
    if not first_above:
        return False
    try:
        ex = int(first_above[1])
    except (TypeError, ValueError, IndexError):
        return False
    if ex & WS_EX_TOOLWINDOW:
        return False
    return not bool(ex & WS_EX_TOPMOST)


def topmost_out_of_band(hwnd) -> bool:
    """桌宠是否**掉出了置顶带** —— 本模块唯一需要的置顶判据。

    ⚠️ 别改成「查 `WS_EX_TOPMOST` 位」：那位**全程为真**，查它永远查不出这个 bug
    （2026-09-21 实测，见本模块顶部注释）。
    """
    b = _first_window_above(hwnd)
    if not b:
        return False                         # 到顶了（比所有窗口都高）→ 必然在带上
    try:
        ex = int(_u32.GetWindowLongW(b, GWL_EXSTYLE))
    except Exception:                        # noqa: BLE001
        return False
    return _band_verdict((b, ex))


def bubble_text_width() -> int:
    """气泡里文字的可用宽度（本体宽减去左右两边的边框 + 内边距）。"""
    return BUBBLE_W - 2 * (BUBBLE_BORDER + BUBBLE_PAD)


def bubble_body_h(text_h) -> int:
    """气泡本体高度 = 文字块高 + 上下各一份（边框 + 内边距）。"""
    return int(text_h) + 2 * (BUBBLE_BORDER + BUBBLE_PAD)


def bubble_sx(side) -> int:
    """本体相对锚点的横向方向：气泡在贴图左侧 → −1（本体向左展开），右侧 → +1。"""
    return -1 if side == SIDE_LEFT else 1


def bubble_anchor(x, y, w, h, *, side=SIDE_LEFT, face=FACE_DOWN):
    """贴图屏幕矩形 -> 锚点 A（尾巴的直角顶点 = 两条直角边 a / b 的交点）。

    A.x = 气泡那一侧的贴图边缘**往外 5px**；A.y 一律**自贴图底边往上量**：
    面朝下 5/7（150×250 贴图 → 距贴图顶 71px，下巴 / 胸口一带），面朝上 2/7（= 5/7 的镜像，
    落到 179px，膝盖一带）。
    """
    ax = x - BUBBLE_GAP_X if side == SIDE_LEFT else x + w + BUBBLE_GAP_X
    ratio = BUBBLE_ANCHOR_RATIO if face == FACE_DOWN else BUBBLE_FLIP_RATIO
    return (ax, y + h - round(h * ratio))


def bubble_body_rect(anchor, body_w, body_h, *, side=SIDE_LEFT, face=FACE_DOWN):
    """本体矩形 `(x, y, w, h)`（与锚点同一坐标系）。

    横向：与尾巴 **b** 边共线的那条竖边框**就在 A.x**；纵向：面朝下时**下**边框 = A.y − 19
    （= 直角边 15 + 间隔 4），面朝上时**上**边框 = A.y + 5（间隔 5）。
    """
    sx = bubble_sx(side)
    x = anchor[0] - body_w if sx < 0 else anchor[0]
    if face == FACE_DOWN:
        y = anchor[1] - (BUBBLE_TAIL_LEG + BUBBLE_TAIL_GAP) - body_h
    else:
        y = anchor[1] + BUBBLE_TAIL_GAP_UP
    return (x, y, body_w, body_h)


def bubble_page_dwell_ms(text) -> int:
    """单段正文该在桌上停留多久（ms）。

    与说话态**同一条标定**（`pipeline.silent_hold_seconds` = `max(1.2s, 0.22s/字)`，见 docs/02 §9.8）：
    静音模式下这一轮说话态的时长本来就是按文本长度这么算的，两边同源 —— 分段节奏自然贴合这一轮的长度，
    不会出现「话都说完了、字还没翻完」。
    """
    n = len(str(text or "").strip())
    return max(BUBBLE_PAGE_MIN_MS, int(round(BUBBLE_PAGE_PER_CHAR_MS * n)))


# 段边界往回让时认的句读（中英文 + 收尾括号）：让切点落在**标点之后**，下一段就不会以标点开头
_PAGE_BREAK_CHARS = "，。！？；：、,.;:!?）】》」』”’)]}"


def _page_break_at(text, start, best, fits=None):
    """段切点：尽量别让下一段以标点开头，其次让本段尽量以句读收尾。

    1. **切点右边紧跟标点**（下一段会以「，。」开头那种）→ 把它一并带进本段。
       带进来会让本段高一点点，所以只在 `fits(带进来那一段)` 为真时才带 ——
       「每段都量得下」这条不变量**不许**为观感破例。
    2. 否则往回让到最近一个句读之后（最多让 `BUBBLE_PAGE_BREAK_BACK` 字）。
    3. 都不成立就原样返回 `best`（硬切）。
    """
    back = BUBBLE_PAGE_BREAK_BACK
    if best < len(text) and text[best] in _PAGE_BREAK_CHARS:
        if fits is None or fits(text[start:best + 1]):
            return best + 1
        # 带不走（本段已量满）→ 只能往回找更早的句读，否则下一段就会以这个标点开头。
        # 这时允许让得更多：宁可本段吃点亏，也别让下一段从「，」开始。
        back = BUBBLE_PAGE_BREAK_BACK_LONG
    floor = max(start + 1, best - back)
    for i in range(best - 1, floor - 1, -1):
        if text[i] in _PAGE_BREAK_CHARS:
            return i + 1
    return best


def bubble_pages(text, *, max_h=BUBBLE_MAX_TEXT_H, text_w=None) -> list:
    """把一轮回复的**中文全文**切成一页页：每页正文块高都 ≤ `max_h`、拼起来 = 原文。

    2026-09-17 四改：气泡本体高原本随文字量**无上限**增长（一条长回复能长出比桌宠还高的气泡、
    顶出屏幕），现在改成**分段显示**（不是截断、也不是滚动）。

    - 量高用的是气泡**同一套** `QTextDocument`（同字号、同宽度），**不按字数估** ——
      中英混排 / 长英文单词的实际行数只能量出来；
    - 逐页「指数探测上界 + 二分」找最多能放多少字：量高只量短的子串，正常页很快就定位到；
    - 段边界往回让到最近句读（见 `_page_break_at`）；
    - **不丢字**：各段都是原文的切片，`"".join(pages) == text`（连空格都在原地）。
    """
    text = str(text or "")
    if not text.strip():
        return []
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(BUBBLE_FONT_PX)
    doc.setDefaultFont(font)
    doc.setTextWidth(bubble_text_width() if text_w is None else text_w)

    def h_of(chunk) -> int:
        doc.setPlainText(chunk)
        return int(math.ceil(doc.documentLayout().documentSize().height()))

    pages = []
    n = len(text)
    i = 0
    while i < n:
        # 不跳空白、也不 rstrip：每一段都是原文的**切片** —— 拼起来必须一字不差
        # （跳空白会把「正好落在段边界上的那个空格」吃掉，英文单词就被粘成一个了）
        step, hi = 8, min(n, i + 8)              # 指数探测：先找一个「一定放不下」的上界
        while hi < n and h_of(text[i:hi]) <= max_h:
            step *= 2
            hi = min(n, i + step)
        lo, best = i + 1, i + 1                  # 兜底：连一个字都放不下也保证有进展
        while lo <= hi:
            mid = (lo + hi) // 2
            if h_of(text[i:mid]) <= max_h:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        cut = (_page_break_at(text, i, best, lambda chunk: h_of(chunk) <= max_h)
               if best < n else best)
        # 尾巴只剩几个字时，把「本段 + 尾巴」对半分 —— 免得最后切出一个「方。」那样的碎段。
        # 两半都量一遍再决定：只有**两半都放得下**才真的对半（不拿不变量冒险）。
        if cut < n and (n - cut) < BUBBLE_PAGE_MIN_TAIL:
            half = i + (n - i) // 2
            if half < cut and h_of(text[i:half]) <= max_h and h_of(text[half:]) <= max_h:
                cut = half
        pages.append(text[i:cut])
        i = cut
    return pages


def _toast_font() -> QFont:
    """状态提示气泡的字体（13px，与正文、聊天气泡同一号）。"""
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(BUBBLE_FONT_PX)
    return font


def toast_text_w(text, font=None) -> int:
    """单行文字的自然宽。

    **单行、不折行** —— 所以这里用 `QFontMetrics.horizontalAdvance`，不是 §14.4 那套 `QTextDocument`
    （那是为「折行 + 精确量高」准备的）。
    """
    return QFontMetrics(font or _toast_font()).horizontalAdvance(str(text or ""))


def toast_body_w(text, font=None) -> int:
    """本体宽 = 文字自然宽 + 左右各一份（边框 + 内边距）——「略宽于文本」就是这么来的。"""
    return toast_text_w(text, font) + 2 * (TOAST_BORDER + TOAST_PAD_X)


def toast_rect(sprite, body_w, *, gap=TOAST_GAP, body_h=TOAST_H, below=False):
    """提示气泡在**屏幕坐标**里的矩形（返回 `(x, y, w, h)` = 窗口左上角 + 本体尺寸）。

    - 横向**以贴图中心线居中**；
    - 纵向默认**贴在贴图上方**：气泡**下沿**距贴图**顶边** `gap`；
    - `below=True` 时翻到**贴图下方**：气泡**上沿**距贴图**底边** `gap`（上下互为镜像，
      见 `toast_above()` —— 上方放不下才走这一支）。
    """
    body_w, body_h = int(body_w), int(body_h)
    x = sprite.x() + (sprite.width() - body_w) // 2
    y = (sprite.y() + sprite.height() + gap) if below else (sprite.y() - gap - body_h)
    return (x, y, body_w, body_h)


def toast_above(sprite, avail, body_h=TOAST_H, cur=True):
    """提示气泡该挂在贴图的**上方**还是**下方**：**上方放得下就挂上方**，否则让到下方。

    需要的高度 = 本体高 + 贴图间隔 5 + 弹出时窗口多留的那 5px（`TOAST_POP_DY`）。
    迟滞 `TOAST_FLIP_HYST`：已经在下方时，上方要重新多出 20px 才回去 —— 贴着屏幕上沿来回拖不会来回跳。
    下方也放不下（屏幕太矮）时**仍按上方**：往下面让同样是出屏，与聊天气泡
    「让位只在『这一侧真的装得下』时发生」同一条口径。
    """
    need = int(body_h) + TOAST_GAP + TOAST_POP_DY + (0 if cur else TOAST_FLIP_HYST)
    if sprite.y() - avail.y() >= need:
        return True
    room = avail.y() + avail.height() - (sprite.y() + sprite.height())
    if room >= TOAST_GAP + int(body_h) + TOAST_POP_DY:
        return False
    return True


def bubble_tail(anchor, *, side=SIDE_LEFT, face=FACE_DOWN):
    """尾巴三个顶点，顺序恒为 `(锚点 A, a 的远端, b 的上端)`。

    - **b**（竖直边）与气泡的左 / 右边框**共线**（x 恒 = A.x）；
    - **a**（水平边）∥ 气泡**朝向贴图那一侧**的横边框，而且**紧贴**它 ——
      面朝下时 a 就在下边框**下方 4px**，面朝上时 a 就在上边框**上方 5px**；
    - **直角顶点 = a 与 b 的交点**。

    两种朝向互为**上下镜像**（2026-09-17 三改）：面朝下时直角顶点在 A 正上方 15px、A 自己是「尾巴尖」；
    面朝上时直角顶点就是 A、尾巴尖在 A 正上方 15px。尾巴尖**一律朝着贴图那一侧**，
    看起来都是从气泡那条横边框上「长」出来、朝着角色收成一个尖。
    """
    sx = bubble_sx(side)
    if face == FACE_DOWN:
        return ((anchor[0], anchor[1]),
                (anchor[0] + BUBBLE_TAIL_LEG * sx, anchor[1] - BUBBLE_TAIL_LEG),
                (anchor[0], anchor[1] - BUBBLE_TAIL_LEG))
    return ((anchor[0], anchor[1]),
            (anchor[0] + BUBBLE_TAIL_LEG * sx, anchor[1]),
            (anchor[0], anchor[1] - BUBBLE_TAIL_LEG))


def _unit(v):
    """把 QPointF 归一化（零向量原样返回；调用方保证不会是零向量）。"""
    d = math.hypot(v.x(), v.y())
    return QPointF(v.x() / d, v.y() / d) if d else QPointF(0.0, 0.0)


def bubble_tail_path(points, radius=None):
    """三角形 -> **圆角**路径（每个顶角按 `radius` 的圆弧切掉），给描边 + 填充用。

    三个角一律用「切点 + 三次贝塞尔」近似那段圆弧（`k = 4/3·tan(α/4)`）—— **不走 `arcTo`**：
    它的角度约定是另一套，一不小心就把圆弧画到补角那边去了。
    """
    r = BUBBLE_RADIUS if radius is None else radius
    pts = [QPointF(float(x), float(y)) for (x, y) in points]
    n = len(pts)
    path = QPainterPath()
    for i in range(n):
        c, p, q = pts[i], pts[i - 1], pts[(i + 1) % n]
        u1, u2 = _unit(p - c), _unit(q - c)
        cos_t = max(-1.0, min(1.0, u1.x() * u2.x() + u1.y() * u2.y()))
        theta = math.acos(cos_t)                 # 内角
        cut = r / math.tan(theta / 2)            # 切点到顶点的距离
        t1, t2 = c + u1 * cut, c + u2 * cut
        center = c + _unit(u1 + u2) * (r / math.sin(theta / 2))
        a1 = math.atan2(t1.y() - center.y(), t1.x() - center.x())
        a2 = math.atan2(t2.y() - center.y(), t2.x() - center.x())
        sweep = a2 - a1                          # 取劣弧：凸角上就是被切掉的那段
        while sweep <= -math.pi:
            sweep += 2 * math.pi
        while sweep > math.pi:
            sweep -= 2 * math.pi
        k = 4.0 / 3.0 * math.tan(sweep / 4.0)
        c1 = t1 + QPointF(-math.sin(a1), math.cos(a1)) * (k * r)
        c2 = t2 - QPointF(-math.sin(a2), math.cos(a2)) * (k * r)
        if i == 0:
            path.moveTo(t1)
        else:
            path.lineTo(t1)
        path.cubicTo(c1, c2, t2)
    path.closeSubpath()
    return path


def bubble_content_box(body_w, body_h, *, side=SIDE_LEFT, face=FACE_DOWN):
    """未旋转时内容的包围盒 `(x0, y0, x1, y1)`（以锚点为原点，位于左上 / 右上象限）。"""
    bx, by, bw, bh = bubble_body_rect((0.0, 0.0), body_w, body_h, side=side, face=face)
    tail = bubble_tail((0.0, 0.0), side=side, face=face)
    xs = [bx, bx + bw] + [p[0] for p in tail]
    ys = [by, by + bh] + [p[1] for p in tail]
    return (min(xs), min(ys), max(xs), max(ys))


def bubble_pop_state(p):
    """弹出动画在进度 p 的（旋转角, 缩放, 不透明度）。p 已含缓动（由动画给出）。"""
    p = max(0.0, min(1.0, float(p)))
    return (-BUBBLE_POP_ANGLE * (1.0 - p),
            BUBBLE_POP_SCALE + (1.0 - BUBBLE_POP_SCALE) * p,
            p)


def bubble_pop_bbox(body_w, body_h, *, side=SIDE_LEFT, face=FACE_DOWN,
                    steps=_BUBBLE_BBOX_STEPS):
    """弹出动画**全程**的并集包围盒（相对锚点，锚点在原点）。

    必须按全程采样，不能按终态开窗口：气泡从「逆时针 15 度、缩到 0.30」转回 0 度的途中，
    横向 / 纵向占位都比终态大（旋转会把包围盒角顶出去），按终态开控件就会把自己裁掉。
    """
    x0, y0, x1, y1 = bubble_content_box(body_w, body_h, side=side, face=face)
    corners = ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
    curve = QEasingCurve(QEasingCurve.OutCubic)
    xs, ys = [], []
    for i in range(steps + 1):
        angle, scale, _ = bubble_pop_state(curve.valueForProgress(i / steps))
        rad = math.radians(angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        for (x, y) in corners:
            sx, sy = x * scale, y * scale           # 先缩放
            xs.append(sx * cos_a - sy * sin_a)     # 再旋转（与 QTransform.rotate 同向）
            ys.append(sx * sin_a + sy * cos_a)
    left, top = int(math.floor(min(xs))) - 1, int(math.floor(min(ys))) - 1
    return QRect(left, top,
                 int(math.ceil(max(xs))) - left + 1,
                 int(math.ceil(max(ys))) - top + 1)


def bubble_side(sprite, avail, cur=SIDE_LEFT):
    """气泡该待在贴图的哪一侧：**左侧放得下就用左侧**，否则让到右侧。

    迟滞 `BUBBLE_FLIP_HYST`：已经在右侧时，左侧要重新多出 20px 才回去 —— 贴边来回拖不会来回翻。

    两侧都放不下（屏幕太窄 / 贴图已经贴在右边）时**保持左侧**：往右让只是把气泡
    推出屏幕，不如不动（与文档同一条口径：让位只在「这一侧真的装得下」时发生）。
    """
    need = BUBBLE_W + (BUBBLE_FLIP_HYST if cur == SIDE_RIGHT else 0)
    if (sprite.x() - avail.x()) >= need:
        return SIDE_LEFT
    room = avail.x() + avail.width() - (sprite.x() + sprite.width())
    return SIDE_RIGHT if room >= BUBBLE_GAP_X + BUBBLE_W else SIDE_LEFT


def bubble_face(sprite, avail, body_h, cur=FACE_DOWN):
    """尾巴朝哪边：**锚点上方放得下气泡就朝下**，否则朝上（气泡挂到 2/7 高度）。

    需要的高度 = 19（尾巴 15 + 间隔 4）+ 本体高；迟滞同 `bubble_side`。
    """
    need = BUBBLE_TAIL_LEG + BUBBLE_TAIL_GAP + int(body_h)
    if cur == FACE_UP:
        need += BUBBLE_FLIP_HYST
    above = (sprite.y() + sprite.height()
             - round(sprite.height() * BUBBLE_ANCHOR_RATIO)) - avail.y()
    return FACE_DOWN if above >= need else FACE_UP

# ---- 音量条（2026-09-19 起住在右键菜单最顶端）----
VOL_BAR_H = 22          # 音量条**图标框**高度（喇叭 20px + 上下各 1px 余量）
VOL_BAR_ICON_X = 3      # 喇叭图标距行左边（px）
VOL_BAR_SLIDER_X = 26   # 滑块起点 = 图标 3 + 20 + 间距 3（**与搬到菜单之前逐字一致**）
VOL_BAR_RIGHT_PAD = 8   # 滑块右端距行右边（px）
VOL_MENU_PAD = 4        # 右键菜单内边距（菜单宽 = 音量条宽 + 2×(4 内边距 + 1 边框)）
MENU_BORDER = "#000000"     # 右键菜单边框色（用户口径：黑色 1px）
MENU_BORDER_W = 1           # 菜单边框厚度（px）—— 算菜单宽度要用，别写成魔数
MENU_RADIUS = 3             # 右键菜单圆角（用户口径：3px）
MENU_ITEM_PAD_X = 14        # 菜单项左右内边距（八改前是 QSS 的 `padding:8px 14px`）
MENU_ITEM_PAD_Y = 8         # 菜单项上下内边距
MENU_ITEM_TEXT_X = 35       # 菜单项文字左边距（从面板左沿算；实测值，含原 QMenu 给勾选列留的宽度）
MENU_CHECK_X = 9            # 勾选标记左边距（从面板左沿算，实测）
MENU_ITEM_H = 28            # 音量条那一行的高度（与「切换」行等高由冒烟测试盯着）
MENU_BG = "#FFFFFF"         # 面板底色（与原 QSS 一致）
MENU_INK = "#334155"        # 正文色
MENU_SEL_BG = "#E6F1FB"     # 悬停行底色
MENU_SEL_INK = "#0C447C"    # 悬停行文字色
MENU_SEP = "#CBD5E1"        # 分隔线颜色
MENU_SEP_X = 6              # 分隔线左右内缩（原 QSS `margin:4px 6px`）
MENU_SEP_Y = 4              # 分隔线上下留白
MENU_NARROW = 5             # 2026-09-19 二改：音量条比**基准**贴图宽窄 5px，菜单随之窄 5px
# 2026-09-19 十六改：**菜单宽度与当前角色的贴图解耦**，一律按爱丽丝那一档来。
# 起因（用户报）：菜单宽原本 = `_base_w - MENU_NARROW`，而 `_base_w` 是按**贴图宽高比**算出来的显示宽
# （`_normal_size()`：高度统一钉 `DISPLAY_HEIGHT`=250，宽度按原图比例）——
#   爱丽丝 300×500 → 150 → 菜单 155；**艾莲 256×256 → 250 → 菜单 255**。
# 于是「切换到艾莲时菜单宽度变了」。用户口径：「将菜单尺寸统一成当前右键爱丽丝贴图弹出的菜单」
# ⇒ 钉一个基准宽，别再跟 `_base_w` 走（`_build_menu()` 里不许再出现 `_base_w`，冒烟测试有 AST 反向断言）。
MENU_REF_W = 150            # 基准贴图宽 = 爱丽丝的在屏显示宽（300×500 @ DISPLAY_HEIGHT=250）
MENU_CONTENT_W = MENU_REF_W - MENU_NARROW   # 145 = 音量条宽；菜单宽 = 145 + 2×(内边距 4 + 边框 1) = **155**（全角色一致）
MENU_GAP = 8                # 菜单靠近贴图的那条边、压住贴图 8px（三改：贴左也是压住，两侧对称）
MENU_FADE_MS = 300          # 右键弹窗**淡出**时长（0.3s，2026-09-19 十二改；一级与二级共用这一个常量）
# 2026-09-19 八改：容器从 `QMenu` 换成自绘弹窗 `_MenuPopup`（`QMenu` 缩放不了，只能整窗改不透明度）。
# 2026-09-19 十改：窗口**不再留 20px 动画余量**（窗口尺寸 == 面板尺寸）。
# 2026-09-19 十一改：撤销十改的「两段式」—— 底板与内容在同一段动画里。
# 2026-09-19 十二改：① 时长 0.5s → **0.3s**；② 淡入起点底色固定成深色（`MENU_POP_BASE`）。
# 2026-09-19 十三改：窗口 region 两个轴都跟着面板缩（修「底层的边框 / 右侧灰块」）；二级宽限改 0s。
# 2026-09-19 十四改：**彻底去掉缩放** —— 一级与二级一样**只做不透明度**（用户口径：
#   「不再进行大小上的变化，只要求右键淡入（仅不透明度提高）」）。
#   ⇒ `MENU_POP_SCALE` / `MENU_POP_BASE` / `_pop_base_color()` / `_apply_anim()` / `_progress` /
#     `_scaling` / `pop_up(scale_in=…)` **全部删除**（`smoke_pet` 有 reverse 断言钉着，别再找回来）。
#   淡入的底改成与淡出同一条路：铺**抓来的真桌面** ⇒ 合成 = `α×菜单 + (1−α)×真桌面`
#   —— 这才是字面意义的「仅不透明度提高」，也顺带把「底层」彻底去掉（十三改后它只剩面板形状，
#   十四改后它干脆就是桌面本身）。抓不到桌面（离屏 / 无权限）时兜底铺 `MENU_BG`。
MENU_POP_MS = 300           # 一级弹窗**淡入**时长（十二改 0.3s；十四改起只做不透明度、不缩放）
MENU_MASK_PAD = 0           # 十改：窗口 region 就按面板形状裁（整窗已是菜单底色，不必再外扩）
MENU_ARROW_DX = 7           # 「切换」右侧小尖的横向跨度
MENU_ARROW_DY = 5           # 「切换」右侧小尖的纵向半高
SUBMENU_FADE_MS = 300       # 二级弹窗**淡入**时长（十二改 0.3s；与一级一样只做不透明度）
SUBMENU_GRACE_MS = 0        # 十三改：鼠标一离开「切换」行 / 二级弹窗就**立刻**淡出（原 0.5s、再原 1.0s）

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICONS = ASSETS / "icon"     # 图标贴图（喇叭 / 思考三帧）—— 与 gui 同一套 assets 目录
# 喇叭图标（有音 / 静音）
_SPEAKER_AUDIO = (ICONS / "speaker_audio.png").as_posix()
_SPEAKER_MUTE = (ICONS / "speaker_mute.png").as_posix()


class _VolumeIcon(QWidget):
    """音量条左端的喇叭图标：**贴 assets/icon/speaker_<state>.png**，点击切换静音。

    图标边长 20px（= 图标框内高，见 `VOL_BAR_H`）—— 所在那一行是菜单项高 `MENU_ITEM_H`，垂直居中，
    音量条本身的样式（容器底色 / 边框 / 轨道 / 圆钮）一律不变。
    贴图缺失时回退为原手绘喇叭（锥体 + 声波 / 静音斜线），保证按钮始终可见可点。
    """

    ICON = 20   # 图标边长（px）；在菜单项高（MENU_ITEM_H）的行里垂直居中

    def __init__(self, parent=None):
        super().__init__(parent)
        self._muted = False
        self._on_click = lambda: None
        self._pix = {
            False: QPixmap(_SPEAKER_AUDIO),
            True: QPixmap(_SPEAKER_MUTE),
        }
        self.setFixedSize(self.ICON, self.ICON)
        self.setCursor(Qt.PointingHandCursor)

    def set_on_click(self, cb):
        self._on_click = cb or (lambda: None)

    def set_muted(self, muted: bool):
        if bool(muted) != self._muted:
            self._muted = bool(muted)
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on_click()
            e.accept()

    def paintEvent(self, e):
        pm = self._pix[self._muted]
        p = QPainter(self)
        if pm is None or pm.isNull():
            self._paint_fallback(p)
            return
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        side = self.ICON
        p.drawPixmap(
            (self.width() - side) // 2,
            (self.height() - side) // 2,
            pm.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation),
        )

    def _paint_fallback(self, p):
        """贴图缺失时的兜底：手绘喇叭（按 18px 原稿等比放大到图标框）。"""
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.ICON / 18.0, self.ICON / 18.0)
        color = QColor("#DCDCDC") if self._muted else QColor("#378ADD")
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        body = QPolygonF([
            QPointF(2, 8), QPointF(6, 8), QPointF(10, 4), QPointF(10, 14),
            QPointF(6, 10), QPointF(2, 10),
        ])
        p.drawPolygon(body)
        pen = QPen(color, 1.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if self._muted:
            p.drawLine(QPointF(12, 4), QPointF(17, 14))
        else:
            p.drawArc(QRectF(12, 6, 4, 6), -80 * 16, 160 * 16)
            p.drawArc(QRectF(15, 4, 3, 10), -80 * 16, 160 * 16)


class _VolumeBar(QWidget):
    """**右键菜单里**那条音量条：左端喇叭图标 + 滑块，**没有容器盒子**（直接摆在菜单底色上）。

    2026-09-19：它原来挂在小人下方（单击贴图弹出来），这一轮搬到右键菜单最顶端。
    2026-09-19 二改（用户口径）：
      * **不要边框** —— 旧的「白底 `#FFFFFF` + `1px solid #7DD3FC` + 圆角 8px」的壳整个去掉；
      * **行高 = 菜单项高度 `MENU_ITEM_H`（28px）**，与「切换」那一行等高（原来写死 22px）；
      * **宽度 = `MENU_CONTENT_W`（145px）** → 靠它适配的菜单也跟着定成 155px。
    2026-09-19 十六改：宽度**不再跟贴图走**（原来是 `_base_w − MENU_NARROW`，切到方形贴图的角色会撑到
    245/255）—— 现在由 `MENU_CONTENT_W` 钉死，**与当前角色无关**（见那个常量的注释）。

    ⚠️ **每次开菜单现造一条**：`QWidgetAction` 会接管控件所有权（菜单销毁 → 控件跟着销毁），
    所以这里不缓存任何状态，值由 `PetWindow._volume` 传入、改动原样回调出去。
    （通用设置那一行用的是同一颗 `volume.VolumeSlider`，那边同样不加边框。）
    """

    def __init__(self, width, value, on_change, on_mute, muted=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(int(width), MENU_ITEM_H)
        self._on_change = on_change or (lambda v: None)
        self._on_mute = on_mute or (lambda m: None)
        self._muted = bool(muted)

        # 喇叭图标在左（点击切换静音）、滑块在右；几何与旧版逐字一致。
        self.icon = _VolumeIcon(self)
        self.icon.set_on_click(self._toggle_mute)
        self.icon.set_muted(self._muted)
        side = self.icon.ICON
        self.icon.setGeometry(VOL_BAR_ICON_X, (MENU_ITEM_H - side) // 2, side, side)

        self.slider = VolumeSlider(self)
        self.slider.setGeometry(VOL_BAR_SLIDER_X, 0,
                                max(0, int(width) - VOL_BAR_SLIDER_X - VOL_BAR_RIGHT_PAD),
                                MENU_ITEM_H)
        self.slider.setValue(self._pct(value))
        self.slider.set_muted(self._muted)
        self.slider.valueChanged.connect(self._on_value)

    @staticmethod
    def _pct(value) -> int:
        return int(round(max(0.0, min(1.0, float(value))) * 100))

    # ---- 对外（只给 `PetWindow` 用）----
    def set_muted(self, muted: bool, notify: bool = True) -> None:
        muted = bool(muted)
        if muted == self._muted:
            return
        self._muted = muted
        self.icon.set_muted(muted)
        self.slider.set_muted(muted)
        if notify:
            self._on_mute(muted)

    def sync(self, value, muted=None) -> None:
        """外部（通用设置那一行 / 语音）改了音量 → 把这条拨过去，**不回调**（防回环）。"""
        self.slider.blockSignals(True)
        self.slider.setValue(self._pct(value))
        self.slider.blockSignals(False)
        if muted is not None:
            self.set_muted(bool(muted), notify=False)

    # ---- 内部 ----
    def _toggle_mute(self):
        self.set_muted(not self._muted)

    def _on_value(self, val):
        if self._muted:
            self.set_muted(False)      # 拖动滑块自动解除静音
        self._on_change(val / 100.0)


class _PetBubble(QWidget):
    """桌宠旁边的聊天气泡：**独立顶层窗**，自绘卡片 + 尾巴，绕尾巴尖弹出 / 淡出，贴边时让位。

    只在「静音模式开 + 主界面关」时由 `main.show_pet_bubble()` 叫出来（本文件不判条件）。
    `PetWindow` 在 move / resize 时用 `follow()` 把它摆到贴图旁边，并按**可用屏幕空间**决定朝向
    （左右 / 上下翻转，见 `bubble_side()` / `bubble_face()`）。

    为什么不做成桌宠窗的子控件：桌宠窗的「窗口尺寸 == 贴图尺寸」是承重不变量（`_normal_size` /
    `_apply_window_size` / 节能变形逐帧 `move(x, 底边-h)` 全按它算），气泡要挂在贴图**外面**，
    加宽窗口就得给贴图补横向偏移、那一串几何算法全得跟着改。详见 design.md 4.16 与 docs/02 14.1。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # WindowTransparentForInput：控件尺寸是「动画全程的并集包围盒」，比看到的气泡大一圈，
        # 那圈透明区域**不能吃掉桌面上的点击**。WA_ShowWithoutActivating：不许抢焦点。
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._font = QFont("Microsoft YaHei UI")
        self._font.setPixelSize(BUBBLE_FONT_PX)
        # 量高与绘制用**同一个** QTextDocument：量到的就是画出来的（见 docs/02 14.4）
        self._doc = QTextDocument()
        self._doc.setDocumentMargin(0)
        self._doc.setDefaultFont(self._font)
        self._text_w = bubble_text_width()
        self._body_w = BUBBLE_W
        self._body_h = bubble_body_h(15)
        self._side, self._face = SIDE_LEFT, FACE_DOWN
        self._bbox = bubble_pop_bbox(self._body_w, self._body_h)
        self._anchor = QPointF(-self._bbox.left(), -self._bbox.top())
        self._angle, self._scale, self._opacity = 0.0, 1.0, 0.0
        self._pop_anim = None
        self._fade_anim = None
        self._flip_anim = None
        # 分段显示（四改）：这一轮的全文 / 切好的段 / 当前第几段；`_text_op` 是**文字自己**的
        # 不透明度（整条气泡那个是 `_opacity`）—— 段间淡字**只动它**。
        self._full_text = ""
        self._pages = []
        self._page_i = 0
        self._text_op = 1.0
        self._page_timer = None
        self._page_anim = None
        self._flip_delta = QPointF(0.0, 0.0)
        self._sprite = None
        self._avail = QRect()
        self.setFixedSize(self._bbox.width(), self._bbox.height())
        self._build_shapes()

    # ---- 形状 / 几何（一律以锚点为原点）----
    def _build_shapes(self):
        tail_pts = bubble_tail((0.0, 0.0), side=self._side, face=self._face)
        self._tail = QPolygonF([QPointF(x, y) for (x, y) in tail_pts])
        self._tail_path = bubble_tail_path(tail_pts)
        bx, by, bw, bh = bubble_body_rect((0.0, 0.0), self._body_w, self._body_h,
                                          side=self._side, face=self._face)
        self._body_rect = QRectF(bx, by, bw, bh)
        inner = BUBBLE_BORDER + BUBBLE_PAD
        self._text_rect = QRectF(self._body_rect.x() + inner, self._body_rect.y() + inner,
                                 self._text_w, self._body_h - 2 * inner)

    def _apply_orientation(self, side, face):
        """换朝向：重算包围盒 / 控件尺寸 / 内部锚点 / 三角与本体矩形（**只改布局**）。"""
        self._side, self._face = side, face
        self._bbox = bubble_pop_bbox(self._body_w, self._body_h, side=side, face=face)
        self._anchor = QPointF(-self._bbox.left(), -self._bbox.top())
        self.setFixedSize(self._bbox.width(), self._bbox.height())
        self._build_shapes()

    def _anchor_xy(self, side=None, face=None):
        r = self._sprite
        return bubble_anchor(r.x(), r.y(), r.width(), r.height(),
                             side=self._side if side is None else side,
                             face=self._face if face is None else face)

    def _target_pos(self):
        """当前朝向 + 当前贴图矩形下，窗口左上角**该在**的位置。"""
        ax, ay = self._anchor_xy()
        return QPointF(ax + self._bbox.left(), ay + self._bbox.top())

    def _move_to(self, pos):
        self.move(int(round(pos.x())), int(round(pos.y())))

    def want_orientation(self):
        """按当前贴图 / 可用屏幕空间算**想要**的朝向（迟滞要拿当前朝向做比较）。"""
        if self._sprite is None or self._avail.isNull():
            return (self._side, self._face)
        side = bubble_side(self._sprite, self._avail, self._side)
        face = bubble_face(self._sprite, self._avail, self._body_h, self._face)
        return (side, face)

    # ---- 对外只读状态（冒烟测试用）----
    @property
    def text(self) -> str:
        """这一轮回复的**全文**（分段后 doc 里只有当前那段，所以这里给的是 `_full_text`）。"""
        return self._full_text

    @property
    def page_text(self) -> str:
        """当前这一段（就是量高 / 绘制那个 doc 里的文字）。"""
        return self._doc.toPlainText()

    @property
    def page_count(self) -> int:
        """这一轮切成了几段（短回复恒为 1）。"""
        return len(self._pages)

    @property
    def page_index(self) -> int:
        """正在显示第几段（0 起）。"""
        return self._page_i

    @property
    def text_opacity(self) -> float:
        """文字自己的不透明度（段间淡字动的是它；整条气泡的是 `pop_pose[2]`）。"""
        return self._text_op

    @property
    def body_height(self) -> int:
        """气泡本体（不含尾巴、不含弹出时的缩放）的高度。"""
        return self._body_h

    @property
    def pop_pose(self):
        """当前这一帧的（旋转角, 缩放, 不透明度）。"""
        return self._angle, self._scale, self._opacity

    @property
    def side(self):
        """气泡在贴图的哪一侧（SIDE_LEFT / SIDE_RIGHT）。"""
        return self._side

    @property
    def face(self):
        """尾巴朝下还是朝上（FACE_DOWN / FACE_UP）。"""
        return self._face

    @property
    def anchor_point(self) -> QPointF:
        """锚点在这个控件里的位置。"""
        return QPointF(self._anchor)

    def is_shown(self) -> bool:
        """是否正在显示（淡出过程中仍算显示，直到不透明度归零）。"""
        return self.isVisible() and self._opacity > 0.0

    def is_flipping(self) -> bool:
        """翻转的平移动画是否正在进行。"""
        return self._flip_anim is not None

    def _char_color(self) -> str:
        """气泡文字的字符格式颜色（#334155）—— 冒烟测试用它守住「别退回调色板色」。"""
        cursor = QTextCursor(self._doc)
        cursor.select(QTextCursor.Document)
        return cursor.charFormat().foreground().color().name().upper()

    # ---- 对外：显示 / 淡出 / 跟随 ----
    def show_text(self, text, sprite, avail=None):
        """把气泡叫出来（文字变了就重算高度与朝向），并**重放**弹出动画。

        已经在显示时再叫一次 = 用新文字重放（同一轮里用户抢话 -> 新一轮），不叠加两个气泡。
        **四改**：超长回复先切段（`bubble_pages`），这里只摆出**第一段**；段与段之间的切换由
        `_schedule_page()` / `_next_page()` 接手。**只有一段时全程没有定时器、不淡字** ——
        短回复的行为与四改前逐位一致。
        """
        self._stop_anims()                 # 上一轮的段定时器 / 淡字动画一律作废，必须**先**停
        self._full_text = str(text or "")
        self._pages = bubble_pages(self._full_text)
        self._page_i = 0
        self._set_page_text(self._pages[0] if self._pages else self._full_text)
        self._sprite = sprite
        if avail is not None:
            self._avail = avail
        self._apply_orientation(*self.want_orientation())
        self._move_to(self._target_pos())
        self._start_pop()
        # 必须排在 `_start_pop()` **之后**：它内部还会 `_stop_anims()`，排在前面会被它清掉
        self._schedule_page()

    def _set_page_text(self, text):
        """把**这一段**写进量高 / 绘制共用的那个 doc，并重算本体高。"""
        self._doc.setPlainText(text)
        # 颜色**必须显式写进字符格式**：`QTextDocument` 既不认 painter 的笔色、也不吃 QSS，
        # 它去用**调色板**的 Text 色 —— 深色主题下那是白色，字会在淡蓝底上直接隐形
        # （本机开发环境就是深色调色板：Text=#FFFFFF / Base=#2D2D2D，实测踩过）。
        cursor = QTextCursor(self._doc)
        cursor.select(QTextCursor.Document)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(BUBBLE_COLOR_TEXT))
        cursor.mergeCharFormat(fmt)
        self._doc.setTextWidth(self._text_w)
        text_h = int(math.ceil(self.doc_height()))
        self._body_h = bubble_body_h(text_h)

    def doc_height(self) -> float:
        """当前这段文字量出来的高度（量高与绘制共用同一个 doc）。"""
        return self._doc.documentLayout().documentSize().height()

    def hide_animated(self):
        """淡出（**只降不透明度**，不反向旋转、不缩小），归零后隐藏。没显示时是空操作。

        分段的段定时器 / 淡字动画一并停掉（走 `_stop_anims`）—— 气泡都要没了，下一段自然不用再翻。
        """
        if not self.isVisible():
            self._set_frame(0.0, 1.0, 0.0)
            return
        self._stop_anims()
        self._fade_anim = self._run_anim(self._opacity, 0.0, BUBBLE_FADE_MS,
                                         QEasingCurve.Linear,
                                         lambda v: self._set_frame(0.0, 1.0, v),
                                         self._on_fade_done)

    def follow(self, sprite, avail=None):
        """贴图挪了 / 变形了：把气泡摆到它的新位置；空间不够就翻到另一侧（平移动画）。"""
        self._sprite = sprite
        if avail is not None:
            self._avail = avail
        if sprite is None or not self.isVisible():
            return
        want = self.want_orientation()
        if want != (self._side, self._face):
            self._start_flip(*want)
        elif self._flip_anim is None:
            self._move_to(self._target_pos())

    # ---- 内部：翻转 ----
    def _start_flip(self, side, face):
        """翻转 = **平移**（500ms）：立即换朝向（尾巴换边是瞬时的），锚点插值到新位置。

        偏移量按「当前位置 − 新朝向的 ideal 位置」算，动画每帧把 ideal 重算一遍 —— 动画期间
        继续拖贴图也不会脱节（ideal 跟着最新贴图走），也不会重放弹出动画 / 闪一下。
        """
        self._stop_flip()
        old = QPointF(self.pos())
        self._apply_orientation(side, face)
        self._flip_delta = old - self._target_pos()
        self._move_to(self._target_pos() + self._flip_delta)
        self._flip_anim = self._run_anim(0.0, 1.0, BUBBLE_FLIP_MS, QEasingCurve.OutCubic,
                                         self._on_flip_value, self._on_flip_done)

    def _on_flip_value(self, p):
        self._move_to(self._target_pos() + self._flip_delta * (1.0 - float(p)))

    def _on_flip_done(self):
        self._flip_anim = None
        self._move_to(self._target_pos())

    def _stop_flip(self):
        if self._flip_anim is not None:
            self._flip_anim.stop()
            self._flip_anim = None
            self._flip_delta = QPointF(0.0, 0.0)

    # ---- 内部：分段显示（超长回复，四改）----
    def _schedule_page(self):
        """排「下一段」的停留定时器 —— **只有多段回复**才会真的排。

        存 `QTimer` **实例**（不用 `QTimer.singleShot`）：静态方法那个停不掉，而气泡被收起 /
        换新回复时必须能立刻把它掐掉（`_stop_anims`）。
        """
        if self._page_timer is not None:
            self._page_timer.stop()
            self._page_timer = None
        if self._page_i + 1 >= len(self._pages):
            return
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(bubble_page_dwell_ms(self._pages[self._page_i]))
        t.timeout.connect(self._next_page)
        self._page_timer = t
        t.start()

    def _next_page(self):
        """停留到点：先把这段文字淡掉（200ms）—— 换段放在「文字不可见」的那一刻做。"""
        self._page_timer = None
        if self._page_i + 1 >= len(self._pages) or not self.isVisible():
            return
        self._page_anim = self._run_anim(self._text_op, 0.0, BUBBLE_TEXT_FADE_MS,
                                         QEasingCurve.Linear,
                                         self._set_text_op, self._on_text_out_done)

    def _on_text_out_done(self):
        """文字已经淡没了：换段 + 改高度 + 重摆，然后再把新的一段淡进来。"""
        self._page_anim = None
        self._page_i += 1
        if self._page_i >= len(self._pages):
            return
        self._set_page_text(self._pages[self._page_i])
        self._relayout()
        self._page_anim = self._run_anim(0.0, 1.0, BUBBLE_TEXT_FADE_MS,
                                         QEasingCurve.Linear,
                                         self._set_text_op, self._on_text_in_done)

    def _on_text_in_done(self):
        self._page_anim = None
        self._set_text_op(1.0)
        self._schedule_page()

    def _set_text_op(self, v):
        """只改**文字**的不透明度（本体与尾巴照旧全不透明）。"""
        self._text_op = float(v)
        self.update()

    def _relayout(self):
        """换段后重摆：位置 / 朝向按**新的本体高**重算（需要换朝向就走 14.7 那条 500ms 平移）。"""
        want = self.want_orientation()
        if want != (self._side, self._face):
            self._start_flip(*want)
        else:
            self._apply_orientation(*want)
            self._move_to(self._target_pos())

    # ---- 内部：动画 ----
    def _set_frame(self, angle, scale, opacity):
        self._angle, self._scale, self._opacity = float(angle), float(scale), float(opacity)
        self.update()

    def _run_anim(self, start, end, ms, curve, on_value, on_done):
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(int(ms))
        anim.setEasingCurve(curve)
        anim.valueChanged.connect(on_value)
        anim.finished.connect(on_done)
        anim.start()
        return anim

    def _stop_anims(self):
        for name in ("_pop_anim", "_fade_anim", "_flip_anim", "_page_anim"):
            anim = getattr(self, name)
            if anim is not None:
                anim.stop()
                setattr(self, name, None)
        if self._page_timer is not None:       # 段定时器不是动画，得单独停
            self._page_timer.stop()
            self._page_timer = None
        self._flip_delta = QPointF(0.0, 0.0)
        # 停 = 回到「文字全不透明」的静止态：新一轮回复从头开始时靠这条，
        # 否则会继承上一轮停在半途的淡字透明度（半透明的字）
        self._text_op = 1.0

    def _start_pop(self):
        """从「逆时针 15 度、缩放 0.30、全透明」转 / 放大 / 淡入到位（以锚点为轴）。"""
        self._stop_anims()
        self._set_frame(*bubble_pop_state(0.0))
        self.show()
        self.raise_()
        self._pop_anim = self._run_anim(
            0.0, 1.0, BUBBLE_POP_MS, QEasingCurve.OutCubic,
            lambda v: self._set_frame(*bubble_pop_state(v)), self._on_pop_done)

    def _on_pop_done(self):
        self._pop_anim = None
        self._set_frame(*bubble_pop_state(1.0))

    def _on_fade_done(self):
        self._fade_anim = None
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        # 旋转 / 缩放 / 透明度**同一条绘制链**（不要拆成 effect）：三者必须严格同步，
        # 而且这样 grab() 抓到的就是真机像素，截图核对才有意义。
        p.setOpacity(self._opacity)
        p.translate(self._anchor)
        p.rotate(self._angle)            # 负角 = 视觉逆时针
        p.scale(self._scale, self._scale)
        # 尾巴：与本体**同款**「深蓝描边 + 淡蓝底」（2026-09-17 三改：原来是实心深蓝），
        # 三个角倒成 BUBBLE_RADIUS 的圆角
        p.setPen(QPen(QColor(BUBBLE_COLOR_BORDER), BUBBLE_BORDER,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QColor(BUBBLE_COLOR_FILL))
        p.drawPath(self._tail_path)
        # 本体：深蓝边框 + 淡蓝底。笔宽是**居中**描边 -> 内缩半个笔宽，
        # 否则一半落在控件外，看起来只有一半粗
        half = BUBBLE_BORDER / 2.0
        p.setPen(QPen(QColor(BUBBLE_COLOR_BORDER), BUBBLE_BORDER))
        p.setBrush(QColor(BUBBLE_COLOR_FILL))
        p.drawRoundedRect(self._body_rect.adjusted(half, half, -half, -half),
                          BUBBLE_RADIUS, BUBBLE_RADIUS)
        # 文字：同一个 doc 量高 + 绘制（drawContents 会跟着 painter 的透明度一起淡；
        # 颜色在 _set_page_text 里写进了字符格式，这里不靠 p.setPen）。
        # **分段换字只动 `_text_op`**（本体与尾巴仍用整条的 `_opacity`）—— 所以这里是乘法
        p.setOpacity(self._opacity * self._text_op)
        p.translate(self._text_rect.x(), self._text_rect.y())
        self._doc.drawContents(p, QRectF(0, 0, self._text_rect.width(), self._text_rect.height()))
        p.end()

class _PetToast(QWidget):
    """桌宠**贴图正上方**的状态提示气泡（长方形、小圆角、深蓝边 + 淡蓝底）。

    一个控件装两种文本，叠在一起：
      - **状态**（常驻）：`set_state()` / `clear_state()` —— 「待机中」+ 点动画 / 「休眠中」；
      - **事件**（一闪）：`flash()` —— 「已唤醒」/「已进入静音模式」…，到点淡出后**自动露出**底下的状态。

    为什么不复用 `_PetBubble`：尺寸随谁变正好相反（这个是**高钉死、宽随文字**）、没有尾巴、不做让位、
    不做分段 —— 硬套会让两边都长出用不到的参数（见 docs/02 §15.1）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # 与聊天气泡同一套窗口 flags：顶层、不吃鼠标（窗比看到的气泡大一圈，那圈透明区域不能挡住桌面点击）
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._font = _toast_font()
        self._state_text = ""
        self._state_dots = False
        self._flash_text = ""
        # 淡出期间继续画的那条：正文（`_flash_text` / 瞬态状态）在淡出**开始时**就被清掉了，
        # 不留这一份的话 `paintEvent` 会因为「没有文本」直接 return -> 画面上什么都不剩，
        # 看着就是「啪」地消失、根本没有淡出（真机报过）。
        self._fade_text = ""
        self._dots_n = 0
        self._sprite = None
        self._avail = QRect()           # 贴图所在屏幕的可用区域（判「上方放不放得下」）
        self._above = True              # 当前挂在上方还是下方（迟滞要拿它比）
        self._flip_anim = None          # 让位是**平移**（TOAST_FLIP_MS），不是重建
        self._flip_delta = QPointF(0.0, 0.0)
        self._opacity = 0.0
        self._dy = 0.0
        self._anim = None
        self._anim_kind = None          # "show" / "hide"：判「淡入还在不在跑」不能靠 _opacity（会被手工收尾绕过）
        # 瞬态文本（一闪事件 / 休眠中）的「停留」计时：**淡入结束后**起表，到点淡出。
        # 唯一不走这条的是「待机中 + 点动画」—— 那是常驻，她一直等你下指令（见 _is_transient）。
        self._hold_timer = None
        self._hold_ms = TOAST_HOLD_MS
        self._hold_pending = False
        self._hold_text = ""
        self._dots_timer = QTimer(self)
        self._dots_timer.setInterval(TOAST_DOT_MS)
        self._dots_timer.timeout.connect(self._on_dot)
        self._body_w = 0
        self._scale = 1.0
        # 窗口比本体**上下各高 `TOAST_POP_DY`**：弹出时本体先画在下方 5px 处，收起时再往上走 5px ——
        # 上下都得留白，只留一边会在另一边被窗口自己裁掉。
        self._win_h = TOAST_H + 2 * TOAST_POP_DY
        self._sync_geometry()
        self.hide()

    # ---- 对外：两类文本 ----
    def set_state(self, text, *, dots: bool = False):
        """挂一条状态：`待机中`（**带点 = 常驻**）/ `休眠中`（**瞬态**：淡入后停留 2s 就走）；
        `text` 为空 = 收起。"""
        text = str(text or "")
        dots = bool(dots and text)
        if (text, dots) == (self._state_text, self._state_dots):
            return                      # 同一个状态重复设：什么都不做（别打断正在跑的动画）
        self._state_text, self._state_dots = text, dots
        self._dots_n = 0                # 从「0 个点」起步，1s 后加第一个
        if dots:
            self._dots_timer.start()
        else:
            self._dots_timer.stop()
        self._refresh()
        self._after_text_change()

    def clear_state(self):
        """收起状态（她开始答话 / 离开等待指令时）。"""
        self.set_state("")

    def flash(self, text, ms=None):
        """弹一条**事件**提示：**淡入结束后**停留 `ms` 毫秒再淡出（默认 `TOAST_HOLD_MS`）。"""
        text = str(text or "")
        if not text:
            return
        self._flash_text = text
        self._hold_ms = int(ms if ms is not None else TOAST_HOLD_MS)
        self._hold_text = ""            # 连着来两条（哪怕文字一样）：后一条重新起表
        self._refresh()
        self._after_text_change()

    def follow(self, sprite, avail=None):
        """贴图挪了 / 变形了：跟到它的**正上方居中**；上方放不下就让到**下方 5px**（平移 0.5s）。"""
        if avail is not None:
            self._avail = avail
        self._sprite = sprite
        want = self._want_above()
        if want != self._above:
            self._start_flip(want)
        else:
            self._move_to_target()

    def _want_above(self) -> bool:
        """按当前贴图 / 可用屏幕空间算**想要**挂哪边（迟滞要拿当前朝向做比较）。"""
        if self._sprite is None or self._avail.isNull():
            return self._above
        return toast_above(self._sprite, self._avail, TOAST_H, self._above)

    # ---- 只读状态（冒烟测试用）----
    @property
    def shown_text(self) -> str:
        """这一帧真正画出来的那条文本（事件优先）。"""
        return self._shown_text()

    @property
    def state_text(self) -> str:
        return self._state_text

    @property
    def flash_text(self) -> str:
        return self._flash_text

    @property
    def dots_n(self) -> int:
        return self._dots_n

    @property
    def body_w(self) -> int:
        return self._body_w

    @property
    def opacity(self) -> float:
        return self._opacity

    @property
    def scale(self) -> float:
        return self._scale

    @property
    def above(self) -> bool:
        """当前是挂在贴图**上方**（True，默认）还是**下方**（False，上方放不下时让位）。"""
        return self._above

    def is_flipping(self) -> bool:
        """让位的平移动画是否正在跑。"""
        return self._flip_anim is not None

    def is_shown(self) -> bool:
        """是否正在显示（淡出过程中仍算显示，直到不透明度归零）。"""
        return self.isVisible() and self._opacity > 0.0

    # ---- 内部：文本 ----
    def _shown_text(self) -> str:
        if self._flash_text:
            return self._flash_text
        if not self._state_text:
            return ""
        return self._state_text + ("." * self._dots_n if self._state_dots else "")

    def _paint_text(self) -> str:
        """这一帧画什么：活的文本优先；正在淡出就继续画淡出前那条（见 `_fade_text`）。"""
        return self._shown_text() or self._fade_text

    def _is_transient(self) -> bool:
        """这条文本要不要「淡入结束后停留 2s 再淡出」。

        **唯一常驻的是「待机中 + 点动画」** —— 它表示「她一直在等你下指令」，得一直挂着；
        其余（一闪事件、`休眠中`）都是「报一下就走」的瞬态提示（用户 2026-09-18 口径）。
        """
        if not self._shown_text():
            return False
        if self._flash_text:
            return True
        return not self._state_dots

    def _after_text_change(self):
        """文本变了：按新文本决定要不要上（或续）「停留」计时。

        只有**显示文本真的换了**才重新起表 —— `clear_state_toast()` 在事件盖着的时候不该把事件的
        停留时间重新计一遍。
        """
        txt = self._shown_text()
        if not txt or not self._is_transient():
            self._stop_hold()
            self._hold_text = ""
            return
        if txt != self._hold_text:
            self._hold_text = txt
            self._arm_hold()

    def _arm_hold(self):
        """给当前这条瞬态文本起「停留」计时。

        **从淡入动画结束那一刻开始算**（用户口径）：动画还在跑就先挂起，
        等 `_on_show_done()` 里再起表。
        """
        self._stop_hold()
        if self._anim_kind == "show":
            self._hold_pending = True   # 淡入还在跑：等 _on_show_done() 再起表
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(self._hold_ms)
        timer.timeout.connect(self._on_hold_done)
        self._hold_timer = timer
        timer.start()

    def _stop_hold(self):
        """停掉停留计时（文本换成常驻 / 收起了 / 要重新起表）。"""
        self._hold_pending = False
        if self._hold_timer is not None:
            self._hold_timer.stop()
            self._hold_timer = None

    def _widest_text(self) -> str:
        """**量宽**用的那条：点按最多算 —— 否则点动画每秒都要改一次宽度（看着像在抖）。"""
        if self._flash_text:
            return self._flash_text
        if not self._state_text:
            return ""
        return self._state_text + ("." * TOAST_DOT_MAX if self._state_dots else "")

    # ---- 内部：几何 / 动画 ----
    def _target_pos(self):
        """当前落点（QPointF：让位时要和 QPointF 的偏移量相加）。"""
        if self._sprite is None:
            return QPointF(self.x(), self.y())
        x, y, _w, _h = toast_rect(self._sprite, self._body_w, below=not self._above)
        return QPointF(x, y - TOAST_POP_DY)     # 窗口在本体上下各多留一圈白

    def _move_to_target(self):
        if self._sprite is None or self._flip_anim is not None:
            return                              # 让位动画在跑时不许被别的重排打断
        pos = self._target_pos()
        self.move(int(round(pos.x())), int(round(pos.y())))

    # ---- 内部：让位（上方放不下 -> 平移到底下）----
    def _start_flip(self, above):
        """让位 = **平移**（500ms）：先换落点（上/下），再让窗口从旧位置插值过去。

        与聊天气泡的翻转同一套做法：偏移量按「当前位置 − 新落点的 ideal」算，
        动画每帧把 ideal 重算一遍 —— 动画期间继续拖贴图也不会脱节。
        """
        self._stop_flip()
        old = QPointF(self.pos())
        self._above = bool(above)
        self._flip_delta = old - self._target_pos()
        _p = self._target_pos() + self._flip_delta
        self.move(int(round(_p.x())), int(round(_p.y())))
        self._flip_anim = self._run(0.0, 1.0, self._on_flip_value, self._on_flip_done,
                                    dur=TOAST_FLIP_MS)

    def _on_flip_value(self, p):
        pos = self._target_pos() + self._flip_delta * (1.0 - float(p))
        self.move(int(round(pos.x())), int(round(pos.y())))

    def _on_flip_done(self):
        self._flip_anim = None
        self._flip_delta = QPointF(0.0, 0.0)
        self._move_to_target()

    def _stop_flip(self):
        if self._flip_anim is not None:
            self._flip_anim.stop()
            self._flip_anim = None
            self._flip_delta = QPointF(0.0, 0.0)

    def _sync_geometry(self):
        """按**最长那条文本**定宽（高度恒定），并跟到贴图正上方。"""
        w = toast_body_w(self._widest_text(), self._font)
        if w != self._body_w or self.size().height() != self._win_h:
            self._body_w = w
            self.setFixedSize(w, self._win_h)
        self._move_to_target()

    def _refresh(self):
        """文本变了：重排 + 该出现就弹出、该消失就淡出。"""
        live = self._shown_text()
        if live:
            self._fade_text = live      # 记下最后画过的那条：淡出期间还得靠它继续画
            self._sync_geometry()
        # 没有活文本 = 要淡出：**不重算几何** —— 现在按空文本量出来只有二十几像素宽，
        # 缩完再淡出就完全看不出「由大到小」了；保持原尺寸、画原来那条。
        self.update()
        if live:
            if not self.isVisible() or self._opacity <= 0.0:
                self._start_show()
            elif self._anim is None and self._opacity < 1.0:
                self._start_show()
        else:
            self._start_hide()

    def _set_frame(self, opacity, dy, scale=1.0):
        self._opacity, self._dy, self._scale = float(opacity), float(dy), float(scale)
        self.update()

    @staticmethod
    def _scale_for(v):
        """缩放：收起态 50% → 到位态 100%（用户口径「大小的 50% 到 100%」）。"""
        return TOAST_MIN_SCALE + (1.0 - TOAST_MIN_SCALE) * float(v)

    def _pop_frame(self, v):
        """弹出中（`v` 0→1）：从**下方 5px** 上来 + 由小到大 + 淡入。"""
        return (float(v), TOAST_POP_DY * (1.0 - float(v)), self._scale_for(v))

    def _out_frame(self, v):
        """收起中（`v` 1→0）：再**往上**走 5px + 由大到小 + 淡出（方向与弹出相反）。"""
        return (float(v), -TOAST_POP_DY * (1.0 - float(v)), self._scale_for(v))

    def _run(self, a0, a1, on_value, on_done, dur=None):
        anim = QVariantAnimation(self)
        anim.setStartValue(float(a0))
        anim.setEndValue(float(a1))
        anim.setDuration(TOAST_POP_MS if dur is None else int(dur))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(on_value)
        anim.finished.connect(on_done)
        anim.start()
        return anim

    def _start_show(self):
        """自下而上 5px + 由小到大 + 淡入（已经在显示时改文本**不重放**：点动画每秒都会走到这里）。"""
        self._stop_anim()
        self.show()
        self.raise_()
        self._anim_kind = "show"
        self._anim = self._run(
            self._opacity, 1.0,
            lambda v: self._set_frame(*self._pop_frame(v)),
            self._on_show_done)

    def _start_hide(self):
        """淡出：不透明度 1→0 + 由大到小（100% → 50%）+ 再向上 5px，0.5s，归零后 hide()。"""
        if not self.isVisible():
            self._fade_text = ""
            self._set_frame(0.0, 0.0, TOAST_MIN_SCALE)
            return
        self._stop_anim()
        self._anim_kind = "hide"
        self._anim = self._run(self._opacity, 0.0,
                               lambda v: self._set_frame(*self._out_frame(v)), self._on_hide_done)

    def _on_show_done(self):
        # 先 `_stop_anim()`：这个回调平时由动画的 `finished` 触发（那时它已经跑完，stop 是空操作），
        # 但测试 / 截图工具会**手工**叫它 —— 这时动画还在跑，只把 `_anim` 置空会让它变成脱缰的孤儿，
        # 0.5s 后自己 `finished` 回头再打一次，把后面手工摆的那一帧盖掉（真踩过）。
        self._stop_anim()
        self._set_frame(1.0, 0.0, 1.0)
        if self._hold_pending:
            self._arm_hold()            # 淡入结束 -> 从**这一刻**起算 2s 停留

    def _on_hide_done(self):
        self._stop_anim()               # 同上：手工触发时把还在跑的淡出动画掐掉
        self._hold_pending = False
        self._fade_text = ""            # 淡完了才把「最后画过的那条」丢掉
        self.hide()

    def _stop_anim(self):
        self._anim_kind = None
        if self._anim is not None:
            self._anim.stop()
            self._anim = None

    def stop_all(self):
        """收干净（退出流程 / 冒烟测试）：停掉所有动画与两个定时器，姿态复位到「到位态」。"""
        self._stop_anim()
        self._stop_flip()
        self._set_frame(self._opacity, 0.0, 1.0)
        self._stop_hold()
        self._hold_text = ""
        self._dots_timer.stop()

    def _on_hold_done(self):
        """停留到点：把这条**瞬态**文本收掉（事件优先，否则是 `休眠中`）。"""
        if self._hold_timer is not None:
            self._hold_timer.stop()     # 手工调用（测试 / 截图）时别留一颗还在跑的定时器
        self._hold_timer = None
        self._hold_pending = False
        if self._flash_text:
            self._flash_text = ""       # 露出底下的常驻状态（没有就整条收起）
        elif self._state_text and not self._state_dots:
            self._state_text = ""       # `休眠中` 也是瞬态：报一下就走
            self._dots_n = 0
        self._hold_text = ""
        self._refresh()
        self._after_text_change()       # 露出来的那条要是也瞬态，给它自己的一轮停留

    def _on_dot(self):
        # 0 → 1 → 2 → 3 → 0 …（**清空那一步也占满 1 秒**，与用户口径一致）
        self._dots_n = (self._dots_n + 1) % (TOAST_DOT_MAX + 1)
        self.update()                   # 宽度按最长那条算 → 只重画、不重排

    def paintEvent(self, event):
        text = self._paint_text()
        if not text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setOpacity(self._opacity)
        # 先绕**本体下边中点**缩放，再整体上下平移 —— 弹出「由小到大 + 自下而上」、收起反过来
        cx, base = self._body_w / 2.0, float(TOAST_POP_DY + TOAST_H)
        p.translate(cx, base + self._dy)
        p.scale(self._scale, self._scale)
        p.translate(-cx, -base)
        half = TOAST_BORDER / 2.0            # 笔宽居中 -> 内缩半个笔宽，外沿才与几何线齐
        body = QRectF(0, TOAST_POP_DY, self._body_w, TOAST_H).adjusted(half, half, -half, -half)
        p.setPen(QPen(QColor(BUBBLE_COLOR_BORDER), TOAST_BORDER))
        p.setBrush(QColor(BUBBLE_COLOR_FILL))
        p.drawRoundedRect(body, TOAST_RADIUS, TOAST_RADIUS)
        p.setPen(QColor(BUBBLE_COLOR_TEXT))
        p.drawText(QRectF(0, TOAST_POP_DY, self._body_w, TOAST_H), Qt.AlignCenter, text)
        p.end()

# ---- 右键菜单的皮肤 / 几何（2026-09-19 二改，规格见 design.md 4.10）----
def menu_rect(sprite: QRect, avail: QRect, click: QPoint, size: QSize):
    """算菜单该摆在哪儿 → `(QRect, side)`，`side` 是 `"right"` / `"left"`（弹出动画的原点角用）。

    用户口径（2026-09-19 二改）：
      * 横向：**两侧对称 —— 菜单都压住贴图 8px**（`MENU_GAP`）：默认贴右侧（菜单左边 = 贴图右边 − 8px），
        右侧放不下就改贴左侧（菜单右边 = 贴图左边 **+** 8px，同样压住 8px）。
      * 纵向：菜单**底边 = 鼠标点击的 y**（从点击处往上长）—— 所以「下方空间不足」不用判断。
      * 纵向兜底：上方实在放不下 → 菜单**上边紧贴可用区顶端**。
      * 横向兜底：两边都放不下 → 夹回可用区，至少不让整张菜单跑到屏幕外。

    `side` = 菜单在贴图的哪一侧 → 决定动画原点：贴右侧用菜单**左下角**，贴左侧用**右下角**
    （就是用户说的「点击位置（菜单整体的左下 / 右下角）」）。
    """
    w, h = size.width(), size.height()
    x = sprite.x() + sprite.width() - MENU_GAP          # 贴右侧：菜单左边 = 贴图右边 − 8（压住 8px）
    side = "right"
    if x + w > avail.x() + avail.width():               # 右侧放不下 → 改贴左侧
        x = sprite.x() + MENU_GAP - w                   # 菜单右边 = 贴图左边 + 8（**也是压住 8px**，两侧对称）
        side = "left"
    x = max(avail.x(), min(x, avail.x() + avail.width() - w))   # 兜底：夹回可用区
    y = click.y() - h                                   # 底边 = 点击位置（往上长）
    if y < avail.y():                                   # 上方放不下 → 上边贴屏幕顶端
        y = avail.y()
    return QRect(x, y, w, h), side


class _PatPatOverlay(QWidget):
    """patpat 模式那一只「手」：一块**独立顶层窗**，盖在角色贴图**之上**。

    用户口径：左键点贴图 → 按顺序显示 `抬起`（0.3s）→ `下压`（0.3s）。

    ⚠️ 为什么是独立顶层窗、不是 `PetWindow` 的子控件 —— 与 `_PetBubble` / `_PetToast` 同一个理由：
    节能态下叠加图会**高出贴图窗口的顶边**（爱丽丝扁平贴图 150×100 + 手 150×113 ⇒ 顶边 −50px），
    子控件会被父窗直接裁掉，而顶层窗想画到哪儿就画到哪儿。

    ⚠️ 三个属性都不能少：
      - `WindowTransparentForInput`：它整块盖在贴图上，**绝不能把点击吃掉** ——
        否则「点贴图摸她」这一下会被这层接走，越摸越点不动；
      - `WA_TranslucentBackground`：手是带 alpha 的 PNG，外圈必须透；
      - `WA_ShowWithoutActivating`：不能因为弹一下就抢走焦点（她本来就不抢焦点）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._pm = QPixmap()
        # 当前画的是第几帧（0=抬起 / 1=下压）。**只给调试与冒烟测试用** ——
        # 不能靠 `pixmap().cacheKey()` 认帧：缩放会生成新的 QPixmap 对象，每次 cacheKey 都不同。
        self._index = -1
        self.hide()

    # ---- 对外 ----
    def set_pixmap(self, pm, index: int = -1):
        """换成这一帧（两帧同尺寸，所以窗口几何不用重算）。"""
        self._pm = pm if pm is not None else QPixmap()
        self._index = int(index)
        if not self._pm.isNull():
            self.setFixedSize(self._pm.size())
        self.update()

    def show_at(self, pos):
        """挪到 `pos`（左上角，屏幕坐标）并显示 / 置顶。

        ⚠️ `raise_()` 要留在 `show()` **之后**：桌宠窗口也是置顶的 `Qt.Tool`，
        只有把这一只再抬一次，手才稳稳压在她头上（而不是被贴图盖住）。
        """
        self.move(int(pos[0]), int(pos[1]))
        self.show()
        self.raise_()

    def move_to(self, pos):
        """只挪位置（贴图被拖动 / 节能变形时跟着走）。"""
        if self.isVisible():
            self.move(int(pos[0]), int(pos[1]))

    def hide_now(self):
        self.hide()

    def is_shown(self) -> bool:
        return self.isVisible()

    def pixmap(self) -> QPixmap:
        """当前这一帧（冒烟测试用：判断此刻画的是「抬起」还是「下压」）。"""
        return self._pm

    def frame_index(self) -> int:
        """当前是第几帧（`0` = 抬起、`1` = 下压、`-1` = 还没放过）。"""
        return self._index

    # ---- 画 ----
    def paintEvent(self, e):  # noqa: N802 (Qt 命名)
        if self._pm.isNull():
            return
        p = QPainter(self)
        # 只贴这一张带 alpha 的手，**不刷任何底色**（窗口本来就是透明的）。
        p.drawPixmap(0, 0, self._pm)
        p.end()


class _ThinkingOverlay(QWidget):
    """思考气泡（**第二款气泡**）：非 patpat 模式单击贴图时，在旁边依次淡入三帧「思考泡泡」。

    规格见 `app/thinking.py`（常量 + 纯几何）与 docs/02 §20。三件事在这里落地：

    1. **画布**恒为 `THINKING_CANVAS`（248×228，= `thinking_fin` 的尺寸；fin 本身**不播放**，
       只用来定三帧的相对位置）。三帧按 `THINKING_OFFSETS` 落在画布上，**层层叠加**
       （0 亮完保留、再叠 1、再叠 2），不是逐个替换；
    2. **时序**：逐帧淡入（各 `THINKING_FADE_MS`，依次错开）→ 停留 `THINKING_HOLD_MS`
       → 整体淡出 `THINKING_OUT_MS` → 收；
    3. **朝向**：与聊天气泡（`_PetBubble`）同一套 —— 左侧放不下让到右侧、上方放不下让到下方；
       ★翻过去时**整张画布镜像**（各帧位置跟着镜像，尾点跑到另一侧）。

    ⚠️ 独立顶层窗 + `WindowTransparentForInput`（与 `_PatPatOverlay` / `_PetBubble` 同一个理由）：
    画布比可见内容大一圈（左下 / 右下那片是空的），而且气泡会伸出贴图窗口的边界
    （自尾尖往左最多 220px、往上最多 219px）—— 做子控件会被父窗直接裁掉，
    而那一圈透明区域又**不能吃掉桌面上的点击**。

    ⚠️ 淡入淡出**只走 `paintEvent` 里的 `setOpacity`**（与 `_PetBubble` 同一条绘制链），
    **不挂 `QGraphicsOpacityEffect`、也不用 `setWindowOpacity`**：那两条会各画一层再合成，
    和镜像变换混在一起容易错位，也让 `grab()` 抓不到真机像素。

    ---- 二十三改（2026-09-21）：跟着贴图等比缩放 + 放文字 + 连点每 2s 换句 ----

    4. **缩放**：比例 = **贴图显示宽 ÷ 贴图原图宽**（爱丽丝 150/300 = 0.5×，见
       `thinking_scale`）。比例由 `PetWindow` 经 `set_scale_provider()` 注入 —— 本窗**不认识**
       `app.pet`，只认「一个能吐出比例的零参回调」。`paintEvent` 里先 `scale(s, s)` 再镜像
       ⇒ 三帧、文字、落点一起缩（各处仍用**基准画布**坐标，不必各乘一遍）；
    5. **文字**：每轮抽**一句**（`play()` 里抽、`_on_switch_tick()` 里换）。文字块位置跟着镜像
       （`thinking_text_rect`），但**字本身不镜像** —— 所以画在 `restore()` 之后。文字有**自己的
       不透明度通道** `_text_op`（与整条气泡的 `_opacity` 相乘）：三帧全亮后 100ms 淡入；
       淡出直接跟气泡走；连点换句时旧字**瞬灭**、新字 100ms 淡入（见 `_fade_text_in`）；
    6. **连点**：`play()` 按「**距上一次单击**多久 ＋ **气泡还在不在**」分岔 ——
       在 `THINKING_MASH_MS` 内**且 `is_shown()`** = 连点：
       **不重装三帧、不重放淡入**（帧直接置全亮续上），只把停留计时续上；换句由一条
       **循环**定时器负责，它从这一轮第一次单击起就一直跑，点击**一个字都不碰它** ——
       这就是用户口径「切换次数仅由时间决定而非连点次数」。
       ★判据**必须**是「距**上一次**单击」：`_mash_origin` 在**每一次**点击时都要续期。
       只在「新一轮」分支里更新是错的 —— 那样连点累计超过 `THINKING_MASH_MS` 之后的那一下
       会掉进「新一轮」⇒ `_ops` 归零 + 三帧重新淡入 ⇒ 肉眼「**气泡消失再淡入**」；
       而用户口径是「**只有文字**该消失再淡入，气泡保持显示；气泡淡出**仅**由停手计时决定」。
       ★★**两个判据缺一不可**（2026-09-29 补第二条，用户口径「气泡消失后再次点击…随机内容要
       排除掉上一条」）：气泡一旦收干净（`THINKING_LIFE_MS` = 1.5+0.3+0.2 = **2s** 到点），
       再点就**必须是新一轮**（重新抽句），否则只是把旧那一句原样续上来 ⇒ 看起来像「重复显示」。
       ⇒ 而「一轮寿命 == 连点窗口（都是 2s）」本身就是用户口径「**气泡的显示时长与连点时
       一次内容显示时长一致**」的落地；两者对齐之后，气泡消失 ⇒ 距上次点击必然已超窗口。
    """

    def __init__(self, anchor_of=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # 锚点由 `PetWindow` 提供（它才有 `bubble_anchor`）—— ★这样「与第一款气泡同一个贴合点」
        # 是**构造上就成立**的，而不是靠本文件再抄一遍 5/7 那套公式。
        self._anchor_of = anchor_of or (lambda side, face: (0, 0))
        # 内容池回调（`PetWindow` 注入）→ `[(kind, 标签, 数值), …]`；没注入 = 不画文字。
        self._content_of = None
        # 缩放比例回调（`PetWindow` 注入）→ 浮点 = 贴图显示宽 ÷ 原图宽（爱丽丝 0.5）；
        # 没注入 = 比例 1.0（保持基准画布，绝不 0）。
        self._scale_of = None
        self._frames = []                 # [(QPixmap, (dx, dy))]，与 `_ops` 一一对应
        self._ops = []                    # 各帧自己的不透明度（逐帧淡入）
        self._opacity = 1.0               # 整条气泡的不透明度（只管最后的整体淡出）
        # ★**文字自己**的不透明度（二十三改·二轮）：只被「文字淡入 / 连点换句」动。
        #   画的时候与 `_opacity` **相乘** ⇒ 淡出天然跟着气泡一起走，不用再排一段动画。
        self._text_op = 0.0
        self._side, self._face = SIDE_LEFT, FACE_DOWN
        self._sprite = None
        self._avail = QRect()
        self._scale = 1.0                 # 二十三改：等比缩放系数 = 贴图显示宽 ÷ 原图宽（爱丽丝 0.5）
        self._content = None              # 当前这一句 `(kind, 标签, 数值)`；`None` = 不画字
        self._mash_origin = None          # **上一次**单击的时刻（`time.monotonic()`）—— 判连点用的是「两次点击的间隔」
        self._in_anim = None
        self._out_anim = None
        self._text_anim = None
        self._flip_anim = None
        self._flip_delta = QPointF(0.0, 0.0)
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(THINKING_HOLD_MS)
        self._hold_timer.timeout.connect(self._on_hold_done)
        # ★连点换句：**循环**定时器（从这一轮第一次单击起一直跑，点击不重排 —— 见类文档第 6 条）。
        #   气泡收掉之后它会在下一次 tick 自查并停表（`_on_switch_tick`），不会空转。
        self._switch_timer = QTimer(self)
        self._switch_timer.setInterval(THINKING_SWITCH_MS)
        self._switch_timer.timeout.connect(self._on_switch_tick)
        self.setFixedSize(THINKING_CANVAS[0], THINKING_CANVAS[1])
        self.hide()

    # ---- 素材 / 内容 ----
    def set_frames(self, pixmaps):
        """装三帧（**顺序 = 播放顺序**）。空列表 = 没有素材，之后 `play` 直接不显示。"""
        self._frames = []
        for i, pm in enumerate(pixmaps or ()):
            if pm is None or pm.isNull() or i >= len(THINKING_OFFSETS):
                continue
            self._frames.append((pm, THINKING_OFFSETS[i]))
        self._ops = [0.0] * len(self._frames)
        self.update()

    def set_content_provider(self, fn):
        """注入内容池回调（`PetWindow._thinking_content`）—— 返回 `[(kind, 标签, 数值), …]`。"""
        self._content_of = fn

    def set_scale_provider(self, fn):
        """注入缩放比例回调（`PetWindow._thinking_ratio`）—— 返回「贴图显示宽 ÷ 原图宽」。

        ★为什么用回调而不是直接传值：贴图会换角色、会在站姿/节能态之间变形，比例是**变的**；
        而这个窗每帧都要用（`follow()` / `play()` 都要重算）⇒ 让它**每次来问**，别存快照。
        本窗**不** import `app.pet`（否则循环依赖），所以「怎么算」留在 `PetWindow` 里。
        """
        self._scale_of = fn

    def _roll_content(self):
        """从池子里抽**一句**（★**排除上一次那一句**）；没注入回调 / 池子空 / 回调出错 ⇒ `None`。

        ★★2026-09-29（用户口径）：把**当前这一句**（= 上一次显示的）当「这次别再来它」传进
        `pick_content(avoid=…)`。起因 —— 无 API 时第一类整类不进池子、只剩 2 条台词，
        纯均匀随机下**连点重复概率 50%**，用户报「出现重复显示的概率极大」。
        ★这条对**两个调用点都生效**（`show_bubble()` 新一轮 / `_on_switch_tick()` 连点换句）——
        用户只提了连点，但「新一轮也该换个花样」显然是同一个诉求，且只此一处逻辑。

        ⚠️★判据就用 `self._content`，**不另开字段**：`_stop_all()` 只清 `_ops` / `_text_op` /
        `_opacity`，**从不碰** `_content` ⇒ 连点链路上（`_patpat_stop()` → `_stop_all()`，
        见类文档第 6 条）它照样活着，正好就是「上一次显示的那一句」。
        """
        pool = []
        if self._content_of is not None:
            try:
                pool = list(self._content_of() or [])
            except Exception:  # noqa: BLE001
                # 内容池取数出错（比如余额线程正在写）最多让这一句不显示，不能把气泡带崩
                pool = []
        prev = self._content          # ★先抓住「上一次那一句」再覆盖 —— 它就是排除规则的唯一输入
        self._content = pick_content(pool, avoid=prev)

    def has_frames(self) -> bool:
        return bool(self._frames)

    def frame_rects(self):
        """三帧在当前朝向下该画在画布里的 `(x, y, w, h)`（冒烟测试用）。

        ⚠️ 这里算的是**镜像后**的位置（`thinking_frame_rect`），必须与 `paintEvent`
        里那把 `QTransform` 的结果一致 —— 测试会把两边对一遍。
        """
        sizes = [(pm.width(), pm.height()) for pm, _ in self._frames]
        return [thinking_frame_rect(i, self._side, self._face, sizes=sizes)
                for i in range(len(self._frames))]

    # ---- 朝向 / 位置 ----
    def _anchor(self, side, face):
        return self._anchor_of(side, face)

    def _target_pos(self):
        ax, ay = self._anchor(self._side, self._face)
        px, py = thinking_pos((ax, ay), self._side, self._face, scale=self._scale)
        return QPointF(px, py)

    def _move_to(self, pos):
        self.move(int(round(pos.x())), int(round(pos.y())))

    # ---- 缩放（二十三改）----
    def _scale_ratio(self):
        """向 `PetWindow` 要**当前**比例（贴图显示宽 ÷ 原图宽）；没注入 / 回调出错 ⇒ 1.0。"""
        if self._scale_of is None:
            return 1.0
        try:
            return float(self._scale_of())
        except Exception:  # noqa: BLE001
            # 拿不到比例最多让气泡按基准尺寸画，不能把整条链路带崩
            return 1.0

    def refresh_scale(self):
        """按注入的比例回调重算缩放（`play` / `_mash` / `show_bubble` / `follow` 都走它）。"""
        return self.set_sprite_scale(self._scale_ratio())

    def set_sprite_scale(self, ratio):
        """按「贴图显示宽 ÷ 原图宽」重定气泡大小（爱丽丝 150/300 ⇒ 0.5× → 124×114）。

        ⚠️ 只改窗口尺寸 + 落点 —— 三帧的落点、文字块位置**全都还是基准画布坐标**，
        缩放统一在 `paintEvent` 的 `scale(s, s)` 里做（各算一遍迟早会差 1px）。
        """
        s = thinking_scale(ratio)
        if abs(s - self._scale) < 1e-9:
            return False
        self._scale = s
        self.setFixedSize(*thinking_canvas_size(s))
        if self._sprite is not None:
            self._move_to(self._target_pos())
        self.update()
        return True

    def want_orientation(self):
        """按当前贴图 / 可用屏幕空间算**想要**的朝向（迟滞要拿当前朝向做比较）。

        ⚠️ 两个判据都拿**「左 + 面朝下」那个锚点**去问（与 `bubble_face` 同口径）：
        问的永远是「如果朝左 / 朝下，那边够不够」，而不是拿当前朝向的锚点去问。
        ⚠️ 判据里的「需要的空间」是**缩放后**的尾尖宽高（气泡变小了、要的地方也小）。
        """
        if self._sprite is None or self._avail.isNull():
            return (self._side, self._face)
        ax, ay = self._anchor(SIDE_LEFT, FACE_DOWN)
        side = thinking_side(self._avail, ax, self._side, scale=self._scale)
        face = thinking_face(self._avail, ay, self._face, scale=self._scale)
        return (side, face)

    def _apply_orientation(self, side, face):
        """换朝向：只记状态（画布尺寸不变，镜像在 `paintEvent` 里做）。"""
        self._side, self._face = side, face
        self.update()

    def _start_flip(self, side, face):
        """翻转 = **平移**（`THINKING_FLIP_MS`）：立即换朝向，位置从旧处插值到新处。

        与 `_PetBubble._start_flip` 同款：偏移量按「当前位置 − 新朝向的 ideal 位置」算，
        动画每帧把 ideal 重算一遍，所以动画期间继续拖贴图也不会脱节，
        也不会重放淡入 / 闪一下。
        """
        self._stop_flip()
        old = QPointF(self.pos())
        self._apply_orientation(side, face)
        self._flip_delta = old - self._target_pos()
        self._move_to(self._target_pos() + self._flip_delta)
        self._flip_anim = self._run_anim(0.0, 1.0, THINKING_FLIP_MS, QEasingCurve.OutCubic,
                                         self._on_flip_value, self._on_flip_done)

    def _on_flip_value(self, p):
        self._move_to(self._target_pos() + self._flip_delta * (1.0 - float(p)))

    def _on_flip_done(self):
        self._flip_anim = None
        self._move_to(self._target_pos())

    def _stop_flip(self):
        if self._flip_anim is not None:
            self._flip_anim.stop()
            self._flip_anim = None
            self._flip_delta = QPointF(0.0, 0.0)

    # ---- 对外 ----
    def play(self, pixmaps, sprite, avail):
        """单击入口：**重新播一轮**还是**连点续命**，由「**距上一次单击**多久 ＋ **气泡还在不在**」决定。

        - 距上一次单击 ≤ `THINKING_MASH_MS`（**2026-09-22 起定 2s**，原先按一轮寿命算得 1500ms）
          **且气泡仍显示着** ⇒ **连点**（用户口径「若出现连点…每两秒随机切换内容」）：
          不重装三帧、不重放淡入，见 `_mash`；
        - 否则 ⇒ **新一轮**：重装三帧 → 抽一句内容 → 从头淡入。

        ★是「距**上一次**」而不是「距这一轮**第一次**」——`_mash_origin` 在**每一次**点击时都续期
        （见下面那行 `self._mash_origin = now`）。用户口径「气泡淡出的判断条件**仅为**鼠标停止
        点击后的计时」⇒ 只要点击间隔还在窗口内，气泡就一直保持显示，换句时**只有文字**在动。

        ★★`is_shown()` 那一条是 **2026-09-29 补的**：「**气泡已经收掉了** ⇒ 这一下不算连点」。
        起因（用户原话）：

        > 气泡消失后再次点击也和连点时一样，随机内容要排除掉上一条显示过的。

        ⚠️ 光有「距上次点击 ≤ 2s」**不够**：气泡收干净的时刻是 **1.5s**（新一轮：300+1000+200）、
        或 **1.7s**（连点续命后：`_hold_timer` 1.5s + 淡出 200ms），而连点窗口要到 **2s** 才满
        ⇒ 那 **0.3~0.5s** 里点下去，按时间仍算连点 ⇒ 走 `_mash()` ⇒ **不重新抽句**、三帧直接置全亮
        ⇒ 用户看到「**同一条内容原样又冒出来**」。真机实测（改前）：连点两次**抽签 `1 → 1`、
        内容 `甲 → 甲`**。
        ★反向不受影响：气泡**还显示着**时点击照样只算连点（不换句、不重播三帧）—— 行为层有断言。
        ⚠️ 早先这里写着「判据**不许**看 `isVisible()` —— 单击链路上 `_patpat_play()` 会先把上一轮
        收掉」。**那条理由在二十三改之后就失效了**：`_patpat_stop()` 已不再收思考气泡
        （见 §20.13.5），连点期间气泡**一直是可见的** ⇒ 可见性完全能当判据用。
        """
        now = time.monotonic()
        mash = (self._mash_origin is not None
                and (now - self._mash_origin) * 1000.0 <= THINKING_MASH_MS
                and self.has_frames()
                # ★★气泡已经收掉 ⇒ 算**新一轮**（重新抽句、排除上一条），不是续命。
                and self.is_shown())
        # ★★判据是「**距上一次点击**」多久 ⇒ **每一次**点击（连点也好、新一轮也好）都要把原点
        #   推到当下。★只在「新一轮」分支里更新是**错的**：那样连点累计超过 `THINKING_MASH_MS`
        #   之后的那一下就会掉进「新一轮」⇒ `show_bubble()` ⇒ `_ops` 归零 + 三帧重新 0→1 淡入
        #   ⇒ 肉眼「**气泡消失再淡入**」（用户报的就是这个，节奏约 2s 所以容易被误当成换句所致
        #   —— 其实换句只动 `_text_op`，一个字都不碰气泡）。
        #   用户口径：「只需文字消失再淡入，**气泡保持显示状态**；气泡淡出的判断条件**仅为鼠标
        #   停止点击后的计时**」⇒ 只要两次点击的间隔还在窗口内，就一直算连点、气泡不重播。
        self._mash_origin = now
        if mash:
            return self._mash(sprite, avail)
        self.set_frames(pixmaps)
        return self.show_bubble(sprite, avail)

    def _mash(self, sprite, avail):
        """连点续命：**不重放三帧淡入**、也**不碰**换句定时器（见类文档第 6 条）。

        帧直接置成全亮再显示 —— 这一步是给「点击落在**淡入 / 淡出**半途」那种情形兜底的
        （淡入里点：不置全亮就会看见一次多余的淡入；淡出里点：不置全亮会先暗一下再亮）。
        走到这里时气泡**一定是可见的**（`play()` 的 `is_shown()` 判据），所以不必担心「窗口没显示」。

        ⚠️★**必须把在途的淡入 / 淡出都掐掉**（★淡出这一条是 2026-09-29 补的）：
        - 留着**三帧淡入**：它每帧都写 `self._ops`，16ms 后会把刚置好的全亮又打回半亮
          （连点在淡入那 300ms 之内发生时肉眼就是「闪一下」）；
        - 留着**整体淡出**：它的收尾 `_on_out_done()` 到点会把 `_ops` 归零 + `hide()` ⇒
          **点完反而没了**（它同时还会掐掉文字、清掉停留计时的意义）。真机实测「淡出中点击」正是这个现象。
        ★掐掉之后 `_on_in_done` 就不会来了 ⇒ 文字的淡入要**在这里补上**（帧已经全亮，
        正是用户口径「气泡完全显示后」那个时点）。
        """
        if not self._frames:
            return False
        self._sprite = QRect(sprite)
        self._avail = QRect(avail)
        self._stop_flip()
        want = self.want_orientation()
        self._side, self._face = want
        self.refresh_scale()
        if self._in_anim is not None:
            self._in_anim.stop()
            self._in_anim = None
        if self._out_anim is not None:      # ★2026-09-29：淡出里点一下 ⇒ 也得掐掉，否则点完接着淡没
            self._out_anim.stop()
            self._out_anim = None
        self._ops = [1.0] * len(self._frames)
        self._opacity = 1.0
        # ★只有还没亮起来的文字才补淡入 —— 已经全亮时不碰它（否则连点会把文字反复打回 0）
        if self._text_op < 1.0:
            self._fade_text_in()
        self._move_to(self._target_pos())
        if not self.isVisible():
            self.show()
            self.raise_()
        self._hold_timer.start(THINKING_HOLD_MS)   # 停手 1s 后照常收（用户口径「回到普通 1s 停留」）
        self.update()
        return True

    def show_bubble(self, sprite, avail):
        """叫出思考气泡：**重置**一轮（重新淡入 + 重新抽一句内容 + 换句节拍重新起表）。"""
        self._sprite = QRect(sprite)
        self._avail = QRect(avail)
        if not self._frames:
            return False
        self._stop_all()
        # ★先定缩放再算朝向/落点：让位判据用的就是缩放后的尾尖宽高。
        self._scale = thinking_scale(self._scale_ratio())
        self.setFixedSize(*thinking_canvas_size(self._scale))
        a0 = self._anchor(SIDE_LEFT, FACE_DOWN)
        side = thinking_side(self._avail, a0[0], SIDE_LEFT, scale=self._scale)
        face = thinking_face(self._avail, a0[1], FACE_DOWN, scale=self._scale)
        self._apply_orientation(side, face)
        self._move_to(self._target_pos())
        self._ops = [0.0] * len(self._frames)
        self._opacity = 1.0
        self._roll_content()          # 每次单击随机抽一句
        self._switch_timer.start()    # ★新一轮 → 节拍重新起表（之后连点不会再碰它）
        self.update()
        self.show()
        self.raise_()
        self._in_anim = self._run_anim(0.0, 1.0, THINKING_IN_TOTAL_MS, QEasingCurve.Linear,
                                       self._on_in_value, self._on_in_done)
        return True

    def follow(self, sprite, avail):
        """贴图挪了：跟着走（顺带按新尺寸重定缩放）；空间不够就翻到另一侧（平移动画）。"""
        self._sprite = QRect(sprite)
        self._avail = QRect(avail)
        if not self.isVisible():
            return
        # ★换角色 / 站姿↔节能态都会改比例 ⇒ 这里每次都重问一次，气泡才会跟着「缩」。
        self.refresh_scale()
        want = self.want_orientation()
        if want != (self._side, self._face):
            self._start_flip(*want)
        elif self._flip_anim is None:
            self._move_to(self._target_pos())

    def hide_now(self):
        """立刻收掉（关模式 / 换角色 / 关窗 / 进节能都走这一条）。"""
        self._stop_all()
        self.hide()

    def is_shown(self) -> bool:
        return self.isVisible()

    # ---- 时序 ----
    def _stop_all(self):
        """把在途的动画（淡入 / 淡出 / 文字淡入 / 平移）与停留计时一起掐掉（**不**改 `hide`）。

        ⚠️★**不掐换句定时器**：它是「按时间走」的那条 —— 连点时 `_patpat_stop()` 会经过这里，
        顺手停掉就等于「每次点击都重置节拍」，正好违背用户口径。它自己会在气泡收掉后的
        下一次 tick 停表（`_on_switch_tick`）。
        """
        for anim in (self._in_anim, self._out_anim):
            if anim is not None:
                anim.stop()
        self._in_anim = None
        self._out_anim = None
        self._hold_timer.stop()
        self._stop_flip()
        self._stop_text_anim()
        self._ops = [0.0] * len(self._frames)
        self._opacity = 1.0
        # 文字也归零：三帧都还没亮，字不该先露出来（`_on_in_done` 才会把它淡起来）。
        self._text_op = 0.0

    def _on_switch_tick(self):
        """连点换句：**只按时间**推进 —— 与期间点了多少次完全无关（用户口径）。

        ★用户口径（二十三改·二轮）「连点超过两秒（限制的文字替换时间）时的文字切换也要加入
        效果，替换前的文字**直接消失**，替换后的文字 100ms 淡入（这 100ms **也算入 2s 的文字
        替换时间**）」⇒ 旧字瞬灭 + 新字 100ms 淡入，且**换句定时器周期仍是整 `THINKING_SWITCH_MS`**
        （不因这 100ms 顺延 —— 这 100ms 就落在下一个 2s 区间里）。
        """
        if not self.isVisible():
            self._switch_timer.stop()      # 气泡已经收了 → 自己停表，别空转
            return
        self._stop_text_anim()
        self._text_op = 0.0                # 替换前的文字**直接消失**
        self._roll_content()
        self._fade_text_in()               # 替换后的文字 100ms 淡入

    def _run_anim(self, start, end, ms, curve, on_value, on_done):
        a = QVariantAnimation(self)
        a.setStartValue(float(start))
        a.setEndValue(float(end))
        a.setDuration(int(ms))
        a.setEasingCurve(curve)
        a.valueChanged.connect(lambda v: on_value(float(v)))
        a.finished.connect(on_done)
        a.start()
        return a

    def _on_in_value(self, p):
        self._ops = [thinking_frame_opacity(p, i) for i in range(len(self._frames))]
        self.update()

    def _on_in_done(self):
        """三帧**全亮** —— 用户口径的「气泡完全显示」这个时点：文字立刻开始 100ms 淡入。"""
        self._in_anim = None
        self._ops = [1.0] * len(self._frames)
        self._fade_text_in()
        self.update()
        self._hold_timer.start(THINKING_HOLD_MS)

    def _on_hold_done(self):
        self._out_anim = self._run_anim(1.0, 0.0, THINKING_OUT_MS, QEasingCurve.OutCubic,
                                        self._on_out_value, self._on_out_done)

    def _on_out_value(self, p):
        self._opacity = float(p)
        self.update()

    def _on_out_done(self):
        self._out_anim = None
        self._opacity = 1.0
        self._ops = [0.0] * len(self._frames)
        self._stop_text_anim()
        self._text_op = 0.0
        self.hide()

    # ---- 文字的不透明度（二十三改·二轮）----
    def _fade_text_in(self):
        """文字 100ms 淡入（0 → 1）。

        ★**只淡入、不单独淡出**：淡出直接靠 `_paint_content` 里那句
        `_opacity × _text_op` —— 气泡整体淡出时文字自然跟着一起淡（用户口径「淡出则与气泡
        一起淡出」），不用再排第二段动画。
        ★每次进来都**先归零**：连点换句时「替换前的文字直接消失」就是这一步。
        """
        self._stop_text_anim()
        self._text_op = 0.0
        self._text_anim = self._run_anim(0.0, 1.0, THINKING_TEXT_FADE_MS, QEasingCurve.OutCubic,
                                         self._set_text_op, self._on_text_in_done)
        self.update()

    def _set_text_op(self, v):
        self._text_op = max(0.0, min(1.0, float(v)))
        self.update()

    def _stop_text_anim(self):
        if self._text_anim is not None:
            self._text_anim.stop()
            self._text_anim = None

    def _on_text_in_done(self):
        self._text_anim = None
        self._text_op = 1.0
        self.update()

    # ---- 探针（冒烟测试用）----
    def side(self):
        return self._side

    def face(self):
        return self._face

    def opacity(self) -> float:
        """整条气泡的不透明度（只有最后的整体淡出会动它）。"""
        return float(self._opacity)

    def text_opacity(self) -> float:
        """**文字自己**的不透明度（文字淡入 / 连点换句看这个；0 = 字还看不见）。"""
        return float(self._text_op)

    def text_fading(self) -> bool:
        """文字的淡入动画此刻在不在跑（探针）。"""
        return self._text_anim is not None

    def frame_opacities(self):
        """各帧自己的不透明度（逐帧淡入看这个）。"""
        return list(self._ops)

    def scale(self) -> float:
        """当前等比缩放系数 = 贴图显示宽 ÷ 原图宽（爱丽丝 0.5）。"""
        return float(self._scale)

    def content(self):
        """当前这句内容 `(kind, 标签, 数值)`；没抽到 / 不显示文字 ⇒ `None`。"""
        return self._content

    def switch_running(self) -> bool:
        """连点换句定时器此刻在不在跑（探针）。"""
        return bool(self._switch_timer.isActive())

    def frame_rects_in_window(self):
        """三帧在**窗口坐标**里该占的 `(x, y, w, h)`（含缩放，冒烟测试对 `paintEvent` 用）。"""
        s = float(self._scale) or 1.0
        return [(r[0] * s, r[1] * s, r[2] * s, r[3] * s) for r in self.frame_rects()]

    # ---- 画 ----
    def paintEvent(self, e):  # noqa: N802 (Qt 命名)
        if not self._frames:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        s = float(self._scale) or 1.0
        p.save()
        # ★先按 scale 放大整个坐标系：下面三帧/文字块用的全是**基准画布**坐标，
        #   这样缩放只有一处真值（`self._scale`），不必每处各乘一遍。
        p.scale(s, s)
        # ★**整张画布镜像**：翻到右侧 → 左右翻；翻到下方 → 上下翻。
        #   于是各帧的落点也一起反过去了（`thinking_frame_rect` 算的就是这个结果）。
        # ⚠️ 镜像轴用 `窗口宽 / s`（= 基准画布宽），不能用 `self.width()` —— 那已经是缩放后的像素。
        if self._side == SIDE_RIGHT:
            p.translate(self.width() / s, 0)
            p.scale(-1.0, 1.0)
        if self._face == FACE_UP:
            p.translate(0, self.height() / s)
            p.scale(1.0, -1.0)
        for i, (pm, (dx, dy)) in enumerate(self._frames):
            op = float(self._ops[i]) * float(self._opacity)
            if op <= 0.0:
                continue
            p.setOpacity(op)
            p.drawPixmap(dx, dy, pm)
        p.restore()
        # ★文字**不镜像**：位置跟着镜像（`thinking_text_rect` 同一套 `p → 尺寸 − p`），
        #   但字本身照常正向画 —— 所以必须画在 `restore()` 之后、用**窗口坐标**。
        if self._content is not None and self._opacity > 0.0 and self._text_op > 0.0:
            self._paint_content(p, s)
        p.end()

    def _paint_content(self, p, s):
        """画这一句内容（不镜像）：标签 + 数值两行；台词类只有一行。

        ★不透明度 = `_opacity`（整条气泡，管淡出）× `_text_op`（文字自己，管淡入）——
        乘法就是用户口径「淡出与气泡一起、淡入自己来」的全部实现，不需要第二段淡出动画。
        """
        kind, label, value = self._content
        x, y, w, h = thinking_text_rect(self._side, self._face)
        box = QRectF(x * s, y * s, w * s, h * s)
        p.save()
        p.setOpacity(float(self._opacity) * float(self._text_op))
        f_val = QFont(THINKING_TEXT_FONT)
        f_val.setPixelSize(max(1, int(round(THINKING_VALUE_PX * s))))
        if not value:
            # 台词（第二类）：一行，用大字号居中
            p.setFont(f_val)
            p.setPen(QColor(THINKING_VALUE_COLOR))
            p.drawText(box, Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap, label)
            p.restore()
            return
        f_lab = QFont(THINKING_TEXT_FONT)
        f_lab.setPixelSize(max(1, int(round(THINKING_LABEL_PX * s))))
        fm_lab = QFontMetrics(f_lab)
        fm_val = QFontMetrics(f_val)
        gap = THINKING_LINE_GAP * s
        lh, vh = fm_lab.height(), fm_val.height()
        top = box.y() + (box.height() - (lh + gap + vh)) / 2.0
        p.setFont(f_lab)
        p.setPen(QColor(THINKING_LABEL_COLOR))
        p.drawText(QRectF(box.x(), top, box.width(), lh),
                   Qt.AlignHCenter | Qt.AlignVCenter, label)
        p.setFont(f_val)
        p.setPen(QColor(THINKING_VALUE_COLOR))
        p.drawText(QRectF(box.x(), top + lh + gap, box.width(), vh),
                   Qt.AlignHCenter | Qt.AlignVCenter, value)
        p.restore()


class _MenuPopup(QWidget):
    """自绘的右键弹窗（2026-09-19 八改：用它替掉 `QMenu`）。

    为什么要换：八改时用户要的弹出效果里带「**50% → 100% 缩放**」，而 `QMenu` 是 Qt 自己管的原生弹窗，
    只能整窗改不透明度 / 挪位置，**缩放不了**；二改那版「快照替身窗」又会先冒出一张缩小、发糊的菜单
    （四改已否）。所以改成**自己画的弹窗**：面板、菜单项、勾选、小尖、分隔线全在 `paintEvent()` 里画 ——
    自绘的另一个好处是**文字按当前字号当场重画**（不是把位图拉大，任何比例都清晰）。

    ⚠️ **2026-09-19 十四改：缩放整条路去掉了** —— 用户口径「不再进行大小上的变化，只要求右键淡入
    （仅不透明度提高）」。于是 `MENU_POP_SCALE` / `MENU_POP_BASE` / `_pop_base_color()` /
    `_apply_anim()` / `_progress` / `_scaling` 全部删除，`paintEvent` 只剩 `p.setOpacity(_opacity)`
    这一个动画通道，一级与二级完全同一条路；窗口几何从 `pop_up()` 到关掉**一动不动**。
    淡入淡出共用同一层底：`paintEvent` 先把**抓来的真桌面**不透明地铺满，再按 α 叠面板 ——
    `α×菜单 + (1−α)×真桌面`，这才是字面意义的「仅不透明度提高」。

    样式与原菜单逐项对齐（规格见 design.md 4.10）：白底 `#FFFFFF`、1px 黑边、圆角 3px、内边距 4px、
    菜单项内边距 `8px 14px`、hover 浅蓝底 `#E6F1FB` + 深蓝字 `#0C447C`、分隔线 `#CBD5E1`
    （1px；左右各内缩 6px、上下各留 4px）、「切换」右侧一个小尖。

    最顶上「音量条」那一行仍然是**真的子控件** `_VolumeBar`（要能拖、能点喇叭）：静止时由它自己画，
    **动画期间**把它 `hide()`、改用 `render()` 画上去，动画一结束再显示回真控件
    （位置尺寸一模一样，看不出切换）。
"""

    TICK_MS = 100        # 二级弹窗宽限计时的检查步长
    # 2026-09-20 十七改：**二级占着鼠标时替一级自算 hover 的节拍**（≈一帧）。
    # 16ms 是为了跟手；窗口只有 155×224，一跳一次 `update()` 的开销可忽略（行没变就不重绘）。
    HOVER_MS = 16

    def __init__(self, content_w: int = MENU_CONTENT_W, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)          # hover 高亮：不按鼠标也要收到 mouseMoveEvent
        self._base_content_w = int(content_w)   # 内容区最小宽度（二级弹窗给 0 = 按文字自适应）
        self._content_w = int(content_w)
        self._panel_size = QSize(self._content_w + 2 * (VOL_MENU_PAD + MENU_BORDER_W), 0)
        self._rows = []                      # 行表（见 add_*）；每行都带一个 "rect"
        self._bar = None                     # 音量条子控件（"volume" 那一行）
        self._hover = -1                     # 鼠标停在哪一行（-1 = 不在任何一行上）
        self._pressed = -1                   # 按下时命中的行（松开要求同一行才触发）
        self._side = "right"                 # 贴贴图的哪一侧（十四改后只剩记录意义：不再影响几何）
        self._owner = None                   # 二级弹窗记着它是谁的二级（选中后要连一级一起关）
        self._sub = None                     # 二级弹窗（「切换」）
        self._sub_row = -1                   # 「切换」那一行的下标
        self._out_ms = 0                     # 鼠标既不在「切换」行、也不在二级弹窗内，已持续多久
        self._closing = False
        # 十四改：没有缩放了 —— `_progress` / `_scaling` 已删除，弹窗只有**不透明度**在动。
        self._opacity = 1.0                  # 整窗不透明度（淡入 0→1 / 淡出 1→0）
        self._backdrop = None                # 十改：抓来的「窗口底下那张桌面」（自制 save-bits，见 pop_up）
        # 十四改：右键重开用的回调（`PetWindow._menu()` 装）：收到新的**屏幕坐标**点击点，
        # 由它按 `menu_rect()` 重算位置再 `repop()`。为 None 时退化成「原地重新淡入」。
        self.reopen_at = None
        self._anim = None
        self._loop = None                    # `run()` 里那个事件循环
        self._poll = QTimer(self)            # 二级弹窗的宽限计时
        self._mask_key = None                # 上一帧 region 的键（一样就不必再 setMask）
        self._poll.setInterval(self.TICK_MS)
        self._poll.timeout.connect(self._tick)
        # 2026-09-20 十七改：二级一 `show()`，Qt 就把鼠标投给**二级**（`activePopupWidget()` 换人，
        # 实测），一级从此**收不到真的 `mouseMoveEvent` / press / release** —— 表现就是
        # 「二级在的时候，一级既不高亮、点了也不生效」。所以自己补一条路：
        #   * hover → 这张 16ms 的表（`_hover_tick()` 用 `QCursor.pos()` 反算）；
        #   * 点击 → `eventFilter` 里转发（`_forward_press()`：**按下即生效** + 关掉整套）。
        # 它**只在**「二级可见 && 一级不是活动 popup」时工作（`_sub_owns_mouse()`），一还权就自己停，
        # 所以不会和真的 `mouseMoveEvent` 抢 `_hover`。
        self._hover_poll = QTimer(self)
        self._hover_poll.setInterval(self.HOVER_MS)
        self._hover_poll.timeout.connect(self._hover_tick)
        self._swallow_release = False        # 转发过按下 → 把配对的抬起也吃掉，别漏给 Qt

    # ---- 内容（行）----
    def add_volume(self, bar) -> None:
        """最顶端那一行：音量条（真子控件）。"""
        bar.setParent(self)
        bar.ensurePolished()
        bar.show()
        self._bar = bar
        self._rows.append({"kind": "volume", "rect": QRect()})

    def add_separator(self) -> None:
        self._rows.append({"kind": "sep", "rect": QRect()})

    def add_item(self, text, on_trigger=None, checkable=False, checked=False,
                 enabled=True, submenu=None) -> None:
        self._rows.append({"kind": "item", "text": str(text), "trigger": on_trigger,
                           "checkable": bool(checkable), "checked": bool(checked),
                           "enabled": bool(enabled), "submenu": submenu, "rect": QRect()})
        if submenu is not None:
            if submenu.parent() is not None:
                submenu.setParent(None)      # 二级弹窗是长驻的独立顶层窗，不能跟着一级弹窗销毁
            submenu._owner = self
            self._sub = submenu
            self._sub_row = len(self._rows) - 1

    def clear_rows(self) -> None:
        """重填行（长驻的二级弹窗每次开菜单重填角色项时用）。"""
        self._rows = []
        self._bar = None
        self._sub = None
        self._sub_row = -1
        self._hover = -1
        self._pressed = -1

    def rows(self):
        """行表（只读；冒烟测试按它逐行断言）。"""
        return self._rows

    def row_text(self, index: int) -> str:
        row = self._rows[index]
        return row["text"] if row["kind"] == "item" else ""

    def row_rect(self, index: int) -> QRect:
        return QRect(self._rows[index]["rect"])

    def bar(self):
        return self._bar

    def submenu(self):
        return self._sub

    # ---- 排版 ----
    def _item_h(self) -> int:
        """菜单项行高 = 文字行高 + 上下各 8px（原 QSS `padding:8px 14px` 的效果）。"""
        return self.fontMetrics().height() + 2 * MENU_ITEM_PAD_Y

    def _width_need(self) -> int:
        """内容区宽度：至少 `_base_content_w`，再看每行文字要多宽。"""
        fm = self.fontMetrics()
        need = self._base_content_w
        for row in self._rows:
            if row["kind"] != "item":
                continue
            tail = MENU_ITEM_PAD_X
            if row["submenu"] is not None:
                tail += MENU_ARROW_DX + 4
            need = max(need, MENU_ITEM_TEXT_X + fm.horizontalAdvance(row["text"]) + tail)
        return need

    def _relayout(self) -> None:
        pad = VOL_MENU_PAD + MENU_BORDER_W
        self._content_w = self._width_need()
        y = pad
        for row in self._rows:
            if row["kind"] == "volume":
                h = MENU_ITEM_H
                if self._bar is not None:
                    self._bar.setGeometry(pad, y, self._content_w, h)
            elif row["kind"] == "sep":
                h = 2 * MENU_SEP_Y + 1
            else:
                h = self._item_h()
            row["rect"] = QRect(pad, y, self._content_w, h)
            y += h
        self._panel_size = QSize(self._content_w + 2 * pad, y + pad)
        # 十改：窗口尺寸**就是面板尺寸**（不再留 20px 动画余量）—— 用户口径「黑底高度要和菜单高度一致」。
        # 十四改：没有缩放 / 位移了，窗口 == 面板 == 终态，既不需要额外余量，也不会被窗口下沿裁掉。
        self.resize(self._panel_size)

    def sizeHint(self):  # noqa: N802 (Qt 命名)
        """**面板**尺寸（含内边距与 1px 边框；十改起 == 窗口尺寸，不再有底部动画余量）。

        上屏前就能算准 —— 版是自己排的，不靠 Qt 猜；`menu_rect()` 与冒烟测试都用这个尺寸。
        """
        self._relayout()
        return QSize(self._panel_size)

    def _panel_rect(self) -> QRect:
        """面板在窗口里的矩形 —— 命中判定用它（十改起窗口 == 面板，恒等于 `rect()`）。"""
        return QRect(0, 0, self._panel_size.width(), self._panel_size.height())

    def _panel_global_rect(self) -> QRect:
        """面板在**屏幕**上的矩形 —— 命中判定 / 宽限计时都用它（十改起窗口 == 面板）。"""
        return QRect(self.mapToGlobal(QPoint(0, 0)), self._panel_size)

    def _panel_hit(self, pos: QPoint) -> bool:
        """`pos`（屏幕坐标）落在自己或二级弹窗的**面板**上？—— 点在这块里都算「点在菜单上」。"""
        if self._panel_global_rect().contains(pos):
            return True
        sub = self._sub
        return (sub is not None and sub.isVisible()
                and sub._panel_global_rect().contains(pos))

    def _sub_hit(self, pos: QPoint) -> bool:
        """`pos` 落在「切换」那一行或二级弹窗面板上？—— 二级弹窗的宽限计时只看这两处。"""
        if 0 <= self._sub_row < len(self._rows):
            r = self._rows[self._sub_row]["rect"]
            if QRect(self.mapToGlobal(r.topLeft()), r.size()).contains(pos):
                return True
        sub = self._sub
        return (sub is not None and sub.isVisible()
                and sub._panel_global_rect().contains(pos))

    def _on_self_panel(self, pos: QPoint) -> bool:
        """`pos`（屏幕坐标）落在**一级自己**的面板上？—— 与 `_panel_hit()` 的区别是不含二级面板。

        十七改转发点击要用它：只有落在一级面板上的左键才归我们管，落在二级面板上的必须放行
        （那是二级自己的 hover / 选中）。
        """
        return self._panel_global_rect().contains(pos)

    def _sub_owns_mouse(self) -> bool:
        """二级弹窗是否正占着鼠标（= 一级收不到真的鼠标事件）。

        2026-09-20 十七改量到：一级与二级**都是 `Qt.Popup`**，而 Qt **只把鼠标投给「活动 popup」**——
        二级 `show()` 之后 `QApplication.activePopupWidget()` 就从一级切到二级，直到二级真的
        `hide()` 才还给一级（★**淡出那 `MENU_FADE_MS` 全程也算**：`closing=True`、`opacity 0.85 → 0.47`
        期间它仍是活动 popup，实测）。所以「一级收不到事件」的判据就是这一句。

        ⚠️ 这个判据同时是**自限开关**：将来 Qt 若改成「一级也能收到事件」，这里立刻返回假 →
        自算 hover 与点击转发一起失效，**不会**和真事件造成双动作。
        万一 `QApplication` 还没建（理论上不可能：菜单自己就是 Qt 应用里的窗口）就保守认为二级占着 ——
        那个方向上最坏也只是「多做一遍我们本来就要做的事」。
        """
        if self._sub is None or not self._sub.isVisible():
            return False
        app = QApplication.instance()
        if app is None:
            return True
        return app.activePopupWidget() is not self

    def _forward_press(self, pos: QPoint) -> bool:
        """十七改：二级占着鼠标时，一级面板上的左键由**我们自己**处理（用户口径：**按下即生效**）。

        为什么要转发：二级一开，一级收不到 press/release，点一级项只会走 Qt 的
        「点到活动 popup 之外」逻辑 —— **把二级关掉、那一项不触发**（用户报的「不能对一级菜单进行操作」）。

        返回 True = 把这一下吃掉（调用方还会把配对的抬起一起吃掉）。
        返回 False = 放行，交给 Qt（**只有音量条那一行**）。

        ⚠️ **音量条（`kind == "volume"`）故意不接管**：它是真子控件（`_VolumeBar`：滑块要能拖、
        喇叭要能点），接管一次按下就得把后续 move/release 也自己回灌给滑块，否则「拖音量」会坏 ——
        为这一条窄缝（≤ `TICK_MS` + `MENU_FADE_MS` ≈ 400ms）引入一套合成鼠标事件不划算。
        放行之后 Qt 会把二级收掉，用户再拖就是正常状态（见 devlog 第十七轮的「残留限制」）。
        """
        row = self._row_at(self.mapFromGlobal(pos))
        if row >= 0 and row == self._sub_row:
            # 「切换」那一行：二级本来就该开着 → 保持不动（别被这次点击关掉）
            self._show_submenu()
            return True
        item = self._rows[row] if row >= 0 else None
        if item is not None and item["kind"] == "volume":
            return False
        if item is not None and item["kind"] == "item" and item["enabled"]:
            cb = item.get("trigger")
            self.close_all()                 # 用户口径：直接生效**并关掉整套**
            if cb is not None:
                cb()
            return True
        # 分隔线 / 面板空白 / 禁用项：与「二级没开时」逐字一致 —— 什么都不做，只把这一下吃掉
        # （不放行是因为放行会落回 Qt 的 popup 逻辑，把二级提前 hide 掉、没有淡出）
        return True

    def eventFilter(self, obj, ev):  # noqa: N802 (Qt 命名)
        """`PetWindow._menu()` 开着菜单时把本窗装到 `QApplication` —— 在这里定菜单的键鼠语义。

        为什么要应用级拦：`Qt.Popup` 的默认处理是「点到外面 → 直接 hide()」—— 淡出没机会播，
        而且那一下还会被 Qt 的 popup 逻辑吞掉（用户实感就是「要在外面点两次才关得掉」）。
        这里在事件送到窗口之前先接住，把这一下**吃掉**并按下面三条规则处理（2026-09-19 十四改）：

        | 点在哪 | 什么键 | 行为 |
        |---|---|---|
        | 菜单里 / 菜单外 | **右键** | **重复弹出**（`_repop_at`：按新点击点重算位置、重新从 α=0 淡入）—— 用户口径「重复按右键则重复弹出而非起到**切换状态**的作用」 |
        | **菜单外** | 左键 | `close_all()` 整套淡出 —— 用户口径「**左键**菜单外的空间才会淡出」 |
        | 菜单里 | 左键 | **不拦**（返回 False），交给弹窗自己走 hover / 选中 |
        | 菜单外 | 其它键 | 吃掉、不动（别让它落到 Qt 的 popup 逻辑上被立刻 hide 掉） |

        ★**2026-09-20 十七改**：上表的「菜单里 | 左键 | 不拦」在**二级开着时是错的** ——
        Qt 这时把鼠标投给了二级，一级**根本收不到** press/release，那一下只会走 Qt 的
        「点到活动 popup 之外」逻辑（**把二级关掉、项不触发**）。所以二级占着鼠标
        （`_sub_owns_mouse()`）时补一张表：

        | 点在哪 | 什么键 | 行为 |
        |---|---|---|
        | **一级面板** | 左键 | **自己转发**（`_forward_press()`：**按下即生效** + `close_all()`），并把配对的抬起也吃掉 |
        | 一级的**音量条**那一行 | 左键 | **放行**（返回 False）—— 它是真子控件，要留给滑块自己拖（见 `_forward_press`） |
        | 一级面板的空白 / 分隔线 / 禁用项 | 左键 | 吃掉、什么都不做（与二级没开时逐字一致） |
        | 「切换」那一行 | 左键 | 保持二级开着（不关） |
        | 二级面板 / 菜单外 | 任意 | 与上表一致，不受影响 |

        （hover 那一路不走事件 —— 见 `_hover_tick()`：二级占着鼠标时用 16ms 的表自己算。）
        """
        if (ev.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
                and self.isVisible()):
            pos = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else QCursor.pos()
            btn = ev.button() if hasattr(ev, "button") else Qt.NoButton
            self._swallow_release = False      # 十七改：每次按下都重置配对标记
            if btn == Qt.RightButton:
                self._repop_at(pos)
                return True
            # 十七改：二级占着鼠标时，落在一级面板上的左键由我们自己转发 ——
            # 否则这一下只会被 Qt 的 popup 逻辑拿去「把二级关掉」，那一项不触发。
            if btn == Qt.LeftButton and self._sub_owns_mouse() and self._on_self_panel(pos):
                ate = self._forward_press(pos)
                self._swallow_release = ate     # 吃下了按下 → 抬起也一起吃掉，别漏给 Qt
                return ate
            if not self._panel_hit(pos):
                if btn == Qt.LeftButton:
                    if not self._closing:      # 正在淡出时再点一下：别重置动画，让它淡完
                        self.close_all()
                return True
        elif (ev.type() == QEvent.Type.MouseButtonRelease and self._swallow_release):
            # 十七改：只吃掉**我们转发过按下**的那一次抬起（`_swallow_release` 配对标记）——
            # 无差别吃抬起会把用户在**二级**上正常选角色那一下也吞掉。
            if (ev.button() if hasattr(ev, "button") else Qt.NoButton) == Qt.LeftButton:
                self._swallow_release = False
                return True
        return super().eventFilter(obj, ev)


    # ---- 弹出 / 收起 ----
    def _grab_backdrop(self, rect: QRect, prev_rect: QRect | None = None,
                       prev_pix=None):
        """抓一张「`rect` 处、弹窗**底下**的桌面」当底板（十改）。

        为什么要这个：`Qt.Popup` 在 Windows 上不是分层窗口，带 alpha 的像素会和**窗口自己的底色**混
        （实测 `opacity=0.5` 时面板是 `(127,127,127)` = 白混黑，而不是混桌面）。Qt 本来会给 popup 做
        save-bits（先把窗口下面那块屏幕存下来当底），这台机器上没生效，那就自己抓一张：淡入淡出混的
        就是真桌面，不会有黑，观感跟分层窗口一致。抓失败（离屏 / 权限）返回 `None` —— `paintEvent`
        里还有「整窗刷成菜单底色」的兜底，照样不会黑。

        ⚠️ **重复弹窗换位置**（十四改，右键重开）时必须传 `prev_rect` / `prev_pix`（= 我们自己现在正
        盖着的那个矩形 + **那时候抓到的干净底图**）：新矩形和旧矩形重叠的那块里，屏幕上是**我们自己**
        （菜单还开着），直接抓会把残影抓到手里 → 淡入时会看见「上一张菜单的鬼影」。所以抓完再用旧底图
        把重叠区**覆盖回去**（`CompositionMode_Source`）。抓取必须在 `setGeometry()` **之前**做 ——
        位置一挪，污染范围就变成整个新矩形、补不回来了。

        dpr 说明：`grabWindow()` 出来是**设备像素**（本机 1.5）且带 `devicePixelRatio`，`paintEvent` 里
        `drawPixmap(0, 0, …)` 正好按逻辑尺寸贴上。这里补丁要把坐标降成**纯设备像素**算（先把 dpr 置 1），
        最后再把 dpr 还原回去，否则贴出来会大 1.5 倍。
        """
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return None
        shot = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
        if shot.isNull():
            return None
        if prev_pix is None or prev_rect is None or prev_rect.isEmpty():
            return shot
        inter = QRect(rect).intersected(prev_rect)
        if inter.isEmpty():
            return shot                        # 换到完全不重叠的地方 → 本来就干净
        img = shot.toImage().convertToFormat(QImage.Format_RGBA8888)
        old = prev_pix.toImage().convertToFormat(QImage.Format_RGBA8888)
        dpr = (img.width() / float(rect.width())) if rect.width() else 1.0
        sx = int(round((inter.x() - prev_rect.x()) * old.width() / float(prev_rect.width())))
        sy = int(round((inter.y() - prev_rect.y()) * old.height() / float(prev_rect.height())))
        dx = int(round((inter.x() - rect.x()) * dpr))
        dy = int(round((inter.y() - rect.y()) * dpr))
        w = int(round(inter.width() * dpr))
        h = int(round(inter.height() * dpr))
        img.setDevicePixelRatio(1.0)           # 补丁阶段一律按设备像素算，别让 dpr 掺进来
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(QRect(dx, dy, w, h), old, QRect(sx, sy, w, h))
        p.end()
        out = QPixmap.fromImage(img)
        out.setDevicePixelRatio(dpr)           # 还原：`paintEvent` 里要按逻辑尺寸贴
        return out

    def pop_up(self, rect: QRect, side: str = "right", duration: int | None = None,
               prev_rect: QRect | None = None, prev_pix=None) -> None:
        """摆到 `rect`（终态）并开始**淡入**（2026-09-19 十四改：一级 / 二级同一条路）。

        用户口径（十四改）：「**不再进行大小上的变化**，只要求右键淡入（**仅不透明度提高**）」——
        所以这里只把 `_opacity` 0 → 1，`MENU_POP_MS`（一级）/ `SUBMENU_FADE_MS`（二级，由
        `duration=` 传进来）时长，painter 不加任何变换。八改～十三改那套「50% → 100% 缩放」的原点 /
        底边钉住 / `_progress` / `_apply_anim()` 全部删除（`smoke_pet` 有 reverse 断言钉着）。

        淡入的**底** = 抓来的真桌面（与淡出同一条路）→ 合成 = `α×菜单 + (1−α)×真桌面`，
        这才是字面意义的「仅不透明度提高」；抓不到时兜底铺 `MENU_BG`。

        `prev_rect` / `prev_pix` 只在**重复弹窗**（右键重开、位置变了）时传，用来把重叠区补干净
        （见 `_grab_backdrop` 的 ⚠️）。
        """
        self._side = side
        self._closing = False
        self._opacity = 0.0
        self._hover = -1
        self._pressed = -1
        self._relayout()
        # 在 show() / setGeometry() **之前**抓，别把弹窗自己（或它挪过去之后的身子）抓进去
        self._backdrop = self._grab_backdrop(rect, prev_rect, prev_pix)
        self.setGeometry(rect)                         # 十改：窗口 == 面板，不再多留 20px
        self._mask_key = None
        self._apply_mask()
        self._sync_children()
        self.show()
        self.repaint()               # 立刻按 α=0 画一帧：换位置重开时不会留「旧菜单停在新位置」的一帧
        self._animate(0.0, 1.0, self._on_in_frame, self._on_in_done,
                      MENU_POP_MS if duration is None else int(duration))

    def repop(self, rect: QRect, side: str = "right") -> None:
        """十四改：**重复弹出** —— 菜单已经开着时再按右键走这里。

        用户口径：「若重复按右键则**重复弹出**而非起到**切换状态**的作用」。所以不是把它当开关关掉，
        而是① 二级弹窗先收掉（回到初始态）、② 按新 `rect` 重新弹一次（不透明度重头 0 → 1）。
        底图沿用「旧矩形 + 旧底图」补重叠区（`pop_up` 的 `prev_*`），所以不会抓到自己。
        """
        self._hide_submenu(animated=False)
        self.pop_up(rect, side, prev_rect=QRect(self.geometry()), prev_pix=self._backdrop)

    def _repop_at(self, global_pos: QPoint) -> None:
        """右键落点 `global_pos` → 重新弹出。

        `reopen_at` 由 `PetWindow._menu()` 装上（它才有贴图 / 可用区，能按 `menu_rect()` 重算位置）；
        没装（离屏单测直接构造弹窗）就退化成「原地重新淡入」。
        """
        if self.reopen_at is not None:
            self.reopen_at(global_pos)
        else:
            self.repop(QRect(self.geometry()), self._side)

    def run(self) -> None:
        """模态地跑到弹窗关掉（替代 `QMenu.exec()`）。"""
        loop = QEventLoop(self)
        self._loop = loop
        loop.exec()
        self._loop = None

    def close_animated(self) -> None:
        """播 `MENU_FADE_MS` 的淡出，播完真的关掉（并退出 `run()` 的事件循环）。"""
        if self._closing:
            return
        self._closing = True
        self._hide_submenu(animated=False)
        self._animate(self._opacity, 0.0, self._on_in_frame, self._finish_close)
        # 兜底：万一动画没被事件循环驱动（窗口已经没了 / 被别的东西抢了），时间到了也一定关掉
        QTimer.singleShot(MENU_FADE_MS + 200, self._finish_close)

    def close_all(self) -> None:
        """把**当前这一套**菜单一起淡出关掉：二级弹窗（开着的话）先起淡出，再关自己。

        顺序要紧：`close_animated()` 里那次「立刻收二级」在 `_hide_submenu(animated=False)` 见到
        `sub._closing` 已经是 True 时会直接让开（见那里），所以得先给它起动画，别被拍灭。
        """
        sub = self._sub
        if sub is not None and sub.isVisible() and not sub._closing:
            sub.close_animated()
        self.close_animated()

    def cancel_close(self) -> None:
        """撤销一次正在播的淡出（鼠标又移回来了）—— 用户口径：回到规定范围内就不关。"""
        if not self._closing:
            return
        self._stop_anim()
        self._closing = False
        self._opacity = 1.0
        self._sync_children()
        self.update()

    def hide_now(self) -> None:
        """立刻收掉（不播淡出）：一级弹窗关掉时顺手收二级弹窗用。"""
        self._stop_anim()
        self._poll.stop()
        self._hide_submenu(animated=False)
        self._closing = False
        self._opacity = 0.0
        self._backdrop = None
        self._sync_children()
        self.hide()

    def _finish_close(self) -> None:
        if not self._closing:
            return
        self._stop_anim()
        self._poll.stop()
        self._hide_submenu(animated=False)
        self._opacity = 0.0
        self._backdrop = None
        self._sync_children()
        self.hide()
        self._closing = False                # 复位：不复位的话这一只淡出过一次就再也弹不出来
        # 十七改：一次点完之后菜单就没了，配对的抬起不一定还会来（窗口已经 hide）
        # ⇒ 把「吃掉抬起」的标记清掉，免得带到下一次开菜单。
        self._swallow_release = False
        if self._sub is not None:
            self._sub._owner = None          # 一级关了，二级别再回头找它
        loop, self._loop = self._loop, None
        if loop is not None:
            loop.quit()

    def _animate(self, a: float, b: float, on_value, on_done, duration=None) -> None:
        self._stop_anim()
        anim = QVariantAnimation(self)
        anim.setDuration(MENU_FADE_MS if duration is None else int(duration))
        anim.setStartValue(float(a))
        anim.setEndValue(float(b))
        # 淡入（b > a）用 OutQuad：0.1s 到 51%、0.2s 到 75% —— 前半程就把不透明度推上去，收尾柔和。
        # （六改起用过的 OutCubic 是 79% / 94%，一上来就太满，十一改换掉。）淡出仍用 Linear。
        anim.setEasingCurve(QEasingCurve.OutQuad if b > a else QEasingCurve.Linear)
        anim.valueChanged.connect(lambda v: on_value(float(v)))
        if on_done is not None:
            anim.finished.connect(on_done)
        self._anim = anim
        anim.start()

    def _stop_anim(self) -> None:
        anim, self._anim = self._anim, None
        if anim is not None:
            anim.stop()
            anim.deleteLater()

    def _on_in_frame(self, v: float) -> None:
        """淡入 / 淡出的**每一帧**（两个方向共用这一条）：只动不透明度。

        十四改起没有缩放，一级 / 二级、淡入 / 淡出都是同一套 —— 原先淡出还另有一份
        逐字相同的 `_on_out_frame`，已合并到这里（`_close_animated` 直接连它）。
        """
        self._opacity = v
        self._apply_mask()
        self._sync_children()
        self.update()

    def _on_in_done(self) -> None:
        """淡入收尾：不透明度到 1.0、`_animating()` 翻假 —— 顺手把**真控件**显示回来。

        ⚠️ 别省这一步。`_sync_children()` 只在动画的**帧**里被调，「动画结束」不是一个帧：末帧万一
        不是恰好 1.0（或动画被提前 `_stop_anim()` 掉），少了这一下音量条就会一直停在「动画期间」的
        `hide()` 状态，而 `paintEvent` 也不再 `render()` 它 —— 菜单弹完，最顶上那条音量条是**空白**的
        （十改时真机截图才发现；十一改合成一段后 `_on_in_frame` 的末帧通常已经覆盖了，但这一下是兜底，
        `smoke_pet` 有**结构层断言**钉着它，别删）。
        """
        self._opacity = 1.0
        self._sync_children()
        self.update()

    def _animating(self) -> bool:
        """十四改起只看**不透明度** —— 没有缩放，所以 `_progress` 这个通道连同它的判据一起删掉了。"""
        return self._opacity < 0.999

    def _sync_children(self) -> None:
        """动画期间把子控件藏起来（改由 `paintEvent` 用 `render()` 画上去），静止时再显示回真控件。"""
        if self._bar is not None:
            self._bar.setVisible(not self._animating())

    def _apply_mask(self) -> None:
        """把窗口 **region 裁成面板的圆角形状**（九改；十改后窗口 == 面板；十四改起不再逐帧变）。

        为什么非要裁：`Qt.Popup` 在 Windows 上**不是分层窗口**，`WA_TranslucentBackground` 不生效，
        凡是我们没画到的地方都会露窗口初始底色 —— 圆角外那一圈就是黑的。这里用窗口 region 顶上：
        只留面板那块，其余直接不属于本窗口。

        ⚠️ **十四改起不再逐帧变**：没有缩放了（用户口径「不再进行大小上的变化」），窗口几何从头到尾
        == 面板，所以 region 就是**面板的圆角矩形**，`pop_up()` 里算一次就够。八改～十三改那套
        「按当前缩放算 region、底边钉住、锚边跟 `side` 走」的算式随之删除 —— 十三改修的那个
        「region 只缩高度、右侧漏出一条底色」的 bug 是从根上没了的（不再有 scale 这个概念）。
        """
        w, h = self._panel_size.width(), self._panel_size.height()
        pad = MENU_MASK_PAD
        key = (w, h, pad)
        if key == self._mask_key:
            return
        self._mask_key = key
        radius = MENU_RADIUS + pad
        path = QPainterPath()
        path.addRoundedRect(QRectF(-pad, -pad, w + 2 * pad, h + 2 * pad), radius, radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def hideEvent(self, e):  # noqa: N802 (Qt 命名)
        self._poll.stop()
        loop, self._loop = self._loop, None
        if loop is not None:
            loop.quit()
        super().hideEvent(e)

    # ---- 画 ----
    def paintEvent(self, e):  # noqa: N802 (Qt 命名)
        p = QPainter(self)
        # `Qt.Popup` 在 Windows 上**不是分层窗口**（八改/九改实测）：我们画上去的像素**不和桌面合成**，
        # 而是和**窗口自己的底色**（实测 #1e1e1e）合成。所以必须自己先铺一层「窗口底下那张桌面」，
        # 半透明像素混的才是真桌面 —— 观感跟分层窗口一致。
        # 十四改起**淡入淡出共用这一层底**（用户口径：「只要求右键淡入（仅不透明度提高）」）：
        # 合成 = `α×菜单 + (1−α)×真桌面` = 字面意义的「只在不透明度上变化」，
        # 也顺手把十二改以来那层「底层」（先白后深）彻底去掉了。
        # ⚠️ 这一层**不跟着 `_opacity` 淡**：一淡就露出窗口底色（深色），收尾会闪一下黑。
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(MENU_BG))        # 兜底：抓不到桌面（离屏）时也不会是黑
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if self._backdrop is not None:
            p.drawPixmap(0, 0, self._backdrop)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing
                         | QPainter.SmoothPixmapTransform)
        p.setOpacity(self._opacity)          # 十四改：唯一的动画通道（没有缩放，`_apply_anim` 已删）
        self._paint_panel(p)
        self._paint_content(p)
        p.end()

    def _paint_panel(self, p: QPainter) -> None:
        """底板：菜单背景色 + 1px 黑边（与 `_paint_content` 同一段绘制 —— 十一改起不再是两段）。"""
        # 白底**画到面板外 1px**：窗口 region 就是面板的圆角形状，外扩这一圈保证 region 里每个像素都被
        # 不透明底色盖满（否则边缘那半像素会露窗口初始底色）；外扩部分在 region 外，看不见。
        w, h = float(self._panel_size.width()), float(self._panel_size.height())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(MENU_BG))
        p.drawRoundedRect(QRectF(-1.0, -1.0, w + 2.0, h + 2.0),
                          MENU_RADIUS + 1.0, MENU_RADIUS + 1.0)
        p.setPen(QPen(QColor(MENU_BORDER), MENU_BORDER_W))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), MENU_RADIUS, MENU_RADIUS)

    def _paint_content(self, p: QPainter) -> None:
        """内容：音量条（动画期间 `render()`）/ 分隔线 / 菜单项文字 / 勾选 / 小尖。"""
        for i, row in enumerate(self._rows):
            if row["kind"] == "volume":
                # 只有**动画期间**才替它画：那时它被 hide() 了，`render()` 走的是「当场重绘」
                # 这条路。静止时它自己画 —— 对可见控件再 `render()` 反而会去
                # 拷它的 backing store，拷出来是一块脏底色（实测是一块深灰）。
                if self._bar is not None and self._animating():
                    # ⚠️ **必须只画子控件**（`DrawChildren`）：`QWidget.render()` 默认还带
                    # `DrawWindowBackground` —— 会先按窗口调色板把整块刷成 `Window` 色，
                    # 而本弹窗调色板的 `Window` 实测是 `#1e1e1e`（深色）。于是动画期间
                    # 音量条那行是**黑底**，动画一结束改走正常绘制（`autoFillBackground=False`，
                    # 不刷背景）才变回菜单白 —— 就是用户报的「动画中音量条背景是黑的」。
                    self._bar.render(p, row["rect"].topLeft(), QRegion(),
                                     QWidget.RenderFlag.DrawChildren)
            elif row["kind"] == "sep":
                r = row["rect"]
                p.setPen(QPen(QColor(MENU_SEP), 1))
                p.drawLine(QPointF(r.x() + MENU_SEP_X, r.center().y() + 0.5),
                           QPointF(r.right() + 1 - MENU_SEP_X, r.center().y() + 0.5))
            else:
                self._paint_item(p, row, i)

    def _ink_of(self, row, selected: bool) -> QColor:
        if not row["enabled"]:
            ink = QColor(MENU_INK)
            ink.setAlpha(90)
            return ink
        return QColor(MENU_SEL_INK if selected else MENU_INK)

    def _paint_item(self, p: QPainter, row, index: int) -> None:
        r = row["rect"]
        selected = index == self._hover and row["enabled"]
        if selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(MENU_SEL_BG))
            p.drawRoundedRect(QRectF(r), MENU_RADIUS, MENU_RADIUS)
        ink = self._ink_of(row, selected)
        p.setPen(ink)
        p.drawText(QRectF(MENU_ITEM_TEXT_X, r.y(), r.width(), r.height()),
                   int(Qt.AlignLeft | Qt.AlignVCenter), row["text"])
        if row["checkable"] and row["checked"]:
            self._paint_check(p, r, ink)
        if row["submenu"] is not None:
            self._paint_arrow(p, r, ink)

    def _paint_check(self, p: QPainter, r: QRect, ink: QColor) -> None:
        """勾选标记：位置与大小照原 QMenu 实测（x 9.3 ~ 16）。"""
        cy = r.center().y() + 0.5
        pen = QPen(ink, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        path = QPainterPath(QPointF(MENU_CHECK_X + 1.0, cy + 0.5))
        path.lineTo(QPointF(MENU_CHECK_X + 3.5, cy + 3.0))
        path.lineTo(QPointF(MENU_CHECK_X + 8.0, cy - 4.0))
        p.drawPath(path)

    def _paint_arrow(self, p: QPainter, r: QRect, ink: QColor) -> None:
        """「切换」右侧那个小尖（照原 QMenu 的样子）。"""
        tip_x = r.right() + 1 - MENU_ITEM_PAD_X
        cy = r.center().y() + 0.5
        pen = QPen(ink, 1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        path = QPainterPath(QPointF(tip_x - MENU_ARROW_DX, cy - MENU_ARROW_DY))
        path.lineTo(QPointF(tip_x, cy))
        path.lineTo(QPointF(tip_x - MENU_ARROW_DX, cy + MENU_ARROW_DY))
        p.drawPath(path)

    # ---- 鼠标 / 键盘 ----
    def _row_at(self, pt: QPoint) -> int:
        for i, row in enumerate(self._rows):
            if row["rect"].contains(pt):
                return i
        return -1

    def _hover_tick(self) -> None:
        """十七改：二级占着鼠标时，**替一级自己算 hover**（一级收不到真的 `mouseMoveEvent`）。

        为什么需要：二级一 `show()`，Qt 就把鼠标投给二级（`activePopupWidget()` 换人，实测）⇒
        一级的 `mouseMoveEvent` 再也不来，`_hover` 永远停在旧值 ⇒ 用户实感「悬停没反应」。
        这条 16ms 的表用 `QCursor.pos()` 反算，`_hover` 一变就重绘（没变不重绘）。

        只在「二级可见 && 一级不是活动 popup」时工作：`_sub_owns_mouse()` 一假就**自己停表**，
        所以二级一收、或 Qt 改回真事件投递，都不会再和真的 `mouseMoveEvent` 抢 `_hover`。
        覆盖整段「二级可见」＝ 包括**淡出那 300ms**（那时它仍是活动 popup，实测），
        这正是用户最容易感知到「点了没反应」的一段。
        """
        if not self._sub_owns_mouse():
            self._hover_poll.stop()
            return
        row = self._row_at(self.mapFromGlobal(QCursor.pos()))
        if row != self._hover:
            self._hover = row
            self.update()

    def mouseMoveEvent(self, e):  # noqa: N802 (Qt 命名)
        row = self._row_at(e.position().toPoint())
        if row != self._hover:
            self._hover = row
            self.update()
        if row == self._sub_row:
            self._show_submenu()
        elif self._sub is not None and self._sub.isVisible():
            # 十三改：宽限 0 —— 光标还在一级弹窗里、但已经不在「切换」那一行 → 当场核一次、立刻淡出。
            # 不这么写就要等 `_poll` 那 100ms，而用户口径是「立刻」。
            self._check_submenu()
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):  # noqa: N802 (Qt 命名)
        if e.button() != Qt.LeftButton:
            # 十四改：**只有左键**才操作菜单项 —— 右键的语义是「重复弹出」（`eventFilter` 里已处理），
            # 落在这里的一律吃掉，免得不小心把某一项点中了。
            e.accept()
            return
        if self._closing:
            e.accept()
            return
        pt = e.position().toPoint()
        if not self._panel_rect().contains(pt):
            # 点到面板之外（十改起窗口 == 面板，面板外就是窗口外）：整套一起淡出关掉
            self.close_all()
            e.accept()
            return
        self._pressed = self._row_at(pt)
        e.accept()

    def mouseReleaseEvent(self, e):  # noqa: N802 (Qt 命名)
        if e.button() != Qt.LeftButton or self._closing:
            e.accept()
            return
        row = self._row_at(e.position().toPoint())
        if row >= 0 and row == self._pressed:
            item = self._rows[row]
            if item["kind"] == "item" and item["enabled"]:
                if item["submenu"] is not None:
                    self._show_submenu()          # 「切换」：点一下把二级弹窗叫出来
                else:
                    self._activate(row)
        self._pressed = -1
        e.accept()

    def keyPressEvent(self, e):  # noqa: N802 (Qt 命名)
        if e.key() == Qt.Key_Escape and not self._closing:
            self.close_animated()
            e.accept()
            return
        super().keyPressEvent(e)

    def _activate(self, index: int) -> None:
        cb = self._rows[index].get("trigger")
        self.close_animated()
        if cb is not None:
            cb()
        if self._owner is not None:              # 二级弹窗里选中某项 → 一级弹窗一起关
            self._owner.close_animated()

    # ---- 二级弹窗（「切换」）----
    def _show_submenu(self) -> None:
        sub = self._sub
        if sub is None:
            return
        if sub.isVisible():
            if sub._closing:                 # 正在淡出：撤销，别让「移回来」落空
                sub.cancel_close()
            self._poll.start()
            self._hover_poll.start()         # 十七改：二级占着鼠标 → 一级 hover 交给 16ms 的表
            return
        size = sub.sizeHint()
        anchor = self._rows[self._sub_row]["rect"]
        avail = self._avail_rect_for_sub()
        y = self.mapToGlobal(QPoint(0, anchor.y())).y()
        y = max(avail.y(), min(y, avail.y() + avail.height() - size.height()))
        frame = self.frameGeometry()
        x = frame.x() + frame.width()            # 紧贴一级弹窗右边框（边框挨边框，不留缝）
        side = "right"
        if x + size.width() > avail.x() + avail.width():
            x = frame.x() - size.width()         # 右边放不下 → 改贴左边，同样紧贴
            side = "left"
        x = max(avail.x(), min(x, avail.x() + avail.width() - size.width()))
        sub.pop_up(QRect(x, y, size.width(), size.height()), side, duration=SUBMENU_FADE_MS)
        self._out_ms = 0
        # 十七改起这张表跟 `_poll` 一起起落：二级一开就替一级算 hover
        # （判据仍在 `_hover_tick()` 里，二级真收掉时它自己会停）
        self._poll.start()
        self._hover_poll.start()

    def _hide_submenu(self, animated: bool = True) -> None:
        self._poll.stop()
        self._hover_poll.stop()              # 十七改：二级要收了 → 一级的 hover 表也一起停
        self._out_ms = 0
        sub = self._sub
        if sub is None or not sub.isVisible():
            return
        if not animated:
            if sub._closing:                     # 它自己正在淡出：别抢，让它播完
                return
            sub.hide_now()
            return
        sub.close_animated()

    def _avail_rect_for_sub(self) -> QRect:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _check_submenu(self, tick: bool = False) -> None:
        """核一次二级弹窗该不该收：鼠标不在「切换」行、也不在二级弹窗上 → 攒够 `SUBMENU_GRACE_MS` 就淡出。

        判据用**面板**矩形（`_sub_hit`），不是窗口 `frameGeometry()` —— 九改前窗口底下还多着 20px
        透明动画余量，鼠标停在那儿看着像「已经离开菜单」，却会把计时一直清零（九改前就是这毛病）。

        `SUBMENU_GRACE_MS` **十三改起是 0** → 「一离开就淡出」。调用点三处：
        ① `_poll` 每 `TICK_MS` 一拍（`tick=True`，只是**兜底** —— 鼠标直接移出屏幕、没有事件过来时那一条）；
        ② 一级弹窗 `mouseMoveEvent` 里光标已不在「切换」那一行；③ `leaveEvent`（一级 / 二级都走它）。
        ②③ 是十三改新增的**事件路径**，让「立刻」是字面意思，不必等那 100ms。
        """
        sub = self._sub
        if sub is None or not sub.isVisible():
            self._poll.stop()
            self._out_ms = 0
            return
        if self._sub_hit(QCursor.pos()):
            self._out_ms = 0
            if sub._closing:                 # 淡出途中又移回来了 → 撤销，不关
                sub.cancel_close()
            return
        if tick:                             # 只有定时器那一路才累加；事件路径是「当场核」
            self._out_ms += self.TICK_MS
        if self._out_ms >= SUBMENU_GRACE_MS:  # 0 时第一拍（乃至事件路径的 0）就成立
            self._out_ms = 0
            self._poll.stop()
            sub.close_animated()

    def _tick(self) -> None:
        """`_poll` 的槽 —— 兜底那一路（宽限 0 时它最坏也只晚 `TICK_MS`）。"""
        self._check_submenu(tick=True)

    def leaveEvent(self, e):  # noqa: N802 (Qt 命名)
        """十三改：光标离开本窗 → **立刻**核一次（宽限 0，不靠 100ms 那一拍）。

        一级弹窗核自己的二级；二级弹窗回头叫一级核（`_owner`）。两边都只信 `_sub_hit()`：
        「移进二级弹窗」或「移回一级弹窗」时它仍为真 → 不会误关；只有真的两边都不在才关。
        """
        if self._owner is not None:
            self._owner._check_submenu()
        else:
            self._check_submenu()
        super().leaveEvent(e)


class PetWindow(QWidget):
    def __init__(self, pet_dir: Path, width: int = 300, height: int = 500):
        super().__init__()
        self.pet_dir = Path(pet_dir)
        self._frames = {}
        self._state = "idle"
        self._index = 0
        self._play_frames = []  # 当前正在播放的帧列表（speaking 时是随机选中的一类）
        self._roles = []  # [(显示名, key)]
        self._current_key = None
        self._on_switch = lambda key: None
        self._on_home = lambda: None
        self._on_settings = lambda: None
        self._on_quit = lambda: None
        self._on_volume = lambda v: None
        self._on_mute = lambda m: None
        self._fallback_w = width
        self._fallback_h = height
        self._base_w = width
        self._base_h = height
        self._muted = False
        self._volume_before_mute = 0.5
        # 节能形态：`_power_save` = 当前是否处于节能态；`_ps_pixmap` = 那张扁平贴图（懒加载）。
        self._power_save = False
        self._ps_pixmap = None
        self._ps_scanned = False
        self._ps_anim = None
        self._ps_swapped = False
        self._ps_from_w = self._ps_from_h = 0
        self._ps_mid_w = self._ps_mid_h = 0
        self._ps_to_w = self._ps_to_h = 0
        self._ps_bottom = 0
        self._normal_w = width
        self._normal_h = height
        self._on_power_save = lambda on: None
        # 聊天气泡（静音模式 + 主界面关闭时才出现）：独立顶层窗，跟随贴图位置
        self._bubble = _PetBubble()
        # 状态提示气泡（贴图**正上方**的「待机中… / 休眠中 / 已唤醒」）：同样是独立顶层窗。
        # 它只看状态，不看静音模式、也不看主界面开不开（见 design.md 4.17）。
        self._toast = _PetToast()
        # 「显示聊天气泡」的检验开关（★2026-09-28：右键菜单那一行已**下架**，开关本身保留）：
        # 开着时气泡被**钉住**（`hide_bubble()` 空操作），用来不必先开静音模式 + 关主界面
        # 就能核对外观 / 高度 / 让位（design.md 4.10）。
        self._bubble_preview = False
        self._on_bubble_preview = lambda on: None

        # ---- patpat 模式（左键抚摸）----
        # 状态 + 叠加窗 + 音效。叠加窗是**独立顶层窗**（与气泡 / 状态提示同款）——
        # 节能态下那只手会高出贴图窗口的顶边，做子控件会被父窗裁掉（见 `_PatPatOverlay`）。
        self._patpat = False
        self._on_patpat = lambda on: None
        self._patpat_ov = _PatPatOverlay()
        # ★★两套音效、各连一个目录、**互不影响**（二十二改）：
        #   `_patpat_audio` → `voices/patpat/`（模式**开着**用，`if with_hand` 那支）；
        #   `_normal_pet_audio` → `voices/normal_pet/`（模式**关着**用，`elif not self._patpat` 那支）。
        # 两个**独立实例**（各自一份 `_cache` / `_player`）⇒ 播一套绝不碰另一套的素材。
        # 目录都由 main.py 注入 —— pet.py 不认识项目根。
        self._patpat_audio = PatPatSound()
        self._normal_pet_audio = PatPatSound()
        self._patpat_frames = ()
        self._patpat_scanned = False
        # 「抬起 → 下压 → 抬起」与「收窗」用**实例**定时器：`QTimer.singleShot()` 返回 None，取消不掉，
        # 而连点必须能把上一轮掐掉再重播。★`_patpat_swap_timer` 一轮里要**响两次**（见 `_patpat_step`）。
        self._patpat_step = 0          # 0=没在放 / 1=已显示抬起 / 2=已显示下压 / 3=已回到抬起
        self._patpat_swap_timer = QTimer(self)
        self._patpat_swap_timer.setSingleShot(True)
        self._patpat_swap_timer.timeout.connect(self._patpat_swap)
        self._patpat_end_timer = QTimer(self)
        self._patpat_end_timer.setSingleShot(True)
        self._patpat_end_timer.timeout.connect(self._patpat_hide)
        # 角色贴图的形变（十九改；二十改起**按形态分两套量**：站姿 35/每侧12、节能态 20/每侧8）：
        # 进度 0..1，由 `_patpat_sq_anim` 平滑驱动。
        # `_patpat_sq_base` = **形变前**的 (x, y, w, h)，还原时逐像素写回。
        self._patpat_sq = 0.0
        self._patpat_sq_anim = None
        self._patpat_sq_base = None
        # 左键「点击」与「拖动」的区分：按下记起点，位移超过 `PATPAT_CLICK_SLOP` 就判成拖动
        # （**拖动只挪位置、不形变** —— 少了这一条，每次拖完松手都会压一下）。
        self._press_pos = None
        self._press_moved = False

        # ---- 思考气泡（**第二款气泡**，2026-09-21）----
        # 非 patpat 模式单击贴图 → 除了形变 + `voices/normal_pet/`，旁边再依次淡入三帧
        # `assets/icon/thinking_0/1/2.png`（各 100ms）→ 停留 1s → 淡出，里面放一句随机内容。
        # 规格见 `app/thinking.py`。独立顶层窗；锚点走 `bubble_anchor`（**与聊天气泡同一个贴合点**）。
        self._thinking_ov = _ThinkingOverlay(anchor_of=self._thinking_anchor_of)
        self._thinking_pm = None          # 三帧 QPixmap（懒加载，缺素材 → `[]`）
        # 内容池（每轮随机抽一句）：由 `main.py` 用 `set_thinking_api()` 注入**当前 API**，
        # 桌宠据此判「第一类内容（余额 / 峰谷）显不显示」= 只有 deepseek 才显示。
        # ★2026-09-27 起第一类只剩 2 句：「今日 Token 用量」按用户要求**整项去掉**（显示不准）。
        self._thinking_api = None
        self._thinking_ov.set_content_provider(self._thinking_content)
        # 缩放比例（贴图显示宽 ÷ 原图宽，爱丽丝 0.5）：也用回调注入 —— 换角色 / 站姿↔节能态
        # 都会改比例，气泡每次来问都是最新的（见 `_ThinkingOverlay.set_scale_provider`）。
        self._thinking_ov.set_scale_provider(self._thinking_ratio)

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._label = QLabel(self)
        self._label.setScaledContents(True)
        self._label.setAlignment(Qt.AlignCenter)
        # 节能变形动画要改「贴图的不透明度」——挂在 label 上（而不是整个窗口），
        # 语义上就是用户说的「贴图不透明度降到 30%」。
        self._label_effect = QGraphicsOpacityEffect(self._label)
        self._label_effect.setOpacity(1.0)
        self._label.setGraphicsEffect(self._label_effect)

        self._timer = QTimer(self)
        self._timer.setInterval(160)
        self._timer.timeout.connect(self._tick)

        # ---- 置顶「入带」看门狗（见本模块顶部 PETS_TOP_BAND_MS 的取证说明）----
        # 只在**判据成立时**才 SetWindowPos —— 正常那 99.9% 的时间它是**零动作**，
        # 所以绝不会把贴图顶到自己的手 / 气泡上面（那套层级是按「谁后 show / raise_」定的）。
        self._top_band_timer = QTimer(self)
        self._top_band_timer.setInterval(PETS_TOP_BAND_MS)
        self._top_band_timer.timeout.connect(self._ensure_topmost_band)

        self._drag = None
        self._dragging = False
        # ---- 桌宠固定（2026-09-22）----
        # 开着 = **不能拖动**（`mouseMoveEvent` 直接返回）；★只锁「拖」—— 单击抚摸 / 思考气泡照旧。
        # 开关在「右键菜单」与「通用设置 → 桌宠调整」两处，两个入口都汇到 `set_locked()`。
        # ⚠️ 这里默认 **False**（= 可拖）：**真值由 main.py 按 cfg 注入**（cfg 里默认 True）。
        #   这样单测里 new 出来的 `PetWindow` 不注入也能照常拖动 —— 老用例（拖动 / 点击分界）不用动。
        self._locked = False
        self._on_lock = lambda on: None
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        # 音量：**值存在这里**（0.0~1.0），UI 在右键菜单最顶端那条音量条上 —— 那是每次开菜单
        # 现造的（见 `_build_menu`）。2026-09-19 起单击贴图不再弹出音量条。
        self._volume = 0.5
        self._bar = None            # 当前开着的菜单里那条音量条（菜单关掉即清）
        self._switch_menu = None    # 「切换」子菜单：**长驻一份**（淡入淡出 / 宽限计时都挂在它身上）
        self._menu_open = False    # 菜单正开着（防重入）：True 时再右键直接忽略

        self.set_state("idle")
        self._resize_to_frame()

    # ---- 置顶带（Windows） ----
    def _ensure_topmost_band(self, force: bool = False) -> bool:
        """把桌宠**真正推进置顶带**；返回是否动作了。

        ⚠️ 只在**判据成立**（`topmost_out_of_band`）或 `force` 时才动：
        无条件 `SetWindowPos(HWND_TOPMOST)` 会把贴图顶到**自己的手 / 气泡上面**，
        而「手盖在贴图之上」「气泡贴着贴图」是设计（见 `_PatPatOverlay.show_at`）。
        判据里排除掉 `WS_EX_TOOLWINDOW`，正是为了保护那几个兄弟窗不被误判成「压在头上」。

        `force=True` 用于**刚 `show()` 完**的那一拍：此刻窗口可能还没入带、z 链也还没稳定，
        直接推一次最省事（同机实测：推完上方可见窗立刻清空）。

        ⚠️ `not _HAS_WIN32` 那句**读的是模块级全局**（不是常量快照）—— 这样测试注入假 user32
        时把它一并改掉，就能把「判据 + 动作」这条链在离屏下整条跑通（2026-09-21 实测：
        这句拦在前面会让所有行动层断言变成「0 次调用」的假绿）。
        """
        if not _HAS_WIN32:
            return False
        hwnd = _hwnd_of(self)
        if not hwnd:
            return False
        if not force and not topmost_out_of_band(hwnd):
            return False
        return _win_set_topmost(hwnd)

    def ensure_topmost_band(self, force: bool = True) -> bool:
        """对外入口：把桌宠推进置顶带（`main.py` 在 `show()` 后补一次）。

        默认 `force=True` —— 调用方（启动流程）此刻并不关心它有没有掉带，
        只在「窗口刚显示出来」这个容易漏入带的时刻推一把。
        """
        return self._ensure_topmost_band(force=force)

    def showEvent(self, e):  # noqa: N802 (Qt 命名)
        """每次「真正显出来」都启动看门狗，并立刻兜一次（登录自启那条路最容易漏入带）。"""
        super().showEvent(e)
        if _HAS_WIN32:
            self._ensure_topmost_band(force=True)
            self._top_band_timer.start()

    # ---- 对外接口 ----
    def set_roles(self, roles):
        self._roles = list(roles)

    def set_current_role(self, key):
        self._current_key = key

    def set_thinking_api_provider(self, fn):
        """注入「当前 API」的**取值回调**（主程序传 `lambda: get_current_api(cfg)`）。

        第二款气泡据此判「第一类内容（余额 / 峰谷）显不显示」——
        用户口径「仅在使用的 api 为 deepseek 模型时会显示」，判据是 `app.stats.is_deepseek`。

        ★为什么要**回调**而不是记一份快照：切 API 的入口在设置界面里有好几处，靠「每切一次
        都记得通知桌宠」迟早漏一处，气泡就会拿着旧 API 的余额不放；这里每次要用时**现读**，
        天然不会过期。
        """
        self._thinking_api = fn or (lambda: None)

    def current_api(self):
        """此刻的 API 配置（经 `set_thinking_api_provider` 注入的回调拿）；拿不到 ⇒ `None`。"""
        fn = self._thinking_api
        if not callable(fn):
            return None
        try:
            return fn()
        except Exception:  # noqa: BLE001
            # 取值出错最多让第一类内容不显示，不能把「点一下贴图」整个带崩。
            return None

    def set_on_switch(self, cb):
        self._on_switch = cb or (lambda key: None)

    def set_on_home(self, cb):
        """右键菜单「主界面」的回调：打开主窗口并切到聊天界面。"""
        self._on_home = cb or (lambda: None)

    def set_on_settings(self, cb):
        """右键菜单「设置」的回调：打开主窗口并切到设置界面。"""
        self._on_settings = cb or (lambda: None)

    def set_on_quit(self, cb):
        self._on_quit = cb or (lambda: None)

    def set_on_volume(self, cb):
        """设置音量变化回调，参数为 0.0~1.0。"""
        self._on_volume = cb or (lambda v: None)

    def set_volume(self, v, muted=None):
        """设置音量（0.0~1.0），**不触发回调**；`muted` 给定时顺带把静音态也记下来。

        音量条控件是「每次开菜单现造」的，所以值存在 `self._volume` 里、造控件时按它初始化；
        菜单正开着的话顺手把那条也拨过去（**「通用设置 → 音量」那一行改音量走的就是这条路**，
        见 `main.py::on_volume_changed` → `win.sync_volume()`）。
        """
        self._volume = max(0.0, min(1.0, float(v)))
        if muted is not None:
            self._muted = bool(muted)
        bar = self._live_bar()
        if bar is not None:
            bar.sync(self._volume, muted=muted)

    def _live_bar(self):
        """当前菜单里那条音量条；菜单已销毁（C++ 对象没了）时返回 None 并清引用。"""
        bar = self._bar
        if bar is None:
            return None
        try:
            bar.isVisible()
        except RuntimeError:
            self._bar = None
            return None
        return bar

    def set_on_mute(self, cb):
        """设置静音状态变化回调，参数为 bool。"""
        self._on_mute = cb or (lambda m: None)

    def set_on_power_save(self, cb):
        """设置节能形态切换回调，参数为 bool（**真的发生切换时**才回调一次）。

        主程序用它落一条系统消息 —— 语音入口和右键菜单入口都会走到，所以提示不会漏、
        也不会重。
        """
        self._on_power_save = cb or (lambda on: None)

    def is_power_save(self) -> bool:
        """当前是否处于节能形态。"""
        return self._power_save

    def set_on_bubble_preview(self, cb):
        """设置「显示聊天气泡」（检验开关）的回调，参数为 bool。

        真正把气泡叫出来 / 收起来的是主程序（它才知道要写什么预览文字），
        这里只记状态 + 回调一次 —— 与节能形态同一套写法。
        """
        self._on_bubble_preview = cb or (lambda on: None)

    def set_bubble_preview(self, on: bool) -> bool:
        """把气泡钉住（检验用）：开着时 `hide_bubble()` 一律空操作。

        ⚠️ 顺序不能反：**先**置位、**后**回调 —— 关掉开关时主程序要在回调里调
        `hide_bubble()`，那一次必须能真的收起来（旗标已经是 False 了）。
        """
        on = bool(on)
        self._bubble_preview = on
        self._on_bubble_preview(on)
        return on

    def toggle_bubble_preview(self) -> bool:
        """反转检验开关（右键菜单点一下）。"""
        return self.set_bubble_preview(not self._bubble_preview)

    def is_bubble_preview(self) -> bool:
        """检验开关是否开着。"""
        return self._bubble_preview

    # ---- 桌宠固定（2026-09-22）----
    # 用户口径：① 通用设置「桌宠调整」里一个滑块，**默认打开固定**、开着时贴图**不能被拖动**，
    #   关掉后可拖（原来默认就是可拖）；② 右键菜单里也要能开关。两处都汇到 `set_locked()`。
    # ★只锁「拖动」：`mousePressEvent` 照常记起点、`mouseReleaseEvent` 照常判「点击」——
    #   抚摸（`_patpat_play`）与思考气泡一个都不受影响（用户口径只说「不会被拖动」）。

    def set_on_lock(self, cb):
        """设置「桌宠固定」切换回调，参数为 bool（**真的发生切换时**才回调一次）。

        与 `set_on_patpat` 同一套写法：主程序用它弹提示 + 同步设置页那一行 ——
        右键菜单与通用设置两个入口都会走到，所以提示不会漏、也不会重。
        """
        self._on_lock = cb or (lambda on: None)

    def is_locked(self) -> bool:
        """贴图当前是否被固定（= 不可拖动）。"""
        return self._locked

    def set_locked(self, on: bool) -> bool:
        """开 / 关「桌宠固定」。返回**是否真的发生了切换**。

        ★实现上就只是一个旗标：被锁的**只有 `mouseMoveEvent` 里那句 `self.move(...)`**。
        所以这里不用管「切换的一瞬间手正按着」—— 置位后下一次 `mouseMoveEvent` 起
        `move()` 就不走了，**连拖动中途锁上也是立刻生效**（不会拖到松手为止）。
        """
        on = bool(on)
        if on == self._locked:
            return False
        self._locked = on
        self._on_lock(on)
        return True

    def toggle_locked(self) -> bool:
        """反转「桌宠固定」（右键菜单点一下）。"""
        return self.set_locked(not self._locked)

    # ---- patpat 模式（左键摸贴图）----
    # 规格见 design.md 4.10 / docs/02 §18。**与其他模式互不冲突**（用户口径「可直接打开」）：
    # 节能态、静音模式、睡下，全都能同时开着 —— 它不改角色贴图的尺寸（形变只在点的那一下、到点弹回）。
    # ★二十一改：模式开了 = 「叠那只手 + 出声」；模式关着单击**照样形变**（只是没有手、没有声音）。

    def set_on_patpat(self, cb):
        """设置 patpat 模式切换回调，参数为 bool（**真的发生切换时**才回调一次）。

        主程序用它弹提示（「patpat模式启动 / 关闭」）并同步设置页那一行 ——
        右键菜单与通用设置两个入口都会走到，所以提示不会漏、也不会重。
        """
        self._on_patpat = cb or (lambda on: None)

    def is_patpat(self) -> bool:
        """patpat 模式是否开着。"""
        return self._patpat

    def set_patpat(self, on: bool) -> bool:
        """开 / 关 patpat 模式。返回**是否真的发生了切换**。

        ⚠️ 与节能形态（`set_power_save`）不同：这里**不做素材门禁** ——
        `pet/patpat/` 缺图时也照样能把模式打开（用户口径「可直接打开」）。
        ★（二十一改）缺图**不等于「点下去没反应」**：贴图照常形变，只是不叠手、不出声
        （见 `_patpat_play` 的返回值语义）。
        """
        on = bool(on)
        if on == self._patpat:
            return False
        self._patpat = on
        if not on:
            self._patpat_stop()             # 关掉时把正在播的那一轮收干净（别留一只手在屏幕上）
        # 第二款气泡只在**非 patpat 模式**出现 ⇒ 模式一开一关都把它收掉。
        # ⚠️（二十三改）这一句原先在 `_patpat_stop()` 里，但那个方法**每次单击**都会走
        #   （`_patpat_play` 第一句），会把连点该续着的气泡误收掉 ⇒ 挪到真正的出口来。
        self._thinking_dismiss()
        self._on_patpat(on)
        return True

    def toggle_patpat(self) -> bool:
        """反转 patpat 模式（右键菜单点一下）。"""
        return self.set_patpat(not self._patpat)

    def set_patpat_sound_dir(self, sound_dir):
        """摸摸音效的目录（`voices/patpat`）。路径由 main.py 注入 —— pet.py 不认识项目根。"""
        self._patpat_audio.set_dir(sound_dir)

    def set_normal_pet_sound_dir(self, sound_dir):
        """★（二十二改）非模式单击音效的目录（`voices/normal_pet`）。

        与 `set_patpat_sound_dir` **各管各的**（两个独立实例）—— 两套音效互不影响、相互独立。
        """
        self._normal_pet_audio.set_dir(sound_dir)

    def _patpat_pixmaps(self):
        """`(抬起, 下压)` 两张 QPixmap；该角色旁边没有 `patpat/` 或缺一张 → `()`。

        只扫一次（换角色时在 `set_pet_dir` 里作废重扫）。
        """
        if not self._patpat_scanned:
            self._patpat_scanned = True
            pair = patpat_frames(self.pet_dir)
            loaded = []
            for path in (pair or ()):
                pm = QPixmap(str(path))
                if not pm.isNull():
                    loaded.append(pm)
            # 两张都得在：只算一张的话「抬起 → 下压」就无从谈起（当成没有素材）
            self._patpat_frames = tuple(loaded) if len(loaded) == 2 else ()
        return self._patpat_frames

    def _patpat_scale(self) -> float:
        """叠加图的缩放系数 = **角色贴图自己那一个**（显示宽 ÷ 原图宽）。

        用户口径「两张图片的显示尺寸与角色一样要进行比例缩放」：
        爱丽丝原图 300×500 → 显示 150×250 ⇒ ×0.5 → 摸摸图 300×225 显示 **150×113**；
        艾莲原图 256×256 → 显示 250×250 ⇒ ×0.9766 → **293×220**。

        ⚠️ 用**站姿**宽（`_normal_w`）而不是当前窗口宽：节能态下贴图被压扁，
        但那只手不该跟着缩小 —— 用户给节能态单独指定了落点，说明手的大小是**不变的**。
        """
        for state in STATES:
            frames = [pm for pm in self._frames_for(state) if not pm.isNull()]
            if frames and frames[0].width() > 0:
                return (self._normal_w or self._fallback_w) / frames[0].width()
        return 1.0

    def _patpat_size(self):
        """叠加图的显示尺寸 `(w, h)`；没素材 → `None`。"""
        pms = self._patpat_pixmaps()
        if not pms:
            return None
        return patpat_size(pms[0].width(), pms[0].height(), self._patpat_scale())

    def _patpat_scaled(self, pm, size):
        """按算好的尺寸缩放这一帧。

        ⚠️ 用 `IgnoreAspectRatio` 是**故意**的：`size` 本来就是按原图比例算出来的，
        再让 Qt 「保持比例」反而会在取整后多留 1px 透明边（真机 `scaled()` 的取整方向与
        我们算的不一定一致）。
        """
        return pm.scaled(size[0], size[1], Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def _patpat_play(self):
        """左键「点一下」贴图：抬起 50ms → 下压 150ms → 抬起 100ms → 收手；贴图形变**全程都跑**。

        返回值 = 这一轮**有没有叠那只手**：

        - patpat 模式**开着**且找得到手图 → `True`（额外叠手 + 随机播一段 `voices/patpat/`）；
        - patpat 模式**开着**但缺手图 → `False`（**只有贴图形变**，不叠手、**一声不出**）；
        - patpat 模式**关着** → `False`（**只有贴图形变**，不叠手，但 ★二十二改起播
          `voices/normal_pet/`）。

        ★★（二十一改）**各情形共用同一条时间线**：三帧时长、形变量、80ms 平滑、底边基准、
        还原精度**完全一致** —— 「模式」这一档开关只管「有没有那只手 + **出哪一套声**」，
        **不管形变**（用户口径见 design.md 4.10 / docs/02 §18.8）。

        ★★（二十二改）**一次点击只响一套、两套互不影响**：
        - `if with_hand:` → 播 `_patpat_audio`（`voices/patpat/`）；
        - `elif not self._patpat:` → 播 `_normal_pet_audio`（`voices/normal_pet/`）。
        ⚠️★必须是 **`elif not self._patpat`** 而**不是 `else`**：模式**开着但缺手图**时
        （`with_hand=False` 且 `self._patpat=True`）要**两套都不播**（用户口径「缺手图时不播」）。
        两个分支互斥，所以永远不可能一次响两套；两套是**两个独立实例**，也不会互相顶班。

        ★**连点 = 截断重播**（二十改明确成硬承诺）：第一句就是 `_patpat_stop()` ——
        它把上一轮的**两个定时器、贴图形变、那只手、以及正在播的那一套音效**一起掐掉，然后才
        重新显示第 0 帧、重新定位、重新播音效、重新起表。所以连点既**不会叠加**，
        也不会残留「上一轮的影子」或「上一段音效还在响」；**不开模式时同样截断**
        （形变不会叠起来、也不会残留半途几何）。

        ⚠️★**这里不许加「模式没开就早退」的门**（二十改那版是 `if not self._patpat: return False`）——
        加了就等于把「不开模式也要形变」这条需求整个吞掉。`smoke_pet` 有反向断言盯着。
        ⚠️★（二十二改）下面那处 `elif not self._patpat:` 只是**选音效**、**里面没有 `return`**，
        跟上面那条反向断言（查的是「以 `_patpat` 为条件的**提前返回**」）不冲突。
        """
        self._patpat_stop()
        hand = self._patpat_pixmaps() if self._patpat else []
        size = self._patpat_size() if hand else None
        with_hand = size is not None
        if with_hand:
            self._patpat_ov.set_pixmap(self._patpat_scaled(hand[PATPAT_SEQ[0]], size),
                                       index=PATPAT_SEQ[0])
            self._patpat_ov.show_at(
                patpat_pos(self._sprite_rect(), size[0], size[1], power_save=self._power_save)
            )
            self._patpat_audio.play()
            # 手亮着这几百毫秒里贴图被它压着，掉带的窗口随便一激活就把「手+贴图」一起盖住 ——
            # 这段时间把置顶看门狗调快一点（收手后再调回去）。
            self._top_band_timer.setInterval(PETS_TOP_BAND_PS_MS)
        elif not self._patpat:
            # ★二十二改：非模式单击 → 只响 `voices/normal_pet/` 那一套（没有素材时 play() 自己空转）。
            #   模式**开着但缺手图**这里不会进（`self._patpat` 为真）⇒ 那一档**一声不出**。
            self._normal_pet_audio.play()
        # ⚠️ 两个定时器**必须无条件起表**（形变靠它们推；被 `if` 包起来就没形变了）——
        #    结构层有「必须在函数体顶层」的断言钉着。
        self._patpat_step = 1
        self._patpat_swap_timer.start(PATPAT_F1_MS)
        self._patpat_end_timer.start(PATPAT_TOTAL_MS)
        return with_hand

    def _patpat_frame(self, idx: int):
        """把那只手切到第 `idx` 张图；**没有手在显示时是空操作**。

        ★（二十一改）为什么单独抽出来：换帧原本和形变推进挤在 `_patpat_swap()` 里，
        而那一版开头有一道 `not self._patpat_ov.is_shown()` 的守卫 —— 它会把
        「不开模式单击」的形变**一并挡掉**。现在守卫只留在这个「只管换帧」的小函数里，
        形变推进在 `_patpat_swap()` 里无条件执行。
        """
        if not self._patpat_ov.is_shown():
            return
        pms = self._patpat_pixmaps()
        size = self._patpat_size()
        if len(pms) < 2 or size is None:
            return
        self._patpat_ov.set_pixmap(self._patpat_scaled(pms[idx], size), index=idx)

    def _patpat_swap(self):
        """到点换帧（一轮里要响**两次**，靠 `_patpat_step` 认第几次）。

        - 第一次（`PATPAT_F1_MS`）：抬起 → 下压，**同时角色贴图开始压扁**；
        - 第二次（再过 `PATPAT_F2_MS`）：下压 → 抬起（第 3 帧还是第 1 张图），形变弹回原形。

        ⚠️★（二十一改）**两道推进在这里无条件执行**，换帧才走 `_patpat_frame()` ——
        这个函数里**不许**出现 `is_shown`（否则「不开模式单击」没有形变）。
        """
        if self._patpat_step == 1:
            self._patpat_frame(PATPAT_SEQ[1])
            self._patpat_squash_to(1.0)          # 压下去 —— 只在「下压」这一帧
            self._patpat_step = 2
            self._patpat_swap_timer.start(PATPAT_F2_MS)
        else:
            self._patpat_frame(PATPAT_SEQ[2])
            self._patpat_squash_to(0.0)          # 抬起来 → 弹回原形
            self._patpat_step = 3

    def _patpat_hide(self):
        """到点收手：收掉那只手，并把贴图的形变**兜底还原**一次。

        正常时序里形变在「抬起」帧（t=200 起 80ms）就弹完了；这里再还一次是兜底 ——
        万一以后把帧时长调得比形变还短，也不会留下一个永久被压扁的贴图。
        """
        self._patpat_step = 0
        self._patpat_squash_restore()
        self._patpat_ov.hide_now()
        self._top_band_timer.setInterval(PETS_TOP_BAND_MS)   # 手收了，看门狗回到常规节奏

    def _patpat_stop(self):
        """掐掉正在播的那一轮：停两个定时器 + **还原形变** + 收手 + **停音效（两套都停）**。

        ★（二十二改）这里把 **`_patpat_audio` 与 `_normal_pet_audio` 都 `stop()`** —— 它不是
        「择一停」，而是「停下时**把声音全收干净**」，保证任何时刻**最多只有一套在响**
        （连点 / 关模式 / 换角色 / 关窗 / 切节能全走这一条）。
        """
        self._patpat_swap_timer.stop()
        self._patpat_end_timer.stop()
        self._patpat_step = 0
        self._patpat_squash_restore()
        self._patpat_ov.hide_now()
        self._top_band_timer.setInterval(PETS_TOP_BAND_MS)   # 手收了，看门狗回到常规节奏
        self._patpat_audio.stop()
        self._normal_pet_audio.stop()
        # ⚠️★**这里不再收思考气泡**（二十三改）：本方法在**每次单击**时都会被
        #   `_patpat_play()` 第一句调到，而思考气泡在连点时要**续着**（每 2s 换一句、
        #   不重放淡入）—— 在这儿收掉会让它闪一下、还逼着下一句立刻重新淡入。
        #   真正要收的四个出口（关模式 / 换角色 / 切节能 / 关窗）各自显式调
        #   `_thinking_dismiss()`，安全网没丢。

    def _thinking_dismiss(self):
        """收掉思考气泡 —— **只在真正的出口**调（单击那条链路故意不调，见 `_patpat_stop`）。"""
        thinking = getattr(self, "_thinking_ov", None)
        if thinking is not None:
            thinking.hide_now()

    # ---- 思考气泡（**第二款气泡**，2026-09-21）----

    def _thinking_anchor_of(self, side, face):
        """思考气泡的锚点 —— **直接复用聊天气泡那一个** `bubble_anchor`。

        用户口径「整体位置与第一款一样」：`_ThinkingOverlay` 只认这个回调，
        所以「同一个贴合点」是**构造上就成立**的，不是在 `app/thinking.py` 里再抄一遍 5/7。
        """
        r = self._sprite_rect()
        return bubble_anchor(r.x(), r.y(), r.width(), r.height(), side=side, face=face)

    def _thinking_pixmaps(self):
        """三帧思考气泡图（`assets/icon/thinking_0/1/2.png`）—— 懒加载，只扫一次。

        缺任何一张 → `[]`（这一击只当没这回事，形变与音效照旧 —— 与「缺手图就不叠手」同口径）。
        """
        if self._thinking_pm is None:
            loaded = []
            for path in thinking_frames(ICONS):
                pm = QPixmap(str(path))
                if not pm.isNull():
                    loaded.append(pm)
            # 三张都得在：少一张就没法「依次淡入」了（当成没有素材）。
            self._thinking_pm = loaded if len(loaded) == len(THINKING_OFFSETS) else []
        return self._thinking_pm

    def _thinking_play(self):
        """非 patpat 模式单击贴图 → 叫出思考气泡；返回这一轮**有没有真的弹**。

        ⚠️★**守卫是「patpat 模式开着就整个不弹」**（用户口径「在**非 patpat 模式**时单击角色贴图」）——
        模式开着那一支由那只手负责，两者不叠。
        ⚠️★**缺素材也返回 `False`**，但**不**影响形变与音效（它们在 `_patpat_play` 里，各管各的）。
        ★是「新一轮」还是「连点续命」由 `_ThinkingOverlay.play()` 按**时间**判 —— 这里不判
        （单击链路上 `_patpat_play()` 并不再收气泡了，但判据仍是时间，见那边的说明）。
        """
        if self._patpat:
            return False
        pms = self._thinking_pixmaps()
        if not pms:
            return False
        # 顺手后台刷一次余额：缓存（60s）没过期时什么都不做，所以连点也不会反复打网络。
        stats.prefetch_balance(self.current_api())
        return self._thinking_ov.play(pms, self._sprite_rect(), self._avail_rect())

    def _thinking_content(self):
        """第二款气泡的内容池（每轮随机抽一句）。

        池子 = **第一类**（余额 / 峰谷倒计时；★只有当前 API 是 deepseek 才进）
             + **第二类**（本角色台词）。组装口径全在 `app/thinking.py::thinking_pool`。

        ★2026-09-27（用户要求「今日 token 用量显示不准确 ⇒ 直接去掉这项显示」）：
        这里**不再**取 `stats.today_tokens()`、也**不再**往 `thinking_pool` 传 `tokens`
        （那个形参已随「今日 Token 用量」整项删除）。
        ⚠️ 底层累计**照旧在跑**（`ai.py` 的用量出口 → `stats.record_tokens`，`main.py` 接线没动），
        删的只是**显示**。
        """
        api = self.current_api()
        deep = stats.is_deepseek(api)
        balance = state = left = None
        if deep:
            balance = stats.cached_balance(api)
            state, left = stats.peak_state()
        return thinking_pool(deepseek=deep, balance=balance,
                             state=state, seconds_left=left, role_key=self._current_key)

    def _sprite_natural_w(self):
        """当前形态贴图的**原图宽**（像素）—— 即素材文件里那张图的宽。

        ⚠️ 走「当前形态」：站姿取状态目录里第一张的原宽，节能态取那张扁平图的原宽。
        ★**不用 `_sprite_rect().width()`**（那是在屏显示宽，是分子不是分母）。
        """
        if self._power_save:
            pm = self._power_save_pixmap()
            if pm is not None and not pm.isNull() and pm.width() > 0:
                return pm.width()
        for state in STATES:
            frames = [pm for pm in self._frames_for(state) if not pm.isNull()]
            if frames and frames[0].width() > 0:
                return frames[0].width()
        return 0

    def _sprite_display_w(self):
        """当前形态贴图在屏幕上的**显示宽**（像素）—— 缩放比例的分子。

        ★用 `_normal_size()` / `_power_save_size()` 这两个**标称**尺寸，而**不是** `_sprite_rect()`：
        拍贴图（patpat 形变）会让窗口实时宽高乱跳，拿实时值当分母的话气泡会跟着抖。
        """
        if self._power_save:
            ps = self._power_save_size()
            if ps is not None:
                return ps[0]
        return self._normal_size()[0]

    def _thinking_ratio(self):
        """思考气泡的等比缩放系数 = **贴图显示宽 ÷ 贴图原图宽**。

        用户口径（2026-09-21 二轮）「贴图在文件夹内的原图尺寸为 300×500，但实际贴图在桌面的
        显示尺寸是按一定比例缩放后再显示的，所以我要求新添加的第二款聊天气泡也要按相同的比例
        进行尺寸的缩小后显示」⇒ 爱丽丝 150/300 = **0.5**（站姿与节能态同值：节能图 300×200、
        显示宽仍是 150）。取不到原宽（0）⇒ 回 1.0，绝不 0。
        """
        nat = self._sprite_natural_w()
        if nat <= 0:
            return 1.0
        return self._sprite_display_w() / float(nat)

    def _thinking_follow(self):
        """贴图动了：思考气泡跟着走（空间不够会翻到另一侧）。"""
        thinking = getattr(self, "_thinking_ov", None)
        if thinking is None or not thinking.is_shown():
            return
        thinking.follow(self._sprite_rect(), self._avail_rect())

    # ---- 思考气泡的探针（冒烟测试用）----

    def is_thinking_shown(self) -> bool:
        """此刻思考气泡是不是正显示着。"""
        return self._thinking_ov.is_shown()

    def thinking_side(self):
        """思考气泡当前朝向（`left` / `right`）。"""
        return self._thinking_ov.side()

    def thinking_face(self):
        """思考气泡当前的尾巴朝向（`down` = 挂在她上边 / `up` = 挂在下边）。"""
        return self._thinking_ov.face()

    def thinking_frame_opacities(self):
        """三帧各自的不透明度（逐帧淡入看这个）。"""
        return self._thinking_ov.frame_opacities()

    def thinking_opacity(self) -> float:
        """整条气泡的不透明度（只有最后的整体淡出会动它）。"""
        return self._thinking_ov.opacity()

    def thinking_scale(self) -> float:
        """气泡当前的等比缩放系数 = 贴图显示宽 ÷ 原图宽（爱丽丝 0.5）。"""
        return self._thinking_ov.scale()

    def thinking_text_opacity(self) -> float:
        """思考气泡里**文字自己**的不透明度（0 = 字还看不见；气泡淡出时它不动）。"""
        return self._thinking_ov.text_opacity()

    def thinking_text_fading(self) -> bool:
        """文字的 100ms 淡入此刻在不在跑（探针）。"""
        return self._thinking_ov.text_fading()

    def thinking_content(self):
        """气泡里此刻那一句 `(kind, 标签, 数值)`；没弹 / 不显示文字 ⇒ `None`。"""
        return self._thinking_ov.content()

    def thinking_switch_running(self) -> bool:
        """连点换句定时器在不在跑（2s 节拍那条）。"""
        return self._thinking_ov.switch_running()

    # ---- 角色贴图的形变（十九改；二十改起分两套量）----

    def _patpat_squash_to(self, target):
        """把贴图的形变进度**平滑**推到 `target`（0 = 原形 / 1 = 压到底）。

        `duration = PATPAT_SQUASH_MS × |目标 − 当前|` —— 半途反向时用的也是「还差多远」，
        所以「压下去」和「弹回来」两段手感一致。
        """
        target = 1.0 if target else 0.0
        span = abs(target - self._patpat_sq)
        if span <= 0:
            return
        if self._patpat_sq_base is None:
            # 第一次形变：把**当时**的几何存下来（还原时逐像素写回）
            self._patpat_sq_base = (self.x(), self.y(), self._base_w, self._base_h)
        if self._patpat_sq_anim is not None:
            self._patpat_sq_anim.stop()
            self._patpat_sq_anim = None
        anim = QVariantAnimation(self)
        anim.setStartValue(float(self._patpat_sq))
        anim.setEndValue(target)
        anim.setDuration(max(1, int(round(PATPAT_SQUASH_MS * span))))
        anim.setEasingCurve(QEasingCurve.OutQuad)
        anim.valueChanged.connect(lambda v: self._patpat_apply_squash(float(v)))
        anim.finished.connect(self._patpat_squash_done)
        self._patpat_sq_anim = anim
        anim.start()

    def _patpat_apply_squash(self, progress):
        """把形变进度画到窗口上：**底边不动**、水平中心不动，只把高度压短、宽度撑宽。

        ⚠️ 靠 `QLabel.setScaledContents(True)` 拉伸 —— 所以**只要改窗口 + 标签的几何**，图就跟着变形
        （节能态的「原地压扁」走的是同一条路，见 `_ps_set_geometry()`）。
        """
        base = self._patpat_sq_base
        if base is None:
            return
        bx, by, bw, bh = base
        # ★按形态取量（二十改）：站姿 35/每侧12、节能态 20/每侧8。`_patpat_sq_base` 记的是**当前形态**的几何，
        # 所以这里必须用**同一个形态**去算 —— 否则「压下去多少」和「顶边下沉多少」会对不上，手会跳。
        w, h = patpat_squash_size(bw, bh, progress, power_save=self._power_save)
        self._patpat_sq = float(progress)
        self.setFixedSize(w, h)
        self.move(bx - (w - bw) // 2, by + bh - h)      # 水平中心不动 + 底边钉住
        self._label.setGeometry(0, 0, w, h)
        self._sync_bubble()

    def _patpat_squash_done(self):
        """形变动画跑完：清掉动画句柄；已经弹回原形的话连基准也一起清掉。"""
        self._patpat_sq_anim = None
        if self._patpat_sq <= 0.0:
            self._patpat_sq_base = None

    def _patpat_squash_restore(self):
        """立刻把形变收干净（停动画 + 逐像素还原几何）。

        连点重播 / 关模式 / 换角色 / 关窗 / 到点收手都走这里 —— 少还一次，贴图就永久变形了。
        """
        if self._patpat_sq_anim is not None:
            self._patpat_sq_anim.stop()
            self._patpat_sq_anim = None
        base = self._patpat_sq_base
        self._patpat_sq = 0.0
        self._patpat_sq_base = None
        if base is None:
            return
        bx, by, bw, bh = base
        self.setFixedSize(bw, bh)
        self.move(bx, by)
        self._label.setGeometry(0, 0, bw, bh)
        self._sync_bubble()

    def _patpat_follow(self):
        """贴图动了 / 变形了：那只手跟着走（只看模式与当前贴图矩形，与别的模式无关）。

        ⚠️ 形变期间**用「无形变」的贴图矩形算落点**，再单独给 y 加上下沉量 —— 否则
        `sprite.x()` 会跟着窗口左边界左移（站姿 12px / 节能态 8px），手就**横着挪一下**了（用户口径
        「除高度随着下层贴图往下降之外不要有其他改变」）。
        """
        if not self._patpat_ov.is_shown():
            return
        size = self._patpat_size()
        if size is None:
            return
        rect = self._sprite_rect()
        drop = 0
        if self._patpat_sq > 0 and self._patpat_sq_base is not None:
            bx, by, bw, bh = self._patpat_sq_base
            rect = QRect(bx, by, bw, bh)
            drop = patpat_squash_drop(self._patpat_sq, power_save=self._power_save)
        pos = patpat_pos(rect, size[0], size[1], power_save=self._power_save)
        self._patpat_ov.move_to((pos[0], pos[1] + drop))

    def is_patpat_playing(self) -> bool:
        """此刻**那只手**是不是正显示着（冒烟测试用）。

        ⚠️（二十一改）**它只回答「有没有手」**：不开模式单击时形变照跑，但这里恒 `False`。
        要问「此刻是不是正被点着」请看 `patpat_step()` / `patpat_squash_progress()`。
        """
        return self._patpat_ov.is_shown()

    def patpat_overlay_pixmap(self) -> QPixmap:
        """此刻那只手画的是哪一帧（抬起 / 下压），冒烟测试用。"""
        return self._patpat_ov.pixmap()

    def patpat_overlay_index(self) -> int:
        """此刻是第几帧（`0` = 抬起、`1` = 下压、`-1` = 还没放过）—— 冒烟测试用。"""
        return self._patpat_ov.frame_index()

    def patpat_step(self) -> int:
        """一轮走到第几步（0=没在放 / 1=抬起 / 2=下压 / 3=又回到抬起）。

        ⚠️ 帧序号认不出第 1 帧和第 3 帧（**同一张图**），要区分这一步只能看它。
        ★（二十一改）它**与模式无关**：不开模式单击时照样置位 —— 所以
        `patpat_step() != 0` 就是「**此刻正在被点 / 被摸**」，第二款聊天气泡将来用这个联动。
        """
        return self._patpat_step

    def patpat_squash_progress(self) -> float:
        """当前形变进度（0=原形 / 1=压到底）—— 冒烟测试用，也是气泡联动的口子。"""
        return float(self._patpat_sq)

    # ---- 聊天气泡（出现条件由 main.show_pet_bubble 判定，这里只管画）----

    def show_bubble(self, text) -> bool:
        """在这一轮回复开始时把气泡叫出来，内容是这句中文全文。空文本不显示。"""
        text = str(text or "").strip()
        if not text:
            return False
        self._bubble.show_text(text, self._sprite_rect(), self._avail_rect())
        return True

    def hide_bubble(self):
        """淡出气泡（当前没显示时是空操作）。

        **检验开关开着时这里是空操作** —— 那个开关的语义就是「把气泡钉住」：
        main.py 里有 6 个自动收起点全都调它，拦在这一道就不用改六处、也不会漏改一处。
        """
        if self._bubble_preview:
            return
        self._bubble.hide_animated()

    def is_bubble_visible(self) -> bool:
        """气泡是否正在显示（淡出过程中仍算显示）。"""
        return self._bubble.is_shown()

    # ---- 状态提示气泡（贴图正上方：待机中… / 休眠中 / 已唤醒 …）----

    def set_state_toast(self, text, *, dots: bool = False):
        """挂一条状态提示：`待机中`（**带点 = 常驻**，一直挂着）/ `休眠中`（**瞬态**，2s 后淡出）；
        `text` 为空 = 收起。

        「待机中」之所以常驻：关掉主界面、又是节能形态（贴图不换帧）时，抬眼就能看出她在等你下指令；
        `休眠中` 只是一次状态播报，报完就走（design.md 4.17）。
        """
        self._toast.set_state(text, dots=dots)
        self._toast.follow(self._sprite_rect(), self._avail_rect())   # 第一次挂上时贴图位置还没告诉过它

    def clear_state_toast(self):
        """收起常驻状态提示（她开始答话 / 离开「等待指令」时）。"""
        self._toast.clear_state()

    def flash_toast(self, text, ms=None):
        """弹一条**事件**提示（`已唤醒` / `已进入静音模式` …）：**淡入结束后**停留 ms 再淡出。

        事件是**盖在**状态提示上的那一层 —— 淡出后自动露出底下的「待机中…」（不需要排队）。
        """
        self._toast.follow(self._sprite_rect(), self._avail_rect())
        self._toast.flash(text, ms)

    def is_toast_visible(self) -> bool:
        """状态提示是否正在显示（淡出过程中仍算显示）。"""
        return self._toast.is_shown()

    @property
    def toast_text(self) -> str:
        """当前**画出来**的那条文本（事件优先于状态）。"""
        return self._toast.shown_text

    @property
    def toast_state_text(self) -> str:
        return self._toast.state_text

    @property
    def toast_flash_text(self) -> str:
        return self._toast.flash_text

    @property
    def toast_dots(self) -> int:
        """常驻状态后面现在挂着几个点（0~3）。"""
        return self._toast.dots_n

    def _sprite_rect(self) -> QRect:
        """贴图在屏幕上的矩形。

        取 `_label` 的 geometry，而不是 `_base_w/_base_h`：节能变形期间窗口每帧都在变高，
        `_base_*` 要到动画中点才更新，只有 `_label` 的 geometry 每一帧都是当前值。
        """
        g = self._label.geometry()
        return QRect(self.x() + g.x(), self.y() + g.y(), g.width(), g.height())

    def _avail_rect(self) -> QRect:
        """桌宠所在屏幕的可用区域（气泡左右 / 上下翻转的判定依据）。"""
        scr = self.screen()
        return scr.availableGeometry() if scr is not None else QRect()

    def _sync_bubble(self):
        """贴图动了 -> 气泡 / 状态提示 / patpat 那只手 / 思考气泡都跟着动（空间不够还会翻到另一侧）。

        `__init__` 早期就会收到 resize/move，那时它们还没建（也可能还没接上屏幕）。
        """
        bubble = getattr(self, "_bubble", None)
        if bubble is not None:
            bubble.follow(self._sprite_rect(), self._avail_rect())
        toast = getattr(self, "_toast", None)
        if toast is not None:
            toast.follow(self._sprite_rect(), self._avail_rect())
        patpat = getattr(self, "_patpat_ov", None)
        if patpat is not None and patpat.is_shown():
            self._patpat_follow()
        thinking = getattr(self, "_thinking_ov", None)
        if thinking is not None and thinking.is_shown():
            self._thinking_follow()

    def moveEvent(self, e):
        super().moveEvent(e)
        self._sync_bubble()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_bubble()

    def closeEvent(self, e):
        self._top_band_timer.stop()        # 关掉就别再抢置顶了（它只会白白早唤醒一个正被销毁的窗口）
        # 气泡 / 状态提示 / patpat 那只手 / 思考气泡都是**独立顶层窗**：实测它们不会跟着桌宠一起关
        # （父窗 close / deleteLater 都不带走），所以退出流程里必须显式收掉，
        # 否则会在桌面上留一个孤儿窗。
        self._patpat_stop()
        self._thinking_ov.hide_now()
        self._patpat_ov.close()
        self._bubble.close()
        self._toast.close()
        self._thinking_ov.close()
        super().closeEvent(e)

    # ---- 音量 / 静音（2026-09-19：UI 在右键菜单里，值在 `self._volume`）----
    def _on_bar_volume(self, value):
        """菜单里那条音量条被拖动 → 记下新值并回调主程序（**音量变化的唯一出口**）。"""
        self._volume = max(0.0, min(1.0, float(value)))
        self._on_volume(self._volume)

    def _on_bar_mute(self, muted: bool):
        """菜单里点了喇叭 / 拖动滑块自动解除静音 → 记下状态并回调主程序。

        旧实现里「拖动滑块自动解除静音」是 pet 自己接的（`_on_slider_changed`）；
        现在这条由 `_VolumeBar` 自己完成配色恢复，再把结果报回来 —— 状态仍只有一份（`self._muted`）。
        """
        self._muted = bool(muted)
        self._on_mute(self._muted)

    def set_pet_dir(self, pet_dir: Path):
        self.pet_dir = Path(pet_dir)
        self._frames = {}
        # 节能贴图按角色缓存 → 换角色必须重扫
        self._ps_pixmap = None
        self._ps_scanned = False
        # patpat 那只手也在角色目录**旁边** → 换角色同样要重扫（并把手收掉，别留上一个角色的）
        self._patpat_stop()
        # 第二款气泡的台词是**按角色分表**的，而且内容池要用新角色的 key ⇒ 换角色也收掉它。
        self._thinking_dismiss()
        self._patpat_frames = ()
        self._patpat_scanned = False
        if self._ps_anim is not None:      # 变形动画途中换角色：直接停下，别让它改新角色的尺寸
            self._ps_anim.stop()
            self._ps_anim = None
        # 新角色没有节能贴图（如 Ellen）→ 安静地退出节能，免得卡在一张不属于它的图上
        if self._power_save and self._power_save_pixmap() is None:
            self._power_save = False
        self._label_effect.setOpacity(1.0)
        self.set_state(self._state)
        self._resize_to_frame()
        if self._power_save:
            pm = self._power_save_pixmap()
            if pm is not None:
                self._label.setPixmap(pm)

    # ---- 帧加载与播放 ----
    @staticmethod
    def _is_power_save_file(f: Path) -> bool:
        """带 `_节能` 标记的贴图是**节能形态专用图**，不进普通帧循环。"""
        return POWER_SAVE_MARK in f.stem

    def _files_in(self, state) -> list:
        """某个状态目录下的贴图（已剔掉节能形态专用图）。"""
        d = self.pet_dir / state
        if not d.exists():
            return []
        return [
            f for f in (sorted(d.glob("*.png")) + sorted(d.glob("*.jpg")) + sorted(d.glob("*.jpeg")))
            if not self._is_power_save_file(f)
        ]

    def _frames_for(self, state):
        if state not in self._frames:
            self._frames[state] = [QPixmap(str(f)) for f in self._files_in(state)]
        return self._frames[state]

    def _speaking_groups(self) -> dict:
        """speaking 状态按文件名前缀分组（如 爱丽丝_正常对话_0.png → 爱丽丝_正常对话）。"""
        groups: dict[str, list[QPixmap]] = {}
        for f in self._files_in("speaking"):
            key = re.sub(r"_\d+$", "", f.stem)  # 去掉末尾 _数字 得到分类名
            groups.setdefault(key, []).append(QPixmap(str(f)))
        return groups

    def _random_speaking_frames(self) -> list:
        """随机选一类 speaking 表情；若全是单帧（占位图）则合并为一组循环。"""
        groups = self._speaking_groups()
        multi = [(k, v) for k, v in groups.items() if len(v) > 1]
        if multi:
            return random.choice(multi)[1]
        singles = [v[0] for v in groups.values() if v]
        return singles

    def _power_save_pixmap(self):
        """**节能形态**那张贴图：先看 `idle/`，没有就扫其余状态目录；只扫一次。

        返回 `QPixmap`，该角色没有这张图时返回 `None`（此时不进节能形态）。
        """
        if not self._ps_scanned:
            self._ps_scanned = True
            dirs = [self.pet_dir / "idle"] + [self.pet_dir / s for s in STATES if s != "idle"]
            for d in dirs:
                if not d.exists():
                    continue
                cand = [
                    f for f in (sorted(d.glob("*.png")) + sorted(d.glob("*.jpg"))
                                + sorted(d.glob("*.jpeg")))
                    if self._is_power_save_file(f)
                ]
                if cand:
                    self._ps_pixmap = QPixmap(str(cand[0]))
                    break
        return self._ps_pixmap

    def _normal_size(self):
        """**站姿**的显示尺寸：高度钉 `DISPLAY_HEIGHT`，宽度按原图比例。"""
        for state in STATES:
            frames = [pm for pm in self._frames_for(state) if not pm.isNull()]
            if frames:
                nat_w, nat_h = frames[0].width(), frames[0].height()
                if nat_h > 0:
                    return max(1, round(nat_w * DISPLAY_HEIGHT / nat_h)), DISPLAY_HEIGHT
                return nat_w, nat_h
        return self._fallback_w, self._fallback_h

    def _power_save_size(self):
        """**节能形态**的显示尺寸：**宽度与站姿相同**，高度按它自己的比例（所以明显更扁）。

        用户要求「原贴图高度被逐渐压短至节能贴图的高度」—— 节能图 300×200、站姿 300×500，
        宽度不变 → 高度 250 压到 100。宽度不变也保证了横向占地不扩大（节能的本意是少挡视线）。
        """
        pm = self._power_save_pixmap()
        if pm is None or pm.isNull() or pm.width() <= 0:
            return None
        w = self._normal_w or self._fallback_w
        return w, max(1, round(w * pm.height() / pm.width()))

    def _current_frame(self):
        """当前该显示的那一帧（节能形态退出时用它换回去）。"""
        if self._play_frames:
            return self._play_frames[self._index % len(self._play_frames)]
        return QPixmap()

    def _resize_to_frame(self):
        """锁定显示尺寸：普通形态按站姿算；节能形态用那张扁平图自己的尺寸。"""
        self._normal_w, self._normal_h = self._normal_size()
        ps = self._power_save_size()
        if self._power_save and ps is not None:
            w, h = ps
        else:
            w, h = self._normal_w, self._normal_h
        self._base_w, self._base_h = w, h
        self._label.setGeometry(0, 0, w, h)
        self._apply_window_size()

    def _apply_window_size(self):
        """窗口尺寸 == 贴图尺寸（**音量条搬进菜单后，这里只剩这一条职责**）。

        2026-09-19 前它还要在小人下方给音量条让出 10+22+6px 的高度；现在不用了 ——
        贴图以外的空间一律不占（气泡 / 状态提示都是独立顶层窗）。
        """
        self.setFixedSize(self._base_w, self._base_h)

    def set_state(self, state):
        state = state if state in STATES else "idle"
        self._state = state
        self._index = 0
        # speaking 每次进入随机选一类表情；其他状态用全部帧
        if state == "speaking":
            self._play_frames = self._random_speaking_frames()
        else:
            self._play_frames = self._frames_for(state)
        if self._power_save:
            # 节能形态是**静态**的：只记住该播哪套帧（退出节能时从这里恢复），
            # 贴图与帧动画一律不动 —— 否则一说话就跳回站姿，节能白做。
            self._timer.stop()
            return
        if self._play_frames:
            self._label.setPixmap(self._play_frames[0])
            # 拖动期间不启动动画，等释放后恢复
            if not self._dragging:
                self._timer.start()
        else:
            self._timer.stop()
            self._label.clear()

    # ---- 节能形态 ----

    def set_power_save(self, on: bool, animate: bool = True) -> bool:
        """进入 / 退出节能形态。返回**是否真的发生了切换**。

        用户指定的动画（整体 `POWER_SAVE_MS`，前后各一半）：
        - **进入**：站姿高度逐渐压短到节能图的高度（300×500→宽度不变→250→100），
          同时不透明度 100%→30%；降到 30% 时换成节能图，再从 30% 升回 100%。
        - **退出**：反过来 —— 先淡到 30%、换回站姿，再一边拉高一边淡回 100%。
        整个过程**底边不动**（原地压扁，而不是往上缩）。
        """
        on = bool(on)
        if on == self._power_save:
            return False
        if on and self._power_save_pixmap() is None:
            return False                      # 该角色没有节能贴图 → 保持原样
        # ★patpat 的形变与节能变形**都改窗口几何**，同时跑会互相覆盖 ——
        # 先把它收掉（几何还原到「切节能之前」），再让节能动画从那儿开始。
        self._patpat_stop()
        # 进 / 出节能态贴图尺寸变了，第二款气泡的缩放要重来 ⇒ 当场收掉（下次单击按新尺寸弹）。
        self._thinking_dismiss()
        self._power_save = on
        self._ps_swapped = False
        self._ps_from_w, self._ps_from_h = self._base_w, self._base_h
        ps = self._power_save_size()
        if on:
            self._ps_mid_w, self._ps_mid_h = ps
            self._ps_to_w, self._ps_to_h = ps
        else:
            self._ps_mid_w, self._ps_mid_h = self._base_w, self._base_h   # 此刻基准 = 节能尺寸
            self._ps_to_w, self._ps_to_h = self._normal_w, self._normal_h
        self._ps_bottom = self.y() + self.height()
        self._timer.stop()                    # 变形期间冻结帧动画
        if self._ps_anim is not None:
            self._ps_anim.stop()
            self._ps_anim = None
        if animate:
            anim = QVariantAnimation(self)
            anim.setDuration(POWER_SAVE_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.valueChanged.connect(self._ps_apply)
            anim.finished.connect(self._ps_finished)
            anim.start()
            self._ps_anim = anim              # 保持引用防 GC
        else:
            self._ps_apply(1.0)
            self._ps_finished()
        self._on_power_save(self._power_save)
        return True

    def toggle_power_save(self) -> bool:
        return self.set_power_save(not self._power_save)

    def _ps_apply(self, value):
        """变形动画的每一帧：压扁 / 拉高 + 淡出 / 淡入，中点换贴图。

        两个方向可以共用一套算式：交换点的高度恒为**节能图的高度**（`_ps_mid_h`）——
        进入时它是「压短的终点」，退出时它就是起点（还没开始拉高）。
        """
        p = max(0.0, min(1.0, float(value)))
        swap = POWER_SAVE_SWAP_OPACITY
        if p <= 0.5:
            u = p / 0.5
            h = round(self._ps_from_h + (self._ps_mid_h - self._ps_from_h) * u)
            opacity = 1.0 + (swap - 1.0) * u
        else:
            self._ps_swap_if_needed()
            v = (p - 0.5) / 0.5
            h = round(self._ps_mid_h + (self._ps_to_h - self._ps_mid_h) * v)
            opacity = swap + (1.0 - swap) * v
        if p >= 1.0:
            self._ps_swap_if_needed()
            h = self._ps_to_h
            opacity = 1.0
        self._ps_set_geometry(self._ps_from_w, h)
        self._label_effect.setOpacity(opacity)

    def _ps_set_geometry(self, w, h):
        """按目标尺寸摆好贴图，并让窗口**底边停在原处**（原地压扁）。"""
        w, h = max(1, int(w)), max(1, int(h))
        self.setFixedSize(w, h)
        self.move(self.x(), self._ps_bottom - h)
        self._label.setGeometry(0, 0, w, h)
        # 贴图的 geometry 是**在** setFixedSize / move **之后**才写的 —— 那两个事件里同步出去的
        # 气泡位置用的还是旧图（实测：锚点会按站姿高度算，贴着 250 而不是当前的 100）。补一次。
        self._sync_bubble()

    def _ps_swap_if_needed(self):
        """不透明度降到 30% 的那一刻换贴图，并把窗口基准尺寸切到新形态。"""
        if self._ps_swapped:
            return
        self._ps_swapped = True
        self._base_w, self._base_h = self._ps_mid_w, self._ps_mid_h
        if self._power_save:
            pm = self._power_save_pixmap()
            if pm is not None:
                self._label.setPixmap(pm)
        else:
            self._label.setPixmap(self._current_frame())

    def _ps_finished(self):
        """变形结束：落到终态尺寸，恢复帧动画（节能形态不播帧）。"""
        self._ps_anim = None
        self._base_w, self._base_h = self._ps_to_w, self._ps_to_h
        self._ps_set_geometry(self._base_w, self._base_h)
        self._label_effect.setOpacity(1.0)
        if self._power_save or not self._play_frames:
            return
        self._index = 0
        self._label.setPixmap(self._play_frames[0])
        if not self._dragging:
            self._timer.start()

    def _tick(self):
        frames = self._play_frames
        if not frames:
            return
        self._index = (self._index + 1) % len(frames)
        self._label.setPixmap(frames[self._index])

    # ---- 鼠标 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # ★「桌宠固定」时**这些照记不误** —— 锁只掐「挪位置」（见 `mouseMoveEvent`），
            #   不掐「这一次到底算点击还是拖动」；否则在锁定的贴图上拖一下，松手会被
            #   当成「点击」⇒ 莫名其妙摸一下头。
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            # 「按下」先记起点：松手时要靠它区分**点击**（patpat 抚摸）与**拖动**（只挪位置）
            self._press_pos = e.globalPosition().toPoint()
            self._press_moved = False
            # 拖动期间暂停帧动画，避免动画重绘干扰拖动。★固定着根本拖不动 ⇒ 也别把动画冻住。
            if not self._locked:
                self._dragging = True
                self._timer.stop()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            pos = e.globalPosition().toPoint()
            if self._press_pos is not None and not self._press_moved:
                d = pos - self._press_pos
                if abs(d.x()) + abs(d.y()) > PATPAT_CLICK_SLOP:
                    self._press_moved = True
            # ★★桌宠固定（2026-09-22）：**唯一**被锁住的就是这一句「挪位置」——
            #    手还按着、上面的位移判据照常算完，只是不动。★别把整块 early-return 掉：
            #    那样 `_press_moved` 永远是 False，松手就被当成「点击」⇒ 在锁定的贴图上
            #    拖一下会摸一下头（用户没要这个）。
            if not self._locked:
                self.move(pos - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        # **2026-09-19：单击贴图不再弹出音量条**（用户口径，那条交互已去掉）——
        # 这里只收尾拖动、恢复帧动画。
        # **2026-09-20 十七改（patpat 模式）**：没有位移的「点击」走 `_patpat_play()`；
        # 拖动过的不算 —— 否则每次挪完位置松手都会压一下。
        # ★**二十一改：这一句**无条件**调（不再先问模式）** —— 模式只管「叠不叠手 / 出不出声」，
        # 形变与模式无关（用户口径「不打开模式时也能单击让贴图形变」）。
        clicked = self._press_pos is not None and not self._press_moved
        self._press_pos = None
        self._press_moved = False
        self._drag = None
        self._dragging = False
        # 释放后恢复帧动画（若当前状态有动画；节能形态是静态的，不恢复）
        if self._play_frames and not self._power_save:
            self._timer.start()
        if clicked:
            self._patpat_play()
            # ★思考气泡（第二款气泡）：**非 patpat 模式**才弹，跟在形变与音效之后。
            #   ⚠️（二十三改）顺序**仍然**必须排在这里（有断言盯着），但语义变了：
            #   `_patpat_play` 已经**不再**顺手收掉思考气泡，所以连点能把它**续**下去 ——
            #   「新一轮 / 连点」由 `_ThinkingOverlay.play()` 按**时间**判，不看点击次数。
            self._thinking_play()
        e.accept()

    def _build_switch_menu(self) -> _MenuPopup:
        """「切换」二级弹窗：**长驻一份**（`self._switch_menu`），每次开菜单重填角色项。

        为什么长驻：它的淡入淡出动画与宽限计时都挂在这一只窗口上 —— 每次开菜单新建一只的话，
        上一次的淡出就落在已经销毁的窗口上了。行表每次用 `clear_rows()` 重填。
        """
        sub = self._switch_menu
        if sub is None:
            sub = _MenuPopup(content_w=0)     # 二级弹窗按角色名自适应宽度
            self._switch_menu = sub
        sub.clear_rows()
        for name, key in self._roles:
            # ★艾莲暂不可切换（2026-09-28，用户拍板：贴图未做完）⇒ 灰掉 + 点不动。
            #   `_MenuPopup` 天生支持 `enabled=False`：`_ink_of()` 把字色降到 alpha 90、
            #   `_paint_item()` 的 selected 判据带 `and row["enabled"]`（不 hover 高亮）、
            #   点击分支 `if ... and item["enabled"]:` 直接跳过（点了没反应）。
            #   ★唯一真值 = `config.SWITCHABLE_ROLES`（不在这儿写死角色名）；见 docs/02 §24。
            sub.add_item(name, checkable=True, checked=(key == self._current_key),
                         enabled=is_role_switchable(key),
                         on_trigger=lambda k=key: self._on_switch(k))
        return sub

    def _build_menu(self) -> _MenuPopup:
        """构造右键弹窗（**只构造，不弹**）。

        与 `MainWindow._build_pencil_menu()` 同一套作法：`run()` 是模态阻塞的，拆开后冒烟测试才能
        拿到弹窗逐行断言。自上而下：**音量条 → 分隔线 → 切换 → 分隔线 → 节能模式 → patpat模式 →
        桌宠固定 → 主界面 / 设置 / 退出**（十七改前是「节能模式 → 显示聊天气泡」，
        2026-09-20 在节能模式下面插了「patpat模式」，2026-09-22 又在它下面插了「桌宠固定」——
        三个都是「模式 / 行为」类开关，排在一起。★2026-09-28：检验用的「显示聊天气泡」**下架**
        （用户口径：实际使用时不需要，它只用来核对气泡显示与样式）—— 代码留着，要用时解注即可）。

        ⚠️ **宽度一律用 `MENU_CONTENT_W`，与本角色的贴图无关**（2026-09-19 十六改）：
        原先两处都写 `self._base_w - MENU_NARROW`，而 `_base_w` 是按贴图宽高比推的（高度钉 250）——
        爱丽丝 150 → 菜单 155，艾莲 250 → 菜单 255，于是「切角色菜单就变宽」（用户报的）。
        用户口径「将菜单尺寸统一成当前右键爱丽丝贴图弹出的菜单」⇒ 钉成常量的那一档。
        ⚠️ **别在这儿写回 `self._base_w`**：冒烟测试有 AST 反向断言盯着（写回去就红）。
        """
        menu = _MenuPopup(MENU_CONTENT_W, self)
        # 音量条**置顶**（2026-09-19）。宽度 = MENU_CONTENT_W，弹窗宽度按它适配
        # （= 音量条宽 + 两侧内边距 4px + 两侧边框 1px = 155px，所有角色一致）。
        bar = _VolumeBar(MENU_CONTENT_W, self._volume, self._on_bar_volume,
                         self._on_bar_mute, muted=self._muted)
        menu.add_volume(bar)
        self._bar = bar

        menu.add_separator()
        menu.add_item("切换", submenu=self._build_switch_menu())
        menu.add_separator()
        # 节能模式：勾选项直接反映当前状态（语音入口与这里共用 pet 内部那套落地逻辑）
        menu.add_item("节能模式", checkable=True, checked=self._power_save,
                      enabled=self._power_save or self._power_save_pixmap() is not None,
                      on_trigger=self.toggle_power_save)
        # patpat 模式（2026-09-20）：左键抚摸贴图。**不做素材门禁** —— 用户口径「可直接打开」，
        # 与节能模式那一行的 `enabled=` 刻意不同（缺图时开着也只是点了没反应，不是不能开）。
        menu.add_item("patpat模式", checkable=True, checked=self._patpat,
                      on_trigger=self.toggle_patpat)
        # 桌宠固定（2026-09-22）：勾选项，开着 = 贴图**不能被拖动**（只锁「拖」，
        # 抚摸 / 思考气泡照旧）。与上面两个「模式」排在一起。
        menu.add_item("桌宠固定", checkable=True, checked=self._locked,
                      on_trigger=self.toggle_locked)
        # 显示聊天气泡（检验用）：★2026-09-28 起**下架**（用户口径：软件实际使用时不需要这个功能，
        # 它只是用来核对气泡的外观 / 高度 / 贴边让位）。下面的开关 / 回调 / 预览文本都还在，
        # 要恢复这一行，解注即可。
        # menu.add_item("显示聊天气泡", checkable=True, checked=self._bubble_preview,
        #               on_trigger=self.toggle_bubble_preview)
        # 「主界面」= 打开主窗口并切到聊天界面；「设置」= 打开主窗口并切到设置界面
        menu.add_item("主界面", on_trigger=self._on_home)
        menu.add_item("设置", on_trigger=self._on_settings)
        menu.add_item("退出", on_trigger=self._on_quit)
        return menu

    def _menu(self, pos):
        """弹出右键弹窗（模态）：位置按 `menu_rect()` 算，**直接上屏**。

        2026-09-19 八改：容器从 `QMenu` 换成自绘的 `_MenuPopup`（原因见那个类的 docstring）——
        位置算法（`menu_rect()`）、防重入（`_menu_open`）、关掉后清 `_bar` 都不变。
        2026-09-19 十四改：给弹窗装上 `reopen_at` —— 菜单开着时**再按右键不是把它关掉（切换状态），
        而是按新点击点重新弹一次**（`_MenuPopup.eventFilter` 收到右键就调它）。
        """
        if self._menu_open:
            return              # 弹窗已经开着 → 忽略这一次右键（防重入，别叠两张）
        menu = self._build_menu()
        size = menu.sizeHint()
        rect, side = menu_rect(self._sprite_rect(), self._avail_rect(), self.mapToGlobal(pos), size)
        # 十四改：右键重开的入口 —— 只有这里知道贴图 / 可用区，能按 `menu_rect()` 重算位置
        menu.reopen_at = lambda gp: self._reopen_menu(menu, gp)
        self._menu_open = True
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(menu)     # 点在菜单外面 → 一次单击就把整套菜单淡出关掉
        try:
            menu.pop_up(rect, side)
            menu.run()
        finally:
            # 弹窗关掉后 `menu` 就没用了：清掉 `_bar`（别让之后 `set_volume` 碰到已销毁的 C++ 对象），
            # 再把它本身排队回收 —— 它是带 parent（=本窗口）的，不回收的话每次右键都会多留一个
            # 隐藏的子弹窗 + 一条音量条，长会话里越攒越多。
            if app is not None:
                app.removeEventFilter(menu)
            self._menu_open = False
            self._bar = None
            menu.deleteLater()

    def _reopen_menu(self, menu, global_pos: QPoint) -> None:
        """十四改：菜单**已经开着**时又按了一次右键 → 按新点击点**重新弹一次**。

        用户口径：「若重复按右键则**重复弹出**而非起到**切换状态**的作用」。
        所以这里不是关掉它，而是用 `menu_rect()` 把位置按新的点击点重算一遍再 `repop()` ——
        和第一次弹出的位置规则完全一致（横向贴贴图那一侧、纵向底边 = 这次点击的 y）；
        `repop()` 内部会把旧底图拿来补掉重叠区，所以不会抓到自己。
        走的是非模态的 `pop_up()`（不回 `run()` 的模态循环），`_menu_open` 期间一直有效。
        """
        size = menu.sizeHint()
        rect, side = menu_rect(self._sprite_rect(), self._avail_rect(), global_pos, size)
        menu.repop(rect, side)
