"""
文档解析工具 - 支持PDF和DOCX格式
"""
import re
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None


class DocumentParser:
    def __init__(self):
        self.supported_formats = [".pdf", ".docx", ".doc"]

    def is_supported(self, file_path: str) -> bool:
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_formats

    async def parse(self, file_path: str) -> Dict:
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            return await self._parse_pdf(file_path)
        elif ext in [".docx", ".doc"]:
            return await self._parse_docx(file_path)
        else:
            raise ValueError(f"Unsupported document format: {ext}")

    async def _parse_pdf(self, file_path: str) -> Dict:
        if PdfReader is None:
            raise ImportError("PyPDF2 is not installed")

        reader = PdfReader(file_path)
        text_content = []
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            text_content.append({
                "page": page_num + 1,
                "text": text
            })

        full_text = "\n".join([p["text"] for p in text_content])
        structured = self._structure_content(full_text)

        logger.info(f"Parsed PDF: {len(text_content)} pages")
        return {
            "pages": text_content,
            "full_text": full_text,
            "structured": structured,
            "page_count": len(text_content)
        }

    async def _parse_docx(self, file_path: str) -> Dict:
        if Document is None:
            raise ImportError("python-docx is not installed")

        doc = Document(file_path)
        paragraphs = []
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text)

        tables = []
        for table in doc.tables:
            table_data = []
            for row in table.rows:
                row_data = [cell.text for cell in row.cells]
                table_data.append(row_data)
            tables.append(table_data)

        full_text = "\n".join(paragraphs)
        structured = self._structure_content(full_text)

        logger.info(f"Parsed DOCX: {len(paragraphs)} paragraphs, {len(tables)} tables")
        return {
            "paragraphs": paragraphs,
            "tables": tables,
            "full_text": full_text,
            "structured": structured,
            "paragraph_count": len(paragraphs),
            "table_count": len(tables)
        }

    def _structure_content(self, text: str) -> Dict:
        lines = text.split("\n")
        sections = []
        current_section = None
        items = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if self._is_heading(line):
                if current_section:
                    sections.append({
                        "title": current_section,
                        "items": items
                    })
                current_section = line
                items = []
            else:
                items.append(line)

        if current_section:
            sections.append({
                "title": current_section,
                "items": items
            })

        functional_points = self._extract_functional_points(text)
        validation_rules = self._extract_validation_rules(text)
        business_flows = self._extract_business_flows(text)

        return {
            "sections": sections,
            "functional_points": functional_points,
            "validation_rules": validation_rules,
            "business_flows": business_flows,
            "raw_text": text
        }

    def _is_heading(self, line: str) -> bool:
        heading_patterns = [
            r"^\d+[\.、]",
            r"^[一二三四五六七八九十]+[\.、]",
            r"^[A-Z][\.\)]",
            r"^\[.+\]$",
            r"^#{1,6}\s"
        ]
        for pattern in heading_patterns:
            if re.match(pattern, line):
                return True
        return len(line) < 50 and line.isupper()

    def _extract_functional_points(self, text: str) -> List[str]:
        patterns = [
            r"功能[：:]\s*(.+?)(?=\n|$)",
            r"功能点[：:]\s*(.+?)(?=\n|$)",
            r"需求[：:]\s*(.+?)(?=\n|$)"
        ]
        points = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            points.extend(matches)
        return list(set(points))

    def _extract_validation_rules(self, text: str) -> List[str]:
        patterns = [
            r"校验[规则]?[：:]\s*(.+?)(?=\n|$)",
            r"验证[规则]?[：:]\s*(.+?)(?=\n|$)",
            r"规则[：:]\s*(.+?)(?=\n|$)"
        ]
        rules = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            rules.extend(matches)
        return list(set(rules))

    def _extract_business_flows(self, text: str) -> List[str]:
        patterns = [
            r"流程[：:]\s*(.+?)(?=\n|$)",
            r"步骤[：:]\s*(.+?)(?=\n|$)",
            r"处理[流程]?[：:]\s*(.+?)(?=\n|$)"
        ]
        flows = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            flows.extend(matches)
        return list(set(flows))


document_parser = DocumentParser()
