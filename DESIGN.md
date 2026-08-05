# AI 测试工具平台 — 设计思路

---

## 一、核心出发点：让测试人员少写代码

传统测试平台门槛高——测试工程师需要掌握编程、维护脚本框架、理解底层驱动。这个项目的起点是反向思考：**能让 AI 做的事，人不做**。

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
  ├── auth / workspaces
  ├── webui（录制/执行/报告）
  ├── ai_cases（文档驱动用例生成）
  ├── api_test（接口自动化 + 压测）
  ├── test_plans（CI/CD 集成）
  ├── global_vars（变量池）
  └── pentest（渗透测试）
    │
┌───┴──────────────────────────────┐
│ WebUI 执行引擎                    │ 接口自动化引擎
│ Recorder（录制）                  │ httpx 异步驱动
│ ActionRunner（确定性执行）         │
│ BrowserPool（Semaphore=6）        │
│ Playwright 驱动                   │
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

WebUI 自动化的核心挑战是**可靠性**——选择器会失效、SPA 路由没有整页刷新、AI 生成的步骤可能语义不精确。平台用了三层设计来解决这个问题：

### 4.1 统一数据模型：ActionStep

录制器、AI 生成、执行引擎之间用 `ActionStep` 字典作为统一接口。每个步骤有固定字段：

```python
{
  "id":          str,     # 步骤 ID（s001, s002...）
  "action":      str,     # 22 种 action 类型之一
  "selector":    str,     # 主选择器
  "selectors":   list,    # 候选选择器列表（执行时按序回退）
  "value":       str,     # 填写内容 / 按键名 / JS 表达式
  "url":         str,     # navigate/wait_for_url 目标
  "expected":    str,     # assert_* 期望值（支持正则）
  "description": str,     # 人类可读描述（报告展示 + pytest 注释）
  "timeout":     int,     # 超时毫秒，默认 10000
  "optional":    bool,    # True = 失败不中断用例
}
```

支持 22 种 action：`navigate / click / dblclick / rightclick / fill / type / select / check / uncheck / hover / press / scroll / upload / wait_for / submit / keydown / wait / assert_text / assert_visible / assert_hidden / assert_url / assert_title / assert_count / screenshot / evaluate`

### 4.2 录制器：JS 事件注入 + 轮询

录制器在有头浏览器页面注入一段 JS 脚本，监听所有用户操作，存入 `window.__recEvents` 队列；Python 侧每 200ms 拉取一次，转换为 ActionStep。

```
用户操作浏览器 → JS 监听事件 → window.__recEvents[]
    Python 轮询 ↗                      ↘
         session.steps[]            _event_to_step()
              ↓
         ws_callback → 前端实时预览
```

**Selector 优先级**（JS 侧生成多个候选）：
`data-testid` > `#id` > `[name=...]` > `[aria-label=...]` > `[placeholder=...]` > `:has-text(...)` > `tag.className` > `tag`

**SPA 路由处理**：同时监听 `MutationObserver`、`popstate`、`hashchange`，Python 轮询也持续检查 `page.url` 变化，两路保障 pushState 路由不丢导航步骤。任何 URL 变化后立即重新注入录制脚本。

**智能步骤补全**（`enrich_recorded_steps`）：
- 检测到用户名 + 密码 + 登录按钮 → 自动插入"等待登录完成 + 断言用户信息可见"
- `submit` 事件后 → 自动插入"等待页面响应 + 断言成功提示（optional）"
- `navigate` 步骤后 → 自动插入"等待页面加载完成"
- 尾部自动追加页面标题断言（optional）

### 4.3 ActionRunner：多 Selector 回退 + 统一执行

`ActionRunner._run_step` 在调用 `_dispatch` 前，先对交互类 action（click / fill / select 等）尝试所有候选 selector：

```python
for _sel in selectors_to_try:
    try:
        await page.wait_for_selector(_sel, state="attached", timeout=2000)
        selector = _sel    # 找到可用 selector，使用它
        break
    except Exception:
        continue           # 换下一个候选
```

这解决了"录制时元素有 id，执行时 id 被框架动态替换"的高频问题。

