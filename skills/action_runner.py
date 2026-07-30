"""
ActionRunner — 确定性 WebUI 执行引擎（方案C）

将 TestCase.steps_json 中的 ActionStep 列表逐步路由到
Playwright 对应 API 执行，支持：
  - 变量替换：{{key}} → TaskEnvVar 表中的值
  - 断言验证：assert_* 类型步骤失败时记录截图并标记失败
  - 步骤级耗时和错误记录
  - optional=True 的步骤失败后继续执行

使用示例：
    runner = ActionRunner(task_id=1, db_session=session)
    await runner.load_env_vars()
    result = await runner.run_case(case_dict, page)
"""
import re
import time
import asyncio
from pathlib import Path
from typing import Optional

from loguru import logger

# Playwright 异步 API
try:
    from playwright.async_api import Page, expect, Error as PlaywrightError
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    PlaywrightError = Exception

from tools.action_schema import validate_step

# 截图保存目录
SCREENSHOT_DIR = Path("reports/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ── 执行结果数据结构 ──────────────────────────────────────────────────────────

def _step_result(step: dict, passed: bool, error: str = "", duration_ms: float = 0,
                 screenshot: str = "") -> dict:
    return {
        "id":           step.get("id", ""),
        "action":       step.get("action", ""),
        "description":  step.get("description", ""),
        "selector":     step.get("selector", ""),
        "value":        step.get("value", ""),
        "url":          step.get("url", ""),
        "expected":     step.get("expected", ""),
        "passed":       passed,
        "error":        error,
        "duration_ms":  round(duration_ms, 1),
        "screenshot":   screenshot,
    }


def _case_result(case: dict, step_results: list, browser: str = "chromium") -> dict:
    total   = len(step_results)
    passed  = sum(1 for s in step_results if s["passed"])
    failed  = total - passed
    ok      = failed == 0
    return {
        "case_id":    case.get("id"),
        "case_name":  case.get("name", ""),
        "status":     "passed" if ok else "failed",
        "browser":    browser,
        "total":      total,
        "passed":     passed,
        "failed":     failed,
        "steps":      step_results,
    }


# ── 变量替换 ──────────────────────────────────────────────────────────────────

def resolve_vars(text: str, env: dict) -> str:
    """将 {{key}} 替换为 env 中的值；未找到的 key 保留原样。"""
    if not text or "{{" not in text:
        return text
    return re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: str(env.get(m.group(1), m.group(0))),
        text,
    )


# ── 主执行引擎 ────────────────────────────────────────────────────────────────

