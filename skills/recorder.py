"""
Recorder — 基于 Playwright 的有头浏览器录制器（方案C）

工作流程：
  1. start_recording(session_id, url, browser_type) — 启动有头浏览器，注入 JS 事件钩子
  2. 用户在浏览器里操作，Python 侧通过轮询 page.evaluate 收集捕获的事件
  3. 每个事件转换为 ActionStep，通过 ws_callback 实时推送到前端预览
  4. stop_recording(session_id) — 关闭浏览器，返回完整 ActionStep 列表
  5. 调用方再把 steps 写入 TestCase.steps_json

Selector 优先级：data-testid > id > name > aria-label > CSS 路径
"""
import asyncio
import uuid
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

try:
    from playwright.async_api import async_playwright, Browser, Page
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

from tools.action_schema import make_step

# ── 注入到页面的录制脚本 ──────────────────────────────────────────────────────
# 监听 click / input / change / submit 事件，生成最优 selector，存入 window.__recEvents
_RECORD_JS = """
(function() {
  if (window.__recInited) return;
  window.__recInited = true;
  window.__recEvents = [];
  var _stepIdx = 0;

  function bestSelectors(el) {
    if (!el || el === document.body) return ['body'];
    var list = [];
    // data-testid
    if (el.dataset && el.dataset.testid) list.push('[data-testid="' + el.dataset.testid + '"]');
    // id
    if (el.id && !/^\\d/.test(el.id)) list.push('#' + CSS.escape(el.id));
    // name
    if (el.name) list.push('[name="' + el.name + '"]');
    // aria-label
    if (el.getAttribute('aria-label')) list.push('[aria-label="' + el.getAttribute('aria-label') + '"]');
    // placeholder
    if (el.placeholder) list.push(el.tagName.toLowerCase() + '[placeholder="' + el.placeholder + '"]');
    // type=submit/button
    if (el.type && ['submit','button','reset'].indexOf(el.type)>=0) list.push(el.tagName.toLowerCase()+'[type="'+el.type+'"]');
    // text content
    var text = (el.textContent || el.value || '').trim().slice(0,50).replace(/"/g,'\\\\"');
    if (text) {
      var tag = el.tagName.toLowerCase();
      if (tag==='a'||tag==='button'||el.getAttribute('role')==='button'||el.getAttribute('role')==='link') {
        list.push(tag+':has-text("'+text+'")');
      }
    }
    // semantic class
    if (el.className && typeof el.className==='string') {
      var cls = el.className.trim().split(/\\s+/).filter(function(c){ return c && !/^[a-f0-9]{6,}$/i.test(c) && !/^[a-z]+-[a-f0-9]{4,}$/i.test(c); });
      if (cls.length>0) list.push(el.tagName.toLowerCase()+'.'+cls[0]);
    }
    // tag fallback
    if (list.length===0) list.push(el.tagName.toLowerCase());
    return list.length>0 ? list : [el.tagName.toLowerCase()];
  }
  
  function bestSelector(el) {
    return bestSelectors(el)[0] || el.tagName.toLowerCase();
  }

  function push(action, data) {
    var sel = bestSelector(data.el || null);
    var sels = data.el ? bestSelectors(data.el) : [sel];
    var entry = { action: action, selector: sel, selectors: sels, description: data.description || '', value: data.value || '', url: window.location.href, timestamp: Date.now() };
    if (action==='fill' || action==='select') entry.value = data.value || '';
    if (data.optional) entry.optional = true;
    if (data.key) entry.key = data.key;
    window.__recEvents = window.__recEvents || [];
    window.__recEvents.push(entry);
  }

  // ── Click ──
  document.addEventListener('click', function(e) {
    var el = e.target;
    var tag = el.tagName ? el.tagName.toLowerCase() : '';
    if (tag === 'select' || tag === 'textarea') return;
    // 只跳过文本类 input，保留 submit/button/reset/image 等可点击类型
    if (tag === 'input') {
      var skipTypes = ['text','password','email','number','tel','url','search','date','time','datetime-local','month','week','color','range','hidden'];
      if (!el.type || skipTypes.indexOf(el.type) >= 0) return;
    }
    push('click', { el: el, description: '点击 ' + ((el.value || el.textContent || '').trim().slice(0, 30)) });
  }, true);

  // ── Double-click ──
  document.addEventListener('dblclick', function(e) {
    var el = e.target;
    push('dblclick', { el: el, description: '双击 ' + (el.textContent || '').trim().slice(0, 30) });
  }, true);

  // ── Hover (debounced, 300ms) ──
  var _hoverTimer = null;
  var _lastHoverEl = null;
  document.addEventListener('mouseover', function(e) {
    var el = e.target;
    if (!el || !el.tagName) return;
    var tag = el.tagName.toLowerCase();
    // 只记录有交互意义的元素：a, button, [role], [onclick], [data-*]
    if (tag !== 'a' && tag !== 'button'
        && !el.hasAttribute('role') && !el.hasAttribute('onclick')
        && !Array.from(el.attributes).some(function(a){ return a.name.startsWith('data-'); })) {
      return;
    }
    if (_lastHoverEl === el) return;
    _lastHoverEl = el;
    if (_hoverTimer) clearTimeout(_hoverTimer);
    _hoverTimer = setTimeout(function() {
      push('hover', { el: _lastHoverEl, description: '悬停 ' + (_lastHoverEl.textContent || '').trim().slice(0, 30) });
      _lastHoverEl = null;
    }, 300);
  }, true);

  // ── Key press (Enter, Tab, Escape) ──
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) {
      push('keydown', { el: e.target, key: 'Enter', description: '按 Enter 键' });
    }
    if (e.key === 'Tab') {
      push('keydown', { el: e.target, key: 'Tab', description: '按 Tab 键切换焦点' });
    }
    if (e.key === 'Escape') {
      push('keydown', { el: e.target, key: 'Escape', description: '按 Escape 键关闭弹窗' });
    }
  }, true);

  // ── Right-click / Context menu ──
  document.addEventListener('contextmenu', function(e) {
    var el = e.target;
    push('rightclick', { el: el, description: '右键菜单' });
  }, true);

  // ── Change (select, checkbox, file) ──
  document.addEventListener('change', function(e) {
    var el = e.target;
    var tag = el.tagName ? el.tagName.toLowerCase() : '';
    if (tag === 'select') {
      push('select', { el: el, value: el.value, description: '选择 ' + el.value });
    } else if (el.type === 'checkbox') {
      push(el.checked ? 'check' : 'uncheck', { el: el, description: (el.checked?'勾选':'取消勾选') });
    } else if (el.type === 'file') {
      push('upload', { el: el, value: '', description: '上传文件' });
    }
  }, true);

  // ── Input (text, textarea, password, etc.) ──
  document.addEventListener('input', function(e) {
    var el = e.target;
    var tag = el.tagName ? el.tagName.toLowerCase() : '';
    if ((tag === 'input' && el.type !== 'checkbox' && el.type !== 'file' && el.type !== 'radio') || tag === 'textarea') {
      // 去重：若最后一个事件也是同一个 selector 的 fill，更新 value 而不新增
      var last = window.__recEvents[window.__recEvents.length - 1];
      if (last && last.action === 'fill' && last.selector === bestSelector(el)) {
        last.value = el.value;
        // 同步更新 description 中的值（密码字段脱敏）
        last.description = '填写 ' + (el.placeholder || el.name || 'input') + ' = ' + (el.type === 'password' ? '***' : el.value);
        return;
      }
      var displayedValue = el.type === 'password' ? '***' : el.value;
      push('fill', { el: el, value: el.value, description: '填写 ' + (el.placeholder || el.name || 'input') + ' = ' + displayedValue });
    }
  }, true);

  // ── Form submit ──
  document.addEventListener('submit', function(e) {
    var el = e.target;
    push('submit', { el: el, description: '提交表单' });
  }, true);

  // Scroll (debounce 500ms, only record significant scrolls >200px)
  var _scrollTimer = null;
  var _lastScrollY = 0;
  window.addEventListener('scroll', function() {
    if (_scrollTimer) clearTimeout(_scrollTimer);
    _scrollTimer = setTimeout(function() {
      var dy = Math.abs(window.scrollY - _lastScrollY);
      if (dy > 200) {
        _lastScrollY = window.scrollY;
        push('scroll', { el: document.body, value: String(window.scrollY), description: '滚动页面到 y=' + window.scrollY });
      }
    }, 500);
  }, true);

  // Modal/Dialog close via click-outside
  document.addEventListener('click', function(e) {
    var el = e.target;
    if (el.classList && (el.classList.contains('el-overlay') || el.classList.contains('ant-modal-mask') || el.classList.contains('modal-backdrop') || el.classList.contains('overlay'))) {
      push('click', { el: el, description: '关闭弹窗/遮罩' });
    }
  }, true);

  // ── URL 变化（SPA 路由 / 表单提交跳转）──
  var _lastUrl = location.href;
  var _navObserver = new MutationObserver(function() {
    if (location.href !== _lastUrl) {
      push('navigate', { url: location.href, description: '导航到 ' + location.href });
      _lastUrl = location.href;
    }
  });
  _navObserver.observe(document, { subtree: true, childList: true });

  // ── 也监听 popstate / hashchange（SPA 路由）──
  window.addEventListener('popstate', function() {
    if (location.href !== _lastUrl) {
      push('navigate', { url: location.href, description: 'SPA 导航到 ' + location.href });
      _lastUrl = location.href;
    }
  });
  window.addEventListener('hashchange', function() {
    if (location.href !== _lastUrl) {
      push('navigate', { url: location.href, description: 'Hash 导航到 ' + location.href });
      _lastUrl = location.href;
    }
  });
  // ── 页面即将卸载时，标记事件待刷新（防止表单提交后整页跳转丢事件）──
  var _hasUnflushed = false;
  window.addEventListener('beforeunload', function() {
    _hasUnflushed = true;
    // 将导航事件也写入（以防轮询未及时拉取）
    if (location.href !== _lastUrl) {
      push('navigate', { url: location.href, description: '导航到 ' + location.href });
      _lastUrl = location.href;
    }
  });
})();
"""

