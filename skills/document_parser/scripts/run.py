"""
文档解析器 - 核心执行逻辑
"""
import asyncio
from typing import Dict, Any, Optional
from loguru import logger


async def execute(
    document_path: str,
    file_type: str = "auto"
) -> Dict[str, Any]:
    """
    解析文档
    
    Args:
        document_path: 文档文件路径
        file_type: 文件类型 (auto/pdf/docx/txt)
    
    Returns:
        包含文档内容的字典
    """
    logger.info(f"开始解析文档: {document_path}")
    
    # 延迟导入以避免启动时的依赖问题
    from tools.document_parser import document_parser
    
    try:
        document_data = await document_parser.parse(document_path)
        
        result = {
            "status": "success",
            "page_count": document_data.get("page_count", 0),
            "paragraph_count": document_data.get("paragraph_count", 0),
            "content": document_data.get("content", ""),
            "metadata": document_data.get("metadata", {}),
            "message": f"文档解析完成: {document_data.get('page_count', 0)} 页"
        }
        
        logger.info(f"文档解析完成: {document_data.get('page_count', 0)} 页")
        return result
        
    except Exception as e:
        logger.error(f"文档解析失败: {str(e)}")
        return {
            "status": "error",
            "page_count": 0,
            "paragraph_count": 0,
            "content": "",
            "metadata": {},
            "message": f"文档解析失败: {str(e)}"
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
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python run.py <document_path>")
        sys.exit(1)
    
    doc_path = sys.argv[1]
    result = asyncio.run(execute(doc_path))
    print(f"解析结果: {result['page_count']} 页, {result['paragraph_count']} 段落")