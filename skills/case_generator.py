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

from skills.step_hardener import harden_and_enrich


def _make_step_json(action: str, selector: str = "", value: str = "", description: str = "") -> dict:
    """构建结构化的步骤 JSON 对象（与 tools/action_schema.py 兼容）。"""
    return {
        "action": action,
        "selector": selector,
        "value": value,
        "description": description or f"{action} {selector}",
    }


class CaseGenerator:
    def __init__(self):
        self.priority_levels = ["P0", "P1", "P2"]

    # ==================================================================
    # 步骤文本 → 结构化 steps_json 解析器（不调 LLM，规则解析）
    # ==================================================================
    @staticmethod
    def parse_steps_to_json(steps_text: str, url: str = "") -> list:
        """
        将 AI 生成的文本步骤解析为执行器可用的结构化 steps_json。
        输入: "1. 找到用户名输入框（selector: #username），输入 'test@example.com'\n2. 点击登录按钮（selector: button.submit）"
        输出: [{"action":"fill","selector":"#username","value":"test@example.com","description":"输入用户名"}, ...]
        """
        import re as _re

        if not steps_text or not isinstance(steps_text, str):
            return []

        # ── 辅助：清理 nth-child 等脆弱选择器 ──
        def _clean_sel(sel: str) -> str:
            sel = (sel or "").strip()
            if not sel:
                return sel
            if ':nth-child(' in sel:
                logger.debug(f"丢弃含 nth-child 的选择器: {sel}")
                return ""
            return sel

        result = []
        # 按换行或数字编号拆分步骤
        raw_steps = _re.split(r'\n\s*(?=\d+[\.\、\)）]\s*)|(?<=\n)\s*(?=\d+[\.\、\)）])', steps_text)
        if len(raw_steps) <= 1:
            # 没有编号前缀，尝试按 \n 拆分
            raw_steps = [s.strip() for s in steps_text.split('\n') if s.strip()]

        for step_text in raw_steps:
            step_text = step_text.strip()
            if not step_text or len(step_text) < 3:
                continue
            # 去掉步骤编号前缀（1. / 1、 / 1) / Step 1: 等）
            step_text = _re.sub(r'^(?:步骤?\s*)?\d+\s*[\.\、\)：:\-]\s*', '', step_text).strip()

            # 提取 selector
            sel_match = _re.search(r'selector[\s:：]*([^\s,，)\n\]]+)', step_text, _re.IGNORECASE)
            selector = sel_match.group(1).strip().rstrip(')）') if sel_match else ""
            # 清理常见尾部符号
            selector = _re.sub(r'[)）\]】]+$', '', selector)
            # 过滤 nth-child 等脆弱选择器
            selector = _clean_sel(selector)

            # 提取引号中的值
            val_match = _re.search(r"[''「「\"\"]([^''」」\"\"]+)[''」」\"\"]", step_text)
            value = val_match.group(1) if val_match else ""
            if not value:
                # 尝试匹配 "输入 xxx" 后面的内容（无引号）
                m2 = _re.search(r'输入\s+([^\s,，。；;，]+(?:[\.\-\w]+)?)', step_text)
                if m2 and m2.group(1) not in ('数据', '内容', '文本', '信息'):
                    value = m2.group(1)

            # ── 动作判定 ──
            text_lower = step_text.lower()

            if any(kw in text_lower for kw in ['导航', '跳转', '打开页面', '进入', 'navigate', 'goto']):
                # 提取 URL
                url_m = _re.search(r'(https?://[^\s,，。]+)', step_text)
                action = "navigate"
                the_url = url_m.group(1) if url_m else ""
                if not the_url and not selector:
                    continue
                result.append(_make_step_json(action, selector or the_url, value or the_url,
                                               f"导航到 {the_url or selector}"))

            elif any(kw in text_lower for kw in ['输入', '填写', '键入', 'fill', 'type', 'enter']):
                if not selector:
                    # 没有 selector 但有输入操作 → 尝试从上下文推断
                    prev_sel = _re.search(r'(?:找到|定位|选择|点击)\s*[^,，。]*(?:selector[:\s]*)?([^\s,，)]+)', step_text)
                    if prev_sel:
                        selector = prev_sel.group(1)
                if selector:
                    result.append(_make_step_json("fill", selector, value or "test",
                                                   f"输入 {value or selector}"))
                else:
                    # 无 selector 的输入不可执行，标记待补充
                    result.append(_make_step_json("fill", "", value or "test",
                                                   f"[需补充selector] 输入 {value or ''}"))

            elif any(kw in text_lower for kw in ['点击', '单击', '按下', 'click', 'press', 'tap']):
                if selector:
                    result.append(_make_step_json("click", selector, "",
                                                   f"点击 {selector}"))
                else:
                    # 尝试提取点击目标
                    click_target = _re.search(r'(?:点击|单击|按下)\s*[""「「]?([^""」」，,，。；;\n]+)', step_text)
                    desc = click_target.group(1) if click_target else ""
                    result.append(_make_step_json("click", "", "", f"[需补充selector] 点击 {desc or '目标元素'}"))

            elif any(kw in text_lower for kw in ['选择', '下拉', 'select', 'pick']):
                result.append(_make_step_json("select", selector, value or "1",
                                               f"选择 {value or selector}"))

            elif any(kw in text_lower for kw in ['悬停', 'hover', 'mouseover']):
                result.append(_make_step_json("hover", selector, "",
                                               f"悬停 {selector}"))

            elif any(kw in text_lower for kw in ['断言', '验证', '检查', '确认', 'assert', 'verify', 'check', 'expect']):
                if any(kw in text_lower for kw in ['包含', 'contain', '显示', 'display', '出现', 'visible']):
                    result.append(_make_step_json("assert_text", selector, value or "",
                                                   f"验证 {selector} 包含 {value or '预期内容'}"))
                elif any(kw in text_lower for kw in ['可见', 'visible']):
                    result.append(_make_step_json("assert_visible", selector, "",
                                                   f"验证 {selector} 可见"))
                elif any(kw in text_lower for kw in ['url', '地址', '跳转', '页面']):
                    result.append(_make_step_json("assert_url", "", value or "",
                                                   f"验证 URL 包含 {value or '预期路径'}"))
                else:
                    result.append(_make_step_json("assert_text", selector, value or "",
                                                   f"验证 {selector or '页面'} {value or '符合预期'}"))

            elif any(kw in text_lower for kw in ['等待', 'wait', 'sleep', '延迟']):
                val = value if value else "1"
                try:
                    float(val)
                except ValueError:
                    val = "1"
                result.append(_make_step_json("wait", "", val, f"等待 {val} 秒"))

            elif any(kw in text_lower for kw in ['截图', 'screenshot']):
                result.append(_make_step_json("screenshot", "", "", "截图"))

            elif selector:
                # 有 selector 但没有明确动作 → 默认 click
                result.append(_make_step_json("click", selector, "", f"操作 {selector}"))

        return result

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
        user_prompt: str = "",
        focus_modules: List[str] = None,
        target_count: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        生成测试用例。

        新增参数：
          user_prompt    — 用户自然语言描述（测试重点、背景、特殊要求）
          focus_modules  — 限定生成范围的模块名列表，为空则全页面生成
          target_count   — 期望生成的用例总数（0 表示不限制，由 LLM 自行决定）
        """
        focus_modules = focus_modules or []
        _hint = ""
        if user_prompt:
            _hint += f"\n【用户补充说明】{user_prompt}"
        if focus_modules:
            _hint += f"\n【仅生成以下模块的用例】{'、'.join(focus_modules)}"
        if target_count > 0:
            _hint += f"\n【期望用例总数】约 {target_count} 条（按模块均匀分配）"
        if _hint:
            logger.info(f"[generate_cases] 用户定制提示:{_hint.strip()}")

        logger.info("Generating test cases via staged LLM...")

        # 累计已生成的用例数，用于进度推送
        _case_count = {"n": 0}

        async def _p(pct: int, stage: str, case_count: int = None):
            if case_count is not None:
                _case_count["n"] = case_count
            if progress_cb:
                result = progress_cb(pct, stage, case_count=_case_count.get("n", 0))
                import inspect as _ins
                if _ins.isawaitable(result):
                    await result

        await _p(3, "准备生成...")

        try:
            cases = await self._generate_staged(
                url, page_elements, document_data, _p,
                user_prompt=_hint,
                focus_modules=focus_modules,
                target_count=target_count,
            )
            if cases:
                # ── 为每条用例解析 steps → steps_json ──
                for case in cases:
                    if not case.get("steps_json"):
                        steps_text = case.get("steps", "")
                        if steps_text:
                            case["steps_json"] = self.parse_steps_to_json(steps_text, url)
                        else:
                            case["steps_json"] = []

                # ── 健壮化：为 AI 生成的 steps_json 补齐候选 selector 和评级 ──
                await _p(96, "正在健壮化用例 selector...")
                hardened_count = 0
                for case in cases:
                    if case.get("steps_json"):
                        try:
                            case["steps_json"] = await harden_and_enrich(case["steps_json"], use_ai=True)
                            hardened_count += 1
                        except Exception as e:
                            logger.warning(f"用例「{case.get('name','')}」健壮化失败: {e}")
                if hardened_count:
                    logger.info(f"健壮化完成: {hardened_count}/{len(cases)} 条用例")

                await _p(100, f"生成完成，共 {len(cases)} 条用例")
                logger.info(f"Staged LLM generated {len(cases)} test cases")
                return cases
            # LLM 返回了0条：尝试文档驱动兜底
            logger.warning("LLM 生成 0 条，尝试文档驱动兜底生成")
            await _p(70, "正在使用需求文档补充生成...")
            doc_cases = await self._generate_doc_driven(url, document_data, _p)
            if doc_cases:
                # ── steps → steps_json ──
                for c in doc_cases:
                    if not c.get("steps_json"):
                        c["steps_json"] = self.parse_steps_to_json(c.get("steps", ""), url)
                # ── 健壮化 ──
                await _p(96, "正在健壮化用例 selector...")
                for c in doc_cases:
                    if c.get("steps_json"):
                        try:
                            c["steps_json"] = await harden_and_enrich(c["steps_json"], use_ai=True)
                        except Exception as e:
                            logger.warning(f"用例「{c.get('name','')}」健壮化失败: {e}")
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
        # ── steps → steps_json ──
        for c in cases:
            if not c.get("steps_json"):
                c["steps_json"] = self.parse_steps_to_json(c.get("steps", ""), url)
        # ── 健壮化 ──
        await _p(96, "正在健壮化用例 selector...")
        has_steps = [c for c in cases if c.get("steps_json")]
        if has_steps:
            for c in has_steps:
                try:
                    c["steps_json"] = await harden_and_enrich(c["steps_json"], use_ai=True)
                except Exception as e:
                    logger.warning(f"用例「{c.get('name','')}」健壮化失败: {e}")
        # ── 无特定元素可生成时，返回页面级基础用例 ──
        if not cases:
            cases = self._generate_page_level_cases(url, page_elements)
            await _p(100, f"页面级基础生成完成，共 {len(cases)} 条用例（页面交互元素较少，建议上传需求文档获得更完整的用例）")
            logger.info(f"Page-level fallback generated {len(cases)} test cases")
        else:
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
        user_prompt: str = "",
        focus_modules: List[str] = None,
        target_count: int = 0,
    ) -> List[Dict[str, Any]]:
        focus_modules = focus_modules or []
        index_map, elements_summary = self._build_indexed_elements(page_elements)
        doc_context = self._build_doc_context(document_data)
        # 将用户提示追加到 doc_context，让各子调用都能感知
        if user_prompt:
            doc_context = doc_context + "\n" + user_prompt if doc_context else user_prompt

        # 页面元素太少（≤3个）时，跳过元素分析，直接以文档为主生成
        FEW_ELEMENTS = len(page_elements) <= 3
        if FEW_ELEMENTS:
            logger.info(f"页面元素太少({len(page_elements)}个)，以需求文档为主生成用例")
            await _p(15, f"页面元素较少，以需求文档为主生成用例...")
            return await self._generate_doc_driven(url, document_data, _p)

        # ── 文档中有详细用例说明？优先提取映射为可执行用例 ──
        doc_cases_mapped = []
        if not focus_modules and document_data and self._is_doc_test_case_rich(document_data):
            logger.info("检测到文档包含详细用例说明，优先从文档提取映射...")
            await _p(6, "检测到文档包含用例说明，正在提取并映射为可执行用例...")
            try:
                doc_cases_mapped = await self._extract_and_map_doc_cases(
                    url, page_elements, document_data, _p
                )
            except Exception as e:
                logger.warning(f"文档用例提取映射失败，回退到模块分析: {e}")

        await _p(max(8, 65 if doc_cases_mapped else 8), "正在分析页面结构...")
        modules = await self._extract_page_modules(elements_summary, doc_context)

        if not modules:
            logger.warning("Module extraction returned empty, falling back to single-call LLM")
            await _p(20, "正在调用 AI 整体生成用例...")
            return await self._generate_single_call(url, elements_summary, doc_context)

        # ── 按用户指定模块过滤 ──
        if focus_modules:
            focus_lower = {f.strip().lower() for f in focus_modules}
            filtered = [m for m in modules if m.get("name", "").strip().lower() in focus_lower]
            if filtered:
                logger.info(f"按用户指定过滤模块: {[m['name'] for m in filtered]}")
                modules = filtered
            else:
                # 模糊匹配
                filtered = [
                    m for m in modules
                    if any(fl in m.get("name", "").lower() or m.get("name", "").lower() in fl
                           for fl in focus_lower)
                ]
                if filtered:
                    logger.info(f"模糊匹配指定模块: {[m['name'] for m in filtered]}")
                    modules = filtered
                else:
                    logger.warning(f"指定模块 {focus_modules} 在页面中未找到，将生成全部模块")

        logger.info(f"Extracted {len(modules)} modules: {[m['name'] for m in modules]}")
        await _p(20, f"识别到 {len(modules)} 个功能模块，开始并行生成...")

        # 每个模块的期望用例数
        # - 不设硬下限，完全遵从用户意图（少于1条时退化为0，让LLM自行决定）
        per_module_count = round(target_count / len(modules)) if target_count > 0 else 0

        sem = asyncio.Semaphore(2)
        counter = {"done": 0, "total": len(modules)}
        _cases_so_far = []   # 共享列表，追踪已生成的用例

        def _count_done():
            return len(_cases_so_far)

        async def _gen_module(idx: int, module: Dict) -> List[Dict]:
            async with sem:
                module_name = module.get("name", f"模块{idx + 1}")
                # 优先从 element_ids 取真实元素；兜底兼容旧格式 elements（字符串列表）
                element_ids = module.get("element_ids") or []
                if element_ids:
                    real_elements = self._resolve_module_elements(element_ids, index_map)
                else:
                    # 兜底：旧格式直接用字符串当 selector
                    real_elements = [{"selector": s, "text": "", "tag": "", "placeholder": "", "name": ""}
                                     for s in (module.get("elements") or []) if isinstance(s, str)]
                try:
                    cases = await self._generate_cases_for_module(
                        url, module_name, real_elements, doc_context,
                        per_module_count=per_module_count,
                    )
                    _cases_so_far.extend(cases)
                    counter["done"] += 1
                    pct = 20 + int(counter["done"] / counter["total"] * 72)
                    await _p(pct, f"模块「{module_name}」完成 ({counter['done']}/{counter['total']})", _count_done())
                    logger.info(f"  [{counter['done']}/{counter['total']}] 「{module_name}」生成 {len(cases)} 条")
                    return cases
                except Exception as e:
                    logger.warning(f"  模块「{module_name}」生成失败: {e}")
                    return []

        all_results = await asyncio.gather(*[_gen_module(i, m) for i, m in enumerate(modules)])

        all_cases: List[Dict] = []
        for cases in all_results:
            all_cases.extend(cases)

        # ── 合并文档映射用例（文档用例优先，模块用例补充未覆盖的元素）──
        if doc_cases_mapped:
            doc_names = {c.get("name", "").strip().lower() for c in doc_cases_mapped}
            # 去重：模块用例中与文档用例重名的跳过
            module_only = []
            for c in all_cases:
                name_lower = c.get("name", "").strip().lower()
                mod_lower = c.get("module", "").strip().lower()
                if name_lower in doc_names:
                    continue  # 完全重名，跳过
                # 同模块检查：如果该模块已有多条文档用例，模块用例可能重复
                is_dup = False
                for dn in doc_names:
                    if len(dn) > 8 and dn in name_lower:
                        is_dup = True
                        break
                if not is_dup:
                    module_only.append(c)
            # doc cases 在前，模块补充在后
            all_cases = doc_cases_mapped + module_only
            logger.info(
                f"合并: {len(doc_cases_mapped)} 文档映射 + {len(module_only)} 模块补充"
                f" = {len(all_cases)} 条"
            )

        # ── 跨模块端到端流程测试（target_count > 0 时不额外追加，避免超出数量）──
        if len(modules) >= 2 and not doc_cases_mapped and target_count == 0:
            await _p(93, "正在生成跨模块端到端流程用例...")
            try:
                flow_cases = await self._generate_flow_tests(
                    url, modules, elements_summary, doc_context, all_cases
                )
                all_cases.extend(flow_cases)
                await _p(95, f"端到端流程用例生成完成 (+{len(flow_cases)} 条)", len(all_cases))
            except Exception as e:
                logger.warning(f"Cross-module flow test generation failed: {e}")
        elif doc_cases_mapped:
            await _p(95, f"生成完成：{len(doc_cases_mapped)} 条文档映射 + {len(all_cases) - len(doc_cases_mapped)} 条模块补充，共 {len(all_cases)} 条")
        else:
            await _p(95, f"生成完成，共 {len(all_cases)} 条用例")

        # ── 最终按 target_count 截断（精确控制总数） ──────────────────────────────
        if target_count > 0 and len(all_cases) > target_count:
            # 优先保留高优先级用例：P0 > P1 > P2
            _prio = {"P0": 0, "P1": 1, "P2": 2}
            all_cases.sort(key=lambda c: _prio.get(c.get("priority", "P2"), 2))
            logger.info(f"按 target_count={target_count} 截断：{len(all_cases)} → {target_count} 条")
            all_cases = all_cases[:target_count]
            await _p(95, f"已按设定截断至 {target_count} 条（P0 优先保留）", len(all_cases))

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
            "You are a senior UI analyst specializing in test case design. "
            "Analyze page elements (each prefixed with a numeric ID like [001]) and group them into logical functional modules. "
            "Return ONLY the numeric IDs — never invent new selectors. "
            "Output ONLY valid JSON. No markdown, no explanation."
        )
        prompt = f"""分析以下页面元素（每个元素带有编号如 [001]），归纳为 3-8 个逻辑功能模块。

