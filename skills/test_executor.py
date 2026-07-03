"""
测试执行技能
- 执行状态按 task_id 隔离，多用户并发执行互不干扰
- 每条用例创建独立浏览器 Context，执行完立即释放
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
from loguru import logger
from tools.browser import browser_pool
from tools.config import settings


class TaskExecutionState:
    """单次任务的执行状态，与其他任务完全隔离。"""
    def __init__(self):
        self.is_running: bool = False
        self.is_paused: bool = False
        self.should_stop: bool = False

    def pause(self):  self.is_paused = True
    def resume(self): self.is_paused = False
    def stop(self):   self.should_stop = True

    def to_dict(self) -> dict:
        return {
            "is_running":   self.is_running,
            "is_paused":    self.is_paused,
            "should_stop":  self.should_stop,
        }


class TestExecutor:
    """
    无全局执行状态的测试执行器。
    每次 execute_batch / execute_test_suite 调用都通过 task_id 维护独立状态，
    多用户并发执行时互不干扰。
    """

    def __init__(self):
        # 按 task_id 存储各任务执行状态
        self._states: Dict[int, TaskExecutionState] = {}
        # 向后兼容：保留一个"当前任务"引用，单用户场景下可直接调用 pause/resume/stop
        self._current_task_id: Optional[int] = None

    # ── 状态管理 ─────────────────────────────────────────────────────────

    def _get_state(self, task_id: int) -> TaskExecutionState:
        if task_id not in self._states:
            self._states[task_id] = TaskExecutionState()
        return self._states[task_id]

    def _cleanup_state(self, task_id: int):
        """任务结束后清理状态，避免内存泄漏。"""
        self._states.pop(task_id, None)

    # ── 向后兼容接口 ──────────────────────────────────────────────────────

    def pause(self):
        if self._current_task_id is not None:
            self._get_state(self._current_task_id).pause()

    def resume(self):
        if self._current_task_id is not None:
            self._get_state(self._current_task_id).resume()

    def stop(self):
        if self._current_task_id is not None:
            self._get_state(self._current_task_id).stop()

    def pause_task(self, task_id: int):
        self._get_state(task_id).pause()

    def resume_task(self, task_id: int):
        self._get_state(task_id).resume()

    def stop_task(self, task_id: int):
        self._get_state(task_id).stop()

    def get_status(self, task_id: int = None) -> dict:
        if task_id is not None:
            return self._get_state(task_id).to_dict()
        # 向后兼容：返回当前任务状态
        if self._current_task_id is not None:
            return self._get_state(self._current_task_id).to_dict()
        return {"is_running": False, "is_paused": False, "should_stop": False}

    # ── 核心执行逻辑 ──────────────────────────────────────────────────────

    async def execute_batch(
        self,
        cases: List[Dict[str, Any]],
        url: str,
        browser_type: str = "chromium",
        screenshots_dir: str = None,
        progress_callback: Optional[Callable] = None,
        task_id: int = None,
    ) -> List[Dict[str, Any]]:
        """
        批量执行测试用例。
        task_id 用于隔离暂停/继续/停止控制，多用户并发执行互不干扰。
        """
        _task_id = task_id or id(cases)   # 没传 task_id 时用对象地址作唯一键
        state = self._get_state(_task_id)
        self._current_task_id = _task_id  # 向后兼容

        state.is_running = True
        state.should_stop = False
        results = []
        total_cases = len(cases)
        completed_cases = 0

        try:
            for case in cases:
                if state.should_stop:
                    break

                while state.is_paused and not state.should_stop:
                    await asyncio.sleep(0.2)
                if state.should_stop:
                    break

                result = await self.execute_case(
                    case, url, browser_type, screenshots_dir
                )
                results.append(result)
                completed_cases += 1

                if progress_callback:
                    await progress_callback({
                        "type": "case_complete",
                        "case_id":        result.get("case_id"),
                        "case_name":      result.get("case_name", ""),
                        "status":         result["status"],
                        "duration":       result.get("duration", 0),
                        "error_message":  result.get("error_message"),
                        "screenshot_path": result.get("screenshot_path"),
                        "progress":       completed_cases / total_cases * 100,
                        "current":        completed_cases,
                        "total":          total_cases,
                    })
        finally:
            state.is_running = False
            self._cleanup_state(_task_id)

        return results

    async def execute_case(
        self,
        case: Dict[str, Any],
        url: str,
        browser_type: str = "chromium",
        screenshots_dir: str = None,
    ) -> Dict[str, Any]:
        """
        执行单条用例，使用独立 Context，执行完立即释放。
        """
        start_time = datetime.utcnow()
        bt = None

        try:
            # 每条用例获取独立 Context
            bt = await browser_pool.acquire(browser_type)

            await bt.navigate(url)

            screenshot_path = None
            error_message = None

            if case.get("element_selector"):
                try:
                    selector = case["element_selector"]
                    case_name = case.get("name", "").lower()

                    if "input" in case_name:
                        await bt.wait_for_selector(selector, timeout=5000)
                        await bt.fill_input(selector, "Test123")

                    elif "点击" in case_name or "button" in case_name:
                        await bt.wait_for_selector(selector, timeout=5000)
                        await bt.click_element(selector)

                    elif "选择" in case_name or "select" in case_name:
                        await bt.wait_for_selector(selector, timeout=5000)
                        await bt.select_option(selector, "1")

                    else:
                        await bt.wait_for_selector(selector, timeout=5000)
                        await bt.click_element(selector)

                    await asyncio.sleep(0.5)

                except Exception as e:
                    error_message = str(e)
                    logger.error(f"Case execution error: {e}")

            if screenshots_dir:
                status_tag = "fail" if error_message else "pass"
                screenshot_filename = (
                    f"case_{case.get('id', 'unknown')}_{status_tag}_"
                    f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
                )
                screenshot_path = str(Path(screenshots_dir) / screenshot_filename)
                try:
                    await bt.take_screenshot(screenshot_path)
                except Exception as se:
                    logger.warning(f"Screenshot failed: {se}")
                    screenshot_path = None

            end_time = datetime.utcnow()
            status = "passed" if not error_message else "failed"

            return {
                "case_id":        case.get("id"),
                "case_name":      case.get("name", ""),
                "status":         status,
                "start_time":     start_time.isoformat(),
                "end_time":       end_time.isoformat(),
                "duration":       (end_time - start_time).total_seconds(),
                "error_message":  error_message,
                "screenshot_path": screenshot_path,
                "logs":           f"Executed case: {case.get('name')}",
            }

        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            end_time = datetime.utcnow()
            return {
                "case_id":        case.get("id"),
                "case_name":      case.get("name", ""),
                "status":         "failed",
                "start_time":     start_time.isoformat(),
                "end_time":       end_time.isoformat(),
                "duration":       (end_time - start_time).total_seconds(),
                "error_message":  str(e),
                "screenshot_path": None,
                "logs":           f"Execution failed: {str(e)}",
            }

        finally:
            # 执行完立即关闭 Context，释放并发槽位
            if bt:
                await bt.close()
                browser_pool.release(bt)

    async def execute_test_suite(
        self,
        tasks: List[Dict[str, Any]],
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """执行测试套件（多任务）。"""
        suite_task_id = id(tasks)
        state = self._get_state(suite_task_id)
        self._current_task_id = suite_task_id

        state.is_running = True
        state.should_stop = False

        results = []
        total_cases = sum(len(task.get("cases", [])) for task in tasks)
        completed_cases = 0

        try:
            for task in tasks:
                if state.should_stop:
                    break

                task_id   = task.get("id")
                task_name = task.get("name")
                url       = task.get("url")
                browser_type = task.get("browser", "chromium")
                cases = task.get("cases", [])

                if progress_callback:
                    await progress_callback({
                        "type":        "task_start",
                        "task_id":     task_id,
                        "task_name":   task_name,
                        "total_cases": len(cases),
                    })

                for case in cases:
                    if state.should_stop:
                        break

                    while state.is_paused and not state.should_stop:
                        await asyncio.sleep(0.2)
                    if state.should_stop:
                        break

                    result = await self.execute_case(case, url, browser_type)
                    results.append(result)
                    completed_cases += 1

                    if progress_callback:
                        await progress_callback({
                            "type":      "case_complete",
                            "case_id":   case.get("id"),
                            "status":    result["status"],
                            "progress":  completed_cases / total_cases * 100,
                            "completed": completed_cases,
                            "total":     total_cases,
                        })

                if progress_callback:
                    await progress_callback({
                        "type":      "task_complete",
                        "task_id":   task_id,
                        "task_name": task_name,
                    })

            passed = sum(1 for r in results if r["status"] == "passed")
            failed = sum(1 for r in results if r["status"] == "failed")

            return {
                "results": results,
                "summary": {
                    "total":        len(results),
                    "passed":       passed,
                    "failed":       failed,
                    "success_rate": (passed / len(results)) * 100 if results else 0,
                },
            }

        finally:
            state.is_running = False
            self._cleanup_state(suite_task_id)


test_executor = TestExecutor()
