"""
核心智能代理 - 任务编排与调度
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
    def __init__(self):
        self.current_task_id: Optional[int] = None
        self.current_task_status: str = "idle"
        self.cases: List[Dict[str, Any]] = []
        self.results: List[Dict[str, Any]] = []
        self.page_elements: List[Dict[str, Any]] = []
        self.document_data: Optional[Dict[str, Any]] = None
        self.intent_history: List[Dict[str, Any]] = []


class UITestAgent:
    def __init__(self):
        self.state = AgentState()
        self._websocket_manager: Optional[Any] = None
        self._skills_loaded = False

    def load_skills(self):
        if not self._skills_loaded:
            skill_registry.load_skills()
            self._skills_loaded = True
            logger.info(f"Loaded {len(skill_registry.list_skills())} skills")

    def set_websocket_manager(self, manager):
        self._websocket_manager = manager

    async def send_progress(self, data: Dict[str, Any]):
        if self._websocket_manager:
            await self._websocket_manager.broadcast(data)

    async def create_task(
        self,
        name: str,
        url: str,
        document_path: Optional[str] = None,
        browser: str = "chromium",
        environment: str = "test"
    ) -> Dict[str, Any]:
        logger.info(f"Creating task: {name}")

        self.state.current_task_id = int(datetime.utcnow().timestamp() * 1000)
        self.state.current_task_status = "created"

        task = {
            "id": self.state.current_task_id,
            "name": name,
            "url": url,
            "document_path": document_path,
            "browser": browser,
            "environment": environment,
            "status": "created",
            "created_at": datetime.utcnow().isoformat()
        }

        await self.send_progress({
            "type": "task_created",
            "task": task
        })

        return task

    async def parse_page(self, url: str, browser_type: str = "chromium") -> List[Dict[str, Any]]:
        logger.info(f"Parsing page elements from: {url}")

        self.state.current_task_status = "parsing"
        await self.send_progress({
            "type": "status",
            "status": "正在解析页面元素...",
            "step": "parse_page"
        })

        browser = await browser_pool.get_browser(browser_type)
        await browser.navigate(url)
        elements = await browser.capture_elements()
        
        self.state.page_elements = elements

        await self.send_progress({
            "type": "page_parsed",
            "element_count": len(elements),
            "elements": elements[:10]
        })

        logger.info(f"Captured {len(elements)} elements")
        return elements

    async def parse_document(self, document_path: str) -> Dict[str, Any]:
        logger.info(f"Parsing document: {document_path}")

        self.state.current_task_status = "parsing"
        await self.send_progress({
            "type": "status",
            "status": "正在解析需求文档...",
            "step": "parse_document"
        })

        document_data = await document_parser.parse(document_path)
        self.state.document_data = document_data

        await self.send_progress({
            "type": "document_parsed",
            "page_count": document_data.get("page_count", 0),
            "paragraph_count": document_data.get("paragraph_count", 0)
        })

        logger.info(f"Document parsed successfully")
        return document_data

    async def generate_cases(self) -> List[Dict[str, Any]]:
        logger.info("Generating test cases...")

        self.state.current_task_status = "generating"
        await self.send_progress({
            "type": "status",
            "status": "正在生成测试用例...",
            "step": "generate_cases"
        })

        cases = await case_generator.generate_cases(
            url="",
            page_elements=self.state.page_elements,
            document_data=self.state.document_data
        )

        for idx, case in enumerate(cases):
            case["id"] = idx + 1

        self.state.cases = cases

        await self.send_progress({
            "type": "cases_generated",
            "case_count": len(cases),
            "cases": cases[:5]
        })

        logger.info(f"Generated {len(cases)} test cases")
        return cases

    async def execute_cases(
        self,
        case_ids: List[int] = None,
        browser_type: str = "chromium",
        url: str = ""
    ) -> List[Dict[str, Any]]:
        logger.info("Executing test cases...")

        self.state.current_task_status = "executing"
        self.state.results = []

        cases_to_execute = self.state.cases
        if case_ids:
            cases_to_execute = [c for c in self.state.cases if c["id"] in case_ids]

        await self.send_progress({
            "type": "execution_started",
            "total_cases": len(cases_to_execute)
        })

        async def progress_callback(progress_data):
            await self.send_progress({
                "type": "execution_progress",
                **progress_data
            })

        results = await test_executor.execute_batch(
            cases=cases_to_execute,
            url=url,
            browser_type=browser_type,
            screenshots_dir="./screenshots",
            progress_callback=progress_callback
        )

        self.state.results = results
        self.state.current_task_status = "completed"

        await self.send_progress({
            "type": "execution_completed",
            "results": {
                "total": len(results),
                "passed": sum(1 for r in results if r.get("status") == "passed"),
                "failed": sum(1 for r in results if r.get("status") == "failed")
            }
        })

        logger.info(f"Execution completed: {len(results)} results")
        return results

    async def generate_report(self, task_name: str) -> Dict[str, Any]:
        logger.info("Generating test report...")

        self.state.current_task_status = "reporting"
        await self.send_progress({
            "type": "status",
            "status": "正在生成测试报告...",
            "step": "generate_report"
        })

        report_data = await report_generator.generate_report(
            task_id=self.state.current_task_id or 0,
            task_name=task_name,
            results=self.state.results,
            metadata={
                "total_cases": len(self.state.cases),
                "browser": "chromium"
            }
        )

        await self.send_progress({
            "type": "report_generated",
            "report_path": report_data["html_path"]
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

    async def handle_command(self, message: str) -> Dict[str, Any]:
        self.load_skills()

        skill_def, handler = skill_registry.find_skill(message)
        if skill_def:
            logger.info(f"Matched skill: {skill_def.name}")

            if skill_registry.is_external_skill(skill_def.name):
                logger.info(f"Executing external skill: {skill_def.name}")
                await self.send_progress({
                    "type": "status",
                    "status": f"正在执行技能: {skill_def.name}...",
                    "step": "external_skill"
                })

                result = await skill_registry.execute_external_skill(
                    skill_def.name,
                    action="test",
                    params={"suite": "smoke", "headless": True}
                )

                await self.send_progress({
                    "type": "external_skill_completed",
                    "skill": skill_def.name,
                    "result": result
                })

                return {
                    "type": "external_skill_result",
                    "skill": skill_def.name,
                    "result": result
                }

            if handler:
                return await handler(message)

        intent = self.parse_intent(message)
        self.state.intent_history.append({
            "message": message,
            "intent": intent,
            "timestamp": datetime.utcnow().isoformat(),
            "matched_skill": skill_def.name if skill_def else None
        })

        logger.info(f"Handling command: {message} -> {intent}")

        if intent["action"] == "execute_all":
            results = await self.execute_cases()
            return {"type": "execution_result", "results": results}

        elif intent["action"] == "execute":
            results = await self.execute_cases()
            return {"type": "execution_result", "results": results}

        elif intent["action"] == "execute_failed":
            failed_case_ids = [
                r.get("case_id") for r in self.state.results
                if r.get("status") == "failed"
            ]
            results = await self.execute_cases(case_ids=failed_case_ids)
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
            return {
                "type": "cases_list",
                "cases": self.state.cases,
                "total": len(self.state.cases)
            }

        elif intent["action"] == "report":
            report = await self.generate_report(f"Task_{self.state.current_task_id}")
            return {"type": "report", "report": report}

        elif intent["action"] == "generate_cases":
            cases = await self.generate_cases()
            return {"type": "cases_generated", "cases": cases, "count": len(cases)}

        elif intent["action"] == "parse_page":
            return {"type": "status", "message": "请提供要解析的页面URL"}

        elif intent["action"] == "parse_document":
            return {"type": "status", "message": "请提供要解析的文档路径"}

        else:
            return {
                "type": "unknown_command",
                "message": f"无法理解指令: {message}",
                "hint": "支持的指令：执行全部用例、暂停、继续、停止、重试、查看报告、生成用例、解析页面",
                "available_skills": [s.name for s in skill_registry.list_skills()]
            }

    def get_state(self) -> Dict[str, Any]:
        self.load_skills()
        return {
            "task_id": self.state.current_task_id,
            "status": self.state.current_task_status,
            "case_count": len(self.state.cases),
            "result_count": len(self.state.results),
            "element_count": len(self.state.page_elements),
            "executor_status": test_executor.get_status(),
            "loaded_skills": [s.name for s in skill_registry.list_skills()]
        }

    def get_skills(self) -> List[Dict[str, Any]]:
        self.load_skills()
        return [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "category": s.category,
                "triggers": s.triggers,
                "examples": s.examples,
                "file_path": s.file_path
            }
            for s in skill_registry.list_skills()
        ]


uitest_agent = UITestAgent()
