# AI 测试工具平台

基于 **AI 大模型 + LangGraph + Playwright** 的智能化零代码全场景自动化测试平台，覆盖 **WebUI 自动化 / 接口自动化 / 渗透测试** 三引擎，支持 Claude / DeepSeek / GPT / Gemini / Ollama 等任意模型一键切换。

📐 [设计思路与技术决策 →](./DESIGN.md)

<div align="center">

<img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/AI%E6%B5%8B%E8%AF%95%E5%B7%A5%E5%85%B7%E5%B9%B3%E5%8F%B0.gif" width="90%" alt="AI 测试平台演示"/>

> ⏳ 演示包含 AI 生成测试用例的完整过程，AI 推理需要一定时间，请耐心观看。

</div>

---

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
| `AI_API_KEY` | 大模型 API Key（也可部署后在平台「大模型配置」页填写） | — |
| `AI_API_URL` | 大模型接口地址，默认 DeepSeek，按需替换 | — |
| `AI_MODEL` | 模型名称，与 `AI_API_URL` 对应 | — |

```bash
docker compose up -d
```

访问 `http://服务器IP:4000`，默认账号 `admin / admin123`，**登录后立即修改密码**。

```bash
# 更新
git pull && docker compose up -d --build

# 查看日志
docker compose logs -f app

# 停止
docker compose down
```

> **数据备份**：数据库和文件存储在 Docker 命名卷 `pg_data` / `app_data` 中。迁移时一并复制即可。
>
> ```bash
> docker volume inspect ai_test_agent_pg_data   # 查看实际路径
> ```

> **升级说明**：新版本在服务启动时自动执行数据库迁移，直接 `--build` 重启即可，无需手动操作。

#### 可选：ARQ 任务队列（多 Worker）

默认使用进程内 `BackgroundTasks`，任务重启后丢失。需要持久化任务队列时启用：

```bash
# .env.docker 中取消注释并填写：
REDIS_URL=redis://redis:6379/0

# 启动时加 --profile worker
docker compose --profile worker up -d

# 可独立横向扩容
docker compose --profile worker up -d --scale worker=3
```

#### 可选：Nginx 反向代理

默认不启动，需要域名 / HTTPS 时使用：

```bash
# 编辑 nginx.conf，填写域名，按需取消 SSL 注释
docker compose --profile nginx up -d
```

---

### 本地启动

**环境要求：** Python 3.11+，Node 18+

```bash
# 1. 克隆项目
git clone https://github.com/ywq2019/ai_test_agent.git
cd ai_test_agent

# 2. 配置文件（git clone 不包含 .env）
cp .env.docker .env
# 编辑 .env，至少填写 AI_API_KEY 和 AI_API_URL
# 本地启动使用 SQLite，DATABASE_URL 保持默认即可

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 安装 Playwright 浏览器
playwright install chromium
# Linux 还需要（Mac/Windows 跳过）：
# sudo playwright install-deps chromium

# 5. 构建前端
cd ui && npm install && npm run build && cd ..

# 6. 启动
python main.py   # 访问 http://localhost:4000
```

**开发模式（前端热更新）：**

```bash
python main.py          # 终端1：后端 4000
cd ui && npm run dev    # 终端2：前端 8090（代理到后端）
```

> **本地 vs Docker 数据库**
>
> | | 本地启动 | Docker 部署 |
> | --- | --- | --- |
> | 数据库 | SQLite（项目根目录 `uitest_agent.db`） | PostgreSQL（Docker 卷 `pg_data`） |
> | RAG 向量检索 | 降级为关键词匹配（不支持 pgvector） | pgvector 完整支持 |
> | 数据位置 | 项目根目录下 `.db` 文件 | Docker 命名卷 |
> | 数据互通 | ❌ 两边数据不互通 | — |
>
> 建议生产环境直接使用 Docker 部署，避免后续迁移麻烦。

---

## 核心功能

### AI 用例生成（文档驱动）

上传需求文档，AI 按功能模块并行生成覆盖 6 种测试方法的高质量用例。

