# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import inspect
import os
from datetime import datetime
from pathlib import Path

from patchright.async_api import Page
from patchright.async_api import Playwright
from patchright.async_api import async_playwright

from utils.config import DEBUG_MODE, LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH, MPAU_HOME
from uploader.base_video import BaseVideoUploader
from utils.base_social_media import set_init_script
from utils.files_times import get_absolute_path
from utils.login_qrcode import build_login_qrcode_path
from utils.login_qrcode import decode_qrcode_from_path
from utils.login_qrcode import print_terminal_qrcode
from utils.login_qrcode import remove_qrcode_file
from utils.login_qrcode import save_data_url_image
from utils.log import kuaishou_logger

KUAISHOU_UPLOAD_URL = "https://cp.kuaishou.com/article/publish/video"
KUAISHOU_MANAGE_URL = "https://cp.kuaishou.com/article/manage/video?status=2&from=publish"
KUAISHOU_LOGIN_URL = "https://passport.kuaishou.com/pc/account/login/?sid=kuaishou.web.cp.api&callback=https%3A%2F%2Fcp.kuaishou.com%2Frest%2Finfra%2Fsts%3FfollowUrl%3Dhttps%253A%252F%252Fcp.kuaishou.com%252Farticle%252Fpublish%252Fvideo%26setRootDomain%3Dtrue"
KUAISHOU_UPLOAD_URL_PATTERN = "**/article/publish/video**"
KUAISHOU_MANAGE_URL_PATTERN = "**/article/manage/video?status=2&from=publish**"
KUAISHOU_COOKIE_INVALID_SELECTOR = "div.names div.container div.name:text('机构服务')"
KUAISHOU_PUBLISH_STRATEGY_IMMEDIATE = "immediate"
KUAISHOU_PUBLISH_STRATEGY_SCHEDULED = "scheduled"


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


def _print_ks_qrcode(qrcode_content: str, qrcode_path: Path) -> None:
    try:
        print_terminal_qrcode(qrcode_content, qrcode_path, "快手APP", compact=False, border=2)
    except TypeError as exc:
        if "unexpected keyword argument 'compact'" not in str(exc):
            raise
        kuaishou_logger.warning(_msg("😵", "检测到旧版二维码打印函数，小人切回兼容模式继续登录"))
        print_terminal_qrcode(qrcode_content, qrcode_path, "快手APP")


async def _emit_qrcode_callback(qrcode_callback, payload: dict):
    if not qrcode_callback:
        return

    callback_result = qrcode_callback(payload)
    if inspect.isawaitable(callback_result):
        await callback_result


def _build_login_result(
    success: bool,
    status: str,
    message: str,
    account_file: str,
    qrcode: dict | None = None,
    current_url: str = "",
) -> dict:
    return {
        "success": success,
        "status": status,
        "message": message,
        "account_file": str(account_file),
        "qrcode": qrcode,
        "current_url": current_url,
    }


async def _is_ks_cookie_invalid(page: Page, timeout: int = 5000) -> bool:
    try:
        await page.wait_for_selector(KUAISHOU_COOKIE_INVALID_SELECTOR, timeout=timeout)
        return True
    except Exception:
        return False


async def _extract_ks_qrcode_src(page: Page) -> str:
    login_form = page.locator("main#login-form").first
    await login_form.wait_for(state="visible", timeout=30000)

    qrcode_img = login_form.locator('div.qr-login img[alt="qrcode"]').first
    try:
        if not await qrcode_img.count() or not await qrcode_img.is_visible():
            platform_switch = login_form.locator("div.platform-switch").first
            await platform_switch.wait_for(state="visible", timeout=10000)
            await platform_switch.click()
            await asyncio.sleep(1)
    except Exception:
        platform_switch = login_form.locator("div.platform-switch").first
        await platform_switch.wait_for(state="visible", timeout=10000)
        await platform_switch.click()
        await asyncio.sleep(1)

    await qrcode_img.wait_for(state="visible", timeout=15000)

    qrcode_src = await qrcode_img.get_attribute("src")
    if not qrcode_src:
        raise RuntimeError("未获取到快手登录二维码地址")

    return qrcode_src


