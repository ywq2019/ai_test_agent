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
    AI_CASES_DIR: str = ""          # 留空时由 ai_case_generator 按规则推导，Docker 下设为 /data/ai_cases
    LOG_RETENTION_DAYS: int = 7     # 日志保留天数
    LLM_CONCURRENCY: int = 6        # 全局 LLM 并发上限
    LLM_SEM_TIMEOUT: int = 60       # LLM Semaphore 等待超时（秒），超时返回"系统繁忙"
    MAX_ACTIVE_GENERATE: int = 3    # 同时进行的 AI 生成任务上限，超出返回 429

    # ── 告警推送 ───────────────────────────────────────────────────────────────
    # 支持钉钉/企业微信/飞书 Webhook；留空则关闭告警
    ALERT_WEBHOOK_URL: str = ""
    # "dingtalk" | "wecom" | "feishu"
    ALERT_WEBHOOK_TYPE: str = "wecom"
    # 同一条错误在此秒数内只推送一次（防刷屏），默认 5 分钟
    ALERT_RATE_LIMIT_SECONDS: int = 300

    # ── 鉴权 ──────────────────────────────────────────────────────────────────
    SECRET_KEY: str = "ai-test-agent-secret-key-change-in-production-2024"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24 * 7   # token 有效期 7 天
    DEFAULT_USERNAME: str = "admin"
    DEFAULT_PASSWORD: str = "admin123"

    class Config:
        env_file = ".env"


settings = Settings()