| 功能 | 说明 |
| --- | --- |
| **异步后台生成** | 提交后立即返回，完成后 WebSocket 推送，进度实时持久化（断线重连可恢复） |
| 分段并行生成 | 提取模块后并发调用 AI（Semaphore=4），每次输出可控，不超时 |
| 6 种测试方法 | 等价类、边界值、判定表、场景法、错误推测、状态转换 |
| **导出格式** | Markdown / XMind / **Excel**（含优先级色标、测试结果下拉、条件格式） |
| **需求变更增量更新** | AI Diff 分析 → 仅对变更模块做用例级合并，unchanged 模块直接保留 |
| **需求追踪矩阵** | 提取结构化需求条目，建立用例-需求双向映射，生成覆盖率矩阵；一键分析缺口并生成补充用例 |
| **覆盖度优化** | 逐模块分析覆盖盲区（并发 4，单轮 LLM，控制在 120s 内完成） |
| **RAG 知识库** | 文档分段入库（pgvector 向量检索，不支持时降级关键词匹配），生成时检索相关段落 |
| 超大文档支持 | BeautifulSoup 深度清洗 HTML；分批并行提取模块（20000字/批） |
| 截断 JSON 自动修复 | LLM 输出被截断时自动补齐，避免丢失已生成内容 |

### WebUI 自动化

Playwright 驱动浏览器，以「AI 场景规划 → 录制 → 健壮化 → 可视化编辑 → 执行」为主线，降低脚本维护成本。

| 功能 | 说明 |
| --- | --- |
| **AI 场景规划** | 抓取页面元素 + 注入已有用例 + 需求文档，从 5 个落地维度（核心流程/表单验证/增删改/筛选/异常反馈）自动规划录制场景，结果持久化到任务；支持追加场景、重新规划 |
| **场景 → 录制联动** | 场景规划结果展示在抽屉里，点击「开始录制」一键启动有头浏览器；录制完成自动标记场景为已录制、重新打开抽屉继续下一个 |
| **录制健壮化** | 保存时自动运行 `step_hardener`：推导多候选 selector（A/B/C/D 稳定性评级）、关键操作后自动插入 wait + assert（optional），显著降低执行失败率 |
| **可视化步骤编辑器** | 用例编辑弹窗双 Tab：基本信息 + 步骤编辑器；步骤表格每行显示健壮度评级，D 级标红；点击 selector 胶囊展开所有备选，一键切换；支持行内编辑 action/selector/value/expected |
| **来源标签** | 用例列表显示来源（🎬录制 / 🤖AI / ✏️手动），AI 生成且失败的用例旁出现「重录」快捷按钮 |
| **场景覆盖视图** | 用例管理新增「场景覆盖」Tab：按规划场景分组，显示覆盖进度，未覆盖场景一键跳去录制 |
| **元素别名库** | 常用元素 selector 命名为别名，步骤编辑器输入 `@` 触发补全，selector 变更只改别名库一处即全部生效 |
| **录制异步化** | 启动录制立即返回，Chrome 后台启动，就绪后 WebSocket 推送 `recording_ready`，前端自动切换状态 |
| **多 Selector 回退** | 执行时按 selector 候选列表逐一尝试，找到可用元素即执行，应对动态 id / 框架重构 |
| **多浏览器并行** | 同一批用例同时在 Chromium / Firefox / WebKit 执行，各出一份报告 |
| **并发执行保护** | 同一任务同时只允许一个执行实例（409 保护）；同一任务只允许一个录制 session |
| 浏览器 Context 池 | `Semaphore(6)` 控制最大并发，每条用例独立 Context（隔离 cookie / session） |
| 执行控制 | 支持暂停/继续/停止，步骤级失败截图，生成 HTML / PDF 报告 |
| **pytest 导出** | 将 ActionStep 列表导出为标准 Python Playwright 测试脚本（zip 包） |
| **页面元素抓取** | 场景规划前可一键抓取页面元素（`domcontentloaded` 策略，5 屏滚动，约 15s 完成） |
| **分页加载** | 用例列表默认每页 20 条，支持 20/50/100 切换，筛选/搜索自动重置到第 1 页 |
| **变量替换** | value / url / expected 等字段支持 `{{变量名}}` 语法，从任务环境变量表替换，支持多环境参数化 |

