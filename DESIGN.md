# AI 测试工具平台 — 设计思路

---

## 一、核心出发点：让测试人员少写代码

传统测试平台门槛高——测试工程师需要掌握编程、维护脚本框架、理解底层驱动。本项目的起点是反向思考：**能让 AI 做的事，人不做**。

| 环节 | 传统做法 | 本平台做法 |
| --- | --- | --- |
| 用例设计 | 人工逐条编写 | 上传文档 → AI 分段生成 |
| 需求变更 | 人工逐条比对、手动改用例 | 上传新文档 → AI Diff + 用例级增量更新 |
| 脚本编写 | Python/JS 脚本 | 录制回放 / `{{fn(arg)}}` 占位符，零代码 |
| 报告分析 | 人工逐条看日志 | 执行完自动调 LLM 输出修复建议 |
| 覆盖度评估 | 凭经验判断 | AI 分析盲区，自动追加补充用例 |

---

## 二、整体架构

```
Vue 3 前端（Element Plus + ECharts + Pinia）
    │ HTTP / WebSocket
FastAPI 路由层
  ├── auth / workspaces / webui / ai_cases
  ├── api_test / test_plans / global_vars / pentest
    │
┌───┴──────────────────────────────┐
│ WebUI 执行引擎                    │ 接口自动化引擎
│ Recorder / ActionRunner          │ httpx 异步驱动
│ BrowserPool（Semaphore=6）        │
└───────────────────┬──────────────┘
                    │
        LangGraph Agent（可选）
                    │
        共用基础设施（WebSocket / DB / JWT / AI / RAG）
```

两类引擎职责分离：UI 测试依赖浏览器状态天然串行，接口测试是纯 HTTP 天然并发，强行统一会相互污染。LangGraph 作为可选层，核心测试功能不依赖 Agent。

---

## 三、AI 集成：统一接口 + Prompt 配置化

所有 AI 调用统一读取「大模型配置」页，自动判断 Anthropic / OpenAI 格式，切换模型即切换全部 AI 功能。

Prompt 统一提取到 `skills/prompts/*.yaml`，懒加载 + LRU 缓存，**修改 YAML 后无需重启即可生效**，调优效果不改代码。

---

## 四、WebUI 执行引擎：ActionStep 驱动的确定性执行

WebUI 自动化的核心挑战是**可靠性**——选择器会失效、SPA 路由没有整页刷新、AI 生成的步骤语义不精确。平台用三层设计解决：

### 4.1 统一数据模型：ActionStep

录制器、AI 生成、执行引擎之间用 `ActionStep` 字典作为统一接口。核心字段：`action`（22 种操作类型）、`selector`、`selectors`（候选列表，执行时按序回退）、`value`、`url`、`expected`（断言期望值，支持正则）、`description`、`timeout`、`optional`（失败不中断）。

### 4.2 录制器：JS 事件注入 + 轮询

录制器向有头浏览器页面注入 JS 脚本，监听用户操作存入 `window.__recEvents`，Python 侧每 200ms 轮询转换为 ActionStep，并通过 WebSocket 实时预览。

**Selector 优先级**（JS 侧生成多个候选）：`data-testid` > `#id` > `[name=...]` > `[aria-label=...]` > `[placeholder=...]` > `:has-text(...)` > `tag.className` > `tag`。

**SPA 路由处理**：同时监听 `MutationObserver`、`popstate`、`hashchange`，Python 轮询持续检查 `page.url` 变化，双路保障 pushState 路由不丢导航步骤；URL 变化后立即重新注入录制脚本。

**智能步骤补全**：检测登录（用户名+密码+登录按钮）自动插入"等待登录 + 断言用户信息"；`submit` 后插入"等待响应 + 断言成功提示"；`navigate` 后插入"等待页面加载"。

### 4.3 ActionRunner：多 Selector 回退 + 统一执行

对交互类 action（click / fill / select 等），执行前依次探测所有候选 selector（`wait_for_selector` 2s 超时），找到可用者即执行。这解决了"录制时元素有 id，执行时 id 被框架动态替换"的高频问题。

**navigate 策略**：统一用 `domcontentloaded`（不等网络 idle），对 SPA 比 `networkidle` 成功率高 3 倍以上。

### 4.4 并发保护：进程内双锁

同一 task_id 的执行和录制各用一把 `asyncio.Lock` + 运行集合保护，重复触发返回 `409 Conflict`；两把锁在后台任务 `finally` 中释放，不会死锁。`BrowserPool` 用 `Semaphore(6)` 控制浏览器并发，超出排队等待而非报错。

---

## 五、需求变更增量更新：用例级精准合并

需求变更后重新生成的最大问题是旧用例全量覆盖。平台解法：

