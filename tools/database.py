"""
数据库初始化和会话管理
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, JSON, ForeignKey
from datetime import datetime
from tools.config import settings

# pgvector 支持（仅 PostgreSQL 时生效；SQLite 时跳过）
try:
    from pgvector.sqlalchemy import Vector as PgVector
    _PGVECTOR_AVAILABLE = True
except ImportError:
    _PGVECTOR_AVAILABLE = False

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


class TestTask(Base):
    __tablename__ = "test_tasks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(1024), nullable=False)
    document_path = Column(String(512), nullable=True)
    status = Column(String(50), default="pending")
    browser = Column(String(50), default="chromium")
    environment = Column(String(50), default="test")
    page_elements = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(100), nullable=True, index=True)
    project_id = Column(Integer, nullable=True, index=True)   # 所属工作空间，NULL=默认空间

    # ── 需求文档快照（用于文档变更后的 Diff 分析） ─────────────────────────
    doc_snapshot = Column(Text, nullable=True)
    doc_hash = Column(String(64), nullable=True)


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    module = Column(String(100))
    priority = Column(String(10), default="P1")
    preconditions = Column(Text)
    steps = Column(Text)
    expected_results = Column(Text)
    element_selector = Column(String(512), nullable=True, default="")
    enabled = Column(Boolean, default=True)       # 用户手动启用/禁用（禁用不执行但用例有效）
    deprecated = Column(Boolean, default=False)   # 需求变更废弃（不参与执行和覆盖率统计）
    created_at = Column(DateTime, default=datetime.utcnow)


class TestResult(Base):
    __tablename__ = "test_results"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False, index=True)
    case_id = Column(Integer, nullable=False, index=True)
    status = Column(String(50), default="pending")
    executor = Column(String(100))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    duration = Column(Float, default=0)
    error_message = Column(Text, nullable=True)
    screenshot_path = Column(String(512), nullable=True)
    logs = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TestReport(Base):
    __tablename__ = "test_reports"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    summary = Column(JSON)
    details = Column(JSON)
    pass_rate = Column(Float, default=0)
    total_cases = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    report_path = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(100), nullable=True, index=True)
    project_id = Column(Integer, nullable=True, index=True)


class AICaseFile(Base):
    __tablename__ = "ai_case_files"

    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(255), nullable=False)
    case_count = Column(Integer, default=0)
    md_path = Column(String(512), nullable=True)
    xmind_path = Column(String(512), nullable=True)
    cases_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(100), nullable=True, index=True)
    project_id = Column(Integer, nullable=True, index=True)   # 所属工作空间

    # ── 文档变更追踪字段 ────────────────────────────────────────────────
    # 需求文档内容的 MD5 哈希，用于检测文档是否发生变更
    doc_hash = Column(String(64), nullable=True, index=True)
    # 需求文档原始文本（用于后续 Diff 分析，截断保存前 20000 字）
    doc_content = Column(Text, nullable=True)
    # 上一版本的 AICaseFile.id；初次生成时为 None，增量更新后指向父版本
    parent_id = Column(Integer, nullable=True, index=True)
    # 本次相对上一版本的变更摘要（AI 生成的一句话描述）
    diff_summary = Column(Text, nullable=True)
    # 记录状态：active（当前有效版本） / deprecated（已被新版本替代）
    record_status = Column(String(20), default="active", nullable=False)
    # 生成状态：generating（后台生成中） / done（已完成） / failed（失败）
    gen_status = Column(String(20), default="done", nullable=False)
    # 生成进度（0-100），后台任务每次推 WebSocket 时同步写库，前端重连后可恢复进度
    gen_progress = Column(Integer, default=0, nullable=False)

    # ── 需求追踪字段 ────────────────────────────────────────────────────
    # 结构化需求列表：[{id, module, title, description, priority}]
    requirements_data = Column(JSON, nullable=True)
    # 用例-需求映射：{mapped_at, mappings: [{case_id, req_refs:[...]}]}
    traceability_data = Column(JSON, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="user")
    created_at = Column(DateTime, default=datetime.utcnow)


class Project(Base):
    """工作空间（项目）：数据隔离的顶层单元。
    每个用户可创建多个工作空间，通过 ProjectMember 控制成员访问。
    admin 角色可跨工作空间查看所有数据。
    """
    __tablename__ = "projects"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(100), nullable=False)
    description = Column(String(500), default="")
    owner       = Column(String(100), nullable=False, index=True)   # 创建人用户名
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProjectMember(Base):
    """工作空间成员关系。role: owner（可管理成员）/ member（只读写数据）。"""
    __tablename__ = "project_members"

    id         = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=False, index=True)
    username   = Column(String(100), nullable=False, index=True)
    role       = Column(String(20), default="member")   # owner / member
    joined_at  = Column(DateTime, default=datetime.utcnow)


class ApiProject(Base):
    __tablename__ = "api_projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    base_url = Column(String(1024), nullable=False)
    description = Column(Text, nullable=True)
    auth_type = Column(String(50), default="none")
    auth_config = Column(JSON, nullable=True)
    global_headers = Column(JSON, nullable=True)
    setup_cases = Column(JSON, nullable=True)
    auth_error_patterns = Column(JSON, nullable=True)
    proxy_url = Column(String(512), nullable=True, default="")
    hosts_map = Column(Text, nullable=True, default="")
    created_by = Column(String(100), nullable=True, index=True)
    workspace_id = Column(Integer, nullable=True, index=True)  # 所属工作空间（避免与自身 project 概念冲突）
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiCase(Base):
    __tablename__ = "api_cases"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    module = Column(String(100), default="通用")
    method = Column(String(10), default="GET")
    path = Column(String(1024), nullable=False, default="/")
    headers = Column(JSON, nullable=True)
    params = Column(JSON, nullable=True)
    body_type = Column(String(20), default="json")   # json / form / raw / none
    body = Column(JSON, nullable=True)
    body_raw = Column(Text, nullable=True)           # raw 文本体
    assertions = Column(JSON, nullable=True)
    var_extracts = Column(JSON, nullable=True)   # [{name, path}] 变量提取规则
    priority = Column(String(10), default="P1")
    enabled = Column(Boolean, default=True)
    description = Column(Text, nullable=True, default='')
    created_at = Column(DateTime, default=datetime.utcnow)


class CustomScript(Base):
    __tablename__ = "custom_scripts"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=True, index=True)   # None = 全局
    name = Column(String(100), nullable=False)
    description = Column(String(500), default='')
    code = Column(Text, nullable=False, default='')
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiLoadConfig(Base):
    __tablename__ = "api_load_configs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=False, index=True)
    name = Column(String(255), default="压测配置")
    concurrent_users = Column(Integer, default=10)
    duration = Column(Integer, default=60)
    ramp_up = Column(Integer, default=10)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiTestReport(Base):
    __tablename__ = "api_test_reports"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=False, index=True)
    project_name = Column(String(255), default="")
    report_type = Column(String(20), default="unit")  # unit/load
    total = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    summary = Column(JSON, nullable=True)
    details = Column(JSON, nullable=True)
    analysis = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GlobalVariable(Base):
    """全局变量池，通过 {{gvar:name}} 在任意项目中引用。
    按工作空间隔离：workspace_id 对应 projects.id，NULL=全局（兼容旧数据）。
    """
    __tablename__ = "global_variables"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    value = Column(Text, nullable=True, default="")
    description = Column(String(500), default="")
    source_project = Column(String(255), default="")
    workspace_id = Column(Integer, nullable=True, index=True)  # 所属工作空间
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TestPlan(Base):
    """测试计划：将若干接口用例按顺序组合，共享变量上下文，生成步骤级报告。"""
    __tablename__ = "test_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")
    project_id = Column(Integer, nullable=True, index=True)
    status = Column(String(50), default="pending")
    proxy_url = Column(String(512), nullable=True, default="")
    hosts_map = Column(Text, nullable=True, default="")
    created_by = Column(String(100), nullable=True, index=True)
    webhook_token = Column(String(128), nullable=True, index=True)
    workspace_id = Column(Integer, nullable=True, index=True)  # 所属工作空间
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TestPlanStep(Base):
    """测试计划步骤：每步对应一条 ApiCase，记录排序、是否启用。"""
    __tablename__ = "test_plan_steps"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, nullable=False, index=True)
    case_id = Column(Integer, nullable=False)                  # 关联 api_cases.id
    case_project_id = Column(Integer, nullable=True)           # 冗余，方便展示
    sort_order = Column(Integer, default=0)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TestPlanReport(Base):
    """测试计划执行报告：记录一次完整执行的汇总及每步结果。"""
    __tablename__ = "test_plan_reports"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, nullable=False, index=True)
    plan_name = Column(String(255), default="")
    total = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    pass_rate = Column(Float, default=0)
    # details: [{step, case_id, case_name, status, duration_ms, assertions, error, extracted_vars, ...}]
    details = Column(JSON, nullable=True)
    var_snapshot = Column(JSON, nullable=True)  # 执行完毕时的共享变量快照
    analysis = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DocumentChunk(Base):
    """文档分段向量表，用于 RAG 检索。
    PostgreSQL 环境下存储 pgvector 向量；SQLite 环境下 embedding 列存 None，退化为关键词检索。
    """
    __tablename__ = "document_chunks"

    id           = Column(Integer, primary_key=True, index=True)
    source_id    = Column(Integer, nullable=False, index=True)   # AICaseFile.id 或 TestTask.id
    source_type  = Column(String(20), nullable=False, index=True) # "ai_case" | "ui_case"
    chunk_index  = Column(Integer, nullable=False)
    content      = Column(Text, nullable=False)                  # 原始文本段落
    # pgvector 列：PostgreSQL 时存 1536 维向量，SQLite 时列不存在（create_all 跳过）
    embedding    = Column(PgVector(1536), nullable=True) if _PGVECTOR_AVAILABLE else Column(Text, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)


async def init_database():
    # PostgreSQL 环境下启用 pgvector 扩展。
    # 必须在独立事务中执行：asyncpg 遇到任何错误都会把当前事务标记为 aborted，
    # 若与 create_all 共用同一 engine.begin() 事务块，扩展创建失败后整个建表事务
    # 全部回滚（PostgreSQL 静默拒绝，SQLAlchemy 不抛异常），导致所有表都没建出来。
    if "postgresql" in settings.DATABASE_URL:
        try:
            async with engine.begin() as conn:
                await conn.execute(__import__('sqlalchemy').text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as e:
            __import__('loguru').logger.warning(f"[init_db] pgvector 扩展创建跳过（可能已存在）: {e}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 兼容旧库：自动补齐新增列。
    # 每条 ALTER TABLE 必须独立事务：asyncpg 遇到"列已存在"错误会把当前事务标记为
    # aborted，若共用同一事务，后续所有 DDL 全部被静默跳过，导致新列未能添加。
    _sql = __import__('sqlalchemy').text
    _log = __import__('loguru').logger
    _admin = settings.DEFAULT_USERNAME

    for ddl in [
        "ALTER TABLE api_test_reports ADD COLUMN analysis TEXT",
        "ALTER TABLE api_cases ADD COLUMN description TEXT",
        "ALTER TABLE api_cases ADD COLUMN body_type VARCHAR(20) DEFAULT 'json'",
        "ALTER TABLE api_cases ADD COLUMN body_raw TEXT",
        "ALTER TABLE api_cases ADD COLUMN var_extracts JSON",
        "ALTER TABLE global_variables ADD COLUMN source_project VARCHAR(255) DEFAULT ''",
        "ALTER TABLE api_projects ADD COLUMN setup_cases JSON",
        "ALTER TABLE api_projects ADD COLUMN auth_error_patterns JSON",
        "ALTER TABLE api_projects ADD COLUMN proxy_url VARCHAR(512) DEFAULT ''",
        "ALTER TABLE api_projects ADD COLUMN hosts_map TEXT DEFAULT ''",
        # test_plans / test_plan_steps / test_plan_reports 由 create_all 自动建表，无需 ALTER
        "ALTER TABLE test_plans ADD COLUMN proxy_url VARCHAR(512) DEFAULT ''",
        "ALTER TABLE test_plans ADD COLUMN hosts_map TEXT DEFAULT ''",
        "ALTER TABLE test_plan_reports ADD COLUMN analysis TEXT",
        # ai_case_files 文档变更追踪字段（兼容旧库）
        "ALTER TABLE ai_case_files ADD COLUMN doc_hash VARCHAR(64)",
        "ALTER TABLE ai_case_files ADD COLUMN doc_content TEXT",
        "ALTER TABLE ai_case_files ADD COLUMN parent_id INTEGER",
        "ALTER TABLE ai_case_files ADD COLUMN diff_summary TEXT",
        "ALTER TABLE ai_case_files ADD COLUMN record_status VARCHAR(20) DEFAULT 'active'",
        "ALTER TABLE ai_case_files ADD COLUMN gen_status VARCHAR(20) DEFAULT 'done'",
        "ALTER TABLE ai_case_files ADD COLUMN requirements_data JSON",
        "ALTER TABLE ai_case_files ADD COLUMN traceability_data JSON",
        "ALTER TABLE ai_case_files ADD COLUMN gen_progress INTEGER DEFAULT 0",
        # test_tasks 文档快照字段（兼容旧库）
        "ALTER TABLE test_tasks ADD COLUMN doc_snapshot TEXT",
        "ALTER TABLE test_tasks ADD COLUMN doc_hash VARCHAR(64)",
        # test_cases 废弃字段（兼容旧库）
        "ALTER TABLE test_cases ADD COLUMN deprecated BOOLEAN DEFAULT 0",
        # 权限隔离：created_by 字段（NULL = 历史数据，对所有用户可见）
        "ALTER TABLE test_tasks ADD COLUMN created_by VARCHAR(100)",
        "ALTER TABLE ai_case_files ADD COLUMN created_by VARCHAR(100)",
        "ALTER TABLE api_projects ADD COLUMN created_by VARCHAR(100)",
        "ALTER TABLE test_plans ADD COLUMN created_by VARCHAR(100)",
        # CI/CD webhook token
        "ALTER TABLE test_plans ADD COLUMN webhook_token VARCHAR(128)",
        # 报告隔离
        "ALTER TABLE test_reports ADD COLUMN created_by VARCHAR(100)",
        # 工作空间 project_id（各业务表）
        "ALTER TABLE test_tasks    ADD COLUMN project_id INTEGER",
        "ALTER TABLE test_reports  ADD COLUMN project_id INTEGER",
        "ALTER TABLE ai_case_files ADD COLUMN project_id INTEGER",
        "ALTER TABLE api_projects  ADD COLUMN workspace_id INTEGER",
        "ALTER TABLE test_plans    ADD COLUMN workspace_id INTEGER",
        "ALTER TABLE global_variables ADD COLUMN workspace_id INTEGER",
    ]:
        try:
            async with engine.begin() as conn:
                await conn.execute(_sql(ddl))
        except Exception:
            pass  # 列已存在则忽略

    # 数据迁移：将 created_by = NULL 的历史数据归属到 admin
    for table in ["test_tasks", "ai_case_files", "api_projects", "test_plans", "test_reports"]:
        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    _sql(f"UPDATE {table} SET created_by = :u WHERE created_by IS NULL"),
                    {"u": _admin},
                )
                if result.rowcount:
                    _log.info(f"[init_db] {table}: {result.rowcount} 条历史数据 created_by 归属到 {_admin}")
        except Exception:
            pass

    # ── 默认工作空间：确保存在，并把旧数据和所有用户纳入 ──────────────────
    try:
        async with engine.begin() as conn:
            # 1. 建或找默认工作空间（名称固定为"默认空间"）
            row = await conn.execute(
                _sql("SELECT id FROM projects WHERE name = '默认空间' LIMIT 1")
            )
            default_ws = row.fetchone()
            if not default_ws:
                await conn.execute(
                    _sql("INSERT INTO projects (name, description, owner, created_at, updated_at) "
                         "VALUES ('默认空间', '系统默认工作空间，旧数据自动归入', :owner, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                    {"owner": _admin},
                )
                row = await conn.execute(
                    _sql("SELECT id FROM projects WHERE name = '默认空间' LIMIT 1")
                )
                default_ws = row.fetchone()
                _log.info(f"[init_db] 默认工作空间已创建 id={default_ws[0]}")

            ws_id = default_ws[0]

        # 2. 旧数据（project_id / workspace_id = NULL）归入默认空间
        for table, col in [
            ("test_tasks",    "project_id"),
            ("ai_case_files", "project_id"),
            ("test_reports",  "project_id"),
            ("api_projects",  "workspace_id"),
            ("test_plans",    "workspace_id"),
        ]:
            try:
                async with engine.begin() as conn:
                    r = await conn.execute(
                        _sql(f"UPDATE {table} SET {col} = :ws WHERE {col} IS NULL"),
                        {"ws": ws_id},
                    )
                    if r.rowcount:
                        _log.info(f"[init_db] {table}: {r.rowcount} 条旧数据归入默认空间 id={ws_id}")
            except Exception:
                pass

        # 3. 只把 admin 加入默认空间（普通用户需要被手动邀请到对应工作空间）
        async with engine.begin() as conn:
            existing = await conn.execute(
                _sql("SELECT id FROM project_members WHERE project_id = :ws AND username = :u"),
                {"ws": ws_id, "u": _admin},
            )
            if not existing.fetchone():
                await conn.execute(
                    _sql("INSERT INTO project_members (project_id, username, role, joined_at) "
                         "VALUES (:ws, :u, 'owner', CURRENT_TIMESTAMP)"),
                    {"ws": ws_id, "u": _admin},
                )
                _log.info(f"[init_db] admin 加入默认空间（owner）")

    except Exception as e:
        _log.warning(f"[init_db] 默认工作空间初始化异常（可忽略）: {e}")


async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