> 📖 步骤编辑详细说明（action 类型、selector 写法、expected 断言、稳定性评级等）请参阅 [WebUI 步骤编辑操作手册](./docs/webui-step-editor-guide.md)

### 接口自动化

从「项目 → 用例 → 执行 → 报告」全链路打通，支持 Swagger / 代码分析 / 自然语言三种用例来源，内置参数化引擎、前置依赖、CSV 数据驱动、压力测试和 PDF 报告，适用于日常接口回归与 CI/CD 集成。

#### 项目与鉴权管理

| 功能 | 说明 |
| --- | --- |
| 多项目管理 | 每个项目独立配置 Base URL、代理（HTTP/SOCKS5）、Hosts 映射 |
| 多种鉴权方式 | Bearer Token / Basic Auth / API Key，统一在项目级配置，执行时自动注入 |
| **多环境支持** | 每个项目可配置多套环境（测试/预发布/生产），执行时下拉切换 Base URL |

#### AI 用例生成

| 输入源 | 说明 |
| --- | --- |
| Swagger / OpenAPI | 解析接口定义，自动生成正常 / 异常 / 边界用例 |
| 自然语言描述 | 描述接口行为，AI 推理补全请求体、断言与边界 |
| 代码（Python/Java/Go/Node.js/PHP） | 静态分析业务代码，提取接口调用并生成用例 |
| **代码可行性分析** | 识别 `missing`（缺失接口）/ `mismatch`（字段不符）/ `extra`（多余字段）/ `risk`（潜在风险）四类偏差，自动补充差异验证用例 |
| **Postman/HAR 导入** | 解析 Postman Collection 或 HAR 文件，直接导入为用例 |

#### 参数化与前置依赖

| 功能 | 说明 |
| --- | --- |
| 全局变量池 | `{{gvar:name}}` 语法引用跨用例共享变量，支持提取表达式写回 |
| 内置函数 | `{{uuid()}}`、`{{timestamp()}}` 等动态值生成，开箱即用 |
| 自定义脚本函数 | 支持 Python 脚本扩展参数化逻辑，满足复杂签名/加密场景 |
| 前置依赖 | 配置登录前置用例，自动提取 Token；鉴权失败自动重试，无需手动维护 Cookie |
| **CSV 数据驱动** | 上传 CSV 文件，每行数据作为独立参数组执行一次用例，支持多行批量验证 |

#### 执行、压测与报告

| 功能 | 说明 |
| --- | --- |
| 单次执行 | 选择全部或指定用例，实时 WebSocket 推送每条用例结果（频道按 project_id 隔离，多用户互不干扰） |
| 压力测试 | 配置并发数 / 持续时长 / 爬坡策略，实时推送 TPS / P95 / P99 指标，ECharts 实时图表 |
| **报告 PDF 导出** | 含用例明细表格 + AI 智能分析段落，一键导出归档 |

### Mock 服务

轻量 HTTP Mock，无需依赖真实后端即可联调前端。

| 功能 | 说明 |
| --- | --- |
| 规则匹配 | 按 method + path + 请求参数精准匹配，支持通配符路径 |
| 动态响应 | 配置响应状态码、Headers、Body（支持 JSON / 纯文本） |
| 延迟模拟 | 配置响应延迟，模拟慢接口 |
| 请求记录 | 每次命中记录请求详情，方便排查联调问题 |

### 测试计划

跨项目接口用例编排，共享变量上下文（登录 → 下单 → 查询）。

| 功能 | 说明 |
| --- | --- |
| 步骤编排 | 从任意项目拖入用例，自由排序、启用/禁用 |
| 共享变量 | 所有步骤共享 `var_store`，前步提取后步直接引用 |
| **定时执行** | Cron 表达式定时触发，APScheduler 管理，服务重启后自动恢复 |
| **CI/CD 集成** | Webhook token 触发，支持 Jenkins / GitHub Actions，可选执行完成回调 |
| **报告 PDF 导出** | 含步骤明细 + AI 分析 |

### 接口渗透测试

基于接口自动化项目中已有的用例，对目标 API 发起安全扫描，自动发现 OWASP API Top 10 及常见漏洞，每条漏洞由 AI 生成定制修复建议，并支持 PDF 报告导出。

