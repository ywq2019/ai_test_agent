"""
页面解析器 - 核心执行逻辑
"""
import asyncio
from typing import Dict, List, Any, Optional
from loguru import logger


async def execute(
    url: str,
    browser_type: str = "chromium",
    headless: bool = True,
    timeout: int = 30000
) -> Dict[str, Any]:
    """
    解析页面元素
    
    Args:
        url: 目标网页URL
        browser_type: 浏览器类型 (chromium/firefox/webkit)
        headless: 是否使用无头模式
        timeout: 超时时间(毫秒)
    
    Returns:
        包含页面元素信息的字典
    """
    logger.info(f"开始解析页面: {url}")
    
    # 延迟导入以避免启动时的依赖问题
    from tools.browser import browser_pool

    bt = None
    try:
        bt = await browser_pool.acquire(browser_type)
        await bt.navigate(url)
        elements = await bt.capture_elements()

        result = {
            "status": "success",
            "url": url,
            "element_count": len(elements),
            "elements": elements,
            "message": f"成功抓取 {len(elements)} 个页面元素"
        }

        logger.info(f"页面解析完成: {len(elements)} 个元素")
        return result

    except Exception as e:
        logger.error(f"页面解析失败: {str(e)}")
        return {
            "status": "error",
            "url": url,
            "element_count": 0,
            "elements": [],
            "message": f"页面解析失败: {str(e)}"
        }
    finally:
        if bt:
            await bt.close()
            browser_pool.release(bt)


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
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python run.py <url> [browser_type]")
        sys.exit(1)
    
    url = sys.argv[1]
    browser_type = sys.argv[2] if len(sys.argv) > 2 else "chromium"
    
    result = asyncio.run(execute(url, browser_type))
    print(f"解析结果: {result['element_count']} 个元素")
