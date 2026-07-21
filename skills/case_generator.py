"""
测试用例生成技能 — 分段调用 Claude LLM 生成可执行的 UI 自动化测试用例
功能：
  generate_cases()        分段生成（Step-1 提取模块 + Step-2 并行逐模块）
  optimize_cases()        覆盖度补全（逐模块找缺口，追加新用例）
  analyze_coverage()      覆盖度统计（规则引擎，无 LLM）
  analyze_doc_diff()      新旧需求文档 AI Diff 分析，返回变更模块清单
  incremental_update()    文档变更后增量更新用例（只对变更/新增模块重生成）
"""
import asyncio
import hashlib
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
            # LLM 返回了0条：尝试文档驱动兜底
            logger.warning("LLM 生成 0 条，尝试文档驱动兜底生成")
            await _p(70, "正在使用需求文档补充生成...")
            doc_cases = await self._generate_doc_driven(url, document_data, _p)
            if doc_cases:
                await _p(100, f"生成完成，共 {len(doc_cases)} 条用例")
                logger.info(f"Doc-driven fallback generated {len(doc_cases)} test cases")
                return doc_cases
        except Exception as e:
            logger.warning(f"Staged LLM generation failed, falling back to template: {e}")
            await _p(80, "LLM 失败，使用模板生成兜底...")

        # 最终兜底：模板生成（页面元素足够时才有意义）
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
        if cases:
            await _p(100, f"模板生成完成，共 {len(cases)} 条用例")
            logger.info(f"Template generated {len(cases)} test cases")
        else:
            await _p(100, "未能生成用例，请确认任务已上传需求文档并成功解析页面元素")
            logger.warning("All generation methods returned 0 cases")
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

        # 页面元素太少（≤3个）时，跳过元素分析，直接以文档为主生成
        FEW_ELEMENTS = len(page_elements) <= 3
        if FEW_ELEMENTS:
            logger.info(f"页面元素太少({len(page_elements)}个)，以需求文档为主生成用例")
            await _p(15, f"页面元素较少，以需求文档为主生成用例...")
            return await self._generate_doc_driven(url, document_data, _p)

        await _p(8, "正在分析页面结构...")
        modules = await self._extract_page_modules(elements_summary, doc_context)

        if not modules:
            logger.warning("Module extraction returned empty, falling back to single-call LLM")
            await _p(20, "正在调用 AI 整体生成用例...")
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
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=60)
            data = json.loads(raw)
            modules = data.get("modules", [])
            if isinstance(modules, list) and modules:
                return modules
            logger.warning(f"Module extraction returned no modules, raw={raw[:200]}")
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
        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
            if not raw.strip().startswith("{") and not raw.strip().startswith("["):
                logger.warning(f"模块「{module_name}」LLM 返回非 JSON 内容: {raw[:200]}")
                return []
            data = json.loads(raw)
        except Exception as e:
            logger.warning(f"模块「{module_name}」LLM 调用失败: {e}")
            return []
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
                # 同时去掉步骤文本中 AI 自带的数字前缀
                import re as _re_step
                case["steps"] = "\n".join(
                    _re_step.sub(r'^\s*\d+\.\s*', '', str(s)) for s in steps
                )
            elif not isinstance(steps, str):
                case["steps"] = str(steps)
        return cases

    # ------------------------------------------------------------------
    # 单次兜底
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 文档驱动生成（页面元素极少时，纯靠需求文档生成功能用例）
    # ------------------------------------------------------------------
    async def _generate_doc_driven(
        self, url: str, document_data: Optional[Dict[str, Any]], _p: Callable
    ) -> List[Dict[str, Any]]:
        """当页面元素太少无法分析时，以需求文档为主生成功能测试用例。"""
        doc_text = ""
        if document_data:
            doc_text = document_data.get("content", "")
            # 也尝试从结构化数据拼出可用文本
            if not doc_text:
                structured = document_data.get("structured", {})
                pts = structured.get("functional_points", [])
                if pts:
                    doc_text = "\n".join(pts)

        if not doc_text or len(doc_text.strip()) < 30:
            logger.warning("文档内容为空，无法生成用例")
            await _p(100, "文档内容不足，无法生成用例，请上传需求文档后重试")
            return []

        system_prompt = (
            "You are a senior QA engineer. Your ONLY task is to generate test cases as a JSON object. "
            "You MUST output a single valid JSON object. Do NOT refuse, do NOT ask questions, "
            "do NOT output any text outside the JSON. Generate test cases directly from the provided document."
        )
        prompt = f"""根据以下需求文档生成功能测试用例（15-25条）。

【重要】直接输出JSON，不要拒绝，不要提问，不要解释。

需求文档内容：
---
{doc_text[:12000]}
---

必须直接输出以下格式的JSON（不要输出任何其他内容）：
{{
  "cases": [
    {{
      "name": "模块-场景描述",
      "module": "所属功能模块",
      "priority": "P0",
      "preconditions": "前置条件",
      "steps": "1. 操作步骤\\n2. 操作步骤",
      "expected_results": "可断言的预期结果",
      "element_selector": ""
    }}
  ]
}}"""

        await _p(30, "正在调用 AI 生成功能用例...")
        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=120)
            # 如果 LLM 返回的不是 JSON（比如拒绝回答的纯文本），记录详细日志
            if not raw.strip().startswith("{") and not raw.strip().startswith("["):
                logger.warning(f"文档驱动生成：LLM 返回非 JSON 内容（前200字）: {raw[:200]}")
                return []
            data = json.loads(raw)
            cases = data.get("cases", [])
            if not isinstance(cases, list):
                return []
            for case in cases:
                case.setdefault("name", "未命名用例")
                case.setdefault("module", "通用")
                case.setdefault("priority", "P1")
                case.setdefault("preconditions", "")
                case.setdefault("expected_results", "")
                case.setdefault("element_selector", "")
                steps = case.get("steps", "")
                if isinstance(steps, list):
                    import re as _re_s
                    case["steps"] = "\n".join(_re_s.sub(r'^\s*\d+\.\s*', '', str(s)) for s in steps)
                elif not isinstance(steps, str):
                    case["steps"] = str(steps)
            logger.info(f"文档驱动生成完成: {len(cases)} 条用例")
            await _p(95, f"生成完成，共 {len(cases)} 条用例")
            return cases
        except Exception as e:
            logger.warning(f"文档驱动生成失败: {e}")
            await _p(95, "AI 生成失败，请稍后重试")
            return []

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
        # 按类型分组：交互元素（input/button/a/select 等）优先，文字节点补充语义
        interactive_tags = {"input", "button", "a", "select", "textarea"}
        interactive = [e for e in elements if e.get("tag", "") in interactive_tags]
        text_nodes   = [e for e in elements if e.get("tag", "") not in interactive_tags and e.get("text", "")]
        # 最多取120个交互元素 + 100个文字节点，总量220；
        # 列表型页面（名师专区/课程列表）以文字节点为主，确保每位教师的姓名/职称不丢失
        selected = interactive[:120] + text_nodes[:100]
        lines = []
        for elem in selected:
            tag = elem.get("tag", "")
            typ = elem.get("type", "")
            name = elem.get("name", "") or elem.get("placeholder", "") or elem.get("text", "")
            selector = elem.get("selector", "")
            parts = [f"<{tag}"]
            if typ:
                parts.append(f" type={typ}")
            if name:
                parts.append(f" name/text={name!r}")
            if selector and selector not in ("div", "span", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
                parts.append(f" selector={selector!r}")
            parts.append(">")
            lines.append("".join(parts))
        return "\n".join(lines)

    def _build_doc_context(self, document_data: Optional[Dict[str, Any]]) -> str:
        if not document_data:
            return ""
        structured = document_data.get("structured", {})
        text = document_data.get("content", "")
        meta_fmt = (document_data.get("metadata") or {}).get("format", "")
        sections = []
        if structured.get("title"):
            sections.append(f"文档标题：{structured['title']}")
        if structured.get("functional_points"):
            points = "\n".join(f"  - {p}" for p in structured["functional_points"][:30])
            sections.append(f"功能点：\n{points}")
        if not sections and text:
            # 页面正文（page_text）比需求文档更丰富，多注入内容；
            # 列表型页面（名师专区/课程列表等）每条数据~200字，6000字≈30条记录
            text_limit = 6000 if meta_fmt == "page_text" else 3000
            sections.append(f"页面内容摘要：\n{text[:text_limit]}")
        if sections:
            return "需求文档信息：\n" + "\n".join(sections)
        return ""

    # ==================================================================
    # LLM 调用（统一入口，支持 Anthropic / OpenAI 兼容格式）
    # ==================================================================
    async def _run_claude_subprocess(
        self, system_prompt: str, prompt: str, timeout_secs: int = 90
    ) -> str:
        """调用 LLM API，自动根据模型和 URL 选择正确格式。"""
        from tools.llm_client import call_llm

        raw = await call_llm(
            system_prompt, prompt,
            max_tokens=8192,
            timeout_secs=timeout_secs,
        )
        raw = raw.strip()
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


    # ==================================================================
    # 文档哈希（复用 ai_case_generator 的约定：MD5 前 16 位）
    # ==================================================================
    @staticmethod
    def compute_doc_hash(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]

    # ==================================================================
    # AI Diff 分析：新旧需求文档 → 变更模块清单
    # ==================================================================
    async def analyze_doc_diff(
        self,
        old_doc_content: str,
        new_doc_content: str,
    ) -> Dict[str, Any]:
        """
        对比两版需求文档，识别功能模块级别的变更范围。
        返回与 AICaseGenerator.analyze_document_diff() 相同结构：
        {
            "changed":    [{"module": "...", "summary": "..."}],
            "added":      [{"module": "...", "summary": "..."}],
            "removed":    ["模块名"],
            "unchanged":  ["模块名"],
            "impact_level": "high|medium|low",
            "diff_summary": "一句话变更总结"
        }
        """
        old_snip = old_doc_content[:6000]
        new_snip = new_doc_content[:6000]

        system_prompt = (
            "You are a senior QA analyst. Compare two versions of a requirements document "
            "and identify which functional modules have changed, been added, removed, or remained the same. "
            "Output ONLY valid JSON. No markdown, no explanation."
        )
        prompt = f"""对比以下新旧两版需求文档，识别功能模块级别的变更范围，用于指导 WebUI 自动化测试用例的增量更新。

【旧版文档】
---
{old_snip}
---

【新版文档】
---
{new_snip}
---

分析要求：
1. 以功能模块为粒度（对应页面中的一个功能区块，如：登录表单、搜索栏、用户菜单等）
2. changed = 模块存在但需求内容发生实质变更（新增/修改/删除了具体交互或字段）
3. added   = 旧文档中完全没有的全新功能模块
4. removed = 旧文档有但新文档彻底删除的功能模块
5. unchanged = 内容完全未变或只有文字细节调整，不影响测试用例的模块
6. impact_level: high（影响核心流程）/ medium（影响部分功能）/ low（仅文字修正）

只输出纯 JSON：
{{
  "changed": [{{"module": "模块名称", "summary": "变更描述（一句话）"}}],
  "added":   [{{"module": "模块名称", "summary": "新增描述（一句话）"}}],
  "removed": ["模块名称"],
  "unchanged": ["模块名称"],
  "impact_level": "high",
  "diff_summary": "本次变更的一句话总结"
}}"""

        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=60)
            result = json.loads(raw)
            result.setdefault("changed", [])
            result.setdefault("added", [])
            result.setdefault("removed", [])
            result.setdefault("unchanged", [])
            result.setdefault("impact_level", "medium")
            result.setdefault("diff_summary", "需求文档已更新")
            logger.info(
                f"WebUI Diff 分析: changed={len(result['changed'])} "
                f"added={len(result['added'])} removed={len(result['removed'])} "
                f"unchanged={len(result['unchanged'])}"
            )
            return result
        except json.JSONDecodeError as e:
            logger.error(f"WebUI Diff 返回非法 JSON: {e}")
            raise RuntimeError(f"Diff 分析失败，AI 返回非 JSON 内容: {e}")
        except Exception as e:
            logger.error(f"WebUI Diff 分析异常: {e}")
            raise RuntimeError(f"Diff 分析异常: {e}")

    # ==================================================================
    # 增量更新：文档变更后只对 changed/added 模块重生成
    # ==================================================================
    async def incremental_update(
        self,
        url: str,
        page_elements: List[Dict[str, Any]],
        existing_cases: List[Dict[str, Any]],
        diff_result: Dict[str, Any],
        new_doc_content: str = "",
        progress_cb: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        根据 diff_result 对 changed/added 模块重生成用例，unchanged 保留，removed 标记废弃。

        返回：
        {
            "new_cases":        List[Dict],   # changed/added 模块新生成的用例
            "retained_cases":   List[Dict],   # unchanged 保留的旧用例（status='active'）
            "deprecated_cases": List[Dict],   # removed 打了 deprecated 标记的旧用例
            "diff_summary":     str,
        }
        所有用例统一重编号 TC001…TCN（deprecated 不参与重编号，保留原 id）。
        """
        async def _p(pct: int, stage: str):
            if progress_cb:
                try:
                    await progress_cb(pct, stage)
                except Exception:
                    pass

        changed_mods   = diff_result.get("changed", [])
        added_mods     = diff_result.get("added", [])
        removed_names  = set(diff_result.get("removed", []))
        unchanged_names = set(diff_result.get("unchanged", []))
        diff_summary   = diff_result.get("diff_summary", "需求文档已更新")

        # ── 按模块对已有用例分组 ──────────────────────────────────────────
        existing_by_module: Dict[str, List[Dict]] = {}
        for c in existing_cases:
            m = c.get("module", "通用")
            existing_by_module.setdefault(m, []).append(c)

        # ── 需要重生成的模块 ──────────────────────────────────────────────
        mods_to_regen = changed_mods + added_mods
        total_tasks   = max(len(mods_to_regen), 1)

        await _p(10, f"共 {len(changed_mods)} 个变更模块（用例级合并）、{len(added_mods)} 个新增模块...")

        elements_summary = self._build_elements_summary(page_elements)
        doc_context = (
            f"需求文档信息：\n{new_doc_content[:2000]}" if new_doc_content else ""
        )

        sem = asyncio.Semaphore(2)
        completed = [0]

        # ── 变更模块：保守式用例级合并（默认保留，只找失效和新增） ────────────
        async def _merge_changed(i: int, mod_info: Dict):
            async with sem:
                name    = mod_info["module"]
                summary = mod_info.get("summary", "")
                old_mod_cases = existing_by_module.get(name, [])
                await _p(
                    10 + int(i / total_tasks * 70),
                    f"用例级合并 {i + 1}/{total_tasks}：{name}...",
                )
                cases_summary = "\n".join(
                    f"  {c.get('id','?')} | {c.get('name','')} | {c.get('priority','')}"
                    for c in old_mod_cases[:30]
                )
                system_prompt = (
                    "You are a senior QA engineer performing a conservative test case review. "
                    "Your default is to KEEP existing test cases. Only mark deprecated if the "
                    "feature has been COMPLETELY REMOVED. Output ONLY valid JSON."
                )
                prompt = f"""需求模块「{name}」发生了变更，请做保守式审查。

变更说明：{summary or '需求有局部更新'}

【新版需求文档】
---
{new_doc_content[:3000]}
---

【现有测试用例】（用例ID | 用例名称 | 优先级）
{cases_summary or '（暂无用例）'}

## 审查原则（严格遵守）
- 默认保留所有旧用例
- deprecated（废弃）：只有功能点在新文档中「完全消失」才废弃，功能调整不废弃
- 不确定是否删除 → 保留
- deprecated 列表通常很小（0-2条），如果超过旧用例一半请重新检查

只输出纯JSON：
{{
  "deprecated": ["用例ID（仅完全删除的功能点对应的用例）"],
  "new_cases": [
    {{
      "name": "新场景用例名称", "module": "{name}", "priority": "P1",
      "preconditions": "前置条件",
      "steps": "1. 步骤\\n2. 步骤",
      "expected_results": "预期结果",
      "element_selector": ""
    }}
  ],
  "reason": "一句话说明废弃原因"
}}"""
                try:
                    raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
                    result = json.loads(raw)
                    result.setdefault("deprecated", [])
                    result.setdefault("new_cases", [])
                except Exception as e:
                    logger.warning(f"WebUI 模块「{name}」用例级合并失败: {e}，全部保留旧用例")
                    result = {"deprecated": [], "new_cases": []}
                completed[0] += 1
                await _p(
                    10 + int(completed[0] / total_tasks * 70),
                    f"已完成 {completed[0]}/{total_tasks}：{name}",
                )
                return name, old_mod_cases, result

        # ── 新增模块：全量生成 ────────────────────────────────────────────
        async def _regen_added(i: int, mod_info: Dict) -> List[Dict]:
            async with sem:
                name    = mod_info["module"]
                summary = mod_info.get("summary", "")
                idx     = len(changed_mods) + i
                await _p(
                    10 + int(idx / total_tasks * 70),
                    f"生成新增模块 {i + 1}/{len(added_mods)}：{name}...",
                )
                extra_ctx = f"变更说明：{summary}\n" + doc_context
                try:
                    cases = await self._generate_cases_for_module(url, name, [], extra_ctx)
                except Exception as e:
                    logger.warning(f"WebUI 新增模块「{name}」生成失败: {e}")
                    cases = []
                completed[0] += 1
                await _p(
                    10 + int(completed[0] / total_tasks * 70),
                    f"已完成 {completed[0]}/{total_tasks}：{name}",
                )
                return cases

        changed_results = []
        added_case_lists = []
        if changed_mods:
            changed_results = await asyncio.gather(
                *[_merge_changed(i, m) for i, m in enumerate(changed_mods)]
            )
        if added_mods:
            added_case_lists = await asyncio.gather(
                *[_regen_added(i, m) for i, m in enumerate(added_mods)]
            )

        await _p(82, "正在合并用例，统一编号...")

        # ── 合并 ─────────────────────────────────────────────────────────
        retained:    List[Dict] = []
        new_cases:   List[Dict] = []
        deprecated:  List[Dict] = []

        # ── 通用测试类型保护：性能/兼容性/安全等测试永远不因需求变更而废弃 ──
        ALWAYS_KEEP_KEYWORDS = ("性能", "兼容", "安全", "压力", "负载", "可靠性", "稳定性")

        def _is_generic_test(name: str) -> bool:
            return any(kw in name for kw in ALWAYS_KEEP_KEYWORDS)

        protected_names: set = set()
        filtered_removed = set()
        for name in removed_names:
            if _is_generic_test(name):
                protected_names.add(name)
            else:
                filtered_removed.add(name)
        if protected_names:
            logger.info(f"WebUI 通用测试模块强制保留: {list(protected_names)}")
        removed_names = filtered_removed

        # ── 兜底：AI Diff 可能漏掉部分旧模块，文本搜索二次判断 ────────────
        explicitly_classified = (
            {m["module"] for m in changed_mods}
            | {m["module"] for m in added_mods}
            | removed_names
            | unchanged_names
            | protected_names
        )
        implicit_unchanged: set = set()
        implicit_removed:   set = set()

        if new_doc_content:
            doc_text_lower = new_doc_content.lower()
            for name in existing_by_module:
                if name in explicitly_classified:
                    continue
                if _is_generic_test(name):
                    implicit_unchanged.add(name)
                    continue
                keyword = (name.replace("模块", "").replace("测试", "")
                           .replace("管理", "").replace("功能", "").strip())
                found = bool(keyword) and keyword.lower() in doc_text_lower
                if found:
                    implicit_unchanged.add(name)
                else:
                    implicit_removed.add(name)
            if implicit_unchanged:
                logger.info(f"WebUI Diff 未分类 → 文本搜索确认保留: {list(implicit_unchanged)}")
            if implicit_removed:
                logger.info(f"WebUI Diff 未分类 → 文本搜索确认废弃: {list(implicit_removed)}")

        all_unchanged = unchanged_names | implicit_unchanged | protected_names
        all_removed   = removed_names   | implicit_removed

        # unchanged + 兜底模块：直接保留
        for name in all_unchanged:
            for c in existing_by_module.get(name, []):
                retained.append({**c, "status": "active"})

        # changed 模块：默认保留所有旧用例，只排除 deprecated，再追加新场景
        for (mod_name, old_mod_cases, merge_result) in changed_results:
            deprecated_ids = set(merge_result.get("deprecated", []))
            new_case_defs  = merge_result.get("new_cases", [])

            # 安全校验：deprecated 超过 50% 则清空（LLM 过激判断保护）
            if len(deprecated_ids) > max(1, len(old_mod_cases) // 2):
                logger.warning(
                    f"WebUI 模块「{mod_name}」废弃用例过多({len(deprecated_ids)}/{len(old_mod_cases)})，重置"
                )
                deprecated_ids = set()

            # 所有旧用例：不在 deprecated_ids 里的全部保留
            for c in old_mod_cases:
                if c.get("id", "") in deprecated_ids:
                    deprecated.append({**c, "status": "deprecated"})
                else:
                    retained.append({**c, "status": "active"})

            # 新场景用例，标记 is_new
            for nc in new_case_defs:
                nc = dict(nc)
                nc["is_new"] = True
                new_cases.append(nc)

        # added 模块：全量新用例，标记 is_new
        for i, cases in enumerate(added_case_lists):
            for c in (cases or []):
                c = dict(c)
                c["is_new"] = True
                new_cases.append(c)

        # removed + 兜底废弃模块：打废弃标记
        for name in all_removed:
            for c in existing_by_module.get(name, []):
                deprecated.append({**c, "status": "deprecated"})

        # 统一编号（只给 active 的）
        tc_counter = 1
        all_active = retained + new_cases
        for c in all_active:
            c["id"] = f"TC{tc_counter:03d}"
            tc_counter += 1

        await _p(100, f"增量更新完成！有效用例 {len(all_active)} 条，废弃 {len(deprecated)} 条")
        logger.info(
            f"WebUI 增量更新: retained={len(retained)} new/updated={len(new_cases)} "
            f"deprecated={len(deprecated)}"
        )
        return {
            "new_cases":        new_cases,
            "retained_cases":   retained,
            "deprecated_cases": deprecated,
            "diff_summary":     diff_summary,
        }


case_generator = CaseGenerator()