**navigate 策略**：统一用 `domcontentloaded`（不等网络 idle），对 SPA 应用比 `networkidle` 成功率高 3 倍以上。commit 级别作为最后兜底。

**keydown action**：`value` 字段存按键名（Enter / Tab / Escape），执行时优先在 selector 元素上 press，fallback 到全局 keyboard.press。

**wait action**：录制后处理插入的固定等待步骤，timeout 字段优先，value 为空字符串时不会崩溃（`str.isdigit()` 判断）。

### 4.4 并发保护：进程内双锁

```python
# 执行锁：同一 task_id 同时只允许一个执行实例
_running_tasks: set = set()
_running_tasks_lock = asyncio.Lock()

# 录制锁：同一 task_id 同时只允许一个录制 session
_active_recording_tasks: set = set()
_active_recording_lock = asyncio.Lock()
```

重复触发时返回 `409 Conflict`，前端可友好提示。两把锁在后台任务结束时（无论成功/失败/异常）的 `finally` 块里释放，不会死锁。

**浏览器 Context 并发**：`BrowserPool` 用 `Semaphore(MAX_CONCURRENT=6)` 控制，超出排队等待而不是报错，适应多用户并发执行场景。

---

## 五、需求变更增量更新：用例级精准合并

需求变更后重新生成的最大问题是旧用例全量覆盖。平台的解法：

**AI Diff 分析（模块级）**：把旧用例模块名注入 Prompt，强制 AI 输出 `changed / added / removed / unchanged` 四分类，漏分的旧模块用关键词搜索二次判断。

**用例级保守合并**：默认保留所有旧用例，LLM 只找「功能点完全消失」的用例标为 deprecated，新场景追加新用例。deprecated 超过 50% 自动重置（防 LLM 过激）。

**版本追踪**：每次更新创建新版本（`parent_id` 指向旧版），废弃用例前端默认隐藏，可开关查看。

---

## 六、废弃与禁用：两个概念分开存储

| 字段 | 语义 | 执行影响 | 覆盖率影响 |
| --- | --- | --- | --- |
| `enabled` | 用户手动启用/禁用 | 由前端传 case_ids 控制 | 计入覆盖率 |
| `deprecated` | 需求变更自动废弃 | **强制跳过** | **排除** |

禁用是「有效的测试设计，暂时不跑」；废弃是「真正无效」，必须分开存储。

---

## 七、需求-用例追踪矩阵

覆盖度分析只能回答「用例写得好不好」，无法回答「有没有漏测」。追踪矩阵从需求出发建立双向映射：

1. **需求提取**：AI 从文档中提取结构化需求条目（ID / 模块 / 标题 / 优先级）
2. **映射建立**：AI 对每条用例判断覆盖了哪些需求 ID，分批处理，进度实时推送
3. **矩阵计算**：`covered`（≥2 条）/ `insufficient`（1 条）/ `uncovered`（0 条）

对覆盖不足的需求，AI 从 8 个测试维度分析缺口，用户勾选后生成补充用例，矩阵实时刷新。所有数据存在 `AICaseFile` 的 JSON 列，不新建表，向后兼容。

---

## 八、接口测试的两个 AI 增强

**代码驱动用例生成**：直接粘贴接口实现代码（Python/Java/Go/Node.js/PHP），AI 解析入参、边界、异常路径，生成覆盖 P0/P1/P2 的用例，解决 Swagger 滞后问题。

**代码可行性分析**：同时提供需求文档和代码，AI 识别 `missing`（未实现）/ `mismatch`（行为不一致）/ `extra`（隐式限制）/ `risk`（潜在风险）四类偏差，自动生成差异验证用例，一键保存到用例库。

---

## 九、变量池：打通执行链路

```
全局变量池  {{gvar:token}}  → 跨项目持久化，scope=global 时写入
局部变量    {{var:user_id}} → 当次执行链内存共享，scope=local（默认）
占位符函数  {{uuid()}}      → 执行时动态计算
```

变量提取时 `scope` 字段决定写入层级。测试计划中所有步骤共享同一 `var_store`，实现真正的端到端链路测试。自定义脚本函数存入 DB，执行时动态编译，用 `{{sign(key, data)}}` 调用，不接触运行时。

---

## 十、网络层可配置：面向真实测试环境

