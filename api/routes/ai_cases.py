"""
AI 文档驱动用例生成路由
  - /ai-cases/*  含 CRUD、diff-check、incremental-update、optimize、coverage
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict, Any, Optional
from pathlib import Path
from loguru import logger

from tools.database import get_db, AICaseFile
from api.websocket_manager import ws_manager

router = APIRouter()


# ── 公共响应构建 ──────────────────────────────────────────────────────────────

class AICaseGenerateRequest(BaseModel):
    task_name: str
    document_path: Optional[str] = None
    content: Optional[str] = None
    formats: List[str] = ["md", "xmind"]


class AICaseFileResponse(BaseModel):
    id: int
    task_name: str
    case_count: int
    has_md: bool
    has_xmind: bool
    modules: List[Dict[str, Any]] = []
    created_at: str = ""
    doc_hash: Optional[str] = None
    parent_id: Optional[int] = None
    diff_summary: Optional[str] = None
    record_status: str = "active"
    gen_status: str = "done"


class DiffCheckRequest(BaseModel):
    new_content: Optional[str] = None
    new_document_path: Optional[str] = None


class IncrementalUpdateRequest(BaseModel):
    new_content: Optional[str] = None
    new_document_path: Optional[str] = None
    diff: Optional[Dict[str, Any]] = None


import re as _re_step
_step_prefix = _re_step.compile(r'^\s*\d+\.\s*')


def _clean_steps(modules):
    cleaned = []
    for mod in (modules or []):
        mod = dict(mod)
        cases = []
        for case in mod.get("cases", []):
            case = dict(case)
            steps = case.get("steps", [])
            if isinstance(steps, list):
                case["steps"] = [_step_prefix.sub('', str(s)) for s in steps]
            cases.append(case)
        mod["cases"] = cases
        cleaned.append(mod)
    return cleaned


def _ai_case_response(record) -> AICaseFileResponse:
    modules = _clean_steps((record.cases_data or {}).get("modules", []))
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
        gen_status=getattr(record, "gen_status", "done") or "done",
    )


# ── 后台生成任务 ──────────────────────────────────────────────────────────────

async def _do_generate_bg(
    record_id: int,
    task_name: str,
    document_path: Optional[str],
    content: Optional[str],
    formats: List[str],
) -> None:
    """AI 用例后台生成任务：生成完成后写库并通过 WebSocket 推送结果。"""
    from tools.database import async_session_maker
    from skills.ai_case_generator import ai_case_generator

    async with async_session_maker() as bg_db:
        res = await bg_db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
        record = res.scalar_one_or_none()
        if not record:
            logger.error(f"_do_generate_bg: record_id={record_id} 不存在，任务中止")
            return

        async def _progress(pct: int, stage: str):
            await ws_manager.broadcast(
                {"type": "ai_gen_progress", "percent": pct, "stage": stage},
                client_id="ai_gen",
            )

        try:
            result = await ai_case_generator.generate(
                task_name=task_name,
                document_path=document_path,
                content=content,
                formats=formats,
                progress_cb=_progress,
                rag_source_id=record_id,
            )
            record.case_count  = result.get("case_count", 0)
            record.md_path     = result["files"].get("md")
            record.xmind_path  = result["files"].get("xmind")
            record.cases_data  = result.get("cases_data")
            record.doc_hash    = result.get("doc_hash")
            record.doc_content = result.get("doc_content")
            record.gen_status  = "done"
            await bg_db.commit()
            await bg_db.refresh(record)
            await ws_manager.broadcast(
                {"type": "ai_gen_done", "record_id": record_id,
                 "case_count": record.case_count, "task_name": task_name},
                client_id="ai_gen",
            )
            logger.info(f"AI 用例后台生成完成: record_id={record_id}，{record.case_count} 条")
        except Exception as e:
            record.gen_status = "failed"
            await bg_db.commit()
            logger.exception("AI 用例后台生成失败: record_id={}, err={}", record_id, repr(e))
            await ws_manager.broadcast(
                {"type": "ai_gen_progress", "percent": 0,
                 "stage": f"生成失败: {type(e).__name__}: {e}", "error": True},
                client_id="ai_gen",
            )


# ── 生成 / 列表 / 详情 / 下载 ─────────────────────────────────────────────────

@router.post("/ai-cases/generate", response_model=AICaseFileResponse)
async def generate_ai_cases(
    request: AICaseGenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    if not request.document_path and not request.content:
        raise HTTPException(status_code=400, detail="请提供文档路径或需求文本内容")
    placeholder = AICaseFile(
        task_name=request.task_name, case_count=0, cases_data=None, gen_status="generating",
    )
    db.add(placeholder)
    await db.commit()
    await db.refresh(placeholder)
    background_tasks.add_task(
        _do_generate_bg,
        record_id=placeholder.id, task_name=request.task_name,
        document_path=request.document_path, content=request.content, formats=request.formats,
    )
    return _ai_case_response(placeholder)


@router.get("/ai-cases", response_model=List[AICaseFileResponse])
async def list_ai_cases(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AICaseFile).order_by(AICaseFile.created_at.desc()))
    return [_ai_case_response(r) for r in result.scalars().all()]


@router.get("/ai-cases/{record_id}", response_model=AICaseFileResponse)
async def get_ai_case(record_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    return _ai_case_response(record)


@router.get("/ai-cases/{record_id}/download")
async def download_ai_case(record_id: int, format: str = "md", db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse
    from urllib.parse import quote
    from datetime import datetime
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    if format == "md":
        file_path, media_type, ext = record.md_path, "text/markdown", ".md"
    elif format == "xmind":
        file_path, media_type, ext = record.xmind_path, "application/octet-stream", ".xmind"
    else:
        raise HTTPException(status_code=400, detail="不支持的格式，请使用 md 或 xmind")
    if not file_path:
        raise HTTPException(status_code=404, detail=f"该记录未生成 {format} 文件")

    # 解析路径
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(__file__).parent.parent.parent / file_path

    # 文件不存在时，从 cases_data 重新生成
    if not p.exists():
        cases_data = record.cases_data
        if not cases_data or not cases_data.get("modules"):
            raise HTTPException(status_code=404, detail="文件已丢失且无法重新生成（用例数据为空）")
        try:
            from skills.ai_case_generator import ai_case_generator
            ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            if format == "md":
                p = await ai_case_generator._save_markdown(cases_data, record.task_name, ts)
                record.md_path = str(p)
            else:
                p = await ai_case_generator._save_xmind(cases_data, record.task_name, ts)
                record.xmind_path = str(p)
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(record, "md_path" if format == "md" else "xmind_path")
            await db.commit()
            logger.info(f"下载时文件不存在，已重新生成: record_id={record_id}, format={format}, path={p}")
        except Exception as e:
            logger.error(f"重新生成下载文件失败: record_id={record_id}, err={e}")
            raise HTTPException(status_code=500, detail=f"文件已丢失，重新生成失败: {e}")

    encoded = quote(record.task_name.replace("/", "_") + ext, safe="")
    return FileResponse(path=str(p), media_type=media_type,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"})


# ── 覆盖度分析 ────────────────────────────────────────────────────────────────

@router.get("/ai-cases/{record_id}/coverage")
async def get_ai_case_coverage(record_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    modules_data = (record.cases_data or {}).get("modules", [])
    all_cases = []
    for mod in modules_data:
        if all(c.get("status") == "deprecated" for c in mod.get("cases", []) if mod.get("cases")):
            continue
        for case in mod.get("cases", []):
            if case.get("status") != "deprecated":
                all_cases.append({**case, "_module": mod.get("name", "通用")})
    total = len(all_cases)
    if total == 0:
        return {"score": 0, "total": 0, "suggestions": ["当前无测试用例"]}
    priority_count = {"P0": 0, "P1": 0, "P2": 0}
    for c in all_cases:
        p = c.get("priority", "P1")
        priority_count[p] = priority_count.get(p, 0) + 1
    module_map: Dict[str, Dict] = {}
    for c in all_cases:
        m = c.get("_module", "通用")
        if m not in module_map:
            module_map[m] = {"total": 0, "P0": 0, "P1": 0, "P2": 0}
        p = c.get("priority", "P1")
        module_map[m]["total"] += 1
        module_map[m][p] = module_map[m].get(p, 0) + 1
    STANDARD_METHODS = ["等价类划分", "边界值分析", "判定表", "场景法", "错误推测", "状态转换"]
    used_methods = {m for c in all_cases for m in STANDARD_METHODS if m in (c.get("test_method") or "")}
    method_coverage = [{"name": m, "covered": m in used_methods} for m in STANDARD_METHODS]
    method_rate = round(len(used_methods) / len(STANDARD_METHODS) * 100)
    TYPES = ["功能测试", "性能测试", "兼容性测试"]
    type_count = {t: 0 for t in TYPES}
    for c in all_cases:
        for key in TYPES:
            if key in (c.get("type") or ""):
                type_count[key] += 1
                break
    p0_ratio = priority_count["P0"] / total
    score = max(0, min(100, round(
        len(used_methods) / len(STANDARD_METHODS) * 40
        + min(p0_ratio * 200, 30)
        + min(len(module_map) * 4, 20)
        + sum(1 for v in type_count.values() if v > 0) / len(TYPES) * 10
    )))
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
        "score": score, "total": total,
        "priority_distribution": priority_count,
        "module_distribution": [{"name": k, **v} for k, v in module_map.items()],
        "method_coverage": method_coverage, "method_rate": method_rate,
        "type_distribution": type_count, "suggestions": suggestions,
    }


# ── 优化 ──────────────────────────────────────────────────────────────────────

@router.post("/ai-cases/{record_id}/optimize", response_model=AICaseFileResponse)
async def optimize_ai_cases(record_id: int, db: AsyncSession = Depends(get_db)):
    from skills.ai_case_generator import ai_case_generator
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    cases_data = record.cases_data or {}
    if not cases_data.get("modules"):
        raise HTTPException(status_code=400, detail="该记录没有可优化的用例数据")

    async def _progress(pct: int, stage: str):
        await ws_manager.broadcast(
            {"type": "ai_gen_progress", "percent": pct, "stage": stage}, client_id="ai_gen",
        )

    try:
        opt_result = await ai_case_generator.optimize(
            task_name=record.task_name, cases_data=cases_data,
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

    record.cases_data = opt_result["cases_data"]
    record.case_count = opt_result["case_count"]
    if opt_result["files"].get("md"):
        record.md_path = opt_result["files"]["md"]
    if opt_result["files"].get("xmind"):
        record.xmind_path = opt_result["files"]["xmind"]
    await db.commit()
    await db.refresh(record)
    return _ai_case_response(record)


# ── 单条用例 CRUD ─────────────────────────────────────────────────────────────

@router.post("/ai-cases/{record_id}/cases", response_model=AICaseFileResponse)
async def add_ai_case_item(record_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    cases_data = dict(record.cases_data or {})
    modules = list(cases_data.get("modules", []))
    module_name = (data.get("module") or "通用").strip()
    target_mod = next((m for m in modules if m["name"] == module_name), None)
    if target_mod is None:
        target_mod = {"name": module_name, "cases": []}
        modules.append(target_mod)
    all_nums = []
    for mod in modules:
        for c in mod.get("cases", []):
            cid = c.get("id", "")
            if cid.upper().startswith("TC"):
                try:
                    all_nums.append(int(cid[2:]))
                except ValueError:
                    pass
    new_id = f"TC{max(all_nums, default=0) + 1:03d}"
    target_mod["cases"].append({
        "id": new_id, "name": data.get("name", "新用例"),
        "priority": data.get("priority", "P1"), "type": data.get("type", "功能测试"),
        "test_method": data.get("test_method", ""), "preconditions": data.get("preconditions", ""),
        "steps": data.get("steps", []), "expected": data.get("expected", ""),
    })
    cases_data["modules"] = modules
    record.cases_data = cases_data
    record.case_count = sum(len(m.get("cases", [])) for m in modules)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(record, "cases_data")
    await db.commit()
    await db.refresh(record)
    return _ai_case_response(record)


@router.put("/ai-cases/{record_id}/cases/{case_id}", response_model=AICaseFileResponse)
async def update_ai_case_item(record_id: int, case_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    cases_data = dict(record.cases_data or {})
    modules = list(cases_data.get("modules", []))
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
    updated_case = dict(modules[found_mod_idx]["cases"][found_case_idx])
    for field in ("name", "priority", "type", "test_method", "preconditions", "steps", "expected"):
        if field in data:
            updated_case[field] = data[field]
    new_module = (data.get("module") or "").strip()
    if new_module and new_module != modules[found_mod_idx]["name"]:
        modules[found_mod_idx]["cases"].pop(found_case_idx)
        target_mod = next((m for m in modules if m["name"] == new_module), None)
        if target_mod is None:
            target_mod = {"name": new_module, "cases": []}
            modules.append(target_mod)
        target_mod["cases"].append(updated_case)
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
    return _ai_case_response(record)


@router.delete("/ai-cases/{record_id}/cases/{case_id}", response_model=AICaseFileResponse)
async def delete_ai_case_item(record_id: int, case_id: str, db: AsyncSession = Depends(get_db)):
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
    modules = [m for m in modules if m.get("cases")]
    cases_data["modules"] = modules
    record.cases_data = cases_data
    record.case_count = sum(len(m.get("cases", [])) for m in modules)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(record, "cases_data")
    await db.commit()
    await db.refresh(record)
    return _ai_case_response(record)


@router.delete("/ai-cases/{record_id}")
async def delete_ai_case(record_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete as sql_delete
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    for path_str in [record.md_path, record.xmind_path]:
        if path_str:
            p = Path(path_str)
            if not p.is_absolute():
                p = Path(__file__).parent.parent.parent / path_str
            if p.exists():
                p.unlink(missing_ok=True)
    await db.execute(sql_delete(AICaseFile).where(AICaseFile.id == record_id))
    await db.commit()
    return {"message": "删除成功"}


# ── Diff 检测 ─────────────────────────────────────────────────────────────────

@router.post("/ai-cases/{record_id}/diff-check")
async def diff_check_ai_case(record_id: int, request: DiffCheckRequest, db: AsyncSession = Depends(get_db)):
    from skills.ai_case_generator import ai_case_generator
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    if not request.new_content and not request.new_document_path:
        raise HTTPException(status_code=400, detail="请提供新版文档路径或文本内容")
    if request.new_document_path:
        try:
            from tools.document_parser import document_parser
            parsed = await document_parser.parse(request.new_document_path)
            new_content = parsed.get("content", "")
            try:
                from bs4 import BeautifulSoup
                import re as _re
                soup = BeautifulSoup(new_content, "html.parser")
                for tag in soup(["script", "style", "head", "meta", "link"]):
                    tag.decompose()
                cleaned = _re.sub(r'\n{3,}', '\n\n', soup.get_text(separator="\n", strip=True)).strip()
                if len(cleaned) >= 200:
                    new_content = cleaned
            except Exception as _e:
                logger.debug(f"diff-check HTML 清洗跳过: {_e}")
            if len(new_content) > 100000:
                new_content = new_content[:100000]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"新文档解析失败: {e}")
    else:
        new_content = request.new_content or ""
    if not new_content.strip():
        raise HTTPException(status_code=400, detail="新文档内容为空")
    new_doc_hash = ai_case_generator._compute_doc_hash(new_content)
    old_doc_hash = record.doc_hash or ""
    if old_doc_hash and new_doc_hash == old_doc_hash:
        return {"has_change": False, "new_doc_hash": new_doc_hash, "old_doc_hash": old_doc_hash,
                "diff": None, "message": "文档内容未发生变化，无需更新用例"}
    old_content = record.doc_content or ""
    if not old_content:
        return {"has_change": True, "new_doc_hash": new_doc_hash, "old_doc_hash": old_doc_hash,
                "diff": None, "message": "旧版文档内容未保存，无法做精确 Diff，可直接重新生成"}
    existing_module_names = [
        m.get("name", "") for m in (record.cases_data or {}).get("modules", [])
        if m.get("name") and "废弃" not in m.get("name", "")
    ]
    try:
        diff_result = await ai_case_generator.analyze_document_diff(
            old_doc_content=old_content, new_doc_content=new_content,
            existing_module_names=existing_module_names,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"has_change": True, "new_doc_hash": new_doc_hash, "old_doc_hash": old_doc_hash, "diff": diff_result}


# ── 增量更新 ──────────────────────────────────────────────────────────────────

@router.post("/ai-cases/{record_id}/incremental-update", response_model=AICaseFileResponse)
async def incremental_update_ai_case(
    record_id: int, request: IncrementalUpdateRequest, db: AsyncSession = Depends(get_db),
):
    from skills.ai_case_generator import ai_case_generator
    result = await db.execute(select(AICaseFile).where(AICaseFile.id == record_id))
    old_record = result.scalar_one_or_none()
    if not old_record:
        raise HTTPException(status_code=404, detail="记录不存在")
    if not request.new_content and not request.new_document_path:
        raise HTTPException(status_code=400, detail="请提供新版文档路径或文本内容")
    if request.new_document_path:
        try:
            from tools.document_parser import document_parser
            parsed = await document_parser.parse(request.new_document_path)
            new_content = parsed.get("content", "")
            try:
                from bs4 import BeautifulSoup
                import re as _re
                soup = BeautifulSoup(new_content, "html.parser")
                for tag in soup(["script", "style", "head", "meta", "link"]):
                    tag.decompose()
                cleaned = _re.sub(r'\n{3,}', '\n\n', soup.get_text(separator="\n", strip=True)).strip()
                if len(cleaned) >= 200:
                    new_content = cleaned
            except Exception as _e:
                logger.debug(f"incremental-update HTML 清洗跳过: {_e}")
            if len(new_content) > 100000:
                new_content = new_content[:100000]
            p = Path(request.new_document_path)
            if "uploads" in p.parts and "documents" in p.parts:
                p.unlink(missing_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"新文档解析失败: {e}")
    else:
        new_content = request.new_content or ""
    if not new_content.strip():
        raise HTTPException(status_code=400, detail="新文档内容为空")

    diff_result = request.diff
    existing_module_names = [
        m.get("name", "") for m in (old_record.cases_data or {}).get("modules", [])
        if m.get("name") and "废弃" not in m.get("name", "")
    ]
    if not diff_result:
        old_content = old_record.doc_content or ""
        if not old_content:
            raise HTTPException(status_code=400, detail="旧版文档内容未保存，无法做精确 Diff。请直接重新生成。")
        try:
            diff_result = await ai_case_generator.analyze_document_diff(
                old_doc_content=old_content, new_doc_content=new_content,
                existing_module_names=existing_module_names,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    if not (diff_result.get("changed") or diff_result.get("added") or diff_result.get("removed")):
        raise HTTPException(status_code=400, detail="Diff 分析未发现任何模块变更，无需更新")

    async def _progress(pct: int, stage: str):
        await ws_manager.broadcast(
            {"type": "ai_gen_progress", "percent": pct, "stage": stage}, client_id="ai_gen",
        )

    formats = [f for f in ["md", "xmind"]
               if (f == "md" and old_record.md_path) or (f == "xmind" and old_record.xmind_path)]
    if not formats:
        formats = ["md", "xmind"]

    try:
        upd_result = await ai_case_generator.incremental_update(
            task_name=old_record.task_name, old_cases_data=old_record.cases_data or {},
            new_doc_content=new_content, diff_result=diff_result,
            formats=formats, progress_cb=_progress,
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

    old_record.record_status = "deprecated"
    await db.flush()

    new_record = AICaseFile(
        task_name=old_record.task_name, case_count=upd_result.get("case_count", 0),
        md_path=upd_result["files"].get("md"), xmind_path=upd_result["files"].get("xmind"),
        cases_data=upd_result.get("cases_data"), doc_hash=upd_result.get("doc_hash"),
        doc_content=upd_result.get("doc_content"), parent_id=old_record.id,
        diff_summary=upd_result.get("diff_summary"), record_status="active",
    )
    db.add(new_record)
    await db.commit()
    await db.refresh(new_record)

    if new_content:
        import asyncio as _asyncio
        from skills.rag import index_document as _index_doc
        _asyncio.create_task(_index_doc(new_record.id, "ai_case", new_content))

    logger.info(f"增量更新完成: 旧记录 #{old_record.id} → 新记录 #{new_record.id}，{new_record.case_count} 条")
    return _ai_case_response(new_record)
