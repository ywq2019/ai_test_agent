"""
JWT 鉴权工具模块
- 密码哈希 / 验证
- Token 生成 / 解析
- FastAPI 依赖注入 get_current_user
- owner_filter: 数据隔离过滤条件工具
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from tools.config import settings
from tools.database import get_db, User

# ── 密码哈希 ──────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

# ── JWT ───────────────────────────────────────────────────────────────────────
bearer_scheme = HTTPBearer(auto_error=False)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=settings.JWT_EXPIRE_HOURS))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None

# ── 依赖注入 ──────────────────────────────────────────────────────────────────
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或 Token 已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials:
        raise exc
    payload = decode_token(credentials.credentials)
    if not payload:
        raise exc
    username: str = payload.get("sub")
    if not username:
        raise exc
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise exc
    return user


# ── 数据隔离工具 ──────────────────────────────────────────────────────────────
def owner_filter(model, user: User):
    """返回数据隔离的 SQLAlchemy 条件：
    - admin：看全部数据
    - 普通用户：只看自己创建的 + created_by 为 NULL 的历史数据
    """
    from sqlalchemy import or_
    if user.role == "admin":
        return None  # 无过滤，查全部
    return or_(model.created_by == user.username, model.created_by.is_(None))


def check_owner(record, user: User, resource_name: str = "记录") -> None:
    """校验当前用户是否有权访问指定记录，无权时抛出 403。
    admin 跳过检查；普通用户只能访问自己的或 created_by=NULL 的历史数据。
    注意：此函数不感知工作空间成员关系，单条记录访问请用 check_access。
    """
    if user.role == "admin":
        return
    if record.created_by is not None and record.created_by != user.username:
        raise HTTPException(status_code=403, detail=f"无权访问此{resource_name}")


async def check_access(db, record, user: User, resource_name: str = "记录") -> None:
    """工作空间感知的访问校验（强制模式）：
    1. admin → 直接放行
    2. 记录有 project_id/workspace_id，且用户是该空间成员 → 放行
    3. 否则 → 403
    """
    if user.role == "admin":
        return
    ws_id = getattr(record, "project_id", None) or getattr(record, "workspace_id", None)
    if ws_id:
        from tools.database import ProjectMember
        from sqlalchemy import select
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == ws_id,
                ProjectMember.username == user.username,
            )
        )
        if result.scalar_one_or_none():
            return
    raise HTTPException(status_code=403, detail=f"无权访问此{resource_name}")


# ── 工作空间过滤工具 ───────────────────────────────────────────────────────────
def workspace_filter(model, workspace_id: int | None, user: User):
    """返回工作空间维度的 SQLAlchemy 过滤条件（同步版，不查成员表）。
    - workspace_id 不为 None：该空间绑定的数据 + 自己的无空间数据
    - workspace_id 为 None：自己的 + 历史 NULL 数据
    - admin：无过滤
    注意：选空间时看不到「同事创建但未绑定空间」的旧数据，
    需要用 workspace_filter_with_members（异步）才能做到完整隔离。
    """
    from sqlalchemy import or_
    if user.role == "admin":
        return None
    if workspace_id is not None:
        return or_(
            model.project_id == workspace_id,
            (model.created_by == user.username) & model.project_id.is_(None),
        )
    return or_(model.created_by == user.username, model.created_by.is_(None))


async def workspace_filter_members(db, model, workspace_id: int | None, user: User):
    """工作空间过滤（强制模式）：
    - admin：不过滤，看全部
    - 普通用户 + 选了空间：只看该空间的数据（project_id == workspace_id）
    - 普通用户 + 未选空间：返回 False（空结果，前端强制选择）
    """
    if user.role == "admin":
        return None
    if workspace_id is not None:
        # 验证用户确实是该空间成员
        from tools.database import ProjectMember
        from sqlalchemy import select
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == workspace_id,
                ProjectMember.username == user.username,
            )
        )
        if not result.scalar_one_or_none():
            # 不是成员，返回 False（空结果）
            from sqlalchemy import false
            return false()
        return model.project_id == workspace_id
    # 未选空间，返回 False（空结果，强制选择）
    from sqlalchemy import false
    return false()


async def check_workspace_member(
    db,
    project_id: int | None,
    user: User,
    resource_name: str = "工作空间",
) -> None:
    """校验用户是否是工作空间成员，不是则抛 403。
    project_id 为 None 或 admin 直接放行。
    """
    if not project_id or user.role == "admin":
        return
    from tools.database import ProjectMember
    from sqlalchemy import select
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.username == user.username,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail=f"无权访问此{resource_name}")
