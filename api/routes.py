"""
API路由定义
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from pathlib import Path
import shutil
import json
from datetime import datetime
from loguru import logger

from api.schemas import (
    TaskCreateRequest, TaskResponse,
    CaseCreateRequest, CaseUpdateRequest, CaseResponse,
    ExecuteRequest, ExecuteResponse,
    ReportResponse,
    CommandRequest, CommandResponse,
    PageElementResponse, HealthResponse,
    LLMConfigRequest, LLMTestRequest, PageParseRequest
)
from tools.database import get_db, TestTask, TestCase, TestResult, TestReport, ApiProject, ApiCase, ApiLoadConfig, ApiTestReport, CustomScript, GlobalVariable, TestPlan, TestPlanStep, TestPlanReport, User
from agent.core import uitest_agent
from api.websocket_manager import ws_manager
from tools.config import settings
from api.auth import get_current_user, verify_password, hash_password, create_access_token

router = APIRouter()

# ── 鉴权接口（无需 token）─────────────────────────────────────────────────────

@router.post("/auth/login")
async def login(data: dict, db: AsyncSession = Depends(get_db)):
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token({"sub": user.username, "role": user.role})
    return {"access_token": token, "token_type": "bearer", "username": user.username, "role": user.role}


@router.get("/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username, "role": current_user.role}


@router.put("/auth/password")
async def change_password(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    old_pwd = data.get("old_password", "")
    new_pwd = data.get("new_password", "")
    if not verify_password(old_pwd, current_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(new_pwd) < 6:
        raise HTTPException(status_code=400, detail="新密码不能少于6位")
    current_user.password_hash = hash_password(new_pwd)
    db.add(current_user)
    await db.commit()
    return {"message": "密码修改成功"}


# ── admin 依赖 ────────────────────────────────────────────────────────────────
async def require_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


# ── 用户管理接口（admin only）────────────────────────────────────────────────

@router.get("/auth/users")
async def list_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [
        {"id": u.id, "username": u.username, "role": u.role,
         "created_at": u.created_at.isoformat() if u.created_at else None}
        for u in users
    ]


@router.post("/auth/users")
async def create_user(
    data: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码不能少于6位")
    if role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="角色只能是 admin 或 user")
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"用户名 '{username}' 已存在")
    new_user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return {"id": new_user.id, "username": new_user.username, "role": new_user.role,
            "created_at": new_user.created_at.isoformat() if new_user.created_at else None}


@router.delete("/auth/users/{username}")
async def delete_user(
    username: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if username == admin.username:
        raise HTTPException(status_code=400, detail="不能删除自己")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    await db.delete(user)
    await db.commit()
    return {"message": f"用户 '{username}' 已删除"}


@router.put("/auth/users/{username}/password")
async def reset_user_password(
    username: str,
    data: dict,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    new_pwd = data.get("new_password", "")
    if len(new_pwd) < 6:
        raise HTTPException(status_code=400, detail="新密码不能少于6位")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(new_pwd)
    db.add(user)
    await db.commit()
    return {"message": f"用户 '{username}' 密码已重置"}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "agent_state": uitest_agent.get_state()
    }


@router.post("/logs/clean")
async def clean_logs_api(retention_days: int = None):
    """手动触发日志清理。retention_days 不传时使用配置默认值。"""
    from tools.logger import clean_logs, LOG_RETENTION_DAYS
    days = retention_days if retention_days is not None else LOG_RETENTION_DAYS
    result = clean_logs(retention_days=days)
    return result


@router.get("/logs/list")
async def list_logs():
    """列出 logs 目录中所有日志文件及大小、修改时间。"""
    import time
    from pathlib import Path
    log_dir = Path(settings.LOG_DIR)
    files = []
    for p in sorted(log_dir.iterdir()):
        if p.is_file():
            stat = p.stat()
            files.append({
                "name": p.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
    return {"log_dir": str(log_dir), "files": files}


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    request: TaskCreateRequest,
    db: AsyncSession = Depends(get_db)
):
    task = TestTask(
        name=request.name,
        url=request.url,
        document_path=request.document_path,
        browser=request.browser,
        environment=request.environment,
        status="created"
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    await ws_manager.broadcast({
        "type": "task_created",
        "task": {
            "id": task.id,
            "name": task.name,
            "url": task.url,
            "status": task.status
        }
    })

    return TaskResponse(
        id=task.id,
        name=task.name,
        url=task.url,
        status=task.status,
        browser=task.browser,
        environment=task.environment,
        created_at=task.created_at.isoformat()
    )


@router.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import select
    result = await db.execute(select(TestTask).offset(skip).limit(limit))
    tasks = result.scalars().all()

    return [
        TaskResponse(
            id=t.id,
            name=t.name,
            url=t.url,
            status=t.status,
            browser=t.browser,
            environment=t.environment,
            created_at=t.created_at.isoformat()
        )
        for t in tasks
    ]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(
        id=task.id,
        name=task.name,
        url=task.url,
        status=task.status,
        browser=task.browser,
        environment=task.environment,
        created_at=task.created_at.isoformat(),
        page_elements=task.page_elements or []
    )


@router.delete("/tasks/{task_id}", response_model=dict)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, delete
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await db.execute(delete(TestTask).where(TestTask.id == task_id))
    await db.execute(delete(TestCase).where(TestCase.task_id == task_id))
    await db.execute(delete(TestResult).where(TestResult.task_id == task_id))
    await db.commit()

    return {"message": "Task deleted successfully"}


_ALLOWED_DOC_EXTS = {
    ".pdf", ".docx", ".doc",
    ".xlsx", ".xls", ".pptx",
    ".md", ".txt", ".csv", ".html", ".htm", ".json",
}

@router.post("/upload/document")
async def upload_document(file: UploadFile = File(...)):
    original_name = file.filename or ""
    ext = Path(original_name).suffix.lower()
    if ext not in _ALLOWED_DOC_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 '{ext}'，支持：PDF / Word / Excel / PPTX / Markdown / TXT / CSV / HTML / JSON"
        )

    raw = await file.read()
    if len(raw) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件过大，请上传 20MB 以内的文件")

    # 按内容哈希去重：相同文件只存一份
    import hashlib
    file_hash = hashlib.sha256(raw).hexdigest()[:16]
    upload_dir = Path(settings.UPLOAD_DIR) / "documents"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{file_hash}{ext}"
    file_path = upload_dir / filename

    if not file_path.exists():
        file_path.write_bytes(raw)

    return {"path": str(file_path), "filename": filename}


@router.post("/parse/page")
async def parse_page(request: PageParseRequest, db: AsyncSession = Depends(get_db)):
    try:
        logger.info(f"Parsing page: {request.url}, browser: {request.browser}, task_id: {request.task_id}")
        elements = await uitest_agent.parse_page(request.url, request.browser)
        
        if request.task_id:
            from sqlalchemy import select
            result = await db.execute(select(TestTask).where(TestTask.id == request.task_id))
            task = result.scalar_one_or_none()
            if task:
                task.page_elements = elements
                task.status = "parsed"
                await db.commit()
                await db.refresh(task)
        
        logger.info(f"Page parsed successfully, found {len(elements)} elements")
        return {
            "url": request.url,
            "element_count": len(elements),
            "elements": elements
        }
    except Exception as e:
        logger.error(f"Error parsing page: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/parse/document")
async def parse_document(document_path: str):
    try:
        document_data = await uitest_agent.parse_document(document_path)
        return document_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/elements", response_model=TaskResponse)
async def set_page_elements(
    task_id: int,
    elements: List[dict],
    db: AsyncSession = Depends(get_db)
):
    try:
        from sqlalchemy import select
        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        task.page_elements = elements
        task.status = "parsed"
        await db.commit()
        await db.refresh(task)
        
        return TaskResponse(
            id=task.id,
            name=task.name,
            url=task.url,
            status=task.status,
            browser=task.browser,
            environment=task.environment,
            created_at=task.created_at.isoformat(),
            page_elements=task.page_elements
        )
    except Exception as e:
        logger.error(f"Error setting page elements: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/count")
async def get_total_case_count(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, func
    result = await db.execute(select(func.count(TestCase.id)))
    count = result.scalar() or 0
    return {"count": count}


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, func
    task_count = (await db.execute(select(func.count(TestTask.id)))).scalar() or 0
    case_count = (await db.execute(select(func.count(TestCase.id)))).scalar() or 0
    passed = (await db.execute(select(func.sum(TestReport.passed)))).scalar() or 0
    failed = (await db.execute(select(func.sum(TestReport.failed)))).scalar() or 0
    return {"task_count": task_count, "case_count": case_count, "passed": int(passed), "failed": int(failed)}


@router.get("/tasks/{task_id}/cases", response_model=List[CaseResponse])
async def list_cases(task_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(
        select(TestCase).where(TestCase.task_id == task_id)
    )
    cases = result.scalars().all()

    return [
        CaseResponse(
            id=c.id,
            task_id=c.task_id,
            name=c.name,
            module=c.module,
            priority=c.priority,
            preconditions=c.preconditions,
            steps=c.steps,
            expected_results=c.expected_results,
            element_selector=getattr(c, 'element_selector', '') or '',
            enabled=c.enabled,
            deprecated=getattr(c, 'deprecated', False) or False,
        )
        for c in cases
    ]


@router.post("/cases", response_model=CaseResponse)
async def create_case(
    request: CaseCreateRequest,
    db: AsyncSession = Depends(get_db)
):
    case = TestCase(
        task_id=request.task_id,
        name=request.name,
        module=request.module,
        priority=request.priority,
        preconditions=request.preconditions,
        steps=request.steps,
        expected_results=request.expected_results,
        enabled=request.enabled
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)

    return CaseResponse(
        id=case.id,
        task_id=case.task_id,
        name=case.name,
        module=case.module,
        priority=case.priority,
        preconditions=case.preconditions,
        steps=case.steps,
        expected_results=case.expected_results,
        enabled=case.enabled,
        deprecated=getattr(case, 'deprecated', False) or False,
    )


def _resolve_doc_path(document_path: str) -> Optional[Path]:
    """解析文档路径，兼容相对路径，文件不存在返回 None。"""
    doc_path = Path(document_path)
    if doc_path.exists():
        return doc_path
    if not doc_path.is_absolute():
        project_root = Path(__file__).parent.parent
        full = project_root / doc_path
        if full.exists():
            return full
    return None


@router.post("/cases/generate/{task_id}", response_model=List[CaseResponse])
async def generate_cases(
    task_id: int,
    db: AsyncSession = Depends(get_db)
):
    try:
        logger.info(f"Generating cases for task: {task_id}")

        from sqlalchemy import select
        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        if not task.page_elements:
            raise HTTPException(status_code=400, detail="No page elements found for this task")

        uitest_agent._get_state(task_id).page_elements = task.page_elements
        uitest_agent._get_state(task_id).current_url = task.url or ""
        uitest_agent._get_state(task_id).document_data = None

        if task.document_path:
            doc_path = _resolve_doc_path(task.document_path)
            if doc_path:
                logger.info(f"Parsing document: {doc_path}")
                try:
                    document_data = await uitest_agent.parse_document(str(doc_path), task_id=task_id)
                    uitest_agent._get_state(task_id).document_data = document_data
                except Exception as doc_err:
                    logger.warning(f"Document parsing failed, proceeding without it: {doc_err}")
            else:
                logger.warning(f"Document not found, skipping: {task.document_path}")

        async def _progress(pct: int, stage: str):
            await ws_manager.broadcast(
                {"type": "cases_gen_progress", "percent": pct, "stage": stage},
                client_id="cases_gen"
            )

        cases = await uitest_agent.generate_cases(progress_cb=_progress)

        # ── 保存文档快照（用于后续增量更新的 Diff 分析） ──────────────────
        if uitest_agent._get_state(task_id).document_data:
            _snap = uitest_agent._get_state(task_id).document_data.get("content", "")
            if _snap:
                from skills.case_generator import case_generator as _cg
                task.doc_snapshot = _snap[:20000]
                task.doc_hash     = _cg.compute_doc_hash(_snap)

        for case in cases:
            db_case = TestCase(
                task_id=task_id,
                name=case.get("name", "Unnamed Case"),
                module=case.get("module", "通用"),
                priority=case.get("priority", "P1"),
                preconditions=case.get("preconditions", ""),
                steps=case.get("steps", ""),
                expected_results=case.get("expected_results", ""),
                element_selector=case.get("element_selector", ""),
                enabled=True
            )
            db.add(db_case)

        await db.commit()

        result = await db.execute(select(TestCase).where(TestCase.task_id == task_id))
        all_cases = result.scalars().all()

        return [
            CaseResponse(
                id=c.id,
                task_id=c.task_id,
                name=c.name,
                module=c.module,
                priority=c.priority,
                preconditions=c.preconditions,
                steps=c.steps,
                expected_results=c.expected_results,
                element_selector=getattr(c, 'element_selector', '') or '',
                enabled=c.enabled
            )
            for c in all_cases
        ]
    except Exception as e:
        logger.error(f"Error generating cases: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/optimize/{task_id}")
async def optimize_cases(
    task_id: int,
    db: AsyncSession = Depends(get_db)
):
    """分析已有用例覆盖缺口，追加补充用例。"""
    try:
        from sqlalchemy import select
        from skills.case_generator import case_generator as cg

        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        result = await db.execute(select(TestCase).where(TestCase.task_id == task_id))
        existing_db_cases = result.scalars().all()
        if not existing_db_cases:
            raise HTTPException(status_code=400, detail="No existing cases to optimize")

        existing_cases = [
            {
                "name": c.name, "module": c.module or "通用",
                "priority": c.priority, "steps": c.steps,
                "expected_results": c.expected_results,
                "element_selector": getattr(c, "element_selector", "") or "",
            }
            for c in existing_db_cases
        ]
        page_elements = task.page_elements or []

        document_data = None
        if task.document_path:
            doc_path = _resolve_doc_path(task.document_path)
            if doc_path:
                try:
                    document_data = await uitest_agent.parse_document(str(doc_path))
                except Exception:
                    pass

        async def _progress(pct: int, stage: str):
            await ws_manager.broadcast(
                {"type": "cases_opt_progress", "percent": pct, "stage": stage},
                client_id="cases_opt"
            )

        new_cases = await cg.optimize_cases(
            existing_cases=existing_cases,
            page_elements=page_elements,
            document_data=document_data,
            progress_cb=_progress,
        )

        added = []
        for case in new_cases:
            db_case = TestCase(
                task_id=task_id,
                name=case.get("name", "补充用例"),
                module=case.get("module", "通用"),
                priority=case.get("priority", "P1"),
                preconditions=case.get("preconditions", ""),
                steps=case.get("steps", ""),
                expected_results=case.get("expected_results", ""),
                element_selector=case.get("element_selector", ""),
                enabled=True
            )
            db.add(db_case)
            added.append(db_case)

        await db.commit()

        return {"added": len(new_cases), "message": f"新增 {len(new_cases)} 条补充用例"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error optimizing cases: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/coverage/{task_id}")
async def get_coverage(
    task_id: int,
    db: AsyncSession = Depends(get_db)
):
    """返回当前任务的用例覆盖度指标。"""
    try:
        from sqlalchemy import select
        from skills.case_generator import case_generator as cg

        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        result = await db.execute(select(TestCase).where(TestCase.task_id == task_id))
        db_cases = result.scalars().all()

        cases = [
            {
                "name": c.name, "module": c.module or "通用",
                "priority": c.priority, "steps": c.steps,
                "expected_results": c.expected_results,
                "element_selector": getattr(c, "element_selector", "") or "",
            }
            for c in db_cases
            if not getattr(c, 'deprecated', False)  # 过滤废弃用例；用户禁用用例仍计入覆盖率
        ]
        page_elements = task.page_elements or []

        return cg.analyze_coverage(cases, page_elements)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting coverage: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# WebUI 用例 — 文档变更检测（Diff 分析，只读，不修改数据库）
# ─────────────────────────────────────────────────────────────────────────────

class WebUIDiffCheckRequest(BaseModel):
    new_content: Optional[str] = None
    new_document_path: Optional[str] = None


@router.post("/cases/doc-diff-check/{task_id}")
async def webui_doc_diff_check(
    task_id: int,
    request: WebUIDiffCheckRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    对比新旧需求文档，返回变更模块清单（不修改数据库，只分析）。
    前端用来展示 Diff 预览，用户确认后再调 incremental-update。
    """
    from sqlalchemy import select
    from skills.case_generator import case_generator as cg

    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 取新文档内容
    if not request.new_content and not request.new_document_path:
        raise HTTPException(status_code=400, detail="请提供新版文档路径或文本内容")

    if request.new_document_path:
        try:
            document_data = await uitest_agent.parse_document(request.new_document_path)
            new_content = document_data.get("content", "")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"新文档解析失败: {e}")
    else:
        new_content = request.new_content or ""

    if not new_content.strip():
        raise HTTPException(status_code=400, detail="新文档内容为空")

    new_hash = cg.compute_doc_hash(new_content)
    old_hash = task.doc_hash or ""

    if old_hash and new_hash == old_hash:
        return {
            "has_change": False,
            "new_doc_hash": new_hash,
            "old_doc_hash": old_hash,
            "diff": None,
            "message": "文档内容未发生变化，无需更新用例",
        }

    old_content = task.doc_snapshot or ""
    if not old_content:
        return {
            "has_change": True,
            "new_doc_hash": new_hash,
            "old_doc_hash": old_hash,
            "diff": None,
            "message": "旧版文档快照未保存（在上次生成用例前请确保已关联文档），建议直接重新生成用例",
        }

    try:
        diff_result = await cg.analyze_doc_diff(
            old_doc_content=old_content,
            new_doc_content=new_content,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "has_change": True,
        "new_doc_hash": new_hash,
        "old_doc_hash": old_hash,
        "diff": diff_result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# WebUI 用例 — 增量更新（文档变更后只重生成 changed/added 模块）
# ─────────────────────────────────────────────────────────────────────────────

class WebUIIncrementalUpdateRequest(BaseModel):
    new_content: Optional[str] = None
    new_document_path: Optional[str] = None
    diff: Optional[dict] = None
    reparse_page: bool = False


@router.post("/cases/incremental-update/{task_id}")
async def webui_incremental_update(
    task_id: int,
    request: WebUIIncrementalUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    WebUI 自动化测试用例增量更新：
    1. 解析新文档；若未传 diff 则重新做 Diff 分析
    2. 只对 changed/added 模块重新生成用例
    3. unchanged 模块保留旧用例，removed 模块用例打 deprecated 标记
    4. 清空旧用例，写入合并后的完整用例集（active + deprecated）
    5. 更新 task.doc_snapshot / doc_hash
    """
    from sqlalchemy import select, delete as sql_delete
    from skills.case_generator import case_generator as cg

    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # ── 1. 获取新文档内容 ────────────────────────────────────────────────
    if not request.new_content and not request.new_document_path:
        raise HTTPException(status_code=400, detail="请提供新版文档路径或文本内容")

    if request.new_document_path:
        try:
            document_data = await uitest_agent.parse_document(request.new_document_path)
            new_content = document_data.get("content", "")
            # 解析完删除临时文件
            from pathlib import Path as _Path
            p = _Path(request.new_document_path)
            if "uploads" in p.parts and "documents" in p.parts:
                p.unlink(missing_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"新文档解析失败: {e}")
    else:
        new_content = request.new_content or ""

    if not new_content.strip():
        raise HTTPException(status_code=400, detail="新文档内容为空")

    # ── 2. 可选：重新抓取页面元素 ─────────────────────────────────────────
    if request.reparse_page and task.url:
        try:
            await ws_manager.broadcast(
                {"type": "cases_gen_progress", "percent": 5, "stage": "重新抓取页面元素..."},
                client_id="cases_gen",
            )
            elements = await uitest_agent.parse_page(task.url, task.browser or "chromium")
            task.page_elements = elements
            logger.info(f"重新抓取页面元素: task_id={task_id}，共 {len(elements)} 个")
        except Exception as e:
            logger.warning(f"页面重新抓取失败，使用旧元素: {e}")

    # ── 3. 获取 diff 结果 ────────────────────────────────────────────────
    diff_result = request.diff
    if not diff_result:
        old_content = task.doc_snapshot or ""
        if not old_content:
            raise HTTPException(
                status_code=400,
                detail="旧版文档快照未保存，无法做精确 Diff。请直接重新生成用例。"
            )
        try:
            diff_result = await cg.analyze_doc_diff(
                old_doc_content=old_content,
                new_doc_content=new_content,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    has_changes = bool(
        diff_result.get("changed") or diff_result.get("added") or diff_result.get("removed")
    )
    if not has_changes:
        raise HTTPException(status_code=400, detail="Diff 分析未发现任何模块变更，无需更新")

    # ── 4. 读取已有用例 ──────────────────────────────────────────────────
    case_result = await db.execute(select(TestCase).where(TestCase.task_id == task_id))
    existing_db_cases = case_result.scalars().all()
    existing_cases = [
        {
            "id":               f"TC{c.id:03d}",
            "name":             c.name,
            "module":           c.module or "通用",
            "priority":         c.priority,
            "preconditions":    c.preconditions or "",
            "steps":            c.steps or "",
            "expected_results": c.expected_results or "",
            "element_selector": getattr(c, "element_selector", "") or "",
        }
        for c in existing_db_cases
    ]

    # ── 5. 执行增量更新 ───────────────────────────────────────────────────
    async def _progress(pct: int, stage: str):
        await ws_manager.broadcast(
            {"type": "cases_gen_progress", "percent": pct, "stage": stage},
            client_id="cases_gen",
        )

    try:
        upd = await cg.incremental_update(
            url           = task.url or "",
            page_elements = task.page_elements or [],
            existing_cases= existing_cases,
            diff_result   = diff_result,
            new_doc_content= new_content,
            progress_cb   = _progress,
        )
    except Exception as e:
        logger.exception("WebUI 增量更新失败: {}", repr(e))
        raise HTTPException(status_code=500, detail=f"增量更新失败: {e}")

    # ── 6. 清空旧用例，写入新完整集合 ────────────────────────────────────
    await db.execute(sql_delete(TestCase).where(TestCase.task_id == task_id))

    all_cases = upd["retained_cases"] + upd["new_cases"] + upd["deprecated_cases"]
    for case in all_cases:
        db_case = TestCase(
            task_id         = task_id,
            name            = case.get("name", "未命名"),
            module          = case.get("module", "通用"),
            priority        = case.get("priority", "P1"),
            preconditions   = case.get("preconditions", ""),
            steps           = case.get("steps", ""),
            expected_results= case.get("expected_results", ""),
            element_selector= case.get("element_selector", ""),
            enabled         = True,   # enabled 只由用户手动控制，不受废弃影响
            deprecated      = (case.get("status") == "deprecated"),
        )
        db.add(db_case)

    # ── 7. 更新 task 文档快照 ─────────────────────────────────────────────
    task.doc_snapshot = new_content[:20000]
    task.doc_hash     = cg.compute_doc_hash(new_content)
    task.status       = "cases_updated"

    await db.commit()

    active_count     = len(upd["retained_cases"]) + len(upd["new_cases"])
    deprecated_count = len(upd["deprecated_cases"])

    logger.info(
        f"WebUI 增量更新完成: task_id={task_id}，"
        f"active={active_count} deprecated={deprecated_count}，"
        f"摘要: {upd['diff_summary']}"
    )
    return {
        "active_count":     active_count,
        "deprecated_count": deprecated_count,
        "diff_summary":     upd["diff_summary"],
        "message":          f"增量更新成功！有效用例 {active_count} 条，废弃 {deprecated_count} 条",
    }


@router.put("/cases/{case_id}", response_model=CaseResponse)
async def update_case(
    case_id: int,
    request: CaseUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import select
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    case = result.scalar_one_or_none()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(case, key, value)

    await db.commit()
    await db.refresh(case)

    return CaseResponse(
        id=case.id,
        task_id=case.task_id,
        name=case.name,
        module=case.module,
        priority=case.priority,
        preconditions=case.preconditions,
        steps=case.steps,
        expected_results=case.expected_results,
        enabled=case.enabled,
        deprecated=getattr(case, 'deprecated', False) or False,
    )


@router.delete("/cases/{case_id}")
async def delete_case(case_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, delete
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    case = result.scalar_one_or_none()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    await db.execute(delete(TestCase).where(TestCase.id == case_id))
    await db.commit()

    return {"message": "Case deleted"}


async def _run_execution_bg(report_id: int, task_id: int, task_name: str,
                            task_url: str, case_dicts: list, case_ids, browser: str):
    """后台执行测试，通过 WebSocket 推送进度，完成后写回数据库"""
    from tools.database import async_session_maker
    try:
        uitest_agent._get_state(task_id).cases = case_dicts
        results = await uitest_agent.execute_cases(
            case_ids=case_ids,
            browser_type=browser,
            url=task_url,
            task_id=task_id,
        )

        for r in results:
            sp = r.get("screenshot_path")
            if sp and not sp.startswith("http"):
                r["screenshot_path"] = f"/screenshots/{Path(sp).name}"

        passed = sum(1 for r in results if r.get("status") == "passed")
        failed = sum(1 for r in results if r.get("status") == "failed")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        pass_rate = (passed / len(results) * 100) if results else 0

        details = [
            {
                "id": idx,
                "case_name": r.get("case_name", "Unknown"),
                "status": r.get("status", "unknown"),
                "duration": round(r.get("duration", 0), 2),
                "error_message": r.get("error_message"),
                "screenshot": r.get("screenshot_path"),
                "start_time": r.get("start_time"),
                "end_time": r.get("end_time")
            }
            for idx, r in enumerate(results, 1)
        ]
        summary = {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pass_rate": round(pass_rate, 2),
            "total_duration": round(sum(r.get("duration", 0) for r in results), 2),
            "failed_cases": [
                {"case_name": r.get("case_name"), "error": r.get("error_message", ""), "duration": r.get("duration", 0)}
                for r in results if r.get("status") == "failed"
            ]
        }

        async with async_session_maker() as db:
            from sqlalchemy import select
            res = await db.execute(select(TestReport).where(TestReport.id == report_id))
            report = res.scalar_one_or_none()
            if report:
                report.summary = summary
                report.details = details
                report.pass_rate = round(pass_rate, 2)
                report.passed = passed
                report.failed = failed
                report.skipped = skipped

                for r in results:
                    db.add(TestResult(
                        task_id=task_id,
                        case_id=r.get("case_id"),
                        status=r.get("status"),
                        start_time=datetime.fromisoformat(r["start_time"]) if r.get("start_time") else None,
                        end_time=datetime.fromisoformat(r["end_time"]) if r.get("end_time") else None,
                        duration=r.get("duration", 0),
                        error_message=r.get("error_message"),
                        screenshot_path=r.get("screenshot_path"),
                        logs=r.get("logs")
                    ))

                try:
                    report_data = await uitest_agent.generate_report(task_name)
                    report.report_path = report_data.get("html_path") or report_data.get("report_path")
                except Exception as e:
                    logger.error(f"Failed to generate report file: {e}")

                await db.commit()

        await ws_manager.broadcast_all({
            "type": "execution_saved",
            "report_id": report_id,
            "summary": summary
        })

    except Exception as e:
        logger.error(f"Background execution failed: {e}", exc_info=True)
        await ws_manager.broadcast_all({
            "type": "execution_error",
            "report_id": report_id,
            "error": str(e)
        })


@router.post("/execute")
async def execute_cases(
    request: ExecuteRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import select
    result = await db.execute(
        select(TestCase).where(TestCase.task_id == request.task_id)
    )
    cases = result.scalars().all()

    if request.case_ids:
        cases = [c for c in cases if c.id in request.case_ids]

    # 废弃用例（需求变更标记的）不参与执行；用户禁用（enabled=False）由 case_ids 控制
    cases = [c for c in cases if not getattr(c, 'deprecated', False)]

    case_dicts = [
        {
            "id": c.id,
            "name": c.name,
            "module": c.module,
            "priority": c.priority,
            "preconditions": c.preconditions,
            "steps": c.steps,
            "expected_results": c.expected_results,
            "element_selector": getattr(c, 'element_selector', '')
        }
        for c in cases
    ]

    task_result = await db.execute(
        select(TestTask).where(TestTask.id == request.task_id)
    )
    task = task_result.scalar_one_or_none()
    task_url = task.url if task else ""
    task_name = task.name if task else f"Task {request.task_id}"

    report = TestReport(
        task_id=request.task_id,
        name=f"{task_name} - 测试报告",
        summary={},
        details=[],
        pass_rate=0,
        total_cases=len(case_dicts),
        passed=0,
        failed=0,
        skipped=0
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    background_tasks.add_task(
        _run_execution_bg,
        report_id=report.id,
        task_id=request.task_id,
        task_name=task_name,
        task_url=task_url,
        case_dicts=case_dicts,
        case_ids=request.case_ids,
        browser=request.browser
    )

    return {
        "report_id": report.id,
        "status": "running",
        "total": len(case_dicts),
        "message": f"开始执行 {len(case_dicts)} 个用例，请通过 WebSocket 接收进度"
    }


@router.get("/reports", response_model=List[ReportResponse])
async def list_reports(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(
        select(TestReport).order_by(TestReport.created_at.desc())
    )
    reports = result.scalars().all()

    return [
        ReportResponse(
            task_id=r.task_id,
            task_name=r.name,
            summary=json.loads(r.summary) if isinstance(r.summary, str) else (r.summary or {}),
            html_path=r.report_path or "",
            report_id=r.id,
            total_cases=r.total_cases or 0,
            passed=r.passed or 0,
            failed=r.failed or 0,
            skipped=r.skipped or 0,
            pass_rate=r.pass_rate or 0,
            details=json.loads(r.details) if isinstance(r.details, str) else (r.details or []),
            created_at=r.created_at.isoformat() if r.created_at else ""
        )
        for r in reports
    ]


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report_by_id(report_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(
        select(TestReport).where(TestReport.id == report_id)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return ReportResponse(
        task_id=report.task_id,
        task_name=report.name,
        summary=json.loads(report.summary) if isinstance(report.summary, str) else (report.summary or {}),
        html_path=report.report_path or "",
        report_id=report.id,
        total_cases=report.total_cases or 0,
        passed=report.passed or 0,
        failed=report.failed or 0,
        skipped=report.skipped or 0,
        pass_rate=report.pass_rate or 0,
        details=json.loads(report.details) if isinstance(report.details, str) else (report.details or []),
        created_at=report.created_at.isoformat() if report.created_at else ""
    )


@router.get("/reports/{report_id}/export")
async def export_report(report_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from fastapi.responses import HTMLResponse
    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    summary = json.loads(report.summary) if isinstance(report.summary, str) else (report.summary or {})
    details = json.loads(report.details) if isinstance(report.details, str) else (report.details or [])
    task_name = report.name or f"报告 {report_id}"
    created_at = report.created_at.strftime("%Y-%m-%d %H:%M:%S") if report.created_at else ""

    details_rows = ""
    for detail in details:
        status_map = {"passed": ("success", "通过"), "failed": ("danger", "失败"), "skipped": ("warning", "跳过")}
        cls, label = status_map.get(detail.get("status", ""), ("secondary", detail.get("status", "-")))
        err = detail.get("error_message") or "-"
        if len(err) > 120:
            err = err[:120] + "…"
        shot = detail.get("screenshot", "")
        shot_cell = f'<td><a href="{shot}" target="_blank" style="color:#409eff;">查看</a></td>' if shot else "<td>-</td>"
        details_rows += f"""
        <tr>
            <td>{detail.get('id', '')}</td>
            <td>{detail.get('case_name', '-')}</td>
            <td><span class="badge bg-{cls}">{label}</span></td>
            <td>{detail.get('duration', 0)}s</td>
            <td style="max-width:300px;word-break:break-all;">{err}</td>
            {shot_cell}
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>测试报告 - {task_name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f5;padding:24px;color:#333}}
.container{{max-width:1200px;margin:0 auto}}
.header{{background:#fff;padding:24px;border-radius:8px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.08)}}
.header h1{{font-size:22px;margin-bottom:6px}}
.meta{{color:#888;font-size:13px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:20px}}
.card{{background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.08);text-align:center}}
.card .num{{font-size:32px;font-weight:700;margin-bottom:4px}}
.card .lbl{{font-size:13px;color:#888}}
.green{{color:#52c41a}}.red{{color:#ff4d4f}}.orange{{color:#fa8c16}}.blue{{color:#1890ff}}
.section{{background:#fff;padding:24px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.08)}}
.section h2{{font-size:16px;margin-bottom:16px;border-left:4px solid #409eff;padding-left:10px}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #f0f0f0;font-size:13px}}
th{{background:#fafafa;font-weight:600;color:#555}}
.badge{{padding:3px 8px;border-radius:4px;font-size:12px}}
.bg-success{{background:#d9f7be;color:#52c41a}}
.bg-danger{{background:#fff1f0;color:#ff4d4f}}
.bg-warning{{background:#fffbe6;color:#fa8c16}}
.bg-secondary{{background:#f5f5f5;color:#999}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>{task_name}</h1>
    <p class="meta">生成时间：{created_at}</p>
  </div>
  <div class="cards">
    <div class="card"><div class="num blue">{summary.get('total', 0)}</div><div class="lbl">总用例数</div></div>
    <div class="card"><div class="num green">{summary.get('passed', 0)}</div><div class="lbl">通过</div></div>
    <div class="card"><div class="num red">{summary.get('failed', 0)}</div><div class="lbl">失败</div></div>
    <div class="card"><div class="num orange">{summary.get('skipped', 0)}</div><div class="lbl">跳过</div></div>
    <div class="card"><div class="num green">{summary.get('pass_rate', 0)}%</div><div class="lbl">通过率</div></div>
    <div class="card"><div class="num">{summary.get('total_duration', 0)}s</div><div class="lbl">总耗时</div></div>
  </div>
  <div class="section">
    <h2>用例执行详情</h2>
    <table>
      <thead><tr><th>序号</th><th>用例名称</th><th>状态</th><th>耗时</th><th>错误信息</th><th>截图</th></tr></thead>
      <tbody>{details_rows}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""

    from urllib.parse import quote
    safe_name = task_name.replace("/", "_")
    encoded_name = quote(safe_name + ".html", safe="")
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"}
    )


@router.delete("/reports/{report_id}")
async def delete_report(report_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, delete
    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    await db.execute(delete(TestReport).where(TestReport.id == report_id))
    await db.commit()
    return {"message": "Report deleted"}


@router.delete("/reports")
async def delete_reports_batch(report_ids: List[int], db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete
    if not report_ids:
        raise HTTPException(status_code=400, detail="No report IDs provided")
    await db.execute(delete(TestReport).where(TestReport.id.in_(report_ids)))
    await db.commit()
    return {"message": f"Deleted {len(report_ids)} reports"}


@router.get("/tasks/{task_id}/report", response_model=ReportResponse)
async def get_report(task_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(
        select(TestReport).where(TestReport.task_id == task_id)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return ReportResponse(
        task_id=report.task_id,
        task_name=report.name,
        summary=json.loads(report.summary) if isinstance(report.summary, str) else (report.summary or {}),
        html_path=report.report_path or "",
        report_id=report.id,
        total_cases=report.total_cases or 0,
        passed=report.passed or 0,
        failed=report.failed or 0,
        skipped=report.skipped or 0,
        pass_rate=report.pass_rate or 0,
        details=json.loads(report.details) if isinstance(report.details, str) else (report.details or []),
        created_at=report.created_at.isoformat() if report.created_at else ""
    )


@router.post("/command", response_model=CommandResponse)
async def send_command(request: CommandRequest):
    result = await uitest_agent.handle_command(request.message)
    return CommandResponse(**result)


@router.get("/agent/state")
async def get_agent_state():
    return uitest_agent.get_state()


@router.post("/agent/pause")
async def pause_execution():
    from skills.test_executor import test_executor
    test_executor.pause()
    return {"message": "Execution paused"}


@router.post("/agent/resume")
async def resume_execution():
    from skills.test_executor import test_executor
    test_executor.resume()
    return {"message": "Execution resumed"}


@router.post("/agent/stop")
async def stop_execution():
    from skills.test_executor import test_executor
    test_executor.stop()  # now sync
    return {"message": "Stop signal sent"}


@router.get("/skills")
async def list_skills():
    uitest_agent.load_skills()
    return {
        "skills": uitest_agent.get_skills(),
        "total": len(uitest_agent.get_skills())
    }


@router.get("/skills/{skill_name}")
async def get_skill(skill_name: str):
    from skills.skill_registry import skill_registry
    uitest_agent.load_skills()
    found_skill = None
    for s in uitest_agent.get_skills():
        if s["name"] == skill_name:
            found_skill = s
            break
    if found_skill:
        return found_skill
    raise HTTPException(status_code=404, detail="Skill not found")


@router.post("/skills/{skill_name}/reload")
async def reload_skill(skill_name: str):
    from skills.skill_loader import skill_loader
    skill_loader.reload()
    uitest_agent._skills_loaded = False
    uitest_agent.load_skills()
    return {"message": f"Skill {skill_name} reloaded", "skills": uitest_agent.get_skills()}


@router.get("/skills/{skill_name}/file-content")
async def get_skill_file_content(skill_name: str, path: str = "SKILL.md"):
    """读取技能目录内的单个文件内容（限 .md / .yaml / .yml / .txt）"""
    from pathlib import Path as FilePath
    allowed_exts = {".md", ".yaml", ".yml", ".txt"}
    uitest_agent.load_skills()
    for skill in uitest_agent.get_skills():
        if skill["name"] == skill_name and skill.get("file_path"):
            skill_root = FilePath(skill["file_path"]).parent
            target = (skill_root / path).resolve()
            # 安全检查：不允许跳出技能目录
            if not str(target).startswith(str(skill_root.resolve())):
                raise HTTPException(status_code=403, detail="Access denied")
            if target.suffix not in allowed_exts:
                raise HTTPException(status_code=400, detail="File type not allowed")
            if not target.exists():
                raise HTTPException(status_code=404, detail="File not found")
            return {"content": target.read_text(encoding="utf-8"), "path": path}
    raise HTTPException(status_code=404, detail="Skill not found")


@router.get("/skills/{skill_name}/files")
async def get_skill_files(skill_name: str):
    from pathlib import Path
    uitest_agent.load_skills()
    for skill in uitest_agent.get_skills():
        if skill["name"] == skill_name and skill.get("file_path"):
            skill_path = Path(skill["file_path"]).parent
            if skill_path.exists():
                files = []
                for f in skill_path.rglob("*"):
                    if f.is_file():
                        files.append({
                            "name": f.name,
                            "path": str(f.relative_to(skill_path)),
                            "size": f.stat().st_size,
                            "type": f.suffix
                        })
                return {"skill_name": skill_name, "path": str(skill_path), "files": files}
    raise HTTPException(status_code=404, detail="Skill not found")


@router.get("/llm/models")
async def get_llm_models():
    from tools.config import settings
    available_models = [
        {"id": "gpt-4o",              "name": "GPT-4o",              "provider": "OpenAI"},
        {"id": "gpt-4o-mini",         "name": "GPT-4o Mini",         "provider": "OpenAI"},
        {"id": "gpt-4-turbo",         "name": "GPT-4 Turbo",         "provider": "OpenAI"},
        {"id": "gpt-3.5-turbo",       "name": "GPT-3.5 Turbo",       "provider": "OpenAI"},
        {"id": "claude-sonnet-4-6",   "name": "Claude Sonnet 4.6",   "provider": "Anthropic"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "provider": "Anthropic"},
        {"id": "claude-opus-4-8",     "name": "Claude Opus 4.8",     "provider": "Anthropic"},
        {"id": "gemini-2.0-flash",    "name": "Gemini 2.0 Flash",    "provider": "Google"},
        {"id": "moonshot-v1-8k",      "name": "Moonshot 8K",         "provider": "Moonshot"},
        {"id": "moonshot-v1-32k",     "name": "Moonshot 32K",        "provider": "Moonshot"},
        {"id": "moonshot-v1-128k",    "name": "Moonshot 128K",       "provider": "Moonshot"},
        {"id": "deepseek-v4-flash",    "name": "DeepSeek V4 Flash",   "provider": "DeepSeek"},
        {"id": "deepseek-reasoner",   "name": "DeepSeek Reasoner",   "provider": "DeepSeek"},
        {"id": "qwen-turbo",          "name": "Qwen Turbo",          "provider": "Alibaba"},
        {"id": "qwen-plus",           "name": "Qwen Plus",           "provider": "Alibaba"},
        {"id": "qwen-max",            "name": "Qwen Max",            "provider": "Alibaba"},
        {"id": "yi-lightning",        "name": "Yi Lightning",        "provider": "01AI"},
    ]
    temperature = getattr(settings, "AI_TEMPERATURE", 0.5)
    return {
        "current_model": settings.AI_MODEL,
        "current_model_name": settings.AI_MODEL_NAME,
        "current_api_url": settings.AI_API_URL,
        "api_key_configured": bool(settings.AI_API_KEY),
        "temperature": temperature,
        "models": available_models
    }


@router.put("/llm/model")
async def update_llm_model(config: LLMConfigRequest):
    from tools.config import settings
    from pathlib import Path
    import os

    model = config.model
    api_key = config.api_key
    api_url = config.api_url

    env_path = Path(__file__).parent.parent / ".env"
    
    # 读取现有配置
    env_lines = []
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            env_lines = f.readlines()

    updates = []
    
    # 更新或添加配置项
    updated = False
    for i, line in enumerate(env_lines):
        if line.startswith("AI_MODEL="):
            env_lines[i] = f"AI_MODEL={model}\n"
            updated = True
            break
    if not updated and model:
        env_lines.append(f"AI_MODEL={model}\n")
    if model:
        settings.AI_MODEL = model
        updates.append(f"AI_MODEL={model}")

    updated = False
    for i, line in enumerate(env_lines):
        if line.startswith("AI_API_KEY="):
            env_lines[i] = f"AI_API_KEY={api_key}\n" if api_key else line
            updated = True
            break
    if not updated and api_key:
        env_lines.append(f"AI_API_KEY={api_key}\n")
    if api_key:
        settings.AI_API_KEY = api_key
        updates.append("AI_API_KEY=<已更新>")

    updated = False
    for i, line in enumerate(env_lines):
        if line.startswith("AI_API_URL="):
            env_lines[i] = f"AI_API_URL={api_url}\n"
            updated = True
            break
    if not updated and api_url:
        env_lines.append(f"AI_API_URL={api_url}\n")
    if api_url:
        settings.AI_API_URL = api_url
        updates.append(f"AI_API_URL={api_url}")

    model_name = config.model_name
    if model_name:
        updated = False
        for i, line in enumerate(env_lines):
            if line.startswith("AI_MODEL_NAME="):
                env_lines[i] = f"AI_MODEL_NAME={model_name}\n"
                updated = True
                break
        if not updated:
            env_lines.append(f"AI_MODEL_NAME={model_name}\n")
        settings.AI_MODEL_NAME = model_name

    temperature = config.temperature
    if temperature is not None:
        updated = False
        for i, line in enumerate(env_lines):
            if line.startswith("AI_TEMPERATURE="):
                env_lines[i] = f"AI_TEMPERATURE={temperature}\n"
                updated = True
                break
        if not updated:
            env_lines.append(f"AI_TEMPERATURE={temperature}\n")
        if hasattr(settings, "AI_TEMPERATURE"):
            settings.AI_TEMPERATURE = temperature

    env_lines = [line for line in env_lines if line.strip() or line == '\n']

    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(env_lines)

    # 热重载 LangGraph Agent
    if settings.AI_API_KEY and settings.AI_API_URL and settings.AI_MODEL:
        try:
            from agent.langgraph_agent import init_langgraph_agent
            init_langgraph_agent(
                api_key=settings.AI_API_KEY,
                base_url=settings.AI_API_URL,
                model_name=settings.AI_MODEL,
            )
            logger.info(f"LangGraph Agent re-initialized: {settings.AI_MODEL}")
        except Exception as e:
            logger.warning(f"LangGraph Agent re-init failed: {e}")

    return {
        "message": "LLM configuration updated",
        "model": settings.AI_MODEL,
        "api_url": settings.AI_API_URL
    }


@router.post("/llm/test")
async def test_llm_connection(request: LLMTestRequest):
    import httpx, json as _json
    from tools.config import settings

    model = request.model
    api_key = request.api_key
    api_url = request.api_url

    test_model = model or settings.AI_MODEL
    test_api_url = (api_url or settings.AI_API_URL).rstrip("/")
    test_api_key = api_key or settings.AI_API_KEY

    if not test_api_key:
        return {"success": False, "error": "API key is required"}

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        # 优先尝试 OpenAI 兼容格式 (/v1/chat/completions)
        for endpoint, headers, body in [
            (
                f"{test_api_url}/v1/chat/completions",
                {"Authorization": f"Bearer {test_api_key}", "Content-Type": "application/json"},
                {"model": test_model, "messages": [{"role": "user", "content": "reply: ok"}], "max_tokens": 10},
            ),
            (
                f"{test_api_url}/v1/messages",
                {"x-api-key": test_api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                {"model": test_model, "max_tokens": 10, "messages": [{"role": "user", "content": "reply: ok"}]},
            ),
        ]:
            try:
                resp = await client.post(endpoint, headers=headers, json=body)
            except Exception as e:
                continue

            if resp.status_code not in (200, 201):
                last_err = resp.text[:300]
                continue

            # 必须是 JSON 且含有效内容，不接受 HTML
            ct = resp.headers.get("content-type", "")
            if "html" in ct or resp.text.lstrip().startswith("<"):
                last_err = "API 返回了 HTML 页面，不是有效的 AI 接口响应"
                continue

            try:
                data = resp.json()
            except Exception:
                last_err = "响应不是有效 JSON"
                continue

            # OpenAI 格式
            if data.get("choices"):
                reply = data["choices"][0].get("message", {}).get("content", "")
                return {"success": True, "model": test_model, "message": f"连接成功，模型回复: {reply[:50]}"}
            # Anthropic 格式
            if data.get("content"):
                reply = data["content"][0].get("text", "") if isinstance(data["content"], list) else str(data["content"])
                return {"success": True, "model": test_model, "message": f"连接成功，模型回复: {reply[:50]}"}

            last_err = f"响应格式未知: {str(data)[:200]}"

        return {"success": False, "error": last_err if 'last_err' in dir() else "连接失败"}


# ======================================================================
# AI 用例生成
# ======================================================================
from pydantic import BaseModel as _BaseModel
from typing import List as _List, Dict as _Dict, Any as _Any, Optional as _Optional

class AICaseGenerateRequest(_BaseModel):
    task_name: str
    document_path: _Optional[str] = None
    content: _Optional[str] = None
    formats: _List[str] = ["md", "xmind"]


class AICaseFileResponse(_BaseModel):
    id: int
    task_name: str
    case_count: int
    has_md: bool
    has_xmind: bool
    modules: _List[_Dict[str, _Any]] = []
    created_at: str = ""
    # 文档变更追踪字段
    doc_hash: _Optional[str] = None
    parent_id: _Optional[int] = None
    diff_summary: _Optional[str] = None
    record_status: str = "active"


def _ai_case_response(record) -> AICaseFileResponse:
    """统一构建 AICaseFileResponse，避免在每个端点重复写相同字段。"""
    modules = (record.cases_data or {}).get("modules", [])
    return AICaseFileResponse(
        id=record.id,
        task_name=record.task_name,
        case_count=record.case_count,
        has_md=bool(record.md_path),
        has_xmind=bool(record.xmind_path),
        modules=modules,
        created_at=record.created_at.isoformat() if record.created_at else "",
        doc_hash=record.doc_hash,
        parent_id=record.parent_id,
        diff_summary=record.diff_summary,
        record_status=getattr(record, "record_status", "active") or "active",
    )


@router.post("/ai-cases/generate", response_model=AICaseFileResponse)
async def generate_ai_cases(
    request: AICaseGenerateRequest,
    db: AsyncSession = Depends(get_db)
):
    from skills.ai_case_generator import ai_case_generator
    from tools.database import AICaseFile
    from api.websocket_manager import ws_manager

    if not request.document_path and not request.content:
        raise HTTPException(status_code=400, detail="请提供文档路径或需求文本内容")

    async def _progress(pct: int, stage: str):
        await ws_manager.broadcast(
            {"type": "ai_gen_progress", "percent": pct, "stage": stage},
            client_id="ai_gen",
        )

    try:
        result = await ai_case_generator.generate(
            task_name=request.task_name,
            document_path=request.document_path,
            content=request.content,
            formats=request.formats,
            progress_cb=_progress,
        )
    except RuntimeError as e:
        await ws_manager.broadcast(
            {"type": "ai_gen_progress", "percent": 0, "stage": f"生成失败: {e}", "error": True},
            client_id="ai_gen",
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("AI 用例生成失败: {}", repr(e))
        raise HTTPException(status_code=500, detail=f"生成失败: {type(e).__name__}: {e}")

    record = AICaseFile(
        task_name=request.task_name,
        case_count=result.get("case_count", 0),
        md_path=result["files"].get("md"),
        xmind_path=result["files"].get("xmind"),
        cases_data=result.get("cases_data"),
        doc_hash=result.get("doc_hash"),
        doc_content=result.get("doc_content"),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # RAG 入库（后台异步，不阻塞响应）
    doc_text = result.get("_doc_text_for_rag", "")
    if doc_text:
        import asyncio as _asyncio
        from skills.rag import index_document as _index_doc
        _asyncio.create_task(_index_doc(record.id, "ai_case", doc_text))

    return _ai_case_response(record)


@router.get("/ai-cases", response_model=List[AICaseFileResponse])
async def list_ai_cases(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from tools.database import AICaseFile

    result = await db.execute(
        select(AICaseFile).order_by(AICaseFile.created_at.desc())
    )
    rows = result.scalars().all()
    return [_ai_case_response(r) for r in rows]


@router.get("/ai-cases/{record_id}", response_model=AICaseFileResponse)
async def get_ai_case(record_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from tools.database import AICaseFile

    result = await db.execute(
        select(AICaseFile).where(AICaseFile.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    return _ai_case_response(record)


@router.get("/ai-cases/{record_id}/download")
async def download_ai_case(record_id: int, format: str = "md", db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from tools.database import AICaseFile
    from fastapi.responses import FileResponse, Response
    from urllib.parse import quote

    result = await db.execute(
        select(AICaseFile).where(AICaseFile.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    if format == "md":
        file_path = record.md_path
        media_type = "text/markdown"
        ext = ".md"
    elif format == "xmind":
        file_path = record.xmind_path
        media_type = "application/octet-stream"
        ext = ".xmind"
    else:
        raise HTTPException(status_code=400, detail="不支持的格式，请使用 md 或 xmind")

    if not file_path:
        raise HTTPException(status_code=404, detail=f"该记录未生成 {format} 文件")

    # 路径解析
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(__file__).parent.parent / file_path
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")

    safe_name = record.task_name.replace("/", "_")
    encoded = quote(safe_name + ext, safe="")
    return FileResponse(
        path=str(p),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@router.post("/ai-cases/{record_id}/optimize", response_model=AICaseFileResponse)
async def optimize_ai_cases(
    record_id: int,
    request: _BaseModel = None,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from tools.database import AICaseFile
    from skills.ai_case_generator import ai_case_generator
    from api.websocket_manager import ws_manager

    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    cases_data = record.cases_data or {}
    if not cases_data.get("modules"):
        raise HTTPException(status_code=400, detail="该记录没有可优化的用例数据")

    async def _progress(pct: int, stage: str):
        await ws_manager.broadcast(
            {"type": "ai_gen_progress", "percent": pct, "stage": stage},
            client_id="ai_gen",
        )

    try:
        opt_result = await ai_case_generator.optimize(
            task_name=record.task_name,
            cases_data=cases_data,
            formats=[f for f in ["md", "xmind"] if (f == "md" and record.md_path) or (f == "xmind" and record.xmind_path)],
            progress_cb=_progress,
        )
    except RuntimeError as e:
        await ws_manager.broadcast(
            {"type": "ai_gen_progress", "percent": 0, "stage": f"优化失败: {e}", "error": True},
            client_id="ai_gen",
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("AI 用例优化失败: {}", repr(e))
        raise HTTPException(status_code=500, detail=f"优化失败: {type(e).__name__}: {e}")

    # 更新数据库记录
    record.cases_data = opt_result["cases_data"]
    record.case_count = opt_result["case_count"]
    if opt_result["files"].get("md"):
        record.md_path = opt_result["files"]["md"]
    if opt_result["files"].get("xmind"):
        record.xmind_path = opt_result["files"]["xmind"]
    await db.commit()
    await db.refresh(record)

    modules = (record.cases_data or {}).get("modules", [])
    return _ai_case_response(record)


@router.get("/ai-cases/{record_id}/coverage")
async def get_ai_case_coverage(record_id: int, db: AsyncSession = Depends(get_db)):
    """分析 AI 用例集的测试方法、优先级、模块覆盖情况。"""
    from sqlalchemy import select
    from tools.database import AICaseFile

    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    modules_data = (record.cases_data or {}).get("modules", [])

    # 只统计有效用例，过滤掉废弃用例（status='deprecated'）
    all_cases = []
    for mod in modules_data:
        if all(c.get("status") == "deprecated" for c in mod.get("cases", []) if mod.get("cases")):
            continue  # 整个模块都废弃，跳过
        for case in mod.get("cases", []):
            if case.get("status") == "deprecated":
                continue  # 单条废弃用例跳过
            all_cases.append({**case, "_module": mod.get("name", "通用")})

    total = len(all_cases)
    if total == 0:
        return {"score": 0, "total": 0, "suggestions": ["当前无测试用例"]}

    # 优先级分布
    priority_count = {"P0": 0, "P1": 0, "P2": 0}
    for c in all_cases:
        p = c.get("priority", "P1")
        priority_count[p] = priority_count.get(p, 0) + 1

    # 模块分布
    module_map = {}
    for c in all_cases:
        m = c.get("_module", "通用")
        if m not in module_map:
            module_map[m] = {"total": 0, "P0": 0, "P1": 0, "P2": 0}
        p = c.get("priority", "P1")
        module_map[m]["total"] += 1
        module_map[m][p] = module_map[m].get(p, 0) + 1

    # 测试方法覆盖（6 种标准方法）
    STANDARD_METHODS = ["等价类划分", "边界值分析", "判定表", "场景法", "错误推测", "状态转换"]
    used_methods = set()
    for c in all_cases:
        tm = c.get("test_method", "")
        if tm:
            for m in STANDARD_METHODS:
                if m in tm:
                    used_methods.add(m)
    method_coverage = [
        {"name": m, "covered": m in used_methods}
        for m in STANDARD_METHODS
    ]
    method_rate = round(len(used_methods) / len(STANDARD_METHODS) * 100)

    # 用例类型分布
    TYPES = ["功能测试", "性能测试", "兼容性测试"]
    type_count = {t: 0 for t in TYPES}
    for c in all_cases:
        t = c.get("type", "功能测试")
        for key in TYPES:
            if key in (t or ""):
                type_count[key] += 1
                break

    # 综合评分
    method_score = len(used_methods) / len(STANDARD_METHODS) * 40   # 满分 40
    p0_ratio = priority_count["P0"] / total
    p0_score = min(p0_ratio * 200, 30)                              # 满分 30
    module_score = min(len(module_map) * 4, 20)                     # 满分 20
    type_score = sum(1 for v in type_count.values() if v > 0) / len(TYPES) * 10  # 满分 10
    score = round(method_score + p0_score + module_score + type_score)
    score = max(0, min(100, score))

    # 建议
    suggestions = []
    missing = [m["name"] for m in method_coverage if not m["covered"]]
    if missing:
        suggestions.append(f"缺少测试方法：{'、'.join(missing)}，建议补充覆盖")
    if priority_count["P0"] == 0:
        suggestions.append("缺少 P0 核心用例，建议补充关键业务流程的主路径用例")
    elif p0_ratio < 0.1:
        suggestions.append(f"P0 用例仅占 {round(p0_ratio*100)}%，建议提升至 15% 以上")
    if priority_count["P2"] == 0:
        suggestions.append("缺少 P2 边界/异常用例，建议运用边界值分析和错误推测法补充")
    if type_count["性能测试"] == 0:
        suggestions.append("缺少性能测试用例，建议补充响应时间、并发等场景")
    if type_count["兼容性测试"] == 0:
        suggestions.append("缺少兼容性测试用例，建议补充多浏览器/多分辨率场景")
    for m_name, m_data in module_map.items():
        if m_data["P0"] == 0:
            suggestions.append(f"模块「{m_name}」无 P0 用例，建议补充核心流程")
    if not suggestions:
        suggestions.append("测试覆盖良好！可进一步增加状态转换和边界组合场景")

    return {
        "score": score,
        "total": total,
        "priority_distribution": priority_count,
        "module_distribution": [{"name": k, **v} for k, v in module_map.items()],
        "method_coverage": method_coverage,
        "method_rate": method_rate,
        "type_distribution": type_count,
        "suggestions": suggestions,
    }


@router.post("/ai-cases/{record_id}/cases", response_model=AICaseFileResponse)
async def add_ai_case_item(record_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    """在指定 AI 用例记录中新建单条用例。"""
    from sqlalchemy import select
    from tools.database import AICaseFile

    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    cases_data = dict(record.cases_data or {})
    modules = list(cases_data.get("modules", []))

    module_name = (data.get("module") or "通用").strip()

    # 找到或创建目标模块
    target_mod = next((m for m in modules if m["name"] == module_name), None)
    if target_mod is None:
        target_mod = {"name": module_name, "cases": []}
        modules.append(target_mod)

    # 生成唯一用例编号（TCxxx）
    all_nums = []
    for mod in modules:
        for c in mod.get("cases", []):
            cid = c.get("id", "")
            if cid.upper().startswith("TC"):
                try:
                    all_nums.append(int(cid[2:]))
                except ValueError:
                    pass
    next_num = max(all_nums, default=0) + 1
    new_id = f"TC{next_num:03d}"

    new_case = {
        "id": new_id,
        "name": data.get("name", "新用例"),
        "priority": data.get("priority", "P1"),
        "type": data.get("type", "功能测试"),
        "test_method": data.get("test_method", ""),
        "preconditions": data.get("preconditions", ""),
        "steps": data.get("steps", []),
        "expected": data.get("expected", ""),
    }
    target_mod["cases"].append(new_case)

    cases_data["modules"] = modules
    record.cases_data = cases_data
    record.case_count = sum(len(m.get("cases", [])) for m in modules)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(record, "cases_data")
    await db.commit()
    await db.refresh(record)

    return AICaseFileResponse(
        id=record.id,
        task_name=record.task_name,
        case_count=record.case_count,
        has_md=bool(record.md_path),
        has_xmind=bool(record.xmind_path),
        modules=(record.cases_data or {}).get("modules", []),
        created_at=record.created_at.isoformat() if record.created_at else "",
        doc_hash=record.doc_hash,
        parent_id=record.parent_id,
        diff_summary=record.diff_summary,
        record_status=getattr(record, "record_status", "active") or "active",
    )


@router.put("/ai-cases/{record_id}/cases/{case_id}", response_model=AICaseFileResponse)
async def update_ai_case_item(record_id: int, case_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    """更新 AI 用例记录中的单条用例，支持跨模块移动。"""
    from sqlalchemy import select
    from tools.database import AICaseFile

    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    cases_data = dict(record.cases_data or {})
    modules = list(cases_data.get("modules", []))

    # 找到用例所在模块和位置
    found_mod_idx = found_case_idx = None
    for mi, mod in enumerate(modules):
        for ci, case in enumerate(mod.get("cases", [])):
            if case.get("id") == case_id:
                found_mod_idx, found_case_idx = mi, ci
                break
        if found_mod_idx is not None:
            break

    if found_mod_idx is None:
        raise HTTPException(status_code=404, detail=f"用例 {case_id} 不存在")

    # 更新用例字段
    updated_case = dict(modules[found_mod_idx]["cases"][found_case_idx])
    for field in ("name", "priority", "type", "test_method", "preconditions", "steps", "expected"):
        if field in data:
            updated_case[field] = data[field]

    new_module = (data.get("module") or "").strip()
    current_module = modules[found_mod_idx]["name"]

    if new_module and new_module != current_module:
        # 从原模块移除
        modules[found_mod_idx]["cases"].pop(found_case_idx)
        # 找到或创建目标模块
        target_mod = next((m for m in modules if m["name"] == new_module), None)
        if target_mod is None:
            target_mod = {"name": new_module, "cases": []}
            modules.append(target_mod)
        target_mod["cases"].append(updated_case)
        # 移除空模块
        modules = [m for m in modules if m.get("cases")]
    else:
        modules[found_mod_idx]["cases"][found_case_idx] = updated_case

    cases_data["modules"] = modules
    record.cases_data = cases_data
    record.case_count = sum(len(m.get("cases", [])) for m in modules)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(record, "cases_data")
    await db.commit()
    await db.refresh(record)

    return AICaseFileResponse(
        id=record.id,
        task_name=record.task_name,
        case_count=record.case_count,
        has_md=bool(record.md_path),
        has_xmind=bool(record.xmind_path),
        modules=(record.cases_data or {}).get("modules", []),
        created_at=record.created_at.isoformat() if record.created_at else "",
        doc_hash=record.doc_hash,
        parent_id=record.parent_id,
        diff_summary=record.diff_summary,
        record_status=getattr(record, "record_status", "active") or "active",
    )


@router.delete("/ai-cases/{record_id}/cases/{case_id}", response_model=AICaseFileResponse)
async def delete_ai_case_item(record_id: int, case_id: str, db: AsyncSession = Depends(get_db)):
    """删除 AI 用例记录中的单条用例。"""
    from sqlalchemy import select
    from tools.database import AICaseFile

    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    cases_data = dict(record.cases_data or {})
    modules = list(cases_data.get("modules", []))

    found = False
    for mod in modules:
        for i, case in enumerate(mod.get("cases", [])):
            if case.get("id") == case_id:
                mod["cases"].pop(i)
                found = True
                break
        if found:
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"用例 {case_id} 不存在")

    # 移除空模块
    modules = [m for m in modules if m.get("cases")]
    cases_data["modules"] = modules
    record.cases_data = cases_data
    record.case_count = sum(len(m.get("cases", [])) for m in modules)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(record, "cases_data")
    await db.commit()
    await db.refresh(record)

    return AICaseFileResponse(
        id=record.id,
        task_name=record.task_name,
        case_count=record.case_count,
        has_md=bool(record.md_path),
        has_xmind=bool(record.xmind_path),
        modules=(record.cases_data or {}).get("modules", []),
        created_at=record.created_at.isoformat() if record.created_at else "",
        doc_hash=record.doc_hash,
        parent_id=record.parent_id,
        diff_summary=record.diff_summary,
        record_status=getattr(record, "record_status", "active") or "active",
    )


@router.delete("/ai-cases/{record_id}")
async def delete_ai_case(record_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, delete as sql_delete
    from tools.database import AICaseFile

    result = await db.execute(
        select(AICaseFile).where(AICaseFile.id == record_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    # 删除磁盘文件
    for path_str in [record.md_path, record.xmind_path]:
        if path_str:
            p = Path(path_str)
            if not p.is_absolute():
                p = Path(__file__).parent.parent / path_str
            if p.exists():
                p.unlink(missing_ok=True)

    await db.execute(sql_delete(AICaseFile).where(AICaseFile.id == record_id))
    await db.commit()
    return {"message": "删除成功"}


# ─────────────────────────────────────────────────────────────────────────────
# AI 用例 — 文档变更检测与 Diff 分析
# ─────────────────────────────────────────────────────────────────────────────

class DiffCheckRequest(_BaseModel):
    new_content: _Optional[str] = None      # 直接粘贴的新文档文本
    new_document_path: _Optional[str] = None  # 已上传的新文档路径


@router.post("/ai-cases/{record_id}/diff-check")
async def diff_check_ai_case(
    record_id: int,
    request: DiffCheckRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    对比新旧需求文档，返回变更摘要（不修改数据库，只分析）。

    前端上传新文档后先调此接口展示变更预览，
    用户确认后再调 /ai-cases/{id}/incremental-update 执行增量更新。

    返回：
    {
        "has_change": true,
        "new_doc_hash": "abc123",
        "old_doc_hash": "def456",
        "diff": {
            "changed": [...],
            "added": [...],
            "removed": [...],
            "unchanged": [...],
            "impact_level": "high",
            "diff_summary": "..."
        }
    }
    """
    from sqlalchemy import select
    from tools.database import AICaseFile
    from skills.ai_case_generator import ai_case_generator

    # ── 1. 取旧记录 ──────────────────────────────────────────────────────
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    # ── 2. 取新文档内容 ──────────────────────────────────────────────────
    if not request.new_content and not request.new_document_path:
        raise HTTPException(status_code=400, detail="请提供新版文档路径或文本内容")

    if request.new_document_path:
        try:
            from tools.document_parser import document_parser
            parsed = await document_parser.parse(request.new_document_path)
            new_content = parsed.get("content", "")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"新文档解析失败: {e}")
    else:
        new_content = request.new_content or ""

    if not new_content.strip():
        raise HTTPException(status_code=400, detail="新文档内容为空")

    # ── 3. 哈希快速判断是否有变更 ─────────────────────────────────────────
    new_doc_hash = ai_case_generator._compute_doc_hash(new_content)
    old_doc_hash = record.doc_hash or ""

    if old_doc_hash and new_doc_hash == old_doc_hash:
        return {
            "has_change": False,
            "new_doc_hash": new_doc_hash,
            "old_doc_hash": old_doc_hash,
            "diff": None,
            "message": "文档内容未发生变化，无需更新用例",
        }

    # ── 4. 有变更：调 AI 做 Diff 分析 ────────────────────────────────────
    old_content = record.doc_content or ""
    if not old_content:
        return {
            "has_change": True,
            "new_doc_hash": new_doc_hash,
            "old_doc_hash": old_doc_hash,
            "diff": None,
            "message": "旧版文档内容未保存，无法做精确 Diff，可直接重新生成",
        }

    # 从旧用例数据中提取实际模块名，传给 Diff 分析做强约束
    existing_module_names = [
        m.get("name", "") for m in (record.cases_data or {}).get("modules", [])
        if m.get("name") and "废弃" not in m.get("name", "")
    ]

    try:
        diff_result = await ai_case_generator.analyze_document_diff(
            old_doc_content=old_content,
            new_doc_content=new_content,
            existing_module_names=existing_module_names,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "has_change": True,
        "new_doc_hash": new_doc_hash,
        "old_doc_hash": old_doc_hash,
        "diff": diff_result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# AI 用例 — 增量更新（文档变更后只重生成 changed/added 模块）
# ─────────────────────────────────────────────────────────────────────────────

class IncrementalUpdateRequest(_BaseModel):
    new_content: _Optional[str] = None          # 新文档文本（与 new_document_path 二选一）
    new_document_path: _Optional[str] = None    # 已上传的新文档路径
    diff: _Optional[_Dict[str, _Any]] = None    # 前端传回 diff-check 的结果，省略则重新分析


@router.post("/ai-cases/{record_id}/incremental-update", response_model=AICaseFileResponse)
async def incremental_update_ai_case(
    record_id: int,
    request: IncrementalUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    文档变更后的增量更新：
    1. 如果 request.diff 已由前端 diff-check 获取，直接用；否则重新分析
    2. 只对 changed/added 模块重新调用 LLM 生成用例
    3. unchanged 模块保留旧用例，removed 模块打 deprecated 标记
    4. 旧记录标记为 deprecated，新记录 parent_id 指向旧记录
    """
    from sqlalchemy import select
    from tools.database import AICaseFile
    from skills.ai_case_generator import ai_case_generator
    from api.websocket_manager import ws_manager

    # ── 1. 取旧记录 ──────────────────────────────────────────────────────
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    old_record = result.scalar_one_or_none()
    if not old_record:
        raise HTTPException(status_code=404, detail="记录不存在")

    # ── 2. 取新文档内容 ──────────────────────────────────────────────────
    if not request.new_content and not request.new_document_path:
        raise HTTPException(status_code=400, detail="请提供新版文档路径或文本内容")

    if request.new_document_path:
        try:
            from tools.document_parser import document_parser
            parsed = await document_parser.parse(request.new_document_path)
            new_content = parsed.get("content", "")
            # 解析完删除临时文件
            from pathlib import Path as _Path
            p = _Path(request.new_document_path)
            if "uploads" in p.parts and "documents" in p.parts:
                p.unlink(missing_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"新文档解析失败: {e}")
    else:
        new_content = request.new_content or ""

    if not new_content.strip():
        raise HTTPException(status_code=400, detail="新文档内容为空")

    # ── 3. 获取 diff（复用前端已分析的结果，或重新分析） ─────────────────
    diff_result = request.diff

    # 从旧用例数据中提取实际模块名（无论是否重新分析都需要，用于后续名字校正）
    existing_module_names = [
        m.get("name", "") for m in (old_record.cases_data or {}).get("modules", [])
        if m.get("name") and "废弃" not in m.get("name", "")
    ]

    if not diff_result:
        old_content = old_record.doc_content or ""
        if not old_content:
            raise HTTPException(
                status_code=400,
                detail="旧版文档内容未保存，无法做精确 Diff。请直接重新生成（/ai-cases/generate）。"
            )
        try:
            diff_result = await ai_case_generator.analyze_document_diff(
                old_doc_content=old_content,
                new_doc_content=new_content,
                existing_module_names=existing_module_names,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── 4. 判断是否实际有变更 ─────────────────────────────────────────────
    has_changes = bool(diff_result.get("changed") or diff_result.get("added") or diff_result.get("removed"))
    if not has_changes:
        raise HTTPException(status_code=400, detail="Diff 分析未发现任何模块变更，无需更新")

    # ── 5. WebSocket 进度回调 ─────────────────────────────────────────────
    async def _progress(pct: int, stage: str):
        await ws_manager.broadcast(
            {"type": "ai_gen_progress", "percent": pct, "stage": stage},
            client_id="ai_gen",
        )

    # ── 6. 执行增量更新 ───────────────────────────────────────────────────
    formats = []
    if old_record.md_path:
        formats.append("md")
    if old_record.xmind_path:
        formats.append("xmind")
    if not formats:
        formats = ["md", "xmind"]

    try:
        upd_result = await ai_case_generator.incremental_update(
            task_name      = old_record.task_name,
            old_cases_data = old_record.cases_data or {},
            new_doc_content= new_content,
            diff_result    = diff_result,
            formats        = formats,
            progress_cb    = _progress,
        )
    except RuntimeError as e:
        await ws_manager.broadcast(
            {"type": "ai_gen_progress", "percent": 0, "stage": f"增量更新失败: {e}", "error": True},
            client_id="ai_gen",
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("增量更新失败: {}", repr(e))
        raise HTTPException(status_code=500, detail=f"增量更新失败: {type(e).__name__}: {e}")

    # ── 7. 旧记录标记为 deprecated ────────────────────────────────────────
    old_record.record_status = "deprecated"
    await db.flush()

    # ── 8. 创建新记录，parent_id 指向旧记录 ──────────────────────────────
    new_record = AICaseFile(
        task_name     = old_record.task_name,
        case_count    = upd_result.get("case_count", 0),
        md_path       = upd_result["files"].get("md"),
        xmind_path    = upd_result["files"].get("xmind"),
        cases_data    = upd_result.get("cases_data"),
        doc_hash      = upd_result.get("doc_hash"),
        doc_content   = upd_result.get("doc_content"),
        parent_id     = old_record.id,
        diff_summary  = upd_result.get("diff_summary"),
        record_status = "active",
    )
    db.add(new_record)
    await db.commit()
    await db.refresh(new_record)

    # RAG：新文档重建索引（后台异步，用新 record_id）
    if new_content:
        import asyncio as _asyncio
        from skills.rag import index_document as _index_doc
        _asyncio.create_task(_index_doc(new_record.id, "ai_case", new_content))

    logger.info(
        f"增量更新完成: 旧记录 #{old_record.id} → 新记录 #{new_record.id}，"
        f"用例 {new_record.case_count} 条，摘要: {new_record.diff_summary}"
    )
    return _ai_case_response(new_record)


# ─────────────────────────────────────────────
# 接口自动化 — 调试端点（测试 claude 子进程）
# ─────────────────────────────────────────────

@router.get("/api-test/debug/claude")
async def debug_claude_subprocess():
    """直接在请求上下文中测试 claude subprocess，用于排查 background task 问题。"""
    import asyncio, subprocess, shutil, os
    claude_bin = shutil.which("claude") or shutil.which("claude.cmd")
    if not claude_bin:
        npm_bin = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm")
        for name in ("claude.cmd", "claude"):
            c = os.path.join(npm_bin, name)
            if os.path.exists(c): claude_bin = c; break
    if not claude_bin:
        return {"error": "claude not found"}

    def _run():
        try:
            r = subprocess.run(
                [claude_bin, "--output-format", "text", "--no-session-persistence",
                 "--input-format", "text", "--system-prompt", "output JSON only", "-p"],
                input=b'output [{"test":1}]',
                capture_output=True, timeout=60, env=os.environ.copy()
            )
            return {"rc": r.returncode, "out": r.stdout.decode("utf-8", errors="replace")[:300],
                    "err": r.stderr.decode("utf-8", errors="replace")[:200]}
        except subprocess.TimeoutExpired:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": str(e)}

    result = await asyncio.to_thread(_run)
    return result


# ─────────────────────────────────────────────
# 接口自动化 — 项目管理
# ─────────────────────────────────────────────

@router.post("/api-test/projects")
async def create_api_project(data: dict, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    proj = ApiProject(
        name=data.get("name", "未命名项目"),
        base_url=data.get("base_url", ""),
        description=data.get("description", ""),
        auth_type=data.get("auth_type", "none"),
        auth_config=data.get("auth_config"),
        global_headers=data.get("global_headers"),
        proxy_url=data.get("proxy_url", ""),
        hosts_map=data.get("hosts_map", ""),
    )
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return _proj_dict(proj)


@router.get("/api-test/projects")
async def list_api_projects(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(ApiProject).order_by(ApiProject.created_at.desc()))
    return [_proj_dict(p) for p in result.scalars().all()]


@router.get("/api-test/all-cases")
async def list_all_cases_grouped(db: AsyncSession = Depends(get_db)):
    """返回所有项目及其用例，供前置用例选择器和测试计划步骤选择使用。"""
    from sqlalchemy import select
    projects = (await db.execute(
        select(ApiProject).order_by(ApiProject.created_at.desc())
    )).scalars().all()
    result = []
    for p in projects:
        cases = (await db.execute(
            select(ApiCase).where(ApiCase.project_id == p.id).order_by(ApiCase.created_at)
        )).scalars().all()
        result.append({
            "project_id": p.id,
            "project_name": p.name,
            "cases": [_case_dict(c) for c in cases],
        })
    return result


@router.put("/api-test/projects/{project_id}")
async def update_api_project(project_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    for field in ("name", "base_url", "description", "auth_type", "auth_config", "global_headers",
                  "setup_cases", "auth_error_patterns", "proxy_url", "hosts_map"):
        if field in data:
            setattr(proj, field, data[field])
    await db.commit()
    await db.refresh(proj)
    return _proj_dict(proj)


@router.delete("/api-test/projects/{project_id}")
async def delete_api_project(project_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, delete as sql_del
    await db.execute(sql_del(ApiCase).where(ApiCase.project_id == project_id))
    await db.execute(sql_del(ApiLoadConfig).where(ApiLoadConfig.project_id == project_id))
    await db.execute(sql_del(ApiTestReport).where(ApiTestReport.project_id == project_id))
    await db.execute(sql_del(ApiProject).where(ApiProject.id == project_id))
    await db.commit()
    return {"message": "删除成功"}


def _proj_dict(p: ApiProject) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "base_url": p.base_url,
        "description": p.description,
        "auth_type": p.auth_type,
        "auth_config": p.auth_config,
        "global_headers": p.global_headers,
        "setup_cases": p.setup_cases or [],
        "auth_error_patterns": p.auth_error_patterns or [],
        "proxy_url": p.proxy_url or "",
        "hosts_map": p.hosts_map or "",
        "created_at": p.created_at.isoformat() if p.created_at else "",
    }


# ─────────────────────────────────────────────
# 接口自动化 — 用例管理
# ─────────────────────────────────────────────

@router.get("/api-test/projects/{project_id}/cases")
async def list_api_cases(project_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(
        select(ApiCase).where(ApiCase.project_id == project_id).order_by(ApiCase.created_at)
    )
    return [_case_dict(c) for c in result.scalars().all()]


@router.post("/api-test/cases")
async def create_api_case(data: dict, db: AsyncSession = Depends(get_db)):
    case = ApiCase(
        project_id=data["project_id"],
        name=data.get("name", "未命名用例"),
        module=data.get("module", "通用"),
        method=data.get("method", "GET"),
        path=data.get("path", "/"),
        headers=data.get("headers"),
        params=data.get("params"),
        body=data.get("body"),
        assertions=data.get("assertions"),
        var_extracts=data.get("var_extracts"),
        priority=data.get("priority", "P1"),
        enabled=data.get("enabled", True),
        body_type=data.get("body_type", "json"),
        body_raw=data.get("body_raw"),
        description=data.get("description", ""),
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return _case_dict(case)


@router.put("/api-test/cases/{case_id}")
async def update_api_case(case_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(ApiCase).where(ApiCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    for field in ("name", "module", "method", "path", "headers", "params", "body", "body_type", "body_raw", "assertions", "var_extracts", "priority", "enabled", "description"):
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


def _case_dict(c: ApiCase) -> dict:
    return {
        "id": c.id,
        "project_id": c.project_id,
        "name": c.name,
        "module": c.module,
        "method": c.method,
        "path": c.path,
        "headers": c.headers,
        "params": c.params,
        "body_type": c.body_type or "json",
        "body": c.body,
        "body_raw": c.body_raw or "",
        "assertions": c.assertions,
        "var_extracts": c.var_extracts or [],
        "priority": c.priority,
        "enabled": c.enabled,
        "description": c.description or "",
        "created_at": c.created_at.isoformat() if c.created_at else "",
    }


# ─────────────────────────────────────────────
# 接口自动化 — AI 生成用例
# ─────────────────────────────────────────────

@router.post("/api-test/projects/{project_id}/cases/generate")
async def generate_api_cases(
    project_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    swagger_text = data.get("swagger_text", "")
    description = data.get("description", "")

    async def _bg():
        from skills.api_case_generator import api_case_generator
        from tools.database import async_session_maker

        async def progress_cb(pct, stage):
            await ws_manager.broadcast(
                {"type": "api_gen_progress", "percent": pct, "stage": stage},
                client_id="api_gen",
            )

        try:
            project_dict = {
                "base_url": proj.base_url,
                "auth_type": proj.auth_type or "none",
                "auth_config": proj.auth_config or {},
                "global_headers": proj.global_headers or {},
            }
            cases = await api_case_generator.generate_cases(
                base_url=proj.base_url,
                swagger_text=swagger_text,
                description=description,
                progress_cb=progress_cb,
                project=project_dict,
            )
            async with async_session_maker() as s:
                for c in cases:
                    s.add(ApiCase(
                        project_id=project_id,
                        name=c.get("name", ""),
                        module=c.get("module", "通用"),
                        method=c.get("method", "GET"),
                        path=c.get("path", "/"),
                        headers=c.get("headers"),
                        params=c.get("params"),
                        body=c.get("body"),
                        body_type=c.get("body_type", "json"),
                        body_raw=c.get("body_raw"),
                        assertions=c.get("assertions"),
                        var_extracts=c.get("var_extracts"),
                        priority=c.get("priority", "P1"),
                        description=c.get("description", ""),
                        enabled=True,
                    ))
                await s.commit()
            await ws_manager.broadcast(
                {"type": "api_gen_done", "count": len(cases)}, client_id="api_gen"
            )
        except Exception as e:
            logger.error(f"API case generation failed: {e}", exc_info=True)
            await ws_manager.broadcast(
                {"type": "api_gen_error", "message": str(e)}, client_id="api_gen"
            )

    background_tasks.add_task(_bg)
    return {"message": "AI生成任务已启动，请通过 WebSocket 接收进度", "project_id": project_id}


# ─────────────────────────────────────────────────────────────────────────────
# 接口代码分析 — 从代码直接生成用例
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api-test/projects/{project_id}/cases/generate-from-code")
async def generate_cases_from_code(
    project_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    从接口实现代码直接生成测试用例。
    body: { code: str, lang: str }
    后台执行，WebSocket client_id=api_gen 推送进度。
    """
    from sqlalchemy import select
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    code = (data.get("code") or "").strip()
    lang = data.get("lang", "python")
    if not code:
        raise HTTPException(status_code=400, detail="请提供接口代码")

    async def _bg():
        from skills.api_case_generator import api_code_analyzer
        from tools.database import async_session_maker

        async def progress_cb(pct, stage):
            await ws_manager.broadcast(
                {"type": "api_gen_progress", "percent": pct, "stage": stage},
                client_id="api_gen",
            )

        try:
            cases = await api_code_analyzer.generate_from_code(
                code=code,
                lang=lang,
                base_url=proj.base_url or "",
                progress_cb=progress_cb,
            )
            async with async_session_maker() as s:
                for c in cases:
                    s.add(ApiCase(
                        project_id=project_id,
                        name=c.get("name", ""),
                        module=c.get("module", "代码分析"),
                        method=c.get("method", "POST"),
                        path=c.get("path", "/"),
                        headers=c.get("headers") or {},
                        params=c.get("params") or {},
                        body=c.get("body"),
                        assertions=c.get("assertions"),
                        var_extracts=c.get("var_extracts"),
                        priority=c.get("priority", "P1"),
                        description=c.get("description", ""),
                        enabled=True,
                    ))
                await s.commit()
            await ws_manager.broadcast(
                {"type": "api_gen_done", "count": len(cases)}, client_id="api_gen"
            )
        except Exception as e:
            logger.error(f"代码用例生成失败: {e}", exc_info=True)
            await ws_manager.broadcast(
                {"type": "api_gen_error", "message": str(e)}, client_id="api_gen"
            )

    background_tasks.add_task(_bg)
    return {"message": "代码分析任务已启动", "project_id": project_id}


# ─────────────────────────────────────────────────────────────────────────────
# 接口代码分析 — 需求文档 vs 代码 差异对比
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api-test/projects/{project_id}/code-analyze")
async def analyze_code_vs_requirement(
    project_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    对比需求文档和接口代码，返回差异分析报告（同步，前端等待结果）。
    body: { requirement: str, code: str, lang: str }
    """
    from sqlalchemy import select
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    requirement = (data.get("requirement") or "").strip()
    code        = (data.get("code") or "").strip()
    lang        = data.get("lang", "python")

    if not code:
        raise HTTPException(status_code=400, detail="请提供接口代码")
    if not requirement:
        raise HTTPException(status_code=400, detail="请提供需求文档或功能描述")

    from skills.api_case_generator import api_code_analyzer

    try:
        report = await api_code_analyzer.analyze_vs_requirement(
            requirement=requirement,
            code=code,
            lang=lang,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("代码可行性分析失败: {}", repr(e))
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")

    return report


# ─────────────────────────────────────────────────────────────────────────────
# 接口代码分析 — 将差异分析报告中的 auto_cases 写入项目用例库
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api-test/projects/{project_id}/code-analyze/save-cases")
async def save_analyze_cases(
    project_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    将代码可行性分析结果中的 auto_cases 写入项目用例库。
    body: { cases: [...] }
    """
    from sqlalchemy import select
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    cases = data.get("cases", [])
    if not cases:
        raise HTTPException(status_code=400, detail="没有可保存的用例")

    saved = 0
    for c in cases:
        db.add(ApiCase(
            project_id=project_id,
            name=c.get("name", "差异验证用例"),
            module=c.get("module", "差异验证"),
            method=c.get("method", "POST"),
            path=c.get("path", "/"),
            headers=c.get("headers") or {},
            params=c.get("params") or {},
            body=c.get("body"),
            assertions=c.get("assertions") or [{"type": "status_code", "expected": 200}],
            var_extracts=c.get("var_extracts"),
            priority=c.get("priority", "P1"),
            description=c.get("description", ""),
            enabled=True,
        ))
        saved += 1

    await db.commit()
    logger.info(f"保存差异验证用例: {saved} 条 → project_id={project_id}")
    return {"message": f"已保存 {saved} 条差异验证用例", "saved": saved}


# ─────────────────────────────────────────────
# 内置函数列表
# ─────────────────────────────────────────────

@router.get("/api-test/builtin-functions")
async def list_builtin_functions():
    from skills.param_resolver import BUILTIN_FUNCTIONS
    return BUILTIN_FUNCTIONS


# ─────────────────────────────────────────────
# 自定义脚本函数 CRUD
# ─────────────────────────────────────────────

@router.get("/api-test/scripts")
async def list_scripts(project_id: int = None, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, or_
    stmt = select(CustomScript).order_by(CustomScript.id)
    if project_id is not None:
        stmt = stmt.where(or_(CustomScript.project_id == project_id, CustomScript.project_id == None))
    result = await db.execute(stmt)
    return [_script_dict(s) for s in result.scalars()]


@router.post("/api-test/scripts")
async def create_script(data: dict, db: AsyncSession = Depends(get_db)):
    s = CustomScript(
        project_id=data.get("project_id"),
        name=data.get("name", "my_func"),
        description=data.get("description", ""),
        code=data.get("code", ""),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return _script_dict(s)


# ── 静态子路由必须在 {script_id} 动态路由之前，否则 FastAPI 会把 "test"/"ai-generate" 当成 id ──

@router.post("/api-test/scripts/test")
async def test_script(data: dict):
    """立即执行脚本，返回结果或错误，用于编辑器预览。"""
    from skills.param_resolver import _exec_custom_fn
    name = data.get("name", "test_fn")
    code = data.get("code", "")
    args_str = data.get("args", "")
    script = {"name": name, "code": code}
    result = _exec_custom_fn(name, args_str, [script])
    if result is None:
        return {"ok": False, "error": "脚本执行失败：未定义同名函数或 result 变量"}
    return {"ok": True, "result": result}


@router.post("/api-test/scripts/ai-generate")
async def ai_generate_script(data: dict):
    """用自然语言描述，调用 LLM 生成 Python 脚本函数。"""
    import httpx
    from tools.config import settings

    prompt = (data.get("prompt") or "").strip()
    func_name = (data.get("func_name") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    api_key  = settings.AI_API_KEY
    base_url = (settings.AI_API_URL or "").rstrip("/")
    model    = settings.AI_MODEL or "deepseek-v4-flash"
    temperature = float(getattr(settings, "AI_TEMPERATURE", 0.3))

    if not api_key:
        raise HTTPException(status_code=400, detail="未配置 AI API Key，请先在 LLM 配置页面填写")

    available_modules = "hashlib, json, time, random, string, uuid, base64, os, re, requests"
    system_prompt = f"""你是一个资深 Python 工程师，专门为 API 接口测试框架编写参数生成脚本。

## 执行环境约束
- 函数运行在沙箱中，可用模块：{available_modules}
- 函数接收可变参数 `*args`，调用时按顺序传入
- 函数必须有返回值（return），返回值会被 str() 转换后注入到接口参数
- 禁止使用文件 IO、系统调用等危险操作

## 代码规范
1. 定义一个与描述匹配的函数，函数名：{func_name if func_name else '根据功能自行命名（小写下划线风格）'}
2. 所有 import 写在函数内部
3. 只输出纯 Python 代码，不要加 markdown 代码块标记
4. 不要输出任何解释说明，只输出代码本身"""

    user_msg = f"请生成以下功能的 Python 脚本函数：\n\n{prompt}"

    # 判断是 Anthropic 还是 OpenAI 兼容接口
    is_anthropic = "anthropic.com" in base_url or model.startswith("claude")

    try:
        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
            if is_anthropic:
                resp = await client.post(
                    f"{base_url}/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": 1024,
                        "temperature": temperature,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_msg}],
                    },
                )
            else:
                resp = await client.post(
                    f"{base_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": 1024,
                        "temperature": temperature,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_msg},
                        ],
                    },
                )

        if resp.status_code != 200:
            err = resp.text[:300]
            logger.error(f"AI 生成脚本失败，HTTP {resp.status_code}: {err}")
            raise HTTPException(status_code=500, detail=f"AI 接口返回错误 {resp.status_code}：{err}")

        body = resp.json()
        if is_anthropic:
            code = body["content"][0]["text"].strip()
        else:
            code = body["choices"][0]["message"]["content"].strip()

        # 去掉模型可能输出的 markdown 代码块标记
        if code.startswith("```"):
            lines = code.splitlines()
            start = 1 if lines[0].startswith("```") else 0
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            code = "\n".join(lines[start:end]).strip()

        # 从代码中提取第一个 def 的函数名
        import re as _re
        parsed_name = ""
        m = _re.search(r"^def\s+(\w+)\s*\(", code, _re.MULTILINE)
        if m:
            parsed_name = m.group(1)

        # 函数名优先级：代码里解析 > 用户传入 > 默认
        final_name = parsed_name or func_name or "custom_func"

        # 描述：截取 prompt 前 60 字作为简洁描述
        description = prompt[:60].rstrip("，。,.") if prompt else ""

        return {"ok": True, "code": code, "func_name": final_name, "description": description}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI 生成脚本失败: {e}")
        raise HTTPException(status_code=500, detail=f"AI 生成失败：{str(e)}")


@router.put("/api-test/scripts/{script_id}")
async def update_script(script_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
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
    from sqlalchemy import select
    result = await db.execute(select(CustomScript).where(CustomScript.id == script_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="脚本不存在")
    await db.delete(s)
    await db.commit()
    return {"message": "已删除"}


def _script_dict(s: CustomScript) -> dict:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "name": s.name,
        "description": s.description,
        "code": s.code,
        "created_at": s.created_at.isoformat() if s.created_at else "",
    }


# ─────────────────────────────────────────────
# 接口自动化 — 单测执行
# ─────────────────────────────────────────────

@router.post("/api-test/projects/{project_id}/execute")
async def execute_api_cases(
    project_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    proj_r = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = proj_r.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    case_ids = data.get("case_ids")

    async def _bg():
        from skills.api_executor import api_executor
        from tools.database import async_session_maker
        from sqlalchemy import select as sel

        async with async_session_maker() as s:
            q = sel(ApiCase).where(ApiCase.project_id == project_id)
            if case_ids:
                q = q.where(ApiCase.id.in_(case_ids))
            cases = (await s.execute(q)).scalars().all()
            cases = [_case_dict(c) for c in cases]

            # 加载当前项目的自定义脚本
            from sqlalchemy import or_ as _or
            sq = sel(CustomScript).where(
                _or(CustomScript.project_id == project_id, CustomScript.project_id == None)
            )
            custom_scripts = [_script_dict(sc) for sc in (await s.execute(sq)).scalars()]

        async def progress_cb(p):
            await ws_manager.broadcast(
                {"type": "api_exec_progress", **p}, client_id="api_exec"
            )

        proj_dict = _proj_dict(proj)
        summary = await api_executor.execute_cases(proj_dict, cases, progress_cb, custom_scripts=custom_scripts)

        async with async_session_maker() as s:
            report = ApiTestReport(
                project_id=project_id,
                project_name=proj.name,
                report_type="unit",
                total=summary["total"],
                passed=summary["passed"],
                failed=summary["failed"],
                summary={"pass_rate": summary["pass_rate"]},
                details=summary["results"],
            )
            s.add(report)
            await s.commit()
            await s.refresh(report)

        await ws_manager.broadcast(
            {"type": "api_exec_done", "report_id": report.id, **summary},
            client_id="api_exec",
        )

    background_tasks.add_task(_bg)
    return {"message": "执行任务已启动", "project_id": project_id}


# ─────────────────────────────────────────────
# 接口自动化 — 压力测试
# ─────────────────────────────────────────────

@router.post("/api-test/projects/{project_id}/load")
async def run_load_test(
    project_id: int,
    data: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    proj_r = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = proj_r.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    config = {
        "concurrent_users": data.get("concurrent_users", 10),
        "duration": data.get("duration", 60),
        "ramp_up": data.get("ramp_up", 10),
    }
    case_ids = data.get("case_ids")  # None = 全部启用的用例

    async def _bg():
        from skills.api_load_tester import api_load_tester
        from tools.database import async_session_maker
        from sqlalchemy import select as sel

        async with async_session_maker() as s:
            q = sel(ApiCase).where(ApiCase.project_id == project_id, ApiCase.enabled == True)
            if case_ids:
                q = q.where(ApiCase.id.in_(case_ids))
            cases = (await s.execute(q)).scalars().all()
            cases = [_case_dict(c) for c in cases]

        async def metrics_cb(m):
            await ws_manager.broadcast(
                {"type": "load_metrics", **m}, client_id="api_load"
            )

        proj_dict = _proj_dict(proj)
        summary = await api_load_tester.run(proj_dict, cases, config, metrics_cb)

        async with async_session_maker() as s:
            report = ApiTestReport(
                project_id=project_id,
                project_name=proj.name,
                report_type="load",
                total=summary.get("total_requests", 0),
                passed=summary.get("passed", 0),
                failed=summary.get("failed", 0),
                summary=summary,
                details=cases,   # 保存压测的接口用例详情
            )
            s.add(report)
            await s.commit()
            await s.refresh(report)

        await ws_manager.broadcast(
            {"type": "load_done", "report_id": report.id, **summary},
            client_id="api_load",
        )

    background_tasks.add_task(_bg)
    return {"message": "压测任务已启动", "project_id": project_id}


@router.post("/api-test/load/stop")
async def stop_load_test():
    from skills.api_load_tester import api_load_tester
    api_load_tester.stop()
    return {"message": "停止信号已发送"}


# ─────────────────────────────────────────────
# 接口自动化 — 报告
# ─────────────────────────────────────────────

@router.get("/api-test/projects/{project_id}/reports")
async def list_api_reports(project_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(
        select(ApiTestReport)
        .where(ApiTestReport.project_id == project_id)
        .order_by(ApiTestReport.created_at.desc())
    )
    return [_report_dict(r) for r in result.scalars().all()]


@router.post("/api-test/reports/{report_id}/analyze")
async def analyze_api_report(report_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(ApiTestReport).where(ApiTestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    rdict = _report_dict(report)
    analysis = await _ai_analyze_report(rdict)

    # 持久化分析结果
    report.analysis = analysis
    await db.commit()

    return {"analysis": analysis}


async def _ai_analyze_report(report: dict) -> str:
    import httpx
    from tools.config import settings

    rtype = report.get("report_type", "unit")
    total = report.get("total", 0)
    passed = report.get("passed", 0)
    failed = report.get("failed", 0)
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
            + "请输出：\n1. 失败原因分析（每个失败用例或共同原因）\n2. 修复建议\n3. 测试质量总结"
        )
    else:
        summary = report.get("summary") or {}
        prompt = (
            f"以下是接口压力测试报告，请分析性能瓶颈并给出优化建议。\n\n"
            f"压测结果：总请求 {summary.get('total_requests')}, "
            f"成功率 {summary.get('success_rate')}%, "
            f"平均TPS {summary.get('avg_tps')}, "
            f"平均耗时 {summary.get('avg_ms')}ms, "
            f"P50 {summary.get('p50_ms')}ms, "
            f"P95 {summary.get('p95_ms')}ms, "
            f"P99 {summary.get('p99_ms')}ms, "
            f"最大耗时 {summary.get('max_ms')}ms\n\n"
            "请输出：\n1. 性能评估（吞吐量、延迟、错误率分析）\n2. 潜在瓶颈分析\n3. 优化建议"
        )

    api_key  = settings.AI_API_KEY
    base_url = (settings.AI_API_URL or "").rstrip("/")
    model    = settings.AI_MODEL or "deepseek-v4-flash"

    is_anthropic = "anthropic.com" in base_url or model.startswith("claude")

    if is_anthropic:
        url     = f"{base_url}/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 2048,
            "system": "你是一名资深测试工程师，擅长分析接口测试报告，给出精准、可操作的建议。用中文回答，使用 Markdown 格式输出，结构要求：用 ## 作为一级标题，### 作为二级标题，重点内容用 **加粗**，列表用 - 开头，不要使用 --- 分隔线，不要过度嵌套，保持简洁清晰。",
            "messages": [{"role": "user", "content": prompt}],
        }
    else:
        url     = f"{base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 2048,
            "messages": [
                {"role": "system", "content": "你是一名资深测试工程师，擅长分析接口测试报告，给出精准、可操作的建议。用中文回答，使用 Markdown 格式输出，结构要求：用 ## 作为一级标题，### 作为二级标题，重点内容用 **加粗**，列表用 - 开头，不要使用 --- 分隔线，不要过度嵌套，保持简洁清晰。"},
                {"role": "user",   "content": prompt},
            ],
        }

    async with httpx.AsyncClient(verify=False, timeout=60) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if is_anthropic:
        return data["content"][0]["text"]
    else:
        return data["choices"][0]["message"]["content"]


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
    from sqlalchemy import select, delete as sql_del
    result = await db.execute(select(ApiTestReport).where(ApiTestReport.id == report_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="报告不存在")
    await db.execute(sql_del(ApiTestReport).where(ApiTestReport.id == report_id))
    await db.commit()
    return {"message": "已删除"}


def _report_dict(r: ApiTestReport) -> dict:
    return {
        "id": r.id,
        "project_id": r.project_id,
        "project_name": r.project_name,
        "report_type": r.report_type,
        "total": r.total,
        "passed": r.passed,
        "failed": r.failed,
        "summary": r.summary,
        "details": r.details,
        "analysis": r.analysis or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


# ─────────────────────────────────────────────
# 全局变量池 CRUD
# ─────────────────────────────────────────────

def _gvar_dict(g: GlobalVariable) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "value": g.value or "",
        "description": g.description or "",
        "source_project": g.source_project or "",
        "updated_at": g.updated_at.isoformat() if g.updated_at else "",
    }


@router.get("/global-vars")
async def list_global_vars(db: AsyncSession = Depends(get_db)):
    """列出所有全局变量。"""
    from sqlalchemy import select
    result = await db.execute(select(GlobalVariable).order_by(GlobalVariable.name))
    return [_gvar_dict(g) for g in result.scalars().all()]


@router.post("/global-vars")
async def create_global_var(data: dict, db: AsyncSession = Depends(get_db)):
    """手动创建全局变量。"""
    from sqlalchemy import select
    from skills.param_resolver import set_global_var
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="变量名不能为空")
    # 检查重名
    exist = (await db.execute(select(GlobalVariable).where(GlobalVariable.name == name))).scalar_one_or_none()
    if exist:
        raise HTTPException(status_code=400, detail=f"变量 '{name}' 已存在，请使用 PUT 更新")
    g = GlobalVariable(
        name=name,
        value=data.get("value", ""),
        description=data.get("description", ""),
        source_project=data.get("source_project", "手动创建"),
    )
    db.add(g)
    await db.commit()
    await db.refresh(g)
    # 同步写内存缓存
    set_global_var(name, g.value or "", source_project=g.source_project)
    from skills.param_resolver import _gvar_dirty
    _gvar_dirty.discard(name)   # 刚写入 DB，标记为干净
    return _gvar_dict(g)


@router.put("/global-vars/{var_id}")
async def update_global_var(var_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    """更新全局变量。"""
    from sqlalchemy import select
    from skills.param_resolver import set_global_var, _gvar_dirty
    result = await db.execute(select(GlobalVariable).where(GlobalVariable.id == var_id))
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="变量不存在")
    for field in ("value", "description", "source_project"):
        if field in data:
            setattr(g, field, data[field])
    from datetime import datetime as _dt
    g.updated_at = _dt.utcnow()
    await db.commit()
    await db.refresh(g)
    set_global_var(g.name, g.value or "", source_project=g.source_project)
    _gvar_dirty.discard(g.name)
    return _gvar_dict(g)


@router.delete("/global-vars/{var_id}")
async def delete_global_var(var_id: int, db: AsyncSession = Depends(get_db)):
    """删除全局变量。"""
    from sqlalchemy import select
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


# ─────────────────────────────────────────────────────────────────────────────
# 测试计划（Test Plan）—— Week 3-4 Tier 3
# 顺序执行 api_cases + 共享变量上下文 + 步骤级报告
# ─────────────────────────────────────────────────────────────────────────────

def _plan_dict(p: TestPlan, steps: list = None) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description or "",
        "project_id": p.project_id,
        "status": p.status or "pending",
        "proxy_url": p.proxy_url or "",
        "hosts_map": p.hosts_map or "",
        "steps": steps or [],
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
    }


def _step_dict(s: TestPlanStep, case_name: str = "", module: str = "", project_name: str = "") -> dict:
    return {
        "id": s.id,
        "plan_id": s.plan_id,
        "case_id": s.case_id,
        "case_project_id": s.case_project_id,
        "case_name": case_name,
        "module": module,
        "project_name": project_name,
        "sort_order": s.sort_order,
        "enabled": s.enabled,
        "created_at": s.created_at.isoformat() if s.created_at else "",
    }


def _plan_report_dict(r: TestPlanReport) -> dict:
    return {
        "id": r.id,
        "plan_id": r.plan_id,
        "plan_name": r.plan_name or "",
        "total": r.total,
        "passed": r.passed,
        "failed": r.failed,
        "pass_rate": r.pass_rate,
        "details": r.details or [],
        "var_snapshot": r.var_snapshot or {},
        "analysis": r.analysis or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


# ── CRUD ────────────────────────────────────────────────────────────────────

@router.get("/test-plans")
async def list_test_plans(db: AsyncSession = Depends(get_db)):
    """列出所有测试计划（不包含步骤详情）。"""
    from sqlalchemy import select, func
    plans = (await db.execute(select(TestPlan).order_by(TestPlan.id.desc()))).scalars().all()
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
async def create_test_plan(data: dict, db: AsyncSession = Depends(get_db)):
    """新建测试计划。body: {name, description?, project_id?, steps: [{case_id, case_project_id, sort_order, enabled}]}"""
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="计划名称不能为空")
    plan = TestPlan(
        name=name,
        description=data.get("description", ""),
        project_id=data.get("project_id"),
        proxy_url=data.get("proxy_url", ""),
        hosts_map=data.get("hosts_map", ""),
        status="pending",
    )
    db.add(plan)
    await db.flush()   # 获取 plan.id

    steps_raw = data.get("steps") or []
    for idx, s in enumerate(steps_raw):
        step = TestPlanStep(
            plan_id=plan.id,
            case_id=s.get("case_id"),
            case_project_id=s.get("case_project_id"),
            sort_order=s.get("sort_order", idx),
            enabled=s.get("enabled", True),
        )
        db.add(step)

    await db.commit()
    await db.refresh(plan)
    return _plan_dict(plan)


@router.get("/test-plans/{plan_id}")
async def get_test_plan(plan_id: int, db: AsyncSession = Depends(get_db)):
    """获取计划详情，含步骤列表（包含用例名称）。"""
    from sqlalchemy import select
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    steps_rows = (await db.execute(
        select(TestPlanStep).where(TestPlanStep.plan_id == plan_id).order_by(TestPlanStep.sort_order)
    )).scalars().all()

    # 批量查 case 名称 + 项目名
    case_ids = [s.case_id for s in steps_rows]
    project_ids = list({s.case_project_id for s in steps_rows if s.case_project_id})
    cases_map, projects_map = {}, {}
    if case_ids:
        cases_map = {
            c.id: c for c in
            (await db.execute(select(ApiCase).where(ApiCase.id.in_(case_ids)))).scalars().all()
        }
    if project_ids:
        projects_map = {
            p.id: p for p in
            (await db.execute(select(ApiProject).where(ApiProject.id.in_(project_ids)))).scalars().all()
        }

    steps = [
        _step_dict(
            s,
            case_name=cases_map.get(s.case_id, type('', (), {'name': f'[用例#{s.case_id}]'})()).name,
            module=getattr(cases_map.get(s.case_id), 'module', '') or '',
            project_name=getattr(projects_map.get(s.case_project_id), 'name', '') or '',
        )
        for s in steps_rows
    ]
    return _plan_dict(plan, steps)


@router.put("/test-plans/{plan_id}")
async def update_test_plan(plan_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    """更新计划基本信息（name/description/project_id）。步骤用专门接口管理。"""
    from sqlalchemy import select
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    for field in ("name", "description", "project_id", "proxy_url", "hosts_map"):
        if field in data:
            setattr(plan, field, data[field])
    from datetime import datetime as _dt
    plan.updated_at = _dt.utcnow()
    await db.commit()
    await db.refresh(plan)
    return _plan_dict(plan)


@router.delete("/test-plans/{plan_id}")
async def delete_test_plan(plan_id: int, db: AsyncSession = Depends(get_db)):
    """删除计划及其步骤和报告。"""
    from sqlalchemy import select, delete as sql_delete
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    await db.execute(sql_delete(TestPlanStep).where(TestPlanStep.plan_id == plan_id))
    await db.execute(sql_delete(TestPlanReport).where(TestPlanReport.plan_id == plan_id))
    await db.delete(plan)
    await db.commit()
    return {"message": f"测试计划 '{plan.name}' 已删除"}


# ── 步骤管理 ────────────────────────────────────────────────────────────────

@router.post("/test-plans/{plan_id}/steps")
async def add_plan_steps(plan_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    """批量追加/重置步骤。body: {steps: [{case_id, case_project_id, sort_order, enabled}], replace: bool}"""
    from sqlalchemy import select, delete as sql_delete
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")

    if data.get("replace", False):
        await db.execute(sql_delete(TestPlanStep).where(TestPlanStep.plan_id == plan_id))

    for idx, s in enumerate(data.get("steps") or []):
        step = TestPlanStep(
            plan_id=plan_id,
            case_id=s.get("case_id"),
            case_project_id=s.get("case_project_id"),
            sort_order=s.get("sort_order", idx),
            enabled=s.get("enabled", True),
        )
        db.add(step)

    from datetime import datetime as _dt
    plan.updated_at = _dt.utcnow()
    await db.commit()
    return {"message": "步骤已保存"}


@router.delete("/test-plans/{plan_id}/steps/{step_id}")
async def delete_plan_step(plan_id: int, step_id: int, db: AsyncSession = Depends(get_db)):
    """删除单个步骤。"""
    from sqlalchemy import select
    s = (await db.execute(
        select(TestPlanStep).where(TestPlanStep.id == step_id, TestPlanStep.plan_id == plan_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="步骤不存在")
    await db.delete(s)
    await db.commit()
    return {"message": "步骤已删除"}


# ── 执行 ────────────────────────────────────────────────────────────────────

@router.post("/test-plans/{plan_id}/run")
async def run_test_plan(
    plan_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    force: bool = False,
):
    """异步执行测试计划。force=true 可强制重置 running 状态后重新执行。"""
    from sqlalchemy import select
    plan = (await db.execute(select(TestPlan).where(TestPlan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    if plan.status == "running" and not force:
        raise HTTPException(status_code=409, detail="计划正在执行中，如需强制重跑请传 force=true")

    plan.status = "running"
    from datetime import datetime as _dt
    plan.updated_at = _dt.utcnow()
    await db.commit()

    background_tasks.add_task(_execute_plan_bg, plan_id)
    return {"message": "测试计划已开始执行", "plan_id": plan_id}


async def _execute_plan_bg(plan_id: int):
    """后台执行测试计划：顺序执行 + 共享 var_store + 步骤级报告。"""
    import httpx
    from sqlalchemy import select, or_
    from skills.api_executor import ApiExecutor
    from skills.param_resolver import flush_global_vars
    from datetime import datetime as _dt
    from tools.database import async_session_maker as _session_maker

    executor = ApiExecutor()
    step_results = []
    var_store: dict = {}
    final_status = "failed"
    plan_name = ""
    report_id = None

    try:
        # ── 阶段1：加载数据，session 关闭前全部转换为纯 dict ───────────────
        steps_plain = []     # [{case_id, case_project_id, sort_order}]
        cases_plain = {}     # case_id -> case dict
        projects_plain = {}  # project_id -> project dict
        custom_scripts = []

        async with _session_maker() as db:
            plan = (await db.execute(
                select(TestPlan).where(TestPlan.id == plan_id)
            )).scalar_one_or_none()
            if not plan:
                logger.warning(f"[plan_exec] 计划 {plan_id} 不存在")
                return
            plan_name = plan.name
            plan_proxy_url = plan.proxy_url or ""
            plan_hosts_map_text = plan.hosts_map or ""

            steps_rows = (await db.execute(
                select(TestPlanStep)
                .where(TestPlanStep.plan_id == plan_id, TestPlanStep.enabled == True)
                .order_by(TestPlanStep.sort_order)
            )).scalars().all()

            if not steps_rows:
                plan.status = "passed"
                plan.updated_at = _dt.utcnow()
                await db.commit()
                await ws_manager.broadcast_all({
                    "type": "plan_done", "plan_id": plan_id,
                    "total": 0, "passed": 0, "failed": 0,
                    "pass_rate": 100, "status": "passed",
                })
                return

            # 转为纯 dict，避免 session 关闭后访问 detached 对象
            steps_plain = [
                {"case_id": s.case_id, "case_project_id": s.case_project_id, "sort_order": s.sort_order}
                for s in steps_rows
            ]

            project_ids = list({s["case_project_id"] for s in steps_plain if s["case_project_id"]})
            if project_ids:
                projs = (await db.execute(
                    select(ApiProject).where(ApiProject.id.in_(project_ids))
                )).scalars().all()
                projects_plain = {
                    p.id: {
                        "id": p.id, "name": p.name,
                        "base_url": p.base_url or "",
                        "auth_type": p.auth_type or "none",
                        "auth_config": p.auth_config or {},
                        "global_headers": p.global_headers or {},
                        "proxy_url": p.proxy_url or "",
                        "hosts_map": p.hosts_map or "",
                    }
                    for p in projs
                }

            case_ids = [s["case_id"] for s in steps_plain]
            cases_rows = (await db.execute(
                select(ApiCase).where(ApiCase.id.in_(case_ids))
            )).scalars().all()
            cases_plain = {c.id: ApiExecutor._case_to_dict(c) for c in cases_rows}

            # 按项目分别加载自定义脚本，避免同名函数在不同项目中覆盖
            # scripts_by_project[project_id] = [{name, code}, ...]，全局脚本合并进每个项目
            all_script_project_ids = list({s["case_project_id"] for s in steps_plain if s["case_project_id"]})
            if plan.project_id and plan.project_id not in all_script_project_ids:
                all_script_project_ids.append(plan.project_id)

            scripts_rows = (await db.execute(
                select(CustomScript).where(
                    or_(
                        CustomScript.project_id.in_(all_script_project_ids) if all_script_project_ids else False,
                        CustomScript.project_id == None,
                    )
                )
            )).scalars().all()

            global_scripts = [{"name": s.name, "code": s.code} for s in scripts_rows if s.project_id is None]
            # 每个项目的脚本 = 该项目专属脚本 + 全局脚本（同名时项目优先）
            scripts_by_project: dict = {}
            for s in scripts_rows:
                if s.project_id is None:
                    continue
                scripts_by_project.setdefault(s.project_id, []).append({"name": s.name, "code": s.code})
            for pid in all_script_project_ids:
                # 项目脚本在前（优先），全局脚本补充未覆盖的函数
                proj_scripts = scripts_by_project.get(pid, [])
                proj_names = {s["name"] for s in proj_scripts}
                scripts_by_project[pid] = proj_scripts + [s for s in global_scripts if s["name"] not in proj_names]

        # ── 阶段2：顺序执行 HTTP，共享 var_store ────────────────────────────
        total_steps = len(steps_plain)

        for idx, step in enumerate(steps_plain):
            case_dict = cases_plain.get(step["case_id"])
            if not case_dict:
                step_results.append({
                    "step": idx + 1,
                    "case_id": step["case_id"],
                    "case_name": f"[用例#{step['case_id']} 不存在]",
                    "status": "skipped",
                    "error": "用例不存在",
                    "duration_ms": 0,
                    "assertions": [],
                    "extracted_vars": {},
                    "response_preview": "",
                })
                continue

            proj = projects_plain.get(step["case_project_id"], {})
            base_url = (proj.get("base_url", "") or "").rstrip("/")
            auth_headers = executor.build_auth_headers(proj) if proj else {}
            global_headers = proj.get("global_headers") or {}
            project_name = proj.get("name", "")
            # 使用该步骤所属项目的脚本（项目脚本优先，全局脚本补充）
            step_scripts = scripts_by_project.get(step["case_project_id"], global_scripts)

            # 代理优先级：计划级 > 项目级
            effective_proxy = plan_proxy_url or proj.get("proxy_url", "")
            if effective_proxy and "://" not in effective_proxy:
                effective_proxy = "http://" + effective_proxy
            _proxy_kwargs = {"proxies": {"all://": effective_proxy}} if effective_proxy else {}

            # hosts 映射：项目级为基础，计划级覆盖同名条目
            from skills.api_executor import _parse_hosts_map, _make_transport
            _proj_hosts = _parse_hosts_map(proj.get("hosts_map") or "")
            _plan_hosts = _parse_hosts_map(plan_hosts_map_text)
            _hosts_map = {**_proj_hosts, **_plan_hosts}   # 计划条目优先
            _transport = _make_transport(_hosts_map, verify=False)

            await ws_manager.broadcast_all({
                "type": "plan_step_start",
                "plan_id": plan_id,
                "step": idx + 1,
                "total": total_steps,
                "case_name": case_dict.get("name", ""),
            })

            try:
                async with httpx.AsyncClient(transport=_transport, verify=False, timeout=30.0, **_proxy_kwargs) as client:
                    result = await executor._run_case(
                        client, base_url, case_dict,
                        auth_headers, global_headers,
                        var_store=var_store,
                        custom_scripts=step_scripts,
                        project_name=project_name,
                    )
            except Exception as step_err:
                result = {
                    "case_id": case_dict.get("id"),
                    "case_name": case_dict.get("name", ""),
                    "method": case_dict.get("method", ""),
                    "url": base_url + case_dict.get("path", ""),
                    "status_code": None,
                    "duration_ms": 0,
                    "status": "failed",
                    "assertions": [],
                    "error": str(step_err),
                    "extracted_vars": {},
                    "response_preview": "",
                }

            step_results.append({
                "step": idx + 1,
                "case_id": case_dict.get("id"),
                "case_name": case_dict.get("name", ""),
                "module": case_dict.get("module", ""),
                "project_name": project_name,
                "method": result.get("method", ""),
                "url": result.get("url", ""),
                "status_code": result.get("status_code"),
                "duration_ms": result.get("duration_ms", 0),
                "status": result.get("status", "failed"),
                "assertions": result.get("assertions", []),
                "error": result.get("error", ""),
                "extracted_vars": result.get("extracted_vars", {}),
                "response_preview": result.get("response_preview", ""),
            })

            await ws_manager.broadcast_all({
                "type": "plan_step_done",
                "plan_id": plan_id,
                "step": idx + 1,
                "total": total_steps,
                "case_name": case_dict.get("name", ""),
                "status": result.get("status"),
                "duration_ms": result.get("duration_ms", 0),
                "method": result.get("method", ""),
                "status_code": result.get("status_code"),
                "error": result.get("error", ""),
                "var_store": dict(var_store),
            })

        # ── 阶段3：统计 & 保存报告 ─────────────────────────────────────────
        passed = sum(1 for r in step_results if r["status"] == "passed")
        failed_count = len(step_results) - passed
        total = len(step_results)
        pass_rate = round(passed / total * 100, 1) if total else 0
        final_status = "passed" if failed_count == 0 else "failed"

        async with _session_maker() as db:
            try:
                await flush_global_vars(source_project=f"plan:{plan_id}")
            except Exception as fv_err:
                logger.warning(f"[plan_exec] flush_global_vars 失败: {fv_err}")

            report = TestPlanReport(
                plan_id=plan_id,
                plan_name=plan_name,
                total=total,
                passed=passed,
                failed=failed_count,
                pass_rate=pass_rate,
                details=step_results,
                var_snapshot=dict(var_store),
            )
            db.add(report)

            plan_upd = (await db.execute(
                select(TestPlan).where(TestPlan.id == plan_id)
            )).scalar_one_or_none()
            if plan_upd:
                plan_upd.status = final_status
                plan_upd.updated_at = _dt.utcnow()

            await db.commit()
            await db.refresh(report)
            report_id = report.id

    except Exception as e:
        logger.error(f"[plan_exec] 计划 {plan_id} 执行异常: {e}", exc_info=True)
        # 异常时也更新计划状态为 failed
        try:
            async with _session_maker() as db:
                plan_upd = (await db.execute(
                    select(TestPlan).where(TestPlan.id == plan_id)
                )).scalar_one_or_none()
                if plan_upd:
                    plan_upd.status = "failed"
                    plan_upd.updated_at = _dt.utcnow()
                    await db.commit()
        except Exception:
            pass

    # ── 无论成功失败，都广播 plan_done，确保前端能退出执行状态 ──────────────
    passed = sum(1 for r in step_results if r["status"] == "passed")
    total = len(step_results)
    failed_count = total - passed
    pass_rate = round(passed / total * 100, 1) if total else 0
    await ws_manager.broadcast_all({
        "type": "plan_done",
        "plan_id": plan_id,
        "report_id": report_id,
        "total": total,
        "passed": passed,
        "failed": failed_count,
        "pass_rate": pass_rate,
        "status": final_status,
    })


# ── 报告 ────────────────────────────────────────────────────────────────────

@router.get("/test-plans/{plan_id}/reports")
async def list_plan_reports(plan_id: int, db: AsyncSession = Depends(get_db)):
    """列出某计划的所有执行报告（不含 details，减少数据量）。"""
    from sqlalchemy import select
    rows = (await db.execute(
        select(TestPlanReport).where(TestPlanReport.plan_id == plan_id).order_by(TestPlanReport.id.desc())
    )).scalars().all()
    result = []
    for r in rows:
        d = _plan_report_dict(r)
        d.pop("details", None)   # 列表页不返回明细
        result.append(d)
    return result


@router.get("/test-plans/reports/{report_id}")
async def get_plan_report(report_id: int, db: AsyncSession = Depends(get_db)):
    """获取单个执行报告完整详情（含步骤级结果）。"""
    from sqlalchemy import select
    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    return _plan_report_dict(r)


@router.delete("/test-plans/reports/batch")
async def delete_plan_reports_batch(ids: List[int], db: AsyncSession = Depends(get_db)):
    """批量删除执行报告。body: [id1, id2, ...]"""
    from sqlalchemy import delete as sql_del
    if not ids:
        raise HTTPException(status_code=400, detail="未提供报告ID")
    await db.execute(sql_del(TestPlanReport).where(TestPlanReport.id.in_(ids)))
    await db.commit()
    return {"message": f"已删除 {len(ids)} 条报告"}


@router.post("/test-plans/reports/{report_id}/analyze")
async def analyze_plan_report(report_id: int, db: AsyncSession = Depends(get_db)):
    """AI 分析测试计划执行报告，返回分析结论并持久化。"""
    from sqlalchemy import select
    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")

    rdict = _plan_report_dict(r)
    analysis = await _ai_analyze_plan_report(rdict)

    r.analysis = analysis
    await db.commit()
    return {"analysis": analysis}


async def _ai_analyze_plan_report(report: dict) -> str:
    import httpx
    from tools.config import settings

    total = report.get("total", 0)
    passed = report.get("passed", 0)
    failed = report.get("failed", 0)
    pass_rate = report.get("pass_rate", 0)
    plan_name = report.get("plan_name", "")
    details = report.get("details") or []

    failed_steps = [d for d in details if d.get("status") == "failed"]
    failed_summary = "\n".join(
        f"- 步骤 {d.get('step')} [{d.get('method', '')} {d.get('url', '')}] {d.get('case_name', '')}: "
        f"{d.get('error') or '断言失败'}"
        + (
            "\n  失败断言: " + "; ".join(
                f"{a.get('type')} 期望={a.get('expected')} 实际={a.get('actual')}"
                for a in (d.get("assertions") or [])
                if not a.get("passed")
            ) if any(not a.get("passed") for a in (d.get("assertions") or [])) else ""
        )
        for d in failed_steps[:20]
    )

    prompt = (
        f"以下是接口测试计划「{plan_name}」的执行报告，请分析失败原因并给出改进建议。\n\n"
        f"执行概况：共 {total} 个步骤，通过 {passed}，失败 {failed}，通过率 {pass_rate}%\n\n"
        + (f"失败步骤明细：\n{failed_summary}\n\n" if failed_steps else "所有步骤均通过。\n\n")
        + "请输出：\n1. 失败原因分析（具体到每个失败步骤或共同根因）\n"
        "2. 修复建议（可操作的步骤）\n"
        "3. 测试质量总结"
    )

    api_key  = settings.AI_API_KEY
    base_url = (settings.AI_API_URL or "").rstrip("/")
    model    = settings.AI_MODEL or "deepseek-v4-flash"

    is_anthropic = "anthropic.com" in base_url or model.startswith("claude")

    if is_anthropic:
        url     = f"{base_url}/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 2048,
            "system": "你是一名资深测试工程师，擅长分析接口测试报告，给出精准、可操作的建议。用中文回答，使用 Markdown 格式输出，结构要求：用 ## 作为一级标题，### 作为二级标题，重点内容用 **加粗**，列表用 - 开头，不要使用 --- 分隔线，不要过度嵌套，保持简洁清晰。",
            "messages": [{"role": "user", "content": prompt}],
        }
    else:
        url     = f"{base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 2048,
            "messages": [
                {"role": "system", "content": "你是一名资深测试工程师，擅长分析接口测试报告，给出精准、可操作的建议。用中文回答，使用 Markdown 格式输出，结构要求：用 ## 作为一级标题，### 作为二级标题，重点内容用 **加粗**，列表用 - 开头，不要使用 --- 分隔线，不要过度嵌套，保持简洁清晰。"},
                {"role": "user",   "content": prompt},
            ],
        }

    async with httpx.AsyncClient(verify=False, timeout=90) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if is_anthropic:
        return data["content"][0]["text"]
    else:
        return data["choices"][0]["message"]["content"]


@router.delete("/test-plans/reports/{report_id}")
async def delete_plan_report(report_id: int, db: AsyncSession = Depends(get_db)):
    """删除执行报告。"""
    from sqlalchemy import select
    r = (await db.execute(select(TestPlanReport).where(TestPlanReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    await db.delete(r)
    await db.commit()
    return {"message": "报告已删除"}
