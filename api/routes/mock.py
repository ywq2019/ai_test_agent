"""
Mock 服务路由

提供两类端点：
1. CRUD 管理接口（/api/v1/mock/*）— 管理 Mock 规则
2. Mock 匹配器（/mock/*）— 动态匹配请求并返回预设响应

Mock 匹配逻辑：
  - 按 method + path 精确匹配（路径支持 {param} 占位符）
  - 多条规则命中时取最先创建的（id 最小）
  - 支持 delay_ms 模拟延迟
  - response_body 支持简单 {{var}} 模板（从请求参数/路径提取）
"""
import asyncio
import json
import re
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from tools.database import get_db, MockRule, User
from api.auth import get_current_user, check_access

router = APIRouter()

# ── Mock 规则 CRUD ─────────────────────────────────────────────────────────────

def _rule_dict(r: MockRule) -> dict:
    return {
        "id": r.id, "project_id": r.project_id, "name": r.name,
        "method": r.method, "path": r.path,
        "status_code": r.status_code,
        "response_headers": r.response_headers or {},
        "response_body": r.response_body or "",
        "match_params": r.match_params or {},   # 请求参数匹配条件
        "delay_ms": r.delay_ms or 0,
        "enabled": r.enabled, "description": r.description or "",
        "workspace_id": r.workspace_id,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


@router.get("/mock/rules")
async def list_mock_rules(
    project_id: int = None,
    workspace_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出 Mock 规则。"""
    stmt = select(MockRule).order_by(MockRule.created_at.desc())
    if project_id is not None:
        stmt = stmt.where(MockRule.project_id == project_id)
    if workspace_id is not None:
        stmt = stmt.where(MockRule.workspace_id == workspace_id)
    rules = (await db.execute(stmt)).scalars().all()
    return [_rule_dict(r) for r in rules]


@router.post("/mock/rules")
async def create_mock_rule(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建 Mock 规则。"""
    rule = MockRule(
        project_id=data.get("project_id"),
        name=data.get("name", "未命名规则"),
        method=(data.get("method") or "GET").upper(),
        path=data.get("path", "/"),
        status_code=data.get("status_code", 200),
        response_headers=data.get("response_headers"),
        response_body=data.get("response_body", "{}"),
        match_params=data.get("match_params"),
        delay_ms=data.get("delay_ms", 0),
        enabled=data.get("enabled", True),
        description=data.get("description", ""),
        workspace_id=data.get("workspace_id"),
        created_by=current_user.username,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_dict(rule)


@router.put("/mock/rules/{rule_id}")
async def update_mock_rule(
    rule_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = (await db.execute(select(MockRule).where(MockRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    for field in ("name", "method", "path", "status_code", "response_headers",
                  "response_body", "match_params", "delay_ms", "enabled", "description"):
        if field in data:
            val = data[field]
            if field == "method" and val:
                val = val.upper()
            setattr(rule, field, val)
    await db.commit()
    await db.refresh(rule)
    return _rule_dict(rule)


@router.delete("/mock/rules/{rule_id}")
async def delete_mock_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = (await db.execute(select(MockRule).where(MockRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    await db.delete(rule)
    await db.commit()
    return {"message": "规则已删除"}


# ── Mock 匹配器（动态路由） ────────────────────────────────────────────────────

def _path_to_regex(path: str) -> re.Pattern:
    """将 /users/{id}/profile 转为正则 /users/([^/]+)/profile"""
    pattern = re.sub(r'\{[^}]+\}', r'([^/]+)', re.escape(path).replace(r'\{', '{').replace(r'\}', '}'))
    # re.escape 会把 { 变成 \{，先 unescape 再替换
    pattern = re.sub(r'\\\{[^}]+\\\}', r'([^/]+)', re.escape(path))
    return re.compile(f"^{pattern}$")


def _render_template(template: str, path_params: dict, query_params: dict) -> str:
    """简单模板渲染：{{param_name}} 替换为路径/查询参数值。"""
    all_params = {**query_params, **path_params}
    def replace(m):
        key = m.group(1).strip()
        return str(all_params.get(key, m.group(0)))
    return re.sub(r'\{\{(\w+)\}\}', replace, template)


mock_catch_router = APIRouter()

@mock_catch_router.api_route("/mock/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def mock_handler(request: Request, path: str, db: AsyncSession = Depends(get_db)):
    """
    动态 Mock 匹配器。
    按 /mock/your/api/path 访问，自动匹配已配置的 Mock 规则并返回预设响应。
    """
    req_method = request.method.upper()
    req_path = "/" + path

    # 查询所有启用的规则
    rules = (await db.execute(
        select(MockRule).where(MockRule.enabled == True).order_by(MockRule.id)
    )).scalars().all()

    matched: MockRule = None
    path_params: dict = {}

    for rule in rules:
        # method 匹配（ANY 匹配所有）
        if rule.method != "ANY" and rule.method != req_method:
            continue
        # path 匹配
        try:
            pattern = _path_to_regex(rule.path)
            m = pattern.match(req_path)
            if not m:
                continue
        except Exception:
            continue

        # 请求参数匹配（match_params 非空时校验）
        mp = rule.match_params or {}
        if mp:
            # 合并 query params 和 body（尽力解析）
            all_req_params = dict(request.query_params)
            try:
                body_bytes = await request.body()
                if body_bytes:
                    body_json = json.loads(body_bytes)
                    if isinstance(body_json, dict):
                        all_req_params.update(body_json)
            except Exception:
                pass
            # 检查每个匹配条件
            param_matched = True
            for k, v in mp.items():
                if k not in all_req_params:
                    param_matched = False
                    break
                if v and str(all_req_params[k]) != str(v):
                    param_matched = False
                    break
            if not param_matched:
                continue

        matched = rule
        path_params = {f"param{i}": v for i, v in enumerate(m.groups())}
        break

    if not matched:
        return Response(
            content=json.dumps({"error": f"No mock rule matched: {req_method} {req_path}"}, ensure_ascii=False),
            status_code=404,
            media_type="application/json",
        )

    # 模拟延迟
    if matched.delay_ms and matched.delay_ms > 0:
        await asyncio.sleep(matched.delay_ms / 1000.0)

    # 渲染响应体
    query_params = dict(request.query_params)
    body = _render_template(matched.response_body or "", path_params, query_params)

    # 响应头
    headers = dict(matched.response_headers or {})
    if "content-type" not in {k.lower() for k in headers}:
        headers["Content-Type"] = "application/json; charset=utf-8"

    logger.info(f"[mock] {req_method} {req_path} → rule={matched.id} status={matched.status_code}")
    return Response(content=body, status_code=matched.status_code, headers=headers)
