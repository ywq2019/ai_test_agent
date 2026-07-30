"""
路由集成测试 — SQLite in-memory + httpx.AsyncClient

覆盖范围：
  - 健康检查
  - 鉴权：登录、无效密码、无 Token 访问受保护路由
  - 用户管理：创建、列表、删除（admin only）
  - 工作空间：CRUD、成员管理
  - 全局变量：创建、更新、删除

运行：
  pytest tests/test_routes_integration.py -v
"""
import os
import sys
import asyncio
from typing import AsyncGenerator

# ── 必须在所有项目模块导入之前设置，否则 settings 已读取默认值 ──────────────────
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

# ── 测试专用引擎：StaticPool 确保所有连接共享同一内存库 ──────────────────────
_TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = async_sessionmaker(
    _TEST_ENGINE,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── 在导入 tools.database / main 之前，把引擎和 session_maker 替换掉 ──────────
# （lifespan 直接用 async_session_maker，不走 get_db 依赖注入）
import tools.database as _db_module
_db_module.engine = _TEST_ENGINE
_db_module.async_session_maker = _TestSession

from tools.database import Base, get_db
from tools.config import settings
from main import app


async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _TestSession() as session:
        yield session


# ── pytest 配置：只用 asyncio，不运行 trio ────────────────────────────────────
pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="session")
def event_loop():
    """整个 session 共用一个事件循环。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    """一次性建表 + 创建默认 admin 用户（替代 lifespan 的初始化逻辑）。"""
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 手动创建 admin 用户，lifespan 在 ASGITransport 下不会自动执行
    from api.auth import hash_password
    from tools.database import User
    from sqlalchemy import select

    async with _TestSession() as db:
        result = await db.execute(select(User).where(User.username == settings.DEFAULT_USERNAME))
        if not result.scalar_one_or_none():
            db.add(User(
                username=settings.DEFAULT_USERNAME,
                password_hash=hash_password(settings.DEFAULT_PASSWORD),
                role="admin",
            ))
            await db.commit()

    yield

    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="session")
async def client(setup_db) -> AsyncGenerator[AsyncClient, None]:
    """Session 级别的 AsyncClient，注入测试数据库。"""
    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="session")
async def admin_token(client: AsyncClient) -> str:
    """用默认 admin 账号登录，返回 JWT token。"""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.DEFAULT_USERNAME, "password": settings.DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200, f"admin 登录失败: {resp.text}"
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────────────────────
# 健康检查
# ─────────────────────────────────────────────────────────────────────────────

async def test_health(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "version" in data


# ─────────────────────────────────────────────────────────────────────────────
# 鉴权
# ─────────────────────────────────────────────────────────────────────────────

async def test_login_success(client: AsyncClient, admin_token: str):
    # admin_token fixture 登录已验证，这里再显式验证一次响应体字段
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.DEFAULT_USERNAME, "password": settings.DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["username"] == settings.DEFAULT_USERNAME
    assert body["role"] == "admin"


async def test_login_wrong_password(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.DEFAULT_USERNAME, "password": "wrong_password"},
    )
    assert resp.status_code == 401


async def test_login_empty_fields(client: AsyncClient):
    resp = await client.post("/api/v1/auth/login", json={"username": "", "password": ""})
    assert resp.status_code == 400


async def test_protected_route_without_token(client: AsyncClient):
    """受保护路由没有 token 时应返回 401。"""
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_protected_route_with_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer totally.invalid.token"},
    )
    assert resp.status_code == 401


async def test_get_me(client: AsyncClient, admin_token: str):
    resp = await client.get("/api/v1/auth/me", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["username"] == settings.DEFAULT_USERNAME


# ─────────────────────────────────────────────────────────────────────────────
# 用户管理
# ─────────────────────────────────────────────────────────────────────────────

async def test_list_users_requires_admin(client: AsyncClient, admin_token: str):
    resp = await client.get("/api/v1/auth/users", headers=_auth(admin_token))
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    usernames = [u["username"] for u in users]
    assert settings.DEFAULT_USERNAME in usernames


async def test_create_and_delete_user(client: AsyncClient, admin_token: str):
    # 创建普通用户
    resp = await client.post(
        "/api/v1/auth/users",
        json={"username": "test_user_tmp", "password": "password123", "role": "user"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "test_user_tmp"

    # 重复创建应返回 400
    resp2 = await client.post(
        "/api/v1/auth/users",
        json={"username": "test_user_tmp", "password": "password123", "role": "user"},
        headers=_auth(admin_token),
    )
    assert resp2.status_code == 400

    # 删除
    resp3 = await client.delete("/api/v1/auth/users/test_user_tmp", headers=_auth(admin_token))
    assert resp3.status_code == 200
    assert "已删除" in resp3.json()["message"]


async def test_create_user_short_password(client: AsyncClient, admin_token: str):
    resp = await client.post(
        "/api/v1/auth/users",
        json={"username": "short_pwd_user", "password": "abc", "role": "user"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400


async def test_non_admin_cannot_list_users(client: AsyncClient, admin_token: str):
    """普通用户访问 /auth/users 应返回 403。"""
    # 创建普通用户
    await client.post(
        "/api/v1/auth/users",
        json={"username": "plain_user", "password": "plainpwd123", "role": "user"},
        headers=_auth(admin_token),
    )
    # 普通用户登录
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "plain_user", "password": "plainpwd123"},
    )
    assert login_resp.status_code == 200
    user_token = login_resp.json()["access_token"]

    # 访问管理员专属路由应被拒绝
    resp = await client.get("/api/v1/auth/users", headers=_auth(user_token))
    assert resp.status_code == 403

    # 清理
    await client.delete("/api/v1/auth/users/plain_user", headers=_auth(admin_token))


async def test_change_password(client: AsyncClient, admin_token: str):
    # 创建用户
    await client.post(
        "/api/v1/auth/users",
        json={"username": "pwd_change_user", "password": "old_password123", "role": "user"},
        headers=_auth(admin_token),
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "pwd_change_user", "password": "old_password123"},
    )
    token = login_resp.json()["access_token"]

    # 修改密码
    resp = await client.put(
        "/api/v1/auth/password",
        json={"old_password": "old_password123", "new_password": "new_password456"},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    # 旧密码不再有效
    resp2 = await client.post(
        "/api/v1/auth/login",
        json={"username": "pwd_change_user", "password": "old_password123"},
    )
    assert resp2.status_code == 401

    # 新密码可以登录
    resp3 = await client.post(
        "/api/v1/auth/login",
        json={"username": "pwd_change_user", "password": "new_password456"},
    )
    assert resp3.status_code == 200

    # 清理
    await client.delete("/api/v1/auth/users/pwd_change_user", headers=_auth(admin_token))


async def test_admin_cannot_delete_self(client: AsyncClient, admin_token: str):
    resp = await client.delete(
        f"/api/v1/auth/users/{settings.DEFAULT_USERNAME}",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400


async def test_delete_nonexistent_user(client: AsyncClient, admin_token: str):
    resp = await client.delete("/api/v1/auth/users/no_such_user_xyz", headers=_auth(admin_token))
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 工作空间
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def workspace(client: AsyncClient, admin_token: str) -> dict:
    """创建临时工作空间，测试结束后自动删除。"""
    resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "集成测试空间", "description": "仅用于测试"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    ws = resp.json()
    yield ws
    await client.delete(f"/api/v1/workspaces/{ws['id']}", headers=_auth(admin_token))


async def test_create_workspace(client: AsyncClient, admin_token: str):
    resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "temp_ws_create", "description": "test"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "temp_ws_create"
    assert data["owner"] == settings.DEFAULT_USERNAME
    # 清理
    await client.delete(f"/api/v1/workspaces/{data['id']}", headers=_auth(admin_token))


async def test_create_workspace_empty_name(client: AsyncClient, admin_token: str):
    resp = await client.post(
        "/api/v1/workspaces",
        json={"name": ""},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400


async def test_create_workspace_duplicate_name(
    client: AsyncClient, workspace: dict, admin_token: str
):
    resp = await client.post(
        "/api/v1/workspaces",
        json={"name": workspace["name"]},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400


async def test_list_workspaces(client: AsyncClient, workspace: dict, admin_token: str):
    resp = await client.get("/api/v1/workspaces", headers=_auth(admin_token))
    assert resp.status_code == 200
    ids = [w["id"] for w in resp.json()]
    assert workspace["id"] in ids


async def test_get_workspace(client: AsyncClient, workspace: dict, admin_token: str):
    resp = await client.get(f"/api/v1/workspaces/{workspace['id']}", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["id"] == workspace["id"]


async def test_get_workspace_not_found(client: AsyncClient, admin_token: str):
    resp = await client.get("/api/v1/workspaces/99999", headers=_auth(admin_token))
    assert resp.status_code == 404


async def test_update_workspace(client: AsyncClient, workspace: dict, admin_token: str):
    resp = await client.put(
        f"/api/v1/workspaces/{workspace['id']}",
        json={"name": "集成测试空间_updated", "description": "updated desc"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "集成测试空间_updated"


async def test_workspace_member_management(
    client: AsyncClient, workspace: dict, admin_token: str
):
    """邀请成员 → 查成员列表 → 移除成员。"""
    # 先创建普通用户
    await client.post(
        "/api/v1/auth/users",
        json={"username": "ws_member_user", "password": "member_pwd123", "role": "user"},
        headers=_auth(admin_token),
    )

    # 邀请成员
    invite_resp = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        json={"username": "ws_member_user", "role": "member"},
        headers=_auth(admin_token),
    )
    assert invite_resp.status_code == 200

    # 成员列表中应能查到
    list_resp = await client.get(
        f"/api/v1/workspaces/{workspace['id']}/members",
        headers=_auth(admin_token),
    )
    assert list_resp.status_code == 200
    members = [m["username"] for m in list_resp.json()]
    assert "ws_member_user" in members

    # 移除成员
    del_resp = await client.delete(
        f"/api/v1/workspaces/{workspace['id']}/members/ws_member_user",
        headers=_auth(admin_token),
    )
    assert del_resp.status_code == 200

    # 确认已移除
    list_resp2 = await client.get(
        f"/api/v1/workspaces/{workspace['id']}/members",
        headers=_auth(admin_token),
    )
    members2 = [m["username"] for m in list_resp2.json()]
    assert "ws_member_user" not in members2

    # 清理
    await client.delete("/api/v1/auth/users/ws_member_user", headers=_auth(admin_token))


async def test_non_member_cannot_access_workspace(
    client: AsyncClient, workspace: dict, admin_token: str
):
    """非成员用户访问工作空间应返回 403。"""
    await client.post(
        "/api/v1/auth/users",
        json={"username": "outsider_user", "password": "outsider_pwd123", "role": "user"},
        headers=_auth(admin_token),
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "outsider_user", "password": "outsider_pwd123"},
    )
    outsider_token = login_resp.json()["access_token"]

    resp = await client.get(
        f"/api/v1/workspaces/{workspace['id']}",
        headers=_auth(outsider_token),
    )
    assert resp.status_code == 403

    await client.delete("/api/v1/auth/users/outsider_user", headers=_auth(admin_token))


# ─────────────────────────────────────────────────────────────────────────────
# 全局变量
# ─────────────────────────────────────────────────────────────────────────────

async def test_global_var_crud(client: AsyncClient, workspace: dict, admin_token: str):
    ws_id = workspace["id"]

    # 创建
    create_resp = await client.post(
        f"/api/v1/global-vars?workspace_id={ws_id}",
        json={"name": "TEST_VAR", "value": "hello", "description": "test"},
        headers=_auth(admin_token),
    )
    assert create_resp.status_code == 200
    var = create_resp.json()
    assert var["name"] == "TEST_VAR"
    assert var["value"] == "hello"
    var_id = var["id"]

    # 重复创建应返回 400
    dup_resp = await client.post(
        f"/api/v1/global-vars?workspace_id={ws_id}",
        json={"name": "TEST_VAR", "value": "dup"},
        headers=_auth(admin_token),
    )
    assert dup_resp.status_code == 400

    # 列表中可查到
    list_resp = await client.get(
        f"/api/v1/global-vars?workspace_id={ws_id}",
        headers=_auth(admin_token),
    )
    assert list_resp.status_code == 200
    names = [v["name"] for v in list_resp.json()]
    assert "TEST_VAR" in names

    # 更新
    upd_resp = await client.put(
        f"/api/v1/global-vars/{var_id}",
        json={"value": "world", "description": "updated"},
        headers=_auth(admin_token),
    )
    assert upd_resp.status_code == 200
    assert upd_resp.json()["value"] == "world"

    # 删除
    del_resp = await client.delete(f"/api/v1/global-vars/{var_id}", headers=_auth(admin_token))
    assert del_resp.status_code == 200

    # 再次删除应返回 404
    del_resp2 = await client.delete(f"/api/v1/global-vars/{var_id}", headers=_auth(admin_token))
    assert del_resp2.status_code == 404


async def test_global_var_empty_name(client: AsyncClient, workspace: dict, admin_token: str):
    resp = await client.post(
        f"/api/v1/global-vars?workspace_id={workspace['id']}",
        json={"name": "", "value": "val"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400
