"""生成「桌宠节能形态」变形预览图（对照 pet.py 的真实算式，非另写一套）。

用途：把 0.6s 变形按进度采样成一排静态帧，方便人眼核对「压扁 / 淡到 30% 换图 / 升回」
三个动作是否就是需求描述的样子。产出一张 PNG，供文档引用。

★ 这里的算尺寸 / 算不透明度**照抄 `app/pet.py`**（`_normal_size` / `_power_save_size` /
`_ps_apply`），改源码时一起改这里，避免预览与实现分叉。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DISPLAY_HEIGHT = 250          # 与 pet.py 一致：站姿高钉死
SWAP = 0.30                   # 与 pet.POWER_SAVE_SWAP_OPACITY 一致
IDLE = ROOT / "pet" / "alice" / "idle"
STAND = IDLE / "爱丽丝_休息.png"
ECO = IDLE / "爱丽丝_节能.png"
OUT = ROOT / "docs" / "screenshots" / "pet-power-save-morph.png"
OUT_GIF = ROOT / "docs" / "screenshots" / "pet-power-save-morph.gif"

BG = (255, 255, 255)
PANEL = (230, 241, 251)       # #E6F1FB
INK = (51, 65, 85)            # #334155
BLUE = (55, 138, 221)         # #378ADD
LINE = (125, 211, 252)        # #7DD3FC


def _font(size):
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def sizes():
    """照抄 pet.py：站姿=高钉 250；节能=宽与站姿同、高按图自身比例。"""
    st = Image.open(STAND)
    ec = Image.open(ECO)
    nw = max(1, round(st.width * DISPLAY_HEIGHT / st.height))
    nw, nh = nw, DISPLAY_HEIGHT
    ew = nw                                     # 宽度与站姿相同
    eh = max(1, round(ew * ec.height / ec.width))
    return (nw, nh), (ew, eh)


def apply_fn(from_h, mid_h, to_h):
    """照抄 pet.py::_ps_apply —— 返回 (高, 不透明度, 是否已换图)。"""
    def f(p):
        if p <= 0.5:
            u = p / 0.5
            h = round(from_h + (mid_h - from_h) * u)
            op = 1.0 + (SWAP - 1.0) * u
            swapped = False
        else:
            v = (p - 0.5) / 0.5
            h = round(mid_h + (to_h - mid_h) * v)
            op = SWAP + (1.0 - SWAP) * v
            swapped = True
        if p >= 1.0:
            h, op, swapped = to_h, 1.0, True
        return h, op, swapped
    return f


def stage_sprite(p, fn, stand, eco):
    h, op, swapped = fn(p)
    src = eco if swapped else stand
    w = stand.width if not swapped else eco.width
    # QLabel.setScaledContents(True)：贴图被拉伸到窗口 geometry（所以是「压扁」不是「缩小」）
    w = SIZES[0][0]
    img = src.convert("RGBA").resize((w, max(1, h)), Image.LANCZOS)
    if op < 1.0:
        a = img.getchannel("A").point(lambda v: int(v * op))
        img.putalpha(a)
    return img, h, op, swapped


def main():
    global SIZES
    normal, eco_size = sizes()
    SIZES = (normal, eco_size)
    nw, nh = normal
    ew, eh = eco_size
    stand = Image.open(STAND).convert("RGBA")
    eco = Image.open(ECO).convert("RGBA")

    fn = apply_fn(nh, eh, eh)                   # 进入节能：站姿高 → 节能高 → 节能高
    samples = [(0.0, "p=0.00"), (0.25, "p=0.25"), (0.5, "p=0.50"),
               (0.5 + 1e-6, "p=0.50+ 刚换图"), (0.75, "p=0.75"), (1.0, "p=1.00")]

    PAD = 26
    CAP = 44
    GAP = 22
    TOP = 40
    FLOOR_PAD = 46                              # 底线下方留白（画底边参考线）
    panel_w = nw + 2 * PAD
    panel_h = nh + TOP + FLOOR_PAD
    W = len(samples) * panel_w + (len(samples) - 1) * GAP + 2 * GAP
    H = 118 + panel_h + 78
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    f_title = _font(24)
    f_sub = _font(15)
    f_cap = _font(15)
    f_small = _font(13)

    d.text((GAP, 20), "桌宠节能形态：原地压扁 + 淡出换图（总时长 0.6s）", font=f_title, fill=INK)
    d.text((GAP, 54),
           f"站姿 {nw}×{nh}  →  节能 {ew}×{eh}（宽不变、高度只剩约 40%；底边全程不动）",
           font=f_sub, fill=BLUE)
    d.text((GAP, 76),
           "不透明度降到 30% 的那一刻才换图 —— 此刻仍是 30%，之后再升回 100%",
           font=f_sub, fill=(100, 116, 139))

    y0 = 118
    for i, (p, label) in enumerate(samples):
        x0 = GAP + i * (panel_w + GAP)
        d.rounded_rectangle([x0, y0, x0 + panel_w, y0 + panel_h], 14,
                            fill=PANEL, outline=LINE, width=1)
        img, h, op, swapped = stage_sprite(p, fn, stand, eco)
        # 底边固定：贴图底 = 面板底 − FLOOR_PAD
        foot = y0 + panel_h - FLOOR_PAD
        px = x0 + (panel_w - nw) // 2
        canvas.paste(img, (px, foot - h), img)
        # 底线参考线
        d.line([x0 + 12, foot, x0 + panel_w - 12, foot], fill=LINE, width=1)

        d.text((x0 + 14, y0 + 12), label, font=f_cap, fill=INK)
        tag = "节能图" if swapped else "站姿图"
        d.text((x0 + 14, y0 + 32), f"{tag} · 高{h} · 透明{round(op*100)}%",
               font=f_small, fill=BLUE if swapped else (100, 116, 139))

    # 底部图例
    ly = y0 + panel_h + 18
    d.line([GAP, ly + 8, GAP + 46, ly + 8], fill=(203, 213, 225), width=2)
    d.text((GAP + 56, ly), "面板底线 = 桌宠底边（切换前后不动）", font=f_small,
           fill=(100, 116, 139))
    d.text((GAP, ly + 30),
           "说明：贴图被拉伸填满窗口（setScaledContents），所以视觉上是「压扁」而非等比缩小；"
           "预览按 pet.py 的同款算式逐帧复算。",
           font=f_small, fill=(148, 163, 184))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT)
    print(f"OK {OUT} {canvas.size}")

    make_gif(fn, stand, eco, nw, panel_w)


def make_gif(fn, stand, eco, nw, panel_w):
    """把 0.6s 变形按 30fps 转成一版 GIF（底边固定，直观看到「原地压扁」）。"""
    FPS = 30
    N = round(600 / 1000 * FPS)                 # 18 帧
    W = nw + 60
    H = 250 + 60
    foot = H - 26
    frames = []
    for i in range(N + 1):
        p = i / N
        img, h, op, swapped = stage_sprite(p, fn, stand, eco)
        fr = Image.new("RGB", (W, H), (247, 250, 252))
        d = ImageDraw.Draw(fr)
        d.line([10, foot, W - 10, foot], fill=LINE, width=1)
        px = (W - nw) // 2
        fr.paste(img, (px, foot - h), img)      # 底边固定 → 原地压扁
        frames.append(fr.quantize(colors=128, dither=Image.NONE))
    frames[0].save(OUT_GIF, save_all=True, append_images=frames[1:],
                   duration=int(1000 / FPS), loop=0, disposal=2)
    print(f"OK {OUT_GIF} {frames[0].size} × {len(frames)}帧")


SIZES = ((150, 250), (150, 100))

if __name__ == "__main__":
    main()
