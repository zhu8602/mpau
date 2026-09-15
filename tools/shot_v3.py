# -*- coding: utf-8 -*-
"""截取合并后的发布工作台(手动模式 + AI 模式)截图供视觉审阅。"""
import asyncio

from patchright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page(viewport={"width": 1560, "height": 1150}, device_scale_factor=1.5)
        await page.goto("http://127.0.0.1:8898/", timeout=30000)
        await page.wait_for_timeout(2600)
        await page.screenshot(path="design_v3_manual.png")
        await page.locator('#modeSeg button[data-mode="ai"]').click()
        await page.wait_for_timeout(500)
        await page.screenshot(path="design_v3_ai.png")
        await browser.close()


asyncio.run(main())
