"""
测试用例生成技能 — 分段调用 Claude LLM 生成可执行的 UI 自动化测试用例
功能：
  generate_cases()    分段生成（Step-1 提取模块 + Step-2 并行逐模块）
  optimize_cases()    覆盖度补全（逐模块找缺口，追加新用例）
  analyze_coverage()  覆盖度统计（规则引擎，无 LLM）
"""
import asyncio
import json
import os
from typing import Any, Callable, Dict, List, Optional
from loguru import logger


class CaseGenerator:
    def __init__(self):
        self.priority_levels = ["P0", "P1", "P2"]

    # ==================================================================
    # 主入口：分段生成
    # ==================================================================
    async def generate_cases(
        self,
        url: str,
        page_elements: List[Dict[str, Any]],
        document_data: Optional[Dict[str, Any]] = None,
        requirements: List[str] = None,
        progress_cb: Optional[Callable] = None,
    ) -> List[Dict[str, Any]]:
        logger.info("Generating test cases via staged LLM...")

        async def _p(pct: int, stage: str):
            if progress_cb:
                await progress_cb(pct, stage)

        await _p(3, "准备生成...")

        try:
            cases = await self._generate_staged(url, page_elements, document_data, _p)
            if cases:
                await _p(100, f"生成完成，共 {len(cases)} 条用例")
                logger.info(f"Staged LLM generated {len(cases)} test cases")
                return cases
        except Exception as e:
            logger.warning(f"Staged LLM generation failed, falling back to template: {e}")
            await _p(80, "LLM 失败，使用模板生成兜底...")

        # 兜底：模板生成
        cases = []
        cases.extend(self._generate_normal_cases(page_elements))
        cases.extend(self._generate_validation_cases(page_elements))
        cases.extend(self._generate_boundary_cases(page_elements))
        if document_data and document_data.get("structured", {}).get("functional_points"):
            cases.extend(self._generate_from_functional_points(
                document_data["structured"]["functional_points"], page_elements
            ))
        cases = self._deduplicate_cases(cases)
        cases = self._assign_priorities(cases)
        await _p(100, f"模板生成完成，共 {len(cases)} 条用例")
        logger.info(f"Template generated {len(cases)} test cases")
        return cases

    # ------------------------------------------------------------------
    # 分段生成主流程
    # ------------------------------------------------------------------
    async def _generate_staged(
        self,
        url: str,
        page_elements: List[Dict[str, Any]],
        document_data: Optional[Dict[str, Any]],
        _p: Callable,
    ) -> List[Dict[str, Any]]:
        elements_summary = self._build_elements_summary(page_elements)
        doc_context = self._build_doc_context(document_data)

        await _p(8, "正在分析页面结构...")
        modules = await self._extract_page_modules(elements_summary, doc_context)

        if not modules:
            logger.warning("Module extraction returned empty, falling back to single-call LLM")
            await _p(20, "模块提取失败，使用单次生成...")
            return await self._generate_single_call(url, elements_summary, doc_context)

        logger.info(f"Extracted {len(modules)} modules: {[m['name'] for m in modules]}")
        await _p(20, f"识别到 {len(modules)} 个功能模块，开始并行生成...")

        sem = asyncio.Semaphore(2)
        counter = {"done": 0, "total": len(modules)}

        async def _gen_module(idx: int, module: Dict) -> List[Dict]:
            async with sem:
                module_name = module.get("name", f"模块{idx + 1}")
                module_elements = module.get("elements", [])
                try:
                    cases = await self._generate_cases_for_module(
                        url, module_name, module_elements, doc_context
                    )
                    counter["done"] += 1
                    pct = 20 + int(counter["done"] / counter["total"] * 72)
                    await _p(pct, f"模块「{module_name}」完成 ({counter['done']}/{counter['total']})")
                    logger.info(f"  [{counter['done']}/{counter['total']}] 「{module_name}」生成 {len(cases)} 条")
                    return cases
                except Exception as e:
                    logger.warning(f"  模块「{module_name}」生成失败: {e}")
                    return []

        all_results = await asyncio.gather(*[_gen_module(i, m) for i, m in enumerate(modules)])

        all_cases: List[Dict] = []
        for cases in all_results:
            all_cases.extend(cases)

        for i, case in enumerate(all_cases):
            case["id"] = f"TC{i + 1:03d}"

        return all_cases

    # ------------------------------------------------------------------
    # Step-1：提取页面模块
    # ------------------------------------------------------------------
    async def _extract_page_modules(
        self, elements_summary: str, doc_context: str
    ) -> List[Dict]:
        system_prompt = (
            "You are a UI analyst. Analyze page elements and group them into logical modules. "
            "Output ONLY valid JSON. No markdown, no explanation."
        )
        prompt = f"""分析以下页面元素，将它们归纳为 2-8 个逻辑功能模块。

页面元素：
{elements_summary}

{doc_context}

只输出纯JSON：
{{
  "modules": [
    {{
      "name": "模块名称（如：登录模块、搜索模块）",
      "elements": ["selector1", "selector2"]
    }}
  ]
}}"""
        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=30)
            data = json.loads(raw)
            modules = data.get("modules", [])
            if isinstance(modules, list) and modules:
                return modules
        except Exception as e:
            logger.warning(f"Module extraction failed: {e}")
        return []

    # ------------------------------------------------------------------
    # Step-2：单模块生成用例
    # ------------------------------------------------------------------
    async def _generate_cases_for_module(
        self,
        url: str,
        module_name: str,
        module_elements: List[str],
        doc_context: str,
    ) -> List[Dict]:
        system_prompt = (
            "You are a senior QA automation engineer. "
            "Generate executable UI automation test cases for Playwright/Selenium. "
            "Output ONLY a single valid JSON object. No markdown, no explanation."
        )
        selectors_str = "\n".join(f"  - {s}" for s in module_elements) if module_elements else "  （见完整元素列表）"
        prompt = f"""为页面模块「{module_name}」生成 UI 自动化测试用例。

目标页面：{url or '（未提供）'}
本模块关键元素：
{selectors_str}

{doc_context}

【要求】
- 生成 5-8 条覆盖正常流程(P0)、表单校验(P1)、边界/异常(P2) 的用例
- 步骤含具体 selector 和测试数据，示例：
  "1. 找到用户名输入框（selector: #username），输入 'test@example.com'\\n2. 点击登录按钮（selector: button.submit）"
- 预期结果可断言（如"页面跳转到 /home，顶部显示欢迎语"）
- 只针对本模块

只输出纯JSON：
{{
  "cases": [
    {{
      "name": "登录-有效账号-登录成功",
      "module": "{module_name}",
      "priority": "P0",
      "preconditions": "前置条件",
      "steps": "1. 步骤一\\n2. 步骤二",
      "expected_results": "可断言预期结果",
      "element_selector": "主元素 selector"
    }}
  ]
}}"""
        raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
        data = json.loads(raw)
        cases = data.get("cases", [])
        if not isinstance(cases, list):
            return []
        for case in cases:
            case.setdefault("name", "未命名用例")
            case.setdefault("module", module_name)
            case.setdefault("priority", "P1")
            case.setdefault("preconditions", "")
            case.setdefault("expected_results", "")
            case.setdefault("element_selector", "")
            steps = case.get("steps", "")
            if isinstance(steps, list):
                case["steps"] = "\n".join(f"{j + 1}. {s}" for j, s in enumerate(steps))
            elif not isinstance(steps, str):
                case["steps"] = str(steps)
        return cases

    # ------------------------------------------------------------------
    # 单次兜底
    # ------------------------------------------------------------------
    async def _generate_single_call(
        self, url: str, elements_summary: str, doc_context: str
    ) -> List[Dict]:
        system_prompt = (
            "You are a senior QA automation engineer. "
            "Generate executable UI automation test cases for Playwright/Selenium. "
            "Output ONLY a single valid JSON object. No markdown, no explanation."
        )
        prompt = f"""根据以下页面结构生成 UI 自动化测试用例（总量不超过 25 条）。

目标页面：{url or '（未提供）'}
页面元素：
{elements_summary}

{doc_context}

步骤含具体 selector 和测试数据，预期结果可断言。
只输出纯JSON：
{{
  "cases": [
    {{
      "name": "...", "module": "...", "priority": "P0",
      "preconditions": "...", "steps": "1. ...\\n2. ...",
      "expected_results": "...", "element_selector": "..."
    }}
  ]
}}"""
        raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=120)
        data = json.loads(raw)
        cases = data.get("cases", [])
        for case in cases:
            steps = case.get("steps", "")
            if isinstance(steps, list):
                case["steps"] = "\n".join(f"{j + 1}. {s}" for j, s in enumerate(steps))
        return cases if isinstance(cases, list) else []

    # ==================================================================
    # 用例优化：逐模块补全覆盖缺口
    # ==================================================================
    async def optimize_cases(
        self,
        existing_cases: List[Dict[str, Any]],
        page_elements: List[Dict[str, Any]],
        document_data: Optional[Dict[str, Any]] = None,
        progress_cb: Optional[Callable] = None,
    ) -> List[Dict[str, Any]]:
        """分析已有用例的覆盖缺口，返回补充的新用例列表。"""
        async def _p(pct: int, stage: str):
            if progress_cb:
                await progress_cb(pct, stage)

        await _p(5, "正在分析现有用例覆盖情况...")

        # 按模块分组
        modules: Dict[str, List[Dict]] = {}
        for case in existing_cases:
            m = case.get("module", "通用")
            modules.setdefault(m, []).append(case)

        elements_summary = self._build_elements_summary(page_elements)
        doc_context = self._build_doc_context(document_data)

        sem = asyncio.Semaphore(2)
        module_names = list(modules.keys())
        counter = {"done": 0, "total": len(module_names)}

        async def _opt_module(module_name: str) -> List[Dict]:
            async with sem:
                existing = modules[module_name]
                try:
                    new_cases = await self._optimize_one_module(
                        module_name, existing, elements_summary, doc_context
                    )
                    counter["done"] += 1
                    pct = 10 + int(counter["done"] / counter["total"] * 80)
                    await _p(pct, f"模块「{module_name}」优化完成 ({counter['done']}/{counter['total']})")
                    return new_cases
                except Exception as e:
                    logger.warning(f"模块「{module_name}」优化失败: {e}")
                    return []

        all_results = await asyncio.gather(*[_opt_module(m) for m in module_names])

        new_cases = [c for batch in all_results for c in batch]

        # 统一编号（接在已有用例之后）
        start = len(existing_cases) + 1
        for i, case in enumerate(new_cases):
            case["id"] = f"TC{start + i:03d}"

        await _p(100, f"优化完成，新增 {len(new_cases)} 条补充用例")
        logger.info(f"Optimization added {len(new_cases)} new cases")
        return new_cases

    async def _optimize_one_module(
        self,
        module_name: str,
        existing_cases: List[Dict],
        elements_summary: str,
        doc_context: str,
    ) -> List[Dict]:
        """分析单个模块的覆盖缺口，输出新增用例。"""
        existing_summary = "\n".join(
            f"  - [{c.get('priority','?')}] {c.get('name','?')}" for c in existing_cases[:20]
        )
        system_prompt = (
            "You are a senior QA automation engineer. "
            "Find coverage gaps in existing test cases and output ONLY new supplementary cases. "
            "Output ONLY valid JSON. No markdown, no explanation."
        )
        prompt = f"""模块「{module_name}」已有 {len(existing_cases)} 条测试用例：
{existing_summary}

页面元素参考：
{elements_summary[:1500]}

{doc_context}

请分析覆盖缺口，生成 3-5 条补充用例（不重复已有用例），重点检查：
- 等价类划分：有没有遗漏的有效/无效等价类
- 边界值：最小值、最大值、零值、空值
- 异常分支：网络错误、并发、权限不足
- 状态转换：从不同前置状态触发操作

只输出纯JSON，只包含新增用例：
{{
  "new_cases": [
    {{
      "name": "用例名称",
      "module": "{module_name}",
      "priority": "P1",
      "preconditions": "前置条件",
      "steps": "1. 步骤一\\n2. 步骤二",
      "expected_results": "预期结果",
      "element_selector": ""
    }}
  ]
}}"""
        raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
        data = json.loads(raw)
        new_cases = data.get("new_cases", [])
        if not isinstance(new_cases, list):
            return []
        for case in new_cases:
            case.setdefault("name", "补充用例")
            case.setdefault("module", module_name)
            case.setdefault("priority", "P1")
            case.setdefault("preconditions", "")
            case.setdefault("expected_results", "")
            case.setdefault("element_selector", "")
            steps = case.get("steps", "")
            if isinstance(steps, list):
                case["steps"] = "\n".join(f"{j + 1}. {s}" for j, s in enumerate(steps))
            elif not isinstance(steps, str):
                case["steps"] = str(steps)
        return new_cases

    # ==================================================================
    # 覆盖度分析（规则引擎，无 LLM）
    # ==================================================================
    def analyze_coverage(
        self,
        cases: List[Dict[str, Any]],
        page_elements: List[Dict[str, Any]],
        document_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """快速统计覆盖情况，返回指标字典。"""
        total = len(cases)
        if total == 0:
            return {"score": 0, "total": 0, "suggestions": ["当前无测试用例，请先生成用例"]}

        # 优先级分布
        priority_count = {"P0": 0, "P1": 0, "P2": 0}
        for c in cases:
            p = c.get("priority", "P1")
            priority_count[p] = priority_count.get(p, 0) + 1

        # 模块分布
        module_map: Dict[str, Dict] = {}
        for c in cases:
            m = c.get("module", "通用")
            if m not in module_map:
                module_map[m] = {"total": 0, "P0": 0, "P1": 0, "P2": 0}
            p = c.get("priority", "P1")
            module_map[m]["total"] += 1
            module_map[m][p] = module_map[m].get(p, 0) + 1

        # 元素覆盖：哪些 selector 在用例里被引用了
        used_selectors = set()
        for c in cases:
            sel = c.get("element_selector", "")
            if sel:
                used_selectors.add(sel)
            # 也从步骤文本里提取 selector:xxx
            steps_text = c.get("steps", "")
            import re
            for m in re.findall(r"selector:\s*([^\s,）\)]+)", steps_text):
                used_selectors.add(m.strip())

        total_elements = len(page_elements)
        covered_elements = 0
        for elem in page_elements:
            sel = elem.get("selector", "")
            if sel and sel in used_selectors:
                covered_elements += 1

        element_coverage = round(covered_elements / total_elements * 100, 1) if total_elements > 0 else 0

        # 综合评分（简单加权）
        p0_ratio = priority_count["P0"] / total
        p0_score = min(p0_ratio * 200, 40)           # P0 占比，满分 40
        module_score = min(len(module_map) * 5, 30)  # 模块数，满分 30
        elem_score = element_coverage * 0.3           # 元素覆盖，满分 30
        score = round(p0_score + module_score + elem_score)
        score = max(0, min(100, score))

        # 建议
        suggestions = []
        if priority_count["P0"] == 0:
            suggestions.append("缺少 P0 核心用例，建议补充关键业务流程的主路径用例")
        if priority_count["P0"] < total * 0.1:
            suggestions.append(f"P0 用例仅占 {round(p0_ratio*100)}%，建议提升至 15% 以上")
        if priority_count["P2"] == 0:
            suggestions.append("缺少 P2 边界/异常用例，建议补充边界值和错误处理场景")
        if len(module_map) == 1:
            suggestions.append("所有用例集中在一个模块，建议按页面功能区划分多个模块")
        if element_coverage < 50 and total_elements > 0:
            suggestions.append(f"元素覆盖率 {element_coverage}%，有 {total_elements - covered_elements} 个页面元素未被测试覆盖")
        for m_name, m_data in module_map.items():
            if m_data["P0"] == 0:
                suggestions.append(f"模块「{m_name}」无 P0 用例")
        if not suggestions:
            suggestions.append("覆盖情况良好，可进一步增加边界值场景提升质量")

        return {
            "score": score,
            "total": total,
            "priority_distribution": priority_count,
            "module_distribution": [
                {"name": k, **v} for k, v in module_map.items()
            ],
            "element_coverage": {
                "total": total_elements,
                "covered": covered_elements,
                "rate": element_coverage,
            },
            "suggestions": suggestions,
        }

    # ==================================================================
    # 构建 prompt 辅助
    # ==================================================================
    def _build_elements_summary(self, elements: List[Dict[str, Any]]) -> str:
        if not elements:
            return "（无页面元素数据）"
        lines = []
        for elem in elements[:80]:
            tag = elem.get("tag", "")
            typ = elem.get("type", "")
            name = elem.get("name", "") or elem.get("placeholder", "") or elem.get("text", "")
            selector = elem.get("selector", "")
            parts = [f"<{tag}"]
            if typ:
                parts.append(f" type={typ}")
            if name:
                parts.append(f" name/text={name!r}")
            if selector:
                parts.append(f" selector={selector!r}")
            parts.append(">")
            lines.append("".join(parts))
        return "\n".join(lines)

    def _build_doc_context(self, document_data: Optional[Dict[str, Any]]) -> str:
        if not document_data:
            return ""
        structured = document_data.get("structured", {})
        text = document_data.get("content", "")
        sections = []
        if structured.get("title"):
            sections.append(f"文档标题：{structured['title']}")
        if structured.get("functional_points"):
            points = "\n".join(f"  - {p}" for p in structured["functional_points"][:20])
            sections.append(f"功能点：\n{points}")
        if not sections and text:
            sections.append(f"需求摘要：\n{text[:2000]}")
        if sections:
            return "需求文档信息：\n" + "\n".join(sections)
        return ""

    # ==================================================================
    # Claude CLI subprocess
    # ==================================================================
    async def _run_claude_subprocess(
        self, system_prompt: str, prompt: str, timeout_secs: int = 90
    ) -> str:
        import shutil
        claude_bin = shutil.which("claude") or shutil.which("claude.cmd")
        if not claude_bin:
            npm_bin = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm")
            for name in ("claude.cmd", "claude"):
                candidate = os.path.join(npm_bin, name)
                if os.path.exists(candidate):
                    claude_bin = candidate
                    break
        if not claude_bin:
            raise RuntimeError("找不到 claude 命令")

        env = os.environ.copy()
        proc = await asyncio.create_subprocess_exec(
            claude_bin,
            "--output-format", "text",
            "--no-session-persistence",
            "--input-format", "text",
            "--system-prompt", system_prompt,
            "-p",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=timeout_secs,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await asyncio.wait_for(proc.communicate(), timeout=5)
            except Exception:
                pass
            raise RuntimeError(f"claude CLI 调用超时（{timeout_secs}s）")

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"claude CLI 错误 (code {proc.returncode}): {err[:300]}")

        raw = stdout.decode("utf-8", errors="replace").strip()
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        return raw

    # ==================================================================
    # 兜底模板方法
    # ==================================================================
    def _generate_normal_cases(self, elements: List[Dict]) -> List[Dict]:
        cases = []
        for elem in elements:
            if elem.get("tag") == "input":
                cases.append({
                    "name": f"输入框{elem.get('name') or elem.get('placeholder')}正常输入",
                    "module": self._get_module(elem),
                    "priority": "P1",
                    "preconditions": f"打开目标页面，找到输入框{elem.get('name') or elem.get('placeholder')}",
                    "steps": "1. 点击输入框\n2. 输入有效数据\n3. 检查输入内容是否正确显示",
                    "expected_results": "输入内容正确显示，无格式错误",
                    "element_selector": elem.get("selector", ""),
                })
            elif elem.get("tag") == "button" or (elem.get("tag") == "a" and elem.get("text")):
                cases.append({
                    "name": f"点击{elem.get('text') or elem.get('name')}按钮",
                    "module": self._get_module(elem),
                    "priority": "P1",
                    "preconditions": f"页面加载完成，按钮{elem.get('text') or elem.get('name')}可见",
                    "steps": "1. 定位到按钮\n2. 点击按钮\n3. 观察页面响应",
                    "expected_results": "按钮点击成功，页面正确响应",
                    "element_selector": elem.get("selector", ""),
                })
            elif elem.get("tag") == "select":
                cases.append({
                    "name": f"下拉框{elem.get('name')}选择操作",
                    "module": self._get_module(elem),
                    "priority": "P1",
                    "preconditions": f"下拉框{elem.get('name')}可见",
                    "steps": "1. 点击下拉框\n2. 选择选项\n3. 验证选择结果",
                    "expected_results": "下拉框选择成功，显示所选内容",
                    "element_selector": elem.get("selector", ""),
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
                    "element_selector": elem.get("selector", ""),
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
                    "steps": "1. 输入超长字符（1000+字符）\n2. 检查系统响应",
                    "expected_results": "系统正确处理超长输入，不崩溃",
                    "element_selector": elem.get("selector", ""),
                })
        return cases

    def _generate_from_functional_points(
        self, functional_points: List[str], elements: List[Dict]
    ) -> List[Dict]:
        return [
            {
                "name": f"功能点: {point}",
                "module": "功能验证",
                "priority": "P0",
                "preconditions": "系统已登录，页面已加载",
                "steps": f"1. 进入相关功能页面\n2. 执行{point}\n3. 验证结果",
                "expected_results": f"{point}功能正常工作",
                "element_selector": "",
            }
            for point in functional_points
        ]

    def _get_module(self, element: Dict) -> str:
        if element.get("id"):
            return element["id"].split("-")[0] if "-" in element["id"] else "通用"
        if element.get("name"):
            return element["name"].split("-")[0] if "-" in element["name"] else "通用"
        return "通用"

    def _deduplicate_cases(self, cases: List[Dict]) -> List[Dict]:
        seen, unique = set(), []
        for case in cases:
            key = case.get("name", "")
            if key not in seen:
                seen.add(key)
                unique.append(case)
        return unique

    def _assign_priorities(self, cases: List[Dict]) -> List[Dict]:
        priority_keywords = {
            "P0": ["必填", "校验", "验证", "登录", "核心", "必选"],
            "P1": ["正常", "常规", "点击", "输入", "选择"],
            "P2": ["边界", "特殊", "超长", "异常"],
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