# ── 会话管理 ──────────────────────────────────────────────────────────────────
_sessions: dict = {}   # session_id → RecordingSession


class RecordingSession:
    def __init__(self, session_id: str, task_id: int, url: str,
                 browser_type: str = "chromium",
                 ws_callback: Optional[Callable] = None):
        self.session_id   = session_id
        self.task_id      = task_id
        self.url          = url
        self.browser_type = browser_type
        self.ws_callback  = ws_callback   # async fn(dict) 推送到前端
        self.steps: list  = []
        self.status       = "idle"        # idle / recording / stopped
        self._browser     = None
        self._page        = None
        self._poll_task   = None
        self._pw          = None


async def start_recording(task_id: int, url: str,
                          browser_type: str = "chromium",
                          ws_callback: Optional[Callable] = None,
                          session_id: Optional[str] = None) -> str:
    """启动有头浏览器，注入录制脚本，开始轮询事件。返回 session_id。"""
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("playwright 未安装，请运行 pip install playwright && playwright install")

    if not session_id:
        session_id = str(uuid.uuid4())[:8]
    session = RecordingSession(session_id, task_id, url, browser_type, ws_callback)
    _sessions[session_id] = session
    logger.info(f"[Recorder] session={session_id} 会话已创建")

    # 先推送一个 navigate 步骤（起始 URL）
    session.steps.append(make_step(
        "navigate",
        step_id="s000",
        url=url,
        description=f"打开 {url}",
    ))

    # 同步尝试启动浏览器，确认能打开后再返回
    logger.info(f"[Recorder] session={session_id} 正在启动 Playwright...")
    session._pw = await async_playwright().__aenter__()
    logger.info(f"[Recorder] session={session_id} Playwright 已启动")
    launcher = getattr(session._pw, session.browser_type)
    try:
        logger.info(f"[Recorder] session={session_id} 正在通过 channel=chrome 启动浏览器...")
        browser = await launcher.launch(headless=False, channel="chrome")
        logger.info(f"[Recorder] session={session_id} Chrome 浏览器已启动")
    except Exception as exc1:
        logger.warning(f"[Recorder] session={session_id} Chrome 启动失败: {exc1}, 尝试默认浏览器")
        try:
            browser = await launcher.launch(headless=False)
            logger.info(f"[Recorder] session={session_id} 默认浏览器已启动")
        except Exception as exc2:
            logger.error(f"[Recorder] session={session_id} 浏览器启动完全失败: {exc2}")
            try:
                await session._pw.__aexit__(None, None, None)
            except Exception:
                pass
            _sessions.pop(session_id, None)
            raise RuntimeError(f"无法启动浏览器，请确认已安装 Playwright 浏览器或系统 Chrome: {exc2}")
    session._browser = browser
    logger.info(f"[Recorder] session={session_id} 正在创建新页面...")
    page = await browser.new_page()
    session._page = page
    session.status = "recording"
    logger.info(f"[Recorder] session={session_id} 页面已创建，状态=recording")

    # 导航到目标 URL 并注入录制脚本
    async def _inject(p):
        try:
            await p.evaluate(_RECORD_JS)
        except Exception:
            pass

    page.on("load", lambda: asyncio.create_task(_inject(page)))
    logger.info(f"[Recorder] session={session_id} 正在导航到 {session.url}...")
    try:
        await page.goto(session.url, wait_until="domcontentloaded", timeout=30000)
        logger.info(f"[Recorder] session={session_id} 页面导航成功")
    except Exception as e:
        logger.error(f"[Recorder] session={session_id} 页面导航失败: {e}")
        await browser.close()
        try:
            await session._pw.__aexit__(None, None, None)
        except Exception:
            pass
        _sessions.pop(session_id, None)
        raise RuntimeError(f"无法访问目标 URL {session.url}: {e}")
    await _inject(page)

    # 浏览器已就绪，启动后台轮询并返回
    session._poll_task = asyncio.create_task(_poll_events(session))

    # Auto-timeout after 15 minutes
    async def _auto_cleanup():
        await asyncio.sleep(900)  # 15 minutes
        if session_id in _sessions:
            logger.warning(f"Recording session {session_id} auto-timeout after 15min")
            await stop_recording(session_id)
    asyncio.ensure_future(_auto_cleanup())

    logger.info(f"[Recorder] session={session_id} 录制开始，url={url}")
    return session_id


