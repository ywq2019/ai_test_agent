# AI 测试工具平台

基于 **AI 大模型 + LangGraph + Playwright** 的智能化零代码全场景自动化测试平台，覆盖 UI 自动化与接口自动化双引擎，支持 Claude / DeepSeek / GPT / Gemini 等任意模型一键切换。

---

<div align="center">

## 🎬 平台演示

<img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/AI%E5%B9%B3%E5%8F%B0%E6%BC%94%E7%A4%BA%E8%A7%86%E9%A2%91_1904w.gif" width="90%" alt="AI 测试平台演示"/>

> ⏳ **提示**：演示中包含 AI 生成测试用例的完整过程，AI 推理需要一定时间，请耐心观看。

</div>

---

## 项目简介

AI 测试工具平台是一款面向测试工程师的智能测试平台，核心理念是让测试人员**无需编写代码**，通过 AI 大模型完成从需求文档解析、测试用例设计、自动化执行到报告生成的完整测试闭环。

平台提供三套并行的用例生成与执行体系：

- **AI 用例生成**（文档驱动）：上传需求文档，分段调用 AI，按功能模块并行生成包含测试方法标注的高质量用例，支持导出 Markdown / XMind，支持**需求变更增量更新**（差异分析 + 用例级保留/废弃/新增）
- **WebUI 自动化**（页面驱动）：解析目标页面元素，结合需求文档，生成可直接被 Playwright 执行的 UI 自动化测试用例，支持**需求变更增量更新**
- **接口自动化**：支持接口用例管理、AI 生成、单测执行、测试计划编排、压力测试与全局变量池，覆盖完整 API 测试场景

***

## 核心功能

### AI 用例生成（文档驱动）

| 功能 | 说明 |
| --- | --- |
| 分段生成 | 先提取功能模块，再并行逐模块生成（Semaphore=2），每次 AI 调用输出量可控，不超时 |
| 6 种测试方法 | 等价类划分、边界值分析、判定表、场景法、错误推测、状态转换，每条用例标注所用方法 |
| 多维度覆盖 | 同步生成功能用例 + 性能用例 + 兼容性用例 |
| 覆盖度优化 | 分析已有用例盲区，逐模块追加补充用例（边界、异常、状态转换） |
| 覆盖度分析 | 综合评分 + 测试方法覆盖情况 + 优先级分布 + 模块分布 + 优化建议（排除废弃用例） |
| 多格式导出 | Markdown（含完整用例表格）+ XMind（思维导图） |
| 模块内批量删除 | 每个功能模块表格支持多选 + 批量删除用例 |
| **需求变更增量更新** | 上传新版文档 → AI Diff 分析变更范围 → 仅对 changed/added 模块做用例级合并（保留旧用例 + 废弃已删除功能点 + 新增新场景），unchanged 模块直接保留；性能/兼容等通用测试模块永不因需求变更废弃 |
| **废弃用例管理** | 废弃用例追加到模块末尾（删除线展示），默认隐藏，支持「显示废弃用例」开关 |
| **版本追踪** | 每次增量更新创建新记录，`parent_id` 指向上一版本，`diff_summary` 记录变更摘要 |
| 取消操作 | 生成/优化过程中支持随时点击「取消」中止请求 |
| test-case-pro-max 技能 | 可在技能管理页启用，启用后使用增强提示词生成更高质量用例 |

### WebUI 自动化

#### 用例管理（页面驱动）

| 功能 | 说明 |
| --- | --- |
| 页面元素解析 | Playwright 自动抓取可交互元素（input/button/select/textarea），提取 CSS 选择器；自动识别移动端 H5 页面，切换 UA，等待 networkidle 确保动态渲染完成 |
| AI 生成用例 | 结合页面元素 + 需求文档 + 目标 URL，分段生成含具体 selector 和测试数据的可执行用例 |
| 生成进度 | WebSocket 实时推送生成阶段（模块识别→逐模块生成→完成），支持随时取消 |
| 用例优化 | 逐模块分析覆盖缺口，追加边界值/异常分支/状态转换补充用例 |
| 覆盖度分析 | 元素覆盖率 + 优先级分布 + 模块覆盖 + 具体优化建议（自动排除废弃用例） |
| **需求变更增量更新** | 上传新版需求文档 → AI Diff 分析 → 用例级保守合并（默认保留所有旧用例，只废弃功能已完全删除的用例，补充新场景用例）|
| 用例管理 | 新建、编辑、批量启用/禁用/删除，按任务筛选；废弃标记（`deprecated`）与用户禁用（`enabled`）字段分离，禁用用例仍可手动执行，废弃用例自动跳过 |

