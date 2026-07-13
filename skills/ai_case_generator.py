"""
AI 测试用例生成器 — 通过本地 claude CLI 调用大模型生成 Markdown / XMind 格式用例文件
"""
import asyncio
import hashlib
import json
import zipfile
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from loguru import logger


def _uid() -> str:
    return uuid.uuid4().hex[:16]


def _xml_escape(text: str) -> str:
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


class AICaseGenerator:
    def __init__(self):
        self.output_dir = Path("ai_cases")
        self.output_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    async def generate(
        self,
        task_name: str,
        document_path: Optional[str] = None,
        content: Optional[str] = None,
        formats: Optional[List[str]] = None,
        progress_cb=None,
        rag_source_id: Optional[int] = None,   # 传入时先入库 RAG，生成时检索
    ) -> Dict[str, Any]:
        """
        生成 AI 测试用例并保存为文件。
        document_path 和 content 二选一；都传时优先解析文档。
        progress_cb: 可选异步回调 async (pct: int, stage: str)
        """
        if formats is None:
            formats = ["md", "xmind"]

        async def _p(pct: int, stage: str):
            if progress_cb:
                try:
                    await progress_cb(pct, stage)
                except Exception:
                    pass

        await _p(5, "文档上传完成，正在解析文档...")
        doc_text = await self._get_content(document_path, content)
        if not doc_text:
            raise ValueError("未提供需求内容（文档路径或文本均为空）")

        # 计算文档哈希，供调用方写入数据库做变更检测
        doc_hash = self._compute_doc_hash(doc_text)

        # RAG 入库：文档解析完成后立即分段入库，生成时可直接检索
        if rag_source_id is not None:
            try:
                from skills.rag import index_document
                await index_document(rag_source_id, "ai_case", doc_text)
                logger.info(f"RAG: indexed doc for ai_case:{rag_source_id}")
            except Exception as e:
                logger.warning(f"RAG index failed, will use truncated context: {e}")

        pro_max = self._load_pro_max_skill()

        if pro_max:
            # ── 分段生成模式 ──────────────────────────────────────────
            max_content = 5000
            truncated = (doc_text[:max_content] + "\n\n[内容已截断]") if len(doc_text) > max_content else doc_text

            await _p(15, "正在分析需求文档，识别功能模块...")
            logger.info(f"AI 用例分段生成开始: {task_name}，内容 {len(doc_text)} 字")

            modules_info = await self._extract_modules(truncated)

            if modules_info:
                total_mod = len(modules_info)
                await _p(20, f"识别到 {total_mod} 个功能模块，开始逐模块生成用例...")
                logger.info(f"提取模块: {[m['name'] for m in modules_info]}")
                cases_data = await self._call_llm_staged(
                    truncated, task_name, modules_info, _p,
                    rag_source_id=rag_source_id,
                )
            else:
                logger.warning("模块识别失败，回退到单次生成")
                await _p(20, "模块识别失败，使用默认方式生成...")
                cases_data = await self._call_llm(doc_text, task_name, _p)
        else:
            # ── 默认单次生成模式 ─────────────────────────────────────
            await _p(20, "文档解析完成，正在调用 AI 生成用例...")
            logger.info(f"AI 用例生成开始: {task_name}，内容长度 {len(doc_text)}")
            cases_data = await self._call_llm(doc_text, task_name, _p)

        await _p(90, "AI 生成完成，正在保存文件...")
        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        result: Dict[str, Any] = {
            "task_name": task_name,
            "cases_data": cases_data,
            "files": {},
        }

        if "md" in formats:
            md_path = await self._save_markdown(cases_data, task_name, ts)
            result["files"]["md"] = str(md_path)

        if "xmind" in formats:
            xmind_path = await self._save_xmind(cases_data, task_name, ts)
            result["files"]["xmind"] = str(xmind_path)

        await self._cleanup_old_files(ts)

        result["case_count"] = sum(
            len(m.get("cases", [])) for m in cases_data.get("modules", [])
        )
        # 将文档哈希和截断内容一并返回，由 routes.py 写入数据库
        result["doc_hash"] = doc_hash
        result["doc_content"] = doc_text[:20000]   # 最多保存 2 万字，够 Diff 分析用
        await _p(100, f"完成！共生成 {result['case_count']} 条用例")
        logger.info(f"AI 用例生成完成: {result['case_count']} 条，文件: {result['files']}")
        return result

    # ------------------------------------------------------------------
    # 文档哈希计算（MD5，16 位短哈希，用于快速判断文档是否变更）
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_doc_hash(text: str) -> str:
        """计算需求文档内容的 MD5 哈希（16 位十六进制），用于变更检测。"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]

    # ------------------------------------------------------------------
    # AI Diff 分析：对比新旧文档，识别变更模块清单
    # ------------------------------------------------------------------
    async def analyze_document_diff(
        self,
        old_doc_content: str,
        new_doc_content: str,
        existing_module_names: Optional[List[str]] = None,   # 旧用例的实际模块名列表
    ) -> Dict[str, Any]:
        """
        调用 LLM 对比新旧需求文档，返回结构化变更清单。
        existing_module_names: 传入旧用例的真实模块名列表，
                               强制 AI 使用这些名字，防止自创新名导致模块找不到。
        """
        old_snip = old_doc_content[:6000]
        new_snip = new_doc_content[:6000]

        # 如果有旧模块名列表，注入到 prompt 里作为强约束
        module_names_hint = ""
        if existing_module_names:
            names_str = "\n".join(f"  - {n}" for n in existing_module_names)
            module_names_hint = f"""
## 重要约束：旧用例的实际模块名列表
以下是旧测试用例中真实存在的模块名（必须用这些原始名字，不能自创新名称）：
{names_str}

在 changed / removed / unchanged 中填写模块名时，**必须从上面列表中选取**，不得使用其他名称。
如果某个旧模块的需求在新文档里发生了变更，用列表中的原名，在 summary 字段描述变更内容。
"""

        system_prompt = (
            "You are a senior QA analyst. Your task is to compare two versions of a requirements document "
            "and produce a COMPLETE classification of every functional module that existed in the old version. "
            "EVERY module from the old document MUST appear in exactly one of: changed, removed, or unchanged. "
            "CRITICAL: When existing module names are provided, you MUST use those exact names. "
            "Output ONLY valid JSON. No markdown, no explanation."
        )
        prompt = f"""对比以下新旧两版需求文档，对旧文档中的每一个功能模块进行完整分类，用于指导测试用例的增量更新。
{module_names_hint}
【旧版文档】
---
{old_snip}
---

【新版文档】
---
{new_snip}
---

## 分析步骤（必须严格按照以下步骤执行）

