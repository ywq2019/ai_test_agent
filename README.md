# AI 测试工具平台

基于 **AI 大模型 + LangGraph + Playwright** 的智能化零代码全场景自动化测试平台，覆盖 UI 自动化与接口自动化双引擎，支持 Claude / DeepSeek / GPT / Gemini 等任意模型一键切换。

📐 [设计思路与技术决策 →](./DESIGN.md)

<div align="center">

<img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/AI%E6%B5%8B%E8%AF%95%E5%B7%A5%E5%85%B7%E5%B9%B3%E5%8F%B0_1904w.gif" width="90%" alt="AI 测试平台演示"/>

> ⏳ 演示包含 AI 生成测试用例的完整过程，AI 推理需要一定时间，请耐心观看。

</div>

***

## 快速部署

### Docker 一键部署（推荐）

**环境要求：** Docker 20.10+（含 Docker Compose v2）

```bash
git clone https://github.com/ywq2019/ai_test_agent.git
cd ai_test_agent
```

编辑 `.env.docker`，修改以下配置（其余保持默认即可）：

| 配置项 | 说明 | 生成命令 |
| --- | --- | --- |
| `SECRET_KEY` | JWT 签名密钥，默认值有安全风险 | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `POSTGRES_PASSWORD` | 数据库密码，同时改 `DATABASE_URL` 里对应的密码 | — |
| `AI_API_KEY` | 大模型 API Key（也可部署后在平台页面填写） | — |
| `AI_API_URL` | 大模型接口地址，默认 DeepSeek，按需替换 | — |
| `AI_MODEL` | 模型名称，与 `AI_API_URL` 对应 | — |

```bash
docker compose up -d
```

访问 `http://服务器IP:4000`，默认账号 `admin / admin123`，**登录后立即修改密码**。

```bash
git pull && docker compose up -d --build  # 更新
docker compose logs -f app                 # 查看日志
docker compose down                        # 停止
```

> **升级说明**：新版本在服务启动时自动执行数据库迁移，直接 `--build` 重启即可，无需手动操作。

> **数据备份**：数据库和文件存储在 Docker 命名卷 `pg_data` / `app_data` 中，使用 `docker volume inspect` 查看实际路径，迁移时一并复制即可。

### 本地启动

**环境要求：** Python 3.11+，Node 18+

```bash
# 1. 克隆项目
git clone https://github.com/ywq2019/ai_test_agent.git
cd ai_test_agent

# 2. 创建 .env 配置文件（必须，git clone 不包含此文件）
cp .env.docker .env
# 然后编辑 .env，至少填写 AI_API_KEY 和 AI_API_URL

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 安装 Playwright 浏览器
playwright install chromium
# Linux 用户还需要（Mac/Windows 跳过）：
# sudo playwright install-deps chromium

# 5. 构建前端
cd ui && npm install && npm run build && cd ..

# 6. 启动（访问 http://localhost:4000）
python main.py
```

开发模式（前端热更新）：

```bash
python main.py          # 终端1：后端 4000
cd ui && npm run dev    # 终端2：前端 8090（代理到后端）
```

> **本地 vs Docker 数据库说明**
>
> | | 本地启动 | Docker 部署 |
> | --- | --- | --- |
> | 数据库 | SQLite（项目根目录 `uitest_agent.db`） | PostgreSQL（Docker 卷 `pg_data`） |
> | RAG 向量检索 | 降级为关键词匹配（不支持 pgvector） | pgvector 完整支持 |
> | 数据位置 | 项目根目录下 `.db` 文件，直接可见 | Docker 命名卷，`docker volume inspect pg_data` 查路径 |
> | 数据互通 | ❌ 两边数据**不互通**，本地产生的数据切换到 Docker 后不会自动迁移 | |
>
> 如需从本地迁移到 Docker，需手动导出数据（或重新录入）。建议生产环境直接使用 Docker 部署，避免后续迁移麻烦。

***

## 核心功能

### AI 用例生成（文档驱动）

上传需求文档，AI 按功能模块并行生成覆盖 6 种测试方法的高质量用例，支持导出 Markdown / XMind。

