# -*- coding: utf-8 -*-
"""Vue SPA 快速验证: /single 与 /batch 渲染 + 无 JS 错误 + AI 提示词框存在。"""
import asyncio
import sys

from patchright.async_api import async_playwright

BASE = "http://127.0.0.1:8898/"


async def main():
    errors: list[str] = []
    checks: list[tuple[str, bool]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page(viewport={"width": 1560, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)

        # ---- 单条发布页 ----
        await page.goto(BASE + "single", timeout=30000)
        await page.wait_for_timeout(3000)
        body = await page.locator("body").inner_text()
        checks.append(("single: 标题输入框", await page.locator("input").count() > 0))
        checks.append(("single: AI 提示词标签", "AI 提示词" in body))
        checks.append(("single: 提示词占位符", "约束 LLM" in body or "生成口语化的文案" in body))
        checks.append(("single: 生成按钮", "立即发布" in body))

        # ---- 批量发布页 ----
        await page.goto(BASE + "batch", timeout=30000)
        await page.wait_for_timeout(3500)
        body2 = await page.locator("body").inner_text()
        checks.append(("batch: AI 提示词标签", "AI 提示词" in body2))
        checks.append(("batch: 整批共用提示", "整批共用" in body2))
        checks.append(("batch: 旧文案已移除", "商品卖点/描述" not in body2))
        checks.append(("batch: 一键生成按钮", "一键生成全部文案" in body2))
        checks.append(("batch: 扫描视频清单", "扫描视频清单" in body2))

        await page.screenshot(path="web_vue_check.png", full_page=False)
        await browser.close()

    failed = [c for c in checks if not c[1]] + ([f"JS error: {e}" for e in errors] if errors else [])
    print("=" * 50)
    for c in checks:
        print(("[OK] " if c[1] else "[FAIL] ") + c[0])
    print(f"checks: {len(checks)}, failed: {len(failed)}")
    if failed:
        for f in failed:
            print("  ❌", f)
        sys.exit(1)
    print("ALL PASS")


asyncio.run(main())
