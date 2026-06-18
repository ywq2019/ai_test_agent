"""
自动化UI测试Agent - FastAPI应用入口
"""
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from api.routes import router as api_router
from api.websocket import websocket_endpoint
from tools.database import init_database
from tools.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Automated UI Testing Agent...")
    await init_database()
    logger.info("Database initialized")

    os.makedirs(settings.SCREENSHOT_DIR, exist_ok=True)
    os.makedirs(settings.REPORT_OUTPUT_DIR, exist_ok=True)

    yield
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

app.include_router(api_router, prefix="/api/v1")
app.websocket("/ws")(websocket_endpoint)


@app.get("/")
async def root():
    return {"message": "自动化UI测试Agent API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