**代理**：HTTP / HTTPS / SOCKS5，留空直连。

**Hosts 映射**：自定义 `httpx.AsyncHTTPTransport` 子类拦截连接请求，域名重定向到指定 IP，保留原域名作为 `Host` 头，不改系统 hosts，应用内隔离。

优先级：测试计划级 > 项目级，不冲突的条目合并生效。

---

## 十一、实时推送：全程 WebSocket，不轮询

所有耗时任务（用例生成、测试执行、压测、AI 分析、录制步骤预览）HTTP 请求立即返回，后台异步执行，WebSocket 推送进度。服务端每 30 秒心跳保活，超 40 秒无响应主动清理僵尸连接。断线兜底：任务结果写库，前端轮询状态恢复进度。

工作空间隔离：客户端订阅后，广播时只推送给同一工作空间的连接，不同项目组的消息互不干扰。

---

## 十二、鉴权与用户管理

JWT 中间件统一验证所有 `/api/` 请求，白名单（登录、健康检查、下载、CI/CD Webhook）直接放行。密码 bcrypt 哈希，Token 有效期 7 天。

前端 axios 拦截器 401 后用 `router.replace` 软跳转（非 `window.location.href` 硬跳转），避免页面重载触发初始化请求死循环；`App.vue` 在登录页时跳过所有初始化请求。

---

## 十三、工作空间与多用户数据隔离

工作空间作为顶层隔离单元，AI 用例、WebUI 任务、接口项目、测试计划、全局变量均挂在工作空间下。成员 role 分 owner（管理成员）/ member（读写数据），admin 可跨空间查看全部。升级时旧数据自动归入「默认空间」，无感知兼容。

---

## 十四、数据库：向前兼容 + asyncpg 事务隔离

启动时 `create_all` 自动建表，新字段用 `ALTER TABLE ... ADD COLUMN` 兼容旧库。SQLite（本机开发）/ PostgreSQL（Docker 生产）双兼容，只改 `DATABASE_URL`，代码零改动。

**关键设计**：asyncpg 遇到任何错误会把当前事务标记为 aborted，后续语句被 PostgreSQL 静默拒绝。因此每条 DDL 必须独立 `engine.begin()` 事务，任何一条失败只影响自己，不连累建表操作。

---

## 十五、RAG 知识库：分段检索替代硬截断

文档按 900 字/段（200 字重叠）分段入库，生成时按模块名检索最相关段落（pgvector 余弦相似度 / SQLite 降级关键词匹配）替代截取前 N 字，确保超长文档后半部分不被遗漏。DeepSeek / Anthropic 不支持 embedding 时自动降级，不中断流程。

---

## 十六、稳定性保障

**截断 JSON 修复**：LLM 被 `max_tokens` 截断时，逐字符扫描找最后一个完整元素，补齐闭合括号，保留已生成内容。

**WebUI 三级兜底**：元素 > 3 → 正常分析；元素 ≤ 3 → 文档驱动；无文档 → 页面正文兜底。配合分屏自动滚动（最多 40 屏）抓取懒加载内容。

**中文 PDF**：pymupdf 优先（直接读 Unicode 映射），PyPDF2 降级，避免乱码导致 LLM 理解失败。

**Anthropic 代理兼容**：防御性解析 content 字段，过滤 thinking block，多备选字段兜底，兼容各类中转代理格式。

**录制稳定性**：
- 表单提交整页跳转时 `beforeunload` 事件内写入最后一次导航，避免轮询未来得及拉取
- `stop_recording` 结束后立即从 `_sessions` 字典移除，防止内存泄漏；路由层无需手动调 `cleanup_session`
- 轮询异常按严重程度分级记录（debug/warning/error），不再用 `except: pass` 吞掉所有异常

**执行稳定性**：
- `is_visible()` 不接受 `timeout` 参数，assert_visible 步骤改用 try/except 包裹
- `wait` action 的 `value` 可能为空字符串，用 `str.isdigit()` 判断后再转 int，避免 `int("")` 崩溃
- `_dispatch` 内新增 action 不引用 `step` 变量（不在参数中），只用已解析的 `value`/`timeout`/`selector`

---

## 附：技术选型