#### 测试执行

| 功能 | 说明 |
| --- | --- |
| 批量执行 | 按任务执行所有启用用例，支持指定用例 ID 子集执行；废弃用例自动过滤，不参与执行 |
| 实时进度 | 通过 WebSocket 推送每条用例执行结果，无需刷新页面 |
| 执行控制 | 支持暂停（当前用例完成后生效）、继续、停止 |
| 自动截图 | 每条用例执行后截图，文件名标注 pass/fail |
| 测试报告 | 自动生成含统计图表、失败截图、完整执行日志的 HTML 报告 |

### 接口自动化

#### 接口测试

| 功能 | 说明 |
| --- | --- |
| 项目管理 | 多项目隔离，支持配置 Base URL、全局请求头、鉴权方式（Bearer / Basic / API Key） |
| 代理配置 | 支持 HTTP / HTTPS / SOCKS5 代理，留空直连 |
| Hosts 映射 | 类 `/etc/hosts` 格式，将指定域名的请求打到自定义 IP，适用于测试环境 DNS 隔离场景 |
| 用例管理 | 新建、编辑、批量启用/禁用/删除，支持 GET/POST/PUT/DELETE 等全 HTTP 方法 |
| AI 生成用例 | 粘贴 Swagger / OpenAPI 文档或功能描述，AI 自动生成含断言的接口用例 |
| 参数化 | 支持全局变量池（`{{var}}`）、内置函数（随机字符串/时间戳/UUID 等）、自定义 Python 脚本函数 |
| 前置用例 | 用例间依赖编排，支持配置登录前置用例，自动提取 Token 注入后续请求 |
| 鉴权失败重试 | 配置失败特征（状态码/响应字段），命中后自动重跑前置用例刷新 Token 并重试 |
| 变量提取 | 从响应 JSON/Header 中提取字段写入全局变量池，跨用例传递 |
| 断言 | 支持状态码、响应体字段、响应时间多维度断言 |
| 单测执行 | 按项目/勾选用例执行，WebSocket 实时推送每条用例结果 |
| 压力测试 | 配置并发用户数、持续时长、爬坡时间，实时推送 TPS / P95 / P99 等性能指标 |
| AI 报告分析 | 执行完成后调用 LLM 自动分析失败原因、性能瓶颈，给出修复建议 |
| 全局变量池 | 统一管理跨项目变量，支持手动创建、用例执行自动写入、页面实时查看 |

#### 测试计划

将多个项目的接口用例按顺序组合，共享变量上下文，实现跨服务的端到端接口链路测试。

| 功能 | 说明 |
| --- | --- |
| 计划管理 | 新建、编辑、删除测试计划，支持配置描述、代理地址、Hosts 映射 |
| 步骤编排 | 从任意项目拖入接口用例，自由排序、启用/禁用单步 |
| 共享变量 | 所有步骤共享同一 `var_store`，前一步提取的变量可直接用于后续步骤的参数/断言 |
| 代理配置 | 计划级代理优先级高于项目级，可按计划统一走指定网络环境 |
| Hosts 映射 | 计划级 hosts 条目覆盖项目级同名条目，两者不冲突的条目合并生效 |
| 异步执行 | 后台执行，执行期间 WebSocket 实时推送每步进度（步骤名/状态/耗时/响应码） |
| 执行报告 | 记录每次执行的汇总（通过率/总步数/耗时）及每步详情（断言结果/提取变量/响应预览） |
| 报告可视化 | 卡片式报告列表，圆环图显示通过率，颜色区分通过/警告/失败 |
| AI 分析 | 一键调用 LLM 分析失败步骤、断言偏差，给出修复建议，结果结构化展示并可复制 |
| 批量删除 | 多选报告批量删除 |

***

## 技术栈

### 后端

