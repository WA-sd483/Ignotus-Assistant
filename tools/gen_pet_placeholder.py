"""生成桌宠占位图：每角色 × 每状态 × 2 帧 PNG + 应用图标，256×256 透明背景。"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent

ROLES = {
    "alice": {"accent": (55, 138, 221, 255), "cheek": (181, 212, 244, 255)},   # 淡蓝
    "ellen": {"accent": (226, 51, 118, 255), "cheek": (248, 187, 208, 255)},   # 玫红
}

STATES = ["idle", "listening", "thinking", "speaking", "working"]


def draw_frame(accent, cheek, state, frame):
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 头
    d.ellipse([40, 40, 216, 216], fill=(255, 255, 255, 255), outline=accent, width=10)

    # 眼睛
    ey = 110
    if state == "idle" and frame == 1:
        d.line([86, ey, 110, ey], fill=accent, width=8)
        d.line([146, ey, 170, ey], fill=accent, width=8)
    elif state == "thinking":
        d.ellipse([86, ey - 8, 110, ey + 8], fill=accent)
        d.ellipse([146, ey - 8, 170, ey + 8], fill=accent)
        d.ellipse([108, 48, 120, 60], fill=accent)
        d.ellipse([128, 42, 140, 54], fill=accent)
        d.ellipse([148, 38, 160, 50], fill=accent)
    else:
        d.ellipse([86, ey - 6, 110, ey + 6], fill=accent)
        d.ellipse([146, ey - 6, 170, ey + 6], fill=accent)

    # 嘴
    my = 158
    if state == "speaking":
        if frame == 0:
            d.ellipse([116, my, 140, my + 24], fill=accent)
        else:
            d.ellipse([110, my - 2, 146, my + 32], fill=accent)
    elif state == "listening":
        d.arc([116, my - 4, 140, my + 18], 0, 180, fill=accent, width=6)
    elif state == "working":
        d.line([108, my + 6, 148, my + 6], fill=accent, width=6)
    else:
        d.arc([116, my - 4, 140, my + 14], 0, 180, fill=accent, width=6)

    # 脸颊
    d.ellipse([68, 138, 90, 156], fill=cheek)
    d.ellipse([166, 138, 188, 156], fill=cheek)
    return img


def main():
    count = 0
    for role_key, pal in ROLES.items():
        for state in STATES:
            out_dir = ROOT / "pet" / role_key / state
            out_dir.mkdir(parents=True, exist_ok=True)
            for frame in (0, 1):
                img = draw_frame(pal["accent"], pal["cheek"], state, frame)
                img.save(out_dir / f"{frame + 1:04d}.png")
                count += 1

    # 应用图标（用于系统托盘）
    icons = ROOT / "assets" / "icon"
    icons.mkdir(parents=True, exist_ok=True)
    icon = draw_frame(ROLES["alice"]["accent"], ROLES["alice"]["cheek"], "idle", 0)
    icon = icon.resize((128, 128), Image.Resampling.LANCZOS)
    icon.save(icons / "app_icon.png")

    print(f"占位图生成完成，共 {count} 张 + 应用图标 1 张")


if __name__ == "__main__":
    main()