Step 1：从【旧用例模块名列表】（若已提供）或【旧版文档】中列出所有功能模块名称。
Step 2：逐一判断每个旧模块在新文档中的状态：
  - **removed（删除）**：该模块在新文档中完全不存在，相关功能/需求被整体删除
  - **changed（变更）**：模块仍存在，但需求内容有实质修改（新增/修改/删除了具体需求点、字段、逻辑）
  - **unchanged（未变）**：模块仍存在，内容几乎完全相同，旧测试用例可以直接复用
Step 3：新文档中有但旧文档没有的模块归入 added。

## 关键规则
- **每个旧模块必须出现在 changed、removed、unchanged 三者之一中，不能遗漏**
- **模块名必须使用旧用例列表中的原始名称，禁止重命名或合并模块**
- removed 判断标准：在新文档中搜索不到该模块名称及其相关需求描述

只输出纯 JSON：
{{
  "changed":   [{{"module": "旧模块原始名称", "summary": "变更描述（一句话）"}}],
  "added":     [{{"module": "新模块名称", "summary": "新增描述（一句话）"}}],
  "removed":   ["旧模块原始名称"],
  "unchanged": ["旧模块原始名称"],
  "impact_level": "high",
  "diff_summary": "本次变更的一句话总结"
}}"""

        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=60)
            result = json.loads(raw)
            # 字段保底，防止 LLM 漏字段
            result.setdefault("changed", [])
            result.setdefault("added", [])
            result.setdefault("removed", [])
            result.setdefault("unchanged", [])
            result.setdefault("impact_level", "medium")
            result.setdefault("diff_summary", "需求文档已更新")
            logger.info(
                f"文档 Diff 分析完成: changed={len(result['changed'])} "
                f"added={len(result['added'])} removed={len(result['removed'])} "
                f"unchanged={len(result['unchanged'])}"
            )
            logger.debug(f"Diff 原始结果: {json.dumps(result, ensure_ascii=False)}")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Diff 分析返回非法 JSON: {e}")
            raise RuntimeError(f"Diff 分析失败，AI 返回非 JSON 内容: {e}")
        except Exception as e:
            logger.error(f"Diff 分析异常: {e}")
            raise RuntimeError(f"Diff 分析异常: {e}")

    # ------------------------------------------------------------------
    # 清理旧生成文件，只保留当前批次
    # ------------------------------------------------------------------
    async def _cleanup_old_files(self, keep_ts: str) -> None:
        try:
            for pattern in ("cases_*.md", "cases_*.xmind"):
                for f in self.output_dir.glob(pattern):
                    if keep_ts not in f.name:
                        f.unlink(missing_ok=True)
                        logger.info(f"已清理旧文件: {f.name}")
        except Exception as e:
            logger.warning(f"清理旧文件失败: {e}")

    # ------------------------------------------------------------------
    # 获取需求文本
    # ------------------------------------------------------------------
    async def _get_content(
        self, document_path: Optional[str], content: Optional[str]
    ) -> str:
        if document_path:
            try:
                from tools.document_parser import document_parser
                parsed = await document_parser.parse(document_path)
                text = parsed.get("content", "")
                if text:
                    # 解析完即删除临时上传文件（uploads/documents 目录下）
                    try:
                        p = Path(document_path)
                        if "uploads" in p.parts and "documents" in p.parts:
                            p.unlink(missing_ok=True)
                            logger.info(f"临时文档已删除: {document_path}")
                    except Exception:
                        pass
                    return text
            except Exception as e:
                logger.warning(f"文档解析失败，回退到纯文本: {e}")
        return content or ""

    # ------------------------------------------------------------------
    # 加载 test-case-pro-max 技能配置（若存在则使用增强提示词）
    # ------------------------------------------------------------------
    def _load_pro_max_skill(self) -> Optional[Dict[str, str]]:
        """尝试加载 test_case_pro_max 技能的 prompt.yaml，返回 {system_prompt, user_prompt_template} 或 None"""
        try:
            import yaml
            skill_dir = Path(__file__).parent / "test_case_pro_max"
            prompt_yaml = skill_dir / "prompt.yaml"
            if not prompt_yaml.exists():
                return None
            with open(prompt_yaml, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            system_prompt = cfg.get("system_prompt", "").strip()
            user_tpl = cfg.get("user_prompt_template", "").strip()
            if system_prompt and user_tpl:
                logger.info("已加载 test-case-pro-max 技能增强提示词")
                return {"system_prompt": system_prompt, "user_prompt_template": user_tpl}
        except Exception as e:
            logger.warning(f"加载 test-case-pro-max 技能失败，回退到默认提示词: {e}")
        return None

    # ------------------------------------------------------------------
    # LLM 调用（统一入口，支持 Anthropic / OpenAI 兼容格式）
    # ------------------------------------------------------------------
    async def _run_claude_subprocess(
        self, system_prompt: str, prompt: str, timeout_secs: int = 90
    ) -> str:
        """调用 LLM API，自动根据模型类型选择 Anthropic 或 OpenAI 兼容格式。"""
        import httpx
        from tools.config import settings

        api_key  = settings.AI_API_KEY
        base_url = (settings.AI_API_URL or "").rstrip("/")
        model    = settings.AI_MODEL or "deepseek-v4-flash"

        if not api_key or not base_url:
            raise RuntimeError("未配置 AI_API_KEY 或 AI_API_URL，请在大模型配置页填写后重试")

        is_anthropic = "anthropic.com" in base_url or model.startswith("claude")

        if is_anthropic:
            url     = f"{base_url}/v1/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": model,
                "max_tokens": 8192,
                "system": system_prompt,
                "messages": [{"role": "user", "content": prompt}],
            }
        else:
            url     = f"{base_url}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            }
            payload = {
                "model": model,
                "max_tokens": 8192,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
            }

        logger.info(f"Calling LLM API: {url}, model={model}")
        async with httpx.AsyncClient(verify=False, timeout=timeout_secs) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        if is_anthropic:
            raw = data["content"][0]["text"]
        else:
            raw = data["choices"][0]["message"]["content"]

        raw = raw.strip()
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        return raw

    # ------------------------------------------------------------------
    # 分段生成 Step-1：提取功能模块列表
    # ------------------------------------------------------------------
    async def _extract_modules(self, content: str) -> list:
        """快速调用 Claude 从需求文档中提取功能模块及其功能点列表。"""
        system_prompt = (
            "You are a business analyst. Extract functional modules from a requirements document. "
            "Output ONLY valid JSON. No markdown, no explanation."
        )
        prompt = f"""分析以下需求文档，识别所有功能模块并列出每个模块的核心功能点。

需求文档：
---
{content}
---

只输出纯JSON：
{{
  "modules": [
    {{
      "name": "模块名称",
      "features": ["核心功能点1", "核心功能点2", "核心功能点3"]
    }}
  ]
}}