| 技术 | 说明 |
| --- | --- |
| Python 3.11+ | 主语言，全异步架构 |
| FastAPI 0.138 | ASGI Web 框架 |
| Uvicorn | ASGI 服务器（端口 4000） |
| SQLAlchemy 2.0 + aiosqlite / asyncpg | 异步 ORM，本机用 SQLite，Docker 部署自动切换 PostgreSQL |
| httpx | 异步 HTTP 客户端，支持代理 / 自定义 transport（Hosts 映射） |
| LangChain + LangGraph | LLM 对话代理工作流（可选，需配置 API Key） |
| httpx LLM 调用 | AI 用例生成核心路径，统一 HTTP API，自动判断 Anthropic / OpenAI 格式 |
| Playwright 1.39 | 浏览器自动化（Chromium / Firefox / WebKit），支持 networkidle 等待策略 |
| Jinja2 | HTML 报告模板渲染 |
| loguru | 滚动日志，按日切割 |
| PyYAML | 技能配置读取 |
| pydantic-settings | 环境变量管理 |

### 前端

| 技术 | 说明 |
| --- | --- |
| Vue 3.4 + Vite 5 | 前端框架 + 构建工具 |
| Element Plus 2.14 | UI 组件库 |
| Pinia 2.1 | 状态管理 |
| Vue Router 4.2 | 路由 |
| ECharts 5.5 | 报告图表可视化 |
| Axios 1.6 | HTTP 客户端（生成接口超时 420s，支持 AbortController 取消） |
| WebSocket 原生 API | 执行进度、生成进度、压测指标实时推送 |

***

## AI 集成方式

### 用例生成：统一 HTTP API（支持任意模型）

用例生成（AI 用例生成页 + 用例管理页 + 接口用例生成）统一通过 HTTP API 调用，读取大模型配置页的设置，**支持一键切换任意模型**：

```python
# 自动判断 Anthropic 或 OpenAI 兼容格式
is_anthropic = "anthropic.com" in base_url or model.startswith("claude")

if is_anthropic:
    # Anthropic 格式
    POST /v1/messages  →  x-api-key + anthropic-version
else:
    # OpenAI 兼容格式
    POST /v1/chat/completions  →  Authorization: Bearer
```

分段生成流程：

```
Step-1  提取功能模块（60s）
        ↓
Step-2  并行逐模块生成用例（Semaphore=2，每模块 90s）
        ↓
合并   统一编号 TC001…TCN，汇总输出
```

需求变更增量更新流程：

```
上传新文档
    ↓
Step-1  AI Diff 分析（传入旧模块名列表作约束，防止 AI 自创模块名）
        → 输出 changed / added / removed / unchanged 模块清单
    ↓
Step-2  对 changed 模块做用例级保守合并（默认保留旧用例，只废弃已彻底删除的功能点）
        对 added 模块全量生成新用例
        对 unchanged/未分类模块直接保留（文本搜索二次校验）
        对 removed 模块整体废弃（性能/兼容等通用模块豁免）
    ↓
保存新版本记录（parent_id 指向旧版，旧版标记 deprecated）
```

支持模型（大模型配置页切换即生效）：

| 提供商 | 模型示例 | API URL |
| --- | --- | --- |
| Claude（Anthropic） | claude-sonnet-4-6 | https://api.anthropic.com |
| DeepSeek | deepseek-v4-flash | https://api.deepseek.com |
| OpenAI | gpt-4o | https://api.openai.com |
| 月之暗面 | moonshot-v1-8k | https://api.moonshot.cn |
| Ollama（本地） | llama3 | http://localhost:11434 |
| 任意 OpenAI 兼容代理 | — | 填入代理地址即可 |

### 可选路径：LangGraph 对话代理

配置 `.env` 中的 `AI_API_KEY` 和 `AI_API_URL` 后启用，支持通过自然语言指令驱动完整测试流程：

```
用户指令 → LangGraph 状态机 → 工具调用（parse_page / generate_cases / execute_tests）→ 输出结果
```

### AI 报告分析

接口测试报告和测试计划执行报告均支持一键 AI 分析，通过大模型配置页的设置调用 LLM，对失败用例、断言偏差、性能指标进行结构化分析并给出修复建议。

***

## 插件化技能架构

