"""
PytestExporter — 将 WebUI 任务用例导出为 pytest + Playwright 脚本（方案C）

生成的脚本可直接在本地运行：
    pip install pytest playwright
    playwright install
    pytest reports/pytest_{task_id}.py -v
"""
import re
from pathlib import Path
from datetime import datetime

# 导出目录
EXPORT_DIR = Path("reports/pytest_exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _snake(name: str) -> str:
    """将中文/空格/特殊字符转为合法 Python 函数名。"""
    name = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name.strip())
    # 非 ASCII 字符转拼音首字母近似（直接保留，pytest 支持 unicode 函数名）
    return name or "case"


def _step_to_code(step: dict, indent: str = "    ") -> str:
    """将单个 ActionStep 转换为 Python Playwright 代码行。支持 frame_selectors。"""
    action          = step.get("action", "")
    selector        = step.get("selector", "")
    value           = step.get("value", "")
    url             = step.get("url", "")
    expected        = step.get("expected", "")
    timeout         = int(step.get("timeout", 10000))
    desc            = step.get("description", "")
    frame_selectors = step.get("frame_selectors") or []

    # 转义单引号
    def q(s):
        return s.replace("\\", "\\\\").replace("'", "\\'")

    comment = f"{indent}# {desc}\n" if desc else ""

    # 构建执行上下文变量表达式
    # 主页面：ctx = page
    # 有 frame：ctx = page.frame_locator('sel1').frame_locator('sel2')
    _page_only_actions = {"navigate", "assert_url", "assert_title", "press",
                          "screenshot", "evaluate", "wait", "keydown"}
    if frame_selectors and action not in _page_only_actions:
        ctx_expr = "page"
        for fs in frame_selectors:
            ctx_expr += f".frame_locator('{q(fs)}')"
    else:
        ctx_expr = "page"

    # 根据 ctx_expr 构建 locator 前缀，支持语义前缀
    import re as _re
    def loc(sel):
        if sel.startswith("role="):
            m = _re.match(r'^role=([^\[]+)(?:\[name="([^"]+)"\])?$', sel)
            if m:
                rname, aname = m.group(1).strip(), m.group(2)
                if aname:
                    return f"{ctx_expr}.get_by_role('{q(rname)}', name='{q(aname)}')"
                return f"{ctx_expr}.get_by_role('{q(rname)}')"
        if sel.startswith("label="):
            return f"{ctx_expr}.get_by_label('{q(sel[6:])}')"
        if sel.startswith("alt="):
            return f"{ctx_expr}.get_by_alt_text('{q(sel[4:])}')"
        return f"{ctx_expr}.locator('{q(sel)}')"

    _shot_name = q(value) if value else "checkpoint.png"
    mapping = {
        "navigate":       f"page.goto('{q(url)}', wait_until='networkidle', timeout={timeout})",
        "click":          f"{loc(selector)}.click(timeout={timeout})",
        "fill":           f"{loc(selector)}.fill('{q(value)}', timeout={timeout})",
        "type":           f"{loc(selector)}.type('{q(value)}', timeout={timeout})",
        "select":         f"{loc(selector)}.select_option('{q(value)}', timeout={timeout})",
        "check":          f"{loc(selector)}.check(timeout={timeout})",
        "uncheck":        f"{loc(selector)}.uncheck(timeout={timeout})",
        "hover":          f"{loc(selector)}.hover(timeout={timeout})",
        "dblclick":       f"{loc(selector)}.dblclick(timeout={timeout})",
        "rightclick":     f"{loc(selector)}.click(button='right', timeout={timeout})",
        "press":          f"page.keyboard.press('{q(value)}')",
        "scroll":         f"{loc(selector)}.scroll_into_view_if_needed(timeout={timeout})" if selector else "page.mouse.wheel(0, 500)",
        "upload":         f"{loc(selector)}.set_input_files('{q(value)}', timeout={timeout})",
        "wait_for":       f"page.wait_for_url('{q(url)}', timeout={timeout})" if url else f"{loc(selector)}.wait_for(state='visible', timeout={timeout})",
        "assert_text":    f"expect({loc(selector)}).to_have_text('{q(expected)}', timeout={timeout})",
        "assert_visible": f"expect({loc(selector)}).to_be_visible(timeout={timeout})",
        "assert_hidden":  f"expect({loc(selector)}).to_be_hidden(timeout={timeout})",
        "assert_url":     f"expect(page).to_have_url('{q(expected)}', timeout={timeout})",
        "assert_title":   f"expect(page).to_have_title('{q(expected)}', timeout={timeout})",
        "assert_count":   f"expect({loc(selector)}).to_have_count({expected}, timeout={timeout})",
        "screenshot":     f"page.screenshot(path='reports/screenshots/{_shot_name}')",
        "evaluate":       f"page.evaluate('{q(value)}')",
    }

    code_line = mapping.get(action)
    if not code_line:
        return f"{comment}{indent}pass  # 未知 action: {action}\n"

    optional = step.get("optional", False)
    if optional:
        return (
            f"{comment}"
            f"{indent}try:\n"
            f"{indent}    {code_line}\n"
            f"{indent}except Exception:\n"
            f"{indent}    pass  # optional step\n"
        )
    return f"{comment}{indent}{code_line}\n"