识别3-10个主要功能模块，每个模块列出3-6个功能点，只提取文档中明确的功能。"""

        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=60)
            data = json.loads(raw)
            modules = data.get("modules", [])
            if isinstance(modules, list) and modules:
                logger.info(f"模块提取成功: {len(modules)} 个模块")
                return modules
        except Exception as e:
            logger.warning(f"模块提取失败: {e}")
        return []

    # ------------------------------------------------------------------
    # 分段生成 Step-2：单模块用例生成
    # ------------------------------------------------------------------
    async def _call_llm_for_module(
        self,
        module_name: str,
        features: list,
        content: str,
        rag_source_id: Optional[int] = None,
        rag_source_type: str = "ai_case",
    ) -> Dict[str, Any]:
        """为单个功能模块生成测试用例，数量根据功能点数量动态调整（8-20条）。
        rag_source_id 不为 None 时优先用 RAG 检索相关段落替代硬截断。
        """
        features_text = "\n".join(f"  - {f}" for f in features[:6])
        case_limit = max(8, min(len(features) * 2, 20))

        # 尝试 RAG 检索，失败则回退截断
        context = None
        if rag_source_id is not None:
            try:
                from skills.rag import search_chunks
                query = f"{module_name} {' '.join(features[:4])}"
                retrieved = await search_chunks(query, rag_source_id, rag_source_type, top_k=5)
                if retrieved:
                    context = "\n\n".join(retrieved)
                    logger.info(f"RAG: module '{module_name}' retrieved {len(retrieved)} chunks")
            except Exception as e:
                logger.warning(f"RAG search failed for '{module_name}': {e}")

        if context is None:
            context = content[:2000]

        from skills.prompt_loader import get_system, render_user
        system_prompt = get_system("ai_case_gen.yaml", "generate_module_cases")
        prompt = render_user("ai_case_gen.yaml", "generate_module_cases",
                             module_name=module_name,
                             features_text=features_text,
                             content=context,
                             case_limit=case_limit)

        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
            data = json.loads(raw)
            return data
        except json.JSONDecodeError as e:
            logger.error(f"模块「{module_name}」返回非法 JSON: {e}")
        except Exception as e:
            logger.warning(f"模块「{module_name}」生成失败: {e}")
        return {"name": module_name, "cases": []}

    # ------------------------------------------------------------------
    # 分段生成 Step-2b：性能 / 兼容性用例生成
    # ------------------------------------------------------------------
    async def _call_llm_for_extra_dimension(
        self, dim_type: str, content: str, task_name: str
    ) -> Dict[str, Any]:
        """生成性能或兼容性测试用例（最多8条）。dim_type: 'performance' | 'compatibility'"""
        if dim_type == "performance":
            dim_name = "性能测试"
            system_prompt = (
                "You are a performance QA engineer. Generate performance test cases. "
                "Output ONLY valid JSON. No markdown."
            )
            prompt = f"""为「{task_name}」系统生成性能测试用例（最多8条）。

参考需求（节选）：
---
{content[:1500]}
---

覆盖以下场景（每类1-2条）：
1. 响应时间：单用户正常操作，接口响应 < 2s
2. 并发负载：10/50/100 并发用户同时操作
3. 大数据量：列表/搜索页 1 万+ 条数据的加载与翻页
4. 峰值压力：持续高频操作 5 分钟，内存/CPU 无明显泄漏
5. 慢网络：3G 网络环境下核心页面可正常加载

只输出纯JSON：
{{
  "name": "性能测试",
  "cases": [
    {{
      "id": "TC001",
      "name": "性能场景描述（如：并发-100用户同时登录-响应时间验证）",
      "priority": "P3",
      "type": "性能测试",
      "test_method": "性能测试",
      "preconditions": "前置条件（测试工具/数据量/网络环境）",
      "steps": ["1. 操作步骤（含具体参数）", "2. 监控指标"],
      "expected": "预期结果（含具体阈值，如：P95响应时间<2s，CPU<80%）"
    }}
  ]
}}"""
        else:
            dim_name = "兼容性测试"
            system_prompt = (
                "You are a compatibility QA engineer. Generate compatibility test cases. "
                "Output ONLY valid JSON. No markdown."
            )
            prompt = f"""为「{task_name}」系统生成兼容性测试用例（最多8条）。

参考需求（节选）：
---
{content[:1500]}
---

覆盖以下场景（每类1-2条）：
1. 浏览器：Chrome 最新版 / Firefox 最新版 / Safari 最新版 / Edge 最新版
2. 移动端浏览器：iOS Safari / Android Chrome / 微信内置浏览器
3. 屏幕分辨率：1920×1080（桌面）/ 1366×768（笔记本）/ 375×812（iPhone）
4. 操作系统：Windows 10 / Windows 11 / macOS 13+
5. 缩放比例：浏览器页面放大 125% / 150% 时布局正常