```
skills/
├── ai_case_generator.py       # AI 用例生成核心（分段 + 增量更新 + 覆盖度优化）
├── case_generator.py          # UI 用例生成（分段 + 增量更新 + 优化 + 覆盖度分析）
├── api_case_generator.py      # 接口用例 AI 生成（Swagger / 描述驱动）
├── api_executor.py            # 接口用例执行（断言 + 变量提取 + 前置依赖 + 代理 + Hosts）
├── api_load_tester.py         # 接口压力测试（并发 + TPS/P95/P99 指标）
├── param_resolver.py          # 参数解析（全局变量 / 内置函数 / 自定义脚本）
├── test_executor.py           # UI 用例执行（Playwright）
├── report_generator.py        # 报告生成（HTML + 图表）
├── langchain_tools.py         # 自动注册 LangChain Tools
├── skill_loader.py            # 技能目录扫描
├── test_case_pro_max/         # 增强提示词技能（可在技能管理页启用）
│   ├── SKILL.md
│   └── prompt.yaml
├── page_parser/               # 页面元素解析技能
├── document_parser/           # PDF/Word/Excel 文档解析技能
├── case_generator/            # 技能元数据目录
├── test_executor/
└── report_generator/
```

**新增技能**：在 `skills/` 下创建子目录，放入 `SKILL.md` 和 `scripts/run.py`，重启自动发现注册。

***

## 项目结构

```
ai_test_agent/
├── main.py                    # 应用入口（Uvicorn，前端静态托管，Vue Router 支持）
├── Dockerfile                 # 多阶段构建（前端 + 后端一体）
├── docker-compose.yml         # 一键部署（app + PostgreSQL）
├── .env                       # 本机开发配置（SQLite）
├── .env.docker                # Docker 部署配置（PostgreSQL）
├── .dockerignore              # Docker 构建排除文件
├── requirements.txt           # Python 依赖（含 asyncpg）
├── agent/
│   ├── core.py                # UITestAgent 主控（状态按 task_id 隔离）
│   └── langgraph_agent.py     # LangGraph 对话代理
├── api/
│   ├── routes.py              # 全部 REST + AI 端点（含增量更新端点）
│   ├── schemas.py             # Pydantic 数据模型（含 deprecated 字段）
│   ├── websocket.py           # WebSocket 端点
│   └── websocket_manager.py   # WS 连接管理（按 client_id 分组广播）
├── skills/                    # 技能与 AI 核心逻辑
│   ├── ai_case_generator.py   # AI 文档驱动用例生成（统一 HTTP API + 增量更新）
│   ├── case_generator.py      # UI 用例生成（统一 HTTP API + 增量更新）
│   ├── api_case_generator.py  # 接口用例 AI 生成（统一 HTTP API）
│   ├── api_executor.py        # 接口用例执行引擎（含代理 / Hosts 映射）
│   ├── api_load_tester.py     # 压力测试引擎
│   └── param_resolver.py      # 参数解析（变量 / 函数 / 脚本）
├── tools/
│   ├── browser.py             # Playwright 浏览器封装（networkidle 等待 + 移动端 UA 自适应）
│   ├── config.py              # 环境变量（pydantic-settings）
│   ├── database.py            # SQLAlchemy 模型（含增量更新追踪字段，兼容 SQLite / PostgreSQL）
│   └── document_parser.py     # PDF / Word / Excel / HTML 解析
├── ui/
│   ├── src/
│   │   ├── api/index.js       # Axios 封装（含各接口超时配置 + AbortController 取消支持）
│   │   ├── router/            # Vue Router
│   │   ├── stores/task.js     # Pinia 状态
│   │   └── views/
│   │       ├── AiCases.vue    # AI 用例生成（文档驱动 + 增量更新 + 废弃用例管理 + 取消操作）
│   │       ├── Home.vue       # 首页
│   │       ├── Tasks.vue      # 任务管理
│   │       ├── Cases.vue      # 用例管理（AI生成 + 增量更新 + 优化 + 覆盖度 + deprecated 字段）
│   │       ├── Execution.vue  # UI 测试执行（实时 WS）
│   │       ├── Reports.vue    # UI 测试报告
│   │       ├── ApiTest.vue    # 接口测试（项目/用例/执行/压测/报告）
│   │       ├── TestPlan.vue   # 测试计划（编排 + 执行 + 报告 + AI 分析）
│   │       ├── LLM.vue        # 大模型配置
│   │       └── Skills.vue     # 技能管理
│   └── dist/                  # 构建产物（FastAPI 静态文件服务）
├── uploads/documents/         # 上传文档（自动创建）
├── ai_cases/                  # AI 生成的 MD / XMind 文件
├── screenshots/               # 执行截图
├── reports/                   # HTML 报告
└── logs/                      # 运行日志
```

