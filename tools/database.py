"""
数据库初始化和会话管理
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, JSON
from datetime import datetime
from tools.config import settings

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

    # ── 需求文档快照（用于文档变更后的 Diff 分析） ─────────────────────────
    # 上次解析的需求文档文本（截断保存前 20000 字），供 incremental-update 对比
    doc_snapshot = Column(Text, nullable=True)
    # 上次解析文档的 MD5 哈希（16位），快速判断文档是否变更
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


class AICaseFile(Base):
    __tablename__ = "ai_case_files"

    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(255), nullable=False)
    case_count = Column(Integer, default=0)
    md_path = Column(String(512), nullable=True)
    xmind_path = Column(String(512), nullable=True)
    cases_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="user")
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiProject(Base):
    __tablename__ = "api_projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    base_url = Column(String(1024), nullable=False)
    description = Column(Text, nullable=True)
    auth_type = Column(String(50), default="none")  # none/bearer/api_key/basic
    auth_config = Column(JSON, nullable=True)
    global_headers = Column(JSON, nullable=True)
    # 前置用例：执行正式用例前先跑这些用例刷新 token
    # 格式：[{"project_id": 3, "case_id": 25, "label": "用户服务/登录"}]
    setup_cases = Column(JSON, nullable=True)
    # 鉴权失败特征：命中则自动刷新 token 并重试
    # 格式：[{"field": "$.status.code", "value": "40042"}, {"field": "http_status", "value": "401"}]
    auth_error_patterns = Column(JSON, nullable=True)
    proxy_url = Column(String(512), nullable=True, default="")   # HTTP/SOCKS5 代理，留空表示直连
    hosts_map = Column(Text, nullable=True, default="")          # hosts 映射，格式同 /etc/hosts
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
    """跨项目全局变量池，通过 {{gvar:name}} 在任意项目中引用。"""
    __tablename__ = "global_variables"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=True, default="")
    description = Column(String(500), default="")
    source_project = Column(String(255), default="")   # 最后写入来源项目名
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TestPlan(Base):
    """测试计划：将若干接口用例按顺序组合，共享变量上下文，生成步骤级报告。"""
    __tablename__ = "test_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")
    project_id = Column(Integer, nullable=True, index=True)   # 关联接口项目（可选）
    status = Column(String(50), default="pending")             # pending/running/passed/failed
    proxy_url = Column(String(512), nullable=True, default="")  # 计划级代理，优先级高于项目代理
    hosts_map = Column(Text, nullable=True, default="")         # 计划级 hosts 映射，覆盖项目级同名条目
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


async def init_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 兼容旧库：自动补齐新增列
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
            # test_tasks 文档快照字段（兼容旧库）
            "ALTER TABLE test_tasks ADD COLUMN doc_snapshot TEXT",
            "ALTER TABLE test_tasks ADD COLUMN doc_hash VARCHAR(64)",
            # test_cases 废弃字段（兼容旧库）
            "ALTER TABLE test_cases ADD COLUMN deprecated BOOLEAN DEFAULT 0",
        ]:
            try:
                await conn.execute(__import__('sqlalchemy').text(ddl))
            except Exception:
                pass  # 列已存在则忽略


async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
