"""
日志配置
"""
import sys
import time
from loguru import logger
from pathlib import Path
from tools.config import settings

log_dir = Path(settings.LOG_DIR)
log_dir.mkdir(exist_ok=True)

# 日志保留天数（可通过 settings 覆盖）
LOG_RETENTION_DAYS = int(getattr(settings, "LOG_RETENTION_DAYS", 7))

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    log_dir / "app_{time:YYYY-MM-DD}.log",
    rotation="00:00",             # 每天零点滚动
    retention=f"{LOG_RETENTION_DAYS} days",  # 保留 N 天
    compression="zip",            # 旧文件压缩节省空间
    level="DEBUG",
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
)


def clean_logs(retention_days: int = LOG_RETENTION_DAYS) -> dict:
    """
    清理 logs 目录中的过期文件。

    规则：
    - app_*.log / app_*.log.zip : 超过 retention_days 天的删除
    - backend.log / server*.log / server*.txt : 超过 retention_days 天未修改则清空（truncate），
      保留文件本身（避免外部脚本因文件消失报错）
    返回清理摘要 dict。
    """
    now = time.time()
    cutoff = now - retention_days * 86400
    removed, truncated, errors = [], [], []

    for path in log_dir.iterdir():
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
            name = path.name

            # loguru 滚动日志（含压缩包）：直接删除
            if name.startswith("app_") and (name.endswith(".log") or name.endswith(".log.zip")):
                if mtime < cutoff:
                    path.unlink()
                    removed.append(name)

            # 固定名称的杂项日志：超期则清空内容，保留文件
            elif name in ("backend.log", "server.log", "server_err.log",
                          "server_err.txt", "server_out.txt"):
                if mtime < cutoff:
                    path.write_bytes(b"")
                    truncated.append(name)

        except Exception as e:
            errors.append(f"{path.name}: {e}")

    summary = {
        "retention_days": retention_days,
        "removed": removed,
        "truncated": truncated,
        "errors": errors,
    }
    logger.info(
        "日志清理完成: 删除 {} 个旧日志, 清空 {} 个固定日志{}",
        len(removed), len(truncated),
        f", 异常 {errors}" if errors else ""
    )
    return summary
