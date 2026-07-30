"""
启动脚本：确保 asyncio 事件循环策略在 uvicorn 启动前正确设置。
Windows 上 Playwright 子进程启动需要 ProactorEventLoop。
"""
import sys
import asyncio

if sys.platform == "win32":
    # 必须在 uvicorn 导入之前设置，否则 uvicorn 会创建不兼容的事件循环
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn
from tools.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        workers=1,
        loop="none",   # 阻止 uvicorn 在 Windows 上覆盖为 SelectorEventLoopPolicy
                       # Playwright 需要 ProactorEventLoop 才能启动浏览器子进程
    )
