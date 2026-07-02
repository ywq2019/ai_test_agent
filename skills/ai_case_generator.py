"""
AI 测试用例生成器 — 通过本地 claude CLI 调用大模型生成 Markdown / XMind 格式用例文件
"""
import asyncio
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
                cases_data = await self._call_llm_staged(truncated, task_name, modules_info, _p)
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
        await _p(100, f"完成！共生成 {result['case_count']} 条用例")
        logger.info(f"AI 用例生成完成: {result['case_count']} 条，文件: {result['files']}")
        return result

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
    # 通用 claude CLI 子进程调用（不带进度模拟）
    # ------------------------------------------------------------------
    async def _run_claude_subprocess(
        self, system_prompt: str, prompt: str, timeout_secs: int = 90
    ) -> str:
        """启动 claude CLI 子进程，返回 stdout 文本（已剥离 markdown 代码块）。"""
        import shutil, os
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
                _, err_out = await asyncio.wait_for(proc.communicate(), timeout=5)
                err_text = err_out.decode("utf-8", errors="replace").strip()
                if err_text:
                    logger.error(f"claude CLI timeout stderr: {err_text[:300]}")
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
        self, module_name: str, features: list, content: str
    ) -> Dict[str, Any]:
        """为单个功能模块生成测试用例（最多10条）。"""
        features_text = "\n".join(f"  - {f}" for f in features[:6])
        system_prompt = (
            "You are a senior QA engineer. Generate functional test cases for ONE specific module. "
            "Use equivalence partitioning, boundary value analysis, scenario testing, and error guessing. "
            "Output ONLY valid JSON. No markdown."
        )
        prompt = f"""为「{module_name}」模块生成功能测试用例（最多10条）。

该模块功能点：
{features_text}

参考需求（节选）：
---
{content[:2000]}
---

只输出纯JSON：
{{
  "name": "{module_name}",
  "cases": [
    {{
      "id": "TC001",
      "name": "功能点-测试方法-场景（如：登录-等价类-有效账号成功登录）",
      "priority": "P0",
      "type": "功能测试",
      "test_method": "等价类划分",
      "preconditions": "前置条件",
      "steps": ["1. 具体操作（含测试数据）", "2. 操作"],
      "expected": "预期结果（可量化验证）"
    }}
  ]
}}

涵盖：正常主流程(P0/P1) + 边界值 + 异常分支(P2)，ID从TC001编号。"""

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
                result = await self._call_llm_for_module(name, features, content)
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

        logger.info("调用 claude CLI 生成用例...")
        import shutil, os

        claude_bin = shutil.which("claude") or shutil.which("claude.cmd")
        if not claude_bin:
            npm_bin = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm")
            for name in ("claude.cmd", "claude"):
                candidate = os.path.join(npm_bin, name)
                if os.path.exists(candidate):
                    claude_bin = candidate
                    break
        if not claude_bin:
            raise RuntimeError("找不到 claude 命令，请确认 Claude Code 已安装且在 PATH 中")

        import sys
        env = os.environ.copy()

        try:
            proc = await asyncio.create_subprocess_exec(
                claude_bin,
                "--output-format", "text",
                "--no-session-persistence",
                "--input-format", "text",   # 从 stdin 读取 prompt，避免 Windows 编码问题
                "--system-prompt", system_prompt,
                "-p",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            prompt_bytes = prompt.encode("utf-8")

            # 后台定时推送模拟进度 30→88%（AI 生成期间约 60-120s）
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
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=prompt_bytes), timeout=360
                )
            except asyncio.TimeoutError:
                # 超时时杀死子进程并记录 stderr（可能含有 claude CLI 的报错信息）
                try:
                    proc.kill()
                    _, err_out = await asyncio.wait_for(proc.communicate(), timeout=5)
                    err_text = err_out.decode("utf-8", errors="replace").strip()
                    if err_text:
                        logger.error(f"claude CLI stderr on timeout: {err_text[:500]}")
                except Exception:
                    pass
                raise
            finally:
                _done_flag[0] = True
                sim_task.cancel()

        except asyncio.TimeoutError:
            raise RuntimeError("claude CLI 调用超时（360s），请检查网络或 cc-switch 状态")
        except FileNotFoundError:
            raise RuntimeError("找不到 claude 命令，请确认 Claude Code 已安装且在 PATH 中")

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"claude CLI 返回错误 (code {proc.returncode}): {err[:300]}")

        raw = stdout.decode("utf-8", errors="replace").strip()

        # 去掉可能的 markdown 代码块
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
