"""
技能加载器 - 自动扫描并加载skills目录下的技能文档
"""
import os
import re
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from loguru import logger
from dataclasses import dataclass, field


@dataclass
class SkillDefinition:
    name: str
    description: str
    version: str
    category: str
    triggers: List[str] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    examples: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    file_path: str = ""
    skill_dir: str = ""


class SkillLoader:
    def __init__(self, skills_dir: str = None):
        if skills_dir is None:
            self.skills_dir = Path(__file__).parent
        else:
            self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, SkillDefinition] = {}
        self._loaded = False

    def scan_skills(self) -> List[tuple]:
        skill_files = []
        for item in self.skills_dir.iterdir():
            if item.is_dir() and not item.name.startswith('_'):
                skill_md = item / "SKILL.md"
                if skill_md.exists():
                    skill_files.append((skill_md, item))
                else:
                    for md_file in item.glob("*.md"):
                        if md_file.name.upper().startswith("SKILL"):
                            skill_files.append((md_file, item))
                            break
            elif item.is_file() and item.suffix == ".md" and "SKILL" in item.name.upper():
                skill_files.append((item, item.parent))
        return skill_files

    def parse_skill_markdown(self, md_path: Path, skill_dir: Path) -> Optional[SkillDefinition]:
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            name = self._extract_frontmatter_field(content, "name")
            description = self._extract_frontmatter_field(content, "description")
            version = self._extract_frontmatter_field(content, "version") or "1.0.0"
            category = self._extract_frontmatter_field(content, "category")

            if not name:
                name = self._extract_name_from_markdown(content, md_path.parent.name)

            if not description:
                description = self._extract_description_from_markdown(content)

            if not category:
                category = self._infer_category(content, name)

            triggers = self._extract_triggers(content)
            examples = self._extract_examples(content)
            actions = self._extract_actions(content)
            parameters = self._extract_parameters(content)

            skill = SkillDefinition(
                name=name,
                description=description or "",
                version=version,
                category=category or "general",
                triggers=triggers,
                actions=actions,
                parameters=parameters,
                examples=examples,
                metadata=self._extract_metadata(content),
                file_path=str(md_path),
                skill_dir=str(skill_dir)
            )

            logger.info(f"Loaded skill: {skill.name} (v{skill.version}) from {md_path}")
            return skill

        except Exception as e:
            logger.error(f"Failed to parse skill {md_path}: {e}")
            return None

    def _extract_name_from_markdown(self, content: str, default_name: str) -> str:
        patterns = [
            r'^#\s+(.+?)(?:\s|$)',
            r'^#\s+(.+?)\s*-',
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.MULTILINE)
            if match:
                name = match.group(1).strip()
                name = name.split('-')[0].strip()
                return name
        return default_name.replace('_', ' ').replace('-', ' ').title()

    def _extract_description_from_markdown(self, content: str) -> str:
        patterns = [
            r'(?:概述|介绍|说明|简介|About|Description)[:：]\s*(.+?)(?=\n##|\n#|\Z)',
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.MULTILINE)
            if match:
                desc = match.group(1).strip()
                desc = re.sub(r'\n+', ' ', desc)
                return desc[:500]
        return ""

    def _infer_category(self, content: str, name: str) -> str:
        content_lower = content.lower()
        name_lower = name.lower()

        if any(kw in content_lower or kw in name_lower for kw in ['web', '网站', '页面', 'page', 'ui']):
            return "web-testing"
        elif any(kw in content_lower or kw in name_lower for kw in ['api', '接口', 'rest']):
            return "api-testing"
        elif any(kw in content_lower or kw in name_lower for kw in ['case', '用例', 'test case']):
            return "test-generation"
        elif any(kw in content_lower or kw in name_lower for kw in ['report', '报告']):
            return "reporting"
        elif any(kw in content_lower or kw in name_lower for kw in ['document', '文档', 'pdf', 'docx']):
            return "document-parsing"
        elif any(kw in content_lower or kw in name_lower for kw in ['execute', '执行', 'runner']):
            return "execution"
        elif any(kw in content_lower or kw in name_lower for kw in ['monitor', '监控', 'cron']):
            return "monitoring"
        return "general"

    def _extract_triggers(self, content: str) -> List[str]:
        triggers = []
        patterns = [
            r'(?:触发词|触发|Triggers|Keywords)[:：]\s*(.+?)(?=\n##|\n#|\Z)',
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.MULTILINE)
            if match:
                trigger_section = match.group(1)
                items = re.findall(r'[-\d]*\s*[`"]?(.+?)[`"]?\s*(?:\n|$)', trigger_section)
                triggers.extend([t.strip() for t in items if t.strip()])
        return triggers[:10]

    def _extract_examples(self, content: str) -> List[str]:
        examples = []
        patterns = [
            r'(?:示例|例子|用法|Examples|Usage)[:：]\s*(.+?)(?=\n##|\n#|\Z)',
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.MULTILINE)
            if match:
                example_section = match.group(1)
                code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', example_section, re.DOTALL)
                for block in code_blocks:
                    cmds = re.findall(r'\$?\s*(?:npm\s+\w+|node\s+\S+|python\s+\S+|pytest\s+\S+)', block)
                    examples.extend(cmds[:3])
                cmds = re.findall(r'(?:npm\s+\w+|node\s+\S+|python\s+\S+)', example_section)
                examples.extend(cmds[:5])
        return list(set(examples))[:10]

    def _extract_actions(self, content: str) -> List[Dict[str, Any]]:
        actions = []
        if 'test' in content.lower() or '测试' in content:
            actions.append({"type": "test", "description": "执行测试"})
        if 'monitor' in content.lower() or '监控' in content:
            actions.append({"type": "monitor", "description": "系统监控"})
        if 'report' in content.lower() or '报告' in content:
            actions.append({"type": "report", "description": "生成报告"})
        if 'api' in content.lower():
            actions.append({"type": "api-test", "description": "API测试"})
        if not actions:
            actions.append({"type": "execute", "description": "执行技能"})
        return actions

    def _extract_parameters(self, content: str) -> Dict[str, Any]:
        params = {}
        if 'config' in content.lower() or '配置' in content:
            params["config_file"] = {
                "type": "string",
                "description": "配置文件路径",
                "default": "config/test_config.json"
            }
        if 'timeout' in content.lower():
            params["timeout"] = {
                "type": "integer",
                "description": "超时时间(毫秒)",
                "default": 30000
            }
        if 'headless' in content.lower():
            params["headless"] = {
                "type": "boolean",
                "description": "无头模式",
                "default": True
            }
        return params

    def _extract_metadata(self, content: str) -> Dict[str, Any]:
        metadata = {}

        if match := re.search(r'(?:site|网站|URL)[:：]\s*(\S+)', content):
            metadata["site"] = match.group(1)

        if match := re.search(r'(?:framework|框架)[:：]\s*(\w+)', content):
            metadata["framework"] = match.group(1)

        if match := re.search(r'(?:dependencies|依赖)[:：]\s*(\w+)', content):
            metadata["dependencies"] = match.group(1)

        return metadata

    def _extract_frontmatter_field(self, content: str, field_name: str) -> Any:
        patterns = [
            rf'^{field_name}:\s*\|?\s*$',
            rf'^{field_name}:\s*(.+?)(?=\n\w+:|$)',
            rf'{field_name}\s*[:：]\s*(.+?)(?=\n|$)'
        ]

        lines = content.split('\n')
        for i, line in enumerate(lines):
            for pattern in patterns:
                match = re.match(pattern, line.strip())
                if match:
                    value = match.group(1).strip()

                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        if next_line.startswith(' ' * 4) or next_line.startswith('\t'):
                            block_content = [value]
                            for j in range(i + 1, len(lines)):
                                next_line = lines[j]
                                if next_line and (next_line[0] == ' ' or next_line[0] == '\t' or next_line.startswith('-') or next_line.startswith('  -')):
                                    block_content.append(next_line.strip())
                                else:
                                    break
                            value = '\n'.join(block_content)
                            if value.startswith('-'):
                                value = [v.strip().lstrip('- ') for v in value.split('\n') if v.strip()]

                    if value.startswith('[') and value.endswith(']'):
                        try:
                            return yaml.safe_load(value)
                        except:
                            pass

                    if '`' in value:
                        value = value.replace('`', '')

                    return value

        return None

    def load_all_skills(self) -> Dict[str, SkillDefinition]:
        if self._loaded:
            return self.skills

        logger.info(f"Scanning skills directory: {self.skills_dir}")
        skill_files = self.scan_skills()

        for skill_file, skill_dir in skill_files:
            skill = self.parse_skill_markdown(skill_file, skill_dir)
            if skill:
                key = skill.name.lower().replace(' ', '_')
                self.skills[skill.name] = skill

        self._loaded = True
        logger.info(f"Loaded {len(self.skills)} skills")
        return self.skills

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        if not self._loaded:
            self.load_all_skills()
        return self.skills.get(name)

    def find_skill_by_trigger(self, trigger: str) -> Optional[SkillDefinition]:
        if not self._loaded:
            self.load_all_skills()

        trigger_lower = trigger.lower()
        for skill in self.skills.values():
            for t in skill.triggers:
                if t.lower() in trigger_lower or trigger_lower in t.lower():
                    return skill
        return None

    def match_skill(self, message: str) -> tuple[Optional[SkillDefinition], Optional[str]]:
        if not self._loaded:
            self.load_all_skills()

        message_lower = message.lower()

        for skill in self.skills.values():
            for trigger in skill.triggers:
                if trigger.lower() in message_lower:
                    return skill, trigger

        keywords_to_skills = {
            ('web', '网站', '页面测试', 'ui测试'): 'web-testing',
            ('api', '接口测试'): 'api-testing',
            ('报告', 'report'): 'reporting',
            ('监控', 'monitor'): 'monitoring',
            ('support', 'genew', 'support.genew'): 'support_web_skill',
        }

        for keywords, skill_key in keywords_to_skills.items():
            if any(kw in message_lower for kw in keywords):
                for skill in self.skills.values():
                    if skill_key in skill.name.lower() or skill_key in skill.category.lower():
                        return skill, keywords[0]

        return None, None

    def get_all_skills(self) -> List[SkillDefinition]:
        if not self._loaded:
            self.load_all_skills()
        return list(self.skills.values())

    def reload(self):
        self._loaded = False
        self.skills = {}
        return self.load_all_skills()


skill_loader = SkillLoader()
