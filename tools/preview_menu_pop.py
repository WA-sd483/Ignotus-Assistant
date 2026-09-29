"""生成「桌宠右键弹窗弹出」的逐帧预览图（真机渲染，`docs/screenshots/pet-menu-pop.png`）。

为什么需要它：弹窗的弹出动画**只有真机能看清**（`Qt.Popup` 在 Windows 上不是分层窗口，屏幕级截帧会被
合成延迟骗到；探针也没法模拟「右键 + 悬停」）。这里退一步：直接把动画**冻在若干进度上**、调真
`paintEvent` 画出来 `grab()`，再按窗口 region（mask）裁掉「屏幕上其实看不到」的部分 ——
得到的就是**真机上那一帧的样子**。

用法（项目根目录，**必须真机**，离屏没有中日韩字形）：
    .venv\\Scripts\\python.exe tools\\preview_menu_pop.py

对齐的口径（2026-09-19 十四改）：
  * 一级弹窗：0.3s 里**只动不透明度**（0 → 1），尺寸**全程不变**（八改～十三改那套「50% → 100%
    缩放」已整条删除，用户口径「不再进行大小上的变化，只要求右键淡入（仅不透明度提高）」）；
  * 淡入的**底** = `pop_up()` 时抓来的**真桌面**（与淡出同一条路）→ 合成 = `α×菜单 + (1−α)×真桌面`。
    所以逐帧图会看到「菜单从背后的桌面里渐渐浮出来」；抓不到桌面（离屏 / 无权限）时兜底铺菜单底色，
    那种情况下 α 很小时几乎看不出变化 —— 这是**预期**的（真机上一定有桌面）；
  * 一级弹窗最顶上那条音量条：动画期间由 `render()` 画，**背景必须一直是菜单底色**（不能是黑）；
  * ⚠️ 裁剪仍按**真机那一帧的 region**：十四改起 region 恒等于整个面板（不再逐帧变），所以这一步
    现在等价于不裁 —— 但保留它，一旦将来 region 又跟面板对不上，预览图会第一时间把多出来的部分露出来。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import pet as petmod  # noqa: E402

OUT = ROOT / "docs" / "screenshots" / "pet-menu-pop.png"

SAMPLES = (0.0, 0.15, 0.30, 0.50, 0.70, 1.0)     # 采样不透明度（十四改：唯一在动的量）
PAD = 18                                          # 每格四周留白
GAP = 10                                          # 格间距
CELL_BG = (241, 245, 249)                         # #F1F5F9：浅色格底，正好模拟「背后是浅色界面」
CELL_EDGE = (203, 213, 225)                       # #CBD5E1
INK = (51, 65, 85)                                # #334155
TITLE_BG = (230, 241, 251)                        # #E6F1FB


def _font(size):
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def to_pil(pm):
    """QImage 内存是 BGRA 小端 —— 先转 RGBA8888 再读，否则红蓝互换。"""
    img = pm.toImage().convertToFormat(QImage.Format_RGBA8888)
    return Image.frombytes("RGBA", (img.width(), img.height()), bytes(img.constBits()))


def main():
    app = QApplication.instance() or QApplication([])

    pet = petmod.PetWindow(ROOT / "pet" / "alice")
    pet.move(700, 300)
    pet.show()
    app.processEvents()
    pet.set_roles([("爱丽丝", "alice"), ("Ellen", "ellen")])
    pet.set_current_role("alice")

    menu = pet._build_menu()
    size = menu.sizeHint()
    rect = QRect(pet.mapToGlobal(QPoint(12, 24)), size)
    menu.pop_up(rect, "right")
    app.processEvents()
    menu._stop_anim()                     # 冻住，下面每帧手工给不透明度

    frames = []
    dpr = 1.0
    for t in SAMPLES:
        menu._on_in_frame(t)
        app.processEvents()
        pm = menu.grab()
        dpr = pm.width() / float(menu.width())
        img = to_pil(pm)
        # 按**真机那一帧的 region** 裁：region 之外的像素在屏幕上不属于本窗口（被 `setMask()` 切掉）。
        # 十四改起 region 恒等于整个面板，所以这一步现在等价于不裁 —— 保留它当护栏。
        r = menu.mask().boundingRect()
        img = img.crop((int(round(r.x() * dpr)), int(round(r.y() * dpr)),
                        int(round((r.x() + r.width()) * dpr)),
                        int(round((r.y() + r.height()) * dpr))))
        frames.append((t, img))

    w_cell = max(f.width for _, f in frames)
    h_cell = max(f.height for _, f in frames)
    head = 74
    W = PAD + len(frames) * (w_cell + GAP) - GAP + PAD
    H = head + PAD + h_cell + 30 + PAD

    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 0, W, head), fill=TITLE_BG)
    d.text((PAD, 12), "桌宠右键弹窗 · 淡入逐帧（真机渲染，0.3s：只改不透明度 0 → 100%，尺寸不变）",
           font=_font(19), fill=INK)
    d.text((PAD, 40), "每格都是「按真机那一帧的 region 裁过」的画面：菜单从背后的**真桌面**里浮出来"
                      "（α×菜单 + (1−α)×桌面），尺寸每格都一样大；"
                      "音量条那行背景全程是菜单底色，不是黑。",
           font=_font(14), fill=(100, 116, 139))

    for i, (t, img) in enumerate(frames):
        x = PAD + i * (w_cell + GAP)
        y = head + PAD + (h_cell - img.height)            # 十四改起每格一样大，这里恒等于顶对齐
        d.rectangle((x - 1, head + PAD - 1, x + w_cell, head + PAD + h_cell), fill=CELL_BG,
                    outline=CELL_EDGE)
        canvas.paste(img, (x, y), img)
        d.text((x, head + PAD + h_cell + 6),
               f"α={t:.2f}  不透明度 {t:.0%}"
               f"  可见区 {img.width}×{img.height}px",
               font=_font(13), fill=INK)

    canvas.save(OUT)
    print(f"saved {OUT}  {canvas.width}x{canvas.height}  frames={len(frames)}  "
          f"dpr={dpr:.2f}  末帧可见区={frames[-1][1].size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