class ActionRunner:
    """按 ActionStep 列表驱动 Playwright Page 执行 WebUI 用例。"""

    def __init__(self, task_id: int, db_session=None, browser: str = "chromium"):
        self.task_id    = task_id
        self.db         = db_session
        self.browser    = browser
        self.env_vars: dict = {}

    async def load_env_vars(self) -> None:
        """从数据库加载任务级环境变量到 self.env_vars。"""
        if self.db is None:
            return
        try:
            from sqlalchemy import text
            rows = await self.db.execute(
                text("SELECT key, value FROM task_env_vars WHERE task_id = :tid"),
                {"tid": self.task_id},
            )
            self.env_vars = {r.key: r.value for r in rows.fetchall()}
            logger.debug(f"[ActionRunner] task={self.task_id} 加载 {len(self.env_vars)} 个环境变量")
        except Exception as e:
            logger.warning(f"[ActionRunner] 加载环境变量失败: {e}")

    def _rv(self, text: str) -> str:
        """快捷方法：对字段做变量替换。"""
        return resolve_vars(text, self.env_vars)

    async def run_case(self, case: dict, page: "Page") -> dict:
        """执行单条用例，返回 case_result 字典。"""
        steps: list = case.get("steps_json") or []
        if not steps:
            logger.warning(f"[ActionRunner] case={case.get('id')} steps_json 为空，跳过")
            return _case_result(case, [], self.browser)

        step_results = []
        for step in steps:
            ok, err = validate_step(step)
            if not ok:
                step_results.append(_step_result(step, False, f"步骤定义错误: {err}"))
                if not step.get("optional"):
                    break
                continue

            sr = await self._run_step(step, page)
            step_results.append(sr)

            if not sr["passed"] and not step.get("optional"):
                logger.info(
                    f"[ActionRunner] case={case.get('id')} 步骤 {step.get('id')} "
                    f"(action={step.get('action')}) 失败，终止"
                )
                break

        return _case_result(case, step_results, self.browser)

    async def _run_step(self, step: dict, page: "Page") -> dict:
        """执行单个步骤，返回 step_result 字典。支持 selectors 多候选回退。"""
        action   = step.get("action", "")
        selector = self._rv(step.get("selector", ""))
        value    = self._rv(step.get("value", ""))
        url      = self._rv(step.get("url", ""))
        expected = self._rv(str(step.get("expected", "")))
        timeout  = int(step.get("timeout", 10000))
        t0       = time.monotonic()
        screenshot_path = ""

        # 对需要 selector 的交互动作，尝试多候选 selector 自动回退
        _interact_actions = {"click", "fill", "type", "select", "check", "uncheck",
                              "hover", "dblclick", "rightclick", "submit",
                              "assert_text", "assert_visible", "assert_hidden", "assert_count"}
        selectors_to_try = step.get("selectors") or ([selector] if selector else [])

        if action in _interact_actions and len(selectors_to_try) > 1:
            used_selector = selector
            for _sel in selectors_to_try:
                try:
                    await page.wait_for_selector(_sel, state="attached", timeout=2000)
                    used_selector = _sel
                    break
                except Exception:
                    continue
            selector = used_selector

        try:
            await self._dispatch(action, page, selector, value, url, expected, timeout)
            duration = (time.monotonic() - t0) * 1000
            return _step_result(step, True, duration_ms=duration)

        except Exception as e:
            duration = (time.monotonic() - t0) * 1000
            # 失败时自动截图
            try:
                fname = f"step_{step.get('id', 'unknown')}_{int(time.time())}.png"
                spath = SCREENSHOT_DIR / fname
                await page.screenshot(path=str(spath))
                screenshot_path = str(spath)
            except Exception:
                pass
            return _step_result(step, False,
                                 error=str(e),
                                 duration_ms=duration,
                                 screenshot=screenshot_path)

    async def _dispatch(self, action: str, page: "Page",
                        selector: str, value: str, url: str,
                        expected: str, timeout: int) -> None:
        """按 action 类型路由到 Playwright 调用。"""
        kw = {"timeout": timeout}

        if action == "navigate":
            # domcontentloaded 更适合 SPA，networkidle 在 SPA 中极易超时
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            except Exception:
                # 如果连 domcontentloaded 也超时（如离线应用），宽松重试一次
                await page.goto(url, wait_until="commit", timeout=timeout)

        elif action == "click":
            await page.click(selector, **kw)

        elif action == "fill":
            await page.fill(selector, value, timeout=timeout)

        elif action == "type":
            await page.locator(selector).type(value, timeout=timeout)

        elif action == "select":
            await page.select_option(selector, value, timeout=timeout)

        elif action == "check":
            await page.check(selector, **kw)

        elif action == "uncheck":
            await page.uncheck(selector, **kw)

        elif action == "hover":
            await page.hover(selector, **kw)

        elif action == "press":
            await page.keyboard.press(value)

        elif action == "scroll":
            if selector:
                await page.locator(selector).scroll_into_view_if_needed(timeout=timeout)
            else:
                await page.mouse.wheel(0, 500)

        elif action == "upload":
            await page.set_input_files(selector, value.split(","), timeout=timeout)

        elif action == "wait_for":
            if url:
                await page.wait_for_url(url, timeout=timeout)
            elif value:
                await page.wait_for_function(value, timeout=timeout)
            else:
                await page.wait_for_selector(selector, timeout=timeout)

        elif action == "assert_text":
            await expect(page.locator(selector)).to_have_text(
                re.compile(expected) if expected.startswith("/") else expected,
                timeout=timeout,
            )

        elif action == "assert_visible":
            await expect(page.locator(selector)).to_be_visible(timeout=timeout)

        elif action == "assert_hidden":
            await expect(page.locator(selector)).to_be_hidden(timeout=timeout)

        elif action == "assert_url":
            pattern = re.compile(expected) if expected.startswith("/") else expected
            await expect(page).to_have_url(pattern, timeout=timeout)

        elif action == "assert_title":
            pattern = re.compile(expected) if expected.startswith("/") else expected
            await expect(page).to_have_title(pattern, timeout=timeout)

        elif action == "assert_count":
            await expect(page.locator(selector)).to_have_count(int(expected), timeout=timeout)

        elif action == "screenshot":
            fname = value or f"checkpoint_{int(time.time())}.png"
            if not fname.endswith(".png"):
                fname += ".png"
            await page.screenshot(path=str(SCREENSHOT_DIR / fname))

        elif action == "evaluate":
            await page.evaluate(value)

        elif action == "dblclick":
            await page.dblclick(selector, **kw)

        elif action == "rightclick":
            await page.locator(selector).click(button="right", timeout=timeout)

        elif action == "submit":
            # 优先 dispatch submit 事件，再 fallback 到 click
            try:
                await page.locator(selector).dispatch_event("submit")
            except Exception:
                await page.click(selector, timeout=timeout)

        elif action == "keydown":
            # value 字段存按键名（recorder.py 里 push 时传的 key）
            key = value or "Enter"
            try:
                if selector and selector != "body":
                    await page.locator(selector).press(key)
                else:
                    await page.keyboard.press(key)
            except Exception:
                await page.keyboard.press(key)

        elif action == "wait":
            # enrich_recorded_steps 插入的固定等待步骤
            # value 可能是 "" 或数字字符串；timeout 已由调用方解析好
            raw = str(value or "").strip()
            ms = int(raw) if raw.isdigit() else timeout
            await asyncio.sleep(ms / 1000)

        else:
            raise ValueError(f"未知 action 类型: {action!r}")
