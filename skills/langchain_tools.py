"""
LangChain 工具注册模块 - 自动发现和注册技能
"""
import asyncio
import yaml
from typing import Dict, List, Any, Optional
from pathlib import Path
from loguru import logger
from langchain.tools import tool


@tool
def parse_page(
    url: str,
    browser_type: str = "chromium",
    headless: bool = True
) -> Dict[str, Any]:
    """
    解析页面元素，抓取网页中的可交互元素信息
    
    Args:
        url: 目标网页URL
        browser_type: 浏览器类型 (chromium/firefox/webkit)
        headless: 是否使用无头模式
    
    Returns:
        包含页面元素信息的字典
    """
    from skills.page_parser.scripts.run import execute
    return asyncio.run(execute(url, browser_type, headless))


@tool
def parse_document(
    document_path: str,
    file_type: str = "auto"
) -> Dict[str, Any]:
    """
    解析PDF、Word等需求文档，提取测试需求信息
    
    Args:
        document_path: 文档文件路径
        file_type: 文件类型 (auto/pdf/docx/txt)
    
    Returns:
        包含文档内容的字典
    """
    from skills.document_parser.scripts.run import execute
    return asyncio.run(execute(document_path, file_type))


@tool
def generate_cases(
    page_elements: List[Dict[str, Any]],
    url: str = "",
    document_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    基于页面元素和需求文档智能生成测试用例
    
    Args:
        page_elements: 页面元素列表
        url: 目标网页URL
        document_data: 需求文档数据（可选）
    
    Returns:
        包含测试用例的字典
    """
    from skills.case_generator.scripts.run import execute
    return asyncio.run(execute(page_elements, url, document_data))


@tool
def execute_tests(
    cases: List[Dict[str, Any]],
    url: str,
    browser_type: str = "chromium",
    headless: bool = True
) -> Dict[str, Any]:
    """
    执行测试用例并返回结果
    
    Args:
        cases: 测试用例列表
        url: 目标网页URL
        browser_type: 浏览器类型 (chromium/firefox/webkit)
        headless: 是否使用无头模式
    
    Returns:
        包含测试结果的字典
    """
    from skills.test_executor.scripts.run import execute
    return asyncio.run(execute(cases, url, browser_type, headless))


@tool
def generate_report(
    task_id: int,
    task_name: str,
    results: List[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    生成测试报告（HTML和JSON格式）
    
    Args:
        task_id: 任务ID
        task_name: 任务名称
        results: 测试结果列表
        metadata: 额外元数据（可选）
    
    Returns:
        包含报告路径的字典
    """
    from skills.report_generator.scripts.run import execute
    return asyncio.run(execute(task_id, task_name, results, metadata))


# 核心工具列表
CORE_TOOLS = [
    parse_page,
    parse_document,
    generate_cases,
    execute_tests,
    generate_report
]


class ToolRegistry:
    def __init__(self):
        self.tools = []
        self.skills_dir = Path(__file__).parent
    
    def discover_skills(self) -> List[Dict[str, Any]]:
        """
        自动发现技能目录
        
        Returns:
            技能元数据列表
        """
        skills = []
        
        for item in self.skills_dir.iterdir():
            if item.is_dir() and not item.name.startswith('_'):
                metadata_path = item / "metadata.yaml"
                script_path = item / "scripts" / "run.py"
                
                if metadata_path.exists() and script_path.exists():
                    try:
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = yaml.safe_load(f)
                        
                        skills.append({
                            "name": metadata.get("name", item.name),
                            "directory": item.name,
                            "metadata": metadata,
                            "script_path": str(script_path)
                        })
                        
                        logger.info(f"发现技能: {metadata.get('name', item.name)}")
                        
                    except Exception as e:
                        logger.error(f"加载技能元数据失败 {item.name}: {e}")
        
        return skills
    
    def register_all(self):
        """注册所有工具"""
        self.tools = CORE_TOOLS
        
        # 自动发现并注册新技能
        discovered_skills = self.discover_skills()
        logger.info(f"自动发现 {len(discovered_skills)} 个技能")
        
        # 这里可以扩展为动态加载新技能
        # 目前只注册核心工具
        logger.info(f"已注册 {len(self.tools)} 个 LangChain 工具")
    
    def get_tools(self):
        """获取所有工具"""
        if not self.tools:
            self.register_all()
        return self.tools
    
    def get_tool_by_name(self, name: str):
        """按名称获取工具"""
        for tool_obj in self.get_tools():
            if tool_obj.name == name:
                return tool_obj
        return None
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有技能信息"""
        skills = self.discover_skills()
        
        # 添加核心工具信息
        for tool_obj in self.tools:
            skills.append({
                "name": tool_obj.name,
                "description": tool_obj.description,
                "type": "core",
                "metadata": {}
            })
        
        return skills


# 全局工具注册表
tool_registry = ToolRegistry()