| 功能 | 说明 |
| --- | --- |
| **异步后台生成** | 提交后立即返回，完成后 WebSocket 推送，进度实时持久化（断线重连可恢复） |
| 分段并行生成 | 提取模块后并发调用 AI（Semaphore=4），每次输出可控，不超时 |
| 6 种测试方法 | 等价类、边界值、判定表、场景法、错误推测、状态转换 |
| **需求变更增量更新** | AI Diff 分析 → 仅对变更模块做用例级合并，unchanged 模块直接保留 |
| **需求追踪矩阵** | 提取结构化需求条目，建立用例-需求双向映射，生成覆盖率矩阵；一键分析缺口并生成补充用例 |
| **RAG 知识库** | 文档分段入库（pgvector 向量检索，不支持时降级关键词匹配），生成时检索相关段落 |
| 超大文档支持 | BeautifulSoup 深度清洗 HTML；分批并行提取模块（20000字/批） |
| 截断 JSON 自动修复 | LLM 输出被截断时自动补齐，避免丢失已生成内容 |

### WebUI 自动化

Playwright 抓取页面元素，AI 生成含具体 selector 的可执行用例。

| 功能 | 说明 |
| --- | --- |
| 页面元素解析 | 抓取可交互元素，等待 networkidle，支持移动端 H5 |
| **懒加载支持** | 自动分屏滚动（最多 40 屏），高度不变连续 2 次停止 |
| **文档驱动兜底** | 页面元素 ≤3 个时自动切换纯文档驱动模式 |
| 执行控制 | 支持暂停/继续/停止，自动截图，生成 HTML 报告 |
| **报告 PDF 导出** | 复用 Playwright Chromium 渲染，无需额外依赖 |
| **需求变更增量更新** | 保守合并策略，默认保留旧用例 |

### 接口自动化

| 功能 | 说明 |
| --- | --- |
| 多项目管理 | Base URL + 鉴权（Bearer/Basic/API Key）+ 代理 + Hosts 映射 |
| AI 生成用例 | Swagger/自然语言/代码（Python/Java/Go/Node.js/PHP）三种输入 |
| **代码可行性分析** | 识别 `missing`/`mismatch`/`extra`/`risk` 四类偏差，自动生成差异验证用例 |
| 参数化 | 全局变量池 `{{gvar:name}}`、内置函数 `{{uuid()}}`、自定义脚本函数 |
| 前置依赖 | 配置登录前置用例，自动提取 Token，鉴权失败自动重试 |
| 压力测试 | 配置并发/时长/爬坡，实时推送 TPS / P95 / P99 |
| **报告 PDF 导出** | 含用例明细表格 + AI 分析段落 |

### 测试计划

跨项目接口用例编排，共享变量上下文（登录 → 下单 → 查询）。

| 功能 | 说明 |
| --- | --- |
| 步骤编排 | 从任意项目拖入用例，自由排序、启用/禁用 |
| 共享变量 | 所有步骤共享 `var_store`，前步提取后步直接引用 |
| **CI/CD 集成** | Webhook token 触发，支持 Jenkins / GitHub Actions，可选执行完成回调 |
| **报告 PDF 导出** | 含步骤明细 + AI 分析 |

### 工作空间

多租户隔离的顶层单元，一个工作空间对应一套独立的测试数据。

| 功能 | 说明 |
| --- | --- |
| 多空间管理 | 每个用户可创建多个工作空间，数据互不干扰 |
| 成员协作 | 邀请成员加入，role 分 owner（管理成员）/ member（读写数据） |
| 跨模块隔离 | AI 用例、WebUI 任务、接口项目、测试计划均按工作空间隔离 |
| admin 穿透 | 系统管理员可跨空间查看所有数据 |

***

## 稳定性与安全

### 多用户并发

| 机制 | 默认值 | 配置项 |
| --- | --- | --- |
| 全局 LLM Semaphore | 6 并发 | `LLM_CONCURRENCY` |
| Semaphore 等待超时 | 60s | `LLM_SEM_TIMEOUT` |
| 后台生成任务上限 | 3 个 | `MAX_ACTIVE_GENERATE` |
| 接口频率限制 | 生成 5次/分钟，优化/分析 3次/分钟 | slowapi，按真实 IP |
| 反向代理 IP 识别 | `X-Real-IP` → `X-Forwarded-For` → TCP | Nginx 反代时自动识别 |

### 数据隔离

**工作空间级**：AI 用例、WebUI 任务、接口项目、测试计划均挂在工作空间下，成员只能访问所在空间的数据。

