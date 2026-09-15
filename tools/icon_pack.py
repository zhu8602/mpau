# -*- coding: utf-8 -*-
"""把一张 PNG 图标源图处理成发布资产: assets/icon.png(1024 透明) + assets/icon.ico(多尺寸)。

自动完成: 裁掉白边 -> 居中裁方 -> 圆角透明蒙版(去掉瓷砖外的杂色底)。

用法: .venv/Scripts/python.exe tools/icon_pack.py "源图.png"
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def crop_to_content(img: Image.Image, thresh: int = 100) -> Image.Image:
    """按"深色瓷砖"定位并裁剪; 瓷砖外有一圈暗色辉光, bbox 需内缩 2.5% 才能切到瓷砖实体。"""
    gray = ImageOps.grayscale(img)
    mask = gray.point(lambda p: 255 if p < thresh else 0)
    bbox = mask.getbbox()
    if not bbox:
        return img
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    ix, iy = int(w * 0.025), int(h * 0.025)
    return img.crop((bbox[0] + ix, bbox[1] + iy, bbox[2] - ix, bbox[3] - iy))


def square_center(img: Image.Image) -> Image.Image:
    side = min(img.width, img.height)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    return img.crop((left, top, left + side, top + side))


def round_corners(img: Image.Image, radius_ratio: float = 0.15) -> Image.Image:
    """圆角蒙版: 圆角外变透明, 边缘 4x 超采样抗锯齿。"""
    side = img.width
    scale = 4
    mask = Image.new("L", (side * scale, side * scale), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(side * radius_ratio * scale)
    draw.rounded_rectangle((0, 0, side * scale - 1, side * scale - 1), radius=radius, fill=255)
    mask = mask.resize((side, side), Image.LANCZOS)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def main() -> int:
    src = Path(sys.argv[1])
    img = Image.open(src).convert("RGBA")
    img = square_center(crop_to_content(img))
    img = img.resize((1024, 1024), Image.LANCZOS)
    icon = round_corners(img)

    ASSETS.mkdir(exist_ok=True)
    png_out = ASSETS / "icon.png"
    ico_out = ASSETS / "icon.ico"
    icon.save(png_out)
    icon.save(ico_out, sizes=ICO_SIZES)
    print(f"OK -> {png_out} (1024px)")
    print(f"OK -> {ico_out} ({len(ICO_SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
