# AI 测试工具平台 — 设计思路

---

## 一、核心出发点：让测试人员少写代码

传统测试平台门槛高——测试工程师需要掌握编程、维护脚本框架、理解底层驱动。这个项目的起点是反向思考：**能让 AI 做的事，人不做**。

| 环节 | 传统做法 | 本平台做法 |
| --- | --- | --- |
| 用例设计 | 人工逐条编写 | 上传文档 → AI 分段生成 |
| 需求变更 | 人工逐条比对、手动改用例 | 上传新文档 → AI Diff + 用例级增量更新 |
| 脚本编写 | Python/JS 脚本 | `{{fn(arg)}}` 占位符，零代码 |
| 报告分析 | 人工逐条看日志 | 执行完自动调 LLM 输出修复建议 |
| 覆盖度评估 | 凭经验判断 | AI 分析盲区，自动追加补充用例 |

平台不追求取代测试工程师的判断力，而是消除重复性劳动，把人的精力集中在测试策略和质量决策上。

---

## 二、两套引擎并行，职责分离

```
┌──────────────────────┐   ┌────────────────────────────┐
│    UI 自动化引擎      │   │      接口自动化引擎          │
│  Playwright 驱动     │   │  httpx 异步驱动              │
│  任务 → 用例 → 执行   │   │  项目 → 用例 → 计划 → 执行  │
└──────────────────────┘   └────────────────────────────┘
           └──────────────┬──────────────────┘
                          ▼
           共用基础设施（WebSocket / DB / AI / JWT）
```

两类测试执行模型有本质差异：UI 测试依赖浏览器状态，天然串行；接口测试是纯 HTTP，天然适合并发和链路编排。强行统一会让两套逻辑相互污染，分离后各自演进，互不影响。

---

## 三、AI 集成：统一接口 + Prompt 配置化

### 统一 HTTP API，支持任意模型

所有 AI 调用（用例生成、报告分析、代码分析）统一读取「大模型配置」页的设置，自动判断格式：

```python
is_anthropic = "anthropic.com" in base_url
# Anthropic：POST /v1/messages + x-api-key
# OpenAI 兼容：POST /v1/chat/completions + Authorization: Bearer
```

好处：大模型配置页切换模型，所有 AI 功能同步生效；不依赖本机 CLI，可部署到任意服务器。

### Prompt 配置化管理

早期所有 Prompt 硬编码在 Python 文件里，调优需要改代码、重启服务。改造后统一提取到 `skills/prompts/*.yaml`：

```
skills/prompts/
├── ai_case_gen.yaml    # 文档驱动用例生成的所有 prompt
├── api_case_gen.yaml   # 接口用例生成 prompt
├── code_analyze.yaml   # 代码可行性分析 prompt
└── ui_case_gen.yaml    # WebUI 用例生成 prompt
```

通过 `prompt_loader.py` 懒加载 + LRU 缓存，skill 文件只调 `get_system()` / `render_user()`，**修改 YAML 后无需重启即可生效**。

---

## 四、需求变更增量更新：用例级精准合并

需求变更后重新生成用例的最大问题是**旧用例全量覆盖**——调试过的用例、人工编辑的步骤、执行历史全部丢失。平台设计了三层机制：

**第一层：AI Diff 分析（模块级）**

把旧用例的真实模块名列表注入 Prompt，强制 AI 使用原始名字，输出 `changed / added / removed / unchanged` 四分类。AI 漏分类的旧模块用文本关键词搜索二次判断；性能/兼容/安全等通用测试模块永不因需求变更废弃。

**第二层：用例级保守合并（changed 模块）**

```
默认保留所有旧用例
  ↓
LLM 只找：功能点在新文档中「完全消失」的用例 → deprecated
LLM 识别：新需求中的新场景 → 生成新用例追加
  ↓
安全兜底：deprecated 超过旧用例 50% → 自动重置为空（防 LLM 过激）
```

为什么默认保留？让 LLM 逐条判断时，面对整个新文档会倾向"不确定就 deprecated"，导致大量旧用例被错误废弃。反向逻辑（有明确依据才废弃）更符合测试工程师习惯。

**第三层：版本追踪**

