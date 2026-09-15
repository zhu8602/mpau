# -*- coding: utf-8 -*-
"""换行专项检测: 窄屏/宽屏下按钮类元素是否内部换行、页面是否横向溢出。"""
import asyncio

from patchright.async_api import async_playwright

BASE = "http://127.0.0.1:8898/"
SEL = ".plat, .chip, .badge, .btn, .check, .seg button, .net-badge, .stat .k, .modal-h h3, " \
      ".tab, .ai-plat, .cand-pill, .batch-accmap .bm, .run-opts .check, .ai-card-h b, " \
      ".cell-top, .cell-top .badge, .batch-table th, .task-actions, .set-sec, " \
      ".tcell .t-v, .tcell .t-k, .tcell .t-s, .counter, .ai-feats span"


async def check(viewport_w, viewport_h):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page(viewport={"width": viewport_w, "height": viewport_h})
        await page.goto(BASE, timeout=30000)
        await page.wait_for_timeout(2200)
        results = await page.evaluate(
            """(sel) => {
              const bad = [];
              document.querySelectorAll(sel).forEach(el => {
                if (el.scrollWidth > el.clientWidth + 1) {
                  bad.push({tag: el.tagName, cls: (el.className||'').toString().slice(0,60), sw: el.scrollWidth, cw: el.clientWidth});
                }
              });
              const docOverflow = document.documentElement.scrollWidth - document.documentElement.clientWidth;
              return {bad, docOverflow};
            }""",
            SEL,
        )
        print(f"[viewport {viewport_w}x{viewport_h}] 内部换行元素: {len(results['bad'])} 个, 页面横向溢出: {results['docOverflow']}px")
        for b in results["bad"]:
            print("   ⚠️", b)
        await browser.close()


async def main():
    await check(1560, 1000)
    await check(900, 900)
    await check(480, 900)
    await check(380, 820)


asyncio.run(main())
