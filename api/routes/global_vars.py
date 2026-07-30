"""
全局变量池路由
  - /global-vars/*
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from tools.database import get_db, GlobalVariable, User
from api.auth import get_current_user

router = APIRouter()

# ── 全局变量池 ────────────────────────────────────────────────────────────────

def _gvar_dict(g: GlobalVariable) -> dict:
    return {
        "id": g.id, "name": g.name, "value": g.value or "",
        "description": g.description or "", "source_project": g.source_project or "",
        "updated_at": g.updated_at.isoformat() if g.updated_at else "",
    }


@router.get("/global-vars")
async def list_global_vars(
    workspace_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(GlobalVariable).order_by(GlobalVariable.name)
    if current_user.role == "admin":
        # admin 选了空间：只看该空间的；未选：看全部（含 NULL 的历史数据）
        if workspace_id is not None:
            stmt = stmt.where(GlobalVariable.workspace_id == workspace_id)
        # workspace_id is None → 不加任何过滤，看全部
    else:
        from sqlalchemy import false as sql_false
        from tools.database import ProjectMember
        from sqlalchemy import select as _sel
        if workspace_id is None:
            stmt = stmt.where(sql_false())
        else:
            m = await db.execute(_sel(ProjectMember).where(
                ProjectMember.project_id == workspace_id,
                ProjectMember.username == current_user.username,
            ))
            if not m.scalar_one_or_none():
                stmt = stmt.where(sql_false())
            else:
                # 普通用户选了空间：只看该空间的（不再包含 NULL，避免跨空间泄漏）
                stmt = stmt.where(GlobalVariable.workspace_id == workspace_id)
    result = await db.execute(stmt)
    return [_gvar_dict(g) for g in result.scalars().all()]


@router.post("/global-vars")
async def create_global_var(
    data: dict,
    workspace_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from skills.param_resolver import set_global_var, confirm_global_var
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="变量名不能为空")
    # 同一空间内变量名唯一（精确匹配 workspace_id，不再混入 NULL 数据）
    ws_id = workspace_id or data.get("workspace_id")
    stmt = select(GlobalVariable).where(GlobalVariable.name == name)
    if ws_id:
        stmt = stmt.where(GlobalVariable.workspace_id == ws_id)
    else:
        stmt = stmt.where(GlobalVariable.workspace_id.is_(None))
    exist = (await db.execute(stmt)).scalar_one_or_none()
    if exist:
        raise HTTPException(status_code=400, detail=f"变量 '{name}' 已存在，请使用 PUT 更新")
    g = GlobalVariable(name=name, value=data.get("value", ""),
                       description=data.get("description", ""),
                       source_project=data.get("source_project", "手动创建"),
                       workspace_id=ws_id)
    db.add(g)
    await db.commit()
    await db.refresh(g)
    set_global_var(name, g.value or "", source_project=g.source_project)
    confirm_global_var(name)
    return _gvar_dict(g)


@router.put("/global-vars/{var_id}")
async def update_global_var(var_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    from skills.param_resolver import set_global_var, confirm_global_var
    from datetime import datetime as _dt
    result = await db.execute(select(GlobalVariable).where(GlobalVariable.id == var_id))
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="变量不存在")
    for field in ("value", "description", "source_project"):
        if field in data:
            setattr(g, field, data[field])
    g.updated_at = _dt.utcnow()
    await db.commit()
    await db.refresh(g)
    set_global_var(g.name, g.value or "", source_project=g.source_project)
    confirm_global_var(g.name)
    return _gvar_dict(g)


@router.delete("/global-vars/{var_id}")
async def delete_global_var(var_id: int, db: AsyncSession = Depends(get_db)):
    from skills.param_resolver import evict_global_var
    result = await db.execute(select(GlobalVariable).where(GlobalVariable.id == var_id))
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="变量不存在")
    evict_global_var(g.name)
    await db.delete(g)
    await db.commit()
    return {"message": f"已删除全局变量 '{g.name}'"}


# ── 测试计划 ──────────────────────────────────────────────────────────────────