> ⚠️ **声明**：本功能仅面向已授权的安全测试场景（内部测试、渗透测试授权委托书、CTF）。请勿对未授权目标使用。

12 个扫描模块覆盖：未授权访问、越权（IDOR）、敏感信息泄露、SQL 注入、JWT 安全缺陷、速率限制缺失、批量赋值、CORS 配置错误、HTTP 动词篡改、SSRF、文件上传漏洞、文件下载路径穿越。

### 工作空间

多租户隔离的顶层单元，一个工作空间对应一套独立的测试数据。

| 功能 | 说明 |
| --- | --- |
| 多空间管理 | 每个用户可创建多个工作空间，数据互不干扰 |
| 成员协作 | 邀请成员加入，role 分 owner（管理成员）/ member（读写数据） |
| 跨模块隔离 | AI 用例、WebUI 任务、接口项目、测试计划均按工作空间隔离 |
| **WS 推送隔离** | WebSocket 广播按工作空间路由，不同空间的执行进度互不干扰 |
| admin 穿透 | 系统管理员可跨空间查看所有数据 |

---

## 稳定性与安全

### 多用户并发

| 机制 | 默认值 | 配置项 |
| --- | --- | --- |
| 全局 LLM Semaphore | 6 并发 | `LLM_CONCURRENCY` |
| Semaphore 等待超时 | 60s | `LLM_SEM_TIMEOUT` |
| 后台生成任务上限 | 3 个 | `MAX_ACTIVE_GENERATE` |
| 浏览器 Context 并发上限 | 6 个 | `tools/browser.py: MAX_CONCURRENT` |
| 同一任务重复执行保护 | 409 响应 | 进程内 `_running_tasks` set |
| 同一任务重复录制保护 | 409 响应 | 进程内 `_active_recording_tasks` set |
| 接口 WS 频道隔离 | 按 project_id 路由 | `api_gen_{id}` / `api_exec_{id}` / `api_load_{id}` |
| 接口频率限制 | 生成 5次/分钟，优化/分析 3次/分钟 | slowapi，按真实 IP |
| 反向代理 IP 识别 | `X-Real-IP` → `X-Forwarded-For` → TCP | Nginx 反代时自动识别 |

### 数据隔离

**工作空间级**：AI 用例、WebUI 任务、接口项目、测试计划均挂在工作空间下，成员只能访问所在空间的数据。

**用户级**：未挂载工作空间的数据，普通用户只能看到自己创建的记录；admin 可查看全部。服务启动时自动将历史 NULL 数据归属到默认管理员账号，升级无感知。

**执行隔离**：每条用例独立 Playwright Context，cookie / session / storage 完全隔离，多用户并发执行互不影响。

### 自愈与告警

| 机制 | 说明 |
| --- | --- |
| 重启状态恢复 | 服务重启时自动将卡住的生成任务重置为 failed，推送 WebSocket 通知 |
| 文件自动清理 | 删除记录时清理整条版本链文件；每天 00:05 扫描孤儿文件 |
| 日志定时清理 | 每天 00:05 清理过期日志（默认保留 7 天），`LOG_RETENTION_DAYS` 可调 |
| **定时任务调度** | APScheduler 管理 Cron 定时计划，服务重启自动恢复，不丢任务 |
| Webhook 告警 | ERROR 级日志自动推钉钉/企微/飞书，5 分钟防刷屏；`ALERT_WEBHOOK_URL` 留空则静默 |

### CI/CD 集成

```bash
# 1. 生成 webhook token（需登录）
curl -X PUT "http://your-host:4000/api/v1/test-plans/1/webhook-token" \
  -H "Authorization: Bearer <JWT>"
# → {"webhook_token": "xxx", "trigger_url": "..."}

# 2. 在 Jenkins / GitHub Actions 里触发
curl -f -X POST "http://your-host:4000/api/v1/test-plans/1/trigger?token=xxx"

# 3. 可选：执行完成后回调
curl -f -X POST "...?token=xxx&callback_url=https://ci.example.com/hook"
```

---

## AI 集成

