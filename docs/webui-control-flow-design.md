# WebUI 用例控制流设计文档（if/while/for/try/goto）

> 目标：让 WebUI 自动化用例从「线性逐步执行」升级为支持条件判断、循环轮询、异常兜底、显式跳转的执行模型，同时保持与现有录制、AI 生成、步骤编辑器、pytest 导出的兼容。

---

## 1. 背景与现状

当前执行引擎 [skills/action_runner.py](../skills/action_runner.py) 的 `run_case` 是一个线性 `for` 循环，按 `TestCase.steps_json` 里的 `ActionStep` 列表顺序执行：

- 控制「失败是否中断」只有 `optional` 一个字段；
- 断言类 `assert_*` 失败即终止整条用例；
- 没有分支、循环、异常处理、显式跳转语义。

`ActionStep` 数据结构见 [tools/action_schema.py](../tools/action_schema.py)，核心字段：

```json
{
  "id": "s001", "action": "click", "selector": "button[type=submit]",
  "value": "", "url": "", "expected": "", "description": "",
  "timeout": 30000, "optional": false, "frame_selectors": []
}
```

---

## 2. 核心思路：三套表达，一套执行

我们有三类表达控制流的方式，历史上容易做成三套不兼容的实现。本设计用「一个统一 IR + 一个持久化格式」把它们收敛到一起：

| 表达方式 | 定位 | 存储形式 | 执行形式 |
|---|---|---|---|
| **A. 扁平控制流 action** | 现有 `steps_json` 的天然扩展 | 直接存扁平数组 | 加载时转成树执行 |
| **B. 嵌套步骤树** | 编辑器/高级用户的可视化结构 | `flatten` 后存扁平数组 | 树直接执行（规范化后） |
| **C. 脚本步骤** | 复杂逻辑兜底（自定义条件/迭代/数据准备） | 存为 `python` 叶子 action 或 `script:` 条件 | 受限沙箱执行 |

**统一执行模型（IR）= 嵌套步骤树**。三种写法最终都编译到这棵树，由同一个执行引擎遍历执行。

**统一持久化格式 = 扁平 `steps_json` 数组**。因为它是现有 `TestCase.steps_json` 字段，向前向后都兼容，旧数据无需迁移。

三者关系一句话：**B（树）是唯一执行 IR，A（扁平）是树的序列化存储，C（脚本）是树的叶子节点与表达式兜底。**

```
任何来源（录制 / AI / 编辑器 / 脚本）
        │
        ▼
  扁平 steps_json 存储          ←—— A 直接写、B flatten 后写、C 作为叶子写
        │  unflatten()
        ▼
  嵌套步骤树（执行 IR）          ←—— 执行引擎遍历
        │  flatten()
        ▼
  扁平 steps_json 持久化 / 导出
```

---

## 3. 统一 IR：嵌套步骤树

### 3.1 节点类型

```
Node
├── StepNode（叶子）：一个普通 ActionStep，另增 label / script 字段
└── ControlNode（容器）：控制流块
      ├── type: "if" | "while" | "for" | "try"
      ├── condition（可选，if/while/for 需要）
      ├── branches / children：子节点列表
      └── 附加参数：max_iter / delay_ms
```

### 3.2 规范化 JSON 示例（树形式）

```json
{
  "type": "root",
  "children": [
    {"type": "step", "step": {"id": "s1", "action": "navigate", "url": "{{base}}/login"}},

    {"type": "if", "condition": "visible(button[type=submit])",
     "then": [
       {"type": "step", "step": {"id": "s3", "action": "click", "selector": "button[type=submit]"}}
     ],
     "else": [
       {"type": "step", "step": {"id": "s5", "action": "click", "selector": "a.retry"}}
     ]},

    {"type": "while", "condition": "not exists(.result-loaded)", "max_iter": 10, "delay_ms": 1000,
     "body": [
       {"type": "step", "step": {"id": "s9", "action": "wait", "value": "1000"}}
     ]},

    {"type": "try",
     "body": [
       {"type": "step", "step": {"id": "s12", "action": "click", "selector": ".optional-btn"}}
     ],
     "except": [
       {"type": "step", "step": {"id": "s14", "action": "screenshot", "value": "fallback.png"}}
     ]}
  ]
}
```

---

## 4. 持久化格式：扁平 steps_json（方案 A 的落地形态）

树结构需要序列化进现有 `steps_json` 数组。用「块关键字 + 配对标签」表达嵌套，通过栈可无损还原为树。

### 4.1 新增控制流 action

在 `ACTION_TYPES` / `validate_step` 的合法集合中新增：

```
if, elseif, else, endif,
while, endwhile,
for, endfor, break, continue,
try, except, endtry,
goto, label
```

