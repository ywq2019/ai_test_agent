"""
接口自动化路由（接口测试 / 压测 / 代码分析 / 全局变量 / 测试计划）
  - /api-test/*
  - /global-vars/*
  - /test-plans/*
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from loguru import logger

from tools.database import (
    get_db, ApiProject, ApiCase, ApiLoadConfig, ApiTestReport,
    CustomScript, GlobalVariable, TestPlan, TestPlanStep, TestPlanReport, User,
)
from api.auth import get_current_user, owner_filter, check_owner, workspace_filter, check_workspace_member, check_access
from api.websocket_manager import ws_manager
from tools.config import settings

router = APIRouter()


# ── 辅助字典构建 ──────────────────────────────────────────────────────────────

def _proj_dict(p: ApiProject) -> dict:
    # 清洗旧数据中 label 含 "undefined" 的前置用例条目，避免前端显示乱码
    raw_setup = p.setup_cases or []
    clean_setup = [
        sc for sc in raw_setup
        if isinstance(sc, dict)
        and sc.get("case_id") is not None
        and "undefined" not in str(sc.get("label", ""))
    ]
    return {
        "id": p.id, "name": p.name, "base_url": p.base_url,
        "description": p.description, "auth_type": p.auth_type,
        "auth_config": p.auth_config, "global_headers": p.global_headers,
        "setup_cases": clean_setup, "auth_error_patterns": p.auth_error_patterns or [],
        "proxy_url": p.proxy_url or "", "hosts_map": p.hosts_map or "",
        "workspace_id": p.workspace_id,
        "created_at": p.created_at.isoformat() if p.created_at else "",
    }


def _case_dict(c: ApiCase) -> dict:
    return {
        "id": c.id, "project_id": c.project_id, "name": c.name, "module": c.module,
        "method": c.method, "path": c.path, "headers": c.headers, "params": c.params,
        "body_type": c.body_type or "json", "body": c.body, "body_raw": c.body_raw or "",
        "assertions": c.assertions, "var_extracts": c.var_extracts or [],
        "priority": c.priority, "enabled": c.enabled, "description": c.description or "",
        "created_at": c.created_at.isoformat() if c.created_at else "",
    }


def _script_dict(s: CustomScript) -> dict:
    return {
        "id": s.id, "project_id": s.project_id, "name": s.name,
        "description": s.description, "code": s.code,
        "created_at": s.created_at.isoformat() if s.created_at else "",
    }


def _report_dict(r: ApiTestReport) -> dict:
    return {
        "id": r.id, "project_id": r.project_id, "project_name": r.project_name,
        "report_type": r.report_type, "total": r.total, "passed": r.passed,
        "failed": r.failed, "summary": r.summary, "details": r.details,
        "analysis": r.analysis or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


def _plan_dict(p: TestPlan, steps: list = None) -> dict:
    return {
        "id": p.id, "name": p.name, "description": p.description or "",
        "project_id": p.project_id, "status": p.status or "pending",
        "proxy_url": p.proxy_url or "", "hosts_map": p.hosts_map or "",
        "webhook_token": p.webhook_token or "",   # 供前端展示触发 URL
        "steps": steps or [],
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
    }


def _step_dict(s: TestPlanStep, case_name: str = "", module: str = "", project_name: str = "") -> dict:
    return {
        "id": s.id, "plan_id": s.plan_id, "case_id": s.case_id,
        "case_project_id": s.case_project_id, "case_name": case_name,
        "module": module, "project_name": project_name,
        "sort_order": s.sort_order, "enabled": s.enabled,
        "created_at": s.created_at.isoformat() if s.created_at else "",
    }


def _plan_report_dict(r: TestPlanReport) -> dict:
    return {
        "id": r.id, "plan_id": r.plan_id, "plan_name": r.plan_name or "",
        "total": r.total, "passed": r.passed, "failed": r.failed,
        "pass_rate": r.pass_rate, "details": r.details or {},
        "var_snapshot": r.var_snapshot or {}, "analysis": r.analysis or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


# ── 调试端点 ──────────────────────────────────────────────────────────────────

@router.get("/api-test/debug/claude")
async def debug_claude_subprocess():
    import asyncio, subprocess, shutil, os
    claude_bin = shutil.which("claude") or shutil.which("claude.cmd")
    if not claude_bin:
        npm_bin = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm")
        for name in ("claude.cmd", "claude"):
            c = os.path.join(npm_bin, name)
            if os.path.exists(c):
                claude_bin = c
                break
    if not claude_bin:
        return {"error": "claude not found"}

    def _run():
        try:
            r = subprocess.run(
                [claude_bin, "--output-format", "text", "--no-session-persistence",
                 "--input-format", "text", "--system-prompt", "output JSON only", "-p"],
                input=b'output [{"test":1}]', capture_output=True, timeout=60, env=os.environ.copy(),
            )
            return {"rc": r.returncode,
                    "out": r.stdout.decode("utf-8", errors="replace")[:300],
                    "err": r.stderr.decode("utf-8", errors="replace")[:200]}
        except subprocess.TimeoutExpired:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": str(e)}

    return await asyncio.to_thread(_run)


# ── 项目管理 ──────────────────────────────────────────────────────────────────

@router.post("/api-test/projects")
async def create_api_project(data: dict, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    proj = ApiProject(
        name=data.get("name", "未命名项目"), base_url=data.get("base_url", ""),
        description=data.get("description", ""), auth_type=data.get("auth_type", "none"),
        auth_config=data.get("auth_config"), global_headers=data.get("global_headers"),
        proxy_url=data.get("proxy_url", ""), hosts_map=data.get("hosts_map", ""),
        workspace_id=data.get("workspace_id"),
        created_by=current_user.username,
    )
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return _proj_dict(proj)


@router.get("/api-test/projects")
async def list_api_projects(workspace_id: int = None, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(ApiProject).order_by(ApiProject.created_at.desc())
    if current_user.role != "admin":
        from sqlalchemy import false as sql_false
        from tools.database import ProjectMember
        from sqlalchemy import select as _sel
        if workspace_id is None:
            stmt = stmt.where(sql_false())
        else:
            # 验证用户是该空间成员
            m = await db.execute(_sel(ProjectMember).where(
                ProjectMember.project_id == workspace_id,
                ProjectMember.username == current_user.username,
            ))
            if not m.scalar_one_or_none():
                stmt = stmt.where(sql_false())
            else:
                stmt = stmt.where(ApiProject.workspace_id == workspace_id)
    result = await db.execute(stmt)
    return [_proj_dict(p) for p in result.scalars().all()]


@router.get("/api-test/all-cases")
async def list_all_cases_grouped(
    workspace_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回用于前置用例选择、测试计划步骤添加的所有项目用例。
    admin：不传 workspace_id 返回全部，传了只返回该空间。
    普通用户：返回其所有成员空间的项目（不限定单个空间），前置用例选择需要跨空间。
    """
    stmt = select(ApiProject).order_by(ApiProject.created_at.desc())
    if current_user.role != "admin":
        from tools.database import ProjectMember
        from sqlalchemy import select as _sel
        if workspace_id is not None:
            # 指定了空间：验证成员身份后过滤
            m = await db.execute(_sel(ProjectMember).where(
                ProjectMember.project_id == workspace_id,
                ProjectMember.username == current_user.username,
            ))
            if not m.scalar_one_or_none():
                from sqlalchemy import false as sql_false
                stmt = stmt.where(sql_false())
            else:
                stmt = stmt.where(ApiProject.workspace_id == workspace_id)
        else:
            # 未指定空间：返回该用户所有成员空间的项目
            my_workspaces = (await db.execute(
                _sel(ProjectMember.project_id).where(
                    ProjectMember.username == current_user.username
                )
            )).scalars().all()
            if my_workspaces:
                stmt = stmt.where(ApiProject.workspace_id.in_(my_workspaces))
            else:
                from sqlalchemy import false as sql_false
                stmt = stmt.where(sql_false())
    elif workspace_id is not None:
        # admin 指定了空间：只返回该空间
        stmt = stmt.where(ApiProject.workspace_id == workspace_id)
    projects = (await db.execute(stmt)).scalars().all()
    result = []
    for p in projects:
        cases = (await db.execute(
            select(ApiCase).where(ApiCase.project_id == p.id).order_by(ApiCase.created_at)
        )).scalars().all()
        result.append({"project_id": p.id, "project_name": p.name, "cases": [_case_dict(c) for c in cases]})
    return result