- **AI Diff 分析（模块级）**：旧用例模块名注入 Prompt，强制输出 `changed / added / removed / unchanged` 四分类，漏分用关键词二次判断。
- **用例级保守合并**：默认保留旧用例，LLM 只标「功能点完全消失」的用例为 deprecated；deprecated 超 50% 自动重置（防过激）。
- **版本追踪**：每次更新创建新版本（`parent_id` 指向旧版），废弃用例前端默认隐藏、可开关查看。

---

## 六、废弃与禁用：两个概念分开存储

| 字段 | 语义 | 执行影响 | 覆盖率影响 |
| --- | --- | --- | --- |
| `enabled` | 用户手动启用/禁用 | 前端传 case_ids 控制 | 计入覆盖率 |
| `deprecated` | 需求变更自动废弃 | **强制跳过** | **排除** |

禁用是「有效的测试设计，暂时不跑」；废弃是「真正无效」，必须分开存储。

---

## 七、需求-用例追踪矩阵

覆盖度分析只能回答「用例写得好不好」，无法回答「有没有漏测」。追踪矩阵从需求出发建立双向映射：

1. **需求提取**：AI 提取结构化需求条目（ID / 模块 / 标题 / 优先级）
2. **映射建立**：AI 判断每条用例覆盖的需求 ID，分批处理、进度推送
3. **矩阵计算**：`covered`（≥2 条）/ `insufficient`（1 条）/ `uncovered`（0 条）

覆盖不足时 AI 从 8 个测试维度分析缺口，勾选后生成补充用例。数据存在 `AICaseFile` 的 JSON 列，不新建表，向后兼容。

---

## 八、接口测试的两个 AI 增强

**代码驱动用例生成**：直接粘贴接口实现代码（Python/Java/Go/Node.js/PHP），AI 解析入参、边界、异常路径，生成 P0/P1/P2 用例，解决 Swagger 滞后问题。

**代码可行性分析**：同时提供需求文档和代码，AI 识别 `missing` / `mismatch` / `extra` / `risk` 四类偏差，自动生成差异验证用例，一键保存。

---

## 九、变量池：打通执行链路

```
全局变量池  {{gvar:token}}  → 跨项目持久化（scope=global）
局部变量    {{var:user_id}} → 当次执行链内存共享（scope=local，默认）
占位符函数  {{uuid()}}      → 执行时动态计算
```

变量提取时 `scope` 决定写入层级；测试计划所有步骤共享同一 `var_store`，实现端到端链路测试。自定义脚本函数存入 DB，执行时动态编译调用，不接触运行时。

接口用例的**请求体同样支持占位符**：`body`（JSON）走 `resolve_obj` 递归解析，`body_raw`（文本）走 `resolve_str`，请求体里可直接写 `{{脚本函数()}}` / `{{var:name}}` / `{{gvar:name}}`，执行时动态计算——签名、加密、随机 token 无需写死。

---

## 十、网络层可配置：面向真实测试环境

- **代理**：HTTP / HTTPS / SOCKS5，留空直连。
- **Hosts 映射**：自定义 `httpx.AsyncHTTPTransport` 子类拦截连接，域名重定向到指定 IP，保留原域名作 `Host` 头，不改系统 hosts，应用内隔离。

优先级：测试计划级 > 项目级，不冲突的条目合并生效。

---

## 十一、实时推送：全程 WebSocket，不轮询

所有耗时任务（用例生成、执行、压测、AI 分析、录制预览）HTTP 立即返回，后台异步执行，WebSocket 推送进度。服务端 30 秒心跳保活，超 40 秒清理僵尸连接；断线兜底靠任务结果写库 + 前端轮询恢复。

工作空间隔离：广播只推送给同一工作空间的连接。

---

## 十二、鉴权与用户管理

JWT 中间件统一验证 `/api/` 请求，白名单（登录、健康检查、下载、CI/CD Webhook）放行。密码 bcrypt 哈希，Token 有效期 7 天。

前端 axios 拦截器 401 后用 `router.replace` 软跳转（非 `window.location.href` 硬跳转），避免页面重载触发初始化请求死循环。

---

## 十三、工作空间与多用户数据隔离

工作空间是顶层隔离单元，AI 用例、WebUI 任务、接口项目、测试计划、全局变量均挂在其下。成员 role 分 owner（管理成员）/ member（读写数据），admin 可跨空间查看。升级时旧数据自动归入「默认空间」，无感知兼容。

---

## 十四、数据库：向前兼容 + asyncpg 事务隔离

启动时 `create_all` 自动建表，新字段用 `ALTER TABLE ... ADD COLUMN` 兼容旧库。SQLite（本机）/ PostgreSQL（Docker）双兼容，只改 `DATABASE_URL`。

