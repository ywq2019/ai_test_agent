"""
ParallelRunner — 多浏览器并行执行调度（方案C）

每个浏览器独立启动 Playwright 上下文，各自执行全套用例，
各自写入一条 TestReport（browser 字段标记对应浏览器）。

asyncio.gather 并发启动所有浏览器，互不阻塞。
"""
import asyncio
import time
from pathlib import Path
from typing import Optional

from loguru import logger

try:
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

from skills.action_runner import ActionRunner


async def run_multi_browser_bg(
    task_id: int,
    task_url: str,
    task_name: str,
    case_dicts: list,
    browsers: list,
    env_vars: dict,
    report_ids: dict,          # {browser: report_id}
    workspace_id: int = None,  # 工作空间隔离
) -> None:
    """后台任务入口：并行启动多浏览器执行，结果写回各自 TestReport。"""
    from tools.database import async_session_maker
    from api.websocket_manager import ws_manager

    if not _PLAYWRIGHT_AVAILABLE:
        logger.error("[ParallelRunner] playwright 未安装")
        return

    async def _push(msg: dict):
        await ws_manager.broadcast_to_workspace(msg, workspace_id)

    await _push({"type": "multi_exec_start", "task_id": task_id, "browsers": browsers})

    tasks = [
        _run_single_browser(
            task_id=task_id,
            task_url=task_url,
            task_name=task_name,
            case_dicts=case_dicts,
            browser=browser,
            env_vars=env_vars,
            report_id=report_ids.get(browser),
            ws_push=_push,
        )
        for browser in browsers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 汇总推送
    summary = {}
    for browser, result in zip(browsers, results):
        if isinstance(result, Exception):
            summary[browser] = {"status": "error", "error": str(result)}
        else:
            summary[browser] = result

    await _push({"type": "multi_exec_done", "task_id": task_id, "summary": summary})
    logger.info(f"[ParallelRunner] task={task_id} 多浏览器执行完成: {list(summary.keys())}")


async def _run_single_browser(
    task_id: int,
    task_url: str,
    task_name: str,
    case_dicts: list,
    browser: str,
    env_vars: dict,
    report_id: Optional[int],
    ws_push,
) -> dict:
    """在指定浏览器中依次执行所有用例，结果写回 TestReport。"""
    from tools.database import async_session_maker, TestReport
    from sqlalchemy import select

    total   = len(case_dicts)
    passed  = 0
    failed  = 0
    details = []

    await ws_push({
        "type": "browser_exec_start",
        "task_id": task_id,
        "browser": browser,
        "total": total,
    })

    try:
        async with async_playwright() as pw:
            launcher = getattr(pw, browser, pw.chromium)
            b = await launcher.launch(headless=True)
            context = await b.new_context()
            page = await context.new_page()

            runner = ActionRunner(task_id=task_id, browser=browser)
            runner.env_vars = env_vars   # 直接注入，避免重复 DB 查询

            for idx, case in enumerate(case_dicts, 1):
                t0 = time.monotonic()
                try:
                    # 优先使用结构化步骤；回退到旧的字符串 steps（向下兼容）
                    if case.get("steps_json"):
                        case_result = await runner.run_case(case, page)
                        status       = case_result["status"]
                        error_msg    = "; ".join(
                            s["error"] for s in case_result["steps"] if s.get("error")
                        ) or None
                        screenshot   = next(
                            (s["screenshot"] for s in case_result["steps"] if s.get("screenshot")), ""
                        )
                    else:
                        # 没有 steps_json：用例无法执行，标记 skipped 而非误判 passed
                        status      = "skipped"
                        error_msg   = "用例无 steps_json，跳过执行"
                        screenshot  = ""

                    # duration 单位统一为毫秒，写入 details 时保留毫秒
                    duration_ms = round((time.monotonic() - t0) * 1000, 1)
                    if status == "passed":
                        passed += 1
                    else:
                        failed += 1

                except Exception as e:
                    duration_ms = round((time.monotonic() - t0) * 1000, 1)
                    status      = "failed"
                    error_msg   = str(e)
                    screenshot  = ""
                    failed     += 1
                    logger.warning(f"[ParallelRunner] {browser} case={case.get('id')} 异常: {e}")

                details.append({
                    "id":            idx,
                    "case_id":       case.get("id"),
                    "case_name":     case.get("name", ""),
                    "status":        status,
                    "duration":      duration_ms,   # 统一单位：毫秒
                    "error_message": error_msg,
                    "screenshot":    screenshot,
                })

                await ws_push({
                    "type":      "browser_exec_progress",
                    "task_id":   task_id,
                    "browser":   browser,
                    "current":   idx,
                    "total":     total,
                    "case_name": case.get("name", ""),
                    "status":    status,
                })

            await b.close()

    except Exception as e:
        logger.error(f"[ParallelRunner] {browser} 启动失败: {e}")
        failed = total
        details = [
            {"id": i + 1, "case_id": c.get("id"), "case_name": c.get("name", ""),
             "status": "failed", "duration": 0, "error_message": str(e), "screenshot": ""}
            for i, c in enumerate(case_dicts)
        ]

    # 写回 TestReport
    pass_rate = round(passed / total * 100, 2) if total else 0
    skipped   = sum(1 for d in details if d["status"] == "skipped")
    summary = {
        "total": total, "passed": passed, "failed": failed, "skipped": skipped,
        "pass_rate": pass_rate, "browser": browser,
        "total_duration": round(sum(d["duration"] for d in details), 2),
    }

    if report_id:
        try:
            async with async_session_maker() as db:
                res = await db.execute(select(TestReport).where(TestReport.id == report_id))
                report = res.scalar_one_or_none()
                if report:
                    report.summary     = summary
                    report.details     = details
                    report.pass_rate   = pass_rate
                    report.total_cases = total
                    report.passed      = passed
                    report.failed      = failed
                    report.skipped     = 0
                    report.browser     = browser
                    await db.commit()
        except Exception as e:
            logger.error(f"[ParallelRunner] 写报告失败 browser={browser}: {e}")

    await ws_push({
        "type":      "browser_exec_done",
        "task_id":   task_id,
        "browser":   browser,
        "report_id": report_id,
        "summary":   summary,
    })

    return summary
