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

# sentinel — distinguishes "key not found" from "key exists with value None"
_MISSING = object()


SYSTEM_PROMPT = """你是一名专业的接口测试工程师，精通 RESTful API 测试设计。
根据接口文档或描述，生成完整的接口测试用例，覆盖正常流、鉴权、边界值、错误码四类场景。

每条用例必须是以下结构的 JSON 对象：
{
  "name": "用例名称",
  "description": "该接口的功能简介，一句话说明接口用途（同一 path 下所有用例必须填写相同的 description）",
  "module": "所属模块",
  "method": "GET|POST|PUT|DELETE|PATCH",
  "path": "/相对路径，如 /users/{id}",
  "headers": {},
  "params": {},
  "body": {"key": "value"},
  "assertions": [
    {"type": "status_code", "expected": 200},
    {"type": "json_path", "path": "$.code", "expected": 0},
    {"type": "response_time", "max_ms": 3000}
  ],
  "priority": "P0|P1|P2",
  "scenario": "正常流|鉴权测试|边界值|错误码"
}

规则：
- description 字段描述接口本身的功能（如"查询用户详情"），不是描述测试用例；同一个 path 的所有用例必须填相同的 description
- headers 不含认证头（认证由项目统一配置）
- GET/DELETE 的 body 必须为 null
- POST/PUT/PATCH 的 body 必须是 JSON 对象，包含该接口所有必要请求参数的示例值，不能为 null 或空对象
- 每个接口至少生成正常流 + 1 个异常场景
- 严格输出 JSON 数组，不要任何解释文字"""


def _get_llm_config():
    from tools.config import settings
    return {
        "api_key": settings.AI_API_KEY,
        "base_url": settings.AI_API_URL,
        "model": settings.AI_MODEL or "claude-sonnet-4-6",
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

    # ─── 主入口 ──────────────────────────────────────────────────────────────

    async def generate_cases(
        self,
        base_url: str,
        swagger_text: str = "",
        description: str = "",
        progress_cb: Optional[Callable] = None,
        project: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        content = swagger_text or description
        if progress_cb:
            await progress_cb(10, "分析接口文档...")

        # Step 1: 识别接口分组
        url_info = self._parse_url_input(content)
        if url_info:
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
                cases = await self._generate_for_group(base_url, g)
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
            c.setdefault("name", f"TC{i+1:03d}")
            c.setdefault("description", "")
            c.setdefault("module", "通用")
            c.setdefault("priority", "P1")
            c.setdefault("method", "GET")
            c.setdefault("path", "/")
            c.setdefault("headers", {})
            c.setdefault("params", {})
            c.setdefault("body", None)
            c.setdefault("assertions", [{"type": "status_code", "expected": 200}])
            c.setdefault("enabled", True)

        # Step 4: 校验并修正断言（用真实响应数据对齐 json_path）
        if progress_cb:
            await progress_cb(85, "校验断言路径...")
        all_cases = await self._correct_assertions(all_cases, base_url, combined_headers)

        # Step 5: 补全描述
        if progress_cb:
            await progress_cb(92, "补全接口描述...")
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
            "分析以下接口文档，提取接口模块分组。\n"
            "输出 JSON 数组，每项包含 name（模块名）和 endpoints（该模块的接口描述）。\n"
            "严格输出 JSON，不要任何解释。\n\n"
            f"文档内容：\n{content[:3000]}"
        )
        try:
            raw = await self._call_api("你是接口文档分析专家，只输出JSON。", prompt)
            data = self._extract_json(raw)
            if isinstance(data, list) and data:
                return data[:10]
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
                probe = await self._probe_endpoint(
                    base_url, cand["path"], cand["method"],
                    cand.get("params", {}), headers,
                )
                if probe:
                    break
            g["_probe"] = probe
            if progress_cb:
                pct = 25 + int((i + 1) / total * 14)
                status_str = str(probe["status_code"]) if probe else "失败"
                await progress_cb(pct, f"探测接口 {i+1}/{total} → HTTP {status_str}")

    # ─── 用例生成 ─────────────────────────────────────────────────────────────

    async def _generate_for_group(self, base_url: str, group: Dict) -> List[Dict]:
        name = group.get("name", "API")
        endpoints = group.get("endpoints", group.get("description", ""))
        if isinstance(endpoints, list):
            endpoints = json.dumps(endpoints, ensure_ascii=False)

        probe_section = self._build_probe_section(group.get("_probe"))

        prompt = (
            f"为以下接口生成完整测试用例，覆盖正常流、鉴权、边界值、错误码场景。\n"
            f"Base URL: {base_url}\n"
            f"模块名称: {name}\n\n"
            f"接口信息:\n{str(endpoints)[:3000]}\n"
            f"{probe_section}"
            "\n重要要求：\n"
            "1. 接口信息中列出的所有 Query 参数必须填入每条用例的 params 字段\n"
            "2. 正常流用例的 params 包含所有参数及其示例值\n"
            "3. 异常用例通过移除或修改某个参数来覆盖错误场景\n"
            "4. path 只填相对路径，不含域名\n"
            "5. POST/PUT/PATCH 用例的 body 字段必须是包含示例数据的 JSON 对象，禁止为 null 或 {}\n"
            "6. GET/DELETE 用例的 body 必须为 null\n"
            "7. 每条用例必须包含 description 字段，内容为该接口的功能简介（一句话）；同一 path 的所有用例 description 必须完全相同\n"
            "8. 严格输出 JSON 数组，不加任何解释"
        )
        try:
            raw = await self._call_api(SYSTEM_PROMPT, prompt)
            cases = self._extract_json(raw)
            if isinstance(cases, list):
                for c in cases:
                    c["module"] = c.get("module") or name
                logger.info(f"Generated {len(cases)} cases for module '{name}'")
                return cases
            logger.warning(f"No JSON list for '{name}', raw[:300]: {raw[:300]}")
        except Exception as e:
            logger.warning(f"Case gen failed for {name}: {e}")
        return []

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
        for p in json_paths[:25]:
            val = p.get("value")
            if val is None:
                path_lines.append(f'  {p["path"]}  → ({p["type"]})')
            else:
                path_lines.append(f'  {p["path"]}  → {repr(val)}')

        body_preview = ""
        if json_body is not None:
            raw_str = json.dumps(json_body, ensure_ascii=False)
            body_preview = f"\n完整响应体:\n{raw_str[:800]}"

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
                        # 异常流：跳过 json_path（无法保证响应结构一致）
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

    # ─── LLM 调用 ─────────────────────────────────────────────────────────────

    async def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        import httpx
        cfg      = _get_llm_config()
        api_key  = cfg["api_key"]
        base_url = cfg["base_url"].rstrip("/")
        model    = cfg["model"]

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
                "messages": [{"role": "user", "content": user_prompt}],
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
                    {"role": "user",   "content": user_prompt},
                ],
            }

        logger.info(f"Calling API: {url}, model={model}")
        async with httpx.AsyncClient(verify=False, timeout=120) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        if is_anthropic:
            text = data["content"][0]["text"]
        else:
            text = data["choices"][0]["message"]["content"]

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
            raw = await self._call_api("你是API接口文档专家，只输出JSON对象。", prompt)
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