async def _save_ks_qrcode(page: Page, account_file: str, previous_qrcode_path: Path | None = None, qrcode_callback=None) -> dict:
    qrcode_src = await _extract_ks_qrcode_src(page)
    qrcode_path = save_data_url_image(qrcode_src, build_login_qrcode_path(account_file, suffix="ks_login_qrcode"))

    if previous_qrcode_path and previous_qrcode_path != qrcode_path:
        if remove_qrcode_file(previous_qrcode_path):
            kuaishou_logger.info(_msg("🧹", f"临时二维码文件已清理: {previous_qrcode_path}"))

    kuaishou_logger.info(_msg("🖼️", f"二维码已经准备好啦，已保存到: {qrcode_path}"))
    qrcode_content = decode_qrcode_from_path(qrcode_path)
    if qrcode_content:
        _print_ks_qrcode(qrcode_content, qrcode_path)
    else:
        kuaishou_logger.warning(_msg("😵", f"终端没法完整显示二维码，请打开 {qrcode_path} 扫码"))

    qrcode_info = {
        "image_path": str(qrcode_path),
        "image_data_url": qrcode_src,
    }
    await _emit_qrcode_callback(qrcode_callback, qrcode_info)
    return qrcode_info


async def _is_ks_qrcode_expired(page: Page) -> bool:
    expired_box = page.locator("div.qrcode-status.qrcode-status-timeout").first
    try:
        if not await expired_box.count():
            return False
        return await expired_box.is_visible()
    except Exception:
        return False


async def _is_ks_login_page_gone(page: Page) -> bool:
    try:
        login_form = page.locator("main#login-form").first
        if not await login_form.count():
            return True
        return not await login_form.is_visible()
    except Exception:
        return True


async def cookie_auth(account_file):
    async with async_playwright() as playwright:
        if LOCAL_CHROME_PATH:
            browser = await playwright.chromium.launch(headless=True, executable_path=LOCAL_CHROME_PATH)
        else:
            browser = await playwright.chromium.launch(headless=True, channel="chrome")
        try:
            context = await browser.new_context(storage_state=account_file)
            context = await set_init_script(context)
            page = await context.new_page()
            await page.goto(KUAISHOU_UPLOAD_URL)
            if await _is_ks_cookie_invalid(page):
                kuaishou_logger.info(_msg("🥹", "cookie 已失效，得重新登录一下"))
                return False

            kuaishou_logger.success(_msg("🥳", "cookie 有效"))
            return True
        except Exception as exc:
            kuaishou_logger.warning(_msg("😵", f"cookie 校验时出错，按失效处理: {exc}"))
            return False
        finally:
            await browser.close()


async def ks_setup(account_file, handle=False, return_detail=False, qrcode_callback=None, headless: bool = LOCAL_CHROME_HEADLESS):
    account_file = get_absolute_path(account_file, "ks_uploader")
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            result = _build_login_result(False, "cookie_invalid", "cookie文件不存在或已失效", account_file)
            return result if return_detail else False
        kuaishou_logger.info(_msg("🥹", "cookie 失效了，准备重新登录快手创作者平台"))
        result = await get_ks_cookie(account_file, qrcode_callback=qrcode_callback, headless=headless)
        return result if return_detail else result["success"]

    result = _build_login_result(True, "cookie_valid", "cookie有效", account_file)
    return result if return_detail else True


async def _extract_ks_nickname(page: Page) -> str:
    """快手创作者平台顶栏 .user-info-name 抓真实昵称; 抓不到返回空串。"""
    try:
        loc = page.locator("div.user-info-name").first
        if await loc.count() and await loc.is_visible():
            return (await loc.inner_text()).strip()
        return ""
    except Exception:
        return ""


async def fetch_account_nickname(account_file) -> str:
    """独立抓取快手创作者平台真实昵称并写入账号元数据(供 `mpau kuaishou nickname` 与 Web 登录回填)。

    与登录子进程解耦: 网页端「完成登录」会 taskkill 登录进程, 那里尾部的抓取可能来不及执行。
    失败返回空串, 不影响登录状态。
    """
    from utils.nickname import capture_nickname

    return await capture_nickname("kuaishou", str(account_file), "https://cp.kuaishou.com/profile", _extract_ks_nickname)


