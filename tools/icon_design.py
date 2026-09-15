# -*- coding: utf-8 -*-
"""mpau 图标设计稿渲染: SVG 方案 -> 预览拼图 + 单图 PNG。

用法: .venv/Scripts/python.exe tools/icon_design.py
产物: package/build/icon-preview.png (A/B/C 三方案 x 多尺寸 x 深浅底)
      package/build/icon-A.png / icon-B.png / icon-C.png (1024px 透明底单图)
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from patchright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "package" / "build"
OUT.mkdir(parents=True, exist_ok=True)

TILE_DARK = "#141B2E"   # 深色瓷砖(贴近产品暗色 UI)
GRAD = "url(#g)"        # 品牌紫 -> 蓝渐变

_DEFS = """
<defs>
  <linearGradient id="g" x1="0" y1="1" x2="1" y2="0">
    <stop offset="0" stop-color="#8B7CFF"/>
    <stop offset="1" stop-color="#4CC3FF"/>
  </linearGradient>
  <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#7C6CFF"/>
    <stop offset="1" stop-color="#3FA9F5"/>
  </linearGradient>
</defs>
"""


def _tile(fill: str) -> str:
    return f'<rect x="12" y="12" width="232" height="232" rx="56" fill="{fill}"/>'


# A「一发多收」: 播放键 + 三道广播波(一个视频发全网)
SVG_A = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
{_DEFS}
{_tile(TILE_DARK)}
<path d="M 38 98 A 104 104 0 0 1 218 98" fill="none" stroke="#4CC3FF" stroke-width="15" stroke-linecap="round"/>
<path d="M 60.5 111 A 78 78 0 0 1 195.5 111" fill="none" stroke="#6A8DFF" stroke-width="15" stroke-linecap="round"/>
<path d="M 83 124 A 52 52 0 0 1 173 124" fill="none" stroke="#8B7CFF" stroke-width="15" stroke-linecap="round"/>
<path d="M 108 134 L 108 192 L 170 163 Z" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="14" stroke-linejoin="round"/>
</svg>"""

# B「发布纸飞机」: 渐变瓷砖 + 白色纸飞机(发送/发布)
SVG_B = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
{_DEFS}
{_tile("url(#tile)")}
<path d="M 202 54 L 56 122 L 116 144 L 136 202 Z" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="10" stroke-linejoin="round"/>
<path d="M 118 142 L 198 58" fill="none" stroke="#6E93F7" stroke-width="11" stroke-linecap="round"/>
</svg>"""

# C「上传即播放」: 上传箭头,负形镂空一个播放三角
SVG_C = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
{_DEFS}
{_tile(TILE_DARK)}
<path d="M 92 132 L 128 76 L 164 132 L 146 132 L 146 192 L 110 192 L 110 132 Z"
      fill="{GRAD}" stroke="{GRAD}" stroke-width="12" stroke-linejoin="round"/>
<path d="M 121 142 L 121 164 L 141 153 Z" fill="{TILE_DARK}"/>
</svg>"""

VARIANTS = {"A": SVG_A, "B": SVG_B, "C": SVG_C}
SIZES = (128, 48, 32, 16)


def _sheet_html() -> str:
    rows = []
    for name, svg in VARIANTS.items():
        cells = "".join(
            f'<div class="cell"><div class="ico" style="width:{s}px;height:{s}px">{svg}</div><span>{s}px</span></div>'
            for s in SIZES
        )
        rows.append(f'<div class="row"><div class="name">{name}</div>{cells}</div>')

    def strip(bg: str, label: str) -> str:
        return f'<div class="strip" style="background:{bg}"><h2>{label}</h2>{"".join(rows)}</div>'

    return f"""<!doctype html><meta charset="utf-8"><style>
body {{ margin:0; font-family:'Segoe UI',sans-serif; }}
.strip {{ padding:28px 36px; }}
h2 {{ color:#8a93a8; font-size:13px; font-weight:600; letter-spacing:2px; margin:0 0 14px; }}
.row {{ display:flex; align-items:center; gap:36px; margin-bottom:22px; }}
.name {{ width:28px; font-size:22px; font-weight:700; color:#c8d0e0; }}
.cell {{ display:flex; flex-direction:column; align-items:center; gap:6px; }}
.cell span {{ color:#7a8398; font-size:11px; }}
.ico svg {{ width:100%; height:100%; display:block; }}
</style>
{strip("#0B0F1A", "DARK")}"""


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(device_scale_factor=2)
        # 1) 预览拼图
        await page.set_content(_sheet_html())
        await page.locator("body").screenshot(path=str(OUT / "icon-preview.png"))
        # 2) 单图 1024 透明底
        for name, svg in VARIANTS.items():
            await page.set_viewport_size({"width": 1024, "height": 1024})
            await page.set_content(
                f'<!doctype html><style>html,body{{margin:0}}svg{{width:1024px;height:1024px;display:block}}</style>{svg}'
            )
            await page.locator("svg").screenshot(
                path=str(OUT / f"icon-{name}.png"), omit_background=True
            )
        await browser.close()
    print(f"OK -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
