"""
用例生成器 - 核心执行逻辑
"""
import asyncio
from typing import Dict, List, Any, Optional
from loguru import logger


async def execute(
    page_elements: List[Dict[str, Any]],
    url: str = "",
    document_data: Optional[Dict[str, Any]] = None,
    llm_model: str = "deepseek-chat"
) -> Dict[str, Any]:
    """
    生成测试用例
    
    Args:
        page_elements: 页面元素列表
        url: 目标网页URL
        document_data: 需求文档数据
        llm_model: 大模型名称
    
    Returns:
        包含测试用例的字典
    """
    logger.info(f"开始生成测试用例，元素数量: {len(page_elements)}")
    
    # 延迟导入以避免启动时的依赖问题
    from skills.case_generator import case_generator
    
    try:
        cases = await case_generator.generate_cases(
            url=url,
            page_elements=page_elements,
            document_data=document_data
        )
        
        for idx, case in enumerate(cases):
            case["id"] = idx + 1
        
        result = {
            "status": "success",
            "case_count": len(cases),
            "cases": cases,
            "message": f"成功生成 {len(cases)} 个测试用例"
        }
        
        logger.info(f"用例生成完成: {len(cases)} 个用例")
        return result
        
    except Exception as e:
        logger.error(f"用例生成失败: {str(e)}")
        return {
            "status": "error",
            "case_count": 0,
            "cases": [],
            "message": f"用例生成失败: {str(e)}"
        }


def get_metadata() -> Dict[str, Any]:
    """获取技能元数据"""
    import yaml
    from pathlib import Path
    
    skill_dir = Path(__file__).parent.parent
    metadata_path = skill_dir / "metadata.yaml"
    
    if metadata_path.exists():
        with open(metadata_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    return {}


if __name__ == "__main__":
    # 命令行测试
    test_elements = [
        {"type": "button", "tag": "button", "selector": "button.submit", "text": "提交"},
        {"type": "input", "tag": "input", "selector": "input.username", "text": ""}
    ]
    
    result = asyncio.run(execute(test_elements, "https://example.com"))
    print(f"生成结果: {result['case_count']} 个用例")
