"""渲染「长系统消息把聊天区顶宽 → 用户气泡被裁右边」的修复前后对照图。

产出 `docs/screenshots/chat-system-message-overflow.png`（上=修复前 / 下=修复后）。

★ 修复前那一栏是**把 `ChatView.add_system` 换回旧实现**（不换行的 QLabel）复现出来的，
  所以它是真现象、不是画出来的示意。

跑法（**不要**配 offscreen：offscreen 下没有中文字形回退，文字会渲染成方框）：
    .venv/Scripts/python.exe tools/render_chat_overflow_fix.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QFont, QImage, QPainter, QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QHBoxLayout, QVBoxLayout, QWidget  # noqa: E402

import app.config as cfgmod  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="ignotus_render_chat_"))
cfgmod.CONFIG_PATH = tmp / "config.json"
cfg = cfgmod.load_config()

from app import gui  # noqa: E402

OUT = ROOT / "docs" / "screenshots" / "chat-system-message-overflow.png"
CW, CH = 640, 360

USER_TXT = "进入节能模式"
SYS = ("已进入节能模式：桌宠压扁待机、不再动画，避免挡住其他软件。"
       "说「退出节能模式」或右键桌宠选「节能模式」可恢复。")


def old_add_system(self, text):
    """修复前的实现：QLabel 不换行 + 两侧 stretch（就是被顶宽的那版）。"""
    row = QHBoxLayout()
    row.addStretch(1)
    lbl = QLabel(text)
    lbl.setStyleSheet("color:#64748B; font-size:12px; padding:6px;")
    lbl.setAlignment(Qt.AlignCenter)
    row.addWidget(lbl, 1)
    row.addStretch(1)
    self._append_row(self._wrap(row))


NEW_ADD_SYSTEM = gui.ChatView.add_system


def build(patch_old):
    if patch_old:
        gui.ChatView.add_system = old_add_system
    else:
        gui.ChatView.add_system = NEW_ADD_SYSTEM
    cv = gui.ChatView()
    cv.resize(CW, CH)
    cv.move(-8000, -8000)      # 移出屏幕外：照常完成布局，又不会在用户眼前闪一下
    cv.show()
    for _ in range(3):
        qapp.processEvents()
    cv.add_bubble("user", "你", "今天天气不错，出去走走？")
    cv.add_system(SYS)
    cv.add_bubble("user", "你", USER_TXT)
    for _ in range(5):
        qapp.processEvents()
    return cv


def report(cv):
    vp = cv._scroll.viewport()
    b = cv._container.findChildren(gui._Bubble)[-1]
    x = b.mapTo(vp, QPoint(0, 0)).x()
    return vp.width(), cv._container.width(), x + b.width()


qapp = QApplication.instance() or QApplication(sys.argv)
qapp.setFont(QFont("Microsoft YaHei UI", 10))

shots = []
for patch in (True, False):
    cv = build(patch)
    vw, cw, right = report(cv)
    cut = max(0, right - vw)
    print(f"{'修复前' if patch else '修复后'}: viewport={vw} container={cw} "
          f"用户气泡右边缘={right} 被裁={cut}px")
    if patch:
        cap = (f"修复前：系统消息不换行 → 容器被顶宽 {cw - vw}px"
               f" → 用户气泡右端被裁 {cut}px")
    else:
        cap = (f"修复后：系统消息自动换行 → 容器宽度 {cw} = 视口宽度 {vw}"
               f" → 气泡完整显示（被裁 {cut}px）")
    shots.append((cv.grab(), patch, cap))
    cv.hide()
    cv.deleteLater()
    qapp.processEvents()

gui.ChatView.add_system = NEW_ADD_SYSTEM

# 拼图：上下两栏 + 各自说明
PAD = 22
CAP = 34
W = CW + 2 * PAD
H = 2 * (CAP + CH) + 3 * PAD
canvas = QImage(W, H, QImage.Format_RGB32)
canvas.fill(QColor("#F1F5F9"))
p = QPainter(canvas)
font = QFont("Microsoft YaHei UI", 10)
p.setFont(font)
y = PAD
for pm, is_old, cap in shots:
    p.setPen(QColor("#B91C1C" if is_old else "#15803D"))
    p.drawText(PAD, y + 22, cap)
    y += CAP
    p.drawImage(PAD, y, pm.toImage())
    y += CH + PAD
p.end()
OUT.parent.mkdir(parents=True, exist_ok=True)
canvas.save(str(OUT))
print("OK", OUT, canvas.size())
