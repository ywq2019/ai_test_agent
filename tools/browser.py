"""
Playwright浏览器控制工具
- BrowserTool：单次请求用的浏览器操作封装，基于独立 Context，执行完调用 close() 释放
- BrowserPool：共享 Browser 实例（进程级），每次请求创建独立 Context，最多 MAX_CONCURRENT 个并发
"""
import asyncio
from typing import List, Dict, Optional, Any
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Playwright
from loguru import logger
from tools.config import settings
from pathlib import Path

# 最多同时运行的浏览器 Context 数量，超出则排队等待
MAX_CONCURRENT = 3


class BrowserTool:
    """
    基于独立 Context 的单次请求浏览器工具。
    使用方式：
        async with BrowserPool.acquire(browser_type) as bt:
            await bt.navigate(url)
            ...
    或直接：
        bt = await BrowserPool.acquire_raw(browser_type)
        try:
            ...
        finally:
            await bt.close()
    """
    def __init__(self, browser: Browser, browser_type: str = "chromium"):
        self.browser_type = browser_type
        self._browser = browser          # 共享 Browser，不由本实例关闭
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def _init_context(self):
        """为当前请求创建独立 Context 和 Page。"""
        self.context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self.page = await self.context.new_page()
        logger.debug(f"New browser context created for {self.browser_type}")

    async def navigate(self, url: str, timeout: int = 60000):
        # 根据 URL 自动判断是否是移动端页面，切换 UA
        is_mobile = any(k in url for k in ['/m/', 'm.', '/mobile', '/wap', 'micropage', 'h5'])
        if is_mobile:
            await self.page.emulate_media()
            await self.context.set_extra_http_headers({"User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
            )})

        # wait_until="networkidle" 等待网络请求静止，确保动态内容渲染完毕
        # 兜底：networkidle 失败则改用 load
        try:
            await self.page.goto(url, timeout=timeout, wait_until="networkidle")
        except Exception:
            await self.page.goto(url, timeout=timeout, wait_until="load")

        logger.info(f"Navigated to {url}")
        # 额外等待 JS 渲染（动态框架通常需要 1-2 秒完成首屏渲染）
        await self.page.wait_for_timeout(3000)

        # 自动滚动页面，触发懒加载内容（需求页面、列表页等常见场景）
        await self._scroll_to_load()

    async def _scroll_to_load(self):
        """分段滚动页面到底部，触发懒加载内容，最多滚动 15 屏。"""
        try:
            # 获取页面总高度
            page_height = await self.page.evaluate("() => document.body.scrollHeight")
            viewport_height = 1080
            scroll_step = viewport_height          # 每次滚动一屏
            current_pos = 0
            max_scrolls = 15                       # 最多滚动 15 屏，防止无限页面卡住
            scroll_count = 0

            logger.info(f"开始滚动加载，页面总高度: {page_height}px")

            while current_pos < page_height and scroll_count < max_scrolls:
                current_pos += scroll_step
                await self.page.evaluate(f"window.scrollTo(0, {current_pos})")
                await self.page.wait_for_timeout(600)   # 等待懒加载内容渲染

                # 重新获取高度（内容动态加载后高度可能增加）
                new_height = await self.page.evaluate("() => document.body.scrollHeight")
                if new_height > page_height:
                    page_height = new_height
                    logger.debug(f"页面高度增加到 {page_height}px（懒加载触发）")

                scroll_count += 1

            # 滚动完成后回到顶部，让页面元素恢复正常状态
            await self.page.evaluate("window.scrollTo(0, 0)")
            await self.page.wait_for_timeout(800)
            logger.info(f"滚动完成，共滚动 {scroll_count} 屏")
        except Exception as e:
            logger.warning(f"滚动加载失败（不影响主流程）: {e}")

    async def capture_elements(self) -> List[Dict[str, Any]]:
        debug_script = """
        () => {
            return {
                title: document.title,
                bodyChildren: document.body.children.length,
                readyState: document.readyState,
                forms: document.forms.length,
                inputs: document.querySelectorAll('input').length,
                buttons: document.querySelectorAll('button').length,
                links: document.querySelectorAll('a').length,
                allTags: [...new Set([...document.querySelectorAll('*')].map(el => el.tagName))].slice(0, 20)
            };
        }
        """
        debug_info = await self.page.evaluate(debug_script)
        logger.info(f"Page debug info: {debug_info}")

        elements_script = """
        () => {
            const elements = [];
            const interactiveTags = ['input', 'button', 'a', 'select', 'textarea', 'checkbox', 'radio', 'option', 'table', 'div', 'span', 'img', 'iframe'];

            document.querySelectorAll(interactiveTags.join(',')).forEach(el => {
                const tag = el.tagName.toLowerCase();
                const type = el.type || '';
                const role = el.getAttribute('role') || '';
                const id = el.id || '';
                const name = el.name || el.getAttribute('data-testid') || '';
                const text = el.innerText || el.value || '';
                const placeholder = el.placeholder || '';
                const href = el.href || '';
                const rect = el.getBoundingClientRect();

                const viewW = window.innerWidth;
                const viewH = window.innerHeight;
                const isLargeContainer = (tag === 'div' || tag === 'span') &&
                    rect.width > viewW * 0.8 && rect.height > viewH * 0.8;

                if (rect.width > 0 && rect.height > 0 && !isLargeContainer) {
                    elements.push({
                        tag, type, role, id, name,
                        text: text.substring(0, 100),
                        placeholder, href,
                        x: rect.x, y: rect.y,
                        width: rect.width, height: rect.height,
                        selector: get_selector(el)
                    });
                }
            });

            function get_selector(el) {
                if (el.id) return `#${el.id}`;
                if (el.name) return `${el.tagName.toLowerCase()}[name="${el.name}"]`;
                if (el.className) return `${el.tagName.toLowerCase()}.${el.className.split(' ').join('.')}`;
                return el.tagName.toLowerCase();
            }

            return elements;
        }
        """
        elements = await self.page.evaluate(elements_script)
        logger.info(f"Captured {len(elements)} interactive elements")

        # 元素太少说明页面还没渲染完，等待后重试一次
        if len(elements) < 5:
            logger.warning(f"Too few elements ({len(elements)}), waiting 3s and retrying...")
            await self.page.wait_for_timeout(3000)
            elements = await self.page.evaluate(elements_script)
            logger.info(f"Retry captured {len(elements)} interactive elements")

        return elements

    async def fill_input(self, selector: str, value: str):
        await self.page.fill(selector, value)
        logger.debug(f"Filled input {selector}")

    async def click_element(self, selector: str):
        await self.page.click(selector)
        logger.debug(f"Clicked element {selector}")

    async def select_option(self, selector: str, value: str):
        await self.page.select_option(selector, value)
        logger.debug(f"Selected option {value} in {selector}")

    async def take_screenshot(self, path: str) -> str:
        screenshot_dir = Path(path).parent
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=path, full_page=True)
        logger.debug(f"Screenshot saved to {path}")
        return path

    async def wait_for_selector(self, selector: str, timeout: int = 5000):
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def get_page_info(self) -> Dict[str, Any]:
        return {
            "title": await self.page.title(),
            "url": self.page.url,
            "content": await self.page.content()
        }

    async def execute_script(self, script: str):
        return await self.page.evaluate(script)

    async def close(self):
        """关闭当前 Context 和 Page，不关闭共享 Browser。"""
        try:
            if self.page:
                await self.page.close()
        except Exception:
            pass
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        logger.debug(f"Browser context closed for {self.browser_type}")


