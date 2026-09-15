# -*- coding: utf-8 -*-
"""把 style.v2.css 的内容替换进 index.html 的 <style> 块。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html_path = ROOT / "web" / "templates" / "index.html"
css_path = ROOT / "web" / "templates" / "style.v2.css"

html = html_path.read_text(encoding="utf-8")
css = css_path.read_text(encoding="utf-8")

new_html, n = re.subn(
    r"<style>.*?</style>",
    "<style>\n" + css.strip() + "\n</style>",
    html,
    count=1,
    flags=re.S,
)
if n != 1:
    raise SystemExit("未找到 <style> 块")

html_path.write_text(new_html, encoding="utf-8")
print(f"spliced {len(css)} bytes of CSS into {html_path.name}")