每次增量更新创建新版本记录（`parent_id` 指向旧版），废弃用例追加模块末尾，前端默认隐藏，可开关查看。

---

## 五、废弃与禁用：两个概念分开存储

早期用 `enabled=False` 同时表示「用户手动禁用」和「需求变更废弃」，造成语义混乱。

改造：给 `TestCase` 加独立的 `deprecated` 字段：

| 字段 | 语义 | 执行影响 | 覆盖率影响 |
| --- | --- | --- | --- |
| `enabled` | 用户手动启用/禁用 | 由前端传 case_ids 控制 | 计入覆盖率 |
| `deprecated` | 需求变更自动废弃 | **强制跳过** | **排除** |

禁用的用例是「有效的测试设计，暂时不跑」；废弃的用例是「真正无效」。两者必须分开。

---

## 六、接口测试的两个 AI 增强能力

### 接口代码驱动用例生成

测试工程师拿到的往往是开发提交的代码，Swagger 文档滞后或根本不存在。新增第三种输入模式：直接粘贴接口实现代码，AI 解析入参结构、边界条件、异常路径、隐式业务规则，生成覆盖 P0/P1/P2 的用例，每条附 `_code_insight` 字段记录关键测试依据。支持 Python/Java/Go/Node.js/PHP。

### 代码可行性分析

代码 Review 关注「代码写得对不对」，代码可行性分析关注「代码实现了需求吗」——视角和产物完全不同，面向不同受众。

同时提供需求文档和接口实现代码，AI 对比识别四类偏差：

| 类型 | 含义 |
| --- | --- |
| `missing` | 需求有但代码未实现 |
| `mismatch` | 需求与代码行为不一致（数值范围/状态码/响应格式） |
| `extra` | 代码有需求未提及的隐式限制（频率限制/权限控制） |
| `risk` | 代码本身的潜在风险（并发竞态/null 未校验） |

每条偏差附严重程度、需求原文、代码行为、测试重点、修复建议，并自动生成 1-2 条差异验证用例，一键保存到用例库。

---

## 七、变量池：打通执行链路

接口测试的核心难题是用例间数据依赖（登录拿到 token，后续接口必须带上）。平台设计三层变量机制：

```
全局变量池  {{gvar:token}}  → 跨项目持久化，DB 存储
本地变量    {{var:user_id}} → 当次执行链内存级共享
占位符函数  {{uuid()}}      → 执行时动态计算
```

测试计划中所有步骤共享同一 `var_store`，实现真正的端到端链路测试。自定义脚本函数以 Python 代码存入 DB，执行时动态编译注入，测试人员用 `{{sign(key, data)}}` 调用，不接触运行时。

---

## 八、网络层可配置：面向真实测试环境

测试环境往往不是标准公网直连。平台在 HTTP 执行层支持两种配置：

**代理**：HTTP / HTTPS / SOCKS5，自动补 `http://` 前缀，留空直连。

**Hosts 映射**：自定义 `httpx.AsyncHTTPTransport` 子类，拦截连接请求，将目标域名重定向到指定 IP，同时保留原域名作为 `Host` 请求头，HTTPS 配合 `verify=False` 正常工作。不改系统 hosts，应用内隔离，不同项目可有不同映射规则。

优先级：测试计划级 > 项目级，不冲突的条目合并生效。

---

## 九、实时推送：全程 WebSocket，不轮询

所有耗时任务（用例生成、测试执行、压力测试、AI 分析）均通过 WebSocket 推送进度，前端不做任何轮询。

```python
# HTTP 请求立即返回，执行在后台异步进行
background_tasks.add_task(_execute_plan_bg, plan_id)
return {"message": "已开始执行"}

# 后台任务推送进度
await ws_manager.broadcast_all({"type": "plan_step_done", ...})
```

**AI 用例生成**同样采用后台任务模式：`POST /ai-cases/generate` 立即返回占位记录（`gen_status=generating`），后台生成完成后推送 `ai_gen_done` 事件，前端收到后刷新列表。彻底解决生成时间超过 axios 超时阈值时前端误报失败的问题。