@router.put("/api-test/projects/{project_id}")
async def update_api_project(project_id: int, data: dict, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    for field in ("name", "base_url", "description", "auth_type", "auth_config", "global_headers",
                  "setup_cases", "auth_error_patterns", "proxy_url", "hosts_map"):
        if field in data:
            setattr(proj, field, data[field])
    await db.commit()
    await db.refresh(proj)
    return _proj_dict(proj)


@router.delete("/api-test/projects/{project_id}")
async def delete_api_project(project_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete as sql_del
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    await db.execute(sql_del(ApiCase).where(ApiCase.project_id == project_id))
    await db.execute(sql_del(ApiLoadConfig).where(ApiLoadConfig.project_id == project_id))
    await db.execute(sql_del(ApiTestReport).where(ApiTestReport.project_id == project_id))
    await db.execute(sql_del(ApiProject).where(ApiProject.id == project_id))
    await db.commit()
    return {"message": "删除成功"}


# ── 用例管理 ──────────────────────────────────────────────────────────────────

@router.get("/api-test/projects/{project_id}/cases")
async def list_api_cases(project_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    proj_result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = proj_result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    result = await db.execute(
        select(ApiCase).where(ApiCase.project_id == project_id).order_by(ApiCase.created_at)
    )
    return [_case_dict(c) for c in result.scalars().all()]


@router.post("/api-test/cases")
async def create_api_case(data: dict, db: AsyncSession = Depends(get_db)):
    case = ApiCase(
        project_id=data["project_id"], name=data.get("name", "未命名用例"),
        module=data.get("module", "通用"), method=data.get("method", "GET"),
        path=data.get("path", "/"), headers=data.get("headers"), params=data.get("params"),
        body=data.get("body"), assertions=data.get("assertions"),
        var_extracts=data.get("var_extracts"), priority=data.get("priority", "P1"),
        enabled=data.get("enabled", True), body_type=data.get("body_type", "json"),
        body_raw=data.get("body_raw"), description=data.get("description", ""),
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return _case_dict(case)


@router.put("/api-test/cases/{case_id}")
async def update_api_case(case_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiCase).where(ApiCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    for field in ("name", "module", "method", "path", "headers", "params", "body", "body_type",
                  "body_raw", "assertions", "var_extracts", "priority", "enabled", "description"):
        if field in data:
            setattr(case, field, data[field])
    await db.commit()
    await db.refresh(case)
    return _case_dict(case)


@router.delete("/api-test/cases")
async def delete_api_cases(ids: List[int], db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete as sql_del
    await db.execute(sql_del(ApiCase).where(ApiCase.id.in_(ids)))
    await db.commit()
    return {"message": f"已删除 {len(ids)} 条用例"}


# ── AI 生成用例 ───────────────────────────────────────────────────────────────

@router.post("/api-test/projects/{project_id}/cases/generate")
async def generate_api_cases(
    project_id: int, data: dict, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")

    swagger_text = data.get("swagger_text", "")
    description  = data.get("description", "")
    proj_dict    = _proj_dict(proj)

    async def _bg():
        from skills.api_case_generator import api_case_generator
        from tools.database import async_session_maker

        async def progress_cb(pct, stage):
            await ws_manager.broadcast(
                {"type": "api_gen_progress", "percent": pct, "stage": stage}, client_id="api_gen",
            )

        try:
            cases = await api_case_generator.generate_cases(
                base_url=proj.base_url, swagger_text=swagger_text,
                description=description, progress_cb=progress_cb,
                project={"base_url": proj.base_url, "auth_type": proj.auth_type or "none",
                         "auth_config": proj.auth_config or {}, "global_headers": proj.global_headers or {}},
            )
            async with async_session_maker() as s:
                for c in cases:
                    s.add(ApiCase(
                        project_id=project_id, name=c.get("name", ""), module=c.get("module", "通用"),
                        method=c.get("method", "GET"), path=c.get("path", "/"),
                        headers=c.get("headers"), params=c.get("params"), body=c.get("body"),
                        body_type=c.get("body_type", "json"), body_raw=c.get("body_raw"),
                        assertions=c.get("assertions"), var_extracts=c.get("var_extracts"),
                        priority=c.get("priority", "P1"), description=c.get("description", ""), enabled=True,
                    ))
                await s.commit()
            await ws_manager.broadcast({"type": "api_gen_done", "count": len(cases)}, client_id="api_gen")
        except Exception as e:
            logger.error(f"API case generation failed: {e}", exc_info=True)
            await ws_manager.broadcast({"type": "api_gen_error", "message": str(e)}, client_id="api_gen")

    background_tasks.add_task(_bg)
    return {"message": "AI生成任务已启动，请通过 WebSocket 接收进度", "project_id": project_id}


@router.post("/api-test/projects/{project_id}/cases/generate-from-code")
async def generate_cases_from_code(
    project_id: int, data: dict, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    code = (data.get("code") or "").strip()
    lang = data.get("lang", "python")
    if not code:
        raise HTTPException(status_code=400, detail="请提供接口代码")

    async def _bg():
        from skills.api_case_generator import api_code_analyzer
        from tools.database import async_session_maker

        async def progress_cb(pct, stage):
            await ws_manager.broadcast(
                {"type": "api_gen_progress", "percent": pct, "stage": stage}, client_id="api_gen",
            )

        try:
            cases = await api_code_analyzer.generate_from_code(
                code=code, lang=lang, base_url=proj.base_url or "", progress_cb=progress_cb,
            )
            async with async_session_maker() as s:
                for c in cases:
                    s.add(ApiCase(
                        project_id=project_id, name=c.get("name", ""), module=c.get("module", "代码分析"),
                        method=c.get("method", "POST"), path=c.get("path", "/"),
                        headers=c.get("headers") or {}, params=c.get("params") or {},
                        body=c.get("body"), assertions=c.get("assertions"),
                        var_extracts=c.get("var_extracts"), priority=c.get("priority", "P1"),
                        description=c.get("description", ""), enabled=True,
                    ))
                await s.commit()
            await ws_manager.broadcast({"type": "api_gen_done", "count": len(cases)}, client_id="api_gen")
        except Exception as e:
            logger.error(f"代码用例生成失败: {e}", exc_info=True)
            await ws_manager.broadcast({"type": "api_gen_error", "message": str(e)}, client_id="api_gen")

    background_tasks.add_task(_bg)
    return {"message": "代码分析任务已启动", "project_id": project_id}


@router.post("/api-test/projects/{project_id}/code-analyze")
async def analyze_code_vs_requirement(project_id: int, data: dict, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    requirement = (data.get("requirement") or "").strip()
    code = (data.get("code") or "").strip()
    lang = data.get("lang", "python")
    if not code:
        raise HTTPException(status_code=400, detail="请提供接口代码")
    if not requirement:
        raise HTTPException(status_code=400, detail="请提供需求文档或功能描述")
    from skills.api_case_generator import api_code_analyzer
    try:
        report = await api_code_analyzer.analyze_vs_requirement(requirement=requirement, code=code, lang=lang)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("代码可行性分析失败: {}", repr(e))
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")
    return report


@router.post("/api-test/projects/{project_id}/code-analyze/save-cases")
async def save_analyze_cases(project_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")
    cases = data.get("cases", [])
    if not cases:
        raise HTTPException(status_code=400, detail="没有可保存的用例")
    for c in cases:
        db.add(ApiCase(
            project_id=project_id, name=c.get("name", "差异验证用例"),
            module=c.get("module", "差异验证"), method=c.get("method", "POST"),
            path=c.get("path", "/"), headers=c.get("headers") or {},
            params=c.get("params") or {}, body=c.get("body"),
            assertions=c.get("assertions") or [{"type": "status_code", "expected": 200}],
            var_extracts=c.get("var_extracts"), priority=c.get("priority", "P1"),
            description=c.get("description", ""), enabled=True,
        ))
    await db.commit()
    logger.info(f"保存差异验证用例: {len(cases)} 条 → project_id={project_id}")
    return {"message": f"已保存 {len(cases)} 条差异验证用例", "saved": len(cases)}


# ── 内置函数 & 自定义脚本 ─────────────────────────────────────────────────────

@router.get("/api-test/builtin-functions")
async def list_builtin_functions():
    from skills.param_resolver import BUILTIN_FUNCTIONS
    return BUILTIN_FUNCTIONS


@router.get("/api-test/scripts")
async def list_scripts(project_id: int = None, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import or_
    stmt = select(CustomScript).order_by(CustomScript.id)
    if project_id is not None:
        stmt = stmt.where(or_(CustomScript.project_id == project_id, CustomScript.project_id == None))
    result = await db.execute(stmt)
    return [_script_dict(s) for s in result.scalars()]


@router.post("/api-test/scripts")
async def create_script(data: dict, db: AsyncSession = Depends(get_db)):
    s = CustomScript(
        project_id=data.get("project_id"), name=data.get("name", "my_func"),
        description=data.get("description", ""), code=data.get("code", ""),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return _script_dict(s)


# 静态子路由必须在 {script_id} 动态路由之前

@router.post("/api-test/scripts/test")
async def test_script(data: dict):
    from skills.param_resolver import _exec_custom_fn
    name   = data.get("name", "test_fn")
    code   = data.get("code", "")
    args_str = data.get("args", "")
    result = _exec_custom_fn(name, args_str, [{"name": name, "code": code}])
    if result is None:
        return {"ok": False, "error": "脚本执行失败：未定义同名函数或 result 变量"}
    return {"ok": True, "result": result}


@router.post("/api-test/scripts/ai-generate")
async def ai_generate_script(data: dict):
    import httpx, re as _re
    prompt    = (data.get("prompt") or "").strip()
    func_name = (data.get("func_name") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    api_key     = settings.AI_API_KEY
    base_url    = (settings.AI_API_URL or "").rstrip("/")
    model       = settings.AI_MODEL or "deepseek-v4-flash"
    temperature = float(getattr(settings, "AI_TEMPERATURE", 0.3))
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置 AI API Key，请先在 LLM 配置页面填写")
    available_modules = "hashlib, json, time, random, string, uuid, base64, os, re, requests"
    system_prompt = (
        f"你是一个资深 Python 工程师，专门为 API 接口测试框架编写参数生成脚本。\n\n"
        f"## 执行环境约束\n- 可用模块：{available_modules}\n- 函数接收可变参数 `*args`\n"
        "- 函数必须有返回值（return）\n- 禁止文件 IO、系统调用等危险操作\n\n"
        "## 代码规范\n1. 所有 import 写在函数内部\n2. 只输出纯 Python 代码\n3. 不要输出解释说明"
    )
    is_anthropic = "anthropic.com" in base_url
    try:
        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
            if is_anthropic:
                resp = await client.post(
                    f"{base_url}/v1/messages",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": model, "max_tokens": 1024, "temperature": temperature,
                          "system": system_prompt, "messages": [{"role": "user", "content": prompt}]},
                )
            else:
                resp = await client.post(
                    f"{base_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
                    json={"model": model, "max_tokens": 1024, "temperature": temperature,
                          "messages": [{"role": "system", "content": system_prompt},
                                       {"role": "user", "content": prompt}]},
                )
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"AI 接口返回错误 {resp.status_code}：{resp.text[:300]}")
        body = resp.json()
        code = (body["content"][0]["text"] if is_anthropic else body["choices"][0]["message"]["content"]).strip()
        if code.startswith("```"):
            lines = code.splitlines()
            code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
        m = _re.search(r"^def\s+(\w+)\s*\(", code, _re.MULTILINE)
        final_name = (m.group(1) if m else None) or func_name or "custom_func"
        return {"ok": True, "code": code, "func_name": final_name, "description": prompt[:60].rstrip("，。,.")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 生成失败：{str(e)}")


@router.put("/api-test/scripts/{script_id}")
async def update_script(script_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CustomScript).where(CustomScript.id == script_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="脚本不存在")
    for field in ("name", "description", "code", "project_id"):
        if field in data:
            setattr(s, field, data[field])
    await db.commit()
    await db.refresh(s)
    return _script_dict(s)


@router.delete("/api-test/scripts/{script_id}")
async def delete_script(script_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CustomScript).where(CustomScript.id == script_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="脚本不存在")
    await db.delete(s)
    await db.commit()
    return {"message": "已删除"}


# ── 单测执行 ──────────────────────────────────────────────────────────────────

@router.post("/api-test/projects/{project_id}/execute")
async def execute_api_cases(
    project_id: int, data: dict, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    proj_r = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = proj_r.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    case_ids = data.get("case_ids")
    proj_dict = _proj_dict(proj)

    async def _bg():
        from skills.api_executor import api_executor
        from tools.database import async_session_maker
        from sqlalchemy import or_ as _or

        async with async_session_maker() as s:
            q = select(ApiCase).where(ApiCase.project_id == project_id)
            if case_ids:
                q = q.where(ApiCase.id.in_(case_ids))
            cases = [_case_dict(c) for c in (await s.execute(q)).scalars().all()]
            sq = select(CustomScript).where(
                _or(CustomScript.project_id == project_id, CustomScript.project_id == None)
            )
            custom_scripts = [_script_dict(sc) for sc in (await s.execute(sq)).scalars()]

        async def progress_cb(p):
            await ws_manager.broadcast({"type": "api_exec_progress", **p}, client_id="api_exec")

        summary = await api_executor.execute_cases(proj_dict, cases, progress_cb, custom_scripts=custom_scripts)

        # 持久化执行链中提取的全局变量，归属到当前项目的工作空间
        try:
            from skills.param_resolver import flush_global_vars
            await flush_global_vars(source_project=proj.name, workspace_id=proj.workspace_id)
        except Exception as _fe:
            logger.warning(f"[exec] flush_global_vars 失败: {_fe}")

        async with async_session_maker() as s:
            report = ApiTestReport(
                project_id=project_id, project_name=proj.name, report_type="unit",
                total=summary["total"], passed=summary["passed"], failed=summary["failed"],
                summary={"pass_rate": summary["pass_rate"]}, details=summary["results"],
            )
            s.add(report)
            await s.commit()
            await s.refresh(report)

        await ws_manager.broadcast(
            {"type": "api_exec_done", "report_id": report.id, **summary}, client_id="api_exec",
        )

    background_tasks.add_task(_bg)
    return {"message": "执行任务已启动", "project_id": project_id}


# ── 压力测试 ──────────────────────────────────────────────────────────────────

@router.post("/api-test/projects/{project_id}/load")
async def run_load_test(
    project_id: int, data: dict, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    proj_r = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = proj_r.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    config   = {"concurrent_users": data.get("concurrent_users", 10),
                "duration": data.get("duration", 60), "ramp_up": data.get("ramp_up", 10)}
    case_ids = data.get("case_ids")
    proj_dict = _proj_dict(proj)

    async def _bg():
        from skills.api_load_tester import api_load_tester
        from tools.database import async_session_maker

        async with async_session_maker() as s:
            q = select(ApiCase).where(ApiCase.project_id == project_id, ApiCase.enabled == True)
            if case_ids:
                q = q.where(ApiCase.id.in_(case_ids))
            cases = [_case_dict(c) for c in (await s.execute(q)).scalars().all()]

        async def metrics_cb(m):
            await ws_manager.broadcast({"type": "load_metrics", **m}, client_id="api_load")

        summary = await api_load_tester.run(proj_dict, cases, config, metrics_cb)

        async with async_session_maker() as s:
            report = ApiTestReport(
                project_id=project_id, project_name=proj.name, report_type="load",
                total=summary.get("total_requests", 0), passed=summary.get("passed", 0),
                failed=summary.get("failed", 0), summary=summary, details=cases,
            )
            s.add(report)
            await s.commit()
            await s.refresh(report)

        await ws_manager.broadcast(
            {"type": "load_done", "report_id": report.id, **summary}, client_id="api_load",
        )

    background_tasks.add_task(_bg)
    return {"message": "压测任务已启动", "project_id": project_id}


@router.post("/api-test/load/stop")
async def stop_load_test():
    from skills.api_load_tester import api_load_tester
    api_load_tester.stop()
    return {"message": "停止信号已发送"}


# ── 接口测试报告 ──────────────────────────────────────────────────────────────

@router.get("/api-test/projects/{project_id}/reports")
async def list_api_reports(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ApiTestReport).where(ApiTestReport.project_id == project_id)
        .order_by(ApiTestReport.created_at.desc())
    )
    return [_report_dict(r) for r in result.scalars().all()]


@router.post("/api-test/reports/{report_id}/analyze")
async def analyze_api_report(report_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiTestReport).where(ApiTestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    rdict    = _report_dict(report)
    analysis = await _ai_analyze_report(rdict)
    report.analysis = analysis
    await db.commit()
    return {"analysis": analysis}


async def _ai_analyze_report(report: dict) -> str:
    import httpx
    rtype     = report.get("report_type", "unit")
    total     = report.get("total", 0)
    passed    = report.get("passed", 0)
    failed    = report.get("failed", 0)
    pass_rate = round(passed / total * 100, 1) if total else 0
    if rtype == "unit":
        details = report.get("details") or []
        failed_cases = [d for d in details if d.get("status") == "failed"]
        failed_summary = "\n".join(
            f"- [{d.get('method')} {d.get('url')}] {d.get('case_name')}: {d.get('error') or '断言失败'}"
            + (f"\n  响应预览: {d.get('response_preview', '')[:200]}" if d.get("response_preview") else "")
            for d in failed_cases[:20]
        )
        prompt = (
            f"以下是接口单元测试报告，请分析失败原因并给出修复建议。\n\n"
            f"测试概况：共 {total} 条，通过 {passed} 条，失败 {failed} 条，通过率 {pass_rate}%\n\n"
            + (f"失败用例明细：\n{failed_summary}\n\n" if failed_cases else "所有用例均通过。\n\n")
            + "请输出：\n1. 失败原因分析\n2. 修复建议\n3. 测试质量总结"
        )
    else:
        summary = report.get("summary") or {}
        prompt = (
            f"以下是接口压力测试报告，请分析性能瓶颈并给出优化建议。\n\n"
            f"压测结果：总请求 {summary.get('total_requests')}, 成功率 {summary.get('success_rate')}%, "
            f"平均TPS {summary.get('avg_tps')}, 平均耗时 {summary.get('avg_ms')}ms, "
            f"P95 {summary.get('p95_ms')}ms, P99 {summary.get('p99_ms')}ms\n\n"
            "请输出：\n1. 性能评估\n2. 潜在瓶颈分析\n3. 优化建议"
        )
    api_key  = settings.AI_API_KEY
    base_url = (settings.AI_API_URL or "").rstrip("/")
    model    = settings.AI_MODEL or "deepseek-v4-flash"
    is_anthropic = "anthropic.com" in base_url
    sys_msg = "你是一名资深测试工程师，擅长分析接口测试报告，给出精准、可操作的建议。用中文回答，使用 Markdown 格式输出。"
    async with httpx.AsyncClient(verify=False, timeout=60) as client:
        if is_anthropic:
            resp = await client.post(
                f"{base_url}/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": 2048, "system": sys_msg, "messages": [{"role": "user", "content": prompt}]},
            )
        else:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
                json={"model": model, "max_tokens": 2048,
                      "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}]},
            )
        resp.raise_for_status()
        data = resp.json()
    return data["content"][0]["text"] if is_anthropic else data["choices"][0]["message"]["content"]


@router.get("/api-test/reports/{report_id}/pdf")
async def export_api_report_pdf(report_id: int, db: AsyncSession = Depends(get_db)):
    """将接口测试报告导出为 PDF。"""
    from fastapi.responses import Response
    from urllib.parse import quote
    from tools.pdf_exporter import html_to_pdf

    r = (await db.execute(select(ApiTestReport).where(ApiTestReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")

    rdict    = _report_dict(r)
    details  = rdict.get("details") or []
    total    = rdict.get("total", 0)
    passed   = rdict.get("passed", 0)
    failed   = rdict.get("failed", 0)
    pass_rate = round(passed / total * 100, 1) if total else 0
    title    = f"{r.project_name or '接口测试'} 报告"
    created  = r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else ""
    analysis = rdict.get("analysis", "")

    rows = ""
    for d in details:
        st = d.get("status", "")
        cls = {"passed": "bg-success", "failed": "bg-danger"}.get(st, "bg-warning")
        lbl = {"passed": "通过", "failed": "失败"}.get(st, st)
        err = str(d.get("error") or d.get("error_message") or "-")[:200]
        rows += (
            f"<tr><td>{d.get('case_name','-')}</td>"
            f"<td>{d.get('method','')}</td><td>{d.get('url','')[:80]}</td>"
            f"<td>{d.get('status_code','')}</td>"
            f"<td><span class='badge {cls}'>{lbl}</span></td>"
            f"<td>{d.get('duration_ms',0)}ms</td>"
            f"<td style='max-width:200px;word-break:break-all'>{err}</td></tr>"
        )
    analysis_block = f"<h3>AI 分析</h3><pre style='white-space:pre-wrap;background:#f9f9f9;padding:12px;border-radius:4px'>{analysis}</pre>" if analysis else ""

    html_str = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{title}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px;color:#333;font-size:13px}}
h2{{margin-bottom:4px}}p.meta{{color:#888;margin-bottom:16px}}
.stats{{display:flex;gap:16px;margin-bottom:20px}}
.stat{{background:#f5f5f5;padding:10px 20px;border-radius:6px;text-align:center}}
.stat .n{{font-size:24px;font-weight:700}}.stat .l{{font-size:12px;color:#888}}
.green{{color:#52c41a}}.red{{color:#ff4d4f}}.blue{{color:#1890ff}}
table{{width:100%;border-collapse:collapse;margin-bottom:20px}}
th,td{{padding:7px 10px;border:1px solid #e8e8e8;font-size:12px}}th{{background:#fafafa;font-weight:600}}
.badge{{padding:2px 8px;border-radius:4px;font-size:11px}}
.bg-success{{background:#d9f7be;color:#389e0d}}.bg-danger{{background:#fff1f0;color:#cf1322}}
.bg-warning{{background:#fffbe6;color:#ad6800}}
</style></head><body>
<h2>{title}</h2>
<p class="meta">生成时间：{created}</p>
<div class="stats">
  <div class="stat"><div class="n blue">{total}</div><div class="l">总用例</div></div>
  <div class="stat"><div class="n green">{passed}</div><div class="l">通过</div></div>
  <div class="stat"><div class="n red">{failed}</div><div class="l">失败</div></div>
  <div class="stat"><div class="n {'green' if pass_rate>=80 else 'red'}">{pass_rate}%</div><div class="l">通过率</div></div>
</div>
<table><thead><tr><th>用例名称</th><th>方法</th><th>URL</th><th>状态码</th><th>结果</th><th>耗时</th><th>错误信息</th></tr></thead>
<tbody>{rows}</tbody></table>
{analysis_block}
</body></html>"""

    try:
        pdf_bytes = await html_to_pdf(html_str=html_str)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    encoded = quote(f"{r.project_name or 'api_report'}_{report_id}.pdf", safe="")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@router.delete("/api-test/reports/batch")
async def delete_api_reports_batch(ids: List[int], db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete as sql_del
    if not ids:
        raise HTTPException(status_code=400, detail="未提供报告ID")
    await db.execute(sql_del(ApiTestReport).where(ApiTestReport.id.in_(ids)))
    await db.commit()
    return {"message": f"已删除 {len(ids)} 条报告"}


@router.delete("/api-test/reports/{report_id}")
async def delete_api_report(report_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete as sql_del
    result = await db.execute(select(ApiTestReport).where(ApiTestReport.id == report_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="报告不存在")
    await db.execute(sql_del(ApiTestReport).where(ApiTestReport.id == report_id))
    await db.commit()
    return {"message": "已删除"}


# ── 全局变量池 ────────────────────────────────────────────────────────────────

def _gvar_dict(g: GlobalVariable) -> dict:
    return {
        "id": g.id, "name": g.name, "value": g.value or "",
        "description": g.description or "", "source_project": g.source_project or "",
        "updated_at": g.updated_at.isoformat() if g.updated_at else "",
    }


@router.get("/global-vars")
async def list_global_vars(
    workspace_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(GlobalVariable).order_by(GlobalVariable.name)
    if current_user.role == "admin":
        # admin 选了空间：只看该空间的；未选：看全部（含 NULL 的历史数据）
        if workspace_id is not None:
            stmt = stmt.where(GlobalVariable.workspace_id == workspace_id)
        # workspace_id is None → 不加任何过滤，看全部
    else:
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
                # 普通用户选了空间：只看该空间的（不再包含 NULL，避免跨空间泄漏）
                stmt = stmt.where(GlobalVariable.workspace_id == workspace_id)
    result = await db.execute(stmt)
    return [_gvar_dict(g) for g in result.scalars().all()]


@router.post("/global-vars")
async def create_global_var(
    data: dict,
    workspace_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from skills.param_resolver import set_global_var, _gvar_dirty
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="变量名不能为空")
    # 同一空间内变量名唯一（精确匹配 workspace_id，不再混入 NULL 数据）
    ws_id = workspace_id or data.get("workspace_id")
    stmt = select(GlobalVariable).where(GlobalVariable.name == name)
    if ws_id:
        stmt = stmt.where(GlobalVariable.workspace_id == ws_id)
    else:
        stmt = stmt.where(GlobalVariable.workspace_id.is_(None))
    exist = (await db.execute(stmt)).scalar_one_or_none()
    if exist:
        raise HTTPException(status_code=400, detail=f"变量 '{name}' 已存在，请使用 PUT 更新")
    g = GlobalVariable(name=name, value=data.get("value", ""),
                       description=data.get("description", ""),
                       source_project=data.get("source_project", "手动创建"),
                       workspace_id=ws_id)
    db.add(g)
    await db.commit()
    await db.refresh(g)
    set_global_var(name, g.value or "", source_project=g.source_project)
    _gvar_dirty.discard(name)
    return _gvar_dict(g)


@router.put("/global-vars/{var_id}")
async def update_global_var(var_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    from skills.param_resolver import set_global_var, _gvar_dirty
    from datetime import datetime as _dt
    result = await db.execute(select(GlobalVariable).where(GlobalVariable.id == var_id))
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="变量不存在")
    for field in ("value", "description", "source_project"):
        if field in data:
            setattr(g, field, data[field])
    g.updated_at = _dt.utcnow()
    await db.commit()
    await db.refresh(g)
    set_global_var(g.name, g.value or "", source_project=g.source_project)
    _gvar_dirty.discard(g.name)
    return _gvar_dict(g)


@router.delete("/global-vars/{var_id}")
async def delete_global_var(var_id: int, db: AsyncSession = Depends(get_db)):
    from skills.param_resolver import _gvar_cache, _gvar_dirty
    result = await db.execute(select(GlobalVariable).where(GlobalVariable.id == var_id))
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="变量不存在")
    _gvar_cache.pop(g.name, None)
    _gvar_dirty.discard(g.name)
    await db.delete(g)
    await db.commit()
    return {"message": f"已删除全局变量 '{g.name}'"}


# ── 测试计划 ──────────────────────────────────────────────────────────────────

@router.get("/test-plans")
async def list_test_plans(workspace_id: int = None, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import func
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
    result = []
    for p in plans:
        step_count = (await db.execute(
            select(func.count()).where(TestPlanStep.plan_id == p.id)
        )).scalar() or 0
        d = _plan_dict(p)
        d["step_count"] = step_count
        result.append(d)
    return result


@router.post("/test-plans")
async def create_test_plan(data: dict, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="计划名称不能为空")
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
async def add_plan_steps(plan_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete as sql_delete
    from datetime import datetime as _dt
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
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
async def delete_plan_step(plan_id: int, step_id: int, db: AsyncSession = Depends(get_db)):
    s = (await db.execute(
        select(TestPlanStep).where(TestPlanStep.id == step_id, TestPlanStep.plan_id == plan_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="步骤不存在")
    await db.delete(s)
    await db.commit()
    return {"message": "步骤已删除"}


@router.post("/test-plans/{plan_id}/run")
async def run_test_plan(
    plan_id: int, background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db), force: bool = False,
):
    from datetime import datetime as _dt
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    if plan.status == "running" and not force:
        raise HTTPException(status_code=409, detail="计划正在执行中，如需强制重跑请传 force=true")
    plan.status = "running"
    plan.updated_at = _dt.utcnow()
    await db.commit()
    background_tasks.add_task(_execute_plan_bg, plan_id)
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
    background_tasks.add_task(_execute_plan_bg, plan_id, callback_url=callback_url)
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


async def _execute_plan_bg(plan_id: int, callback_url: Optional[str] = None):
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
                await ws_manager.broadcast_all({"type": "plan_done", "plan_id": plan_id,
                                                "total": 0, "passed": 0, "failed": 0, "pass_rate": 100, "status": "passed"})
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
            from skills.api_executor import _parse_hosts_map, _make_transport
            _hosts_map = {**_parse_hosts_map(proj.get("hosts_map") or ""), **_parse_hosts_map(plan_hosts_map_text)}
            _transport = _make_transport(_hosts_map, verify=False)
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
                                    details=step_results, var_snapshot=dict(var_store))
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
    await ws_manager.broadcast_all({"type": "plan_done", "plan_id": plan_id, "report_id": report_id,
                                    "total": total, "passed": passed, "failed": failed_count,
                                    "pass_rate": pass_rate, "status": final_status})

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


@router.get("/test-plans/{plan_id}/reports")
async def list_plan_reports(plan_id: int, db: AsyncSession = Depends(get_db)):
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
async def get_plan_report(report_id: int, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    return _plan_report_dict(r)


@router.get("/test-plans/reports/{report_id}/pdf")
async def export_plan_report_pdf(report_id: int, db: AsyncSession = Depends(get_db)):
    """将测试计划报告导出为 PDF。"""
    from fastapi.responses import Response
    from urllib.parse import quote
    from tools.pdf_exporter import html_to_pdf

    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")

    rdict    = _plan_report_dict(r)
    details  = rdict.get("details") or []
    total    = rdict.get("total", 0)
    passed   = rdict.get("passed", 0)
    failed   = rdict.get("failed", 0)
    pass_rate = rdict.get("pass_rate", 0)
    title    = f"{r.plan_name or '测试计划'} 报告"
    created  = r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else ""
    analysis = rdict.get("analysis", "")

    rows = ""
    for d in details:
        st  = d.get("status", "")
        cls = {"passed": "bg-success", "failed": "bg-danger"}.get(st, "bg-warning")
        lbl = {"passed": "通过", "failed": "失败"}.get(st, st)
        err = str(d.get("error") or "-")[:200]
        rows += (
            f"<tr><td>{d.get('step','')}</td>"
            f"<td>{d.get('case_name','-')}</td>"
            f"<td>{d.get('project_name','')}</td>"
            f"<td>{d.get('method','')}</td>"
            f"<td>{d.get('status_code','')}</td>"
            f"<td><span class='badge {cls}'>{lbl}</span></td>"
            f"<td>{d.get('duration_ms',0)}ms</td>"
            f"<td style='max-width:200px;word-break:break-all'>{err}</td></tr>"
        )
    analysis_block = f"<h3>AI 分析</h3><pre style='white-space:pre-wrap;background:#f9f9f9;padding:12px;border-radius:4px'>{analysis}</pre>" if analysis else ""

    html_str = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{title}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px;color:#333;font-size:13px}}
h2{{margin-bottom:4px}}p.meta{{color:#888;margin-bottom:16px}}
.stats{{display:flex;gap:16px;margin-bottom:20px}}
.stat{{background:#f5f5f5;padding:10px 20px;border-radius:6px;text-align:center}}
.stat .n{{font-size:24px;font-weight:700}}.stat .l{{font-size:12px;color:#888}}
.green{{color:#52c41a}}.red{{color:#ff4d4f}}.blue{{color:#1890ff}}
table{{width:100%;border-collapse:collapse;margin-bottom:20px}}
th,td{{padding:7px 10px;border:1px solid #e8e8e8;font-size:12px}}th{{background:#fafafa;font-weight:600}}
.badge{{padding:2px 8px;border-radius:4px;font-size:11px}}
.bg-success{{background:#d9f7be;color:#389e0d}}.bg-danger{{background:#fff1f0;color:#cf1322}}
.bg-warning{{background:#fffbe6;color:#ad6800}}
</style></head><body>
<h2>{title}</h2>
<p class="meta">生成时间：{created}</p>
<div class="stats">
  <div class="stat"><div class="n blue">{total}</div><div class="l">总步骤</div></div>
  <div class="stat"><div class="n green">{passed}</div><div class="l">通过</div></div>
  <div class="stat"><div class="n red">{failed}</div><div class="l">失败</div></div>
  <div class="stat"><div class="n {'green' if pass_rate>=80 else 'red'}">{pass_rate}%</div><div class="l">通过率</div></div>
</div>
<table><thead><tr><th>#</th><th>用例名称</th><th>所属项目</th><th>方法</th><th>状态码</th><th>结果</th><th>耗时</th><th>错误信息</th></tr></thead>
<tbody>{rows}</tbody></table>
{analysis_block}
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
async def delete_plan_reports_batch(ids: List[int], db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete as sql_del
    if not ids:
        raise HTTPException(status_code=400, detail="未提供报告ID")
    await db.execute(sql_del(TestPlanReport).where(TestPlanReport.id.in_(ids)))
    await db.commit()
    return {"message": f"已删除 {len(ids)} 条报告"}


@router.post("/test-plans/reports/{report_id}/analyze")
async def analyze_plan_report(report_id: int, db: AsyncSession = Depends(get_db)):
    import httpx
    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
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
    api_key  = settings.AI_API_KEY
    base_url = (settings.AI_API_URL or "").rstrip("/")
    model    = settings.AI_MODEL or "deepseek-v4-flash"
    is_anthropic = "anthropic.com" in base_url
    sys_msg = "你是一名资深测试工程师，擅长分析接口测试报告，给出精准、可操作的建议。用中文回答，使用 Markdown 格式输出。"
    async with httpx.AsyncClient(verify=False, timeout=90) as client:
        if is_anthropic:
            resp = await client.post(
                f"{base_url}/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": 2048, "system": sys_msg, "messages": [{"role": "user", "content": prompt}]},
            )
        else:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
                json={"model": model, "max_tokens": 2048,
                      "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}]},
            )
        resp.raise_for_status()
        data = resp.json()
    return data["content"][0]["text"] if is_anthropic else data["choices"][0]["message"]["content"]


@router.delete("/test-plans/reports/{report_id}")
async def delete_plan_report(report_id: int, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    await db.delete(r)
    await db.commit()
    return {"message": "报告已删除"}