**用户级**：未挂载工作空间的数据，普通用户只能看到自己创建的记录；admin 可查看全部。服务启动时自动将历史 NULL 数据归属到默认管理员账号，升级无感知。

### 自愈与告警

| 机制 | 说明 |
| --- | --- |
| 重启状态恢复 | 服务重启时自动将卡住的生成任务重置为 failed，推送 WebSocket 通知 |
| 文件自动清理 | 删除记录时清理整条版本链文件；每天 00:05 扫描孤儿文件 |
| 日志定时清理 | 每天 00:05 清理过期日志（默认保留 7 天），`LOG_RETENTION_DAYS` 可调 |
| Webhook 告警 | ERROR 级日志自动推钉钉/企微/飞书，5 分钟防刷屏；`ALERT_WEBHOOK_URL` 留空则静默 |

### CI/CD 集成

```bash
# 1. 生成 webhook token（需登录）
curl -X PUT "http://your-host:4000/api/v1/test-plans/1/webhook-token" \
  -H "Authorization: Bearer <JWT>" -d '{}'
# → {"webhook_token": "xxx", "trigger_url": "..."}

# 2. 在 Jenkins / GitHub Actions 里触发
curl -f -X POST "http://your-host:4000/api/v1/test-plans/1/trigger?token=xxx"

# 3. 可选：执行完成后回调
curl -f -X POST "...?token=xxx&callback_url=https://ci.example.com/hook"
```

***

## AI 集成

所有 AI 功能统一读取「大模型配置」页，**自动判断 Anthropic / OpenAI 格式**，支持一键切换：

| 提供商 | 模型示例 | API URL |
| --- | --- | --- |
| Claude | claude-opus-4-8 | https://api.anthropic.com |
| DeepSeek | deepseek-v4-flash | https://api.deepseek.com |
| OpenAI | gpt-4o | https://api.openai.com |
| Ollama（本地） | llama3 | http://localhost:11434 |
| 任意 OpenAI 兼容代理 | — | 填入代理地址即可 |

Prompt 统一管理在 `skills/prompts/*.yaml`，无需改代码即可调整生成效果。

***

## 技术栈

| 层 | 技术 | 说明 |
| --- | --- | --- |
| 后端 | Python 3.11+ / FastAPI 0.138 | 全异步 ASGI，Uvicorn 单进程 |
| Agent | LangGraph 1.2 / LangChain 1.3 | LangGraph 编排 Agent 工作流，LangChain 管理工具注册 |
| ORM | SQLAlchemy 2.0 | SQLite（本机）/ PostgreSQL（Docker）双兼容，自动迁移 |
| 浏览器 | Playwright 1.39 | UI 自动化 + PDF 报告导出 |
| 限流 | slowapi | 按真实 IP，支持反向代理 |
| 向量库 | pgvector | RAG 检索，不支持时降级关键词匹配 |
| 鉴权 | python-jose + bcrypt | JWT（7 天有效期）+ 密码哈希 |
| 前端 | Vue 3.4 + Vite 5 + Element Plus 2.14 | 含 ECharts 压测图表、marked Markdown 渲染 |

***

## 接口说明

完整文档：`http://localhost:4000/docs`

| 类别 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 认证 | POST | `/api/v1/auth/login` | 登录，返回 JWT |
| 认证 | PUT | `/api/v1/auth/password` | 修改密码 |
| 用户 | GET/POST/DELETE | `/api/v1/auth/users` | 用户管理（admin） |
| 工作空间 | POST | `/api/v1/workspaces` | 创建工作空间 |
| 工作空间 | GET | `/api/v1/workspaces` | 列出我的工作空间 |
| 工作空间 | POST/DELETE | `/api/v1/workspaces/{id}/members` | 邀请 / 移除成员 |
| AI 用例 | POST | `/api/v1/ai-cases/generate` | 生成用例 |
| AI 用例 | POST | `/api/v1/ai-cases/{id}/incremental-update` | 需求变更增量更新 |
| AI 用例 | POST | `/api/v1/ai-cases/{id}/coverage` | 生成需求追踪矩阵 |
| WebUI | POST | `/api/v1/execute` | 执行测试 |
| WebUI | GET | `/api/v1/reports/{id}/pdf` | 导出 PDF |
| 接口测试 | POST | `/api/v1/api-test/projects/{id}/execute` | 执行用例 |
| 接口测试 | GET | `/api/v1/api-test/reports/{id}/pdf` | 导出 PDF |
| 全局变量 | GET/POST/PUT/DELETE | `/api/v1/global-vars` | 全局变量池管理 |
| 测试计划 | PUT | `/api/v1/test-plans/{id}/webhook-token` | 生成 CI/CD 触发 token |
| 测试计划 | POST | `/api/v1/test-plans/{id}/trigger?token=xxx` | CI/CD 触发（无需 JWT） |
| 测试计划 | GET | `/api/v1/test-plans/reports/{id}/pdf` | 导出 PDF |