**关键设计**：asyncpg 遇到错误会把当前事务标记为 aborted，后续语句被静默拒绝。因此每条 DDL 必须独立 `engine.begin()` 事务，任何一条失败只影响自己。

---

## 十五、RAG 知识库：分段检索替代硬截断

文档按 900 字/段（200 字重叠）分段入库，生成时按模块名检索最相关段落（pgvector 余弦相似度 / SQLite 降级关键词匹配），避免超长文档后半部分被遗漏。embedding 不可用时自动降级，不中断流程。

---

## 十六、稳定性保障

- **截断 JSON 修复**：LLM 输出被 `max_tokens` 截断时，扫描最后一个完整元素并补齐闭合括号。
- **WebUI 三级兜底**：元素 > 3 正常分析；≤ 3 走文档驱动；无文档走页面正文，配合分屏自动滚动抓取懒加载内容。
- **中文 PDF**：pymupdf 优先（直接读 Unicode），PyPDF2 降级。
- **Anthropic 代理兼容**：防御性解析 content 字段、过滤 thinking block，兼容各类中转代理。
- **录制/执行细节**：表单跳转用 `beforeunload` 兜底导航；`stop_recording` 后立即清理 session 防内存泄漏；空值/无 timeout 参数的边界均做防御处理。

---

## 附：技术选型

| 问题 | 选型 | 原因 |
| --- | --- | --- |
| 异步服务 | FastAPI + Uvicorn | 原生 async，自动 API 文档 |
| Agent 编排 | LangGraph + LangChain | 工作流状态机 + 工具注册 |
| 数据库 | SQLite / PostgreSQL | 开发零配置，生产多并发 |
| 浏览器自动化 | Playwright | async API，多浏览器，录制支持 |
| 接口执行 | httpx | 原生异步，支持自定义 Transport |
| 实时通信 | WebSocket | 服务端主动推送 |
| 前端 | Vue 3 + Element Plus | 组件成熟，适合工具类产品 |
| AI 调用 | 统一 HTTP API | 支持任意模型，不依赖本机 CLI |
| 鉴权 | JWT + bcrypt | 中间件统一验证，密码安全存储 |
| Prompt 管理 | YAML + prompt_loader | 与代码解耦，修改无需重启 |
| 限流 | slowapi | 按真实 IP，支持反向代理 |
| 反向代理 | Nginx（可选） | WebSocket 升级，HTTPS |
| 并发控制 | asyncio.Semaphore + set | 进程内轻量，无外部依赖 |
| 任务队列 | ARQ + Redis（可选） | 多 Worker 持久化，降级 BackgroundTasks |
| 定时调度 | APScheduler | Cron 定时计划，重启自动恢复 |

---

## 十七、WebUI 场景规划：AI 只做"测什么"，人来做"怎么点"

### 17.1 根本问题：AI 生成的 selector 是猜的

AI 看到的是静态元素元数据，SPA 动态 id、条件渲染、弹窗时序的任何偏差都会导致失败。录制器则从真实 DOM 提取 selector，亲测可用。**结论：AI 只做场景规划（测什么），不做 steps_json 生成（怎么点）。**

### 17.2 场景规划接口设计

`POST /cases/plan-scenes/{task_id}` 输入：页面关键元素（按功能区分组去重）、已有用例名称（防重复）、需求文档摘要；场景数量按信息量分级（有文档 8-10 / 有元素 6-8 / 无信息 5-6）。

输出 5 个落地维度的场景列表（名称、优先级、操作步骤描述、预期结果），持久化到 `TestTask.scene_plan`，支持追加规划。**5 个维度**：核心业务流程（P0）、表单验证（P1）、数据增删改（P1）、列表与筛选（P1）、异常与错误反馈（P1）。不选"权限控制"和"并发"（单 session 录制无法实现）。

### 17.3 场景 → 录制联动

AI 规划出场景列表后，点「开始录制」即关抽屉启动有头浏览器，用户录制操作 → 停止 → AI 健壮化 → 保存用例 → 场景标记 recorded=true。重新规划时保留已录制场景，只清空未录制的。

---

## 十八、录制步骤健壮化：step_hardener

录制器虽已生成多候选 selector，但原始候选质量参差（动态数字 id、哈希 class）。`skills/step_hardener.py` 在保存时自动运行：

