"""主窗口：PCL 风格（顶部蓝色栏 + 左右双栏）。"""
import html
import os
import random
import threading
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, QUrl,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QCursor, QColor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QIcon,
    QLinearGradient,
    QPainter, QPainterPath, QPen, QPixmap, QRegion, QTransform,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Qt 的 QWIDGETSIZE_MAX（PySide6 未导出该常量）：setMaximumHeight 用它表示「不限制」
MAX_WIDGET_H = 16777215

# 危险操作倒计时弹窗（DangerCountdownDialog）：尺寸 / 配色 / 节奏。
# **这张卡片是自绘的**（要整卡缩放，QSS + 子控件做不到 —— 见 design.md 4.5 与 docs/02 §8.7），
# 所以色值提成常量；它们与 ConfirmDialog / InputDialog / ApiFormDialog 的 QSS **逐条对齐**，
# 并有断言盯着「这里的常量 == 那三款 QSS 里的字面值」，防止两边漂移。
DLG_CARD_W, DLG_CARD_H = 200, 150      # 卡片本体（用户口径 200×150）
DLG_CARD_RADIUS = 16                    # 与另外三款弹窗同一条圆角
DLG_CARD_PAD = 14                       # 卡片内边距
DLG_POP_DY = 15                         # 淡入时自下而上平移的像素数 = 窗口比卡片高出来的那一截
DLG_ANIM_MS = 500                       # 淡入 / 淡出时长
DLG_MIN_SCALE = 0.5                     # 淡入起点 = 原本大小的 50%
DLG_CANCEL_HOLD_MS = 1500               # 取消态（红色）保持多久再淡出
DLG_BTN_W, DLG_BTN_H = 80, 30           # 一行两个按钮（卡片只有 200 宽，88×34 那两个放不下）
DLG_BTN_GAP, DLG_BTN_RADIUS = 8, 8
DLG_CARD_BORDER = "#E6F1FB"             # 蓝态边框（= ConfirmDialog 的 QSS 值）
DLG_TITLE_INK = "#0C447C"               # 蓝态标题（= 那三款的标题色）
DLG_NUM_BLUE = "#378ADD"                # 蓝态大号秒数（= 主蓝）
DLG_MUTED = "#64748B"                   # 「秒」/ 灰字（= 那三款取消按钮的字色）
DLG_CARD_BORDER_RED = "#FCA5A5"         # 红态边框（已取消）
DLG_TITLE_INK_RED = "#991B1B"           # 红态标题
DLG_NUM_RED = "#DC2626"                 # 红态大号字
DLG_BTN_PRIMARY = "#378ADD"             # 「立刻执行」= 蓝底白字（= 那三款确认按钮）
DLG_BTN_PRIMARY_HOVER = "#2F74BF"
DLG_BTN_GHOST_BORDER = "#CBD5E1"        # 「取消」= 透明底灰边（= 那三款取消按钮）
DLG_BTN_GHOST_HOVER = "#F1F5F9"
DLG_BTN_RUN_TEXT = "立刻执行"       # 通用文案：关机 / 重启 / 注销…都用它
DLG_BTN_CANCEL_TEXT = "取消"

from .config import (DEFAULT_BASE_URL, DEFAULT_MODEL,
                     is_role_switchable, resolve_persona_text, save_config)
# ★is_role_switchable：角色的可切换性真值（docs/02 §24）
# ★resolve_persona_text：人设取值的**唯一入口**（「查看」弹窗用它，别再自己读文件；docs/02 §25.17）
from .volume import VolumeSlider, VolumeStepButton
from .state import State
from . import voice_model
from . import voice_download
# ★P2（2026-10-02）：诊断内核与更新内核。两者都**不 import Qt**，
#   判据全在那边（同一份结论给「引导 / 状态条 / 自检」三段 UI，见 app/health.py 抬头）。
from . import health
from . import update
# ★版本号的**唯一真值**在 `app/__init__.py`（检查更新拿它跟 GitHub 的 tag 比）
from . import __version__ as APP_VERSION

BASE = Path(__file__).resolve().parent.parent
ASSETS = BASE / "assets"
ICONS = ASSETS / "icon"        # 图标贴图（下拉箭头 / 垃圾桶 / 铅笔 / 窗口按钮…）
AVATARS = ASSETS / "avatar"    # 角色头像

# 图标路径
_ARROW_GRAY = (ICONS / "arrow_down_gray.png").as_posix()
_TRASH_RED = (ICONS / "trash_red.png").as_posix()
_PENCIL = (ICONS / "icon_pencil.png").as_posix()
_SWITCH = (ICONS / "icon_switch.png").as_posix()
_MINIMIZE = (ICONS / "icon_minimize.png").as_posix()
_CLOSE = (ICONS / "icon_close.png").as_posix()
_DEFAULT_AVATAR = (AVATARS / "default_avatar.png").as_posix()


STATUS_TEXT = {
    State.IDLE: "待机",
    State.LISTENING: "聆听中…",
    State.THINKING: "思考中…",
    State.SPEAKING: "说话中…",
    State.WORKING: "执行操作中…",
}


def mask_key(key: str) -> str:
    """脱敏 API key：DeepSeek 官方格式 sk-前五位*****末尾四位。"""
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 9:
        return key
    prefix = ""
    body = key
    if key.lower().startswith("sk-"):
        prefix = key[:3]
        body = key[3:]
    if len(body) <= 9:
        return key
    return f"{prefix}{body[:5]}*****{body[-4:]}"


# 随机头像池：角色 → 文件名前缀（`assets/avatar/<前缀>*` 里的图片全进池）。
# ★往文件夹里加头像（前缀 + 任意名字）即自动进池，**不用改代码**。
AVATAR_POOL_PREFIX = {"alice": "avatar_aris_"}
_AVATAR_EXTS = (".png", ".jpg", ".jpeg")
# 本会话固定的选图：角色 → 文件名（空串 = 该角色没有池 → 回退默认灰色头像）
_avatar_picks: dict[str, str] = {}


def _avatar_pool(role_key: str) -> list[str]:
    """角色的随机头像池：`assets/avatar/` 下 `<前缀>*` 里的图片，按文件名排序；没有池就给 []。"""
    prefix = AVATAR_POOL_PREFIX.get(role_key)
    if not prefix:
        return []
    return sorted(p.name for p in AVATARS.glob(f"{prefix}*")
                  if p.is_file() and p.suffix.lower() in _AVATAR_EXTS)


def _avatar_pick(role_key: str) -> str:
    """本会话固定的随机头像**文件名**（每次启动随机一次，会话内固定）；没有池就给空串。"""
    if role_key not in _avatar_picks:
        pool = _avatar_pool(role_key)
        _avatar_picks[role_key] = random.choice(pool) if pool else ""
    return _avatar_picks[role_key]


def _circular_crop(pixmap: QPixmap, size: int) -> QPixmap:
    """中心裁剪：缩放到短边=size（保持比例），裁正中央 size×size，再裁成圆形。"""
    if pixmap.isNull() or size <= 0:
        return pixmap
    w, h = pixmap.width(), pixmap.height()
    scale = max(size / w, size / h)  # 短边对齐 size（横图=高度对齐、竖图=宽度对齐）
    sw = max(size, int(w * scale))
    sh = max(size, int(h * scale))
    scaled = pixmap.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    x = (sw - size) // 2
    y = (sh - size) // 2
    cropped = scaled.copy(x, y, size, size)
    # 圆形遮罩
    result = QPixmap(size, size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    return result


def _load_avatar(role_key: str, size: int | None = None) -> QPixmap:
    """加载角色头像。有随机池的角色（爱丽丝）随机选一张，其余用 `avatar/{key}.png`，
    都没有则默认灰色头像。size 非空时中心裁剪成 size×size 圆形。"""
    pick = _avatar_pick(role_key)
    p = AVATARS / (pick or f"{role_key}.png")
    pm = QPixmap(str(p)) if p.is_file() else QPixmap(_DEFAULT_AVATAR)
    if size and not pm.isNull():
        return _circular_crop(pm, size)
    return pm


class HoverComboBox(QComboBox):
    """带悬停颜色渐变动画的下拉框：圆形箭头按钮直径与文本框同高。"""

    _DROPDOWN_SIZE = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._apply_hover)
        self._hover = 0.0
        self._hovering_dropdown = False
        self._pressed = False
        self.setMouseTracking(True)
        self._apply_hover(0.0)

    @staticmethod
    def _lerp_color(c1, c2, t):
        def hx(s, i):
            return int(s[i:i + 2], 16)
        r = round(hx(c1, 1) + (hx(c2, 1) - hx(c1, 1)) * t)
        g = round(hx(c1, 3) + (hx(c2, 3) - hx(c1, 3)) * t)
        b = round(hx(c1, 5) + (hx(c2, 5) - hx(c1, 5)) * t)
        return f"#{r:02X}{g:02X}{b:02X}"

    def _apply_hover(self, t):
        self._hover = float(t)
        bg = self._lerp_color("#F6FAFF", "#DCDCDC", self._hover)
        self.setStyleSheet(
            "QComboBox { background:#F6FAFF; border:1px solid #7DD3FC; border-radius:15px; padding:6px 30px 6px 12px; }"
            "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; "
            f"width:30px; height:30px; border:none; border-radius:15px; background:{bg}; margin-right:0; }}"
            f"QComboBox::down-arrow {{ image:url({_ARROW_GRAY}); width:15px; height:15px; }}"
            "QComboBox QAbstractItemView { background:#FFFFFF; border:1px solid #7DD3FC; "
            "border-radius:8px; selection-background-color:#E6F1FB; selection-color:#0C447C; }"
        )

    def _dropdown_rect(self) -> QRect:
        s = self._DROPDOWN_SIZE
        w = self.width()
        h = self.height()
        return QRect(w - s, (h - s) // 2, s, s)

    def _animate_to(self, target, duration=None):
        self._anim.stop()
        if duration is not None:
            self._anim.setDuration(duration)
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.start()

    def _update_hover_state(self, pos):
        inside = self._dropdown_rect().contains(pos)
        if inside != self._hovering_dropdown:
            self._hovering_dropdown = inside
            self._animate_to(1.0 if inside else 0.0)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        inside = self._dropdown_rect().contains(pos)
        if inside != self._hovering_dropdown:
            self._hovering_dropdown = inside
            if not self._pressed:
                self._animate_to(1.0 if inside else 0.0)
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._dropdown_rect().contains(e.position().toPoint()):
            self._pressed = True
            self._animate_to(0.0, 120)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._pressed:
            self._pressed = False
            if self._dropdown_rect().contains(e.position().toPoint()):
                self._animate_to(1.0, 300)
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._hovering_dropdown:
            self._hovering_dropdown = False
            if not self._pressed:
                self._animate_to(0.0)
        self._pressed = False
        super().leaveEvent(e)

    def hidePopup(self):
        super().hidePopup()
        self._pressed = False
        self._update_hover_state(self.mapFromGlobal(QCursor.pos()))


# ========== 嵌入面板 ==========

def _animate_from_bottom(widget):
    """弹窗出现时：从目标位置向下 10px 处，自下而上移动 10px 到目标位置（200ms）。"""
    def apply():
        target = widget.pos()
        widget.move(target.x(), target.y() + 10)
        anim = QPropertyAnimation(widget, b"pos", widget)
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(QPoint(target.x(), target.y() + 10))
        anim.setEndValue(target)
        anim.start()
        widget._popup_anim = anim  # 保持引用防被 GC
    QTimer.singleShot(0, apply)


def _animate_message(label, text, color):
    """消息提示动画：上移 5px + 透明度 0.5→1 出现，3s 后下移 5px + 淡出消失。"""
    label.setStyleSheet(f"color:{color}; font-weight:500;")
    # 先停掉旧动画与定时器，避免旧 effect 动画仍在运行时被移除（导致 QPainter 警告）
    if getattr(label, "_msg_timer", None) is not None:
        label._msg_timer.stop()
    for a in list(getattr(label, "_msg_anims", [])):
        try:
            a.stop()
        except Exception:  # noqa: BLE001
            pass
    label._msg_anims = []
    label.setGraphicsEffect(None)
    label.setText(text)
    label.adjustSize()
    target = label.pos()
    effect = QGraphicsOpacityEffect(label)
    effect.setOpacity(0.5)
    label.setGraphicsEffect(effect)
    label.move(target.x(), target.y() + 5)
    in_pos = QPropertyAnimation(label, b"pos", label)
    in_pos.setDuration(200)
    in_pos.setStartValue(QPoint(target.x(), target.y() + 5))
    in_pos.setEndValue(target)
    in_op = QPropertyAnimation(effect, b"opacity", label)
    in_op.setDuration(200)
    in_op.setStartValue(0.5)
    in_op.setEndValue(1.0)
    in_pos.start()
    in_op.start()
    label._msg_anims = [in_pos, in_op]

    def fade_out():
        out_pos = QPropertyAnimation(label, b"pos", label)
        out_pos.setDuration(200)
        out_pos.setStartValue(target)
        out_pos.setEndValue(QPoint(target.x(), target.y() + 5))
        out_op = QPropertyAnimation(effect, b"opacity", label)
        out_op.setDuration(200)
        out_op.setStartValue(1.0)
        out_op.setEndValue(0.0)

        def clear():
            label.clear()
            label.setGraphicsEffect(None)
        out_op.finished.connect(clear)
        out_pos.start()
        out_op.start()
        label._msg_anims = [out_pos, out_op]

    label._msg_timer = QTimer(label)
    label._msg_timer.setSingleShot(True)
    label._msg_timer.timeout.connect(fade_out)
    label._msg_timer.start(3000)


# ---- 管理/设置面板的公共结构（标题 → 说明 → 滚动区 → 底部 → 消息行）----

_CHEVRON_CACHE = {}


def _chevron_pixmap(collapsed: bool) -> QPixmap:
    """分组标题的展开指示箭头：复用下拉框箭头图，收起态旋转 −90° 指向右。

    缓存两份（收起 / 展开），避免每次 rebuild 都重新做变换。
    """
    key = bool(collapsed)
    if key not in _CHEVRON_CACHE:
        pm = QPixmap(_ARROW_GRAY)
        if not pm.isNull():
            if collapsed:
                pm = pm.transformed(QTransform().rotate(-90))
            pm = pm.scaled(14, 14, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        _CHEVRON_CACHE[key] = pm
    return _CHEVRON_CACHE[key]


def _panel_scroll(parent_lay):
    """给面板挂一个滚动区，返回 (scroll, body, body_lay)。

    **垂直滚动条恒常驻位**（`ScrollBarAlwaysOn`，2026-09-18）：滚动条出现 / 消失会让
    `widgetResizable=True` 的视口在 8px 之间跳变，body 跟着变宽变窄 → 带边框的卡片
    「可操作目录/文件夹」等的右边框一进一出（用户报的 bug）。策略固定之后视口宽度恒定，
    body 的右内边距 8px 就是「卡片右边框 → 滑块」的固定呼吸位。
    代价是短页面右侧也留着 8px 空道 —— 滑块本身由 `_SmoothScrollBar.paintEvent`
    在没有滚动量时**不画**，所以只是一条空道，不会出现一根常驻灰柱。
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
    scroll.setVerticalScrollBar(_SmoothScrollBar())
    body = QWidget()
    body.setStyleSheet("background:transparent;")
    body_lay = QVBoxLayout(body)
    body_lay.setContentsMargins(0, 0, 8, 0)
    body_lay.setSpacing(8)
    scroll.setWidget(body)
    parent_lay.addWidget(scroll, 1)
    return scroll, body, body_lay


# 设置页 / 管理面板底部「消息行区」的高度：= 滚动条到窗口最右侧的间距（24px）。
# 此前底部是 20(面板底边距)+14(间距)+16(消息行) = 50px，白空一整块把内容挡住；
# 现改为 4 + 16 + 4 = 24px —— 与右侧留白完全一致，底部不再多出一块。
MSG_ROW_H = 16      # 消息行单行高度（钉住，保证底部区高度确定）
TAIL_GAP = 4        # 滚动区与消息行之间的间距
TAIL_BOTTOM = 4     # 面板底边距（消息行下方）
TAIL_H = MSG_ROW_H + TAIL_GAP + TAIL_BOTTOM     # 24px


def _panel_bottom(parent_lay):
    """底部「滚动区 + 消息行」区：返回 `(scroll, body, body_lay, msg_label)`。

    **单独起一层 `spacing=TAIL_GAP(4px)` 的子布局**：直接挂在面板 layout 上会带上它的
    14px 行距，底部就压不到 24px（面板 layout 的 14px 行距是给「标题 → 说明 → 滚动区」
    用的）。底部整块 = TAIL_GAP(4) + 消息行 16 + TAIL_BOTTOM(4) = **24px**，与「滚动条
    到窗口最右侧的间距」相等 —— 此前是 50px，白空一整块把内容挡住。
    消息行钉住单行高 16px（否则字体度量差 1px 就对不上 24），多行提示会自己撑高。
    """
    tail = QVBoxLayout()
    tail.setContentsMargins(0, 0, 0, 0)
    tail.setSpacing(TAIL_GAP)
    scroll, body, body_lay = _panel_scroll(tail)
    msg_label = QLabel("")
    msg_label.setWordWrap(True)
    msg_label.setMinimumHeight(MSG_ROW_H)
    tail.addWidget(msg_label)
    parent_lay.addLayout(tail, 1)
    return scroll, body, body_lay, msg_label


def _scroll_to_top(widget):
    """把面板的滚动区复位到顶端（重新进入该页面时调用）。

    QScrollArea 在内容高度不变时会**保留原滚动值**，所以「在权限管理里下拉 →
    切到别的页 → 再切回来」仍停在半截位置。设置页一律以顶端为默认视图。
    """
    scroll = getattr(widget, "_scroll", None)
    if isinstance(scroll, QScrollArea):
        bar = scroll.verticalScrollBar()
        bar.setValue(bar.minimum())


# 「计算机」（此电脑）是 Windows 的**虚拟文件夹**，没有盘符路径。Qt 认的是 `clsid:` 方案的
# URL，而且它内部调的是 SHGetKnownFolderIDList() —— 只认 **KNOWNFOLDERID**。
# ⚠️ 网上流传的 `::{20D04FE0-3AEA-1069-A2D8-08002B30309D}`（"我的电脑"经典 CLSID）**不是**
# KNOWNFOLDERID：实测该函数返回 0x80070002，Qt 只打一行 warning，**对话框静默退回当前目录**
# （看不出报错，只是开在了错的地方）。正确值是 FOLDERID_ComputerFolder。
# 也不能写成 setDirectory("::{CLSID}") —— setDirectory 走本地路径分支，同样落进当前目录。
COMPUTER_FOLDER_ID = "0AC0837C-BBF8-452A-850D-79D08E667CA7"   # FOLDERID_ComputerFolder


def _dialog_start_url() -> QUrl:
    """文件 / 文件夹选择对话框的默认起始位置：「计算机」。

    只能通过 `QFileDialog.setDirectoryUrl` 传（`setDirectory` 会把它当本地路径）。
    非 Windows 返回空 URL，交给系统默认行为。
    """
    return QUrl(f"clsid:{COMPUTER_FOLDER_ID}") if os.name == "nt" else QUrl()


def _panel_title(parent_lay, text, desc=None):
    """面板标题 16px Bold #0C447C + 可选说明 12px #64748B。"""
    title = QLabel(text)
    title.setStyleSheet("font-size:16px; font-weight:bold; color:#0C447C; background:transparent;")
    parent_lay.addWidget(title)
    if desc:
        lbl = QLabel(desc)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#64748B; font-size:12px; background:transparent;")
        parent_lay.addWidget(lbl)


def _group_header(body_lay, name, hint=None, add_text=None, on_add=None):
    """分组小标题（+ 可选蓝色镂空添加按钮）+ 说明行。"""
    head = QHBoxLayout()
    lbl = QLabel(name)
    lbl.setStyleSheet("font-weight:bold; color:#334155; background:transparent;")
    head.addWidget(lbl)
    head.addStretch(1)
    if add_text:
        btn = QPushButton(add_text)
        btn.setObjectName("outlineBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=False: on_add())
        head.addWidget(btn)
    body_lay.addLayout(head)
    if hint:
        tip = QLabel(hint)
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#64748B; font-size:12px; background:transparent;")
        body_lay.addWidget(tip)


def _hint_tip(body_lay, text):
    """滚动区内的空列表提示行（也用作带边框卡片内的空态，故左内边距与行文本对齐）。

    **必须 `setWordWrap(True)`**：滚动区是 `widgetResizable=True` 且**关掉了水平滚动条**，
    不换行的长提示会把内容区的最小宽度顶到视口之外 —— 整个分组（含右侧行内按钮 /
    开关）会一起被裁掉右边一截（实测：一句 60 字的说明把行宽顶到 871 > 视口 860）。
    """
    tip = QLabel(text)
    tip.setWordWrap(True)
    tip.setStyleSheet(
        "color:#64748B; font-size:12px; padding:8px 10px 10px 10px; background:transparent;"
    )
    body_lay.addWidget(tip)


def _clear_body(body_lay):
    """清空滚动区内容：先 setParent(None) 立即脱离层级，再 deleteLater。

    分组标题行是子布局（QHBoxLayout），也要把里面的控件一并销毁，
    否则每次 rebuild 都会泄漏一组标题/按钮。

    **重建前先把「落在待拆控件里的焦点」收掉**（关键）：行内按钮 / 分组添加按钮都是
    `QPushButton`，点一下就会拿到焦点；rebuild 会把它连同内容一起销毁，Qt 随即把焦点
    转交给别的控件，而 `QScrollArea` 会 `ensureWidgetVisible` 去追这个新焦点 ——
    表现就是「删一行 / 改个名，画面自己滚到别处」（实测：滚到 559 后删一行 → 直接跳到底部）。
    在这里统一收掉，所有走 `_clear_body` 的面板（权限 / API / 唤醒词）一次性修好。
    """
    fw = None
    host = body_lay.parentWidget()
    if host is not None:
        win = host.window()
        fw = win.focusWidget() if win is not None else None
    if fw is not None and host is not None and (fw is host or host.isAncestorOf(fw)):
        fw.clearFocus()
    while body_lay.count():
        item = body_lay.takeAt(0)
        w = item.widget()
        if w is None:
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    child = sub.takeAt(0)
                    cw = child.widget()
                    if cw is not None:
                        cw.setParent(None)
                        cw.deleteLater()
                sub.deleteLater()
            continue
        if isinstance(w, (_PermRow, _PermToggleRow, _SettingRow, _CollapsibleGroup)):
            # 停掉 hover 渐变动画与高度动画，避免销毁后回调仍在跑
            anim = getattr(w, "_hover_anim", None)
            if anim is not None:
                try:
                    anim.stop()
                    anim.valueChanged.disconnect()
                except (AttributeError, TypeError, RuntimeError):
                    pass
            for name in ("_head_anim", "_h_anim_timer", "_add_anim"):
                obj = getattr(w, name, None)
                if obj is not None:
                    try:
                        obj.stop()
                    except (AttributeError, RuntimeError):
                        pass
        w.setParent(None)
        w.deleteLater()


# 四款「卡片弹窗」（ConfirmDialog / ChoiceDialog / InputDialog / ApiFormDialog）**共用同一张皮肤**：
# 卡片底 + 圆角边框 + 两颗按钮的常态 / hover 色逐字相同。原先四个类各抄一份（改一处就漂移，
# `tests/smoke_api.py` 有「三个弹窗共用同一张卡片皮肤」的断言盯着），这里拆成四块、按各弹窗
# **原来的拼接顺序**取用 —— 拼出来的样式表与重构前逐字一致。
_CARD_FRAME_QSS = (
    "QFrame#confirmCard { background:#FFFFFF; border:1px solid #E6F1FB; border-radius:16px; }"
)
_CARD_EDIT_QSS = (
    "QLineEdit { background:#F6FAFF; border:1px solid #7DD3FC; border-radius:15px; padding:6px 12px; color:#334155; }"
)
_CARD_BTN_QSS = (
    "QPushButton#cancelBtn { background:transparent; color:#64748B; border:1px solid #CBD5E1; border-radius:8px; }"
    "QPushButton#cancelBtn:hover { background:#F1F5F9; }"
    "QPushButton#confirmBtn { background:#378ADD; color:white; border:none; border-radius:8px; font-weight:bold; }"
    "QPushButton#confirmBtn:hover { background:#2F74BF; }"
)
_CARD_DANGER_QSS = (
    "QPushButton#dangerBtn { background:transparent; color:#C0392B; border:1px solid #C0392B; border-radius:8px; }"
    "QPushButton#dangerBtn:hover { background:#FDEDEC; }"
)
# 「查看」预设弹窗里的内容框（2026-09-30）：输入框那套「`#F6FAFF` 底 + `#7DD3FC` 描边」
# 用在**多行**文本框上的样子。★圆角取 **12px**（design.md 4.2 卡片那一档）而不是输入框的
# 15px 胶囊 —— 15px 圆角套在几百像素高的大框上，两端会鼓出来。
_PRESET_BOX_QSS = (
    "QFrame#presetFieldBox { background:#F6FAFF; border:1px solid #7DD3FC; border-radius:12px; }"
    "QFrame#presetFieldBox QLabel { background:transparent; }"
)


class _CardDialog(QDialog):
    """卡片弹窗公共基类：窗口模态 + 「自下而上淡入」的入场动画（四款弹窗同一条）。

    子类照旧自己管窗口标志与卡片内容；`exec()` / `result()` 等 QDialog 接口沿 MRO 原样可用。

    ★★**窗口模态只锁父窗**（2026-10-01 用户报「主界面一弹窗，桌宠就点不动了」）：
      * `setModal(True)` == `Qt.ApplicationModal` ⇒ **整个应用的所有顶层窗一起被拦** ——
        桌宠窗虽然跟弹窗**没有**父子关系，也照样被 `EnableWindow(hwnd, FALSE)`。
        真机量到的印记（`tests/probe_modal_pet_input.py`，真 windows 平台看 `IsWindowEnabled`）：
        `ApplicationModal` 下主窗与桌宠窗的 HWND **双双变 False** ⇒ 左键摸头 / 右键菜单全废。
      * `Qt.WindowModal` 的判据（`QGuiApplicationPrivate::isWindowBlocked`，Qt 源码）是
        「从**被查询窗**沿 transient 父链上溯，看链上有没有窗是**模态窗的祖先**」⇒
          主窗 = 弹窗的 transient 父窗（`dlg.transientParent() is mainWin`）⇒ **被拦** ✔
          桌宠窗 `transientParent() is None` ⇒ **不在那条链上** ⇒ **不拦** ✔
        （真机量过：`WindowModal` 下主窗 False、桌宠窗 True。）
      * ★**前置条件：弹窗必须有 parent** —— parent 为 None 时模态窗没有祖先可挂，
        WindowModal **谁也拦不住**（比 ApplicationModal 还松）⇒ 兜底退回 ApplicationModal，
        宁可多拦也不静默不拦。
    ★⚠️ 别退回 `setModal(True)`：它会连桌宠一起拦掉，且**测试抓不到**
      （QTest 的合成点击**绕不过**模态，见 `tests/probe_modal_pet_input.py` 的说明）。
    """

    MODALITY = Qt.WindowModal

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowModality(
            self.MODALITY if parent is not None else Qt.ApplicationModal
        )

    def showEvent(self, event):
        super().showEvent(event)
        _animate_from_bottom(self)


class ConfirmDialog(_CardDialog):
    """PCL 风格确认弹窗：无边框、圆角白底、淡蓝确认按钮。"""

    CARD_W = 360                 # 卡片宽（★提成常量是为了让 ChoiceDialog 的「加宽」可比）

    def __init__(self, parent, message: str, confirm_text: str = "确认", cancel_text: str = "取消"):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(self.CARD_W)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("confirmCard")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 24, 24, 20)
        card_lay.setSpacing(18)

        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setStyleSheet("color:#334155; font-size:14px; background:transparent;")
        card_lay.addWidget(msg)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        cancel_btn = QPushButton(cancel_text)
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setFixedSize(88, 34)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        confirm_btn = QPushButton(confirm_text)
        confirm_btn.setObjectName("confirmBtn")
        confirm_btn.setCursor(Qt.PointingHandCursor)
        confirm_btn.setFixedSize(88, 34)
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)
        card_lay.addLayout(btn_row)
        outer.addWidget(card)

        self.setStyleSheet(_CARD_FRAME_QSS + _CARD_BTN_QSS)

    @staticmethod
    def confirm(parent, message: str, confirm_text: str = "确认", cancel_text: str = "取消") -> bool:
        dlg = ConfirmDialog(parent, message, confirm_text, cancel_text)
        return dlg.exec() == QDialog.Accepted


class ChoiceDialog(_CardDialog):
    """**三选一**弹窗（与 `ConfirmDialog` 同一张卡片皮肤 `#confirmCard`，只是卡片加宽、按钮三颗）。

    ★**为什么不复用 `ConfirmDialog`**：它的 `exec()` 只回「接受 / 拒绝」两值 —— 而这里两个
      「确认」的代价差 3 倍以上（仅模型 ≈1.2 GB vs 全部 ≈3.6 GB），**返回值必须能区分三档**，
      否则「用户选了哪一档」这件事在类型上就表达不出来，只能靠猜 / 靠额外状态。
    ★首用者：设置页「音色克隆模型下载 → 卸载」（`docs/01` F7、`design.md` 4.13）。

    用法：`ChoiceDialog.choose(parent, message, [("model", "仅模型卸载", "primary"), ...])`
    —— 回 `None`（取消）或某个 `key`。
    """

    CARD_W = 440                 # ★用户口径「弹窗的宽度可以适当加宽」（文案要写清两档各删什么）
    BTN_W, BTN_H = 96, 34
    BTN_GAP = 10                 # 与 ConfirmDialog 两颗按钮同一节奏

    def __init__(self, parent, message: str, choices, cancel_text: str = "取消"):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(self.CARD_W)
        self._choice = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("confirmCard")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 24, 24, 20)
        card_lay.setSpacing(18)

        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setStyleSheet("color:#334155; font-size:14px; background:transparent;")
        card_lay.addWidget(msg)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(self.BTN_GAP)
        btn_row.addStretch(1)                 # 按钮组靠右（与 ConfirmDialog 一致）
        cancel_btn = QPushButton(cancel_text)
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setFixedSize(self.BTN_W, self.BTN_H)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        for key, text, style in choices:
            # ★`style` 只认 "primary"（主蓝实心）/ "danger"（红边镂空，与权限页删除同色）；
            #   别的值当作普通镂空，别让一个拼错的字符串变成「没样式」的裸按钮。
            obj = {"primary": "confirmBtn", "danger": "dangerBtn"}.get(style, "cancelBtn")
            btn = QPushButton(text)
            btn.setObjectName(obj)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(self.BTN_W, self.BTN_H)
            # ★默认参数 `k=key` 钉住这一圈的值：闭包直接捕获 `key` 会在循环里全指向最后一个。
            btn.clicked.connect(lambda _=False, k=key: self._pick(k))
            btn_row.addWidget(btn)
        card_lay.addLayout(btn_row)
        outer.addWidget(card)

        self.setStyleSheet(_CARD_FRAME_QSS + _CARD_BTN_QSS + _CARD_DANGER_QSS)

    def _pick(self, key):
        self._choice = key
        self.accept()

    def result_key(self):
        """用户选了哪个 `key`；取消 / 关掉窗口 ⇒ `None`。"""
        return self._choice

    @staticmethod
    def choose(parent, message: str, choices, cancel_text: str = "取消"):
        dlg = ChoiceDialog(parent, message, choices, cancel_text)
        dlg.exec()
        return dlg.result_key()


class InputDialog(_CardDialog):
    """PCL 风格单行输入弹窗（与删除确认弹窗同款）。"""

    def __init__(self, parent, title: str, label: str, default: str = "", password: bool = False):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(360)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("confirmCard")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 24, 24, 20)
        card_lay.setSpacing(14)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size:15px; font-weight:bold; color:#0C447C; background:transparent;")
        card_lay.addWidget(title_lbl)

        label_lbl = QLabel(label)
        label_lbl.setWordWrap(True)
        label_lbl.setStyleSheet("color:#334155; font-size:13px; background:transparent;")
        card_lay.addWidget(label_lbl)

        self.edit = QLineEdit(default)
        if password:
            self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText("请输入…")
        card_lay.addWidget(self.edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setFixedSize(88, 34)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        confirm_btn = QPushButton("确认")
        confirm_btn.setObjectName("confirmBtn")
        confirm_btn.setCursor(Qt.PointingHandCursor)
        confirm_btn.setFixedSize(88, 34)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)
        card_lay.addLayout(btn_row)
        outer.addWidget(card)

        self.setStyleSheet(_CARD_FRAME_QSS + _CARD_EDIT_QSS + _CARD_BTN_QSS)

        self.edit.returnPressed.connect(self._on_confirm)
        self._result = ""

    def _on_confirm(self):
        self._result = self.edit.text().strip()
        self.accept()

    @staticmethod
    def get_text(parent, title: str, label: str, default: str = "", password: bool = False):
        dlg = InputDialog(parent, title, label, default, password)
        if dlg.exec() == QDialog.Accepted:
            return dlg._result, True
        return "", False


class PresetViewDialog(_CardDialog):
    """「查看」预设弹窗（**540×460**，2026-09-30 定稿）。

    用户口径：内部显示「角色背景设定 / 说话风格 / 口癖 / 称呼 / 回复语言」五项，
    **每项内容用一个文本框框住**；内容基本较长 ⇒ 弹窗可下拉（右侧给滚动条留位、下侧留位放
    「关闭」按钮）。

    - 与另外四款弹窗**共用同一张卡片皮肤**（`_CARD_FRAME_QSS` / `_CARD_BTN_QSS`，design.md 4.5），
      只是尺寸按用户口径放大到 540×460。
    - 「回复语言」由调用方算好传进来（它不在人设文件里，见 `_PRESET_FIELDS` 上方的注释）。
    - ★★**唯一的关法是底部那颗「关闭」按钮**（2026-09-30 用户拍板）。
      同日晚些时候曾做过「点弹窗外也关闭」，**已按用户要求整块删除** —— 三层机制
      （应用级 `eventFilter` + 给透明边涂 `alpha=1` + `mousePressEvent` 几何兜底）都撤了；
      连带 `OUTER` 那圈 12px 透明边也不再需要：**窗口 = 卡片**（540×460），窗口里没有"外面"。
      ⇒ **别再加回来**（`docs/02 §25.6` 记着它当时为什么不好使）。
    """

    CARD_W, CARD_H = 540, 460
    BTN_W, BTN_H = 88, 34

    def __init__(self, parent, name: str, rows):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.CARD_W, self.CARD_H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("confirmCard")        # ★沿用四款弹窗那张卡片的 objectName
        card.setFixedSize(self.CARD_W, self.CARD_H)
        self._card = card
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 20, 24, 20)
        card_lay.setSpacing(14)

        # 标题 = 预设命名（看的人要能一眼确认"这是哪一套设定"）
        title = QLabel(str(name))
        title.setWordWrap(True)
        title.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#0C447C; background:transparent;"
        )
        card_lay.addWidget(title)

        # 滚动区：复用面板那套（`_SmoothScrollBar` 胶囊条 + 垂直常驻位 + body 右留 8px 呼吸位）
        _scroll, _body, body_lay = _panel_scroll(card_lay)
        body_lay.setSpacing(14)
        for label, text in rows:
            body_lay.addWidget(self._build_field(label, text))
        body_lay.addStretch(1)

        # 底部：下侧留出放「关闭」的空间（按钮右对齐，与另外四款同一条排法）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("confirmBtn")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(self.BTN_W, self.BTN_H)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        card_lay.addLayout(btn_row)

        outer.addWidget(card)
        self.setStyleSheet(_CARD_FRAME_QSS + _CARD_BTN_QSS + _PRESET_BOX_QSS)

    @staticmethod
    def _build_field(label: str, text: str) -> QWidget:
        """一项 = 「小标题 + 一个框住内容的文本框」。

        ★文本框用 `QFrame` + `QLabel(wordWrap)`，**不用 `QTextEdit`**：阅读用的只读文本
          不需要自己的滚动条 / 光标，而且 `QTextEdit` 必须钉死高度 —— 内容长的要单独滚、
          短的会空一大块，跟「整页一起下拉」的口径冲突。
        ★长内容必须能换行（`setWordWrap(True)`）且**横向策略 `Ignored`**：滚动区是
          `widgetResizable` + 关掉了水平滚动条，不换行的长文本会把内容区最小宽度顶到视口之外
          —— 整块被裁掉右边一截（`_SettingRow` / `_hint_tip` 都踩过这个坑）。
          ★改策略时**基于现有 policy 改**（不要 `setSizePolicy(新对象)`）：`QLabel.setWordWrap`
            会带上 `heightForWidth`，换一个全新 policy 会把那个标志丢掉 ⇒ 多行文本只剩一行高。
        """
        wrap = QWidget()
        wrap.setStyleSheet("background:transparent;")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        head = QLabel(label)
        head.setStyleSheet("font-weight:bold; color:#334155; background:transparent;")
        v.addWidget(head)

        box = QFrame()
        box.setObjectName("presetFieldBox")
        box_lay = QVBoxLayout(box)
        box_lay.setContentsMargins(12, 8, 12, 8)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)   # 只读，但允许选中复制
        pol = body.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Ignored)
        body.setSizePolicy(pol)
        body.setStyleSheet("color:#334155; font-size:13px; background:transparent;")
        box_lay.addWidget(body)
        v.addWidget(box)
        return wrap

    @staticmethod
    def view(parent, name: str, rows):
        dlg = PresetViewDialog(parent, name, rows)
        dlg.exec()


# ========== P2 体验三件套：首次引导 / 一键自检 / 检查更新（2026-10-02）==========
#
# ★三张卡片都继承 `_CardDialog`，走 design.md 4.5 那条共用皮肤
#   （圆角 16px / 标题 15px Bold #0C447C / 正文 13px #334155 / 底部按钮右对齐 88×34）。
# ★★**判据一个字都不在这里** —— 全在 `app/health.py`（三处 UI 用同一份结论，
#   各写各的迟早漂移成「自检说没问题、状态条说没配 key」）。这里只负责**呈现**。
# ★`level` 三档的配色**只用 design.md §1 已有的三个语义色**（不新增颜色）：
#     ok   → 成功绿 #1E8E3E
#     warn → 主蓝  #378ADD   （「你可能是故意的」，是信息不是错误）
#     fail → 错误红 #C0392B
_HL_COLORS = {"ok": "#1E8E3E", "warn": "#378ADD", "fail": "#C0392B"}


def _status_dot(level: str) -> QLabel:
    """状态小圆点（8px）。★颜色表在上面 —— 想加第四档之前先往 design.md 里加色。"""
    dot = QLabel()
    dot.setFixedSize(8, 8)
    dot.setStyleSheet(
        "background:%s; border-radius:4px;" % _HL_COLORS.get(level, "#64748B")
    )
    return dot


class FirstRunDialog(_CardDialog):
    """**首次使用引导**（P2）：还没配过 API 时自动弹一次；之后可随时从托盘 / 设置页重开。

    用户视角的问题：装完第一次打开，软件「什么都没发生」—— 因为默认**没有 API Key、
    白名单也是空的**（README 里那「第一次要自己做的两件事」）。本卡把那两件事摆在最前面，
    并给一颗直通设置页的按钮。

    - 宽度 360（design.md 4.5 的常规档）。
    - 两项的 ✓/✗ 由 `health.guide_items()` **现算** ⇒ 重新打开时显示的是**当前**进度，
      不是一张写死的说明图。
    - 「去设置」= primary（`exec()` 回 Accepted）；「稍后再说」= 取消语义。
    """

    CARD_W = 360
    BTN_W, BTN_H = 88, 34

    def __init__(self, parent, items):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(self.CARD_W)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("confirmCard")          # ★沿用五款弹窗那张卡片
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 24, 24, 20)
        card_lay.setSpacing(14)

        title = QLabel("欢迎使用 Ignotus Assistant")
        title.setWordWrap(True)
        title.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#0C447C; background:transparent;"
        )
        card_lay.addWidget(title)

        intro = QLabel("她装好了，但还差两件事才能开口。按下面的提示各做一步就行：")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#334155; font-size:13px; background:transparent;")
        card_lay.addWidget(intro)

        for item in items:
            card_lay.addWidget(self._build_item(item))

        tip = QLabel("做完之后这一步会自动打勾。也可以在「设置」里随时再打开这份引导。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#64748B; font-size:12px; background:transparent;")
        card_lay.addWidget(tip)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        later = QPushButton("稍后再说")
        later.setObjectName("cancelBtn")
        later.setCursor(Qt.PointingHandCursor)
        later.setFixedSize(self.BTN_W, self.BTN_H)
        later.clicked.connect(self.reject)
        btn_row.addWidget(later)
        go = QPushButton("去设置")
        go.setObjectName("confirmBtn")
        go.setCursor(Qt.PointingHandCursor)
        go.setFixedSize(self.BTN_W, self.BTN_H)
        go.clicked.connect(self.accept)
        btn_row.addWidget(go)
        card_lay.addLayout(btn_row)

        outer.addWidget(card)
        self.setStyleSheet(_CARD_FRAME_QSS + _CARD_BTN_QSS)

    @staticmethod
    def _build_item(item) -> QWidget:
        """一项 = 「✓/✗ + 标题（加粗）+ 一句怎么办」。

        ★这里的 ✓ 判据是 `item.ok`（= health 里的 `level == "ok"`），**不是**「有没有配置」
          之类的第二套逻辑 —— 引导页和自检页必须同一口径。
        """
        done = (item.level == health.LEVEL_OK)
        wrap = QWidget()
        wrap.setStyleSheet("background:transparent;")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(_status_dot(item.level), 0, Qt.AlignVCenter)
        name = QLabel(("%s　%s" % ("✓" if done else "•", item.title)))
        name.setStyleSheet(
            "font-size:13px; font-weight:bold; color:%s; background:transparent;"
            % ("#1E8E3E" if done else "#0C447C")
        )
        head.addWidget(name, 1)
        v.addLayout(head)

        body_text = item.detail if done else (item.fix or item.detail)
        body = QLabel("　　" + body_text)      # 缩进两格，与上面的圆点错开
        body.setWordWrap(True)
        pol = body.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Ignored)   # ★别顶宽卡片（见 _SettingRow 的教训）
        body.setSizePolicy(pol)
        body.setStyleSheet("color:#64748B; font-size:12px; background:transparent;")
        v.addWidget(body)
        return wrap

    @staticmethod
    def show_guide(parent, items, on_go=None):
        """弹一次引导。**非阻塞**（`open()`，不是 `exec()`）。

        ★★为什么必须非阻塞：`main()` 在启动末尾会调它，而 `exec()` 会**嵌一个模态事件循环**
          —— `main()` 从此回不去，`app.exec()` 也永远轮不到。那些「真跑一次 main() 再收尾」的
          探针（`tests/boot_probe.py` 等，它们的 `exec` 是跑一小段就 return 的替身）会当场挂死。
        ★`on_go`：点了「去设置」之后的回调（给 `MainWindow.show_first_run` 用）。
        ★返回值是那个弹窗对象（**不阻塞**，所以拿不到「点了哪个按钮」的同步结果）——
          非阻塞是这条路的硬约束，要结果就用 `on_go`。
        """
        dlg = FirstRunDialog(parent, items)
        if on_go is not None:
            dlg.finished.connect(lambda code: on_go() if code == QDialog.Accepted else None)
        dlg.open()
        return dlg


class SelfCheckDialog(_CardDialog):
    """**一键自检**（P2）：把 `health.check_all()` 的清单原样列出来。

    每条 = 「圆点 + 标题（加粗）+ 当前状态一句话」，不通过的再补一行**怎么办**。
    顶部那行汇总写「通过 N · 提示 N · 失败 N」，末尾给一颗「重新检查」（现算，不缓存）。

    ★宽度 440（同 `ChoiceDialog`）：每条要放「标题 + 一句状态 + 一句修复指引」，
      360 装不下、会频繁折行；高度给到 430，一屏能看全六条。
    """

    CARD_W, CARD_H = 440, 430
    BTN_W, BTN_H = 88, 34

    def __init__(self, parent, checks, on_recheck=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.CARD_W, self.CARD_H)
        self._on_recheck = on_recheck

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("confirmCard")
        card.setFixedSize(self.CARD_W, self.CARD_H)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 20, 24, 20)
        card_lay.setSpacing(12)

        title = QLabel("一键自检")
        title.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#0C447C; background:transparent;"
        )
        card_lay.addWidget(title)

        self._summary = QLabel("")
        self._summary.setStyleSheet("color:#64748B; font-size:12px; background:transparent;")
        card_lay.addWidget(self._summary)

        # 滚动区复用设置页那一套（胶囊滚动条 + 垂直常驻位 + body 右留 8px 呼吸位）
        _scroll, _body, self._body_lay = _panel_scroll(card_lay)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        self._recheck_btn = QPushButton("重新检查")
        self._recheck_btn.setObjectName("cancelBtn")
        self._recheck_btn.setCursor(Qt.PointingHandCursor)
        self._recheck_btn.setFixedSize(self.BTN_W, self.BTN_H)
        self._recheck_btn.clicked.connect(self._recheck)
        btn_row.addWidget(self._recheck_btn)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("confirmBtn")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(self.BTN_W, self.BTN_H)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        card_lay.addLayout(btn_row)

        outer.addWidget(card)
        self.setStyleSheet(_CARD_FRAME_QSS + _CARD_BTN_QSS + _PRESET_BOX_QSS)

        self.set_checks(checks)

    def set_checks(self, checks) -> None:
        """灌一份清单（`on_recheck` 回来之后也走它 —— 重新检查不重建弹窗，只换内容）。"""
        self._checks = list(checks)
        _clear_body(self._body_lay)
        for c in self._checks:
            self._body_lay.addWidget(self._build_row(c))
        self._body_lay.addStretch(1)
        ok, warn, fail = health.summary(self._checks)
        self._summary.setText("通过 %d · 提示 %d · 失败 %d" % (ok, warn, fail))
        # 一条都不失败时，把汇总染成绿色（成功提示，design.md 的 #1E8E3E）
        self._summary.setStyleSheet(
            "color:%s; font-size:12px; background:transparent;"
            % ("#1E8E3E" if not fail else "#64748B")
        )

    def _build_row(self, c) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("presetFieldBox")     # 借用「框住内容」那套皮（淡蓝底 + 淡蓝边）
        v = QVBoxLayout(wrap)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(_status_dot(c.level), 0, Qt.AlignVCenter)
        name = QLabel(c.title)
        name.setStyleSheet(
            "font-size:13px; font-weight:bold; color:%s; background:transparent;"
            % _HL_COLORS.get(c.level, "#334155")
        )
        head.addWidget(name, 1)
        v.addLayout(head)

        detail = QLabel(c.detail)
        detail.setWordWrap(True)
        pol = detail.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Ignored)   # ★别顶宽卡片
        detail.setSizePolicy(pol)
        detail.setStyleSheet("color:#334155; font-size:12px; background:transparent;")
        v.addWidget(detail)

        if c.fix:
            fix = QLabel("怎么办：" + c.fix)
            fix.setWordWrap(True)
            pol = fix.sizePolicy()
            pol.setHorizontalPolicy(QSizePolicy.Ignored)
            fix.setSizePolicy(pol)
            fix.setStyleSheet("color:#378ADD; font-size:12px; background:transparent;")
            v.addWidget(fix)
        return wrap

    def _recheck(self):
        """「重新检查」：向调用方**再要一份清单**（现算，不吃缓存）。"""
        if self._on_recheck is None:
            return
        self.set_checks(self._on_recheck())

    @staticmethod
    def run_check(parent, checks, on_recheck=None):
        dlg = SelfCheckDialog(parent, checks, on_recheck=on_recheck)
        dlg.exec()


class UpdateDialog(_CardDialog):
    """**检查更新**（P2）：查 GitHub 最新 release，比 `app.__version__`。

    ★★**联网在后台线程里跑，主线程只轮询结果**：一个 HTTP 请求最长要等到超时（6s），
      直接在 UI 线程里调会把界面冻住 6 秒。线程把三态结果写进**普通 dict**、
      QTimer 每 120ms 读一次 —— 与 `GeneralPanel` 轮询下载进度**同一套写法**，
      **不发 Qt 信号**（本项目的铁律：跨线程只传 str/int）。

    ★四态由 `update.check_latest` 给出，文案在这里成形：
        update → 「发现新版本 vX」+「前往下载」
        latest → 「已是最新版本（vX）」
        none   → 「仓库还没有发布版本」（**不是错误**：新仓库的正常状态）
        error  → 「检查失败：…」（不吓人，可重试）
    """

    CARD_W, CARD_H = 400, 230
    BTN_W, BTN_H = 88, 34
    POLL_MS = 120

    def __init__(self, parent, current, checker=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.CARD_W, self.CARD_H)
        # ★`checker` 可注入（测试喂一个不下网的假实现）；默认走 update.check_latest
        self._checker = checker or (lambda: update.check_latest(current))
        # 线程 → 主线程的唯一通道：一个只含 str 的 dict（轮询读，不发信号）
        self._result = {"state": "", "detail": "", "url": ""}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("confirmCard")
        card.setFixedSize(self.CARD_W, self.CARD_H)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 20, 24, 20)
        card_lay.setSpacing(12)

        title = QLabel("检查更新")
        title.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#0C447C; background:transparent;"
        )
        card_lay.addWidget(title)

        self._ver = QLabel("当前版本：v%s" % current)
        self._ver.setStyleSheet("color:#64748B; font-size:12px; background:transparent;")
        card_lay.addWidget(self._ver)

        self._msg = QLabel("正在检查…")
        self._msg.setWordWrap(True)
        pol = self._msg.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Ignored)
        self._msg.setSizePolicy(pol)
        self._msg.setStyleSheet("color:#334155; font-size:13px; background:transparent;")
        card_lay.addWidget(self._msg)

        self._extra = QLabel("")
        self._extra.setWordWrap(True)
        pol = self._extra.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Ignored)
        self._extra.setSizePolicy(pol)
        self._extra.setStyleSheet("color:#64748B; font-size:12px; background:transparent;")
        card_lay.addWidget(self._extra)

        card_lay.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        self._go = QPushButton("前往下载")
        self._go.setObjectName("confirmBtn")
        self._go.setCursor(Qt.PointingHandCursor)
        self._go.setFixedSize(self.BTN_W + 16, self.BTN_H)
        self._go.clicked.connect(self._open_page)
        self._go.setVisible(False)
        btn_row.addWidget(self._go)
        self._retry = QPushButton("重试")
        self._retry.setObjectName("cancelBtn")
        self._retry.setCursor(Qt.PointingHandCursor)
        self._retry.setFixedSize(self.BTN_W, self.BTN_H)
        self._retry.clicked.connect(self._start)
        self._retry.setVisible(False)
        btn_row.addWidget(self._retry)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("cancelBtn")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(self.BTN_W, self.BTN_H)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        card_lay.addLayout(btn_row)

        outer.addWidget(card)
        self.setStyleSheet(_CARD_FRAME_QSS + _CARD_BTN_QSS)

        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)

    # ---- 开始 / 轮询 ----
    def start(self):
        """弹窗显示之后由调用方（或 `show_check`）调一次。"""
        self._start()
        return self.exec()

    def _start(self):
        """起一个后台线程跑检查（**已有线程在跑就不重复起**）。"""
        if self._result.get("state"):
            self._result = {"state": "", "detail": "", "url": ""}
        self._msg.setText("正在检查…")
        self._extra.setText("")
        self._go.setVisible(False)
        self._retry.setVisible(False)

        def work():
            try:
                state, detail, url = self._checker()
            except Exception as e:  # noqa: BLE001  线程里绝不许漏异常（会静默死）
                state, detail, url = update.STATE_ERROR, "检查更新失败：%s" % e, update.RELEASES_PAGE
            # ★只写字符串（跨线程铁律）；主线程在 `_poll` 里取
            self._result["state"] = str(state)
            self._result["detail"] = str(detail)
            self._result["url"] = str(url)

        threading.Thread(target=work, daemon=True).start()
        self._timer.start()

    def _poll(self):
        state = self._result.get("state") or ""
        if not state:
            return
        self._timer.stop()
        detail = self._result.get("detail") or ""
        if state == update.STATE_UPDATE:
            self._msg.setText("发现新版本：%s" % detail)
            self._msg.setStyleSheet("color:#1E8E3E; font-size:13px; background:transparent;")
            self._extra.setText("可到 GitHub Releases 下载新的成品包（解压覆盖即可）。")
            self._go.setVisible(True)
        elif state == update.STATE_LATEST:
            self._msg.setText("已是最新版本（%s）。" % detail)
            self._msg.setStyleSheet("color:#1E8E3E; font-size:13px; background:transparent;")
        elif state == update.STATE_NONE:
            self._msg.setText(detail)
            self._msg.setStyleSheet("color:#334155; font-size:13px; background:transparent;")
            self._extra.setText("等作者发布第一个版本后，这里就能检查到更新了。")
        else:
            self._msg.setText(detail)
            self._msg.setStyleSheet("color:#C0392B; font-size:13px; background:transparent;")
            self._retry.setVisible(True)

    def _open_page(self):
        url = self._result.get("url") or update.RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(url))

    def closeEvent(self, event):
        self._timer.stop()          # 关窗就停表（线程是 daemon，自己会退出）
        super().closeEvent(event)

    @staticmethod
    def show_check(parent, current, checker=None):
        dlg = UpdateDialog(parent, current, checker=checker)
        dlg.start()
        return dlg


class DangerCountdownDialog(QDialog):
    """危险操作（关机 / 重启 / 注销 / 锁屏）的**屏幕正中央**倒计时卡片（200×150）。

    - 与 `ConfirmDialog` / `InputDialog` / `ApiFormDialog` **共用同一张卡片皮肤**（design.md 4.5）；
    - 但它**不是**确认框：**非模态、不抢焦点**，一行两个按钮（左「立刻执行」/ 右「取消」）由它自己
      画出来、自己命中测试 —— 点击只是叫回调，真正执行 / 中止由 `main.py` 注册进来（GUI 不认识 `tools`）；
    - 左边那个按钮是**通用**的「立刻执行」（关机 / 重启 / 注销都用它），不随操作改文案 ——
      用户口径是「立刻执行」，这样它不必跟着排的是哪种危险操作变；
    - **自绘**的原因：入场要求「**整卡**从 50% 长到 100%」，Qt widgets 里子控件与字体都不会跟着缩
      （`setFixedSize` 还会挡住改几何）—— 只能一条 `QPainter` 链把卡片 / 文字 / 两个按钮全画出来，
      `paintEvent` 之外只剩命中测试（见 design.md 4.5 与 docs/02 §8.7）；
    - 窗口 **200×165**：多出来的 15px 全在卡片**下方**，给「自下而上 15px」的弹出位移用
      （起点正好贴窗口下沿）；卡片本体在窗口**顶部**，所以摆位按卡片高的一半算即可；
    - 每次刷新**只改数字**（`set_countdown()`），窗口的重建 / 落位 / 入场动画由
      `MainWindow.show_danger_countdown()` 一处管。
    """

    SIZE = (DLG_CARD_W, DLG_CARD_H)                        # 卡片本体（用户口径 200×150）
    WINDOW_SIZE = (DLG_CARD_W, DLG_CARD_H + DLG_POP_DY)    # 窗口：卡片高 + 弹出位移那 15px

    def __init__(self, parent=None):
        super().__init__(parent)
        # 置顶 + 不进任务栏：倒计时期间用户可能已经切到别的窗口去了
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)   # 不抢焦点：用户照常打自己的字
        self.setModal(False)
        self.setFixedSize(*self.WINDOW_SIZE)
        self.setMouseTracking(True)                      # 按钮 hover 要跟着鼠标走

        # 字体：标题 13px Bold / 秒数 34px Bold / 单位 13px / 按钮 12px（确认那个加粗）
        self._title_font = QFont(self.font())
        self._title_font.setPixelSize(13)
        self._title_font.setBold(True)
        self._num_font = QFont(self.font())
        self._num_font.setPixelSize(34)
        self._num_font.setBold(True)
        self._unit_font = QFont(self.font())
        self._unit_font.setPixelSize(13)
        self._btn_font = QFont(self.font())
        self._btn_font.setPixelSize(12)
        self._btn_font_bold = QFont(self.font())
        self._btn_font_bold.setPixelSize(12)
        self._btn_font_bold.setBold(True)

        self._label = ""
        self._remaining = 0
        self._cancelled = False
        # `_pop` 一个量同时管三样：不透明度 / 缩放 / 自下而上的位移（映射见 `_pop_frame` + `paintEvent`）
        self._pop = 1.0
        self._anim = None
        self._anim_kind = None      # "show" / "hide"：判「淡出还在不在跑」不能只看 `_pop`
        self._hover = None          # "run" / "cancel"
        self._pressed = None
        self._run_cb = None
        self._cancel_cb = None
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(DLG_CANCEL_HOLD_MS)
        self._hold_timer.timeout.connect(self.hide_with_fade)

    # ---- 只读（给测试 / 别的模块看）----
    @property
    def title_text(self) -> str:
        return f"已取消{self._label}" if self._cancelled else f"{self._label}倒计时"

    @property
    def number_text(self) -> str:
        return self.shown_text()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def pop(self) -> float:
        return self._pop

    @property
    def buttons(self):
        """(「立刻关机」, 「取消」) 两个按钮的矩形（卡片坐标系；自绘也要能断言 / 命中）。"""
        return self._button_rects()

    def shown_text(self) -> str:
        """画笔真正画出去的那串字 = 剩余秒数。

        **取消态也保留**（用户 2026-09-18 三改）：红态只是「停止不动」，不是「数字消失」——
        数字停在取消那一刻的读数，让人一眼看见「就是在还剩 23 秒的时候取消的」。
        `set_countdown()` 在取消态直接返回，所以这个数**冻住**了，不会跟着每秒的 tick 走。
        """
        return str(self._remaining)

    def button_at(self, pos):
        """命中测试：返回 "run" / "cancel" / None。"""
        run, cancel = self._button_rects()
        x, y = float(pos.x()), float(pos.y())
        if run.contains(x, y):
            return "run"
        if cancel.contains(x, y):
            return "cancel"
        return None

    def set_countdown(self, label: str, remaining) -> None:
        """刷新文案：标题 =「{操作}倒计时」、数字 = 剩余秒数（**只改真的变了的那个**）。"""
        if self._cancelled:
            return
        label = str(label or "").strip()
        remaining = max(0, int(remaining))
        if (label, remaining) == (self._label, self._remaining):
            return
        self._label, self._remaining = label, remaining
        self.update()

    def set_callbacks(self, run_cb, cancel_cb) -> None:
        """把两个按钮接到 `main.py`（点击 → 立刻执行 / 取消）。"""
        self._run_cb = run_cb
        self._cancel_cb = cancel_cb

    # ---- 取消态：转红 + 藏按钮（**保留读数**）+ 撑 1.5s 再淡出 ----
    def show_cancelled(self) -> None:
        """已取消：整体转红、两个按钮消失、**剩下的秒数留在原地不动**，保持 1.5s 再淡出。

        排版与倒计时态**完全一致**（标题 / 数字 / 「秒」都在原来的位置），只是把下方那行按钮去掉 ——
        所以这里不需要动布局，画的时候跳过按钮行即可（见 `paintEvent`）。
        """
        if self._cancelled or not self.isVisible():
            return
        self._cancelled = True
        self._hover = None
        self._pressed = None
        self.setCursor(Qt.ArrowCursor)
        self.update()
        self._hold_timer.start()

    def reset_cancelled(self) -> None:
        """回到蓝态（新的排程进来时用）：取消 hold 计时、按钮重新出现。"""
        self._hold_timer.stop()
        self._cancelled = False
        self._hover = None
        self._pressed = None
        self.update()

    # ---- 动画：0→1 淡入、1→0 淡出（同一套映射，方向正好相反）----
    @staticmethod
    def _pop_frame(v):
        """`v` 0→1：不透明度、自下而上的位移、缩放三件套。"""
        v = float(v)
        return (v, DLG_POP_DY * (1.0 - v), DLG_MIN_SCALE + (1.0 - DLG_MIN_SCALE) * v)

    def _set_pop(self, v) -> None:
        self._pop = float(v)
        self.update()

    def _run(self, a0, a1, on_done):
        anim = QVariantAnimation(self)
        anim.setStartValue(float(a0))
        anim.setEndValue(float(a1))
        anim.setDuration(DLG_ANIM_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._set_pop)
        anim.finished.connect(on_done)
        anim.start()
        return anim

    def start_show_anim(self) -> None:
        """淡入 0.5s：50% → 100% + 透明 → 不透明 + **自下而上 15px**。"""
        self._stop_anim()
        self._pop = 0.0
        self._anim_kind = "show"
        self._anim = self._run(0.0, 1.0, self._on_show_done)

    def hide_with_fade(self) -> None:
        """淡出 0.5s：与淡入**完全相反**（100% → 50%、1 → 0、**向下** 15px），归零后 hide()。"""
        if not self.isVisible():
            self._hold_timer.stop()
            self._set_pop(0.0)
            self.hide()
            return
        self._hold_timer.stop()
        self._stop_anim()
        self._anim_kind = "hide"
        self._anim = self._run(self._pop, 0.0, self._on_hide_done)

    def is_fading_out(self) -> bool:
        return self._anim_kind == "hide"

    def _on_show_done(self) -> None:
        # 先 `_stop_anim()`：这个回调平时由 `finished` 触发（那时它已经跑完，stop 是空操作），
        # 但测试 / 截图工具会**手工**叫它 —— 那时动画还在跑，只把 `_anim` 置空会让它变成
        # 脱缰的孤儿，0.5s 后回头再打一次，把后面手工摆的那一帧盖掉（在 `_PetToast` 上真踩过）。
        self._stop_anim()
        self._set_pop(1.0)

    def _on_hide_done(self) -> None:
        self._stop_anim()
        self._set_pop(0.0)
        self.hide()

    def _stop_anim(self) -> None:
        self._anim_kind = None
        if self._anim is not None:
            self._anim.stop()
            self._anim = None

    # ---- 配色（红态优先）----
    def _border_color(self) -> str:
        return DLG_CARD_BORDER_RED if self._cancelled else DLG_CARD_BORDER

    def _title_color(self) -> str:
        return DLG_TITLE_INK_RED if self._cancelled else DLG_TITLE_INK

    def _number_color(self) -> str:
        # 红态的数字**照样画**（冻在取消那一刻），只是换成红色
        return DLG_NUM_RED if self._cancelled else DLG_NUM_BLUE

    # ---- 布局（自绘：矩形只有一个来源，画与命中测试共用）----
    def _button_rects(self):
        y = float(DLG_CARD_H - DLG_CARD_PAD - DLG_BTN_H)
        x = (DLG_CARD_W - (2 * DLG_BTN_W + DLG_BTN_GAP)) / 2.0
        run = QRectF(x, y, DLG_BTN_W, DLG_BTN_H)
        cancel = QRectF(x + DLG_BTN_W + DLG_BTN_GAP, y, DLG_BTN_W, DLG_BTN_H)
        return run, cancel

    def _num_bottom(self) -> float:
        return float(DLG_CARD_H - DLG_CARD_PAD - DLG_BTN_H) - 12.0

    def _paint_button(self, p, rect: QRectF, text: str, *, primary: bool) -> None:
        key = "run" if primary else "cancel"
        active = self._hover == key or self._pressed == key
        if primary:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(DLG_BTN_PRIMARY_HOVER if active else DLG_BTN_PRIMARY))
            ink = QColor("#FFFFFF")
        else:
            p.setPen(QPen(QColor(DLG_BTN_GHOST_BORDER), 1))
            p.setBrush(QColor(DLG_BTN_GHOST_HOVER if active else "#FFFFFF"))
            ink = QColor(DLG_MUTED)
        r = QRectF(rect)
        if not primary:
            r = r.adjusted(0.5, 0.5, -0.5, -0.5)   # 笔宽居中 -> 内缩半个笔宽
        p.drawRoundedRect(r, DLG_BTN_RADIUS, DLG_BTN_RADIUS)
        p.setPen(ink)
        p.setFont(self._btn_font_bold if primary else self._btn_font)
        p.drawText(rect, Qt.AlignCenter, text)

    def paintEvent(self, event):
        # 布局先算完再套绘制链（`translate`/`scale` 会改画笔坐标系，先算后画才对得上）
        w, h = float(DLG_CARD_W), float(DLG_CARD_H)
        title = self.title_text
        number = self.shown_text()
        run_rect, cancel_rect = self._button_rects()
        num_bottom = self._num_bottom()

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setOpacity(self._pop)
        # 缩放原点 = 卡片**下边中点**（卡片像是从下往上长出来），再整体自下而上平移 15px
        cx, base = w / 2.0, h
        dy = DLG_POP_DY * (1.0 - self._pop)
        k = DLG_MIN_SCALE + (1.0 - DLG_MIN_SCALE) * self._pop
        p.translate(cx, base + dy)
        p.scale(k, k)
        p.translate(-cx, -base)

        card = QRectF(0.0, 0.0, w, h).adjusted(0.5, 0.5, -0.5, -0.5)   # 1px 边框居中
        p.setPen(QPen(QColor(self._border_color()), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(card, DLG_CARD_RADIUS, DLG_CARD_RADIUS)

        p.setPen(QColor(self._title_color()))
        p.setFont(self._title_font)
        tm = QFontMetrics(self._title_font)
        p.drawText(QRectF(0.0, float(DLG_CARD_PAD), w, float(tm.height())),
                   Qt.AlignHCenter | Qt.AlignTop, title)

        if number:
            nm = QFontMetrics(self._num_font)
            um = QFontMetrics(self._unit_font)
            nw = float(nm.horizontalAdvance(number))
            uw = float(um.horizontalAdvance("秒"))
            x0 = (w - (nw + 2.0 + uw)) / 2.0
            p.setPen(QColor(self._number_color()))
            p.setFont(self._num_font)
            p.drawText(QRectF(x0, num_bottom - nm.height(), nw, float(nm.height())),
                       Qt.AlignLeft | Qt.AlignBottom, number)
            p.setPen(QColor(DLG_MUTED))
            p.setFont(self._unit_font)
            p.drawText(QRectF(x0 + nw + 2.0, num_bottom - um.height(), uw, float(um.height())),
                       Qt.AlignLeft | Qt.AlignBottom, "秒")

        if not self._cancelled:
            self._paint_button(p, run_rect, DLG_BTN_RUN_TEXT, primary=True)
            self._paint_button(p, cancel_rect, DLG_BTN_CANCEL_TEXT, primary=False)
        p.end()

    # ---- 鼠标：hover 换手型、按下 / 抬起落在同一个按钮才触发 ----
    def mouseMoveEvent(self, event):
        btn = None if self._cancelled else self.button_at(event.position().toPoint())
        if btn != self._hover:
            self._hover = btn
            self.setCursor(Qt.PointingHandCursor if btn else Qt.ArrowCursor)
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover is not None:
            self._hover = None
            self.setCursor(Qt.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self._cancelled:
            self._pressed = self.button_at(event.position().toPoint())
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self._cancelled:
            btn = self.button_at(event.position().toPoint())
            pressed, self._pressed = self._pressed, None
            self.update()
            if btn is not None and btn == pressed:
                cb = self._run_cb if btn == "run" else self._cancel_cb
                if callable(cb):
                    cb()
        super().mouseReleaseEvent(event)


class _Segment(QWidget):
    """标题栏三等分容器：重写 sizeHint 为 0，配合 stretch 严格均分三段空间。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def sizeHint(self):
        return QSize(0, 32)

    def minimumSizeHint(self):
        return QSize(0, 32)


class _ShadowBar(QWidget):
    """竖向阴影条：左侧（靠左栏）最深，向右渐变到透明。宽度可调（默认 3px）。"""

    def __init__(self, width: int = 3, parent=None):
        super().__init__(parent)
        self.setFixedWidth(width)

    def paintEvent(self, event):
        p = QPainter(self)
        # 先填充白色背景，避免半透明渐变混合到未初始化的黑底
        p.fillRect(self.rect(), QColor(255, 255, 255))
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, self.width(), 0)
        c0 = QColor(0, 0, 0)
        c0.setAlpha(60)  # 左深
        c1 = QColor(0, 0, 0)
        c1.setAlpha(0)   # 右透明
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRect(self.rect())
        p.end()


class _ColorPanel(QFrame):
    """背景色自绘的容器。

    左栏底色需要在「白 ↔ 浅蓝」之间做 260ms 插值。若用 setStyleSheet 改 QSS，
    每一帧都会触发整棵子树的样式重算 + 布局激活，而布局激活会把正在做位移动画的
    子页面 geometry 重置回满尺寸 —— 表现为切换末尾的画面回弹抽搐。改为 paintEvent
    自绘后，改色只是 set_bg() + update()，零样式重算、零布局激活。
    """

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)  # 底色由 paintEvent 负责
        self._bg = QColor(*color)

    def set_bg(self, color):
        c = QColor(*color)
        if c != self._bg:
            self._bg = c
            self.update()

    def bg_rgb(self):
        return (self._bg.red(), self._bg.green(), self._bg.blue())

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self._bg)
        p.end()


class _SlideStack(QWidget):
    """页面宿主：手动管理页面显隐与 geometry，替代 QStackedWidget。

    QStackedLayout 在任何一次布局激活时都会把当前页 geometry 重置成满尺寸，
    于是在做「平移入场」动画时会出现「动画设值 → 布局重置 → 动画再设值」的
    逐帧对抗，肉眼看到的就是画面抖动/回弹。这里自己摆放页面即可彻底避免。

    保留 QStackedWidget 的常用接口（addWidget / count / widget / indexOf /
    currentIndex / currentWidget / setCurrentIndex），上层代码无需改动。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self._pages = []
        self._index = -1
        self._sliding = None   # 正在被动画驱动的页面：动画期间不做满尺寸对齐

    # ---- 接口 ----
    def addWidget(self, w):
        w.setParent(self)
        w.setGeometry(0, 0, self.width(), self.height())
        w.setVisible(False)
        self._pages.append(w)
        if self._index < 0:
            self._index = 0
            w.setGeometry(0, 0, self.width(), self.height())
            w.setVisible(True)
        return len(self._pages) - 1

    def count(self):
        return len(self._pages)

    def widget(self, i):
        return self._pages[i] if 0 <= i < len(self._pages) else None

    def indexOf(self, w):
        try:
            return self._pages.index(w)
        except ValueError:
            return -1

    def currentIndex(self):
        return self._index

    def currentWidget(self):
        return self.widget(self._index)

    def setCurrentIndex(self, i):
        if not 0 <= i < len(self._pages) or i == self._index:
            return
        old = self.currentWidget()
        self._index = i
        new = self._pages[i]
        new.setGeometry(0, 0, self.width(), self.height())
        new.setVisible(True)
        new.raise_()
        if old is not None and old is not new:
            old.setVisible(False)

    # ---- 动画协作 ----
    def begin_slide(self, page):
        """标记 page 交给动画驱动，期间 resizeEvent 不再抢占它的 geometry。"""
        self._sliding = page

    def end_slide(self, page):
        """动画收尾：解锁并对齐到宿主实际尺寸，保证停位精确。"""
        if self._sliding is page:
            self._sliding = None
        page.setGeometry(0, 0, self.width(), self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cur = self.currentWidget()
        if cur is not None and cur is not self._sliding:
            cur.setGeometry(0, 0, self.width(), self.height())


class _ToolTip(QLabel):
    """自定义悬浮提示：白底 + 灰边、贴合文字，带自下而上 5px 出现动画、淡出动画。

    ⚠️ **不要退回 Qt 自带的 `QToolTip`**：默认深色 tooltip 在本机会被渲染成一条「黑条」
    （用户明确要求去掉），所以全项目统一用这个自绘控件。当前唯一使用者是左侧悬浮操作按钮
    （`_ActionButton`，悬停 0.6s 出现）。

    📌 历史备注：2026-09-16 曾把「免 UAC」的说明做成**聊天气泡皮肤**（蓝边 + 浅蓝底 +
    深蓝字、280px 钉宽换行）+ `show_above()`（贴控件上方、右端对齐）；同日用户改为
    **只保留确认弹窗**，悬停气泡整体删除，相关代码（换肤参数 / 钉宽换行 / `show_above` /
    `cancel_hide`）一并移除。若将来还要做换行气泡，**高度绝不能用 `heightForWidth()`**
    （QSS 生效前后返回值不一致），改用 `QFontMetrics.boundingRect(...) + 2·pad_y`；
    完整配方见 `design.md` §4.14 与 `devlog/2026-09-16.md` §八 / §九。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 提示绝不能吃鼠标事件：否则它盖在触发它的控件上会引发 Leave → 自己把自己抖掉
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignCenter)
        self._bg = QColor("#FFFFFF")
        self._border = QColor("#CBD5E1")
        self._radius = 6.0
        # 背景用 paintEvent 绘制（QSS background 在 QLabel 上不可靠）
        self.setStyleSheet(
            "color:#000000; padding:4px 8px; font-size:12px; background:transparent;"
        )
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._op_anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._op_anim.setDuration(200)
        self._op_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._pos_anim = QPropertyAnimation(self, b"pos", self)
        self._pos_anim.setDuration(200)
        self._pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self.hide()

    def paintEvent(self, event):
        # 画底 + 边 + 圆角文本框
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self._border, 1))
        p.setBrush(self._bg)
        r = self._radius
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), r, r)
        p.end()
        super().paintEvent(event)  # 画文字

    def _clamp(self, pos, size):
        """把提示拉回屏幕内（贴近屏幕边缘时不至于露到屏幕外）。"""
        scr = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if scr is None:
            return pos
        a = scr.availableGeometry()
        x = min(max(pos.x(), a.left() + 8), a.right() - size.width() - 8)
        y = min(max(pos.y(), a.top() + 8), a.bottom() - size.height() - 8)
        return QPoint(x, y)

    def _present(self, target):
        """从 target 下移 5px、全透明处，自下而上淡入到位。"""
        self.move(target.x(), target.y() + 5)
        self._effect.setOpacity(0.0)
        self.show()
        self._pos_anim.stop()
        self._pos_anim.setStartValue(QPoint(target.x(), target.y() + 5))
        self._pos_anim.setEndValue(target)
        self._op_anim.stop()
        self._op_anim.setStartValue(0.0)
        self._op_anim.setEndValue(1.0)
        self._pos_anim.start()
        self._op_anim.start()

    def show_text(self, anchor: QPoint, text: str):
        """anchor 为按钮左下角全局坐标，提示显示在其左下角下方。"""
        self.setText(text)
        self.adjustSize()  # 文字与边框一起确定尺寸，避免先空白后撑大的闪烁
        target = QPoint(anchor.x() - 5, anchor.y() + 8)  # 按钮左下角（左移 5px、下移 8px）
        self._present(self._clamp(target, self.size()))

    def fade_out(self):
        """淡出（不平移），动画结束后隐藏。"""
        self._hide_timer.stop()
        self._op_anim.stop()
        self._op_anim.setStartValue(self._effect.opacity())
        self._op_anim.setEndValue(0.0)
        self._op_anim.start()
        self._hide_timer.start(200)

    def hide_now(self):
        """立即隐藏（无动画）。"""
        self._op_anim.stop()
        self._pos_anim.stop()
        self._hide_timer.stop()
        self._effect.setOpacity(0.0)
        self.hide()


class _ActionButton(QPushButton):
    """悬浮操作按钮：hover 0.6s 后显示提示；点击立即消失；移出淡出。"""

    def __init__(self, icon_path, tip, parent=None):
        super().__init__(parent)
        self._tip = tip
        self.setIcon(QIcon(icon_path))
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(36, 36)
        self.setStyleSheet(
            "QPushButton{background:#E6F1FB; border:none; border-radius:8px;}"
            "QPushButton:hover{background:#C7E1FB;}"
        )
        self._tooltip = _ToolTip(parent)
        # 悬停 0.6s 后再显示提示
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show_tooltip)

    def _show_tooltip(self):
        anchor = self.mapToGlobal(self.rect().bottomLeft())
        self._tooltip.show_text(anchor, self._tip)

    def enterEvent(self, e):
        super().enterEvent(e)
        self._show_timer.start(600)  # 悬停 0.6s 再出现

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._show_timer.stop()  # 取消待显示
        self._tooltip.fade_out()  # 移出淡出

    def mousePressEvent(self, e):
        self._show_timer.stop()  # 取消待显示
        self._tooltip.hide_now()  # 点击立即消失
        super().mousePressEvent(e)


class _SmoothScrollBar(QScrollBar):
    """带 0.2s hover 颜色渐变的胶囊形滚动条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = 0.0  # 0=默认 #DCDCDC，1=hover #C9C9C9
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(200)
        self._anim.valueChanged.connect(self._apply)
        self._apply(0.0)

    def _apply(self, t):
        self._hover = float(t)
        r = int(220 + (201 - 220) * t)  # #DC → #C9
        g = int(220 + (201 - 220) * t)
        b = int(220 + (201 - 220) * t)
        self.setStyleSheet(
            "QScrollBar:vertical { background:transparent; width:8px; margin:0px; }"
            f"QScrollBar::handle:vertical {{ background:rgb({r},{g},{b}); border-radius:4px; min-height:30px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; width:0px; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }"
        )

    def paintEvent(self, e):  # noqa: N802 (Qt 命名)
        """**没有滚动量时整条不画。**

        `_panel_scroll` 把滚动条策略钉成 `AlwaysOn`（防卡片右边框跳变），短页面
        （`maximum() <= minimum()`）下 Qt 会画一根占满全高的滑块 —— 那就是一条常驻灰柱。
        直接 return 即可：滑块 / 轨道在 QSS 里都是 `background:transparent`，非不透明子控件
        的底由父级（白色面板）透出来，不会有残影。
        """
        if self.maximum() <= self.minimum():
            return
        super().paintEvent(e)

    def enterEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(e)


class _ScrollTopButton(QPushButton):
    """面板标题行里的「回到顶部」：滚过一定距离才淡入，点击 0.3s 平滑滚回顶部。

    - **显隐**：停在顶部（`value < SHOW_AT`）时收起，往下滚动超过 `SHOW_AT` 后淡入。
    - **不顶动邻居**：它排在标题行 `addStretch(1)` 的**右侧**（在「恢复默认」左边），
      所以隐藏 / 出现都不会让「恢复默认」左右移动 —— 不需要靠"永远占位"来防抖。
    - **回顶**：`QVariantAnimation` 逐帧写 `QScrollBar.value`（300ms OutCubic）。
      起点取**当前值**，连点两次不会先跳回上一次的起点。
    """

    SHOW_AT = 40      # 往下滚过这么多像素才出现
    FADE_MS = 200     # 淡入淡出时长（与分组「添加按钮」同一套）
    SCROLL_MS = 300   # 回到顶部的滚动时长（用户指定 0.3s）

    def __init__(self, scroll: QScrollArea, parent=None):
        super().__init__("回到顶部", parent)
        self.setObjectName("outlineBtn")          # 与「恢复默认」同款蓝色镂空
        self.setCursor(Qt.PointingHandCursor)
        self._scroll = scroll
        self._bar = scroll.verticalScrollBar()

        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(0.0)
        self.setGraphicsEffect(self._eff)
        self._fade = QPropertyAnimation(self._eff, b"opacity", self)
        self._fade.setDuration(self.FADE_MS)
        self._fade.finished.connect(self._on_fade_done)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self.SCROLL_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._apply_scroll)

        self._want_visible = False
        self.setVisible(False)                    # 初始在顶部 → 不显示
        self.clicked.connect(self.scroll_to_top)
        self._bar.valueChanged.connect(self._sync_visible)
        self._sync_visible(animate=False)

    # ---- 显隐 ----

    def _sync_visible(self, _value=None, animate=True):
        self.set_shown(self._bar.value() >= self.SHOW_AT, animate=animate)

    def set_shown(self, visible: bool, animate: bool = True):
        visible = bool(visible)
        if visible == self._want_visible and self.isVisible() == visible:
            return
        self._want_visible = visible
        self._fade.stop()        # stop 不触发 finished，不会误隐藏
        if not animate:
            self._eff.setOpacity(1.0 if visible else 0.0)
            self.setVisible(visible)
            return
        if visible:
            self.setVisible(True)   # 先可见再淡入
        self._fade.setStartValue(self._eff.opacity())
        self._fade.setEndValue(1.0 if visible else 0.0)
        self._fade.start()

    def _on_fade_done(self):
        """淡出结束后真正隐藏（否则透明按钮仍占位、仍可点击）。"""
        if not self._want_visible:
            self.setVisible(False)

    def is_shown(self) -> bool:
        """逻辑上是否处于「显示」状态（测试用；不等同于 isVisible）。"""
        return bool(self._want_visible)

    # ---- 回顶 ----

    def scroll_to_top(self):
        self._anim.stop()
        self._anim.setStartValue(self._bar.value())
        self._anim.setEndValue(self._bar.minimum())
        self._anim.start()

    def _apply_scroll(self, value):
        self._bar.setValue(int(value))


class _HoverRow:
    """行 hover 渐变（白 → 淡蓝）的公共实现：4 个行类共用同一套 `enterEvent` / `leaveEvent`。

    ★子类必须：① 在 `__init__` 里把 `self._hover` 置 0；② 用 `_make_hover_anim(...)`
    建好 `self._hover_anim`；③ 提供 `_apply_bg(t)`（把 hover 强度落到样式表上）。
    `super()` 沿 MRO 走到后面的 QFrame / QWidget —— 与原先「各自直接继承 QFrame」同一条路。
    """

    def _make_hover_anim(self, duration=200):
        """`_hover` 的 0↔1 渐变：`valueChanged` 直接喂给 `_apply_bg(t)`。"""
        anim = QVariantAnimation(self)
        anim.setDuration(duration)
        anim.valueChanged.connect(self._apply_bg)
        return anim

    def set_round_bottom(self, flag=True):
        """标记为内容区末行：底部圆角，与外框圆角对齐（否则 hover 色块会顶出圆角）。"""
        self._round_bottom = bool(flag)
        self._apply_bg(self._hover)

    def enterEvent(self, e):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(e)


class _ApiRow(_HoverRow, QFrame):
    """API 列表行：默认折叠只显示名称；hover 淡蓝渐变 0.2s；点击展开双倍显示 key + 编辑/删除按钮；删除需确认。"""
    COLLAPSED_H = 60
    EXPANDED_H = 120

    def __init__(self, entry: dict, panel, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.panel = panel
        self._hover = 0.0  # 0=白, 1=淡蓝
        self._expanded = False
        self.setObjectName("apiRow")
        self._apply_bg(0.0)
        self.setCursor(Qt.PointingHandCursor)
        # 主体布局：两行各 60px 高（未展开只显示第 1 行，展开显示两行）
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 0, 12, 0)
        v.setSpacing(0)
        # 第 1 行：API 名称，60px 高，垂直居中
        self._name_lbl = QLabel(f"<b>{entry.get('name','')}</b>")
        self._name_lbl.setStyleSheet("color:#0C447C; font-size:14px; background:transparent;")
        self._name_lbl.setFixedHeight(60)
        self._name_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        v.addWidget(self._name_lbl)
        # 第 2 行：key + 编辑/删除，60px 高，内容垂直居中
        self._expand = QWidget()
        self._expand.setStyleSheet("background:transparent;")
        self._expand.setVisible(False)
        self._expand.setFixedHeight(60)
        hl = QHBoxLayout(self._expand)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        _model = (entry.get("model") or DEFAULT_MODEL).strip()
        self._key_lbl = QLabel(f"{mask_key(entry.get('api_key', ''))}   ·   模型 {_model}")
        self._key_lbl.setStyleSheet("color:#64748B; background:transparent;")
        self._key_lbl.setToolTip(
            f"接口地址：{entry.get('base_url') or DEFAULT_BASE_URL}\n模型名：{_model}"
        )
        hl.addWidget(self._key_lbl, 1, Qt.AlignVCenter)
        edit_btn = QPushButton("编辑")
        edit_btn.setObjectName("outlineBtn")
        edit_btn.setFixedWidth(64)
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.clicked.connect(lambda _=False: panel._edit_row(entry, self))
        hl.addWidget(edit_btn, 0, Qt.AlignVCenter)
        del_btn = QPushButton("删除")
        del_btn.setObjectName("dangerBtn")
        del_btn.setFixedWidth(64)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(lambda _=False: self._confirm_delete())
        hl.addWidget(del_btn, 0, Qt.AlignVCenter)
        v.addWidget(self._expand)
        # 折叠态固定最大高度（避免被 QVBoxLayout 拉伸）
        self.setMaximumHeight(self.COLLAPSED_H)
        # hover 渐变动画
        self._hover_anim = self._make_hover_anim(200)
        # 展开/收起高度动画（QTimer 手动驱动，避免 QPropertyAnimation 不生效）
        self._h_anim_timer = QTimer(self)
        self._h_anim_timer.setInterval(16)
        self._h_anim_timer.timeout.connect(self._h_anim_tick)

    def _apply_bg(self, t: float):
        self._hover = float(t)
        # 白色 #FFFFFF → 淡蓝 #E6F1FB
        r = int(255 + (230 - 255) * t)
        g = int(255 + (241 - 255) * t)
        b = 255
        self.setStyleSheet(
            f"QFrame#apiRow{{background:rgb({r},{g},{b}); border:1px solid #CBD5E1; border-radius:10px;}}"
            "QFrame#apiRow QLabel{background:transparent;}"
            "QFrame#apiRow QWidget{background:transparent;}"
            "QPushButton#outlineBtn{background:transparent; color:#378ADD; border:1px solid #378ADD; border-radius:8px; padding:4px 12px;}"
            "QPushButton#outlineBtn:hover{background:#E6F1FB;}"
            "QPushButton#dangerBtn{background:transparent; color:#C0392B; border:1px solid #C0392B; border-radius:8px; padding:4px 12px;}"
            "QPushButton#dangerBtn:hover{background:#FDEDEC;}"
        )

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            super().mousePressEvent(e)
            return
        pos = e.position().toPoint()
        # 只有点击上面名称行（y < 60）才展开/收起；下面展开区不触发
        if pos.y() >= self.COLLAPSED_H:
            super().mousePressEvent(e)
            return
        self._toggle_expand()
        e.accept()

    def _toggle_expand(self):
        self._expanded = not self._expanded
        target_h = self.EXPANDED_H if self._expanded else self.COLLAPSED_H
        start_h = self.height()  # 记录当前高度（展开前 60，收起前 120）
        if self._expanded:
            # 展开：先显示展开区（位于名称下方），再动画高度
            self._expand.setVisible(True)
        # 立即锁定当前高度，防止 setVisible 触发 layout 跳变到 sizeHint
        self.setMinimumHeight(start_h)
        self.setMaximumHeight(start_h)
        self._animate_height(target_h, duration=200)

    def _animate_height(self, target_h: int, duration: int = 200):
        self._h_anim_start = self.height()
        self._h_anim_end = target_h
        self._h_anim_steps = max(1, duration // 16)
        self._h_anim_step = 0
        self._h_anim_timer.start()

    def _h_anim_tick(self):
        self._h_anim_step += 1
        t = min(1.0, self._h_anim_step / self._h_anim_steps)
        h = int(self._h_anim_start + (self._h_anim_end - self._h_anim_start) * t)
        # 同时设最小和最大高度，让 layout 接受新高度
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)
        if self._h_anim_step >= self._h_anim_steps:
            self._h_anim_timer.stop()
            # 动画结束后，按状态设置最终的高度限制
            if self._expanded:
                self.setMinimumHeight(self.EXPANDED_H)
                self.setMaximumHeight(self.EXPANDED_H)
            else:
                # 收起完成后再隐藏展开区（动画过程中已随高度上移被遮挡）
                self._expand.setVisible(False)
                self.setMinimumHeight(0)
                self.setMaximumHeight(self.COLLAPSED_H)

    def _confirm_delete(self):
        if ConfirmDialog.confirm(
            self, f"确定要删除 API「{self.entry.get('name','')}」吗？此操作不可撤销。"
        ):
            self.panel._delete(self.entry)


class _MessagePanel:
    """面板底部「一行提示」的公共实现（4 个面板共用）：绿色=成功，红色=失败。

    ★子类必须建好 `self._msg_label`（`_panel_bottom()` 返回值之一）。默认参数 `error=False`
    兼容两种旧签名（有的面板原先没有默认值）。
    """

    def _msg(self, text, error=False):
        color = "#C0392B" if error else "#1E8E3E"
        _animate_message(self._msg_label, text, color)


class ApiPanel(_MessagePanel, QWidget):
    """嵌入右侧的 API 管理面板：当前 API 选择 + 列表 + 添加。"""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._key_visible = False
        self._build()
        self._apply_style()
        self.refresh()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # 标题
        title = QLabel("管理 API")
        title.setStyleSheet("font-size:16px; font-weight:bold; color:#0C447C; background:transparent;")
        lay.addWidget(title)

        # 卡片：当前 API
        current_card = QFrame()
        current_card.setObjectName("card")
        cl = QVBoxLayout(current_card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)
        cl.addWidget(QLabel("当前 API"))
        self.api_combo = HoverComboBox()
        self.api_combo.currentIndexChanged.connect(self._on_api_select)
        cl.addWidget(self.api_combo)
        info_row = QHBoxLayout()
        self.api_info_label = QLabel("")
        self.api_info_label.setWordWrap(True)
        self.api_info_label.setStyleSheet(
            "background:#F6FAFF; border:1px solid #7DD3FC; border-radius:12px; padding:8px 12px; color:#334155;"
        )
        info_row.addWidget(self.api_info_label, 1)
        self.toggle_key_btn = QPushButton("显示 Key")
        self.toggle_key_btn.setObjectName("outlineBtn")
        self.toggle_key_btn.clicked.connect(self._toggle_key)
        info_row.addWidget(self.toggle_key_btn)
        cl.addLayout(info_row)
        lay.addWidget(current_card)

        # 操作按钮行
        btn_row = QHBoxLayout()
        self.add_api_btn = QPushButton("添加 API")
        self.add_api_btn.clicked.connect(self._add_api)
        btn_row.addWidget(self.add_api_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        list_label = QLabel("已有 API")
        list_label.setStyleSheet("font-weight:bold; color:#334155;")
        lay.addWidget(list_label)

        # 滚动区：只有这里滚动，多出的 API 行通过滚轮下滑查看，上滑内容被 list_label 遮挡
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        self._scroll.setVerticalScrollBar(_SmoothScrollBar())
        self._list_container = QWidget()
        self._list_container.setStyleSheet("background:transparent;")
        self._list_lay = QVBoxLayout(self._list_container)
        self._list_lay.setContentsMargins(0, 0, 8, 0)
        self._list_lay.setSpacing(8)
        self._scroll.setWidget(self._list_container)
        lay.addWidget(self._scroll, 1)

        # 消息标签移到底部，避免撑开"添加 API 按钮"与"已有 API"之间的间距
        self._msg_label = QLabel("")
        self._msg_label.setWordWrap(True)
        lay.addWidget(self._msg_label)

    def _apply_style(self):
        self.setStyleSheet(
            "QWidget { background:#FFFFFF; color:#334155; font-size:13px; }"
            "QLineEdit { background:#F6FAFF; border:1px solid #7DD3FC; border-radius:15px; padding:6px 12px; }"
            "QPushButton { background:#378ADD; color:white; border:none; border-radius:8px; padding:8px 18px; font-weight:bold; }"
            "QPushButton:hover { background:#2F74BF; }"
            "QPushButton#outlineBtn { background:transparent; color:#378ADD; border:1px solid #378ADD; border-radius:8px; padding:6px 14px; }"
            "QPushButton#outlineBtn:hover { background:#E6F1FB; }"
            "QPushButton#dangerBtn { background:transparent; color:#C0392B; border:1px solid #C0392B; border-radius:8px; padding:4px 12px; }"
            "QPushButton#dangerBtn:hover { background:#FDEDEC; }"
            "QFrame#card { background:#F6FAFF; border:1px solid #7DD3FC; border-radius:12px; }"
        )

    def refresh(self):
        self.api_combo.blockSignals(True)
        self.api_combo.clear()
        names = [a.get("name") for a in self.cfg.get("apis", [])]
        self.api_combo.addItems(names)
        cur = self.cfg.get("current_api")
        if cur in names:
            self.api_combo.setCurrentIndex(names.index(cur))
        self.api_combo.blockSignals(False)
        self._refresh_api_info()
        self._rebuild_list()

    def _current_entry(self):
        name = self.cfg.get("current_api")
        for a in self.cfg.get("apis", []):
            if a.get("name") == name:
                return a
        return None

    def _refresh_api_info(self):
        entry = self._current_entry()
        if not entry:
            self.api_info_label.setText("尚未添加 API")
            self.toggle_key_btn.setEnabled(False)
            return
        self.toggle_key_btn.setEnabled(True)
        key = entry.get("api_key", "")
        if self._key_visible:
            shown = key
            self.toggle_key_btn.setText("隐藏 Key")
        else:
            shown = mask_key(key)
            self.toggle_key_btn.setText("显示 Key")
        self.api_info_label.setText(f"key：{shown}")

    def _on_api_select(self):
        self.cfg["current_api"] = self.api_combo.currentText()
        self._key_visible = False
        save_config(self.cfg)
        self._refresh_api_info()
        self._rebuild_list()

    def _toggle_key(self):
        self._key_visible = not self._key_visible
        self._refresh_api_info()

    def _add_api(self):
        existing = [a.get("name") for a in self.cfg.get("apis", [])]
        dlg = ApiFormDialog(
            "添加 API",
            [
                ("name", "AI 名称：", "例如：爱丽丝", "", False),
                ("api_key", "API Key：", "sk-...", "", True),
                ("base_url", "接口地址：", DEFAULT_BASE_URL, DEFAULT_BASE_URL, False),
                ("model", "模型名：", DEFAULT_MODEL, DEFAULT_MODEL, False),
            ],
            self,
        )
        dlg.exec()
        if not dlg.confirmed():
            return
        name = dlg.get("name")
        key = dlg.get("api_key")
        if not name or not key:
            self._msg("名称与 API Key 不能为空。", error=True)
            return
        if name in existing:
            self._msg(f"名称「{name}」已存在，请换一个。", error=True)
            return
        self.cfg.setdefault("apis", []).append({
            "name": name,
            "api_key": key,
            "base_url": dlg.get("base_url") or DEFAULT_BASE_URL,
            "model": dlg.get("model") or DEFAULT_MODEL,
        })
        # 新添加的即成为当前 API；同一时刻只有一个 API 生效，其余自动停用
        self.cfg["current_api"] = name
        save_config(self.cfg)
        self.refresh()
        self._msg(f"已添加「{name}」并切换为当前 API。", error=False)

    def _rebuild_list(self):
        # 记录当前展开的 API 名称，重建后恢复展开状态（编辑等操作不收起）
        expanded_names = set()
        for i in range(self._list_lay.count()):
            item = self._list_lay.itemAt(i)
            w = item.widget()
            if isinstance(w, _ApiRow) and w._expanded:
                expanded_names.add(w.entry.get("name"))
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        apis = self.cfg.get("apis", [])
        if not apis:
            empty = QLabel("暂无 API，点击上方「添加 API」开始。")
            empty.setStyleSheet("color:#64748B; padding:10px;")
            self._list_lay.addWidget(empty)
            return
        for a in apis:
            row = self._build_row(a)
            self._list_lay.addWidget(row)
            # 恢复之前展开的行
            if a.get("name") in expanded_names:
                row._expanded = True
                row._expand.setVisible(True)
                row.setMinimumHeight(row.EXPANDED_H)
                row.setMaximumHeight(row.EXPANDED_H)
        # 底部 stretch 把额外空间推到底部，避免列表项被拉伸填满空白
        self._list_lay.addStretch(1)

    def _build_row(self, entry):
        return _ApiRow(entry, self)

    def _edit_row(self, entry, row_frame):
        # 编辑 API：名称 / 接口地址 / 模型名（API Key 保持不变，避免误改）
        old_name = entry.get("name")
        dlg = ApiFormDialog(
            "编辑 API",
            [
                ("name", "AI 名称：", "例如：爱丽丝", old_name or "", False),
                ("base_url", "接口地址：", DEFAULT_BASE_URL,
                 entry.get("base_url") or DEFAULT_BASE_URL, False),
                ("model", "模型名：", DEFAULT_MODEL,
                 entry.get("model") or DEFAULT_MODEL, False),
            ],
            self,
        )
        dlg.exec()
        if not dlg.confirmed():
            return
        new_name = dlg.get("name")
        if not new_name:
            self._msg("名称不能为空。", error=True)
            return
        # 重名校验（排除自己）
        others = [a.get("name") for a in self.cfg.get("apis", []) if a is not entry]
        if new_name in others:
            self._msg(f"名称「{new_name}」已存在。", error=True)
            return
        entry["name"] = new_name
        entry["base_url"] = dlg.get("base_url") or DEFAULT_BASE_URL
        entry["model"] = dlg.get("model") or DEFAULT_MODEL
        if self.cfg.get("current_api") == old_name:
            self.cfg["current_api"] = new_name
        save_config(self.cfg)
        self.refresh()
        self._msg(f"已保存「{new_name}」。", error=False)

    def _delete(self, entry):
        """执行删除（确认框已由 _confirm_delete 弹过，这里不再重复确认）。"""
        name = entry.get("name")
        self.cfg["apis"] = [a for a in self.cfg.get("apis", []) if a is not entry]
        if self.cfg.get("current_api") == name:
            remaining = self.cfg.get("apis", [])
            self.cfg["current_api"] = remaining[0]["name"] if remaining else ""
        save_config(self.cfg)
        self.refresh()
        self._msg(f"已删除「{name}」。", error=False)

class _WakeRow(_HoverRow, QFrame):
    """唤醒词行：白底圆角、hover 淡蓝渐变、词 + 删除按钮（样式同 API 行）。"""

    def __init__(self, word, panel, parent=None):
        super().__init__(parent)
        self.word = word
        self.panel = panel
        self._hover = 0.0
        self.setObjectName("wakeRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        hl = QHBoxLayout(self)
        hl.setContentsMargins(16, 0, 12, 0)
        hl.setSpacing(10)
        lbl = QLabel(word)
        lbl.setStyleSheet("color:#0C447C; font-size:14px; background:transparent;")
        hl.addWidget(lbl, 1)
        del_btn = QPushButton("删除")
        del_btn.setObjectName("dangerBtn")
        del_btn.setFixedWidth(56)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(lambda _=False: panel._delete_word(word))
        hl.addWidget(del_btn)
        self._hover_anim = self._make_hover_anim(200)
        # layout 之后再设样式，避免构造期间 QPainter 状态异常导致警告
        self._apply_bg(0.0)

    def _apply_bg(self, t):
        self._hover = float(t)
        # 白 #FFFFFF → 淡蓝 #E6F1FB
        r = int(255 + (230 - 255) * t)
        g = int(255 + (241 - 255) * t)
        b = 255
        self.setStyleSheet(
            f"QFrame#wakeRow{{background:rgb({r},{g},{b}); border:1px solid #CBD5E1; border-radius:10px;}}"
            "QFrame#wakeRow QLabel{background:transparent;}"
            "QPushButton#dangerBtn{background:transparent; color:#C0392B; border:1px solid #C0392B; border-radius:8px; padding:4px 12px;}"
            "QPushButton#dangerBtn:hover{background:#FDEDEC;}"
        )


class WakeWordPanel(_MessagePanel, QWidget):
    """嵌入右侧的唤醒词管理面板。"""

    def __init__(self, cfg, role_key, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.role_key = role_key
        self._build()
        self._apply_style()
        self._rebuild()

    def set_role(self, role_key):
        self.role_key = role_key
        # 标题与左栏导航项（MANAGE_ITEMS 的「管理唤醒词」）保持同名，避免同一页两个叫法
        self.title_label.setText(f"管理唤醒词 - {self.cfg['roles'][role_key].get('name', role_key)}")
        self._rebuild()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # 标题
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size:16px; font-weight:bold; color:#0C447C; background:transparent;")
        lay.addWidget(self.title_label)

        # 添加唤醒词按钮（蓝色镂空）
        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("添加唤醒词")
        self.add_btn.setObjectName("outlineBtn")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._start_add)
        btn_row.addWidget(self.add_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        # "已有的唤醒词" 标签
        list_label = QLabel("已有的唤醒词")
        list_label.setStyleSheet("font-weight:bold; color:#334155;")
        lay.addWidget(list_label)

        # 滚动区（唤醒词行列表，胶囊形滚动条）
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        self._scroll.setVerticalScrollBar(_SmoothScrollBar())
        self._rows_container = QWidget()
        self._rows_container.setStyleSheet("background:transparent;")
        self._rows_lay = QVBoxLayout(self._rows_container)
        self._rows_lay.setContentsMargins(0, 0, 8, 0)
        self._rows_lay.setSpacing(8)
        self._scroll.setWidget(self._rows_container)
        lay.addWidget(self._scroll, 1)

        # 消息
        self._msg_label = QLabel("")
        self._msg_label.setWordWrap(True)
        lay.addWidget(self._msg_label)

    def _apply_style(self):
        self.setStyleSheet(
            "QWidget { background:#FFFFFF; color:#334155; font-size:13px; }"
            "QLineEdit { background:#F6FAFF; border:1px solid #7DD3FC; border-radius:15px; padding:6px 12px; }"
            "QPushButton#outlineBtn { background:transparent; color:#378ADD; border:1px solid #378ADD; border-radius:8px; padding:6px 14px; }"
            "QPushButton#outlineBtn:hover { background:#E6F1FB; }"
        )

    def _wake_words(self):
        return self.cfg["roles"][self.role_key].setdefault("wake_words", [])

    def _rebuild(self):
        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # 删除前停止 hover 动画并断开信号，避免在已脱离布局的 widget 上触发 setStyleSheet 导致 QPainter 警告
                if isinstance(w, _WakeRow):
                    w._hover_anim.stop()
                    try:
                        w._hover_anim.valueChanged.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                w.setParent(None)
                w.deleteLater()
        words = self._wake_words()
        if not words:
            empty = QLabel("暂无唤醒词，点击上方「添加唤醒词」开始。")
            empty.setStyleSheet("color:#64748B; padding:14px;")
            self._rows_lay.addWidget(empty)
        else:
            for w in words:
                self._rows_lay.addWidget(self._build_row(w))
        self._rows_lay.addStretch(1)

    def _build_row(self, word):
        return _WakeRow(word, self)

    def _start_add(self):
        # 弹窗输入新唤醒词（与 API 管理输入弹窗同款）
        word, ok = InputDialog.get_text(self, "添加唤醒词", "新唤醒词", "")
        if not ok or not word.strip():
            return
        word = word.strip()
        words = self._wake_words()
        if word in words:
            self._msg(f"唤醒词「{word}」已存在。", error=True)
            return
        words.append(word)
        save_config(self.cfg)
        self._msg(f"已添加「{word}」。", error=False)
        self._rebuild()

    def _delete_word(self, word):
        if ConfirmDialog.confirm(self, f"确定要删除唤醒词「{word}」吗？此操作不可撤销。"):
            words = self._wake_words()
            if word in words:
                words.remove(word)
                save_config(self.cfg)
                self._msg(f"已删除「{word}」。", error=False)
                self._rebuild()

# ========== 设定卡（管理区第 3 页，2026-09-30）==========
#
# 页面口径（用户 2026-09-30 口述整理）：
# - 左栏管理导航新增「设定卡」，**排在最后**（管理 API → 管理唤醒词 → 设定卡）。
# - 右栏内容 = **只有「预设」一个区块**（五个展示项不铺在页面上，点「查看」才看）。
#   将来会加「自定义」区块，**接在预设下面**；★被选中的那张预设卡**不挪位置**
#   （不能因为"当前项要排前面"而重排 —— 顺序恒等于配置里的列表顺序）。
# - 预设卡：最左单选框 / 中间预设命名 / 最右蓝底白字「查看」。
#   ★★**整张卡点得动 = 切到这张预设**（2026-09-30 晚用户口径：「点整张卡或圆点都可以切换，
#     但点击右侧的按钮不会切换」）—— 卡片仍是**不可编辑、不可删除**的（编辑随"自定义"一起做）。
#     ★页面标题右上角那颗圆点只是"当前选中"的显示，点击由卡片统一处理（圆点不吃鼠标）。
# - 「查看」弹窗 540×460（2026-09-30 二次改版：高度再 −20）：五个展示项各用一个文本框框住；
#   内容较长 ⇒ 可下拉（右侧留滚动条位、下侧留位放「关闭」按钮）。
#   ★★**唯一的关法就是那颗「关闭」**（用户 2026-09-30 拍板）：「点弹窗外关闭」那三层机制
#     **做过、已整块删除**，`PresetViewDialog` 上不再有 `eventFilter` / `paintEvent` / `OUTER`
#     之类的东西 —— **别再加回来**（为什么那三层不成立见 docs/02 §25.6 / §25.14）。
# - **跟随当前角色**（与「管理唤醒词」同一套做法）：切到艾莲就显示艾莲的预设。
# - 「回复语言」指的是**合成语音**说的语言（聊天界面恒为中文），当前固定日语、**只读**：
#   编辑能力随自定义功能一起做（用户口径）。

# ★2026-09-30 晚：卡片自带**人设全文**（`presets[*].persona`），`persona/*.md` 退化成
#   「首次播种用的素材」—— 详见 docs/02 §25.17。取值一律走 `config.resolve_persona_text`，
#   **不许在 gui 里拼路径、也不许自己读文件**（那正是"看着是 A、实际用的是 B"的来源）。

# 「查看」弹窗里的五个展示项。前四项从人设全文按 `## 小节` 取；第五项（回复语言）
# **不在人设文件里** —— 它是合成语音的语言，唯一真值在 `tts.DEFAULT_TEXT_LANGUAGE`，见下。
_PRESET_FIELDS = (
    ("background", "角色背景设定", "设定"),
    ("style", "说话风格", "说话风格"),
    ("verbal_tics", "口癖", "口癖"),
    ("address", "称呼", "称呼"),
)
# 人设文件里没有这一条时的显示占位（**照实留空，不替角色编内容**）
PRESET_EMPTY = "（未设置）"


def _clean_preset_text(lines) -> str:
    """把人设文件里的一个小节转成适合放进文本框的纯文本。

    只做两件**无损的显示层**处理：行首 `- ` → `• `（**统一顶格**）、去掉 `**` 与反引号。
    ★不改写任何字句：这一页展示的就是「当前真正在用的设定」，措辞必须原样保留。
    ★★**子级缩进一律拍平**（2026-09-30 二次改版，用户口径「口癖里有几条的 · 和其他没对齐」）：
      人设文件用 `  - ` 表示子项，但正文字体是**比例字体**，两个半角空格的缩进既不像"缩进"
      也不像"没缩进"，看起来就是几个 `•` 没对齐。层级信息由人设的措辞承担
      （「在以下两类场合」），显示层只保证**所有 `•` 落在同一条竖线上**。
    """
    out = []
    for raw in lines:
        stripped = raw.strip()
        # 条目行：丢掉原有缩进，统一顶格；非条目行（如缩进的对齐示例）原样保留
        line = "• " + stripped[2:] if stripped.startswith("- ") else raw.rstrip()
        out.append(line.replace("**", "").replace("`", ""))
    return "\n".join(out).strip("\n")


def persona_sections_from_text(text) -> dict:
    """把**人设全文**按 `## 小节` 拆出 `_PRESET_FIELDS` 里的四项（缺的给空串）。

    ★2026-09-30 晚：「设定卡」可切换 + 卡片自带人设全文 ⇒ 本函数从"读文件"改成"吃文本"，
      **调用方拿到的就是 `presets[*].persona` 那份全文本身**（取值走 `config.resolve_persona_text`）。
      好处是「页面上显示的」与「实际喂给模型的」**是同一串字符**，不可能各说各话；
      也不再需要在 `gui` 里拼路径（那只会在人设载体变化时静默失效）。

    - **只认 `##` 标题**：`# 爱丽丝（《蔚蓝档案》）` 是文件大标题不是小节（遇到它即结束当前小节）。
    - 空文本 → 四项全空串（**不抛异常**：人设是可被用户替换的素材）。
    - ★艾莲那份**故意缺「口癖 / 称呼」**（她的人设里本来就没这两条）⇒ 解析层照实返回空串，
      占位由调用方补 —— **别在这儿替角色编一段**，那会让"页面上显示的"与"实际喂给模型的"不一致。
    """
    out = {key: "" for key, _title, _head in _PRESET_FIELDS}
    heads = {head: key for key, _title, head in _PRESET_FIELDS}
    cur, buf = None, []
    for line in str(text or "").splitlines():
        if line.startswith("#"):
            if cur is not None:
                out[cur] = _clean_preset_text(buf)
            cur, buf = heads.get(line.lstrip("#").strip()), []
            continue
        if cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = _clean_preset_text(buf)
    return out


def preset_language_name() -> str:
    """「回复语言」的显示名。★唯一真值 = `tts.DEFAULT_TEXT_LANGUAGE`（不在本文件里另写一份）。

    ★局部 import：`tts` 会拉起 `sounddevice` / `numpy`，gui 模块顶层不该为了一个显示名去背它
      （本文件其它用到 tts 的地方也都是函数内 import）。
    """
    from .tts import DEFAULT_TEXT_LANGUAGE, TEXT_LANGUAGE_NAMES

    return TEXT_LANGUAGE_NAMES.get(DEFAULT_TEXT_LANGUAGE, DEFAULT_TEXT_LANGUAGE)


class _PresetDot(QWidget):
    """设定卡预设卡最左侧的**实心圆单选**（自绘）。

    用户口径（2026-09-30）：**外圈 1px 细线；未选中 = 空心；选中 = 内部填一个略小于
    外圈半径的实心圆**。

    ★★2026-10-01 用户口径：「设置里『关闭行为』的单选框也改成和设定卡一样」
      ⇒ **全项目只剩这一款单选钮** —— 设定卡 + 设置页「关闭行为」共用**同一个类**。
      旧款 `_RadioDot`（圆心**永远留白**的「两圈描边 + 中间一圈蓝环」）**已整块删除**；
      `_RadioItem`（设置页那一行）现在直接拿这个类当圆点。
      ⇒ **改这里的观感 = 同时改两处**。别再按调用方在 `paintEvent` 里分叉
        （那是当初保留两个类的理由，随本轮口径作废）；也别把「圆心留白」那款加回来。

    - 外径 18px（设置页「关闭行为」那行行高钉死 **58px**，两处必须同尺寸才对得齐）、
      边框 1px、实心圆直径 12px
      （比外圈半径 9px 小 ⇒ 留 1px 边框 + 2px 空隙，看起来才是"略小"而不是"顶满"）。
    - 选中 ↔ 未选中是 **500ms 变色淡入淡出**（设定卡与设置页同一节奏）：着色进度 `_t` 在 0↔1
      之间插值，外圈灰→蓝、实心圆按同一进度淡入淡出。**不要每帧 `setStyleSheet`**（会 polish + 重排）。
    - **自己不处理鼠标、让事件穿透到卡片**（`WA_TransparentForMouseEvents`）：
      2026-09-30 晚起**整张卡都可点切换**（用户口径：「点整张卡或圆点都可以切换」）——
      圆点保持"纯展示、不自己写 `mousePressEvent`"，点击直接落到 `_PresetCard` 上，
      于是「点圆点」与「点卡片」走的是**同一条**切换路径（不必在这里再写一份）。
      ★别把 `WA_TransparentForMouseEvents` 去掉改成自己接事件：那就有了两条切换路径。
    """

    DOT = 18
    BORDER = 1
    SOLID = 12
    ON = "#378ADD"          # 选中：外圈与实心圆同为主蓝
    IDLE = "#CBD5E1"        # 未选中：只有外圈，灰（与滑块关态、行边框同色）
    FADE_MS = 500

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        # 着色进度：0 = 未选中（只画灰外圈），1 = 选中（蓝外圈 + 实心圆）。
        # 绘制读 `_t` 而不是 `_checked`，切换才是渐变而非瞬间跳变。
        self._t = 1.0 if self._checked else 0.0
        self.setFixedSize(self.DOT, self.DOT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self.FADE_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_t)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool, animate: bool = True) -> None:
        """拨到选中 / 未选中。`animate=False` 直接落终态（构建期用，省一次无谓动画）。"""
        on = bool(on)
        if on == self._checked:
            return
        self._checked = on
        target = 1.0 if on else 0.0
        self._anim.stop()
        if not animate:
            self._set_t(target)
            return
        self._anim.setStartValue(self._t)   # 从当前进度续上，连点两次不会闪
        self._anim.setEndValue(target)
        self._anim.start()

    def _set_t(self, value) -> None:
        self._t = float(value)
        self.update()

    def paintEvent(self, _e):  # noqa: N802 (Qt 命名)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s, b, t = self.DOT, self.BORDER, self._t
        outer = QRectF(b / 2, b / 2, s - b, s - b)
        p.setPen(QPen(_mix_color(self.IDLE, self.ON, t), b))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(outer)                 # 外圈：灰 → 蓝，全程可见
        if t > 0.0:
            inner = QRectF((s - self.SOLID) / 2, (s - self.SOLID) / 2, self.SOLID, self.SOLID)
            p.setPen(Qt.NoPen)
            p.setBrush(_fade_color(self.ON, t))
            p.drawEllipse(inner)             # 实心圆：随进度淡入 / 淡出


class _PresetCard(_HoverRow, QFrame):
    """「预设」区块里的一张预设卡（2026-09-30）。

    用户口径：卡片样式**类似设置界面**（= `_SettingRow` 那张卡：白底 / 圆角 10 / 1px `#CBD5E1` /
    高 58px），自左向右依次是「实心圆单选 → 预设命名 → 蓝底白字『查看』」。

    - ★★**整张卡可点 = 切换到这张预设**（2026-09-30 晚用户口径：「点整张卡或圆点都可以切换，
      **但点击右侧的按钮不会切换**」）：
        · 切换落在 `mouseReleaseEvent`（不是 press）—— 按下去又拖出去松手 **不算**点击，
          判据是"松开时指针还在卡里"（`self.rect().contains(...)`）；
        · 「点右侧按钮不切换」**天然成立**，不需要额外判断：`QPushButton` 会把落在自己身上的
          按下/松开**自己吃掉**（它要 press+release 成对才发 `clicked`），父控件根本收不到；
        · 圆点也一样（`WA_TransparentForMouseEvents` ⇒ 事件穿透上来），所以"点圆点"与
          "点卡片"共用这一条路径，**没有第二份切换逻辑**。
    - ★★**悬停效果 = 与「管理 API」/「管理唤醒词」的卡片同一条**（2026-09-30 晚·第五批，用户口径
      「鼠标悬停时卡片的变化效果参照管理 api 和管理唤醒词里的卡片效果」）：
      **底色 200ms 由白 `#FFFFFF` 渐到淡蓝 `#E6F1FB`，描边全程保持 `#CBD5E1`**。
      实现方式是与 `_ApiRow` / `_WakeRow` / `_PermRow` **共用 `_HoverRow` 混入类**
      （`_make_hover_anim` + `enterEvent` / `leaveEvent` → `_apply_bg(t)`）—— 四处视觉必须一致，
      改一处等于改四处。
      ★这推翻了同日早先的「只把描边染蓝、底色保持白」：那时的顾虑是「整块填色会盖过
        『这张选中了』的实心圆观感」，实测淡蓝底上圆点的灰圈 / 蓝实心圆都还看得清
        （对照图 `docs/screenshots/manage-preset-hover.png`）。★改需求时记得复核这条注释。
    - ★早先还有一条「本页只有『查看』可点、不做整行 hover」的口径 —— 那条随「整卡可点」一起反转了：
      卡片成了主操作，就必须有可点反馈。**只要卡片还能点，hover 就不能删。**
    - 单选状态由 `checked` 参数决定、**不写死**：由调用方按「哪张是角色 `persona` 指向的那份」传值。
      切换后**不重建卡片**，只调 `set_checked()` —— 保住那颗圆点 500ms 的变色动画
      （重建的话新圆点直接落终态，看起来像"瞬移"）。
    - 名称是单行 `QLabel` ⇒ 横向策略设 `Ignored` + `resizeEvent` 里按当前宽度右侧省略：
      不这么做，长预设名会把行顶宽、把右边那颗「查看」挤出可视区（`_SettingRow` 踩过同一个坑）。
    """

    def __init__(self, name: str, checked: bool, on_view, on_switch=None, parent=None):
        super().__init__(parent)
        self.setObjectName("presetCard")
        self.setFixedHeight(58)
        self._name_text = str(name)
        self._on_switch = on_switch
        self._hover = 0.0          # 0=白, 1=淡蓝（与 `_ApiRow` / `_WakeRow` 同一套）
        # 整卡可点 ⇒ 给个"手型"，否则用户不知道点得动（「查看」那颗按钮自带同一个光标）
        if on_switch is not None:
            self.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(self)
        hl.setContentsMargins(16, 8, 12, 8)
        hl.setSpacing(10)

        self._dot = _PresetDot(checked)
        hl.addWidget(self._dot, 0, Qt.AlignVCenter)

        self._name = QLabel(self._name_text)
        self._name.setStyleSheet("color:#0C447C; font-size:13px; background:transparent;")
        self._name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        hl.addWidget(self._name, 1)

        self._view_btn = QPushButton("查看")
        self._view_btn.setObjectName("presetViewBtn")
        self._view_btn.setCursor(Qt.PointingHandCursor)
        # ★NoFocus：与权限页行内按钮同一条理由 —— 这类临时操作按钮不该进键盘焦点链，
        #   否则关掉弹窗后焦点被移交给别的控件，滚动区会 ensureWidgetVisible 去追它。
        self._view_btn.setFocusPolicy(Qt.NoFocus)
        self._view_btn.setFixedHeight(28)
        self._view_btn.clicked.connect(lambda _=False: on_view())
        hl.addWidget(self._view_btn, 0, Qt.AlignVCenter)

        # hover 渐变：复用 `_HoverRow` 的那条 **200ms** 动画（`valueChanged` → `_apply_bg(t)`），
        # 与 `_ApiRow` / `_WakeRow` 同款 —— 底色白 → 淡蓝、描边不动。
        self._hover_anim = self._make_hover_anim(200)
        # ★布局装完之后再落一次底色：构造期就 `setStyleSheet` 会多触发一轮无用 polish。
        self._apply_bg(0.0)

    def _apply_bg(self, t: float):
        """把 hover 强度 `t`（0 = 白 → 1 = 淡蓝）落到样式表上。

        ★**与 `_ApiRow._apply_bg` / `_WakeRow._apply_bg` 是同一条插值**（白 `#FFFFFF` →
          `#E6F1FB`）、**描边一律 `#CBD5E1`**（hover 不染蓝）、圆角同为 10px ——
          三处必须保持一致，改一处等于改三处。
        """
        self._hover = float(t)
        r = int(255 + (230 - 255) * t)
        g = int(255 + (241 - 255) * t)
        b = 255
        self.setStyleSheet(
            f"QFrame#presetCard{{background:rgb({r},{g},{b}); border:1px solid #CBD5E1; border-radius:10px;}}"
            "QFrame#presetCard QLabel{background:transparent;}"
            "QPushButton#presetViewBtn{background:#378ADD; color:#FFFFFF; border:none;"
            " border-radius:8px; padding:4px 12px; font-size:12px;}"
            "QPushButton#presetViewBtn:hover{background:#2F74BF;}"
        )

    def set_checked(self, on: bool, animate: bool = True) -> None:
        """只拨那颗圆点（**不重建**卡片）—— 切换后保住 500ms 变色动画的入口。"""
        self._dot.setChecked(on, animate=animate)

    def mouseReleaseEvent(self, e):  # noqa: N802 (Qt 命名)
        """松开鼠标 ⇒ 切到这张预设（★判据见类 docstring：落在「查看」上的事件收不到、不必特判）。"""
        super().mouseReleaseEvent(e)
        if e.button() != Qt.LeftButton:
            return
        # 按下去又拖到卡外才松手 ⇒ 不算点击（`QPushButton` 同一套规矩，用户习惯一致）
        if not self.rect().contains(e.position().toPoint()):
            return
        if self._on_switch is not None:
            self._on_switch()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        avail = self._name.width()
        if avail > 0 and self._name_text:
            # 一律拿**原文**去省略：宽度变回去时能自动还原，不会越省略越短
            self._name.setText(
                self._name.fontMetrics().elidedText(self._name_text, Qt.ElideRight, avail)
            )


class PresetPanel(_MessagePanel, QWidget):
    """设定卡面板（管理区，2026-09-30）：显示**当前角色**的设定预设。

    结构与其他管理 / 设置面板同一条：标题 → 滚动区 → 底部消息行（`_panel_bottom`）。
    页面内容只有「预设」一个分组（`_group_header`）—— 将来的「自定义」区块接在它**下面**。
    ★卡片顺序 = 配置里的列表顺序，**选中态不改变位置**（用户口径）。
    """

    def __init__(self, cfg, role_key, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.role_key = role_key
        self._cards = []      # 当前页上的卡片引用，切换后只拨圆点、**不重建**（见 `_sync_checked`）
        self._build()
        self._apply_style()
        self._rebuild()

    def set_role(self, role_key):
        """跟随当前角色（与 `WakeWordPanel.set_role` 同一套做法）。"""
        self.role_key = role_key
        self._rebuild()

    def _build(self):
        lay = QVBoxLayout(self)
        # 与 4.11 / 4.13 同一套底部尺寸：底边距 4 + 消息行前间距 4 + 消息行 16 = 24px
        lay.setContentsMargins(24, 20, 24, TAIL_BOTTOM)
        lay.setSpacing(14)
        _panel_title(lay, "设定卡")
        self._scroll, self._body, self._body_lay, self._msg_label = _panel_bottom(lay)

    def _apply_style(self):
        self.setStyleSheet("QWidget { background:#FFFFFF; color:#334155; font-size:13px; }")

    def _role(self) -> dict:
        role = self.cfg.get("roles", {}).get(self.role_key)
        return role if isinstance(role, dict) else {}

    def _presets(self) -> list:
        presets = self._role().get("presets")
        return presets if isinstance(presets, list) else []

    def current_name(self) -> str:
        """**哪张卡是选中的**：presets 里 `persona` == 角色 `persona` 的那一张。

        ★判据只用「当前生效的人设」这一个事实（见 `config.DEFAULT_CONFIG` 里 roles 的注释）
          —— 不引入 `current_preset` 之类的第二份状态：两份状态一旦漂移，
          页面上显示的是这一份、实际用的是那一份，而且**不会有任何报错**。
        ★两边都是**人设全文**（`config.resolve_persona_text` 在 `load_config` 里统一解析过），
          **逐字相等**才算选中 —— 所以「切换」只要把那串文本写进 `role["persona"]` 就完事，
          本函数**一个字都不用改**。
        """
        current = str(self._role().get("persona") or "").strip()
        for item in self._presets():
            if isinstance(item, dict) and str(item.get("persona") or "").strip() == current:
                return str(item.get("name") or "")
        return ""

    def refresh(self):
        self._rebuild()

    def _rebuild(self):
        _clear_body(self._body_lay)
        self._cards = []
        _group_header(self._body_lay, "预设")
        presets = [p for p in self._presets() if isinstance(p, dict)]
        if not presets:
            _hint_tip(self._body_lay, "当前角色还没有预设。")
            return
        current = self.current_name()
        for item in presets:
            name = str(item.get("name") or "")
            card = _PresetCard(
                name, name == current,
                lambda n=name, i=item: self._on_view(n, i),
                on_switch=lambda i=item: self._on_switch(i),
            )
            self._cards.append(card)
            self._body_lay.addWidget(card)
        self._body_lay.addStretch(1)

    def _on_switch(self, item):
        """点卡片（或圆点）⇒ **把这张预设切为当前使用**（2026-09-30 晚；本页从"只读"变成有交互）。

        写回的是 `role["persona"]` —— 它同时是「哪张卡选中」的**唯一判据**（不设第二份指针）；
        而 `main.py` 每轮回复都重新读一次 cfg ⇒ **下一句话就用新设定**，不必重启。
        ★已经是这张 ⇒ **直接返回、不写盘**（否则"点一下当前那张"也会产生一次磁盘写 + 一条回执）。
        ★卡内容为空 ⇒ 只提示、不切（切过去等于把 system prompt 变空，模型会丢掉全部人设）。
        ★落盘走 `save_config`：这一步把**人设全文**写进 `config.json`，此后运行时就
          **不再读 `persona/*.md`** 了（用户口径"直接读设定卡"；取舍见 docs/02 §25.17）。
        """
        name = str(item.get("name") or "")
        text = resolve_persona_text(item.get("persona"))
        role = self._role()
        if not text:
            self._msg(f"「{name}」没有内容，不能切换。", error=True)
            return
        if text == str(role.get("persona") or ""):
            return
        role["persona"] = text
        save_config(self.cfg)
        self._sync_checked()
        self._msg(f"已切换到「{name}」。", error=False)

    def _sync_checked(self):
        """按当前 cfg **只拨圆点**（不重建卡片）⇒ 卡片顺序、滚动位置都不动，还保住变色动画。"""
        current = self.current_name()
        for card in getattr(self, "_cards", []):
            card.set_checked(card._name_text == current)

    def _on_view(self, name, item):
        """「查看」：把**这张卡自带的人设全文**里的四条 + 「回复语言」装进弹窗。

        ★内容与实际喂给模型的**是同一串字符**（都取自 `presets[*].persona`）⇒
          这一页不可能出现"看着是 A、实际用的是 B"。
        """
        fields = persona_sections_from_text(resolve_persona_text(item.get("persona")))
        rows = [(title, fields.get(key) or PRESET_EMPTY) for key, title, _head in _PRESET_FIELDS]
        rows.append(("回复语言", preset_language_name()))
        PresetViewDialog.view(self, name, rows)


# ========== 权限管理面板 ==========

# 操作类型 → 中文名（权限面板显示用）
_ACTION_NAMES = {
    "query_info": "查询信息（时间 / 日期 / IP / 位置）",
    "list_dir": "查看目录内容",
    "open_path": "打开文件 / 文件夹",
    "open_url": "打开收藏的网址",
    "open_app": "打开软件",
    "search": "浏览器搜索",
    "run_command": "系统操作（关机 / 重启 / 注销 / 锁屏）",
}


def _elide_middle(text: str, limit: int = 44) -> str:
    """中间省略过长文本（长路径在窄行里会顶掉按钮）。"""
    if len(text) <= limit:
        return text
    head = (limit - 3) // 2
    tail = limit - 3 - head
    return f"{text[:head]}...{text[-tail:]}"


class _PermRow(_HoverRow, QFrame):
    """权限列表行：hover 淡蓝渐变 + 右侧操作按钮（删除 / 修改）。

    `flat=True` 用于折叠分组的内容区：**无边框、无圆角、行间无缝**，且右侧操作按钮
    默认隐藏（透明但占位），随行 hover 渐变**同步 200ms 淡入 / 淡出**。
    """

    HOVER_MS = 200
    # 行内右侧按钮宽度**下限**：两字文案（删除 / 修改）正好 56px；
    # 三字文案（如「重命名」，sizeHint=62）必须按文字自动放宽 —— 写死 56 会把
    # 最后一个字裁掉（QPushButton 不走省略号，直接切）。用 Minimum 策略而非 Fixed：
    # 布局不会把它压回 56，文案不变时也不会抖动。
    BTN_W = 56

    def __init__(self, text, action_text, on_action, danger=True, mono=False,
                 flat=False, extra_text=None, on_extra=None,
                 switch_text=None, switch_checked=False, on_switch=None,
                 parent=None):
        super().__init__(parent)
        self._hover = 0.0
        self._flat = bool(flat)
        self._round_bottom = False
        self.setObjectName("permRow")
        self.setFixedHeight(44)
        hl = QHBoxLayout(self)
        margins = (10, 0, 10, 0) if self._flat else (16, 0, 12, 0)
        hl.setContentsMargins(*margins)
        hl.setSpacing(10)
        lbl = QLabel(_elide_middle(text))
        lbl.setStyleSheet(
            "color:#334155; font-size:12px; background:transparent;"
            if mono else
            "color:#0C447C; font-size:13px; background:transparent;"
        )
        hl.addWidget(lbl, 1)
        # 行内开关（目前只有「免 UAC」用）：小字标签 + 圆形滑块。
        # 显隐与行内按钮一致：**随行 hover 200ms 淡入 / 淡出**（用户要求「和重命名、删除
        # 按钮一样，仅鼠标悬停时显示」）。滑块是自绘控件，走它自己的 `set_opacity`
        # （内部同时管 alpha 与鼠标穿透）；旁边的小字另配一个 `QGraphicsOpacityEffect`
        # —— 两者必须同进同出，否则会看到「文字还在、开关没了」。
        self._switch = None
        self._switch_lbl = None
        self._switch_lbl_effect = None
        self._on_switch = on_switch
        if switch_text:
            self._switch_lbl = QLabel(switch_text)
            self._switch_lbl.setStyleSheet(
                "color:#64748B; font-size:12px; background:transparent;"
            )
            # 点字样 = 点滑块 → 手型光标给出暗示
            self._switch_lbl.setCursor(Qt.PointingHandCursor)
            hl.addWidget(self._switch_lbl, 0, Qt.AlignVCenter)
            self._switch = _ToggleSwitch(bool(switch_checked))
            self._switch.set_bg("#FFFFFF")   # 透明态铺底，防露黑块
            self._switch.clicked.connect(self._switch_clicked)
            hl.addWidget(self._switch, 0, Qt.AlignVCenter)
            if self._flat:
                self._switch_lbl_effect = QGraphicsOpacityEffect(self._switch_lbl)
                self._switch_lbl_effect.setOpacity(0.0)
                self._switch_lbl.setGraphicsEffect(self._switch_lbl_effect)
            # 标签要装过滤器：**点「字样」等同点滑块**（见 `eventFilter`）。
            # 悬停说明已按用户要求删除（2026-09-16：只保留开启前的确认弹窗），
            # 所以这里**不再**接管 Enter/Leave，也不再建 `_ToolTip` 气泡。
            self._switch_lbl.installEventFilter(self)
        # 额外按钮（蓝色镂空 = 非破坏性）排在主按钮**左侧**，与 API 行「蓝编辑 / 红删除」同序。
        # 权限页只有「从磁盘添加的软件」行会用到它（重命名）。
        self._btn_extra = None
        if extra_text:
            self._btn_extra = QPushButton(extra_text)
            self._btn_extra.setObjectName("outlineBtn")
            self._btn_extra.setMinimumWidth(self.BTN_W)
            self._btn_extra.setCursor(Qt.PointingHandCursor)
            # 行内按钮是「hover 才现形」的临时操作，不该抢键盘焦点：一旦它拿着焦点，
            # rebuild 销毁它时 Qt 会转移焦点、滚动区随之 ensureWidgetVisible → 画面乱滚。
            self._btn_extra.setFocusPolicy(Qt.NoFocus)
            self._btn_extra.clicked.connect(lambda _=False: on_extra())
            hl.addWidget(self._btn_extra)
        self._btn = QPushButton(action_text)
        self._btn.setObjectName("dangerBtn" if danger else "outlineBtn")
        self._btn.setMinimumWidth(self.BTN_W)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setFocusPolicy(Qt.NoFocus)
        self._btn.clicked.connect(lambda _=False: on_action())
        hl.addWidget(self._btn)

        # flat 行：按钮默认「完全透明但依然占位」。用透明度而不是 setVisible ——
        # 隐藏的控件在 QLayout 里尺寸归零，左侧文字会重新排版（抖动）；再用
        # WA_TransparentForMouseEvents 保证淡出后点不到它（否则等于隐形按钮）。
        # 一行可能有 2 个按钮，**各自一个 effect 并一起渐变**，否则会一亮一暗。
        self._btn_effect = None
        self._btn_extra_effect = None
        self._action_btns = [b for b in (self._btn_extra, self._btn) if b is not None]
        if self._flat:
            for _b in self._action_btns:
                _eff = QGraphicsOpacityEffect(_b)
                _eff.setOpacity(0.0)
                _b.setGraphicsEffect(_eff)
                _b.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                if _b is self._btn_extra:
                    self._btn_extra_effect = _eff
                else:
                    self._btn_effect = _eff

        self._hover_anim = self._make_hover_anim(self.HOVER_MS)
        self._apply_bg(0.0)

    def _apply_bg(self, t):
        self._hover = float(t)
        # 白 #FFFFFF → 淡蓝 #E6F1FB
        r = int(255 + (230 - 255) * t)
        g = int(255 + (241 - 255) * t)
        b = 255
        if self._flat:
            radius = (
                "border-bottom-left-radius:9px; border-bottom-right-radius:9px;"
                if self._round_bottom else ""
            )
            frame = f"QFrame#permRow{{background:rgb({r},{g},{b}); border:none; {radius}}}"
        else:
            frame = (
                f"QFrame#permRow{{background:rgb({r},{g},{b});"
                " border:1px solid #CBD5E1; border-radius:10px;}"
            )
        self.setStyleSheet(
            frame
            + "QFrame#permRow QLabel{background:transparent;}"
            "QPushButton#dangerBtn{background:transparent; color:#C0392B; border:1px solid #C0392B; border-radius:8px; padding:4px 12px;}"
            "QPushButton#dangerBtn:hover{background:#FDEDEC;}"
            "QPushButton#outlineBtn{background:transparent; color:#378ADD; border:1px solid #378ADD; border-radius:8px; padding:4px 12px;}"
            "QPushButton#outlineBtn:hover{background:#E6F1FB;}"
        )
        # 开关是自绘控件，底色要跟着行底色走（透明铺底时用它，否则露黑块）
        if self._switch is not None:
            self._switch.set_bg(QColor(r, g, b))
        self._apply_action_opacity(t)

    def _switch_clicked(self):
        """开关自己已经切好了视觉状态，这里把**新状态**交给面板。

        面板负责真正落地（可能弹一次管理员授权），失败时用 `set_switch` 拨回来 ——
        与「设置页开关按真实状态回拨」是同一套约定。
        """
        if self._on_switch is not None:
            self._on_switch(self._switch.isChecked())

    def set_switch(self, checked, animate=True):
        """把行内开关拨到指定状态（面板在落地失败 / 外部同步时调用）。"""
        if self._switch is not None:
            self._switch.setChecked(bool(checked), animate=animate)

    def switch_checked(self):
        return bool(self._switch is not None and self._switch.isChecked())

    def _apply_action_opacity(self, t):
        """按钮 / 行内开关随 hover 渐变淡入 / 淡出（与底色变化同一动画、同一 200ms）。

        一行最多 2 个按钮 + 1 个开关，各自持有自己的 effect —— 必须**一起**设置透明度，
        否则会出现「一个已经亮了、另一个还是暗的」的错位。
        开关是自绘控件，走它自己的 `set_opacity`（内部同时管 alpha 与鼠标穿透）；
        旁边的小字用 `QGraphicsOpacityEffect`，并一起屏蔽鼠标事件（透明白字不该能点）。
        """
        if not self._flat:
            return
        blocked = t < 0.5
        for b in self._action_btns:
            eff = b.graphicsEffect()
            if eff is not None:
                eff.setOpacity(t)
            if b.testAttribute(Qt.WA_TransparentForMouseEvents) != blocked:
                b.setAttribute(Qt.WA_TransparentForMouseEvents, blocked)
        if self._switch is not None:
            self._switch.set_opacity(t)
        if self._switch_lbl_effect is not None:
            self._switch_lbl_effect.setOpacity(t)
        if self._switch_lbl is not None:
            if self._switch_lbl.testAttribute(Qt.WA_TransparentForMouseEvents) != blocked:
                self._switch_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, blocked)

    # ---- 点「字样」等同点滑块 ----

    def eventFilter(self, obj, ev):
        """**点「开关字样」等同点滑块本体**。

        悬停说明气泡已按用户要求删除（2026-09-16：说明只在**开启前的确认弹窗**里出现），
        所以这里不再接管 Enter/Leave，只保留点击转发。
        """
        if (obj is self._switch_lbl and ev.type() == QEvent.MouseButtonPress
                and ev.button() == Qt.LeftButton):
            self._switch_toggle_from_label()
            return True
        return super().eventFilter(obj, ev)

    def _switch_toggle_from_label(self):
        """点「免 UAC」字样 = 点滑块（同一个语义，走同一条确认 / 回落逻辑）。"""
        if self._switch is None:
            return
        self._switch.toggle()
        self._switch.clicked.emit()

class _ToggleSwitch(QWidget):
    """圆形滑块开关：蓝色轨道 + 白色圆钮 = 开，灰色轨道 = 关。

    自绘（不走 QSS），点击即切换；圆钮位置带 140ms 过渡动画。
    """

    clicked = Signal()

    WIDTH = 44           # 轨道宽
    HEIGHT = 24          # 轨道高（圆钮直径 = HEIGHT - 2 * PAD）
    PAD = 3              # 圆钮与轨道边缘的留白
    DURATION = 140

    TRACK_ON = "#378ADD"         # 开：主蓝
    TRACK_ON_HOVER = "#2F74BF"   # 开：悬停加深
    TRACK_OFF = "#CBD5E1"        # 关：中性灰
    TRACK_OFF_HOVER = "#B4C2D2"  # 关：悬停加深
    TRACK_LOCKED = "#E2E8F0"     # 锁死：恒定的浅灰（不随开 / 关变色，见 design.md §4.13）
    KNOB = "#FFFFFF"

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = bool(checked)
        self._hover = False
        # 锁死（2026-09-22）：点不动 + 恒定灰轨道。目前唯一使用者是「静音模式」
        # —— 没下载音色克隆模型时它被锁死在「开」（见 docs/02 §22.5）。
        self._locked = False
        self._opacity = 1.0                       # 整体透明度（列表行 hover 时淡入）
        self._bg = QColor("#FFFFFF")              # 所在行的底色（先铺底再画，防黑块）
        self._t = 1.0 if self._checked else 0.0   # 圆钮归一化位置：0=左 1=右
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self.DURATION)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    # ---- 状态 ----

    def isChecked(self):
        return self._checked

    def set_bg(self, color):
        """同步所在行的底色：透明时用它铺底，否则会露出未初始化的黑底。"""
        self._bg = QColor(color)
        self.update()

    def set_opacity(self, value):
        """整体透明度（0 = 完全隐藏）。由所在行的 hover 动画驱动，与底色同步。

        用自绘 alpha 而不是 QGraphicsOpacityEffect：本控件本来就是 paintEvent 自绘，
        直接给颜色乘 alpha 更省一层离屏渲染。透明时同时屏蔽鼠标事件，避免点到
        「看不见但还在」的滑块。
        """
        value = max(0.0, min(1.0, float(value)))
        self._opacity = value
        blocked = value < 0.5
        if self.testAttribute(Qt.WA_TransparentForMouseEvents) != blocked:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, blocked)
        self.update()

    def set_locked(self, locked):
        """锁死：**点不动** + 轨道恒定画成灰（不随开 / 关变色、也不 hover 加深）。

        ★必须落在**这个控件**上，而不是外面的行控件：滑块是自绘的，而且
        `mousePressEvent` **不查 `isEnabled()`** —— 光调 `setEnabled(False)` 拦不住点击，
        滑块照样会翻过去（design.md §4.13 有记）。
        """
        locked = bool(locked)
        if locked == self._locked:
            return
        self._locked = locked
        self.setCursor(Qt.ArrowCursor if locked else Qt.PointingHandCursor)
        self._hover = False
        self.update()

    def is_locked(self):
        return self._locked

    def setChecked(self, checked, animate=True):
        checked = bool(checked)
        self._checked = checked
        target = 1.0 if checked else 0.0
        if not animate:
            self._anim.stop()
            self._t = target
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(target)
        self._anim.start()

    def toggle(self):
        self.setChecked(not self._checked)

    def _on_anim(self, value):
        self._t = float(value)
        self.update()

    # ---- 交互 ----

    def mousePressEvent(self, e):
        # 锁死：点了当没点（**不要** super()，否则事件还会冒泡到所在行）
        if self._locked:
            return
        if e.button() == Qt.LeftButton:
            self.toggle()
            self.clicked.emit()
        super().mousePressEvent(e)

    def enterEvent(self, e):
        if not self._locked:
            self._hover = True
            self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self._locked:
            self._hover = False
            self.update()
        super().leaveEvent(e)

    # ---- 绘制 ----

    def paintEvent(self, e):
        p = QPainter(self)
        # 先铺满所在行的底色：本控件会整体透明（未 hover 时），缺了这步会露出
        # 未初始化的黑块（子控件 backing store 不保证有父级内容）。
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg)
        p.drawRect(self.rect())
        if self._opacity <= 0.0:
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = r.height() / 2.0
        if self._locked:
            track = self.TRACK_LOCKED
        elif self._checked:
            track = self.TRACK_ON_HOVER if self._hover else self.TRACK_ON
        else:
            track = self.TRACK_OFF_HOVER if self._hover else self.TRACK_OFF
        track_c = QColor(track)
        track_c.setAlphaF(self._opacity)
        p.setBrush(track_c)
        p.drawRoundedRect(r, radius, radius)
        d = r.height() - 2 * self.PAD          # 圆钮直径
        x0 = r.left() + self.PAD               # 关：靠左
        x1 = r.right() - self.PAD - d          # 开：靠右
        knob_c = QColor(self.KNOB)
        knob_c.setAlphaF(self._opacity)
        p.setBrush(knob_c)
        p.drawEllipse(QRectF(x0 + (x1 - x0) * self._t, r.top() + self.PAD, d, d))


class _PermToggleRow(_HoverRow, QFrame):
    """操作类型开关行：名称 + 右侧圆形滑块（开=允许，关=禁止）。

    `flat=True`（折叠分组内容区）：无边框无圆角、与相邻行无缝；滑块默认隐藏，
    随行 hover 渐变**同步 200ms 淡入 / 淡出**。
    """

    HOVER_MS = 200

    def __init__(self, atype, text, allowed, on_toggle, flat=False, parent=None):
        super().__init__(parent)
        self._atype = atype
        self._on_toggle = on_toggle
        self._hover = 0.0
        self._flat = bool(flat)
        self._round_bottom = False
        self._allowed = bool(allowed)
        self.setObjectName("permToggleRow")
        self.setFixedHeight(44)
        hl = QHBoxLayout(self)
        margins = (10, 0, 10, 0) if self._flat else (16, 0, 12, 0)
        hl.setContentsMargins(*margins)
        hl.setSpacing(10)
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#0C447C; font-size:13px; background:transparent;")
        hl.addWidget(lbl, 1)
        self._btn = _ToggleSwitch(self._allowed)
        self._btn.clicked.connect(self._on_clicked)
        hl.addWidget(self._btn, 0, Qt.AlignVCenter)
        # flat 行：滑块默认完全隐藏，随行 hover 淡入；否则常显
        self._btn.set_opacity(0.0 if self._flat else 1.0)
        self._hover_anim = self._make_hover_anim(self.HOVER_MS)
        self._apply_bg(0.0)

    def _on_clicked(self):
        # 滑块自己已经切换了视觉状态，这里只同步行内记录并回调面板
        self._allowed = self._btn.isChecked()
        self._on_toggle(self._atype)

    def set_allowed(self, allowed):
        self._allowed = bool(allowed)
        self._btn.setChecked(self._allowed, animate=False)
        self._apply_bg(self._hover)

    def _apply_bg(self, t):
        self._hover = float(t)
        # 白 #FFFFFF → 淡蓝 #E6F1FB
        r = int(255 + (230 - 255) * t)
        g = int(255 + (241 - 255) * t)
        if self._flat:
            radius = (
                "border-bottom-left-radius:9px; border-bottom-right-radius:9px;"
                if self._round_bottom else ""
            )
            frame = f"QFrame#permToggleRow{{background:rgb({r},{g},255); border:none; {radius}}}"
            self._btn.set_bg(QColor(r, g, 255))
            self._btn.set_opacity(t)
        else:
            frame = ("QFrame#permToggleRow{background:#FFFFFF;"
                     " border:1px solid #CBD5E1; border-radius:10px;}")
        self.setStyleSheet(frame + "QFrame#permToggleRow QLabel{background:transparent;}")

class _HeadFrame(QFrame):
    """`_CollapsibleGroup` 的标题行容器：**自绘圆角底色**（不设 QSS）。

    hover 底色是逐帧渐变的。若用 `setStyleSheet` 落地，每帧都会触发样式重算 ——
    实测一次 200ms 的 hover 淡入会给标题行带来 **14 次 style + 14 次 layout**，
    里面的文字控件被反复 polish，视觉上就是「小字在重新渲染」。与左栏 `_ColorPanel`
    同一手法：`paintEvent` 自绘，动画期间零样式开销。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._bg = QColor("#FFFFFF")
        self._r_top = 0
        self._r_bottom = 0

    def set_bg(self, color, r_top, r_bottom):
        """底色 + 上/下圆角。值没变时直接返回，避免无谓重绘。"""
        color = QColor(color)
        r_top, r_bottom = int(r_top), int(r_bottom)
        if (color.rgb(), r_top, r_bottom) == (self._bg.rgb(), self._r_top, self._r_bottom):
            return
        self._bg = color
        self._r_top = r_top
        self._r_bottom = r_bottom
        self.update()

    def bg_rgb(self):
        return self._bg.rgb()

    def _arc(self, path, x, y, radius, start, sweep):
        if radius > 0:
            path.arcTo(QRectF(x, y, 2 * radius, 2 * radius), start, sweep)

    def paintEvent(self, e):
        r = QRectF(self.rect())
        tl = tr = self._r_top
        bl = br = self._r_bottom
        path = QPainterPath()
        path.moveTo(r.left() + tl, r.top())
        path.lineTo(r.right() - tr, r.top())
        self._arc(path, r.right() - 2 * tr, r.top(), tr, 90, -90)
        path.lineTo(r.right(), r.bottom() - br)
        self._arc(path, r.right() - 2 * br, r.bottom() - 2 * br, br, 0, -90)
        path.lineTo(r.left() + bl, r.bottom())
        self._arc(path, r.left(), r.bottom() - 2 * bl, bl, 270, -90)
        path.lineTo(r.left(), r.top() + tl)
        self._arc(path, r.left(), r.top(), tl, 180, -90)
        path.closeSubpath()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillPath(path, self._bg)


class _CollapsibleGroup(QWidget):
    """权限面板的可折叠分组：**一张带边框卡片**（标题行 + 内容区）。

    标题行 = **一个富文本 `QLabel`（大字标题 + 小字提示合成一个整体）** + 右端的
    「添加按钮 + 展开箭头」（装在固定高 28px 的 `_head_btns` 里）；添加按钮**只在
    展开时显示**（200ms 淡入淡出）。标题行底色由 `_HeadFrame` 自绘（hover 渐变不能走
    QSS，否则子控件每帧被 polish → 小字看起来在重新渲染）。

    卡片自带 `1px` 边框与 10px 圆角，展开时随高度动画**一起被拉长**，内容行自上而下
    逐条露出（超出卡片的部分会被裁掉）。默认收起。

    标题行（大字 + 小字）**全程贴在卡片上边框**：展开 / 收起时只有边框向下拉长 / 缩短，
    文字相对上边框的位置不动（高度恒 ≥ `HEAD_MIN_H`，无小字时文字块在这 60px 里垂直居中，
    见 `_head_height()`）。保证这一点需要**两条**措施：

    1. 标题行高度用 `setFixedHeight` 硬约束（`_sync_head_height()`）→ 卡片被强制改高时
       它自己不被"等比压缩"；标题行内底部 `addStretch(1)` 兜底把多余空白落到底部。
    2. **动画期间把内容区垂直策略临时改成 `Ignored`**（`_set_content_shrinkable`）→ 内容区
       不再向布局报"最小高度"，布局永远"装得下"，内容区因而**恒贴在标题行正下方**
       （`y = 标题行高 + 2×边框`），只被卡片裁掉。

    第 2 条是关键：只做第 1 条时，展开动画一轮里卡片高度会被强制压到「标题行 + 内容区
    最小高度」以下，`QBoxLayout` 兜底压缩会把**内容区整体上移**（实测 y 从 61 掉到
    0/36/42/48/55），它那些不透明白底的列表行就盖在标题行的小字上 → 标题 / 小字
    「消失后又逐帧露出」，即用户看到的抽动。逐帧采样验证见 `tests/smoke_settings.py`。

    展开 / 收起的动画沿用 API 管理里 API 行的方案 —— QTimer 16ms 手动驱动
    `setMinimumHeight` + `setMaximumHeight`（用 QPropertyAnimation 改 maximumHeight
    时 layout 的 sizeHint 不更新，视觉上常常看不到变化）。
    """

    HEAD_HOVER_MS = 200
    HEAD_HOVER_BG = (230, 241, 251)   # hover 终态底色 = 淡蓝 #E6F1FB（与 4.x 列表行同色）
    ANIM_MS = 200
    ADD_FADE_MS = 200    # 标题行内「添加按钮」淡入淡出时长（展开显示 / 收起隐藏）
    TIP_GAP = 4          # 标题（大字）与小字提示之间的间距，写进富文本的 margin-top
    HEAD_ROW_H = 28      # 首行高度 = 添加按钮高度：让「有无添加按钮」的分组标题行等高
    HEAD_MIN_H = 60      # 标题行**最小**高度：小字删掉之后仍保留原来的两行高度（文字垂直居中，卡片 62px）
    TICK_MS = 16
    RADIUS = 10          # 卡片外框圆角
    INNER_RADIUS = 9     # 内部色块圆角 = 外框圆角 − 1px 边框
    CARD_BORDER = 1      # 卡片边框宽度（QSS 值，仅用于高度换算）

    toggled = Signal(bool)   # 参数：切换后的「是否收起」

    def __init__(self, title, hint=None, add_text=None, on_add=None,
                 collapsed=True, parent=None):
        super().__init__(parent)
        self._collapsed = bool(collapsed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # 1) 卡片：外框边框随高度动画拉长，内部自上而下是 标题行 → 内容区
        self._card = QFrame()
        self._card.setObjectName("permGroupBox")
        self._card.setStyleSheet(
            "QFrame#permGroupBox{background:#FFFFFF; border:1px solid #CBD5E1;"
            f" border-radius:{self.RADIUS}px;}}"
            "QFrame#permGroupBox QLabel{background:transparent;}"
        )
        card_lay = QVBoxLayout(self._card)
        # 子控件让开 1px 边框：Qt 会把 QSS 的边框宽度算进布局可用区（自动 1px 内缩），
        # 这里不再手动加 margins，高度计算时按 CARD_BORDER*2 补回来即可。
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        # 2) 标题行（+ 小字提示）：整块可点，右端依次是「添加按钮」「展开指示箭头」
        self._head = _HeadFrame()
        self._head.setCursor(Qt.PointingHandCursor)
        # 标题行**不可压缩**（垂直 Minimum）+ `resizeEvent` 里 `setFixedHeight` 钉死：
        # 展开 / 收起动画期间卡片高度被强制改变，容器一旦小于布局的 minimumSize，
        # QBoxLayout 会「等比压缩所有子项」（实测标题行 56 → 28），小字提示被逐帧
        # 压扁又弹回 → 文字抽动。与 API 行把名称行 setFixedHeight(60) 是同一手法。
        self._head.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        hv = QVBoxLayout(self._head)
        hv.setContentsMargins(10, 6, 10, 6)
        hv.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        # 「大字标题 + 小字提示」= **同一个富文本 QLabel**（一个整体，一起排布 / 一起绘制）。
        # 拆成两个 widget 时它们会被各自 polish / 重排，hover 淡入一次各被刷 28 次，
        # 小字就会出现「重新渲染」的观感。
        self._title_lbl = QLabel()
        self._title_lbl.setTextFormat(Qt.RichText)
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setStyleSheet("background:transparent;")
        self._title_lbl.setText(self._head_html(title, hint))
        top.addWidget(self._title_lbl, 1)
        # 添加按钮 + 展开箭头：装在**固定高 HEAD_ROW_H 的容器**里，整体贴首行对齐。
        # 首行的高度就由这个容器撑着（`QLabel` 的文档比 28px 矮，靠默认 AlignVCenter 居中），
        # 所以 `_head_html` 里**不需要**再写 `line-height` —— 见那边的说明。容器内两者垂直居中、间距 8px。
        self._head_btns = QWidget()
        self._head_btns.setFixedHeight(self.HEAD_ROW_H)
        btns = QHBoxLayout(self._head_btns)
        btns.setContentsMargins(0, 0, 0, 0)
        btns.setSpacing(8)
        # 添加按钮：标题行右端、箭头左侧；**仅展开时显示**（200ms 淡入淡出）
        self._add_btn = None
        self._add_btn_eff = None
        self._add_anim = None
        if add_text:
            self._add_btn = QPushButton(add_text)
            self._add_btn.setObjectName("outlineBtn")
            self._add_btn.setCursor(Qt.PointingHandCursor)
            self._add_btn.setFixedHeight(self.HEAD_ROW_H)   # 与首行同高（等高）
            self._add_btn.clicked.connect(lambda _=False: on_add())
            self._add_btn_eff = QGraphicsOpacityEffect(self._add_btn)
            self._add_btn_eff.setOpacity(0.0)   # 默认收起 → 初始全透明
            self._add_btn.setGraphicsEffect(self._add_btn_eff)
            self._add_anim = QPropertyAnimation(self._add_btn_eff, b"opacity", self)
            self._add_anim.setDuration(self.ADD_FADE_MS)
            self._add_anim.finished.connect(self._on_add_fade_done)
            btns.addWidget(self._add_btn, 0, Qt.AlignVCenter)
        self._chevron = QLabel()
        self._chevron.setFixedSize(14, 14)
        btns.addWidget(self._chevron, 0, Qt.AlignVCenter)
        top.addWidget(self._head_btns, 0, Qt.AlignTop)
        # **首尾各一个 addStretch**：把「大字（+ 小字）+ 右侧按钮容器」整行在标题行里
        # **垂直居中**。高度 = max(文字行所需高度, HEAD_MIN_H = 60px)（见 `_head_height()`）：
        #   - 文字行本身由右侧那个固定 28px 的 `_head_btns` 撑高（文档只有 16px 上下，
        #     在 QLabel 里按默认 AlignVCenter 居中），带小字时再叠 4px 间距 + 16px 小字行；
        #   - 没小字（现行的四个分组）：28px 的行放进 60px 里，多出来的 20px 上下各分 10px。
        # 这正是 2026-09-18 用户口径「卡片高度改回原来的 62px、边框内的文字居中」的实现；
        # 文字相对上边框的位置**全程不变**（展开 / 收起只改卡片高度，见类文档）。
        # 注意：居中**不是**抽动问题的修复 —— 抽动的真因是动画期间内容区被
        # `QBoxLayout` 上移盖住标题行，见类文档第 2 条。
        hv.addStretch(1)
        hv.addLayout(top)
        hv.addStretch(1)
        card_lay.addWidget(self._head)

        # 4) 内容区：行都加到 body_lay（收起时整体隐藏）；行间无缝，靠卡片裁切
        self._content = QWidget()
        self._content.setStyleSheet("background:transparent;")
        # 备份默认垂直策略：动画期间会被临时改成 Ignored（见 `_set_content_shrinkable`），
        # 动画结束必须原样还原。
        self._content_v_policy = self._content.sizePolicy().verticalPolicy()
        self.body_lay = QVBoxLayout(self._content)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(0)
        card_lay.addWidget(self._content)
        lay.addWidget(self._card)

        # 标题 hover 渐变：白 #FFFFFF → 淡蓝 #E6F1FB（与 _PermRow 同手感）
        self._hover_t = 0.0
        self._head_anim = QVariantAnimation(self)
        self._head_anim.setDuration(self.HEAD_HOVER_MS)
        self._head_anim.valueChanged.connect(self._apply_head_bg)
        self._head.mousePressEvent = self._head_press
        self._head.enterEvent = self._head_enter
        self._head.leaveEvent = self._head_leave
        self._apply_head_bg(0.0)

        # 高度动画（QTimer 手动驱动，同 API 行）
        self._h_anim_timer = QTimer(self)
        self._h_anim_timer.setInterval(self.TICK_MS)
        self._h_anim_timer.timeout.connect(self._h_anim_tick)

        # 展开收尾「放开最小高度」的延迟触发器：见 `_release_min_height`
        self._min_release_timer = QTimer(self)
        self._min_release_timer.setSingleShot(True)
        self._min_release_timer.setInterval(0)
        self._min_release_timer.timeout.connect(self._release_min_height)

        self.set_collapsed(self._collapsed, animate=False)

    # ---- 状态 ----

    def is_collapsed(self):
        return self._collapsed

    def toggle(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed, animate=True):
        """切换展开 / 收起。状态真的变化时发 `toggled`（程序化调用也会被记录）。"""
        collapsed = bool(collapsed)
        changed = collapsed != self._collapsed
        self._collapsed = collapsed
        self._update_chevron()
        # 标题行在「收起」时是卡片最后一块（四角都要圆），展开后只圆上面两角
        self._apply_head_bg(self._hover_t)
        collapsed_h, expanded_h = self._measure()
        if not animate or not self.isVisible():
            # 免动画路径：直接落到终态（首次构建走这里，避免开局闪一下）
            self._h_anim_timer.stop()
            self._min_release_timer.stop()
            # 兜底还原策略：若上一次动画被此处打断（快速连点），策略可能还停在 Ignored
            self._set_content_shrinkable(False)
            self._content.setVisible(not collapsed)
            self._set_add_btn_visible(not collapsed, animate=False)
            # 收起态把高度钉死（min = max）：卡片不允许被父布局压扁，
            # 否则滚动区内容超高时标题 / 小字提示会被裁掉
            self.setMinimumHeight(collapsed_h if collapsed else 0)
            self.setMaximumHeight(collapsed_h if collapsed else MAX_WIDGET_H)
        else:
            start_h = max(self.height(), collapsed_h)
            # 动画开始：作废上一次「展开收尾延迟放开最小高度」（否则它会在本帧把最小高度清零，
            # 让正在进行的收起动画被父布局拉回 sizeHint）
            self._min_release_timer.stop()
            # **必须在显示内容区之前**先让它"没有最小高度诉求"：否则会存在一瞬
            # 「内容区已可见、卡片还只有收起高度」，布局立刻把它上移盖住标题行
            # （逐次布局采样实测 content.y 会掉到 31）。见 `_set_content_shrinkable`。
            self._set_content_shrinkable(True)
            if not collapsed:
                # 先显示内容（它在标题下方），再由高度动画逐步露出
                self._content.setVisible(True)
            # 添加按钮随展开淡入 / 随收起淡出（与高度动画同时进行）
            self._set_add_btn_visible(not collapsed, animate=True)
            # 立刻锁住当前高度，防 setVisible 让 layout 跳到 sizeHint
            self.setMinimumHeight(start_h)
            self.setMaximumHeight(start_h)
            self._animate_height(expanded_h if not collapsed else collapsed_h)
        if changed:
            self.toggled.emit(collapsed)

    def _release_min_height(self):
        """展开收尾：等布局把 sizeHint 重算完之后，再把最小高度交还给父布局。

        `_set_content_shrinkable(False)` 引起的布局失效是**排队投递**的 —— 同一个事件循环
        轮次里，分组自己的 `sizeHint()` 读到的还是「内容区按 Ignored 算」的旧值（只有标题
        行 62px）。若当场 `setMinimumHeight(0)`，父布局会先按 62px 摆一次、下一轮才弹回
        370px，展开收尾闪一下。推迟到下一轮就正好用上正确的 370px，不产生这个中间态。
        """
        if not self._collapsed:
            self.setMinimumHeight(0)

    @classmethod
    def _head_html(cls, title, hint):
        """标题行的富文本：**大字标题与小字提示合成同一个控件**（一个整体）。

        ⚠️ **首行刻意不写 `line-height`**（2026-09-18 第十二轮）：Qt 的富文本遇到固定行高时会把
        字形**贴着行盒底部**摆 —— 真机字体实测「28px 行盒里墨迹中心比行盒中心低 5.8px」，
        于是按行盒居中 = 大字看着偏下（用户看到的就是这个）。交给字体自己的行高时字形天然居中
        （实测偏差 -0.2px），再由 `hv` 首尾两个拉伸项把行盒居中，才是真的视觉居中。
        首行高度照样是 28px：右侧那个固定 `HEAD_ROW_H` 的 `_head_btns` 撑着，
        `QLabel` 默认 `AlignVCenter` 把这段文档在 28px 里居中 —— **几何一点没变**，
        所以展开 / 收起动画的那套「位置全程不变」断言不受影响。
        提示行补 `margin-top:4px`。文本一律 HTML 转义，避免标题 / 提示里的 `<` `&` 破坏富文本。
        """
        esc = lambda s: html.escape(str(s), quote=False)   # noqa: E731
        out = (f'<div style="margin:0; font-weight:bold;'
               f' color:#334155;">{esc(title)}</div>')
        if hint:
            out += (f'<div style="margin:{cls.TIP_GAP}px 0 0 0; line-height:16px;'
                    f' color:#64748B; font-size:12px;">{esc(hint)}</div>')
        return out

    def _head_height(self):
        """标题行真实高度：小字提示会自动换行，必须按**当前宽度**算而不是裸 sizeHint。

        `sizeHint()` 在控件还没有宽度时（构造阶段）返回的是「按方形估算」的多行高度，
        比实际所需的单行高度大好几像素，直接用会让卡片上下留白不一致。

        **下限 `HEAD_MIN_H`（60px）**：小字提示删掉之后（2026-09-18）四个分组的文字块只剩
        28px，按布局算出来是 40px —— 卡片会跟着缩到 42px。用户要求「改回原来的高度」，
        所以这里兜一道底：恒 ≥ 60px，短出来的部分由 `hv` 首尾两个拉伸项上下均分
        （文字垂直居中，卡片 = 60 + 上下各 1px 边框 = 62px）。
        ⚠️ `setFixedHeight` **不会**改变 `sizeHint()`（仍返回 40px），断言高度请用本函数或
        `HEAD_MIN_H`，不要用 `_head.sizeHint().height()`。
        """
        width = self._head.width() or self._card.width()
        lay = self._head.layout()
        if width > 0 and lay.hasHeightForWidth():
            h = lay.heightForWidth(width)
        else:
            h = self._head.sizeHint().height()
        return max(h, self.HEAD_MIN_H)

    def _sync_head_height(self):
        """把标题行高度**钉死**为当前宽度下的真实高度（`setFixedHeight`）。

        展开 / 收起动画期间卡片高度被强制改变，而 QBoxLayout 在容器小于自己的 minimumSize 时
        会**等比压缩所有子项**（实测标题行 56→28）。`setFixedHeight` 给的是硬约束、布局必须
        遵守，于是标题行高度全程不变。与 API 行把名称行 `setFixedHeight(60)` 是同一手法。
        注意：这只解决了"标题行自己被压扁"，**没有**解决"内容区被上移盖住标题行" ——
        后者由 `_set_content_shrinkable` 在动画期间处理。
        """
        h = self._head_height()
        if h > 0 and self._head.minimumHeight() != h:
            self._head.setFixedHeight(h)

    def _set_content_shrinkable(self, on):
        """动画期间临时把内容区**垂直策略改成 `Ignored`**（无最小高度诉求）。

        展开 / 收起动画会强制改变卡片高度。只要「标题行 + 内容区最小高度」超过当前卡片
        高度，`QBoxLayout` 就会兜底压缩，并把内容区**整体上移**（实测 `content.y` 从 61
        掉到 0/36/42/48/55），它那些不透明白底的列表行随即盖在标题行的小字上 → 标题 / 小字
        「消失后又逐帧露出」（抽动）。把内容区垂直策略设为 `Ignored` 后，它向布局报的
        最小高度是 0 → 布局永远"装得下" → 内容区恒贴在标题行正下方，只被卡片裁掉。

        **动画结束必须还原**：`Ignored` 会让卡片 `sizeHint` 不含内容区高度，若一直保留，
        松开高度约束（`setMinimumHeight(0)`）后卡片会缩回"只有标题行"的高度、内容被裁没。
        """
        pol = self._content.sizePolicy()
        target = QSizePolicy.Ignored if on else self._content_v_policy
        if pol.verticalPolicy() != target:
            pol.setVerticalPolicy(target)
            self._content.setSizePolicy(pol)

    def _measure(self):
        """返回 (收起高度, 展开高度)。与内容区当前可见性无关，直接按 sizeHint 算。"""
        head = self._head_height()
        # 卡片自身上下各 1px 边框不占 sizeHint，要显式加进高度里
        border = 2 * self.CARD_BORDER
        collapsed = head + border
        return collapsed, collapsed + self._content.sizeHint().height()

    def finish_body(self):
        """内容区收尾：把末行标记为「底部圆角」，与卡片外框圆角对齐。

        行本身没有边框、左右铺满卡片，方形色块会在卡片圆角处顶出去，所以末行
        单独补上底部圆角。每次往 `body_lay` 加完行后调用一次。
        """
        last = None
        for i in range(self.body_lay.count()):
            w = self.body_lay.itemAt(i).widget()
            if w is not None:
                last = w
        if last is not None and hasattr(last, "set_round_bottom"):
            last.set_round_bottom(True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not getattr(self, "_card", None):
            return
        # 宽度确定后（首次布局 / 滚动条出现消失 / 窗口缩放）把标题行高度钉死，
        # 这样展开动画期间它不会被卡片「等比压缩」→ 文字不再抽动。
        self._sync_head_height()
        # 首次布局后卡片宽度才确定，标题行（小字提示换行）的真实高度随之确定 →
        # 重新校准收起高度。否则初始收起态会和「手动收起一次」差几像素，
        # 几个分组之间也不一致。
        if not self._collapsed:
            return
        if self._h_anim_timer.isActive():
            return
        target = self._measure()[0]
        if target != self.maximumHeight():
            self.setMinimumHeight(target)
            self.setMaximumHeight(target)

    def _animate_height(self, target_h):
        # 注意：调用前 `set_collapsed` 已把内容区策略切成 Ignored（必须在 `setVisible` 之前），
        # 动画结束时由 `_h_anim_tick` 还原。这里不再重复切换，避免两处状态分叉。
        self._h_start = self.height()
        self._h_end = int(target_h)
        self._h_steps = max(1, self.ANIM_MS // self.TICK_MS)
        self._h_step = 0
        self._h_anim_timer.start()

    def _h_anim_tick(self):
        self._h_step += 1
        t = min(1.0, self._h_step / self._h_steps)
        h = int(self._h_start + (self._h_end - self._h_start) * t)
        # 同时设最小和最大高度，让 layout 接受新高度
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)
        if self._h_step >= self._h_steps:
            self._h_anim_timer.stop()
            if self._collapsed:
                # 收起完成：先隐藏内容，再还原策略（内容已隐藏，还原后布局不会把它上移闪一下）
                self._content.setVisible(False)
                self._set_content_shrinkable(False)
                # 高度钉死：不允许父布局把卡片压扁
                self.setMinimumHeight(self._h_end)
                self.setMaximumHeight(self._h_end)
            else:
                # 展开完成：先还原策略（让卡片 sizeHint 重新包含内容区高度），再放开高度限制。
                self._set_content_shrinkable(False)
                self.setMaximumHeight(MAX_WIDGET_H)
                # 关键：**本帧先钉住展开高度，把"放开最小高度"推迟到下一轮布局之后**。
                # `setSizePolicy` 的失效是排队投递的，同一轮里分组自己的 sizeHint 还是旧值
                # （内容区按 Ignored 算 = 只剩标题行 62px）；此刻若放开最小高度，父布局会先按
                # 62px 摆一次、下一轮才弹回 370px → 展开收尾闪一下（实测收尾 5 个布局事件里
                # 卡片掉回 62、内容区 y 掉到 31，标题行小字又被盖住一瞬）。
                self.setMinimumHeight(self._h_end)
                self._min_release_timer.start()

    def _update_chevron(self):
        pm = _chevron_pixmap(self._collapsed)
        if not pm.isNull():
            self._chevron.setPixmap(pm)

    def _set_add_btn_visible(self, visible, animate=True):
        """添加按钮只随分组展开显示：展开 → 淡入并显示；收起 → 淡出后隐藏。

        用 `QGraphicsOpacityEffect` + `QPropertyAnimation` 做 200ms 淡入淡出；
        免动画（首次构建 / 面板尚未显示）时直接落到终态。
        """
        if self._add_btn is None:
            return
        self._add_anim.stop()   # stop 不触发 finished，不会误隐藏
        if not animate or not self.isVisible():
            self._add_btn_eff.setOpacity(1.0 if visible else 0.0)
            self._add_btn.setVisible(visible)
            return
        if visible:
            self._add_btn.setVisible(True)
        self._add_anim.setStartValue(self._add_btn_eff.opacity())
        self._add_anim.setEndValue(1.0 if visible else 0.0)
        self._add_anim.start()

    def _on_add_fade_done(self):
        """淡出结束后把按钮真正隐藏（否则透明按钮仍占位、仍可点击）。"""
        if self._add_btn is not None and self._collapsed:
            self._add_btn.setVisible(False)

    # ---- 交互 ----

    def _head_press(self, e):
        if e.button() != Qt.LeftButton:
            return
        self.toggle()
        e.accept()

    def _head_enter(self, e):
        self._head_anim.stop()
        self._head_anim.setStartValue(self._hover_t)
        self._head_anim.setEndValue(1.0)
        self._head_anim.start()

    def _head_leave(self, e):
        # 鼠标移到标题行内的添加按钮上时也会触发本控件的 leaveEvent，
        # 这种情况不该收起 hover 底色（否则底色会在按钮周围「缺一块」）
        if self._add_btn is not None and self._add_btn.underMouse():
            return
        self._head_anim.stop()
        self._head_anim.setStartValue(self._hover_t)
        self._head_anim.setEndValue(0.0)
        self._head_anim.start()

    def _apply_head_bg(self, t):
        """标题行底色（**自绘**，不设 QSS —— 见 `_HeadFrame` 的说明）。

        白 `#FFFFFF` → 淡蓝 `#E6F1FB`（`HEAD_HOVER_BG`）按 t 插值；它位于卡片顶部：
        上面两角恒为内圆角；收起时它同时是卡片底部 → 四角全圆。
        """
        self._hover_t = float(t)
        r0, g0, b0 = 255, 255, 255
        r1, g1, b1 = self.HEAD_HOVER_BG
        color = QColor(
            int(r0 + (r1 - r0) * self._hover_t),
            int(g0 + (g1 - g0) * self._hover_t),
            int(b0 + (b1 - b0) * self._hover_t),
        )
        inner = self.INNER_RADIUS
        self._head.set_bg(color, inner, inner if self._collapsed else 0)


class PermPanel(_MessagePanel, QWidget):
    """嵌入右侧的权限管理面板（白名单 + 危险级延迟执行）。"""

    # 可折叠分组的默认状态：True = 收起。四个白名单分组默认收起，
    # 「危险操作延迟」不参与折叠（只有一行，保持常显）。
    DEFAULT_GROUP_COLLAPSED = {"dirs": True, "apps": True, "actions": True, "blocked": True}

    # 间距（用户确认值）：分组之间 20px；「危险操作延迟」与上方分组之间 30px。
    # 实现：滚动区行距由 `_BODY_SPACING` 给定，故每组后再补 `GROUP_GAP-_BODY_SPACING`；
    # 「危险操作延迟」前在末尾再补 `DELAY_GAP-GROUP_GAP`，两个值因此完全独立可调。
    GROUP_GAP = 20
    DELAY_GAP = 30
    _BODY_SPACING = 8    # = _panel_scroll() 里 body_lay 的 setSpacing 值

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        # 各分组的展开 / 收起状态，跨 rebuild 保留（删一行不会把分组弹回收起）
        self._group_state = dict(self.DEFAULT_GROUP_COLLAPSED)
        # 软件名 → 该行的 `_PermRow`（开关落地失败时要拨回它）；rebuild 时整体重建
        self._app_rows = {}
        self._build()
        self._apply_style()
        self._rebuild()

    # ---- 数据 ----

    def _perms(self):
        if not isinstance(self.cfg.get("permissions"), dict):
            self.cfg["permissions"] = {}
        return self.cfg["permissions"]

    def _materialize(self):
        """把当前生效值落成显式配置：首次编辑后不再依赖内置默认。"""
        from .tools import get_permissions
        eff = get_permissions()
        p = self._perms()
        for key in ("allowed_dirs", "allowed_apps", "allowed_actions", "blocked_keywords",
                    "no_uac"):
            p[key] = list(eff.get(key, []))
        p["danger_delay"] = int(eff.get("danger_delay", 30))
        p["custom_apps"] = dict(eff.get("custom_apps") or {})
        return p

    def _commit(self, msg=None, error=False, rebuild=True):
        """写回权限并持久化。

        `rebuild=False` 用于**不改变列表结构**的操作（如切换操作类型开关）：滑块
        自身已经切好了视觉状态，重建整棵内容树只会让光标下那一行的 hover 态和
        滑块淡入被打断（重建后的新控件收不到 enter 事件，滑块会诡异地消失）。
        """
        from .tools import apply_permissions
        apply_permissions(self._perms())
        save_config(self.cfg)
        if rebuild:
            self._rebuild()
        if msg:
            self._msg(msg, error)

    def reset_groups(self):
        """把所有可折叠分组复位成默认的收起态。

        由 `MainWindow._refresh_settings_panel` 在**真正发生页面切换进入本页**时调用：
        分组展开状态只在当前停留期间有效，切走再回来一律回到收起。
        （rebuild 之类的内部刷新不调它 —— 删一行不该把分组弹回去。）
        """
        self._group_state = dict(self.DEFAULT_GROUP_COLLAPSED)

    # ---- 界面 ----

    def _build(self):
        lay = QVBoxLayout(self)
        # 底边距用 TAIL_BOTTOM(4px)：底部消息行区的总高必须正好等于「滚动条到窗口右侧的
        # 间距」(24px) = TAIL_BOTTOM(4) + TAIL_GAP(4) + 消息行 16，见 _panel_bottom()。
        lay.setContentsMargins(24, 20, 24, TAIL_BOTTOM)
        lay.setSpacing(14)

        # 标题行：左「权限管理」、右侧「回到顶部」+「恢复默认」（同一行，按钮靠右上角）
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        title = QLabel("权限管理")
        title.setStyleSheet("font-size:16px; font-weight:bold; color:#0C447C; background:transparent;")
        head.addWidget(title, 0, Qt.AlignVCenter)
        # stretch 把右侧两个按钮一起顶到最右边。「回到顶部」排在它右边 ⇒ 隐藏 / 出现
        # 都只影响自己，不会顶动「恢复默认」（不需要靠"永远占位"来防抖）。
        head.addStretch(1)
        self._reset_btn = QPushButton("恢复默认")
        self._reset_btn.setObjectName("outlineBtn")
        self._reset_btn.setCursor(Qt.PointingHandCursor)
        self._reset_btn.clicked.connect(self._restore_defaults)
        head.addWidget(self._reset_btn, 0, Qt.AlignVCenter)
        lay.addLayout(head)
        self._head_row = head

        # 标题下**不写说明小字**（2026-09-18 用户口径，与通用设置同一次优化）：这一页的
        # 说明只留「危险操作延迟」那一条（见 `_rebuild()` 第 5 段），其余灰色文字全删。

        self._scroll, self._body, self._body_lay, self._msg_label = _panel_bottom(lay)

        # 「回到顶部」插到「恢复默认」左边（此时 head = [标题, stretch, 恢复默认]）。
        # 建在这里是因为它要拿到滚动区（`_panel_bottom` 之后才有 `self._scroll`）。
        self._top_btn = _ScrollTopButton(self._scroll)
        head.insertWidget(head.indexOf(self._reset_btn), self._top_btn, 0, Qt.AlignVCenter)

    def _apply_style(self):
        self.setStyleSheet(
            "QWidget { background:#FFFFFF; color:#334155; font-size:13px; }"
            "QPushButton#outlineBtn { background:transparent; color:#378ADD; border:1px solid #378ADD; border-radius:8px; padding:6px 14px; }"
            "QPushButton#outlineBtn:hover { background:#E6F1FB; }"
        )

    def _clear_body(self):
        _clear_body(self._body_lay)

    def _group(self, name, hint, add_text=None, on_add=None):
        """常显分组（不可折叠）：分组小标题（+ 可选添加按钮）+ 提示行。"""
        _group_header(self._body_lay, name, hint, add_text, on_add)

    def _collapsible_group(self, key, name, hint, add_text=None, on_add=None):
        """可折叠分组：**带边框卡片（标题行右端带添加按钮 + 提示行 + 内容区）**。

        内容行加在返回的 `group.body_lay` 上（不是 `self._body_lay`），加完记得调
        `group.finish_body()` 让末行补底部圆角；空列表提示用
        `_hint_tip(group.body_lay, ...)`。展开状态在 `_group_state` 里按 key 记着，
        rebuild 后原样恢复；页面切换重新进入时由 `reset_groups()` 清空。
        """
        group = _CollapsibleGroup(
            name, hint, add_text, on_add,
            collapsed=self._group_state.get(key, True),
        )
        group.toggled.connect(lambda c, k=key: self._group_state.__setitem__(k, c))
        self._body_lay.addWidget(group)
        # 组间间距 = 滚动区行距 8 + 这里 (GROUP_GAP-8) = GROUP_GAP（20px）
        self._body_lay.addSpacing(self.GROUP_GAP - self._BODY_SPACING)
        return group

    def _rebuild(self):
        from .tools import DEFAULT_ALLOWED_ACTIONS, get_permissions
        # 重建 = 拆掉全部内容再重新摆一遍。**滚动位置必须原样搬运**：用户要求
        # 「做出修改时画面不要滑动」—— 增删改一行不该把视口带到别处（行内按钮
        # 的焦点已经由 `_clear_body` 收掉，这里再兜一道硬的）。
        _sb = self._scroll.verticalScrollBar()
        _keep = _sb.value()
        self._clear_body()
        eff = get_permissions()
        dirs = eff.get("allowed_dirs", [])
        apps = eff.get("allowed_apps", [])
        actions = eff.get("allowed_actions", [])
        blocked = eff.get("blocked_keywords", [])
        delay = int(eff.get("danger_delay", 30))

        # 1. 目录范围（可折叠，默认收起）
        # 分组标题后面**不再跟说明小字**（2026-09-18 用户口径，与通用设置同一件事）：
        # 只有「危险操作延迟」那一组保留（见本方法第 5 段）。
        g = self._collapsible_group(
            "dirs", "可操作目录/文件夹", "",
            "添加目录", self._add_dir,
        )
        if dirs:
            for d in dirs:
                g.body_lay.addWidget(
                    _PermRow(d, "删除", lambda p=d: self._remove_item("allowed_dirs", p),
                             mono=True, flat=True)
                )
        else:
            _hint_tip(g.body_lay, "暂无允许目录，所有打开操作都会被拒绝。")
        g.finish_body()

        # 2. 软件范围（可折叠，默认收起）
        #    提示行**必须保持单行**：四个分组的标题行高度要一致（`_head` 由
        #    「组名 + 提示」合成一个富文本 QLabel，提示多一行整块就高一截）。
        #    「免 UAC」的说明**不在内容区常驻**（用户要求删掉那一行），改成
        #    **悬停「免 UAC」字样或滑块时弹出的气泡**（蓝边 + 浅底 + 深字，同聊天气泡）。
        g = self._collapsible_group(
            "apps", "可启动软件", "",
            "添加软件", self._add_app,
        )
        self._app_rows = {}
        if apps:
            custom_apps = eff.get("custom_apps", {}) or {}
            no_uac = set(eff.get("no_uac", []) or [])
            for a in apps:
                # 只有「从磁盘添加的软件」才有「重命名」——内置软件的名字是固定映射，改不了；
                # 蓝色镂空按钮排在红色「删除」左侧（与 API 行「蓝编辑 / 红删除」同序）。
                # 「免 UAC」同理：只有自定义软件有 exe 绝对路径，建得出计划任务。
                is_custom = a in custom_apps
                kw = {}
                if is_custom:
                    kw["extra_text"] = "重命名"
                    kw["on_extra"] = (lambda x=a: self._rename_app(x))
                    kw["switch_text"] = "免 UAC"
                    kw["switch_checked"] = a in no_uac
                    kw["on_switch"] = (lambda want, x=a: self._toggle_no_uac(x, want))
                    # 「免 UAC」的说明**只在开启前的确认弹窗里**出现（2026-09-16 用户要求
                    # 删除悬停气泡、只留弹窗），所以行上不再挂任何提示。
                row = _PermRow(a, "删除", lambda x=a: self._remove_item("allowed_apps", x),
                               flat=True, **kw)
                self._app_rows[a] = row
                g.body_lay.addWidget(row)
        else:
            _hint_tip(g.body_lay, "暂无允许软件。")
        g.finish_body()

        # 3. 操作类型（可折叠，默认收起）
        g = self._collapsible_group(
            "actions", "可操作类型", ""
        )
        known = list(DEFAULT_ALLOWED_ACTIONS)
        for extra in actions:
            if extra not in known:
                known.append(extra)
        for atype in known:
            g.body_lay.addWidget(
                _PermToggleRow(
                    atype,
                    _ACTION_NAMES.get(atype, atype),
                    atype in actions,
                    self._toggle_action,
                    flat=True,
                )
            )
        g.finish_body()

        # 4. 禁止关键词（可折叠，默认收起）
        g = self._collapsible_group(
            "blocked", "禁止关键词", "",
            "添加关键词", self._add_blocked,
        )
        if blocked:
            for kw in blocked:
                g.body_lay.addWidget(
                    _PermRow(kw, "删除", lambda k=kw: self._remove_item("blocked_keywords", k),
                             flat=True)
                )
        else:
            _hint_tip(g.body_lay, "暂无禁止关键词。")
        g.finish_body()

        # 5. 危险操作延迟（只有一行，不可折叠、常显）
        # 与上方分组的间距独立设置：上面那组后已加过 GROUP_GAP，这里补差额到 DELAY_GAP（30px）
        self._body_lay.addSpacing(self.DELAY_GAP - self.GROUP_GAP)
        self._group("危险操作延迟", "关机 / 重启 / 注销 / 锁屏执行前的等待时间，期间可语音取消。")
        self._body_lay.addWidget(
            _PermRow(f"{delay} 秒", "修改", self._edit_delay, danger=False)
        )

        self._body_lay.addStretch(1)
        # 复原滚动位置（内容变短时按新上限收敛，不会越界）
        _sb.setValue(min(_keep, _sb.maximum()))

    # ---- 交互 ----

    def _add_dir(self):
        """选一个可操作目录/文件夹：直接弹系统文件夹选择框，默认停在「计算机」。"""
        dlg = QFileDialog(self, "选择可操作目录/文件夹")
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.ShowDirsOnly, True)
        dlg.setDirectoryUrl(_dialog_start_url())
        if not dlg.exec():
            return
        picked = dlg.selectedFiles()
        if not picked:
            return
        d = str(Path(picked[0])).replace("\\", "/")
        p = self._materialize()
        if d in p["allowed_dirs"]:
            self._msg(f"目录「{d}」已在允许列表内。", error=True)
            return
        p["allowed_dirs"].append(d)
        self._commit(f"已添加目录「{_elide_middle(d, 30)}」。")

    def _add_app(self):
        """选一个可启动软件：直接弹系统文件选择框（只列 exe），默认停在「计算机」。

        软件名取**文件名去扩展名**，exe 的绝对路径登记进 `custom_apps` ——
        这样内置表之外的程序也能被「打开 XXX」识别并启动。
        """
        from .tools import DEFAULT_DENIED_APPS, is_denied_app
        dlg = QFileDialog(self, "选择可启动软件")
        dlg.setFileMode(QFileDialog.ExistingFile)
        dlg.setNameFilter("程序 (*.exe)")
        dlg.setDirectoryUrl(_dialog_start_url())
        if not dlg.exec():
            return
        picked = dlg.selectedFiles()
        if not picked:
            return
        exe = Path(picked[0])
        name = exe.stem.strip()
        if not name:
            self._msg("无法从这个文件推断软件名，请换一个 exe。", error=True)
            return
        if is_denied_app(name) or is_denied_app(exe.name):
            self._msg(
                "「{}」属于默认禁止的命令入口（{}），不能添加。".format(
                    name, "、".join(DEFAULT_DENIED_APPS)
                ),
                error=True,
            )
            return
        p = self._materialize()
        if name in p["allowed_apps"]:
            self._msg(f"软件「{name}」已在允许列表内。", error=True)
            return
        p["allowed_apps"].append(name)
        p.setdefault("custom_apps", {})[name] = str(exe).replace("\\", "/")
        self._commit(f"已允许打开「{name}」。")

    def _toggle_no_uac(self, app_name, want):
        """「免 UAC」开关：开 = 建一个最高权限计划任务（弹一次授权）；关 = 只从配置里摘掉。

        **开之前先用弹窗确认**（弹窗里就是原来那条悬停说明）：开着要弹一次管理员授权、
        且会留下一个计划任务，属于「需要用户明确点头」的操作 —— 与删除类操作同一套约定。
        **关的时候不删任务** —— 任务没有触发器、只在被点名时启动，留着既无副作用，
        又省掉下次再开时那次授权。彻底删除交给「删除软件」和「恢复默认」里的批量清理。

        开关由滑块自己先切好了视觉，这里落地；用户取消 / 失败（取消授权、建任务失败）
        就把它拨回去 —— 不能让界面显示「已开启」而实际没生效。
        """
        from . import launch_task
        row = (self._app_rows or {}).get(app_name)
        p = self._materialize()
        no_uac = p.setdefault("no_uac", [])
        if not want:
            if app_name in no_uac:
                no_uac.remove(app_name)
                self._commit(rebuild=False)
            self._msg(f"已关闭「{app_name}」的免 UAC（下次打开会照常请求授权）。")
            return
        # 弹窗确认（说明只在**开启**方向给；文案不再夹带「点确认后会弹授权框」的括注，
        # 2026-09-16 用户要求去掉）
        if not ConfirmDialog.confirm(
            self,
            f"开启后，打开「{app_name}」不再弹出 UAC 授权框。\n\n"
            "需要一次管理员授权，之后一直有效。",
            "确认", "取消",
        ):
            if row is not None:
                row.set_switch(False)
            self._msg(f"已取消开启「{app_name}」的免 UAC。")
            return
        exe = (p.get("custom_apps") or {}).get(app_name) or ""
        if not exe:
            if row is not None:
                row.set_switch(False)
            self._msg(f"「{app_name}」没有登记可执行文件，无法免 UAC 启动。", error=True)
            return
        ok, info = launch_task.ensure_task(exe)
        if not ok:
            if row is not None:
                row.set_switch(False)
            self._msg(f"「{app_name}」免 UAC 设置失败：{info}", error=True)
            return
        if app_name not in no_uac:
            no_uac.append(app_name)
        self._commit(rebuild=False)
        self._msg(f"已为「{app_name}」开启免 UAC，之后打开它不再弹授权框。")

    def _add_blocked(self):
        kw, ok = InputDialog.get_text(self, "添加禁止关键词", "关键词", "")
        if not ok or not kw.strip():
            return
        kw = kw.strip()
        p = self._materialize()
        if kw in p["blocked_keywords"]:
            self._msg(f"禁止词「{kw}」已存在。", error=True)
            return
        p["blocked_keywords"].append(kw)
        self._commit(f"已添加禁止词「{kw}」。")

    def _remove_item(self, group, value):
        # 目录 / 软件 / 禁止词三处删除共用这一个入口 —— 在这里统一二次确认，
        # 与 API、唤醒词、恢复默认的删除行为保持一致。
        kind = {
            "allowed_dirs": "目录",
            "allowed_apps": "软件",
            "blocked_keywords": "禁止词",
        }.get(group, "条目")
        if not ConfirmDialog.confirm(
            self,
            f"确定要删除{kind}「{_elide_middle(str(value), 30)}」吗？此操作不可撤销。",
        ):
            return
        p = self._materialize()
        if value in p[group]:
            p[group].remove(value)
            extra = ""
            # 删掉软件时一并清掉它的自定义登记（内置 APP_MAP 的名字本来就不在表里）
            if group == "allowed_apps":
                exe = p.get("custom_apps", {}).pop(value, None)
                if value in (p.get("no_uac") or []):
                    p["no_uac"].remove(value)
                    # 顺手删掉它的免 UAC 计划任务（要一次管理员授权）。
                    # 用户取消授权也不影响：任务无触发器、又不再被引用，等同失效。
                    if exe:
                        from . import launch_task
                        ok, _info = launch_task.remove_task(exe)
                        if not ok:
                            extra = "（免 UAC 计划任务未删除，但已不再生效）"
            self._commit(f"已移除「{_elide_middle(str(value), 30)}」。{extra}")
        else:
            self._commit()

    def _rename_app(self, old):
        """重命名「从磁盘添加的软件」—— 改的是**匹配用的名字**，exe 路径不动。

        exe 的文件名常和用户平时说的名字对不上（`WeaselSetup.exe` / `QQMusic.exe`），
        而语音识别正是按这个显示名匹配的，所以允许改名才能让指令对上口语。
        内置 `APP_MAP` 的软件没有这一项（名字固定、也没有路径可改）。
        """
        from .tools import APP_MAP, DEFAULT_DENIED_APPS, is_denied_app
        p = self._materialize()
        custom = p.get("custom_apps", {})
        if old not in custom:
            self._msg(f"「{old}」是内置软件，名字固定，不支持重命名。", error=True)
            return
        new, ok = InputDialog.get_text(self, "重命名软件", "新的软件名", old)
        if not ok:
            return
        new = (new or "").strip()
        # 1) 空 / 与原名相同 → 视为取消
        if not new or new == old:
            return
        # 2) 命中默认禁止的命令入口 → 拒绝（否则等于用改名绕过黑名单）
        if is_denied_app(new):
            self._msg(
                "「{}」属于默认禁止的命令入口（{}），不能用这个名字。".format(
                    new, "、".join(DEFAULT_DENIED_APPS)
                ),
                error=True,
            )
            return
        # 3) 与内置软件或已添加的软件重名 → 拒绝。
        #    detect_action 是「先 APP_MAP 后 custom_apps」的顺序遍历，重名会让
        #    自定义这条永远匹配不到 —— 界面显示新名字、语音却启动另一个，静默失效。
        #    比对用**待写入的 p**（而不是 tools 里上一次落盘的状态），免得连续操作时口径不一致。
        taken = set(APP_MAP) | set(p.get("allowed_apps", []))
        if new in taken:
            self._msg(f"「{new}」已被内置软件或其他软件占用，请换一个名字。", error=True)
            return
        # 校验全部通过后再落盘，避免「改了一半」的中间态
        exe = custom.pop(old)
        custom[new] = exe
        p["allowed_apps"] = [new if x == old else x for x in p["allowed_apps"]]
        # 「免 UAC」记的也是显示名，必须一起改 —— 只改一边会让开关凭空消失
        # （计划任务名由 exe 路径推出，与显示名无关，所以任务本身不用动）。
        p["no_uac"] = [new if x == old else x for x in p.get("no_uac", [])]
        self._commit(f"已把「{old}」重命名为「{new}」。")

    def _toggle_action(self, atype):
        p = self._materialize()
        actions = p["allowed_actions"]
        if atype in actions:
            actions.remove(atype)
            self._commit(f"已禁止「{_ACTION_NAMES.get(atype, atype)}」类操作。", rebuild=False)
        else:
            actions.append(atype)
            self._commit(f"已允许「{_ACTION_NAMES.get(atype, atype)}」类操作。", rebuild=False)

    def _edit_delay(self):
        from .tools import get_permissions
        cur = int(get_permissions().get("danger_delay", 30))
        text, ok = InputDialog.get_text(self, "危险操作延迟", "延迟秒数（5~120）", str(cur))
        if not ok or not text.strip():
            return
        try:
            val = int(float(text.strip()))
        except ValueError:
            self._msg("请输入 5~120 之间的整数。", error=True)
            return
        if not 5 <= val <= 120:
            self._msg("请输入 5~120 之间的整数。", error=True)
            return
        p = self._materialize()
        p["danger_delay"] = val
        self._commit(f"危险操作延迟已设为 {val} 秒。")

    def _restore_defaults(self):
        if not ConfirmDialog.confirm(self, "确定要恢复默认权限设置吗？自定义的目录、软件和禁止词都会被清空。"):
            return
        had_no_uac = bool(self._perms().get("no_uac"))
        self.cfg["permissions"] = {
            "allowed_dirs": [],
            "allowed_apps": [],
            "allowed_actions": [],
            "blocked_keywords": [],
            "danger_delay": 30,
            "custom_apps": {},
            "no_uac": [],
        }
        # 自定义软件全清 → 它们的免 UAC 计划任务都成了孤儿，一次性清掉（要一次管理员授权；
        # 取消授权也不影响使用，只是任务还挂在任务计划里，无触发器、不会被自动触发）。
        extra = ""
        if had_no_uac:
            from . import launch_task
            if not launch_task.remove_all_tasks()[0]:
                extra = "（免 UAC 计划任务未清理，但已不再生效）"
        self._commit(f"已恢复默认权限。{extra}")


# ========== 通用设置面板 ==========

def _setting_outline_button(text):
    """设置行右侧的**蓝色镂空按钮**（`#outlineBtn`，高 28px）。

    `outlineBtn` 在本项目一向是**分面板各写一份** QSS 的（见 `_SettingActionRow` 的注释）；
    但设置页这几行属于**同一页同一个视觉规格**，所以从 2026-09-22 起收敛到这一个工厂函数里
    —— 多了 `:disabled` 态（灰字 `#94A3B8` + 灰边 `#CBD5E1`），给「下载 / 卸载」用。
    """
    btn = QPushButton(text)
    btn.setObjectName("outlineBtn")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(28)
    btn.setStyleSheet(
        "QPushButton#outlineBtn{background:transparent; color:#378ADD;"
        " border:1px solid #378ADD; border-radius:8px; padding:4px 12px; font-size:12px;}"
        "QPushButton#outlineBtn:hover{background:#E6F1FB;}"
        "QPushButton#outlineBtn:disabled{color:#94A3B8; border-color:#CBD5E1; background:transparent;}"
    )
    return btn


class _SettingRow(QFrame):
    """设置行基类：左「标题 13px #0C447C + **可选**说明 12px #64748B」，右侧挂控件。

    高 58px、圆角 10px、`1px solid #CBD5E1` 边框（同 4.11 权限行视觉）。

    **说明行是可选的**（2026-09-18 用户口径）：通用设置里那些解释性小字**全部删掉**了 ——
    标题下再挂一行灰字只会显得拥挤。传空串时不显示那一行（`setVisible(False)`，不占位），
    只剩标题时 QLabel 自己**垂直居中**，行高仍是 58px —— 与权限页的行高一致。
    `set_hint()` 之后按新文本重新决定显不显示，别写死。

    标题 / 说明都是**单行** QLabel，而 QLabel 不换行时 `minimumSizeHint` 就等于整段
    文字宽度 —— 文字较长时会把行顶宽，滚动区的 body 随之被撑到可视区之外
    （`widgetResizable` 取 max(viewport, 最小宽)，水平滚动条又是 AlwaysOff），
    **行的右边框就被裁掉了**（实测窗口 820 默认尺寸：body 608 > viewport 589）。
    所以文字块的横向策略设为 `Ignored`（不参与最小宽度协商），并改由
    `_apply_elide()` 按当前宽度做右侧省略 —— 行宽永远跟着可视区走，四边闭合。
    """

    def __init__(self, title, hint, parent=None):
        super().__init__(parent)
        self.setObjectName("settingRow")
        self.setFixedHeight(58)
        # 文案原文：宽度变化时按可用宽度重新省略（见 `_apply_elide`）
        self._title_text = str(title)
        self._hint_text = str(hint or "")
        hl = QHBoxLayout(self)
        hl.setContentsMargins(16, 8, 12, 8)
        hl.setSpacing(10)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        self._title = QLabel(self._title_text)
        self._title.setStyleSheet("color:#0C447C; font-size:13px; background:transparent;")
        self._title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left.addWidget(self._title)
        self._hint = QLabel(self._hint_text)
        self._hint.setStyleSheet("color:#64748B; font-size:12px; background:transparent;")
        self._hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # 没有说明就不占那一行（QSizePolicy.Ignored 只保证不吃宽度，高度得靠 hide 收掉）
        self._hint.setVisible(bool(self._hint_text))
        left.addWidget(self._hint)
        hl.addLayout(left, 1)
        self._row = hl

        self.setStyleSheet(
            "QFrame#settingRow{background:#FFFFFF; border:1px solid #CBD5E1; border-radius:10px;}"
            "QFrame#settingRow QLabel{background:transparent;}"
        )

    def add_right(self, widget, alignment=None):
        """右侧控件（自动靠右：左侧标题占 stretch=1）。"""
        if alignment is None:
            self._row.addWidget(widget)
        else:
            self._row.addWidget(widget, 0, alignment)
        return widget

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_elide()

    def _apply_elide(self):
        """按当前宽度把「标题 / 说明」做右侧省略（宽度不足时不再顶宽整行）。"""
        for lbl, full in ((self._title, self._title_text), (self._hint, self._hint_text)):
            avail = lbl.width()
            if avail <= 0 or not full:
                continue
            elided = lbl.fontMetrics().elidedText(full, Qt.ElideRight, avail)
            if elided != lbl.text():
                lbl.setText(elided)

    def set_hint(self, text):
        self._hint_text = str(text or "")
        self._hint.setText(self._hint_text)
        self._hint.setVisible(bool(self._hint_text))
        self._apply_elide()


class _SettingToggleRow(_SettingRow):
    """开关行：右侧**圆形滑块开关**（与权限管理页的 `_ToggleSwitch` 同款）。

    开 = 蓝轨道 `#378ADD` + 圆钮靠右，关 = 灰轨道 `#CBD5E1` + 圆钮靠左；
    滑块自绘、点击即切换（圆钮位置 140ms OutCubic 过渡）。点击后只回调面板，
    由面板按**注册表实际状态**回拨 —— 写失败时滑块自动回到真实状态。
    """

    def __init__(self, title, hint, enabled, on_toggle, parent=None):
        super().__init__(title, hint, parent)
        self._enabled = bool(enabled)
        self._on_toggle = on_toggle
        sw = _ToggleSwitch(self._enabled)
        sw.set_bg("#FFFFFF")                 # 行底色为白：透明态铺底，防露黑块
        sw.clicked.connect(self._on_clicked)
        self._switch = sw
        self.add_right(sw, Qt.AlignVCenter)

    def _on_clicked(self):
        # 滑块自己已经切换了视觉状态，这里只同步行内记录再回调面板
        self._enabled = self._switch.isChecked()
        self._on_toggle()

    def is_enabled(self):
        return self._enabled

    def set_enabled(self, enabled, animate=True):
        """把滑块拨到指定状态（面板按注册表实际值同步；写失败时回弹）。"""
        self._enabled = bool(enabled)
        self._switch.setChecked(self._enabled, animate=animate)

    def set_locked(self, locked):
        """锁死这一行：滑块置灰 + 点不动 + 标题降成 `#94A3B8`（design.md §4.13）。

        目前唯一使用者是通用设置里的「静音模式」—— 没下载音色克隆模型时它被锁死在「开」。
        """
        locked = bool(locked)
        self._switch.set_locked(locked)
        self._title.setStyleSheet(
            "color:%s; font-size:13px; background:transparent;"
            % ("#94A3B8" if locked else "#0C447C")
        )

    def is_locked(self):
        return self._switch.is_locked()


# ---- 自绘小控件的颜色插值（`_PresetDot` 用；`_RadioDot` 已于 2026-10-01 整块删除）----

def _mix_color(c1, c2, t):
    """两个颜色按 t 插值（t=0 → c1，t=1 → c2）。"""
    a, z = QColor(c1), QColor(c2)
    return QColor(round(a.red() + (z.red() - a.red()) * t),
                  round(a.green() + (z.green() - a.green()) * t),
                  round(a.blue() + (z.blue() - a.blue()) * t))


def _fade_color(c, t):
    """同色，整体不透明度 = t（超出 0~1 会被夹住）。"""
    col = QColor(c)
    col.setAlphaF(max(0.0, min(1.0, float(t))))
    return col


class _RadioItem(QWidget):
    """一个选项 = **实心圆单选 + 文字**，整块可点（点文字等同点圆点）。"""

    clicked = Signal()

    def __init__(self, text: str, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        self._dot = _PresetDot(checked)      # ★2026-10-01：与设定卡同一个类（实心圆）
        self._lbl = QLabel(str(text))
        self._lbl.setStyleSheet("color:#334155; font-size:13px; background:transparent;")
        # 文字不吃鼠标事件：点击透给本控件，整块算一次点击
        self._lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        hl.addWidget(self._dot, 0, Qt.AlignVCenter)
        hl.addWidget(self._lbl, 0, Qt.AlignVCenter)

    def isChecked(self) -> bool:
        return self._dot.isChecked()

    def setChecked(self, on: bool, animate: bool = True) -> None:
        self._dot.setChecked(on, animate=animate)

    def mousePressEvent(self, e):  # noqa: N802 (Qt 命名)
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class _SettingChoiceRow(_SettingRow):
    """互斥选项行：右侧一排**实心圆单选**（如「最小化到托盘 / 关闭软件」）。

    2026-09-18 用户口径：原来是「蓝底 / 蓝边」胶囊按钮，改成圆型单选。
    ★★2026-10-01 用户口径：「改成和设定卡里的一样」⇒ 圆点换成 `_PresetDot`（实心圆），
    旧款「圆心留白」的 `_RadioDot` **已整块删除** —— 两处现在是**同一个类**，
    选中态由**实心圆 + 外圈**表达，文字两侧不再有底色。改 `_PresetDot` = 同时改两处。
    """

    def __init__(self, title, hint, options, current, on_pick, parent=None):
        super().__init__(title, hint, parent)
        self._on_pick = on_pick
        self._items = {}
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)                     # 两个选项之间留出呼吸位
        for value, label in options:
            item = _RadioItem(label, value == current)
            item.clicked.connect(lambda v=value: self._pick(v))
            hl.addWidget(item, 0, Qt.AlignVCenter)
            self._items[value] = item
        self.add_right(box, Qt.AlignVCenter)
        self.set_current(current)

    def _pick(self, value):
        self.set_current(value)
        self._on_pick(value)

    def set_current(self, current, animate: bool = True):
        self._current = current
        for value, item in self._items.items():
            item.setChecked(value == current, animate=animate)


class _SettingActionRow(_SettingRow):
    """动作行：右侧一个蓝色镂空按钮（`#outlineBtn`，高 28px），点一下就执行动作。

    与开关行 / 互斥选项行的区别：它**没有状态**（不存任何东西、也不需要同步），
    点完只回调一次。通用设置里的「重置角色位置」用它（见 design.md 4.13）。
    """

    def __init__(self, title, hint, button_text, on_click, parent=None):
        super().__init__(title, hint, parent)
        self._on_click = on_click
        btn = _setting_outline_button(button_text)
        btn.clicked.connect(lambda _=False: self._on_click())
        self._button = btn
        self.add_right(btn, Qt.AlignVCenter)


class _SettingDownloadRow(_SettingRow):
    """下载行：右侧「**状态文字** + `[下载]` `[卸载]`」两颗蓝色镂空按钮（2026-09-22）。

    与别的设置行同一套写法：**只同步这一行、不整页重建**。

    ★**状态不存在行里**（`docs/02` §22.1）：`GeneralPanel.refresh()` 会把行全部销毁重建，
    状态若存在行里，「切到权限管理再回来」就丢了。真实状态由 `voice_model.is_installed()`
    **现算**，行只负责显示 —— 所以这里只有 `set_state / set_buttons` 两个显示用接口。

    三态（未下载 / 下载中 / 已下载）的文字与按钮可用性见 `docs/01` F7；视觉见 `design.md` §4.13。
    """

    BTN_GAP = 8        # 两颗按钮之间 8px（与 4.11 标题行右侧那两颗同一规格）
    # 状态文字宽度**钉死**：文字在「未下载 / 下载中 42% / 已下载」之间变化时按钮不位移。
    # ★100 而不是 84：二期加了「下载中　NN%」这一态，实测**最宽的 `下载中　100%` = 96px**
    #   （12px 字体，全角空格）—— 84px 会把最后的 `%` 裁掉。留 4px 余量。
    STATE_W = 100

    def __init__(self, title, hint, state_text, on_download, on_uninstall, parent=None):
        super().__init__(title, hint, parent)
        self._on_download = on_download
        self._on_uninstall = on_uninstall
        self._state = QLabel(str(state_text))
        self._state.setStyleSheet("color:#64748B; font-size:12px; background:transparent;")
        self._state.setFixedWidth(self.STATE_W)
        self._state.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.add_right(self._state, Qt.AlignVCenter)

        self._download_btn = _setting_outline_button("下载")
        self._download_btn.clicked.connect(lambda _=False: self._on_download())
        self._uninstall_btn = _setting_outline_button("卸载")
        self._uninstall_btn.clicked.connect(lambda _=False: self._on_uninstall())
        # 两颗按钮放进自己的容器：`_SettingRow._row` 的 spacing 是 10px，而这里要的是 8px
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(self.BTN_GAP)
        hl.addWidget(self._download_btn)
        hl.addWidget(self._uninstall_btn)
        self.add_right(box, Qt.AlignVCenter)

    # ---- 显示（状态一律由面板现算后灌进来）----

    def set_state(self, text):
        self._state.setText(str(text))

    def state_text(self):
        return self._state.text()

    def set_download_text(self, text):
        """改「下载」那颗按钮的文字 —— 下载中要变成「取消」（二期，2026-09-22）。

        ★只 `setText()`，**不碰 QSS**：这一行行高钉死 58px，下载期间每 200ms 刷一次，
        改样式会闪。文字都是两个字（「下载」/「取消」）⇒ 宽度不变、右边的按钮不位移。
        """
        self._download_btn.setText(str(text))

    def download_text(self):
        return self._download_btn.text()

    def uninstall_text(self):
        return self._uninstall_btn.text()

    def download_enabled(self):
        return self._download_btn.isEnabled()

    def uninstall_enabled(self):
        return self._uninstall_btn.isEnabled()

    def set_buttons(self, download=None, uninstall=None):
        """设两颗按钮的可用性。禁用时同时把光标换回箭头（灰按钮还带手型会误导）。"""
        if download is not None:
            self._set_btn_enabled(self._download_btn, bool(download))
        if uninstall is not None:
            self._set_btn_enabled(self._uninstall_btn, bool(uninstall))

    @staticmethod
    def _set_btn_enabled(btn, on):
        btn.setEnabled(on)
        btn.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)


class _SettingPathRow(_SettingRow):
    """路径行：左侧标题，右侧「**当前路径**（`…` 中段截断）+ `[更改]` 按钮」（2026-09-22）。

    用于通用设置的「安装位置」。路径可能很长，所以**钉死一块宽度 + `ElideMiddle` 截断**
    —— 与 4.13 里标题 / 说明「不顶宽整行」是同一条道理（QScrollArea 关掉了水平滚动条，
    长文本会把行撑到视口之外，右边框整条被裁）。
    """

    PATH_W = 240       # 路径文字区宽度（固定；超出用 `…` 截断）

    def __init__(self, title, hint, path_text, button_text, on_click, parent=None):
        super().__init__(title, hint, parent)
        self._on_click = on_click
        self._path_text = str(path_text or "")
        self._path = QLabel(self._path_text)
        self._path.setStyleSheet("color:#64748B; font-size:12px; background:transparent;")
        self._path.setFixedWidth(self.PATH_W)
        self._path.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.add_right(self._path, Qt.AlignVCenter)
        self._button = _setting_outline_button(button_text)
        self._button.clicked.connect(lambda _=False: self._on_click())
        self.add_right(self._button, Qt.AlignVCenter)
        self._apply_path_elide()

    def set_path(self, path_text):
        self._path_text = str(path_text or "")
        self._apply_path_elide()

    def path_text(self):
        return self._path_text

    def shown_text(self):
        """实际显示出来的（可能已被 `…` 截断）文本。"""
        return self._path.text()

    def _apply_path_elide(self):
        elided = self._path.fontMetrics().elidedText(
            self._path_text, Qt.ElideMiddle, self.PATH_W)
        self._path.setText(elided)


class _SettingVolumeRow(_SettingRow):
    """音量行（2026-09-19）：左侧只有**「音量」二字**，右侧是 `[−] ──── [+]`。

    - 音量条**不带容器边框**（与桌宠右键菜单里那条**同一颗** `volume.VolumeSlider`，
      只是少了菜单里那层白底圆角壳 —— 用户口径：这里不需要另外加边框）；
    - **整组宽度 = 原来的 90%**（2026-09-19 二改）：原来 22+8+160+8+22 = 220px → 现在 **198px**。
      宽度是**从音量条身上减的**（160 → 138），两颗按钮与 8px 间距不动 —— 按钮是视觉锚点，
      缩小它们只会让 `−` / `+` 看着发虚，而音量条本来就有余量；
    - 两颗圆形按钮无边框、**底色 = 界面底色**，鼠标移入 / 移出时底色**渐变**到浅蓝
      （`volume.VolumeStepButton`，200ms 线性，见 design.md §5）；
    - 点一下 `−` / `+` = 音量 ∓ / ± `STEP`（5%）；改动**只回调面板**，由面板落 cfg 并通知 main
      （`pet` 那条音量条与 TTS 增益的同步都在 `main.on_volume_changed` 一个函数里）。
    """

    SLIDER_W = 138      # 音量条宽度（固定：行内右对齐，拖窗口不会忽宽忽窄；整组 198px = 原来的 90%）
    SLIDER_H = 22       # 与桌宠那条同高
    STEP = 5            # 单击一次 ±5%（1% 要点十几次才听得出差别）

    def __init__(self, title, hint, value, on_change, parent=None):
        super().__init__(title, hint, parent)
        self._on_change = on_change
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)                     # 按钮与音量条之间留 8px
        self._minus = VolumeStepButton(-1)
        self._slider = VolumeSlider()
        self._slider.setFixedSize(self.SLIDER_W, self.SLIDER_H)
        self._plus = VolumeStepButton(+1)
        self._minus.clicked.connect(lambda _=False: self._step(-1))
        self._plus.clicked.connect(lambda _=False: self._step(+1))
        self._slider.valueChanged.connect(self._on_slider)
        hl.addWidget(self._minus, 0, Qt.AlignVCenter)
        hl.addWidget(self._slider, 0, Qt.AlignVCenter)
        hl.addWidget(self._plus, 0, Qt.AlignVCenter)
        self.add_right(box, Qt.AlignVCenter)
        self.set_value(value, notify=False)   # 构建期只摆位置，不回调

    # ---- 数据 ----
    def value(self) -> float:
        return self._slider.value() / 100.0

    def set_value(self, value, notify=True):
        """把音量条拨到指定值；`notify=False` 时不回调（构建期 / 反向同步用）。"""
        pct = int(round(max(0.0, min(1.0, float(value))) * 100))
        self._slider.blockSignals(True)
        self._slider.setValue(pct)
        self._slider.blockSignals(False)
        if notify:
            self._on_change(pct / 100.0)

    def _on_slider(self, val):
        # 拖动滑块 / 点微调按钮都汇到这里 —— **唯一出口**，不会出现两套逻辑各写一次 cfg
        self._on_change(val / 100.0)

    def _step(self, sign):
        self._slider.setValue(max(0, min(100, self._slider.value() + sign * self.STEP)))


class GeneralPanel(_MessagePanel, QWidget):
    """通用设置：启动（开机自启）、语音模型（下载 / 安装位置）、静音模式、关闭行为、桌宠。

    ★**下载进度靠主动拉取**（二期，2026-09-22）：`voice_download.snapshot()` 只含 str / int，
    所以这里用一个 200ms 的 `QTimer` 去拿，而不是让下载线程发 Qt 信号 —— 下载模块要能脱离 Qt
    单独跑，而且「跨线程只传 str/int」本来就是本项目的铁律。
    """

    DOWNLOAD_POLL_MS = 200      # 进度刷新间隔（再快只是白刷，下载本身的粒度比这粗）

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        # 主窗口：**构造时就记住** —— 面板会被放进 QStackedWidget，那以后 parent() 就不再是主窗口了。
        # 「重置角色位置」要请主窗口去命令桌宠（桌宠不归设置面板管）。
        self._win = parent
        self._dl_timer = QTimer(self)
        self._dl_timer.setInterval(self.DOWNLOAD_POLL_MS)
        self._dl_timer.timeout.connect(self._poll_download)
        self._build()
        self._apply_style()
        self.refresh()

    # ---- 数据 ----

    def _general(self):
        if not isinstance(self.cfg.get("general"), dict):
            self.cfg["general"] = {}
        return self.cfg["general"]

    # ---- 界面 ----

    def _build(self):
        lay = QVBoxLayout(self)
        # 与 4.11 同一套底部尺寸：底边距 4 + 消息行前间距 4 + 消息行 16 = 24px
        lay.setContentsMargins(24, 20, 24, TAIL_BOTTOM)
        lay.setSpacing(14)

        # 标题下**不写说明小字**（2026-09-18 用户口径）：这一页本身就短，说明堆在标题下 /
        # 每一行下面只会显得拥挤，四行设置本身的标题已经说清了各自是干什么的。
        _panel_title(lay, "通用设置")

        self._scroll, self._body, self._body_lay, self._msg_label = _panel_bottom(lay)

    def _apply_style(self):
        self.setStyleSheet("QWidget { background:#FFFFFF; color:#334155; font-size:13px; }")

    def refresh(self):
        """按注册表实际状态重建（配置里的 auto_start 只作缓存）。"""
        from .autostart import is_enabled

        actual = is_enabled()
        self._general()["auto_start"] = actual

        _clear_body(self._body_lay)

        # 所有 `hint=""` = 这一行**不要**说明小字（见 `_SettingRow` 文档）。
        _group_header(self._body_lay, "启动")
        self._autostart_row = _SettingToggleRow(
            "开机自启",
            hint="",
            enabled=actual,
            on_toggle=self._toggle_autostart,
        )
        self._body_lay.addWidget(self._autostart_row)

        # 「语音模型」分组（2026-09-22）：这一行**紧贴**它要锁死的「静音模式」（就在下一个分组），
        # 用户才看得出因果。组内两行（下载 / 安装位置），与「启动」组只有一行是同一种形态。
        _group_header(self._body_lay, "语音模型")
        self._model_row = _SettingDownloadRow(
            "音色克隆模型下载",
            hint="",
            state_text="未下载",
            on_download=self._download_model,
            on_uninstall=self._uninstall_model,
        )
        self._body_lay.addWidget(self._model_row)
        self._model_dir_row = _SettingPathRow(
            "安装位置",
            hint="",
            path_text=self._model_dir_display(),
            button_text="更改",
            on_click=self._change_model_dir,
        )
        self._body_lay.addWidget(self._model_dir_row)

        _group_header(self._body_lay, "模式切换")
        self._mute_row = _SettingToggleRow(
            "静音模式",
            hint="",
            enabled=bool(self._general().get("mute_mode", False)),
            on_toggle=self._toggle_mute_mode,
        )
        self._body_lay.addWidget(self._mute_row)
        # patpat 模式（2026-09-20）：左键点贴图摸一下她。与静音模式同一套写法（只同步这一行、
        # 不整页重建），但★**不是同一份记忆**：静音已在 2026-09-29 改成落盘，patpat 仍是纯运行时。
        # **不做素材门禁**：`pet/patpat/` 缺图时也允许打开（用户口径「可直接打开」）。
        self._patpat_row = _SettingToggleRow(
            "patpat模式",
            hint="",
            enabled=bool(self._general().get("patpat_mode", False)),
            on_toggle=self._toggle_patpat_mode,
        )
        self._body_lay.addWidget(self._patpat_row)

        _group_header(self._body_lay, "关闭行为")
        self._body_lay.addWidget(
            _SettingChoiceRow(
                "关闭主界面时",
                hint="",
                options=(("tray", "最小化到托盘"), ("quit", "关闭软件")),
                current=self._general().get("close_action", "tray"),
                on_pick=self._set_close_action,
            )
        )

        _group_header(self._body_lay, "桌宠调整")
        # 桌宠固定（2026-09-22）：开着 = 角色贴图**不能被拖动**（只锁「拖」，单击抚摸 / 思考气泡照旧）。
        # ★与静音 / patpat 那两行**不同**：这一项是**落盘的偏好**（用户口径「记住选择」），
        #   所以 `refresh()` 里按 cfg 初始化就行，不用像它们那样每次启动强制回「关」。
        self._lock_row = _SettingToggleRow(
            "桌宠固定",
            hint="",
            enabled=bool(self._general().get("lock_pet", True)),
            on_toggle=self._toggle_pet_lock,
        )
        self._body_lay.addWidget(self._lock_row)
        # 「音量」排在「重置角色位置」之上：常驻设置在前、一次性动作在后。
        self._volume_row = _SettingVolumeRow(
            "音量",
            hint="",
            value=float(self.cfg.get("volume", 0.5)),
            on_change=self._set_volume,
        )
        self._body_lay.addWidget(self._volume_row)
        self._reset_pos_row = _SettingActionRow(
            "重置角色位置",
            hint="",
            button_text="重置位置",
            on_click=self._reset_pet_pos,
        )
        self._body_lay.addWidget(self._reset_pos_row)

        # 「帮助」分组（P2，2026-10-02）：三件都是**点一下就走**的一次性动作，所以都用
        # `_SettingActionRow`（右侧一颗蓝色镂空按钮，无状态）。★三行各自弹的卡片都在
        # gui.py 里（首引 / 自检 / 更新），判据在 app/health.py 与 app/update.py。
        _group_header(self._body_lay, "帮助")
        self._body_lay.addWidget(
            _SettingActionRow("使用引导", hint="", button_text="打开引导",
                              on_click=self._open_guide)
        )
        self._body_lay.addWidget(
            _SettingActionRow("一键自检", hint="", button_text="开始自检",
                              on_click=self._run_self_check)
        )
        self._body_lay.addWidget(
            _SettingActionRow("检查更新", hint="", button_text="检查更新",
                              on_click=self._check_update)
        )

        # 行全部建好之后，再按**模型是否就位**刷新「下载行」与「静音滑块」的锁死状态。
        # 必须放在这里而不是各行新建时：锁死要动 `_mute_row`，它得先存在。
        self._apply_model_state()
        self._body_lay.addStretch(1)

    # `_autostart_hint()` / `_mute_hint()` 已删：通用设置不再有任何说明小字（2026-09-18 用户口径）。
    # ⚠️旧注释「静音模式只对本次运行有效」**已作废**（2026-09-29 用户要求「重开要保留开关状态」
    # ⇒ 它现在真的落盘，`app/config.py::_RUNTIME_ONLY_GENERAL` 里只剩 patpat_mode）。
    # ★但「不再用一行灰字去讲」这条**仍然成立** —— 两件事别混：口径变了，灰字还是不许加。

    # ---- 交互 ----

    def _toggle_autostart(self):
        from .autostart import disable, enable, is_enabled
        ok, msg = disable() if is_enabled() else enable()
        actual = is_enabled()
        if ok:
            self._general()["auto_start"] = actual
            save_config(self.cfg)
        # 只同步这一行、不整页重建：滑块此刻正在处理自己的 mousePressEvent，
        # 销毁它（`_clear_body` 会 setParent(None)）不必要且有风险；写失败时
        # 也正好靠这一步把滑块拨回注册表的真实状态。
        row = getattr(self, "_autostart_row", None)
        if row is not None:
            row.set_enabled(actual, animate=True)
        self._msg(msg, error=not ok)

    def _toggle_mute_mode(self):
        """静音模式开关（滑块已经先切了视觉状态，这里只把它落到配置里）。

        与自启行同样的写法：**只同步这一行、不整页重建** —— 滑块此刻正在处理自己的
        `mousePressEvent`，销毁它没必要且有风险；写盘失败也不会让它停在错的视觉上
        （它是纯本地配置，没有「真实状态」需要回拨）。
        ★★这里的 `save_config(self.cfg)` 从 2026-09-29 起**真的写进文件**了（在那之前
        `mute_mode` 躺在 `_RUNTIME_ONLY_GENERAL` 里被剔掉，这一行等于空转）。语音那条路
        （`main.py::set_mute_mode`）本次也补了写盘 —— **两条路都要落盘**，只补一边就会
        变成「用语音开的静音重启就丢、用滑块开的记得住」。
        """
        row = getattr(self, "_mute_row", None)
        if row is None:
            return
        # 锁死时不该走到这里（滑块自己会拦住点击），这里只是防别处误调。
        if row.is_locked():
            return
        on = bool(row.is_enabled())
        self._general()["mute_mode"] = on
        save_config(self.cfg)
        # 通知主程序（**只负责弹一下桌宠的提示气泡**）：cfg 与页面提示本页已经落过了，
        # 回调里别再重复一遍。语音那条路（「开启静音模式」）走 main.set_mute_mode，
        # 不经过这里 —— 两条路各弹各的、不会重叠。
        if self._win is not None:
            self._win.notify_mute_mode(on)
        self._refresh_health(False)     # P2：静音开关也影响「顶上那条常显状态条」
        self._msg("已开启静音模式：回复只输出中文，不再合成语音（已记住，重启后仍是开启）。"
                  if on else "已关闭静音模式：恢复日语语音。（已记住，重启后仍是关闭）")

    def _toggle_patpat_mode(self):
        """patpat 模式开关（滑块已经先切了视觉状态，这里只把它落到配置里）。

        与静音模式同一套写法（**只同步这一行、不整页重建**），但**记忆规则不同**：
        本条**刻意不落盘**（纯运行时状态，重启即关 —— ★这一条只对 patpat 成立，
        静音已在 2026-09-29 改成落盘）。与静音模式那条路的区别还有一点：patpat 模式的
        **状态在桌宠那边**（点击行为归它管），所以这里只发个通知，由 main.py 去
        `pet.set_patpat()` —— 桌宠切完会从它自己的切换回调里弹提示并回同步这一行。
        """
        row = getattr(self, "_patpat_row", None)
        if row is None:
            return
        on = bool(row.is_enabled())
        self._general()["patpat_mode"] = on
        save_config(self.cfg)
        if self._win is not None:
            self._win.notify_patpat_mode(on)
        self._msg("已开启 patpat 模式：左键点击角色贴图，她会摸摸头（本次运行有效，重启后自动关闭）。"
                  if on else "已关闭 patpat 模式（关着时单击贴图仍会形变，只是没有那只手、也没有声音）。")

    def _toggle_pet_lock(self):
        """「桌宠固定」开关（滑块已经先切了视觉状态，这里只把它落到配置里）。

        与 patpat 模式同一套写法：**只同步这一行、不整页重建** —— 滑块此刻正在处理自己的
        `mousePressEvent`，销毁它没必要且有风险。区别有两点：
        ① 这一项**要落盘**（用户口径「记住选择」）—— patpat 那种纯运行时状态不落盘
           （★2026-09-29 起静音模式也落盘了，别再把这句写成「静音 / patpat 都不落盘」）；
        ② 状态**在桌宠那边**（拖动行为归它管），所以这里只发通知，由 main.py 去
           `pet.set_locked()` —— 桌宠切完会从它自己的切换回调里弹提示、并回同步这一行。
        """
        row = getattr(self, "_lock_row", None)
        if row is None:
            return
        on = bool(row.is_enabled())
        self._general()["lock_pet"] = on
        save_config(self.cfg)
        if self._win is not None:
            self._win.notify_pet_lock(on)
        self._msg("已固定桌宠：角色贴图不会被拖动（单击抚摸 / 思考气泡不受影响）。"
                  if on else "已取消固定：角色贴图可以拖动。")

    def _set_close_action(self, value):
        self._general()["close_action"] = value
        save_config(self.cfg)
        self._msg(
            "关闭主界面后将最小化到托盘（桌宠继续陪伴）。"
            if value == "tray"
            else "关闭主界面后将直接退出软件。"
        )

    def _set_volume(self, value):
        """音量行改了 → 落 cfg + 交给 main（同步桌宠那条音量条与 TTS 增益）。

        与别的设置行同一个写法：**只动这一行、不整页重建** —— 滑块此刻正在处理自己的
        `valueChanged`。也**不往底部消息行写字**：音量条本身就是反馈，拖一次写一行字只会刷屏。
        """
        v = round(max(0.0, min(1.0, float(value))), 2)
        self.cfg["volume"] = v
        save_config(self.cfg)
        if self._win is not None:
            self._win.notify_volume(v)

    def _reset_pet_pos(self):
        """「重置角色位置」：真正的落位动作在 main.py（桌宠不归设置面板管），
        这里只负责把结果说给用户（反馈走面板底部那一行，与别的设置行一致）。
        """
        win = self._win
        ok = bool(win is not None and win.reset_pet_pos())
        self._msg("桌宠已回到默认位置（屏幕右下角）。" if ok
                  else "角色还没就位，稍后再试。", error=not ok)

    # ---- 帮助（P2：使用引导 / 一键自检 / 检查更新，2026-10-02）----

    def _refresh_health(self, recompute=False):
        """设置页改了东西之后，顺手把顶上那条**常显状态条**重算一次（P2）。

        ★必须做：状态条讲的与这一页改的是**同一件事**（静音 / 模型 / 白名单），
          一个变了另一个还写着旧的，比不显示更误导。
        ★`recompute=True` 只在**真的可能改变外部事实**的地方用（换安装位置 / 下载完成 /
          卸载）—— 它会去 stat 模型目录；滑块回调那种场景只重跑 cfg 判据就够。
        """
        win = self._win
        if win is not None and hasattr(win, "refresh_health"):
            win.refresh_health(recompute_facts=recompute)

    def _open_guide(self):
        """「打开引导」：与首次启动弹的是**同一张卡**（判据现算 ⇒ 会显示当前进度）。"""
        if self._win is not None:
            self._win.show_first_run()

    def _run_self_check(self):
        """「开始自检」：弹自检清单（现算，不吃缓存）。"""
        if self._win is not None:
            self._win.self_check()

    def _check_update(self):
        """「检查更新」：弹更新卡（后台线程查 GitHub，主界面不冻）。"""
        if self._win is not None:
            self._win.check_update()

    # ---- 语音模型（音色克隆模型下载 / 安装位置，2026-09-22）----

    def _model_dir_display(self):
        """「安装位置」显示什么：**永远是 `voice_model.install_root(cfg)`**。

        它是下载 / 卸载 / 运行时三方共用的**唯一真值**（`docs/02` §22.10），所以这一行显示的
        就是「点下载会装到哪、点卸载会删哪、运行时从哪拉起服务」——三者必须与显示一致。

        ★**不要再用 `resolve_install_dir()`**（那条要求「模型完整」）：模型一卸载它就返回 `None`
          ⇒ 界面回落到「项目内默认」，用户看到的就是「**卸载后安装位置变成了桌面\\…**」，
          可下载其实还会装回同一个地方 —— **显示与实际不符**正是 2026-09-27 那次目录混乱的起点
          （用户因此手动把位置改成了子目录，然后炸出三层嵌套，见 `docs/02` §22.10.2）。
        """
        return str(voice_model.install_root(self.cfg))

    def _apply_model_state(self):
        """按**模型是否就位**刷新「下载行」与「静音滑块」的锁死状态，返回是否已安装。

        ★状态**现算**、不存行里（`refresh()` 会把行全部销毁重建），见 `docs/02` §22.1。
        ★没有模型 ⇒ 静音滑块**锁死在「开」**：没有模型就一声都出不来，还留着可关只会让人
          以为软件坏了（`docs/01` F7）。模型就位后**解锁但值不动** —— 不突然出声，由用户自己关。
        ★**下载中**由 `voice_download.snapshot()` 说了算（它跨线程、只含 str/int）：
          下载期间不显示「已下载」，也不解锁静音（模型还没落地）。
        """
        snap = voice_download.snapshot()
        if snap["running"]:
            # 切页面回来时定时器可能已经停了（面板还在，表却停着）⇒ 补启动
            if not self._dl_timer.isActive():
                self._dl_timer.start()
            self._apply_download_state(snap)
            return False

        installed = voice_model.is_installed(self.cfg)

        row = getattr(self, "_model_row", None)
        if row is not None:
            row.set_state("已下载" if installed else "未下载")
            row.set_download_text("下载")
            row.set_buttons(download=not installed, uninstall=installed)
            row.set_hint("")

        prow = getattr(self, "_model_dir_row", None)
        if prow is not None:
            prow.set_path(self._model_dir_display())

        mrow = getattr(self, "_mute_row", None)
        if mrow is not None:
            if installed:
                mrow.set_locked(False)
            else:
                mrow.set_enabled(True, animate=False)   # 强制拨到「开」
                mrow.set_locked(True)
                self._general()["mute_mode"] = True
        return installed

    # ---- 下载中（二期）----

    def _apply_download_state(self, snap):
        """把 `voice_download` 的快照灌到行上。**只 setText / setEnabled / setHint，不碰 QSS。**

        下载期间：状态文字 `下载中　42%`、「下载」那颗按钮变「取消」且**保持可用**（3.5 GB
        下不动就太糟了）、「卸载」禁用、hint 显示当前阶段；静音**照样锁死在开**。
        """
        row = getattr(self, "_model_row", None)
        if row is not None:
            row.set_state(voice_download.progress_text(snap))
            row.set_download_text("取消")
            row.set_buttons(download=True, uninstall=False)
            row.set_hint(snap.get("message") or "")
        prow = getattr(self, "_model_dir_row", None)
        if prow is not None:
            prow.set_path(self._model_dir_display())
        mrow = getattr(self, "_mute_row", None)
        if mrow is not None:
            mrow.set_enabled(True, animate=False)
            mrow.set_locked(True)
            self._general()["mute_mode"] = True

    def _poll_download(self):
        """定时器回调：拉快照 → 刷新行；跑完就停表并把结果说出来。"""
        snap = voice_download.snapshot()
        if snap["running"]:
            self._apply_download_state(snap)
            return
        self._dl_timer.stop()
        self._apply_model_state()
        self._refresh_health(True)      # P2：下载收尾（下完 / 取消 / 报错）⇒ 重探事实
        if snap.get("done"):
            self._msg("音色克隆模型下载完成 —— 静音模式已解锁，但仍保持「开」（要出声请自己关掉静音）。",
                      error=False)
        elif snap.get("cancelled"):
            self._msg("已取消下载。已下好的部分会保留，下次点「下载」接着走。", error=False)
        elif snap.get("error"):
            self._msg(snap["error"], error=True)

    def _cancel_download(self):
        """点「取消」：只置标志，真正的收尾由下载线程做（下一拍 `_poll_download` 报结果）。"""
        if not voice_download.is_running():
            self._apply_model_state()
            return
        voice_download.cancel()
        self._msg("正在取消下载…（已下好的文件会保留）", error=False)

    def set_model_dir(self, path):
        """落盘新的安装位置并刷新状态（「更改」按钮选中目录后调它；测试可直接调，不用弹窗）。

        ★提示必须按**用户指定的那个目录**判断（`is_model_dir_ok`），**不能**拿
          `_apply_model_state()` 的返回值来说事 —— 探测顺序里有兜底路径（项目内 →
          `D:\\GPT-SoVITS`），指定目录不存在时会被兜底命中、界面照旧「已下载」，
          这时说「该目录下模型已就位」就是骗人。
        """
        path = str(path or "").strip()
        if not path:
            return None
        self._general()["model_dir"] = path
        save_config(self.cfg)
        self._apply_model_state()
        self._refresh_health(True)      # P2：安装位置变了 ⇒ 重探「模型就位没」

        if voice_model.is_model_dir_ok(Path(path) / voice_model.MODEL_SUBDIR):
            self._msg("安装位置已改为 %s（模型已就位）。" % path)
            return True
        cur = voice_model.resolve_install_dir(self.cfg)
        if cur is not None:
            self._msg("安装位置已改为 %s，但该目录下没有完整模型；当前仍在使用 %s。"
                      % (path, cur), error=True)
            return False
        self._msg("安装位置已改为 %s，该目录下没有完整模型，静音模式已锁死在开。" % path,
                  error=True)
        return False

    def _change_model_dir(self):
        """「更改」：选目录 → `set_model_dir()`。"""
        chosen = QFileDialog.getExistingDirectory(
            self, "选择 GPT-SoVITS 安装目录", self._model_dir_display())
        if chosen:
            self.set_model_dir(chosen)

    def _download_model(self):
        """「下载」：**下载中这颗按钮是「取消」**，所以先分流；否则**先确认**、再启动真下载
        （`docs/02` §22.6.6 / §22.6.7）。

        ★顺序（用户口径 2026-09-27「点击确认后才正式开始下载」）：
          **分流取消 → 弹确认框 → 磁盘预检 → 起线程**。确认框是**第一道**，预检在 `start()`
          内部（同步、只看 stat）：先问再预检，预检不过就等确认之后立刻报错。
        ★确认框只拦「真正要开始下载」这一支 —— 下载中那颗按钮已经是「取消」，**不许弹**
          （否则点「取消」反被问「是否下载？」，听起来像要再下一次）。
        ★确认框文案**由 `voice_download.confirm_message(is_full)` 生成**，不是写死的常量串：
          全量时**三行**（中间那行报「共约 3.6 GB」），只下模型时**两行**。
          ★「要不要全量」用的是**流水线实际跳不跳段的同一个判据**（`is_full_install`），
            不许在这里另算一套 —— 两套判据迟早漂移，弹窗就会对用户说假话。
        ★磁盘预检在 `voice_download.start()` 里**同步**做完（只看 stat，毫秒级）：不足就
          **根本不启动**并直接说要多少 —— 别让人等十分钟才失败。
        ★装到 `voice_model.install_root(self.cfg)`（**安装根 = 唯一真值**）：用户指定目录 →
          本机已有安装（项目内 → `D:\\GPT-SoVITS`）→ 全新装到项目内。**不再用
          `default_install_dir()`** —— 那条不含历史路径，会出现「`D:\\GPT-SoVITS` 明明能用、
          点下载却在项目内又造一套」。
        """
        if voice_download.is_running():
            self._cancel_download()
            return
        root = voice_model.install_root(self.cfg)
        if not ConfirmDialog.confirm(
            self,
            voice_download.confirm_message(voice_download.is_full_install(self.cfg, root)),
            confirm_text="确认", cancel_text="取消",
        ):
            return
        ok, msg = voice_download.start(self.cfg, root=root)
        if not ok:
            self._msg(msg, error=True)
            return
        self._dl_timer.start()
        self._apply_download_state(voice_download.snapshot())
        self._msg("%s已开始下载到 %s。" % (msg, root), error=False)

    def _uninstall_model(self):
        """「卸载」：**三选一**弹窗 → `仅模型卸载` / `全部卸载`（送回收站）→ 回「未下载」态并锁死静音。

        两档的口径（`docs/01` F7 / `docs/02` §22.4）：

        - **仅模型卸载**（推荐档，弹窗里那颗主蓝实心按钮）：只删**探测到的模型目录**
          （`<安装根>/GPT_SoVITS/pretrained_models`，≈1.15 GB）。代码体 / venv / 依赖 /
          `refs/` 一概不动 ⇒ 重装只需重下 1.15 GB 而不是 15~40 分钟。
        - **全部卸载**（红边镂空）：按 `voice_model.PURGE_TARGETS` 删「代码体 + venv + 依赖 + 模型」
          （≈3.6 GB），**保留** `refs/`、`ffmpeg.exe`、`.git/` 等**非下载所得**的用户资产
          —— 清单与理由见 `docs/02` §22.11。

        ★文案由 `voice_model.uninstall_message(cfg)` 生成（纯函数，可离线断言），
          **不许在这里拼字符串** —— 否则「两档各删什么」这件事就没法在测试里钉住。
        ★三按钮的 `key` **直接就用** `voice_model.UNINSTALL_MODEL / UNINSTALL_ALL`
          （不写 `"model"` / `"all"` 字面量）：弹窗回来的值可以**原样**转交给 `uninstall()`，
          gui 里也就不存在「一份字符串 key + 一份常量」两套说法。
        ★守卫必须先于一切：下载中不许卸载（否则可能删到正在写入的目录）。
        """
        if voice_download.is_running():
            # 按钮虽然禁用着，但这条入口也可能被别处调到（语音指令 / 测试），守卫必须有
            self._msg("正在下载，先点「取消」再卸载。", error=True)
            return
        md = voice_model.model_dir(self.cfg)
        if md is None:
            self._apply_model_state()
            self._msg("没有找到可卸载的模型（当前就是「未下载」）。", error=True)
            return
        chosen = ChoiceDialog.choose(
            self, voice_model.uninstall_message(self.cfg),
            [(voice_model.UNINSTALL_MODEL, "仅模型卸载", "primary"),
             (voice_model.UNINSTALL_ALL, "全部卸载", "danger")],
        )
        # ★`None`（取消 / 关掉窗口）与任何非预期值走同一条路：**一个字都不动**。
        #   按钮的 key 直接就是 `voice_model` 的档位常量 ⇒ 这里不必再把字符串翻译成常量，
        #   也就不会出现「gui 里写死 'model' 字面量、常量改了它不知道」那种漂移。
        if chosen not in (voice_model.UNINSTALL_MODEL, voice_model.UNINSTALL_ALL):
            self._msg("已取消卸载。")
            return
        done = voice_model.uninstall(self.cfg, chosen)
        self._apply_model_state()
        self._refresh_health(True)      # P2：卸载完 ⇒ 重探「模型就位没」
        if not done:
            self._msg("卸载没有完成：还有文件没删掉（可能被别的程序占用），可稍后重试。", error=True)
            return
        if chosen == voice_model.UNINSTALL_MODEL:
            self._msg("模型已卸载（已送进回收站，可还原）。静音模式已锁死在开 —— 没有模型就出不了声。")
        else:
            self._msg("已全部卸载（已送进回收站，可还原）。refs（角色参考音频）、ffmpeg.exe 与 .git "
                      "都保留着；静音模式已锁死在开 —— 没有模型就出不了声。")


# ========== 聊天气泡 ==========

class _Bubble(QWidget):
    """聊天气泡：纯圆角文本框（无尾巴）。

    宽度规则（上限由 `ChatView` 按聊天区宽度下发）：
      * 文字**单行装得下**（自然单行宽 ≤ 上限）→ 紧贴文字、一行显示；
      * 装不下 → **撑到上限**再换行，上限 = 聊天区可用宽的一半。
    实际宽度用 `fit_width()` 钉死，不依赖 Qt 对换行文本那条「猜宽度」的 sizeHint
    启发式（那会让长文本只撑到 200px 上下、永远到不了上限）。
    """

    RADIUS = 12             # 圆角半径
    FALLBACK_MAX_W = 400    # 聊天区宽度未知时的兜底上限

    def __init__(self, text, role, parent=None, dim=False, max_width=None):
        super().__init__(parent)
        self._role = role  # "assistant"(左) 或 "user"(右)
        self._max_w = int(max_width) if max_width else self.FALLBACK_MAX_W
        self._fit_w = 0     # 已钉下的实际宽度（0 = 还没钉过）
        self._lbl = QLabel(text)
        self._lbl.setWordWrap(True)
        self._lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self._lbl.setMaximumWidth(self._max_w)  # fit 之前先按上限兜住
        if role == "assistant":
            color = "#9AA5B1" if dim else "#334155"
            self._lbl.setStyleSheet(f"padding:10px 14px; color:{color}; background:transparent;")
            self._body = QColor("#F6FAFF")
        else:
            color = "#9AA5B1" if dim else "#0C447C"
            self._lbl.setStyleSheet(f"padding:10px 14px; color:{color}; background:transparent;")
            self._body = QColor("#E6F1FB")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._lbl)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        body = QRectF(0, 0, w, h)
        p.setPen(Qt.NoPen)  # 无边框线
        p.setBrush(self._body)
        p.drawRoundedRect(body, self.RADIUS, self.RADIUS)
        p.end()
        super().paintEvent(event)  # 画子 QLabel 文字

    @property
    def role(self) -> str:
        """"assistant"（左）或 "user"（右）。"""
        return self._role

    @property
    def text(self) -> str:
        """气泡里的文字（宽度重算时要用它量自然单行宽）。"""
        return self._lbl.text()

    @property
    def max_width(self) -> int:
        """气泡能撑到的最大宽（= 聊天区可用宽的一半，assistant 已扣头像占位）。"""
        return self._max_w

    @property
    def fit_width_value(self) -> int:
        """当前实际钉下的宽度（0 = 还没钉过、仍按上限兜着）。"""
        return self._fit_w

    def set_max_width(self, width: int):
        """更新「能撑到的上限」（聊天区变宽/变窄时由 `ChatView` 下发）。"""
        width = int(width)
        if width > 0:
            self._max_w = width
            if self._fit_w == 0:      # 尚未 fit，同步把兜底上限也挪过去
                self._lbl.setMaximumWidth(width)

    def fit_width(self, natural_width: int):
        """按「自然单行宽」和「上限」钉出实际宽度。

        `natural_width` 由 `ChatView._natural_width()` 用同款内边距的非换行标签量得。
        """
        width = max(1, min(int(natural_width), self._max_w))
        if width != self._fit_w:
            self._fit_w = width
            self._lbl.setFixedWidth(width)


class ChatView(QWidget):
    """聊天气泡列表：角色消息（头像+气泡靠左），我的消息（气泡无头像靠右）。"""

    # ---- 气泡宽度策略：左右各占聊天区的一半，两侧气泡的「内边缘」都落在中线上 ----
    # 上限 = 可用宽 / 2；assistant 行左侧被头像占掉，所以要把它扣掉，
    # 否则它的右边缘会越过中线 46px，与 user 气泡不对称。
    ROW_MARGIN = 20        # 与 `_rows_lay` 的左右外边距保持一致
    AVATAR_W = 36          # 头像直径
    AVATAR_GAP = 10        # 头像与气泡间距
    MIN_BUBBLE_W = 140     # 窗口极窄时的兜底，避免气泡被压成竖条
    BUBBLE_PAD_X = 14      # 气泡左右内边距（与 `_Bubble` 的 QSS padding 保持一致）

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBar(_SmoothScrollBar())
        self._container = QWidget()
        self._container.setStyleSheet("background:#FFFFFF;")
        self._rows_lay = QVBoxLayout(self._container)
        # 左右外边距必须与 `ROW_MARGIN` 一致（气泡上限是按它算出来的）
        self._rows_lay.setContentsMargins(self.ROW_MARGIN, 20, self.ROW_MARGIN, 20)
        self._rows_lay.setSpacing(14)
        self._rows_lay.addStretch(1)
        self._scroll.setWidget(self._container)
        lay.addWidget(self._scroll)
        # 自动滚动到底：粘底模式下，滚动范围变化即滚到底；用户向上滚则退出粘底、不打扰回看
        self._sticky_bottom = True
        sb = self._scroll.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll_value_changed)
        sb.rangeChanged.connect(self._on_range_changed)
        # 加载角色头像缓存
        self._avatar_cache = {}
        # 量「自然单行宽」用：**不换行**的同款标签，它的 sizeHint 就是单行总宽（含内边距）。
        # 直接对气泡标签本身取 sizeHint 不行 —— 换行标签的 sizeHint 走 Qt 的「猜宽度」
        # 启发式（长文本只给 200px 上下），撑不到上限。
        self._measure = QLabel(self)
        self._measure.setWordWrap(False)
        self._measure.setStyleSheet(f"padding:10px {self.BUBBLE_PAD_X}px;")
        self._measure.hide()
        self._measure.ensurePolished()
        self._last_content_w = -1
        # 视口尺寸变化（拖窗口 / 竖向滚动条出现或消失）都要重算气泡宽度
        self._scroll.viewport().installEventFilter(self)

    # ---- 气泡宽度 ----

    def _natural_width(self, text: str) -> int:
        """这段文字**单行显示**需要的宽度（含气泡内边距）。"""
        self._measure.setText(text)
        return self._measure.sizeHint().width()

    def _content_width(self) -> int:
        """聊天区实际可用宽（已扣掉左右外边距）。"""
        vw = self._scroll.viewport().width()
        if vw <= 0:
            vw = self.width()  # 尚未布局时退回控件自身宽度
        return max(0, vw - 2 * self.ROW_MARGIN)

    def bubble_max_width(self, role: str) -> int:
        """按角色给出气泡最大宽：用户占右半，角色占左半（扣掉头像占位）。"""
        half = self._content_width() // 2
        if role == "assistant":
            half -= self.AVATAR_W + self.AVATAR_GAP
        return max(self.MIN_BUBBLE_W, half)

    def _fit_bubble(self, bubble: "_Bubble"):
        """把气泡实际该占的宽钉下来：装得下就单行紧贴，装不下就撑到上限再换行。"""
        bubble.set_max_width(self.bubble_max_width(bubble.role))
        bubble.fit_width(self._natural_width(bubble.text))

    def _sync_bubble_widths(self):
        """聊天区宽度变了才重算（拖窗口 / 滚动条出现会高频触发，值没变就别白跑）。"""
        content_w = self._content_width()
        if content_w == self._last_content_w:
            return
        self._last_content_w = content_w
        for b in self._container.findChildren(_Bubble):
            self._fit_bubble(b)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_bubble_widths()

    def eventFilter(self, obj, ev):
        # 竖向滚动条出现/消失时视口会变窄，气泡宽度要跟着收回来
        if obj is self._scroll.viewport() and ev.type() == QEvent.Resize:
            self._sync_bubble_widths()
        return super().eventFilter(obj, ev)

    def avatar(self, role_key):
        if role_key not in self._avatar_cache:
            self._avatar_cache[role_key] = _load_avatar(role_key, self.AVATAR_W)
        return self._avatar_cache[role_key]

    def add_bubble(self, role: str, name: str, text: str, role_key: str = "") -> "_Bubble":
        """role: 'user'(右) 或 'assistant'(左)；返回气泡控件。"""
        row = QHBoxLayout()
        row.setSpacing(self.AVATAR_GAP)  # 头像与气泡间留空隙
        if role == "assistant":
            av = self.avatar(role_key) if role_key else _load_avatar("", self.AVATAR_W)
            av_lbl = QLabel()
            av_lbl.setPixmap(av)
            av_lbl.setFixedSize(self.AVATAR_W, self.AVATAR_W)
            row.addWidget(av_lbl, 0, Qt.AlignTop)
            bubble = _Bubble(text, role="assistant")
            self._fit_bubble(bubble)   # 定宽后再进布局，第一遍 layout 就是对的
            row.addWidget(bubble, 0, Qt.AlignTop)
            row.addStretch(1)  # 右侧占满，气泡紧贴文字
        else:
            row.addStretch(1)  # 左侧占满，气泡靠右
            bubble = _Bubble(text, role="user")
            self._fit_bubble(bubble)
            row.addWidget(bubble, 0, Qt.AlignTop)
        # 插入到 stretch 之上
        self._append_row(self._wrap(row))
        return bubble

    def add_system(self, text: str):
        row = QHBoxLayout()
        lbl = QLabel(text)
        # ★**必须换行**（`_hint_tip` 那条坑的同款）：系统消息不换行时，QLabel 的
        #   `minimumSizeHint` = 整段文字的**单行宽**，会把滚动区 `_container` 的**最小宽**
        #   顶到视口之外；而滚动区是 `widgetResizable=True` + 水平滚动条关闭 → 内容比视口宽
        #   就直接被裁右边，且**加过就不会自己恢复**。靠右的**用户气泡**首当其冲：
        #   右端被裁掉，看起来像「向右偏移、只剩左半截」。
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#64748B; font-size:12px; padding:6px;")
        lbl.setAlignment(Qt.AlignCenter)
        # ★水平策略设 `Ignored`：让它**不参与最小宽度诉求**（长文本也不能把内容区顶宽）。
        #   注意 `setWordWrap(True)` 会把策略重置成 (Preferred, Preferred, heightForWidth=True)，
        #   所以必须在它**之后**改，并且**只改水平轴**、保留 `heightForWidth` —— 否则换行后
        #   高度按单行算，正文会被纵向裁掉。
        pol = lbl.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Ignored)
        lbl.setSizePolicy(pol)
        # 单条 label 铺满整行（文字靠 `AlignCenter` 居中），不再用两侧 stretch 分摊宽度：
        # 那样长文本只会拿到 1/3 行宽、被挤成一条窄柱。
        row.addWidget(lbl, 1)
        self._append_row(self._wrap(row))

    def show_thinking(self, name: str, role_key: str = ""):
        """显示「头像 + 灰色气泡『xxx 正在思考...』」（AI 思考/合成期间）。"""
        self.hide_thinking()
        row = QHBoxLayout()
        row.setSpacing(self.AVATAR_GAP)
        av = self.avatar(role_key) if role_key else _load_avatar("", self.AVATAR_W)
        av_lbl = QLabel()
        av_lbl.setPixmap(av)
        av_lbl.setFixedSize(self.AVATAR_W, self.AVATAR_W)
        row.addWidget(av_lbl, 0, Qt.AlignTop)
        bubble = _Bubble(f"{name} 正在思考...", role="assistant", dim=True)
        self._fit_bubble(bubble)
        row.addWidget(bubble, 0, Qt.AlignTop)
        row.addStretch(1)
        self._thinking_row = self._wrap(row)
        self._append_row(self._thinking_row)

    def hide_thinking(self):
        """移除「正在思考...」提示（若有）。"""
        if getattr(self, "_thinking_row", None) is not None:
            row = self._thinking_row
            # 先停止其进入动画，避免动画引用已删除的 widget
            anim = getattr(row, "_row_anim", None)
            if anim is not None:
                anim.stop()
                row._row_anim = None
            row.setParent(None)
            row.deleteLater()
            self._thinking_row = None

    def _wrap(self, layout):
        w = QWidget()
        w.setLayout(layout)
        w.setStyleSheet("background:transparent;")
        return w

    def _on_scroll_value_changed(self, value):
        # 用户滚轮/拖动滚动时实时更新粘底状态：靠近底部则粘底，向上离开则不粘底
        sb = self._scroll.verticalScrollBar()
        self._sticky_bottom = (sb.maximum() - value) <= 8

    def _on_range_changed(self, _min, _max):
        # 新增消息导致滚动范围更新（此刻 maximum 已是最终值）；粘底模式下自动滚到最新底部
        if self._sticky_bottom:
            self._scroll.verticalScrollBar().setValue(_max)

    def _append_row(self, wrapped):
        self._rows_lay.insertWidget(self._rows_lay.count() - 1, wrapped)
        # 新对话进入动画：自下而上移动 15px 到目标位置（延迟到 layout 完成后再取目标位置）
        QTimer.singleShot(0, lambda: self._animate_row_in(wrapped))

    def _animate_row_in(self, wrapped):
        # 强制 container 更新到新尺寸 + 重新布局，确保取到正确的目标位置（否则多条消息会重叠）
        self._container.adjustSize()
        self._rows_lay.activate()
        target = wrapped.pos()
        start = QPoint(target.x(), target.y() + 15)
        wrapped.move(start)
        anim = QPropertyAnimation(wrapped, b"pos", wrapped)
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(start)
        anim.setEndValue(target)

        def on_finished():
            # 动画结束后强制更新尺寸 + 重新布局，让所有行回到正确位置，消除重叠
            self._container.adjustSize()
            self._rows_lay.activate()

        anim.finished.connect(on_finished)
        anim.start()
        wrapped._row_anim = anim  # 保持引用防 GC

    def clear(self):
        # 移除所有气泡行（保留最后的 stretch）
        while self._rows_lay.count() > 1:
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        # 「正在思考」那一行也在这批里被删了，引用必须一起清掉，
        # 否则后续 hide_thinking() 会去操作一个已经销毁的控件。
        self._thinking_row = None


# ========== API 表单对话框（添加 / 编辑共用，可配接口地址与模型名） ==========

class ApiFormDialog(_CardDialog):
    """API 表单弹窗（添加 / 编辑共用）—— 与 `ConfirmDialog` / `InputDialog` 同一张卡片皮肤。

    fields: [(attr, 标签, 占位提示, 初始值, 是否密码框)]
    判定用户是否点了「确认」用 `confirmed()`（`exec()` 返回 `Accepted`）。

    ⚠️ **不要退回 `QMessageBox`**（2026-09-17 用户报「不符合规范」）：它自带系统标题栏、
    图标列与自己的按钮布局，QSS 也管不到它的按钮 —— 实测「取消」会跟着「确认」一起变成
    蓝底、卡片没有 16px 圆角、宽度也不受 `setFixedWidth` 摆布。规范见 design.md §4.5。
    """

    # 与 ConfirmDialog / InputDialog 的按钮同尺寸
    BTN_SIZE = (88, 34)

    def __init__(self, title, fields, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(360)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("confirmCard")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 24, 24, 20)
        card_lay.setSpacing(14)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size:15px; font-weight:bold; color:#0C447C; background:transparent;")
        card_lay.addWidget(title_lbl)

        # 字段区：每个字段两行（标签 + 输入框），字段之间 12px
        self.edits = {}
        fields_box = QVBoxLayout()
        fields_box.setSpacing(12)
        for attr, label, placeholder, initial, is_password in fields:
            # 旧标签写成「AI 名称：」是为了和输入框同行；现在标签独占一行，冒号去掉
            lbl = QLabel(str(label).rstrip("：:"))
            lbl.setStyleSheet("color:#334155; font-size:13px; background:transparent;")
            fields_box.addWidget(lbl)
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            if initial:
                edit.setText(str(initial))
            if is_password:
                edit.setEchoMode(QLineEdit.Password)
            # 宽度由卡片 360px − 左右各 24px 内边距决定，**不要**写 min-width
            fields_box.addWidget(edit)
            self.edits[attr] = edit
        card_lay.addLayout(fields_box)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setFixedSize(*self.BTN_SIZE)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        self.confirm_btn = QPushButton("确认")
        self.confirm_btn.setObjectName("confirmBtn")
        self.confirm_btn.setCursor(Qt.PointingHandCursor)
        self.confirm_btn.setFixedSize(*self.BTN_SIZE)
        self.confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.confirm_btn)
        card_lay.addLayout(btn_row)
        outer.addWidget(card)

        self.setStyleSheet(_CARD_FRAME_QSS + _CARD_EDIT_QSS + _CARD_BTN_QSS)

        # 回车 = 确认（与 InputDialog 一致）
        for edit in self.edits.values():
            edit.returnPressed.connect(self.accept)

    def get(self, attr: str) -> str:
        return self.edits[attr].text().strip()

    def confirmed(self) -> bool:
        return self.result() == QDialog.Accepted

# ========== 主窗口 ==========

class MainWindow(QWidget):
    """主窗口：顶部蓝色标题栏（聊天/管理/设置）+ 左栏（角色区 / 设置导航）+ 右栏内容。"""

    LEFT_WIDTH = 180

    # ---- 右栏页面索引（0~3 为主界面，4 起为设置页，顺序与 SETTINGS_ITEMS 一致）----
    PAGE_CHAT = 0
    PAGE_API = 1
    PAGE_WAKE = 2
    PAGE_PRESET = 3          # 设定卡（2026-09-30）
    SETTINGS_BASE = 4        # ★加了管理页就要跟着往后挪：设置页索引从它起算

    # 管理项：(右栏页索引, 左栏显示名) —— 与 PAGE_API / PAGE_WAKE / PAGE_PRESET 一一对应。
    # 加管理页只需在这里加一行 + 在 _build_right_panel 里补一个面板（面板顺序必须与这里一致）。
    MANAGE_ITEMS = (
        (PAGE_API, "管理 API"),
        (PAGE_WAKE, "管理唤醒词"),
        (PAGE_PRESET, "设定卡"),   # ★排在最后（用户口径）
    )

    # 设置项：(key, 左栏显示名)。新增设置页只需在这里加一行 ——
    # 左栏导航自动生成，右栏页面在 _build_right_panel 的 builders 里补一个构造函数。
    SETTINGS_ITEMS = (
        ("general", "通用设置"),
        ("permissions", "权限管理"),
    )

    # ---- 左栏三态：角色区 / 管理导航 / 设置导航（真值只有 _left_mode 一个字符串）----
    LEFT_MODE_ROLE = "role"
    LEFT_MODE_MANAGE = "manage"
    LEFT_MODE_SETTINGS = "settings"
    LEFT_MODES = (LEFT_MODE_ROLE, LEFT_MODE_MANAGE, LEFT_MODE_SETTINGS)

    # 左栏底色只有两种：角色区白底 → 导航页浅蓝 #C7E1FB（比顶部标题栏 #2F74BF 浅，做区分）
    LEFT_BG_ROLE = (255, 255, 255)
    LEFT_BG_SETTINGS = (199, 225, 251)
    LEFT_SLIDE = 20      # 左栏内容「从左向右平移」的入场距离
    RIGHT_SLIDE = 20     # 右栏内容「自上而下平移」的入场距离（全场景统一）

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self._hide_to_tray = None
        self._role_change_cb = None
        self._quit_app = None
        self._reset_pet_pos_cb = None     # 「通用设置 → 重置角色位置」的动作（main.py 注入）
        self._on_mute_mode = None         # 「通用设置 → 静音模式」切换后的通知（main.py 注入，只弹提示）
        self._on_patpat_mode = None       # 「通用设置 → patpat模式」切换后的通知（main.py 注入）
        self._on_pet_lock = None          # 「通用设置 → 桌宠固定」切换后的通知（main.py 注入）
        self._on_volume = None            # 「通用设置 → 音量」改动后的通知（main.py 注入）
        self._page_change_cb = None        # 右栏换页后的通知（main.py 用它重判桌宠气泡）
        # ★P2（2026-10-02）常显状态条：`_health_facts_fn` 由 main.py 注入（只有它知道
        #   「麦克风 / 语音识别就绪没」）；未注入时退回 `health.collect_facts`（只探模型）。
        #   ★`_health_facts` 是**缓存**：翻页时用 `refresh_health(recompute_facts=False)`
        #     复用上一次的结果 —— 免得每次切页都去 stat 一遍几百 MB 的模型目录。
        self._health_facts_fn = None
        self._health_facts = {}
        self._health_status = None
        self._health_full_text = ""
        self._quitting = False          # 正在退出：closeEvent 一律放行（见 closeEvent 注释）
        self._left_mode = self.LEFT_MODE_ROLE   # 左栏形态：role / manage / settings
        self._settings_page = self.SETTINGS_BASE   # 上次停留的设置页（右栏页索引）
        self._left_bg_t = 0.0            # 底色插值：0=白，1=深蓝
        self._current_role_key = cfg.get("current_role", "alice")
        self._switching_role = False
        self._chat_history = {}  # {role_key: [(role, text)]} role: "user"|"assistant"|"system"
        # 历史上限
        self._chat_max = 200
        self.setWindowTitle("Ignotus Assistant")
        # 无系统标题栏（自定义）
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(820, 540)
        self._build()
        self._apply_style()
        self._load_chat_history()  # 加载内存中的聊天记录
        self._set_role(self._current_role_key)
        self._switch_right_panel(0, animate=False)  # 默认聊天面板
        self._apply_rounded_corners()

    @property
    def _settings_mode(self) -> bool:
        """是否处于设置区左栏形态 —— **只读**，真值是 `_left_mode`。

        只为兼容既有读取点（tests/boot_probe.py、tools/render_shots.py、冒烟测试）而保留；
        没有 setter，往它赋值会立刻 AttributeError，以防左栏形态出现第二个真值。
        """
        return self._left_mode == self.LEFT_MODE_SETTINGS

    # ---- 构建 ----
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_titlebar())
        root.addWidget(self._build_health_strip())   # ★P2：常显状态条（标题栏正下方）
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_left_panel(), 0)
        body.addWidget(self._build_divider(), 0)
        body.addWidget(self._build_right_panel(), 1)
        root.addLayout(body, 1)

    # ---- P2：常显状态条（2026-10-02）----

    HEALTH_H = 30       # 状态条高度

    def _build_health_strip(self):
        """标题栏正下方的**常显状态条**：一眼看出「她现在能不能用、不能的话卡在哪」。

        - 高 **30px**；浅蓝底 `#F6FAFF` + 1px 下边框 `#E6F1FB`（= design.md §1 的输入框底色
          与弹窗边框，不新增颜色）。
        - 左：8px 状态圆点 + 12px 文案；右：一颗「去设置」小按钮（**只在有落点时才出现**）。
        - ★★**文案与落点都不由这里决定** —— `health.status_line()` 说了算。它与「一键自检」
          「首次引导」用的是**同一份判据**，所以那三处不可能互相打架（见 app/health.py 抬头）。
        - ★它是**常驻**的：一切就绪时显示绿色「一切就绪」而不是把自己藏起来 ——
          用户要能靠它确认「现在到底正不正常」，藏起来就只剩「出问题时才出现」这一个信号，
          反而分不清「没问题」和「这软件没有这个功能」。
        """
        bar = QFrame()
        bar.setObjectName("healthStrip")
        bar.setFixedHeight(self.HEALTH_H)
        bar.setStyleSheet(
            "QFrame#healthStrip{background:#F6FAFF; border:none;"
            " border-bottom:1px solid #E6F1FB;}"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(8)

        self._health_dot = _status_dot(health.LEVEL_OK)
        h.addWidget(self._health_dot, 0, Qt.AlignVCenter)

        self._health_label = QLabel("")
        self._health_label.setStyleSheet(
            "color:#64748B; font-size:12px; background:transparent;"
        )
        # ★横向 `Ignored` + 自己按宽度省略（同 `_SettingRow` 的教训：不换行的 QLabel 的
        #   minimumSizeHint 等于整段文字宽度，会把状态条顶宽、把右边那颗按钮挤出去）
        pol = self._health_label.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Ignored)
        self._health_label.setSizePolicy(pol)
        h.addWidget(self._health_label, 1)

        self._health_btn = QPushButton("去设置")
        self._health_btn.setCursor(Qt.PointingHandCursor)
        self._health_btn.setFixedSize(64, 22)
        self._health_btn.setStyleSheet(
            "QPushButton{background:transparent; color:#378ADD; border:1px solid #378ADD;"
            " border-radius:8px; font-size:12px; padding:0;}"
            "QPushButton:hover{background:#E6F1FB;}"
        )
        self._health_btn.clicked.connect(self._health_go)
        self._health_btn.setVisible(False)
        h.addWidget(self._health_btn, 0, Qt.AlignVCenter)

        self._health_strip = bar
        return bar

    def set_health_facts_provider(self, fn):
        """注入「外部事实」的取值回调（main.py 用；返回 `{"tts_installed": bool|None,
        "asr_ok": bool|None}`）。不注入时退回 `health.collect_facts`（只探模型）。"""
        self._health_facts_fn = fn

    def _compute_health_facts(self) -> dict:
        if self._health_facts_fn is not None:
            try:
                return dict(self._health_facts_fn() or {})
            except Exception:  # noqa: BLE001  取事实失败不该把界面搞崩
                return {}
        return health.collect_facts(self.cfg)

    def refresh_health(self, recompute_facts: bool = True):
        """重算状态条（返回那条 `Status`）。

        - `recompute_facts=True`（默认）：**重新探一遍**外部事实（会 stat 模型目录）——
          启动、ASR 初始化完成、模型下载完成之后调它。
        - `recompute_facts=False`：**复用缓存的事实**，只重跑那几条纯判据（读 cfg）——
          翻页时调它，用来接住「用户刚在设置页填了 key / 加了目录 / 拨了静音」。

        ★**故意不缓存结论**：每次现算。缓存了就会出现「改了设置、状态条还写着旧的」。
        """
        if recompute_facts:
            self._health_facts = self._compute_health_facts()
        facts = self._health_facts or {}
        st = health.status_line(
            self.cfg,
            tts_installed=facts.get("tts_installed"),
            asr_ok=facts.get("asr_ok"),
        )
        self._health_status = st
        self._health_full_text = st.text
        self._health_label.setText(st.text)
        self._health_label.setStyleSheet(
            "color:%s; font-size:12px; background:transparent;" % _HL_COLORS.get(st.level, "#64748B")
        )
        self._health_dot.setStyleSheet(
            "background:%s; border-radius:4px;" % _HL_COLORS.get(st.level, "#64748B")
        )
        self._health_btn.setVisible(st.page is not None)
        self._apply_health_elide()
        return st

    def _apply_health_elide(self):
        """状态条文案按当前宽度做右侧省略（窄窗口下不许把「去设置」挤出去）。"""
        lbl = getattr(self, "_health_label", None)
        if lbl is None or not self._health_full_text:
            return
        avail = lbl.width()
        if avail <= 0:
            return
        elided = lbl.fontMetrics().elidedText(self._health_full_text, Qt.ElideRight, avail)
        if elided != lbl.text():
            lbl.setText(elided)

    def _health_go(self):
        """状态条右边那颗「去设置」。"""
        st = getattr(self, "_health_status", None)
        if st is not None:
            self.open_health_target(st.page)

    def open_health_target(self, page):
        """跳到某个问题所在的页（`page` 是 `health.PAGE_*` 字符串）。

        ★走 `_show_manage_page` / `_show_settings_page` —— 与「点左栏导航」完全同一条路，
          所以进入设置页该刷新的会刷新、折叠分组该复位的会复位，不另起一套。
        """
        if not page:
            return
        self.bring_to_front()
        if page == health.PAGE_API:
            self._show_manage_page(self.PAGE_API)
        elif page == health.PAGE_PERMISSIONS:
            self._show_settings_page(self._settings_index.get("permissions", self.SETTINGS_BASE))
        else:
            self._show_settings_page(self._settings_index.get("general", self.SETTINGS_BASE))

    # ---- P2：一键自检 / 检查更新 / 首次引导 ----

    def health_facts(self) -> dict:
        """把「外部事实」取回来（自检清单与状态条**共用**这一份）。"""
        return self._compute_health_facts()

    def _build_checks(self):
        """现算一份自检清单（`on_recheck` 与首次弹窗都走它 —— 不吃缓存）。"""
        f = self.health_facts()
        return health.check_all(self.cfg, tts_installed=f.get("tts_installed"),
                                asr_ok=f.get("asr_ok"))

    def self_check(self):
        """跑一次「一键自检」并弹窗（设置页 / 托盘菜单都汇到这里）。"""
        SelfCheckDialog.run_check(self, self._build_checks(), on_recheck=self._build_checks)

    def check_update(self):
        """「检查更新」：弹窗 + 后台线程查 GitHub 最新 release。"""
        UpdateDialog.show_check(self, APP_VERSION)

    def show_first_run(self):
        """弹「首次使用引导」（启动时若还没配过 API 会自动调；也可从托盘 / 设置页手动打开）。

        ★**非阻塞**（见 `FirstRunDialog.show_guide`）：启动路径里不许 `exec()` 一个模态窗，
          否则 `main()` 回不去、探针全挂。
        ★点「去设置」⇒ 直接送到「管理 API」页（那是首次必做的那一步）。
        """
        FirstRunDialog.show_guide(
            self,
            health.guide_items(self.cfg),
            on_go=lambda: self.open_health_target(health.PAGE_API),
        )

    def _build_divider(self):
        """左栏与右栏之间的分界：向右 3px 渐变阴影。"""
        return _ShadowBar(width=3)

    def _build_titlebar(self):
        bar = QFrame()
        bar.setFixedHeight(48)
        bar.setStyleSheet("background:#2F74BF; border:none;")
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(0)
        self._title_label = QLabel("Ignotus Assistant")
        self._title_label.setStyleSheet("color:#FFFFFF; font-size:18px; font-weight:bold; background:transparent;")
        h.addWidget(self._title_label)

        # 中间导航栏：聊天 / 管理 / 设置（PCL 风格胶囊按钮）
        self._nav_chat_btn = QPushButton("聊天")
        self._nav_manage_btn = QPushButton("管理")
        self._nav_settings_btn = QPushButton("设置")
        for btn in (self._nav_chat_btn, self._nav_manage_btn, self._nav_settings_btn):
            btn.setFixedSize(72, 32)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
        self._nav_chat_btn.setChecked(True)
        self._nav_chat_btn.clicked.connect(lambda: self._select_nav(0))
        self._nav_manage_btn.clicked.connect(lambda: self._select_nav(1))
        self._nav_settings_btn.clicked.connect(lambda: self._select_nav(2))
        # PCL 风格导航按钮：未选中蓝底白字、hover 略亮蓝；选中白底蓝字+边框
        nav_qss = (
            "QPushButton{background:transparent; color:#FFFFFF; border:1px solid transparent; "
            "border-radius:16px; font-size:13px; font-weight:bold;}"
            "QPushButton:hover{background:#378ADD;}"
            "QPushButton:checked{background:#FFFFFF; color:#378ADD; border:1px solid #FFFFFF;}"
        )
        self._nav_chat_btn.setStyleSheet(nav_qss)
        self._nav_manage_btn.setStyleSheet(nav_qss)
        self._nav_settings_btn.setStyleSheet(nav_qss)
        # nav 容器（_Segment，sizeHint=0，stretch=1 均分；内部 stretch 让按钮组居中）
        nav_w = _Segment()
        nav_lay = QHBoxLayout(nav_w); nav_lay.setContentsMargins(0, 0, 0, 0); nav_lay.setSpacing(8)
        nav_lay.addStretch(1)
        nav_lay.addWidget(self._nav_chat_btn)
        nav_lay.addWidget(self._nav_manage_btn)
        nav_lay.addWidget(self._nav_settings_btn)
        nav_lay.addStretch(1)

        # 右侧窗口控制按钮
        self._min_btn = QPushButton()
        self._min_btn.setIcon(QIcon(_MINIMIZE))
        self._min_btn.setIconSize(self._min_btn.iconSize())
        self._min_btn.setFixedSize(40, 36)
        self._min_btn.setStyleSheet(
            "QPushButton{background:transparent; border:none;}"
            "QPushButton:hover{background:#378ADD;}"
        )
        self._min_btn.clicked.connect(self.showMinimized)
        self._close_btn = QPushButton()
        self._close_btn.setIcon(QIcon(_CLOSE))
        self._close_btn.setIconSize(self._close_btn.iconSize())
        self._close_btn.setFixedSize(40, 36)
        self._close_btn.setStyleSheet(
            "QPushButton{background:transparent; border:none;}"
            "QPushButton:hover{background:#C0392B;}"
        )
        self._close_btn.clicked.connect(self.close)

        # 标题栏三等分：title_w(左对齐) | nav_w(居中) | btns_w(右对齐)，各 stretch=1 均分
        title_w = _Segment()
        title_w_lay = QHBoxLayout(title_w); title_w_lay.setContentsMargins(0, 0, 0, 0); title_w_lay.setSpacing(0)
        title_w_lay.addWidget(self._title_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        title_w_lay.addStretch(1)
        h.addWidget(title_w, 1)

        h.addWidget(nav_w, 1)

        btns_w = _Segment()
        btns_w_lay = QHBoxLayout(btns_w); btns_w_lay.setContentsMargins(0, 0, 0, 0); btns_w_lay.setSpacing(0)
        btns_w_lay.addStretch(1)
        btns_w_lay.addWidget(self._min_btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        btns_w_lay.addWidget(self._close_btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(btns_w, 1)

        # 自定义标题栏支持拖动窗口（标题栏整体可拖，不限于文字）
        self._drag_pos = None
        bar.mousePressEvent = self._title_mouse_press
        bar.mouseMoveEvent = self._title_mouse_move
        bar.mouseDoubleClickEvent = lambda e: self.toggleMaximized()
        return bar

    # ---- 外部唤起（托盘 / 桌宠右键菜单）----

    def bring_to_front(self):
        """显示主窗口并前置，**不改动当前页面**。

        2026-09-19 十五改：**窗口最小化到任务栏时 `show()` 是空操作** —— 最小化态下 `isVisible()`
        本来就是 True（见 §14），`show()` = `setVisible(True)` 因此什么都不做，窗口继续躺在任务栏里，
        「右键桌宠 → 主界面 / 设置」点了等于没点。实测：最小化后 `show()`，`isMinimized()` 仍为真。
        所以最小化时改走 `showNormal()`（只清 `WindowMinimized` 位）。

        为什么**不**无条件调 `showNormal()`：它在「可见的**最大化**窗口」上会把窗口还原成普通大小
        （`toggleMaximized()` 正是靠这个语义），「最大化着点托盘」会被无辜缩小。
        只在 `isMinimized()` 为真时才走它；而 Windows 上 Qt 把最大化位保留在最小化态里
        （`windowState()` = `min|max`），所以「最大化 → 最小化 → 唤起」仍还原成最大化。
        详见 docs/02 §17。
        """
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # ---- 页面状态（main.py 用它重判桌宠气泡的出现条件）----

    def is_chat_page(self) -> bool:
        """当前右栏是不是**聊天页**（桌宠气泡的条件之一，见 docs/02 §14.5）。"""
        return self._right_stack.currentIndex() == self.PAGE_CHAT

    def is_chat_visible(self) -> bool:
        """聊天区**用户现在真的看得到**吗：窗口显示着、没最小化、而且停在聊天页。

        最小化到任务栏时 `isVisible()` 仍是 True，但聊天区谁都看不见 —— 桌宠气泡的出现条件里
        必须把这一档算进去（否则「最小化着聊天页」时她的回复既没字也没气泡）。
        """
        return self.isVisible() and not self.isMinimized() and self.is_chat_page()

    def changeEvent(self, event):
        """窗口**最小化 / 还原**也要重判一次桌宠气泡 —— 换页会发通知，窗口状态变化同样会。"""
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self._notify_page_change()

    def set_page_change_cb(self, cb):
        """设置「右栏换页后」的通知（main.py 注入，用来重判桌宠气泡）。"""
        self._page_change_cb = cb

    def _notify_page_change(self):
        """页面**真的换了**之后通知一次。

        必须排在 `setCurrentIndex()` **之后** —— 回调里要读的是新页面（`is_chat_page()`）。
        ★这里**顺带重算一次状态条**（`recompute_facts=False`，只读 cfg、不 stat 模型目录）：
          用户在设置页填完 key / 加完目录、切回聊天页时，状态条要当场变绿 ——
          否则它一直写着旧结论，比不显示还误导。
        """
        self.refresh_health(recompute_facts=False)
        if self._page_change_cb is not None:
            self._page_change_cb()

    def open_nav_page(self, nav_index):
        """显示主窗口并切到指定顶部导航：0=聊天 / 1=管理 / 2=设置。

        桌宠右键菜单的「主界面」「设置」走这里 —— 与点击顶部导航按钮完全同一条路径，
        因此「已在设置区再点设置」保持当前页、「从别处进设置」落到通用设置等语义一致。
        """
        self.bring_to_front()
        self._select_nav(nav_index)

    def _select_nav(self, nav_index):
        """顶部导航栏切换：0=聊天，1=管理（管理 API / 管理唤醒词），2=设置（通用 / 权限）。

        左栏形态不在这里决定 —— 它跟着右栏目标页走（`_switch_right_panel` → `_set_left_mode`）。
        """
        cur = self._right_stack.currentIndex()
        if nav_index == 0:
            self._show_chat_panel()
        elif nav_index == 1:
            # 已在某个管理页就保持当前页，只纠正选中态；否则回到管理 API
            if self._is_manage_page(cur):
                self._switch_right_panel(cur)
            else:
                self._show_api_panel()
        else:
            # 已在设置区（通用设置 / 权限管理）→ 点「设置」不改动当前内容；
            # 从别处进设置 → 一律落在「通用设置」（不记忆上次停留的设置页）
            if self._is_settings_page(cur):
                self._switch_right_panel(cur)
            else:
                self._show_settings_page(self.SETTINGS_BASE)

    def _is_manage_page(self, index):
        return index in (self.PAGE_API, self.PAGE_WAKE, self.PAGE_PRESET)

    def _is_settings_page(self, index):
        return index >= self.SETTINGS_BASE

    def _left_mode_for(self, index):
        """右栏页索引 → 左栏形态（唯一的映射入口，别在别处各判一遍）。"""
        if self._is_settings_page(index):
            return self.LEFT_MODE_SETTINGS
        if self._is_manage_page(index):
            return self.LEFT_MODE_MANAGE
        return self.LEFT_MODE_ROLE

    def _update_nav_state(self, current_index=None):
        """根据右栏当前页面，同步顶部三个导航按钮的选中态。"""
        if current_index is None:
            current_index = self._right_stack.currentIndex()
        self._nav_chat_btn.setChecked(current_index == self.PAGE_CHAT)
        self._nav_manage_btn.setChecked(self._is_manage_page(current_index))
        self._nav_settings_btn.setChecked(self._is_settings_page(current_index))

    def _show_settings_page(self, index):
        """切到设置区某个页面（index 为右栏页索引，>=SETTINGS_BASE）。"""
        if not self._is_settings_page(index):
            index = self.SETTINGS_BASE
        # 只有真的发生页面切换才复位折叠分组（重复点同一个设置项不该被弹回去）
        switching = self._right_stack.currentIndex() != index
        self._refresh_settings_panel(index, reset_groups=switching)
        self._switch_right_panel(index)

    def _show_manage_page(self, index):
        """切到管理区某个页面（index 为右栏页索引：管理 API / 管理唤醒词 / 设定卡）。"""
        if index == self.PAGE_WAKE:
            self._show_wake_panel()
        elif index == self.PAGE_PRESET:
            self._show_preset_panel()
        else:
            self._show_api_panel()

    def _sync_settings_nav(self, index):
        for page_index, btn in getattr(self, "_settings_nav_btns", ()):
            btn.setChecked(page_index == index)

    def _sync_manage_nav(self, index):
        for page_index, btn in getattr(self, "_manage_nav_btns", ()):
            btn.setChecked(page_index == index)

    def _title_mouse_press(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _title_mouse_move(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def toggleMaximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _build_left_panel(self):
        """左栏容器：白底角色区 ↔ 浅蓝底管理导航 / 设置导航，三者互斥切换。"""
        panel = _ColorPanel(self.LEFT_BG_ROLE)
        panel.setObjectName("leftPanel")
        panel.setFixedWidth(self.LEFT_WIDTH)
        self._left_panel = panel

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._left_stack = _SlideStack()
        outer.addWidget(self._left_stack, 1)

        # 危险操作倒计时提示（胶囊，默认隐藏）：挂在左栏底部而非角色页内，
        # 这样切到管理 / 设置区时倒计时依然可见，不会漏掉关机前的取消时机。
        self._notice_label = QLabel("")
        self._notice_label.setWordWrap(True)
        self._notice_label.setMaximumWidth(self.LEFT_WIDTH - 32)
        self._notice_label.setStyleSheet(
            "color:#854F0B; background:#FAEEDA; border:1px solid #FAC775;"
            " border-radius:10px; padding:4px 10px; font-size:12px;"
        )
        self._notice_label.setAlignment(Qt.AlignCenter)
        self._notice_label.setVisible(False)
        notice_wrap = QHBoxLayout()
        notice_wrap.setContentsMargins(16, 0, 16, 16)
        notice_wrap.addWidget(self._notice_label)
        outer.addLayout(notice_wrap)

        self._left_role_page = self._build_left_role_page()
        self._left_manage_page = self._build_left_manage_page()
        self._left_settings_page = self._build_left_settings_page()
        self._left_stack.addWidget(self._left_role_page)
        self._left_stack.addWidget(self._left_manage_page)
        self._left_stack.addWidget(self._left_settings_page)
        # 形态 → 页面（`_set_left_mode` 唯一的取页入口）
        self._left_pages = {
            self.LEFT_MODE_ROLE: self._left_role_page,
            self.LEFT_MODE_MANAGE: self._left_manage_page,
            self.LEFT_MODE_SETTINGS: self._left_settings_page,
        }

        # 底色渐变：白 ↔ 深蓝（QSS 的 :hover 不支持过渡，这里用 QVariantAnimation 插值）
        self._left_bg_anim = QVariantAnimation(self)
        self._left_bg_anim.setDuration(260)
        self._left_bg_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._left_bg_anim.valueChanged.connect(self._apply_left_bg)
        self._left_slide_anims = []
        self._apply_left_bg(0.0)

        panel.enterEvent = lambda e: self._show_actions()
        panel.leaveEvent = lambda e: self._hide_actions()
        return panel

    def _build_left_role_page(self):
        """角色区：头像 / 名字 / 状态 / 倒计时提示 / 悬浮按钮 / 角色下拉。"""
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 24, 0, 24)
        v.setSpacing(12)
        v.setAlignment(Qt.AlignHCenter)

        # 头像（点击切换角色）
        self._avatar_btn = QPushButton()
        self._avatar_btn.setFixedSize(108, 108)
        self._avatar_btn.setIconSize(QSize(108, 108))
        self._avatar_btn.setStyleSheet(
            "QPushButton{background:transparent; border:none; border-radius:54px;}"
            "QPushButton:hover{background:#E6F1FB; border-radius:54px;}"
        )
        self._avatar_btn.clicked.connect(self._on_avatar_clicked)
        v.addWidget(self._avatar_btn, 0, Qt.AlignHCenter)

        # 角色名
        self._name_label = QLabel()
        self._name_label.setStyleSheet("font-size:15px; font-weight:bold; color:#0C447C; background:transparent;")
        self._name_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self._name_label, 0, Qt.AlignHCenter)

        # 状态标签（胶囊）
        self._status_label = QLabel("待机")
        self._status_label.setStyleSheet(
            "color:#185FA5; background:#E6F1FB; border-radius:10px; padding:4px 12px; font-size:12px;"
        )
        self._status_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self._status_label, 0, Qt.AlignHCenter)

        # 悬浮按钮组（默认隐藏，带 0.3s 淡入淡出）
        self._action_row = QHBoxLayout()
        self._action_row.setSpacing(8)
        self._action_row.setAlignment(Qt.AlignCenter)
        self._pencil_btn = self._make_action_btn(_PENCIL, "编辑")
        self._switch_btn = self._make_action_btn(_SWITCH, "切换角色")
        self._pencil_btn.clicked.connect(self._show_pencil_menu)
        self._switch_btn.clicked.connect(self._enter_switch_mode)
        self._action_row.addWidget(self._pencil_btn)
        self._action_row.addWidget(self._switch_btn)
        self._action_widget = QWidget()
        self._action_widget.setLayout(self._action_row)
        # 透明度效果 + 淡入淡出动画
        self._action_effect = QGraphicsOpacityEffect(self._action_widget)
        self._action_effect.setOpacity(0.0)
        self._action_widget.setGraphicsEffect(self._action_effect)
        self._action_widget.setVisible(False)
        self._action_anim = QPropertyAnimation(self._action_effect, b"opacity", self)
        self._action_anim.setDuration(200)
        v.addWidget(self._action_widget, 0, Qt.AlignHCenter)

        # 切换角色的下拉框（默认隐藏，带透明度效果避免出现时一闪而过）
        self._switch_combo = HoverComboBox()
        for key, role in self.cfg["roles"].items():
            self._switch_combo.addItem(role["name"], key)
            if not is_role_switchable(key):
                # ★艾莲暂不可切换（2026-09-28，用户拍板：贴图未做完）⇒ **灰显 + 选不中**。
                #   走 QComboBox 的标准做法：关掉该行 model item 的 enabled ⇒ 灰字；
                #   `activated` 不会为禁用行发出 ⇒ **点不动**。
                #   ★唯一真值 = `config.SWITCHABLE_ROLES`（别在这儿写死角色名）；见 docs/02 §24。
                item = self._switch_combo.model().item(self._switch_combo.count() - 1)
                if item is not None:
                    item.setEnabled(False)
        self._switch_combo.activated.connect(self._on_switch_combo_activated)
        self._switch_combo.setFixedWidth(140)
        self._switch_combo_effect = QGraphicsOpacityEffect(self._switch_combo)
        self._switch_combo_effect.setOpacity(0.0)
        self._switch_combo.setGraphicsEffect(self._switch_combo_effect)
        self._switch_combo.setVisible(False)
        v.addWidget(self._switch_combo, 0, Qt.AlignHCenter)

        v.addStretch(1)
        return page

    def _build_left_nav_page(self, items, on_pick):
        """左栏导航页（浅蓝底）：若干可切换的胶囊按钮，无标题、各项自顶边留白起等距排列。

        管理导航（`MANAGE_ITEMS`）与设置导航（`SETTINGS_ITEMS`）**共用这一份实现** ——
        两处的尺寸 / 配色 / 选中态 / hover / 入场动画必须完全一致，不允许各写一份。

        `items` 是 `(page_index, 显示名)` 序列，其中 `page_index` 必须等于该面板在
        `_right_stack` 里的真实索引；返回 `(page, [(page_index, btn), ...])`。
        """
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 24, 0, 24)
        v.setSpacing(6)

        btns = []
        for page_index, name in items:
            btn = QPushButton(name)
            btn.setFixedHeight(40)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:transparent; color:#0C447C; border:1px solid transparent;"
                " border-radius:15px; font-size:13px;}"
                "QPushButton:hover{background:#E6F1FB;}"
                "QPushButton:checked{background:#378ADD; color:#FFFFFF; font-weight:bold;}"
            )
            btn.clicked.connect(lambda _=False, idx=page_index: on_pick(idx))
            row = QHBoxLayout()
            row.setContentsMargins(14, 0, 14, 0)
            row.addWidget(btn)
            v.addLayout(row)
            btns.append((page_index, btn))

        v.addStretch(1)
        return page, btns

    def _build_left_manage_page(self):
        """管理导航页（浅蓝底）：管理 API / 管理唤醒词（与设置导航同款）。"""
        page, self._manage_nav_btns = self._build_left_nav_page(
            self.MANAGE_ITEMS, self._show_manage_page
        )
        return page

    def _build_left_settings_page(self):
        """设置导航页（浅蓝底）：通用设置 / 权限管理（与设置导航同款）。"""
        page, self._settings_nav_btns = self._build_left_nav_page(
            ((self.SETTINGS_BASE + i, name)
             for i, (_key, name) in enumerate(self.SETTINGS_ITEMS)),
            self._show_settings_page,
        )
        return page

    # ---- 左栏形态（角色区 / 管理导航 / 设置导航）----

    def _apply_left_bg(self, t):
        """底色插值：t=0 白底（角色区），t=1 浅蓝（管理 / 设置导航页）。自绘，不走 QSS。"""
        t = max(0.0, min(1.0, float(t)))
        self._left_bg_t = t
        r0, g0, b0 = self.LEFT_BG_ROLE
        r1, g1, b1 = self.LEFT_BG_SETTINGS
        r = int(r0 + (r1 - r0) * t)
        g = int(g0 + (g1 - g0) * t)
        b = int(b0 + (b1 - b0) * t)
        self._left_panel.set_bg((r, g, b))

    def _set_left_mode(self, mode, animate=True):
        """左栏三态切换：role（角色区）/ manage（管理导航）/ settings（设置导航）。

        底色只有「白 ↔ 浅蓝」两种：角色区白底，管理与设置都是浅蓝导航页；
        管理 ↔ 设置之间底色不变，只有内容做 20px 横向平移（`_switch_left_page`）。
        """
        if mode not in self.LEFT_MODES:
            raise ValueError(f"未知的左栏形态：{mode!r}")
        if self._left_mode == mode:
            return
        self._left_mode = mode
        # 清掉两个导航的选中态；随后由 _switch_right_panel 按目标页重新点亮。
        # （回角色区也要清 —— 否则下次进管理区之前，那个隐藏的按钮会一直是选中态。）
        for _page_index, btn in self._settings_nav_btns + self._manage_nav_btns:
            btn.setChecked(False)

        if mode != self.LEFT_MODE_ROLE:
            # 进导航页：角色切换态与悬浮按钮都先收起，避免残留在浅蓝底上；
            # 必须在动画开始前做完 —— 这些显隐会触发布局失效，动画中途发生就会抖一下。
            self._switching_role = False
            self._switch_combo.setVisible(False)
            self._action_widget.setVisible(False)
            self._action_effect.setOpacity(0.0)

        self._left_bg_anim.stop()
        if animate:
            self._left_bg_anim.setStartValue(self._left_bg_t)
            self._left_bg_anim.setEndValue(0.0 if mode == self.LEFT_MODE_ROLE else 1.0)
            self._left_bg_anim.start()
        else:
            self._apply_left_bg(0.0 if mode == self.LEFT_MODE_ROLE else 1.0)

        self._switch_left_page(self._left_pages[mode], animate=animate)

    def _switch_left_page(self, target, animate=True):
        """左栏页面切换：新页自左侧 -LEFT_SLIDE 平移到位（从左向右）。

        注意：这里只做 geometry 平移、不加 QGraphicsOpacityEffect ——
        左栏需要透出外层的底色，而 effect 会把页面先渲染进独立 pixmap，
        半透明期间会糊成一块白底盖住底色（右栏页面本身是白底，所以那边可以用淡入）。
        """
        stack = self._left_stack
        if stack.currentWidget() is target:
            return
        w = stack.width() or self.LEFT_WIDTH
        h = stack.height() or 400

        stack.setCurrentIndex(stack.indexOf(target))
        if not animate:
            stack.end_slide(target)
            return

        start = QRect(-self.LEFT_SLIDE, 0, w, h)
        end = QRect(0, 0, w, h)
        target.setGeometry(start)
        stack.begin_slide(target)

        pos_anim = QPropertyAnimation(target, b"geometry", stack)
        pos_anim.setDuration(320)
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        pos_anim.setStartValue(start)
        pos_anim.setEndValue(end)
        pos_anim.finished.connect(lambda: stack.end_slide(target))
        pos_anim.start()
        self._left_slide_anims = [pos_anim]  # 保持引用防被 GC

    def _make_action_btn(self, icon_path, tip):
        return _ActionButton(icon_path, tip, self)

    def _show_actions(self):
        if self._switching_role or self._left_mode != self.LEFT_MODE_ROLE:
            return
        # 取消待执行的隐藏定时器，避免移入后被上一次移出的 timer 隐藏
        if getattr(self, "_action_hide_timer", None) is not None:
            self._action_hide_timer.stop()
        self._action_widget.setVisible(True)
        self._action_anim.stop()
        self._action_anim.setStartValue(self._action_effect.opacity())
        self._action_anim.setEndValue(1.0)
        self._action_anim.start()

    def _hide_actions(self):
        if getattr(self, "_menu_open", False):
            return  # 菜单弹出期间不隐藏按钮
        # 停止当前动画，从当前不透明度开始淡出
        self._action_anim.stop()
        self._action_anim.setStartValue(self._action_effect.opacity())
        self._action_anim.setEndValue(0.0)
        self._action_anim.start()
        # 动画结束后（0.2s）再隐藏，避免占用布局/拦截鼠标
        if getattr(self, "_action_hide_timer", None) is not None:
            self._action_hide_timer.stop()
        self._action_hide_timer = QTimer(self)
        self._action_hide_timer.setSingleShot(True)
        self._action_hide_timer.timeout.connect(lambda: self._action_widget.setVisible(False))
        self._action_hide_timer.start(200)

    def _on_avatar_clicked(self):
        # 点击头像 = 切换角色
        self._enter_switch_mode()

    def _build_pencil_menu(self):
        """构建铅笔按钮的菜单：只保留两个管理入口（设置从顶部「设置」进入）。"""
        menu = QMenu(self)
        # 禁用系统自带的 drop shadow，改用自定义较小阴影
        menu.setWindowFlag(Qt.NoDropShadowWindowHint, True)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        shadow = QGraphicsDropShadowEffect(menu)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 60))
        menu.setGraphicsEffect(shadow)
        menu.setStyleSheet(
            "QMenu{background:#FFFFFF; border:1px solid #E6F1FB; border-radius:8px; padding:4px;}"
            "QMenu::item{padding:8px 20px; border-radius:6px; color:#334155;}"
            "QMenu::item:selected{background:#E6F1FB; color:#0C447C;}"
        )
        menu.addAction("管理 API")
        menu.addAction("管理唤醒词")
        return menu

    def _show_pencil_menu(self):
        # 菜单弹出期间标记，阻止 leaveEvent 触发的淡出把按钮隐藏
        self._menu_open = True
        self._show_actions()  # 确保按钮显示
        menu = self._build_pencil_menu()
        act_api, act_wake = menu.actions()[:2]
        # 菜单从偏左侧弹出：x 对齐到左栏左边缘（距窗口左 8px），y 对齐铅笔按钮底部 + 3px 间距
        pos = self._pencil_btn.mapToGlobal(self._pencil_btn.rect().bottomLeft())
        pos.setX(self.mapToGlobal(QPoint(0, 0)).x() + 8)
        pos.setY(pos.y() + 3)
        chosen = menu.exec(pos)
        self._menu_open = False
        if chosen is act_api:
            self._show_api_panel()
        elif chosen is act_wake:
            self._show_wake_panel()

    def _enter_switch_mode(self):
        self._switching_role = True
        # 记录按钮那一行的 y 坐标（下拉框的目标位置，与按钮同排）
        self._action_row_y = self._action_widget.pos().y()
        # 1. 两个按钮原地淡出 0.2s，完成后隐藏
        self._action_anim.stop()
        self._action_anim.setStartValue(self._action_effect.opacity())
        self._action_anim.setEndValue(0.0)
        self._action_anim.start()
        QTimer.singleShot(200, lambda: self._action_widget.setVisible(False))
        # 2. 显示角色下拉框（初始透明，避免在原位置一闪而过）
        self._switch_combo.setVisible(True)
        self._switch_combo_effect.setOpacity(0.0)
        idx = self._switch_combo.findData(self._current_role_key)
        if idx >= 0:
            self._switch_combo.setCurrentIndex(idx)
        # 3. 下拉框自下而上 10px 上移到按钮那一行 + 淡入动画
        def animate_combo():
            target_x = self._switch_combo.pos().x()  # 保持居中 x
            target_y = self._action_row_y + 5  # 按钮那一行下方 5px
            self._switch_combo.move(target_x, target_y + 10)
            pos_anim = QPropertyAnimation(self._switch_combo, b"pos", self._switch_combo)
            pos_anim.setDuration(200)
            pos_anim.setEasingCurve(QEasingCurve.OutCubic)
            pos_anim.setStartValue(QPoint(target_x, target_y + 10))
            pos_anim.setEndValue(QPoint(target_x, target_y))
            op_anim = QPropertyAnimation(self._switch_combo_effect, b"opacity", self._switch_combo)
            op_anim.setDuration(200)
            op_anim.setEasingCurve(QEasingCurve.OutCubic)
            op_anim.setStartValue(0.0)
            op_anim.setEndValue(1.0)
            pos_anim.start()
            op_anim.start()
            self._combo_anims = [pos_anim, op_anim]  # 保持引用
        QTimer.singleShot(0, animate_combo)
        # 灰色默认头像
        self._set_avatar_default()
        # 右侧切换到空聊天界面（清空）
        self._chat_view.clear()
        self._chat_view.add_system("请选择要切换的角色")
        # 只显示下拉框，不自动弹出下拉列表（用户手动点击下拉框再选择）

    def _on_switch_combo_activated(self, idx):
        key = self._switch_combo.itemData(idx)
        # ★兜底（docs/02 §24）：**不可切换的角色（艾莲）即便被程序化选中也不切过去**。
        #   模型层已经把「点它」拦住了（`activated` 不为其发出），所以正常路径走不到这里；
        #   这道闸是**显式失败** —— 万一将来有人绕过模型直接发信号，也不会真的切过去。
        if key and not is_role_switchable(key):
            return
        if not key or key == self._current_role_key:
            self._confirm_switch(key or self._current_role_key)
            return
        self._confirm_switch(key)

    def _confirm_switch(self, new_key):
        self._switching_role = False
        self._switch_combo.setVisible(False)
        self.cfg["current_role"] = new_key
        save_config(self.cfg)
        self._set_role(new_key)
        # 加载历史（如果有）
        self._load_chat_history()
        # 不需要调 _role_change_cb 吗？main.py 里有 set_role_change_cb
        if self._role_change_cb:
            self._role_change_cb(new_key)

    def _set_avatar_default(self):
        self._avatar_btn.setIcon(QIcon(_circular_crop(QPixmap(_DEFAULT_AVATAR), 108)))

    def _set_avatar_role(self, role_key):
        self._avatar_btn.setIcon(QIcon(_circular_crop(_load_avatar(role_key), 108)))

    def _set_role(self, role_key):
        self._current_role_key = role_key
        role = self.cfg["roles"][role_key]
        self._name_label.setText(role["name"])
        self._set_avatar_role(role_key)

    def _build_right_panel(self):
        self._right_panel = QFrame()
        self._right_panel.setStyleSheet("background:#FFFFFF;")
        v = QVBoxLayout(self._right_panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._right_stack = _SlideStack()
        v.addWidget(self._right_stack, 1)

        # 聊天面板
        self._chat_view = ChatView(self)
        self._right_stack.addWidget(self._chat_view)

        # API 面板
        self._api_panel = ApiPanel(self.cfg, self)
        self._right_stack.addWidget(self._api_panel)

        # 唤醒词面板
        self._wake_panel = WakeWordPanel(self.cfg, self._current_role_key, self)
        self._right_stack.addWidget(self._wake_panel)

        # 设定卡面板（管理区第 3 页：跟随当前角色，与唤醒词页同一套做法）
        self._preset_panel = PresetPanel(self.cfg, self._current_role_key, self)
        self._right_stack.addWidget(self._preset_panel)

        # 设置类页面（顺序必须与 SETTINGS_ITEMS 一致，索引从 SETTINGS_BASE 起）
        builders = {
            "general": lambda: GeneralPanel(self.cfg, self),
            "permissions": lambda: PermPanel(self.cfg, self),
        }
        self._settings_index = {}
        self._settings_panels = {}
        for key, _name in self.SETTINGS_ITEMS:
            panel = builders[key]()
            self._settings_panels[key] = panel
            self._settings_index[key] = self._right_stack.addWidget(panel)
        self._perm_panel = self._settings_panels["permissions"]

        # 给所有页面加透明度效果（用于切换时的淡出/淡入），并记录各自位置
        self._panel_effects = {}
        self._panel_positions = {}
        for i in range(self._right_stack.count()):
            w = self._right_stack.widget(i)
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(1.0)
            eff.setEnabled(False)  # 不透明时禁用，避免与子控件 effect 嵌套冲突
            w.setGraphicsEffect(eff)
            self._panel_effects[w] = eff
            self._panel_positions[w] = i

        return self._right_panel

    def _refresh_settings_panel(self, index, reset_groups=False):
        """设置页显示前刷新数据（各面板刷新方法名不一致，统一在这里适配）。

        `reset_groups=True` 时先让面板把折叠分组复位（页面切换进入时用），
        然后再刷新内容，使重建出来的分组就是收起态。
        """
        panel = self._right_stack.widget(index)
        if reset_groups:
            reset = getattr(panel, "reset_groups", None)
            if callable(reset):
                reset()
        for name in ("refresh", "_rebuild"):
            fn = getattr(panel, name, None)
            if callable(fn):
                fn()
                break
        # 重新进入设置页时回到顶端（不保留上次的下拉位置）
        _scroll_to_top(panel)

    def _switch_right_panel(self, index, animate=True):
        # 左栏形态**只在这里**跟随右栏目标页：设置页 → 设置导航；管理页 → 管理导航；其余 → 角色区
        self._set_left_mode(self._left_mode_for(index), animate=animate)
        if self._is_settings_page(index):
            # 记住停留页 + 同步左栏选中态（_set_left_mode 进导航页时会先清空选中）
            self._settings_page = index
            self._sync_settings_nav(index)
        elif self._is_manage_page(index):
            # 同步左栏管理导航的选中态（同上，先被 _set_left_mode 清空）
            self._sync_manage_nav(index)
        if self._right_stack.currentIndex() == index:
            self._update_nav_state(index)
            return
        # 同步顶部导航栏选中态（聊天=0；管理=1/2；设置=3 起）
        self._update_nav_state(index)
        target = self._right_stack.widget(index)
        if not animate:
            self._right_stack.setCurrentIndex(index)
            self._notify_page_change()
            return
        cur = self._right_stack.currentWidget()
        w = self._right_stack.width()
        h = self._right_stack.height()
        # 右栏内容一律「自上而下平移」入场：起点在终点上方 RIGHT_SLIDE 像素处
        start_geo = QRect(0, -self.RIGHT_SLIDE, w, h)

        # 1. 当前界面原地淡出（0.2s）
        cur_eff = self._panel_effects[cur]
        cur_eff.setEnabled(True)  # 动画期间启用 effect
        cur_op = QPropertyAnimation(cur_eff, b"opacity", cur)
        cur_op.setDuration(200)
        cur_op.setStartValue(cur_eff.opacity())
        cur_op.setEndValue(0.0)

        # 2. 先切换到目标界面，再立即移到滑动起点（避免先在终点闪现）
        self._right_stack.setCurrentIndex(index)
        self._notify_page_change()
        target_eff = self._panel_effects[target]
        target_eff.setOpacity(1.0)
        target.setGeometry(start_geo)
        self._right_stack.begin_slide(target)  # 动画期间锁住，防布局/尺寸事件抢位
        pos_anim = QPropertyAnimation(target, b"geometry", self._right_stack)
        pos_anim.setDuration(400)
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        pos_anim.setStartValue(start_geo)
        pos_anim.setEndValue(QRect(0, 0, w, h))
        pos_anim.finished.connect(lambda: self._right_stack.end_slide(target))

        cur_op.start()
        pos_anim.start()
        self._current_anims = [cur_op, pos_anim]  # 保持引用防被 GC

        # 动画结束后恢复旧界面透明度并禁用 effect，便于下次切换
        def cleanup():
            cur_eff.setOpacity(1.0)
            cur_eff.setEnabled(False)
        cur_op.finished.connect(cleanup)

    def _show_api_panel(self):
        self._api_panel.refresh()
        self._switch_right_panel(self.PAGE_API)

    def _show_wake_panel(self):
        self._wake_panel.set_role(self._current_role_key)
        self._switch_right_panel(self.PAGE_WAKE)

    def _show_preset_panel(self):
        """切到设定卡页 —— 每次进入都按**当前角色**重新渲染（预设是跟随角色的）。"""
        self._preset_panel.set_role(self._current_role_key)
        self._switch_right_panel(self.PAGE_PRESET)

    def _show_chat_panel(self):
        self._switch_right_panel(self.PAGE_CHAT)

    def _apply_style(self):
        self.setStyleSheet(
            "QWidget { background:#FFFFFF; color:#334155; font-size:13px; }"
        )

    def _apply_rounded_corners(self):
        """给窗口设置圆角遮罩（无边框窗口默认是方角）。"""
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 16, 16)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_rounded_corners()
        self._apply_health_elide()      # 状态条按新宽度重新省略（P2）

    # ---- 对外接口（main.py 依赖）----
    def set_status(self, state: State):
        self._status_label.setText(STATUS_TEXT.get(state, state.value))

    # ---- 危险操作倒计时弹窗（屏幕正中央，2026-09-18）----

    def show_danger_countdown(self, label: str, remaining) -> None:
        """把「{操作}倒计时」摆到**屏幕正中央**（第一次调用建窗 + 落位，之后每秒只改数字）。

        **已经显示时直接返回**：不重建、不重放入场动画、连位置都不动 —— 数字每秒跳一下已经够醒目，
        窗口再弹一下会让人以为「又出事了」。红色取消态例外：新排程进来要把它复位回蓝态。
        """
        dlg = getattr(self, "_danger_dlg", None)
        if dlg is None:
            dlg = DangerCountdownDialog()
            dlg.set_callbacks(getattr(self, "_danger_run_cb", None),
                              getattr(self, "_danger_cancel_cb", None))
            self._danger_dlg = dlg
        if dlg.cancelled:
            dlg.reset_cancelled()      # 上一个操作刚被取消、红色还没散：新排程把它接回蓝态
        dlg.set_countdown(label, remaining)
        if dlg.isVisible():
            return
        scr = QGuiApplication.primaryScreen()
        geo = scr.availableGeometry() if scr is not None else QRect(0, 0, 0, 0)
        # **在 show() 之前搬**：move() 会给窗口打上 WA_Moved，Qt 才不会在 show() 时又按父窗摆回中间
        # 用「(可用区 − 卡片) // 2」这条标准居中算式：拿 center() 减半个宽（`// 2`）在宽高为偶数时
        # 会整体偏 1px（`QRect.center()` 用的是 `(w−1)//2`），几何中心对不上。
        # **按卡片高算**：卡片本体在窗口顶部，多出来的 15px 全在下方（弹出位移用）——
        # 按窗口高的一半摆会让卡片整体偏上 7.5px。
        dlg.move(geo.x() + (geo.width() - DLG_CARD_W) // 2,
                 geo.y() + (geo.height() - DLG_CARD_H) // 2)
        dlg.show()
        dlg.start_show_anim()          # 淡入 0.5s：50%→100% + 自下而上 15px

    def cancel_danger_countdown(self) -> None:
        """「取消」：把倒计时弹窗转成**红色取消态**（保持 1.5s 再自己淡出）。

        **幂等**：没弹窗 / 已经取消过都直接返回。取消态期间 `hide_danger_countdown()` 是空操作
        （否则下一秒 `_tick_danger` 的「队列空了」会把红色态当场抹掉）。
        """
        dlg = getattr(self, "_danger_dlg", None)
        if dlg is None or not dlg.isVisible() or dlg.cancelled:
            return
        dlg.show_cancelled()

    def hide_danger_countdown(self) -> None:
        """收起倒计时弹窗（到点执行 / 队列被清空 / 被新排程顶掉：三种收尾都走它）。

        取消态**不收**（交给它自己的 1.5s 计时），淡出中也不重放。
        """
        dlg = getattr(self, "_danger_dlg", None)
        if dlg is None or not dlg.isVisible():
            return
        if dlg.cancelled or dlg.is_fading_out():
            return
        dlg.hide_with_fade()

    def set_danger_callbacks(self, run_cb, cancel_cb) -> None:
        """把倒计时弹窗的两个按钮接到 `main.py`（点击 → 立刻执行 / 取消）。"""
        self._danger_run_cb = run_cb
        self._danger_cancel_cb = cancel_cb
        dlg = getattr(self, "_danger_dlg", None)
        if dlg is not None:
            dlg.set_callbacks(run_cb, cancel_cb)

    def set_notice(self, text: str):
        """左栏倒计时提示（危险操作排程中显示剩余秒数，传空串隐藏）。"""
        text = (text or "").strip()
        self._notice_label.setText(text)
        self._notice_label.setVisible(bool(text))

    def _general_setting_row(self, attr: str):
        """取「通用设置」页里的某一行（面板 / 行还没建好 ⇒ `None`）。

        所有 `sync_*` 都走它 —— 口径统一为「**只同步这一行、不整页重建**」：重建会打断
        正在进行的动画，也可能销毁别处正在用的控件（与设置页里点滑块的处理一致）。
        """
        panel = self._settings_panels.get("general")
        if panel is None:
            return None
        return getattr(panel, attr, None)

    def sync_mute_mode(self, on: bool) -> None:
        """语音开关切了静音模式后，把通用设置里那一行的**滑块**同步过来。

        **只同步这一行、不整页重建** —— 与设置页里点滑块的处理一致（重建会打断
        正在进行的动画，也可能销毁别处正在用的控件）。面板若还没建好就跳过。
        """
        row = self._general_setting_row("_mute_row")
        if row is not None:
            row.set_enabled(bool(on), animate=True)

    def append_log(self, text: str):
        """兼容旧接口：作为系统提示显示。"""
        self._chat_view.add_system(text)

    def add_assistant_message(self, role_key: str, name: str, text: str):
        """AI 回复气泡（角色头像 + 气泡，靠左）。整条一次性给出，并落进聊天记录。"""
        self._chat_view.add_bubble("assistant", name, text, role_key=role_key)
        self._save_chat_message(role_key, "assistant", text)

    # ---- 回复气泡：**一次性**出现（文字与声音同刻）----
    def begin_assistant_message(self, role_key: str, name: str, text: str):
        """建出这条回复的气泡（此时中文已经吐完，写进去的就是完整文本）。"""
        self._chat_view.add_bubble("assistant", name, text, role_key=role_key)

    def finish_assistant_message(self, role_key: str, text: str):
        """回复结束：把最终中文落进聊天记录。"""
        if (text or "").strip():
            self._save_chat_message(role_key, "assistant", text)

    def add_user_message(self, text: str):
        """用户消息气泡（无头像，靠右）。"""
        self._chat_view.add_bubble("user", "你", text)
        self._save_chat_message(self._current_role_key, "user", text)

    def add_system_message(self, text: str):
        self._chat_view.add_system(text)
        self._save_chat_message(self._current_role_key, "system", text)

    def show_thinking(self, name: str):
        """AI 思考期间显示「头像 + 灰色气泡『xxx 正在思考...』」提示。"""
        self._chat_view.show_thinking(name, role_key=self._current_role_key)

    def hide_thinking(self):
        """移除「正在思考...」提示。"""
        self._chat_view.hide_thinking()

    def set_role_change_cb(self, cb):
        self._role_change_cb = cb

    def set_hide_to_tray(self, cb):
        self._hide_to_tray = cb

    def set_quit_app(self, cb):
        """设置「完全退出软件」的回调（通用设置里选「关闭软件」时用）。"""
        self._quit_app = cb

    def set_reset_pet_pos(self, cb):
        """设置「把桌宠放回默认位置」的动作（通用设置里的「重置角色位置」）。

        桌宠不归主窗口管（它是独立顶层窗），所以这里只存一个动作；
        真正的落位由 main.py 注入（`pet_default_pos` 与启动落位同一处计算）。
        """
        self._reset_pet_pos_cb = cb

    def reset_pet_pos(self) -> bool:
        """跑一次「重置角色位置」。返回是否真的落位了（main.py 还没接上时 False）。"""
        if self._reset_pet_pos_cb is None:
            return False
        self._reset_pet_pos_cb()
        return True

    def set_mute_mode_cb(self, cb):
        """设置「静音模式被切换」的通知（通用设置里的静音滑块）。

        与 `set_reset_pet_pos` 同一个写法：桌宠不归主窗口管，这里只存一个动作，
        真正的「弹一下状态提示气泡」由 main.py 注入。**注意**：设置页自己已经落过
        cfg、也提示过用户了，这里注册的回调只该弹桌宠提示，别重复写盘 / 发消息。
        """
        self._on_mute_mode = cb

    def notify_mute_mode(self, on: bool) -> None:
        """跑一次「静音模式被切换」的通知（main.py 还没接上时什么也不做）。"""
        if self._on_mute_mode is not None:
            self._on_mute_mode(bool(on))

    def set_patpat_mode_cb(self, cb):
        """设置「patpat 模式被切换」的通知（通用设置里那个滑块）。

        写法与 `set_mute_mode_cb` 一样，但**职责不同**：静音模式的状态在配置里，设置页落完就完了；
        patpat 模式的状态**在桌宠那边**（点击行为归它管），所以这里注册的回调要去 `pet.set_patpat()`
        —— 桌宠那边切完会从它自己的切换回调里弹提示、并回同步这一行。
        """
        self._on_patpat_mode = cb

    def notify_patpat_mode(self, on: bool) -> None:
        """跑一次「patpat 模式被切换」的通知（main.py 还没接上时什么也不做）。"""
        if self._on_patpat_mode is not None:
            self._on_patpat_mode(bool(on))

    def sync_patpat_mode(self, on: bool) -> None:
        """从别处（右键菜单）切了 patpat 模式后，把通用设置里那一行的**滑块**同步过来。

        与 `sync_mute_mode` 同一套写法：**只同步这一行、不整页重建**。面板若还没建好就跳过。
        """
        row = self._general_setting_row("_patpat_row")
        if row is not None:
            row.set_enabled(bool(on), animate=True)

    def set_pet_lock_cb(self, cb):
        """设置「桌宠固定被切换」的通知（通用设置里那个滑块）。

        写法与 `set_patpat_mode_cb` 一样：固定状态**在桌宠那边**（拖动行为归它管），
        所以这里注册的回调要去 `pet.set_locked()` —— 桌宠那边切完会从它自己的切换回调里
        弹提示、并回同步这一行。★与 patpat 的差别只有一点：初始值由 main.py 从 cfg 注入。
        """
        self._on_pet_lock = cb

    def notify_pet_lock(self, on: bool) -> None:
        """跑一次「桌宠固定被切换」的通知（main.py 还没接上时什么也不做）。"""
        if self._on_pet_lock is not None:
            self._on_pet_lock(bool(on))

    def sync_pet_lock(self, on: bool) -> None:
        """从别处（右键菜单）切了「桌宠固定」后，把通用设置里那一行的**滑块**同步过来。

        与 `sync_patpat_mode` 同一套写法：**只同步这一行、不整页重建**。面板若还没建好就跳过。
        """
        row = self._general_setting_row("_lock_row")
        if row is not None:
            row.set_enabled(bool(on), animate=True)

    def set_volume_cb(self, cb):
        """设置「通用设置 → 音量」改动后的回调（main.py 注入）。

        与 `set_mute_mode_cb` 同一个写法：设置页自己已经落过 cfg，这里注册的回调负责
        「让桌宠那条音量条与 TTS 增益跟上」—— 别重复写盘。菜单里那条音量条改音量走的是
        `PetWindow._on_volume`，两条路都收敛到 main 的同一个函数。
        """
        self._on_volume = cb

    def notify_volume(self, value: float) -> None:
        """跑一次「音量被设置页改了」的通知（main.py 还没接上时什么也不做）。"""
        if self._on_volume is not None:
            self._on_volume(float(value))

    def sync_volume(self, value: float) -> None:
        """从别处（桌宠菜单 / 语音）改了音量后，**只同步设置页那一行**。

        与 `sync_mute_mode` 同一套写法：不整页重建 —— 重建会打断正在进行的动画，
        也可能销毁别处正在用的控件。`notify=False` 保证不会回环。
        """
        row = self._general_setting_row("_volume_row")
        if row is not None:
            row.set_value(float(value), notify=False)

    def close_action(self):
        """关闭主界面时的行为：tray=最小化到托盘，quit=关闭软件。"""
        action = (self.cfg.get("general") or {}).get("close_action", "tray")
        return action if action in ("tray", "quit") else "tray"

    def set_current_role(self, key):
        """供 main.py switch_role 调用：更新头像/名字/聊天历史，并触发 _role_change_cb。"""
        if not key or key == self._current_role_key:
            return
        self.cfg["current_role"] = key
        save_config(self.cfg)
        self._set_role(key)
        self._load_chat_history()
        if self._role_change_cb:
            self._role_change_cb(key)

    def get_current_role(self):
        return self._current_role_key

    # ---- 聊天记录（仅内存，重启清空；切换面板/角色保留）----
    def _save_chat_message(self, role_key, role, text):
        hist = self._chat_history.setdefault(role_key, [])
        hist.append({"role": role, "text": text})
        if len(hist) > self._chat_max:
            del hist[: len(hist) - self._chat_max]

    def _load_chat_history(self):
        """从内存加载当前角色的聊天历史到右侧聊天面板。"""
        self._chat_view.clear()
        hist = self._chat_history.get(self._current_role_key, [])
        if not hist:
            self._chat_view.add_system("还没聊天记录，唤醒角色开始对话吧～")
            return
        for m in hist:
            if m["role"] == "assistant":
                role = self.cfg["roles"].get(self._current_role_key, {})
                self._chat_view.add_bubble("assistant", role.get("name", ""), m["text"], role_key=self._current_role_key)
            elif m["role"] == "user":
                self._chat_view.add_bubble("user", "你", m["text"])
            else:
                self._chat_view.add_system(m["text"])

    def mark_quitting(self):
        """标记「正在退出」。

        退出流程里 app.quit() 会让 Qt 关闭所有顶层窗口（从而再次进入 closeEvent）。
        若不标记，closeEvent 会在「关闭软件」分支再次调用退出回调，形成
        closeEvent → quit → closeEvent 的死循环（表现为只关掉了桌宠、主窗口还在且退不掉）。
        """
        self._quitting = True

    def closeEvent(self, event):
        # 关闭行为由「设置 → 通用设置」决定：tray=最小化到托盘（默认）| quit=关闭软件
        # 关键：不要在「关闭软件」分支里 event.ignore()，否则 app.quit() 触发的关闭会被拦下，
        # 再次进入本方法 → 死循环。这里必须放行事件，让窗口真正关闭，退出流程才能走完。
        if self._quitting:
            event.accept()
            return
        if self.close_action() == "quit" and self._quit_app is not None:
            self._quitting = True
            event.accept()
            self._quit_app()
            return
        if self._hide_to_tray:
            event.ignore()
            self.hide()
            self._hide_to_tray()
        else:
            event.accept()

    # ---- 窗口控制（自定义标题栏）----
    def showNormal(self):
        super().showNormal()
