"""
接口测试用例 AI 生成器 — 直接调用 Anthropic API，不依赖 Claude CLI subprocess
"""
import asyncio
import base64
import json
import re
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Any, Optional, Callable
from loguru import logger
from skills.prompt_loader import get_system, get_prompt, render_user

# sentinel — distinguishes "key not found" from "key exists with value None"
_MISSING = object()


def _get_system_prompt():
    """懒加载接口用例生成的 system prompt（支持修改 YAML 后 reload）。"""
    return get_system("api_case_gen.yaml", "generate_cases")


# 保留向后兼容的模块级常量（部分直接引用 SYSTEM_PROMPT 的地方用到）
@property
def SYSTEM_PROMPT():
    return _get_system_prompt()


def _get_llm_config():
    from tools.config import settings
    return {
        "api_key": settings.AI_API_KEY,
        "base_url": settings.AI_API_URL,
        "model": settings.AI_MODEL or "deepseek-v4-flash",
    }


class ApiCaseGenerator:

    # ─── URL 解析 ────────────────────────────────────────────────────────────

    def _parse_url_input(self, content: str) -> Optional[Dict]:
        stripped = content.strip()
        if not re.match(r'^https?://', stripped):
            return None
        try:
            parsed = urlparse(stripped)
            params = {k: (v[0] if len(v) == 1 else v)
                      for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
            return {"scheme": parsed.scheme, "host": parsed.netloc,
                    "path": parsed.path or "/", "params": params}
        except Exception:
            return None

    def _url_to_description(self, url_info: Dict, project_base_url: str) -> str:
        path = url_info["path"]
        params = url_info["params"]
        inferred_host = f"{url_info['scheme']}://{url_info['host']}"
        lines = [
            f"接口路径: {path}",
            f"请求方法: GET",
            f"Base URL: {project_base_url or inferred_host}",
        ]
        if params:
            lines.append("Query 参数（每条用例的 params 字段必须包含这些 key）：")
            for k, v in params.items():
                lines.append(f"  - {k}: {v}")
        lines += [
            "",
            "要求：",
            "1. 正常流用例的 params 包含所有参数及其示例值",
            "2. 生成缺少鉴权参数（如 passport/token）的异常用例",
            "3. 生成参数边界值用例（ID 为 0、负数、超长字符串等）",
            "4. path 只填相对路径，不含域名",
        ]
        return "\n".join(lines)

    # ─── Curl 解析 ───────────────────────────────────────────────────────────

    def _parse_curl_input(self, content: str) -> Optional[Dict]:
        """解析 curl 命令，提取 method / url / headers / body。

        支持格式：
        - curl 'http://...'  /  curl "http://..."
        - curl -X POST ... -H "..." -d '{...}'
        - curl ... --data-binary '{...}' --compressed
        - 反引号包裹 URL
        - 多行续行符 \\ 和 ^
        - URL 不在第一位（前面有 -H 等参数）
        """
        stripped = content.strip()
        # 必须是 curl 命令开头
        if not re.match(r'^curl\s+', stripped, re.IGNORECASE):
            return None

        # 移除续行符（\ 和 ^）
        clean = re.sub(r'\\\s*\n\s*', ' ', stripped)
        clean = re.sub(r'\^\s*\n\s*', ' ', clean)

        # ── 提取 URL：找最后一个 http(s):// 开头的参数 ──
        # 通用匹配：在引号内或裸露的 http(s):// 链接
        url_match = re.findall(
            r"""(?:["'`])(https?://[^"'\s`]+?)(?:["'`])"""  # "url" 或 'url' 或 `url`
            r"""|(?:["'`])(https?://[^"'\s`]+)$"""            # "url" 在末尾
            r"""|(?<=\s)(https?://[^\s"']+)(?:\s|$)""",      # 裸露 url
            clean
        )
        url_str = None
        for t in url_match:
            for candidate in t:
                if candidate and candidate.startswith(('http://', 'https://')):
                    url_str = candidate.rstrip('"\'`')  # 去掉末尾引号
                    break
        if not url_str:
            return None

        # 解析 URL
        try:
            parsed = urlparse(url_str.rstrip('/\\'))
        except Exception:
            return None

        # ── 提取方法 ──
        method_match = re.search(r'-X\s+(\w+)', clean, re.IGNORECASE)
        # 有 body 时默认 POST，否则 GET
        method = method_match.group(1).upper() if method_match else \
                 ("POST" if "--data" in clean or "--data-binary" in clean or "--data-raw" in clean else "GET")

        # ── 提取 headers ──
        headers = {}
        for m in re.finditer(r"-H\s+(?:\"([^\"]*)\"|'([^']*)'|(\S+))", clean):
            hv = m.group(1) or m.group(2) or m.group(3)
            if ":" in hv:
                k, v = hv.split(":", 1)
                headers[k.strip()] = v.strip()

        # ── 提取 body（-d / --data / --data-raw / --data-binary）──
        body = None
        body_type = "json"
        body_match = re.search(
            r'(--data-binary|--data-raw|--data|-d)\s+'
            r'(?:\$\'([^\']*)\'|'
            r'\$"([^"]*)"|'
            r'"((?:[^"\\]|\\.)*)"|'    # 支持 JSON 内转义引号
            r"\'([^\']*)\'|"
            r'(\S+))',
            clean
        )
        if body_match:
            raw_body = body_match.group(2) or body_match.group(3) or body_match.group(4) or body_match.group(5) or body_match.group(6) or ""
            if raw_body:
                # bash 双引号内的 JSON 会转义 \" → "，先还原
                raw_body = raw_body.replace('\\"', '"')
                try:
                    body = json.loads(raw_body)
                    body_type = "json"
                except (json.JSONDecodeError, Exception):
                    body = raw_body
                    body_type = "raw"
                if body_type == "json" and isinstance(body, dict) and len(body) <= 1:
                    # 单字段 dict 可能是误解析，尝试作为字符串
                    if list(body.values()) == [''] or all(v == 0 for v in body.values() if not isinstance(v, str)):
                        body = raw_body

        # ── URL query params ──
        params = {}
        if parsed.query:
            from urllib.parse import parse_qs
            params = {k: (v[0] if len(v) == 1 else v)
                      for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}

        # ── Content-Type 推断 ──
        ct = headers.get("Content-Type", headers.get("content-type", ""))
        if "x-www-form-urlencoded" in ct:
            body_type = "form"
        elif "json" in ct:
            body_type = "json"

        return {
            "scheme": parsed.scheme,
            "host": parsed.netloc,
            "path": parsed.path or "/",
            "method": method,
            "params": params,
            "headers": headers,
            "body": body,
            "body_type": body_type,
        }

    def _curl_to_description(self, curl_info: Dict, project_base_url: str) -> str:
        """将 curl 解析结果转为结构化的接口描述。"""
        path = curl_info["path"]
        method = curl_info["method"]
        params = curl_info["params"]
        headers = curl_info.get("headers", {})
        body = curl_info.get("body")
        body_type = curl_info.get("body_type", "json")
        inferred_host = f"{curl_info['scheme']}://{curl_info['host']}"

        lines = [
            f"接口路径: {path}",
            f"请求方法: {method}",
            f"Base URL: {project_base_url or inferred_host}",
        ]
        if params:
            lines.append("Query 参数：")
            for k, v in params.items():
                lines.append(f"  - {k}: {v}")
        if headers:
            # 过滤掉通用 header，只保留业务相关
            biz_headers = {k: v for k, v in headers.items()
                          if k.lower() not in ('host', 'user-agent', 'accept', 'accept-encoding',
                                                'connection', 'content-length', 'cache-control')}
            if biz_headers:
                lines.append("请求 Headers：")
                for k, v in biz_headers.items():
                    lines.append(f"  - {k}: {v}")
        if body:
            lines.append(f"请求体（{body_type}）：")
            if isinstance(body, dict):
                lines.append(json.dumps(body, ensure_ascii=False, indent=2))
            else:
                lines.append(str(body)[:500])
        lines += [
            "",
            "要求：",
            f"1. 正常流用例使用上述 {method} 方法和真实参数值",
            "2. 生成鉴权失败用例（Headers 中的 token/passport 置空）",
            "3. 生成参数校验和边界值用例",
            "4. 生成 body 字段缺失/格式错误的用例（如有 body）" if body else "",
        ]
        return "\n".join(lines)

    # ─── 主入口 ──────────────────────────────────────────────────────────────

    async def generate_cases(
        self,
        base_url: str,
        swagger_text: str = "",
        description: str = "",
        curl_text: str = "",
        progress_cb: Optional[Callable] = None,
        project: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        content = swagger_text or description or curl_text
        # ── Curl 优先：粘贴 curl 命令，精确解析 method/url/headers/body ──
        # 支持在任意字段中自动检测 curl（curl_text / description / swagger_text）
        curl_info = self._parse_curl_input(curl_text) if curl_text else None
        if not curl_info:
            curl_info = self._parse_curl_input(description) if description else None
        if not curl_info:
            curl_info = self._parse_curl_input(swagger_text) if swagger_text else None
        is_curl = bool(curl_info)
        user_intent = self._parse_user_intent(description) if description and not swagger_text else {}
        if progress_cb:
            await progress_cb(10, "分析接口文档...")

        # Step 1: 识别接口分组
        url_info = self._parse_url_input(content)
        if is_curl:
            # ── Curl 输入：精确解析，构造单个分组 ──
            structured = self._curl_to_description(curl_info, base_url)
            logger.info(
                f"Curl detected: method={curl_info['method']} path={curl_info['path']}, "
                f"has_body={bool(curl_info.get('body'))}"
            )
            module_name = curl_info["path"].rstrip("/").split("/")[-1] or "接口"
            probe_hint = {
                "path": curl_info["path"],
                "method": curl_info["method"],
                "params": curl_info["params"],
            }
            if curl_info.get("headers"):
                probe_hint["headers"] = curl_info["headers"]
            if curl_info.get("body"):
                probe_hint["body"] = curl_info["body"]
                probe_hint["body_type"] = curl_info.get("body_type", "json")
            groups = [{
                "name": module_name,
                "endpoints": structured,
                "_probe_hint": probe_hint,
            }]
        elif url_info:
            structured = self._url_to_description(url_info, base_url)
            logger.info(f"URL detected: path={url_info['path']}, params={list(url_info['params'].keys())}")
            module_name = url_info["path"].rstrip("/").split("/")[-1] or "接口"
            groups = [{
                "name": module_name,
                "endpoints": structured,
                "_probe_hint": {"path": url_info["path"], "method": "GET", "params": url_info["params"]},
            }]
        else:
            groups = await self._extract_groups(content)
            if not groups:
                groups = [{"name": "API接口", "endpoints": content}]

        if progress_cb:
            await progress_cb(25, f"识别到 {len(groups)} 个接口模块，开始探测真实响应...")

        # Step 2: 预探测 — 获取响应结构，为生成提供上下文
        auth_headers = self._build_auth_headers(project or {})
        global_headers = (project or {}).get("global_headers") or {}
        combined_headers = {**global_headers, **auth_headers}

        await self._probe_groups(base_url, groups, combined_headers, progress_cb)

        if progress_cb:
            await progress_cb(40, "接口探测完成，开始生成测试用例...")

        # Step 3: AI 生成用例
        sem = asyncio.Semaphore(2)
        total = len(groups)
        done = [0]

        async def gen_one(g):
            async with sem:
                cases = await self._generate_for_group(base_url, g, user_intent=user_intent)
                done[0] += 1
                if progress_cb:
                    pct = 40 + int(done[0] / total * 44)   # 40 → 84
                    await progress_cb(pct, f"已生成 {done[0]}/{total} 个模块")
                return cases

        results = await asyncio.gather(*[gen_one(g) for g in groups], return_exceptions=True)

        all_cases = []
        for r in results:
            if isinstance(r, list):
                all_cases.extend(r)

        for i, c in enumerate(all_cases):
            c.setdefault("module", "通用")
            c.setdefault("method", "GET")
            c.setdefault("path", "/")
            if not c.get("name"):
                module = c.get("module") or "API"
                scenario = c.get("scenario") or ""
                c["name"] = f"{module}-{scenario}" if scenario else f"{module}-{c.get('method')} {c.get('path')}"
            c.setdefault("description", "")
            c.setdefault("priority", "P1")
            c.setdefault("headers", {})
            c.setdefault("params", {})
            c.setdefault("body", None)
            c.setdefault("assertions", [{"type": "status_code", "expected": 200}])
            c.setdefault("enabled", True)

        # Step 4: 校验并修正断言（用真实响应数据对齐 json_path）
        if progress_cb:
            await progress_cb(85, "校验断言路径...")
        all_cases = await self._correct_assertions(all_cases, base_url, combined_headers)

        # Step 4.5: ReAct 自检循环 — 执行正常流用例并让 AI 修正不可行的用例
        if progress_cb:
            await progress_cb(88, "AI 自检修正中...")
        try:
            all_cases = await asyncio.wait_for(
                self._self_correct_loop(all_cases, base_url, combined_headers, progress_cb=progress_cb),
                timeout=60,
            )
        except asyncio.TimeoutError:
            logger.warning("[self_correct] 自检超时（60s），跳过")
        except Exception as e:
            logger.warning(f"[self_correct] 自检异常，跳过: {e}")

        # Step 5: 补全描述
        if progress_cb:
            await progress_cb(95, "补全接口描述...")
        all_cases = await self._fill_descriptions(all_cases)

        if progress_cb:
            await progress_cb(100, f"生成完成，共 {len(all_cases)} 条用例")

        logger.info(f"API case generation done: {len(all_cases)} cases")
        return all_cases

    # ─── 分组提取 ─────────────────────────────────────────────────────────────

    async def _extract_groups(self, content: str) -> List[Dict]:
        if not content.strip():
            return []
        prompt = (
            "分析以下接口文档，严格只从文档中提取真实存在的接口模块分组。\n"
            "输出 JSON 数组，每项包含 name（模块名，必须能在文档中找到对应）和 endpoints（该模块的接口描述）。\n"
            "不要编造任何模块名。如果文档中找不到明确的模块，返回空数组 []。\n"
            "只输出 JSON，不要解释。\n\n"
            f"文档内容：\n{content[:3000]}"
        )
        try:
            raw = await self._call_api(get_system("api_case_gen.yaml", "extract_groups"), prompt)
            data = self._extract_json(raw)
            if isinstance(data, list) and data:
                # ── 校验：模块名必须在文档内容中出现 ──
                content_lower = content.lower()
                valid = []
                for g in data:
                    if not isinstance(g, dict):
                        continue
                    name = g.get("name", "")
                    # 模块名为中文时拆分逐词检查，英文时直接匹配
                    if any(ch >= '\u4e00' and ch <= '\u9fff' for ch in name):
                        # 中文模块名：每个字独立检查是否在文档中出现（容忍少量不在的）
                        chars_in = sum(1 for c in name if c in content)
                        ratio = chars_in / len(name) if name else 0
                        if ratio >= 0.6:
                            valid.append(g)
                        else:
                            logger.warning(f"Dropped hallucinated group: '{name}' (only {ratio:.0%} chars in content)")
                    else:
                        # 英文模块名：直接检查子串
                        if name.lower() in content_lower:
                            valid.append(g)
                        else:
                            logger.warning(f"Dropped hallucinated group: '{name}' (not found in content)")
                if valid:
                    return valid
                logger.warning(f"All {len(data)} groups filtered out as hallucinations, falling back to single group")
            return data[:30] if data else []
        except Exception as e:
            logger.warning(f"Group extraction failed: {e}")
        return []

    # ─── 认证头构建 ───────────────────────────────────────────────────────────

    def _build_auth_headers(self, project: Dict) -> Dict:
        auth_type = project.get("auth_type", "none")
        cfg = project.get("auth_config") or {}
        if auth_type == "bearer":
            token = cfg.get("token", "")
            return {"Authorization": f"Bearer {token}"} if token else {}
        elif auth_type == "api_key" and cfg.get("in") == "header":
            return {cfg.get("key", "X-API-Key"): cfg.get("value", "")}
        elif auth_type == "basic":
            cred = f"{cfg.get('username', '')}:{cfg.get('password', '')}".encode()
            return {"Authorization": "Basic " + base64.b64encode(cred).decode()}
        return {}

    # ─── 接口探测（预探测） ───────────────────────────────────────────────────

    def _extract_probe_candidates(self, group: Dict) -> List[Dict]:
        """从 group 文本中提取可探测的 {path, method, params} 候选。"""
        if "_probe_hint" in group:
            return [group["_probe_hint"]]

        text = str(group.get("endpoints", ""))
        results = []
        patterns = [
            (r'\b(GET|POST|PUT|DELETE|PATCH)\b[\s:]+(/[^\s\n,;`"\']+)', 2),
            (r'(?:接口路径|path)[：:\s]+(/[^\s\n,;`"\']+)', 1),
            (r'"path"\s*:\s*"(/[^"]+)"', 1),
            (r'`(/[^`\s]+)`', 1),
        ]
        seen_paths: set = set()
        for pat, ngroups in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                if ngroups == 2:
                    method = m.group(1).upper()
                    path = m.group(2).split("?")[0].rstrip(".,;")
                else:
                    method = "GET"
                    path = m.group(1).split("?")[0].rstrip(".,;")
                if path not in seen_paths and path.startswith("/"):
                    seen_paths.add(path)
                    results.append({"path": path, "method": method, "params": {}})
            if results:
                break
        return results[:2]

    async def _probe_endpoint(
        self,
        base_url: str,
        path: str,
        method: str,
        params: Dict,
        headers: Dict,
        body: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """向目标接口发出真实 HTTP 请求，返回响应摘要。"""
        import httpx
        url = base_url.rstrip("/") + path
        try:
            req_kwargs: dict = {"headers": headers or {}, "params": params or {}}
            if method in ("POST", "PUT", "PATCH") and body:
                req_kwargs["json"] = body
            async with httpx.AsyncClient(verify=False, timeout=10) as client:
                resp = await client.request(method, url, **req_kwargs)
            status = resp.status_code
            try:
                json_body = resp.json()
                json_paths = self._extract_json_paths(json_body)
                logger.info(f"Probe {method} {url} → {status}, {len(json_paths)} json_paths")
                return {"status_code": status, "json": json_body, "json_paths": json_paths}
            except Exception:
                preview = resp.text[:600]
                logger.info(f"Probe {method} {url} → {status}, non-JSON body")
                return {"status_code": status, "text": preview, "json_paths": []}
        except Exception as e:
            logger.info(f"Probe failed {method} {url}: {e}")
            return None

    def _extract_json_paths(
        self, data: Any, prefix: str = "$", max_depth: int = 4, _depth: int = 0
    ) -> List[Dict]:
        """递归提取 JSON 路径和示例值，供断言生成使用。"""
        if _depth >= max_depth:
            return []
        paths = []
        if isinstance(data, dict):
            for k, v in list(data.items())[:20]:
                p = f"{prefix}.{k}"
                if isinstance(v, (dict, list)):
                    paths.append({"path": p, "value": None, "type": type(v).__name__})
                    paths.extend(self._extract_json_paths(v, p, max_depth, _depth + 1))
                else:
                    paths.append({"path": p, "value": v, "type": type(v).__name__})
        elif isinstance(data, list) and data:
            p = f"{prefix}[0]"
            first = data[0]
            if isinstance(first, (dict, list)):
                paths.append({"path": p, "value": None, "type": type(first).__name__})
                paths.extend(self._extract_json_paths(first, p, max_depth, _depth + 1))
            else:
                paths.append({"path": p, "value": first, "type": type(first).__name__})
        return paths[:40]

    async def _probe_groups(
        self,
        base_url: str,
        groups: List[Dict],
        headers: Dict,
        progress_cb: Optional[Callable],
    ) -> None:
        """为每个 group 预探测主接口，结果挂到 group['_probe']。"""
        total = len(groups)
        for i, g in enumerate(groups):
            candidates = self._extract_probe_candidates(g)
            probe = None
            for cand in candidates:
                # 合并项目级 header 和 curl 专用 header
                probe_headers = dict(headers)
                hint_headers = (g.get("_probe_hint") or {}).get("headers", {})
                if hint_headers:
                    probe_headers.update(hint_headers)
                probe = await self._probe_endpoint(
                    base_url, cand["path"], cand["method"],
                    cand.get("params", {}), probe_headers,
                    body=(g.get("_probe_hint") or {}).get("body"),
                )
                if probe:
                    break
            g["_probe"] = probe
            if progress_cb:
                pct = 25 + int((i + 1) / total * 14)
                status_str = str(probe["status_code"]) if probe else "失败"
                await progress_cb(pct, f"探测接口 {i+1}/{total} → HTTP {status_str}")

    # ─── 用例生成 ─────────────────────────────────────────────────────────────

    # 兜底场景列表（AI 分析失败时使用）
    _DEFAULT_SCENES = [
        "正常流-所有参数正确",
        "鉴权失败-passport为空",
        "鉴权失败-token无效",
        "缺少必填参数",
        "边界值-数值参数为0",
        "边界值-数值参数为负数",
    ]

    async def _analyze_scenes(self, group: Dict) -> List[str]:
        """
        根据接口信息让 AI 自主规划测试场景列表。
        prompt 极短，max_tokens=600，只输出场景名 JSON 数组。
        失败时返回默认场景列表。
        """
        name = group.get("name", "API")
        probe_hint = group.get("_probe_hint", {})
        real_params = probe_hint.get("params", {})
        path = probe_hint.get("path", "/")
        method = probe_hint.get("method", "GET")

        # 只传参数 key 列表，不传值（避免 token 过多）
        param_keys = list(real_params.keys()) if real_params else []

        prompt = (
            f"API: {method} {path}, module: {name}, params: {', '.join(param_keys)}\n"
            "List the test scenarios needed for this API as a JSON array of Chinese strings.\n"
            "Cover: normal flow, auth failures, missing required params, invalid types, "
            "boundary values, and pagination/sort/filter when applicable.\n"
            "Decide the number based on the API's real complexity: more params/branches "
            "=> more scenarios, simple read-only query => fewer. "
            "Do not pad with redundant scenarios. Output JSON array only."
        )
        try:
            from tools.llm_client import call_llm
            raw = await call_llm(
                "Output a JSON array of Chinese test scenario names only. No explanation.",
                prompt,
                max_tokens=900,
                timeout_secs=30,
            )
            scenes = self._extract_json(raw)
            if isinstance(scenes, list) and scenes and all(isinstance(s, str) for s in scenes):
                # 去重，仅保留防御性上限防止 LLM 异常输出过多
                seen: set = set()
                uniq = [s for s in scenes if not (s in seen or seen.add(s))]
                logger.info(f"AI planned {len(uniq)} scenes for '{name}': {uniq}")
                return uniq[:30]
        except Exception as e:
            logger.warning(f"Scene analysis failed for '{name}': {e}")
        return self._DEFAULT_SCENES

    async def _generate_for_group(self, base_url: str, group: Dict, user_intent: dict = None) -> List[Dict]:
        """
        两阶段并行生成：
          1. AI 分析接口功能，自主规划测试场景（快速，~500ms）
          2. 并行为每个场景各生成 1 条用例（4 路并发）
        """
        name = group.get("name", "API")

        # 根据用户意图确定场景列表
        intent = user_intent or {}
        count_hint = intent.get("count")
        scenes_hint = intent.get("scenes")

        if scenes_hint:
            scenes = scenes_hint
            if count_hint and count_hint < len(scenes):
                scenes = scenes[:count_hint]
        elif count_hint:
            scenes = self._DEFAULT_SCENES[:count_hint]
        else:
            # AI 自主分析场景
            scenes = await self._analyze_scenes(group)

        # 并行生成，每个场景独立一次 LLM 调用
        sem = asyncio.Semaphore(4)

        async def gen_one(scenario: str) -> Optional[Dict]:
            async with sem:
                return await self._generate_single_case(base_url, group, scenario)

        results = await asyncio.gather(
            *[gen_one(s) for s in scenes],
            return_exceptions=True,
        )

        cases = [r for r in results if isinstance(r, dict) and r.get("path")]
        if not cases and scenes:
            # ── LLM 全部失败，用模板兜底生成基础用例 ──
            probe = group.get("_probe") or group.get("_probe_hint") or {}
            fallback_path = probe.get("path", "/")
            fallback_method = probe.get("method", "GET")
            fallback_params = probe.get("params", {})
            fallback = {
                "name": f"{name}-正常流",
                "module": name,
                "method": fallback_method,
                "path": fallback_path,
                "params": fallback_params,
                "headers": {},
                "body": None,
                "assertions": [{"type": "status_code", "expected": 200}],
                "description": f"{name}接口正常流测试（AI生成失败，使用模板兜底，请检查大模型配置后重试）",
                "priority": "P1",
                "enabled": True,
            }
            cases = [fallback]
            logger.warning(f"All {len(scenes)} scenes failed for '{name}', using template fallback")
        logger.info(f"Generated {len(cases)}/{len(scenes)} cases for module '{name}'")
        return cases

    async def _generate_single_case(
        self,
        base_url: str,
        group: Dict,
        scenario: str,
    ) -> Optional[Dict]:
        """
        只生成 1 条用例的 LLM 调用。
        prompt 极短（约 300-500 token），reasoner 模型思考约 200 token，
        输出单条 JSON 对象约 150-200 token，max_tokens=800 完全够用。
        """
        name = group.get("name", "API")
        endpoints = group.get("endpoints", group.get("description", ""))
        if isinstance(endpoints, list):
            endpoints = json.dumps(endpoints, ensure_ascii=False)

        # 从 probe_hint 提取真实参数值（URL 输入时有完整参数值）
        probe_hint = group.get("_probe_hint", {})
        real_params = probe_hint.get("params", {})

        # 构建参数描述：有真实值的带上真实值，没有的只列 key
        if real_params:
            # 鉴权类参数识别
            auth_keys = {'token', 'passport', 'access_token', 'edu24ol_token',
                         'authorization', 'auth', 'api_key', 'apikey', 'secret'}
            is_auth_fail = "鉴权" in scenario or "auth" in scenario.lower()

            param_parts = []
            for k, v in real_params.items():
                is_auth = any(ak in k.lower() for ak in auth_keys)
                if is_auth:
                    # 鉴权失败场景：填空；正常流：用真实值
                    val = "" if is_auth_fail else str(v)
                else:
                    val = str(v)
                param_parts.append(f"{k}={val}")
            params_line = ", ".join(param_parts)
        else:
            # 非 URL 输入，只有参数名
            import re as _re
            endpoints_str = str(endpoints)
            keys = _re.findall(r'- (\w+):', endpoints_str[:500])
            params_line = ", ".join(keys) if keys else endpoints_str[:200]

        path = probe_hint.get("path", "/")
        method = probe_hint.get("method", "GET")

        # 从 probe_hint 提取请求体与业务 headers（curl 输入时存在）
        real_body = probe_hint.get("body")
        real_body_type = probe_hint.get("body_type", "json")
        body_desc = ""
        if real_body is not None:
            body_str = json.dumps(real_body, ensure_ascii=False) if isinstance(real_body, (dict, list)) else str(real_body)
            body_desc = f"Body({real_body_type}): {body_str}"

        hint_headers = probe_hint.get("headers") or {}
        biz_headers = {k: v for k, v in hint_headers.items()
                       if k.lower() not in ('host', 'user-agent', 'accept', 'accept-encoding',
                                             'connection', 'content-length', 'cache-control',
                                             'content-type')}
        headers_desc = "Headers: " + json.dumps(biz_headers, ensure_ascii=False) if biz_headers else ""

        # ── 将预探测结果注入 prompt，让 LLM 基于真实响应生成断言 ──
        probe = group.get("_probe")
        probe_section = self._build_probe_section(probe) if probe else ""

        prompt_parts = []
        if probe_section:
            prompt_parts.append(probe_section)

        info_lines = [
            f"Generate 1 test case. API: {method} {path}.",
            f"Module: {name}. Base URL: {base_url}.",
            f"Params: {params_line}",
        ]
        if body_desc:
            info_lines.append(body_desc)
        if headers_desc:
            info_lines.append(headers_desc)
        info_lines.append(f"Scenario: {scenario}")
        info_lines.append(
            "Rules: name=中文(接口功能-场景), all params required, "
            "use exact param values above, auth failure params set to empty string, "
            "include the request body for POST/PUT/PATCH requests."
        )
        prompt_parts.append("\n".join(info_lines))
        prompt = "\n".join(prompt_parts)
        try:
            raw = await self._call_api(_get_system_prompt(), prompt)
            # 优先解析为单个对象，其次尝试取数组第一条
            case = self._extract_json_obj(raw)
            if not case:
                arr = self._extract_json(raw)
                if isinstance(arr, list) and arr:
                    case = arr[0]
            # ── 容错补全：缺失字段从 probe_hint 自动填充 ──
            if case and isinstance(case, dict):
                if not case.get("path"):
                    case["path"] = probe_hint.get("path", path)
                if not case.get("method"):
                    case["method"] = probe_hint.get("method", method)
                # 始终用 group 名覆盖 module，防止 LLM 编造其它模块
                if name:
                    case["module"] = name
                # name 缺失时按「模块-场景」命名，避免落到 TC00x 编号兜底
                if not case.get("name"):
                    case["name"] = f"{name}-{scenario}"
                if not case.get("body_type") and case.get("body"):
                    case["body_type"] = "json"
                # POST/PUT/PATCH 正常流：LLM 漏掉 body 时回填 curl 真实请求体
                if (method in ("POST", "PUT", "PATCH") and real_body is not None
                        and not case.get("body") and "正常" in scenario):
                    case["body"] = real_body
                    if not case.get("body_type"):
                        case["body_type"] = real_body_type
                if case.get("path"):
                    return case
            logger.warning(f"Single case parse failed for '{name}/{scenario}', raw[:200]: {raw[:200]}")
        except Exception as e:
            logger.warning(f"Single case gen failed for '{name}/{scenario}': {e}")
        return None

    def _build_probe_section(self, probe: Optional[Dict]) -> str:
        """将预探测结果格式化为 prompt 上下文段落。"""
        if not probe:
            return ""
        status = probe.get("status_code", "?")
        json_paths = probe.get("json_paths") or []
        json_body = probe.get("json")

        if not json_paths and not json_body:
            if probe.get("text"):
                return (
                    f"\n\n【真实接口响应预览（HTTP {status}）】\n"
                    f"{probe['text'][:400]}\n"
                )
            return ""

        path_lines = []
        for p in json_paths[:10]:
            val = p.get("value")
            if val is None:
                path_lines.append(f'  {p["path"]}')
            else:
                path_lines.append(f'  {p["path"]} = {repr(val)}')

        body_preview = ""  # 不再包含完整响应体，避免 reasoner 模型思考量爆炸

        return (
            f"\n\n【真实接口正常流响应（HTTP {status}）】\n"
            f"响应 JSON 字段路径及示例值：\n"
            + "\n".join(path_lines)
            + body_preview
            + "\n\n断言要求：\n"
            "- 正常流用例的 assertions 必须包含至少2条 json_path 断言\n"
            "- json_path 的 path 字段必须从上方列出的真实字段路径中选取\n"
            "- json_path 的 expected 值必须与上方真实响应中的对应值完全一致\n"
            "- 对关键业务字段（如 code、status、success 等）必须断言\n"
        )

    def _parse_user_intent(self, description: str) -> dict:
        """从用户自然语言描述里解析生成意图。
        返回 {"count": int|None, "scenes": list|None}
        例：
          "生成一条正向用例" → {"count": 1, "scenes": ["正向"]}
          "生成3条用例"      → {"count": 3, "scenes": None}
          "只要正向和边界值" → {"count": None, "scenes": ["正向", "边界值"]}
          "生成完整用例"     → {}
        """
        import re
        result = {}

        # ── 解析数量 ──────────────────────────────────────────────────────────
        CN_NUM = {"一": 1, "两": 2, "三": 3, "四": 4, "五": 5,
                  "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        # 匹配 "生成X条" / "只要X条" / "X条用例"
        m = re.search(r'(\d+|[一两三四五六七八九十])\s*条', description)
        if m:
            raw = m.group(1)
            result["count"] = int(raw) if raw.isdigit() else CN_NUM.get(raw, 1)

        # ── 解析场景 ──────────────────────────────────────────────────────────
        scene_map = {
            # 正向/正常流
            "正向": "正向流用例",
            "正常": "正向流用例",
            "正常流": "正向流用例",
            "主流程": "正向流用例",
            "happy path": "正向流用例",
            # 异常/负向
            "异常": "异常场景用例",
            "负向": "异常场景用例",
            "错误": "异常场景用例",
            "失败": "异常场景用例",
            # 边界值
            "边界": "边界值用例",
            "边界值": "边界值用例",
            # 鉴权
            "鉴权": "鉴权场景用例",
            "权限": "鉴权场景用例",
            "认证": "鉴权场景用例",
        }
        matched_scenes = []
        seen = set()
        for kw, label in scene_map.items():
            if kw.lower() in description.lower() and label not in seen:
                matched_scenes.append(label)
                seen.add(label)

        if matched_scenes:
            result["scenes"] = matched_scenes

        return result

    # ─── 断言校验与修正 ───────────────────────────────────────────────────────

    def _jsonpath_get_safe(self, data: Any, path: str) -> Any:
        """执行 JSONPath 查询，找不到返回 _MISSING（区分 None 值）。"""
        try:
            parts = path.lstrip("$").lstrip(".").split(".")
            cur = data
            for part in parts:
                if not part:
                    continue
                if "[" in part:
                    key, idx_str = part.split("[", 1)
                    idx = int(idx_str.rstrip("]"))
                    if key:
                        cur = cur[key]
                    cur = cur[idx]
                else:
                    cur = cur[part]
            return cur
        except (KeyError, TypeError, IndexError, ValueError):
            return _MISSING

    async def _correct_assertions(
        self,
        cases: List[Dict],
        base_url: str,
        headers: Dict,
    ) -> List[Dict]:
        """
        校验并修正每条用例的断言：
        - 对正常流用例：用真实响应重新校验 json_path 断言，删除无效路径，补全缺失的关键字段断言
        - 对异常流用例：保留 status_code / response_time，移除 json_path（异常响应结构不固定）
        """
        # 按 (method, path) 分组
        path_map: Dict[tuple, List[Dict]] = {}
        for c in cases:
            key = (c.get("method", "GET").upper(), c.get("path", "/"))
            path_map.setdefault(key, []).append(c)

        sem = asyncio.Semaphore(3)

        async def correct_one(method_path, group_cases):
            method, path = method_path
            async with sem:
                await self._correct_group(base_url, method, path, group_cases, headers)

        await asyncio.gather(*[
            correct_one(mp, gc) for mp, gc in path_map.items()
        ], return_exceptions=True)

        return cases

    async def _correct_group(
        self,
        base_url: str,
        method: str,
        path: str,
        group_cases: List[Dict],
        headers: Dict,
    ) -> None:
        """对单个 (method, path) 下的所有用例修正断言。"""
        # 找正常流用例（用它的 params/body 来探测真实响应）
        normal_case = next(
            (c for c in group_cases
             if re.search(r'正常|normal|happy|success', c.get("scenario", ""), re.IGNORECASE)),
            group_cases[0],
        )

        probe = await self._probe_endpoint(
            base_url, path, method,
            normal_case.get("params") or {},
            headers,
            normal_case.get("body") if method in ("POST", "PUT", "PATCH") else None,
        )

        if not probe or not probe.get("json"):
            # 探测失败：只保留 status_code / response_time，移除不可验证的 json_path
            for c in group_cases:
                c["assertions"] = [
                    a for a in (c.get("assertions") or [])
                    if a.get("type") in ("status_code", "response_time")
                ]
            logger.info(f"Probe failed for {method} {path}, stripped json_path assertions")
            return

        real_json = probe["json"]
        real_status = probe["status_code"]
        json_paths = probe.get("json_paths", [])

        # 只在 2xx 时用真实状态码更新正常流
        is_success = 200 <= real_status < 300

        for case in group_cases:
            scenario = case.get("scenario", "")
            is_normal = bool(re.search(r'正常|normal|happy|success', scenario, re.IGNORECASE))

            new_assertions: List[Dict] = []
            has_valid_jsonpath = False

            for a in (case.get("assertions") or []):
                atype = a.get("type")

                if atype == "status_code":
                    if is_normal and is_success:
                        new_assertions.append({"type": "status_code", "expected": real_status})
                    else:
                        new_assertions.append(a)

                elif atype == "response_time":
                    new_assertions.append(a)

                elif atype == "json_path":
                    if not is_normal:
                        # 异常流：仅保留通用错误字段（code/msg/message/error）的断言
                        _common_err_fields = ('$.code', '$.msg', '$.message', '$.error', '$.status', '$.success')
                        if a["path"] in _common_err_fields:
                            new_assertions.append(a)
                        continue
                    # 校验路径是否在真实响应中存在
                    actual = self._jsonpath_get_safe(real_json, a["path"])
                    if actual is _MISSING:
                        logger.info(
                            f"  Drop invalid json_path '{a['path']}' "
                            f"for {method} {path} (not in real response)"
                        )
                        continue
                    # 路径有效：用真实值覆盖 expected
                    new_assertions.append({
                        "type": "json_path",
                        "path": a["path"],
                        "expected": actual,
                        "match_type": "equals",
                    })
                    has_valid_jsonpath = True

            # 正常流且没有有效 json_path → 从真实响应自动补全
            if is_normal and not has_valid_jsonpath and json_paths:
                added = 0
                for jp in json_paths:
                    val = jp.get("value")
                    # 只取叶子节点（非 dict/list）且值不为 None
                    if val is None or isinstance(val, (dict, list)):
                        continue
                    new_assertions.append({
                        "type": "json_path",
                        "path": jp["path"],
                        "expected": val,
                        "match_type": "equals",
                    })
                    added += 1
                    if added >= 3:
                        break
                if added:
                    logger.info(
                        f"  Auto-added {added} json_path assertions "
                        f"for {method} {path} from real response"
                    )

            case["assertions"] = new_assertions

    # ─── ReAct 自检循环 ───────────────────────────────────────────────────────

    async def _self_correct_loop(
        self,
        cases: List[Dict],
        base_url: str,
        headers: Dict,
        max_rounds: int = 2,
        progress_cb: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        ReAct 自检：对正常流用例执行一次真实请求，
        若结果与预期偏差明显，调用 AI 修正用例参数 / body / 断言。

        最多执行 max_rounds 轮，每轮只处理仍有问题的用例。
        无法联通的接口（网络错误）跳过，不计入失败。

        修正维度：
          - 请求 body 字段名 / 类型错误（AI 基于响应修正）
          - 状态码预期错误（如生成了 200 但实际返回 422 参数校验失败）
          - 无效的 json_path 断言（断言路径在响应中不存在）
        """
        import httpx

        # 只处理正常流用例（scenario 含正常/normal/happy/success）
        normal_cases = [
            c for c in cases
            if re.search(r'正常|normal|happy|success', c.get("scenario", ""), re.IGNORECASE)
        ]
        if not normal_cases:
            # 没有明确标注正常流的，取每个 path 第一条用例
            seen: set = set()
            for c in cases:
                key = (c.get("method", "GET"), c.get("path", "/"))
                if key not in seen:
                    seen.add(key)
                    normal_cases.append(c)

        # 限制：最多 self-correct 10 条，避免超时
        normal_cases = normal_cases[:10]

        problem_cases = normal_cases
        for round_idx in range(max_rounds):
            if not problem_cases:
                break

            sem = asyncio.Semaphore(3)
            fixed_count = [0]

            async def verify_and_fix(case: Dict) -> Dict:
                async with sem:
                    return await self._verify_one_case(case, base_url, headers, fixed_count)

            results = await asyncio.gather(
                *[verify_and_fix(c) for c in problem_cases],
                return_exceptions=True,
            )

            # 收集仍有问题的用例进入下一轮
            next_problem = []
            for r in results:
                if isinstance(r, dict) and r.get("_self_correct_failed"):
                    next_problem.append(r)

            logger.info(
                f"[self_correct] round {round_idx + 1}: "
                f"checked {len(problem_cases)}, fixed {fixed_count[0]}, "
                f"still problematic {len(next_problem)}"
            )
            problem_cases = next_problem

        # 清理内部标记
        for c in cases:
            c.pop("_self_correct_failed", None)

        return cases

    async def _verify_one_case(
        self,
        case: Dict,
        base_url: str,
        headers: Dict,
        fixed_count: List[int],
    ) -> Dict:
        """
        执行单条用例的真实请求，若结果异常则调用 AI 修正。
        返回修正后的 case（若无法修正则打上 _self_correct_failed 标记）。
        """
        import httpx
        method = case.get("method", "GET").upper()
        path = case.get("path", "/")
        url = base_url.rstrip("/") + path

        req_headers = {**headers, **(case.get("headers") or {})}
        params = case.get("params") or {}
        body = case.get("body") if method in ("POST", "PUT", "PATCH") else None

        try:
            async with httpx.AsyncClient(verify=False, timeout=15) as client:
                resp = await client.request(
                    method, url,
                    headers=req_headers,
                    params=params,
                    json=body if body else None,
                )
            actual_status = resp.status_code
            try:
                actual_body = resp.json()
            except Exception:
                actual_body = resp.text[:500]

        except Exception as e:
            # 网络错误：跳过，不算失败
            logger.info(f"[self_correct] skip {method} {path}: {e}")
            return case

        # 判断是否需要修正
        expected_status = next(
            (a["expected"] for a in (case.get("assertions") or [])
             if a.get("type") == "status_code"),
            200,
        )
        status_ok = (actual_status == expected_status)

        # 响应 4xx 且预期 2xx：明显有问题，需修正
        needs_fix = (not status_ok and actual_status >= 400 and expected_status < 300)

        # ── json_path 断言路径存在性检查 ──
        json_path_issues = False
        if not needs_fix and isinstance(actual_body, dict):
            for a in (case.get("assertions") or []):
                if a.get("type") != "json_path":
                    continue
                jp = a["path"]
                # 检查路径是否在真实响应中存在
                val = self._jsonpath_get_safe(actual_body, jp)
                if val is _MISSING:
                    logger.info(
                        f"[self_correct] json_path '{jp}' missing in response "
                        f"for {method} {path}"
                    )
                    json_path_issues = True
                    break  # 至少有一个路径不匹配就需要修正

        needs_fix = needs_fix or json_path_issues

        if not needs_fix:
            # 状态码 + json_path 都符合预期，不需要修正
            return case

        # ── 调用 AI 修正 ──────────────────────────────────────────────────────
        fix_prompt = (
            f"以下接口用例执行后返回了非预期结果，请修正用例，使其能成功请求并通过断言。\n\n"
            f"接口信息：\n"
            f"  方法: {method}\n"
            f"  路径: {path}\n"
            f"  完整URL: {url}\n\n"
            f"原用例（JSON）：\n{json.dumps(case, ensure_ascii=False, indent=2)}\n\n"
            f"真实响应：\n"
            f"  状态码: {actual_status}\n"
            f"  响应体: {json.dumps(actual_body, ensure_ascii=False)[:800] if isinstance(actual_body, (dict, list)) else str(actual_body)[:800]}\n\n"
            f"请分析原因并输出修正后的完整用例 JSON（只输出 JSON，不要解释）。\n"
            f"修正规则：\n"
            f"1. 若响应体包含字段说明，据此修正 body / params 的字段名和类型\n"
            f"2. 若真实接口返回 {actual_status} 是正常行为（如登录接口未提供 token 返回 401），"
            f"则修改 assertions 中的 status_code expected 为 {actual_status}\n"
            f"3. 保持用例其他字段不变"
        )

        try:
            system = "你是接口测试专家。请根据接口真实响应修正测试用例，只输出 JSON，不要任何解释。"
            raw = await self._call_api(system, fix_prompt)
            fixed = self._extract_json_obj(raw)
            if fixed and isinstance(fixed, dict) and fixed.get("path"):
                # 用修正后的用例覆盖原用例（原地修改）
                case.update(fixed)
                fixed_count[0] += 1
                logger.info(f"[self_correct] fixed {method} {path}: {actual_status} → expected updated")
                return case
        except Exception as e:
            logger.warning(f"[self_correct] AI fix failed for {method} {path}: {e}")

        # AI 修正失败，标记留到下一轮
        case["_self_correct_failed"] = True
        return case

    # ─── LLM 调用 ─────────────────────────────────────────────────────────────

    async def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        from tools.llm_client import call_llm
        # max_tokens=2048：reasoner 思考约 500 token，输出约 500 token，JSON mode 更稳定
        text = await call_llm(
            system_prompt, user_prompt,
            max_tokens=2048, timeout_secs=60,
            response_format={"type": "json_object"},
        )
        logger.info(f"API response received, len={len(text)}")
        return text

    # ─── JSON 解析 ────────────────────────────────────────────────────────────

    def _extract_json(self, text: str):
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except Exception:
                pass
        m = re.search(r'(\[[\s\S]*\])', text)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        return []

    def _extract_json_obj(self, text: str) -> dict:
        text = text.strip()
        try:
            r = json.loads(text)
            if isinstance(r, dict):
                return r
        except Exception:
            pass
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if m:
            try:
                r = json.loads(m.group(1).strip())
                if isinstance(r, dict):
                    return r
            except Exception:
                pass
        m = re.search(r'(\{[\s\S]*\})', text)
        if m:
            try:
                r = json.loads(m.group(1))
                if isinstance(r, dict):
                    return r
            except Exception:
                pass
        return {}

    # ─── 描述补全 ─────────────────────────────────────────────────────────────

    def _infer_description(self, path: str, method: str = "GET") -> str:
        verb_map = {"GET": "查询", "POST": "创建", "PUT": "更新", "DELETE": "删除", "PATCH": "修改"}
        verb = verb_map.get(method.upper(), "操作")
        parts = [p for p in path.strip("/").split("/") if p and not p.startswith("{")]
        noun = parts[-1].replace("-", "").replace("_", "") if parts else "资源"
        return f"{noun}{verb}接口"

    async def _fill_descriptions(self, cases: List[Dict]) -> List[Dict]:
        path_map: dict = {}
        for c in cases:
            p = c.get("path", "/")
            path_map.setdefault(p, []).append(c)

        missing_paths = []
        for path, cs in path_map.items():
            existing = next(
                (c["description"] for c in cs if c.get("description", "").strip()), ""
            )
            if existing:
                for c in cs:
                    c["description"] = existing
            else:
                missing_paths.append((path, cs[0].get("method", "GET")))

        if not missing_paths:
            return cases

        logger.info(f"Filling descriptions for {len(missing_paths)} paths via AI")
        paths_text = "\n".join(f"- {p}" for p, _ in missing_paths)
        prompt = (
            "为以下 API 路径各生成一句简洁的中文接口功能描述（10字以内），"
            "严格只输出一个 JSON 对象，key 为路径字符串，value 为描述字符串，不要任何其他内容。\n\n"
            f"路径列表：\n{paths_text}"
        )
        try:
            raw = await self._call_api(get_system("api_case_gen.yaml", "fill_descriptions"), prompt)
            desc_map = self._extract_json_obj(raw)
            logger.info(f"AI description map: {desc_map}")
            for path, cs in path_map.items():
                desc = desc_map.get(path, "").strip()
                if not desc:
                    for k, v in desc_map.items():
                        if k in path or path.endswith(k):
                            desc = v.strip()
                            break
                if desc:
                    for c in cs:
                        c["description"] = desc
                else:
                    fallback = self._infer_description(path, cs[0].get("method", "GET"))
                    for c in cs:
                        c["description"] = fallback
        except Exception as e:
            logger.warning(f"AI description fill failed: {e}, using fallback inference")
            for path, method in missing_paths:
                fallback = self._infer_description(path, method)
                for c in path_map[path]:
                    c["description"] = fallback

        return cases


api_case_generator = ApiCaseGenerator()


# ─────────────────────────────────────────────────────────────────────────────
# 代码分析器（单独类，不依赖项目配置）
# ─────────────────────────────────────────────────────────────────────────────

LANG_HINTS = {
    "java":   "Java (Spring Boot / Spring MVC)",
    "python": "Python (FastAPI / Flask / Django)",
    "go":     "Go (Gin / Echo / net/http)",
    "node":   "Node.js (Express / Koa / NestJS)",
    "php":    "PHP (Laravel / ThinkPHP)",
    "other":  "其他语言",
}


class ApiCodeAnalyzer:
    """
    方案二核心：从接口实现代码生成用例 / 与需求文档对比找差异。
    """

    async def _call_llm(self, system_prompt: str, prompt: str, timeout: int = 120) -> str:
        from tools.llm_client import call_llm
        raw = await call_llm(system_prompt, prompt, max_tokens=8192, timeout_secs=timeout)
        raw = raw.strip()
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        return raw

    # ── 方法一：从接口代码直接生成测试用例 ─────────────────────────────────────
    async def generate_from_code(
        self,
        code: str,
        lang: str = "python",
        base_url: str = "",
        progress_cb=None,
    ) -> List[Dict[str, Any]]:
        """
        解析接口实现代码，识别入参/边界条件/异常路径，生成覆盖这些场景的测试用例。
        返回与 generate_cases() 相同格式，可直接写入 ApiCase 表。
        """
        lang_hint = LANG_HINTS.get(lang, lang)

        async def _p(pct, stage):
            if progress_cb:
                try:
                    await progress_cb(pct, stage)
                except Exception:
                    pass

        await _p(10, "正在解析接口代码结构...")

        system_prompt = get_system("code_analyze.yaml", "generate_from_code")

        prompt = f"""以下是一段 {lang_hint} 接口实现代码，请仔细分析：

1. 所有接口路径（path）、请求方法（method）
2. 入参类型、必填/选填、取值范围、格式约束
3. 内部的条件分支（if/else/switch/try-catch）覆盖的场景
4. 边界值：最大值/最小值/空值/null/特殊字符等
5. 异常路径：参数校验失败、业务异常、未授权等的返回格式和错误码

然后生成测试用例，覆盖以下场景（按优先级排列）：
- P0：正常主流程（必须有，且参数填写真实合理的示例值）
- P1：参数校验失败（每种校验各一条）
- P1：业务异常场景（从代码逻辑推断）
- P2：边界值（最大值/最小值/空值）

```code
{code[:6000]}
```

输出严格的 JSON 数组，每条用例结构如下：
[
  {{
    "name": "用例名称（如：创建订单-正常流程）",
    "module": "从代码推断的模块名",
    "method": "GET|POST|PUT|DELETE|PATCH",
    "path": "/接口路径（含路径参数如 /users/{{id}}）",
    "params": {{}},
    "body": {{}},
    "assertions": [
      {{"type": "status_code", "expected": 200}},
      {{"type": "json_path", "path": "$.code", "expected": 0}}
    ],
    "priority": "P0",
    "description": "该接口的功能简介（一句话）",
    "scenario": "正常流|参数校验|业务异常|边界值",
    "_code_insight": "从代码中识别到的关键测试依据（如：第23行校验 quantity>0）"
  }}
]

Base URL（如有）：{base_url or '（未提供，path 请使用相对路径）'}"""

        await _p(30, "AI 正在分析代码逻辑和边界条件...")

        try:
            raw = await self._call_llm(system_prompt, prompt, timeout=120)
            cases = json.loads(raw)
            if not isinstance(cases, list):
                cases = []
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"代码生成用例失败: {e}")
            cases = []

        # 统一字段默认值
        for i, c in enumerate(cases):
            c.setdefault("module", "代码分析")
            c.setdefault("method", "POST")
            c.setdefault("path", "/")
            c.setdefault("scenario", "正常流")
            if not c.get("name"):
                module = c.get("module") or "代码分析"
                scenario = c.get("scenario") or ""
                c["name"] = f"{module}-{scenario}" if scenario else f"{module}-用例{i+1}"
            c.setdefault("params", {})
            c.setdefault("body", None)
            c.setdefault("headers", {})
            c.setdefault("assertions", [{"type": "status_code", "expected": 200}])
            c.setdefault("priority", "P1")
            c.setdefault("description", "")
            c.setdefault("enabled", True)

        await _p(100, f"代码分析完成，生成 {len(cases)} 条用例")
        logger.info(f"从代码生成用例: {len(cases)} 条")
        return cases

    # ── 方法二：需求文档 vs 代码 差异对比分析 ───────────────────────────────────
    async def analyze_vs_requirement(
        self,
        requirement: str,
        code: str,
        lang: str = "python",
        progress_cb=None,
    ) -> Dict[str, Any]:
        """
        对比需求文档和接口代码实现，识别偏差，返回结构化分析报告。

        返回格式：
        {
            "risk_level": "high|medium|low",
            "summary": "整体评估一句话",
            "items": [
                {
                    "type": "missing|mismatch|extra|risk",
                    "severity": "high|medium|low",
                    "title": "问题标题",
                    "requirement": "需求文档原文或描述",
                    "code_behavior": "代码实际行为",
                    "suggestion": "建议的修复方向",
                    "test_focus": "针对此偏差应测试什么"
                }
            ],
            "auto_cases": [...]   # 针对差异项自动生成的测试用例
        }
        """
        lang_hint = LANG_HINTS.get(lang, lang)

        async def _p(pct, stage):
            if progress_cb:
                try:
                    await progress_cb(pct, stage)
                except Exception:
                    pass

        await _p(10, "正在解析需求文档...")
        await _p(20, "正在解析接口代码...")
        await _p(35, "AI 正在对比需求与实现...")

        system_prompt = get_system("code_analyze.yaml", "analyze_vs_requirement")

        prompt = f"""请对比以下需求文档和接口实现代码，识别所有偏差和风险。

【需求文档】
---
{requirement[:4000]}
---

【接口实现代码（{lang_hint}）】
---
{code[:4000]}
---

## 分析维度

逐条检查以下四类问题：

1. **missing（需求有，代码没有实现）**
   - 需求描述的功能点在代码中完全缺失
   - 需求要求的参数校验在代码中没有
   - 需求要求的错误码/返回格式代码未实现

2. **mismatch（需求和代码行为不一致）**
   - 数值范围不同（如需求说≤999，代码写的≤100）
   - 返回格式不同（需求说返回 error_code，代码返回 message）
   - 状态码不同（需求说失败返回400，代码返回200带错误信息）

3. **extra（代码有，需求未提及的隐式限制）**
   - 代码中有需求未说明的频率限制、权限控制、黑名单等
   - 对测试有影响，需要专门覆盖

4. **risk（代码本身的潜在问题）**
   - 缺少参数 null 校验
   - 并发场景下可能的竞态条件
   - 大数值/特殊字符未做防护

## 输出格式

输出纯 JSON，格式如下：
{{
  "risk_level": "high|medium|low",
  "summary": "整体评估，一句话概括主要问题",
  "items": [
    {{
      "type": "missing|mismatch|extra|risk",
      "severity": "high|medium|low",
      "title": "问题的简短标题（15字以内）",
      "requirement": "需求文档的相关原文或描述（若是 risk 类型则填 N/A）",
      "code_behavior": "代码的实际行为描述",
      "suggestion": "建议开发修复的方向（一句话）",
      "test_focus": "针对此问题，测试时应重点验证什么"
    }}
  ]
}}

如果没有发现问题，items 返回空数组，risk_level 为 low。
每类问题最多列举 5 条，总 items 不超过 15 条。"""

        try:
            raw = await self._call_llm(system_prompt, prompt, timeout=120)
            report = json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"需求 vs 代码对比分析失败: {e}")
            report = {
                "risk_level": "low",
                "summary": f"分析过程出现异常: {e}",
                "items": [],
            }

        report.setdefault("risk_level", "low")
        report.setdefault("summary", "分析完成")
        report.setdefault("items", [])

        await _p(70, f"发现 {len(report['items'])} 个差异点，正在生成针对性测试用例...")

        # 针对差异点自动生成用例（每条差异生成 1-2 条专项用例）
        auto_cases = []
        if report["items"]:
            auto_cases = await self._generate_diff_cases(
                report["items"], requirement, code, lang_hint
            )
        report["auto_cases"] = auto_cases

        await _p(100, f"分析完成，发现 {len(report['items'])} 个差异点，生成 {len(auto_cases)} 条专项用例")
        logger.info(
            f"代码可行性分析完成: risk={report['risk_level']} "
            f"items={len(report['items'])} auto_cases={len(auto_cases)}"
        )
        return report

    async def _generate_diff_cases(
        self,
        items: List[Dict],
        requirement: str,
        code: str,
        lang_hint: str,
    ) -> List[Dict]:
        """针对每条差异项生成专项测试用例（覆盖偏差场景）"""
        if not items:
            return []

        items_summary = "\n".join(
            f"{i+1}. [{item.get('type','?')}][{item.get('severity','?')}] "
            f"{item.get('title','')}：{item.get('test_focus','')}"
            for i, item in enumerate(items[:10])
        )

        system_prompt = get_system("code_analyze.yaml", "generate_diff_cases")
        prompt = f"""根据以下需求与代码差异点，为每个差异生成 1-2 条专项测试用例，
专门验证该差异是否真实存在（从测试角度触发和验证）。

【差异清单】
{items_summary}

【接口代码概要（{lang_hint}）】
{code[:2000]}

输出 JSON 数组，格式与标准接口用例相同：
[
  {{
    "name": "用例名称（需体现是针对哪个差异的验证）",
    "module": "差异验证",
    "method": "POST",
    "path": "/接口路径",
    "params": {{}},
    "body": {{"示例参数": "示例值"}},
    "assertions": [{{"type": "status_code", "expected": 200}}],
    "priority": "P1",
    "description": "该用例验证的差异描述",
    "scenario": "差异验证",
    "_diff_ref": "对应差异标题"
  }}
]"""

        try:
            raw = await self._call_llm(system_prompt, prompt, timeout=90)
            cases = json.loads(raw)
            if not isinstance(cases, list):
                return []
            for c in cases:
                c.setdefault("enabled", True)
                c.setdefault("headers", {})
                c.setdefault("var_extracts", [])
            return cases
        except Exception as e:
            logger.warning(f"差异用例生成失败: {e}")
            return []


api_code_analyzer = ApiCodeAnalyzer()
