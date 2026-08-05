"""
接口自动化路由（接口测试 / 压测 / 代码分析 / 全局变量 / 测试计划）
  - /api-test/*
  - /global-vars/*
  - /test-plans/*
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, UploadFile, File
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


def _md_to_html(text: str) -> str:
    """将 AI 返回的 Markdown 文本转换为带样式的 HTML，用于 PDF 报告。

    支持：
      - # / ## / ### 标题
      - **bold**、*italic*、`code`
      - 数字列表（1. / 1、）、无序列表（- / * / •）含缩进嵌套
      - > 引用块
      - | 表格（含表头分隔行）
      - --- 分割线
      - 空行分段
    """
    import re, html as _html

    def fmt_inline(s: str) -> str:
        """行内格式：**bold**、*italic*、`code`。先转义再替换。"""
        s = _html.escape(s)
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:#1a1a2e">\1</strong>', s)
        s = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)',
                   r'<em style="color:#555;font-style:italic">\1</em>', s)
        s = re.sub(r'`(.+?)`',
                   r'<code style="background:#eef0f8;padding:1px 6px;border-radius:3px;'
                   r'font-size:11.5px;color:#0958d9;font-family:Consolas,monospace">\1</code>', s)
        return s

    def parse_table_row(line: str) -> list[str]:
        """把 | a | b | c | 拆成 ['a','b','c']，去掉首尾空管道符。"""
        cells = [c.strip() for c in line.strip().split('|')]
        # 去掉首尾空字符串（行首/行尾的 |）
        if cells and cells[0] == '':
            cells = cells[1:]
        if cells and cells[-1] == '':
            cells = cells[:-1]
        return cells

    def is_table_row(line: str) -> bool:
        return bool(re.match(r'\s*\|', line))

    def is_separator_row(line: str) -> bool:
        """表头与数据之间的分隔行，如 |---|:---:|---:|"""
        return bool(re.match(r'\s*\|[\s\-:|]+\|\s*$', line))

    def render_table(raw_rows: list[str]) -> str:
        """将连续的表格行渲染成 HTML <table>。"""
        rows   = [parse_table_row(r) for r in raw_rows if not is_separator_row(r)]
        if not rows:
            return ''
        thead_cells = rows[0]
        tbody_rows  = rows[1:]

        th_html = ''.join(
            f'<th style="background:#1d4ed8;color:#fff;padding:8px 12px;'
            f'text-align:left;font-size:12px;font-weight:600;'
            f'border:1px solid #2563eb;white-space:nowrap">'
            f'{fmt_inline(c)}</th>'
            for c in thead_cells
        )
        thead = f'<thead><tr>{th_html}</tr></thead>'

        tbody_html = ''
        for i, row in enumerate(tbody_rows):
            bg = '#ffffff' if i % 2 == 0 else '#f0f5ff'
            td_html = ''.join(
                f'<td style="padding:7px 12px;font-size:12px;color:#2d3748;'
                f'border:1px solid #dde8f8;background:{bg};vertical-align:top">'
                f'{fmt_inline(c)}</td>'
                for c in row
            )
            tbody_html += f'<tr>{td_html}</tr>'
        tbody = f'<tbody>{tbody_html}</tbody>'

        return (
            f'<div style="overflow-x:auto;margin:10px 0">'
            f'<table style="width:100%;border-collapse:collapse;'
            f'border-radius:6px;overflow:hidden;border:1px solid #c7d8f8">'
            f'{thead}{tbody}</table></div>'
        )

    # ── 预处理：先把原文按段落分成"表格块"和"普通块" ─────────────────────────
    lines = text.split('\n')
    out   = []
    in_ul = False
    table_buf: list[str] = []   # 正在积累的表格行

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append('</ul>')
            in_ul = False

    def flush_table():
        nonlocal table_buf
        if table_buf:
            out.append(render_table(table_buf))
            table_buf = []

    for line in lines:
        stripped = line.rstrip()

        # ── 表格行（含分隔行）
        if is_table_row(stripped):
            close_ul()
            table_buf.append(stripped)
            continue
        else:
            flush_table()

        # ── 分割线 ---
        if re.match(r'^-{3,}$', stripped) or re.match(r'^={3,}$', stripped):
            close_ul()
            out.append('<hr style="border:none;border-top:1px solid #dde3f0;margin:12px 0">')
            continue

        # ── ATX 标题 #、##、###
        m = re.match(r'^(#{1,3})\s+(.*)', stripped)
        if m:
            close_ul()
            lvl    = len(m.group(1))
            txt    = fmt_inline(m.group(2))
            size   = {1: '15px', 2: '14px', 3: '13px'}.get(lvl, '13px')
            mt     = '18px' if lvl == 1 else '13px'
            border = 'border-left:3px solid #3a7bd5;padding-left:9px;' if lvl <= 2 else ''
            bg     = 'background:rgba(58,123,213,.06);border-radius:3px;padding:3px 9px;' if lvl == 1 else ''
            out.append(
                f'<div style="margin:{mt} 0 6px;font-size:{size};font-weight:700;'
                f'color:#1a1a2e;{border}{bg}">{txt}</div>'
            )
            continue

        # ── 引用块 >
        m = re.match(r'^>\s?(.*)', stripped)
        if m:
            close_ul()
            txt = fmt_inline(m.group(1))
            out.append(
                f'<div style="border-left:3px solid #3a7bd5;background:#f0f5ff;'
                f'padding:6px 12px;margin:6px 0;border-radius:0 4px 4px 0;'
                f'font-size:13px;color:#3a4a6b;line-height:1.65">{txt}</div>'
            )
            continue

        # ── 数字列表 1. / 1、
        m = re.match(r'^(\s*)(\d+)[.、．\)]\s+(.*)', stripped)
        if m:
            close_ul()
            indent = len(m.group(1))
            num    = m.group(2)
            txt    = fmt_inline(m.group(3))
            ml     = 8 + indent * 16
            out.append(
                f'<div style="display:flex;align-items:flex-start;gap:8px;margin:5px 0 5px {ml}px">'
                f'<span style="min-width:20px;height:20px;border-radius:50%;background:#3a7bd5;color:#fff;'
                f'font-size:10px;font-weight:700;display:inline-flex;align-items:center;'
                f'justify-content:center;flex-shrink:0;margin-top:2px">{num}</span>'
                f'<span style="font-size:13px;line-height:1.7;color:#2d3748">{txt}</span></div>'
            )
            continue

        # ── 无序列表 - / * / •（含缩进嵌套）
        m = re.match(r'^(\s*)[-*•]\s+(.*)', stripped)
        if m:
            indent = len(m.group(1))
            txt    = fmt_inline(m.group(2))
            if not in_ul:
                out.append('<ul style="margin:4px 0 4px 24px;padding:0;list-style:none">')
                in_ul = True
            bullet_color = '#3a7bd5' if indent == 0 else '#84a4d4'
            pl = indent * 14
            out.append(
                f'<li style="display:flex;align-items:flex-start;gap:6px;'
                f'font-size:13px;line-height:1.7;color:#2d3748;margin:3px 0;padding-left:{pl}px">'
                f'<span style="color:{bullet_color};font-size:16px;line-height:1.4;flex-shrink:0">•</span>'
                f'<span>{txt}</span></li>'
            )
            continue

        close_ul()

        # ── 空行
        if not stripped:
            out.append('<div style="height:7px"></div>')
            continue

        # ── 普通段落
        out.append(
            f'<p style="margin:5px 0;font-size:13px;line-height:1.75;color:#2d3748">'
            f'{fmt_inline(stripped)}</p>'
        )

    flush_table()
    close_ul()
    return '\n'.join(out)

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
        "environments": p.environments or [],  # [{name, base_url}]
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
        "timeout_ms": c.timeout_ms,  # None=使用执行引擎默认值(30s)
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
        "created_by": r.created_by or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


def _plan_dict(p: TestPlan, steps: list = None) -> dict:
    return {
        "id": p.id, "name": p.name, "description": p.description or "",
        "project_id": p.project_id, "status": p.status or "pending",
        "proxy_url": p.proxy_url or "", "hosts_map": p.hosts_map or "",
        "webhook_token": p.webhook_token or "",   # 供前端展示触发 URL
        "cron_expr": p.cron_expr or "",
        "cron_enabled": bool(p.cron_enabled),
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
        "created_by": r.created_by or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


# ── 调试端点 ──────────────────────────────────────────────────────────────────

@router.get("/api-test/debug/claude")
async def debug_claude_subprocess(
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问调试接口")
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
    ws_id = data.get("workspace_id")
    if ws_id:
        await check_workspace_member(db, ws_id, current_user, "创建接口项目")
    proj = ApiProject(
        name=data.get("name", "未命名项目"), base_url=data.get("base_url", ""),
        description=data.get("description", ""), auth_type=data.get("auth_type", "none"),
        auth_config=data.get("auth_config"), global_headers=data.get("global_headers"),
        proxy_url=data.get("proxy_url", ""), hosts_map=data.get("hosts_map", ""),
        environments=data.get("environments"),
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
    if not projects:
        return []
    # 一次性批量查询所有项目的用例，避免 N+1
    project_ids = [p.id for p in projects]
    all_cases = (await db.execute(
        select(ApiCase)
        .where(ApiCase.project_id.in_(project_ids))
        .order_by(ApiCase.project_id, ApiCase.created_at)
    )).scalars().all()
    # Python 端按 project_id 分组
    from collections import defaultdict
    cases_by_project: dict = defaultdict(list)
    for c in all_cases:
        cases_by_project[c.project_id].append(_case_dict(c))
    return [
        {"project_id": p.id, "project_name": p.name, "cases": cases_by_project[p.id]}
        for p in projects
    ]


@router.put("/api-test/projects/{project_id}")
async def update_api_project(project_id: int, data: dict, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    for field in ("name", "base_url", "description", "auth_type", "auth_config", "global_headers",
                  "setup_cases", "auth_error_patterns", "proxy_url", "hosts_map", "environments"):
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
async def create_api_case(data: dict, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    project_id = data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id 不能为空")
    # 校验项目存在且用户是 workspace 成员
    proj = (await db.execute(select(ApiProject).where(ApiProject.id == project_id))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
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
async def update_api_case(case_id: int, data: dict, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    result = await db.execute(select(ApiCase).where(ApiCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    # 校验用例所属项目的访问权限
    proj = (await db.execute(select(ApiProject).where(ApiProject.id == case.project_id))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    for field in ("name", "module", "method", "path", "headers", "params", "body", "body_type",
                  "body_raw", "assertions", "var_extracts", "priority", "enabled", "description",
                  "timeout_ms"):
        if field in data:
            setattr(case, field, data[field])
    await db.commit()
    await db.refresh(case)
    return _case_dict(case)


@router.delete("/api-test/cases")
async def delete_api_cases(ids: List[int], db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    # 校验所有用例属于同一 workspace 且用户有权访问
    cases = (await db.execute(select(ApiCase).where(ApiCase.id.in_(ids)))).scalars().all()
    if not cases:
        raise HTTPException(status_code=404, detail="未找到指定用例")
    project_ids = set(c.project_id for c in cases)
    # 确保所有用例属于同一项目
    if len(project_ids) > 1:
        raise HTTPException(status_code=400, detail="只能批量删除同一项目的用例")
    proj_id = project_ids.pop()
    proj = (await db.execute(select(ApiProject).where(ApiProject.id == proj_id))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
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

        ws_cid = f"api_gen_{project_id}"

        async def progress_cb(pct, stage):
            await ws_manager.broadcast(
                {"type": "api_gen_progress", "percent": pct, "stage": stage}, client_id=ws_cid,
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
            await ws_manager.broadcast({"type": "api_gen_done", "count": len(cases)}, client_id=ws_cid)
            # 全局铃铛通知
            await ws_manager.broadcast_to_workspace(
                {"type": "cases_generated", "case_count": len(cases), "source": "api_test",
                 "message": f"接口用例生成完成，共 {len(cases)} 条"},
                workspace_id=proj.workspace_id,
            )
        except Exception as e:
            logger.error(f"API case generation failed: {e}", exc_info=True)
            await ws_manager.broadcast({"type": "api_gen_error", "message": "接口用例生成失败，请稍后重试"}, client_id=ws_cid)

    background_tasks.add_task(_bg)
    return {"message": "AI生成任务已启动，请通过 WebSocket 接收进度", "project_id": project_id, "ws_client_id": f"api_gen_{project_id}"}


@router.post("/api-test/projects/{project_id}/cases/import")
async def import_cases(
    project_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导入 Postman Collection v2.1 或 HAR 文件为接口用例。"""
    proj_r = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = proj_r.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("utf-8-sig", errors="replace")

    try:
        from skills.import_parser import parse_import_file
        cases = parse_import_file(content, file.filename or "", proj.base_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[import] 解析失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"解析失败: {e}")

    if not cases:
        raise HTTPException(status_code=400, detail="文件中没有解析到任何请求，请检查文件内容")

    created = []
    for c in cases:
        case = ApiCase(
            project_id=project_id,
            name=c.get("name", "未命名"),
            module=c.get("module", "导入"),
            method=c.get("method", "GET"),
            path=c.get("path", "/"),
            headers=c.get("headers"),
            params=c.get("params"),
            body=c.get("body"),
            body_type=c.get("body_type", "json"),
            body_raw=c.get("body_raw", ""),
            assertions=c.get("assertions"),
            var_extracts=None,
            priority=c.get("priority", "P1"),
            description=c.get("description", ""),
            enabled=True,
        )
        db.add(case)
        created.append(case)
    await db.commit()
    for case in created:
        await db.refresh(case)

    return {"imported": len(created), "message": f"成功导入 {len(created)} 条用例"}


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

        ws_cid = f"api_gen_{project_id}"

        async def progress_cb(pct, stage):
            await ws_manager.broadcast(
                {"type": "api_gen_progress", "percent": pct, "stage": stage}, client_id=ws_cid,
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
            await ws_manager.broadcast({"type": "api_gen_done", "count": len(cases)}, client_id=ws_cid)
            # 全局铃铛通知
            await ws_manager.broadcast_to_workspace(
                {"type": "cases_generated", "case_count": len(cases), "source": "api_test",
                 "message": f"接口用例生成完成，共 {len(cases)} 条"},
                workspace_id=proj.workspace_id,
            )
        except Exception as e:
            logger.error(f"代码用例生成失败: {e}", exc_info=True)
            await ws_manager.broadcast({"type": "api_gen_error", "message": "代码用例生成失败，请稍后重试"}, client_id=ws_cid)

    background_tasks.add_task(_bg)
    return {"message": "代码分析任务已启动", "project_id": project_id, "ws_client_id": f"api_gen_{project_id}"}


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
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("代码可行性分析失败: {}", repr(e))
        raise HTTPException(status_code=500, detail="代码可行性分析失败，请稍后重试")
    return report


@router.post("/api-test/projects/{project_id}/code-analyze/save-cases")
async def save_analyze_cases(
    project_id: int, data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
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
async def list_scripts(project_id: int = None, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    from sqlalchemy import or_
    stmt = select(CustomScript).order_by(CustomScript.id)
    if project_id is not None:
        # 校验用户有权访问该项目
        proj = (await db.execute(select(ApiProject).where(ApiProject.id == project_id))).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="项目不存在")
        await check_access(db, proj, current_user, "接口项目")
        stmt = stmt.where(or_(CustomScript.project_id == project_id, CustomScript.project_id == None))
    result = await db.execute(stmt)
    return [_script_dict(s) for s in result.scalars()]


@router.post("/api-test/scripts")
async def create_script(data: dict, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    pid = data.get("project_id")
    if pid:
        proj = (await db.execute(select(ApiProject).where(ApiProject.id == pid))).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="项目不存在")
        await check_access(db, proj, current_user, "接口项目")
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
    import re as _re
    from tools.llm_client import call_llm
    prompt    = (data.get("prompt") or "").strip()
    func_name = (data.get("func_name") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    if not settings.AI_API_KEY:
        raise HTTPException(status_code=400, detail="未配置 AI API Key，请先在 LLM 配置页面填写")
    available_modules = "hashlib, json, time, random, string, uuid, base64, os, re, requests"
    system_prompt = (
        f"你是一个资深 Python 工程师，专门为 API 接口测试框架编写参数生成脚本。\n\n"
        f"## 执行环境约束\n- 可用模块：{available_modules}\n- 函数接收可变参数 `*args`\n"
        "- 函数必须有返回值（return）\n- 禁止文件 IO、系统调用等危险操作\n\n"
        "## 代码规范\n1. 所有 import 写在函数内部\n2. 只输出纯 Python 代码\n3. 不要输出解释说明"
    )
    temperature = float(getattr(settings, "AI_TEMPERATURE", 0.3))
    try:
        code = await call_llm(
            system_prompt, prompt,
            max_tokens=1024, temperature=temperature, timeout_secs=60,
        )
        code = code.strip()
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
async def update_script(script_id: int, data: dict, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    result = await db.execute(select(CustomScript).where(CustomScript.id == script_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="脚本不存在")
    if s.project_id:
        proj = (await db.execute(select(ApiProject).where(ApiProject.id == s.project_id))).scalar_one_or_none()
        if proj:
            await check_access(db, proj, current_user, "接口项目")
    for field in ("name", "description", "code", "project_id"):
        if field in data:
            setattr(s, field, data[field])
    await db.commit()
    await db.refresh(s)
    return _script_dict(s)


@router.delete("/api-test/scripts/{script_id}")
async def delete_script(script_id: int, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    result = await db.execute(select(CustomScript).where(CustomScript.id == script_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="脚本不存在")
    if s.project_id:
        proj = (await db.execute(select(ApiProject).where(ApiProject.id == s.project_id))).scalar_one_or_none()
        if proj:
            await check_access(db, proj, current_user, "接口项目")
    await db.delete(s)
    await db.commit()
    return {"message": "已删除"}


# ── 单测执行 ──────────────────────────────────────────────────────────────────

@router.post("/api-test/projects/{project_id}/cases/{case_id}/data-driven")
async def execute_data_driven(
    project_id: int,
    case_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    background_tasks: BackgroundTasks = None,
):
    """
    CSV 数据驱动执行：上传 CSV 文件，每行作为一组参数执行同一个用例。
    首行为变量名，对应用例 params/body 中的 {{var:变量名}} 占位符。
    """
    proj_r = await db.execute(select(ApiProject).where(ApiProject.id == project_id))
    proj = proj_r.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")

    case_r = await db.execute(select(ApiCase).where(ApiCase.id == case_id, ApiCase.project_id == project_id))
    case = case_r.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("utf-8-sig", errors="replace")

    from skills.csv_driver import parse_csv_data
    try:
        rows = parse_csv_data(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV 解析失败: {e}")

    if not rows:
        raise HTTPException(status_code=400, detail="CSV 文件中没有数据行")
    if len(rows) > 500:
        raise HTTPException(status_code=400, detail="CSV 行数超过上限（500行）")

    proj_dict = _proj_dict(proj)
    case_dict = _case_dict(case)

    async def _bg():
        from skills.api_executor import api_executor
        from tools.database import async_session_maker
        from sqlalchemy import or_ as _or

        ws_cid = f"api_exec_{project_id}"

        async with async_session_maker() as s:
            sq = select(CustomScript).where(
                _or(CustomScript.project_id == project_id, CustomScript.project_id == None)
            )
            custom_scripts = [_script_dict(sc) for sc in (await s.execute(sq)).scalars()]

        # 每行数据注入 var_store，执行一次
        all_results = []
        for i, row in enumerate(rows):
            # 把 CSV 列名作为 var_store 传给执行器
            case_with_row = {**case_dict}
            summary = await api_executor.execute_cases(
                proj_dict, [case_with_row],
                progress_cb=None,
                custom_scripts=custom_scripts,
                extra_var_store=row,  # CSV 行数据注入
            )
            result = summary["results"][0] if summary["results"] else {}
            result["_csv_row"] = row
            result["_row_index"] = i + 1
            all_results.append(result)

        passed = sum(1 for r in all_results if r.get("status") == "passed")
        async with async_session_maker() as s:
            report = ApiTestReport(
                project_id=project_id, project_name=proj.name, report_type="data_driven",
                total=len(all_results), passed=passed, failed=len(all_results) - passed,
                summary={"pass_rate": round(passed / len(all_results) * 100, 1), "rows": len(rows)},
                details=all_results,
                created_by=current_user.username,
            )
            s.add(report)
            await s.commit()
            await s.refresh(report)

        await ws_manager.broadcast(
            {"type": "api_exec_done", "total": len(all_results), "passed": passed,
             "failed": len(all_results) - passed,
             "pass_rate": round(passed / len(all_results) * 100, 1),
             "results": all_results, "report_id": report.id},
            client_id=ws_cid,
        )

    background_tasks.add_task(_bg)
    return {"message": f"数据驱动执行已启动，共 {len(rows)} 行数据", "rows": len(rows), "ws_client_id": f"api_exec_{project_id}"}


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
    env_base_url = data.get("env_base_url", "")  # 环境切换：覆盖项目 Base URL
    proj_dict = _proj_dict(proj)
    if env_base_url:
        proj_dict["base_url"] = env_base_url  # 执行时覆盖，不修改数据库

    async def _bg():
        from skills.api_executor import api_executor
        from tools.database import async_session_maker
        from sqlalchemy import or_ as _or

        ws_cid = f"api_exec_{project_id}"

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
            await ws_manager.broadcast({"type": "api_exec_progress", **p}, client_id=ws_cid)

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
                created_by=current_user.username,
            )
            s.add(report)
            await s.commit()
            await s.refresh(report)

        await ws_manager.broadcast(
            {"type": "api_exec_done", "report_id": report.id, **summary}, client_id=ws_cid,
        )

        # 执行完成通知
        try:
            from tools.config import settings
            if settings.ALERT_WEBHOOK_URL:
                from tools.alerter import fire_alert
                passed = summary["passed"]
                total = summary["total"]
                pass_rate = summary["pass_rate"]
                icon = "✅" if summary["failed"] == 0 else "⚠️"
                fire_alert(
                    f"> **项目**：{proj.name}\n\n"
                    f"> **结果**：通过率 {pass_rate}%（{passed}/{total}）",
                    title=f"{icon} 接口测试执行完成",
                    fingerprint=f"api_exec_{report.id}",
                )
        except Exception as _ne:
            logger.warning(f"[exec] 通知失败: {_ne}")

    background_tasks.add_task(_bg)
    return {"message": "执行任务已启动", "project_id": project_id, "ws_client_id": f"api_exec_{project_id}"}


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

        ws_cid = f"api_load_{project_id}"

        async with async_session_maker() as s:
            q = select(ApiCase).where(ApiCase.project_id == project_id, ApiCase.enabled == True)
            if case_ids:
                q = q.where(ApiCase.id.in_(case_ids))
            cases = [_case_dict(c) for c in (await s.execute(q)).scalars().all()]

        async def metrics_cb(m):
            await ws_manager.broadcast({"type": "load_metrics", **m}, client_id=ws_cid)

        summary = await api_load_tester.run(proj_dict, cases, config, metrics_cb)

        async with async_session_maker() as s:
            report = ApiTestReport(
                project_id=project_id, project_name=proj.name, report_type="load",
                total=summary.get("total_requests", 0), passed=summary.get("passed", 0),
                failed=summary.get("failed", 0), summary=summary, details=cases,
                created_by=current_user.username,
            )
            s.add(report)
            await s.commit()
            await s.refresh(report)

        await ws_manager.broadcast(
            {"type": "load_done", "report_id": report.id, **summary}, client_id=ws_cid,
        )

    background_tasks.add_task(_bg)
    return {"message": "压测任务已启动", "project_id": project_id, "ws_client_id": f"api_load_{project_id}"}


@router.post("/api-test/load/stop")
async def stop_load_test():
    from skills.api_load_tester import api_load_tester
    api_load_tester.stop()
    return {"message": "停止信号已发送"}


# ── 接口测试报告 ──────────────────────────────────────────────────────────────

@router.get("/api-test/projects/{project_id}/reports")
async def list_api_reports(project_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    # 校验项目访问权限
    proj = (await db.execute(select(ApiProject).where(ApiProject.id == project_id))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    result = await db.execute(
        select(ApiTestReport).where(ApiTestReport.project_id == project_id)
        .order_by(ApiTestReport.created_at.desc())
    )
    return [_report_dict(r) for r in result.scalars().all()]


@router.post("/api-test/reports/{report_id}/analyze")
async def analyze_api_report(report_id: int, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    result = await db.execute(select(ApiTestReport).where(ApiTestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    # 校验报告所属项目的访问权限
    proj = (await db.execute(select(ApiProject).where(ApiProject.id == report.project_id))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
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
    sys_msg = "你是一名资深测试工程师，擅长分析接口测试报告，给出精准、可操作的建议。用中文回答，使用 Markdown 格式输出。"
    from tools.llm_client import call_llm
    return await call_llm(sys_msg, prompt, max_tokens=2048, timeout_secs=60)


@router.get("/api-test/reports/{report_id}/pdf")
async def export_api_report_pdf(report_id: int, db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(get_current_user)):
    """将接口测试报告导出为详细 PDF（单测 / 压测自动分支）。"""
    from fastapi.responses import Response
    from urllib.parse import quote
    from datetime import timezone, timedelta
    from tools.pdf_exporter import html_to_pdf

    r = (await db.execute(select(ApiTestReport).where(ApiTestReport.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")
    # 校验报告所属项目的访问权限
    proj = (await db.execute(select(ApiProject).where(ApiProject.id == r.project_id))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")

    _TZ = timezone(timedelta(hours=8))
    def _fmt(dt):
        if not dt: return "—"
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ).strftime("%Y-%m-%d %H:%M:%S")

    rdict    = _report_dict(r)
    summary  = rdict.get("summary") or {}
    details  = rdict.get("details") or []
    title    = f"{r.project_name or '接口测试'} 报告"
    created  = _fmt(r.created_at)
    now      = __import__('datetime').datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")
    analysis = rdict.get("analysis", "")
    executor = rdict.get("created_by") or "—"

    # ── 公共 CSS ────────────────────────────────────────────────────────────
    common_css = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;color:#1a1a1a;font-size:13px;line-height:1.6}
.cover{background:linear-gradient(135deg,#0f2027 0%,#203a43 50%,#2c5364 100%);color:#fff;padding:48px}
.cover h1{font-size:28px;font-weight:700;margin-bottom:6px}
.cover .sub{font-size:14px;opacity:.65;margin-bottom:24px}
.cover .meta{font-size:12px;opacity:.5;margin-top:16px}
.body{padding:32px 48px}
.section{margin-bottom:32px}
.section h2{font-size:17px;font-weight:700;padding-bottom:8px;border-bottom:2px solid #e8e8e8;margin-bottom:16px;color:#1a1a1a}
.stats{display:flex;gap:14px;margin-bottom:4px}
.stat{flex:1;background:#fafafa;border:1px solid #e8e8e8;border-radius:8px;padding:14px;text-align:center}
.stat .n{font-size:28px;font-weight:700}.stat .l{font-size:11px;color:#888;margin-top:2px}
table{width:100%;border-collapse:collapse}
th,td{padding:8px 10px;border:1px solid #e8e8e8;text-align:left;font-size:12px;vertical-align:top}
th{background:#f5f7fa;font-weight:600;color:#555}
tr:nth-child(even) td{background:#fafbff}
.method{display:inline-block;padding:1px 7px;border-radius:3px;font-size:11px;font-weight:700;background:#e6f4ff;color:#0958d9}
.kv-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:4px}
.kv-card{background:#fafafa;border:1px solid #e8e8e8;border-radius:8px;padding:14px;text-align:center}
.kv-card .kv-v{font-size:24px;font-weight:700;margin-bottom:4px}
.kv-card .kv-l{font-size:11px;color:#888}
.kv-grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:4px}
.badge-ok{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;background:#f6ffed;color:#389e0d}
.badge-fail{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;background:#fff1f0;color:#cf1322}
.footer{text-align:center;color:#bbb;font-size:11px;padding:20px 48px;border-top:1px solid #eee;margin-top:16px}
@media print{body{-webkit-print-color-adjust:exact;print-color-adjust:exact}}"""

    # ── AI 分析块（两种报告共用）────────────────────────────────────────────
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

    # ════════════════════════════════════════════════════════════════════════
    # 压测报告
    # ════════════════════════════════════════════════════════════════════════
    if r.report_type == "load":
        total_req    = summary.get("total_requests", 0)
        passed_req   = summary.get("passed", 0)
        failed_req   = summary.get("failed", 0)
        success_rate = summary.get("success_rate", 0)
        avg_tps      = summary.get("avg_tps", 0)
        avg_ms       = summary.get("avg_ms", 0)
        min_ms       = summary.get("min_ms", 0)
        max_ms       = summary.get("max_ms", 0)
        p50_ms       = summary.get("p50_ms", 0)
        p95_ms       = summary.get("p95_ms", 0)
        p99_ms       = summary.get("p99_ms", 0)
        duration_s   = summary.get("duration_secs", 0)
        cfg          = summary.get("config") or {}
        concurrent   = cfg.get("concurrent_users", "—")
        duration_cfg = cfg.get("duration", "—")
        ramp_up      = cfg.get("ramp_up", "—")

        sr_color = "#52c41a" if success_rate >= 95 else ("#faad14" if success_rate >= 80 else "#ff4d4f")

        # 参与压测的用例列表
        case_rows = ""
        for i, c in enumerate(details, 1):
            case_rows += (
                f"<tr>"
                f"<td style='color:#aaa;text-align:center'>{i}</td>"
                f"<td style='font-weight:500'>{c.get('name', '-')}</td>"
                f"<td><span class='method'>{c.get('method','')}</span></td>"
                f"<td style='font-size:11px;color:#555;word-break:break-all'>{c.get('path','')}</td>"
                f"</tr>"
            )

        body_content = f"""
<div class="section">
  <h2>📊 压测概览</h2>
  <div class="kv-grid" style="margin-bottom:14px">
    <div class="kv-card"><div class="kv-v" style="color:#1890ff">{total_req}</div><div class="kv-l">总请求数</div></div>
    <div class="kv-card"><div class="kv-v" style="color:#52c41a">{passed_req}</div><div class="kv-l">成功</div></div>
    <div class="kv-card"><div class="kv-v" style="color:#ff4d4f">{failed_req}</div><div class="kv-l">失败</div></div>
    <div class="kv-card"><div class="kv-v" style="color:{sr_color}">{success_rate}%</div><div class="kv-l">成功率</div></div>
  </div>
</div>

<div class="section">
  <h2>⚡ 性能指标</h2>
  <div class="kv-grid" style="margin-bottom:14px">
    <div class="kv-card"><div class="kv-v" style="color:#722ed1">{avg_tps}</div><div class="kv-l">平均 TPS（请求/秒）</div></div>
    <div class="kv-card"><div class="kv-v" style="color:#1890ff">{avg_ms} ms</div><div class="kv-l">平均响应时间</div></div>
    <div class="kv-card"><div class="kv-v" style="color:#13c2c2">{p50_ms} ms</div><div class="kv-l">P50 响应时间</div></div>
    <div class="kv-card"><div class="kv-v" style="color:#faad14">{p95_ms} ms</div><div class="kv-l">P95 响应时间</div></div>
  </div>
  <div class="kv-grid-3">
    <div class="kv-card"><div class="kv-v" style="color:#ff4d4f">{p99_ms} ms</div><div class="kv-l">P99 响应时间</div></div>
    <div class="kv-card"><div class="kv-v" style="color:#52c41a">{min_ms} ms</div><div class="kv-l">最小响应时间</div></div>
    <div class="kv-card"><div class="kv-v" style="color:#ff7a45">{max_ms} ms</div><div class="kv-l">最大响应时间</div></div>
  </div>
</div>

<div class="section">
  <h2>⚙️ 压测配置</h2>
  <table style="width:auto;min-width:400px">
    <tbody>
      <tr><th style="width:140px">并发用户数</th><td>{concurrent}</td></tr>
      <tr><th>持续时长</th><td>{duration_cfg} 秒</td></tr>
      <tr><th>爬坡时长</th><td>{ramp_up} 秒</td></tr>
      <tr><th>实际执行时长</th><td>{duration_s} 秒</td></tr>
    </tbody>
  </table>
</div>

<div class="section">
  <h2>📋 参与压测用例（共 {len(details)} 条）</h2>
  <table>
    <thead><tr><th style="width:36px">#</th><th>用例名称</th><th style="width:60px">方法</th><th>路径</th></tr></thead>
    <tbody>{case_rows if case_rows else '<tr><td colspan="4" style="text-align:center;color:#aaa;padding:24px">无用例数据</td></tr>'}</tbody>
  </table>
</div>
{analysis_block}"""

        report_type_label = "接口压力测试报告"
        cover_sub = f"并发：{concurrent} 用户 &nbsp;·&nbsp; 时长：{duration_cfg}s &nbsp;·&nbsp; 成功率：<b style=\"color:{sr_color}\">{success_rate}%</b>"

    # ════════════════════════════════════════════════════════════════════════
    # 单元测试报告
    # ════════════════════════════════════════════════════════════════════════
    else:
        total     = rdict.get("total", 0)
        passed    = rdict.get("passed", 0)
        failed    = rdict.get("failed", 0)
        pass_rate = round(passed / total * 100, 1) if total else 0
        pr_color  = "#52c41a" if pass_rate >= 80 else "#ff4d4f"

        rows = ""
        for i, d in enumerate(details, 1):
            st  = d.get("status", "")
            sty = {"passed": "background:#f6ffed;color:#389e0d", "failed": "background:#fff1f0;color:#cf1322"}.get(st, "background:#fffbe6;color:#ad6800")
            lbl = {"passed": "✓ 通过", "failed": "✗ 失败"}.get(st, st)
            err = str(d.get("error") or d.get("error_message") or "—")[:300]
            url = (d.get("url") or "")[:100]
            rows += (
                f"<tr>"
                f"<td style='color:#aaa;text-align:center'>{i}</td>"
                f"<td style='font-weight:500'>{d.get('case_name','-')}</td>"
                f"<td><span class='method'>{d.get('method','')}</span></td>"
                f"<td style='font-size:11px;color:#555;word-break:break-all'>{url}</td>"
                f"<td style='text-align:center'>{d.get('status_code','—')}</td>"
                f"<td><span style='padding:2px 8px;border-radius:10px;font-size:11px;{sty}'>{lbl}</span></td>"
                f"<td style='text-align:right;color:#666'>{d.get('duration_ms',0)} ms</td>"
                f"<td style='font-size:11px;color:#888;word-break:break-all'>{err}</td>"
                f"</tr>"
            )

        body_content = f"""
<div class="section">
  <h2>📊 执行统计</h2>
  <div class="stats">
    <div class="stat"><div class="n" style="color:#1890ff">{total}</div><div class="l">总用例数</div></div>
    <div class="stat"><div class="n" style="color:#52c41a">{passed}</div><div class="l">通过</div></div>
    <div class="stat"><div class="n" style="color:#ff4d4f">{failed}</div><div class="l">失败</div></div>
    <div class="stat"><div class="n" style="color:{pr_color}">{pass_rate}%</div><div class="l">通过率</div></div>
  </div>
</div>
<div class="section">
  <h2>📋 用例详情</h2>
  <table>
    <thead><tr><th style="width:36px">#</th><th>用例名称</th><th style="width:60px">方法</th><th>请求 URL</th><th style="width:60px">状态码</th><th style="width:72px">结果</th><th style="width:72px">耗时</th><th>错误信息</th></tr></thead>
    <tbody>{rows if rows else '<tr><td colspan="8" style="text-align:center;color:#aaa;padding:24px">暂无执行数据</td></tr>'}</tbody>
  </table>
</div>
{analysis_block}"""

        report_type_label = "接口自动化测试报告"
        cover_sub = f"通过率：<b style=\"color:{'#52c41a' if pass_rate>=80 else '#ff4d4f'}\">{pass_rate}%</b>"

    # ── 最终拼 HTML ──────────────────────────────────────────────────────────
    html_str = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{title}</title>
<style>{common_css}</style></head><body>
<div class="cover">
  <div style="font-size:11px;opacity:.4;margin-bottom:10px;letter-spacing:2px">API TEST REPORT</div>
  <h1>{title}</h1>
  <div class="sub">{report_type_label}</div>
  <div style="display:flex;gap:24px;font-size:13px;flex-wrap:wrap">
    <span>执行时间：{created}</span>
    <span>执行者：{executor}</span>
    <span>{cover_sub}</span>
  </div>
  <div class="meta">导出时间：{now}</div>
</div>
<div class="body">
{body_content}
</div>
<div class="footer">本报告由 AI 测试平台自动生成 · {now}</div>
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
async def delete_api_reports_batch(
    ids: List[int],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import delete as sql_del
    if not ids:
        raise HTTPException(status_code=400, detail="未提供报告ID")
    # 校验所有报告属于同一 workspace 且用户有权访问
    reports = (await db.execute(select(ApiTestReport).where(ApiTestReport.id.in_(ids)))).scalars().all()
    if not reports:
        raise HTTPException(status_code=404, detail="未找到指定报告")
    project_ids = set(r.project_id for r in reports)
    if len(project_ids) > 1:
        raise HTTPException(status_code=400, detail="只能批量删除同一项目的报告")
    proj_id = project_ids.pop()
    proj = (await db.execute(select(ApiProject).where(ApiProject.id == proj_id))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    await db.execute(sql_del(ApiTestReport).where(ApiTestReport.id.in_(ids)))
    await db.commit()
    return {"message": f"已删除 {len(ids)} 条报告"}


@router.delete("/api-test/reports/{report_id}")
async def delete_api_report(report_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    from sqlalchemy import delete as sql_del
    result = await db.execute(select(ApiTestReport).where(ApiTestReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    # 校验报告所属项目的访问权限
    proj = (await db.execute(select(ApiProject).where(ApiProject.id == report.project_id))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    await check_access(db, proj, current_user, "接口项目")
    await db.execute(sql_del(ApiTestReport).where(ApiTestReport.id == report_id))
    await db.commit()
    return {"message": "已删除"}


