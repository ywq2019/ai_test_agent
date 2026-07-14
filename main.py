"""
自动化UI测试Agent - FastAPI应用入口
基于 LangChain + LangGraph 架构
"""
import asyncio
import sys
import os

# Windows 下 Playwright async API 需要 ProactorEventLoop 才能 create_subprocess_exec
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from api.routes import router as api_router
from api.websocket import websocket_endpoint
from tools.database import init_database
from tools.config import settings
from skills.langchain_tools import tool_registry
from agent.langgraph_agent import init_langgraph_agent


async def _log_cleanup_loop():
    """每天凌晨 00:05 执行一次日志清理，服务启动时也立即执行一次。"""
    from tools.logger import clean_logs
    # 启动时先清理一次
    try:
        clean_logs()
    except Exception as e:
        logger.warning(f"启动时日志清理失败: {e}")

    while True:
        # 等到下一个 00:05
        import time
        from datetime import datetime, timedelta
        now = datetime.now()
        next_run = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        sleep_secs = (next_run - now).total_seconds()
        logger.info(f"下次日志清理将在 {next_run.strftime('%Y-%m-%d %H:%M:%S')} 执行")
        await asyncio.sleep(sleep_secs)
        try:
            clean_logs()
        except Exception as e:
            logger.warning(f"定时日志清理失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Automated UI Testing Agent...")

    # 初始化数据库
    await init_database()
    logger.info("Database initialized")

    # 创建必要目录
    os.makedirs(settings.LOG_DIR, exist_ok=True)
    os.makedirs(settings.SCREENSHOT_DIR, exist_ok=True)
    os.makedirs(settings.REPORT_OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(settings.UPLOAD_DIR, "documents"), exist_ok=True)

    # 注册 LangChain 工具
    tool_registry.register_all()
    logger.info("LangChain tools registered")

    # 初始化 LangGraph Agent（如果配置了大模型）
    if settings.AI_API_KEY and settings.AI_API_URL:
        init_langgraph_agent(
            api_key=settings.AI_API_KEY,
            base_url=settings.AI_API_URL,
            model_name=settings.AI_MODEL
        )
        logger.info("LangGraph Agent initialized")

    # 启动日志定时清理后台任务
    cleanup_task = asyncio.create_task(_log_cleanup_loop())
    logger.info("日志定时清理任务已启动（保留 {} 天）".format(
        getattr(settings, "LOG_RETENTION_DAYS", 7)
    ))

    # 从数据库加载全局变量到内存缓存
    from skills.param_resolver import load_global_vars
    await load_global_vars()
    logger.info("全局变量池已加载")

    # 初始化默认管理员账号
    from api.auth import hash_password
    from sqlalchemy import select
    from tools.database import async_session_maker, User
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.username == settings.DEFAULT_USERNAME))
        if not result.scalar_one_or_none():
            db.add(User(
                username=settings.DEFAULT_USERNAME,
                password_hash=hash_password(settings.DEFAULT_PASSWORD),
                role="admin"
            ))
            await db.commit()
            logger.info(f"默认管理员账号已创建：{settings.DEFAULT_USERNAME} / {settings.DEFAULT_PASSWORD}")

    yield

    # 关闭时取消清理任务
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutting down...")


app = FastAPI(
    title="AI 测试工具平台",
    description=(
        "基于 AI 大模型 + LangGraph + Playwright 的智能化零代码全场景自动化测试平台。\n\n"
        "**核心能力：**\n"
        "- **AI 用例生成**：上传需求文档，分段调用大模型按功能模块并行生成测试用例，支持导出 Markdown / XMind\n"
        "- **WebUI 自动化**：解析页面元素，AI 生成可直接被 Playwright 执行的 UI 自动化测试用例\n"
        "- **接口自动化**：支持 AI 生成接口用例、断言、变量提取、前置依赖、压力测试与全局变量池\n"
        "- **测试计划**：跨项目接口用例编排，共享变量上下文，实现端到端链路测试\n"
        "- **多模型支持**：兼容 Claude / DeepSeek / GPT / Gemini / Ollama 等任意 OpenAI 兼容接口\n"
        "- **实时推送**：所有耗时操作通过 WebSocket 实时推送进度，无需轮询\n\n"
        "**GitHub**：https://github.com/ywq2019/ai_test_agent"
    ),
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# ── 全局异常处理：屏蔽堆栈信息，统一返回格式 ─────────────────────────────────
from fastapi import HTTPException as FastAPIHTTPException

@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error [{request.method} {request.url.path}]: {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── JWT 鉴权中间件 ────────────────────────────────────────────────────────────
# 白名单：不需要 token 的路径前缀
_AUTH_WHITELIST = (
    "/api/v1/auth/login",
    "/api/v1/health",
    "/ws",
    "/assets",
    "/screenshots",
    "/reports",
)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # 白名单路径直接放行
    if any(path.startswith(w) for w in _AUTH_WHITELIST):
        return await call_next(request)
    # 非 API 路径（前端页面）放行
    if not path.startswith("/api/"):
        return await call_next(request)
    # 验证 token
    from api.auth import decode_token
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token or not decode_token(token):
        return JSONResponse(
            status_code=401,
            content={"detail": "未登录或 Token 已过期"}
        )
    return await call_next(request)

# 挂载前端构建产物（模块级，目录固定存在）
_dist_dir = os.path.join(os.path.dirname(__file__), "ui", "dist")
if os.path.exists(_dist_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist_dir, "assets")), name="assets")

# 挂载截图目录（执行报告中的截图查看）
_screenshots_dir = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(_screenshots_dir, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=_screenshots_dir), name="screenshots")

app.include_router(api_router, prefix="/api/v1")
app.websocket("/ws")(websocket_endpoint)


@app.get("/")
async def root():
    """返回前端页面"""
    index_file = os.path.join(_dist_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "AI 测试工具平台 API", "version": settings.APP_VERSION}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    """Vue Router history 模式支持：所有非 API 路径返回 index.html"""
    # API / WS / 静态资源路径不拦截
    if full_path.startswith(("api/", "ws", "screenshots/", "reports/", "assets/")):
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    index_file = os.path.join(_dist_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    from fastapi import HTTPException
    raise HTTPException(status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)
