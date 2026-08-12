"""
数据库初始化和会话管理
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, JSON, ForeignKey, Index, UniqueConstraint
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

    # ── AI 场景规划持久化 ─────────────────────────────────────────────────────
    # plan_scenes 接口生成的场景列表，格式: [{id, name, priority, description, steps_desc, expected, recorded}, ...]
    scene_plan = Column(JSON, nullable=True)

    # ── 前置登录态（方案三：storage_state 快照）────────────────────────────────
    # 指向同任务下某条「登录用例」的 id，执行前自动跑该用例并保存 storage_state
    setup_case_id = Column(Integer, nullable=True)
    # 快照文件路径（由执行引擎自动管理，前端只读）
    storage_state_path = Column(String(512), nullable=True)
    # 快照有效期（分钟），超时自动重跑 setup 用例；0 表示每次都重新跑
    storage_ttl_minutes = Column(Integer, default=60, nullable=False)


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
    enabled = Column(Boolean, default=True)
    deprecated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # ── 乐观锁版本号，每次更新 +1 ──
    version = Column(Integer, default=1, nullable=False)

    # ── 方案C：结构化执行字段 ─────────────────────────────────────────────────
    # 录制/AI生成的结构化步骤列表，格式见 tools/action_schema.py ActionStep
    steps_json = Column(JSON, nullable=True)
    # 浏览器矩阵执行结果快照：{chromium: {status, duration}, firefox: {...}, ...}
    browser_matrix = Column(JSON, nullable=True)

    # ── 用例来源 ──────────────────────────────────────────────────────────────
    # recorded=录制产生  ai_generated=AI生成  manual=手动创建
    source = Column(String(20), nullable=True, default="manual")

    # ── 前置步骤（方案一：case 级 setup_steps）────────────────────────────────
    # 在 steps_json 执行前先跑这些步骤（如导航到特定页面、展开弹窗等），
    # 与 steps_json 共用同一个 Page，不产生独立用例依赖
    setup_steps = Column(JSON, nullable=True)
    # 是否在执行前加载 task 级 storage_state 快照（默认 True）
    # 设为 False 则该用例始终以干净状态运行（如登录用例本身）
    use_storage = Column(Boolean, default=True, nullable=False)

    # ── 权限与隔离 ──
    created_by = Column(String(100), nullable=True, index=True)
    project_id = Column(Integer, nullable=True, index=True)

    # 执行时常同时过滤 task_id + deprecated，加复合索引提速
    __table_args__ = (
        Index("ix_test_cases_task_deprecated", "task_id", "deprecated"),
    )


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
    logs = Column(JSON, nullable=True, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 报告聚合时常联合查询 (task_id, case_id)
    __table_args__ = (
        Index("ix_test_results_task_case", "task_id", "case_id"),
    )


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
    finished_at = Column(DateTime, nullable=True, comment="执行完成时间")
    created_by = Column(String(100), nullable=True, index=True)
    project_id = Column(Integer, nullable=True, index=True)

    # ── 方案C：多浏览器报告字段 ───────────────────────────────────────────────
    browser     = Column(String(50), default="chromium")     # 本报告对应的浏览器
    script_path = Column(String(512), nullable=True)          # 导出的 pytest 脚本路径


class TaskEnvVar(Base):
    """WebUI 任务级环境变量，供结构化步骤中 {{key}} 变量替换使用。
    按 task_id 隔离，is_secret=True 的变量前端显示 ***，不回显明文。
    """
    __tablename__ = "task_env_vars"

    id        = Column(Integer, primary_key=True, index=True)
    task_id   = Column(Integer, nullable=False)
    key       = Column(String(100), nullable=False)
    value     = Column(Text, nullable=False, default="")
    is_secret = Column(Boolean, default=False)   # 密码/token 等敏感值
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_task_env_vars_task", "task_id"),
        UniqueConstraint("task_id", "key", name="uq_task_env_var"),
    )


class ElementAlias(Base):
    """WebUI 元素别名库：将语义名称映射到候选 selector 列表。
    步骤里用 @别名名称 引用，执行时展开为 selectors[] 多候选回退。
    """
    __tablename__ = "element_aliases"

    id          = Column(Integer, primary_key=True, index=True)
    task_id     = Column(Integer, nullable=False)
    name        = Column(String(100), nullable=False)           # 别名，如"登录按钮"
    selectors   = Column(JSON, nullable=False, default=list)    # 候选 selector 列表（按优先级）
    description = Column(String(255), nullable=True, default="")
    created_by  = Column(String(100), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_element_aliases_task", "task_id"),
        UniqueConstraint("task_id", "name", name="uq_element_alias"),
    )


class AICaseFile(Base):
    __tablename__ = "ai_case_files"

    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(255), nullable=False)
    case_count = Column(Integer, default=0)
    md_path = Column(String(512), nullable=True)
    xmind_path = Column(String(512), nullable=True)
    xlsx_path = Column(String(512), nullable=True)
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

    # 列表查询常同时按 record_status + gen_status 过滤
    __table_args__ = (
        Index("ix_ai_case_files_status", "record_status", "gen_status"),
    )


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

    # 复合唯一索引：check_access 每次请求都按 (project_id, username) 查询，必须有
    __table_args__ = (
        Index("ix_project_members_project_user", "project_id", "username", unique=True),
    )


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
    environments = Column(JSON, nullable=True)  # [{name, base_url}] 多环境配置
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
    timeout_ms = Column(Integer, nullable=True)  # 用例级超时（毫秒），None=使用项目默认30s
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
    created_by = Column(String(100), nullable=True)
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


class MockRule(Base):
    """Mock 规则：匹配请求路径+方法，返回预设响应体。"""
    __tablename__ = "mock_rules"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=True, index=True)  # 关联接口项目，None=全局
    name = Column(String(255), nullable=False)
    method = Column(String(10), default="GET")     # GET/POST/PUT/DELETE/ANY
    path = Column(String(1024), nullable=False)    # 匹配路径，如 /api/users/{id}
    status_code = Column(Integer, default=200)
    response_headers = Column(JSON, nullable=True)  # {"Content-Type": "application/json"}
    response_body = Column(Text, nullable=True)    # 响应体，支持 {{var}} 模板
    match_params = Column(JSON, nullable=True)     # {key: value} 请求参数匹配条件，空=匹配所有
    delay_ms = Column(Integer, default=0)          # 模拟延迟（毫秒）
    enabled = Column(Boolean, default=True)
    description = Column(Text, nullable=True, default="")
    created_by = Column(String(100), nullable=True)
    workspace_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


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
    cron_expr = Column(String(100), nullable=True)     # Cron 表达式，如 "0 9 * * 1-5"
    cron_enabled = Column(Boolean, default=False)      # 是否启用定时执行
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
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PentestTask(Base):
    """渗透测试任务：一次扫描的配置与执行状态，按工作空间隔离。"""
    __tablename__ = "pentest_tasks"

    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(String(255), nullable=False)
    workspace_id = Column(Integer, nullable=True, index=True)   # 所属工作空间
    project_id   = Column(Integer, nullable=True, index=True)   # 关联接口项目（借用认证/BaseURL）
    created_by   = Column(String(100), nullable=True, index=True)
    executed_by  = Column(String(100), nullable=True)            # 最近一次触发扫描的用户
    status       = Column(String(20), default="pending")        # pending/running/done/failed
    scan_modules = Column(JSON, nullable=True)                  # ["unauth","idor","sensitive","sqli"]
    case_ids     = Column(JSON, nullable=True)                  # 指定扫描的用例 id 列表，空=全部
    concurrency  = Column(Integer, default=3)                   # 最大并发请求数
    # 汇总：执行完毕后写入
    total_checks = Column(Integer, default=0)
    high_count   = Column(Integer, default=0)
    medium_count = Column(Integer, default=0)
    low_count    = Column(Integer, default=0)
    info_count   = Column(Integer, default=0)
    created_at   = Column(DateTime, default=datetime.utcnow)
    finished_at  = Column(DateTime, nullable=True)


class PentestFinding(Base):
    """渗透测试发现的单条漏洞记录。"""
    __tablename__ = "pentest_findings"

    id               = Column(Integer, primary_key=True, index=True)
    task_id          = Column(Integer, nullable=False, index=True)  # → PentestTask.id
    vuln_type        = Column(String(50), nullable=False)           # unauth/idor/sensitive/sqli
    severity         = Column(String(10), default="medium")         # high/medium/low/info
    endpoint         = Column(String(512), default="")              # METHOD /path
    payload          = Column(Text, nullable=True)                  # 发送的 payload（若有）
    evidence         = Column(Text, nullable=True)                  # 响应摘要（截断200字）
    request_detail   = Column(JSON, nullable=True)                  # {method, url, headers, body}
    suggestion       = Column(Text, nullable=True)                  # AI 生成的修复建议
    created_at       = Column(DateTime, default=datetime.utcnow)


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
        # test_cases 乐观锁版本号（兼容旧库）
        "ALTER TABLE test_cases ADD COLUMN version INTEGER DEFAULT 1",
        # 权限隔离：created_by 字段（NULL = 历史数据，对所有用户可见）
        "ALTER TABLE test_tasks ADD COLUMN created_by VARCHAR(100)",
        "ALTER TABLE ai_case_files ADD COLUMN created_by VARCHAR(100)",
        "ALTER TABLE api_projects ADD COLUMN created_by VARCHAR(100)",
        "ALTER TABLE test_plans ADD COLUMN created_by VARCHAR(100)",
        # CI/CD webhook token
        "ALTER TABLE test_plans ADD COLUMN webhook_token VARCHAR(128)",
        # 报告隔离
        "ALTER TABLE test_reports ADD COLUMN created_by VARCHAR(100)",
        # 接口测试报告 / 测试计划报告执行者字段
        "ALTER TABLE api_test_reports ADD COLUMN created_by VARCHAR(100)",
        "ALTER TABLE test_plan_reports ADD COLUMN created_by VARCHAR(100)",
        # 工作空间 project_id（各业务表）
        "ALTER TABLE test_tasks    ADD COLUMN project_id INTEGER",
        "ALTER TABLE test_reports  ADD COLUMN project_id INTEGER",
        "ALTER TABLE ai_case_files ADD COLUMN project_id INTEGER",
        "ALTER TABLE api_projects  ADD COLUMN workspace_id INTEGER",
        "ALTER TABLE test_plans    ADD COLUMN workspace_id INTEGER",
        "ALTER TABLE global_variables ADD COLUMN workspace_id INTEGER",
        # test_cases 权限与隔离
        "ALTER TABLE test_cases   ADD COLUMN created_by VARCHAR(100)",
        "ALTER TABLE test_cases   ADD COLUMN project_id INTEGER",
        # 渗透测试：executed_by 记录最近一次触发扫描的用户（兼容旧库）
        "ALTER TABLE pentest_tasks ADD COLUMN executed_by VARCHAR(100)",
        # 方案C WebUI：结构化步骤和多浏览器报告字段（兼容旧库）
        "ALTER TABLE test_cases   ADD COLUMN steps_json JSON",
        "ALTER TABLE test_cases   ADD COLUMN browser_matrix JSON",
        "ALTER TABLE test_reports ADD COLUMN browser VARCHAR(50) DEFAULT 'chromium'",
        "ALTER TABLE test_reports ADD COLUMN script_path VARCHAR(512)",
        "ALTER TABLE test_reports ADD COLUMN finished_at DATETIME",
        # 多环境支持
        "ALTER TABLE api_projects ADD COLUMN environments JSON",
        # global_headers（已在模型定义，兼容旧库）
        "ALTER TABLE api_projects ADD COLUMN global_headers JSON",
        # 测试计划定时执行
        "ALTER TABLE test_plans ADD COLUMN cron_expr VARCHAR(100)",
        "ALTER TABLE test_plans ADD COLUMN cron_enabled BOOLEAN DEFAULT 0",
        # 用例级超时
        "ALTER TABLE api_cases ADD COLUMN timeout_ms INTEGER",
        # Mock 规则请求参数匹配
        "ALTER TABLE mock_rules ADD COLUMN match_params JSON",
        # 用例来源标记
        "ALTER TABLE test_cases ADD COLUMN source VARCHAR(20) DEFAULT 'manual'",
        # 任务级 AI 场景规划结果持久化
        "ALTER TABLE test_tasks ADD COLUMN scene_plan JSON",
        # 前置登录态 — storage_state 快照（方案三）
        "ALTER TABLE test_tasks ADD COLUMN setup_case_id INTEGER",
        "ALTER TABLE test_tasks ADD COLUMN storage_state_path VARCHAR(512)",
        "ALTER TABLE test_tasks ADD COLUMN storage_ttl_minutes INTEGER DEFAULT 60",
        # 用例级前置步骤 — setup_steps（方案一）
        "ALTER TABLE test_cases ADD COLUMN setup_steps JSON",
        "ALTER TABLE test_cases ADD COLUMN use_storage BOOLEAN DEFAULT 1",
        # 元素别名库（create_all 自动建表，无需 ALTER）
    ]:
        try:
            async with engine.begin() as conn:
                await conn.execute(_sql(ddl))
        except Exception:
            pass  # 列已存在则忽略

    # 数据迁移：将 created_by = NULL 的历史数据归属到 admin
    for table in ["test_tasks", "test_cases", "ai_case_files", "api_projects", "test_plans", "test_reports"]:
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
            ("test_cases",    "project_id"),
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

    # ── 性能索引 ────────────────────────────────────────────────────────────
    _indexes_sql = [
        "CREATE INDEX IF NOT EXISTS ix_test_results_task_start ON test_results (task_id, start_time)",
        "CREATE INDEX IF NOT EXISTS ix_test_reports_task_created ON test_reports (task_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_test_cases_task_module ON test_cases (task_id, module)",
        "CREATE INDEX IF NOT EXISTS ix_test_results_task_created ON test_results (task_id, created_at)",
    ]
    for _index_sql in _indexes_sql:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(_index_sql))
        except Exception:
            pass


async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