压测场景每秒推送 TPS 指标，轮询会产生大量无效请求；用例执行需要逐条实时展示，轮询延迟不可接受。前端通过 `AbortController` 支持随时取消正在进行的 AI 生成任务。

---

## 十、鉴权与用户管理

**JWT 中间件鉴权**：所有 `/api/` 请求经 HTTP 中间件统一验证 Token，白名单（`/auth/login`、`/health`、静态资源）直接放行，其余返回 401。不修改每个路由，中间件一处覆盖全部。

**多账号支持**：`admin` 账号可在「用户管理」页新建/删除用户、重置密码；普通用户只能登录和修改自己的密码。密码用 bcrypt 哈希存储，Token 有效期 7 天。

```
用户登录 → 返回 JWT Token
前端 axios 请求拦截器自动附加 Authorization: Bearer xxx
401 响应 → 清除本地 Token → 跳转登录页
```

---

## 十一、插件化技能架构

```
skills/
  ├── test_case_pro_max/   ← 放进去就自动注册
  │   ├── SKILL.md         ← 描述、提示词配置
  │   └── scripts/run.py
  └── prompts/             ← 所有 LLM Prompt（YAML，无需改代码）
```

新增测试能力不修改主代码，扫描目录自动发现注册。Prompt 与代码解耦，调优 AI 效果只需编辑 YAML。

---

## 十二、数据库：向前兼容，零停机升级

SQLAlchemy ORM，启动时自动建表。新字段通过 `ALTER TABLE ... ADD COLUMN` 兼容旧库，列已存在则忽略，SQLite / PostgreSQL 均适用：

```python
# 直接拉代码 → 重启服务 → 旧数据库自动补列，数据完整保留
```

双数据库支持：本机开发用 SQLite（零配置），Docker 部署自动切换 PostgreSQL（多并发）。只需修改 `DATABASE_URL`，代码无需任何改动。

---

## 十三、前端工程化

**组件拆分**：接口测试主页面从 4044 行拆分，脚本函数 Dialog 抽为独立 `ScriptDialog.vue`，工具函数提取为 `useApiTestUtils.js` composable。

**单元测试**：覆盖四个核心模块，共 96 条测试：
- `param_resolver`：内置函数、变量替换、类型推断、自定义脚本（27 条）
- `api_executor`：断言逻辑、JSONPath、全部 match_type（27 条）
- 增量更新合并逻辑 + Prompt 加载器（12 条）
- `ai_case_generator` 核心纯逻辑（30 条）：截断 JSON 修复、控制字符转义、分段索引构建、关键词定位、增量合并五个函数全覆盖

**前端鉴权**：Pinia auth store 持久化 Token，路由守卫未登录跳 `/login`，axios 拦截器自动附加 Token，401 自动跳登录页。

---

## 二十、后端路由拆分：按功能域分包

原始 `api/routes.py` 随功能积累膨胀到 4300+ 行，所有域的路由混在一个文件里，定位困难、修改风险高。按功能域拆分为四个独立子模块：

```
api/routes/
├── __init__.py      # 汇总并导出合并 router，保持向后兼容
├── auth.py          # 鉴权与用户管理（/auth/*、/health、/logs）
├── webui.py         # WebUI 自动化（/tasks、/cases、/execute、/reports、/agent、/skills、/llm）
├── ai_cases.py      # AI 文档驱动用例（/ai-cases/*，含 diff-check、incremental-update）
└── api_test.py      # 接口自动化（/api-test/*、/global-vars、/test-plans）
```

**拆分原则**：零逻辑改动，纯文件搬家。路由定义、辅助函数、后台任务函数全部随所属域迁移，不修改任何业务逻辑。

**向后兼容**：`routes/__init__.py` 用 `include_router` 把四个子路由合并为一个 `router` 导出，`api/__init__.py` 和 `main.py` 的 `from api.routes import router` 无需改动。

**效果**：单文件从 4333 行缩减为 185～1188 行，各域独立演进互不影响，新增接口只需找到对应子文件修改。

---

## 十四、RAG 知识库：文档全文检索替代硬截断

AI 用例生成时面临一个矛盾：文档越长，信息越丰富，但单次 prompt 塞不下；简单截取前 N 字会遗漏后半部分的功能点。RAG 用分段检索解决这个问题：