只输出纯JSON：
{{
  "name": "兼容性测试",
  "cases": [
    {{
      "id": "TC001",
      "name": "兼容场景描述（如：浏览器-Firefox最新版-核心功能正常）",
      "priority": "P3",
      "type": "兼容性测试",
      "test_method": "兼容性测试",
      "preconditions": "前置条件（浏览器版本/设备型号/分辨率设置）",
      "steps": ["1. 在指定环境打开系统", "2. 执行核心操作"],
      "expected": "预期结果（页面布局正常，功能无异常，无JS报错）"
    }}
  ]
}}"""

        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
            data = json.loads(raw)
            return data
        except json.JSONDecodeError as e:
            logger.error(f"{dim_name}返回非法 JSON: {e}")
        except Exception as e:
            logger.warning(f"{dim_name}生成失败: {e}")
        return {"name": dim_name, "cases": []}

    # ------------------------------------------------------------------
    # 分段生成 Step-3：并发调度 + 合并结果（含性能 + 兼容性）
    # ------------------------------------------------------------------
    async def _call_llm_staged(
        self,
        content: str,
        task_name: str,
        modules_info: list,
        _p,
        rag_source_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """并发（最多2路）逐模块生成功能用例，同时生成性能和兼容性用例，统一编号合并。"""
        total_all = len(modules_info) + 2  # +2：性能 + 兼容性
        sem = asyncio.Semaphore(2)
        completed = [0]

        async def _progress_done(label: str):
            completed[0] += 1
            await _p(
                20 + int(completed[0] / total_all * 65),
                f"已完成 {completed[0]}/{total_all}：{label}",
            )

        async def _gen_func(i: int, module: dict):
            async with sem:
                name = module.get("name", f"模块{i+1}")
                features = module.get("features", [])
                await _p(
                    20 + int(i / total_all * 65),
                    f"正在生成功能模块 {i+1}/{len(modules_info)}：{name}...",
                )
                result = await self._call_llm_for_module(
                    name, features, content,
                    rag_source_id=rag_source_id,
                )
                await _progress_done(name)
                return result

        async def _gen_perf():
            async with sem:
                await _p(20, "正在生成性能测试用例...")
                result = await self._call_llm_for_extra_dimension("performance", content, task_name)
                await _progress_done("性能测试")
                return result

        async def _gen_compat():
            async with sem:
                await _p(20, "正在生成兼容性测试用例...")
                result = await self._call_llm_for_extra_dimension("compatibility", content, task_name)
                await _progress_done("兼容性测试")
                return result

        all_tasks = (
            [_gen_func(i, m) for i, m in enumerate(modules_info)]
            + [_gen_perf(), _gen_compat()]
        )
        all_results = await asyncio.gather(*all_tasks)

        func_results = all_results[:len(modules_info)]
        perf_result  = all_results[-2]
        compat_result = all_results[-1]

        # 统一重新编号 TC001, TC002...
        counter = 1
        merged_modules = []
        for mod in list(func_results) + [perf_result, compat_result]:
            if not mod:
                continue
            cases = mod.get("cases", [])
            if not cases:
                continue
            renamed = []
            for case in cases:
                c = dict(case)
                c["id"] = f"TC{counter:03d}"
                counter += 1
                renamed.append(c)
            merged_modules.append({"name": mod["name"], "cases": renamed})

        total_cases = sum(len(m["cases"]) for m in merged_modules)
        logger.info(f"分段生成完成: {len(merged_modules)} 个模块，共 {total_cases} 条用例")
        return {
            "title": f"{task_name} 完整测试用例集",
            "modules": merged_modules,
        }
    async def _call_llm(self, content: str, task_name: str, _p=None) -> Dict[str, Any]:
        # 内容截断：5000 字足够 Claude 理解需求，同时保证输出 token 可控
        max_content = 5000
        if len(content) > max_content:
            content = content[:max_content] + f"\n\n[内容已截断，以上为前 {max_content} 字]"

        if len(content.strip()) < 50:
            raise RuntimeError(
                f"文档内容太少（仅 {len(content.strip())} 字），无法生成用例。"
                "请确认上传了正确的需求文档，或直接在文本框粘贴需求内容。"
            )

        # 优先加载 test-case-pro-max 技能的增强提示词
        pro_max = self._load_pro_max_skill()
        if pro_max:
            system_prompt = pro_max["system_prompt"]
            prompt = pro_max["user_prompt_template"].format(
                task_name=task_name,
                content=content,
            )
            if _p:
                await _p(25, "已加载 test-case-pro-max 技能，正在调用 AI 生成专业级用例...")
        else:
            system_prompt = (
                "You are a test case JSON generator. "
                "Your only job is to output a single valid JSON object matching the schema the user provides. "
                "Never output explanations, markdown, or any text outside the JSON object."
            )
            prompt = f"""根据以下需求文档，为任务「{task_name}」生成完整测试用例集。

需求文档：
---
{content}
---

输出要求：
- 只输出纯 JSON，不加任何说明文字或 markdown 代码块
- 严格匹配如下结构：
{{
  "title": "测试用例集名称",
  "modules": [
    {{
      "name": "模块名称",
      "cases": [
        {{
          "id": "TC001",
          "name": "用例名称",
          "priority": "P0",
          "type": "功能测试",
          "preconditions": "前置条件",
          "steps": ["步骤1", "步骤2"],
          "expected": "预期结果"
        }}
      ]
    }}
  ]
}}

