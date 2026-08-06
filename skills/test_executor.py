"""
测试执行技能
- 执行状态按 task_id 隔离，多用户并发执行互不干扰
- 每条用例创建独立浏览器 Context，执行完立即释放
"""
import asyncio
import json
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
            # ── 预检：执行前先确认目标页面可达 ──
            try:
                precheck_bt = await browser_pool.acquire(browser_type)
                try:
                    # 轻量 goto：不用 navigate() 的 networkidle+滚动+等待，只确认页面可达
                    await asyncio.wait_for(
                        precheck_bt.page.goto(url, wait_until="domcontentloaded", timeout=15000),
                        timeout=18,
                    )
                    logger.info(f"[Pre-flight] URL {url} 可达")
                except asyncio.TimeoutError:
                    logger.error(f"[Pre-flight] URL {url} 连接超时（18s）")
                    return [{
                        "case_id": None, "case_name": "（连通性预检）",
                        "status": "failed", "start_time": datetime.utcnow().isoformat(),
                        "end_time": datetime.utcnow().isoformat(), "duration": 18,
                        "error_message": f"目标页面 {url} 无法访问（18秒超时），请检查：\n1. 页面地址是否正确\n2. 测试服务器能否访问该地址\n3. 是否需要 VPN/代理",
                        "screenshot_path": None, "logs": "",
                    }]
                except Exception as e:
                    logger.error(f"[Pre-flight] URL {url} 导航失败: {e}")
                    return [{
                        "case_id": None, "case_name": "（连通性预检）",
                        "status": "failed", "start_time": datetime.utcnow().isoformat(),
                        "end_time": datetime.utcnow().isoformat(), "duration": 0,
                        "error_message": f"目标页面 {url} 无法访问：{str(e)[:200]}",
                        "screenshot_path": None, "logs": "",
                    }]
                finally:
                    try:
                        await precheck_bt.close()
                    except Exception:
                        pass
                    browser_pool.release(precheck_bt)
            except Exception as e:
                logger.error(f"[Pre-flight] 浏览器启动失败: {e}")
                return [{
                    "case_id": None, "case_name": "（浏览器启动预检）",
                    "status": "failed", "start_time": datetime.utcnow().isoformat(),
                    "end_time": datetime.utcnow().isoformat(), "duration": 0,
                    "error_message": f"浏览器启动失败（{browser_type}）：{str(e)[:200]}。请确认 Playwright 浏览器已正确安装。",
                    "screenshot_path": None, "logs": "",
                }]

            for case in cases:
                if state.should_stop:
                    break

                while state.is_paused and not state.should_stop:
                    await asyncio.sleep(0.2)
                if state.should_stop:
                    break

                result = await self.execute_case(
                    case, url, browser_type, screenshots_dir,
                    task_id=_task_id,
                    step_callback=progress_callback,
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
        task_id: int = None,
        step_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        执行单条用例，优先使用 ActionRunner 执行结构化 steps_json，
        无结构化步骤时回退到 element_selector 简单执行。
        """
        start_time = datetime.utcnow()
        bt = None

        try:
            bt = await browser_pool.acquire(browser_type)
            await bt.navigate(url)

            screenshot_path = None
            error_message = None

            # ── 方案C：优先使用 ActionRunner 执行结构化步骤 ──
            steps_json = case.get("steps_json")
            if steps_json:
                try:
                    if isinstance(steps_json, str):
                        steps_json = json.loads(steps_json)

                    if steps_json and isinstance(steps_json, list):
                        from skills.action_runner import ActionRunner
                        from tools.database import TaskEnvVar, async_session_maker
                        from sqlalchemy import select as _sa_select

                        runner = ActionRunner(task_id=task_id, browser=browser_type)
                        if step_callback:
                            runner.step_callback = step_callback

                        # 加载任务级环境变量 + 元素别名库（共享同一个 session）
                        try:
                            async with async_session_maker() as _ses:
                                _r = await _ses.execute(
                                    _sa_select(TaskEnvVar).where(TaskEnvVar.task_id == task_id)
                                )
                                runner.env_vars = {ev.key: ev.value for ev in _r.scalars().all()}
                                # 把 db session 挂上去，让 _load_aliases 能读别名库
                                runner.db = _ses
                                await runner._load_aliases()
                                runner.db = None   # 加载完解绑，避免跨 session 使用
                        except Exception:
                            pass

                        # 直接委托给 ActionRunner.run_case，所有新特性（别名解析、
                        # 语义 locator、strict mode 降级、AI 修复）在这里统一处理
                        case_payload = dict(case)
                        case_payload["steps_json"] = steps_json
                        result = await runner.run_case(case_payload, bt.page)

                        end_time = datetime.utcnow()
                        step_results = result.get("steps", [])   # _case_result 用 "steps" 字段
                        case_passed = result.get("status") == "passed"
                        # 从失败步骤里提取错误信息
                        failed_steps = [s for s in step_results if not s.get("passed")]
                        err = failed_steps[0].get("error", "") if failed_steps else ""
                        # 失败步骤截图（ActionRunner 已在 step_result 里记录路径）
                        failed_shot = next(
                            (s.get("screenshot") for s in step_results if s.get("screenshot")),
                            screenshot_path,
                        )
                        return {
                            "case_id": case.get("id"),
                            "case_name": case.get("name", ""),
                            "status": "passed" if case_passed else "failed",
                            "start_time": start_time.isoformat(),
                            "end_time": end_time.isoformat(),
                            "duration": (end_time - start_time).total_seconds(),
                            "error_message": err,
                            "screenshot_path": failed_shot or "",
                            "logs": json.dumps(step_results, ensure_ascii=False),
                        }
                except Exception as e:
                    logger.warning(f"ActionRunner 执行失败，回退到简单执行: {e}")

            # ── 回退：简单 element_selector 执行（旧逻辑） ──
            if error_message or not case.get("steps_json"):
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
                        error_message = None  # 简单执行成功

                    except Exception as e:
                        error_message = error_message or str(e)
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

                    result = await self.execute_case(case, url, browser_type, task_id=task_id)
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