***

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Playwright 浏览器内核
- 任意 AI 大模型 API Key（DeepSeek / Claude / GPT 等）

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/ywq2019/ai_test_agent.git
cd ai_test_agent

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 安装 Playwright 浏览器
playwright install chromium

# 4. 安装前端依赖并构建
cd ui
npm install
npm run build
cd ..
```

### 配置

复制并编辑 `.env`：

```ini
# 应用信息
APP_NAME=AI 测试工具平台
APP_VERSION=1.0.0

# 服务配置
HOST=0.0.0.0
PORT=4000
DEBUG=True
CORS_ORIGINS=["*"]

# 数据库
DATABASE_URL=sqlite+aiosqlite:///./uitest_agent.db

# AI 大模型配置（所有 AI 功能统一使用，支持任意 OpenAI 兼容接口）
AI_API_KEY=your_api_key
AI_API_URL=https://api.deepseek.com       # 不要加 /v1，代码自动拼接
AI_MODEL=deepseek-v4-flash
AI_MODEL_NAME=DeepSeek V4 Flash
AI_TEMPERATURE=0.5

# 浏览器
DEFAULT_BROWSER=chromium

# 数据目录
REPORT_OUTPUT_DIR=./reports
SCREENSHOT_DIR=./screenshots
LOG_DIR=./logs
UPLOAD_DIR=./uploads
```

> 也可以在平台启动后进入**大模型配置**页面直接修改，支持 DeepSeek / Claude / GPT / Gemini / Moonshot / Ollama 等任意 OpenAI 兼容接口。

### 启动

项目分为**后端**（FastAPI）和**前端**（Vue + Vite）两个服务，需分别启动。

---

#### 第一步：启动后端（必须先启动）

打开一个终端，在项目根目录执行：

```bash
cd E:\ai_test_agent

# 前台运行（推荐开发时使用，可直接看日志）
python main.py

# 或后台运行（Windows，日志写入文件）
start /B python main.py > logs\server_out.txt 2>&1
```

后端启动成功后，终端会输出类似：

```
INFO     Starting Automated UI Testing Agent...
INFO     Database initialized
INFO     LangChain tools registered
INFO     Uvicorn running on http://0.0.0.0:4000
```

---

#### 第二步：启动前端开发服务器

**另开一个新终端**，必须先 `cd` 进入 `ui` 目录再运行：

```bash
cd E:\ai_test_agent\ui
npm run dev
```

前端启动成功后，终端会输出类似：

```
  VITE v5.x.x  ready in xxx ms

  ➜  Local:   http://localhost:8090/
  ➜  Network: use --host to expose
```

---

#### 本地访问地址

两个服务都启动后，通过以下地址访问：

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| **平台主页面（推荐）** | http://localhost:8090 | 前端 Vue 界面，开发模式 |
| **后端 API** | http://localhost:4000 | FastAPI 直接访问 |
| **API 文档（Swagger）** | http://localhost:4000/docs | 接口调试文档 |
| **健康检查** | http://localhost:4000/health | 服务状态检测 |

> **推荐访问 `http://localhost:8090`**，前端开发服务器会自动将 `/api`、`/ws`、`/screenshots`、`/reports` 等请求代理到后端 4000 端口，无需手动配置跨域。

---

#### 仅使用后端（生产模式）

如果只想运行后端（不启动前端 dev server），需要先构建前端：

```bash
cd E:\ai_test_agent\ui
npm run build
cd ..
python main.py
```

构建产物会输出到 `ui/dist/`，FastAPI 会自动将其挂载为静态文件，直接访问 `http://localhost:4000` 即可。

---

#### 停止服务

- 前台运行：在对应终端按 `Ctrl + C`
- 后台运行：`taskkill /F /IM python.exe`（停止后端）、`taskkill /F /IM node.exe`（停止前端）

***

## 使用流程

### 流程一：AI 用例生成（文档驱动）

适用于**有需求文档**、生成高质量功能测试用例并导出的场景。