生成要求：
1. 优先级：P0（核心主流程）、P1（主要功能）、P2（边界/异常/兼容）
2. 覆盖正常流程 + 异常场景 + 边界值
3. 步骤具体可操作，预期结果可量化验证
4. 第一个字符必须是 {{，最后一个字符必须是 }}"""

        logger.info("调用 LLM API 生成用例...")
        import httpx
        from tools.config import settings

        api_key  = settings.AI_API_KEY
        base_url = (settings.AI_API_URL or "").rstrip("/")
        model    = settings.AI_MODEL or "deepseek-v4-flash"

        if not api_key or not base_url:
            raise RuntimeError("未配置 AI_API_KEY 或 AI_API_URL，请在大模型配置页填写后重试")

        is_anthropic = "anthropic.com" in base_url or model.startswith("claude")

        if is_anthropic:
            url     = f"{base_url}/v1/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": model,
                "max_tokens": 8192,
                "system": system_prompt,
                "messages": [{"role": "user", "content": prompt}],
            }
        else:
            url     = f"{base_url}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            }
            payload = {
                "model": model,
                "max_tokens": 8192,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
            }

        # 后台模拟进度推送 30→88%（AI 生成期间）
        _done_flag = [False]
        async def _simulate_progress():
            pct = 30
            while not _done_flag[0] and pct < 88:
                await asyncio.sleep(6)
                pct = min(pct + 4, 88)
                if not _done_flag[0] and _p:
                    await _p(pct, f"AI 正在生成用例，请耐心等候... ({pct}%)")

        sim_task = asyncio.ensure_future(_simulate_progress())
        try:
            async with httpx.AsyncClient(verify=False, timeout=360) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        finally:
            _done_flag[0] = True
            sim_task.cancel()

        if is_anthropic:
            raw = data["content"][0]["text"]
        else:
            raw = data["choices"][0]["message"]["content"]

        raw = raw.strip()
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("LLM 返回非法 JSON: {}\n原文(前500): {}", e, raw[:500])
            raise RuntimeError(
                f"AI 返回内容不是 JSON 格式，无法解析。\n"
                f"AI 实际返回（前200字）：{raw[:200]}"
            )

    # ------------------------------------------------------------------
    # 增量更新入口：文档变更后只重生成 changed/added 模块
    # ------------------------------------------------------------------
    async def incremental_update(
        self,
        task_name: str,
        old_cases_data: Dict[str, Any],
        new_doc_content: str,
        diff_result: Dict[str, Any],
        formats: Optional[List[str]] = None,
        progress_cb=None,
    ) -> Dict[str, Any]:
        """
        根据 diff_result 只对变更/新增模块重生成用例，未变更模块直接保留，
        删除模块用例打上 deprecated 标记后追加到末尾（审计追踪）。

        返回与 generate() 相同的结构，额外包含 diff_summary。
        """
        if formats is None:
            formats = ["md", "xmind"]

        async def _p(pct: int, stage: str):
            if progress_cb:
                try:
                    await progress_cb(pct, stage)
                except Exception:
                    pass

        changed_mods   = diff_result.get("changed", [])
        added_mods     = diff_result.get("added", [])
        removed_names  = diff_result.get("removed", [])
        unchanged_names = diff_result.get("unchanged", [])
        diff_summary   = diff_result.get("diff_summary", "需求文档已更新")

        # 旧用例按模块分布情况（方便排查）
        old_modules_list = (old_cases_data or {}).get("modules", [])
        logger.info(
            f"旧用例数据: 共 {len(old_modules_list)} 个模块, "
            f"各模块用例数: { {m.get('name','?'): len(m.get('cases',[])) for m in old_modules_list} }"
        )

        # 需要重生成的模块列表（added 仍然全量生成）
        total_changed = len(changed_mods)
        total_added   = len(added_mods)
        total_tasks   = max(total_changed + total_added, 1)

        await _p(10, f"共 {total_changed} 个变更模块（用例级合并）、{total_added} 个新增模块...")
        logger.info(
            f"增量更新: changed={len(changed_mods)} added={len(added_mods)} "
            f"removed={len(removed_names)} unchanged={len(unchanged_names)}"
        )

        # 旧用例按模块名建索引（用于 changed 模块的用例级合并）
        old_modules_index = {
            m.get("name", ""): m
            for m in (old_cases_data or {}).get("modules", [])
        }

        # ── 名字校正：若 AI Diff 返回的 changed 模块名在旧用例里找不到，
        # 做模糊匹配（包含关系），找到最接近的旧模块名替换 ─────────────────
        def _fuzzy_match(ai_name: str, real_names: List[str]) -> Optional[str]:
            """从真实模块名里找与 ai_name 最匹配的，返回 None 表示找不到"""
            ai_lower = ai_name.lower()
            # 精确匹配
            if ai_name in real_names:
                return ai_name
            # 包含匹配：旧名包含 AI 名的关键词，或 AI 名包含旧名的关键词
            for real in real_names:
                r_lower = real.lower()
                if ai_lower in r_lower or r_lower in ai_lower:
                    return real
            # 字符重叠率：超过 60% 的字符相同
            for real in real_names:
                common = sum(1 for c in ai_name if c in real)
                ratio  = common / max(len(ai_name), 1)
                if ratio >= 0.6:
                    return real
            return None

        real_names = list(old_modules_index.keys())
        corrected_changed = []
        for mod_info in changed_mods:
            ai_name = mod_info.get("module", "")
            if ai_name in old_modules_index:
                corrected_changed.append(mod_info)
            else:
                matched = _fuzzy_match(ai_name, real_names)
                if matched:
                    logger.info(f"模块名校正: AI返回「{ai_name}」→ 旧用例实际名「{matched}」")
                    corrected_changed.append({**mod_info, "module": matched})
                else:
                    # 找不到匹配则当作 added（新增模块），不丢弃
                    logger.warning(f"模块「{ai_name}」在旧用例中找不到匹配，当作新增模块处理")
                    added_mods = list(added_mods) + [mod_info]
        changed_mods = corrected_changed

        sem = asyncio.Semaphore(2)
        completed = [0]

        async def _progress_done(label: str):
            completed[0] += 1
            await _p(
                10 + int(completed[0] / total_tasks * 75),
                f"已完成 {completed[0]}/{total_tasks}：{label}",
            )

        # ── 变更模块：用例级合并（keep/deprecated/new） ──────────────────
        async def _merge_changed(i: int, mod_info: dict):
            async with sem:
                name    = mod_info["module"]
                summary = mod_info.get("summary", "")
                old_mod = old_modules_index.get(name, {})
                old_cases = old_mod.get("cases", [])
                logger.info(f"changed 模块「{name}」: 找到旧用例 {len(old_cases)} 条, 旧模块索引 keys={list(old_modules_index.keys())}")
                await _p(
                    10 + int(i / total_tasks * 75),
                    f"用例级合并 {i + 1}/{total_tasks}：{name}...",
                )
                result = await self._merge_module_cases(
                    module_name    = name,
                    old_cases      = old_cases,
                    new_doc_content= new_doc_content,
                    change_summary = summary,
                )
                await _progress_done(name)
                return name, old_cases, result

        # ── 新增模块：全量生成 ────────────────────────────────────────────
        async def _regen_added(i: int, mod_info: dict):
            async with sem:
                name     = mod_info["module"]
                features = [mod_info.get("summary", "")]
                idx      = total_changed + i
                await _p(
                    10 + int(idx / total_tasks * 75),
                    f"生成新增模块 {i + 1}/{total_added}：{name}...",
                )
                result = await self._call_llm_for_module(name, features, new_doc_content)
                await _progress_done(name)
                return result

        changed_results: List = []
        added_results:   List = []

        if changed_mods:
            changed_results = await asyncio.gather(
                *[_merge_changed(i, m) for i, m in enumerate(changed_mods)]
            )
        if added_mods:
            added_results = await asyncio.gather(
                *[_regen_added(i, m) for i, m in enumerate(added_mods)]
            )

        # ── 合并用例 ──────────────────────────────────────────────────
        await _p(87, "正在合并用例，统一编号...")
        merged = self._merge_cases(
            old_cases_data  = old_cases_data,
            changed_results = changed_results,   # [(name, old_cases, merge_result), ...]
            added_results   = added_results,     # [{name, cases}, ...]
            added_names     = [m["module"] for m in added_mods],
            unchanged_names = unchanged_names,
            removed_names   = removed_names,
            new_doc_content = new_doc_content,
        )

        # ── 保存文件 ──────────────────────────────────────────────────
        await _p(90, "保存文件...")
        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        result: Dict[str, Any] = {
            "task_name": task_name,
            "cases_data": merged,
            "files": {},
            "diff_summary": diff_summary,
            "doc_hash": self._compute_doc_hash(new_doc_content),
            "doc_content": new_doc_content[:20000],
        }

        if "md" in formats:
            md_path = await self._save_markdown(merged, task_name, ts)
            result["files"]["md"] = str(md_path)
        if "xmind" in formats:
            xmind_path = await self._save_xmind(merged, task_name, ts)
            result["files"]["xmind"] = str(xmind_path)

        await self._cleanup_old_files(ts)

        # 统计活跃用例数（不含 deprecated）
        active_count = sum(
            len([c for c in m.get("cases", []) if c.get("status") != "deprecated"])
            for m in merged.get("modules", [])
        )
        result["case_count"] = active_count
        await _p(100, f"增量更新完成！共 {active_count} 条有效用例")
        logger.info(f"增量更新完成: {task_name}，有效用例 {active_count} 条")
        return result

    # ------------------------------------------------------------------
    # 用例级别合并：changed 模块内精确找「失效用例」+「新增场景」
    # ------------------------------------------------------------------
    async def _merge_module_cases(
        self,
        module_name: str,
        old_cases: List[Dict],
        new_doc_content: str,
        change_summary: str = "",
    ) -> Dict[str, Any]:
        """
        策略：默认保留所有旧用例，只让 LLM 识别两件事：
        1. deprecated_ids：因变更导致「功能点已从新需求中删除」的旧用例 ID（少数）
        2. new_cases：新需求中出现的、旧用例未覆盖的新场景

        判断标准（严格）：
        - 只有当旧用例测试的功能点在新文档中「完全消失」时，才标 deprecated
        - 功能点仍然存在（即使逻辑有调整）→ 保留旧用例，由测试人员手动调整步骤
        - 不确定是否删除 → 保留（保守原则）
        """
        cases_summary = "\n".join(
            f"  {c.get('id','?')} | {c.get('name','')} | {c.get('test_method') or c.get('type','')} | {c.get('priority','')}"
            for c in old_cases[:30]
        )

        system_prompt = (
            "You are a senior QA engineer performing a conservative test case review. "
            "Your default is to KEEP existing test cases unless the feature they test "
            "has been COMPLETELY REMOVED from the new requirements. "
            "Output ONLY valid JSON. No markdown."
        )
        prompt = f"""需求模块「{module_name}」发生了变更，请对现有测试用例做保守式审查。