class BrowserPool:
    """
    进程级共享 Browser 池。
    - 每种浏览器类型维护一个 Browser 实例（复用，避免反复启动开销）
    - 每次请求通过 acquire() 获取独立 Context，完全隔离 cookie / storage / 状态
    - Semaphore 限制最大并发 Context 数，超出排队等待
    """
    def __init__(self, max_concurrent: int = MAX_CONCURRENT):
        self._browsers: Dict[str, Browser] = {}
        self._playwright: Optional[Playwright] = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()
        self._max_concurrent = max_concurrent

    async def _ensure_playwright(self):
        if self._playwright is None:
            self._playwright = await async_playwright().start()

    async def _ensure_browser(self, browser_type: str) -> Browser:
        """确保指定类型的 Browser 已启动（懒加载，线程安全）。"""
        async with self._lock:
            await self._ensure_playwright()
            if browser_type not in self._browsers:
                browser_map = {
                    "chromium": self._playwright.chromium,
                    "firefox":  self._playwright.firefox,
                    "webkit":   self._playwright.webkit,
                }
                launcher = browser_map.get(browser_type, self._playwright.chromium)
                self._browsers[browser_type] = await launcher.launch(headless=True)
                logger.info(f"Browser {browser_type} launched (shared instance)")
        return self._browsers[browser_type]

    async def acquire(self, browser_type: str = "chromium") -> "BrowserTool":
        """
        获取一个独立 Context 的 BrowserTool 实例。
        调用方必须在使用完毕后调用 release(bt) 或使用 async with 语法。
        """
        await self._semaphore.acquire()
        try:
            browser = await self._ensure_browser(browser_type)
            bt = BrowserTool(browser, browser_type)
            await bt._init_context()
            return bt
        except Exception:
            self._semaphore.release()
            raise

    def release(self, bt: "BrowserTool"):
        """归还 Semaphore 槽位（关闭 context 由调用方负责）。"""
        self._semaphore.release()

    # ── 向后兼容：旧代码调用 browser_pool.get_browser() ──────────────────
    async def get_browser(self, browser_type: str = "chromium", headless: bool = True) -> "BrowserTool":
        """
        兼容旧接口。返回带独立 Context 的 BrowserTool。
        注意：调用方需在用完后调用 bt.close() + browser_pool.release(bt)。
        """
        return await self.acquire(browser_type)

    async def close_all(self):
        for browser in self._browsers.values():
            try:
                await browser.close()
            except Exception:
                pass
        self._browsers.clear()
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        logger.info("BrowserPool closed all browsers")


browser_pool = BrowserPool(max_concurrent=MAX_CONCURRENT)
