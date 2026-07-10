# AI 测试工具平台

基于 **AI 大模型 + LangGraph + Playwright** 的智能化零代码全场景自动化测试平台，覆盖 UI 自动化与接口自动化双引擎，支持 Claude / DeepSeek / GPT / Gemini 等任意模型一键切换。

📐 [设计思路与技术决策 →](./DESIGN.md)

<div align="center">

<img src="https://raw.githubusercontent.com/ywq2019/ai_test_agent/master/image/AI%E6%B5%8B%E8%AF%95%E5%B7%A5%E5%85%B7%E5%B9%B3%E5%8F%B0_1904w.gif" width="90%" alt="AI 测试平台演示"/>

> ⏳ 演示包含 AI 生成测试用例的完整过程，AI 推理需要一定时间，请耐心观看。

</div>

---

## 快速部署

### 方式一：Docker 一键部署（推荐，适合服务器）

服务器已安装 Docker 和 Docker Compose 即可：

```bash
git clone https://github.com/ywq2019/ai_test_agent.git && cd ai_test_agent && docker compose up -d
```

启动后访问 `http://服务器IP:4000`，进入**大模型配置**页填写 API Key。

| 服务 | 说明 |
| --- | --- |
| `app` | FastAPI 后端 + 前端静态文件，监听 4000 端口 |
| `db` | PostgreSQL 15，自动建表，数据持久化到 Volume |

```bash
git pull && docker compose up -d --build  # 更新
docker compose logs -f                     # 查看日志
docker compose down                        # 停止
```

### 方式二：本地启动

**环境要求**：Python 3.11+、Node.js 18+

**生产模式**（单端口，前端打包后由后端托管）：

```bash
# 1. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 2. 构建前端（编译产物由后端静态托管）
cd ui && npm install && npm run build && cd ..

# 3. 启动
python main.py
```

访问 `http://localhost:4000`，前端由后端统一托管，只需启动一个进程。

**开发模式**（双端口，支持热更新，适合开发调试）：

```bash
# 终端1：后端（API 服务，端口 4000）
python main.py

# 终端2：前端 Vite 开发服务器（端口 8090，自动代理 /api 请求到后端 4000）
cd ui && npm run dev
```

访问 `http://localhost:8090`，前端代码修改实时生效。

> **两个端口说明**：生产模式下 FastAPI 直接托管 `ui/dist/` 静态文件，访问 4000 即可；开发模式下 Vite 在 8090 启动独立服务并将 `/api`、`/ws` 等请求代理转发到后端 4000。

### 局域网共享（Windows 团队使用）

本机启动后，团队成员可通过内网 IP 直接访问，无需额外配置：

```bash
# 查看本机内网 IP（找以太网或 WLAN 的 IPv4 地址）
ipconfig
```

开放防火墙入站端口：

```powershell
New-NetFirewallRule -DisplayName "AI测试平台" -Direction Inbound -Protocol TCP -LocalPort 4000 -Action Allow
```

团队成员访问 `http://<本机IP>:4000` 即可使用，例如 `http://192.168.1.100:4000`。

### 登录账号

平台内置 JWT 鉴权，首次启动自动创建默认账号：

| 用户名 | 密码 | 权限 |
| --- | --- | --- |
| `admin` | `admin123` | 管理员，可管理用户 |

> 登录后点击顶栏右上角「用户管理」可新建账号，普通用户只能登录和修改自己的密码。

---

## 核心功能

### AI 用例生成（文档驱动）

上传需求文档，AI 按功能模块并行生成覆盖 6 种测试方法的高质量用例，导出 Markdown / XMind。

| 功能 | 说明 |
| --- | --- |
| 分段并行生成 | 提取模块后并发调用 AI（Semaphore=2），每次输出可控，不超时 |
| 6 种测试方法 | 等价类、边界值、判定表、场景法、错误推测、状态转换，每条用例标注方法 |
| 多维度覆盖 | 功能用例 + 性能用例 + 兼容性用例同步生成 |
| 覆盖度优化 | 分析已有用例盲区，自动追加补充用例 |
| **需求变更增量更新** | 上传新版文档 → AI Diff 分析 → 仅对变更模块做用例级保守合并，unchanged 模块直接保留，通用测试模块（性能/兼容）永不废弃 |
| 废弃用例管理 | 废弃用例追加模块末尾（删除线展示），默认隐藏，可开关查看 |

