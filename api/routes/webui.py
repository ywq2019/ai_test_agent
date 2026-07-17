"""
WebUI 自动化测试路由
  - tasks / cases / execute / reports / agent / skills / llm
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from pathlib import Path
import json
from datetime import datetime
from loguru import logger

from api.schemas import (
    TaskCreateRequest, TaskResponse,
    CaseCreateRequest, CaseUpdateRequest, CaseResponse,
    ExecuteRequest, ReportResponse,
    CommandRequest, CommandResponse,
    HealthResponse, LLMConfigRequest, LLMTestRequest, PageParseRequest,
)
from tools.database import (
    get_db, TestTask, TestCase, TestResult, TestReport, User,
)
from agent.core import uitest_agent
from api.websocket_manager import ws_manager
from tools.config import settings
from api.auth import get_current_user, owner_filter, check_owner

router = APIRouter()


# ── 任务管理 ──────────────────────────────────────────────────────────────────

@router.post("/tasks", response_model=TaskResponse)
async def create_task(request: TaskCreateRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = TestTask(
        name=request.name,
        url=request.url,
        document_path=request.document_path,
        browser=request.browser,
        environment=request.environment,
        status="created",
        created_by=current_user.username,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    await ws_manager.broadcast({"type": "task_created", "task": {
        "id": task.id, "name": task.name, "url": task.url, "status": task.status,
    }})
    return TaskResponse(
        id=task.id, name=task.name, url=task.url, status=task.status,
        browser=task.browser, environment=task.environment,
        created_at=task.created_at.isoformat(),
    )


@router.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(TestTask).offset(skip).limit(limit).order_by(TestTask.created_at.desc())
    f = owner_filter(TestTask, current_user)
    if f is not None:
        stmt = stmt.where(f)
    result = await db.execute(stmt)
    tasks = result.scalars().all()
    return [
        TaskResponse(
            id=t.id, name=t.name, url=t.url, status=t.status,
            browser=t.browser, environment=t.environment,
            created_at=t.created_at.isoformat(),
        )
        for t in tasks
    ]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    check_owner(task, current_user, "任务")
    return TaskResponse(
        id=task.id, name=task.name, url=task.url, status=task.status,
        browser=task.browser, environment=task.environment,
        created_at=task.created_at.isoformat(),
        page_elements=task.page_elements or [],
    )


@router.delete("/tasks/{task_id}", response_model=dict)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    check_owner(task, current_user, "任务")
    await db.execute(delete(TestTask).where(TestTask.id == task_id))
    await db.execute(delete(TestCase).where(TestCase.task_id == task_id))
    await db.execute(delete(TestResult).where(TestResult.task_id == task_id))
    await db.commit()
    return {"message": "Task deleted successfully"}


# ── 文档 / 页面解析 ───────────────────────────────────────────────────────────

_ALLOWED_DOC_EXTS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx",
    ".md", ".txt", ".csv", ".html", ".htm", ".json",
}


@router.post("/upload/document")
async def upload_document(file: UploadFile = File(...)):
    import hashlib
    original_name = file.filename or ""
    ext = Path(original_name).suffix.lower()
    if ext not in _ALLOWED_DOC_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 '{ext}'，支持：PDF / Word / Excel / PPTX / Markdown / TXT / CSV / HTML / JSON",
        )
    raw = await file.read()
    if len(raw) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件过大，请上传 20MB 以内的文件")
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
            result = await db.execute(select(TestTask).where(TestTask.id == request.task_id))
            task = result.scalar_one_or_none()
            if task:
                task.page_elements = elements
                task.status = "parsed"
                await db.commit()
                await db.refresh(task)
        logger.info(f"Page parsed successfully, found {len(elements)} elements")
        return {"url": request.url, "element_count": len(elements), "elements": elements}
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
async def set_page_elements(task_id: int, elements: List[dict], db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        check_owner(task, current_user, "任务")
        task.page_elements = elements
        task.status = "parsed"
        await db.commit()
        await db.refresh(task)
        return TaskResponse(
            id=task.id, name=task.name, url=task.url, status=task.status,
            browser=task.browser, environment=task.environment,
            created_at=task.created_at.isoformat(),
            page_elements=task.page_elements,
        )
    except Exception as e:
        logger.error(f"Error setting page elements: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── 用例管理 ──────────────────────────────────────────────────────────────────

@router.get("/cases/count")
async def get_total_case_count(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func
    result = await db.execute(select(func.count(TestCase.id)))
    return {"count": result.scalar() or 0}


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func
    from tools.database import TestReport as TR
    task_count = (await db.execute(select(func.count(TestTask.id)))).scalar() or 0
    case_count = (await db.execute(select(func.count(TestCase.id)))).scalar() or 0
    passed = (await db.execute(select(func.sum(TR.passed)))).scalar() or 0
    failed = (await db.execute(select(func.sum(TR.failed)))).scalar() or 0
    return {"task_count": task_count, "case_count": case_count, "passed": int(passed), "failed": int(failed)}


@router.get("/tasks/{task_id}/cases", response_model=List[CaseResponse])
async def list_cases(task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    check_owner(task, current_user, "任务")
    result = await db.execute(select(TestCase).where(TestCase.task_id == task_id))
    cases = result.scalars().all()
    return [
        CaseResponse(
            id=c.id, task_id=c.task_id, name=c.name, module=c.module,
            priority=c.priority, preconditions=c.preconditions,
            steps=c.steps, expected_results=c.expected_results,
            element_selector=getattr(c, "element_selector", "") or "",
            enabled=c.enabled,
            deprecated=getattr(c, "deprecated", False) or False,
        )
        for c in cases
    ]


@router.post("/cases", response_model=CaseResponse)
async def create_case(request: CaseCreateRequest, db: AsyncSession = Depends(get_db)):
    case = TestCase(
        task_id=request.task_id, name=request.name, module=request.module,
        priority=request.priority, preconditions=request.preconditions,
        steps=request.steps, expected_results=request.expected_results,
        enabled=request.enabled,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return CaseResponse(
        id=case.id, task_id=case.task_id, name=case.name, module=case.module,
        priority=case.priority, preconditions=case.preconditions,
        steps=case.steps, expected_results=case.expected_results,
        enabled=case.enabled,
        deprecated=getattr(case, "deprecated", False) or False,
    )


def _resolve_doc_path(document_path: str) -> Optional[Path]:
    """解析文档路径，兼容相对路径，文件不存在返回 None。"""
    doc_path = Path(document_path)
    if doc_path.exists():
        return doc_path
    if not doc_path.is_absolute():
        project_root = Path(__file__).parent.parent.parent
        full = project_root / doc_path
        if full.exists():
            return full
    return None


@router.post("/cases/generate/{task_id}", response_model=List[CaseResponse])
async def generate_cases(task_id: int, request: dict = None, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    if request is None:
        request = {}
    reparse_page: bool = request.get("reparse_page", False)
    try:
        logger.info(f"Generating cases for task: {task_id}, reparse_page={reparse_page}")
        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        check_owner(task, current_user, "任务")

        if reparse_page and task.url:
            try:
                await ws_manager.broadcast(
                    {"type": "cases_gen_progress", "percent": 5, "stage": "正在重新抓取页面元素..."},
                    client_id="cases_gen",
                )
                elements = await uitest_agent.parse_page(task.url, task.browser or "chromium")
                if elements:
                    task.page_elements = elements
                    await db.commit()
                    logger.info(f"重新抓取页面元素成功: task_id={task_id}，共 {len(elements)} 个")
                else:
                    logger.warning("重新抓取页面元素返回空，保留旧元素")
            except Exception as e:
                logger.warning(f"页面重新抓取失败，使用旧元素: {e}")
                await ws_manager.broadcast(
                    {"type": "cases_gen_progress", "percent": 5, "stage": "页面抓取失败，使用已有元素继续生成..."},
                    client_id="cases_gen",
                )

        if not task.page_elements:
            raise HTTPException(status_code=400, detail="No page elements found for this task")

        uitest_agent._get_state(task_id).page_elements = task.page_elements
        uitest_agent._get_state(task_id).current_url = task.url or ""
        if not reparse_page:
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
                client_id="cases_gen",
            )

        cases = await uitest_agent.generate_cases(task_id=task_id, progress_cb=_progress)

        if uitest_agent._get_state(task_id).document_data:
            _snap = uitest_agent._get_state(task_id).document_data.get("content", "")
            if _snap:
                from skills.case_generator import case_generator as _cg
                task.doc_snapshot = _snap[:20000]
                task.doc_hash = _cg.compute_doc_hash(_snap)

        for case in cases:
            db.add(TestCase(
                task_id=task_id,
                name=case.get("name", "Unnamed Case"),
                module=case.get("module", "通用"),
                priority=case.get("priority", "P1"),
                preconditions=case.get("preconditions", ""),
                steps=case.get("steps", ""),
                expected_results=case.get("expected_results", ""),
                element_selector=case.get("element_selector", ""),
                enabled=True,
            ))
        await db.commit()
        result = await db.execute(select(TestCase).where(TestCase.task_id == task_id))
        all_cases = result.scalars().all()
        return [
            CaseResponse(
                id=c.id, task_id=c.task_id, name=c.name, module=c.module,
                priority=c.priority, preconditions=c.preconditions,
                steps=c.steps, expected_results=c.expected_results,
                element_selector=getattr(c, "element_selector", "") or "",
                enabled=c.enabled,
            )
            for c in all_cases
        ]
    except Exception as e:
        logger.error(f"Error generating cases: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/optimize/{task_id}")
async def optimize_cases(task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """分析已有用例覆盖缺口，追加补充用例。"""
    try:
        from skills.case_generator import case_generator as cg
        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        check_owner(task, current_user, "任务")
        result = await db.execute(select(TestCase).where(TestCase.task_id == task_id))
        existing_db_cases = result.scalars().all()
        if not existing_db_cases:
            raise HTTPException(status_code=400, detail="No existing cases to optimize")
        existing_cases = [
            {"name": c.name, "module": c.module or "通用", "priority": c.priority,
             "steps": c.steps, "expected_results": c.expected_results,
             "element_selector": getattr(c, "element_selector", "") or ""}
            for c in existing_db_cases
        ]
        page_elements = task.page_elements or []
        document_data = None
        if task.document_path:
            doc_path = _resolve_doc_path(task.document_path)
            if doc_path:
                try:
                    document_data = await uitest_agent.parse_document(str(doc_path))
                except Exception as _e:
                    logger.debug(f"文档解析失败（优化流程忽略）: {_e}")

        async def _progress(pct: int, stage: str):
            await ws_manager.broadcast(
                {"type": "cases_opt_progress", "percent": pct, "stage": stage},
                client_id="cases_opt",
            )

        new_cases = await cg.optimize_cases(
            existing_cases=existing_cases, page_elements=page_elements,
            document_data=document_data, progress_cb=_progress,
        )
        for case in new_cases:
            db.add(TestCase(
                task_id=task_id, name=case.get("name", "补充用例"),
                module=case.get("module", "通用"), priority=case.get("priority", "P1"),
                preconditions=case.get("preconditions", ""), steps=case.get("steps", ""),
                expected_results=case.get("expected_results", ""),
                element_selector=case.get("element_selector", ""), enabled=True,
            ))
        await db.commit()
        return {"added": len(new_cases), "message": f"新增 {len(new_cases)} 条补充用例"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error optimizing cases: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/coverage/{task_id}")
async def get_coverage(task_id: int, db: AsyncSession = Depends(get_db)):
    """返回当前任务的用例覆盖度指标。"""
    try:
        from skills.case_generator import case_generator as cg
        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        result = await db.execute(select(TestCase).where(TestCase.task_id == task_id))
        db_cases = result.scalars().all()
        cases = [
            {"name": c.name, "module": c.module or "通用", "priority": c.priority,
             "steps": c.steps, "expected_results": c.expected_results,
             "element_selector": getattr(c, "element_selector", "") or ""}
            for c in db_cases if not getattr(c, "deprecated", False)
        ]
        return cg.analyze_coverage(cases, task.page_elements or [])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting coverage: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── WebUI 文档变更检测 & 增量更新 ─────────────────────────────────────────────

class WebUIDiffCheckRequest(BaseModel):
    new_content: Optional[str] = None
    new_document_path: Optional[str] = None


@router.post("/cases/doc-diff-check/{task_id}")
async def webui_doc_diff_check(
    task_id: int, request: WebUIDiffCheckRequest, db: AsyncSession = Depends(get_db),
):
    from skills.case_generator import case_generator as cg
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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
        return {"has_change": False, "new_doc_hash": new_hash, "old_doc_hash": old_hash,
                "diff": None, "message": "文档内容未发生变化，无需更新用例"}
    old_content = task.doc_snapshot or ""
    if not old_content:
        return {"has_change": True, "new_doc_hash": new_hash, "old_doc_hash": old_hash,
                "diff": None, "message": "旧版文档快照未保存，建议直接重新生成用例"}
    try:
        diff_result = await cg.analyze_doc_diff(old_doc_content=old_content, new_doc_content=new_content)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"has_change": True, "new_doc_hash": new_hash, "old_doc_hash": old_hash, "diff": diff_result}


class WebUIIncrementalUpdateRequest(BaseModel):
    new_content: Optional[str] = None
    new_document_path: Optional[str] = None
    diff: Optional[dict] = None
    reparse_page: bool = False


@router.post("/cases/incremental-update/{task_id}")
async def webui_incremental_update(
    task_id: int, request: WebUIIncrementalUpdateRequest, db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import delete as sql_delete
    from skills.case_generator import case_generator as cg
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not request.new_content and not request.new_document_path:
        raise HTTPException(status_code=400, detail="请提供新版文档路径或文本内容")
    if request.new_document_path:
        try:
            document_data = await uitest_agent.parse_document(request.new_document_path)
            new_content = document_data.get("content", "")
            p = Path(request.new_document_path)
            if "uploads" in p.parts and "documents" in p.parts:
                p.unlink(missing_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"新文档解析失败: {e}")
    else:
        new_content = request.new_content or ""
    if not new_content.strip():
        raise HTTPException(status_code=400, detail="新文档内容为空")
    if request.reparse_page and task.url:
        try:
            await ws_manager.broadcast(
                {"type": "cases_gen_progress", "percent": 5, "stage": "重新抓取页面元素..."},
                client_id="cases_gen",
            )
            elements = await uitest_agent.parse_page(task.url, task.browser or "chromium")
            task.page_elements = elements
        except Exception as e:
            logger.warning(f"页面重新抓取失败，使用旧元素: {e}")
    diff_result = request.diff
    if not diff_result:
        old_content = task.doc_snapshot or ""
        if not old_content:
            raise HTTPException(status_code=400, detail="旧版文档快照未保存，无法做精确 Diff。请直接重新生成用例。")
        try:
            diff_result = await cg.analyze_doc_diff(old_doc_content=old_content, new_doc_content=new_content)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
    if not (diff_result.get("changed") or diff_result.get("added") or diff_result.get("removed")):
        raise HTTPException(status_code=400, detail="Diff 分析未发现任何模块变更，无需更新")
    case_result = await db.execute(select(TestCase).where(TestCase.task_id == task_id))
    existing_cases = [
        {"id": f"TC{c.id:03d}", "name": c.name, "module": c.module or "通用",
         "priority": c.priority, "preconditions": c.preconditions or "",
         "steps": c.steps or "", "expected_results": c.expected_results or "",
         "element_selector": getattr(c, "element_selector", "") or ""}
        for c in case_result.scalars().all()
    ]

    async def _progress(pct: int, stage: str):
        await ws_manager.broadcast(
            {"type": "cases_gen_progress", "percent": pct, "stage": stage},
            client_id="cases_gen",
        )

    try:
        upd = await cg.incremental_update(
            url=task.url or "", page_elements=task.page_elements or [],
            existing_cases=existing_cases, diff_result=diff_result,
            new_doc_content=new_content, progress_cb=_progress,
        )
    except Exception as e:
        logger.exception("WebUI 增量更新失败: {}", repr(e))
        raise HTTPException(status_code=500, detail=f"增量更新失败: {e}")
    await db.execute(sql_delete(TestCase).where(TestCase.task_id == task_id))
    for case in upd["retained_cases"] + upd["new_cases"] + upd["deprecated_cases"]:
        db.add(TestCase(
            task_id=task_id, name=case.get("name", "未命名"),
            module=case.get("module", "通用"), priority=case.get("priority", "P1"),
            preconditions=case.get("preconditions", ""), steps=case.get("steps", ""),
            expected_results=case.get("expected_results", ""),
            element_selector=case.get("element_selector", ""), enabled=True,
            deprecated=(case.get("status") == "deprecated"),
        ))
    task.doc_snapshot = new_content[:20000]
    task.doc_hash = cg.compute_doc_hash(new_content)
    task.status = "cases_updated"
    await db.commit()
    active_count = len(upd["retained_cases"]) + len(upd["new_cases"])
    deprecated_count = len(upd["deprecated_cases"])
    logger.info(f"WebUI 增量更新完成: task_id={task_id}，active={active_count} deprecated={deprecated_count}")
    return {"active_count": active_count, "deprecated_count": deprecated_count,
            "diff_summary": upd["diff_summary"],
            "message": f"增量更新成功！有效用例 {active_count} 条，废弃 {deprecated_count} 条"}


@router.put("/cases/{case_id}", response_model=CaseResponse)
async def update_case(case_id: int, request: CaseUpdateRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    for key, value in request.model_dump(exclude_unset=True).items():
        setattr(case, key, value)
    await db.commit()
    await db.refresh(case)
    return CaseResponse(
        id=case.id, task_id=case.task_id, name=case.name, module=case.module,
        priority=case.priority, preconditions=case.preconditions,
        steps=case.steps, expected_results=case.expected_results,
        enabled=case.enabled, deprecated=getattr(case, "deprecated", False) or False,
    )


@router.delete("/cases/{case_id}")
async def delete_case(case_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Case not found")
    await db.execute(delete(TestCase).where(TestCase.id == case_id))
    await db.commit()
    return {"message": "Case deleted"}


# ── 执行 & 报告 ───────────────────────────────────────────────────────────────

async def _run_execution_bg(
    report_id: int, task_id: int, task_name: str,
    task_url: str, case_dicts: list, case_ids, browser: str,
):
    """后台执行测试，通过 WebSocket 推送进度，完成后写回数据库。"""
    from tools.database import async_session_maker, TestResult as TR
    try:
        uitest_agent._get_state(task_id).cases = case_dicts
        results = await uitest_agent.execute_cases(
            case_ids=case_ids, browser_type=browser, url=task_url, task_id=task_id,
        )
        for r in results:
            sp = r.get("screenshot_path")
            if sp and not sp.startswith("http"):
                r["screenshot_path"] = f"/screenshots/{Path(sp).name}"
        passed  = sum(1 for r in results if r.get("status") == "passed")
        failed  = sum(1 for r in results if r.get("status") == "failed")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        pass_rate = (passed / len(results) * 100) if results else 0
        details = [
            {"id": idx, "case_name": r.get("case_name", "Unknown"),
             "status": r.get("status", "unknown"), "duration": round(r.get("duration", 0), 2),
             "error_message": r.get("error_message"), "screenshot": r.get("screenshot_path"),
             "start_time": r.get("start_time"), "end_time": r.get("end_time")}
            for idx, r in enumerate(results, 1)
        ]
        summary = {
            "total": len(results), "passed": passed, "failed": failed, "skipped": skipped,
            "pass_rate": round(pass_rate, 2),
            "total_duration": round(sum(r.get("duration", 0) for r in results), 2),
            "failed_cases": [
                {"case_name": r.get("case_name"), "error": r.get("error_message", ""),
                 "duration": r.get("duration", 0)}
                for r in results if r.get("status") == "failed"
            ],
        }
        async with async_session_maker() as db:
            res = await db.execute(select(TestReport).where(TestReport.id == report_id))
            report = res.scalar_one_or_none()
            if report:
                report.summary  = summary
                report.details  = details
                report.pass_rate = round(pass_rate, 2)
                report.passed   = passed
                report.failed   = failed
                report.skipped  = skipped
                for r in results:
                    db.add(TR(
                        task_id=task_id, case_id=r.get("case_id"), status=r.get("status"),
                        start_time=datetime.fromisoformat(r["start_time"]) if r.get("start_time") else None,
                        end_time=datetime.fromisoformat(r["end_time"]) if r.get("end_time") else None,
                        duration=r.get("duration", 0), error_message=r.get("error_message"),
                        screenshot_path=r.get("screenshot_path"), logs=r.get("logs"),
                    ))
                try:
                    report_data = await uitest_agent.generate_report(task_name)
                    report.report_path = report_data.get("html_path") or report_data.get("report_path")
                except Exception as e:
                    logger.error(f"Failed to generate report file: {e}")
                await db.commit()
        await ws_manager.broadcast_all({"type": "execution_saved", "report_id": report_id, "summary": summary})
    except Exception as e:
        logger.error(f"Background execution failed: {e}", exc_info=True)
        await ws_manager.broadcast_all({"type": "execution_error", "report_id": report_id, "error": str(e)})


@router.post("/execute")
async def execute_cases(
    request: ExecuteRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(TestCase).where(TestCase.task_id == request.task_id))
    cases = result.scalars().all()
    if request.case_ids:
        cases = [c for c in cases if c.id in request.case_ids]
    cases = [c for c in cases if not getattr(c, "deprecated", False)]
    case_dicts = [
        {"id": c.id, "name": c.name, "module": c.module, "priority": c.priority,
         "preconditions": c.preconditions, "steps": c.steps,
         "expected_results": c.expected_results, "element_selector": getattr(c, "element_selector", "")}
        for c in cases
    ]
    task_result = await db.execute(select(TestTask).where(TestTask.id == request.task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    check_owner(task, current_user, "任务")
    task_url  = task.url  if task else ""
    task_name = task.name if task else f"Task {request.task_id}"
    report = TestReport(
        task_id=request.task_id, name=f"{task_name} - 测试报告",
        summary={}, details=[], pass_rate=0, total_cases=len(case_dicts),
        passed=0, failed=0, skipped=0,
        created_by=current_user.username,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    background_tasks.add_task(
        _run_execution_bg,
        report_id=report.id, task_id=request.task_id, task_name=task_name,
        task_url=task_url, case_dicts=case_dicts, case_ids=request.case_ids, browser=request.browser,
    )
    return {"report_id": report.id, "status": "running", "total": len(case_dicts),
            "message": f"开始执行 {len(case_dicts)} 个用例，请通过 WebSocket 接收进度"}


@router.get("/reports", response_model=List[ReportResponse])
async def list_reports(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(TestReport).order_by(TestReport.created_at.desc())
    f = owner_filter(TestReport, current_user)
    if f is not None:
        stmt = stmt.where(f)
    result = await db.execute(stmt)
    reports = result.scalars().all()
    return [
        ReportResponse(
            task_id=r.task_id, task_name=r.name,
            summary=json.loads(r.summary) if isinstance(r.summary, str) else (r.summary or {}),
            html_path=r.report_path or "", report_id=r.id,
            total_cases=r.total_cases or 0, passed=r.passed or 0,
            failed=r.failed or 0, skipped=r.skipped or 0, pass_rate=r.pass_rate or 0,
            details=json.loads(r.details) if isinstance(r.details, str) else (r.details or []),
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in reports
    ]


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report_by_id(report_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    check_owner(report, current_user, "报告")
    return ReportResponse(
        task_id=report.task_id, task_name=report.name,
        summary=json.loads(report.summary) if isinstance(report.summary, str) else (report.summary or {}),
        html_path=report.report_path or "", report_id=report.id,
        total_cases=report.total_cases or 0, passed=report.passed or 0,
        failed=report.failed or 0, skipped=report.skipped or 0, pass_rate=report.pass_rate or 0,
        details=json.loads(report.details) if isinstance(report.details, str) else (report.details or []),
        created_at=report.created_at.isoformat() if report.created_at else "",
    )


@router.get("/reports/{report_id}/export")
async def export_report(report_id: int, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import HTMLResponse
    from urllib.parse import quote
    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")  if isinstance(report.summary, str)  else (report.summary  or {})
    details  = json.loads(report.details)  if isinstance(report.details, str)  else (report.details  or [])
    task_name  = report.name or f"报告 {report_id}"
    created_at = report.created_at.strftime("%Y-%m-%d %H:%M:%S") if report.created_at else ""
    details_rows = ""
    for detail in details:
        status_map = {"passed": ("success", "通过"), "failed": ("danger", "失败"), "skipped": ("warning", "跳过")}
        cls, label = status_map.get(detail.get("status", ""), ("secondary", detail.get("status", "-")))
        err = (detail.get("error_message") or "-")[:120]
        shot = detail.get("screenshot", "")
        shot_cell = f'<td><a href="{shot}" target="_blank" style="color:#409eff;">查看</a></td>' if shot else "<td>-</td>"
        details_rows += f"""
        <tr>
            <td>{detail.get('id','')}</td><td>{detail.get('case_name','-')}</td>
            <td><span class="badge bg-{cls}">{label}</span></td>
            <td>{detail.get('duration',0)}s</td>
            <td style="max-width:300px;word-break:break-all;">{err}</td>
            {shot_cell}
        </tr>"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>测试报告 - {task_name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f5;padding:24px;color:#333}}