### 4.2 新增字段

| 字段 | 类型 | 用于 | 说明 |
|---|---|---|---|
| `condition` | str | if/elseif/while/for | 条件表达式（声明式 DSL 或 `script:` 前缀） |
| `target` | str | goto | 目标 `step.id` 或 `label` |
| `label` | str | 任意步骤 | 跳转锚点，可多个步骤同名 |
| `max_iter` | int | while/for | 循环次数上限，防死循环，默认 100 |
| `delay_ms` | int | while | 每次循环结束后的等待毫秒 |
| `script` | str | python action / script 条件 | 沙箱脚本片段 |

### 4.3 扁平示例（与 3.2 树等价）

```json
[
  {"id":"s1","action":"navigate","url":"{{base}}/login"},

  {"id":"s2","action":"if","condition":"visible(button[type=submit])"},
  {"id":"s3","action":"click","selector":"button[type=submit]"},
  {"id":"s4","action":"else"},
  {"id":"s5","action":"click","selector":"a.retry"},
  {"id":"s6","action":"endif"},

  {"id":"s7","action":"while","condition":"not exists(.result-loaded)","max_iter":10,"delay_ms":1000},
  {"id":"s8","action":"wait","value":"1000"},
  {"id":"s9","action":"endwhile"},

  {"id":"s10","action":"try"},
  {"id":"s11","action":"click","selector":".optional-btn"},
  {"id":"s12","action":"except"},
  {"id":"s13","action":"screenshot","value":"fallback.png"},
  {"id":"s14","action":"endtry"},

  {"id":"s15","action":"goto","target":"s20"},
  {"id":"s20","action":"navigate","url":"{{base}}/home"}
]
```

### 4.4 扁平 ↔ 树 转换

- `unflatten(flat_steps) -> tree`：用栈扫描，`if/while/for/try` 压栈，`else/except` 切换分支，`endif/endwhile/endfor/endtry` 出栈；遇到未配对的块关键字直接报「控制流块不配对」，不进入执行。
- `flatten(tree) -> flat_steps`：递归先序遍历，输出 `if` 关键字 + 子块 + `else` + 子块 + `endif` 等。

这两个函数是 A/B 兼容的关键，需做成纯函数并单测覆盖。

---

## 5. 条件表达式（两档）

### 5.1 声明式 DSL（默认，安全）

用 Python `ast` 白名单解析，禁止 `eval`。支持的原子与运算符：

- 元素查询：`exists(sel)`、`visible(sel)`、`hidden(sel)`、`count(sel)`、`text(sel)`
- 页面：`url`、`title`
- 比较：`==`、`!=`、`contains`
- 逻辑：`and`、`or`、`not`、括号
- 变量：`{{key}}` 先替换为环境变量值再比较

示例：

```
visible(button[type=submit])
not exists(.result-loaded)
count(.todo-item) > 0 and text(.status) contains "成功"
url == "{{base}}/home"
```

### 5.2 脚本表达式（方案 C 兜底）

当声明式 DSL 表达不了复杂逻辑时，用 `script:` 前缀走沙箱脚本，返回值必须为布尔：

```
script: return page.visible('button[type=submit]') and len(page.query_all('.todo')) > 0
```

脚本运行环境见 §7。

---

## 6. 执行引擎改造

改造对象：[skills/action_runner.py](../skills/action_runner.py) 的 `run_case` / `_run_step`。

### 6.1 执行流程

```
load steps_json
  → unflatten 成树（含配对校验）
  → 执行树（递归 / 显式栈遍历，等价于指令指针）
  → 保留每步的 _run_step 结果
  → 汇总 case_result
```

### 6.2 控制流语义

| 块 | 进入条件 | 失败/异常行为 |
|---|---|---|
| `if` | 求值 `condition` | 真→`then`，假→`else`（有 `elseif` 依次判断） |
| `while` | 循环前先求值 | 真→执行 body，`continue` 回条件，`break` 跳出；`max_iter` 到上限且条件仍真→记 `error` 并失败 |
| `for` | 求值迭代器 | 按迭代序列执行 body；`break/continue` 同上 |
| `try` | 无条件进 body | body 任一步非 `optional` 失败→跳到 `except` 分支继续；`except` 正常执行完毕后用例按「已兜底」处理 |
| `goto` | 无条件跳 `target` | 目标不存在→报配置错误并失败 |
| `label` | 不执行，仅锚点 | — |

### 6.3 需要保留的既有能力

- `optional=True` 步骤失败不中断（在块内同样生效）；
- 外部 `should_stop_cb` 停止信号（每步前检查，且要能跳出循环块）；
- 失败自动截图、多候选 selector 回退、strict mode 降级、AI selector 修复、iframe `frame_locator`；
- `max_iter` 防死循环、单次用例总步骤上限（防止 goto 成环）。

