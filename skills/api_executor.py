"""
接口测试执行引擎
使用 httpx.AsyncClient 执行用例，支持状态码 / JSONPath / 响应时间三种断言
支持：前置用例（setup_cases）自动刷新 token + 鉴权失败自动重试
"""
import base64
import time
from typing import List, Dict, Any, Optional, Callable
from loguru import logger
from skills.param_resolver import resolve_obj, resolve_str, set_global_var, flush_global_vars


def _parse_hosts_map(hosts_text: str) -> dict:
    """将 hosts 文件格式文本解析为 {hostname: ip} 字典。
    支持格式：'47.94.236.243 japi.hqwx.com'，忽略空行和 # 注释。
    """
    result = {}
    for line in (hosts_text or "").splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) >= 2:
            ip = parts[0]
            for hostname in parts[1:]:
                result[hostname] = ip
    return result


try:
    import httpx as _httpx

    class _HostsTransport(_httpx.AsyncHTTPTransport):
        """重写指定域名的连接目标 IP，但保留 Host 请求头（用于 HTTPS SNI + 虚拟主机）。"""

        def __init__(self, hosts_map: dict, **kwargs):
            self._hosts = hosts_map
            super().__init__(**kwargs)

        async def handle_async_request(self, request: _httpx.Request) -> _httpx.Response:
            host = request.url.host
            if host in self._hosts:
                ip = self._hosts[host]
                new_url = request.url.copy_with(host=ip)
                # 重建请求头：移除旧 Host，补上原始 hostname
                new_headers = [
                    (k, v) for k, v in request.headers.multi_items()
                    if k.lower() != 'host'
                ]
                new_headers.append(('host', host))
                content = await request.aread()
                request = _httpx.Request(
                    method=request.method,
                    url=new_url,
                    headers=new_headers,
                    content=content,
                )
            return await super().handle_async_request(request)

except ImportError:
    _HostsTransport = None  # httpx 未安装时降级


def _make_transport(hosts_map: dict, verify: bool = False):
    """根据 hosts_map 返回合适的 transport。"""
    if hosts_map and _HostsTransport is not None:
        return _HostsTransport(hosts_map, verify=verify)
    import httpx
    return httpx.AsyncHTTPTransport(verify=verify)