所有 AI 功能统一读取「大模型配置」页，**自动判断 Anthropic / OpenAI 格式**，支持一键切换：

| 提供商 | 模型示例 | API URL |
| --- | --- | --- |
| Claude | claude-opus-5 | https://api.anthropic.com |
| DeepSeek | deepseek-v4-flash | https://api.deepseek.com |
| OpenAI | gpt-4o | https://api.openai.com |
| Gemini | gemini-2.0-flash | https://generativelanguage.googleapis.com |
| Ollama（本地） | llama3 | http://localhost:11434 |
| 任意 OpenAI 兼容代理 | — | 填入代理地址即可 |

Prompt 统一管理在 `skills/prompts/*.yaml`，**无需重启**即可生效（懒加载 + LRU 缓存，修改 YAML 后下次调用自动读新版本）。

---

## 技术栈

| 层 | 技术 | 说明 |
| --- | --- | --- |
| 后端 | Python 3.11+ / FastAPI 0.138 | 全异步 ASGI，Uvicorn 单进程 |
| Agent | LangGraph 1.2 / LangChain 1.3 | LangGraph 编排 Agent 工作流，LangChain 管理工具注册 |
| ORM | SQLAlchemy 2.0 | SQLite（本机）/ PostgreSQL（Docker）双兼容，自动迁移 |
| 浏览器 | Playwright 1.39 | UI 自动化 + 录制回放 + PDF 报告导出 |
| 任务队列 | ARQ + Redis（可选） | 多 Worker 持久化任务队列，不配置时降级为 BackgroundTasks |
| 定时调度 | APScheduler 3.11 | 测试计划 Cron 定时执行，重启自动恢复 |
| 限流 | slowapi | 按真实 IP，支持反向代理 |
| 向量库 | pgvector | RAG 检索，不支持时降级关键词匹配 |
| 鉴权 | python-jose + bcrypt | JWT（7 天有效期）+ 密码哈希 |
| 前端 | Vue 3.4 + Vite 5 + Element Plus 2.14 | 含 ECharts 压测图表、marked Markdown 渲染 |
| 代理 | Nginx（可选） | 反向代理 + HTTPS + WebSocket 升级 |

---

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
| AI 用例 | GET | `/api/v1/ai-cases/{id}/export-excel` | 导出 Excel |
| AI 用例 | POST | `/api/v1/ai-cases/{id}/incremental-update` | 需求变更增量更新 |
| AI 用例 | GET | `/api/v1/ai-cases/{id}/traceability` | 需求追踪矩阵 |
| WebUI | POST | `/api/v1/parse/page` | 抓取页面元素（供场景规划使用） |
| WebUI | POST | `/api/v1/cases/plan-scenes/{task_id}` | AI 场景规划（5 维度，持久化到任务；`append=true` 追加） |
| WebUI | GET | `/api/v1/cases/scene-plan/{task_id}` | 读取持久化场景规划 |
| WebUI | PATCH | `/api/v1/cases/scene-plan/{task_id}/mark-recorded` | 标记场景已录制 |
| WebUI | GET | `/api/v1/cases/{case_id}/steps` | 获取用例 steps_json（步骤编辑器加载）|
| WebUI | POST | `/api/v1/execute` | 执行测试（单浏览器） |
| WebUI | POST | `/api/v1/execute/multi-browser` | 多浏览器并行执行 |
| WebUI | POST | `/api/v1/recording/start` | 启动录制（异步，立即返回 session_id） |
| WebUI | POST | `/api/v1/recording/stop` | 停止录制，返回 ActionStep 列表 |
| WebUI | POST | `/api/v1/recording/save` | 将录制步骤保存为用例（含 AI 健壮化） |
| WebUI | GET | `/api/v1/reports/{id}/pdf` | 导出 PDF |
| WebUI | POST | `/api/v1/tasks/{id}/export/pytest` | 导出 pytest 脚本（zip） |
| 接口测试 | POST | `/api/v1/api-test/projects/{id}/execute` | 执行用例 |
| 接口测试 | POST | `/api/v1/api-test/projects/{id}/cases/import` | 导入用例（Postman/HAR） |
| 接口测试 | POST | `/api/v1/api-test/projects/{id}/cases/{cid}/data-driven` | CSV 数据驱动执行 |
| 接口测试 | GET | `/api/v1/api-test/reports/{id}/pdf` | 导出 PDF |
| Mock | ANY | `/mock/{path}` | Mock 请求匹配（无需 JWT） |
| 全局变量 | GET/POST/PUT/DELETE | `/api/v1/global-vars` | 全局变量池管理 |
| 测试计划 | PUT | `/api/v1/test-plans/{id}/webhook-token` | 生成 CI/CD 触发 token |
| 测试计划 | POST | `/api/v1/test-plans/{id}/trigger?token=xxx` | CI/CD 触发（无需 JWT） |
| 测试计划 | GET | `/api/v1/test-plans/reports/{id}/pdf` | 导出 PDF |
| 渗透测试 | GET | `/api/v1/pentest/tasks` | 任务列表（按工作空间） |
| 渗透测试 | POST | `/api/v1/pentest/tasks/{id}/run` | 触发执行 |
| 渗透测试 | POST | `/api/v1/pentest/tasks/{id}/cancel` | 取消运行中的任务 |
| 渗透测试 | GET | `/api/v1/pentest/tasks/{id}/pdf` | 导出 PDF 报告 |
| 健康检查 | GET | `/api/v1/health` | 服务健康检查（无需鉴权） |

