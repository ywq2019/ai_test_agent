"""
测试计划路由
  - /test-plans/*
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from loguru import logger

from tools.database import (
    get_db, ApiCase, ApiProject, ApiTestReport,
    TestPlan, TestPlanStep, TestPlanReport, User,
)
from api.auth import get_current_user, check_workspace_member, check_access
from api.websocket_manager import ws_manager
# 辅助函数由 api_test.py 提供（避免重复定义）
from api.routes.api_test import (
    _plan_dict, _step_dict, _plan_report_dict, _md_to_html,
)

router = APIRouter()

@router.get("/test-plans")
async def list_test_plans(workspace_id: int = None, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(TestPlan).order_by(TestPlan.created_at.desc())
    if current_user.role != "admin":
        from sqlalchemy import false as sql_false
        from tools.database import ProjectMember
        from sqlalchemy import select as _sel
        if workspace_id is None:
            stmt = stmt.where(sql_false())
        else:
            m = await db.execute(_sel(ProjectMember).where(
                ProjectMember.project_id == workspace_id,
                ProjectMember.username == current_user.username,
            ))
            if not m.scalar_one_or_none():
                stmt = stmt.where(sql_false())
            else:
                stmt = stmt.where(TestPlan.workspace_id == workspace_id)
    plans = (await db.execute(stmt)).scalars().all()
    if not plans:
        return []
    # 一次 GROUP BY 查询所有计划的步骤数，避免 N+1
    from sqlalchemy import func
    plan_ids = [p.id for p in plans]
    step_counts_rows = (await db.execute(
        select(TestPlanStep.plan_id, func.count(TestPlanStep.id).label("cnt"))
        .where(TestPlanStep.plan_id.in_(plan_ids))
        .group_by(TestPlanStep.plan_id)
    )).all()
    step_count_map = {row.plan_id: row.cnt for row in step_counts_rows}
    result = []
    for p in plans:
        d = _plan_dict(p)
        d["step_count"] = step_count_map.get(p.id, 0)
        result.append(d)
    return result


@router.post("/test-plans")
async def create_test_plan(data: dict, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="计划名称不能为空")
    ws_id = data.get("workspace_id")
    if ws_id:
        await check_workspace_member(db, ws_id, current_user, "创建测试计划")
    plan = TestPlan(
        name=name, description=data.get("description", ""),
        project_id=data.get("project_id"), proxy_url=data.get("proxy_url", ""),
        hosts_map=data.get("hosts_map", ""), status="pending",
        workspace_id=data.get("workspace_id"),
        created_by=current_user.username,
    )
    db.add(plan)
    await db.flush()
    for idx, s in enumerate(data.get("steps") or []):
        db.add(TestPlanStep(
            plan_id=plan.id, case_id=s.get("case_id"), case_project_id=s.get("case_project_id"),
            sort_order=s.get("sort_order", idx), enabled=s.get("enabled", True),
        ))
    await db.commit()
    await db.refresh(plan)
    return _plan_dict(plan)


@router.get("/test-plans/{plan_id}")
async def get_test_plan(plan_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    await check_access(db, plan, current_user, "测试计划")
    steps_rows = (await db.execute(
        select(TestPlanStep).where(TestPlanStep.plan_id == plan_id).order_by(TestPlanStep.sort_order)
    )).scalars().all()
    case_ids    = [s.case_id for s in steps_rows]
    project_ids = list({s.case_project_id for s in steps_rows if s.case_project_id})
    cases_map, projects_map = {}, {}
    if case_ids:
        cases_map = {c.id: c for c in (await db.execute(select(ApiCase).where(ApiCase.id.in_(case_ids)))).scalars().all()}
    if project_ids:
        projects_map = {p.id: p for p in (await db.execute(select(ApiProject).where(ApiProject.id.in_(project_ids)))).scalars().all()}
    steps = [
        _step_dict(
            s,
            case_name=getattr(cases_map.get(s.case_id), "name", f"[用例#{s.case_id}]"),
            module=getattr(cases_map.get(s.case_id), "module", "") or "",
            project_name=getattr(projects_map.get(s.case_project_id), "name", "") or "",
        )
        for s in steps_rows
    ]
    return _plan_dict(plan, steps)


@router.put("/test-plans/{plan_id}")
async def update_test_plan(plan_id: int, data: dict, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from datetime import datetime as _dt
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    await check_access(db, plan, current_user, "测试计划")
    for field in ("name", "description", "project_id", "proxy_url", "hosts_map"):
        if field in data:
            setattr(plan, field, data[field])
    plan.updated_at = _dt.utcnow()
    await db.commit()
    await db.refresh(plan)
    return _plan_dict(plan)


@router.delete("/test-plans/{plan_id}")
async def delete_test_plan(plan_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete as sql_delete
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    await check_access(db, plan, current_user, "测试计划")
    await db.execute(sql_delete(TestPlanStep).where(TestPlanStep.plan_id == plan_id))
    await db.execute(sql_delete(TestPlanReport).where(TestPlanReport.plan_id == plan_id))
    await db.delete(plan)
    await db.commit()
    return {"message": f"测试计划 '{plan.name}' 已删除"}


@router.post("/test-plans/{plan_id}/steps")
async def add_plan_steps(
    plan_id: int, data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import delete as sql_delete
    from datetime import datetime as _dt
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    await check_access(db, plan, current_user, "测试计划")
    if data.get("replace", False):
        await db.execute(sql_delete(TestPlanStep).where(TestPlanStep.plan_id == plan_id))
    for idx, s in enumerate(data.get("steps") or []):
        db.add(TestPlanStep(
            plan_id=plan_id, case_id=s.get("case_id"), case_project_id=s.get("case_project_id"),
            sort_order=s.get("sort_order", idx), enabled=s.get("enabled", True),
        ))
    plan.updated_at = _dt.utcnow()
    await db.commit()
    return {"message": "步骤已保存"}


@router.delete("/test-plans/{plan_id}/steps/{step_id}")
async def delete_plan_step(
    plan_id: int, step_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = (await db.execute(
        select(TestPlanStep).where(TestPlanStep.id == step_id, TestPlanStep.plan_id == plan_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="步骤不存在")
    # 校验对所属计划的访问权限
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if plan:
        await check_access(db, plan, current_user, "测试计划")
    await db.delete(s)
    await db.commit()
    return {"message": "步骤已删除"}


@router.post("/test-plans/{plan_id}/run")
async def run_test_plan(
    plan_id: int, background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db), force: bool = False,
    current_user: User = Depends(get_current_user),
):
    from datetime import datetime as _dt
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    await check_access(db, plan, current_user, "测试计划")
    if plan.status == "running" and not force:
        raise HTTPException(status_code=409, detail="计划正在执行中，如需强制重跑请传 force=true")
    plan.status = "running"
    plan.updated_at = _dt.utcnow()
    await db.commit()
    background_tasks.add_task(_execute_plan_bg, plan_id, executed_by=current_user.username)
    return {"message": "测试计划已开始执行", "plan_id": plan_id}


# ── CI/CD Webhook 触发 ────────────────────────────────────────────────────────

@router.post("/test-plans/{plan_id}/trigger")
async def trigger_test_plan(
    plan_id: int,
    background_tasks: BackgroundTasks,
    token: str,                          # ?token=xxx 查询参数，无需 JWT
    force: bool = False,
    callback_url: Optional[str] = None,  # 执行完成后回调的 URL（可选）
    db: AsyncSession = Depends(get_db),
):
    """
    CI/CD Webhook 触发接口，无需 JWT，用 token 鉴权。

    用法（Jenkins / GitHub Actions）：
        curl -X POST "http://your-host:4000/api/v1/test-plans/{plan_id}/trigger?token=xxx"
        curl -X POST "...?token=xxx&callback_url=https://ci.example.com/hook"

    token 通过 PUT /test-plans/{plan_id}/webhook-token 获取。
    """
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    # token 鉴权：未配置 token 或 token 不匹配均拒绝
    if not plan.webhook_token or plan.webhook_token != token:
        raise HTTPException(status_code=401, detail="无效的 webhook token")
    if plan.status == "running" and not force:
        raise HTTPException(status_code=409, detail="计划正在执行中，如需强制重跑请传 force=true")

    from datetime import datetime as _dt
    plan.status = "running"
    plan.updated_at = _dt.utcnow()
    await db.commit()
    background_tasks.add_task(_execute_plan_bg, plan_id, callback_url=callback_url, executed_by="webhook")
    logger.info(f"[webhook] 计划 {plan_id}「{plan.name}」由 CI/CD 触发")
    return {
        "message": "测试计划已由 webhook 触发",
        "plan_id": plan_id,
        "plan_name": plan.name,
    }


@router.put("/test-plans/{plan_id}/webhook-token")
async def set_webhook_token(
    plan_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    生成或更新 webhook token。
    body: {} 表示自动生成新 token；{"token": "your-token"} 表示手动指定。
    """
    import secrets
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    await check_access(db, plan, current_user, "测试计划")

    new_token = data.get("token") or secrets.token_urlsafe(32)
    if len(new_token) < 16:
        raise HTTPException(status_code=400, detail="token 长度不能少于 16 个字符")

    plan.webhook_token = new_token
    await db.commit()
    return {
        "plan_id": plan_id,
        "webhook_token": new_token,
        "trigger_url": f"/api/v1/test-plans/{plan_id}/trigger?token={new_token}",
    }


