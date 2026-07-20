"""
鉴权与用户管理路由
  - POST   /auth/login
  - GET    /auth/me
  - PUT    /auth/password
  - GET/POST/DELETE/PUT  /auth/users/*
  - GET    /health
  - POST   /logs/clean
  - GET    /logs/list
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from loguru import logger

from api.schemas import HealthResponse
from tools.database import get_db, User
from agent.core import uitest_agent
from tools.config import settings
from api.auth import get_current_user, verify_password, hash_password, create_access_token

router = APIRouter()


# ── 鉴权接口（无需 token）─────────────────────────────────────────────────────

@router.post("/auth/login")
async def login(data: dict, db: AsyncSession = Depends(get_db)):
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token({"sub": user.username, "role": user.role})
    return {"access_token": token, "token_type": "bearer", "username": user.username, "role": user.role}


@router.get("/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username, "role": current_user.role}


@router.put("/auth/password")
async def change_password(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    old_pwd = data.get("old_password", "")
    new_pwd = data.get("new_password", "")
    if not verify_password(old_pwd, current_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(new_pwd) < 6:
        raise HTTPException(status_code=400, detail="新密码不能少于6位")
    current_user.password_hash = hash_password(new_pwd)
    db.add(current_user)
    await db.commit()
    return {"message": "密码修改成功"}


# ── admin 依赖 ────────────────────────────────────────────────────────────────
async def require_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


# ── 用户管理接口（admin only）────────────────────────────────────────────────

@router.get("/auth/users")
async def list_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [
        {"id": u.id, "username": u.username, "role": u.role,
         "created_at": u.created_at.isoformat() if u.created_at else None}
        for u in users
    ]


@router.post("/auth/users")
async def create_user(
    data: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码不能少于6位")
    if role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="角色只能是 admin 或 user")
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"用户名 '{username}' 已存在")
    new_user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    # 普通用户不自动加入任何工作空间，需要由空间 owner 手动邀请
    return {"id": new_user.id, "username": new_user.username, "role": new_user.role,
            "created_at": new_user.created_at.isoformat() if new_user.created_at else None}


@router.delete("/auth/users/{username}")
async def delete_user(
    username: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if username == admin.username:
        raise HTTPException(status_code=400, detail="不能删除自己")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 同步删除该用户在所有工作空间的成员记录
    from tools.database import ProjectMember
    from sqlalchemy import delete as sql_delete
    await db.execute(sql_delete(ProjectMember).where(ProjectMember.username == username))
    await db.delete(user)
    await db.commit()
    return {"message": f"用户 '{username}' 已删除"}


@router.put("/auth/users/{username}/password")
async def reset_user_password(
    username: str,
    data: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    new_pwd = data.get("new_password", "")
    if len(new_pwd) < 6:
        raise HTTPException(status_code=400, detail="新密码不能少于6位")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(new_pwd)
    db.add(user)
    await db.commit()
    return {"message": f"用户 '{username}' 密码已重置"}


# ── 健康检查 & 日志 ────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "agent_state": uitest_agent.get_state()
    }


@router.post("/logs/clean")
async def clean_logs_api(retention_days: int = None):
    """手动触发日志清理。retention_days 不传时使用配置默认值。"""
    from tools.logger import clean_logs, LOG_RETENTION_DAYS
    days = retention_days if retention_days is not None else LOG_RETENTION_DAYS
    result = clean_logs(retention_days=days)
    return result


@router.get("/logs/list")
async def list_logs():
    """列出 logs 目录中所有日志文件及大小、修改时间。"""
    from pathlib import Path
    log_dir = Path(settings.LOG_DIR)
    files = []
    for p in sorted(log_dir.iterdir()):
        if p.is_file():
            stat = p.stat()
            files.append({
                "name": p.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
    return {"log_dir": str(log_dir), "files": files}