def _event_to_step(ev: dict, current_len: int) -> Optional[dict]:
    """将 JS 事件对象转换为 ActionStep 字典。"""
    action = ev.get("action", "")
    if not action:
        return None

    step_id = ev.get("id") or f"s{str(current_len + 1).zfill(3)}"
    # keydown 事件的按键名存在 ev["key"]，需要映射到 value 字段
    value = ev.get("key") if action == "keydown" else ev.get("value", "")
    return make_step(
        action,
        step_id=step_id,
        selector=ev.get("selector", ""),
        value=value or "",
        url=ev.get("url", ""),
        expected=ev.get("expected", ""),
        description=ev.get("description", ""),
    )



async def _poll_events(session: RecordingSession) -> None:
    """后台任务：轮询页面事件直到 stop。"""
    _last_known_url = session.url
    try:
        while session.status == "recording":
            await asyncio.sleep(0.2)
            try:
                # ── 检测导航：如果页面 URL 已变化，自动补充 navigate 步骤 ──
                try:
                    current_url = session._page.url
                    if current_url and current_url != _last_known_url:
                        step = make_step(
                            "navigate",
                            step_id=f"s{str(len(session.steps) + 1).zfill(3)}",
                            url=current_url,
                            description=f"导航到 {current_url}",
                        )
                        session.steps.append(step)
                        _last_known_url = current_url
                        if session.ws_callback:
                            try:
                                await session.ws_callback({
                                    "type": "rec_step",
                                    "step": step,
                                    "total": len(session.steps),
                                })
                            except Exception:
                                pass
                        logger.info(f"[Recorder] 检测到导航: {current_url[:80]}")
                        # 重新注入录制脚本到新页面（SPA pushState 路由不触发 load 事件）
                        try:
                            await session._page.evaluate(_RECORD_JS)
                        except Exception as inj_e:
                            logger.debug(f"[Recorder] 重注入脚本失败（可忽略）: {inj_e}")
                except Exception as nav_e:
                    logger.debug(f"[Recorder] URL 检测异常: {nav_e}")

                # ── 拉取 JS 侧事件 ──
                try:
                    new_events = await session._page.evaluate("""
                        () => {
                            var evs = window.__recEvents || [];
                            window.__recEvents = [];
                            return evs;
                        }
                    """)
                    for ev in new_events:
                        step = _event_to_step(ev, len(session.steps))
                        if step:
                            session.steps.append(step)
                            if session.ws_callback:
                                try:
                                    await session.ws_callback({
                                        "type":  "rec_step",
                                        "step":  step,
                                        "total": len(session.steps),
                                    })
                                except Exception:
                                    pass
                except Exception as poll_e:
                    # 页面关闭或正在导航中，属正常情况，debug 级别记录
                    logger.debug(f"[Recorder] 拉取事件异常（页面可能正在跳转）: {poll_e}")

            except Exception as outer_e:
                logger.warning(f"[Recorder] 轮询外层异常: {outer_e}")

        await session._browser.close()
        logger.info(f"[Recorder] session={session.session_id} 浏览器已关闭，共 {len(session.steps)} 步")

    except Exception as e:
        logger.error(f"[Recorder] session={session.session_id} 异常: {e}")
        session.status = "stopped"