| 问题 | 选型 | 原因 |
| --- | --- | --- |
| 异步服务 | FastAPI + Uvicorn | 原生 async，自动 API 文档 |
| Agent 编排 | LangGraph + LangChain | 工作流状态机 + 工具注册 |
| 数据库 | SQLite / PostgreSQL | 开发零配置，生产多并发 |
| 浏览器自动化 | Playwright | async API，多浏览器，录制支持 |
| 接口执行 | httpx | 原生异步，支持自定义 Transport |
| 实时通信 | WebSocket | 服务端主动推送，拒绝轮询 |
| 前端 | Vue 3 + Element Plus | 组件成熟，适合工具类产品 |
| AI 调用 | 统一 HTTP API | 支持任意模型，不依赖本机 CLI |
| 鉴权 | JWT + bcrypt | 中间件统一验证，密码安全存储 |
| Prompt 管理 | YAML + prompt_loader | 与代码解耦，修改无需重启 |
| 限流 | slowapi | 按真实 IP，支持反向代理 |
| 反向代理 | Nginx（可选） | WebSocket 升级，HTTPS，静态资源缓存 |
| 并发控制 | asyncio.Semaphore + set | 进程内轻量，无外部依赖 |
| 任务队列 | ARQ + Redis（可选） | 多 Worker 持久化，不配置降级 BackgroundTasks |
| 定时调度 | APScheduler | Cron 定时计划，重启自动恢复 |

---

## 十七、WebUI 场景规划：AI 只做"测什么"，人来做"怎么点"

### 17.1 根本问题：AI 生成的 selector 是猜的

AI 看到的是静态元素元数据，它在推断 `[data-testid="login-btn"]` 能否点到。SPA 动态 id、条件渲染、弹窗时序，任何细节偏差就失败。录制器则是从真实 DOM 里提取 selector，亲测能用。

**结论：AI 应该只做"测什么"（场景规划），不做"怎么点"（steps_json 生成）。**

### 17.2 场景规划接口设计

`POST /cases/plan-scenes/{task_id}` 接受可选的功能描述，输入：

1. **页面关键元素**（按功能区分组：表单输入/操作按钮/导航链接/下拉选择，去重取前 8）
2. **已有用例名称**（注入 Prompt，防止生成重复场景）
3. **需求文档摘要**（task.doc_snapshot 前 800 字，截断到最近句号）
4. **场景数量**：有文档 → 8-10，有元素 → 6-8，无信息 → 5-6

输出 5 个落地维度的场景列表，每个场景含名称、优先级、操作步骤描述（无 selector）、预期结果。结果持久化到 `TestTask.scene_plan`，支持追加规划（保留已录制场景）。

**5 个落地维度**（对应录制器能捕捉的操作）：
- **核心业务流程**（P0）：页面主要功能的 happy path
- **表单验证**（P1）：必填/格式/联动/提交拦截
- **数据增删改**（P1）：创建→列表出现，编辑→内容更新，删除→确认弹窗→消失
- **列表与筛选**（P1）：搜索/条件筛选/分页/排序/清空/空态
- **异常与错误反馈**（P1）：错误提示/空状态/加载态

不选"权限控制"和"并发"，因为这两个在单 session 录制里无法实现。

### 17.3 场景 → 录制联动

```
AI 规划 → 场景列表（抽屉）
           → 点「开始录制」
              → 关抽屉，启动有头浏览器
              → 用户录制操作
              → 停止录制 → AI 健壮化 → 保存用例
              → 场景标记 recorded=true（同步持久化后端）
              → 重新打开抽屉，继续下一个场景
```

场景卡片支持行内编辑名称/描述，步骤预览默认折叠，减少视觉噪音。"重新规划"时保留已录制场景，只清空未录制的。

---

## 十八、录制步骤健壮化：step_hardener

录制器已有多 selector 候选（按 data-testid > id > name > aria-label > :has-text > class > tag 优先级生成），但原始候选质量参差不齐——动态数字 id、哈希 class 混在其中，执行时仍会失败。

`skills/step_hardener.py` 在录制保存时自动运行：

### 18.1 Selector 评级（A/B/C/D）