**WebSocket 频道**（连接地址：`ws://host:4000/ws?client_id=<频道>`）

| client_id | 说明 |
| --- | --- |
| `ai_gen` | AI 用例生成/优化/增量更新进度 |
| `cases_gen` | WebUI 用例生成进度 |
| `rec_{task_id}` | 录制步骤实时预览 + `recording_ready` / `recording_failed` 事件 |
| `api_gen_{project_id}` | 接口用例 AI 生成进度（按项目隔离） |
| `api_exec_{project_id}` | 接口用例执行进度（按项目隔离） |
| `api_load_{project_id}` | 压测实时指标 TPS / P95 / P99（按项目隔离） |
| `plan_{id}` | 测试计划执行进度 |
| `pentest` | 渗透扫描实时进度 |

---

## 项目结构

```
ai_test_agent/
├── main.py                      # 入口：JWT 中间件、启动恢复、孤儿文件清理、调度器初始化
├── Dockerfile                   # 多阶段构建：前端 Node → 生产 Playwright Python
├── docker-compose.yml           # 四服务：db / redis / app / worker / nginx（后三个按 profile 启动）
├── nginx.conf                   # Nginx 反向代理（可选，--profile nginx 启动）
├── .env.docker                  # Docker 环境变量模板（生产配置，不提交 .env）
├── requirements.txt
├── api/
│   ├── auth.py                  # JWT + owner_filter + workspace 权限
│   ├── limiter.py               # slowapi 限流（支持反向代理 IP 识别）
│   ├── schemas.py               # Pydantic 请求/响应模型
│   ├── scheduler.py             # APScheduler 定时任务管理（测试计划 Cron）
│   ├── websocket.py             # WebSocket 连接处理
│   ├── websocket_manager.py     # 多频道广播管理器（心跳 + 工作空间隔离）
│   └── routes/
│       ├── __init__.py          # 路由聚合
│       ├── auth.py              # 鉴权、用户管理、健康检查
│       ├── workspaces.py        # 工作空间 CRUD + 成员管理
│       ├── webui.py             # WebUI 自动化（场景规划/录制/执行/报告/步骤健壮化）
│       ├── ai_cases.py          # AI 文档驱动用例（生成/增量更新/需求追踪/Excel导出）
│       ├── api_test.py          # 接口自动化（执行/压测/CSV数据驱动/WS隔离）
│       ├── global_vars.py       # 全局变量池
│       ├── test_plans.py        # 测试计划 + Cron 定时 + CI/CD webhook
│       ├── mock.py              # Mock 服务规则管理
│       └── pentest.py           # 渗透测试模块
├── agent/
│   ├── core.py                  # UITestAgent：任务编排，AgentState 按 task_id 隔离
│   └── langgraph_agent.py       # LangGraph Agent 初始化与编排
├── skills/
│   ├── action_runner.py         # ActionRunner：ActionStep 确定性执行引擎（AI selector 自修复）
│   ├── recorder.py              # 有头浏览器录制器（JS 事件注入 + 轮询 + 步骤补全）
│   ├── step_hardener.py         # 录制步骤健壮化（selector 评级/多候选/断言插入）
│   ├── test_executor.py         # TestExecutor：批量执行调度，task_id 状态隔离
│   ├── parallel_runner.py       # 多浏览器并行执行调度
│   ├── ai_case_generator.py     # 文档驱动用例生成（RAG + 并发控制 + JSON 修复 + 覆盖度优化）
│   ├── api_case_generator.py    # 接口用例 AI 生成（Swagger/代码/描述）
│   ├── api_executor.py          # 接口用例执行引擎
│   ├── api_load_tester.py       # 压力测试引擎
│   ├── csv_driver.py            # CSV 数据驱动解析
│   ├── import_parser.py         # Postman / HAR 导入解析
│   ├── param_resolver.py        # 参数化解析（全局变量池 / 内置函数 / 自定义脚本）
│   ├── pentest_engine.py        # 渗透测试扫描引擎（12 模块，AI 修复建议）
│   ├── rag.py                   # RAG 向量检索（pgvector / 关键词降级）
│   ├── prompt_loader.py         # YAML Prompt 加载器（懒加载 + LRU 缓存）
│   └── prompts/                 # LLM Prompt 配置（YAML，修改无需重启）
│       ├── ai_case_gen.yaml
│       ├── ui_case_gen.yaml     # 含 plan_scenes（场景规划5维度）
│       ├── api_case_gen.yaml
│       └── code_analyze.yaml
├── tools/
│   ├── action_schema.py         # ActionStep 数据结构定义（22 种 action 类型）
│   ├── browser.py               # BrowserPool（Semaphore=6，domcontentloaded策略）
│   ├── config.py                # 环境变量（pydantic-settings）
│   ├── database.py              # ORM 模型 + 自动迁移（含 source/scene_plan 新字段）
│   ├── document_parser.py       # 文档解析（PDF/Word/Excel/PPT/HTML）
│   ├── llm_client.py            # 统一 LLM 调用层（兼容 Anthropic / OpenAI 格式）
│   ├── pdf_exporter.py          # HTML → PDF（Playwright headless A4）
│   ├── alerter.py               # 钉钉/企微/飞书告警推送
│   └── logger.py                # 日志（按日滚动 + zip + 定时清理 + 告警 sink）
├── worker/
│   └── arq_worker.py            # ARQ Worker 配置（多 Worker 任务队列）
├── ui/src/                      # Vue 3 前端（Element Plus + ECharts + Pinia）
│   ├── views/
│   │   ├── AiCases.vue          # AI 用例生成（生成/优化/增量/追踪矩阵/Excel导出）
│   │   ├── Execution.vue        # WebUI 执行（AI场景规划/录制/健壮化/执行/多浏览器）
│   │   ├── Cases.vue            # WebUI 用例管理（来源标签/可视化步骤编辑器/备选Selector/场景覆盖/分页）
│   │   ├── Tasks.vue            # 任务管理
│   │   ├── Reports.vue          # 执行报告
│   │   ├── ApiTest.vue          # 接口测试（含CSV数据驱动/Postman导入）
│   │   ├── TestPlan.vue         # 测试计划（含 Cron 定时）
│   │   ├── Mock.vue             # Mock 服务
│   │   ├── Pentest.vue          # 渗透测试
│   │   ├── Home.vue             # 首页看板
│   │   ├── LLM.vue              # 大模型配置
│   │   └── Skills.vue           # 技能管理
│   └── api/index.js             # Axios 封装 + 401 拦截器
├── tests/                       # 单元测试
└── docs/
    └── webui-step-editor-guide.md  # WebUI 步骤编辑操作手册（action/selector/expected 详解）
```

---

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
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/9.png"/></td>
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
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/17.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/18.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/19.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/20.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/21.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/22.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/23.png"/></td>
    </tr>
    <tr>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/24.png"/></td>
        <td><img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/25.png"/></td>
    </tr>
</table>

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE)