```
文档入库（index_document）
  ↓ split_text：900字/段，200字重叠，段落优先
  ↓ get_embeddings：调 /v1/embeddings 获取向量（失败则 None）
  ↓ DocumentChunk 表写入（pgvector 存向量 / SQLite 存 None）

逐模块生成时（_call_llm_for_module）
  ↓ search_chunks(query=模块名+功能点, top_k=10)
  ↓ pgvector + 有向量 → 余弦相似度排序
  ↓ 无向量或 SQLite → 关键词 TF 匹配降级
  ↓ 检索到的相关段落（最多 8000 字）替代硬截断
```

**降级策略**：DeepSeek / Anthropic 不支持 `/v1/embeddings`，检测到后自动退到关键词匹配，不报错、不中断生成流程。真正有向量检索能力需接入 OpenAI / 智谱 / 阿里等支持 embedding 的模型。

**超大文档保护**：BeautifulSoup 深度清洗 HTML 噪音后，文档按 20000 字/段分批并行提取模块（Semaphore=5，全文覆盖无批次上限），全文分段索引每段 20000 字、重叠 2000 字，无全局硬截断，确保超长文档后半部分的功能模块不被遗漏。

---

## 十五、超大文档的三层稳定性保障

文档驱动用例生成面对超大文档（50 万字以上）时，容易出现 LLM 超时、批次无限累积、输出截断三类问题，平台针对性地设计了三个机制：

**批次上限防卡死**：模块提取阶段按 20000 字/批并行分段处理（Semaphore=5），覆盖全文无上限，各批次同时发出，结果合并去重（高相似度模块自动合并功能点）。

**超大文档无硬截断**：全文分段索引每段 20000 字、重叠 2000 字，逐模块生成时通过关键词打分精准定位对应段落，替代截取前 N 字的粗暴做法，确保后半部分功能点不被遗漏。

**截断 JSON 自动修复**：LLM 因 `max_tokens` 被截断时，输出的 JSON 末尾不完整。修复器逐字符扫描，找到最后一个完整闭合的顶层元素，截断到该位置并补齐缺失的 `}` / `]`，保留已生成的内容而不是整批丢弃。

**HTML 噪音深度清洗**：从 HTML 文件导出的需求文档会携带大量 CSS 选择器、JS 代码、样式声明。BeautifulSoup 先移除 `<script>` / `<style>` / `<noscript>` 等标签，再提取纯文本，可将 778543 字的 HTML 压缩到真实需求文本量级，避免噪音稀释 LLM 理解能力。

---

## 十六、WebUI 用例生成的三级兜底策略

页面元素爬取质量直接影响 WebUI 用例生成效果。针对不同场景设计了三级降级机制：

**第一级：正常元素分析**（页面元素 > 3 个）
分析交互元素，提取功能模块，并发调用 AI 逐模块生成含 selector 的可执行用例。

**第二级：文档驱动兜底**（页面元素 ≤ 3 个，或第一级 LLM 返回 0 条）
当页面爬取结果不足时，自动切换为纯文档驱动模式，基于上传的需求文档生成功能测试用例，不依赖页面结构。

**第三级：页面正文兜底**（无上传文档）
parse_page 时同步提取页面 body 正文（最多 5 万字），移除 script/style 噪音后作为 document_data 注入，即便没有上传文档也能有上下文可用。

配合**分屏自动滚动**（最多 40 屏，连续 2 步高度不变则停止），确保懒加载列表类页面的元素尽量被完整抓取，降低触发兜底策略的概率。

---

## 十七、中文 PDF 兼容：pymupdf 优先策略

PyPDF2 对部分中文 PDF 存在编码问题，提取出的文本为乱码，LLM 无法理解，导致返回空响应进而引发 JSON 解析失败。

改造方案：优先使用 **pymupdf（fitz）** 提取 PDF 文本，其直接读取字体 Unicode 映射，中文字符正确还原；pymupdf 不可用时降级到 PyPDF2。

```python
if _HAS_FITZ:
    # pymupdf — 正确处理中文 PDF（Unicode 直接提取）
    doc = _fitz.open(file_path)
    for page in doc:
        t = page.get_text() or ""
elif PdfReader is not None:
    # PyPDF2 降级（部分中文 PDF 可能乱码）
    ...
```

