"""
项目配置管理
"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_NAME: str = "自动化UI测试Agent"
    VERSION: str = "1.0.0"
    DEBUG: bool = True

    CORS_ORIGINS: List[str] = ["*"]

    DATABASE_URL: str = "sqlite+aiosqlite:///./uitest_agent.db"

    AI_API_KEY: str = ""
    AI_API_URL: str = "https://api.openai.com/v1/chat/completions"
    AI_MODEL: str = "gpt-4"

    PLAYWRIGHT_BROWSERS: List[str] = ["chromium", "firefox", "webkit"]
    DEFAULT_BROWSER: str = "chromium"

    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024
    DOCUMENT_TIMEOUT: int = 10
    ELEMENT_CAPTURE_TIMEOUT: int = 5

    REPORT_OUTPUT_DIR: str = "./reports"
    SCREENSHOT_DIR: str = "./screenshots"
    LOG_DIR: str = "./logs"

    class Config:
        env_file = ".env"


settings = Settings()