async def get_ks_cookie(
    account_file,
    qrcode_callback=None,
    headless: bool = LOCAL_CHROME_HEADLESS,
    poll_interval: int = 3,
    max_checks: int = 100,
):
    if headless:
        kuaishou_logger.info(_msg("🖼️", "快手登录将以无头模式运行，小人会输出终端二维码并保存本地二维码图片"))

    async with async_playwright() as playwright:
        if LOCAL_CHROME_PATH:
            browser = await playwright.chromium.launch(headless=headless, executable_path=LOCAL_CHROME_PATH)
        else:
            browser = await playwright.chromium.launch(headless=headless, channel="chrome")
        context = await browser.new_context()
        context = await set_init_script(context)
        qrcode_path = None
        qrcode_info = None
        result = _build_login_result(False, "failed", "快手登录失败", account_file)
        try:
            page = await context.new_page()
            await page.goto(KUAISHOU_LOGIN_URL)
            kuaishou_logger.info(_msg("🧍", "请在浏览器里扫码登录快手，小人正在耐心等待"))

            qrcode_info = await _save_ks_qrcode(page, account_file, qrcode_callback=qrcode_callback)
            qrcode_path = Path(qrcode_info["image_path"])

            for _ in range(max_checks):
                if page.url.startswith(KUAISHOU_UPLOAD_URL) or await _is_ks_login_page_gone(page):
                    await context.storage_state(path=account_file)
                    if await cookie_auth(account_file):
                        kuaishou_logger.success(_msg("🥳", "快手扫码登录成功，小人开心收工"))
                        result = _build_login_result(True, "success", "快手扫码登录成功", account_file, qrcode_info, page.url)
                        # 抓取真实昵称用于账号列表展示(失败不影响登录结果)
                        try:
                            from pipeline.account_meta import set_nickname

                            nickname = await _extract_ks_nickname(page)
                            if not nickname:
                                await page.goto("https://cp.kuaishou.com/profile", timeout=30000, wait_until="domcontentloaded")
                                await page.wait_for_timeout(3000)
                                nickname = await _extract_ks_nickname(page)
                            if nickname:
                                set_nickname("kuaishou", Path(account_file).stem, nickname)
                                kuaishou_logger.info(_msg("👤", f"已记录平台昵称: {nickname}"))
                                print(f"[PROFILE] platform=kuaishou account={Path(account_file).stem} nickname={nickname}", flush=True)
                        except Exception:
                            pass
                    else:
                        kuaishou_logger.error(_msg("😢", "快手扫码完成了，但 cookie 校验失败"))
                        result = _build_login_result(
                            False,
                            "cookie_invalid",
                            "快手扫码流程结束，但 cookie 校验失败",
                            account_file,
                            qrcode_info,
                            page.url,
                        )
                    return result

                if qrcode_info and await _is_ks_qrcode_expired(page):
                    kuaishou_logger.warning(_msg("😵", "二维码失效了，小人马上去刷新"))
                    refresh_button = page.locator("p.qrcode-refresh").first
                    if await refresh_button.count():
                        await refresh_button.click()
                        await asyncio.sleep(1)
                    qrcode_info = await _save_ks_qrcode(
                        page,
                        account_file,
                        qrcode_path,
                        qrcode_callback=qrcode_callback,
                    )
                    qrcode_path = Path(qrcode_info["image_path"])

                await asyncio.sleep(poll_interval)

            result = _build_login_result(
                False,
                "timeout",
                "等待快手扫码登录超时",
                account_file,
                qrcode_info,
                page.url,
            )
        except Exception as exc:
            result = _build_login_result(False, "failed", str(exc), account_file, current_url=page.url if "page" in locals() else "")
        finally:
            if remove_qrcode_file(qrcode_path):
                kuaishou_logger.info(_msg("🧹", f"临时二维码文件已清理: {qrcode_path}"))
            if not result["success"]:
                kuaishou_logger.error(_msg("😢", f"登录失败: {result['message']}"))
            await context.close()
            await browser.close()

    return result