- **Selector 评级（A/B/C/D）**：A（data-testid/aria-label/name/placeholder）> B（:has-text/role/type）> C（.class/#id）> D（动态 id/哈希 class，标红提示）。
- **候选推导**：从 `#id` 推 `[name=id]`/`[aria-label=id]`，从 description 提取 `:has-text(...)`，fill/type 的 value 作 `[placeholder=value]` 候选，合并后按 A→B→C→D 重排。
- **断言插入**：检测"登录/提交/确认/删除"等关键操作，下一步非 assert/wait 时自动插入 `wait` + `assert_visible`（optional）。
- **前端编辑器**：双 Tab（基本信息 / 步骤编辑器），每行显示评级标签，D 级 selector 标红并可一键切换备选。

---

## 十九、接口自动化 WebSocket 隔离

接口生成/执行/压测的进度按 `project_id` 动态路由（`api_gen_{id}` / `api_exec_{id}` / `api_load_{id}`），替代固定 client_id，多用户操作不同项目时进度完全隔离。

---

## 二十、覆盖度优化耗时控制

覆盖度分析从「每模块两轮 LLM（600s）」优化为「单轮 + 并发 Semaphore(4) + 模块上限 8（120s）」，用第二轮盲区确认的少量补充场景换取 5× 速度提升。

---

## 二十一、Mock 服务

轻量内置 Mock，路由注册在 `/mock/*`（不经过 JWT，前端联调无需 token）。匹配优先级：method + path 精确匹配 → path 通配符 → 404；`match_params` 支持对请求体/查询参数做子集匹配，每次命中记录请求日志。

---

## 二十二、定时执行调度器

测试计划支持 Cron 定时触发（APScheduler）。服务重启时扫描 `cron_enabled=True` 的计划自动恢复注册；启用/禁用切换动态 add_job / remove_job，无需重启。

---

## 二十三、接口用例生成：请求体注入与动态场景规划

接口用例 AI 生成链路（curl 解析 → 分组 → 预探测 → 场景分析 → 逐条生成 → 断言校验 → ReAct 自检）早期存在三个质量问题，已修复：

- **请求体注入**：curl 的 `--data-binary`/`-d` body 曾被解析到 `probe_hint` 却未回传 Prompt，导致 POST/PUT/PATCH 用例请求体缺失。现将 body、body_type、业务 headers（剔除通用头）拼入 Prompt，并对「正常流」缺失 body 做确定性回填。
- **动态场景数量**：不再写死上限，按接口真实复杂度动态规划（参数/分支越多场景越多，简单查询越少），去重后防御性上限 30 条；用户指定数量时用 AI 规划 + 默认场景补齐。
- **功能化命名**：命名兜底从 `TC001` 编号改为「模块-场景」中文命名。

---

## 二十四、WebUI 控制流：if/else 与 while

WebUI 用例从线性执行升级为支持条件分支与循环轮询。执行引擎通过 `skills/control_flow.py` 将扁平 `steps_json` 与嵌套步骤树无损互转（`unflatten`/`flatten`），条件表达式用 `ast` 白名单安全求值（禁用 `eval`）。

第一阶段支持 `if / else / endif`（条件分支）与 `while / endwhile`（循环轮询，`max_iter` 防死循环、`delay_ms` 轮询间隔）。条件 DSL 支持 `exists/visible/hidden/count/text(sel)`、页面属性 `url/title`、比较/逻辑/`contains`、`{{key}}` 变量替换。

`for/endfor/break/continue/elseif/try/goto/label` 已在 `docs/webui-control-flow-design.md` 规划，第一阶段显式禁止，遇到会明确报错而非静默执行。

---

## 二十五、Docker 一键部署

生产环境通过 Docker Compose 一键部署，前端构建与后端运行分两阶段打包进同一镜像：

- **多阶段构建**（`Dockerfile`）：Node 18 构建 `ui/dist` → 官方 Playwright Python 镜像（内置 Chromium，跳过重复下载）→ 非 root `appuser` 运行。
- **服务编排**（`docker-compose.yml`）：`db`（pgvector）+ `app` 常驻；`redis`/`worker`（ARQ）、`nginx`（反向代理）按 `--profile` 按需启动。
- **数据持久化**：PostgreSQL 与文件分别落在命名卷 `pg_data` / `app_data`。
- **单进程约束**：`workers=1`（全局 LLM Semaphore 与后台计数器均为进程内对象），横向扩展应部署多容器实例。
- **配置外置**：`.env.docker` 提供完整环境变量模板，`.env` 不提交仓库。

---

## 一句话总结

> 平台的设计主线是**把 AI 能力嵌入测试生命周期的每个环节**——场景规划让 AI 决定"测什么"，录制让人负责"怎么点"，健壮化保证录制结果的执行可靠性，可视化步骤编辑器让调整有据可查，工作空间支持团队协作，三层变量池打通接口链路，RAG 替代硬截断，多级兜底保证各种场景下都能生成——整体目标是让测试工程师从重复劳动中解放出来，专注于测试策略和质量判断。