**WebSocket 频道**（连接地址：`ws://host:4000/ws?client_id=<频道>`）

| client_id | 说明 |
| --- | --- |
| `ai_gen` | AI 用例生成/优化/增量更新进度 |
| `cases_gen` | WebUI 用例生成进度 |
| `api_exec` | 接口用例执行进度 |
| `api_load` | 压测实时指标（TPS / P95 / P99） |
| `plan_<id>` | 测试计划执行进度 |

***

## 项目结构

```
ai_test_agent/
├── main.py                     # 入口：JWT 中间件、启动恢复、孤儿文件清理、安全检查
├── Dockerfile / docker-compose.yml / .env.docker
├── api/
│   ├── auth.py                 # JWT + owner_filter + check_owner + workspace 权限
│   ├── limiter.py              # slowapi 限流（支持反向代理 IP 识别）
│   ├── schemas.py              # Pydantic 请求/响应模型
│   ├── websocket.py            # WebSocket 连接处理
│   ├── websocket_manager.py    # 多频道广播管理器
│   └── routes/
│       ├── auth.py             # 鉴权、用户管理、健康检查、日志管理
│       ├── workspaces.py       # 工作空间 CRUD + 成员管理
│       ├── webui.py            # WebUI 自动化（含报告 PDF 导出）
│       ├── ai_cases.py         # AI 文档驱动用例（含增量更新/需求追踪）
│       └── api_test.py         # 接口自动化 + 全局变量 + 测试计划 + CI/CD webhook
├── agent/
│   ├── core.py                 # Agent 核心逻辑
│   └── langgraph_agent.py      # LangGraph Agent 初始化与编排
├── skills/
│   ├── ai_case_generator.py    # 文档驱动用例生成（RAG + 并发控制 + JSON 修复）
│   ├── api_case_generator.py   # 接口用例 AI 生成
│   ├── api_executor.py         # 接口用例执行引擎
│   ├── api_load_tester.py      # 压力测试引擎
│   ├── param_resolver.py       # 参数化解析（全局变量池 / 内置函数 / 自定义脚本）
│   ├── rag.py                  # RAG 向量检索（pgvector / 关键词降级）
│   ├── langchain_tools.py      # LangChain 工具注册
│   ├── prompt_loader.py        # YAML Prompt 加载器
│   └── prompts/                # LLM Prompt 配置（YAML，无需改代码即可调整）
│       ├── ai_case_gen.yaml
│       ├── ui_case_gen.yaml
│       ├── api_case_gen.yaml
│       └── code_analyze.yaml
├── tools/
│   ├── database.py             # ORM 模型 + 自动迁移 + 历史数据归属
│   ├── llm_client.py           # 统一 LLM 调用层（兼容 Anthropic / OpenAI 格式）
│   ├── pdf_exporter.py         # HTML → PDF（Playwright headless A4）
│   ├── alerter.py              # 钉钉/企微/飞书告警推送
│   ├── config.py               # 环境变量（pydantic-settings）
│   ├── browser.py              # Playwright 浏览器封装
│   ├── document_parser.py      # 文档解析（PDF/Word/Excel/PPT/HTML）
│   └── logger.py               # 日志（按日滚动 + zip + 定时清理 + 告警 sink）
├── ui/src/                     # Vue 3 前端
└── tests/                      # 单元测试
```

***

## 截图

<table>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/0.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/1.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/2.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/3.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/4.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/5.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/6.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/7.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/8.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/8.1.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/9.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/9.1.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/9.2.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/9.3.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/10.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/11.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/12.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/13.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/14.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/15.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/16.png"/></td>
        <td></td>
    </tr>
</table>

***

## 许可证

MIT License — 详见 [LICENSE](LICENSE)
