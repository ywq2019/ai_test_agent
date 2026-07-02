"""
Pydantic请求/响应模式定义
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class TaskCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="任务名称")
    url: str = Field(..., description="待测试页面URL")
    document_path: Optional[str] = Field(None, description="需求文档路径")
    browser: str = Field("chromium", description="浏览器类型: chromium/firefox/webkit")
    environment: str = Field("test", description="测试环境: test/staging/production")


class TaskResponse(BaseModel):
    id: int
    name: str
    url: str
    status: str
    browser: str
    environment: str
    created_at: str
    page_elements: Optional[List[Dict[str, Any]]] = None


class CaseCreateRequest(BaseModel):
    task_id: int
    name: str = Field(..., min_length=1)
    module: Optional[str] = "通用"
    priority: str = Field("P1", pattern="^(P0|P1|P2)$")
    preconditions: Optional[str] = ""
    steps: str = Field(..., min_length=1)
    expected_results: str = Field(..., min_length=1)
    enabled: bool = True


class CaseUpdateRequest(BaseModel):
    name: Optional[str] = None
    module: Optional[str] = None
    priority: Optional[str] = None
    preconditions: Optional[str] = None
    steps: Optional[str] = None
    expected_results: Optional[str] = None
    enabled: Optional[bool] = None


class CaseResponse(BaseModel):
    id: int
    task_id: int
    name: str
    module: Optional[str]
    priority: str
    preconditions: Optional[str]
    steps: str
    expected_results: str
    element_selector: Optional[str] = ""
    enabled: bool


class ExecuteRequest(BaseModel):
    task_id: int
    case_ids: Optional[List[int]] = Field(None, description="指定用例ID列表，None表示全部")
    browser: str = Field("chromium")


class ExecuteResponse(BaseModel):
    total: int
    passed: int
    failed: int
    skipped: int
    results: List[Dict[str, Any]]


class ReportResponse(BaseModel):
    report_id: Optional[int] = None
    task_id: int
    task_name: str
    summary: Dict[str, Any] = {}
    html_path: str = ""
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    pass_rate: float = 0
    details: List[Dict[str, Any]] = []
    created_at: str = ""


class CommandRequest(BaseModel):
    message: str = Field(..., min_length=1, description="自然语言指令")


class CommandResponse(BaseModel):
    type: str
    message: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = None
    cases: Optional[List[Dict[str, Any]]] = None
    report: Optional[Dict[str, Any]] = None


class PageElementResponse(BaseModel):
    tag: str
    type: str
    name: str
    text: str
    placeholder: str
    selector: str
    x: float
    y: float
    width: float
    height: float


class HealthResponse(BaseModel):
    status: str
    version: str
    agent_state: Dict[str, Any]


class LLMConfigRequest(BaseModel):
    model: Optional[str] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    api_url: Optional[str] = None
    temperature: Optional[float] = None


class LLMTestRequest(BaseModel):
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_url: Optional[str] = None


class PageParseRequest(BaseModel):
    url: str
    browser: str = "chromium"
    task_id: Optional[int] = None
