"""
工作空间（项目级隔离）路由
  - POST   /workspaces            创建工作空间
  - GET    /workspaces            列出我的工作空间
  - GET    /workspaces/{id}       工作空间详情
  - PUT    /workspaces/{id}       更新工作空间
  - DELETE /workspaces/{id}       删除工作空间（owner / admin）
  - GET    /workspaces/{id}/members        成员列表
  - POST   /workspaces/{id}/members        邀请成员
  - DELETE /workspaces/{id}/members/{username}  移除成员
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete
from loguru import logger

from tools.database import get_db, Project, ProjectMember, User
from api.auth import get_current_user

router = APIRouter()


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _project_dict(p: Project, role: str = "") -> dict:
    return {
        "id": p.id, "name": p.name, "description": p.description or "",
        "owner": p.owner, "role": role,
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
    }


async def _get_member_role(db: AsyncSession, project_id: int, username: str) -> str | None:
    """返回用户在工作空间中的角色，不是成员返回 None。admin 系统角色视为 owner。"""
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.username == username,
        )
    )
    m = result.scalar_one_or_none()
    return m.role if m else None


async def _require_member(db: AsyncSession, project_id: int, user: User) -> str:
    """确保用户是工作空间成员，返回角色。admin 直接放行。"""
    if user.role == "admin":
        return "owner"
    role = await _get_member_role(db, project_id, user.username)
    if not role:
        raise HTTPException(status_code=403, detail="无权访问此工作空间")
    return role


async def _require_owner(db: AsyncSession, project_id: int, user: User) -> None:
    """确保用户是工作空间 owner（或系统 admin）。"""
    if user.role == "admin":
        return
    role = await _get_member_role(db, project_id, user.username)
    if role != "owner":
        raise HTTPException(status_code=403, detail="需要工作空间 owner 权限")


# ── 工作空间 CRUD ─────────────────────────────────────────────────────────────

@router.post("/workspaces")
async def create_workspace(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="工作空间名称不能为空")
    # 同一用户下不能重名
    exists = await db.execute(
        select(Project).where(Project.owner == current_user.username, Project.name == name)
    )
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"工作空间「{name}」已存在")

    p = Project(
        name=name,
        description=data.get("description", ""),
        owner=current_user.username,
    )
    db.add(p)
    await db.flush()
    # 创建者自动成为 owner 成员
    db.add(ProjectMember(project_id=p.id, username=current_user.username, role="owner"))
    await db.commit()
    await db.refresh(p)
    logger.info(f"工作空间创建: id={p.id} name={p.name} owner={p.owner}")
    return _project_dict(p, role="owner")


@router.get("/workspaces")
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户有权访问的所有工作空间（admin 看全部）。"""
    if current_user.role == "admin":
        result = await db.execute(select(Project).order_by(Project.created_at.desc()))
        projects = result.scalars().all()
        return [_project_dict(p, role="owner") for p in projects]

    # 普通用户：通过成员关系查
    result = await db.execute(
        select(Project, ProjectMember).join(
            ProjectMember,
            (ProjectMember.project_id == Project.id) &
            (ProjectMember.username == current_user.username),
        ).order_by(Project.created_at.desc())
    )
    rows = result.all()
    return [_project_dict(p, role=m.role) for p, m in rows]


@router.get("/workspaces/{project_id}")
async def get_workspace(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    role = await _require_member(db, project_id, current_user)
    return _project_dict(p, role=role)


@router.put("/workspaces/{project_id}")
async def update_workspace(
    project_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    await _require_owner(db, project_id, current_user)
    if "name" in data and data["name"].strip():
        p.name = data["name"].strip()
    if "description" in data:
        p.description = data["description"]
    await db.commit()
    await db.refresh(p)
    return _project_dict(p, role="owner")


@router.delete("/workspaces/{project_id}")
async def delete_workspace(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    await _require_owner(db, project_id, current_user)
    await db.execute(sql_delete(ProjectMember).where(ProjectMember.project_id == project_id))
    await db.delete(p)
    await db.commit()
    logger.info(f"工作空间删除: id={project_id}")
    return {"message": f"工作空间「{p.name}」已删除"}


# ── 成员管理 ──────────────────────────────────────────────────────────────────

@router.get("/workspaces/{project_id}/members")
async def list_members(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    await _require_member(db, project_id, current_user)
    result = await db.execute(
        select(ProjectMember).where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.joined_at)
    )
    members = result.scalars().all()
    return [
        {"username": m.username, "role": m.role,
         "joined_at": m.joined_at.isoformat() if m.joined_at else ""}
        for m in members
    ]


@router.post("/workspaces/{project_id}/members")
async def invite_member(
    project_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """邀请成员加入工作空间（owner / admin 可操作）。"""
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    await _require_owner(db, project_id, current_user)

    username = (data.get("username") or "").strip()
    role = data.get("role", "member")
    if not username:
        raise HTTPException(status_code=400, detail="请提供用户名")
    if role not in ("owner", "member"):
        raise HTTPException(status_code=400, detail="角色只能是 owner 或 member")

    # 验证用户存在
    user_exists = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if not user_exists:
        raise HTTPException(status_code=404, detail=f"用户「{username}」不存在")

    # 已是成员则更新角色
    existing = (await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.username == username,
        )
    )).scalar_one_or_none()

    if existing:
        existing.role = role
        await db.commit()
        return {"message": f"已更新「{username}」的角色为 {role}"}

    db.add(ProjectMember(project_id=project_id, username=username, role=role))
    await db.commit()
    logger.info(f"成员邀请: workspace={project_id} user={username} role={role}")
    return {"message": f"已邀请「{username}」加入工作空间，角色：{role}"}


@router.delete("/workspaces/{project_id}/members/{username}")
async def remove_member(
    project_id: int,
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    await _require_owner(db, project_id, current_user)
    if username == p.owner:
        raise HTTPException(status_code=400, detail="不能移除工作空间创建者")

    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.username == username,
        )
    )
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail=f"「{username}」不是此工作空间成员")
    await db.delete(m)
    await db.commit()
    return {"message": f"已移除成员「{username}」"}