class KSBaseUploader(BaseVideoUploader):
    def __init__(
        self,
        publish_date: datetime | int,
        account_file,
        publish_strategy: str | None = None,
        debug: bool = DEBUG_MODE,
        headless: bool = LOCAL_CHROME_HEADLESS,
    ):
        self.publish_date = publish_date
        self.account_file = str(account_file)
        self.publish_strategy = publish_strategy
        self.debug = debug
        self.headless = headless
        self.local_executable_path = LOCAL_CHROME_PATH
        self.date_format = "%Y-%m-%d %H:%M"

    async def validate_base_args(self):
        if not os.path.exists(self.account_file):
            raise RuntimeError(f"cookie文件不存在，请先完成快手登录: {self.account_file}")
        if not await cookie_auth(self.account_file):
            raise RuntimeError(f"cookie文件已失效，请先完成快手登录: {self.account_file}")

        if self.publish_strategy is None:
            self.publish_strategy = (
                KUAISHOU_PUBLISH_STRATEGY_SCHEDULED
                if self.publish_date != 0
                else KUAISHOU_PUBLISH_STRATEGY_IMMEDIATE
            )

        if self.publish_strategy not in {
            KUAISHOU_PUBLISH_STRATEGY_IMMEDIATE,
            KUAISHOU_PUBLISH_STRATEGY_SCHEDULED,
        }:
            raise ValueError(f"不支持的发布策略: {self.publish_strategy}")

        if self.publish_strategy == KUAISHOU_PUBLISH_STRATEGY_SCHEDULED:
            self.publish_date = self.validate_publish_date(self.publish_date)
        else:
            self.publish_date = 0

    async def set_schedule_time(self, page: Page, publish_date: datetime):
        kuaishou_logger.info(_msg("🕒", "小人准备设置定时发布时间"))
        publish_date_str = publish_date.strftime("%Y-%m-%d %H:%M:%S")

        # 1. 切换到"定时发布"radio (用文本匹配更稳)
        await page.locator('label.ant-radio-wrapper').filter(has_text="定时发布").click()
        await asyncio.sleep(2)

        # 2. 点击 picker 打开下拉面板
        await page.locator('input[placeholder="选择日期时间"]').click()
        await asyncio.sleep(1)

        # 3. 用 React 兼容的方式直接设置 input 的 value
        #    (ant-design DatePicker 是 controlled component, 必须用 native setter + bubbling event)
        js_code = """
        (newValue) => {
            const input = document.querySelector('input[placeholder="选择日期时间"]');
            if (!input) return false;
            const nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeSetter.call(input, newValue);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }
        """
        ok = await page.evaluate(js_code, publish_date_str)
        if not ok:
            kuaishou_logger.error("❌ 找不到时间选择器输入框")
            return

        await asyncio.sleep(1)
        # 4. 按 Enter 确认
        await page.keyboard.press("Enter")
        await asyncio.sleep(2)
        kuaishou_logger.info(f"✅ 定时发布时间已设置为 {publish_date_str}")

    async def close_guide_overlay(self, page: Page) -> bool:
        joyride_tooltip = page.locator('div[id^="react-joyride-step"] div[role="alertdialog"]')

        # 判断是否显示
        if await joyride_tooltip.count() > 0 and await joyride_tooltip.first.is_visible():
            print("检测到 Joyride 引导遮罩，正在关闭...")

            # 点击关闭按钮（X），使用多个可靠特征
            close_button = page.locator('div[role="alertdialog"]').locator(
                '[aria-label="Skip"], [data-action="skip"], button[title="Skip"]'
            )

            await close_button.click(force=True)

            # 等待遮罩消失
            await joyride_tooltip.wait_for(state="hidden", timeout=5000)

            print("✅ 已关闭 Joyride 遮罩")
        else:
            print("未检测到 Joyride 遮罩，继续执行")


