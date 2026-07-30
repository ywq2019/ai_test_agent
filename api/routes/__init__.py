"""
API 路由汇总 — 按功能域拆分后统一在此导入，供 main.py include_router 使用。
"""
from fastapi import APIRouter

from api.routes.auth        import router as auth_router
from api.routes.webui       import router as webui_router
from api.routes.ai_cases    import router as ai_cases_router
from api.routes.api_test    import router as api_test_router
from api.routes.global_vars import router as global_vars_router
from api.routes.test_plans  import router as test_plans_router
from api.routes.workspaces  import router as workspaces_router
from api.routes.pentest     import router as pentest_router

# 向后兼容：把所有子路由合并为一个 router
router = APIRouter()
router.include_router(auth_router)
router.include_router(webui_router)
router.include_router(ai_cases_router)
router.include_router(api_test_router)
router.include_router(global_vars_router)
router.include_router(test_plans_router)
router.include_router(workspaces_router)
router.include_router(pentest_router)

__all__ = [
    "router",
    "auth_router", "webui_router", "ai_cases_router",
    "api_test_router", "global_vars_router", "test_plans_router",
    "workspaces_router", "pentest_router",
]