变更说明：{change_summary or '需求有局部更新'}

【新版需求文档】
---
{new_doc_content[:4000]}
---

【现有测试用例】（用例ID | 用例名称 | 测试方法 | 优先级）
{cases_summary}

## 审查原则（请严格遵守）

**废弃标准（必须同时满足以下两条才能废弃）**：
1. 该用例测试的功能点在新版需求文档中「完全不存在」——不是调整了，是彻底删掉了
2. 你能在新文档中明确找到"该功能已被移除"的依据

**保留原则（满足任意一条就应保留）**：
- 功能点仍然存在，只是需求描述有所调整 → 保留（测试人员手动更新步骤）
- 无法确定该功能是否被删除 → 保留
- 该用例测试的是边界值、异常流程、兼容性等通用场景 → 保留

**新增用例**：只针对新文档中出现的、旧用例完全没有覆盖的全新功能场景。

## 输出格式（只输出纯JSON）
{{
  "deprecated": ["TC002"],
  "new_cases": [
    {{
      "name": "新场景用例名称",
      "priority": "P1",
      "type": "功能测试",
      "test_method": "等价类划分",
      "preconditions": "前置条件",
      "steps": ["1. 操作步骤"],
      "expected": "预期结果"
    }}
  ],
  "reason": "一句话说明废弃了哪些用例及原因"
}}