@router.delete("/test-plans/{plan_id}/webhook-token")
async def revoke_webhook_token(
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤销 webhook token，撤销后 CI/CD 触发将返回 401。"""
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    await check_access(db, plan, current_user, "测试计划")
    plan.webhook_token = None
    await db.commit()
    return {"message": "webhook token 已撤销", "plan_id": plan_id}


async def _execute_plan_bg(plan_id: int, callback_url: Optional[str] = None, executed_by: str = ""):
    """后台执行测试计划：顺序执行 + 共享 var_store + 步骤级报告。
    callback_url：可选，执行完成后向该 URL 发送 POST 回调（用于 CI/CD 流水线状态通知）。
    """
    import httpx
    from sqlalchemy import select as _sel, or_
    from skills.api_executor import ApiExecutor
    from skills.param_resolver import flush_global_vars
    from datetime import datetime as _dt
    from tools.database import async_session_maker as _session_maker

    executor = ApiExecutor()
    step_results = []
    var_store: dict = {}
    final_status = "failed"
    plan_name = ""
    plan_workspace_id = None
    report_id = None

    try:
        steps_plain, cases_plain, projects_plain = [], {}, {}
        custom_scripts, scripts_by_project = [], {}

        async with _session_maker() as db:
            plan = (await db.execute(_sel(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
            if not plan:
                logger.warning(f"[plan_exec] 计划 {plan_id} 不存在")
                return
            plan_name           = plan.name
            plan_workspace_id   = plan.workspace_id
            plan_proxy_url      = plan.proxy_url or ""
            plan_hosts_map_text = plan.hosts_map or ""

            steps_rows = (await db.execute(
                _sel(TestPlanStep).where(TestPlanStep.plan_id == plan_id, TestPlanStep.enabled == True)
                .order_by(TestPlanStep.sort_order)
            )).scalars().all()

            if not steps_rows:
                plan.status = "passed"
                plan.updated_at = _dt.utcnow()
                await db.commit()
                await ws_manager.broadcast_to_workspace({"type": "plan_done", "plan_id": plan_id,
                                                "plan_name": plan_name,
                                                "total": 0, "passed": 0, "failed": 0, "pass_rate": 100, "status": "passed"},
                                                plan_workspace_id)
                return

            steps_plain = [{"case_id": s.case_id, "case_project_id": s.case_project_id, "sort_order": s.sort_order}
                           for s in steps_rows]
            project_ids = list({s["case_project_id"] for s in steps_plain if s["case_project_id"]})
            if project_ids:
                projs = (await db.execute(_sel(ApiProject).where(ApiProject.id.in_(project_ids)))).scalars().all()
                projects_plain = {p.id: {"id": p.id, "name": p.name, "base_url": p.base_url or "",
                                          "auth_type": p.auth_type or "none", "auth_config": p.auth_config or {},
                                          "global_headers": p.global_headers or {},
                                          "proxy_url": p.proxy_url or "", "hosts_map": p.hosts_map or ""}
                                  for p in projs}
            case_ids = [s["case_id"] for s in steps_plain]
            cases_rows = (await db.execute(_sel(ApiCase).where(ApiCase.id.in_(case_ids)))).scalars().all()
            cases_plain = {c.id: ApiExecutor._case_to_dict(c) for c in cases_rows}

            all_pid = list({s["case_project_id"] for s in steps_plain if s["case_project_id"]})
            if plan.project_id and plan.project_id not in all_pid:
                all_pid.append(plan.project_id)
            scripts_rows = (await db.execute(
                _sel(CustomScript).where(or_(
                    CustomScript.project_id.in_(all_pid) if all_pid else False,
                    CustomScript.project_id == None,
                ))
            )).scalars().all()
            global_scripts = [{"name": s.name, "code": s.code} for s in scripts_rows if s.project_id is None]
            for s in scripts_rows:
                if s.project_id is None:
                    continue
                scripts_by_project.setdefault(s.project_id, []).append({"name": s.name, "code": s.code})
            for pid in all_pid:
                proj_scripts = scripts_by_project.get(pid, [])
                proj_names = {s["name"] for s in proj_scripts}
                scripts_by_project[pid] = proj_scripts + [s for s in global_scripts if s["name"] not in proj_names]

        total_steps = len(steps_plain)
        for idx, step in enumerate(steps_plain):
            case_dict = cases_plain.get(step["case_id"])
            if not case_dict:
                step_results.append({"step": idx+1, "case_id": step["case_id"],
                                     "case_name": f"[用例#{step['case_id']} 不存在]",
                                     "status": "skipped", "error": "用例不存在",
                                     "duration_ms": 0, "assertions": [], "extracted_vars": {}, "response_preview": ""})
                continue
            proj           = projects_plain.get(step["case_project_id"], {})
            base_url       = (proj.get("base_url", "") or "").rstrip("/")
            auth_headers   = executor.build_auth_headers(proj) if proj else {}
            global_headers = proj.get("global_headers") or {}
            project_name   = proj.get("name", "")
            step_scripts   = scripts_by_project.get(step["case_project_id"], global_scripts)
            effective_proxy = plan_proxy_url or proj.get("proxy_url", "")
            if effective_proxy and "://" not in effective_proxy:
                effective_proxy = "http://" + effective_proxy
            _proxy_kwargs = {"proxies": {"all://": effective_proxy}} if effective_proxy else {}
            from skills.api_executor import parse_hosts_map, make_transport
            _hosts_map = {**parse_hosts_map(proj.get("hosts_map") or ""), **parse_hosts_map(plan_hosts_map_text)}
            _transport = make_transport(_hosts_map, verify=False)
            await ws_manager.broadcast_all({"type": "plan_step_start", "plan_id": plan_id,
                                            "step": idx+1, "total": total_steps,
                                            "case_name": case_dict.get("name", "")})
            try:
                async with httpx.AsyncClient(transport=_transport, verify=False, timeout=30.0, **_proxy_kwargs) as client:
                    result = await executor._run_case(
                        client, base_url, case_dict, auth_headers, global_headers,
                        var_store=var_store, custom_scripts=step_scripts, project_name=project_name,
                    )
            except Exception as step_err:
                result = {"case_id": case_dict.get("id"), "case_name": case_dict.get("name", ""),
                          "method": case_dict.get("method", ""), "url": base_url + case_dict.get("path", ""),
                          "status_code": None, "duration_ms": 0, "status": "failed",
                          "assertions": [], "error": str(step_err), "extracted_vars": {}, "response_preview": ""}
            step_results.append({"step": idx+1, "case_id": case_dict.get("id"),
                                  "case_name": case_dict.get("name", ""), "module": case_dict.get("module", ""),
                                  "project_name": project_name, "method": result.get("method", ""),
                                  "url": result.get("url", ""), "status_code": result.get("status_code"),
                                  "duration_ms": result.get("duration_ms", 0), "status": result.get("status", "failed"),
                                  "assertions": result.get("assertions", []), "error": result.get("error", ""),
                                  "extracted_vars": result.get("extracted_vars", {}),
                                  "response_preview": result.get("response_preview", "")})
            await ws_manager.broadcast_all({"type": "plan_step_done", "plan_id": plan_id,
                                            "step": idx+1, "total": total_steps,
                                            "case_name": case_dict.get("name", ""),
                                            "status": result.get("status"), "duration_ms": result.get("duration_ms", 0),
                                            "method": result.get("method", ""), "status_code": result.get("status_code"),
                                            "error": result.get("error", ""), "var_store": dict(var_store)})

        passed      = sum(1 for r in step_results if r["status"] == "passed")
        total       = len(step_results)
        failed_count = total - passed
        pass_rate   = round(passed / total * 100, 1) if total else 0
        final_status = "passed" if failed_count == 0 else "failed"

        async with _session_maker() as db:
            try:
                await flush_global_vars(source_project=f"plan:{plan_id}", workspace_id=plan_workspace_id)
            except Exception as fv_err:
                logger.warning(f"[plan_exec] flush_global_vars 失败: {fv_err}")
            report = TestPlanReport(plan_id=plan_id, plan_name=plan_name, total=total,
                                    passed=passed, failed=failed_count, pass_rate=pass_rate,
                                    details=step_results, var_snapshot=dict(var_store),
                                    created_by=executed_by or "")
            db.add(report)
            plan_upd = (await db.execute(_sel(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
            if plan_upd:
                plan_upd.status = final_status
                plan_upd.updated_at = _dt.utcnow()
            await db.commit()
            await db.refresh(report)
            report_id = report.id

    except Exception as e:
        logger.error(f"[plan_exec] 计划 {plan_id} 执行异常: {e}", exc_info=True)
        try:
            async with _session_maker() as db:
                plan_upd = (await db.execute(_sel(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
                if plan_upd:
                    plan_upd.status = "failed"
                    plan_upd.updated_at = _dt.utcnow()
                    await db.commit()
        except Exception:
            pass

    passed      = sum(1 for r in step_results if r["status"] == "passed")
    total       = len(step_results)
    failed_count = total - passed
    pass_rate   = round(passed / total * 100, 1) if total else 0
    await ws_manager.broadcast_to_workspace({"type": "plan_done", "plan_id": plan_id, "plan_name": plan_name, "report_id": report_id,
                                    "total": total, "passed": passed, "failed": failed_count,
                                    "pass_rate": pass_rate, "status": final_status}, plan_workspace_id)

    # CI/CD 回调：执行完成后向 callback_url 发送 POST 通知
    if callback_url:
        import httpx as _httpx
        payload = {
            "plan_id": plan_id, "plan_name": plan_name,
            "status": final_status, "report_id": report_id,
            "total": total, "passed": passed, "failed": failed_count,
            "pass_rate": pass_rate,
        }
        try:
            async with _httpx.AsyncClient(timeout=10, verify=False) as _c:
                resp = await _c.post(callback_url, json=payload)
            logger.info(f"[webhook] 回调成功: {callback_url} → {resp.status_code}")
        except Exception as cb_err:
            logger.warning(f"[webhook] 回调失败: {callback_url} → {cb_err}")


# ── 辅助：报告访问校验 ────────────────────────────────────────────────────────
async def _check_report_access(db: AsyncSession, report, current_user: User):
    """通过报告的 plan_id 追溯 TestPlan，校验工作空间访问权限。"""
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == report.plan_id))).scalar_one_or_none()
    if plan:
        await check_access(db, plan, current_user, "测试报告")


@router.get("/test-plans/{plan_id}/reports")
async def list_plan_reports(plan_id: int, db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    # 先校验计划访问权限
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    await check_access(db, plan, current_user, "测试计划")
    rows = (await db.execute(
        select(TestPlanReport).where(TestPlanReport.plan_id == plan_id).order_by(TestPlanReport.id.desc())
    )).scalars().all()
    result = []
    for r in rows:
        d = _plan_report_dict(r)
        d.pop("details", None)
        result.append(d)
    return result


@router.get("/test-plans/reports/{report_id}")
async def get_plan_report(report_id: int, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    await _check_report_access(db, r, current_user)
    return _plan_report_dict(r)


@router.get("/test-plans/reports/{report_id}/pdf")
async def export_plan_report_pdf(report_id: int, db: AsyncSession = Depends(get_db),
                                 current_user: User = Depends(get_current_user)):
    """将测试计划报告导出为详细 PDF。"""
    from fastapi.responses import Response
    from urllib.parse import quote
    from datetime import timezone, timedelta
    from tools.pdf_exporter import html_to_pdf

    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    await _check_report_access(db, r, current_user)

    _TZ = timezone(timedelta(hours=8))
    def _fmt(dt):
        if not dt: return "—"
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ).strftime("%Y-%m-%d %H:%M:%S")

    rdict     = _plan_report_dict(r)
    details   = rdict.get("details") or []
    total     = rdict.get("total", 0)
    passed    = rdict.get("passed", 0)
    failed    = rdict.get("failed", 0)
    pass_rate = rdict.get("pass_rate", 0)
    title     = f"{r.plan_name or '测试计划'} 报告"
    created   = _fmt(r.created_at)
    now       = __import__('datetime').datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")
    analysis  = rdict.get("analysis", "")
    executor  = rdict.get("created_by") or "—"
    pr_color  = "#52c41a" if pass_rate >= 80 else "#ff4d4f"

    # 变量快照
    var_snap = rdict.get("var_snapshot") or {}
    var_rows = "".join(
        f"<tr><td style='font-weight:500'>{k}</td><td style='word-break:break-all;color:#555'>{v}</td></tr>"
        for k, v in var_snap.items()
    ) if var_snap else "<tr><td colspan='2' style='color:#aaa;text-align:center'>无</td></tr>"

    rows = ""
    for d in details:
        st  = d.get("status", "")
        sty = {"passed": "background:#f6ffed;color:#389e0d", "failed": "background:#fff1f0;color:#cf1322"}.get(st, "background:#fffbe6;color:#ad6800")
        lbl = {"passed": "✓ 通过", "failed": "✗ 失败"}.get(st, st)
        err = str(d.get("error") or "—")[:300]
        # 断言详情
        assertions = d.get("assertions") or []
        asr_html = ""
        if assertions:
            asr_lines = []
            for a in assertions:
                ok = a.get("passed", True)
                ico = "✓" if ok else "✗"
                col = "#389e0d" if ok else "#cf1322"
                asr_lines.append(f"<span style='color:{col}'>{ico} {a.get('field','')} {a.get('comparator','')} {a.get('expected','')}</span>")
            asr_html = "<br>".join(asr_lines)
        rows += (
            f"<tr>"
            f"<td style='color:#aaa;text-align:center'>{d.get('step','')}</td>"
            f"<td style='font-weight:500'>{d.get('case_name','-')}</td>"
            f"<td style='font-size:11px;color:#666'>{d.get('project_name','')}</td>"
            f"<td><span class='method'>{d.get('method','')}</span></td>"
            f"<td style='text-align:center'>{d.get('status_code','—')}</td>"
            f"<td><span style='padding:2px 8px;border-radius:10px;font-size:11px;{sty}'>{lbl}</span></td>"
            f"<td style='text-align:right;color:#666'>{d.get('duration_ms',0)} ms</td>"
            f"<td style='font-size:11px;color:#888;word-break:break-all'>{err}</td>"
            f"<td style='font-size:11px;line-height:1.8'>{asr_html or '—'}</td>"
            f"</tr>"
        )

    analysis_block = ""
    if analysis:
        analysis_html = _md_to_html(analysis)
        analysis_block = f"""
<div class="section" style="page-break-inside:avoid">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;
              padding:10px 16px;border-radius:8px 8px 0 0;
              background:linear-gradient(90deg,#1d4ed8 0%,#3a7bd5 100%);color:#fff">
    <span style="font-size:18px">🤖</span>
    <span style="font-size:15px;font-weight:700;letter-spacing:.3px">AI 智能分析结论</span>
  </div>
  <div style="border:1px solid #c7d8f8;border-top:none;border-radius:0 0 8px 8px;
              padding:20px 24px;background:#f8fbff;line-height:1.75">
    {analysis_html}
  </div>
</div>"""

    html_str = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{title}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;color:#1a1a1a;font-size:13px;line-height:1.6}}
.cover{{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);color:#fff;padding:48px}}
.cover h1{{font-size:28px;font-weight:700;margin-bottom:6px}}
.cover .sub{{font-size:14px;opacity:.65;margin-bottom:24px}}
.cover .meta{{font-size:12px;opacity:.5;margin-top:16px}}
.body{{padding:32px 48px}}
.section{{margin-bottom:32px}}
.section h2{{font-size:17px;font-weight:700;padding-bottom:8px;border-bottom:2px solid #e8e8e8;margin-bottom:16px}}
.stats{{display:flex;gap:14px}}
.stat{{flex:1;background:#fafafa;border:1px solid #e8e8e8;border-radius:8px;padding:14px;text-align:center}}
.stat .n{{font-size:30px;font-weight:700}}.stat .l{{font-size:11px;color:#888;margin-top:2px}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:8px 10px;border:1px solid #e8e8e8;text-align:left;font-size:12px;vertical-align:top}}
th{{background:#f5f7fa;font-weight:600;color:#555}}
tr:nth-child(even) td{{background:#fafbff}}
.method{{display:inline-block;padding:1px 7px;border-radius:3px;font-size:11px;font-weight:700;background:#e6f4ff;color:#0958d9}}
.footer{{text-align:center;color:#bbb;font-size:11px;padding:20px 48px;border-top:1px solid #eee;margin-top:16px}}
@media print{{body{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}
</style></head><body>
<div class="cover">
  <div style="font-size:11px;opacity:.4;margin-bottom:10px;letter-spacing:2px">TEST PLAN REPORT</div>
  <h1>{title}</h1>
  <div class="sub">测试计划执行报告</div>
  <div style="display:flex;gap:24px;font-size:13px">
    <span>执行时间：{created}</span>
    <span>执行者：{executor}</span>
    <span>通过率：<b style="color:{'#52c41a' if pass_rate>=80 else '#ff4d4f'}">{pass_rate}%</b></span>
  </div>
  <div class="meta">导出时间：{now}</div>
</div>
<div class="body">
<div class="section">
  <h2>📊 执行统计</h2>
  <div class="stats">
    <div class="stat"><div class="n" style="color:#1890ff">{total}</div><div class="l">总步骤数</div></div>
    <div class="stat"><div class="n" style="color:#52c41a">{passed}</div><div class="l">通过</div></div>
    <div class="stat"><div class="n" style="color:#ff4d4f">{failed}</div><div class="l">失败</div></div>
    <div class="stat"><div class="n" style="color:{pr_color}">{pass_rate}%</div><div class="l">通过率</div></div>
  </div>
</div>
<div class="section">
  <h2>📋 步骤详情</h2>
  <table>
    <thead><tr><th style="width:36px">#</th><th>用例名称</th><th>所属项目</th><th style="width:60px">方法</th><th style="width:60px">状态码</th><th style="width:72px">结果</th><th style="width:72px">耗时</th><th>错误信息</th><th>断言结果</th></tr></thead>
    <tbody>{rows if rows else '<tr><td colspan="9" style="text-align:center;color:#aaa;padding:24px">暂无执行数据</td></tr>'}</tbody>
  </table>
</div>
<div class="section">
  <h2>🔑 变量快照</h2>
  <table>
    <thead><tr><th style="width:200px">变量名</th><th>值</th></tr></thead>
    <tbody>{var_rows}</tbody>
  </table>
</div>
{analysis_block}
</div>
<div class="footer">本报告由 AI 测试平台自动生成 · {now}</div>
</body></html>"""

    try:
        pdf_bytes = await html_to_pdf(html_str=html_str)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    encoded = quote(f"{r.plan_name or 'plan_report'}_{report_id}.pdf", safe="")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@router.delete("/test-plans/reports/batch")
async def delete_plan_reports_batch(ids: List[int], db: AsyncSession = Depends(get_db),
                                   current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete as sql_del
    if not ids:
        raise HTTPException(status_code=400, detail="未提供报告ID")
    # 校验所有报告所属计划的工作空间权限
    reports = (await db.execute(select(TestPlanReport).where(TestPlanReport.id.in_(ids)))).scalars().all()
    for r in reports:
        await _check_report_access(db, r, current_user)
    await db.execute(sql_del(TestPlanReport).where(TestPlanReport.id.in_(ids)))
    await db.commit()
    return {"message": f"已删除 {len(ids)} 条报告"}


@router.post("/test-plans/reports/{report_id}/analyze")
async def analyze_plan_report(report_id: int, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(get_current_user)):
    import httpx
    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    await _check_report_access(db, r, current_user)
    rdict    = _plan_report_dict(r)
    analysis = await _ai_analyze_plan_report(rdict)
    r.analysis = analysis
    await db.commit()
    return {"analysis": analysis}


async def _ai_analyze_plan_report(report: dict) -> str:
    import httpx
    total     = report.get("total", 0)
    passed    = report.get("passed", 0)
    failed    = report.get("failed", 0)
    pass_rate = report.get("pass_rate", 0)
    plan_name = report.get("plan_name", "")
    details   = report.get("details") or []
    failed_steps = [d for d in details if d.get("status") == "failed"]
    failed_summary = "\n".join(
        f"- 步骤 {d.get('step')} [{d.get('method','')} {d.get('url','')}] {d.get('case_name','')}: "
        f"{d.get('error') or '断言失败'}"
        for d in failed_steps[:20]
    )
    prompt = (
        f"以下是接口测试计划「{plan_name}」的执行报告，请分析失败原因并给出改进建议。\n\n"
        f"执行概况：共 {total} 个步骤，通过 {passed}，失败 {failed}，通过率 {pass_rate}%\n\n"
        + (f"失败步骤明细：\n{failed_summary}\n\n" if failed_steps else "所有步骤均通过。\n\n")
        + "请输出：\n1. 失败原因分析\n2. 修复建议\n3. 测试质量总结"
    )
    sys_msg = "你是一名资深测试工程师，擅长分析接口测试报告，给出精准、可操作的建议。用中文回答，使用 Markdown 格式输出。"
    from tools.llm_client import call_llm
    return await call_llm(sys_msg, prompt, max_tokens=2048, timeout_secs=90)


@router.delete("/test-plans/reports/{report_id}")
async def delete_plan_report(report_id: int, db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete as sql_del
    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    await _check_report_access(db, r, current_user)
    await db.execute(sql_del(TestPlanReport).where(TestPlanReport.id == report_id))
    await db.commit()
    return {"message": "报告已删除"}
