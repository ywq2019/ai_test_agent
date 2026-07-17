"""
PDF 导出工具 — 用已有的 Playwright 把 HTML 渲染成 PDF。

支持两种输入：
  - html_path : 磁盘上已有的 HTML 文件路径（WebUI 报告）
  - html_str  : 动态生成的 HTML 字符串（接口报告、测试计划报告）

输出：PDF 字节流（bytes），由调用方决定写文件还是直接作为 HTTP 响应返回。
"""
import asyncio
import tempfile
from pathlib import Path
from loguru import logger


async def html_to_pdf(
    html_path: str | None = None,
    html_str: str | None = None,
    timeout_ms: int = 30_000,
) -> bytes:
    """将 HTML 转为 PDF 字节流。

    Args:
        html_path: 磁盘上的 HTML 文件绝对/相对路径（与 html_str 二选一）
        html_str:  HTML 字符串（与 html_path 二选一）
        timeout_ms: Playwright 页面加载超时（毫秒）

    Returns:
        PDF 二进制内容

    Raises:
        ValueError: 参数缺失
        RuntimeError: Playwright 转换失败
    """
    if not html_path and not html_str:
        raise ValueError("html_path 和 html_str 至少提供一个")

    from playwright.async_api import async_playwright

    _tmp_file = None
    try:
        # html_str 模式：写到临时文件，再用 file:// 打开
        if html_str and not html_path:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, mode="w", encoding="utf-8"
            )
            tmp.write(html_str)
            tmp.flush()
            tmp.close()
            _tmp_file = tmp.name
            target_path = Path(_tmp_file).resolve()
        else:
            target_path = Path(html_path).resolve()
            if not target_path.exists():
                raise RuntimeError(f"HTML 文件不存在: {target_path}")

        url = target_path.as_uri()   # file:///absolute/path/to/report.html

        async with async_playwright() as pw:
            # 复用项目已有的 chromium；headless 模式不需要显示器
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "16mm", "bottom": "16mm",
                            "left": "12mm", "right": "12mm"},
                )
            finally:
                await browser.close()

        logger.info(f"PDF 生成成功: {len(pdf_bytes)} bytes，来源={url}")
        return pdf_bytes

    except Exception as e:
        logger.error(f"PDF 生成失败: {e}")
        raise RuntimeError(f"PDF 生成失败: {e}") from e
    finally:
        if _tmp_file:
            try:
                Path(_tmp_file).unlink(missing_ok=True)
            except Exception:
                pass
