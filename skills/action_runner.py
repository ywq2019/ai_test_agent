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

# 截图保存目录（必须与 main.py 的 StaticFiles mount 路径一致）
try:
    from tools.config import settings as _settings
    import os as _os
    SCREENSHOT_DIR = Path(_os.path.abspath(_settings.SCREENSHOT_DIR))
except Exception:
    SCREENSHOT_DIR = Path(__file__).parent.parent / "screenshots"
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

    def __init__(self, task_id: int, db_session=None, browser: str = "chromium", should_stop_cb=None):
        self.task_id      = task_id
        self.db           = db_session
        self.browser      = browser
        self.env_vars: dict = {}
        self._alias_map: dict = {}   # name → selectors[]，懒加载
        self.step_callback = None    # async fn(step_info) — 步骤级进度推送
        self._should_stop_cb = should_stop_cb  # Callable[[], bool] — 外部 stop 信号检查

    @staticmethod
    def _build_locator(ctx, selector: str):
        """将 selector 字符串转换为 Playwright Locator。
        支持语义前缀（录制侧生成）：
          role=button[name="提交"]  → ctx.get_by_role("button", name="提交")
          label=用户名              → ctx.get_by_label("用户名")
          alt=logo                  → ctx.get_by_alt_text("logo")
        其余退化为普通 CSS/XPath locator。
        特殊处理：tag:has-text("X") → locator().filter()
        """
        if selector.startswith("role="):
            m = re.match(r'^role=([^\[]+)(?:\[name="([^"]+)"\])?$', selector)
            if m:
                role_name = m.group(1).strip()
                acc_name  = m.group(2)
                if acc_name:
                    return ctx.get_by_role(role_name, name=acc_name)
                return ctx.get_by_role(role_name)
        if selector.startswith("label="):
            return ctx.get_by_label(selector[6:])
        if selector.startswith("alt="):
            return ctx.get_by_alt_text(selector[4:])

        # tag:has-text("X") → locator().filter()
        m = re.match(r'^(\w+):has-text\("([^"]+)"\)$', selector)
        if m:
            tag, text = m.group(1), m.group(2)
            return ctx.locator(tag).filter(has_text=text)

        return ctx.locator(selector)

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

    async def _load_aliases(self) -> None:
        """懒加载元素别名库到 self._alias_map。"""
        if self._alias_map or self.db is None:
            return
        try:
            from sqlalchemy import text
            rows = await self.db.execute(
                text("SELECT name, selectors FROM element_aliases WHERE task_id = :tid"),
                {"tid": self.task_id},
            )
            import json as _j
            for r in rows.fetchall():
                sels = r.selectors if isinstance(r.selectors, list) else _j.loads(r.selectors or "[]")
                self._alias_map[r.name] = sels
            logger.info(f"[ActionRunner] task={self.task_id} 加载 {len(self._alias_map)} 个元素别名: {list(self._alias_map.keys())}")
        except Exception as e:
            logger.warning(f"[ActionRunner] 加载元素别名失败: {e}")

    async def _resolve_alias(self, selector: str, step: dict) -> tuple[str, list]:
        """若 selector 以 @ 开头，从别名库展开为 (primary_selector, selectors[])。
        返回 (selector, selectors_to_try)。
        """
        if not selector.startswith("@"):
            return selector, step.get("selectors") or ([selector] if selector else [])
        alias_name = selector[1:]   # 去掉 @ 前缀
        await self._load_aliases()
        sels = self._alias_map.get(alias_name)
        if sels:
            logger.info(f"[ActionRunner] 别名 @{alias_name} 展开为 {sels}")
            return sels[0], sels
        logger.warning(f"[ActionRunner] 别名 @{alias_name} 未找到(task={self.task_id}, 库中有{list(self._alias_map.keys())})，保留原始 selector")
        return selector, [selector]

    def _rv(self, text: str) -> str:
        """快捷方法：对字段做变量替换。"""
        return resolve_vars(text, self.env_vars)

    async def run_case(self, case: dict, page: "Page") -> dict:
        """执行单条用例，返回 case_result 字典。

        第一阶段支持控制流：扁平 steps_json 先 unflatten 成树，再按树遍历执行
        （if/else、while）；纯线性用例（无控制流关键字）行为与之前完全一致。
        """
        from skills.control_flow import unflatten

        steps: list = case.get("steps_json") or []
        if not steps:
            logger.warning(f"[ActionRunner] case={case.get('id')} steps_json 为空，跳过")
            return _case_result(case, [], self.browser)

        try:
            tree = unflatten(steps)
        except ValueError as e:
            logger.warning(f"[ActionRunner] case={case.get('id')} 控制流配置错误: {e}")
            return _case_result(
                case,
                [_step_result({"action": "if", "description": "控制流解析"}, False, f"控制流配置错误: {e}")],
                self.browser,
            )

        step_results = []
        state = {
            "case":       case,
            "page":       page,
            "results":    step_results,
            "leaf_total": self._count_leaf_steps(tree),
            "leaf_idx":   0,
            "stop":       False,
        }
        await self._run_node(tree, state)
        return _case_result(case, step_results, self.browser)

    @staticmethod
    def _count_leaf_steps(node: dict) -> int:
        """统计树中叶子步骤数（用于进度 total 的静态估计）。"""
        t = node["type"]
        if t == "step":
            return 1
        if t == "root":
            return sum(ActionRunner._count_leaf_steps(c) for c in node.get("children", []))
        if t == "if":
            return max(
                sum(ActionRunner._count_leaf_steps(c) for c in node.get("then", [])),
                sum(ActionRunner._count_leaf_steps(c) for c in node.get("else", [])),
            )
        if t == "while":
            return sum(ActionRunner._count_leaf_steps(c) for c in node.get("body", []))
        return 0

    async def _run_node(self, node: dict, state: dict) -> None:
        """递归执行树节点。"""
        t = node["type"]
        if t == "root":
            for child in node.get("children", []):
                if state["stop"]:
                    break
                await self._run_node(child, state)
        elif t == "step":
            await self._run_step_node(node["step"], state)
        elif t == "if":
            await self._run_if(node, state)
        elif t == "while":
            await self._run_while(node, state)

    async def _run_step_node(self, step: dict, state: dict) -> None:
        """执行单个叶子步骤（原 run_case 循环体的逻辑）。"""
        if state["stop"]:
            return
        case = state["case"]

        # ── 每步骤前检查外部 stop 信号 ──
        if self._should_stop_cb and self._should_stop_cb():
            state["results"].append(_step_result(step, False, "执行被用户停止"))
            state["stop"] = True
            return

        ok, err = validate_step(step)
        if not ok:
            state["results"].append(_step_result(step, False, f"步骤定义错误: {err}"))
            if not step.get("optional"):
                state["stop"] = True
            return

        # 步骤开始前推送进度
        state["leaf_idx"] += 1
        if self.step_callback:
            try:
                await self.step_callback({
                    "type":        "step_start",
                    "case_id":     case.get("id"),
                    "case_name":   case.get("name", ""),
                    "step_idx":    state["leaf_idx"],
                    "step_total":  state["leaf_total"],
                    "action":      step.get("action", ""),
                    "description": step.get("description", "") or step.get("selector", ""),
                })
            except Exception:
                pass

        sr = await self._run_step(step, state["page"])
        state["results"].append(sr)

        if not sr["passed"] and not step.get("optional"):
            logger.info(
                f"[ActionRunner] case={case.get('id')} 步骤 {step.get('id')} "
                f"(action={step.get('action')}) 失败，终止"
            )
            state["stop"] = True

    async def _run_if(self, node: dict, state: dict) -> None:
        """执行 if/else 分支。"""
        from skills.control_flow import ConditionEvaluator
        condition = node.get("condition", "")
        try:
            truthy = await ConditionEvaluator(state["page"]).eval(condition, self.env_vars)
        except Exception as e:
            state["results"].append(_step_result(
                {"action": "if", "condition": condition}, False, f"条件求值失败: {e}"))
            state["stop"] = True
            return

        branch = node.get("then", []) if truthy else node.get("else", [])
        for child in branch:
            if state["stop"]:
                break
            await self._run_node(child, state)

    async def _run_while(self, node: dict, state: dict) -> None:
        """执行 while 循环（含 max_iter 防死循环 + delay_ms）。"""
        from skills.control_flow import ConditionEvaluator
        condition = node.get("condition", "")
        max_iter = int(node.get("max_iter") or 100)
        delay_ms = int(node.get("delay_ms") or 0)
        evaluator = ConditionEvaluator(state["page"])
        iterations = 0

        while not state["stop"]:
            if self._should_stop_cb and self._should_stop_cb():
                state["stop"] = True
                break

            try:
                truthy = await evaluator.eval(condition, self.env_vars)
            except Exception as e:
                state["results"].append(_step_result(
                    {"action": "while", "condition": condition}, False, f"循环条件求值失败: {e}"))
                state["stop"] = True
                break

            if not truthy:
                break

            iterations += 1
            if iterations > max_iter:
                state["results"].append(_step_result(
                    {"action": "while", "condition": condition}, False,
                    f"循环超过最大次数 {max_iter}，疑似死循环"))
                state["stop"] = True
                break

            for child in node.get("body", []):
                if state["stop"]:
                    break
                await self._run_node(child, state)

            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)

    async def _run_step(self, step: dict, page: "Page") -> dict:
        """执行单个步骤，返回 step_result 字典。支持 selectors 多候选回退 + iframe。"""
        action   = step.get("action", "")
        selector = self._rv(step.get("selector", ""))
        value    = self._rv(step.get("value", ""))
        url      = self._rv(step.get("url", ""))
        expected = self._rv(str(step.get("expected", "")))
        timeout  = int(step.get("timeout", 30000))
        t0       = time.monotonic()
        screenshot_path = ""

        # ── 提前校验 selector 合法性，避免无意义等待 ──────────────────────────
        _selector_actions = {"click", "fill", "type", "select", "check", "uncheck",
                             "hover", "dblclick", "rightclick", "submit",
                             "assert_text", "assert_visible", "assert_hidden", "assert_count",
                             "scroll", "upload", "wait_for"}
        if action in _selector_actions and selector and not selector.startswith(
            ("@", "role=", "label=", "alt=", "#", ".", "[", "/", "(", "*", ":")):
            # 纯数字、纯汉字等明显不是 CSS selector 的字符串，提前报配置错误
            if re.match(r'^[\d一-鿿]+$', selector):
                return _step_result(step, False,
                    f'步骤配置错误：selector="{selector}" 不是合法的 CSS selector。'
                    f'请填写元素定位符（如 input[name="phone"]），'
                    f'如果要填写输入内容请放到 value 字段。')

        # ── 解析 frame 上下文 ──────────────────────────────────────────────────
        frame_selectors = step.get("frame_selectors") or []
        # navigate/wait_for_url/assert_url/press 等无 selector 的动作在主 page 执行
        _page_only_actions = {"navigate", "wait_for", "assert_url", "assert_title",
                               "press", "wait", "keydown", "screenshot", "evaluate"}
        if frame_selectors and action not in _page_only_actions:
            # 逐层进入 iframe，得到 FrameLocator
            ctx = page
            for fs in frame_selectors:
                ctx = ctx.frame_locator(fs)
        else:
            ctx = page   # 主页面

        # 对需要 selector 的交互动作，尝试多候选 selector 自动回退
        _interact_actions = {"click", "fill", "type", "select", "check", "uncheck",
                              "hover", "dblclick", "rightclick", "submit",
                              "assert_text", "assert_visible", "assert_hidden", "assert_count"}

        # 别名解析：@名称 → 展开为 selectors[]
        selector, selectors_to_try = await self._resolve_alias(selector, step)
        # 过滤掉 selectors[] 里残留的 @别名 项（别名已由上面展开，不应再进入多候选探测）
        selectors_to_try = [s for s in selectors_to_try if not s.startswith("@")]
        if not selectors_to_try and selector:
            selectors_to_try = [selector]

        _ai_fix_attempted = False   # 防止 probe + dispatch 两处都触发 LLM 修复

        if action in _interact_actions and selectors_to_try:
            used_selector = selector
            # 多候选：逐个用短超时探测，找到第一个可见的用它
            # 单候选：同样用短超时预探，失败时立即转 AI 修复，不等完整 timeout
            _probe_timeout = min(timeout, 5000)
            found = False
            for _sel in selectors_to_try:
                try:
                    await self._build_locator(ctx, _sel).wait_for(state="visible", timeout=_probe_timeout)
                    used_selector = _sel
                    found = True
                    break
                except Exception:
                    continue

            if not found and len(selectors_to_try) == 1 and not frame_selectors:
                # 单候选探测失败：直接走 AI 修复，跳过无意义的 30 秒等待
                _ai_fix_attempted = True
                fixed_selector = await self._ai_fix_selector(page, step, selector, f"Element not found: {selector}")
                if fixed_selector and fixed_selector != selector:
                    try:
                        await self._build_locator(ctx, fixed_selector).wait_for(state="visible", timeout=_probe_timeout)
                        used_selector = fixed_selector
                        found = True
                        logger.info(f"[AI selector fix early] step={step.get('id')} {selector!r} → {fixed_selector!r}")
                        step["selector"] = fixed_selector
                    except Exception:
                        pass

            selector = used_selector

        try:
            shot = await self._dispatch(action, page, ctx, selector, value, url, expected, timeout)
            duration = (time.monotonic() - t0) * 1000
            return _step_result(step, True, duration_ms=duration, screenshot=shot)

        except Exception as e:
            duration = (time.monotonic() - t0) * 1000
            err_str = str(e)

            # ── Strict mode 自动降级：匹配到多个元素时用 .first ────────────────
            if ("strict mode violation" in err_str or "resolved to" in err_str) and selector:
                first_selector = f"{selector} >> nth=0"
                try:
                    shot = await self._dispatch(action, page, ctx, first_selector, value, url, expected, timeout)
                    duration = (time.monotonic() - t0) * 1000
                    logger.info(
                        f"[strict mode fallback] step={step.get('id')} "
                        f"selector={selector!r} 匹配多个元素，降级为 nth=0"
                    )
                    step["selector"] = first_selector
                    return _step_result(step, True, duration_ms=duration, screenshot=shot)
                except Exception:
                    pass

            # ── AI Selector 自动修复（仅主页面支持，frame 暂不支持） ────────────
            # 只在超时/找不到元素时触发，不在断言失败时触发；且每步最多尝试一次
            _fixable = ("Timeout" in err_str or "waiting for" in err_str or
                        "not found" in err_str.lower())
            if _fixable and action in _interact_actions and selector and not frame_selectors and not _ai_fix_attempted:
                _ai_fix_attempted = True
                fixed_selector = await self._ai_fix_selector(page, step, selector, str(e))
                if fixed_selector and fixed_selector != selector:
                    try:
                        # AI 修复用较短超时验证，避免再等 30 秒
                        _fix_timeout = min(timeout, 10000)
                        shot = await self._dispatch(action, page, page, fixed_selector, value, url, expected, _fix_timeout)
                        duration = (time.monotonic() - t0) * 1000
                        logger.info(
                            f"[AI selector fix] step={step.get('id')} "
                            f"原: {selector!r} → 修复: {fixed_selector!r}"
                        )
                        step["selector"] = fixed_selector
                        return _step_result(step, True, duration_ms=duration, screenshot=shot)
                    except Exception:
                        pass

            # 失败时自动截图
            try:
                fname = f"step_{step.get('id', 'unknown')}_{int(time.time())}.png"
                spath = SCREENSHOT_DIR / fname
                await page.screenshot(path=str(spath))
                screenshot_path = f"/screenshots/{fname}"
            except Exception:
                pass
            return _step_result(step, False,
                                 error=str(e),
                                 duration_ms=duration,
                                 screenshot=screenshot_path)

    async def _ai_fix_selector(
        self,
        page: "Page",
        step: dict,
        failed_selector: str,
        error_msg: str,
    ) -> Optional[str]:
        """
        当所有候选 selector 都失败时，抓取当前页面可交互元素列表，
        让 AI 推断一个可用的 selector。

        返回 AI 推断的新 selector，或 None（AI 不确定时不强行修复）。

        设计约束：
          - 只抓前 60 个可交互元素（避免 prompt 过长）
          - 调用 LLM 超时设为 20s（步骤执行不能被 AI 拖死）
          - 失败时静默返回 None，不抛出异常
        """
        try:
            # 抓取当前页面可交互元素概要
            elements = await page.evaluate("""() => {
                const selectors = [
                    'button', 'a', 'input', 'select', 'textarea',
                    '[role="button"]', '[role="link"]', '[role="tab"]',
                    '[role="menuitem"]', '[role="checkbox"]', '[role="radio"]',
                    '[onclick]', 'form'
                ];
                const items = [];
                for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 && rect.height === 0) continue;
                        items.push({
                            tag: el.tagName.toLowerCase(),
                            id: el.id || '',
                            text: (el.textContent || '').trim().slice(0, 40),
                            name: el.getAttribute('name') || '',
                            type: el.getAttribute('type') || '',
                            placeholder: el.getAttribute('placeholder') || '',
                            class: (el.className || '').split(' ').slice(0, 3).join(' '),
                            role: el.getAttribute('role') || '',
                            href: el.getAttribute('href') || '',
                        });
                        if (items.length >= 60) break;
                    }
                    if (items.length >= 60) break;
                }
                return items;
            }""")

            if not elements:
                return None

            # 格式化元素列表为 prompt 可读格式
            el_lines = []
            for el in elements[:60]:
                parts = [el["tag"]]
                if el["id"]:
                    parts.append(f'id="{el["id"]}"')
                if el["name"]:
                    parts.append(f'name="{el["name"]}"')
                if el["type"]:
                    parts.append(f'type="{el["type"]}"')
                if el["text"]:
                    parts.append(f'text="{el["text"]}"')
                if el["placeholder"]:
                    parts.append(f'placeholder="{el["placeholder"]}"')
                el_lines.append("  " + " ".join(parts))

            action = step.get("action", "")
            step_desc = step.get("description") or step.get("name") or action
            page_url = page.url

            prompt = (
                f"在 Playwright 自动化测试中，以下 selector 执行 '{action}' 操作失败：\n"
                f"  失败的 selector：{failed_selector!r}\n"
                f"  错误信息：{error_msg[:200]}\n"
                f"  步骤描述：{step_desc}\n"
                f"  当前页面 URL：{page_url}\n\n"
                f"当前页面中找到以下可交互元素（共 {len(elements)} 个）：\n"
                + "\n".join(el_lines[:40]) +
                "\n\n"
                f"请根据步骤描述推断最可能匹配的元素，输出一个有效的 CSS selector 或 XPath。\n"
                f"只输出 selector 字符串，不要任何解释。\n"
                f"若无法确定，输出 NONE。"
            )

            system = "你是 Playwright 自动化测试专家，擅长从页面元素列表中推断正确的 selector。"
            from tools.llm_client import call_llm
            raw = await call_llm(system, prompt, max_tokens=200, timeout_secs=20)
            candidate = raw.strip().strip('"\'`').strip()

            if not candidate or candidate.upper() == "NONE" or len(candidate) > 200:
                return None

            logger.info(f"[AI selector fix] AI 推断候选 selector: {candidate!r}")
            return candidate

        except Exception as e:
            logger.warning(f"[AI selector fix] 推断失败: {e}")
            return None

    async def _dispatch(self, action: str, page: "Page", ctx,
                        selector: str, value: str, url: str,
                        expected: str, timeout: int) -> str:
        """按 action 类型路由到 Playwright 调用。返回截图路径（仅 screenshot action 非空）。"""
        kw = {"timeout": timeout}

        if action == "navigate":
            # navigate 始终在主 page 执行
            # 先等 domcontentloaded（快），再等 load（JS 执行完），SPA 渲染更可靠
            try:
                await page.goto(url, wait_until="load", timeout=timeout)
            except Exception:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                except Exception:
                    await page.goto(url, wait_until="commit", timeout=timeout)

        elif action == "click":
            await self._build_locator(ctx, selector).click(**kw)

        elif action == "fill":
            await self._build_locator(ctx, selector).fill(value, timeout=timeout)

        elif action == "type":
            await self._build_locator(ctx, selector).type(value, timeout=timeout)

        elif action == "select":
            await self._build_locator(ctx, selector).select_option(value, timeout=timeout)

        elif action == "check":
            await self._build_locator(ctx, selector).check(**kw)

        elif action == "uncheck":
            await self._build_locator(ctx, selector).uncheck(**kw)

        elif action == "hover":
            await self._build_locator(ctx, selector).hover(**kw)

        elif action == "dblclick":
            await self._build_locator(ctx, selector).dblclick(**kw)

        elif action == "rightclick":
            await self._build_locator(ctx, selector).click(button="right", **kw)

        elif action == "press":
            if selector:
                await self._build_locator(ctx, selector).press(value, timeout=timeout)
            else:
                await page.keyboard.press(value)

        elif action == "scroll":
            if selector:
                await self._build_locator(ctx, selector).scroll_into_view_if_needed(timeout=timeout)
            else:
                await page.mouse.wheel(0, 500)

        elif action == "upload":
            import json as _json
            _files = (_json.loads(value) if value.strip().startswith('[')
                      else [v.strip() for v in value.split(',') if v.strip()])
            await self._build_locator(ctx, selector).set_input_files(_files, timeout=timeout)

        elif action == "wait_for":
            if url:
                await page.wait_for_url(url, timeout=timeout)
            elif value:
                await page.wait_for_function(value, timeout=timeout)
            else:
                await self._build_locator(ctx, selector).wait_for(state="visible", timeout=timeout)

        elif action == "assert_text":
            await expect(self._build_locator(ctx, selector)).to_have_text(
                re.compile(expected) if expected.startswith("/") else expected,
                timeout=timeout,
            )

        elif action == "assert_visible":
            await expect(self._build_locator(ctx, selector)).to_be_visible(timeout=timeout)

        elif action == "assert_hidden":
            await expect(self._build_locator(ctx, selector)).to_be_hidden(timeout=timeout)

        elif action == "assert_url":
            pattern = re.compile(expected) if expected.startswith("/") else expected
            await expect(page).to_have_url(pattern, timeout=timeout)

        elif action == "assert_title":
            pattern = re.compile(expected) if expected.startswith("/") else expected
            await expect(page).to_have_title(pattern, timeout=timeout)

        elif action == "assert_count":
            await expect(self._build_locator(ctx, selector)).to_have_count(int(expected), timeout=timeout)

        elif action == "screenshot":
            fname = value or f"checkpoint_{int(time.time())}.png"
            if not fname.endswith(".png"):
                fname += ".png"
            await page.screenshot(path=str(SCREENSHOT_DIR / fname))
            return f"/screenshots/{fname}"

        elif action == "evaluate":
            await page.evaluate(value)

        elif action == "submit":
            try:
                await self._build_locator(ctx, selector).dispatch_event("submit")
            except Exception:
                await self._build_locator(ctx, selector).click(timeout=timeout)

        elif action == "keydown":
            key = value or "Enter"
            try:
                if selector and selector != "body":
                    await self._build_locator(ctx, selector).press(key)
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
        return ""
