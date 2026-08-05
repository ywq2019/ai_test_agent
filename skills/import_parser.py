"""
Postman Collection v2.1 / HAR 文件导入解析器

支持格式：
  - Postman Collection v2.1（.json）
  - HAR（HTTP Archive）v1.2（.har）

输出：List[dict]，格式与 ApiCase 兼容，可直接批量入库。
"""
import json
from typing import List, Dict, Any, Optional
from loguru import logger


def _safe_str(val) -> str:
    if val is None:
        return ""
    return str(val)


def parse_postman(data: dict, base_url: str = "") -> List[Dict]:
    """解析 Postman Collection v2.1 → ApiCase 列表"""
    cases = []
    info = data.get("info", {})
    collection_name = info.get("name", "导入用例")

    def _process_item(item: dict, module: str = "通用"):
        name = item.get("name", "未命名")
        # 文件夹（无 request 字段）
        if "item" in item:
            folder_name = name
            for sub in item["item"]:
                _process_item(sub, module=folder_name)
            return
        # 请求
        req = item.get("request")
        if not req:
            return

        method = _safe_str(req.get("method", "GET")).upper()

        # URL
        url_obj = req.get("url", {})
        if isinstance(url_obj, str):
            path = url_obj.replace(base_url, "") or "/"
            params = {}
        else:
            raw_path = url_obj.get("path", [])
            path = "/" + "/".join(raw_path) if raw_path else "/"
            # Query params
            params = {}
            for q in url_obj.get("query", []):
                if not q.get("disabled"):
                    params[q.get("key", "")] = q.get("value", "")

        # Headers（排除鉴权头，由项目统一配置）
        headers = {}
        skip_headers = {"authorization", "content-type"}
        for h in req.get("header", []):
            if not h.get("disabled") and h.get("key", "").lower() not in skip_headers:
                headers[h["key"]] = h.get("value", "")

        # Body
        body = None
        body_type = "json"
        body_raw = ""
        body_obj = req.get("body", {}) or {}
        mode = body_obj.get("mode", "")
        if mode == "raw":
            raw_str = body_obj.get("raw", "")
            lang = body_obj.get("options", {}).get("raw", {}).get("language", "json")
            if lang == "json" and raw_str.strip():
                try:
                    body = json.loads(raw_str)
                    body_type = "json"
                except Exception:
                    body_raw = raw_str
                    body_type = "raw"
            else:
                body_raw = raw_str
                body_type = "raw"
        elif mode == "urlencoded":
            body = {e["key"]: e.get("value", "") for e in body_obj.get("urlencoded", []) if not e.get("disabled")}
            body_type = "form"
        elif mode == "formdata":
            body = {e["key"]: e.get("value", "") for e in body_obj.get("formdata", []) if not e.get("disabled") and e.get("type") != "file"}
            body_type = "form"

        cases.append({
            "name": name,
            "module": module,
            "method": method,
            "path": path,
            "headers": headers or None,
            "params": params or None,
            "body": body,
            "body_type": body_type,
            "body_raw": body_raw,
            "assertions": [{"type": "status_code", "expected": 200}],
            "priority": "P1",
            "description": item.get("description") or "",
            "enabled": True,
        })

    for item in data.get("item", []):
        _process_item(item)

    logger.info(f"[import] Postman 导入: {collection_name}，解析 {len(cases)} 条用例")
    return cases


def parse_har(data: dict, base_url: str = "") -> List[Dict]:
    """解析 HAR v1.2 → ApiCase 列表"""
    cases = []
    entries = data.get("log", {}).get("entries", [])

    for entry in entries:
        req = entry.get("request", {})
        method = _safe_str(req.get("method", "GET")).upper()
        url = req.get("url", "")

        # 提取 path
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            path = parsed.path or "/"
            params = {k: (v[0] if len(v) == 1 else v)
                      for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        except Exception:
            path = "/"
            params = {}

        # Headers
        headers = {}
        skip = {"authorization", "content-type", "cookie", "host", "user-agent",
                 "accept", "accept-encoding", "accept-language", "connection"}
        for h in req.get("headers", []):
            if h.get("name", "").lower() not in skip:
                headers[h["name"]] = h.get("value", "")

        # Body
        body = None
        body_type = "json"
        body_raw = ""
        post_data = req.get("postData", {}) or {}
        mime = post_data.get("mimeType", "")
        text = post_data.get("text", "")
        if text:
            if "json" in mime:
                try:
                    body = json.loads(text)
                    body_type = "json"
                except Exception:
                    body_raw = text
                    body_type = "raw"
            elif "form" in mime:
                params_list = post_data.get("params", [])
                body = {p["name"]: p.get("value", "") for p in params_list}
                body_type = "form"
            else:
                body_raw = text
                body_type = "raw"

        # 响应断言
        resp = entry.get("response", {})
        status = resp.get("status", 200)
        assertions = [{"type": "status_code", "expected": status}]

        # 用 path 末尾部分作为用例名
        name_part = path.rstrip("/").split("/")[-1] or path
        cases.append({
            "name": f"{method} {name_part}",
            "module": "导入",
            "method": method,
            "path": path,
            "headers": headers or None,
            "params": params or None,
            "body": body,
            "body_type": body_type,
            "body_raw": body_raw,
            "assertions": assertions,
            "priority": "P1",
            "description": "",
            "enabled": True,
        })

    logger.info(f"[import] HAR 导入: 解析 {len(cases)} 条请求")
    return cases


def parse_import_file(content: str, filename: str, base_url: str = "") -> List[Dict]:
    """
    自动识别文件类型并解析。
    filename: 用于判断 .har 还是 Postman Collection
    返回 ApiCase 兼容的字典列表。
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"文件不是有效的 JSON: {e}")

    fname = filename.lower()
    if fname.endswith(".har"):
        return parse_har(data, base_url)
    # Postman Collection 特征：info.schema 含 "postman"
    schema = data.get("info", {}).get("schema", "")
    if "postman" in schema or "item" in data:
        return parse_postman(data, base_url)
    # 最后尝试 HAR
    if "log" in data and "entries" in data.get("log", {}):
        return parse_har(data, base_url)
    raise ValueError("无法识别文件格式，请上传 Postman Collection v2.1 或 HAR 文件")