---

## 十八、Anthropic 代理兼容：防御性响应解析

直接对接 Anthropic 官方 API 时，响应格式固定；但通过第三方代理（如企业内网代理、中转网关）时，`content` 字段可能出现多种变体：

| 代理类型 | content 格式 | 原代码问题 |
| --- | --- | --- |
| 标准 Anthropic | `[{"type":"text","text":"..."}]` | 正常 |
| 部分代理 | text block 有 `type` 无 `text` 字段 | `KeyError: 'text'` |
| 部分代理 | `content` 直接是字符串 | `TypeError` |
| Claude 扩展思考 | content 含 `type=thinking` block | 取第一个 text block 之前卡死 |

改造后采用防御性解析：过滤 thinking block 只取 `type=text` 的 block，`block.get("text", "")` 取不到时依次尝试 `content`/`value`/`message` 备选字段，最终仍为空才抛出含完整响应的可读错误。

---

## 二十一、需求-用例追踪矩阵

用例生成后最难回答的问题是：**这批用例到底覆盖了需求里的哪些功能点？有没有漏掉？**

覆盖度分析（6 种测试方法、模块分布）只能回答「用例写得好不好」，无法回答「有没有漏测」。追踪矩阵从需求出发，建立双向映射关系，直接回答这个问题。

### 三步实现追踪

**Step 1：需求提取**

AI 从已保存的需求文档（`doc_content`）中提取结构化需求条目，每条需求代表一个可独立测试的功能行为：

```json
{ "id": "LOGIN-001", "module": "登录", "title": "手机号验证码登录",
  "description": "用户输入手机号和验证码，验证通过后跳转首页", "priority": "P0" }
```

ID 格式为 `模块缩写-序号`，在后续映射步骤中作为稳定引用键。

**Step 2：用例-需求映射（后验）**

AI 对每条已有用例判断它覆盖了哪些需求 ID，写入每条用例的 `req_refs` 字段：

```json
{ "case_id": "LOGIN-001", "req_refs": ["LOGIN-001", "LOGIN-002"] }
```

分批处理（每批 50 条），分批推进度，结果存入 `traceability_data`。

**Step 3：生成追踪矩阵**

`GET /ai-cases/{id}/traceability` 从 `requirements_data` + `traceability_data` + `cases_data` 三个来源实时计算：

```
需求覆盖状态：
  covered      — 有 ≥2 条用例关联（充分）
  insufficient — 仅有 1 条用例关联（不足）
  uncovered    — 无任何用例关联（漏测风险）

用例视角：
  orphan_cases — 未关联任何需求的用例（冗余/通用）
```

### 覆盖不足的处理：分析 + 补充

对覆盖不足的需求，提供两步操作：

1. **缺口分析**：AI 从 8 个测试维度（等价类、边界值、异常分支、权限控制、并发/重复、状态转换、数据完整性、恢复场景）逐一检查已有用例，找出未覆盖的维度，给出举例

2. **生成补充用例**：用户勾选要补充的维度，AI 针对性生成用例，追加到对应模块并自动更新 `traceability_data` 映射，矩阵实时刷新

### 数据设计

所有追踪数据存在 `AICaseFile` 的 JSON 列里，不新建表，向后兼容：

| 字段 | 存储内容 |
| --- | --- |
| `requirements_data` | `{extracted_at, requirements: [...]}` |
| `traceability_data` | `{mapped_at, mappings: [{case_id, req_refs}]}` |

全程后台任务 + WebSocket 推送，提取/映射/补充三个操作均不阻塞 HTTP 请求，前端进度条实时反馈。

---

## 十九、一句话总结