```
1. 进入「AI 用例生成」菜单
2. 点击「新建生成」→ 填写任务名，上传需求文档（PDF/Word/HTML）或粘贴文本
3. 选择输出格式（Markdown / XMind），点击「开始生成」（生成中可随时取消）
4. 等待分段生成完成（进度条实时显示当前模块）
5. 查看生成结果，点击「覆盖度分析」评估测试覆盖情况
6. 如需补充，点击「覆盖度优化」自动追加缺口用例
7. 下载 Markdown 或 XMind 文件

需求变更时：
8. 点击「文档变更更新」→ 上传新版需求文档
9. 查看 AI Diff 分析结果（变更/新增/删除/未变更模块统计）
10. 确认后执行增量更新：旧用例保留 + 废弃已删除功能点 + 新增新场景用例
11. 废弃用例默认隐藏，可通过「显示废弃用例」开关查看
```

> 启用「技能管理」中的 `test-case-pro-max` 可使用增强提示词，生成更规范的用例（含测试方法标注）。

### 流程二：WebUI 自动化测试（页面驱动）

适用于**直接执行自动化测试**的场景。

```
1. 「任务管理」→ 新建任务，填写目标 URL，可选上传需求文档
2. 点击「解析页面」，等待 Playwright 抓取页面元素
   （移动端 H5 页面自动切换 UA，等待 networkidle 确保动态渲染完成）
3. 「用例管理」→ 选择任务 → 点击「AI 生成用例」
   - 进度弹窗实时显示生成阶段，支持取消
   - 生成完成后可点击「覆盖度分析」查看覆盖情况
   - 点击「优化用例」自动追加补充用例
4. 勾选用例 → 点击「批量执行测试」，进入执行页面
   （禁用用例不会自动执行；废弃用例强制跳过）
5. 「报告查看」查看结果，下载 HTML 报告

需求变更时：
6. 点击「文档变更更新」→ 上传新版需求文档（可选勾选「同时重新抓取页面元素」）
7. 查看变更范围 → 确认增量更新
```

### 流程三：接口测试

适用于**单接口/单项目 API 测试与压力测试**的场景。

```
1. 「接口测试」→ 新建项目，填写 Base URL、鉴权方式
   - 可选：配置代理地址（http://proxy:8080）
   - 可选：配置 Hosts 映射（47.94.236.243 japi.example.com）
2. 手动新建用例，或粘贴 Swagger 文档点击「AI 生成」批量创建用例
3. 配置断言规则（状态码 / 响应字段 / 响应时间）
4. 配置变量提取，将登录 Token 等字段写入全局变量池，供后续用例复用
5. 点击「执行」，WebSocket 实时推送每条用例结果
6. 查看执行报告，点击「AI 分析」获取失败原因和修复建议
7. 如需压测：配置并发用户数 / 持续时长 / 爬坡策略，实时查看 TPS / P95 / P99 指标
```

### 流程四：测试计划（跨项目接口链路测试）

适用于**多服务端到端接口链路测试**的场景，例如：登录 → 获取数据 → 提交订单 → 查询结果。

```
1. 「测试计划」→ 新建计划，填写名称、描述
   - 可选：配置计划级代理（优先级高于项目代理）
   - 可选：配置计划级 Hosts 映射（覆盖项目级同名条目）
2. 点击「添加步骤」，从任意项目选择接口用例，调整执行顺序
3. 点击「执行计划」，后台异步执行，WebSocket 实时推送每步进度
   - 步骤间共享变量上下文（前步提取的变量可直接用于后步）
4. 执行完成后查看报告：
   - 卡片列表展示历史报告（通过率/耗时/步骤数）
   - 点击「详情」查看每步断言结果、提取变量、响应预览
   - 点击「AI 分析」获取失败分析和修复建议
5. 支持多选报告批量删除
```

***

## 代理与 Hosts 映射

接口测试和测试计划均支持配置网络环境，适用于多套测试环境（内网/外网/代理）的切换。

### 代理地址

支持 HTTP / HTTPS / SOCKS5 协议，留空表示直连：

```
# 以下写法均支持
192.168.1.100:8080              ← 自动补 http://
http://192.168.1.100:8080
https://proxy.corp.com:3128
socks5://user:pass@host:1080
```

**优先级**：测试计划代理 > 项目代理 > 直连

### Hosts 映射

格式同系统 `/etc/hosts`，将指定域名的连接打到目标 IP，但保留原域名作为 `Host` 请求头（HTTPS 下配合 `verify=False` 使用）：

```
# 格式：IP 域名（每行一条，支持一 IP 对多域名，# 开头为注释）
47.94.236.243 japi.hqwx.com
192.168.1.10  api.dev.example.com staging.example.com
```

