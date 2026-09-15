# -*- coding: utf-8 -*-
"""截取 v2 设计的两页截图供视觉审阅。"""
import asyncio

from patchright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page(viewport={"width": 1560, "height": 1000}, device_scale_factor=1.5)
        await page.goto("http://127.0.0.1:8898/", timeout=30000)
        await page.wait_for_timeout(2600)
        await page.screenshot(path="design_v2_publish.png")
        await page.locator('.tab[data-tab="batch"]').click()
        await page.wait_for_timeout(900)
        await page.screenshot(path="design_v2_batch.png")
        await browser.close()


asyncio.run(main())