async def stop_recording(session_id: str) -> dict:
    """停止录制，返回 {steps, page_elements}，并自动清理会话内存。"""
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"录制会话不存在: {session_id}")

    session.status = "stopped"
    if session._poll_task and not session._poll_task.done():
        try:
            await asyncio.wait_for(session._poll_task, timeout=3.0)
        except (asyncio.TimeoutError, Exception):
            session._poll_task.cancel()

    # Collect page elements snapshot
    page_elements = []
    try:
        if session._page:
            elements_js = """
            (() => {
                const results = [];
                const interactive = document.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"], [onclick], [data-testid]');
                interactive.forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        results.push({
                            tag: el.tagName.toLowerCase(),
                            selector: (el.dataset?.testid ? '[data-testid="'+el.dataset.testid+'"]' :
                                      el.id && !/^\\d/.test(el.id) ? '#'+el.id :
                                      el.name ? '[name="'+el.name+'"]' :
                                      el.placeholder ? el.tagName.toLowerCase()+'[placeholder="'+el.placeholder+'"]' :
                                      el.tagName.toLowerCase()),
                            text: (el.textContent || el.value || el.placeholder || '').trim().slice(0, 60),
                            type: el.type || '',
                            placeholder: el.placeholder || '',
                        });
                    }
                });
                return results;
            })()
            """
            page_elements = await session._page.evaluate(elements_js)
    except Exception:
        pass

    # 关闭 playwright
    try:
        await session._pw.__aexit__(None, None, None)
    except Exception:
        pass

    steps = session.steps[:]
    logger.info(f"[Recorder] session={session_id} 录制停止，返回 {len(steps)} 个步骤，{len(page_elements)} 个页面元素")

    # 停止后立即从字典中移除，防止内存泄漏（路由层无需再调 cleanup_session）
    _sessions.pop(session_id, None)

    return {"steps": steps, "page_elements": page_elements}


