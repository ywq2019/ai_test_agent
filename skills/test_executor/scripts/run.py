"""
测试执行器 - 核心执行逻辑
"""
import asyncio
from typing import Dict, List, Any, Optional, Callable
from loguru import logger


async def execute(
    cases: List[Dict[str, Any]],
    url: str,
    browser_type: str = "chromium",
    headless: bool = True,
    screenshots_dir: str = "./screenshots",
    progress_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    执行测试用例
    
    Args:
        cases: 测试用例列表
        url: 目标网页URL
        browser_type: 浏览器类型
        headless: 是否使用无头模式
        screenshots_dir: 截图保存目录
        progress_callback: 进度回调函数
    
    Returns:
        包含测试结果的字典
    """
    logger.info(f"开始执行测试用例，数量: {len(cases)}")
    
    # 延迟导入以避免启动时的依赖问题
    from skills.test_executor import test_executor
    
    try:
        results = await test_executor.execute_batch(
            cases=cases,
            url=url,
            browser_type=browser_type,
            screenshots_dir=screenshots_dir,
            progress_callback=progress_callback
        )
        
        passed = sum(1 for r in results if r.get("status") == "passed")
        failed = sum(1 for r in results if r.get("status") == "failed")
        
        result = {
            "status": "success",
            "results": results,
            "summary": {
                "total": len(results),
                "passed": passed,
                "failed": failed
            },
            "message": f"测试执行完成: {passed}/{len(results)} 通过"
        }
        
        logger.info(f"测试执行完成: {passed} 通过, {failed} 失败")
        return result
        
    except Exception as e:
        logger.error(f"测试执行失败: {str(e)}")
        return {
            "status": "error",
            "results": [],
            "summary": {
                "total": 0,
                "passed": 0,
                "failed": 0
            },
            "message": f"测试执行失败: {str(e)}"
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
    test_cases = [
        {
            "id": 1,
            "name": "测试用例1",
            "steps": "点击按钮",
            "expected_results": "页面跳转"
        }
    ]
    
    result = asyncio.run(execute(test_cases, "https://example.com"))
    print(f"执行结果: {result['summary']['passed']}/{result['summary']['total']} 通过")
