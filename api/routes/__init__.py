"""
API 路由汇总 — 按功能域拆分后统一在此导入，供 main.py include_router 使用。
"""
from fastapi import APIRouter

from api.routes.auth       import router as auth_router
from api.routes.webui      import router as webui_router
from api.routes.ai_cases   import router as ai_cases_router
from api.routes.api_test   import router as api_test_router
from api.routes.workspaces import router as workspaces_router

# 向后兼容：把所有子路由合并为一个 router，
# 供 api/__init__.py 和其他直接 import router 的地方使用
router = APIRouter()
router.include_router(auth_router)
router.include_router(webui_router)
router.include_router(ai_cases_router)
router.include_router(api_test_router)
router.include_router(workspaces_router)

__all__ = [
    "router", "auth_router", "webui_router",
    "ai_cases_router", "api_test_router", "workspaces_router",
]
