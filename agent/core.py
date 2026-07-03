"""
核心智能代理 - 任务编排与调度
- AgentState 按 task_id 隔离，多用户并发操作互不干扰
- UITestAgent 保留单例，但不持有任何任务级状态
"""
import asyncio
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from loguru import logger

from tools.browser import browser_pool, BrowserTool
from tools.document_parser import document_parser
from skills.case_generator import case_generator
from skills.test_executor import test_executor
from skills.report_generator import report_generator
from skills.skill_loader import skill_loader, SkillDefinition
from skills.skill_registry import skill_registry


class AgentState:
    """单个任务的运行状态，与其他任务完全隔离。"""
    def __init__(self, task_id: int):
        self.task_id: int = task_id
        self.current_task_status: str = "idle"
        self.cases: List[Dict[str, Any]] = []
        self.results: List[Dict[str, Any]] = []
        self.page_elements: List[Dict[str, Any]] = []
        self.document_data: Optional[Dict[str, Any]] = None
        self.current_url: str = ""
        self.intent_history: List[Dict[str, Any]] = []


class UITestAgent:
    """
    无全局任务状态的 Agent 单例。
    所有任务级数据通过 _states[task_id] 隔离存储，并发执行时互不干扰。
    """

    def __init__(self):
        self._states: Dict[int, AgentState] = {}
        self._websocket_manager: Optional[Any] = None
        self._skills_loaded = False

    # ── 状态管理 ─────────────────────────────────────────────────────────

    def _get_state(self, task_id: int) -> AgentState:
        if task_id not in self._states:
            self._states[task_id] = AgentState(task_id)
        return self._states[task_id]

    def _cleanup_state(self, task_id: int):
        """任务结束后清理状态，释放内存。"""
        self._states.pop(task_id, None)

    # ── 技能 & WebSocket ──────────────────────────────────────────────────

    def load_skills(self):
        if not self._skills_loaded:
            skill_registry.load_skills()
            self._skills_loaded = True
            logger.info(f"Loaded {len(skill_registry.list_skills())} skills")

    def set_websocket_manager(self, manager):
        self._websocket_manager = manager

    async def send_progress(self, data: Dict[str, Any]):
        if self._websocket_manager:
            await self._websocket_manager.broadcast_all(data)

    # ── 核心流程 ──────────────────────────────────────────────────────────

    async def create_task(
        self,
        name: str,
        url: str,
        document_path: Optional[str] = None,
        browser: str = "chromium",
        environment: str = "test",
    ) -> Dict[str, Any]:
        logger.info(f"Creating task: {name}")

        task_id = int(datetime.utcnow().timestamp() * 1000)
        state = self._get_state(task_id)
        state.current_task_status = "created"
        state.current_url = url

        task = {
            "id":            task_id,
            "name":          name,
            "url":           url,
            "document_path": document_path,
            "browser":       browser,
            "environment":   environment,
            "status":        "created",
            "created_at":    datetime.utcnow().isoformat(),
        }

        await self.send_progress({"type": "task_created", "task": task})
        return task

    async def parse_page(
        self, url: str, browser_type: str = "chromium", task_id: int = None
    ) -> List[Dict[str, Any]]:
        logger.info(f"Parsing page elements from: {url}")

        state = self._get_state(task_id or 0)
        state.current_task_status = "parsing"
        await self.send_progress({
            "type": "status",
            "status": "正在解析页面元素...",
            "step": "parse_page",
        })

        # 独立 Context，解析完立即释放
        bt = await browser_pool.acquire(browser_type)
        try:
            await bt.navigate(url)
            elements = await bt.capture_elements()
        finally:
            await bt.close()
            browser_pool.release(bt)

        state.page_elements = elements
        state.current_url = url

        await self.send_progress({
            "type": "page_parsed",
            "element_count": len(elements),
            "elements": elements[:10],
        })

        logger.info(f"Captured {len(elements)} elements")
        return elements

    async def parse_document(
        self, document_path: str, task_id: int = None
    ) -> Dict[str, Any]:
        logger.info(f"Parsing document: {document_path}")

        state = self._get_state(task_id or 0)
        state.current_task_status = "parsing"
        await self.send_progress({
            "type": "status",
            "status": "正在解析需求文档...",
            "step": "parse_document",
        })

        document_data = await document_parser.parse(document_path)
        state.document_data = document_data

        await self.send_progress({
            "type": "document_parsed",
            "page_count":      document_data.get("page_count", 0),
            "paragraph_count": document_data.get("paragraph_count", 0),
        })

        logger.info("Document parsed successfully")
        return document_data

    async def generate_cases(
        self, task_id: int = None, progress_cb=None
    ) -> List[Dict[str, Any]]:
        logger.info("Generating test cases...")

        state = self._get_state(task_id or 0)
        state.current_task_status = "generating"
        await self.send_progress({
            "type": "status",
            "status": "正在生成测试用例...",
            "step": "generate_cases",
        })

        cases = await case_generator.generate_cases(
            url=state.current_url,
            page_elements=state.page_elements,
            document_data=state.document_data,
            progress_cb=progress_cb,
        )

        for idx, case in enumerate(cases):
            case["id"] = idx + 1

        state.cases = cases

        await self.send_progress({
            "type": "cases_generated",
            "case_count": len(cases),
            "cases": cases[:5],
        })

        logger.info(f"Generated {len(cases)} test cases")
        return cases

    async def execute_cases(
        self,
        case_ids: List[int] = None,
        browser_type: str = "chromium",
        url: str = "",
        task_id: int = None,
    ) -> List[Dict[str, Any]]:
        logger.info("Executing test cases...")

        state = self._get_state(task_id or 0)
        state.current_task_status = "executing"
        state.results = []

        cases_to_execute = state.cases
        if case_ids:
            cases_to_execute = [c for c in state.cases if c["id"] in case_ids]

        await self.send_progress({
            "type": "execution_started",
            "total_cases": len(cases_to_execute),
        })

        async def progress_callback(progress_data):
            await self.send_progress({"type": "execution_progress", **progress_data})

        results = await test_executor.execute_batch(
            cases=cases_to_execute,
            url=url,
            browser_type=browser_type,
            screenshots_dir="./screenshots",
            progress_callback=progress_callback,
            task_id=task_id or 0,
        )

        state.results = results
        state.current_task_status = "completed"

        await self.send_progress({
            "type": "execution_completed",
            "results": {
                "total":  len(results),
                "passed": sum(1 for r in results if r.get("status") == "passed"),
                "failed": sum(1 for r in results if r.get("status") == "failed"),
            },
        })

        logger.info(f"Execution completed: {len(results)} results")
        return results

    async def generate_report(
        self, task_name: str, task_id: int = None
    ) -> Dict[str, Any]:
        logger.info("Generating test report...")

        state = self._get_state(task_id or 0)
        state.current_task_status = "reporting"
        await self.send_progress({
            "type": "status",
            "status": "正在生成测试报告...",
            "step": "generate_report",
        })

        report_data = await report_generator.generate_report(
            task_id=state.task_id,
            task_name=task_name,
            results=state.results,
            metadata={
                "total_cases": len(state.cases),
                "browser":     "chromium",
            },
        )

        await self.send_progress({
            "type": "report_generated",
            "report_path": report_data["html_path"],
        })

        logger.info(f"Report generated: {report_data['html_path']}")
        return report_data

    def parse_intent(self, message: str) -> Dict[str, Any]:
        message_lower = message.lower()

        if any(kw in message_lower for kw in ["执行", "运行", "开始", "run"]):
            if "全部" in message or "所有" in message:
                return {"action": "execute_all", "params": {}}
            elif "失败" in message:
                return {"action": "execute_failed", "params": {}}
            else:
                return {"action": "execute", "params": {}}
        elif any(kw in message_lower for kw in ["暂停", "pause"]):
            return {"action": "pause", "params": {}}
        elif any(kw in message_lower for kw in ["继续", "恢复", "resume"]):
            return {"action": "resume", "params": {}}
        elif any(kw in message_lower for kw in ["停止", "终止", "stop"]):
            return {"action": "stop", "params": {}}
        elif any(kw in message_lower for kw in ["重试", "retry", "重新"]):
            return {"action": "retry", "params": {}}
        elif any(kw in message_lower for kw in ["报告", "report"]):
            return {"action": "report", "params": {}}
        elif any(kw in message_lower for kw in ["用例", "cases"]):
            return {"action": "list_cases", "params": {}}
        elif any(kw in message_lower for kw in ["解析", "分析", "抓取", "页面"]):
            return {"action": "parse_page", "params": {}}
        elif any(kw in message_lower for kw in ["文档", "需求", "上传"]):
            return {"action": "parse_document", "params": {}}
        elif any(kw in message_lower for kw in ["生成", "创建"]):
            return {"action": "generate_cases", "params": {}}
        else:
            return {"action": "unknown", "params": {}}

    async def handle_command(
        self, message: str, task_id: int = None
    ) -> Dict[str, Any]:
        self.load_skills()

        skill_def, handler = skill_registry.find_skill(message)
        if skill_def:
            logger.info(f"Matched skill: {skill_def.name}")
            if skill_registry.is_external_skill(skill_def.name):
                await self.send_progress({
                    "type": "status",
                    "status": f"正在执行技能: {skill_def.name}...",
                    "step": "external_skill",
                })
                result = await skill_registry.execute_external_skill(
                    skill_def.name,
                    action="test",
                    params={"suite": "smoke", "headless": True},
                )
                await self.send_progress({
                    "type": "external_skill_completed",
                    "skill": skill_def.name,
                    "result": result,
                })
                return {"type": "external_skill_result", "skill": skill_def.name, "result": result}
            if handler:
                return await handler(message)

        state = self._get_state(task_id or 0)
        intent = self.parse_intent(message)
        state.intent_history.append({
            "message":       message,
            "intent":        intent,
            "timestamp":     datetime.utcnow().isoformat(),
            "matched_skill": skill_def.name if skill_def else None,
        })

        logger.info(f"Handling command: {message} -> {intent}")

        if intent["action"] in ("execute_all", "execute"):
            results = await self.execute_cases(task_id=task_id)
            return {"type": "execution_result", "results": results}

        elif intent["action"] == "execute_failed":
            failed_ids = [r.get("case_id") for r in state.results if r.get("status") == "failed"]
            results = await self.execute_cases(case_ids=failed_ids, task_id=task_id)
            return {"type": "execution_result", "results": results}

        elif intent["action"] == "pause":
            test_executor.pause()
            return {"type": "status", "message": "测试已暂停"}

        elif intent["action"] == "resume":
            test_executor.resume()
            return {"type": "status", "message": "测试已继续"}

        elif intent["action"] == "stop":
            test_executor.stop()
            return {"type": "status", "message": "停止指令已发送"}

        elif intent["action"] == "list_cases":
            return {"type": "cases_list", "cases": state.cases, "total": len(state.cases)}

        elif intent["action"] == "report":
            report = await self.generate_report(f"Task_{task_id}", task_id=task_id)
            return {"type": "report", "report": report}

        elif intent["action"] == "generate_cases":
            cases = await self.generate_cases(task_id=task_id)
            return {"type": "cases_generated", "cases": cases, "count": len(cases)}

        elif intent["action"] == "parse_page":
            return {"type": "status", "message": "请提供要解析的页面URL"}

        elif intent["action"] == "parse_document":
            return {"type": "status", "message": "请提供要解析的文档路径"}

        else:
            return {
                "type":             "unknown_command",
                "message":          f"无法理解指令: {message}",
                "hint":             "支持的指令：执行全部用例、暂停、继续、停止、重试、查看报告、生成用例、解析页面",
                "available_skills": [s.name for s in skill_registry.list_skills()],
            }

    def get_state(self, task_id: int = None) -> Dict[str, Any]:
        self.load_skills()
        state = self._get_state(task_id or 0) if task_id else AgentState(0)
        return {
            "task_id":       task_id,
            "status":        state.current_task_status,
            "case_count":    len(state.cases),
            "result_count":  len(state.results),
            "element_count": len(state.page_elements),
            "executor_status": test_executor.get_status(task_id),
            "loaded_skills": [s.name for s in skill_registry.list_skills()],
        }

    def get_skills(self) -> List[Dict[str, Any]]:
        self.load_skills()
        return [
            {
                "name":        s.name,
                "description": s.description,
                "version":     s.version,
                "category":    s.category,
                "triggers":    s.triggers,
                "examples":    s.examples,
                "file_path":   s.file_path,
            }
            for s in skill_registry.list_skills()
        ]


uitest_agent = UITestAgent()
