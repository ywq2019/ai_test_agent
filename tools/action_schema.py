"""
ActionStep 结构化步骤定义 — WebUI 自动化方案C核心数据模型

ActionStep 是录制器和执行引擎之间的统一接口：
  - 录制器将用户浏览器操作转换为 ActionStep 列表存入 TestCase.steps_json
  - ActionRunner 按 ActionStep 类型路由到对应 Playwright 调用执行
  - pytest 导出器将 ActionStep 列表转换为 Python Playwright 代码

变量替换：value / url / expected 等字段支持 {{key}} 语法，
执行时从 TaskEnvVar 表按 task_id 读取替换值。
"""
from typing import Literal, Optional

# ── 支持的 Action 类型 ────────────────────────────────────────────────────────
ACTION_TYPES = Literal[
    "navigate",       # 导航到 URL                 → page.goto(url)
    "click",          # 点击元素                   → page.click(selector)
    "dblclick",       # 双击元素                   → page.dblclick(selector)
    "rightclick",     # 右键元素                   → page.click(selector, button='right')
    "fill",           # 填写输入框                 → page.fill(selector, value)
    "type",           # 逐字符输入（触发键盘事件）  → page.type(selector, value)
    "select",         # 下拉框选择                 → page.select_option(selector, value)
    "check",          # 勾选 checkbox              → page.check(selector)
    "uncheck",        # 取消勾选                   → page.uncheck(selector)
    "hover",          # 鼠标悬停                   → page.hover(selector)
    "press",          # 键盘按键                   → page.keyboard.press(key)
    "scroll",         # 滚动到元素                 → page.locator(selector).scroll_into_view_if_needed()
    "upload",         # 文件上传                   → page.set_input_files(selector, files)
    "wait_for",       # 等待条件满足               → page.wait_for_selector/url/function
    "assert_text",    # 断言元素文本               → expect(locator).to_have_text(expected)
    "assert_visible", # 断言元素可见               → expect(locator).to_be_visible()
    "assert_hidden",  # 断言元素不可见             → expect(locator).to_be_hidden()
    "assert_url",     # 断言当前 URL               → expect(page).to_have_url(pattern)
    "assert_title",   # 断言页面标题               → expect(page).to_have_title(pattern)
    "assert_count",   # 断言元素数量               → expect(locator).to_have_count(count)
    "screenshot",     # 截图检查点                 → page.screenshot(path=...)
    "evaluate",       # 执行 JS 表达式             → page.evaluate(expression)
]

# ── 每种 action 的字段说明 ─────────────────────────────────────────────────────
ACTION_FIELD_DOCS: dict = {
    "navigate":       {"url": "目标页面 URL，支持 {{变量}}"},
    "click":          {"selector": "CSS/XPath 选择器"},
    "fill":           {"selector": "CSS/XPath 选择器", "value": "填写内容，支持 {{变量}}"},
    "type":           {"selector": "CSS/XPath 选择器", "value": "输入内容，支持 {{变量}}"},
    "select":         {"selector": "CSS/XPath 选择器", "value": "选项 value 或 label"},
    "check":          {"selector": "CSS/XPath 选择器"},
    "uncheck":        {"selector": "CSS/XPath 选择器"},
    "hover":          {"selector": "CSS/XPath 选择器"},
    "press":          {"value": "按键名，如 Enter、Tab、Escape"},
    "scroll":         {"selector": "滚动到指定元素（可选）"},
    "upload":         {"selector": "文件输入框选择器", "value": "文件路径"},
    "wait_for":       {"selector": "等待该选择器出现", "url": "等待 URL 匹配（与 selector 二选一）",
                       "value": "等待 JS 条件表达式（可选）"},
    "assert_text":    {"selector": "CSS/XPath 选择器", "expected": "期望文本，支持正则"},
    "assert_visible": {"selector": "CSS/XPath 选择器"},
    "assert_hidden":  {"selector": "CSS/XPath 选择器"},
    "assert_url":     {"expected": "期望 URL，支持正则/glob"},
    "assert_title":   {"expected": "期望页面标题，支持正则"},
    "assert_count":   {"selector": "CSS/XPath 选择器", "expected": "期望数量（整数字符串）"},
    "screenshot":     {"value": "截图文件名（可选，默认自动命名）"},
    "evaluate":       {"value": "要执行的 JS 表达式"},
}

# ── ActionStep 字典结构（类型提示用） ─────────────────────────────────────────
# 实际存储为 JSON，不强制 Pydantic，避免依赖版本问题
#
# {
#   "id":          str,     # 步骤唯一ID，如 "s001"
#   "action":      str,     # ACTION_TYPES 之一
#   "selector":    str,     # CSS/XPath 选择器（click/fill/assert_* 等需要）
#   "value":       str,     # 填写内容 / 按键名 / JS 表达式（视 action 而定）
#   "url":         str,     # navigate/wait_for_url 时的目标 URL
#   "expected":    str,     # assert_* 时的期望值
#   "description": str,     # 步骤描述，供报告展示和 pytest 注释
#   "timeout":     int,     # 超时毫秒，默认 10000
#   "optional":    bool,    # True = 失败不中断整条用例
# }