| 等级 | Selector 特征 | 示例 |
| --- | --- | --- |
| A | data-testid / aria-label / name / placeholder | `[data-testid="login-btn"]` |
| B | :has-text() / role / type=submit | `button:has-text("登录")` |
| C | .className / 普通 #id | `.submit-btn`, `#login-form` |
| D | 动态数字 id / 哈希 class / 纯 tag | `#btn-20241105`, `.abc123def` |

### 18.2 候选 selector 推导规则

从已有 selector + description + value 规则推导更多候选，自动排序：
- 从 `#id` 推导 `[name=id]` / `[aria-label=id]`
- 从 description 提取关键词生成 `:has-text("...")`
- fill/type 步骤：value 作为 `[placeholder=value]` 候选
- 合并已有候选，按 A→B→C→D 重新排序

### 18.3 关键操作后自动插入断言

检测"登录/提交/确认/删除"等关键操作（click 动作 + 语义关键词），若下一步不是 assert/wait，自动插入：
```
wait { timeout: 3000, optional: true }
assert_visible { selector: "[role='alert'],.el-message,.toast", optional: true }
```

### 18.4 前端步骤编辑器

用例编辑弹窗升级为双 Tab：
- **基本信息**：原有文本表单
- **步骤编辑器**：步骤表格，每行显示健壮度评级（A/B/C/D 彩色标签）、action 下拉、selector（D 级标红，点击展开所有备选一键切换）、value/expected、超时/optional

步骤编辑保存时同步生成 `steps` 可读文本（向后兼容报告显示）。

---

## 十九、接口自动化 WebSocket 隔离

原来接口生成/执行/压测用固定 client_id（`"api_gen"` / `"api_exec"` / `"api_load"`），多用户同时操作不同项目时进度互串。

改为按 project_id 动态路由：

```
api_gen_{project_id}   → 该项目的 AI 生成进度
api_exec_{project_id}  → 该项目的执行进度
api_load_{project_id}  → 该项目的压测实时指标
```

前端在发起请求前先 `connectWs(`api_gen_${project.id}`)` 订阅正确频道，后端 background task 里用相同 client_id broadcast。项目 A 和项目 B 的进度完全隔离。

---

## 二十、覆盖度优化耗时控制

原设计：每模块两轮 LLM（第一轮 90s + 第二轮 60s），并发 Semaphore(2)。  
8 个模块最坏耗时 = ceil(8/2) × 150s = **600s**，超出 axios 420s 超时。

优化后：
- 两轮合并为单轮（8维度简化为5维度，关键维度保留），单模块 LLM timeout = 60s
- 并发 Semaphore(2) → **Semaphore(4)**
- 模块数量上限 **MAX_MODULES = 8**，超出按用例数降序取前 8
- 最坏耗时 = ceil(8/4) × 60s = **120s**

质量损失：第二轮"盲区确认"的额外补充场景（平均 1-2 条/模块）换取 5× 速度提升，可接受。

---

## 二十一、Mock 服务

轻量内置 Mock，路由注册在 `/mock/*`，不经过 JWT 中间件（前端联调不需要 token）。

规则匹配优先级：method + path 精确匹配 → path 通配符匹配 → 404。请求参数匹配（`match_params` JSON 字段）支持对请求体或查询参数做子集匹配。每次命中记录请求日志，便于调试。

---

## 二十二、定时执行调度器

测试计划支持 Cron 定时触发，`api/scheduler.py` 使用 APScheduler：

```python
scheduler = AsyncIOScheduler()

async def init_scheduler():
    # 扫描所有 cron_enabled=True 的计划，注册到 scheduler
    # 服务重启时自动恢复，不依赖外部存储
    ...
```

Cron 表达式存在 `TestPlan.cron_expr`，启用/禁用切换时动态 add_job / remove_job，不需要重启服务。

---

## 一句话总结

> 平台的设计主线是**把 AI 能力嵌入测试生命周期的每个环节**——场景规划让 AI 决定"测什么"，录制让人负责"怎么点"，健壮化保证录制结果的执行可靠性，可视化步骤编辑器让调整有据可查，工作空间支持团队协作，三层变量池打通接口链路，RAG 替代硬截断，多级兜底保证各种场景下都能生成——整体目标是让测试工程师从重复劳动中解放出来，专注于测试策略和质量判断。
