"""
测试执行技能
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
from loguru import logger
from tools.browser import BrowserTool, browser_pool
from tools.config import settings


class TestExecutor:
    def __init__(self):
        self.current_task_id: Optional[int] = None
        self.is_running: bool = False
        self.is_paused: bool = False
        self.should_stop: bool = False
        self.progress_callback: Optional[Callable] = None

    def _execute_batch_sync(
        self,
        cases: List[Dict[str, Any]],
        url: str,
        browser_type: str = "chromium",
        screenshots_dir: str = None,
        progress_queue=None
    ) -> List[Dict[str, Any]]:
        """
        同步批量执行测试用例（在单独线程中运行）
        """
        results = []
        total_cases = len(cases)
        completed_cases = 0
        browser = None
        
        try:
            browser = BrowserTool(browser_type)
            browser._launch_sync()
            
            if url:
                browser.sync_navigate(url)
            
            for case in cases:
                if self.should_stop:
                    break
                
                start_time = datetime.utcnow()
                
                try:
                    screenshot_path = None
                    error_message = None
                    
                    if case.get("element_selector"):
                        try:
                            selector = case["element_selector"]
                            
                            if "input" in case.get("name", "").lower():
                                browser.sync_wait_for_selector(selector, timeout=5000)
                                browser.sync_fill_input(selector, "Test123")
                            
                            elif "点击" in case.get("name", "") or "button" in case.get("name", "").lower():
                                browser.sync_wait_for_selector(selector, timeout=5000)
                                browser.sync_click_element(selector)
                            
                            elif "选择" in case.get("name", "") or "select" in case.get("name", "").lower():
                                browser.sync_wait_for_selector(selector, timeout=5000)
                                browser.sync_select_option(selector, "1")
                            
                            else:
                                browser.sync_wait_for_selector(selector, timeout=5000)
                                browser.sync_click_element(selector)
                            
                            import time
                            time.sleep(0.5)
                            
                        except Exception as e:
                            error_message = str(e)
                            logger.error(f"Case execution error: {e}")
                    
                    if screenshots_dir and not error_message:
                        screenshot_filename = f"case_{case.get('id', 'unknown')}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
                        screenshot_path = str(Path(screenshots_dir) / screenshot_filename)
                        browser.sync_take_screenshot(screenshot_path)
                    
                    end_time = datetime.utcnow()
                    duration = (end_time - start_time).total_seconds()
                    
                    status = "passed" if not error_message else "failed"
                    
                    result = {
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

                    result = {
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
                
                results.append(result)
                completed_cases += 1
                
                if progress_queue:
                    progress_queue.put({
                        "type": "case_complete",
                        "case_id": case.get("id"),
                        "case_name": case.get("name", ""),
                        "status": result["status"],
                        "progress": completed_cases / total_cases * 100,
                        "current": completed_cases,
                        "total": total_cases
                    })
            
            return results
            
        finally:
            if browser:
                browser.close()
            self.is_running = False

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
        
        import queue
        progress_queue = queue.Queue()
        
        async def process_progress():
            while self.is_running or not progress_queue.empty():
                try:
                    progress_data = progress_queue.get(timeout=0.5)
                    if progress_callback:
                        await progress_callback(progress_data)
                except queue.Empty:
                    await asyncio.sleep(0.1)
        
        progress_task = asyncio.create_task(process_progress())
        
        results = await asyncio.to_thread(
            self._execute_batch_sync,
            cases,
            url,
            browser_type,
            screenshots_dir,
            progress_queue
        )
        
        await progress_task
        
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
            browser = browser_pool.get_browser(browser_type)
            page = browser.page

            browser.navigate(url)

            screenshot_path = None
            error_message = None

            if case.get("element_selector"):
                try:
                    selector = case["element_selector"]

                    if "input" in case.get("name", "").lower():
                        page.wait_for_selector(selector, timeout=5000)
                        test_value = "Test123"
                        page.fill(selector, test_value)

                    elif "点击" in case.get("name", "") or "button" in case.lower():
                        page.wait_for_selector(selector, timeout=5000)
                        page.click(selector)

                    elif "选择" in case.get("name", "") or "select" in case.get("name", "").lower():
                        page.wait_for_selector(selector, timeout=5000)
                        options = page.query_selector_all(f"{selector} option")
                        if len(options) > 1:
                            page.select_option(selector, options[1].get_attribute("value"))

                    else:
                        page.wait_for_selector(selector, timeout=5000)
                        page.click(selector)

                    await asyncio.sleep(0.5)

                except Exception as e:
                    error_message = str(e)
                    logger.error(f"Case execution error: {e}")

            if screenshots_dir:
                screenshot_filename = f"case_{case['id']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
                screenshot_path = str(Path(screenshots_dir) / screenshot_filename)
                page.screenshot(path=screenshot_path, full_page=True)

            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            status = "passed" if not error_message else "failed"

            return {
                "case_id": case.get("id"),
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

    async def stop(self):
        self.should_stop = True


test_executor = TestExecutor()