def get_session_status(session_id: str) -> dict:
    """获取录制会话状态（供 API 端点轮询）。"""
    session = _sessions.get(session_id)
    if not session:
        return {"status": "not_found", "steps_count": 0}
    return {
        "status":      session.status,
        "steps_count": len(session.steps),
        "steps":       session.steps,
    }


def cleanup_session(session_id: str) -> None:
    """清理已完成的会话，释放内存。"""
    session = _sessions.pop(session_id, None)
    if session:
        try:
            if session._pw:
                import asyncio as _asyncio
                _asyncio.ensure_future(session._pw.__aexit__(None, None, None))
        except Exception:
            pass


def enrich_recorded_steps(steps: list, page_title: str = "") -> list:
    """
    录制后处理：对原始录制步骤进行智能补全。

    补全内容：
    1. 登录表单检测 → 在登录操作后插入断言步骤
    2. 表单提交检测 → 在 submit 后插入成功提示断言
    3. navigatoin 步骤后插入 wait 步骤
    4. 尾部追加结果验证步骤
    """
    if not steps:
        return steps

    enriched = []
    has_login_form = False
    has_username = False
    has_password = False
    last_was_click_on_button = False
    last_button_selector = ""

    for i, step in enumerate(steps):
        enriched.append(step)
        action = step.get("action", "")
        sel = step.get("selector", "")
        desc = step.get("description", "").lower()
        val = step.get("value", "")

        # 检测登录表单特征
        if action == "fill":
            if any(kw in str(sel).lower() + desc for kw in ["user", "账户", "手机", "邮箱", "email", "phone", "tel"]):
                has_username = True
            if any(kw in str(sel).lower() + desc for kw in ["password", "密码", "pass"]):
                has_password = True

        # 检测点击登录按钮
        if action == "click":
            is_login_click = any(kw in desc + str(sel).lower() for kw in ["登录", "login", "signin", "sign in", "登", "提交"])
            is_form_submit = any(kw in desc + str(sel).lower() for kw in ["提交", "submit", "保存", "确认", "确定", "注册"])
            if is_login_click or is_form_submit:
                last_was_click_on_button = True
                last_button_selector = sel

        # 在 submit 后添加断言
        if action == "submit":
            enriched.append(make_step(
                "wait", step_id=f"s{str(len(enriched) + 1).zfill(3)}",
                description="等待页面响应", timeout=5000,
            ))
            # 表单提交成功后通常有提示或跳转
            enriched.append(make_step(
                "assert_visible",
                step_id=f"s{str(len(enriched) + 1).zfill(3)}",
                selector=".el-message, .ant-message, .toast, [role='alert'], .success",
                expected="可见",
                description="断言：页面出现成功提示",
                optional=True,
            ))

        # 检测登录完成模式（用户名 + 密码 + 登录按钮）
        if has_username and has_password and last_was_click_on_button and not has_login_form:
            has_login_form = True
            # 在登录按钮点击后追加断言
            enriched.append(make_step(
                "wait", step_id=f"s{str(len(enriched) + 1).zfill(3)}",
                description="等待登录完成", timeout=3000,
            ))
            enriched.append(make_step(
                "assert_visible",
                step_id=f"s{str(len(enriched) + 1).zfill(3)}",
                selector=".user-info, .avatar, .nickname, [class*='user'], [class*='logout'], [class*='退出']",
                expected="登录成功标识可见",
                description="断言：已成功登录（可见用户信息或退出按钮）",
                optional=True,
            ))

        # 导航后添加 wait
        if action == "navigate" and i > 0:
            enriched.append(make_step(
                "wait", step_id=f"s{str(len(enriched) + 1).zfill(3)}",
                description="等待页面加载完成", timeout=3000,
            ))

    # 尾部追加页面标题断言
    if page_title:
        enriched.append(make_step(
            "assert_title",
            step_id=f"s{str(len(enriched) + 1).zfill(3)}",
            expected=page_title,
            description=f"断言：页面标题为「{page_title}」",
            optional=True,
        ))

    return enriched