### 6.4 变量上下文

新增一个 `run_context`（dict），随执行流动：

- `load_env_vars` 加载的 `env_vars` 作为初始值；
- 脚本步骤可读写 `run_context`；
- 条件表达式中的 `{{key}}` 从 `run_context` 解析；
- 后续 `for` 迭代变量也存这里（`for item in items` 中 `item` 可被 body 内步骤引用）。

---

## 7. 脚本沙箱（方案 C）

新增 `python` action 与 `script:` 条件共用一套受限执行器。

### 7.1 能力（白名单）

脚本内可访问：

- `page`：只读页面查询（`visible(sel)`、`text(sel)`、`count(sel)`、`query_all(sel)`、`url`、`title`）；
- `ctx`：读写变量上下文（`ctx.get(key)`、`ctx.set(key, value)`）；
- 内置函数：`sleep_ms`、`log`；
- 纯 Python 运算、控制流、列表/字典操作。

### 7.2 限制

- 禁止 `import`、文件/网络访问、`eval/exec`、反射危险属性；
- 单步脚本超时（如 5s）、代码长度上限；
- 用 `ast` 白名单节点 + 受限内置函数字典实现，不引入重型沙箱依赖；若后续需要更强隔离再评估 `restrictedpython`。

### 7.3 与已有 `evaluate` 的关系

- 已有 `evaluate`（JS，浏览器内执行）保留，用于页面内计算；
- 新增 `python`（服务端沙箱）用于控制测试流程/变量，两者不冲突。

---

## 8. 前端编辑器（Cases.vue）

- 读入用例时 `unflatten` 成树，按缩进渲染控制流层级；
- 提供「插入 if / while / for / try / goto」入口，自动补全块关键字和配对；
- `condition` 输入框带语法高亮与实时校验；
- 保存时 `flatten` 回扁平 `steps_json`，保证与后端存储格式一致；
- 普通步骤仍走现有 `saveSteps` 的 `frame_selectors` 清理逻辑。

---

## 9. pytest 导出器

[skills/pytest_exporter.py](../skills/pytest_exporter.py) 导出时，把树结构映射为 Python 原生语句：

```
if visible(button[type=submit]):      # → if ...
while not exists(.result-loaded):     # → while ...
for item in items:                    # → for ...
try: ... except: ...                  # → try/except
```

导出前同样先 `unflatten`，保证导出结果与执行语义一致。

---

## 10. AI 生成

- 在 case 生成 prompt 中说明支持的控制流关键字与 `condition` DSL，允许 AI 输出 `if/while/try/goto`；
- 生成结果仍走 `parse_steps_to_json` → 扁平 `steps_json`；
- 首期可不强制 AI 生成控制流，等引擎+编辑器稳定后再放开。

---

## 11. 兼容与迁移

- 旧 `steps_json` 无任何控制流关键字 → `unflatten` 得到单层 root，行为与现在完全一致，**零迁移**；
- 新增字段均为可选，旧数据不加载也不会报错；
- `validate_step` 新增控制流 action 到合法集合，避免「未知 action」误报。

---

## 12. 分阶段落地计划

| 阶段 | 内容 | 交付 |
|---|---|---|
| P0 | `action_schema` 扩展字段 + 控制流 action 合法集 | 数据模型就绪 |
| P0 | `unflatten` / `flatten` 纯函数 + 单测 | A↔B 无损转换 |
| P1 | 执行引擎树遍历 + if/while/goto 语义 | 核心控制流可执行 |
| P1 | 条件表达式 DSL（ast 白名单求值器） | 声明式条件 |
| P2 | try/for + `max_iter`/`break/continue` | 异常兜底与迭代 |
| P2 | 脚本沙箱 `python` action + `script:` 条件 | 方案 C 兜底 |
| P3 | 前端编辑器嵌套渲染 + 控制流插入入口 | 可视化编辑 |
| P3 | pytest 导出器控制流映射 | 导出一致 |
| P4 | AI 生成控制流 + 文档同步 | 智能化增强 |

---

## 13. 风险与边界

- **goto 成环 / 死循环**：`max_iter` + 用例总步骤上限双保险；
- **脚本安全**：默认只读页面 + 变量上下文，禁止 IO/import；上线前做安全评审；
- **兼容性**：所有新字段可选，旧数据零迁移，先跑单测再放开前端；
- **复杂度**：控制流会让「步骤级报告」从线性列表变成树，报告展示需保留「扁平展开 + 缩进」两态，避免执行记录丢失上下文。