页面元素（带编号）：
{elements_summary}

{doc_context}

【分组原则】
1. 每个模块聚焦一个独立功能（如登录、搜索、表单提交、导航）
2. 每个元素只能归入一个模块
3. 关联紧密的元素归入同一模块（如"用户名+密码+登录按钮" → 登录模块）
4. elements 数组里填元素编号（数字），不要填 selector 字符串

只输出纯JSON：
{{
  "modules": [
    {{
      "name": "登录模块",
      "element_ids": [1, 2, 5]
    }},
    {{
      "name": "搜索模块",
      "element_ids": [8, 9]
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
        module_elements: List,           # 可以是真实元素 dict 列表，也兼容旧格式字符串列表
        doc_context: str,
        per_module_count: int = 0,
    ) -> List[Dict]:
        system_prompt = (
            "You are a senior QA automation engineer. "
            "Generate thorough, executable UI automation test cases for Playwright/Selenium. "
            "Cover happy paths, validation errors, edge cases, and boundary conditions. "
            "Output ONLY a single valid JSON object. No markdown, no explanation."
        )

        # ── 构建本模块真实元素的展示文本 ──────────────────────────────
        elem_lines = []
        for e in (module_elements or []):
            if isinstance(e, dict):
                sel   = e.get("selector", "").strip()
                text  = (e.get("text", "") or "").strip()[:40]
                ph    = (e.get("placeholder", "") or "").strip()[:40]
                name  = (e.get("name", "") or "").strip()
                tag   = e.get("tag", "")
                typ   = e.get("type", "")
                label = (e.get("label", "") or "").strip()[:40]

                # 构建人类可读的描述 + 必须使用的真实 selector
                desc_parts = []
                if text:
                    desc_parts.append(f"文本={text!r}")
                if ph:
                    desc_parts.append(f"placeholder={ph!r}")
                if label:
                    desc_parts.append(f"label={label!r}")
                if name:
                    desc_parts.append(f"name={name!r}")
                desc = "、".join(desc_parts) if desc_parts else "（无语义描述）"

                # 构建候选 selector（优先真实 selector，补充 :has-text 作为备选）
                sel_candidates = []
                if sel and sel not in ("a", "button", "input", "select", "textarea", ""):
                    sel_candidates.append(sel)
                if text and tag in ("button", "a"):
                    sel_candidates.append(f'{tag}:has-text("{text[:20]}")')
                if ph:
                    sel_candidates.append(f'{tag or "input"}[placeholder="{ph}"]')
                if name:
                    sel_candidates.append(f'[name="{name}"]')

                if sel_candidates:
                    elem_lines.append(
                        f"  • {tag}[{typ}] {desc} → 【真实selector】{sel_candidates[0]}"
                        + (f"  备选: {sel_candidates[1]}" if len(sel_candidates) > 1 else "")
                    )
            else:
                # 旧格式：直接是 selector 字符串
                if str(e).strip():
                    elem_lines.append(f"  • {e}")

        if elem_lines:
            selectors_str = "\n".join(elem_lines)
        else:
            selectors_str = "  （未找到具体元素，请根据页面 URL 和文档推断）"

        # 动态用例数量要求
        count_hint = (
            f"- 【严格限制】只生成 {per_module_count} 条用例，不多不少"
            if per_module_count > 0
            else "- 生成 8-12 条用例，覆盖以下类型："
        )

        prompt = f"""为页面模块「{module_name}」生成 UI 自动化测试用例。

目标页面：{url or '（未提供）'}
本模块真实页面元素（selector 来自实际页面抓取，必须直接使用，不得修改或替换）：
{selectors_str}

{doc_context}

【Selector 使用规则（必须严格遵守）】
- 步骤中的 selector 必须直接复制上方"【真实selector】"字段的值，不得自行编造
- 如果一个步骤的目标元素在上方列表中有真实 selector，必须用那个，例如：
    input[name="keyword"] → 直接写 selector: input[name="keyword"]
    a.header2018-unloginlink.header2018-unloginlink1 → 直接写这个完整 selector
- 断言步骤（验证文字/可见性）可以用 :has-text() 构造，如 p:has-text("错误提示")
- 严禁使用 :nth-child、伪造的 #id、或任何未在上方列表中出现的 selector

【生成要求】
{count_hint}
  * P0-正向流程：标准操作路径，验证核心功能可用（2-3条）
  * P0-必填校验：空值/缺失必填项时的错误提示（2-3条）
  * P1-格式校验：非法格式输入（如邮箱缺@、手机号位数不足）（2-3条）
  * P1-边界值：最大/最小长度、特殊字符、空格处理（2-3条）
  * P2-异常场景：网络超时、重复提交、并发操作（1-2条）
- 每个步骤格式：操作描述（selector: 真实selector值），示例：
  "1. 找到关键词输入框（selector: input[name='keyword']），输入 '会计'
   2. 点击搜索按钮（selector: input.header2018-submit）
   3. 验证搜索结果出现（selector: .search-result-item）"
- 校验/边界值用例也必须带 selector，不可只写"输入超长字符串"
- 预期结果必须可自动化断言
- 只针对「{module_name}」模块

只输出纯JSON：
{{
  "cases": [
    {{
      "name": "搜索-关键词搜索-返回结果",
      "module": "{module_name}",
      "priority": "P0",
      "preconditions": "用户在首页",
      "steps": "1. 找到搜索框（selector: input[name=\\"keyword\\"]），输入 '会计'\\n2. 点击搜索按钮（selector: input.header2018-submit）\\n3. 验证搜索结果列表出现（selector: .result-list）",
      "expected_results": "页面显示与'会计'相关的课程/讲师列表",
      "element_selector": "input[name=\\"keyword\\"]"
    }}
  ]
}}"""
        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
            if not raw.strip().startswith("{") and not raw.strip().startswith("["):
                logger.warning(f"模块「{module_name}」LLM 返回非 JSON 内容: {raw[:200]}")
                return []
            # 复用 ai_case_generator 的 JSON 修复工具
            from skills.ai_case_generator import _sanitize_json_string, _repair_truncated_json
            raw = _sanitize_json_string(raw)   # 修复未转义的换行/引号
            raw = _repair_truncated_json(raw)  # 修复截断的 JSON
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e2:
                logger.warning(f"模块「{module_name}」LLM 调用失败: {e2}")
                return []
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
    # 跨模块端到端流程测试
    # ------------------------------------------------------------------
    async def _generate_flow_tests(
        self,
        url: str,
        modules: List[Dict],
        elements_summary: str,
        doc_context: str,
        existing_cases: List[Dict],
    ) -> List[Dict]:
        """生成跨模块的用户端到端流程测试，补充模块间的集成覆盖。"""
        module_names = [m.get("name", "") for m in modules[:6]]
        existing_summary = "\n".join(
            f"- [{c.get('module','')}] {c.get('name','')} ({c.get('priority','')})"
            for c in existing_cases[:30]
        )
        system_prompt = (
            "You are a senior QA architect. Design end-to-end user journey test cases "
            "that span multiple UI modules. Focus on real user workflows. "
            "Output ONLY a single valid JSON object. No markdown, no explanation."
        )
        prompt = f"""基于以下页面信息，设计 3-6 条跨模块端到端流程测试用例。

目标页面：{url or '（未提供）'}
已识别模块：{', '.join(module_names)}

页面元素摘要：
{elements_summary}

{doc_context}

已有模块级用例（避免重复）：
{existing_summary}

【要求】
- 模拟真实用户完整操作路径，跨越 2-4 个模块
- 覆盖典型业务场景（如：注册→登录→下单→支付）
- 每个步骤含 selector 和操作描述
- 预期结果可自动化断言

只输出纯JSON：
{{
  "cases": [
    {{
      "name": "用户注册到下单完整流程",
      "module": "端到端流程",
      "priority": "P0",
      "preconditions": "用户未注册，购物车为空",
      "steps": "1. 点击注册链接...\\n2. 填写注册表单...\\n...",
      "expected_results": "订单创建成功，跳转到订单确认页",
      "element_selector": ""
    }}
  ]
}}"""
        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
            if not raw.strip().startswith("{") and not raw.strip().startswith("["):
                logger.warning(f"Flow test LLM returned non-JSON: {raw[:200]}")
                return []
            from skills.ai_case_generator import _sanitize_json_string, _repair_truncated_json
            raw = _sanitize_json_string(raw)
            raw = _repair_truncated_json(raw)
            data = json.loads(raw)
            cases = data.get("cases", [])
            for c in cases:
                c.setdefault("module", "端到端流程")
                c.setdefault("priority", "P0")
                c.setdefault("preconditions", "")
                c.setdefault("expected_results", "")
                c.setdefault("element_selector", "")
            logger.info(f"Generated {len(cases)} end-to-end flow test cases")
            return cases
        except Exception as e:
            logger.warning(f"Flow test generation failed: {e}")
            return []

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

    # ------------------------------------------------------------------
    # 文档用例提取 + selector 映射（文档中包含详细用例说明时的主路径）
    # ------------------------------------------------------------------
    @staticmethod
    def _is_doc_test_case_rich(document_data: Optional[Dict[str, Any]]) -> bool:
        """检测文档是否包含详细的用例说明（而非纯需求描述）。"""
        if not document_data:
            return False
        content = document_data.get("content", "") or ""
        structured = document_data.get("structured", {}) or {}
        pts = structured.get("functional_points", []) or []
        full_text = content + "\n".join(str(p) for p in pts)
        if len(full_text) < 100:
            return False
        import re
        indicators = [
            r'(?:步骤|操作步骤|测试步骤|Steps?)[：:]\s*\d+\.',
            r'(?:预期|预期结果|期望|Expect(?:ed)?\s*Result)[：:]',
            r'(?:前置|前置条件|前提|Precondition)[：:]',
            r'(?:优先级|Priority|P0|P1|P2)',
            r'(?:用例|测试用例|Test\s*Case|TC\d+)',
            r'\n\s*(?:P0|P1|P2)\s*[：:\-]',
        ]
        matches = sum(1 for pat in indicators if re.search(pat, full_text, re.IGNORECASE))
        return matches >= 2

    async def _extract_and_map_doc_cases(
        self,
        url: str,
        page_elements: List[Dict[str, Any]],
        document_data: Dict[str, Any],
        _p: Callable,
    ) -> List[Dict[str, Any]]:
        """两步流水线：提取文档用例 → 逐批映射 selector → 可执行用例。"""
        elements_summary = self._build_elements_summary(page_elements)
        doc_text = document_data.get("content", "") or ""
        structured = document_data.get("structured", {}) or {}
        pts = structured.get("functional_points", []) or []
        if not doc_text and pts:
            doc_text = "\n".join(str(p) for p in pts)

        # Step 1: 从文档提取用例结构
        await _p(8, "正在从文档中提取用例...")
        system_prompt = (
            "You are a senior QA engineer. Extract all test cases from the document. "
            "Output ONLY a valid JSON array. No markdown, no explanation, no refusal."
        )
        prompt = f"""从以下需求文档/用例说明中提取所有测试用例。每个用例一个独立条目。

目标页面 URL：{url or '（未提供）'}

文档内容（用例说明）：
---
{doc_text[:12000]}
---

【提取规则】
1. 保留文档中原有的用例名称、模块归属、优先级（P0/P1/P2）
2. 保留完整的操作步骤和预期结果描述
3. 如果文档有前置条件也保留
4. 如果原文没有拆分模块，根据用例内容推断所属模块
5. 如果原文没有标记优先级，根据场景重要性推断（核心流程=P0，校验场景=P1，边界=P2）

只输出纯JSON数组：
[
  {{
    "name": "模块-用例名称（保留原文描述）",
    "module": "所属功能模块",
    "priority": "P0",
    "preconditions": "前置条件",
    "steps": "1. 步骤一\\n2. 步骤二",
    "expected_results": "预期结果描述"
  }}
]"""
        extracted = []
        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=120)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1].strip()
            if not raw.startswith("[") and not raw.startswith("{"):
                logger.warning(f"Doc case extraction returned non-JSON: {raw[:200]}")
                return []
            data = json.loads(raw)
            extracted = data if isinstance(data, list) else data.get("cases", data.get("test_cases", []))
        except Exception as e:
            logger.warning(f"Document case extraction failed: {e}")
            return []

        if not extracted:
            logger.info("No test cases extracted from document")
            return []

        await _p(15, f"从文档提取到 {len(extracted)} 条用例，正在映射页面元素...")

        # Step 2: 分批复核 — 为每批用例补齐 selector
        mapped_cases = []
        batch_size = 6
        total_batches = (len(extracted) + batch_size - 1) // batch_size
        for batch_idx in range(total_batches):
            batch = extracted[batch_idx * batch_size : (batch_idx + 1) * batch_size]
            pct = 15 + int((batch_idx + 1) / max(total_batches, 1) * 50)
            await _p(pct, f"正在映射页面元素 ({batch_idx + 1}/{total_batches})...")

            map_system = (
                "You are a Playwright/Selenium automation engineer. "
                "Given test cases and available page elements, fill in the correct selectors. "
                "Output ONLY a valid JSON array. No markdown, no explanation."
            )
            map_prompt = f"""为以下测试用例补齐页面元素 selector。每个步骤中涉及的元素都要标注 selector。

可用页面元素（含正确 selector）：
{elements_summary[:2000]}

待映射的用例：
{json.dumps(batch, ensure_ascii=False, indent=2)}

【映射规则】
1. 每个步骤中提到 UI 元素的地方，在步骤描述末尾追加 `(selector: 实际selector)`
2. selector 必须从「可用页面元素」中选取，不要编造
3. 如果页面元素中没有完全匹配的，选功能最接近的
4. 如果完全没有对应元素，保留原步骤不添加 selector，在 element_selector 字段标注需要补充的元素关键词
5. 保持步骤编号和原有描述不变

输出格式（纯JSON数组）：
[
  {{
    "name": "原用例名称",
    "module": "原模块",
    "priority": "P0",
    "preconditions": "原前置条件",
    "steps": "1. 步骤描述 (selector: #xxx)\\n2. 步骤描述 (selector: button.yyy)",
    "expected_results": "预期结果",
    "element_selector": "主元素 selector 或 需要补充的元素关键词"
  }}
]"""
            try:
                raw = await self._run_claude_subprocess(map_system, map_prompt, timeout_secs=90)
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```", 2)[1].strip()
                if not raw.startswith("[") and not raw.startswith("{"):
                    logger.warning(f"Selector mapping batch {batch_idx+1} returned non-JSON")
                    for item in batch:
                        item["element_selector"] = item.get("element_selector", "")
                    mapped_cases.extend(batch)
                    continue
                data = json.loads(raw)
                batch_mapped = data if isinstance(data, list) else data.get("cases", [])
                for item in batch_mapped:
                    item.setdefault("element_selector", "")
                    steps = item.get("steps", "")
                    if isinstance(steps, list):
                        import re as _re_m
                        item["steps"] = "\n".join(_re_m.sub(r'^\s*\d+\.\s*', '', str(s)) for s in steps)
                    elif not isinstance(steps, str):
                        item["steps"] = str(steps)
                mapped_cases.extend(batch_mapped)
                logger.info(f"  Batch {batch_idx+1}/{total_batches}: mapped {len(batch_mapped)} cases")
            except Exception as e:
                logger.warning(f"Selector mapping batch {batch_idx+1} failed: {e}")
                for item in batch:
                    item["element_selector"] = item.get("element_selector", "")
                mapped_cases.extend(batch)

        await _p(65, f"文档用例映射完成，共 {len(mapped_cases)} 条")
        return mapped_cases

    async def _generate_single_call(
        self, url: str, elements_summary: str, doc_context: str
    ) -> List[Dict]:
        system_prompt = (
            "You are a senior QA automation engineer. "
            "Generate thorough, executable UI automation test cases for Playwright/Selenium. "
            "Cover happy paths, validations, edge cases, and error scenarios. "
            "Output ONLY a single valid JSON object. No markdown, no explanation."
        )
        prompt = f"""根据以下页面结构生成 UI 自动化测试用例（总量不超过 30 条，覆盖所有优先级）。

目标页面：{url or '（未提供）'}
页面元素：
{elements_summary}

{doc_context}

【覆盖要求】
- P0 正向流程 40%（核心功能可用）
- P1 校验/边界 40%（格式校验、边界值、必填校验）
- P2 异常/兼容 20%（异常输入、超时、并发）

步骤含具体 selector 和测试数据，预期结果可自动化断言。
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
                result = progress_cb(pct, stage)
                import inspect as _ins
                if _ins.isawaitable(result):
                    await result

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
        _opt_cases_so_far = []   # 共享追踪

        async def _opt_module(module_name: str) -> List[Dict]:
            async with sem:
                existing = modules[module_name]
                try:
                    new_cases = await self._optimize_one_module(
                        module_name, existing, elements_summary, doc_context
                    )
                    counter["done"] += 1
                    _opt_cases_so_far.extend(new_cases)
                    pct = 10 + int(counter["done"] / counter["total"] * 80)
                    await _p(pct, f"模块「{module_name}」优化完成 (+{len(new_cases)}) ({counter['done']}/{counter['total']})", len(_opt_cases_so_far))
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
    # 用例自我修正：分析失败用例，AI 修复 selector/步骤
    # ==================================================================
    async def self_correct_cases(
        self,
        failed_cases: List[Dict[str, Any]],
        page_elements: List[Dict[str, Any]],
        url: str,
        progress_cb: Optional[Callable] = None,
    ) -> List[Dict[str, Any]]:
        """分析执行失败的用例，由 AI 修正 selector 和步骤缺陷后返回。"""

        async def _p(pct: int, stage: str, case_count: int = 0):
            if progress_cb:
                result = progress_cb(pct, stage, case_count)
                import inspect as _ins
                if _ins.isawaitable(result):
                    await result

        await _p(5, "正在分析失败用例...")
        elements_summary = self._build_elements_summary(page_elements)
        # 按错误类型分组
        by_error = {}
        for fc in failed_cases:
            err = fc.get("error_message", "") or "未知错误"
            key = "selector not found" if any(kw in err.lower() for kw in ["selector", "element not found", "locator", "timeout"]) else "other"
            by_error.setdefault(key, []).append(fc)

        corrected: List[Dict] = []
        total = len(failed_cases)
        done = 0

        # ── Selector 类错误：修正 selector ──
        selector_fails = by_error.get("selector not found", [])
        if selector_fails:
            await _p(10, f"正在修正 {len(selector_fails)} 个 selector 错误...")
            corr = await self._correct_selector_errors(selector_fails, elements_summary, url)
            corrected.extend(corr)
            done += len(selector_fails)
            await _p(10 + int(done / max(total, 1) * 50), f"Selector 修正完成 (+{len(corr)})")

        # ── 其他类错误：整体分析修复 ──
        other_fails = by_error.get("other", [])
        if other_fails:
            await _p(60, f"正在分析修正 {len(other_fails)} 个其他错误...")
            corr = await self._correct_other_errors(other_fails, elements_summary, url)
            corrected.extend(corr)
            done += len(other_fails)
            await _p(90, f"其他错误修正完成 (+{len(corr)})")

        await _p(100, f"用例修正完成，共修复 {len(corrected)} 条", 0)
        # ── steps → steps_json ──
        for c in corrected:
            steps_text = c.get("corrected_steps") or c.get("steps", "")
            c["steps_json"] = self.parse_steps_to_json(steps_text, url)
        return corrected

    async def _correct_selector_errors(
        self, failed: List[Dict], elements_summary: str, url: str
    ) -> List[Dict]:
        """专门修正 selector 找不到导致的失败。"""
        system_prompt = (
            "You are a Playwright/Selenium expert specializing in fixing broken selectors. "
            "Given a failed test case and available page elements, suggest the correct selector. "
            "Output ONLY a single valid JSON object. No markdown, no explanation."
        )
        failed_batch = []
        for f in failed[:8]:  # 每批最多 8 条
            failed_batch.append({
                "name": f.get("case_name", f.get("name", "")),
                "original_steps": f.get("steps", ""),
                "error_message": f.get("error_message", ""),
            })
        prompt = f"""以下测试用例因 selector 找不到而失败。请根据可用的页面元素修正它们的 selector。

目标页面：{url}

可用页面元素（含正确 selector）：
{elements_summary[:2000]}

失败的用例：
{json.dumps(failed_batch, ensure_ascii=False, indent=2)}

【修正要求】
1. 将原始步骤中的 selector 替换为页面元素中**最匹配的实际 selector**
2. 如果原始 selector 不存在于页面元素中，找功能最接近的替代 selector
3. 如果完全无法匹配，在 corrected_steps 中标注"// 需要人工确认: 原 selector 'xxx' 在页面中未找到"
4. 保持步骤结构和测试逻辑不变

只输出纯JSON：
{{
  "corrected_cases": [
    {{
      "name": "原始用例名称",
      "corrected_steps": "修正后的步骤（含正确selector）",
      "fix_note": "说明修改了什么",
      "confidence": "high | medium | low"
    }}
  ]
}}"""
        try:
            from skills.ai_case_generator import _sanitize_json_string
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=60)
            data = json.loads(_sanitize_json_string(raw))
            results = data.get("corrected_cases", [])
            for i, r in enumerate(results):
                if i < len(failed):
                    orig = failed[i]
                    orig_copy = dict(orig)
                    orig_copy["corrected_steps"] = r.get("corrected_steps", orig.get("steps", ""))
                    orig_copy["fix_note"] = r.get("fix_note", "")
                    orig_copy["confidence"] = r.get("confidence", "medium")
                    orig_copy["is_corrected"] = True
                results[i] = orig_copy
            return results
        except Exception as e:
            logger.warning(f"Selector correction failed: {e}")
            # 兜底：尝试基于页面元素的关键词匹配
            return self._selector_fallback(failed, elements_summary)

    def _selector_fallback(self, failed: List[Dict], elements_summary: str) -> List[Dict]:
        """关键词匹配兜底修正。"""
        corrected = []
        for f in failed:
            orig_steps = f.get("steps", "") or f.get("corrected_steps", "")
            new_steps = orig_steps
            import re
            all_selectors = re.findall(r'selector:\s*([^\s)\n]+)', orig_steps)
            replaced = 0
            for sel in all_selectors:
                # 尝试在元素摘要中找到相似 selector
                improved = self._fuzzy_match_selector(sel, elements_summary)
                if improved and improved != sel:
                    new_steps = new_steps.replace(sel, improved)
                    replaced += 1
            f_copy = dict(f)
            f_copy["corrected_steps"] = new_steps
            f_copy["fix_note"] = f"兜底规则匹配，替换 {replaced} 个 selector" if replaced else "无法自动匹配，需人工确认"
            f_copy["confidence"] = "low"
            f_copy["is_corrected"] = True
            corrected.append(f_copy)
        return corrected

    @staticmethod
    def _fuzzy_match_selector(original: str, elements_summary: str) -> Optional[str]:
        """简单的模糊 selector 匹配。"""
        import re
        canonical = re.sub(r'[.#\[\]\'"*=>~+\-]', ' ', original).strip().split()
        # 提取关键词（长度>=2的非纯数字）
        keywords = [w for w in canonical if len(w) >= 2 and not w.isdigit()]
        if not keywords:
            return None
        best_match = None
        best_score = 0
        for line in elements_summary.split("\n"):
            line_sel = re.search(r'selector=([^\s,)]+)', line)
            if not line_sel:
                continue
            cand = line_sel.group(1)
            score = sum(1 for kw in keywords if kw.lower() in cand.lower())
            if score > best_score:
                best_score = score
                best_match = cand
        if best_score >= max(1, len(keywords) * 0.5):
            return best_match
        return None

    async def _correct_other_errors(
        self, failed: List[Dict], elements_summary: str, url: str
    ) -> List[Dict]:
        """修正非 selector 类错误（断言失败、超时、逻辑错误等）。"""
        system_prompt = (
            "You are a senior QA automation engineer. "
            "Analyze failed test cases and fix issues in steps, assertions, or test logic. "
            "Output ONLY a single valid JSON object. No markdown, no explanation."
        )
        failed_batch = []
        for f in failed[:5]:
            failed_batch.append({
                "name": f.get("case_name", f.get("name", "")),
                "steps": f.get("steps", f.get("corrected_steps", "")),
                "error_message": f.get("error_message", ""),
                "expected_results": f.get("expected_results", ""),
            })
        prompt = f"""以下测试用例执行失败，请分析错误并修正。

目标页面：{url}

可用页面元素：
{elements_summary[:1500]}

失败的用例：
{json.dumps(failed_batch, ensure_ascii=False, indent=2)}

【修正策略】
- 超时错误 → 增加等待步骤或调整预期结果
- 断言失败 → 检查预期结果是否合理，必要时调整预期
- 逻辑错误 → 调整操作顺序或输入数据
- 未知错误 → 添加防御性步骤

只输出纯JSON：
{{
  "corrected_cases": [
    {{
      "name": "原始用例名称",
      "corrected_steps": "修正后的步骤",
      "expected_results": "修正后的预期结果",
      "fix_note": "说明修改了什么",
      "confidence": "high | medium | low"
    }}
  ]
}}"""
        try:
            from skills.ai_case_generator import _sanitize_json_string
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=60)
            data = json.loads(_sanitize_json_string(raw))
            results = data.get("corrected_cases", [])
            for i, r in enumerate(results):
                if i < len(failed):
                    orig = failed[i]
                    orig_copy = dict(orig)
                    orig_copy["corrected_steps"] = r.get("corrected_steps", orig.get("steps", ""))
                    orig_copy["expected_results"] = r.get("expected_results", orig.get("expected_results", ""))
                    orig_copy["fix_note"] = r.get("fix_note", "")
                    orig_copy["confidence"] = r.get("confidence", "medium")
                    orig_copy["is_corrected"] = True
                results[i] = orig_copy
            return results
        except Exception as e:
            logger.warning(f"Other error correction failed: {e}")
            return failed  # 返回原样

    # ==================================================================
    # 覆盖率补全：根据执行结果检测未覆盖元素，补充用例
    # ==================================================================
    async def fill_coverage_gaps(
        self,
        existing_cases: List[Dict[str, Any]],
        execution_results: List[Dict[str, Any]],
        page_elements: List[Dict[str, Any]],
        url: str,
        document_data: Optional[Dict[str, Any]] = None,
        progress_cb: Optional[Callable] = None,
    ) -> List[Dict[str, Any]]:
        """
        基于执行结果分析覆盖率缺口，针对未覆盖的页面元素生成补充用例。
        - 找到被0条用例触及的元素 → 补齐用例
        - 找到仅被1条用例触及的元素 → 建议加强
        """

        async def _p(pct: int, stage: str, case_count: int = 0):
            if progress_cb:
                result = progress_cb(pct, stage, case_count)
                import inspect as _ins
                if _ins.isawaitable(result):
                    await result

        await _p(5, "正在分析元素覆盖率...")

        # ── 1. 收集已有用例触及的元素 ──
        touched_selectors: Dict[str, int] = {}  # selector → 用例数
        for case in existing_cases:
            sel = case.get("element_selector", "")
            if sel:
                touched_selectors[sel] = touched_selectors.get(sel, 0) + 1
            # 也从步骤中提取 selector
            steps = case.get("steps", "") or case.get("corrected_steps", "")
            if steps:
                import re
                for s in re.findall(r'selector:\s*([^\s)\n]+)', steps):
                    touched_selectors[s] = touched_selectors.get(s, 0) + 1

        # ── 2. 分析页面元素中哪些未被覆盖 ──
        interactive_tags = {"input", "button", "a", "select", "textarea"}
        uncovered = []
        weak_covered = []
        for elem in page_elements[:200]:
            tag = elem.get("tag", "")
            if tag not in interactive_tags:
                continue
            sel = elem.get("selector", "") or elem.get("css_selector", "")
            if not sel:
                continue
            count = touched_selectors.get(sel, 0)
            if count == 0:
                elem_type = elem.get("type", "") or tag
                elem_text = elem.get("text", "") or elem.get("name", "") or elem.get("placeholder", "")
                uncovered.append({
                    "selector": sel,
                    "tag": tag,
                    "type": elem_type,
                    "label": (elem_text[:50] if elem_text else f"{tag}[{sel[:30]}]"),
                })
            elif count == 1:
                weak_covered.append(sel)

        logger.info(f"Coverage gap analysis: {len(uncovered)} uncovered, {len(weak_covered)} weak elements")

        if not uncovered:
            await _p(100, "所有元素已有覆盖，无需补充", len(existing_cases))
            return []

        await _p(10, f"发现 {len(uncovered)} 个未覆盖元素，正在生成补充用例...")

        # ── 3. 为未覆盖元素生成补充用例 ──
        doc_context = ""
        if document_data:
            reqs = document_data.get("requirements", "") or document_data.get("content", "")
            if reqs:
                doc_context = f"\n需求文档参考：\n{str(reqs)[:1500]}\n"

        system_prompt = (
            "You are a senior QA engineer. Generate focused test cases "
            "for uncovered page elements. Output ONLY valid JSON."
        )
        prompt = f"""以下页面元素**没有任何测试用例覆盖**，请为它们生成测试用例。

目标页面：{url or '（未提供）'}

未覆盖元素：
{json.dumps(uncovered[:30], ensure_ascii=False, indent=2)}

{doc_context}

【要求】
- 为每个元素生成 1-2 条用例（优先交互元素如 button/input/a）
- P0 优先：核心按钮（提交、确认、搜索）→ P0
- P1：表单输入框、链接 → P1
- 步骤含具体 selector
- 关联元素可合并（如"用户名+密码+登录按钮"）

只输出纯JSON：
{{
  "cases": [
    {{
      "name": "用例名称",
      "module": "补充覆盖",
      "priority": "P0",
      "preconditions": "前置条件",
      "steps": "1. 步骤一（selector: xxx）",
      "expected_results": "可断言预期结果",
      "element_selector": "主元素的 selector"
    }}
  ]
}}"""
        try:
            from skills.ai_case_generator import _sanitize_json_string
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
            data = json.loads(_sanitize_json_string(raw))
            new_cases = data.get("cases", [])
            for c in new_cases:
                c.setdefault("module", "补充覆盖")
                c.setdefault("priority", "P1")
                c.setdefault("preconditions", "")
                c.setdefault("expected_results", "")
                steps = c.get("steps", "")
                if isinstance(steps, list):
                    c["steps"] = "\n".join(f"{j + 1}. {s}" for j, s in enumerate(steps))
                elif not isinstance(steps, str):
                    c["steps"] = str(steps)
            await _p(100, f"补充覆盖完成，新增 {len(new_cases)} 条用例", len(existing_cases) + len(new_cases))
            return new_cases
        except Exception as e:
            logger.warning(f"Gap fill generation failed: {e}")
            return []

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
        """构建给 LLM 的元素摘要文本（无编号版，用于不需要回查的场合）。"""
        _, summary = self._build_indexed_elements(elements)
        return summary

    def _build_indexed_elements(
        self, elements: List[Dict[str, Any]]
    ) -> tuple:
        """
        构建带编号的元素列表，同时返回：
          index_map: {编号(int) -> 元素 dict}  — 用于模块分组后回查真实 selector
          summary:   str                        — 带编号的文本，传给 LLM

        只选取有意义的交互元素（有 selector 且不是裸 tag 的），避免给 LLM
        太多噪音，也避免 LLM 拿到裸 "a" / "button" 当作 selector 写进步骤。
        """
        if not elements:
            return {}, "（无页面元素数据）"

        interactive_tags = {"input", "button", "a", "select", "textarea"}

        # 过滤：保留交互元素，selector 不能是裸 tag（如 "a" "button"）
        bare_tags = {"a", "button", "input", "select", "textarea", "div", "span", ""}
        interactive = [
            e for e in elements
            if e.get("tag", "") in interactive_tags
            and (e.get("selector", "") or "") not in bare_tags
        ]
        # 没有 selector 的但有语义信息的也保留（后面可用 :has-text 补）
        interactive_no_sel = [
            e for e in elements
            if e.get("tag", "") in interactive_tags
            and (e.get("selector", "") or "") in bare_tags
            and ((e.get("text", "") or "").strip() or (e.get("placeholder", "") or "").strip())
        ]
        text_nodes = [
            e for e in elements
            if e.get("tag", "") not in interactive_tags and (e.get("text", "") or "").strip()
        ]

        selected = interactive[:120] + interactive_no_sel[:30] + text_nodes[:60]

        index_map: dict = {}
        lines: list = []
        for idx, elem in enumerate(selected, start=1):
            tag = elem.get("tag", "")
            typ = elem.get("type", "")
            text = (elem.get("text", "") or "").strip()[:40]
            placeholder = (elem.get("placeholder", "") or "").strip()[:40]
            label = (elem.get("label", "") or elem.get("aria_label", "") or "").strip()[:40]
            name = elem.get("name", "")
            selector = (elem.get("selector", "") or "").strip()

            # 构建给 LLM 的描述行（带编号）
            parts = [f"[{idx:03d}] <{tag}"]
            if typ:
                parts.append(f" type={typ}")
            if text:
                parts.append(f" text={text!r}")
            if placeholder:
                parts.append(f" placeholder={placeholder!r}")
            if label:
                parts.append(f" label={label!r}")
            if name:
                parts.append(f" name={name!r}")
            if selector:
                parts.append(f" selector={selector!r}")
            parts.append(">")
            lines.append("".join(parts))

            # 构建回查用的元素信息（含真实 selector 与语义）
            index_map[idx] = {
                "tag": tag,
                "type": typ,
                "text": text,
                "placeholder": placeholder,
                "label": label,
                "name": name,
                "selector": selector,
            }

        return index_map, "\n".join(lines)

    def _resolve_module_elements(
        self,
        element_indices: List,           # LLM 返回的编号列表（可能含字符串或整数）
        index_map: Dict[int, Dict],      # 编号→元素 dict
    ) -> List[Dict]:
        """
        根据 LLM 返回的编号列表，从 index_map 中取出真实元素信息。
        返回的每个元素 dict 包含 selector、text、tag 等真实字段。
        """
        result = []
        seen_sels = set()
        for raw in element_indices:
            try:
                idx = int(str(raw).strip())
            except (ValueError, TypeError):
                continue
            elem = index_map.get(idx)
            if not elem:
                continue
            sel = elem.get("selector", "")
            # 去重，且跳过无意义的裸 tag selector
            if sel and sel not in seen_sels:
                seen_sels.add(sel)
                result.append(elem)
        return result

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

    def _generate_page_level_cases(self, url: str, elements: List[Dict]) -> List[Dict]:
        """当页面交互元素极少时的最终兜底：生成页面级基础验证用例。"""
        from urllib.parse import urlparse
        cases = []
        domain = urlparse(url).netloc or "目标页面"
        page_name = domain.replace("www.", "").split(".")[0] or "目标页面"

        # 1. 页面可访问性验证
        cases.append({
            "name": f"{page_name} 页面可访问性验证",
            "module": "页面验证",
            "priority": "P0",
            "preconditions": "网络连接正常",
            "steps": f"1. 访问 {url}\n2. 等待页面加载完成\n3. 检查 HTTP 状态码",
            "expected_results": "页面返回 200，正常加载，无报错",
            "element_selector": "",
        })

        # 2. 页面标题/URL 验证
        cases.append({
            "name": f"{page_name} 页面标题与 URL 验证",
            "module": "页面验证",
            "priority": "P1",
            "preconditions": "页面已加载完成",
            "steps": f"1. 获取当前页面 URL\n2. 检查 URL 是否包含 {domain}\n3. 获取页面标题并验证非空",
            "expected_results": f"URL 正确指向 {domain}，页面标题非空",
            "element_selector": "",
        })

        # 3. 为每个已解析的元素生成存在性验证
        for i, elem in enumerate(elements, 1):
            tag = elem.get("tag", "元素")
            text = elem.get("text", "") or elem.get("name", "") or elem.get("id", "") or f"#{i}"
            selector = elem.get("selector", "")
            cases.append({
                "name": f"页面元素 [{tag}] {text} 存在性验证",
                "module": "页面验证",
                "priority": "P1",
                "preconditions": "页面已加载完成",
                "steps": f"1. 等待页面渲染完成\n2. 检查元素 [{tag}] {text} 是否存在{chr(10)}3. 确认元素的 selector 可用: {selector}" if selector else f"1. 等待页面渲染完成\n2. 检查元素 [{tag}] {text} 是否存在\n3. 确认元素可见",
                "expected_results": f"元素 [{tag}] {text} 存在且可见",
                "element_selector": selector,
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
                    result = progress_cb(pct, stage)
                    import inspect as _ins
                    if _ins.isawaitable(result):
                        await result
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