注意：deprecated 列表应该很小（通常0-3条），如果你发现自己要废弃很多用例，请重新检查是否符合废弃标准。"""

        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
            result = json.loads(raw)
            deprecated = result.get("deprecated", [])
            new_cases  = result.get("new_cases", [])

            # 安全校验：deprecated 不能超过旧用例总数的 50%（超出说明 LLM 判断过激）
            max_deprecated = max(1, len(old_cases) // 2)
            if len(deprecated) > max_deprecated:
                logger.warning(
                    f"模块「{module_name}」废弃用例过多({len(deprecated)}/{len(old_cases)})，"
                    f"超过50%阈值，重置为空（全部保留）"
                )
                deprecated = []

            logger.info(
                f"模块「{module_name}」用例级合并: "
                f"keep={len(old_cases)-len(deprecated)} "
                f"deprecated={len(deprecated)} new={len(new_cases)} "
                f"reason={result.get('reason','')}"
            )
            return {
                "deprecated": deprecated,
                "new_cases":  new_cases,
            }
        except Exception as e:
            logger.warning(f"模块「{module_name}」用例级合并失败: {e}，全部保留旧用例")
            return {"deprecated": [], "new_cases": []}

    # ------------------------------------------------------------------
    # 用例合并：unchanged 保留 + changed/added 用新生成替换 + removed 打标记
    # ------------------------------------------------------------------
    def _merge_cases(
        self,
        old_cases_data: Dict[str, Any],
        changed_results: List,           # [(name, old_cases, {keep,deprecated,new_cases}), ...]
        added_results: List,             # [{name, cases}, ...]  全量新模块
        added_names: List[str],
        unchanged_names: List[str],
        removed_names: List[str],
        new_doc_content: str = "",
    ) -> Dict[str, Any]:
        """
        合并规则：
        1. unchanged 模块：直接保留旧用例
        2. changed 模块：旧用例按 keep/deprecated 分别处理 + 追加新用例
        3. added 模块：全量新用例
        4. removed 模块：旧用例全部标 deprecated
        5. 未分类旧模块：文本搜索二次判断 unchanged/removed

        编号规则：active 用例统一重编 TC001…；deprecated 用例追加在模块末尾，
        保留原始 id 前缀并加 (废弃) 后缀区分，不参与重编号。
        """
        old_modules: List[Dict] = (old_cases_data or {}).get("modules", [])
        old_index = {m.get("name", ""): m for m in old_modules}

        # ── 通用测试类型保护：性能/兼容性/安全等测试与需求无关，永远不废弃 ────
        ALWAYS_KEEP_KEYWORDS = ("性能", "兼容", "安全", "压力", "负载", "可靠性", "稳定性")

        def _is_generic_test(name: str) -> bool:
            return any(kw in name for kw in ALWAYS_KEEP_KEYWORDS)

        # 把 removed 里的通用测试类型模块移回 unchanged
        protected: List[str] = []
        filtered_removed = []
        for name in removed_names:
            if _is_generic_test(name):
                protected.append(name)
            else:
                filtered_removed.append(name)
        if protected:
            logger.info(f"通用测试模块不随需求删除，强制保留: {protected}")
        removed_names = filtered_removed

        # ── 兜底：未分类旧模块用文本搜索二次判断 ──────────────────────────
        changed_names_set = {r[0] for r in changed_results}
        explicitly_classified = (
            changed_names_set | set(added_names) | set(removed_names) | set(unchanged_names)
            | set(protected)
        )
        implicit_unchanged: List[str] = []
        implicit_removed:   List[str] = []

        if new_doc_content:
            doc_text_lower = new_doc_content.lower()
            for name in old_index:
                if name in explicitly_classified:
                    continue
                # 通用测试类型：无论文本搜索结果如何，一律保留
                if _is_generic_test(name):
                    implicit_unchanged.append(name)
                    continue
                keyword = (name.replace("模块", "").replace("测试", "")
                           .replace("管理", "").replace("功能", "").strip())
                if bool(keyword) and keyword.lower() in doc_text_lower:
                    implicit_unchanged.append(name)
                else:
                    implicit_removed.append(name)
            if implicit_unchanged:
                logger.info(f"Diff 未分类 → 文本搜索确认保留: {implicit_unchanged}")
            if implicit_removed:
                logger.info(f"Diff 未分类 → 文本搜索确认废弃: {implicit_removed}")

        all_unchanged = list(unchanged_names) + implicit_unchanged + protected
        all_removed   = list(removed_names)   + implicit_removed

        result_modules: List[Dict] = []
        tc_counter = 1

        # 1. unchanged 模块：全部旧用例保留，重新编号
        for name in all_unchanged:
            old_mod = old_index.get(name)
            if not old_mod:
                continue
            active = []
            for c in old_mod.get("cases", []):
                c = dict(c)
                c["id"] = f"TC{tc_counter:03d}"
                c.pop("status", None)
                c.pop("is_new", None)
                c.pop("is_updated", None)
                tc_counter += 1
                active.append(c)
            if active:
                result_modules.append({"name": name, "cases": active})

        # 2. changed 模块：默认保留所有旧用例，只排除 deprecated，再追加新用例
        for (mod_name, old_cases, merge_result) in changed_results:
            if not merge_result:
                continue
            deprecated_ids = set(merge_result.get("deprecated", []))
            new_case_defs  = merge_result.get("new_cases", [])

            old_case_index = {c.get("id", ""): c for c in old_cases}

            active: List[Dict] = []
            dep:    List[Dict] = []

            # 所有旧用例：不在 deprecated_ids 里的全部保留
            for c in old_cases:
                cid = c.get("id", "")
                c = dict(c)
                if cid in deprecated_ids:
                    c["status"] = "deprecated"
                    dep.append(c)
                else:
                    c["id"] = f"TC{tc_counter:03d}"
                    c.pop("status", None)
                    c.pop("is_new", None)
                    c.pop("is_updated", None)
                    tc_counter += 1
                    active.append(c)

            # 新场景用例：标 is_new，追加到 active
            for nc in new_case_defs:
                nc = dict(nc)
                nc["id"] = f"TC{tc_counter:03d}"
                nc["is_new"] = True
                if "expected" in nc and "expected_results" not in nc:
                    nc["expected_results"] = nc.pop("expected")
                tc_counter += 1
                active.append(nc)

            all_cases = active + dep
            if all_cases:
                result_modules.append({"name": mod_name, "cases": all_cases})

        # 3. added 模块：全量新用例，标记 is_new
        for i, mod_result in enumerate(added_results):
            if not mod_result:
                continue
            name = added_names[i] if i < len(added_names) else mod_result.get("name", "")
            active = []
            for c in mod_result.get("cases", []):
                c = dict(c)
                c["id"] = f"TC{tc_counter:03d}"
                c["is_new"] = True
                tc_counter += 1
                active.append(c)
            if active:
                result_modules.append({"name": name, "cases": active})

        # 4. removed 模块：全部旧用例标 deprecated，追加到末尾
        for name in all_removed:
            old_mod = old_index.get(name)
            if not old_mod:
                continue
            dep_cases = []
            for c in old_mod.get("cases", []):
                c = dict(c)
                c["status"] = "deprecated"
                dep_cases.append(c)
            if dep_cases:
                result_modules.append({"name": f"{name}（已废弃）", "cases": dep_cases})

        title = (old_cases_data or {}).get("title", "测试用例集")
        return {"title": title, "modules": result_modules}

    # ------------------------------------------------------------------
    # 用例优化入口
    # ------------------------------------------------------------------
    async def optimize(
        self,
        task_name: str,
        cases_data: Dict[str, Any],
        formats: Optional[List[str]] = None,
        progress_cb=None,
    ) -> Dict[str, Any]:
        """
        分段覆盖度优化：逐模块分析盲区 + 补充性能/兼容性模块（若缺失）。
        """
        if formats is None:
            formats = ["md", "xmind"]

        async def _p(pct: int, stage: str):
            if progress_cb:
                try:
                    await progress_cb(pct, stage)
                except Exception:
                    pass

        existing_modules = cases_data.get("modules", [])
        total_existing = sum(len(m.get("cases", [])) for m in existing_modules)
        await _p(10, f"分析现有 {total_existing} 条用例，开始逐模块补充覆盖盲区...")

        # 检查是否已有性能/兼容性模块
        existing_names = {m.get("name", "") for m in existing_modules}
        has_perf   = any("性能" in n for n in existing_names)
        has_compat = any("兼容" in n for n in existing_names)

        extra_tasks = []
        if not has_perf:
            extra_tasks.append("performance")
        if not has_compat:
            extra_tasks.append("compatibility")

        total_tasks = len(existing_modules) + len(extra_tasks)
        sem = asyncio.Semaphore(2)
        completed = [0]

        async def _progress_done(label: str):
            completed[0] += 1
            await _p(
                10 + int(completed[0] / total_tasks * 75),
                f"已完成 {completed[0]}/{total_tasks}：{label}",
            )

        async def _opt_module(i: int, module: dict):
            async with sem:
                name = module.get("name", f"模块{i+1}")
                await _p(
                    10 + int(i / total_tasks * 75),
                    f"补充模块 {i+1}/{len(existing_modules)}：{name} 的覆盖盲区...",
                )
                new_cases = await self._optimize_one_module(name, module.get("cases", []))
                await _progress_done(name)
                return (module, new_cases)

        async def _gen_missing(dim_type: str):
            async with sem:
                label = "性能测试" if dim_type == "performance" else "兼容性测试"
                await _p(10, f"补充缺失的{label}模块...")
                result = await self._call_llm_for_extra_dimension(dim_type, "", task_name)
                await _progress_done(label)
                return result

        all_tasks = (
            [_opt_module(i, m) for i, m in enumerate(existing_modules)]
            + [_gen_missing(d) for d in extra_tasks]
        )
        all_results = await asyncio.gather(*all_tasks)

        opt_results    = all_results[:len(existing_modules)]
        extra_results  = all_results[len(existing_modules):]

        # 合并：原有用例 + 新增用例，重新统一编号
        counter = 1
        merged_modules = []
        for module, new_cases in opt_results:
            combined = list(module.get("cases", [])) + list(new_cases)
            renamed = []
            for c in combined:
                c = dict(c)
                c["id"] = f"TC{counter:03d}"
                counter += 1
                renamed.append(c)
            merged_modules.append({"name": module["name"], "cases": renamed})

        for extra_mod in extra_results:
            if extra_mod and extra_mod.get("cases"):
                renamed = []
                for c in extra_mod["cases"]:
                    c = dict(c)
                    c["id"] = f"TC{counter:03d}"
                    counter += 1
                    renamed.append(c)
                merged_modules.append({"name": extra_mod["name"], "cases": renamed})

        optimized = {
            "title": cases_data.get("title", task_name),
            "modules": merged_modules,
        }

        await _p(90, "优化完成，正在保存文件...")
        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        result: Dict[str, Any] = {"task_name": task_name, "cases_data": optimized, "files": {}}

        if "md" in formats:
            md_path = await self._save_markdown(optimized, task_name, ts)
            result["files"]["md"] = str(md_path)
        if "xmind" in formats:
            xmind_path = await self._save_xmind(optimized, task_name, ts)
            result["files"]["xmind"] = str(xmind_path)

        new_total = sum(len(m.get("cases", [])) for m in merged_modules)
        result["case_count"] = new_total
        await _p(100, f"优化完成！{total_existing} → {new_total} 条用例")
        logger.info(f"用例优化完成: {task_name}，{total_existing} → {new_total} 条")
        return result

    async def _optimize_one_module(
        self, module_name: str, existing_cases: list
    ) -> list:
        """分析单模块现有用例的覆盖盲区，返回仅新增用例列表。"""
        case_summary = "\n".join(
            f"  - {c.get('id','')}: {c.get('name','')} [{c.get('test_method') or c.get('type','')}]"
            for c in existing_cases[:20]
        )
        system_prompt = (
            "You are a QA coverage expert. Given existing test cases for one module, "
            "identify coverage gaps and output ONLY NEW test cases to add. "
            "Never repeat or copy existing cases. Output ONLY valid JSON."
        )
        prompt = f"""分析「{module_name}」模块现有用例的覆盖盲区，补充缺失场景（3-5条新用例）。

