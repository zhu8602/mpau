# -*- coding: utf-8 -*-
"""用 patchright(Playwright 兼容 API)在页面主世界验证 UI 完整性(单条发布 + AI 多样发布 + 批量发布 + 设置)。"""
import asyncio
import sys

import requests

from patchright.async_api import async_playwright

BASE = "http://127.0.0.1:8898/"


def api(path, method="GET", body=None):
    if method == "POST":
        return requests.post(BASE + path, json=body or {}, timeout=60)
    return requests.get(BASE + path, timeout=60)


async def main():
    errors = []
    checks = []

    def ok(name, value):
        checks.append((name, value))
        print(f"[OK] {name}: {value}")

    # 切换 mock 模型, 测试 AI 生成 UI
    api("api/settings", "POST", {"llm": {"model": "mock"}, "scheduler": {}})

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page(viewport={"width": 1560, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in ("error",) else None)
        await page.goto(BASE, timeout=30000)
        await page.wait_for_timeout(2500)

        # ---- 原有基础检查 ----
        ok("1. typeof toast", await page.evaluate("typeof toast"))
        ok("2. typeof pollTasks", await page.evaluate("typeof pollTasks"))
        ok("3. platforms", await page.locator(".plat").count())
        ok("4. stats", await page.locator(".stat").count())
        ok("5. platform_pills_initial_active", await page.locator(".plat.active").get_attribute("data-p"))

        await page.locator('.plat[data-p="kuaishou"]').click()
        await page.wait_for_timeout(500)
        ok("6. after switch active", await page.locator(".plat.active").get_attribute("data-p"))
        ok("7. pub hint", (await page.locator("#pubPlatHint").inner_text()).strip())

        # 文件浏览弹窗(手动/图文已移除, 视频文件浏览保留)
        await page.locator("#btnBrowse").click()
        await page.wait_for_timeout(800)
        ok("8. file modal open", await page.locator("#fileModal").evaluate("el => el.classList.contains('show')"))
        ok("9. file rows", await page.locator(".file-row").count())
        await page.locator('.modal-x[data-close="fileModal"]').click()

        await page.evaluate('toast("测试通知", "ok")')
        await page.wait_for_timeout(400)
        ok("11. toast shown", await page.locator("#toast-wrap .toast").count())

        # 任务列表(有历史任务时显示任务, 否则空态)
        task_text = await page.locator("#taskList").inner_text()
        ok("12. task list rendered", bool(task_text.strip()))
        await page.wait_for_timeout(3200)
        ok("13. poll cycle ok, js errors", errors if errors else "none")

        # ---- 设计稿新增: 今日数据看板 / 字数计数 / 常用模板 / 去发布 ----
        await page.wait_for_timeout(300)
        stats_text = await page.locator(".today-grid").inner_text()
        ok("13b. today stats card", "今日发布" in stats_text and "成功率" in stats_text)
        has_tasks = await page.locator("#taskList .task-item").count() > 0
        go_btn = await page.locator("#btnGoPublish").count()
        if has_tasks:
            ok("13c. go publish btn", "skipped (task list non-empty, 去发布只在空态渲染)")
        else:
            ok("13c. go publish btn", go_btn)
        await page.locator("#fTitle").fill("标题测试")
        ok("13d. title counter", (await page.locator("#fTitleCnt").inner_text()).endswith("/55"))
        await page.locator("#fDesc").fill("描")
        ok("13e. desc counter", (await page.locator("#fDescCnt").inner_text()).endswith("/500"))
        await page.locator("#fTitle").fill("")
        ok("13f. template select", "常用模板" in await page.locator("#tplSel").inner_text())
        ok("13g. ai feats", await page.locator(".ai-feats span").count())
        ok("13h. ai preview btn", await page.locator("#btnAiPreview").count())

        # ---- AI 多样发布(手动发布已移除, AI 区常驻) ----
        ok("14. ai platform pills", await page.locator(".ai-plat").count())
        ok("14b. ai controls visible", await page.locator("#aiPlats").is_visible())
        await page.locator("#fFile").fill("D:\\videos\\demo.mp4")
        await page.locator("#fTitle").fill("新品实测真的好用")
        await page.locator("#btnAiGen").click()
        await page.wait_for_timeout(4000)
        ok("15. ai result cards", await page.locator(".ai-card").count())
        ok("16. ai cand pills", await page.locator(".ai-card .cand-pill").count())
        ok("17. ai title filled", await page.locator('.ai-card[data-p="douyin"] .ai-t').input_value())
        # 切换候选
        await page.locator('.ai-card[data-p="xiaohongshu"] .cand-pill').nth(1).click()
        await page.wait_for_timeout(600)
        ok("18. xhs cand switched", await page.locator('.ai-card[data-p="xiaohongshu"] .ai-t').input_value())
        ok("18b. ai gen btn enabled", not await page.locator("#btnAiGen").is_disabled())

        # ---- 批量发布 Tab ----
        await page.locator('.tab[data-tab="batch"]').click()
        await page.wait_for_timeout(600)
        ok("19. batch tab visible", await page.locator("#tab-batch").is_visible())
        ok("20. account map selects", await page.locator(".batch-accmap select").count())
        ok("21. batch controls", await page.locator("#btnBatchGen").count())
        # 已有批次则看审阅矩阵; 否则验证空态(数据无关, 干净机器也可跑)
        batch_ids = api("api/batch/batches").json().get("batches", [])
        ok("22. batches listed", len(batch_ids) >= 0)  # 恒真, 仅记录数量
        print(f"      -> batches: {len(batch_ids)}")
        if batch_ids:
            await page.locator("#batchSel").select_option(batch_ids[0]["batch_id"])
            await page.wait_for_timeout(1200)
            # 视频表已移除: 有视频时显示扫描信息条; 审阅表行数 = 条目数(n×m)
            bv = api("api/batch/videos?batch_id=" + batch_ids[0]["batch_id"]).json().get("videos", [])
            items = api("api/batch/items?batch_id=" + batch_ids[0]["batch_id"]).json().get("items", [])
            ok("23. scan info strip", (await page.locator("#batchVideosInfo").is_visible()) == (len(bv) > 0))
            ok("24. review rows (n×m)", await page.locator("#reviewBody tr").count() == len(items))
            ok("25. status badges", await page.locator("#reviewBody .badge").count() == len(items))
            ok("26. batch progress box", bool((await page.locator("#batchProgress").inner_text()).strip()))
        else:
            batch_videos = api("api/batch/videos").json().get("videos", [])
            if batch_videos:
                ok("23-26. batch empty state (no batches)", "skipped (batch tab has scanned videos)")
            else:
                ok("23-26. batch empty state (no batches)", "暂无批次" in await page.locator("#tab-batch").inner_text() or
                   await page.locator("#batchEmpty").is_visible())

        # ---- 设置弹窗 ----
        await page.locator("#btnSettings").click()
        await page.wait_for_timeout(700)
        ok("27. settings modal open", await page.locator("#settingsModal").evaluate("el => el.classList.contains('show')"))
        ok("28. settings base_url", await page.locator("#setBaseUrl").input_value())
        await page.locator('.modal-x[data-close="settingsModal"]').click()

        await page.screenshot(path="web_ui_preview.png", full_page=False)
        ok("29. screenshot saved", "web_ui_preview.png")
        await browser.close()

    # 恢复真实模型配置
    api("api/settings", "POST", {"llm": {"model": "deepseek-chat"}, "scheduler": {}})

    failed = [c for c in checks if not c[1]] + ([f"JS error: {e}" for e in errors] if errors else [])
    print("=" * 50)
    print(f"checks: {len(checks)}, failed: {len(failed)}")
    if failed:
        for f in failed:
            print("  ❌", f)
        sys.exit(1)
    print("ALL PASS")


asyncio.run(main())