def make_step(
    action: str,
    *,
    step_id: Optional[str] = None,
    selector: str = "",
    value: str = "",
    url: str = "",
    expected: str = "",
    description: str = "",
    timeout: int = 10000,
    optional: bool = False,
) -> dict:
    """构造一个 ActionStep 字典，用于录制器和 AI 生成时统一创建步骤。"""
    return {
        "id":          step_id or "",
        "action":      action,
        "selector":    selector,
        "value":       value,
        "url":         url,
        "expected":    expected,
        "description": description,
        "timeout":     timeout,
        "optional":    optional,
    }


def validate_step(step: dict) -> tuple[bool, str]:
    """基础校验：action 合法、必填字段不为空。返回 (ok, error_msg)。"""
    action = step.get("action", "")
    valid_actions = {
        # 核心导航与交互
        "navigate", "click", "dblclick", "rightclick", "fill", "type",
        "select", "check", "uncheck", "hover", "press", "scroll",
        "upload", "wait_for", "submit",
        # 录制器额外产生的 action
        "keydown",   # 键盘事件（Enter/Tab/Escape）
        "wait",      # enrich_recorded_steps 插入的固定等待
        # 断言
        "assert_text", "assert_visible", "assert_hidden",
        "assert_url", "assert_title", "assert_count",
        # 工具
        "screenshot", "evaluate",
    }
    if action not in valid_actions:
        return False, f"未知 action 类型: {action!r}"

    # 需要 selector 的 action（scroll/keydown selector 可为空，所以不在此列）
    needs_selector = {
        "click", "fill", "type", "select", "check", "uncheck", "hover",
        "upload", "wait_for",
        "assert_text", "assert_visible", "assert_hidden", "assert_count",
    }
    if action in needs_selector and not step.get("selector"):
        return False, f"action={action!r} 需要 selector 字段"

    # 需要 url 的 action
    if action == "navigate" and not step.get("url"):
        return False, "navigate action 需要 url 字段"

    # 需要 expected 的 assert action
    needs_expected = {"assert_text", "assert_url", "assert_title", "assert_count"}
    if action in needs_expected and not step.get("expected") and step.get("expected") != 0:
        return False, f"action={action!r} 需要 expected 字段"

    return True, ""


def steps_to_description(steps: list) -> str:
    """将 ActionStep 列表转换为人类可读的操作描述（用于报告展示）。"""
    lines = []
    for i, step in enumerate(steps, 1):
        action = step.get("action", "")
        desc = step.get("description", "")
        sel = step.get("selector", "")
        val = step.get("value", "")
        # fill / type / select 即使有 description 也要补齐 value
        if desc and action in ("fill", "type", "select"):
            # 如果 desc 里已经有 " = " 就不再追加
            if " = " not in desc and val:
                desc = f"{desc} = {val}"
            lines.append(f"{i}. {desc}")
            continue
        if desc:
            lines.append(f"{i}. {desc}")
            continue
        # 自动生成描述
        sel = step.get("selector", "")
        val = step.get("value", "")
        url = step.get("url", "")
        exp = step.get("expected", "")
        mapping = {
            "navigate":       f"导航到 {url}",
            "click":          f"点击 {sel}",
            "dblclick":       f"双击 {sel}",
            "rightclick":     f"右键 {sel}",
            "fill":           f"填写 {sel} = {val}",
            "type":           f"输入 {sel} = {val}",
            "select":         f"选择 {sel} → {val}",
            "check":          f"勾选 {sel}",
            "uncheck":        f"取消勾选 {sel}",
            "submit":         f"提交表单 {sel or ''}",
            "hover":          f"悬停 {sel}",
            "press":          f"按键 {val}",
            "scroll":         f"滚动到 {sel}",
            "wait_for":       f"等待 {sel or url}",
            "assert_text":    f"断言 {sel} 文本 = {exp}",
            "assert_visible": f"断言 {sel} 可见",
            "assert_hidden":  f"断言 {sel} 不可见",
            "assert_url":     f"断言 URL = {exp}",
            "assert_title":   f"断言标题 = {exp}",
            "assert_count":   f"断言 {sel} 数量 = {exp}",
            "screenshot":     f"截图 {val or '自动命名'}",
            "evaluate":       f"执行 JS: {val[:40]}{'...' if len(val) > 40 else ''}",
        }
        lines.append(f"{i}. {mapping.get(action, action)}")
    return "\n".join(lines)
