"""
测试执行技能
- 执行状态按 task_id 隔离，多用户并发执行互不干扰
- 每条用例创建独立浏览器 Context，执行完立即释放
- 方案一：case 级 setup_steps，在 steps_json 前执行前置步骤
- 方案三：task 级 storage_state 快照，一次登录全批复用
"""
import asyncio
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
from loguru import logger
from tools.browser import browser_pool
from tools.config import settings

# 快照存储目录
_STORAGE_DIR = Path("./screenshots/.storage_states")
_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


class TaskExecutionState:
    """单次任务的执行状态，与其他任务完全隔离。"""
    def __init__(self):
        self.is_running: bool = False
        self.is_paused: bool = False
        self.should_stop: bool = False
        self._active_browser_tool = None  # 当前活跃的 BrowserTool，stop 时主动关闭

    def pause(self):  self.is_paused = True
    def resume(self): self.is_paused = False

    def stop(self):
        self.should_stop = True
        # 主动关闭活跃浏览器 Context，打断正在执行的 Playwright 操作
        bt = self._active_browser_tool
        if bt is not None:
            try:
                import asyncio
                asyncio.ensure_future(self._force_close_browser(bt))
            except Exception:
                pass

    async def _force_close_browser(self, bt):
        """在 stop 时强制关闭浏览器 Context，导致当前 Playwright 操作立即报错退出。"""
        try:
            await bt.close()
        except Exception:
            pass
        try:
            from tools.browser import browser_pool
            browser_pool.release(bt)
        except Exception:
            pass

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
        setup_case: Optional[Dict[str, Any]] = None,
        storage_state_path: Optional[str] = None,
        storage_ttl_minutes: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        批量执行测试用例。
        task_id           — 用于隔离暂停/继续/停止控制
        setup_case        — 登录用例 dict（方案三：执行前先跑它，保存 storage_state）
        storage_state_path— 快照文件路径（由本方法自动管理）
        storage_ttl_minutes — 快照有效期分钟数（0=每次重跑）
        """
        _task_id = task_id or id(cases)
        state = self._get_state(_task_id)
        self._current_task_id = _task_id

        state.is_running = True
        state.should_stop = False
        was_stopped = False
        results = []
        total_cases = len(cases)
        completed_cases = 0

        # ── 方案三：生成 / 复用 storage_state 快照 ──────────────────────────
        active_storage_state = None
        if setup_case:
            snap_path = Path(storage_state_path) if storage_state_path else \
                        _STORAGE_DIR / f"task_{_task_id}.json"
            active_storage_state = await self._ensure_storage_state(
                setup_case=setup_case,
                url=url,
                browser_type=browser_type,
                snap_path=snap_path,
                ttl_minutes=storage_ttl_minutes,
                progress_callback=progress_callback,
            )

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
                    was_stopped = True
                    break

                while state.is_paused and not state.should_stop:
                    await asyncio.sleep(0.2)
                if state.should_stop:
                    was_stopped = True
                    break

                # 方案三：use_storage 明确为 True 时注入快照（默认 False，不自动注入）
                case_storage = None
                if active_storage_state and case.get("use_storage") is True:
                    case_storage = active_storage_state

                result = await self.execute_case(
                    case, url, browser_type, screenshots_dir,
                    task_id=_task_id,
                    step_callback=progress_callback,
                    storage_state=case_storage,
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
        storage_state=None,
    ) -> Dict[str, Any]:
        """
        执行单条用例，优先使用 ActionRunner 执行结构化 steps_json，
        无结构化步骤时回退到 element_selector 简单执行。
        storage_state: 文件路径或状态字典，注入登录态（方案三）。
        """
        start_time = datetime.utcnow()
        bt = None
        state = self._get_state(task_id) if task_id else None

        try:
            bt = await browser_pool.acquire(browser_type, storage_state=storage_state)

            # ── 注册活跃浏览器，供 stop 时强制关闭 ──
            if state:
                state._active_browser_tool = bt

            await bt.navigate(url)

            screenshot_path = None
            error_message = None

            # ── 方案C：优先使用 ActionRunner 执行结构化步骤 ──
            steps_json = case.get("steps_json")
            if steps_json:
                try:
                    # 执行前检查 stop 标志
                    if state and state.should_stop:
                        end_time = datetime.utcnow()
                        return {
                            "case_id": case.get("id"),
                            "case_name": case.get("name", ""),
                            "status": "skipped",
                            "start_time": start_time.isoformat(),
                            "end_time": end_time.isoformat(),
                            "duration": 0,
                            "error_message": "用户停止执行",
                            "screenshot_path": "",
                            "logs": "",
                        }

                    if isinstance(steps_json, str):
                        steps_json = json.loads(steps_json)

                    if steps_json and isinstance(steps_json, list):
                        from skills.action_runner import ActionRunner
                        from tools.database import TaskEnvVar, async_session_maker
                        from sqlalchemy import select as _sa_select

                        # 传入 stop 检查回调，让 ActionRunner 感知停止信号
                        _stop_cb = (lambda st=state: st.should_stop) if state else None
                        runner = ActionRunner(task_id=task_id, browser=browser_type, should_stop_cb=_stop_cb)
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

                        # ── 方案一：先执行 setup_steps（与主步骤共用同一 Page）──
                        setup_steps = case.get("setup_steps")
                        if setup_steps:
                            if isinstance(setup_steps, str):
                                try:
                                    setup_steps = json.loads(setup_steps)
                                except Exception:
                                    setup_steps = []
                            if setup_steps and isinstance(setup_steps, list):
                                logger.info(f"[execute_case] case={case.get('id')} 执行前置步骤 {len(setup_steps)} 步")
                                setup_payload = dict(case)
                                setup_payload["steps_json"] = setup_steps
                                setup_payload["name"] = f"{case.get('name','')}_setup"
                                setup_result = await runner.run_case(setup_payload, bt.page)
                                if setup_result.get("status") != "passed":
                                    # 前置步骤失败 → 直接标记用例为 failed，跳过主步骤
                                    end_time = datetime.utcnow()
                                    setup_err = next(
                                        (s.get("error","") for s in setup_result.get("steps",[]) if not s.get("passed")),
                                        "前置步骤失败"
                                    )
                                    logger.warning(f"[execute_case] case={case.get('id')} 前置步骤失败: {setup_err}")
                                    return {
                                        "case_id": case.get("id"),
                                        "case_name": case.get("name", ""),
                                        "status": "failed",
                                        "start_time": start_time.isoformat(),
                                        "end_time": end_time.isoformat(),
                                        "duration": (end_time - start_time).total_seconds(),
                                        "error_message": f"[前置步骤失败] {setup_err}",
                                        "screenshot_path": next(
                                            (s.get("screenshot","") for s in setup_result.get("steps",[]) if s.get("screenshot")),
                                            ""
                                        ),
                                        "logs": setup_result.get("steps", []),
                                    }

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
            # ── 清理活跃浏览器引用，防止 stop 重复关闭 ──
            if state:
                state._active_browser_tool = None
            if bt:
                try:
                    await bt.close()
                except Exception:
                    pass
                browser_pool.release(bt)

    # ── 方案三：storage_state 快照管理 ─────────────────────────────────────

    async def _ensure_storage_state(
        self,
        setup_case: Dict[str, Any],
        url: str,
        browser_type: str,
        snap_path: Path,
        ttl_minutes: int,
        progress_callback: Optional[Callable] = None,
    ) -> Optional[str]:
        """
        确保 storage_state 快照存在且在有效期内。
        - 有效：直接返回快照路径
        - 无效/不存在：执行 setup_case，保存快照后返回路径
        - ttl_minutes=0：每次都重新跑
        返回快照文件路径（str），失败返回 None（降级为无登录态执行）。
        """
        snap_path = Path(snap_path)

        # 检查快照是否在有效期内
        if ttl_minutes > 0 and snap_path.exists():
            age_minutes = (time.time() - snap_path.stat().st_mtime) / 60
            if age_minutes < ttl_minutes:
                logger.info(f"[storage_state] 复用快照 {snap_path}（剩余 {ttl_minutes - age_minutes:.1f} 分钟）")
                return str(snap_path)
            else:
                logger.info(f"[storage_state] 快照已过期（{age_minutes:.1f} 分钟），重新生成")

        # 通知前端
        if progress_callback:
            try:
                await progress_callback({
                    "type": "setup_running",
                    "message": f"正在执行登录前置用例「{setup_case.get('name', '')}」...",
                })
            except Exception:
                pass

        # 执行 setup 用例，获取登录态
        bt = None
        try:
            bt = await browser_pool.acquire(browser_type)  # 干净 context
            await bt.navigate(url)

            steps_json = setup_case.get("steps_json")
            if isinstance(steps_json, str):
                steps_json = json.loads(steps_json)

            if not steps_json:
                logger.warning("[storage_state] setup_case 无 steps_json，跳过快照生成")
                return None

            from skills.action_runner import ActionRunner
            runner = ActionRunner(task_id=0, browser=browser_type)
            setup_payload = dict(setup_case)
            setup_payload["steps_json"] = steps_json
            result = await runner.run_case(setup_payload, bt.page)

            if result.get("status") != "passed":
                failed_err = next(
                    (s.get("error", "") for s in result.get("steps", []) if not s.get("passed")),
                    "setup 用例失败"
                )
                logger.warning(f"[storage_state] setup 用例执行失败: {failed_err}，将以无登录态继续")
                return None

            # 保存 storage_state 到文件
            snap_path.parent.mkdir(parents=True, exist_ok=True)
            await bt.context.storage_state(path=str(snap_path))
            logger.info(f"[storage_state] 快照已保存: {snap_path}")

            if progress_callback:
                try:
                    await progress_callback({
                        "type": "setup_done",
                        "message": "登录态已建立，开始执行测试用例",
                    })
                except Exception:
                    pass

            return str(snap_path)

        except Exception as e:
            logger.error(f"[storage_state] 快照生成异常: {e}，将以无登录态继续")
            return None
        finally:
            if bt:
                try:
                    await bt.close()
                except Exception:
                    pass
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
