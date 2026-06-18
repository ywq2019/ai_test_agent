"""
基于 LangGraph 的 UI 测试 Agent 核心
Agent = 大模型 + 思考决策逻辑 + 外部工具集
"""
import asyncio
from typing import Dict, List, Any, Optional, TypedDict
from datetime import datetime
from loguru import logger

from langchain_openai import ChatOpenAI
from langchain.tools import BaseTool
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from skills.langchain_tools import tool_registry


# 定义代理状态
class AgentState(TypedDict):
    task_id: Optional[int]
    task_name: str
    url: str
    status: str
    page_elements: List[Dict[str, Any]]
    cases: List[Dict[str, Any]]
    results: List[Dict[str, Any]]
    report_path: str
    messages: List[BaseMessage]
    next_step: str


class LangGraphAgent:
    def __init__(self, api_key: str, base_url: str, model_name: str = "deepseek-chat"):
        """
        初始化 LangGraph Agent
        
        Args:
            api_key: 大模型 API Key
            base_url: 大模型 API 地址
            model_name: 模型名称
        """
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=0.5,
            api_key=api_key,
            base_url=base_url
        )
        
        self.tools = tool_registry.get_tools()
        self.tool_node = ToolNode(self.tools)
        
        # 初始化状态
        self.state = AgentState(
            task_id=None,
            task_name="",
            url="",
            status="idle",
            page_elements=[],
            cases=[],
            results=[],
            report_path="",
            messages=[],
            next_step=""
        )
        
        # 构建图
        self.graph = self._build_graph()
        
        logger.info("LangGraph Agent 初始化完成")
    
    def _build_graph(self) -> StateGraph:
        """构建状态图"""
        workflow = StateGraph(AgentState)
        
        # 添加节点
        workflow.add_node("parse_page", self._parse_page_node)
        workflow.add_node("generate_cases", self._generate_cases_node)
        workflow.add_node("execute_tests", self._execute_tests_node)
        workflow.add_node("generate_report", self._generate_report_node)
        workflow.add_node("decide", self._decide_node)
        workflow.add_node("tool_node", self.tool_node)
        
        # 添加边
        workflow.set_entry_point("decide")
        
        workflow.add_edge("parse_page", "decide")
        workflow.add_edge("generate_cases", "decide")
        workflow.add_edge("execute_tests", "decide")
        workflow.add_edge("generate_report", END)
        
        workflow.add_conditional_edges(
            "decide",
            self._route_decision,
            {
                "parse_page": "parse_page",
                "generate_cases": "generate_cases",
                "execute_tests": "execute_tests",
                "generate_report": "generate_report",
                "end": END
            }
        )
        
        # 编译图
        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)
    
    async def _decide_node(self, state: AgentState) -> AgentState:
        """决策节点 - 决定下一步行动"""
        logger.info(f"决策节点: 当前状态 - {state['status']}")
        
        # 简单的状态机逻辑
        if not state["page_elements"] and state["url"]:
            return {**state, "next_step": "parse_page"}
        elif not state["cases"] and state["page_elements"]:
            return {**state, "next_step": "generate_cases"}
        elif not state["results"] and state["cases"]:
            return {**state, "next_step": "execute_tests"}
        elif not state["report_path"] and state["results"]:
            return {**state, "next_step": "generate_report"}
        else:
            return {**state, "next_step": "end"}
    
    def _route_decision(self, state: AgentState) -> str:
        """路由决策"""
        return state["next_step"]
    
    async def _parse_page_node(self, state: AgentState) -> AgentState:
        """解析页面节点"""
        logger.info(f"解析页面: {state['url']}")
        
        from skills.page_parser.scripts.run import execute
        
        result = await execute(
            url=state["url"],
            browser_type="chromium",
            headless=True
        )
        
        if result["status"] == "success":
            return {
                **state,
                "page_elements": result["elements"],
                "status": "parsed",
                "messages": [
                    *state["messages"],
                    AIMessage(content=f"已成功解析页面，获取到 {len(result['elements'])} 个元素")
                ]
            }
        else:
            return {
                **state,
                "status": "error",
                "messages": [
                    *state["messages"],
                    AIMessage(content=f"页面解析失败: {result['message']}")
                ]
            }
    
    async def _generate_cases_node(self, state: AgentState) -> AgentState:
        """生成用例节点"""
        logger.info(f"生成测试用例: {len(state['page_elements'])} 个元素")
        
        from skills.case_generator.scripts.run import execute
        
        result = await execute(
            page_elements=state["page_elements"],
            url=state["url"]
        )
        
        if result["status"] == "success":
            return {
                **state,
                "cases": result["cases"],
                "status": "cases_generated",
                "messages": [
                    *state["messages"],
                    AIMessage(content=f"已成功生成 {len(result['cases'])} 个测试用例")
                ]
            }
        else:
            return {
                **state,
                "status": "error",
                "messages": [
                    *state["messages"],
                    AIMessage(content=f"用例生成失败: {result['message']}")
                ]
            }
    
    async def _execute_tests_node(self, state: AgentState) -> AgentState:
        """执行测试节点"""
        logger.info(f"执行测试用例: {len(state['cases'])} 个")
        
        from skills.test_executor.scripts.run import execute
        
        result = await execute(
            cases=state["cases"],
            url=state["url"],
            browser_type="chromium",
            headless=True
        )
        
        if result["status"] == "success":
            summary = result["summary"]
            return {
                **state,
                "results": result["results"],
                "status": "executed",
                "messages": [
                    *state["messages"],
                    AIMessage(
                        content=f"测试执行完成: {summary['passed']}/{summary['total']} 通过"
                    )
                ]
            }
        else:
            return {
                **state,
                "status": "error",
                "messages": [
                    *state["messages"],
                    AIMessage(content=f"测试执行失败: {result['message']}")
                ]
            }
    
    async def _generate_report_node(self, state: AgentState) -> AgentState:
        """生成报告节点"""
        logger.info(f"生成测试报告: 任务ID {state['task_id']}")
        
        from skills.report_generator.scripts.run import execute
        
        result = await execute(
            task_id=state["task_id"] or 0,
            task_name=state["task_name"],
            results=state["results"]
        )
        
        if result["status"] == "success":
            return {
                **state,
                "report_path": result["html_path"],
                "status": "completed",
                "messages": [
                    *state["messages"],
                    AIMessage(content=f"报告生成完成: {result['html_path']}")
                ]
            }
        else:
            return {
                **state,
                "status": "error",
                "messages": [
                    *state["messages"],
                    AIMessage(content=f"报告生成失败: {result['message']}")
                ]
            }
    
    async def run(self, task_name: str, url: str) -> AgentState:
        """
        运行完整的测试流程
        
        Args:
            task_name: 任务名称
            url: 目标网页URL
        
        Returns:
            最终状态
        """
        logger.info(f"开始执行任务: {task_name}")
        
        # 设置初始状态
        initial_state = AgentState(
            task_id=int(datetime.utcnow().timestamp() * 1000),
            task_name=task_name,
            url=url,
            status="started",
            page_elements=[],
            cases=[],
            results=[],
            report_path="",
            messages=[HumanMessage(content=f"开始测试任务: {task_name}")],
            next_step=""
        )
        
        # 执行图
        result = await self.graph.ainvoke(initial_state)
        
        logger.info(f"任务执行完成: {result['status']}")
        return result
    
    async def chat(self, message: str) -> str:
        """
        对话模式 - 基于用户消息进行响应
        
        Args:
            message: 用户消息
        
        Returns:
            响应内容
        """
        # 添加用户消息到状态
        self.state["messages"].append(HumanMessage(content=message))
        
        # 简单的意图解析
        message_lower = message.lower()
        
        if any(kw in message_lower for kw in ["解析", "抓取", "页面"]):
            # 提取URL
            import re
            url_match = re.search(r'https?://[\w\-\._~:/?#\[\]@!\$&\'\(\)\*\+,;=%]+', message)
            if url_match:
                self.state["url"] = url_match.group(0)
                result = await self.run(self.state["task_name"] or "测试任务", self.state["url"])
                return f"开始解析页面: {self.state['url']}"
            else:
                return "请提供要解析的页面URL"
        
        elif any(kw in message_lower for kw in ["执行", "运行"]):
            if self.state["cases"]:
                await self._execute_tests_node(self.state)
                return "开始执行测试..."
            else:
                return "请先解析页面并生成测试用例"
        
        elif any(kw in message_lower for kw in ["报告", "结果"]):
            if self.state["results"]:
                await self._generate_report_node(self.state)
                return f"报告已生成: {self.state['report_path']}"
            else:
                return "请先执行测试"
        
        else:
            # 使用LLM进行响应
            response = self.llm.invoke([HumanMessage(content=message)])
            return response.content


# 全局代理实例
uitest_langgraph_agent = None


def init_langgraph_agent(api_key: str, base_url: str, model_name: str = "deepseek-chat"):
    """初始化 LangGraph 代理"""
    global uitest_langgraph_agent
    uitest_langgraph_agent = LangGraphAgent(api_key, base_url, model_name)
    return uitest_langgraph_agent