**优先级**：测试计划 hosts 条目 > 项目 hosts 条目（相同域名计划覆盖项目，不冲突的条目合并生效）

***

## 接口说明

### 主要 REST 端点

**WebUI 自动化**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/tasks` | 创建任务 |
| POST | `/api/v1/parse/page` | 解析页面元素 |
| POST | `/api/v1/cases/generate/{task_id}` | AI 生成 UI 用例（分段） |
| POST | `/api/v1/cases/optimize/{task_id}` | 优化用例（追加补充） |
| GET  | `/api/v1/cases/coverage/{task_id}` | 用例覆盖度分析（排除废弃用例） |
| POST | `/api/v1/cases/doc-diff-check/{task_id}` | 文档变更检测（Diff 分析，不修改数据） |
| POST | `/api/v1/cases/incremental-update/{task_id}` | 用例增量更新（文档变更后） |
| POST | `/api/v1/execute` | 执行 UI 测试用例（自动跳过废弃用例） |

**AI 用例生成**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/ai-cases/generate` | AI 用例生成（文档驱动） |
| POST | `/api/v1/ai-cases/{id}/optimize` | AI 用例覆盖度优化 |
| GET  | `/api/v1/ai-cases/{id}/coverage` | AI 用例覆盖度分析（排除废弃用例） |
| GET  | `/api/v1/ai-cases/{id}/download` | 下载 MD / XMind |
| POST | `/api/v1/ai-cases/{id}/diff-check` | 文档变更检测（Diff 分析，不修改数据） |
| POST | `/api/v1/ai-cases/{id}/incremental-update` | 增量更新（创建新版本记录，旧版标记 deprecated） |

**接口测试**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/api-test/projects` | 创建接口项目 |
| GET  | `/api/v1/api-test/projects` | 项目列表 |
| PUT  | `/api/v1/api-test/projects/{id}` | 更新项目（含代理/Hosts配置） |
| POST | `/api/v1/api-test/cases` | 新建接口用例 |
| PUT  | `/api/v1/api-test/cases/{id}` | 编辑接口用例 |
| POST | `/api/v1/api-test/projects/{id}/cases/generate` | AI 生成接口用例 |
| POST | `/api/v1/api-test/projects/{id}/execute` | 执行接口用例 |
| POST | `/api/v1/api-test/projects/{id}/load` | 启动压力测试 |
| POST | `/api/v1/api-test/load/stop` | 停止压力测试 |
| GET  | `/api/v1/api-test/projects/{id}/reports` | 接口测试报告列表 |
| POST | `/api/v1/api-test/reports/{id}/analyze` | AI 分析接口测试报告 |
| GET  | `/api/v1/global-vars` | 全局变量池列表 |

**测试计划**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET  | `/api/v1/test-plans` | 计划列表 |
| POST | `/api/v1/test-plans` | 新建计划 |
| GET  | `/api/v1/test-plans/{id}` | 计划详情（含步骤） |
| PUT  | `/api/v1/test-plans/{id}` | 更新计划（含代理/Hosts配置） |
| DELETE | `/api/v1/test-plans/{id}` | 删除计划 |
| POST | `/api/v1/test-plans/{id}/run` | 执行计划（异步） |
| GET  | `/api/v1/test-plans/{id}/reports` | 执行报告列表 |
| DELETE | `/api/v1/test-plans/reports/batch` | 批量删除报告 |
| POST | `/api/v1/test-plans/reports/{id}/analyze` | AI 分析执行报告 |

完整文档：`http://localhost:4000/docs`

### WebSocket 事件

连接地址：`ws://localhost:4000/ws?client_id=<id>`

| client_id | 事件类型 | 说明 |
| --- | --- | --- |
| `ui` | `execution_progress` | UI 用例执行进度 |
| `ai_gen` | `ai_gen_progress` | AI 用例生成/优化/增量更新进度 |
| `cases_gen` | `cases_gen_progress` | UI 用例生成/增量更新进度 |
| `cases_opt` | `cases_opt_progress` | 用例优化进度 |
| `api_gen` | `api_gen_progress` | 接口用例 AI 生成进度 |
| `api_exec` | `api_exec_progress` | 接口用例执行进度 |
| `api_load` | `load_metrics` | 压测实时指标推送 |
| `plan_<id>` | `plan_step_start` / `plan_step_done` / `plan_done` | 测试计划执行进度 |