class ApiExecutor:

    async def _run_setup_cases(
        self,
        client,
        setup_cases: List[Dict],
        custom_scripts: Optional[List],
        var_store: Dict,
        progress_cb: Optional[Callable],
    ) -> None:
        """执行前置用例，刷新全局 token 等变量。"""
        if not setup_cases:
            return
        from tools.database import async_session_maker, ApiCase, ApiProject
        from sqlalchemy import select
        from skills.param_resolver import _gvar_cache

        for sc in setup_cases:
            case_id = sc.get("case_id")
            project_id = sc.get("project_id")
            label = sc.get("label", f"前置用例#{case_id}")
            if not case_id or not project_id:
                continue
            try:
                async with async_session_maker() as db:
                    proj_r = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
                    proj = proj_r.scalar_one_or_none()
                    case_r = await db.execute(select(ApiCase).where(ApiCase.id == case_id))
                    case = case_r.scalar_one_or_none()
                    # 加载前置用例所属项目的自定义脚本（如 generate_req_sign）
                    from tools.database import CustomScript
                    from sqlalchemy import or_
                    scripts_r = await db.execute(
                        select(CustomScript).where(
                            or_(CustomScript.project_id == project_id,
                                CustomScript.project_id == None)
                        )
                    )
                    setup_scripts = [
                        {"name": s.name, "code": s.code}
                        for s in scripts_r.scalars().all()
                    ]

                if not proj or not case:
                    logger.warning(f"[setup] 前置用例 {label} 不存在，跳过")
                    continue

                setup_base_url = (proj.base_url or "").rstrip("/")
                setup_auth = self.build_auth_headers({
                    "auth_type": proj.auth_type,
                    "auth_config": proj.auth_config,
                })
                setup_global_headers = proj.global_headers or {}
                case_dict = self._case_to_dict(case)

                if progress_cb:
                    await progress_cb({"type": "setup", "label": label, "status": "running"})

                result = await self._run_case(
                    client, setup_base_url, case_dict,
                    setup_auth, setup_global_headers,
                    var_store=var_store, custom_scripts=setup_scripts,
                    project_name=proj.name,
                )
                status = result.get("status", "failed")
                logger.info(f"[setup] 前置用例「{label}」执行{status}，"
                            f"提取变量: {result.get('extracted_vars', {})}")

                if progress_cb:
                    await progress_cb({"type": "setup", "label": label, "status": status})

            except Exception as e:
                logger.warning(f"[setup] 前置用例「{label}」执行异常: {e}")

    def _is_auth_error(self, result: Dict, patterns: List[Dict]) -> bool:
        """判断执行结果是否命中鉴权失败特征。"""
        if not patterns:
            return False
        preview = result.get("response_preview", "")
        status_code = result.get("status_code")
        import json as _json
        try:
            resp_json = _json.loads(preview) if preview else {}
        except Exception:
            resp_json = {}

        for p in patterns:
            field = (p.get("field") or "").strip()
            expected = str(p.get("value", "")).strip()
            if not field or not expected:
                continue
            # http_status 直接比较状态码
            if field == "http_status":
                if str(status_code) == expected:
                    return True
                continue
            # JSON path 提取
            try:
                actual = str(self._jsonpath_get(resp_json, field))
                if actual == expected:
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def _case_to_dict(case) -> Dict:
        """SQLAlchemy 模型 → dict（避免循环引入 _case_dict）。"""
        return {
            "id": case.id, "name": case.name, "module": case.module,
            "method": case.method, "path": case.path,
            "headers": case.headers, "params": case.params,
            "body_type": case.body_type or "json", "body": case.body,
            "body_raw": case.body_raw or "",
            "assertions": case.assertions, "var_extracts": case.var_extracts or [],
            "priority": case.priority, "enabled": case.enabled,
            "description": case.description or "",
        }

    async def execute_cases(
        self,
        project: Dict,
        cases: List[Dict],
        progress_cb: Optional[Callable] = None,
        custom_scripts: Optional[List] = None,
    ) -> Dict[str, Any]:
        import httpx

        auth_headers = self.build_auth_headers(project)
        global_headers = project.get("global_headers") or {}
        base_url = (project.get("base_url") or "").rstrip("/")
        project_name = project.get("name", "")
        setup_cases = project.get("setup_cases") or []
        auth_error_patterns = project.get("auth_error_patterns") or []
        proxy_url = project.get("proxy_url") or ""
        hosts_map = _parse_hosts_map(project.get("hosts_map") or "")
        enabled = [c for c in cases if c.get("enabled", True)]
        total = len(enabled)
        results = []
        var_store: Dict = {}

        if proxy_url and "://" not in proxy_url:
            proxy_url = "http://" + proxy_url
        _proxy_kwargs = {"proxies": {"all://": proxy_url}} if proxy_url else {}
        _transport = _make_transport(hosts_map, verify=False)
        async with httpx.AsyncClient(transport=_transport, verify=False, timeout=30.0, **_proxy_kwargs) as client:

            # ── Step 1：执行前置用例（刷新 token 等全局变量）────────────────
            if setup_cases:
                logger.info(f"[setup] 开始执行 {len(setup_cases)} 个前置用例...")
                await self._run_setup_cases(
                    client, setup_cases, custom_scripts, var_store, progress_cb
                )
                # 前置用例执行完立即持久化全局变量，确保后续用例能读到最新值
                await flush_global_vars(source_project=project_name)

            # ── Step 2：执行正式用例 ─────────────────────────────────────────
            for i, case in enumerate(enabled):
                result = await self._run_case(
                    client, base_url, case, auth_headers, global_headers,
                    var_store=var_store, custom_scripts=custom_scripts,
                    project_name=project_name,
                )

                # ── Step 3：鉴权失败自动重试（仅一次）──────────────────────
                if result.get("status") == "failed" and \
                        self._is_auth_error(result, auth_error_patterns) and \
                        setup_cases:
                    logger.warning(
                        f"[retry] 用例「{case.get('name')}」命中鉴权失败特征，"
                        "自动刷新 token 后重试..."
                    )
                    if progress_cb:
                        await progress_cb({
                            "type": "retry",
                            "case_name": case.get("name", ""),
                            "reason": "token 已过期，正在刷新...",
                        })
                    await self._run_setup_cases(
                        client, setup_cases, custom_scripts, var_store, progress_cb
                    )
                    await flush_global_vars(source_project=project_name)
                    result = await self._run_case(
                        client, base_url, case, auth_headers, global_headers,
                        var_store=var_store, custom_scripts=custom_scripts,
                        project_name=project_name,
                    )
                    result["_retried"] = True   # 标记已重试
                    logger.info(f"[retry] 重试结果: {result.get('status')}")

                results.append(result)
                if progress_cb:
                    await progress_cb({
                        "current": i + 1,
                        "total": total,
                        "case_name": case.get("name", ""),
                        "status": result["status"],
                        "progress": int((i + 1) / total * 100),
                        "var_store": dict(var_store),
                    })

        await flush_global_vars(source_project=project_name)

        passed = sum(1 for r in results if r["status"] == "passed")
        failed = len(results) - passed
        return {
            "results": results,
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / len(results) * 100, 1) if results else 0,
        }

    async def _run_case(
        self,
        client,
        base_url: str,
        case: Dict,
        auth_headers: Dict,
        global_headers: Dict,
        var_store: Optional[Dict] = None,
        custom_scripts: Optional[List] = None,
        project_name: str = "",
    ) -> Dict:
        t0 = time.time()
        method = (case.get("method") or "GET").upper()
        path = case.get("path") or "/"
        url = base_url + path

        # ── 解析动态参数占位符 ──────────────────────────────────────────────
        case_headers = resolve_obj(case.get("headers") or {}, var_store, custom_scripts)
        params       = resolve_obj(case.get("params")  or {}, var_store, custom_scripts)
        body_type    = case.get("body_type") or "json"
        body         = resolve_obj(case.get("body"),           var_store, custom_scripts)
        body_raw     = resolve_str(case.get("body_raw") or "", var_store, custom_scripts)
        # ────────────────────────────────────────────────────────────────────

        headers = {**global_headers, **auth_headers, **case_headers}
        no_body = method in ("GET", "DELETE")

        req_kwargs: dict = {"headers": headers, "params": params}
        if not no_body:
            if body_type == "form" and body:
                req_kwargs["data"] = body
            elif body_type == "raw" and body_raw:
                req_kwargs["content"] = body_raw.encode("utf-8") if isinstance(body_raw, str) else body_raw
                # 不覆盖 Content-Type，优先使用用例 headers 中已设置的值
            elif body_type == "json" and body:
                req_kwargs["json"] = body

        try:
            resp = await client.request(method, url, **req_kwargs)
            duration_ms = int((time.time() - t0) * 1000)
            assertion_results = self._run_assertions(resp, duration_ms, case.get("assertions") or [])
            passed = all(a["passed"] for a in assertion_results)
            failed_assertions = [a for a in assertion_results if not a["passed"]]
            error_parts = []
            for a in failed_assertions:
                t = a["type"]
                mt = a.get("match_type", "equals")
                err = a.get("error", "")
                path = a.get("path", "")
                prefix = f"[{path}]" if path else ""
                if t == "status_code":
                    error_parts.append(f"状态码 期望 {a.get('expected')} 实际 {a.get('actual')}")
                elif t == "response_time":
                    error_parts.append(f"响应时间超出 {a.get('max_ms')}ms 实际 {a.get('actual_ms')}ms")
                elif t == "json_path":
                    if err:
                        error_parts.append(f"json_path{prefix}: {err}")
                    elif mt == "contains":
                        error_parts.append(f"json_path{prefix}: 实际 {a.get('actual')} 不包含 {a.get('expected')}")
                    elif mt == "not_exists":
                        error_parts.append(f"json_path{prefix}: 字段存在 实际 {a.get('actual')}")
                    elif mt == "regex":
                        error_parts.append(f"json_path{prefix}: 不匹配正则 {a.get('expected')}")
                    elif mt in ("exists", "not_empty", "type"):
                        error_parts.append(f"json_path{prefix}: {mt} 失败 实际 {a.get('actual')}")
                    else:
                        error_parts.append(f"json_path{prefix}: 期望 {a.get('expected')} 实际 {a.get('actual')}")
                else:
                    if err:
                        error_parts.append(f"{t} 异常: {err}")
                    else:
                        error_parts.append(f"{t}: 期望 {a.get('expected')} 实际 {a.get('actual', a.get('actual_ms', ''))}")
            error_msg = "; ".join(error_parts) if error_parts else ""
            # ── 变量提取（支持 scope: local / global） ───────────────────────
            extracted_vars: Dict = {}
            for ve in (case.get("var_extracts") or []):
                var_name = (ve.get("name") or "").strip()
                var_path = (ve.get("path") or "").strip()
                scope    = (ve.get("scope") or "local").strip()   # "local" | "global"
                if not var_name or not var_path:
                    continue
                try:
                    resp_json = resp.json()
                    val = self._jsonpath_get(resp_json, var_path)
                    extracted_vars[var_name] = val
                    # 写入局部变量池
                    if var_store is not None:
                        var_store[var_name] = val
                    # scope=global 时额外写入全局变量缓存（执行完批次后持久化）
                    if scope == "global":
                        set_global_var(var_name, str(val), source_project=project_name)
                except Exception as ve_err:
                    logger.debug(f"var_extract '{var_name}' @ '{var_path}': {ve_err}")
            # ─────────────────────────────────────────────────────────────────
            return {
                "case_id": case.get("id"),
                "case_name": case.get("name"),
                "method": method,
                "url": url,
                "status_code": resp.status_code,
                "duration_ms": duration_ms,
                "status": "passed" if passed else "failed",
                "assertions": assertion_results,
                "error": error_msg,
                "extracted_vars": extracted_vars,
                "response_preview": resp.text[:800] if resp.text else "",
            }
        except Exception as e:
            return {
                "case_id": case.get("id"),
                "case_name": case.get("name"),
                "method": method,
                "url": url,
                "status_code": None,
                "duration_ms": int((time.time() - t0) * 1000),
                "status": "failed",
                "assertions": [],
                "error": str(e),
            }

    def _run_assertions(self, resp, duration_ms: int, assertions: List[Dict]) -> List[Dict]:
        results = []
        for a in assertions:
            t = a.get("type")
            if t == "status_code":
                expected = a.get("expected", 200)
                actual = resp.status_code
                results.append({"type": t, "expected": expected, "actual": actual, "passed": actual == expected})
            elif t == "json_path":
                results.append(self._eval_json_path(resp, a))
            elif t == "response_time":
                max_ms = a.get("max_ms", 3000)
                results.append({"type": t, "max_ms": max_ms, "actual_ms": duration_ms, "passed": duration_ms <= max_ms})
        if not results:
            passed = 200 <= resp.status_code < 300
            results.append({"type": "status_code", "expected": "2xx", "actual": resp.status_code, "passed": passed})
        return results

    def _eval_json_path(self, resp, a: Dict) -> Dict:
        """Evaluate a single json_path assertion with match_type support."""
        import re as _re
        path = a.get("path", "")
        expected = a.get("expected")
        match_type = a.get("match_type", "equals")
        base = {"type": "json_path", "path": path, "match_type": match_type, "expected": expected}

        try:
            resp_json = resp.json()
        except Exception as e:
            return {**base, "passed": False, "actual": None, "error": f"响应非JSON: {e}"}

        # not_exists: success = path not found
        if match_type == "not_exists":
            try:
                actual = self._jsonpath_get(resp_json, path)
                return {**base, "passed": False, "actual": actual, "error": f"字段存在，实际值: {actual}"}
            except (KeyError, TypeError, IndexError):
                return {**base, "passed": True, "actual": None}

        # Get actual value for all other match types
        try:
            actual = self._jsonpath_get(resp_json, path)
        except (KeyError, TypeError, IndexError):
            top_keys = list(resp_json.keys()) if isinstance(resp_json, dict) else []
            hint = f"路径 '{path}' 不存在"
            if top_keys:
                hint += f"，顶层字段：{top_keys}"
            return {**base, "passed": False, "actual": None, "error": hint}
        except Exception as e:
            return {**base, "passed": False, "actual": None, "error": str(e)}

        if match_type == "equals":
            passed = self._flexible_equal(actual, expected)
            return {**base, "passed": passed, "actual": actual}

        elif match_type == "contains":
            if isinstance(actual, list):
                passed = any(self._flexible_equal(x, expected) for x in actual)
            else:
                passed = str(expected) in str(actual)
            return {**base, "passed": passed, "actual": actual}

        elif match_type == "exists":
            passed = actual is not None
            return {**base, "passed": passed, "actual": actual,
                    "error": "" if passed else "字段值为 null"}

        elif match_type == "not_empty":
            passed = actual is not None and actual != "" and actual != [] and actual != {}
            return {**base, "passed": passed, "actual": actual,
                    "error": "" if passed else f"字段为空，实际: {actual!r}"}

        elif match_type == "type":
            type_map = {
                "string": str, "str": str,
                "number": (int, float), "integer": int, "int": int, "float": float,
                "boolean": bool, "bool": bool,
                "array": list, "list": list,
                "object": dict,
                "null": type(None),
            }
            exp_lower = (str(expected) if expected is not None else "").lower().strip()
            target = type_map.get(exp_lower)
            if target is None:
                return {**base, "passed": False, "actual": actual,
                        "error": f"未知类型 '{expected}'，可用: string/number/boolean/array/object/null"}
            passed = isinstance(actual, target)
            actual_type = "null" if actual is None else type(actual).__name__
            return {**base, "passed": passed, "actual": actual,
                    "error": "" if passed else f"期望类型 {expected}，实际类型 {actual_type}"}

        elif match_type == "regex":
            try:
                passed = bool(_re.search(str(expected), str(actual)))
                return {**base, "passed": passed, "actual": actual}
            except _re.error as e:
                return {**base, "passed": False, "actual": actual, "error": f"正则表达式错误: {e}"}

        else:
            passed = self._flexible_equal(actual, expected)
            return {**base, "passed": passed, "actual": actual}

    def _flexible_equal(self, actual: Any, expected: Any) -> bool:
        """宽松比较：先精确匹配，再尝试字符串/数值转换，兼容 UI 字符串输入与 JSON 数值/布尔的比较。"""
        if actual == expected:
            return True
        # 字符串化比较（覆盖 0 == "0"、True == "True" 等场景）
        if str(actual) == str(expected):
            return True
        # 数值比较（覆盖 1.0 == "1"、"1.5" == 1.5 等）
        try:
            return float(actual) == float(expected)
        except (ValueError, TypeError):
            return False

    def _jsonpath_get(self, data: Any, path: str) -> Any:
        parts = path.lstrip("$").lstrip(".").split(".")
        cur = data
        for part in parts:
            if not part:
                continue
            if "[" in part:
                key, idx = part.split("[", 1)
                idx = int(idx.rstrip("]"))
                if key:
                    cur = cur[key]
                cur = cur[idx]
            else:
                cur = cur[part]
        return cur

    def build_auth_headers(self, project: Dict) -> Dict:
        auth_type = project.get("auth_type", "none")
        cfg = project.get("auth_config") or {}
        if auth_type == "bearer":
            token = cfg.get("token", "")
            return {"Authorization": f"Bearer {token}"} if token else {}
        elif auth_type == "api_key" and cfg.get("in") == "header":
            return {cfg.get("key", "X-API-Key"): cfg.get("value", "")}
        elif auth_type == "basic":
            cred = f"{cfg.get('username','')}:{cfg.get('password','')}".encode()
            return {"Authorization": "Basic " + base64.b64encode(cred).decode()}
        return {}


api_executor = ApiExecutor()
