"""
报告生成器 - 核心执行逻辑
"""
import asyncio
from typing import Dict, List, Any, Optional
from loguru import logger


async def execute(
    task_id: int,
    task_name: str,
    results: List[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    生成测试报告
    
    Args:
        task_id: 任务ID
        task_name: 任务名称
        results: 测试结果列表
        metadata: 额外元数据
    
    Returns:
        包含报告路径的字典
    """
    logger.info(f"开始生成测试报告，任务ID: {task_id}")
    
    # 延迟导入以避免启动时的依赖问题
    from skills.report_generator import report_generator
    
    try:
        report_data = await report_generator.generate_report(
            task_id=task_id,
            task_name=task_name,
            results=results,
            metadata=metadata or {}
        )
        
        passed = sum(1 for r in results if r.get("status") == "passed")
        total = len(results)
        pass_rate = (passed / total) * 100 if total > 0 else 0
        
        result = {
            "status": "success",
            "html_path": report_data.get("html_path", ""),
            "json_path": report_data.get("json_path", ""),
            "summary": report_data.get("summary", {}),
            "pass_rate": pass_rate,
            "message": f"报告生成完成: {report_data.get('html_path', '')}"
        }
        
        logger.info(f"报告生成完成: {report_data.get('html_path')}")
        return result
        
    except Exception as e:
        logger.error(f"报告生成失败: {str(e)}")
        return {
            "status": "error",
            "html_path": "",
            "json_path": "",
            "summary": {},
            "pass_rate": 0,
            "message": f"报告生成失败: {str(e)}"
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
    test_results = [
        {
            "case_id": 1,
            "case_name": "测试用例1",
            "status": "passed",
            "duration": 1.5
        }
    ]
    
    result = asyncio.run(execute(1, "测试任务", test_results))
    print(f"报告路径: {result['html_path']}")