class KSVideo(KSBaseUploader):
    def __init__(
        self,
        title,
        file_path,
        tags,
        publish_date: datetime | int,
        account_file,
        publish_strategy: str | None = None,
        debug: bool = DEBUG_MODE,
        headless: bool = LOCAL_CHROME_HEADLESS,
        thumbnail_path=None,
        desc: str | None = None,
        goods_name: str | None = None,
    ):
        super().__init__(
            publish_date=publish_date,
            account_file=account_file,
            publish_strategy=publish_strategy,
            debug=debug,
            headless=headless,
        )
        self.title = title
        self.file_path = file_path
        self.tags = tags or []
        self.thumbnail_path = thumbnail_path
        self.desc = desc or ""
        # 快手只支持按**商品名称**关联商品(不支持商品ID), 名称需与快手小店里一致
        self.goods_name = str(goods_name).strip() if goods_name else ""

    async def validate_upload_args(self):
        await self.validate_base_args()
        if not self.title or not str(self.title).strip():
            raise ValueError("快手视频上传时，title 是必须的")
        self.file_path = str(self.validate_video_file(self.file_path))
        if self.thumbnail_path:
            self.thumbnail_path = str(self.validate_image_file(self.thumbnail_path))
        if self.goods_name and not str(self.goods_name).strip():
            raise ValueError("快手商品名称不能为空白")

    async def handle_upload_error(self, page: Page):
        kuaishou_logger.warning(_msg("😵", "视频上传摔了一跤，小人马上重新上传"))
        await page.locator('div.progress-div [class^="upload-btn-input"]').set_input_files(self.file_path)

    async def set_thumbnail(self, page: Page):
        if not self.thumbnail_path:
            return

        kuaishou_logger.info(_msg("🖼️", "小人准备设置封面"))

        cover_label = page.locator("span").filter(has_text="封面设置")
        await cover_label.wait_for(state="visible", timeout=30000)
        await cover_label.locator("xpath=../following-sibling::div[1]").locator('div').nth(0).click()

        modal = page.locator('div[role="document"].ant-modal')
        await modal.wait_for(state="visible", timeout=30000)

        upload_cover_tab = modal.get_by_text("上传封面", exact=True)
        await upload_cover_tab.wait_for(state="visible", timeout=10000)
        await upload_cover_tab.click()

        file_input = modal.locator('input[type="file"]')
        await file_input.wait_for(state="attached", timeout=30000)
        await file_input.set_input_files(self.thumbnail_path)
        await asyncio.sleep(1)

        confirm_button = modal.get_by_role("button", name="确认", exact=True)
        await confirm_button.wait_for(state="visible", timeout=10000)
        await confirm_button.click()

        await modal.wait_for(state="hidden", timeout=30000)
        kuaishou_logger.success(_msg("🥳", "封面已经设置完成"))

    async def _add_goods(self, page: Page) -> None:
        """挂载快手商品 —— 走「作者服务 → 关联商品」, 按**商品名称**搜索并关联。

        真机校准结论(2026-09-11, 账号 百悦食品专营店):
          - 入口: 「作者服务」行第一个 ant-select, 默认值「选择服务类型」
          - 选项: 关联商品 / 关联推广任务 / 关联小程序 / 招聘人才
          - 选中「关联商品」后, 该行右侧出现商品搜索框(占位「关联商品获得更多收入」)
          - 输入商品名后结果是 antd 选项(.ant-select-item-option), 内容形如「商品名￥19.99」
          - 候选项文本里带商品 JSON({"title":...,"url":...}), 优先用它精确匹配名称
        注意: 必须先 close_guide_overlay —— Joyride 遮罩会拦截所有点击。

        任一步失败即截图并抛异常中断, 绝不静默发布一条没挂上商品的视频。
        """
        if not self.goods_name:
            return
        goods_name = str(self.goods_name).strip()
        kuaishou_logger.info(_msg("🛍️", f"小人准备关联商品: {goods_name}"))

        async def _fail(reason: str) -> None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shot_dir = Path(MPAU_HOME) / "logs"
            shot_dir.mkdir(parents=True, exist_ok=True)
            shot = str(shot_dir / f"ks_goods_{ts}.png")
            try:
                await page.screenshot(path=shot, full_page=True)
            except Exception:  # noqa: BLE001
                shot = "(截图失败)"
            kuaishou_logger.error(_msg("❌", f"{reason} 截图: {shot}"))
            raise RuntimeError(f"快手商品关联失败: {reason} 截图: {shot}")

        # 步骤 1: 滚动到底(该区块在页面底部, 不滚动则未渲染)
        for _ in range(6):
            await page.mouse.wheel(0, 1200)
            await asyncio.sleep(0.3)
        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)

        # 步骤 2: 关 Joyride 引导遮罩(否则点击全被拦截)
        try:
            await self.close_guide_overlay(page)
        except Exception as exc:  # noqa: BLE001
            kuaishou_logger.warning(_msg("😵", f"关引导遮罩异常, 继续: {exc}"))
        removed = await page.evaluate(
            "() => { let n=0; document.querySelectorAll('#react-joyride-portal')"
            ".forEach(e => { e.remove(); n++; }); return n; }"
        )
        if removed:
            kuaishou_logger.info(_msg("🧹", f"已移除引导遮罩节点 x{removed}"))
            await asyncio.sleep(0.5)

        # 步骤 3: 定位「作者服务」行(按坐标, 规避哈希类名), 点开服务类型下拉
        located = await page.evaluate("""() => {
            const vis = el => { const r = el.getBoundingClientRect();
                if (!r.width || !r.height) return false;
                const st = getComputedStyle(el);
                return st.visibility !== 'hidden' && st.display !== 'none'; };
            const labels = [...document.querySelectorAll('label,div,span')]
                .filter(el => (el.textContent || '').trim() === '作者服务' && vis(el));
            if (!labels.length) return {ok: false, err: '未找到「作者服务」字段'};
            const lb = labels[0].getBoundingClientRect();
            const sels = [...document.querySelectorAll('.ant-select')].filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && Math.abs(r.y - lb.y) < 20 && r.x > lb.x;
            });
            if (!sels.length) return {ok: false, err: '「作者服务」行未找到下拉框'};
            sels[0].setAttribute('data-mpau', 'svc');
            if (sels.length > 1) sels[1].setAttribute('data-mpau', 'goodsbox');
            return {ok: true, row_text: (sels[0].textContent || '').trim().slice(0, 24)};
        }""")
        if not located.get("ok"):
            await _fail(f"未找到「作者服务 → 关联商品」入口({located.get('err')})。"
                        f"该账号可能未开通商品分享权限")
        kuaishou_logger.info(_msg("🔎", f"作者服务当前值: {located.get('row_text')}"))

        try:
            await page.locator('[data-mpau="svc"]').first.click(timeout=8000)
        except Exception:  # noqa: BLE001
            # 遮罩/遮挡兜底: 直接派发鼠标事件
            await page.locator('[data-mpau="svc"]').first.evaluate("""el => {
                for (const t of ['mousedown','mouseup','click'])
                    el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window}));
            }""")
        await asyncio.sleep(1.5)

        # 步骤 4: 选「关联商品」(JS 点选更稳, 绕开 hit-testing)
        try:
            await page.wait_for_selector(
                ".ant-select-dropdown:not(.ant-select-dropdown-hidden)", timeout=8000
            )
        except Exception:  # noqa: BLE001
            kuaishou_logger.warning(_msg("😵", "等待服务类型下拉超时, 仍尝试点选"))
        picked = await page.evaluate("""() => {
            const dds = [...document.querySelectorAll('.ant-select-dropdown')]
                .filter(d => !d.className.includes('hidden'));
            for (const dd of dds) {
                for (const it of dd.querySelectorAll('.ant-select-item-option,[role="option"]')) {
                    if ((it.textContent || '').trim() === '关联商品') {
                        it.scrollIntoView({block: 'center'});
                        it.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                        it.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true, view:window}));
                        it.click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        if not picked:
            # 兜底: Playwright 点击
            try:
                await page.locator(
                    '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option'
                ).filter(has_text="关联商品").first.click(timeout=8000)
                picked = True
            except Exception as exc:  # noqa: BLE001
                await _fail(f"未能选中「关联商品」选项({exc})")
        await asyncio.sleep(2)

        # 断言服务类型已切换, 且商品框已启用
        state = await page.evaluate("""() => {
            const labels = [...document.querySelectorAll('label,div,span')]
                .filter(el => (el.textContent || '').trim() === '作者服务');
            if (!labels.length) return {err: 'no-label'};
            const lb = labels[0].getBoundingClientRect();
            const sels = [...document.querySelectorAll('.ant-select')].filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && Math.abs(r.y - lb.y) < 20 && r.x > lb.x;
            });
            return {row_texts: sels.map(s => (s.textContent || '').trim().slice(0, 24)),
                    disabled: sels.map(s => s.className.includes('disabled'))};
        }""")
        texts = state.get("row_texts") or []
        if not texts or "关联商品" not in texts[0]:
            await _fail(f"服务类型未切换为「关联商品」(当前: {texts})")
        if len(texts) > 1 and "收入" not in texts[1]:
            await _fail(f"商品搜索框未出现(当前行: {texts})")
        if state.get("disabled") and state["disabled"][-1]:
            await _fail("商品搜索框处于禁用状态")
        kuaishou_logger.info(_msg("✅", "已选中「关联商品」, 商品搜索框已就绪"))

        # 步骤 5: 输入商品名称并等待结果
        search = page.locator('[data-mpau="goodsbox"] input').first
        try:
            await search.click(timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(1)
        try:
            await search.fill("")
            await search.type(goods_name, delay=40)
        except Exception as exc:  # noqa: BLE001
            await _fail(f"商品名称输入失败({exc})")
        await asyncio.sleep(4)

        # 步骤 6: 匹配并点选商品(优先用候选项里的商品 JSON 精确比对)
        chosen = await page.evaluate("""(want) => {
            const dds = [...document.querySelectorAll('.ant-select-dropdown')]
                .filter(d => !d.className.includes('hidden'));
            const opts = [];
            for (const dd of dds) {
                for (const it of dd.querySelectorAll('.ant-select-item-option,[role="option"]')) {
                    const txt = (it.textContent || '').trim();
                    if (!txt || !(txt.includes('￥') || txt.includes('¥'))) continue;
                    opts.push(it);
                }
            }
            if (!opts.length) return {found: false, reason: 'no-option'};
            const meta = el => {
                const m = (el.textContent || '').match(/\\{[^{}]*"title"\\s*:\\s*"([^"]+)"/);
                return m ? m[1] : '';
            };
            const norm = s => (s || '').replace(/\\s+/g, '').toLowerCase();
            const target = norm(want);
            let hit = opts.find(o => norm(meta(o)) === target);
            if (!hit) hit = opts.find(o => norm(meta(o)).includes(target));
            if (!hit) hit = opts.find(o => norm(o.textContent).includes(target));
            if (!hit) return {found: false, reason: 'no-match', count: opts.length};
            hit.scrollIntoView({block: 'center'});
            hit.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
            hit.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true, view:window}));
            hit.click();
            return {found: true, picked: meta(hit) || (hit.textContent || '').trim().slice(0, 60),
                    count: opts.length};
        }""", goods_name)

        if not chosen.get("found"):
            detail = "搜索结果为空" if chosen.get("reason") == "no-option" else \
                     f"搜索结果里没有匹配「{goods_name}」的商品(共 {chosen.get('count')} 条)"
            await _fail(f"{detail}。请确认商品名称与快手小店里完全一致")
        await asyncio.sleep(2)
        kuaishou_logger.success(_msg("🛍️", f"已关联商品: {chosen.get('picked')}"))

    async def upload(self, playwright: Playwright) -> None:
        kuaishou_logger.info(_msg("🧍", "小人先检查 cookie、视频文件、封面和发布时间"))
        await self.validate_upload_args()
        kuaishou_logger.info(_msg("🥳", "上传前检查通过"))

        if self.local_executable_path:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                executable_path=self.local_executable_path,
            )
        else:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                channel="chrome",
            )
        context = await browser.new_context(storage_state=self.account_file)
        context = await set_init_script(context)

        upload_success = False
        try:
            page = await context.new_page()
            await page.goto(KUAISHOU_UPLOAD_URL)
            kuaishou_logger.info(_msg("🏃", f"小人开始搬运视频: {self.title}.mp4"))
            kuaishou_logger.info(_msg("🧭", "小人正在赶往快手上传主页"))
            await page.wait_for_url(KUAISHOU_UPLOAD_URL_PATTERN)

            upload_button = page.locator("button[class^='_upload-btn']")
            await upload_button.wait_for(state="visible", timeout=10000)

            async with page.expect_file_chooser() as fc_info:
                await upload_button.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(self.file_path)

            await asyncio.sleep(2)

            know_button = page.locator('button[type="button"] span:text("我知道了")').first
            try:
                if await know_button.count() and await know_button.is_visible():
                    await know_button.click()
            except Exception:
                pass

            await self.close_guide_overlay(page)

            kuaishou_logger.info(_msg("✍️", "小人开始填描述和话题"))
            await page.get_by_text("描述").locator("xpath=following-sibling::div").click()
            await page.keyboard.press("Backspace")
            await page.keyboard.press("Control+KeyA")
            await page.keyboard.press("Delete")
            await page.keyboard.type(self.desc or self.title)
            await page.keyboard.press("Enter")

            for index, tag in enumerate(self.tags[:3], start=1):
                kuaishou_logger.info(_msg("🏷️", f"小人正在添加第 {index} 个话题: #{tag}"))
                await page.keyboard.type(f"#{tag} ")
                await asyncio.sleep(2)

            max_retries = 60
            retry_count = 0
            while retry_count < max_retries:
                try:
                    number = await page.locator("text=上传中").count()
                    if number == 0:
                        kuaishou_logger.success(_msg("🥳", "视频已经传完啦"))
                        break

                    if retry_count % 5 == 0:
                        kuaishou_logger.info(_msg("🏃", "小人正在努力上传视频"))

                    if await page.locator("text=上传失败").count():
                        await self.handle_upload_error(page)

                    await asyncio.sleep(2)
                except Exception as exc:
                    kuaishou_logger.warning(_msg("😵", f"检查上传状态时出错，小人继续重试: {exc}"))
                    await asyncio.sleep(2)
                retry_count += 1

            if retry_count == max_retries:
                kuaishou_logger.warning(_msg("😵", "超过最大重试次数，视频上传可能未完成"))

            await self.set_thumbnail(page)

            # 挂车: 上传完成后、发布前关联商品(失败会抛异常中断, 不静默发无商品视频)
            await self._add_goods(page)

            if self.publish_strategy == KUAISHOU_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
                await self.set_schedule_time(page, self.publish_date)

            while True:
                try:
                    publish_button = page.get_by_text("发布", exact=True)
                    if await publish_button.count() > 0:
                        await publish_button.click()

                    await asyncio.sleep(1)
                    confirm_button = page.get_by_text("确认发布")
                    if await confirm_button.count() > 0:
                        await confirm_button.click()

                    await page.wait_for_url(KUAISHOU_MANAGE_URL_PATTERN, timeout=5000)
                    kuaishou_logger.success(_msg("🥳", "视频发布成功，小人开心收工"))
                    break
                except Exception as exc:
                    kuaishou_logger.info(_msg("🏃", f"小人正在冲刺发布视频: {exc}"))
                    if self.debug:
                        await page.screenshot(full_page=True)
                    await asyncio.sleep(1)

            upload_success = True
        finally:
            if upload_success:
                await context.storage_state(path=self.account_file)
                kuaishou_logger.success(_msg("🥳", "cookie 更新完毕"))
                await asyncio.sleep(2)
            await context.close()
            await browser.close()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)


class KSNote(KSBaseUploader):
    def __init__(
        self,
        image_paths,
        note,
        tags,
        publish_date: datetime | int,
        account_file,
        title: str | None = None,
        publish_strategy: str | None = None,
        debug: bool = DEBUG_MODE,
        headless: bool = LOCAL_CHROME_HEADLESS,
    ):
        super().__init__(
            publish_date=publish_date,
            account_file=account_file,
            publish_strategy=publish_strategy,
            debug=debug,
            headless=headless,
        )
        self.image_paths = image_paths
        self.note = note or ""
        self.title = title or (self.note[:20] if self.note else "")
        self.tags = tags or []

    async def validate_upload_args(self):
        await self.validate_base_args()
        if not self.title or not str(self.title).strip():
            raise ValueError("快手图文上传时，title 是必须的")
        if not self.image_paths:
            raise ValueError("快手图文上传时，图片是必须的")

        if isinstance(self.image_paths, (str, Path)):
            self.image_paths = [self.image_paths]

        normalized_image_paths = []
        for image_path in self.image_paths:
            normalized_image_paths.append(str(self.validate_image_file(image_path)))
        self.image_paths = normalized_image_paths

    async def upload_note_content(self, page: Page) -> None:
        kuaishou_logger.info(_msg("🏃", f"小人开始搬运图文，共 {len(self.image_paths)} 张图片"))
        kuaishou_logger.info(_msg("🔀", "小人正在切换到图文发布"))
        await page.locator('div[role="tablist"] div[role="tab"]:has-text("图文")').click()
        await page.wait_for_timeout(1000)

        kuaishou_logger.info(_msg("📤", "小人正在上传图片"))
        upload_button = page.locator("button[class^='_upload-btn']").filter(has_text="上传图片")
        await upload_button.wait_for(state="visible", timeout=10000)

        async with page.expect_file_chooser() as fc_info:
            await upload_button.click()
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.image_paths)

        know_button = page.locator('button[type="button"] span:text("我知道了")').first
        try:
            if await know_button.count() and await know_button.is_visible():
                await know_button.click()
        except Exception:
            pass

        await self.close_guide_overlay(page)

        kuaishou_logger.info(_msg("✍️", "小人开始填写图文内容和话题"))
        await page.get_by_text("描述").locator("xpath=following-sibling::div").click()
        await page.keyboard.press("Backspace")
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.press("Delete")
        await page.keyboard.type(self.note)
        await page.keyboard.press("Enter")

        for index, tag in enumerate(self.tags[:3], start=1):
            kuaishou_logger.info(_msg("🏷️", f"小人正在添加第 {index} 个话题: #{tag}"))
            await page.keyboard.type(f"#{tag} ")
            await asyncio.sleep(2)

        max_retries = 60
        retry_count = 0
        while retry_count < max_retries:
            try:
                number = await page.locator("text=上传中").count()
                if number == 0:
                    kuaishou_logger.success(_msg("🥳", "图文素材已经传完啦"))
                    break

                if retry_count % 5 == 0:
                    kuaishou_logger.info(_msg("🏃", "小人正在努力上传图文素材"))

                if await page.locator("text=上传失败").count():
                    kuaishou_logger.warning(_msg("😵", "图文素材上传摔了一跤，小人马上重新上传"))
                    await page.locator('div.progress-div [class^="upload-btn-input"]').set_input_files(self.image_paths)

                await asyncio.sleep(2)
            except Exception as exc:
                kuaishou_logger.warning(_msg("😵", f"检查图文上传状态时出错，小人继续重试: {exc}"))
                await asyncio.sleep(2)
            retry_count += 1

        if retry_count == max_retries:
            kuaishou_logger.warning(_msg("😵", "超过最大重试次数，图文上传可能未完成"))

        if self.publish_strategy == KUAISHOU_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
            await self.set_schedule_time(page, self.publish_date)

        while True:
            try:
                publish_button = page.get_by_text("发布", exact=True)
                if await publish_button.count() > 0:
                    await publish_button.click()

                await asyncio.sleep(1)
                confirm_button = page.get_by_text("确认发布")
                if await confirm_button.count() > 0:
                    await confirm_button.click()

                await page.wait_for_url(KUAISHOU_MANAGE_URL_PATTERN, timeout=5000)
                kuaishou_logger.success(_msg("🥳", "图文发布成功，小人开心收工"))
                break
            except Exception as exc:
                kuaishou_logger.info(_msg("🏃", f"小人正在冲刺发布图文: {exc}"))
                if self.debug:
                    await page.screenshot(full_page=True)
                await asyncio.sleep(1)

    async def upload(self, playwright: Playwright) -> None:
        kuaishou_logger.info(_msg("🧍", "小人先检查 cookie、图片和发布时间"))
        await self.validate_upload_args()
        kuaishou_logger.info(_msg("🥳", "图文上传前检查通过"))

        if self.local_executable_path:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                executable_path=self.local_executable_path,
            )
        else:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                channel="chrome",
            )
        context = await browser.new_context(storage_state=self.account_file)
        context = await set_init_script(context)

        upload_success = False
        try:
            page = await context.new_page()
            await page.goto(KUAISHOU_UPLOAD_URL)
            kuaishou_logger.info(_msg("🧭", "小人正在赶往快手图文发布页"))
            await page.wait_for_url(KUAISHOU_UPLOAD_URL_PATTERN)

            await self.upload_note_content(page)
            upload_success = True
        finally:
            if upload_success:
                await context.storage_state(path=self.account_file)
                kuaishou_logger.success(_msg("🥳", "cookie 更新完毕"))
                await asyncio.sleep(2)
            await context.close()
            await browser.close()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
