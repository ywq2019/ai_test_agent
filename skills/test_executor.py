"""
测试执行技能
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
from loguru import logger
from tools.browser import browser_pool
from tools.config import settings


class TestExecutor:
    def __init__(self):
        self.current_task_id: Optional[int] = None
        self.is_running: bool = False
        self.is_paused: bool = False
        self.should_stop: bool = False
        self.progress_callback: Optional[Callable] = None

    async def execute_batch(
        self,
        cases: List[Dict[str, Any]],
        url: str,
        browser_type: str = "chromium",
        screenshots_dir: str = None,
        progress_callback: Optional[Callable] = None
    ) -> List[Dict[str, Any]]:
        """
        批量执行测试用例
        """
        self.progress_callback = progress_callback
        self.is_running = True
        self.should_stop = False
        results = []
        total_cases = len(cases)
        completed_cases = 0

        try:
            for case in cases:
                if self.should_stop:
                    break

                # 暂停等待
                while self.is_paused and not self.should_stop:
                    await asyncio.sleep(0.2)
                if self.should_stop:
                    break

                result = await self.execute_case(case, url, browser_type, screenshots_dir)
                results.append(result)
                completed_cases += 1

                if progress_callback:
                    await progress_callback({
                        "type": "case_complete",
                        "case_id": result.get("case_id"),
                        "case_name": result.get("case_name", ""),
                        "status": result["status"],
                        "duration": result.get("duration", 0),
                        "error_message": result.get("error_message"),
                        "screenshot_path": result.get("screenshot_path"),
                        "progress": completed_cases / total_cases * 100,
                        "current": completed_cases,
                        "total": total_cases
                    })
        finally:
            self.is_running = False

        return results

    async def execute_case(
        self,
        case: Dict[str, Any],
        url: str,
        browser_type: str = "chromium",
        screenshots_dir: str = None
    ) -> Dict[str, Any]:
        browser = None
        start_time = datetime.utcnow()

        try:
            browser = await browser_pool.get_browser(browser_type)
            page = browser.page

            await browser.navigate(url)

            screenshot_path = None
            error_message = None

            if case.get("element_selector"):
                try:
                    selector = case["element_selector"]

                    if "input" in case.get("name", "").lower():
                        await browser.wait_for_selector(selector, timeout=5000)
                        test_value = "Test123"
                        await browser.fill_input(selector, test_value)

                    elif "点击" in case.get("name", "") or "button" in case.get("name", "").lower():
                        await browser.wait_for_selector(selector, timeout=5000)
                        await browser.click_element(selector)

                    elif "选择" in case.get("name", "") or "select" in case.get("name", "").lower():
                        await browser.wait_for_selector(selector, timeout=5000)
                        await browser.select_option(selector, "1")

                    else:
                        await browser.wait_for_selector(selector, timeout=5000)
                        await browser.click_element(selector)

                    await asyncio.sleep(0.5)

                except Exception as e:
                    error_message = str(e)
                    logger.error(f"Case execution error: {e}")

            if screenshots_dir:
                status_tag = "fail" if error_message else "pass"
                screenshot_filename = f"case_{case.get('id', 'unknown')}_{status_tag}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
                screenshot_path = str(Path(screenshots_dir) / screenshot_filename)
                try:
                    await browser.take_screenshot(screenshot_path)
                except Exception as se:
                    logger.warning(f"Screenshot failed: {se}")
                    screenshot_path = None

            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            status = "passed" if not error_message else "failed"

            return {
                "case_id": case.get("id"),
                "case_name": case.get("name", ""),
                "status": status,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration": duration,
                "error_message": error_message,
                "screenshot_path": screenshot_path,
                "logs": f"Executed case: {case.get('name')}"
            }

        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            return {
                "case_id": case.get("id"),
                "case_name": case.get("name", ""),
                "status": "failed",
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration": duration,
                "error_message": str(e),
                "screenshot_path": None,
                "logs": f"Execution failed: {str(e)}"
            }

    async def execute_test_suite(
        self,
        tasks: List[Dict[str, Any]],
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        self.progress_callback = progress_callback
        self.is_running = True
        self.should_stop = False

        results = []
        total_cases = sum(len(task.get("cases", [])) for task in tasks)
        completed_cases = 0

        try:
            for task in tasks:
                if self.should_stop:
                    break

                task_id = task.get("id")
                task_name = task.get("name")
                url = task.get("url")
                browser_type = task.get("browser", "chromium")
                cases = task.get("cases", [])

                if self.progress_callback:
                    await self.progress_callback({
                        "type": "task_start",
                        "task_id": task_id,
                        "task_name": task_name,
                        "total_cases": len(cases)
                    })

                for case in cases:
                    if self.should_stop:
                        break

                    while self.is_paused and not self.should_stop:
                        await asyncio.sleep(0.2)
                    if self.should_stop:
                        break

                    result = await self.execute_case(case, url, browser_type)
                    results.append(result)
                    completed_cases += 1

                    if self.progress_callback:
                        await self.progress_callback({
                            "type": "case_complete",
                            "case_id": case.get("id"),
                            "status": result["status"],
                            "progress": completed_cases / total_cases * 100,
                            "completed": completed_cases,
                            "total": total_cases
                        })

                if self.progress_callback:
                    await self.progress_callback({
                        "type": "task_complete",
                        "task_id": task_id,
                        "task_name": task_name
                    })

            passed = sum(1 for r in results if r["status"] == "passed")
            failed = sum(1 for r in results if r["status"] == "failed")

            return {
                "results": results,
                "summary": {
                    "total": len(results),
                    "passed": passed,
                    "failed": failed,
                    "success_rate": (passed / len(results)) * 100 if results else 0
                }
            }

        finally:
            self.is_running = False

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self):
        self.should_stop = True

    def get_status(self) -> dict:
        return {
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "should_stop": self.should_stop
        }


test_executor = TestExecutor()