def generate_case_name(steps: list, page_title: str = "") -> str:
    """根据录制步骤智能生成用例名称。"""
    actions = [s.get("description", "") for s in steps[:6]]
    actions_text = " → ".join(s[:30] for s in actions if s)

    # 检测关键操作模式
    has_login = any("登录" in str(s) or "login" in str(s).lower() for s in actions)
    has_search = any("搜索" in str(s) or "search" in str(s).lower() for s in actions)
    has_form = any("提交" in str(s) or "submit" in str(s).lower() for s in actions)

    if has_login:
        prefix = "登录流程"
    elif has_search:
        prefix = "搜索功能"
    elif has_form:
        prefix = "表单提交"
    elif page_title:
        prefix = page_title[:15]
    else:
        prefix = "录制操作"

    return f"{prefix} - {len(steps)}步"


def generate_expected_results(steps: list) -> str:
    """根据步骤自动生成预期结果描述。"""
    results = []
    has_login = False
    has_nav = False
    
    for s in steps:
        action = s.get("action", "")
        desc = s.get("description", "")
        
        if action == "fill" and any(kw in str(desc).lower() for kw in ["user", "账户", "手机", "email", "密码", "password"]):
            has_login = True
        if action == "click" and any(kw in str(desc).lower() for kw in ["登录", "login", "signin"]):
            has_login = True
        if action == "navigate":
            has_nav = True

    if has_login:
        results.append("1. 登录成功，页面跳转至首页或显示用户信息")
    if has_nav:
        results.append("2. 目标页面正确加载，关键元素可见")
    
    if not results:
        results.append("1. 所有操作步骤执行成功")
        results.append("2. 页面无明显错误提示")

    return "\n".join(results)