### WebUI 自动化

Playwright 抓取页面元素，AI 生成含具体 selector 的可执行用例，直接运行自动化测试。

| 功能 | 说明 |
| --- | --- |
| 页面元素解析 | 自动抓取可交互元素，识别移动端 H5，等待 networkidle 确保动态渲染完成 |
| AI 生成用例 | 结合页面元素 + 需求文档分段生成，含 selector 和测试数据，支持随时取消 |
| 执行控制 | 支持暂停/继续/停止，自动截图，生成含图表的 HTML 报告 |
| **需求变更增量更新** | 保守合并策略：默认保留所有旧用例，只废弃功能已彻底删除的用例 |

### 接口自动化

#### 接口测试

| 功能 | 说明 |
| --- | --- |
| 多项目管理 | Base URL + 鉴权方式（Bearer/Basic/API Key）+ 代理 + Hosts 映射 |
| AI 生成用例 | 三种输入：Swagger/OpenAPI、自然语言描述、**直接粘贴接口实现代码**（Python/Java/Go/Node.js/PHP） |
| **代码可行性分析** | 对比需求文档与代码实现，识别 `missing`/`mismatch`/`extra`/`risk` 四类偏差，自动生成差异验证用例 |
| 参数化 | 全局变量池 `{{gvar:name}}`、内置函数 `{{uuid()}}`、自定义 Python 脚本函数 |
| 前置依赖 | 配置登录前置用例，自动提取 Token，鉴权失败自动重试 |
| 压力测试 | 配置并发/时长/爬坡，实时推送 TPS / P95 / P99 |
| AI 报告分析 | 执行完成后调用 LLM 分析失败原因，给出修复建议 |

#### 测试计划

跨项目接口用例编排，共享变量上下文，实现端到端链路测试（如：登录 → 下单 → 查询）。

| 功能 | 说明 |
| --- | --- |
| 步骤编排 | 从任意项目拖入用例，自由排序、启用/禁用单步 |
| 共享变量 | 所有步骤共享 `var_store`，前步提取的变量后步直接引用 |
| 计划级网络配置 | 代理/Hosts 优先级高于项目级，可按计划统一切换测试环境 |
| 执行报告 | WebSocket 实时推送进度，卡片式报告展示通过率/断言详情/AI 分析 |

---

## 技术栈

### 后端

| 技术 | 说明 |
| --- | --- |
| Python 3.11+ / FastAPI 0.138 | 全异步 ASGI 框架，Uvicorn 服务器 |
| SQLAlchemy 2.0 | 异步 ORM，SQLite（本机）/ PostgreSQL（Docker）双数据库兼容 |
| httpx | 异步 HTTP 客户端，支持代理 / 自定义 Transport（Hosts 映射） |
| Playwright 1.39 | 浏览器自动化，支持 networkidle 等待策略 |
| LangChain + LangGraph | LLM 对话代理工作流（可选） |
| python-jose + bcrypt | JWT 鉴权 + 密码哈希 |
| PyYAML | Prompt 配置文件读取 |

### 前端

| 技术 | 说明 |
| --- | --- |
| Vue 3.4 + Vite 5 | 前端框架 + 构建工具 |
| Element Plus 2.14 | UI 组件库 |
| Pinia / Vue Router | 状态管理 / 路由（含登录守卫） |
| ECharts 5.5 | 压测实时图表 |
| Axios 1.6 | HTTP 客户端，请求拦截器自动附加 JWT Token |

---

## AI 集成

所有 AI 功能统一读取「大模型配置」页的设置，**自动判断 Anthropic / OpenAI 格式**，支持一键切换：