def export_task(task_id: int, task_name: str, task_url: str,
                cases: list, env_vars: dict) -> str:
    """
    生成 pytest 脚本，写入 EXPORT_DIR/pytest_{task_id}.py，返回文件路径。

    cases: list of {id, name, steps_json: ActionStep[]}
    env_vars: {key: value}（明文，调用方负责是否传入 secret）
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 文件头 ────────────────────────────────────────────────────────────────
    lines = [
        f"# 自动生成 by AI Test Agent — 任务: {task_name}\n",
        f"# 生成时间: {now}\n",
        f"# 目标地址: {task_url}\n",
        "#\n",
        "# 运行方式:\n",
        "#   pip install pytest playwright\n",
        "#   playwright install\n",
        f"#   pytest reports/pytest_exports/pytest_{task_id}.py -v\n",
        "\n",
        "import pytest\n",
        "from playwright.sync_api import Page, expect\n",
        "\n",
        "\n",
    ]

    # ── env fixture ───────────────────────────────────────────────────────────
    env_repr = repr(env_vars)
    lines += [
        "@pytest.fixture(scope='module')\n",
        "def env():\n",
        f"    return {env_repr}\n",
        "\n",
        "\n",
    ]

    # ── 每条用例生成一个 test_ 函数 ──────────────────────────────────────────
    for case in cases:
        case_id   = case.get("id", 0)
        case_name = case.get("name", f"case_{case_id}")
        steps     = case.get("steps_json") or []
        fn_name   = f"test_{case_id}_{_snake(case_name)}"

        lines.append(f"def {fn_name}(page: Page, env: dict):\n")
        lines.append(f'    """{case_name}"""\n')

        if not steps:
            # 没有结构化步骤：生成一个基础 navigate 作为占位
            lines.append(f"    # 该用例无结构化步骤，仅验证页面可达\n")
            if task_url:
                lines.append(f"    page.goto('{task_url}', wait_until='networkidle')\n")
            else:
                lines.append(f"    pass\n")
        else:
            for step in steps:
                lines.append(_step_to_code(step, indent="    "))

        lines.append("\n\n")

    script = "".join(lines)
    out_path = EXPORT_DIR / f"pytest_{task_id}.py"
    out_path.write_text(script, encoding="utf-8")
    return str(out_path)


async def export_task_from_db(task_id: int, db, include_secrets: bool = False) -> str:
    """从数据库读取任务、用例、环境变量，调用 export_task 生成脚本。"""
    from sqlalchemy import select
    from tools.database import TestTask, TestCase, TaskEnvVar

    task_result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise ValueError(f"任务 {task_id} 不存在")

    cases_result = await db.execute(
        select(TestCase).where(TestCase.task_id == task_id,
                               TestCase.deprecated == False)
    )
    cases = [
        {"id": c.id, "name": c.name, "steps_json": c.steps_json or []}
        for c in cases_result.scalars().all()
    ]

    env_result = await db.execute(
        select(TaskEnvVar).where(TaskEnvVar.task_id == task_id)
    )
    env_vars = {}
    for r in env_result.scalars().all():
        if r.is_secret and not include_secrets:
            env_vars[r.key] = "***SECRET***"
        else:
            env_vars[r.key] = r.value

    return export_task(
        task_id=task_id,
        task_name=task.name,
        task_url=task.url or "",
        cases=cases,
        env_vars=env_vars,
    )
