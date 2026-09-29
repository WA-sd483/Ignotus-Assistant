"""音量条控件：**桌宠右键菜单**与**通用设置 → 音量**共用一份实现（2026-09-19）。

沿革：音量条原来只活在 `pet.py` 里（单击贴图 → 在小人下方弹出来）。这一轮它搬进了桌宠的
右键菜单，同时通用设置的「桌宠调整」分组也多了一行音量 —— 两处必须长得一样、还要互相同步，
所以把共用的那颗滑块与那颗圆形微调按钮抽到这里。

⚠️ **不要**让 `pet.py` 与 `gui.py` 互相 import（`gui` 是主界面，反过来的依赖会把它拖进桌宠模块）。
两边都 import 本模块即可 —— 本模块只依赖 PySide6，不依赖项目里任何别的模块。

规格（`design.md` 4.10 / 4.13）：
  * 轨道 6px、圆角 3px、底色 `#E6F1FB`；已填充 `#378ADD`；圆钮 14px 白底 + `1px #378ADD` 边框。
  * 静音时**只换颜色**（已填充 / 圆钮边框变灰 `#DCDCDC`），滑块位置不动。
  * 音量条本身**没有容器边框** —— 桌宠菜单里那个白底圆角盒是 `pet._VolumeBar` 自己画的壳。
"""
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSlider

# ---- 滑块（轨道 / 已填充 / 圆钮）----
TRACK_H = 6          # 轨道高
HANDLE_D = 14        # 圆钮直径
RADIUS = 3           # 轨道与已填充的圆角（2 倍就够画成胶囊）
FILL = "#378ADD"     # 已填充部分（主蓝）
GROOVE = "#E6F1FB"   # 轨道底色（浅蓝）
MUTED = "#DCDCDC"    # 静音时的灰（已填充 + 圆钮边框）

# ---- 圆形微调按钮（只给「通用设置 → 音量」用）----
STEP_D = 22          # 按钮直径
STEP_GLYPH = "#378ADD"   # 中间那道 `−` / `+` 的颜色（主蓝）
STEP_BG = "#FFFFFF"      # 静止底色 = 界面底色（行底是白的，静止时与行底融为一体）
STEP_HOVER = "#E6F1FB"   # hover 底色（浅蓝）
STEP_FADE_MS = 200       # hover 变色时长（与全项目 hover 渐变同一档）


def slider_qss(muted=False):
    """滑块的三行 QSS。

    `muted=True` 时已填充部分与圆钮边框一起变灰 —— 与旧实现逐字一致，
    只是从 `pet._update_slider_style()` 搬到这里，好让设置页那颗也吃同一套。
    """
    sub = MUTED if muted else FILL
    edge = MUTED if muted else FILL
    return (
        f"QSlider::groove:horizontal {{ height:{TRACK_H}px; background:{GROOVE};"
        f" border-radius:{RADIUS}px; }}"
        f"QSlider::sub-page:horizontal {{ background:{sub}; border-radius:{RADIUS}px; }}"
        f"QSlider::handle:horizontal {{ width:{HANDLE_D}px; height:{HANDLE_D}px; margin:-4px 0;"
        f" border-radius:{HANDLE_D // 2}px; background:#FFFFFF; border:1px solid {edge}; }}"
    )


class VolumeSlider(QSlider):
    """横向音量滑块（0~100）。**自身不带边框**，皮肤全部由 `slider_qss()` 给。

    用 `set_muted()` 换色而不是换控件：静音只是「听不见」，滑块该停在哪儿还停在哪儿
    （拖动一下自动解除静音的逻辑在调用方，见 `pet` / 通用设置）。
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setRange(0, 100)
        self._muted = False
        self.setStyleSheet(slider_qss(False))

    def set_muted(self, muted: bool) -> None:
        muted = bool(muted)
        if muted == self._muted:
            return
        self._muted = muted
        self.setStyleSheet(slider_qss(muted))

    def is_muted(self) -> bool:
        return self._muted


class VolumeStepButton(QAbstractButton):
    """音量微调按钮：直径 22px 的**圆形**，`−` / `+` 由 `sign` 决定。

    用户口径（2026-09-19）：**无边框、底色与界面底色一致**，鼠标移入 / 移出时**颜色渐变**。
    所以底色从 `STEP_BG` 插值到 `STEP_HOVER`（200ms 线性）。

    ⚠️ **必须自绘 + `QVariantAnimation`**：QSS 的 `:hover` 不支持过渡（design.md §5 的实现约定），
    而它所在的那一行行高钉死 58px —— `setStyleSheet` 每帧重算会闪。
    """

    def __init__(self, sign: int = 1, parent=None):
        super().__init__(parent)
        self.sign = 1 if sign > 0 else -1
        self._t = 0.0                       # 0 = 静止底色，1 = hover 底色
        self.setFixedSize(STEP_D, STEP_D)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("音量加" if self.sign > 0 else "音量减")
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(STEP_FADE_MS)
        self._anim.setEasingCurve(QEasingCurve.Linear)
        self._anim.valueChanged.connect(self._set_t)

    # ---- hover 渐变 ----
    def _set_t(self, value):
        self._t = float(value)
        self.update()

    def _animate_to(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(float(target))
        self._anim.start()

    def enterEvent(self, e):  # noqa: N802 (Qt 命名)
        super().enterEvent(e)
        self._animate_to(1.0)

    def leaveEvent(self, e):  # noqa: N802 (Qt 命名)
        super().leaveEvent(e)
        self._animate_to(0.0)

    # ---- 自绘 ----
    @staticmethod
    def _blend(c1, c2, t):
        a, z = QColor(c1), QColor(c2)
        return QColor(round(a.red() + (z.red() - a.red()) * t),
                      round(a.green() + (z.green() - a.green()) * t),
                      round(a.blue() + (z.blue() - a.blue()) * t))

    def paintEvent(self, _e):  # noqa: N802 (Qt 命名)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        d = STEP_D
        p.setPen(Qt.NoPen)                       # 无边框：只填圆底
        p.setBrush(self._blend(STEP_BG, STEP_HOVER, self._t))
        p.drawEllipse(QRectF(0.0, 0.0, d, d))
        # `−`：一条横线；`+`：再叠一条竖线。线宽 2px、圆头，长 10px。
        arm = 10.0
        c = d / 2.0
        pen = QPen(QColor(STEP_GLYPH), 2.0)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(c - arm / 2.0, c), QPointF(c + arm / 2.0, c))
        if self.sign > 0:
            p.drawLine(QPointF(c, c - arm / 2.0), QPointF(c, c + arm / 2.0))
