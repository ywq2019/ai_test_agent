"""
WebUI 自动化测试路由
  - tasks / cases / execute / reports / agent / skills / llm
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from pathlib import Path
import asyncio
import json
import base64
import mimetypes
import html as _html
import time
from datetime import datetime, timezone, timedelta

_TZ_CST = timezone(timedelta(hours=8))

# ── 并发执行保护：同一 task_id 同一时间只允许一个执行任务 ────────────────────────
_running_tasks: set = set()       # 正在执行中的 task_id 集合
_running_tasks_lock = asyncio.Lock()  # 保护 set 的读写


def _fmt_cst(dt) -> str:
    """将 UTC naive datetime 格式化为 CST（UTC+8）可读字符串。"""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_TZ_CST).strftime("%Y-%m-%d %H:%M:%S")


def _screenshot_data_uri(shot: str) -> str:
    """把截图路径/URL 转成 base64 data URI，供独立 HTML/PDF 内嵌显示。

    支持两种输入：
    - Web 路径（/screenshots/xxx.png）→ 拼出本地磁盘路径后读取
    - 磁盘绝对/相对路径            → 直接读取
    返回 data:image/...;base64,... 字符串；失败时原样返回。
    """
    if not shot:
        return shot
    from pathlib import Path as _Path
    from tools.config import settings as _settings

    # 把 web 路径映射到本地磁盘
    if shot.startswith("/screenshots/"):
        filename = shot[len("/screenshots/"):]
        disk_path = _Path(_settings.SCREENSHOT_DIR) / filename
    elif shot.startswith("http://") or shot.startswith("https://"):
        # 远程 URL 无法内嵌，直接返回原值
        return shot
    else:
        disk_path = _Path(shot)

    try:
        if not disk_path.is_absolute():
            # 相对路径以项目根目录为基准
            disk_path = _Path(__file__).parent.parent.parent / disk_path
        with open(disk_path, "rb") as fh:
            raw = fh.read()
        mime = mimetypes.guess_type(str(disk_path))[0] or "image/png"
        b64  = base64.b64encode(raw).decode()
        return f"data:{mime};base64,{b64}"
    except Exception:
        # 读取失败（文件不存在等）返回原值，页面会显示 broken image 但不崩溃
        return shot
from loguru import logger

from api.schemas import (
    TaskCreateRequest, TaskUpdateRequest, TaskResponse,
    CaseCreateRequest, CaseUpdateRequest, CaseResponse,
    ExecuteRequest, ReportResponse,
    CommandRequest, CommandResponse,
    HealthResponse, LLMConfigRequest, LLMTestRequest, PageParseRequest,
    WebUIDiffCheckRequest, WebUIIncrementalUpdateRequest,
)
from tools.database import (
    get_db, TestTask, TestCase, TestResult, TestReport, User, TaskEnvVar, ElementAlias,
)
from agent.core import uitest_agent
from api.websocket_manager import ws_manager
from tools.config import settings
from api.auth import get_current_user, owner_filter, check_owner, workspace_filter, workspace_filter_members, check_workspace_member, check_access

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
        project_id=request.workspace_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    await ws_manager.broadcast_to_workspace({"type": "task_created", "task": {
        "id": task.id, "name": task.name, "url": task.url, "status": task.status,
    }}, request.workspace_id)
    return TaskResponse(
        id=task.id, name=task.name, url=task.url, status=task.status,
        browser=task.browser, environment=task.environment,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
    )


@router.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(skip: int = 0, limit: int = 100, workspace_id: int = None, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(TestTask).offset(skip).limit(limit).order_by(TestTask.created_at.desc())
    f = await workspace_filter_members(db, TestTask, workspace_id, current_user)
    if f is not None:
        stmt = stmt.where(f)
    result = await db.execute(stmt)
    tasks = result.scalars().all()
    return [
        TaskResponse(
            id=t.id, name=t.name, url=t.url, status=t.status,
            browser=t.browser, environment=t.environment,
            document_path=t.document_path,
            page_elements=t.page_elements or [],
            created_at=t.created_at.isoformat(),
            updated_at=t.updated_at.isoformat() if t.updated_at else None,
        )
        for t in tasks
    ]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
    return TaskResponse(
        id=task.id, name=task.name, url=task.url, status=task.status,
        browser=task.browser, environment=task.environment,
        document_path=task.document_path,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
        page_elements=task.page_elements or [],
    )


@router.delete("/tasks/{task_id}", response_model=dict)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
    await db.execute(delete(TestTask).where(TestTask.id == task_id))
    await db.execute(delete(TestCase).where(TestCase.task_id == task_id))
    await db.execute(delete(TestResult).where(TestResult.task_id == task_id))
    await db.execute(delete(TestReport).where(TestReport.task_id == task_id))
    await db.execute(delete(TaskEnvVar).where(TaskEnvVar.task_id == task_id))
    await db.execute(delete(ElementAlias).where(ElementAlias.task_id == task_id))
    await db.commit()
    return {"message": "Task deleted successfully"}


@router.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: int, request: TaskUpdateRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")

    # 只更新传入了的字段
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    await db.commit()
    await db.refresh(task)
    return TaskResponse(
        id=task.id, name=task.name, url=task.url, status=task.status,
        browser=task.browser, environment=task.environment,
        document_path=task.document_path,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
    )


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
async def parse_page(
    request: PageParseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        logger.info(f"Parsing page: {request.url}, browser: {request.browser}, task_id: {request.task_id}")
        elements = await uitest_agent.parse_page(request.url, request.browser)
        if request.task_id:
            result = await db.execute(select(TestTask).where(TestTask.id == request.task_id))
            task = result.scalar_one_or_none()
            if task:
                await check_access(db, task, current_user, "任务")
                task.page_elements = elements
                task.status = "parsed"
                await db.commit()
                await db.refresh(task)
        logger.info(f"Page parsed successfully, found {len(elements)} elements")
        return {"url": request.url, "element_count": len(elements), "elements": elements}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error parsing page: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="页面解析失败，请检查 URL 或浏览器配置")


@router.post("/parse/document")
async def parse_document(
    document_path: str,
    current_user: User = Depends(get_current_user),
):
    # 安全校验：只允许访问 uploads 目录下的文件，防止路径遍历
    from pathlib import Path as _Path
    safe_root = _Path(settings.UPLOAD_DIR).resolve()
    target = (_Path(document_path) if _Path(document_path).is_absolute()
              else safe_root / document_path).resolve()
    if not str(target).startswith(str(safe_root)):
        from fastapi import HTTPException as _HTTP
        raise _HTTP(status_code=400, detail="不允许访问该路径")
    try:
        document_data = await uitest_agent.parse_document(document_path)
        return document_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="文档解析失败，请检查文件格式或路径")


@router.post("/tasks/{task_id}/elements", response_model=TaskResponse)
async def set_page_elements(task_id: int, elements: List[dict], db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        await check_access(db, task, current_user, "任务")
        task.page_elements = elements
        task.status = "parsed"
        await db.commit()
        await db.refresh(task)
        return TaskResponse(
            id=task.id, name=task.name, url=task.url, status=task.status,
            browser=task.browser, environment=task.environment,
            created_at=task.created_at.isoformat(),
            updated_at=task.updated_at.isoformat() if task.updated_at else None,
            page_elements=task.page_elements,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting page elements: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="更新页面元素失败，请稍后重试")


# ── 用例管理 ──────────────────────────────────────────────────────────────────

@router.get("/cases/count")
async def get_total_case_count(
    workspace_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import func, false as sql_false
    if current_user.role == "admin":
        result = await db.execute(select(func.count(TestCase.id)))
    elif workspace_id is None:
        # 未选空间：返回 0
        return {"count": 0}
    else:
        # 只统计该空间内任务的用例数
        task_ids_q = select(TestTask.id).where(TestTask.project_id == workspace_id)
        result = await db.execute(
            select(func.count(TestCase.id)).where(TestCase.task_id.in_(task_ids_q))
        )
    return {"count": result.scalar() or 0}


@router.get("/stats")
async def get_stats(
    workspace_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import func
    from tools.database import TestReport as TR

    if current_user.role != "admin" and workspace_id is None:
        return {"task_count": 0, "case_count": 0, "passed": 0, "failed": 0, "recorded_count": 0}

    if current_user.role == "admin" or workspace_id is None:
        task_count = (await db.execute(select(func.count(TestTask.id)))).scalar() or 0
        case_count = (await db.execute(select(func.count(TestCase.id)))).scalar() or 0
        passed = (await db.execute(select(func.sum(TR.passed)))).scalar() or 0
        failed = (await db.execute(select(func.sum(TR.failed)))).scalar() or 0
        recorded_count = (await db.execute(
            select(func.count(TestCase.id)).where(TestCase.module == "录制")
        )).scalar() or 0
    else:
        task_ids_q = select(TestTask.id).where(TestTask.project_id == workspace_id)
        task_count = (await db.execute(
            select(func.count(TestTask.id)).where(TestTask.project_id == workspace_id)
        )).scalar() or 0
        case_count = (await db.execute(
            select(func.count(TestCase.id)).where(TestCase.task_id.in_(task_ids_q))
        )).scalar() or 0
        passed = (await db.execute(
            select(func.sum(TR.passed)).where(TR.project_id == workspace_id)
        )).scalar() or 0
        failed = (await db.execute(
            select(func.sum(TR.failed)).where(TR.project_id == workspace_id)
        )).scalar() or 0
        recorded_count = (await db.execute(
            select(func.count(TestCase.id)).where(
                TestCase.task_id.in_(task_ids_q),
                TestCase.module == "录制"
            )
        )).scalar() or 0

    return {
        "task_count": task_count,
        "case_count": case_count,
        "passed": int(passed),
        "failed": int(failed),
        "recorded_count": int(recorded_count),
    }


@router.get("/tasks/{task_id}/cases", response_model=List[CaseResponse])
async def list_cases(task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
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
            source=getattr(c, "source", "manual") or "manual",
        )
        for c in cases
    ]


@router.post("/cases", response_model=CaseResponse)
async def create_case(request: CaseCreateRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 通过关联任务校验工作空间访问权限（TestCase 通过 task_id 继承隔离）
    task_result = await db.execute(select(TestTask).where(TestTask.id == request.task_id))
    task = task_result.scalar_one_or_none()
    if task:
        await check_access(db, task, current_user, "任务")
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
        source="manual",
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
    # 前端通过请求体传入 ws_client_id，精确推送给对应的 WebSocket 连接
    ws_client_id: str = request.get("ws_client_id") or "cases_gen"
    try:
        logger.info(f"Generating cases for task: {task_id}, reparse_page={reparse_page}, ws_client_id={ws_client_id}")
        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        await check_access(db, task, current_user, "任务")

        if reparse_page and task.url:
            try:
                await ws_manager.broadcast(
                    {"type": "cases_gen_progress", "percent": 5, "stage": "正在重新抓取页面元素..."},
                    client_id=ws_client_id,
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
                    client_id=ws_client_id,
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

        async def _progress(pct: int, stage: str, case_count: int = 0):
            await ws_manager.broadcast(
                {"type": "cases_gen_progress", "percent": pct, "stage": stage, "case_count": case_count},
                client_id=ws_client_id,
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
                steps_json=case.get("steps_json") or [],
                expected_results=case.get("expected_results", ""),
                element_selector=case.get("element_selector", ""),
                source="ai_generated",
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
                source=getattr(c, "source", "ai_generated") or "ai_generated",
            )
            for c in all_cases
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating cases: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="用例生成失败，请稍后重试")


@router.post("/cases/plan-scenes/{task_id}")
async def plan_scenes(task_id: int, request: dict = None,
                      db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    """
    AI 场景规划：分析页面元素 + 已有用例 + 文档摘要，生成测试场景列表。
    支持 append=true 追加规划（保留已录制场景），默认重新规划。
    """
    if request is None:
        request = {}
    description = request.get("description", "")
    append_mode = request.get("append", False)   # True=追加，False=重新规划

    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")

    url = task.url or ""
    page_elements = task.page_elements or []

    # ── 0. 如果有需求文档但 doc_snapshot 为空，自动解析一次 ─────────────────────
    if task.document_path and not task.doc_snapshot:
        try:
            doc_path = _resolve_doc_path(task.document_path)
            if doc_path:
                document_data = await uitest_agent.parse_document(str(doc_path), task_id=task_id)
                snap = (document_data or {}).get("content", "")
                if snap:
                    task.doc_snapshot = snap[:20000]
                    await db.commit()
                    await db.refresh(task)
        except Exception as _e:
            logger.warning(f"[plan_scenes] 自动解析需求文档失败: {_e}")

    # ── 1. 构建分组元素摘要（按功能区分类，信息密度更高）──────────────────────
    def _build_elements_summary(elements: list) -> str:
        if not elements:
            return "（页面元素未抓取，建议先在「任务设置」中解析页面，以获得更精准的场景规划）"

        groups: dict[str, list[str]] = {
            "表单输入": [],
            "操作按钮": [],
            "导航链接": [],
            "下拉选择": [],
            "其他元素": [],
        }
        for e in elements[:60]:
            etype = e.get("type", "")
            tag   = e.get("tag", "")
            text  = (e.get("text") or e.get("placeholder") or e.get("selector", ""))[:40]
            if not text:
                continue
            if etype == "input" or tag == "input":
                groups["表单输入"].append(text)
            elif etype == "button" or tag == "button" or etype == "submit":
                groups["操作按钮"].append(text)
            elif etype == "a" or tag == "a":
                groups["导航链接"].append(text)
            elif etype == "select" or tag == "select":
                groups["下拉选择"].append(text)
            elif text:
                groups["其他元素"].append(text)

        lines = []
        for group, items in groups.items():
            unique = list(dict.fromkeys(items))[:8]  # 去重取前8
            if unique:
                lines.append(f"  [{group}] {' / '.join(unique)}")
        return "\n".join(lines) if lines else "（未识别到关键交互元素）"

    elements_summary = _build_elements_summary(page_elements)

    # ── 2. 已有用例名称（避免重复规划）────────────────────────────────────────
    existing_cases_result = await db.execute(
        select(TestCase.name).where(
            TestCase.task_id == task_id,
            TestCase.deprecated == False,
        )
    )
    existing_names = [r[0] for r in existing_cases_result.fetchall()]
    existing_cases_text = (
        "\n".join(f"  - {n}" for n in existing_names[:20])
        if existing_names else "（暂无已有用例）"
    )

    # ── 3. 文档摘要（取前 800 字，聚焦功能描述）──────────────────────────────
    doc_snippet = "（无需求文档）"
    if task.doc_snapshot:
        snippet = task.doc_snapshot[:800].strip()
        # 截断到最近的句号/换行，避免截断到半句
        for sep in ["。", "\n", ".", "；"]:
            idx = snippet.rfind(sep, 200)
            if idx > 200:
                snippet = snippet[:idx + 1]
                break
        doc_snippet = snippet

    # ── 4. 计算建议场景数量 ──────────────────────────────────────────────────
    # 有文档 → 最多 10 个；仅有元素 → 6-8 个；无信息 → 5 个
    if task.doc_snapshot:
        scene_count = "8-10"
    elif page_elements:
        scene_count = "6-8"
    else:
        scene_count = "5-6"

    try:
        from tools.llm_client import call_llm
        from skills.prompt_loader import get_system, render_user
        import json as _json, re as _re

        system_prompt = get_system("ui_case_gen.yaml", "plan_scenes")
        user_prompt = render_user("ui_case_gen.yaml", "plan_scenes",
            url=url,
            description=description or f"对 {url} 页面进行完整测试",
            elements_summary=elements_summary,
            existing_cases=existing_cases_text,
            doc_snippet=doc_snippet,
            scene_count=scene_count,
        )

        raw = await call_llm(system_prompt, user_prompt, max_tokens=4000, timeout_secs=120)

        # 提取 JSON，多级修复保障：
        # 1. 去掉首尾 markdown 代码块
        # 2. 提取最外层 { } 对象
        # 3. _sanitize_json_string：修复裸引号/控制字符
        # 4. 若仍失败：强制替换所有裸换行（Unterminated string 的根因）
        # 5. 若仍失败：_repair_truncated_json 截断修复
        from skills.ai_case_generator import _sanitize_json_string, _repair_truncated_json

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.split("```")[0].strip()

        m = _re.search(r'\{[\s\S]*\}', raw)
        json_str = m.group(0) if m else raw

        def _try_parse(s: str):
            """依次尝试多种修复策略，返回解析后的 dict，全部失败抛异常。"""
            import json as __json

            # 策略1：直接解析
            try:
                return __json.loads(s)
            except __json.JSONDecodeError:
                pass

            # 策略2：sanitize（裸引号/控制字符）
            s2 = _sanitize_json_string(s)
            try:
                return __json.loads(s2)
            except __json.JSONDecodeError:
                pass

            # 策略3：强制把字符串值内的裸换行/回车替换为空格
            # 原理：在 in_string 状态下把 \n \r 换成空格，比 sanitize 更激进
            result = []
            in_str = False
            esc = False
            for ch in s2:
                if esc:
                    result.append(ch); esc = False
                elif ch == '\\' and in_str:
                    result.append(ch); esc = True
                elif ch == '"':
                    result.append(ch); in_str = not in_str
                elif in_str and ch in ('\n', '\r'):
                    result.append(' ')   # 裸换行替换为空格
                else:
                    result.append(ch)
            s3 = ''.join(result)
            try:
                return __json.loads(s3)
            except __json.JSONDecodeError:
                pass

            # 策略4：截断修复
            s4 = _repair_truncated_json(s3)
            return __json.loads(s4)   # 若仍失败则抛出，外层捕获

        data = _try_parse(json_str)

        # LLM 有时直接返回数组 [{...}, {...}] 而不是 {"scenes": [...]}
        if isinstance(data, list):
            new_scenes = data
        elif isinstance(data, dict):
            new_scenes = data.get("scenes", [])
        else:
            new_scenes = []

        # 过滤掉非 dict 的项（防御性处理）
        new_scenes = [s for s in new_scenes if isinstance(s, dict)]

        # ── 5. 标准化字段 ────────────────────────────────────────────────────
        for i, s in enumerate(new_scenes):
            s.setdefault("id", f"scene_{i+1:02d}")
            s.setdefault("priority", "P1")
            s.setdefault("dimension", "")
            s.setdefault("steps_desc", [])
            s.setdefault("expected", "")
            s["recorded"] = False

        # ── 6. 追加模式：保留已录制场景，合并新场景 ──────────────────────────
        if append_mode:
            existing_plan = list(getattr(task, "scene_plan", None) or [])
            recorded_scenes = [s for s in existing_plan if s.get("recorded")]
            # 去重：新场景名与已有场景名相同则跳过
            existing_names_set = {s["name"] for s in existing_plan}
            fresh = [s for s in new_scenes if s["name"] not in existing_names_set]
            # 重新编号
            merged = recorded_scenes + fresh
            for i, s in enumerate(merged, 1):
                s["id"] = f"scene_{i:02d}"
            scenes = merged
        else:
            scenes = new_scenes

        # ── 7. 持久化 ────────────────────────────────────────────────────────
        task.scene_plan = scenes
        await db.commit()

        logger.info(
            f"[plan_scenes] task={task_id} {'追加' if append_mode else '生成'} "
            f"{len(scenes)} 个场景，已持久化"
        )
        return {"task_id": task_id, "url": url, "scenes": scenes, "append": append_mode}

    except Exception as e:
        logger.error(f"[plan_scenes] 场景规划失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"场景规划失败：{e}")


@router.get("/cases/scene-plan/{task_id}")
async def get_scene_plan(task_id: int,
                         db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """读取任务的 AI 场景规划结果（持久化版本）。"""
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
    scenes = getattr(task, "scene_plan", None) or []
    return {"task_id": task_id, "url": task.url or "", "scenes": scenes}


@router.patch("/cases/scene-plan/{task_id}/mark-recorded")
async def mark_scene_recorded(task_id: int, body: dict,
                               db: AsyncSession = Depends(get_db),
                               current_user: User = Depends(get_current_user)):
    """标记某个场景已录制（scene_id + recorded=True/False）。"""
    scene_id = body.get("scene_id")
    recorded = body.get("recorded", True)
    if not scene_id:
        raise HTTPException(status_code=400, detail="scene_id 不能为空")

    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")

    scenes = list(getattr(task, "scene_plan", None) or [])
    for s in scenes:
        if s.get("id") == scene_id:
            s["recorded"] = recorded
            break
    task.scene_plan = scenes
    await db.commit()
    return {"task_id": task_id, "scene_id": scene_id, "recorded": recorded}



@router.post("/cases/optimize/{task_id}")
async def optimize_cases(task_id: int, request: dict = None, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """分析已有用例覆盖缺口，追加补充用例。"""
    if request is None:
        request = {}
    ws_client_id: str = (request.get("ws_client_id") if isinstance(request, dict) else None) or "cases_gen"
    try:
        from skills.case_generator import case_generator as cg
        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        await check_access(db, task, current_user, "任务")
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

        async def _progress(pct: int, stage: str, case_count: int = 0):
            await ws_manager.broadcast(
                {"type": "cases_opt_progress", "percent": pct, "stage": stage, "case_count": case_count},
                client_id=ws_client_id,
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
                steps_json=case.get("steps_json") or [],
                expected_results=case.get("expected_results", ""),
                element_selector=case.get("element_selector", ""),
                source="ai_generated", enabled=True,
            ))
        await db.commit()
        return {"added": len(new_cases), "message": f"新增 {len(new_cases)} 条补充用例"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error optimizing cases: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases/coverage/{task_id}")
async def get_coverage(task_id: int, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    """返回当前任务的用例覆盖度指标。"""
    try:
        from skills.case_generator import case_generator as cg
        result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        await check_access(db, task, current_user, "任务")
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

@router.post("/cases/doc-diff-check/{task_id}")
async def webui_doc_diff_check(
    task_id: int, request: WebUIDiffCheckRequest, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from skills.case_generator import case_generator as cg
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
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


@router.post("/cases/incremental-update/{task_id}")
async def webui_incremental_update(
    task_id: int, request: WebUIIncrementalUpdateRequest, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import delete as sql_delete
    from skills.case_generator import case_generator as cg
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
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
                client_id=request.ws_client_id or "cases_gen",
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
    _ws_cid = request.ws_client_id or "cases_gen"

    async def _progress(pct: int, stage: str, case_count: int = 0):
        await ws_manager.broadcast(
            {"type": "cases_gen_progress", "percent": pct, "stage": stage, "case_count": case_count},
            client_id=_ws_cid,
        )

    try:
        upd = await cg.incremental_update(
            url=task.url or "", page_elements=task.page_elements or [],
            existing_cases=existing_cases, diff_result=diff_result,
            new_doc_content=new_content, progress_cb=_progress,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("WebUI 增量更新失败: {}", repr(e))
        raise HTTPException(status_code=500, detail="增量更新失败，请稍后重试")
    # ── UPSERT：retained_cases 保留 steps_json，new_cases 插入，deprecated 标记 ──
    # 先建原有用例名称→ORM对象映射，保留 steps_json 和录制结果
    _existing_res = await db.execute(select(TestCase).where(TestCase.task_id == task_id))
    _existing_map: dict = {c.name: c for c in _existing_res.scalars().all()}

    # retained_cases：已存在则 UPSERT（保留 steps_json）；否则 INSERT
    for case in upd["retained_cases"]:
        name = case.get("name", "未命名")
        if name in _existing_map:
            old = _existing_map[name]
            old.module = case.get("module", old.module)
            old.priority = case.get("priority", old.priority)
            old.preconditions = case.get("preconditions", old.preconditions)
            old.steps = case.get("steps", old.steps)
            old.expected_results = case.get("expected_results", old.expected_results)
            old.element_selector = case.get("element_selector", getattr(old, "element_selector", "") or "")
            old.deprecated = False
            old.enabled = True
            # steps_json 不动：保留已录制 / 已编辑的结构化步骤
        else:
            db.add(TestCase(
                task_id=task_id, name=name,
                module=case.get("module", "通用"), priority=case.get("priority", "P1"),
                preconditions=case.get("preconditions", ""), steps=case.get("steps", ""),
                expected_results=case.get("expected_results", ""),
                element_selector=case.get("element_selector", ""), enabled=True,
                deprecated=False, source=case.get("source", "ai_generated"),
            ))

    # new_cases：直接 INSERT
    for case in upd["new_cases"]:
        db.add(TestCase(
            task_id=task_id, name=case.get("name", "未命名"),
            module=case.get("module", "通用"), priority=case.get("priority", "P1"),
            preconditions=case.get("preconditions", ""), steps=case.get("steps", ""),
            expected_results=case.get("expected_results", ""),
            element_selector=case.get("element_selector", ""), enabled=True,
            deprecated=False, source=case.get("source", "ai_generated"),
        ))

    # deprecated_cases：已存在则标记 deprecated；否则 INSERT（标记）
    for case in upd["deprecated_cases"]:
        name = case.get("name", "未命名")
        if name in _existing_map:
            old = _existing_map[name]
            old.deprecated = True
        else:
            db.add(TestCase(
                task_id=task_id, name=name,
                module=case.get("module", "通用"), priority=case.get("priority", "P1"),
                preconditions=case.get("preconditions", ""), steps=case.get("steps", ""),
                expected_results=case.get("expected_results", ""),
                element_selector=case.get("element_selector", ""), enabled=True,
                deprecated=True, source=case.get("source", "ai_generated"),
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


@router.get("/cases/{case_id}/steps")
async def get_case_steps(case_id: int, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """返回单条用例的 steps_json（可视化步骤编辑器加载用）。"""
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    return {
        "id": case.id,
        "name": case.name,
        "steps_json": case.steps_json or [],
        "source": getattr(case, "source", "manual") or "manual",
    }


@router.put("/cases/{case_id}", response_model=CaseResponse)
async def update_case(case_id: int, request: CaseUpdateRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    # 通过关联任务校验工作空间访问权限
    task_result = await db.execute(select(TestTask).where(TestTask.id == case.task_id))
    task = task_result.scalar_one_or_none()
    if task:
        await check_access(db, task, current_user, "任务")

    update_data = request.model_dump(exclude_unset=True)

    # 如果更新了 steps_json，同步生成 steps 可读文本
    if "steps_json" in update_data and update_data["steps_json"]:
        from tools.action_schema import steps_to_description
        update_data["steps"] = steps_to_description(update_data["steps_json"])

    for key, value in update_data.items():
        setattr(case, key, value)
    await db.commit()
    await db.refresh(case)
    return CaseResponse(
        id=case.id, task_id=case.task_id, name=case.name, module=case.module,
        priority=case.priority, preconditions=case.preconditions,
        steps=case.steps, expected_results=case.expected_results,
        enabled=case.enabled, deprecated=getattr(case, "deprecated", False) or False,
        source=getattr(case, "source", "manual") or "manual",
    )


@router.delete("/cases/{case_id}")
async def delete_case(case_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete
    result = await db.execute(select(TestCase).where(TestCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    # 通过关联任务校验工作空间访问权限
    task_result = await db.execute(select(TestTask).where(TestTask.id == case.task_id))
    task = task_result.scalar_one_or_none()
    if task:
        await check_access(db, task, current_user, "任务")
    await db.execute(delete(TestCase).where(TestCase.id == case_id))
    await db.commit()
    return {"message": "Case deleted"}


# ── 用例自我修正 & 覆盖率补全 ─────────────────────────────────────────────────
@router.post("/cases/self-correct/{task_id}")
async def self_correct_cases(
    task_id: int,
    request: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    用例自我修正：分析执行失败的用例，AI 自动修正 selector/步骤后返回。
    请求体：{"failed_cases": [...], "ws_client_id": "..."}
    """
    task_result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
    failed_cases = request.get("failed_cases", [])
    if not failed_cases:
        raise HTTPException(status_code=400, detail="请提供需要修正的失败用例列表")
    ws_client_id = request.get("ws_client_id") or "cases_correct"

    from skills.case_generator import CaseGenerator
    cg = CaseGenerator()
    page_elements = task.page_elements or []

    async def _progress(pct: int, stage: str, case_count: int = 0):
        await ws_manager.broadcast(
            {"type": "cases_correct_progress", "percent": pct, "stage": stage, "case_count": case_count},
            client_id=ws_client_id,
        )

    corrected = await cg.self_correct_cases(
        failed_cases=failed_cases,
        page_elements=page_elements,
        url=task.url,
        progress_cb=_progress,
    )
    stats = {
        "total": len(corrected),
        "high": sum(1 for c in corrected if c.get("confidence") == "high"),
        "medium": sum(1 for c in corrected if c.get("confidence") == "medium"),
        "low": sum(1 for c in corrected if c.get("confidence") == "low"),
    }
    return {"corrected": corrected, "stats": stats}


