"""
API路由定义
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
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
from tools.database import get_db, TestTask, TestCase, TestResult, TestReport
from agent.core import uitest_agent
from api.websocket_manager import ws_manager
from tools.config import settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "agent_state": uitest_agent.get_state()
    }


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


@router.post("/upload/document")
async def upload_document(file: UploadFile = File(...)):
    if file.size and file.size > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="File too large")

    upload_dir = Path("./uploads/documents")
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    file_path = upload_dir / filename

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

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
            enabled=c.enabled
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
        enabled=case.enabled
    )


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
        
        uitest_agent.state.page_elements = task.page_elements
        uitest_agent.state.current_task_id = task_id
        
        cases = await uitest_agent.generate_cases()
        
        for case in cases:
            db_case = TestCase(
                task_id=task_id,
                name=case.get("name", "Unnamed Case"),
                module=case.get("module", "通用"),
                priority=case.get("priority", "P1"),
                preconditions=case.get("preconditions", ""),
                steps=case.get("steps", ""),
                expected_results=case.get("expected_results", ""),
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
                enabled=c.enabled
            )
            for c in all_cases
        ]
    except Exception as e:
        logger.error(f"Error generating cases: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
        enabled=case.enabled
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


@router.post("/execute", response_model=ExecuteResponse)
async def execute_cases(
    request: ExecuteRequest,
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import select
    result = await db.execute(
        select(TestCase).where(TestCase.task_id == request.task_id)
    )
    cases = result.scalars().all()

    if request.case_ids:
        cases = [c for c in cases if c.id in request.case_ids]

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

    uitest_agent.state.cases = case_dicts
    
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

    results = await uitest_agent.execute_cases(
        case_ids=request.case_ids,
        browser_type=request.browser,
        url=task_url
    )

    for r in results:
        sp = r.get("screenshot_path")
        if sp and not sp.startswith("http"):
            r["screenshot_path"] = f"/screenshots/{Path(sp).name}"

    passed = sum(1 for r in results if r.get("status") == "passed")
    failed = sum(1 for r in results if r.get("status") == "failed")
    skipped = sum(1 for r in results if r.get("status") == "skipped")

    test_results = []
    for r in results:
        test_result = TestResult(
            task_id=request.task_id,
            case_id=r.get("case_id"),
            status=r.get("status"),
            start_time=datetime.fromisoformat(r["start_time"]) if r.get("start_time") else None,
            end_time=datetime.fromisoformat(r["end_time"]) if r.get("end_time") else None,
            duration=r.get("duration", 0),
            error_message=r.get("error_message"),
            screenshot_path=r.get("screenshot_path"),
            logs=r.get("logs")
        )
        test_results.append(test_result)
        db.add(test_result)

    pass_rate = (passed / len(results) * 100) if len(results) > 0 else 0

    details = []
    for idx, r in enumerate(results, 1):
        details.append({
            "id": idx,
            "case_name": r.get("case_name", "Unknown"),
            "status": r.get("status", "unknown"),
            "duration": round(r.get("duration", 0), 2),
            "error_message": r.get("error_message"),
            "screenshot": r.get("screenshot_path"),
            "start_time": r.get("start_time"),
            "end_time": r.get("end_time")
        })

    summary = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": round(pass_rate, 2),
        "total_duration": round(sum(r.get("duration", 0) for r in results), 2),
        "failed_cases": [
            {
                "case_name": r.get("case_name", "Unknown"),
                "error": r.get("error_message", "Unknown error"),
                "duration": r.get("duration", 0)
            }
            for r in results if r.get("status") == "failed"
        ]
    }

    report.summary = summary
    report.details = details
    report.pass_rate = round(pass_rate, 2)
    report.passed = passed
    report.failed = failed
    report.skipped = skipped

    import json
    report_path = None
    html_path = None
    try:
        report_data = await uitest_agent.generate_report(task_name)
        report.report_path = report_data.get("report_path")
        html_path = report_data.get("html_path")
    except Exception as e:
        logger.error(f"Failed to generate report file: {e}")

    await db.commit()

    return ExecuteResponse(
        total=len(results),
        passed=passed,
        failed=failed,
        skipped=skipped,
        results=results
    )


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
    test_executor.stop()
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
        {"id": "gpt-4", "name": "GPT-4", "provider": "OpenAI"},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "provider": "OpenAI"},
        {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "provider": "OpenAI"},
        {"id": "claude-3-opus", "name": "Claude 3 Opus", "provider": "Anthropic"},
        {"id": "claude-3-sonnet", "name": "Claude 3 Sonnet", "provider": "Anthropic"},
        {"id": "claude-3-haiku", "name": "Claude 3 Haiku", "provider": "Anthropic"},
        {"id": "gemini-pro", "name": "Gemini Pro", "provider": "Google"},
        {"id": "moonshot-v1-8k", "name": "Moonshot V1 8K", "provider": "Moonshot"},
        {"id": "moonshot-v1-32k", "name": "Moonshot V1 32K", "provider": "Moonshot"},
        {"id": "moonshot-v1-128k", "name": "Moonshot V1 128K", "provider": "Moonshot"},
        {"id": "deepseek-chat", "name": "DeepSeek Chat", "provider": "DeepSeek"},
        {"id": "qwen-turbo", "name": "Qwen Turbo", "provider": "Alibaba"},
        {"id": "qwen-plus", "name": "Qwen Plus", "provider": "Alibaba"},
        {"id": "qwen-max", "name": "Qwen Max", "provider": "Alibaba"},
        {"id": "yi-large", "name": "Yi Large", "provider": "01AI"},
    ]
    return {
        "current_model": settings.AI_MODEL,
        "current_api_url": settings.AI_API_URL,
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
    env_content = ""
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            env_content = f.read()

    updates = []
    if model:
        settings.AI_MODEL = model
        updates.append(f"AI_MODEL={model}")
        if "AI_MODEL" in env_content:
            env_content = f'AI_MODEL={model}\n'.join(env_content.split("AI_MODEL="))
        else:
            env_content += f"\nAI_MODEL={model}"

    if api_key:
        settings.AI_API_KEY = api_key
        updates.append("AI_API_KEY=***")
        if "AI_API_KEY" in env_content:
            env_content = env_content.replace(f"AI_API_KEY={api_key}", "AI_API_KEY=***")
        else:
            env_content += f"\nAI_API_KEY={api_key}"

    if api_url:
        settings.AI_API_URL = api_url
        updates.append(f"AI_API_URL={api_url}")
        if "AI_API_URL" in env_content:
            env_content = env_content.replace(f"AI_API_URL={api_url}", f"AI_API_URL={api_url}")
        else:
            env_content += f"\nAI_API_URL={api_url}"

    with open(env_path, 'w', encoding='utf-8') as f:
        f.write(env_content)

    return {
        "message": "LLM configuration updated",
        "model": settings.AI_MODEL,
        "api_url": settings.AI_API_URL
    }


@router.post("/llm/test")
async def test_llm_connection(request: LLMTestRequest):
    import httpx
    from tools.config import settings

    model = request.model
    api_key = request.api_key
    api_url = request.api_url

    test_model = model or settings.AI_MODEL
    test_api_url = api_url or settings.AI_API_URL
    test_api_key = api_key or settings.AI_API_KEY

    if not test_api_key:
        return {"success": False, "error": "API key is required"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{test_api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {test_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": test_model,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 10
                }
            )

            if response.status_code == 200:
                return {"success": True, "model": test_model, "message": "Connection successful"}
            else:
                return {
                    "success": False,
                    "error": f"API returned status {response.status_code}",
                    "detail": response.text[:200]
                }
    except Exception as e:
        return {"success": False, "error": str(e)}
