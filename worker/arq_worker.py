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

Worker 启动：
  python -m worker.arq_worker
  # 或 Docker：单独起一个 app-worker 容器
"""

from __future__ import annotations
import logging
from typing import Optional

from arq import ArqRedis

logger = logging.getLogger(__name__)

# ── 全局连接池（lifespan 中初始化） ────────────────────────────────────────────
_arq_pool: Optional[ArqRedis] = None


def get_arq_pool() -> Optional[ArqRedis]:
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
      - 重试策略（job_retry=2）
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


# ── Worker 配置（arq worker 读取此处配置）──────────────────────────────────────

class WorkerSettings:
    """arq worker 配置。启动命令：arq worker.arq_worker.WorkerSettings"""

    functions = [
        task_generate_ai_cases,
        task_run_pentest,
        task_execute_plan,
        task_run_execution,
    ]

    @property
    def redis_settings(self):
        from tools.config import settings
        from arq.connections import RedisSettings
        return RedisSettings.from_dsn(settings.REDIS_URL or "redis://localhost:6379/0")

    max_jobs = 20           # 与 settings.ARQ_MAX_JOBS 一致
    job_timeout = 3600      # 单任务超时 1 小时
    max_tries = 2           # 失败最多重试 1 次（共执行 2 次）
    keep_result = 3600      # 结果保留 1 小时供查询