> 平台的设计主线是**把 AI 能力嵌入测试生命周期的每个环节**：用插件化架构保证可扩展，用 WebSocket 保证实时体验，用需求变更增量更新避免旧用例丢失，用废弃/禁用字段分离保证执行精度，用可配置网络层适配真实测试环境，用共享变量池打通接口链路，用统一 HTTP API 适配任意大模型，用 Prompt YAML 配置化支持无代码调优，用 JWT 鉴权支持多账号团队使用，用接口代码驱动消除文档依赖，用代码可行性分析在代码阶段提前暴露需求偏差，用 RAG 分段检索替代硬截断让超长文档也能被充分理解，用三层兜底策略保证 WebUI 用例在各种页面条件下都能生成，用 pymupdf 优先策略修复中文 PDF 乱码，用截断 JSON 修复机制保留 LLM 已生成的内容，用防御性 API 解析兼容各类第三方代理，用路由按域分包降低单文件复杂度，用需求追踪矩阵回答「有没有漏测」，用心跳保活和轮询兜底提升 WebSocket 稳定性，用启动时密钥检测降低生产安全风险——整体目标是让测试工程师从重复劳动中解放出来，专注于测试策略和质量判断。

---

## 二十二、WebSocket 稳定性：心跳保活 + 断线兜底

所有耗时任务（用例生成、需求提取、映射）依赖 WebSocket 推送完成通知，但代理/浏览器通常在 60 秒无消息后断开连接，导致后台任务明明跑完了，前端却永远收不到通知，按钮一直转圈。

**心跳保活**：服务端每 30 秒向所有连接推 `{"type":"ping"}`，客户端收到后立即回 `{"type":"pong"}`，同时更新存活时间戳。超过 40 秒未收到 pong 的连接视为断开，主动清理，避免僵尸连接积累。

**断线兜底**：后台任务的结果写入数据库（`gen_status=done`、`requirements_data`、`traceability_data`），不只依赖 WebSocket 推送。前端有两层兜底：
- **生成列表兜底**：加载列表时发现有 `gen_status=generating` 的记录，每 5 秒轮询一次，状态变化时更新展示并提示用户
- **追踪任务兜底**：点「提取需求」/「建立映射」后同时启动轮询（首次 30 秒后开始，之后每 10 秒），WebSocket 断线时从数据库恢复状态

两者相互补充：心跳减少断线概率，轮询保证断线后结果不丢失。

---

## 二十三、生产安全：启动时密钥检测

项目内置三个默认值方便本地开发，但直接用于生产环境会有安全风险：

| 配置项 | 默认值 | 风险 |
| --- | --- | --- |
| `SECRET_KEY` | `ai-test-agent-secret-key...` | JWT Token 可被伪造，任意账号登录 |
| 管理员密码 | `admin123` | 弱密码，暴力破解风险 |
| 数据库密码 | `uitest123456` | 弱密码，数据库裸奔 |

启动时（`lifespan`）逐项检测，发现默认值则打印醒目 WARNING，并给出修改命令。不强制阻止启动（开发环境需要默认值），但生产部署时日志里会有清晰提示，不会悄悄放过。

---

## 附：技术选型

| 问题 | 选型 | 原因 |
| --- | --- | --- |
| 异步 HTTP 服务 | FastAPI + Uvicorn | 原生 async/await，自动生成 API 文档 |
| 数据库 | SQLite / PostgreSQL | 零配置适合开发，PG 适合生产；ORM 层无缝切换 |
| 浏览器自动化 | Playwright | 多浏览器，async API，networkidle + 分屏滚动适合 SPA 和懒加载页面 |
| 接口执行 | httpx | 原生异步，支持自定义 Transport（Hosts 映射依赖） |
| 实时通信 | WebSocket | 服务端主动推送，拒绝轮询 |
| 前端框架 | Vue 3 + Element Plus | 组件成熟，适合工具类产品 |
| AI 调用 | 统一 HTTP API | 支持任意模型，一键切换，不依赖本机 CLI |
| 鉴权 | JWT + bcrypt | python-jose 签发，中间件统一验证，密码安全存储 |
| Prompt 管理 | YAML + prompt_loader | 与代码解耦，修改无需重启 |
| 状态管理 | Pinia | 比 Vuex 更轻，支持 Token 持久化 |
| PDF 解析 | pymupdf 优先 / PyPDF2 降级 | pymupdf 正确处理中文字体映射，PyPDF2 作为兜底 |
| HTML 清洗 | BeautifulSoup4 | 精准移除 CSS/JS 噪音，提取主内容区域 |