已有用例（{len(existing_cases)}条）：
{case_summary}

逐项检查是否存在盲区：
1. 等价类：是否覆盖全部有效/无效等价类？
2. 边界值：最大值/最小值/空值/特殊字符是否测试？
3. 异常分支：权限不足/重复操作/网络异常是否覆盖？
4. 状态转换：合法/非法状态转换是否完整？

只输出纯JSON，只包含新增用例：
{{
  "new_cases": [
    {{
      "id": "NEW001",
      "name": "用例名称-覆盖盲区描述",
      "priority": "P2",
      "type": "功能测试",
      "test_method": "边界值分析",
      "preconditions": "前置条件",
      "steps": ["1. 操作（含具体数据）"],
      "expected": "预期结果（可量化验证）"
    }}
  ]
}}"""

        try:
            raw = await self._run_claude_subprocess(system_prompt, prompt, timeout_secs=90)
            data = json.loads(raw)
            return data.get("new_cases", [])
        except json.JSONDecodeError as e:
            logger.error(f"模块「{module_name}」优化返回非法 JSON: {e}")
        except Exception as e:
            logger.warning(f"模块「{module_name}」优化失败: {e}")
        return []


    # ------------------------------------------------------------------
    # 保存 Markdown
    # ------------------------------------------------------------------
    async def _save_markdown(
        self, cases_data: Dict, task_name: str, ts: str
    ) -> Path:
        title = cases_data.get("title", task_name)
        modules = cases_data.get("modules", [])
        total = sum(len(m.get("cases", [])) for m in modules)
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            f"# {title}",
            "",
            f"> 生成时间：{now}　　任务：{task_name}",
            "",
            "## 概览",
            "",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 模块数 | {len(modules)} |",
            f"| 用例总数 | {total} |",
            "",
        ]

        for mod in modules:
            mod_name = mod.get("name", "未知模块")
            cases = mod.get("cases", [])
            lines += [f"## {mod_name}", "", f"共 {len(cases)} 个用例", ""]

            for case in cases:
                cid = case.get("id", "")
                name = case.get("name", "")
                priority = case.get("priority", "P1")
                ctype = case.get("type", "功能测试")
                method = case.get("test_method", "")
                pre = case.get("preconditions", "无")
                steps = case.get("steps", [])
                expected = case.get("expected", "")

                method_row = f"| 测试方法 | {method} |\n" if method else ""
                lines += [
                    f"### {cid} {name}",
                    "",
                    f"| 字段 | 内容 |",
                    f"|------|------|",
                    f"| 优先级 | {priority} |",
                    f"| 测试类型 | {ctype} |",
                ]
                if method:
                    lines.append(f"| 测试方法 | {method} |")
                lines += [
                    f"| 前置条件 | {pre} |",
                    "",
                    "**测试步骤：**",
                    "",
                ]
                for i, step in enumerate(steps, 1):
                    lines.append(f"{i}. {step}")
                lines += ["", f"**预期结果：** {expected}", "", "---", ""]

        md_path = self.output_dir / f"cases_{ts}.md"
        md_path.write_text("\n".join(lines), encoding="utf-8")
        return md_path

    # ------------------------------------------------------------------
    # 保存 XMind
    # ------------------------------------------------------------------
    async def _save_xmind(
        self, cases_data: Dict, task_name: str, ts: str
    ) -> Path:
        title = cases_data.get("title", task_name)
        modules = cases_data.get("modules", [])
        now_ts = str(int(time.time() * 1000))

        def topic(label: str, children_xml: str = "") -> str:
            inner = (
                f"<children><topics type=\"attached\">{children_xml}</topics></children>"
                if children_xml else ""
            )
            return (
                f'<topic id="{_uid()}" timestamp="{now_ts}">'
                f"<title>{_xml_escape(label)}</title>"
                f"{inner}</topic>"
            )

        mod_topics = ""
        for mod in modules:
            case_topics = ""
            for case in mod.get("cases", []):
                cid = case.get("id", "")
                name = case.get("name", "")
                priority = case.get("priority", "P1")
                method = case.get("test_method", "")
                pre = case.get("preconditions", "无")
                steps = case.get("steps", [])
                expected = case.get("expected", "")

                step_topics = "".join(
                    topic(f"{i}. {s}") for i, s in enumerate(steps, 1)
                )
                method_topic = topic(f"测试方法：{method}") if method else ""
                detail = (
                    method_topic
                    + topic(f"前置条件：{pre}")
                    + topic("测试步骤", step_topics)
                    + topic(f"预期结果：{expected}")
                )
                case_topics += topic(f"[{priority}] {cid} {name}", detail)

            mod_topics += topic(mod.get("name", "模块"), case_topics)

        root = topic(title, mod_topics)

        content_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            '<xmap-content xmlns="urn:xmind:xmap:xmlns:content:2.0" '
            'xmlns:fo="http://www.w3.org/1999/XSL/Format" '
            'xmlns:svg="http://www.w3.org/2000/svg" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" version="2.0">\n'
            f'  <sheet id="{_uid()}" timestamp="{now_ts}">\n'
            f"    {root}\n"
            f"    <title>Sheet 1</title>\n"
            "  </sheet>\n"
            "</xmap-content>"
        )

        manifest_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            '<manifest xmlns="urn:xmind:xmap:xmlns:manifest:1.0">\n'
            '  <file-entry full-path="content.xml" media-type="text/xml"/>\n'
            '  <file-entry full-path="META-INF/" media-type=""/>\n'
            '  <file-entry full-path="META-INF/manifest.xml" media-type="text/xml"/>\n'
            "</manifest>"
        )

        xmind_path = self.output_dir / f"cases_{ts}.xmind"
        with zipfile.ZipFile(xmind_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("content.xml", content_xml)
            zf.writestr("META-INF/manifest.xml", manifest_xml)

        return xmind_path


ai_case_generator = AICaseGenerator()
