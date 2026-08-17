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
MAX_CONCURRENT = 6


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

    async def _init_context(self, storage_state=None):
        """为当前请求创建独立 Context 和 Page。
        storage_state: 可传文件路径(str)或状态字典，用于恢复登录态。
        """
        ctx_opts = dict(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        if storage_state:
            ctx_opts["storage_state"] = storage_state
        self.context = await self._browser.new_context(**ctx_opts)
        self.page = await self.context.new_page()
        logger.debug(f"New browser context created for {self.browser_type}"
                     + (" (with storage_state)" if storage_state else ""))

    async def navigate(self, url: str, timeout: int = 60000):
        # 根据 URL 自动判断是否是移动端页面，切换 UA
        is_mobile = any(k in url for k in ['/m/', 'm.', '/mobile', '/wap', 'micropage', 'h5'])
        if is_mobile:
            await self.page.emulate_media()
            await self.context.set_extra_http_headers({"User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
            )})

        # SPA / 动态页面优先用 domcontentloaded（不等网络 idle），更快更稳
        # networkidle 对 WebSocket/轮询类应用会一直等，容易超时
        try:
            await self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        except Exception:
            # 兜底：commit（只要收到响应就算，最宽松）
            try:
                await self.page.goto(url, timeout=timeout, wait_until="commit")
            except Exception:
                pass  # 已有部分内容，继续尝试抓取

        logger.info(f"Navigated to {url}")
        # 额外等待 JS 渲染（动态框架通常需要 1-2 秒完成首屏渲染）
        await self.page.wait_for_timeout(2000)

        # 自动滚动页面，触发懒加载内容（需求页面、列表页等常见场景）
        await self._scroll_to_load()

    async def _scroll_to_load(self):
        """分段滚动页面到底部，触发懒加载内容。
        策略：
        - 每步滚动一屏，等待 JS 渲染 + MutationObserver 稳定
        - 检测页面高度变化，有新内容时额外等待
        - 连续 3 步高度不变则认为内容已全部加载
        - 最多滚动 12 屏（覆盖常见长列表/无限滚动页面）
        - 自动检测并等待 Loading 动画消失
        """
        try:
            # ── 智能等待：Loading / 骨架屏消失 ──
            await self._wait_loading_disappear()

            viewport_height = await self.page.evaluate("() => window.innerHeight") or 1080
            page_height     = await self.page.evaluate("() => document.body.scrollHeight")
            current_pos     = 0
            max_scrolls     = 12    # 从 5 增加到 12，覆盖长列表页面
            scroll_count    = 0
            unchanged_count = 0     # 连续高度未变计数

            logger.info(f"开始滚动加载，页面总高度: {page_height}px，视口: {viewport_height}px")

            while scroll_count < max_scrolls:
                next_pos = current_pos + viewport_height
                await self.page.evaluate(f"window.scrollTo({{top: {next_pos}, behavior: 'smooth'}})")

                # 等待 JS 渲染 + DOM 稳定
                await self.page.wait_for_timeout(600)
                await self._wait_dom_stable(timeout=800)

                new_height = await self.page.evaluate("() => document.body.scrollHeight")
                if new_height > page_height:
                    logger.debug(f"页面高度增加 {page_height}→{new_height}px，等待内容稳定...")
                    page_height     = new_height
                    unchanged_count = 0
                    # 新内容较多时，等待更久并再次检查 Loading
                    await self.page.wait_for_timeout(1000)
                    await self._wait_loading_disappear()
                else:
                    unchanged_count += 1

                current_pos   = next_pos
                scroll_count += 1

                # 已滚到底或连续 3 步无新内容 → 结束（从 2 步放宽到 3 步，给懒加载更多机会）
                if current_pos >= page_height or unchanged_count >= 3:
                    break

            logger.info(f"滚动完成，共滚动 {scroll_count} 屏，最终页面高度: {page_height}px")

            # 停在底部等内容稳定，然后回顶
            await self.page.wait_for_timeout(500)
            await self._wait_dom_stable(timeout=800)
            await self.page.evaluate("window.scrollTo(0, 0)")
            await self.page.wait_for_timeout(500)

        except Exception as e:
            logger.warning(f"滚动加载失败（不影响主流程）: {e}")

    async def _wait_loading_disappear(self, timeout: int = 5000):
        """等待页面 Loading 动画 / 骨架屏消失。"""
        try:
            await self.page.evaluate("""
                async (timeout) => {
                    const start = Date.now();
                    const checkInterval = 300;
                    const loaders = [
                        '[class*="loading"]', '[class*="spinner"]', '[class*="Loading"]',
                        '[class*="skeleton"]', '[class*="Skeleton"]', '[class*="mask"]',
                        '.el-loading-mask', '.ant-spin', '.n-spin', '.van-loading',
                        '[role="progressbar"]', '.loading-text', '.loader'
                    ];
                    while (Date.now() - start < timeout) {
                        let allHidden = true;
                        for (const sel of loaders) {
                            try {
                                const els = document.querySelectorAll(sel);
                                for (const el of els) {
                                    const style = window.getComputedStyle(el);
                                    const visible = el.offsetParent !== null &&
                                        style.display !== 'none' &&
                                        style.visibility !== 'hidden' &&
                                        parseFloat(style.opacity) > 0.1;
                                    if (visible) { allHidden = false; break; }
                                }
                            } catch(e) { /* ignore invalid selectors */ }
                            if (!allHidden) break;
                        }
                        if (allHidden) break;
                        await new Promise(r => setTimeout(r, checkInterval));
                    }
                }
            """, timeout)
        except Exception as e:
            logger.debug(f"等待 Loading 消失时出错（不影响主流程）: {e}")

    async def _wait_dom_stable(self, timeout: int = 1000):
        """通过 MutationObserver 等待 DOM 稳定（无新增节点）。"""
        try:
            await self.page.evaluate(f"""
                async (timeout) => {{
                    const start = Date.now();
                    let lastChange = start;
                    const observer = new MutationObserver(() => {{ lastChange = Date.now(); }});
                    observer.observe(document.body, {{
                        childList: true, subtree: true,
                        attributes: false, characterData: false
                    }});
                    while (Date.now() - start < timeout) {{
                        await new Promise(r => setTimeout(r, 200));
                        if (Date.now() - lastChange > 200) break;  // 200ms 无变化则稳定
                    }}
                    observer.disconnect();
                }}
            """, timeout)
        except Exception as e:
            logger.debug(f"等待 DOM 稳定时出错（不影响主流程）: {e}")

    async def capture_elements(self) -> List[Dict[str, Any]]:
        """抓取页面交互元素 + 语义文字节点。
        优化：
        - 抓取前智能等待 Loading 消失 + DOM 稳定
        - 选择器优先级：data-testid > id > aria-label > name > placeholder > class > tag
        - 过滤不可见/全屏容器元素
        - 语义文字节点始终追加
        - 交互元素 < 8 时自动重试（放宽阈值）
        """
        # ── 抓取前：等待页面就绪 ──
        await self._wait_loading_disappear()
        await self._wait_dom_stable(timeout=1200)

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
            const viewW = window.innerWidth;
            const viewH = window.innerHeight;
            const interactiveTags = ['input', 'button', 'a', 'select', 'textarea', 'option', 'table', 'img', 'iframe'];

            // ── Selector 生成（优先级：data-testid > id > aria-label > name > placeholder > class > tag）──
            function get_selector(el) {
                const testId = el.getAttribute('data-testid');
                if (testId) return `[data-testid="${testId}"]`;

                if (el.id && !/^\\d/.test(el.id)) return `#${CSS.escape(el.id)}`;

                const ariaLabel = el.getAttribute('aria-label');
                if (ariaLabel) return `${el.tagName.toLowerCase()}[aria-label="${ariaLabel}"]`;

                if (el.name) return `${el.tagName.toLowerCase()}[name="${el.name}"]`;

                const ph = el.getAttribute('placeholder');
                if (ph) return `${el.tagName.toLowerCase()}[placeholder="${ph}"]`;

                if (el.className && typeof el.className === 'string') {
                    const cls = el.className.trim().split(/\\s+/).filter(c => c && !/^(active|hover|focus|selected|disabled)$/i.test(c)).slice(0, 2).join('.');
                    if (cls) return `${el.tagName.toLowerCase()}.${cls}`;
                }

                return el.tagName.toLowerCase();
            }

            // ── 收集单个文档内的交互元素（frameSelectors 为当前 frame 路径）──
            function scanDoc(doc, frameSelectors) {
                const out = [];

                // 第一批：真正的交互元素
                doc.querySelectorAll(interactiveTags.join(',')).forEach(el => {
                    const tag = el.tagName.toLowerCase();
                    const rect = el.getBoundingClientRect();

                    // 跳过不可见元素
                    if (rect.width <= 0 || rect.height <= 0) return;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) < 0.1) return;

                    // 跳过全屏容器 (div/span > 80%视口)
                    if (rect.width > viewW * 0.8 && rect.height > viewH * 0.8) return;

                    const type = el.type || '';
                    const role = el.getAttribute('role') || '';
                    const id = el.id || '';
                    const name = el.name || '';
                    const text = (el.innerText || el.value || '').trim();
                    const placeholder = el.placeholder || '';
                    const href = el.href || '';

                    out.push({
                        tag, type, role, id, name,
                        text: text.substring(0, 100),
                        placeholder, href,
                        x: rect.x, y: rect.y,
                        width: rect.width, height: rect.height,
                        selector: get_selector(el),
                        frame_selectors: frameSelectors
                    });
                });

                // 第二批：有交互属性的 div/span/li
                doc.querySelectorAll('div, span, li').forEach(el => {
                    const hasInteraction =
                        el.getAttribute('role') === 'button' ||
                        el.hasAttribute('tabindex') ||
                        el.hasAttribute('onclick') ||
                        el.hasAttribute('data-testid') ||
                        el.hasAttribute('data-action') ||
                        el.className && (
                            el.className.includes('btn') ||
                            el.className.includes('click') ||
                            el.className.includes('tab') ||
                            el.className.includes('menu') ||
                            el.className.includes('card') ||
                            el.className.includes('item')
                        );

                    if (!hasInteraction) return;

                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return;

                    const tag = el.tagName.toLowerCase();
                    const text = (el.innerText || '').trim();
                    if (!text) return;  // 无文本的交互 div 不收录

                    out.push({
                        tag, type: '', role: el.getAttribute('role') || '',
                        id: el.id || '', name: el.getAttribute('data-testid') || '',
                        text: text.substring(0, 100),
                        placeholder: '', href: '',
                        x: rect.x, y: rect.y,
                        width: rect.width, height: rect.height,
                        selector: get_selector(el),
                        frame_selectors: frameSelectors
                    });
                });

                return out;
            }

            // ── 递归遍历同源 iframe（跨域 contentDocument 访问会抛异常/为 null，跳过）──
            function collectFrames(doc, frameSelectors) {
                const collected = scanDoc(doc, frameSelectors);
                doc.querySelectorAll('iframe').forEach(iframeEl => {
                    try {
                        const innerDoc = iframeEl.contentDocument;
                        if (!innerDoc) return;
                        const fs = get_selector(iframeEl);
                        const child = collectFrames(innerDoc, frameSelectors.concat([fs]));
                        for (const c of child) collected.push(c);
                    } catch (e) {
                        // 跨域 iframe：忽略
                    }
                });
                return collected;
            }

            const elements = collectFrames(document, []);

            // ── 去重：frame 路径 + selector + text → 只保留可见的 ──
            const seen = new Map();
            const deduped = [];
            for (const el of elements) {
                const key = (el.frame_selectors || []).join('>>') + '|' + el.selector + '|' + el.text;
                const existing = seen.get(key);
                if (existing) {
                    // 保留面积更大或位置更靠上的
                    if (el.width * el.height > existing.width * existing.height) {
                        deduped[deduped.indexOf(existing)] = el;
                        seen.set(key, el);
                    }
                } else {
                    seen.set(key, el);
                    deduped.push(el);
                }
            }

            return deduped;
        }
        """
        elements = await self.page.evaluate(elements_script)
        logger.info(f"Captured {len(elements)} interactive elements")

        # 元素太少说明页面还没渲染完，等待后重试（阈值从 5 提高到 8）
        if len(elements) < 8:
            logger.warning(f"Too few elements ({len(elements)}), waiting 3s and retrying...")
            await self.page.wait_for_timeout(3000)
            await self._wait_loading_disappear()
            await self._wait_dom_stable(timeout=1200)
            elements = await self.page.evaluate(elements_script)
            logger.info(f"Retry 1 captured {len(elements)} interactive elements")

        if len(elements) < 5:
            logger.warning(f"Still too few ({len(elements)}), waiting 5s more and retrying...")
            await self.page.wait_for_timeout(5000)
            elements = await self.page.evaluate(elements_script)
            logger.info(f"Retry 2 captured {len(elements)} interactive elements")

        # ── 补充文字内容节点（h/p/li/label/strong 等）──────────────────────────
        # 始终追加页面文字节点作为语义补充。
        # 对于内容型页面（如电商、SaaS 后台等），页面的文字信息是 AI 生成用例的关键输入。
        logger.info("补充抓取页面文字节点（语义增强）...")
        text_script = """
        () => {
            const texts = [];
            const textTags = ['h1','h2','h3','h4','h5','h6','p','li','td','th','label','strong','dt','dd','span'];
            document.querySelectorAll(textTags.join(',')).forEach(el => {
                const t = (el.innerText || '').trim();
                if (t.length > 3 && t.length < 500) {
                    texts.push({
                        tag: el.tagName.toLowerCase(),
                        text: t.substring(0, 200),
                        type: '', role: '', id: el.id || '', name: '',
                        placeholder: '', href: '',
                        x: 0, y: 0, width: 100, height: 20,
                        selector: el.tagName.toLowerCase()
                    });
                }
            });
            // 去重（相同文本只保留一条）
            const seen = new Set();
            return texts.filter(t => {
                if (seen.has(t.text)) return false;
                seen.add(t.text); return true;
            }).slice(0, 300);  // 最多300条文字节点
        }
        """
        text_elements = await self.page.evaluate(text_script)
        logger.info(f"补充文字节点: {len(text_elements)} 条")
        elements = elements + text_elements

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

    async def acquire(self, browser_type: str = "chromium", storage_state=None) -> "BrowserTool":
        """
        获取一个独立 Context 的 BrowserTool 实例。
        storage_state: 文件路径或状态字典，用于恢复登录态（方案三）。
        调用方必须在使用完毕后调用 release(bt) 或使用 async with 语法。
        """
        await self._semaphore.acquire()
        try:
            browser = await self._ensure_browser(browser_type)
            bt = BrowserTool(browser, browser_type)
            await bt._init_context(storage_state=storage_state)
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