.container{{max-width:1200px;margin:0 auto}}
.header{{background:#fff;padding:24px;border-radius:8px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.08)}}
.header h1{{font-size:22px;margin-bottom:6px}}.meta{{color:#888;font-size:13px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:20px}}
.card{{background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.08);text-align:center}}
.card .num{{font-size:32px;font-weight:700;margin-bottom:4px}}.card .lbl{{font-size:13px;color:#888}}
.green{{color:#52c41a}}.red{{color:#ff4d4f}}.orange{{color:#fa8c16}}.blue{{color:#1890ff}}
.section{{background:#fff;padding:24px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.08)}}
.section h2{{font-size:16px;margin-bottom:16px;border-left:4px solid #409eff;padding-left:10px}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #f0f0f0;font-size:13px}}
th{{background:#fafafa;font-weight:600;color:#555}}
.badge{{padding:3px 8px;border-radius:4px;font-size:12px}}
.bg-success{{background:#d9f7be;color:#52c41a}}.bg-danger{{background:#fff1f0;color:#ff4d4f}}
.bg-warning{{background:#fffbe6;color:#fa8c16}}.bg-secondary{{background:#f5f5f5;color:#999}}
</style></head><body>
<div class="container">
  <div class="header"><h1>{task_name}</h1><p class="meta">生成时间：{created_at}</p></div>
  <div class="cards">
    <div class="card"><div class="num blue">{summary.get('total',0)}</div><div class="lbl">总用例数</div></div>
    <div class="card"><div class="num green">{summary.get('passed',0)}</div><div class="lbl">通过</div></div>
    <div class="card"><div class="num red">{summary.get('failed',0)}</div><div class="lbl">失败</div></div>
    <div class="card"><div class="num orange">{summary.get('skipped',0)}</div><div class="lbl">跳过</div></div>
    <div class="card"><div class="num green">{summary.get('pass_rate',0)}%</div><div class="lbl">通过率</div></div>
    <div class="card"><div class="num">{summary.get('total_duration',0)}s</div><div class="lbl">总耗时</div></div>
  </div>
  <div class="section"><h2>用例执行详情</h2>
    <table><thead><tr><th>序号</th><th>用例名称</th><th>状态</th><th>耗时</th><th>错误信息</th><th>截图</th></tr></thead>
    <tbody>{details_rows}</tbody></table>
  </div>
</div></body></html>"""
    encoded_name = quote(task_name.replace("/", "_") + ".html", safe="")
    return HTMLResponse(content=html, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"})


@router.get("/reports/{report_id}/pdf")
async def export_report_pdf(report_id: int, db: AsyncSession = Depends(get_db)):
    """将测试报告导出为 PDF 文件（复用 Playwright Chromium 渲染）。"""
    from fastapi.responses import Response
    from urllib.parse import quote
    from tools.pdf_exporter import html_to_pdf

    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    task_name = report.name or f"报告_{report_id}"

    # 优先使用已落盘的 HTML 文件；若文件丢失则动态构建 HTML 字符串
    html_path = report.report_path or ""
    if html_path:
        p = Path(html_path)
        if not p.is_absolute():
            p = Path(__file__).parent.parent.parent / html_path
        if not p.exists():
            html_path = ""

    try:
        if html_path:
            pdf_bytes = await html_to_pdf(html_path=str(p))
        else:
            # report_path 不存在时，从 export_report 接口复用同样的 HTML 构建逻辑
            summary = json.loads(report.summary) if isinstance(report.summary, str) else (report.summary or {})
            details = json.loads(report.details) if isinstance(report.details, str) else (report.details or [])
            created_at = report.created_at.strftime("%Y-%m-%d %H:%M:%S") if report.created_at else ""
            details_rows = ""
            for detail in details:
                status_map = {"passed": ("success", "通过"), "failed": ("danger", "失败"), "skipped": ("warning", "跳过")}
                cls, label = status_map.get(detail.get("status", ""), ("secondary", detail.get("status", "-")))
                err = (detail.get("error_message") or "-")[:120]
                details_rows += f"<tr><td>{detail.get('id','')}</td><td>{detail.get('case_name','-')}</td><td><span class='badge bg-{cls}'>{label}</span></td><td>{detail.get('duration',0)}s</td><td>{err}</td></tr>"
            html_str = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{task_name}</title>
<style>body{{font-family:-apple-system,sans-serif;padding:24px;color:#333}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:8px 12px;border:1px solid #e8e8e8;font-size:13px}}
th{{background:#fafafa}}.badge{{padding:2px 8px;border-radius:4px;font-size:12px}}
.bg-success{{background:#d9f7be;color:#52c41a}}.bg-danger{{background:#fff1f0;color:#ff4d4f}}
.bg-warning{{background:#fffbe6;color:#fa8c16}}</style></head>
<body><h2>{task_name}</h2><p>生成时间：{created_at} &nbsp;|&nbsp; 通过率：{summary.get('pass_rate',0)}%</p>
<table><thead><tr><th>序号</th><th>用例名称</th><th>状态</th><th>耗时</th><th>错误信息</th></tr></thead>
<tbody>{details_rows}</tbody></table></body></html>"""
            pdf_bytes = await html_to_pdf(html_str=html_str)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    encoded_name = quote(task_name.replace("/", "_") + ".pdf", safe="")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.delete("/reports/{report_id}")
async def delete_report(report_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete
    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    check_owner(report, current_user, "报告")
    await db.execute(delete(TestReport).where(TestReport.id == report_id))
    await db.commit()
    return {"message": "Report deleted"}


@router.delete("/reports")
async def delete_reports_batch(report_ids: List[int], db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete
    if not report_ids:
        raise HTTPException(status_code=400, detail="No report IDs provided")
    # 批量删除只删属于自己的（admin 可删全部，普通用户只删自己的）
    stmt = select(TestReport).where(TestReport.id.in_(report_ids))
    f = owner_filter(TestReport, current_user)
    if f is not None:
        stmt = stmt.where(f)
    result = await db.execute(stmt)
    allowed_ids = [r.id for r in result.scalars().all()]
    if not allowed_ids:
        raise HTTPException(status_code=403, detail="无权删除所选报告")
    await db.execute(delete(TestReport).where(TestReport.id.in_(allowed_ids)))
    await db.commit()
    return {"message": f"Deleted {len(allowed_ids)} reports"}


@router.get("/tasks/{task_id}/report", response_model=ReportResponse)
async def get_report(task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestReport).where(TestReport.task_id == task_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    check_owner(report, current_user, "报告")
    return ReportResponse(
        task_id=report.task_id, task_name=report.name,
        summary=json.loads(report.summary) if isinstance(report.summary, str) else (report.summary or {}),
        html_path=report.report_path or "", report_id=report.id,
        total_cases=report.total_cases or 0, passed=report.passed or 0,
        failed=report.failed or 0, skipped=report.skipped or 0, pass_rate=report.pass_rate or 0,
        details=json.loads(report.details) if isinstance(report.details, str) else (report.details or []),
        created_at=report.created_at.isoformat() if report.created_at else "",
    )


# ── Agent / Skills / LLM ─────────────────────────────────────────────────────

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
    test_executor.stop()
    return {"message": "Stop signal sent"}


@router.get("/skills")
async def list_skills():
    uitest_agent.load_skills()
    return {"skills": uitest_agent.get_skills(), "total": len(uitest_agent.get_skills())}


@router.get("/skills/{skill_name}")
async def get_skill(skill_name: str):
    uitest_agent.load_skills()
    for s in uitest_agent.get_skills():
        if s["name"] == skill_name:
            return s
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
    allowed_exts = {".md", ".yaml", ".yml", ".txt"}
    uitest_agent.load_skills()
    for skill in uitest_agent.get_skills():
        if skill["name"] == skill_name and skill.get("file_path"):
            skill_root = Path(skill["file_path"]).parent
            target = (skill_root / path).resolve()
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
    uitest_agent.load_skills()
    for skill in uitest_agent.get_skills():
        if skill["name"] == skill_name and skill.get("file_path"):
            skill_path = Path(skill["file_path"]).parent
            if skill_path.exists():
                files = [
                    {"name": f.name, "path": str(f.relative_to(skill_path)),
                     "size": f.stat().st_size, "type": f.suffix}
                    for f in skill_path.rglob("*") if f.is_file()
                ]
                return {"skill_name": skill_name, "path": str(skill_path), "files": files}
    raise HTTPException(status_code=404, detail="Skill not found")


@router.get("/llm/models")
async def get_llm_models():
    available_models = [
        {"id": "gpt-4o",               "name": "GPT-4o",              "provider": "OpenAI"},
        {"id": "gpt-4o-mini",          "name": "GPT-4o Mini",         "provider": "OpenAI"},
        {"id": "gpt-4-turbo",          "name": "GPT-4 Turbo",         "provider": "OpenAI"},
        {"id": "gpt-3.5-turbo",        "name": "GPT-3.5 Turbo",       "provider": "OpenAI"},
        {"id": "claude-sonnet-4-6",    "name": "Claude Sonnet 4.6",   "provider": "Anthropic"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "provider": "Anthropic"},
        {"id": "claude-opus-4-8",      "name": "Claude Opus 4.8",     "provider": "Anthropic"},
        {"id": "gemini-2.0-flash",     "name": "Gemini 2.0 Flash",    "provider": "Google"},
        {"id": "moonshot-v1-8k",       "name": "Moonshot 8K",         "provider": "Moonshot"},
        {"id": "moonshot-v1-32k",      "name": "Moonshot 32K",        "provider": "Moonshot"},
        {"id": "moonshot-v1-128k",     "name": "Moonshot 128K",       "provider": "Moonshot"},
        {"id": "deepseek-v4-flash",    "name": "DeepSeek V4 Flash",   "provider": "DeepSeek"},
        {"id": "deepseek-reasoner",    "name": "DeepSeek Reasoner",   "provider": "DeepSeek"},
        {"id": "qwen-turbo",           "name": "Qwen Turbo",          "provider": "Alibaba"},
        {"id": "qwen-plus",            "name": "Qwen Plus",           "provider": "Alibaba"},
        {"id": "qwen-max",             "name": "Qwen Max",            "provider": "Alibaba"},
        {"id": "yi-lightning",         "name": "Yi Lightning",        "provider": "01AI"},
    ]
    temperature = getattr(settings, "AI_TEMPERATURE", 0.5)
    return {
        "current_model": settings.AI_MODEL, "current_model_name": settings.AI_MODEL_NAME,
        "current_api_url": settings.AI_API_URL, "api_key_configured": bool(settings.AI_API_KEY),
        "temperature": temperature, "models": available_models,
    }


@router.put("/llm/model")
async def update_llm_model(config: LLMConfigRequest):
    import os
    model     = config.model
    api_key   = config.api_key
    api_url   = config.api_url
    env_path  = Path(__file__).parent.parent.parent / ".env"
    env_lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            env_lines = f.readlines()

    def _upsert(lines, key, val):
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={val}\n"
                return lines
        lines.append(f"{key}={val}\n")
        return lines

    if model:
        env_lines = _upsert(env_lines, "AI_MODEL", model)
        settings.AI_MODEL = model
    if api_key:
        env_lines = _upsert(env_lines, "AI_API_KEY", api_key)
        settings.AI_API_KEY = api_key
    if api_url:
        env_lines = _upsert(env_lines, "AI_API_URL", api_url)
        settings.AI_API_URL = api_url
    if config.model_name:
        env_lines = _upsert(env_lines, "AI_MODEL_NAME", config.model_name)
        settings.AI_MODEL_NAME = config.model_name
    if config.temperature is not None:
        env_lines = _upsert(env_lines, "AI_TEMPERATURE", config.temperature)
        if hasattr(settings, "AI_TEMPERATURE"):
            settings.AI_TEMPERATURE = config.temperature
    env_lines = [line for line in env_lines if line.strip() or line == "\n"]
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(env_lines)
    if settings.AI_API_KEY and settings.AI_API_URL and settings.AI_MODEL:
        try:
            from agent.langgraph_agent import init_langgraph_agent
            init_langgraph_agent(api_key=settings.AI_API_KEY, base_url=settings.AI_API_URL, model_name=settings.AI_MODEL)
            logger.info(f"LangGraph Agent re-initialized: {settings.AI_MODEL}")
        except Exception as e:
            logger.warning(f"LangGraph Agent re-init failed: {e}")
    return {"message": "LLM configuration updated", "model": settings.AI_MODEL, "api_url": settings.AI_API_URL}


@router.post("/llm/test")
async def test_llm_connection(request: LLMTestRequest):
    import httpx
    test_model   = request.model   or settings.AI_MODEL
    test_api_url = (request.api_url or settings.AI_API_URL).rstrip("/")
    test_api_key = request.api_key or settings.AI_API_KEY
    if not test_api_key:
        return {"success": False, "error": "API key is required"}
    last_err = "连接失败"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        for endpoint, headers, body in [
            (f"{test_api_url}/v1/chat/completions",
             {"Authorization": f"Bearer {test_api_key}", "Content-Type": "application/json"},
             {"model": test_model, "messages": [{"role": "user", "content": "reply: ok"}], "max_tokens": 10}),
            (f"{test_api_url}/v1/messages",
             {"x-api-key": test_api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
             {"model": test_model, "max_tokens": 10, "messages": [{"role": "user", "content": "reply: ok"}]}),
        ]:
            try:
                resp = await client.post(endpoint, headers=headers, json=body)
            except Exception:
                continue
            if resp.status_code not in (200, 201):
                last_err = resp.text[:300]
                continue
            ct = resp.headers.get("content-type", "")
            if "html" in ct or resp.text.lstrip().startswith("<"):
                last_err = "API 返回了 HTML 页面，不是有效的 AI 接口响应"
                continue
            try:
                data = resp.json()
            except Exception:
                last_err = "响应不是有效 JSON"
                continue
            if data.get("choices"):
                reply = data["choices"][0].get("message", {}).get("content", "")
                return {"success": True, "model": test_model, "message": f"连接成功，模型回复: {reply[:50]}"}
            if data.get("content"):
                reply = data["content"][0].get("text", "") if isinstance(data["content"], list) else str(data["content"])
                return {"success": True, "model": test_model, "message": f"连接成功，模型回复: {reply[:50]}"}
            last_err = f"响应格式未知: {str(data)[:200]}"
    return {"success": False, "error": last_err}
