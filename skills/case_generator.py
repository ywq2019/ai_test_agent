"""
测试用例生成技能
"""
import json
from typing import List, Dict, Any, Optional
from loguru import logger


class CaseGenerator:
    def __init__(self):
        self.priority_levels = ["P0", "P1", "P2"]

    async def generate_cases(
        self,
        url: str,
        page_elements: List[Dict[str, Any]],
        document_data: Optional[Dict[str, Any]] = None,
        requirements: List[str] = None
    ) -> List[Dict[str, Any]]:
        logger.info("Generating test cases...")

        cases = []

        cases.extend(self._generate_normal_cases(page_elements))
        cases.extend(self._generate_validation_cases(page_elements))
        cases.extend(self._generate_boundary_cases(page_elements))

        if document_data and document_data.get("structured"):
            structured = document_data["structured"]
            if structured.get("functional_points"):
                cases.extend(self._generate_from_functional_points(
                    structured["functional_points"],
                    page_elements
                ))

        cases = self._deduplicate_cases(cases)
        cases = self._assign_priorities(cases)

        logger.info(f"Generated {len(cases)} test cases")
        return cases

    def _generate_normal_cases(self, elements: List[Dict]) -> List[Dict]:
        cases = []

        for elem in elements:
            if elem.get("tag") == "input":
                cases.append({
                    "name": f"输入框{elem.get('name') or elem.get('placeholder')}正常输入",
                    "module": self._get_module(elem),
                    "priority": "P1",
                    "preconditions": f"打开目标页面，找到输入框{elem.get('name') or elem.get('placeholder')}",
                    "steps": f"1. 点击输入框\n2. 输入有效数据\n3. 检查输入内容是否正确显示",
                    "expected_results": "输入内容正确显示，无格式错误",
                    "element_selector": elem.get("selector", "")
                })

            elif elem.get("tag") == "button" or (elem.get("tag") == "a" and elem.get("text")):
                cases.append({
                    "name": f"点击{elem.get('text') or elem.get('name')}按钮",
                    "module": self._get_module(elem),
                    "priority": "P1",
                    "preconditions": f"页面加载完成，按钮{elem.get('text') or elem.get('name')}可见",
                    "steps": f"1. 定位到按钮\n2. 点击按钮\n3. 观察页面响应",
                    "expected_results": "按钮点击成功，页面正确响应",
                    "element_selector": elem.get("selector", "")
                })

            elif elem.get("tag") == "select":
                cases.append({
                    "name": f"下拉框{elem.get('name')}选择操作",
                    "module": self._get_module(elem),
                    "priority": "P1",
                    "preconditions": f"下拉框{elem.get('name')}可见",
                    "steps": f"1. 点击下拉框\n2. 选择选项\n3. 验证选择结果",
                    "expected_results": "下拉框选择成功，显示所选内容",
                    "element_selector": elem.get("selector", "")
                })

            elif elem.get("tag") == "textarea":
                cases.append({
                    "name": f"文本域{elem.get('name') or elem.get('placeholder')}输入",
                    "module": self._get_module(elem),
                    "priority": "P1",
                    "preconditions": f"文本域{elem.get('name') or elem.get('placeholder')}可见",
                    "steps": f"1. 点击文本域\n2. 输入多行文本\n3. 验证输入内容",
                    "expected_results": "文本域输入成功，内容正确显示",
                    "element_selector": elem.get("selector", "")
                })

            elif elem.get("tag") == "div" and (elem.get("role") or elem.get("text")):
                element_name = elem.get("text") or elem.get("role") or "DIV元素"
                cases.append({
                    "name": f"点击{element_name}",
                    "module": self._get_module(elem),
                    "priority": "P1",
                    "preconditions": f"页面加载完成，{element_name}可见",
                    "steps": f"1. 定位到{element_name}\n2. 点击该元素\n3. 观察页面响应",
                    "expected_results": "元素点击成功，页面正确响应",
                    "element_selector": elem.get("selector", "")
                })

        return cases

    def _generate_validation_cases(self, elements: List[Dict]) -> List[Dict]:
        cases = []

        for elem in elements:
            if elem.get("tag") == "input":
                input_name = elem.get("name") or elem.get("placeholder") or "输入框"

                cases.append({
                    "name": f"{input_name}必填校验",
                    "module": self._get_module(elem),
                    "priority": "P0",
                    "preconditions": f"找到必填输入框{input_name}",
                    "steps": f"1. 留空{input_name}\n2. 尝试提交\n3. 检查提示信息",
                    "expected_results": "显示必填提示，不允许提交",
                    "element_selector": elem.get("selector", "")
                })

                cases.append({
                    "name": f"{input_name}格式校验",
                    "module": self._get_module(elem),
                    "priority": "P1",
                    "preconditions": f"找到输入框{input_name}",
                    "steps": f"1. 输入格式错误的数据\n2. 尝试提交\n3. 检查格式错误提示",
                    "expected_results": "显示格式错误提示",
                    "element_selector": elem.get("selector", "")
                })

        return cases

    def _generate_boundary_cases(self, elements: List[Dict]) -> List[Dict]:
        cases = []

        for elem in elements:
            if elem.get("tag") == "input":
                input_name = elem.get("name") or elem.get("placeholder") or "输入框"

                cases.append({
                    "name": f"{input_name}边界值-超长输入",
                    "module": self._get_module(elem),
                    "priority": "P2",
                    "preconditions": f"找到输入框{input_name}",
                    "steps": f"1. 输入超长字符（1000+字符）\n2. 检查系统响应",
                    "expected_results": "系统正确处理超长输入，不崩溃",
                    "element_selector": elem.get("selector", "")
                })

                cases.append({
                    "name": f"{input_name}边界值-特殊字符",
                    "module": self._get_module(elem),
                    "priority": "P2",
                    "preconditions": f"找到输入框{input_name}",
                    "steps": f"1. 输入特殊字符（<>\"'&等）\n2. 检查系统响应",
                    "expected_results": "特殊字符被正确转义或过滤",
                    "element_selector": elem.get("selector", "")
                })

        return cases

    def _generate_from_functional_points(
        self,
        functional_points: List[str],
        elements: List[Dict]
    ) -> List[Dict]:
        cases = []
        for point in functional_points:
            cases.append({
                "name": f"功能点: {point}",
                "module": "功能验证",
                "priority": "P0",
                "preconditions": "系统已登录，页面已加载",
                "steps": f"1. 进入相关功能页面\n2. 执行{point}\n3. 验证结果",
                "expected_results": f"{point}功能正常工作",
                "element_selector": ""
            })
        return cases

    def _get_module(self, element: Dict) -> str:
        if element.get("id"):
            return element.get("id").split("-")[0] if "-" in element.get("id") else "通用"
        if element.get("name"):
            return element.get("name").split("-")[0] if "-" in element.get("name") else "通用"
        return "通用"

    def _deduplicate_cases(self, cases: List[Dict]) -> List[Dict]:
        seen = set()
        unique_cases = []
        for case in cases:
            key = case.get("name", "")
            if key not in seen:
                seen.add(key)
                unique_cases.append(case)
        return unique_cases

    def _assign_priorities(self, cases: List[Dict]) -> List[Dict]:
        priority_keywords = {
            "P0": ["必填", "校验", "验证", "登录", "核心", "必选"],
            "P1": ["正常", "常规", "点击", "输入", "选择"],
            "P2": ["边界", "特殊", "超长", "异常"]
        }

        for case in cases:
            name = case.get("name", "")
            priority = "P1"
            for p_level, keywords in priority_keywords.items():
                if any(kw in name for kw in keywords):
                    priority = p_level
                    break
            case["priority"] = priority

        return cases


case_generator = CaseGenerator()
