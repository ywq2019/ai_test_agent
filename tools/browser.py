"""
Playwright浏览器控制工具
"""
from typing import List, Dict, Optional, Any
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
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

    async def launch(self, headless: bool = True):
        """启动浏览器"""
        self.playwright = await async_playwright().start()
        browser_map = {
            "chromium": self.playwright.chromium,
            "firefox": self.playwright.firefox,
            "webkit": self.playwright.webkit
        }
        browser_class = browser_map.get(self.browser_type, self.playwright.chromium)
        self.browser = await browser_class.launch(headless=headless)
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self.page = await self.context.new_page()
        logger.info(f"Browser {self.browser_type} launched")
        return self

    async def navigate(self, url: str, timeout: int = 60000):
        """导航到URL"""
        await self.page.goto(url, timeout=timeout, wait_until="commit")
        logger.info(f"Navigated to {url}")
        await self.page.wait_for_timeout(5000)

    async def capture_elements(self) -> List[Dict[str, Any]]:
        """捕获页面元素"""
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

                // 过滤掉大容器（宽高超过视口 80% 的 div/span 通常是布局容器，无测试价值）
                const viewW = window.innerWidth;
                const viewH = window.innerHeight;
                const isLargeContainer = (tag === 'div' || tag === 'span') &&
                    rect.width > viewW * 0.8 && rect.height > viewH * 0.8;

                if (rect.width > 0 && rect.height > 0 && !isLargeContainer) {
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
        elements = await self.page.evaluate(elements_script)
        logger.info(f"Captured {len(elements)} interactive elements")
        return elements

    async def fill_input(self, selector: str, value: str):
        """填充输入框"""
        await self.page.fill(selector, value)
        logger.debug(f"Filled input {selector} with value")

    async def click_element(self, selector: str):
        """点击元素"""
        await self.page.click(selector)
        logger.debug(f"Clicked element {selector}")

    async def select_option(self, selector: str, value: str):
        """选择选项"""
        await self.page.select_option(selector, value)
        logger.debug(f"Selected option {value} in {selector}")

    async def take_screenshot(self, path: str) -> str:
        """截图"""
        screenshot_dir = Path(path).parent
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=path, full_page=True)
        logger.debug(f"Screenshot saved to {path}")
        return path

    async def wait_for_selector(self, selector: str, timeout: int = 5000):
        """等待选择器"""
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def get_page_info(self) -> Dict[str, Any]:
        """获取页面信息"""
        return {
            "title": await self.page.title(),
            "url": self.page.url,
            "content": await self.page.content()
        }

    async def execute_script(self, script: str):
        """执行脚本"""
        return await self.page.evaluate(script)

    async def close(self):
        """关闭浏览器"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser closed")


class BrowserPool:
    def __init__(self, size: int = 3):
        self.size = size
        self.browsers: Dict[str, BrowserTool] = {}

    async def get_browser(self, browser_type: str = "chromium", headless: bool = True) -> BrowserTool:
        """获取浏览器实例"""
        key = f"{browser_type}"
        if key not in self.browsers:
            browser = BrowserTool(browser_type)
            await browser.launch(headless=headless)
            self.browsers[key] = browser
        return self.browsers[key]

    async def close_all(self):
        for browser in self.browsers.values():
            await browser.close()
        self.browsers.clear()


browser_pool = BrowserPool()
