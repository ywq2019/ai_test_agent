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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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

    yield

    # 关闭时取消清理任务
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutting down...")


app = FastAPI(
    title="自动化UI测试Agent",
    description="智能化、零代码的Web UI自动化测试工具",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists(settings.SCREENSHOT_DIR):
    app.mount("/screenshots", StaticFiles(directory=settings.SCREENSHOT_DIR), name="screenshots")

if os.path.exists(settings.REPORT_OUTPUT_DIR):
    app.mount("/reports", StaticFiles(directory=settings.REPORT_OUTPUT_DIR), name="reports")

# 挂载前端构建产物
_dist_dir = os.path.join(os.path.dirname(__file__), "ui", "dist")
if os.path.exists(_dist_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist_dir, "assets")), name="assets")

app.include_router(api_router, prefix="/api/v1")
app.websocket("/ws")(websocket_endpoint)


@app.get("/")
async def root():
    """返回前端页面"""
    index_file = os.path.join(_dist_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "自动化UI测试Agent API", "version": "1.0.0"}


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
