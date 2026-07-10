"""
项目配置管理
"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_NAME: str = "自动化UI测试Agent"
    APP_VERSION: str = "1.0.0"
    VERSION: str = "1.0.0"
    DEBUG: bool = True

    HOST: str = "0.0.0.0"
    PORT: int = 4000

    CORS_ORIGINS: List[str] = ["*"]

    DATABASE_URL: str = "sqlite+aiosqlite:///./uitest_agent.db"

    AI_API_KEY: str = ""
    AI_API_URL: str = "https://api.deepseek.com"
    AI_MODEL: str = "deepseek-v4-flash"
    AI_MODEL_NAME: str = "DeepSeek V4 Flash"
    AI_TEMPERATURE: float = 0.5

    PLAYWRIGHT_BROWSERS: List[str] = ["chromium", "firefox", "webkit"]
    DEFAULT_BROWSER: str = "chromium"

    MAX_UPLOAD_SIZE: int = 20 * 1024 * 1024
    DOCUMENT_TIMEOUT: int = 10
    ELEMENT_CAPTURE_TIMEOUT: int = 5

    REPORT_OUTPUT_DIR: str = "./reports"
    SCREENSHOT_DIR: str = "./screenshots"
    LOG_DIR: str = "./logs"
    UPLOAD_DIR: str = "./uploads"

    # ── 鉴权 ──────────────────────────────────────────────────────────────────
    SECRET_KEY: str = "ai-test-agent-secret-key-change-in-production-2024"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24 * 7   # token 有效期 7 天
    DEFAULT_USERNAME: str = "admin"
    DEFAULT_PASSWORD: str = "admin123"

    class Config:
        env_file = ".env"


settings = Settings()
