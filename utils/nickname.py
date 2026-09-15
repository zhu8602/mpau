# -*- coding: utf-8 -*-
"""平台真实昵称抓取(登录回填): headless 打开平台主页, 用平台抽取器取昵称并写入账号元数据。

为什么独立成命令: 登录子进程尾部的抓取会被网页端「完成登录」taskkill 打断(先存 Cookie
后抓昵称, 杀进程时抓取还没执行), 所以昵称抓取拆成 `mpau <platform> nickname` 独立命令,
由 Web 在 Cookie 校验通过后后台触发; 昵称只用于展示, 任何失败都静默返回空串。
"""
from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

from patchright.async_api import Page, async_playwright

from utils.base_social_media import set_init_script
from utils.config import LOCAL_CHROME_PATH

# 通用兜底抽取器: 账号区(祖先链含 header/user/account/profile/avatar)里 class 带 name/nick 的短文本
_GENERIC_NICKNAME_JS = """() => {
  const bad = new Set(['首页','内容管理','互动管理','数据中心','收入变现','创作服务','作品发布',
    '视频号助手','发表视频','立即登录','登录']);
  const cands = [...document.querySelectorAll('[class*="name"],[class*="nick"]')];
  for (const el of cands) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 24 || bad.has(t) || t.includes('\\n')) continue;
    let cur = el;
    for (let i = 0; i < 6 && cur; i++) {
      const c = typeof cur.className === 'string' ? cur.className : '';
      if (/header|account|avatar|user|profile/i.test(c)) return t;
      cur = cur.parentElement;
    }
  }
  return '';
}"""


async def generic_nickname(page: Page) -> str:
    """无平台专属抽取器时的通用启发式; 抓不到返回空串。"""
    try:
        return str(await page.evaluate(_GENERIC_NICKNAME_JS) or "").strip()
    except Exception:
        return ""


async def capture_nickname(
    platform: str,
    account_file: str,
    home_url: str,
    extract: Callable[[Page], Awaitable[str]] | None = None,
    wait_ms: int = 3000,
) -> str:
    """headless 打开 home_url, 用 extract(缺省通用启发式)抓昵称并写入 accounts.json。

    专属抽取器落空时自动再试一次通用兜底。全程静默: 任何异常都返回空串。
    """
    nickname = ""
    try:
        async with async_playwright() as playwright:
            if LOCAL_CHROME_PATH:
                browser = await playwright.chromium.launch(headless=True, executable_path=LOCAL_CHROME_PATH)
            else:
                browser = await playwright.chromium.launch(headless=True, channel="chrome")
            try:
                context = await browser.new_context(storage_state=str(account_file))
                context = await set_init_script(context)
                page = await context.new_page()
                await page.goto(home_url, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(wait_ms)
                nickname = ((await (extract or generic_nickname)(page)) or "").strip()
                if not nickname and extract is not None:
                    nickname = await generic_nickname(page)
            finally:
                await browser.close()
    except Exception:
        return ""
    if nickname:
        try:
            from pipeline.account_meta import set_nickname
            set_nickname(platform, Path(account_file).stem, nickname)
        except Exception:
            return ""
    return nickname