| 提供商 | 模型示例 | API URL |
| --- | --- | --- |
| Claude（Anthropic） | claude-sonnet-4-5 | https://api.anthropic.com |
| DeepSeek | deepseek-v4-flash | https://api.deepseek.com |
| OpenAI | gpt-4o | https://api.openai.com |
| Ollama（本地） | llama3 | http://localhost:11434 |
| 任意 OpenAI 兼容代理 | — | 填入代理地址即可 |

所有 Prompt 统一管理在 `skills/prompts/*.yaml`，无需改代码即可调整 AI 生成效果。

---

## 项目结构

```
ai_test_agent/
├── main.py                 # 应用入口（含 JWT 鉴权中间件、默认账号初始化）
├── Dockerfile / docker-compose.yml
├── api/
│   ├── auth.py             # JWT 工具 + get_current_user 依赖注入
│   ├── routes.py           # 全部 REST 端点（含用户管理、增量更新、代码分析）
│   ├── websocket.py        # WebSocket 端点
│   └── websocket_manager.py
├── skills/
│   ├── ai_case_generator.py    # AI 文档驱动用例生成（分段 + 增量更新）
│   ├── case_generator.py       # UI 用例生成（分段 + 增量更新）
│   ├── api_case_generator.py   # 接口用例生成 + 代码分析
│   ├── api_executor.py         # 接口用例执行（断言 + 变量提取 + 前置依赖）
│   ├── api_load_tester.py      # 压力测试引擎
│   ├── param_resolver.py       # 参数解析（变量 / 函数 / 脚本）
│   ├── prompt_loader.py        # Prompt YAML 加载器
│   └── prompts/                # LLM Prompt 配置（YAML，无需改代码即可调整）
│       ├── ai_case_gen.yaml
│       ├── api_case_gen.yaml
│       ├── code_analyze.yaml
│       └── ui_case_gen.yaml
├── tools/
│   ├── database.py         # SQLAlchemy 模型（兼容 SQLite / PostgreSQL）
│   ├── config.py           # 环境变量（含 JWT 配置）
│   └── browser.py          # Playwright 封装（networkidle + 移动端 UA）
├── ui/src/
│   ├── api/index.js        # Axios 封装（JWT 拦截器 + 401 跳登录）
│   ├── stores/auth.js      # Pinia Auth Store（token 持久化）
│   ├── views/Login.vue     # 登录页
│   └── views/ApiTest/      # 接口测试组件（拆分后）
│       └── ScriptDialog.vue
└── tests/                  # 单元测试
    ├── test_param_resolver.py   # 27 条
    ├── test_api_executor.py     # 27 条
    └── test_incremental.py      # 12 条
```

---

## 接口说明

完整文档：`http://localhost:4000/docs`

**认证**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/auth/login` | 登录，返回 JWT Token |
| GET | `/api/v1/auth/users` | 用户列表（admin） |
| POST | `/api/v1/auth/users` | 新建用户（admin） |
| DELETE | `/api/v1/auth/users/{username}` | 删除用户（admin） |
| PUT | `/api/v1/auth/users/{username}/password` | 重置密码（admin） |

**接口测试（部分）**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/api-test/projects/{id}/cases/generate` | AI 生成用例（Swagger/描述/代码） |
| POST | `/api/v1/api-test/projects/{id}/cases/generate-from-code` | 从代码生成用例 |
| POST | `/api/v1/api-test/projects/{id}/code-analyze` | 代码可行性分析 |
| POST | `/api/v1/api-test/projects/{id}/execute` | 单测执行 |
| POST | `/api/v1/api-test/projects/{id}/load` | 压力测试 |

**WebSocket 频道**

| client_id | 说明 |
| --- | --- |
| `ai_gen` | AI 用例生成/优化/增量更新进度 |
| `cases_gen` | UI 用例生成进度 |
| `api_exec` | 接口用例执行进度 |
| `api_load` | 压测实时指标 |
| `plan_<id>` | 测试计划执行进度 |

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

---

## 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE) 文件。