***

## 当前架构与部署

### 当前架构（Windows 单机）

```
浏览器 → FastAPI（4000）→ SQLite
                         → Playwright（独立 Context，并发隔离）
                         → httpx LLM API（任意大模型）
                         → httpx（代理 / Hosts 映射）
```

适合个人或小团队（局域网共享，最多 3 个浏览器并发）使用。

### 局域网共享（团队使用）

无需额外配置，启动后端后团队成员直接通过内网 IP 访问：

```bash
# 查看本机内网 IP
ipconfig   # Windows
# 找到以太网 IPv4 地址，如 10.96.41.42

# 团队成员访问
http://10.96.41.42:4000
```

**前提**：开放 Windows 防火墙入站端口：

```powershell
New-NetFirewallRule -DisplayName "AI测试平台 4000" -Direction Inbound -Protocol TCP -LocalPort 4000 -Action Allow
```

### 服务器部署（Nginx 反代）

**前端打包**（已内置到 FastAPI 静态文件服务，通常无需单独配置）：

```bash
cd ui && npm run build
```

**Nginx 配置**：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:4000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws {
        proxy_pass http://127.0.0.1:4000/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

### 多人并发部署（已实施）

以下改造已完成，当前版本已支持多人并发使用：

| 改造项 | 状态 | 说明 |
| --- | --- | --- |
| 浏览器 Context 隔离 | ✅ 已完成 | `BrowserPool` 改为共享 Browser + 每请求独立 Context，`Semaphore(3)` 限制并发，超出排队等待 |
| Agent 状态隔离 | ✅ 已完成 | `AgentState` 按 `task_id` 字典隔离，多用户并发操作互不干扰 |
| 执行状态隔离 | ✅ 已完成 | `TestExecutor` 执行状态按 `task_id` 独立管理，暂停/停止精确控制单个任务 |
| 前端静态托管 | ✅ 已完成 | `ui/dist` 挂载到 FastAPI，无需单独启动前端服务 |
| WebSocket 端口自适应 | ✅ 已完成 | WS 地址改为 `location.host`，任何端口访问均正常推送进度 |

**待扩展（大规模部署）**：

| 改造项 | 状态 | 说明 |
| --- | --- | --- |
| SQLite → PostgreSQL | ✅ docker-compose 已集成 | 通过 Docker 部署自动使用 PostgreSQL，适合 10 人以上并发写入 |
| 加认证中间件 | 🔲 待实现 | 基于现有 `User` 表，加 JWT 路由保护，隔离多用户数据 |
| 任务队列 | 🔲 待实现 | 用 Celery + Redis 隔离并发执行任务，支持水平扩展 |

### Docker 一键部署（服务器）

项目已内置 `Dockerfile` + `docker-compose.yml`，支持一键部署到任意 Linux 服务器。

**前提条件**：服务器已安装 Docker 和 Docker Compose

```bash
git clone https://github.com/ywq2019/ai_test_agent.git && cd ai_test_agent && docker compose up -d
```

启动成功后访问 `http://服务器IP:4000`，进入**大模型配置**页填写 API Key 即可使用。

**包含服务**：

| 服务 | 说明 |
| --- | --- |
| `app` | FastAPI 后端 + 前端静态文件，监听 4000 端口 |
| `db` | PostgreSQL 15，自动建表，数据持久化到 Volume |

**后续维护**：

```bash
# 更新代码
git pull && docker compose up -d --build

# 查看日志
docker compose logs -f

# 停止服务
docker compose down

# 重启（数据不丢失）
docker compose restart
```

**数据持久化**：数据库（PostgreSQL Volume）、报告、截图、日志均挂载到 Docker Volume，容器重启或重建后数据不丢失。

**本机开发 vs 服务器部署**：

| 环境 | 数据库 | 说明 |
| --- | --- | --- |
| 本机 Windows 开发 | SQLite | 零配置，直接 `python main.py` |
| 服务器 Docker 部署 | PostgreSQL | 自动启动，支持多人并发 |

***

## 截图

<table>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/1.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/2.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/3.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/4.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/5.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/6.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/7.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/8.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/9.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/10.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/11.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/12.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/13.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/14.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/15.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/16.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/17.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/18.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/19.png"/></td>
        <td></td>
    </tr>
</table>

***

## 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE) 文件。
