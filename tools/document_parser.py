"""
文档解析工具 - 支持 PDF / DOCX / TXT / MD / CSV / XLSX / HTML / PPTX / JSON
"""
import re
import csv
import json
from io import StringIO
from pathlib import Path
from typing import Dict, List, Any, Optional
from loguru import logger

# ── 可选依赖，缺失时优雅降级 ──────────────────────────────────────────
try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

try:
    from html.parser import HTMLParser as _HTMLParser
    _HAS_HTML_PARSER = True
except ImportError:
    _HAS_HTML_PARSER = False


# ── 轻量 HTML → text 提取器 ──────────────────────────────────────────
class _TextExtractor(_HTMLParser if _HAS_HTML_PARSER else object):
    def __init__(self):
        if _HAS_HTML_PARSER:
            super().__init__()
        self._parts: List[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        self._skip = tag in ("script", "style")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip and data.strip():
            self._parts.append(data.strip())

    def get_text(self) -> str:
        return "\n".join(self._parts)


def _detect_encoding(raw: bytes) -> str:
    """简单编码探测：utf-8 → gbk → latin-1"""
    for enc in ("utf-8", "gbk", "utf-16", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            pass
    return "latin-1"


class DocumentParser:
    SUPPORTED = {
        ".pdf", ".docx", ".doc",
        ".txt", ".md",
        ".csv",
        ".xlsx", ".xls",
        ".html", ".htm",
        ".pptx",
        ".json",
    }

    def is_supported(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in self.SUPPORTED

    async def parse(self, file_path: str) -> Dict[str, Any]:
        ext = Path(file_path).suffix.lower()
        parsers = {
            ".pdf":  self._parse_pdf,
            ".docx": self._parse_docx,
            ".doc":  self._parse_docx,
            ".txt":  self._parse_txt,
            ".md":   self._parse_md,
            ".csv":  self._parse_csv,
            ".xlsx": self._parse_xlsx,
            ".xls":  self._parse_xlsx,
            ".html": self._parse_html,
            ".htm":  self._parse_html,
            ".pptx": self._parse_pptx,
            ".json": self._parse_json,
        }
        fn = parsers.get(ext)
        if fn is None:
            raise ValueError(f"不支持的文档格式: {ext}，支持格式: {', '.join(sorted(self.SUPPORTED))}")
        return await fn(file_path)

    # ── PDF ──────────────────────────────────────────────────────────
    async def _parse_pdf(self, file_path: str) -> Dict[str, Any]:
        if PdfReader is None:
            raise ImportError("请安装 PyPDF2：pip install pypdf2")
        reader = PdfReader(file_path)
        pages_text = []
        for i, page in enumerate(reader.pages):
            t = page.extract_text() or ""
            pages_text.append({"page": i + 1, "text": t})
        content = "\n".join(p["text"] for p in pages_text)
        logger.info(f"PDF 解析完成: {len(pages_text)} 页")
        return {
            "content": content,
            "page_count": len(pages_text),
            "paragraph_count": len([l for l in content.splitlines() if l.strip()]),
            "pages": pages_text,
            "structured": self._structure_content(content),
            "metadata": {"format": "pdf", "pages": len(pages_text)},
        }

    # ── DOCX ─────────────────────────────────────────────────────────
    async def _parse_docx(self, file_path: str) -> Dict[str, Any]:
        if DocxDocument is None:
            raise ImportError("请安装 python-docx：pip install python-docx")
        doc = DocxDocument(file_path)
        paras = [p.text for p in doc.paragraphs if p.text.strip()]
        tables = []
        for tbl in doc.tables:
            tables.append([[cell.text for cell in row.cells] for row in tbl.rows])
        content = "\n".join(paras)
        logger.info(f"DOCX 解析完成: {len(paras)} 段落, {len(tables)} 表格")
        return {
            "content": content,
            "page_count": 0,
            "paragraph_count": len(paras),
            "table_count": len(tables),
            "tables": tables,
            "structured": self._structure_content(content),
            "metadata": {"format": "docx", "paragraphs": len(paras), "tables": len(tables)},
        }

    # ── TXT ──────────────────────────────────────────────────────────
    async def _parse_txt(self, file_path: str) -> Dict[str, Any]:
        raw = Path(file_path).read_bytes()
        enc = _detect_encoding(raw)
        content = raw.decode(enc, errors="replace")
        lines = [l for l in content.splitlines() if l.strip()]
        logger.info(f"TXT 解析完成: {len(lines)} 行, 编码 {enc}")
        return {
            "content": content,
            "page_count": 0,
            "paragraph_count": len(lines),
            "structured": self._structure_content(content),
            "metadata": {"format": "txt", "encoding": enc, "lines": len(lines)},
        }

    # ── Markdown ─────────────────────────────────────────────────────
    async def _parse_md(self, file_path: str) -> Dict[str, Any]:
        raw = Path(file_path).read_bytes()
        enc = _detect_encoding(raw)
        content = raw.decode(enc, errors="replace")
        # 去掉 markdown 语法符号，方便后续提取
        plain = re.sub(r"#{1,6}\s", "", content)
        plain = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", plain)
        plain = re.sub(r"`{1,3}[^`]*`{1,3}", "", plain)
        plain = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", plain)
        lines = [l for l in plain.splitlines() if l.strip()]
        headings = [l.strip() for l in content.splitlines() if re.match(r"^#{1,6}\s", l)]
        logger.info(f"Markdown 解析完成: {len(headings)} 个标题")
        return {
            "content": content,
            "page_count": 0,
            "paragraph_count": len(lines),
            "headings": headings,
            "structured": self._structure_content(plain),
            "metadata": {"format": "md", "encoding": enc, "headings": len(headings)},
        }

    # ── CSV ──────────────────────────────────────────────────────────
    async def _parse_csv(self, file_path: str) -> Dict[str, Any]:
        raw = Path(file_path).read_bytes()
        enc = _detect_encoding(raw)
        text = raw.decode(enc, errors="replace")
        reader = csv.reader(StringIO(text))
        rows = list(reader)
        headers = rows[0] if rows else []
        # 将表格转换为易读文本
        lines = [", ".join(r) for r in rows]
        content = "\n".join(lines)
        logger.info(f"CSV 解析完成: {len(rows)} 行, {len(headers)} 列")
        return {
            "content": content,
            "page_count": 0,
            "paragraph_count": len(rows),
            "headers": headers,
            "row_count": len(rows),
            "col_count": len(headers),
            "structured": self._structure_content(content),
            "metadata": {"format": "csv", "rows": len(rows), "columns": len(headers)},
        }

    # ── Excel (xlsx/xls) ─────────────────────────────────────────────
    async def _parse_xlsx(self, file_path: str) -> Dict[str, Any]:
        if openpyxl is None:
            raise ImportError("请安装 openpyxl：pip install openpyxl")
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        all_lines = []
        sheet_info = []
        for sheet in wb.worksheets:
            rows_text = []
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                if any(c.strip() for c in cells):
                    rows_text.append(", ".join(cells))
            all_lines.append(f"[Sheet: {sheet.title}]")
            all_lines.extend(rows_text)
            sheet_info.append({"name": sheet.title, "rows": len(rows_text)})
        wb.close()
        content = "\n".join(all_lines)
        total_rows = sum(s["rows"] for s in sheet_info)
        logger.info(f"Excel 解析完成: {len(sheet_info)} 个 Sheet, {total_rows} 行")
        return {
            "content": content,
            "page_count": len(sheet_info),
            "paragraph_count": total_rows,
            "sheets": sheet_info,
            "structured": self._structure_content(content),
            "metadata": {"format": "xlsx", "sheets": len(sheet_info), "total_rows": total_rows},
        }

    # ── HTML ─────────────────────────────────────────────────────────
    async def _parse_html(self, file_path: str) -> Dict[str, Any]:
        raw = Path(file_path).read_bytes()
        enc = _detect_encoding(raw)
        html_text = raw.decode(enc, errors="replace")

        # 先提取可见文字
        if _HAS_HTML_PARSER:
            extractor = _TextExtractor()
            extractor.feed(html_text)
            content = extractor.get_text()
        else:
            content = re.sub(r"<[^>]+>", " ", html_text)
        content = re.sub(r"\s{3,}", "\n\n", content).strip()

        # 如果可见文字太少（SPA/数据导出类 HTML），尝试从 script 标签里提取 JSON 数据
        if len(content) < 200:
            content = self._extract_script_data(html_text) or content

        lines = [l for l in content.splitlines() if l.strip()]
        logger.info(f"HTML 解析完成: {len(lines)} 行")
        return {
            "content": content,
            "page_count": 0,
            "paragraph_count": len(lines),
            "structured": self._structure_content(content),
            "metadata": {"format": "html", "encoding": enc},
        }

    def _extract_script_data(self, html_text: str) -> str:
        """从 script 标签中提取 JS 变量赋值的 JSON 数据，转为可读文本。"""
        # 用字符串搜索代替正则，避免大文件回溯爆炸
        pos = 0
        while True:
            start = html_text.find("<script", pos)
            if start == -1:
                break
            tag_end = html_text.find(">", start)
            if tag_end == -1:
                break
            content_start = tag_end + 1
            end = html_text.find("</script>", content_start)
            if end == -1:
                end = len(html_text)
            script = html_text[content_start:end].strip()
            pos = end + 9

            if len(script) < 100:
                continue
            # 匹配 const/let/var xxx = [...] 或 = {...}
            m = re.match(r"(?:const|let|var)\s+\w+\s*=\s*(\[|{)", script)
            if not m:
                continue
            json_start_idx = m.start(1)
            json_str = script[json_start_idx:]
            try:
                data, _ = json.JSONDecoder().raw_decode(json_str)
                result = self._flatten_json_to_text(data)
                if len(result) > 100:
                    logger.info(f"从 script 标签提取文本: {len(result)} 字符")
                    return result
            except (json.JSONDecodeError, ValueError):
                pass
        return ""

    def _flatten_json_to_text(self, data, depth: int = 0, _acc: list = None) -> str:
        """递归把 JSON 数据转成纯文本，方便 AI 理解。超过 30000 字符时提前停止。"""
        if _acc is None:
            _acc = []
        indent = "  " * depth
        if isinstance(data, list):
            for item in data:
                if sum(len(x) for x in _acc) >= 30000:
                    break
                self._flatten_json_to_text(item, depth, _acc)
        elif isinstance(data, dict):
            for k, v in data.items():
                if sum(len(x) for x in _acc) >= 30000:
                    break
                if isinstance(v, (dict, list)):
                    _acc.append(f"{indent}{k}:\n")
                    self._flatten_json_to_text(v, depth + 1, _acc)
                elif v and str(v).strip():
                    _acc.append(f"{indent}{k}: {v}\n")
        else:
            if data and str(data).strip():
                _acc.append(f"{indent}{data}\n")
        return "".join(_acc)

    # ── PowerPoint ───────────────────────────────────────────────────
    async def _parse_pptx(self, file_path: str) -> Dict[str, Any]:
        if Presentation is None:
            raise ImportError("请安装 python-pptx：pip install python-pptx")
        prs = Presentation(file_path)
        slides_text = []
        for i, slide in enumerate(prs.slides):
            parts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    parts.append(shape.text.strip())
            slides_text.append({"slide": i + 1, "text": "\n".join(parts)})
        content = "\n\n".join(f"[幻灯片 {s['slide']}]\n{s['text']}" for s in slides_text)
        logger.info(f"PPTX 解析完成: {len(slides_text)} 页")
        return {
            "content": content,
            "page_count": len(slides_text),
            "paragraph_count": len([l for l in content.splitlines() if l.strip()]),
            "slides": slides_text,
            "structured": self._structure_content(content),
            "metadata": {"format": "pptx", "slides": len(slides_text)},
        }

    # ── JSON ─────────────────────────────────────────────────────────
    async def _parse_json(self, file_path: str) -> Dict[str, Any]:
        raw = Path(file_path).read_bytes()
        enc = _detect_encoding(raw)
        text = raw.decode(enc, errors="replace")
        try:
            data = json.loads(text)
            content = json.dumps(data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            content = text
            data = {}
        lines = [l for l in content.splitlines() if l.strip()]
        logger.info(f"JSON 解析完成: {len(lines)} 行")
        return {
            "content": content,
            "page_count": 0,
            "paragraph_count": len(lines),
            "structured": self._structure_content(content),
            "metadata": {"format": "json"},
        }

    # ── 通用结构化提取 ────────────────────────────────────────────────
    def _structure_content(self, text: str) -> Dict[str, Any]:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        sections, current_title, items = [], None, []
        for line in lines:
            if self._is_heading(line):
                if current_title:
                    sections.append({"title": current_title, "items": items})
                current_title, items = line, []
            else:
                items.append(line)
        if current_title:
            sections.append({"title": current_title, "items": items})
        return {
            "sections": sections,
            "functional_points": self._extract_functional_points(text),
            "validation_rules": self._extract_validation_rules(text),
            "business_flows": self._extract_business_flows(text),
        }

    def _is_heading(self, line: str) -> bool:
        patterns = [
            r"^\d+[\.、]", r"^[一二三四五六七八九十]+[\.、]",
            r"^[A-Z][\.\)]", r"^\[.+\]$", r"^#{1,6}\s",
        ]
        return any(re.match(p, line) for p in patterns) or (len(line) < 50 and line.isupper())

    def _extract_functional_points(self, text: str) -> List[str]:
        pts = []
        for p in [r"功能[：:]\s*(.+?)(?=\n|$)", r"需求[：:]\s*(.+?)(?=\n|$)"]:
            pts.extend(re.findall(p, text))
        return list(set(pts))

    def _extract_validation_rules(self, text: str) -> List[str]:
        rules = []
        for p in [r"校验[规则]?[：:]\s*(.+?)(?=\n|$)", r"规则[：:]\s*(.+?)(?=\n|$)"]:
            rules.extend(re.findall(p, text))
        return list(set(rules))

    def _extract_business_flows(self, text: str) -> List[str]:
        flows = []
        for p in [r"流程[：:]\s*(.+?)(?=\n|$)", r"步骤[：:]\s*(.+?)(?=\n|$)"]:
            flows.extend(re.findall(p, text))
        return list(set(flows))


document_parser = DocumentParser()
