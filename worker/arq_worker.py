"""
ARQ 异步任务队列 — 任务注册中心

设计原则：
  - Redis 不可用时调用方降级为 BackgroundTasks，不影响现有逻辑
  - 任务函数统一在此注册，worker 和路由共享同一份定义
  - 每个任务函数签名 async def task_fn(ctx, **kwargs) -> dict
    ctx 是 arq worker context（含 redis 连接），kwargs 是业务参数

降级策略：
  get_arq_pool() 返回 None 时表示 Redis 不可用，
  路由层判断后回退到 background_tasks.add_task()。

Worker 启动（两种方式）：
  # 直接启动
  arq worker.arq_worker.WorkerSettings

  # Docker（--profile worker）
  docker compose --profile worker up -d

  # 多实例扩容
  docker compose --profile worker up -d --scale worker=3
"""

from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── 全局连接池（lifespan 中初始化） ────────────────────────────────────────────
_arq_pool = None


def get_arq_pool():
    """返回 ARQ Redis 连接池；未初始化或 Redis 不可用时返回 None。"""
    return _arq_pool


async def init_arq_pool() -> bool:
    """
    尝试连接 Redis 并初始化 ARQ 连接池。
    返回 True 表示成功，False 表示 Redis 不可用（降级模式）。
    """
    global _arq_pool
    from tools.config import settings
    if not settings.REDIS_URL:
        logger.info("[ARQ] REDIS_URL 未配置，任务队列运行在降级模式（BackgroundTasks）")
        return False
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
        redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
        _arq_pool = await create_pool(redis_settings)
        logger.info(f"[ARQ] Redis 连接成功: {settings.REDIS_URL}")
        return True
    except Exception as e:
        logger.warning(f"[ARQ] Redis 连接失败，降级为 BackgroundTasks 模式: {e}")
        _arq_pool = None
        return False


async def close_arq_pool() -> None:
    """关闭 ARQ 连接池（lifespan 结束时调用）。"""
    global _arq_pool
    if _arq_pool:
        await _arq_pool.close()
        _arq_pool = None
        logger.info("[ARQ] Redis 连接池已关闭")


# ── ARQ 任务函数（与 worker 共享）──────────────────────────────────────────────

async def task_generate_ai_cases(
    ctx: dict,
    record_id: int,
    task_name: str,
    document_path: Optional[str],
    content: Optional[str],
    formats: list,
) -> dict:
    """
    ARQ 任务：AI 用例后台生成。

    等价于原 _do_generate_bg，但由 ARQ worker 执行，支持：
      - 任务持久化（进程重启不丢失）
      - 重试策略（max_tries=2）
      - 多 worker 横向扩展
    """
    from api.routes.ai_cases import _do_generate_bg
    await _do_generate_bg(
        record_id=record_id,
        task_name=task_name,
        document_path=document_path,
        content=content,
        formats=formats,
    )
    return {"record_id": record_id, "status": "done"}


async def task_run_pentest(ctx: dict, task_id: int) -> dict:
    """ARQ 任务：渗透测试扫描。"""
    from api.routes.pentest import _bg_run
    await _bg_run(task_id)
    return {"task_id": task_id, "status": "done"}


async def task_execute_plan(
    ctx: dict,
    plan_id: int,
    callback_url: Optional[str] = None,
    executed_by: str = "system",
) -> dict:
    """ARQ 任务：测试计划执行。"""
    from api.routes.test_plans import _execute_plan_bg
    await _execute_plan_bg(plan_id, callback_url=callback_url, executed_by=executed_by)
    return {"plan_id": plan_id, "status": "done"}


async def task_run_execution(
    ctx: dict,
    report_id: int,
    task_id: int,
    task_name: str,
    task_url: str,
    case_dicts: list,
    case_ids: Optional[list],
    browser: str,
    workspace_id: Optional[int],
) -> dict:
    """ARQ 任务：WebUI 用例执行。"""
    from api.routes.webui import _run_execution_bg
    await _run_execution_bg(
        report_id=report_id, task_id=task_id, task_name=task_name,
        task_url=task_url, case_dicts=case_dicts, case_ids=case_ids,
        browser=browser, workspace_id=workspace_id,
    )
    return {"report_id": report_id, "status": "done"}


# ── Worker 生命周期钩子 ────────────────────────────────────────────────────────

async def on_worker_startup(ctx: dict) -> None:
    """
    Worker 进程启动时执行：
    - 初始化数据库连接（ORM + 迁移）
    - 加载全局变量池
    - 重置上次崩溃时卡住的任务状态
    """
    logger.info("[ARQ worker] 启动中...")

    # 初始化数据库
    from tools.database import init_database
    await init_database()
    logger.info("[ARQ worker] 数据库已就绪")

    # 加载全局变量池
    from skills.param_resolver import load_global_vars
    await load_global_vars()
    logger.info("[ARQ worker] 全局变量池已加载")

    # 重置卡住的 AI 生成任务（worker 崩溃时可能遗留 generating 状态）
    from sqlalchemy import update as _sql_update
    from tools.database import async_session_maker, AICaseFile
    async with async_session_maker() as db:
        result = await db.execute(
            _sql_update(AICaseFile)
            .where(AICaseFile.gen_status == "generating")
            .values(gen_status="failed")
            .returning(AICaseFile.id)
        )
        stuck = [row[0] for row in result.fetchall()]
        await db.commit()
    if stuck:
        logger.warning(f"[ARQ worker] 重置 {len(stuck)} 个卡住的生成任务: ids={stuck}")

    logger.info("[ARQ worker] 启动完成，等待任务...")


async def on_worker_shutdown(ctx: dict) -> None:
    """Worker 进程关闭时清理资源。"""
    logger.info("[ARQ worker] 正在关闭...")


# ── Worker 配置 ────────────────────────────────────────────────────────────────

def _get_redis_settings():
    """从环境变量读取 Redis 配置，供 WorkerSettings 调用。"""
    from tools.config import settings
    from arq.connections import RedisSettings
    return RedisSettings.from_dsn(settings.REDIS_URL or "redis://localhost:6379/0")


class WorkerSettings:
    """
    ARQ worker 配置。

    启动命令：
      arq worker.arq_worker.WorkerSettings

    Docker 多实例：
      docker compose --profile worker up -d --scale worker=3

    注意：arq 要求 redis_settings 为类变量（不能是 @property），
    此处使用延迟初始化方案兼容环境变量加载顺序。
    """

    functions = [
        task_generate_ai_cases,
        task_run_pentest,
        task_execute_plan,
        task_run_execution,
    ]

    on_startup = on_worker_startup
    on_shutdown = on_worker_shutdown

    # arq 读取此类属性作为 Redis 连接配置
    # 若 REDIS_URL 未配置，此处使用默认本地地址（worker 启动本身就依赖 Redis）
    redis_settings = _get_redis_settings()

    max_jobs = 20       # 单 worker 最大并发任务数；多 worker 时各自独立计数
    job_timeout = 3600  # 单任务超时 1 小时，超时自动 cancel 并标记失败
    max_tries = 2       # 失败最多重试 1 次（共执行 2 次）
    keep_result = 3600  # 任务结果在 Redis 中保留 1 小时供查询
    queue_read_limit = 10  # 每次从队列取出的最大任务数，控制突发峰值
