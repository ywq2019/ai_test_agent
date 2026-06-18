"""
Playwright浏览器控制工具
"""
import asyncio
from typing import List, Dict, Optional, Any
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from loguru import logger
from tools.config import settings
from pathlib import Path


class BrowserTool:
    def __init__(self, browser_type: str = "chromium"):
        self.browser_type = browser_type
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def _launch_sync(self):
        """同步启动浏览器（内部方法）"""
        self.playwright = sync_playwright().start()
        browser_map = {
            "chromium": self.playwright.chromium,
            "firefox": self.playwright.firefox,
            "webkit": self.playwright.webkit
        }
        browser_class = browser_map.get(self.browser_type, self.playwright.chromium)
        self.browser = browser_class.launch(headless=True)
        self.context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self.page = self.context.new_page()
        logger.info(f"Browser {self.browser_type} launched")
        return self

    async def launch(self):
        """异步启动浏览器"""
        return await asyncio.to_thread(self._launch_sync)

    def _navigate_sync(self, url: str, timeout: int):
        """同步导航到URL（内部方法）"""
        self.page.goto(url, timeout=timeout, wait_until="commit")
        logger.info(f"Navigated to {url}")
        self.page.wait_for_timeout(5000)

    async def navigate(self, url: str, timeout: int = 60000):
        """异步导航到URL"""
        await asyncio.to_thread(self._navigate_sync, url, timeout)

    def _capture_elements_sync(self) -> List[Dict[str, Any]]:
        """同步捕获页面元素（内部方法）"""
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
        debug_info = self.page.evaluate(debug_script)
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

                if (rect.width > 0 && rect.height > 0) {
                    elements.push({
                        tag,
                        type,
                        role,
                        id,
                        name,
                        text: text.substring(0, 100),
                        placeholder,
                        href,
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
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
        elements = self.page.evaluate(elements_script)
        logger.info(f"Captured {len(elements)} interactive elements")
        return elements

    async def capture_elements(self) -> List[Dict[str, Any]]:
        """异步捕获页面元素"""
        return await asyncio.to_thread(self._capture_elements_sync)

    def _fill_input_sync(self, selector: str, value: str):
        """同步填充输入框（内部方法）"""
        self.page.fill(selector, value)
        logger.debug(f"Filled input {selector} with value")

    async def fill_input(self, selector: str, value: str):
        """异步填充输入框"""
        await asyncio.to_thread(self._fill_input_sync, selector, value)

    def _click_element_sync(self, selector: str):
        """同步点击元素（内部方法）"""
        self.page.click(selector)
        logger.debug(f"Clicked element {selector}")

    async def click_element(self, selector: str):
        """异步点击元素"""
        await asyncio.to_thread(self._click_element_sync, selector)

    def _select_option_sync(self, selector: str, value: str):
        """同步选择选项（内部方法）"""
        self.page.select_option(selector, value)
        logger.debug(f"Selected option {value} in {selector}")

    async def select_option(self, selector: str, value: str):
        """异步选择选项"""
        await asyncio.to_thread(self._select_option_sync, selector, value)

    def _take_screenshot_sync(self, path: str) -> str:
        """同步截图（内部方法）"""
        screenshot_dir = Path(path).parent
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=path, full_page=True)
        logger.debug(f"Screenshot saved to {path}")
        return path

    async def take_screenshot(self, path: str) -> str:
        """异步截图"""
        return await asyncio.to_thread(self._take_screenshot_sync, path)

    def _wait_for_selector_sync(self, selector: str, timeout: int):
        """同步等待选择器（内部方法）"""
        self.page.wait_for_selector(selector, timeout=timeout)

    async def wait_for_selector(self, selector: str, timeout: int = 5000):
        """异步等待选择器"""
        await asyncio.to_thread(self._wait_for_selector_sync, selector, timeout)

    def _get_page_info_sync(self) -> Dict[str, Any]:
        """同步获取页面信息（内部方法）"""
        return {
            "title": self.page.title(),
            "url": self.page.url,
            "content": self.page.content()
        }

    async def get_page_info(self) -> Dict[str, Any]:
        """异步获取页面信息"""
        return await asyncio.to_thread(self._get_page_info_sync)

    def close(self):
        """关闭浏览器"""
        if self.page:
            self.page.close()
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        logger.info("Browser closed")

    def _execute_script_sync(self, script: str):
        """同步执行脚本（内部方法）"""
        return self.page.evaluate(script)

    async def execute_script(self, script: str):
        """异步执行脚本"""
        return await asyncio.to_thread(self._execute_script_sync, script)

    # 同步方法保持不变，供非异步调用使用
    def sync_fill_input(self, selector: str, value: str):
        self.page.fill(selector, value)
        logger.debug(f"Filled input {selector} with value")

    def sync_click_element(self, selector: str):
        self.page.click(selector)
        logger.debug(f"Clicked element {selector}")

    def sync_select_option(self, selector: str, value: str):
        self.page.select_option(selector, value)
        logger.debug(f"Selected option {value} in {selector}")

    def sync_wait_for_selector(self, selector: str, timeout: int = 5000):
        self.page.wait_for_selector(selector, timeout=timeout)

    def sync_take_screenshot(self, path: str) -> str:
        screenshot_dir = Path(path).parent
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=path, full_page=True)
        logger.debug(f"Screenshot saved to {path}")
        return path

    def sync_navigate(self, url: str, timeout: int = 60000):
        self.page.goto(url, timeout=timeout, wait_until="commit")
        logger.info(f"Navigated to {url}")
        self.page.wait_for_timeout(5000)


class BrowserPool:
    def __init__(self, size: int = 3):
        self.size = size
        self.browsers: Dict[str, BrowserTool] = {}

    async def get_browser(self, browser_type: str = "chromium") -> BrowserTool:
        """异步获取浏览器实例"""
        key = f"{browser_type}"
        if key not in self.browsers:
            browser = BrowserTool(browser_type)
            await browser.launch()
            self.browsers[key] = browser
        return self.browsers[key]

    def close_all(self):
        for browser in self.browsers.values():
            browser.close()
        self.browsers.clear()


browser_pool = BrowserPool()
