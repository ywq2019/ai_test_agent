"""
测试计划定时执行调度器 — 基于 APScheduler

服务启动时加载所有 cron_enabled=True 的测试计划，
更新计划 Cron 配置时动态增删 Job。
"""
import asyncio
from loguru import logger

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    _scheduler_available = True
except ImportError:
    _scheduler = None
    _scheduler_available = False
    logger.warning("[scheduler] APScheduler 未安装，定时执行功能不可用")


def _job_id(plan_id: int) -> str:
    return f"plan_cron_{plan_id}"


async def _run_plan(plan_id: int):
    """调度器触发：执行测试计划（复用 test_plans.py 的后台执行函数）。"""
    try:
        from api.routes.test_plans import _execute_plan_bg
        logger.info(f"[scheduler] Cron 触发计划 {plan_id}")
        await _execute_plan_bg(plan_id, executed_by="scheduler")
    except Exception as e:
        logger.error(f"[scheduler] 计划 {plan_id} Cron 执行异常: {e}", exc_info=True)


async def refresh_plan_schedule(plan) -> None:
    """根据计划的 cron_expr / cron_enabled 更新调度 Job。"""
    if not _scheduler_available:
        return
    job_id = _job_id(plan.id)
    # 先移除旧 Job
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
    # 如果启用且有表达式，重新添加
    if plan.cron_enabled and plan.cron_expr:
        try:
            _scheduler.add_job(
                _run_plan,
                trigger=CronTrigger.from_crontab(plan.cron_expr, timezone="Asia/Shanghai"),
                args=[plan.id],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info(f"[scheduler] 计划 {plan.id}「{plan.name}」已注册 Cron: {plan.cron_expr}")
        except Exception as e:
            logger.warning(f"[scheduler] 计划 {plan.id} Cron 表达式无效: {plan.cron_expr} → {e}")


async def init_scheduler() -> None:
    """服务启动时初始化：加载所有启用了 Cron 的计划。"""
    if not _scheduler_available:
        return
    from tools.database import async_session_maker, TestPlan
    from sqlalchemy import select
    async with async_session_maker() as db:
        plans = (await db.execute(
            select(TestPlan).where(TestPlan.cron_enabled == True, TestPlan.cron_expr != None)
        )).scalars().all()
    for plan in plans:
        await refresh_plan_schedule(plan)
    _scheduler.start()
    logger.info(f"[scheduler] APScheduler 已启动，加载 {len(plans)} 个 Cron 计划")


async def shutdown_scheduler() -> None:
    """服务关闭时停止调度器。"""
    if _scheduler_available and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] APScheduler 已停止")