@router.post("/cases/fill-gaps/{task_id}")
async def fill_coverage_gaps(
    task_id: int,
    request: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """覆盖率补全：分析元素覆盖缺口，生成补充用例。"""
    task_result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
    existing_cases = request.get("existing_cases", [])
    execution_results = request.get("execution_results", [])
    ws_client_id = request.get("ws_client_id") or "cases_gap"

    from skills.case_generator import CaseGenerator
    cg = CaseGenerator()
    page_elements = task.page_elements or []

    async def _progress(pct: int, stage: str, case_count: int = 0):
        await ws_manager.broadcast(
            {"type": "cases_gap_progress", "percent": pct, "stage": stage, "case_count": case_count},
            client_id=ws_client_id,
        )

    new_cases = await cg.fill_coverage_gaps(
        existing_cases=existing_cases,
        execution_results=execution_results,
        page_elements=page_elements,
        url=task.url,
        document_data=task.document_path,
        progress_cb=_progress,
    )
    return {"new_cases": new_cases, "gap_count": len(new_cases)}


@router.post("/cases/auto-fix/{task_id}")
async def auto_fix_cases(
    task_id: int,
    request: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一键自动修正+补全：先修正失败用例，再分析覆盖缺口生成补充用例。"""
    task_result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
    failed_cases = request.get("failed_cases", [])
    existing_cases = request.get("existing_cases", [])
    execution_results = request.get("execution_results", [])
    ws_client_id = request.get("ws_client_id") or "auto_fix"

    from skills.case_generator import CaseGenerator
    cg = CaseGenerator()
    page_elements = task.page_elements or []

    async def _progress(pct: int, stage: str, case_count: int = 0):
        await ws_manager.broadcast(
            {"type": "cases_auto_fix_progress", "percent": pct, "stage": stage, "case_count": case_count},
            client_id=ws_client_id,
        )

    corrected = []
    if failed_cases:
        corrected = await cg.self_correct_cases(
            failed_cases=failed_cases,
            page_elements=page_elements,
            url=task.url,
            progress_cb=lambda p, s, c=0: _progress(p // 2, s, c),
        )

    new_cases = []
    if existing_cases:
        new_cases = await cg.fill_coverage_gaps(
            existing_cases=existing_cases,
            execution_results=execution_results,
            page_elements=page_elements,
            url=task.url,
            document_data=task.document_path,
            progress_cb=lambda p, s, c=0: _progress(50 + p // 2, s, c),
        )

    await _progress(100, f"修正完成：{len(corrected)} 条修正 + {len(new_cases)} 条补充", len(corrected) + len(new_cases))
    return {
        "corrected": corrected,
        "new_cases": new_cases,
        "stats": {"corrected_count": len(corrected), "gap_count": len(new_cases)},
    }


@router.get("/cases/latest-failed/{task_id}")
async def get_latest_failed_cases(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定任务最近一次执行的失败用例列表（用于「修正失败用例」功能）。
    同时返回全部执行结果（含 case_id + status）供表格高亮显示。"""
    from sqlalchemy import desc
    task_result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")

    report_result = await db.execute(
        select(TestReport)
        .where(TestReport.task_id == task_id)
        .order_by(desc(TestReport.created_at))
        .limit(1)
    )
    report = report_result.scalar_one_or_none()
    if not report:
        return {"failed_cases": [], "report_id": None, "summary": None, "execution_results": []}

    summary = report.summary or {}
    failed_cases = summary.get("failed_cases", [])

    # 查询该报告关联的 TestResult 记录（按时间范围匹配最近一次执行）
    from tools.database import TestResult as TR
    execution_results = []
    if report.created_at:
        # 取最近一次执行前后10秒内的结果
        from datetime import timedelta
        window_start = report.created_at - timedelta(seconds=30)
        results_result = await db.execute(
            select(TR)
            .where(TR.task_id == task_id, TR.start_time >= window_start)
            .order_by(TR.start_time)
        )
        trs = results_result.scalars().all()
        execution_results = [
            {
                "case_id": tr.case_id,
                "case_name": "",
                "status": tr.status,
                "error_message": tr.error_message,
                "duration": tr.duration,
            }
            for tr in trs
        ]

    # 如果没有 TestResult（旧数据），回退使用 report.details 匹配
    if not execution_results and report.details:
        execution_results = report.details

    return {
        "failed_cases": failed_cases,
        "report_id": report.id,
        "execution_results": execution_results,
        "summary": {
            "total": report.total_cases,
            "passed": report.passed,
            "failed": report.failed,
            "pass_rate": report.pass_rate,
            "created_at": _fmt_cst(report.created_at),
            "finished_at": _fmt_cst(report.finished_at) if report.finished_at else _fmt_cst(report.created_at),
        },
    }


# ── 执行 & 报告 ───────────────────────────────────────────────────────────────

async def _run_execution_bg(
    report_id: int, task_id: int, task_name: str,
    task_url: str, case_dicts: list, case_ids, browser: str,
    workspace_id: int = None,
):
    """后台执行测试，通过 WebSocket 推送进度，完成后写回数据库。"""
    from tools.database import async_session_maker, TestResult as TR
    total_cases = len(case_dicts)
    try:
        # ── 通知前端开始执行 ──────────────────────────────────────────────────────
        await ws_manager.broadcast_to_workspace({
            "type": "execution_started",
            "report_id": report_id,
            "total_cases": total_cases,
        }, workspace_id)

        # ── 直接调用 execute_batch，不经过 uitest_agent 的全局 state.cases ──
        # 避免并发执行同一 task_id 时 state.cases 被互相覆盖的竞态问题
        from skills.test_executor import test_executor as _executor

        async def _progress_cb(progress_data):
            await ws_manager.broadcast_to_workspace(
                {"type": "case_complete", **progress_data}, workspace_id
            )

        results = await _executor.execute_batch(
            cases=case_dicts,
            url=task_url,
            browser_type=browser,
            screenshots_dir="./screenshots",
            progress_callback=_progress_cb,
            task_id=task_id,
        )

        passed  = sum(1 for r in results if r.get("status") == "passed" and r.get("case_id") is not None)
        failed  = sum(1 for r in results if r.get("status") == "failed" and r.get("case_id") is not None)
        skipped = sum(1 for r in results if r.get("status") == "skipped" and r.get("case_id") is not None)
        # 过滤掉预检/连通性测试结果用于统计
        real_results = [r for r in results if r.get("case_id") is not None]
        pass_rate = (passed / len(real_results) * 100) if real_results else 0

        def _safe_parse_steps(logs_val):
            """安全解析 logs → steps 列表，防止非标准数据导致崩溃。"""
            if logs_val is None:
                return []
            if isinstance(logs_val, list):
                return logs_val
            if isinstance(logs_val, str) and logs_val.strip():
                try:
                    return json.loads(logs_val)
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    logger.warning(f"Failed to parse steps JSON: {e}")
                    return []
            return []

        details = [
            {"id": idx, "case_name": r.get("case_name", "Unknown"),
             "status": r.get("status", "unknown"), "duration": round(r.get("duration", 0) or 0, 2),
             "error_message": r.get("error_message"), "screenshot": r.get("screenshot_path"),
             "start_time": r.get("start_time"), "end_time": r.get("end_time"),
             "steps": _safe_parse_steps(r.get("logs"))}
            for idx, r in enumerate(results, 1)
        ]
        summary = {
            "total": len(real_results), "passed": passed, "failed": failed, "skipped": skipped,
            "pass_rate": round(pass_rate, 2),
            "total_duration": round(sum(r.get("duration", 0) for r in real_results), 2),
            "failed_cases": [
                {"case_name": r.get("case_name"), "error": r.get("error_message", ""),
                 "duration": r.get("duration", 0)}
                for r in results if r.get("status") == "failed"
            ],
            "executed_at": datetime.utcnow().isoformat(),
        }
        async with async_session_maker() as db:
            try:
                res = await db.execute(select(TestReport).where(TestReport.id == report_id))
                report = res.scalar_one_or_none()
                if report:
                    report.summary    = summary
                    report.details    = details
                    report.pass_rate  = round(pass_rate, 2)
                    report.total_cases = len(real_results)
                    report.passed     = passed
                    report.failed     = failed
                    report.skipped    = skipped
                    report.finished_at = datetime.utcnow()  # 执行完成时间
                    for r in results:
                        if not r.get("case_id"):
                            continue
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
                    logger.info(f"[Execution] Report {report_id} saved: {len(real_results)} results, {passed}/{failed}/{skipped} p/f/s")
                else:
                    logger.error(f"[Execution] Report {report_id} not found in DB!")
            except Exception as db_err:
                logger.error(f"[Execution] DB commit failed for report {report_id}: {db_err}", exc_info=True)
                await db.rollback()
                raise
        # 执行完成事件（前端重置进度条、停止计时器）
        await ws_manager.broadcast_to_workspace({
            "type": "execution_completed",
            "report_id": report_id,
        }, workspace_id)
        # 保存完成事件（含汇总数据）
        await ws_manager.broadcast_to_workspace({
            "type": "execution_saved",
            "report_id": report_id,
            "summary": summary
        }, workspace_id)
    except Exception as e:
        logger.error(f"Background execution failed: {e}", exc_info=True)
        try:
            async with async_session_maker() as _ses:
                _r = await _ses.execute(select(TestReport).where(TestReport.id == report_id))
                _rep = _r.scalar_one_or_none()
                if _rep:
                    _rep.summary = {"status": "error", "error": str(e), "total": len(case_dicts), "passed": 0, "failed": 0, "pass_rate": 0}
                    _rep.pass_rate = 0
                    await _ses.commit()
        except Exception:
            pass
        await ws_manager.broadcast_to_workspace({
            "type": "execution_error",
            "report_id": report_id,
            "error": str(e)
        }, workspace_id)
    finally:
        # 无论成功/失败，释放执行锁
        async with _running_tasks_lock:
            _running_tasks.discard(task_id)


@router.post("/execute")
async def execute_cases(
    request: ExecuteRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ── 防止同一 task 重复并发执行 ────────────────────────────────────────────
    async with _running_tasks_lock:
        if request.task_id in _running_tasks:
            raise HTTPException(status_code=409,
                                detail="该任务正在执行中，请等待完成后再触发")
        _running_tasks.add(request.task_id)

    try:
        result = await db.execute(select(TestCase).where(TestCase.task_id == request.task_id))
        cases = result.scalars().all()
        if request.case_ids:
            cases = [c for c in cases if c.id in request.case_ids]
        cases = [c for c in cases if not getattr(c, "deprecated", False)]
        case_dicts = [
            {"id": c.id, "name": c.name, "module": c.module, "priority": c.priority,
             "preconditions": c.preconditions, "steps": c.steps,
             "expected_results": c.expected_results,
             "element_selector": getattr(c, "element_selector", ""),
             "steps_json": getattr(c, "steps_json", None)}
            for c in cases
        ]
        task_result = await db.execute(select(TestTask).where(TestTask.id == request.task_id))
        task = task_result.scalar_one_or_none()
        if not task:
            async with _running_tasks_lock:
                _running_tasks.discard(request.task_id)
            raise HTTPException(status_code=404, detail="任务不存在")
        await check_access(db, task, current_user, "任务")
        task_url  = task.url  if task else ""
        task_name = task.name if task else f"Task {request.task_id}"
        report = TestReport(
            task_id=request.task_id, name=f"{task_name} - 测试报告",
            summary={}, details=[], pass_rate=0, total_cases=len(case_dicts),
            passed=0, failed=0, skipped=0,
            created_by=current_user.username,
            project_id=task.project_id,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)
        background_tasks.add_task(
            _run_execution_bg,
            report_id=report.id, task_id=request.task_id, task_name=task_name,
            task_url=task_url, case_dicts=case_dicts, case_ids=request.case_ids, browser=request.browser,
            workspace_id=task.project_id,
        )
        return {"report_id": report.id, "status": "running", "total": len(case_dicts),
                "message": f"开始执行 {len(case_dicts)} 个用例，请通过 WebSocket 接收进度"}
    except HTTPException:
        async with _running_tasks_lock:
            _running_tasks.discard(request.task_id)
        raise
    except Exception:
        async with _running_tasks_lock:
            _running_tasks.discard(request.task_id)
        raise


@router.get("/reports", response_model=List[ReportResponse])
async def list_reports(workspace_id: int = None, task_id: int = None, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(TestReport).order_by(TestReport.created_at.desc())
    f = await workspace_filter_members(db, TestReport, workspace_id, current_user)
    if f is not None:
        stmt = stmt.where(f)
    if task_id:
        stmt = stmt.where(TestReport.task_id == task_id)
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
            created_at=_fmt_cst(r.created_at),
            finished_at=_fmt_cst(r.finished_at) if r.finished_at else _fmt_cst(r.created_at),
            browser=r.browser or "chromium",
        )
        for r in reports
    ]


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report_by_id(report_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    await check_access(db, report, current_user, "报告")
    return ReportResponse(
        task_id=report.task_id, task_name=report.name,
        summary=json.loads(report.summary) if isinstance(report.summary, str) else (report.summary or {}),
        html_path=report.report_path or "", report_id=report.id,
        total_cases=report.total_cases or 0, passed=report.passed or 0,
        failed=report.failed or 0, skipped=report.skipped or 0, pass_rate=report.pass_rate or 0,
        details=json.loads(report.details) if isinstance(report.details, str) else (report.details or []),
        created_at=_fmt_cst(report.created_at),
        finished_at=_fmt_cst(report.finished_at) if report.finished_at else _fmt_cst(report.created_at),
        browser=report.browser or "chromium",
    )


@router.get("/reports/{report_id}/export")
async def export_report(report_id: int, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    from fastapi.responses import HTMLResponse
    from urllib.parse import quote
    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    await check_access(db, report, current_user, "报告")
    summary  = json.loads(report.summary) if isinstance(report.summary, str) else (report.summary  or {})
    details  = json.loads(report.details)  if isinstance(report.details, str)  else (report.details  or [])
    task_name  = report.name or f"报告 {report_id}"
    created_at = _fmt_cst(report.created_at)
    # 统计数字以 summary JSON 为准
    s_total    = summary.get("total") or len(details)
    s_passed   = summary.get("passed", 0)
    s_failed   = summary.get("failed", 0)
    s_skipped  = summary.get("skipped", 0)
    s_rate     = round(summary.get("pass_rate", 0), 1)
    s_duration = round(summary.get("total_duration", 0), 2)
    s_pr_color = "green" if s_rate >= 80 else "red"
    details_rows = ""
    for detail in details:
        status_map = {"passed": ("success", "通过"), "failed": ("danger", "失败"), "skipped": ("warning", "跳过")}
        cls, label = status_map.get(detail.get("status", ""), ("secondary", detail.get("status", "-")))
        err = _html.escape(str((detail.get("error_message") or "-")[:120]))
        case_name = _html.escape(str(detail.get('case_name', '-')))
        shot = detail.get("screenshot", "")
        if shot:
            data_uri = _screenshot_data_uri(shot)
            shot_cell = (
                f'<td><a href="{data_uri}" target="_blank" style="display:inline-block">'
                f'<img src="{data_uri}" style="max-width:120px;max-height:80px;border-radius:4px;'
                f'border:1px solid #e8e8e8;cursor:pointer" title="点击查看原图" /></a></td>'
            )
        else:
            shot_cell = "<td style='color:#ccc'>-</td>"
        details_rows += f"""
        <tr>
            <td>{detail.get('id','')}</td><td>{case_name}</td>
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
    <div class="card"><div class="num blue">{s_total}</div><div class="lbl">总用例数</div></div>
    <div class="card"><div class="num green">{s_passed}</div><div class="lbl">通过</div></div>
    <div class="card"><div class="num red">{s_failed}</div><div class="lbl">失败</div></div>
    <div class="card"><div class="num orange">{s_skipped}</div><div class="lbl">跳过</div></div>
    <div class="card"><div class="num {s_pr_color}">{s_rate}%</div><div class="lbl">通过率</div></div>
    <div class="card"><div class="num">{s_duration}s</div><div class="lbl">总耗时</div></div>
  </div>
  <div class="section"><h2>用例执行详情</h2>
    <table><thead><tr><th>序号</th><th>用例名称</th><th>状态</th><th>耗时</th><th>错误信息</th><th>截图</th></tr></thead>
    <tbody>{details_rows}</tbody></table>
  </div>
</div></body></html>"""
    encoded_name = quote(task_name.replace("/", "_") + ".html", safe="")
    return HTMLResponse(content=html, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"})


@router.get("/reports/{report_id}/progress")
async def get_report_progress(report_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取报告执行进度（用于页面切换后恢复进度条状态）"""
    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    await check_access(db, report, current_user, "报告")

    # 检查是否仍在执行中：summary 为空且创建时间在 30 分钟内视为 running
    is_running = False
    if report.summary is None or report.summary == {}:
        import datetime as _dt
        age = (_dt.datetime.utcnow() - report.created_at.replace(tzinfo=None)).total_seconds()
        if age < 1800:  # 30 分钟内
            is_running = True

    return {
        "report_id": report.id,
        "is_running": is_running,
        "total_cases": report.total_cases or 0,
        "passed": report.passed or 0,
        "failed": report.failed or 0,
        "details": report.details or [],
    }


@router.get("/reports/{report_id}/pdf")
async def export_report_pdf(report_id: int, db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    """将 UI 自动化测试报告导出为 PDF（永远从 DB 现场重建，数据最新最准确）。"""
    from fastapi.responses import Response
    from urllib.parse import quote
    from tools.pdf_exporter import html_to_pdf

    # ── 1. 查报告 ──────────────────────────────────────────────────────────────
    result = await db.execute(select(TestReport).where(TestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    await check_access(db, report, current_user, "报告")

    # ── 2. 查关联任务（补充 URL / 浏览器 / 环境等字段）──────────────────────
    task_result = await db.execute(select(TestTask).where(TestTask.id == report.task_id))
    task = task_result.scalar_one_or_none()

    # ── 3. 基本元数据 ──────────────────────────────────────────────────────────
    task_name  = report.name or f"报告_{report_id}"
    now        = datetime.now(_TZ_CST).strftime("%Y-%m-%d %H:%M:%S")
    created_at = _fmt_cst(report.created_at)   # 报告创建时间（CST）
    task_url   = (task.url   if task else "") or ""
    browser    = (task.browser if task else "") or "chromium"
    env        = (task.environment if task else "") or "test"
    executor   = report.created_by or "—"

    # ── 4. 统计数据：优先取 summary JSON（执行结束后写入的正本）──────────────
    summary        = json.loads(report.summary) if isinstance(report.summary, str) else (report.summary or {})
    details        = json.loads(report.details) if isinstance(report.details, str) else (report.details or [])
    total          = summary.get("total") or report.total_cases or len(details)
    passed         = summary.get("passed", 0) if summary.get("passed") is not None else (report.passed or 0)
    failed         = summary.get("failed", 0) if summary.get("failed") is not None else (report.failed or 0)
    skipped        = summary.get("skipped", 0) if summary.get("skipped") is not None else (report.skipped or 0)
    pass_rate      = round(summary.get("pass_rate") if summary.get("pass_rate") is not None else (report.pass_rate or 0), 1)
    total_duration = round(summary.get("total_duration") or 0, 2)
    failed_cases   = summary.get("failed_cases") or []

    # ── 5. 从 details 推算真实执行时间段（start_time 最小值 → end_time 最大值）──
    def _parse_iso(s):
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(_TZ_CST)
        except Exception:
            return None

    start_times = [_parse_iso(d.get("start_time")) for d in details]
    end_times   = [_parse_iso(d.get("end_time"))   for d in details]
    start_times = [t for t in start_times if t]
    end_times   = [t for t in end_times   if t]
    exec_start  = min(start_times).strftime("%Y-%m-%d %H:%M:%S") if start_times else created_at
    exec_end    = max(end_times).strftime("%Y-%m-%d %H:%M:%S")   if end_times   else "—"

    # ── 6. 颜色 & 样式辅助 ────────────────────────────────────────────────────
    pr_color   = "#52c41a" if pass_rate >= 80 else ("#fa8c16" if pass_rate >= 60 else "#ff4d4f")
    pr_bg      = "#f6ffed" if pass_rate >= 80 else ("#fffbe6" if pass_rate >= 60 else "#fff1f0")

    # ── 7. 构建用例详情行 ──────────────────────────────────────────────────────
    rows = ""
    for d in details:
        st  = d.get("status", "")
        lbl = {"passed": "✓ 通过", "failed": "✗ 失败", "skipped": "⊘ 跳过"}.get(st, st)
        st_color  = {"passed": "#389e0d", "failed": "#cf1322", "skipped": "#ad6800"}.get(st, "#666")
        st_bg     = {"passed": "#f6ffed", "failed": "#fff1f0", "skipped": "#fffbe6"}.get(st, "#fafafa")
        err       = (d.get("error_message") or "—")[:400]
        dur       = d.get("duration", 0)
        # 时间列
        d_start   = _parse_iso(d.get("start_time"))
        d_end     = _parse_iso(d.get("end_time"))
        time_str  = d_start.strftime("%H:%M:%S") if d_start else "—"
        # 截图列
        shot = d.get("screenshot", "")
        if shot:
            data_uri = _screenshot_data_uri(shot)
            shot_td = (
                f"<td style='text-align:center;padding:4px 8px'>"
                f"<a href='{data_uri}' target='_blank'>"
                f"<img src='{data_uri}' style='max-width:96px;max-height:64px;"
                f"border-radius:4px;border:1px solid #e8e8e8;display:block;margin:0 auto'/>"
                f"</a></td>"
            )
        else:
            shot_td = "<td style='color:#ccc;text-align:center'>—</td>"

        rows += (
            f"<tr>"
            f"<td style='color:#aaa;text-align:center;width:36px'>{d.get('id','')}</td>"
            f"<td style='font-weight:500;min-width:120px'>{d.get('case_name','-')}</td>"
            f"<td style='width:64px'><span style='padding:2px 10px;border-radius:10px;font-size:11px;"
            f"font-weight:600;background:{st_bg};color:{st_color}'>{lbl}</span></td>"
            f"<td style='width:56px;text-align:right;color:#666'>{dur} s</td>"
            f"<td style='width:72px;color:#888;font-size:11px'>{time_str}</td>"
            f"<td style='font-size:11px;color:#888;word-break:break-all'>{err}</td>"
            f"{shot_td}"
            f"</tr>"
        )

    # ── 8. 失败用例摘要块 ──────────────────────────────────────────────────────
    failed_block = ""
    if failed_cases:
        failed_items = "".join(
            f"<li style='margin:5px 0;color:#cf1322'>"
            f"<b>{fc.get('case_name','—')}</b>"
            f"<span style='color:#888;font-size:11px;margin-left:8px'>{str(fc.get('error',''))[:200]}</span>"
            f"</li>"
            for fc in failed_cases[:20]
        )
        failed_block = f"""
<div class="section">
  <div class="sec-hdr"><span class="sec-icon">⚠️</span>失败用例摘要</div>
  <ul style="list-style:none;padding:0;margin:0">{failed_items}</ul>
</div>"""

    # ── 9. 拼 HTML ─────────────────────────────────────────────────────────────
    empty_row = f'<tr><td colspan="7" style="text-align:center;color:#aaa;padding:32px">暂无执行数据</td></tr>'
    html_str = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{task_name}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
      color:#1a1a1a;font-size:13px;line-height:1.65;background:#fff}}

/* ── 封面 ── */
.cover{{background:linear-gradient(140deg,#0f2544 0%,#1a3d6e 55%,#0d5c8f 100%);color:#fff;padding:52px 56px 44px}}
.cover-badge{{font-size:10px;letter-spacing:3px;opacity:.45;margin-bottom:14px;text-transform:uppercase}}
.cover h1{{font-size:26px;font-weight:700;margin-bottom:4px;line-height:1.3}}
.cover-sub{{font-size:13px;opacity:.55;margin-bottom:28px}}
.cover-stats{{display:flex;gap:0;margin:0 -1px}}
.cs{{flex:1;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);
     padding:14px 12px;text-align:center;margin:0 1px;border-radius:6px}}
.cs .n{{font-size:26px;font-weight:700;line-height:1}}
.cs .l{{font-size:10px;opacity:.55;margin-top:4px}}
.cover-meta{{font-size:11px;opacity:.38;margin-top:20px;line-height:1.8}}

/* ── 正文 ── */
.body{{padding:32px 48px 40px}}
.section{{margin-bottom:28px}}
.sec-hdr{{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:700;color:#0f2544;
          padding-bottom:10px;border-bottom:2px solid #e8edf2;margin-bottom:16px}}
.sec-icon{{font-size:16px}}

/* ── 信息卡 ── */
.info-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.info-item{{background:#f7f9fc;border:1px solid #e4eaf0;border-radius:6px;padding:10px 14px}}
.info-label{{font-size:11px;color:#8a9ab0;margin-bottom:3px}}
.info-value{{font-size:13px;color:#1a2a3a;font-weight:500;word-break:break-all}}

/* ── 通过率大数字 ── */
.rate-row{{display:flex;align-items:center;gap:24px;margin-bottom:20px}}
.rate-circle{{width:90px;height:90px;border-radius:50%;display:flex;flex-direction:column;
              align-items:center;justify-content:center;border:5px solid {pr_color};flex-shrink:0}}
.rate-pct{{font-size:22px;font-weight:700;color:{pr_color};line-height:1}}
.rate-lbl{{font-size:10px;color:#8a9ab0;margin-top:2px}}
.stat-bars{{flex:1;display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px}}
.sb{{background:#f7f9fc;border:1px solid #e4eaf0;border-radius:6px;padding:12px;text-align:center}}
.sb .n{{font-size:22px;font-weight:700;line-height:1;margin-bottom:4px}}
.sb .l{{font-size:10px;color:#8a9ab0}}

/* ── 表格 ── */
table{{width:100%;border-collapse:collapse}}
th,td{{padding:8px 10px;border:1px solid #e8edf2;text-align:left;font-size:12px;vertical-align:middle}}
th{{background:#f0f4f8;font-weight:600;color:#445566;white-space:nowrap}}
tr:nth-child(even) td{{background:#fafbfd}}
tr:hover td{{background:#f0f7ff}}

/* ── 页脚 ── */
.footer{{text-align:center;color:#b0bcc8;font-size:10px;padding:20px 0 8px;
         border-top:1px solid #eaeff4;margin-top:8px}}

@media print{{
  body{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
  .cover{{page-break-after:always}}
}}
</style></head><body>

<!-- ══ 封面 ══════════════════════════════════════════════════════════════ -->
<div class="cover">
  <div class="cover-badge">UI Automation Report</div>
  <h1>{task_name}</h1>
  <div class="cover-sub">UI 自动化测试报告</div>
  <div class="cover-stats">
    <div class="cs"><div class="n">{total}</div><div class="l">总用例</div></div>
    <div class="cs"><div class="n" style="color:#73d13d">{passed}</div><div class="l">通过</div></div>
    <div class="cs"><div class="n" style="color:#ff7875">{failed}</div><div class="l">失败</div></div>
    <div class="cs"><div class="n" style="color:#ffc53d">{skipped}</div><div class="l">跳过</div></div>
    <div class="cs"><div class="n" style="color:{'#73d13d' if pass_rate>=80 else ('#ffc53d' if pass_rate>=60 else '#ff7875')}">{pass_rate}%</div><div class="l">通过率</div></div>
    <div class="cs"><div class="n">{total_duration}s</div><div class="l">总耗时</div></div>
  </div>
  <div class="cover-meta">
    执行开始：{exec_start} &nbsp;|&nbsp; 执行结束：{exec_end}<br>
    目标地址：{task_url or '—'} &nbsp;|&nbsp; 浏览器：{browser} &nbsp;|&nbsp; 环境：{env}<br>
    执行人：{executor} &nbsp;|&nbsp; 导出时间：{now}（北京时间）
  </div>
</div>

<!-- ══ 正文 ══════════════════════════════════════════════════════════════ -->
<div class="body">

  <!-- 执行信息 -->
  <div class="section">
    <div class="sec-hdr"><span class="sec-icon">📋</span>执行信息</div>
    <div class="info-grid">
      <div class="info-item"><div class="info-label">目标地址</div><div class="info-value">{task_url or '—'}</div></div>
      <div class="info-item"><div class="info-label">浏览器 / 环境</div><div class="info-value">{browser} / {env}</div></div>
      <div class="info-item"><div class="info-label">执行开始</div><div class="info-value">{exec_start}</div></div>
      <div class="info-item"><div class="info-label">执行结束</div><div class="info-value">{exec_end}</div></div>
      <div class="info-item"><div class="info-label">报告生成</div><div class="info-value">{created_at}</div></div>
      <div class="info-item"><div class="info-label">执行人</div><div class="info-value">{executor}</div></div>
    </div>
  </div>

  <!-- 执行统计 -->
  <div class="section">
    <div class="sec-hdr"><span class="sec-icon">📊</span>执行统计</div>
    <div class="rate-row">
      <div class="rate-circle">
        <div class="rate-pct">{pass_rate}%</div>
        <div class="rate-lbl">通过率</div>
      </div>
      <div class="stat-bars">
        <div class="sb"><div class="n" style="color:#1677ff">{total}</div><div class="l">总用例数</div></div>
        <div class="sb"><div class="n" style="color:#52c41a">{passed}</div><div class="l">通过</div></div>
        <div class="sb"><div class="n" style="color:#ff4d4f">{failed}</div><div class="l">失败</div></div>
        <div class="sb"><div class="n" style="color:#faad14">{skipped}</div><div class="l">跳过</div></div>
      </div>
    </div>
  </div>

  {failed_block}

  <!-- 用例详情 -->
  <div class="section">
    <div class="sec-hdr"><span class="sec-icon">🔍</span>用例执行详情</div>
    <table>
      <thead>
        <tr>
          <th style="width:36px">#</th>
          <th>用例名称</th>
          <th style="width:64px">结果</th>
          <th style="width:52px">耗时</th>
          <th style="width:68px">开始时间</th>
          <th>错误信息</th>
          <th style="width:106px">截图</th>
        </tr>
      </thead>
      <tbody>{rows if rows else empty_row}</tbody>
    </table>
  </div>

</div>
<div class="footer">本报告由 AI 测试平台自动生成 &nbsp;·&nbsp; 导出时间：{now}（北京时间）</div>
</body></html>"""

    try:
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
        raise HTTPException(status_code=404, detail="报告不存在")
    await check_access(db, report, current_user, "报告")
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
        raise HTTPException(status_code=404, detail="报告不存在")
    await check_access(db, report, current_user, "报告")
    return ReportResponse(
        task_id=report.task_id, task_name=report.name,
        summary=json.loads(report.summary) if isinstance(report.summary, str) else (report.summary or {}),
        html_path=report.report_path or "", report_id=report.id,
        total_cases=report.total_cases or 0, passed=report.passed or 0,
        failed=report.failed or 0, skipped=report.skipped or 0, pass_rate=report.pass_rate or 0,
        details=json.loads(report.details) if isinstance(report.details, str) else (report.details or []),
        created_at=_fmt_cst(report.created_at),
        finished_at=_fmt_cst(report.finished_at) if report.finished_at else _fmt_cst(report.created_at),
        browser=report.browser or "chromium",
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
    raise HTTPException(status_code=404, detail="技能不存在")


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
                raise HTTPException(status_code=404, detail="文件不存在")
            return {"content": target.read_text(encoding="utf-8"), "path": path}
    raise HTTPException(status_code=404, detail="技能不存在")


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
    raise HTTPException(status_code=404, detail="技能不存在")


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

    # 根据 API URL 判断是否 Anthropic，优先用匹配的端点格式
    is_anthropic = "anthropic.com" in test_api_url
    if is_anthropic:
        candidates = [
            (f"{test_api_url}/v1/messages",
             {"x-api-key": test_api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
             {"model": test_model, "max_tokens": 10, "messages": [{"role": "user", "content": "reply: ok"}]}),
            (f"{test_api_url}/v1/chat/completions",
             {"Authorization": f"Bearer {test_api_key}", "Content-Type": "application/json"},
             {"model": test_model, "messages": [{"role": "user", "content": "reply: ok"}], "max_tokens": 10}),
        ]
    else:
        candidates = [
            (f"{test_api_url}/v1/chat/completions",
             {"Authorization": f"Bearer {test_api_key}", "Content-Type": "application/json"},
             {"model": test_model, "messages": [{"role": "user", "content": "reply: ok"}], "max_tokens": 10}),
            (f"{test_api_url}/v1/messages",
             {"x-api-key": test_api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
             {"model": test_model, "max_tokens": 10, "messages": [{"role": "user", "content": "reply: ok"}]}),
        ]

    last_err = "连接失败"
    # 每个端点最多等 15 秒，两个端点合计不超过 30 秒，前端 60s 超时足够
    async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
        for endpoint, headers, body in candidates:
            try:
                resp = await client.post(endpoint, headers=headers, json=body)
            except Exception as e:
                last_err = f"请求异常: {e}"
                continue
            if resp.status_code not in (200, 201):
                ct = resp.headers.get("content-type", "")
                if "html" in ct or resp.text.lstrip().startswith("<"):
                    status_hints = {
                        403: "403 Forbidden —— 服务器拒绝访问，可能原因：① 当前服务器 IP 被 Anthropic 地区限制，需使用中转代理；② API Key 已失效",
                        401: "401 Unauthorized —— API Key 无效或已过期，请检查 Key 是否正确",
                        429: "429 Too Many Requests —— 请求频率超限或账户余额不足",
                        404: "404 Not Found —— API 地址不正确，请确认 URL 格式",
                    }
                    last_err = status_hints.get(resp.status_code, f"HTTP {resp.status_code} 错误，服务器返回了 HTML 页面")
                else:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
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


# ── 任务级环境变量（TaskEnvVar） ──────────────────────────────────────────────

@router.get("/tasks/{task_id}/env-vars")
async def list_env_vars(task_id: int, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    task_result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if task:
        await check_access(db, task, current_user, "任务")
    result = await db.execute(select(TaskEnvVar).where(TaskEnvVar.task_id == task_id))
    rows = result.scalars().all()
    return [
        {"id": r.id, "key": r.key,
         "value": "***" if r.is_secret else r.value,
         "is_secret": r.is_secret}
        for r in rows
    ]


@router.post("/tasks/{task_id}/env-vars")
async def upsert_env_var(task_id: int, body: dict,
                         db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """新增或更新单个变量（key 相同则覆盖）。"""
    task_result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if task:
        await check_access(db, task, current_user, "任务")
    key       = body.get("key", "").strip()
    value     = body.get("value", "")
    is_secret = bool(body.get("is_secret", False))
    if not key:
        raise HTTPException(status_code=400, detail="key 不能为空")
    result = await db.execute(
        select(TaskEnvVar).where(TaskEnvVar.task_id == task_id, TaskEnvVar.key == key)
    )
    var = result.scalar_one_or_none()
    if var:
        var.value     = value
        var.is_secret = is_secret
    else:
        var = TaskEnvVar(task_id=task_id, key=key, value=value, is_secret=is_secret)
        db.add(var)
    await db.commit()
    await db.refresh(var)
    return {"id": var.id, "key": var.key, "is_secret": var.is_secret}


@router.delete("/tasks/{task_id}/env-vars/{var_id}")
async def delete_env_var(task_id: int, var_id: int,
                         db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete as sql_delete
    task_result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if task:
        await check_access(db, task, current_user, "任务")
    await db.execute(
        sql_delete(TaskEnvVar).where(TaskEnvVar.id == var_id, TaskEnvVar.task_id == task_id)
    )
    await db.commit()
    return {"message": "deleted"}


@router.delete("/env-vars/{var_id}")
async def delete_env_var_by_id(var_id: int,
                                db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(get_current_user)):
    """按 var_id 直接删除环境变量（前端简化调用路径）。"""
    from sqlalchemy import delete as sql_delete
    # 通过 TaskEnvVar.task_id 追溯 task 并校验工作空间权限
    var_result = await db.execute(select(TaskEnvVar).where(TaskEnvVar.id == var_id))
    env_var = var_result.scalar_one_or_none()
    if env_var:
        task_result = await db.execute(select(TestTask).where(TestTask.id == env_var.task_id))
        task = task_result.scalar_one_or_none()
        if task:
            await check_access(db, task, current_user, "任务")
    await db.execute(sql_delete(TaskEnvVar).where(TaskEnvVar.id == var_id))
    await db.commit()
    return {"message": "deleted"}


# ── 录制端点 ──────────────────────────────────────────────────────────────────
# 每个 task_id 同时只允许一个录制 session，防止多 session 互相收到对方步骤事件
_active_recording_tasks: set = set()
_active_recording_lock = asyncio.Lock()


# ── 元素别名库 CRUD ───────────────────────────────────────────────────────────

@router.get("/tasks/{task_id}/element-aliases")
async def list_element_aliases(task_id: int,
                                db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(get_current_user)):
    """列出任务下所有元素别名。"""
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
    rows = (await db.execute(
        select(ElementAlias).where(ElementAlias.task_id == task_id)
        .order_by(ElementAlias.created_at)
    )).scalars().all()
    return [{"id": r.id, "name": r.name, "selectors": r.selectors or [],
             "description": r.description or ""} for r in rows]


@router.post("/tasks/{task_id}/element-aliases")
async def create_element_alias(task_id: int, body: dict,
                                db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(get_current_user)):
    """新建元素别名。"""
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="别名名称不能为空")
    selectors = body.get("selectors") or []
    if not selectors:
        raise HTTPException(status_code=400, detail="至少填写一个 selector")
    alias = ElementAlias(
        task_id=task_id, name=name,
        selectors=selectors,
        description=body.get("description", ""),
        created_by=current_user.username,
    )
    db.add(alias)
    await db.commit()
    await db.refresh(alias)
    return {"id": alias.id, "name": alias.name, "selectors": alias.selectors,
            "description": alias.description or ""}


@router.put("/tasks/{task_id}/element-aliases/{alias_id}")
async def update_element_alias(task_id: int, alias_id: int, body: dict,
                                db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(get_current_user)):
    """更新元素别名。"""
    result = await db.execute(
        select(ElementAlias).where(ElementAlias.id == alias_id,
                                    ElementAlias.task_id == task_id)
    )
    alias = result.scalar_one_or_none()
    if not alias:
        raise HTTPException(status_code=404, detail="别名不存在")
    if "name" in body and body["name"]:
        alias.name = body["name"].strip()
    if "selectors" in body:
        alias.selectors = body["selectors"] or []
    if "description" in body:
        alias.description = body.get("description", "")
    await db.commit()
    return {"id": alias.id, "name": alias.name, "selectors": alias.selectors,
            "description": alias.description or ""}


@router.delete("/tasks/{task_id}/element-aliases/{alias_id}")
async def delete_element_alias(task_id: int, alias_id: int,
                                db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(get_current_user)):
    """删除元素别名。"""
    from sqlalchemy import delete as sql_delete
    await db.execute(
        sql_delete(ElementAlias).where(ElementAlias.id == alias_id,
                                        ElementAlias.task_id == task_id)
    )
    await db.commit()
    return {"message": "已删除"}


@router.post("/recording/start")
async def recording_start(body: dict,
                           db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    """
    异步启动录制：立即返回 session_id，Chrome 在后台启动。
    启动完成后通过 WebSocket rec_{task_id} 推送 recording_ready 消息。
    """
    from skills.recorder import start_recording
    from api.websocket_manager import ws_manager as _ws
    import secrets as _secrets

    task_id      = int(body.get("task_id", 0))
    url          = body.get("url", "")
    browser_type = body.get("browser_type", "chromium")
    if not url:
        raise HTTPException(status_code=400, detail="url 不能为空")

    if task_id:
        task_result = await db.execute(select(TestTask).where(TestTask.id == task_id))
        task = task_result.scalar_one_or_none()
        if task:
            await check_access(db, task, current_user, "任务")

    # 同一任务只允许一个录制 session
    async with _active_recording_lock:
        if task_id and task_id in _active_recording_tasks:
            raise HTTPException(status_code=409,
                                detail="该任务已有录制会话正在进行，请先停止再重新录制")
        if task_id:
            _active_recording_tasks.add(task_id)

    # 预生成 session_id，立即返回给前端，不等 Chrome 启动
    session_id = _secrets.token_hex(8)

    async def _push(msg: dict):
        await _ws.broadcast(msg, client_id=f"rec_{task_id}")

    async def _start_bg():
        """后台异步启动 Chrome，就绪后推送 recording_ready。"""
        try:
            real_session_id = await start_recording(task_id, url, browser_type, _push, session_id=session_id)
            # 启动成功，通知前端
            await _ws.broadcast(
                {"type": "recording_ready", "session_id": real_session_id, "task_id": task_id},
                client_id=f"rec_{task_id}",
            )
        except Exception as e:
            import traceback
            full_tb = traceback.format_exc()
            logger.error(f"[Recording] 录制启动失败: {type(e).__name__}: {e}\n{full_tb}")
            # 启动失败，通知前端并释放锁
            await _ws.broadcast(
                {"type": "recording_failed", "task_id": task_id, "error": str(e)},
                client_id=f"rec_{task_id}",
            )
            async with _active_recording_lock:
                _active_recording_tasks.discard(task_id)

    import asyncio as _asyncio
    _asyncio.create_task(_start_bg())

    return {"session_id": session_id, "status": "starting", "task_id": task_id}


@router.post("/recording/stop")
async def recording_stop(body: dict,
                          current_user: User = Depends(get_current_user)):
    """停止录制，返回 ActionStep 列表。支持 session_id 或 task_id 两种方式定位会话。"""
    from skills.recorder import stop_recording, _sessions
    session_id = body.get("session_id", "")

    # 如果没有 session_id，尝试通过 task_id 查找当前会话
    if not session_id:
        task_id = body.get("task_id")
        if task_id:
            for sid, sess in list(_sessions.items()):
                if sess.task_id == int(task_id):
                    session_id = sid
                    break
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id 不能为空，或找不到对应 task_id 的录制会话")
    # 停止前先记录 task_id，用于释放锁
    task_id_to_release = None
    if session_id in _sessions:
        task_id_to_release = _sessions[session_id].task_id
    try:
        result = await stop_recording(session_id)
        return {
            "session_id": session_id,
            "steps": result["steps"],
            "count": len(result["steps"]),
            "page_elements": result.get("page_elements", [])
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        # 无论成功/失败，释放录制锁
        if task_id_to_release:
            async with _active_recording_lock:
                _active_recording_tasks.discard(task_id_to_release)


@router.get("/recording/status/{session_id}")
async def recording_status(session_id: str,
                            current_user: User = Depends(get_current_user)):
    """查询录制会话状态（前端轮询或 WS 断线后恢复用）。"""
    from skills.recorder import get_session_status
    return get_session_status(session_id)


@router.post("/recording/save")
async def recording_save(body: dict,
                          db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    """将录制结果（ActionStep[]）保存为新用例。

    前端传 task_id + steps；后端自动在该任务下新建一条用例，
    steps 同时写入 steps_json（结构化执行引擎用）和 steps（可读文本）。
    录制步骤会经过智能补全（断言/wait）和 AI 健壮化（selector 多候选 + 评级）。
    """
    from tools.action_schema import steps_to_description
    from skills.recorder import enrich_recorded_steps, generate_case_name, generate_expected_results
    from skills.step_hardener import harden_and_enrich
    task_id = int(body.get("task_id", 0))
    steps   = body.get("steps", [])
    page_title = body.get("page_title", "")
    name    = body.get("name", "")

    if not task_id:
        raise HTTPException(status_code=400, detail="task_id 不能为空")
    if not steps:
        raise HTTPException(status_code=400, detail="steps 不能为空")

    task_result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")

    # ── 步骤处理流水线 ──
    # 1. 智能补全：断言 + wait + 名称 + 预期结果（原有逻辑）
    enriched_steps = enrich_recorded_steps(steps, page_title)
    if not name:
        name = generate_case_name(enriched_steps, page_title)
    expected = generate_expected_results(enriched_steps)

    # 2. AI 健壮化：selector 多候选推导 + 评级 + 关键操作后断言插入
    try:
        enriched_steps = await harden_and_enrich(enriched_steps, use_ai=True)
    except Exception as _he:
        logger.warning(f"[recording/save] 健壮化失败（静默跳过）: {_he}")

    # 将 ActionStep 列表转换为可读文本，存入 steps 字段（兼容旧版报告显示）
    steps_text = steps_to_description(enriched_steps)

    case = TestCase(
        task_id=task_id,
        name=name,
        module="录制",
        priority="P1",
        steps=steps_text,
        steps_json=enriched_steps,
        expected_results=expected,
        enabled=True,
        source="recorded",
        created_by=current_user.username,
        project_id=task.project_id,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return {"case_id": case.id, "steps_count": len(enriched_steps), "message": f"录制步骤已保存为用例「{name}」"}


# ── 多浏览器并行执行 ──────────────────────────────────────────────────────────

@router.post("/execute/multi-browser")
async def execute_multi_browser(
    body: dict, background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """多浏览器并行执行：每个浏览器独立生成一条 TestReport。"""
    from skills.parallel_runner import run_multi_browser_bg

    task_id  = int(body.get("task_id", 0))
    browsers = body.get("browsers", ["chromium"])
    case_ids = body.get("case_ids") or None

    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")

    # 查用例
    stmt = select(TestCase).where(TestCase.task_id == task_id,
                                   TestCase.deprecated == False)
    if case_ids:
        stmt = stmt.where(TestCase.id.in_(case_ids))
    cases_result = await db.execute(stmt)
    cases = cases_result.scalars().all()
    if not cases:
        raise HTTPException(status_code=400, detail="没有可执行的用例")

    case_dicts = [
        {"id": c.id, "name": c.name, "module": c.module,
         "steps_json": c.steps_json or [], "steps": c.steps or "",
         "expected_results": c.expected_results or "",
         "element_selector": getattr(c, "element_selector", "") or ""}
        for c in cases
    ]

    # 读取环境变量
    env_result = await db.execute(
        select(TaskEnvVar).where(TaskEnvVar.task_id == task_id)
    )
    env_vars = {r.key: r.value for r in env_result.scalars().all()}

    # 为每个浏览器预建一条 TestReport（状态 running）
    report_ids = {}
    for browser in browsers:
        report = TestReport(
            task_id=task_id,
            name=f"{task.name} [{browser}] - 测试报告",
            summary={}, details=[], pass_rate=0,
            total_cases=len(case_dicts),
            passed=0, failed=0, skipped=0,
            browser=browser,
            created_by=current_user.username,
            project_id=task.project_id,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)
        report_ids[browser] = report.id

    background_tasks.add_task(
        run_multi_browser_bg,
        task_id=task_id,
        task_url=task.url,
        task_name=task.name,
        case_dicts=case_dicts,
        browsers=browsers,
        env_vars=env_vars,
        report_ids=report_ids,
        workspace_id=task.project_id,
    )

    return {
        "status": "running",
        "browsers": browsers,
        "report_ids": report_ids,
        "total_cases": len(case_dicts),
        "message": f"已启动 {len(browsers)} 个浏览器并行执行 {len(case_dicts)} 条用例",
    }


# ── pytest 脚本导出 ───────────────────────────────────────────────────────────

@router.post("/tasks/{task_id}/export/pytest")
async def export_pytest(task_id: int, body: dict = None,
                        db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    """生成 pytest + Playwright 脚本，直接作为文件流返回（zip 包）。"""
    from skills.pytest_exporter import export_task_from_db
    from fastapi.responses import FileResponse
    from urllib.parse import quote
    import zipfile, io

    include_secrets = bool((body or {}).get("include_secrets", False))
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
    try:
        script_path = await export_task_from_db(task_id, db, include_secrets)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成脚本失败: {e}")

    # 将 .py 文件打包成 zip 流返回（前端 responseType: 'blob' 直接下载）
    py_path = Path(script_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(py_path, py_path.name)
    buf.seek(0)

    from fastapi.responses import StreamingResponse
    safe_name = quote(f"pytest_task_{task_id}.zip", safe="")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


@router.get("/tasks/{task_id}/export/download")
async def download_pytest_script(task_id: int,
                                  db: AsyncSession = Depends(get_db),
                                  current_user: User = Depends(get_current_user)):
    """下载最近一次导出的 pytest 脚本文件。"""
    from fastapi.responses import FileResponse
    from urllib.parse import quote
    result = await db.execute(select(TestTask).where(TestTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await check_access(db, task, current_user, "任务")
    script_path = Path(f"reports/pytest_exports/pytest_{task_id}.py")
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="脚本文件不存在，请先调用 /export/pytest 生成")
    safe_name = quote(f"{task.name}_pytest.py".replace("/", "_"), safe="")
    return FileResponse(
        path=str(script_path),
        media_type="text/x-python",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )
