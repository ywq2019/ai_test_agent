# WebUI 用例步骤编辑操作手册

> 适用版本：P2 及以上（可视化步骤编辑器 + AI 场景规划联动）

---

## 目录

1. [步骤编辑器入口](#1-步骤编辑器入口)
2. [步骤结构总览](#2-步骤结构总览)
3. [Action 类型详解](#3-action-类型详解)
4. [Selector 编写指南](#4-selector-编写指南)
5. [Value 填写规则](#5-value-填写规则)
6. [Expected 断言写法](#6-expected-断言写法)
7. [Selector 稳定性评级（A/B/C/D）](#7-selector-稳定性评级abcd)
8. [元素别名库（@ 触发补全）](#8-元素别名库--触发补全)
9. [变量替换语法](#9-变量替换语法)
10. [frame 内元素操作](#10-frame-内元素操作)
11. [步骤编辑实战示例](#11-步骤编辑实战示例)
12. [控制流（if / else / while）](#12-控制流if--else--while)
13. [常见问题 FAQ](#13-常见问题-faq)

---

## 1. 步骤编辑器入口

1. 进入 **用例管理** 页面（菜单 → 用例管理）
2. 选择要编辑的任务
3. 点击任意用例行的 **编辑** 按钮
4. 弹窗切换到 **步骤编辑器** Tab

> 录制后点击「保存」，系统会自动对步骤进行 AI 健壮化处理（推导多候选 selector、插入 wait/assert），保存完成后再进入编辑器即可看到完整的健壮化结果。

---

## 2. 步骤结构总览

每条步骤包含以下字段：

| 字段 | 说明 | 必填 |
|------|------|------|
| `action` | 操作类型，如 `click`、`fill`、`assert_text` | ✅ |
| `selector` | 定位目标元素的 CSS/XPath/Locator | 视 action 而定 |
| `value` | 操作值，如填写内容、按键名、JS 表达式 | 视 action 而定 |
| `url` | navigate / wait_for_url 时的目标 URL | 视 action 而定 |
| `expected` | 断言类 action 的期望值 | 视 action 而定 |
| `description` | 步骤描述（展示在报告里） | 建议填写 |
| `timeout` | 超时毫秒，默认 30000（30秒） | 否 |
| `optional` | `true` = 失败不中断整条用例 | 否 |

---

## 3. Action 类型详解

### 3.1 导航类

| action | 必填字段 | 说明 | 示例 |
|--------|---------|------|------|
| `navigate` | `url` | 打开页面 | `url: https://example.com/login` |
| `wait_for` | `selector` 或 `url` | 等待元素出现 / URL 匹配 | `selector: .main-content` |

```
# navigate 示例
action:   navigate
url:      https://example.com/login
description: 打开登录页

# wait_for 等待元素
action:   wait_for
selector: [data-testid="dashboard"]
description: 等待仪表盘加载完成

# wait_for 等待 URL
action:   wait_for
url:      /dashboard
description: 等待跳转到首页
```

### 3.2 点击类

| action | 必填字段 | 说明 |
|--------|---------|------|
| `click` | `selector` | 鼠标单击 |
| `dblclick` | `selector` | 鼠标双击 |
| `rightclick` | `selector` | 鼠标右键 |
| `hover` | `selector` | 鼠标悬停（不点击） |

```
# click 示例
action:   click
selector: [data-testid="login-btn"]
description: 点击登录按钮

# hover 示例（触发下拉菜单）
action:   hover
selector: .nav-dropdown
description: 悬停触发下拉菜单
```

### 3.3 输入类

| action | 必填字段 | 可选字段 | 说明 |
|--------|---------|---------|------|
| `fill` | `selector`, `value` | — | 清空后填写（推荐） |
| `type` | `selector`, `value` | — | 逐字符输入（触发键盘事件，适合自动补全） |
| `select` | `selector`, `value` | — | 下拉框选择 |
| `check` | `selector` | — | 勾选 checkbox |
| `uncheck` | `selector` | — | 取消勾选 checkbox |
| `press` | `value` | — | 键盘按键 |
| `upload` | `selector`, `value` | — | 上传文件 |

```
# fill 示例
action:   fill
selector: [name="username"]
value:    admin
description: 填写用户名

# select 下拉框（用选项 value）
action:   select
selector: #role-select
value:    manager
description: 选择角色为管理员

# select 下拉框（用选项文本）
action:   select
selector: [name="city"]
value:    北京
description: 选择城市

# press 键盘事件
action:   press
value:    Enter
description: 回车提交

# press 组合键
action:   press
value:    Control+a
description: 全选

# upload 文件上传
action:   upload
selector: input[type="file"]
value:    /data/test_files/avatar.jpg
description: 上传头像
```

**常用按键名列表（`press` value 值）：**

| 按键 | value 值 |
|------|---------|
| 回车 | `Enter` |
| Tab | `Tab` |
| 退格 | `Backspace` |
| Escape | `Escape` |
| 上/下/左/右箭头 | `ArrowUp` / `ArrowDown` / `ArrowLeft` / `ArrowRight` |
| Delete | `Delete` |
| 全选 | `Control+a`（Windows）/ `Meta+a`（Mac） |
| 复制 | `Control+c` |

### 3.4 滚动与截图

| action | 字段 | 说明 |
|--------|------|------|
| `scroll` | `selector`（可空） | 将元素滚动到可视区域 |
| `screenshot` | `value`（可空） | 截图检查点，文件名自动命名 |

### 3.5 断言类

| action | 必填字段 | 说明 |
|--------|---------|------|
| `assert_text` | `selector`, `expected` | 断言元素文本内容 |
| `assert_visible` | `selector` | 断言元素可见 |
| `assert_hidden` | `selector` | 断言元素不可见 |
| `assert_url` | `expected` | 断言当前页面 URL |
| `assert_title` | `expected` | 断言页面标题 |
| `assert_count` | `selector`, `expected` | 断言元素数量 |

### 3.6 高级操作

| action | 字段 | 说明 |
|--------|------|------|
| `evaluate` | `value` | 执行 JavaScript 表达式 |

```
# 执行 JS 清除 localStorage
action:   evaluate
value:    window.localStorage.clear()
description: 清除本地缓存

# 执行 JS 修改 DOM
action:   evaluate
value:    document.querySelector('.overlay').remove()
description: 移除遮罩层
```

---

## 4. Selector 编写指南

### 4.1 推荐写法（按稳定性从高到低）

#### ✅ A 级：语义锚定（最稳定，首选）

优先使用专为测试设计的属性，不受样式重构影响。

```css
/* data-testid（最推荐，需前端配合添加） */
[data-testid="login-btn"]
[data-testid="submit-form"]

/* aria-label（无障碍语义，稳定） */
[aria-label="关闭"]
[aria-label="提交按钮"]

/* name 属性（表单元素） */
[name="username"]
[name="password"]
[name="remember"]

/* placeholder 属性 */
[placeholder="请输入手机号"]
[placeholder="搜索..."]

/* role 属性 */
[role="button"]
[role="dialog"]
[role="alertdialog"]

/* Playwright 内置 Locator（推荐） */
getByRole('button', { name: '提交' })
getByLabel('用户名')
getByPlaceholder('请输入密码')
getByTestId('submit-btn')
```

#### ✅ B 级：内容/行为语义（较稳定）

```css
/* has-text 文本匹配（Playwright 语法） */
button:has-text("登录")
.btn:has-text("确认删除")
li:has-text("订单管理")

/* type 属性 */
input[type="submit"]
input[type="checkbox"]

/* aria-* 系列 */
[aria-expanded="true"]
[aria-selected="true"]

/* nth-child（位置相对固定时） */
.menu-item:nth-child(2)
```

#### ⚠️ C 级：class / id（样式重构风险）

```css
/* 语义化 class（尚可接受） */
.login-btn
.submit-button
#login-form

/* 复合选择器（提高定位精度） */
.form-group input[type="text"]
.card-header .title
```

#### ❌ D 级：不稳定，应避免（系统自动标红）

```css
/* 纯 tag name — 极不稳定 */
button
input
div

/* 动态 id（含大量数字或哈希） */
#btn-1234567
#el-input-8f3a9b

/* CSS Module 哈希 class */
.LoginButton--abc12
._container_x9k3z

/* Vue scoped hash */
.title[data-v-3f1a9c]
```

### 4.2 XPath 写法

XPath 用于 CSS 无法表达的情况（如按文本查找父元素）：

```xpath
# 按文本内容
//button[text()="提交"]
//button[contains(text(),"登录")]

# 按属性
//input[@name="username"]
//div[@data-testid="modal"]

# 按父子关系
//label[contains(text(),"用户名")]/following-sibling::input
//td[contains(text(),"张三")]/preceding-sibling::td[1]

# 按位置
(//table//tr)[2]/td[3]
```

### 4.3 如何查找正确的 Selector

**方法一：浏览器开发者工具**
1. 打开 DevTools（F12）→ 点击 Elements 面板左上角的「选择器」图标
2. 在页面点击目标元素
3. 右键 HTML 元素 → Copy → `Copy selector` 或 `Copy XPath`
4. ⚠️ 直接复制的 selector 通常是 C/D 级，建议手动优化

**方法二：录制后查看健壮化结果**
1. 先录制操作，点击「保存」
2. 进入步骤编辑器，查看每条步骤左侧的稳定性评级（A/B/C/D）
3. 点击 selector 胶囊，展开备选 selector 列表
4. 选择评级更高的备选项

**方法三：Playwright Inspector**
```bash
# 本地调试时使用
PWDEBUG=1 playwright python your_script.py
```
在打开的 Inspector 界面，点击元素可以看到 Playwright 推荐的 locator 写法。

**方法四：使用 @ 触发别名补全**（见第8章）

---

## 5. Value 填写规则

### 5.1 fill / type — 输入内容

```
# 普通文本
value: admin123

# 含特殊字符（直接写，无需转义）
value: user@example.com
value: P@ssw0rd!

# 使用变量（见第9章）
value: {{username}}
value: {{base_url}}/api/test
```

### 5.2 select — 下拉框选项

```
# 用选项的 value 属性
value: manager

# 用选项的显示文本
value: 管理员

# 用选项的索引（第2个，从0开始）
value: 1
```

### 5.3 press — 按键名

```
value: Enter
value: Tab
value: Escape
value: ArrowDown
value: Control+a
value: Meta+z
```

### 5.4 evaluate — JavaScript 表达式

```javascript
// 返回值会被忽略（仅执行副作用）
window.localStorage.clear()
document.querySelector('.modal').style.display = 'none'

// 需要返回值（供 assert 使用）
document.title
document.querySelector('h1').textContent
```

### 5.5 screenshot — 文件名

```
# 留空：自动命名（step_001.png）
value:

# 指定文件名（不含路径，自动存到截图目录）
value: login-success.png
value: after-submit.png
```

### 5.6 upload — 文件路径

```
# 容器内绝对路径（Docker 部署）
value: /data/uploads/test_avatar.jpg

# 支持多文件（用英文逗号分隔）
value: /data/uploads/file1.pdf,/data/uploads/file2.pdf
```

---

## 6. Expected 断言写法

### 6.1 assert_text — 断言文本

```
# 精确匹配
expected: 登录成功

# 部分匹配（用正则）
expected: /登录成功|Login Success/

# 忽略大小写（正则）
expected: /welcome/i

# 多行文本中包含某段（正则）
expected: /订单号：\d+/
```

### 6.2 assert_url — 断言 URL

```
# 精确匹配
expected: https://example.com/dashboard

# 部分匹配（glob 语法，* 通配符）
expected: **/dashboard**

# 包含路径片段（正则）
expected: /\/dashboard$/

# 包含查询参数
expected: **/orders?status=paid**
```

### 6.3 assert_title — 断言页面标题

```
# 精确匹配
expected: 首页 - 管理后台

# 正则
expected: /管理后台/
```

### 6.4 assert_count — 断言元素数量

```
# 期望有 5 个列表项
selector: .list-item
expected: 5

# 期望没有错误提示
selector: .error-msg
expected: 0
```

### 6.5 断言步骤的 optional 标记

健壮化后系统自动插入的断言步骤会被标记为 `optional: true`，表示断言失败不中断用例，仅记录警告。

手动添加的核心断言（如登录成功验证）应设置 `optional: false`（默认）。

---

## 7. Selector 稳定性评级（A/B/C/D）

步骤编辑器每行显示稳定性评级标签，含义如下：

| 等级 | 含义 | 典型 selector |
|------|------|--------------|
| **A** 🟢 | 语义锚定，重构不影响 | `[data-testid=...]`, `[name=...]`, `[aria-label=...]`, `getByRole(...)` |
| **B** 🟡 | 内容/行为语义，较稳定 | `button:has-text("提交")`, `[type="submit"]`, `:nth-child(n)` |
| **C** 🟠 | 样式类/静态 id，有重构风险 | `.submit-btn`, `#login-form`, `input.form-control` |
| **D** 🔴 | 动态/哈希，极不稳定 | `#el-input-123456`, `.btn_abc12`, `div > div > button` |

**D 级处理建议：**
1. 点击 selector 胶囊，查看备选列表
2. 从列表中选择评级更高的备选
3. 或手动输入更稳定的 selector（@ 触发别名补全）
4. 使用 `getByRole` / `getByLabel` 等 Playwright 内置 locator

---

## 8. 元素别名库（@ 触发补全）

元素别名是将常用元素的 selector 命名为易记的别名，避免每次手写。

### 8.1 管理别名

1. 选择任务后，点击 **更多操作 → 元素别名库**
2. 点击「新建别名」
3. 填写别名名称和对应 selector，保存

```
别名名称: login-btn
selector: [data-testid="login-submit"]

别名名称: username-input
selector: [name="username"]

别名名称: success-toast
selector: .el-message--success
```

### 8.2 使用别名

在步骤编辑器的 selector 输入框中输入 `@` 即触发补全下拉，选择对应别名即自动填入 selector。

```
# 输入 @log 会出现
@login-btn  →  [data-testid="login-submit"]

# 输入 @user 会出现
@username-input  →  [name="username"]
```

### 8.3 别名命名规范

- 使用小写 + 连字符：`submit-btn`, `error-msg`
- 按功能命名，而非样式：❌ `blue-button`，✅ `save-button`
- 包含所在页面前缀（多页面共用时）：`login-username`, `register-username`

---

## 9. 变量替换语法

`value`、`url`、`expected` 等字段支持 `{{变量名}}` 语法，执行时从任务的**环境变量**表中读取替换值。

### 9.1 配置环境变量

1. 选择任务后，点击 **更多操作 → 环境变量**
2. 新增变量，填写 key 和 value

```
key: base_url    value: https://test.example.com
key: username    value: test_user
key: password    value: Test@123456
key: admin_token value: Bearer eyJhbGci...
```

### 9.2 在步骤中引用变量

```
# navigate 使用变量 URL
action:   navigate
url:      {{base_url}}/login

# fill 使用变量
action:   fill
selector: [name="username"]
value:    {{username}}

action:   fill
selector: [name="password"]
value:    {{password}}

# assert_url 使用变量
action:   assert_url
expected: {{base_url}}/dashboard

# 拼接变量
action:   navigate
url:      {{base_url}}/users/{{user_id}}/profile
```

### 9.3 注意事项

- 变量区分大小写：`{{Username}}` ≠ `{{username}}`
- 找不到变量时，原样保留 `{{变量名}}` 字符串（不会报错，但操作可能失败）
- 变量值中含特殊字符时无需转义，原样替换

---

## 10. frame 内元素操作

当目标元素在 `<iframe>` 内时，需要指定 `frame_selectors` 定位 frame。

```json
{
  "action": "fill",
  "selector": "[name='email']",
  "value": "user@example.com",
  "frame_selectors": ["iframe#payment-frame"],
  "description": "在支付 iframe 内填写邮箱"
}
```

`frame_selectors` 是一个数组，支持嵌套 frame：

```json
"frame_selectors": ["iframe.outer-frame", "iframe#inner-content"]
```

> ⚠️ 当前步骤编辑器 UI 暂不支持直接编辑 `frame_selectors`，需通过录制自动生成（录制器会自动识别 iframe 并记录）。

---

## 11. 步骤编辑实战示例

### 示例一：登录流程

```
步骤 1
  action:      navigate
  url:         {{base_url}}/login
  description: 打开登录页

步骤 2
  action:      fill
  selector:    [name="username"]
  value:       {{username}}
  description: 填写用户名

步骤 3
  action:      fill
  selector:    [name="password"]
  value:       {{password}}
  description: 填写密码

步骤 4
  action:      click
  selector:    [data-testid="login-submit"]
  description: 点击登录按钮

步骤 5（健壮化自动插入）
  action:      wait_for
  selector:    [data-testid="dashboard"]
  optional:    true
  description: 等待跳转到仪表盘

步骤 6
  action:      assert_url
  expected:    **/dashboard**
  description: 验证已成功登录（URL 跳转）

步骤 7
  action:      assert_visible
  selector:    [data-testid="user-avatar"]
  description: 验证用户头像可见（已登录态）
```

### 示例二：表单提交（含输入验证）

```
步骤 1
  action:      click
  selector:    [data-testid="add-user-btn"]
  description: 点击新建用户

步骤 2
  action:      wait_for
  selector:    [role="dialog"]
  description: 等待弹窗出现

步骤 3
  action:      fill
  selector:    [placeholder="请输入用户名"]
  value:       test_user_001
  description: 填写用户名

步骤 4
  action:      fill
  selector:    [name="email"]
  value:       test@example.com
  description: 填写邮箱

步骤 5
  action:      select
  selector:    [name="role"]
  value:       admin
  description: 选择角色为管理员

步骤 6
  action:      click
  selector:    button:has-text("确认")
  description: 点击确认提交

步骤 7
  action:      assert_visible
  selector:    .el-message--success
  description: 验证成功提示出现

步骤 8
  action:      assert_text
  selector:    [data-testid="user-list"] td:has-text("test_user_001")
  expected:    test_user_001
  description: 验证新用户出现在列表
```

### 示例三：搜索与筛选

```
步骤 1
  action:      fill
  selector:    [placeholder="搜索..."]
  value:       张三
  description: 输入搜索关键词

步骤 2
  action:      press
  value:       Enter
  description: 回车触发搜索

步骤 3
  action:      wait_for
  selector:    .search-result
  description: 等待搜索结果加载

步骤 4
  action:      assert_count
  selector:    .result-item
  expected:    3
  description: 验证搜索结果为 3 条

步骤 5
  action:      assert_text
  selector:    .result-item:first-child .name
  expected:    张三
  description: 验证第一条结果是张三
```

### 示例四：文件上传

```
步骤 1
  action:      click
  selector:    [data-testid="upload-zone"]
  description: 点击上传区域

步骤 2
  action:      upload
  selector:    input[type="file"]
  value:       /data/uploads/test_document.pdf
  description: 选择要上传的 PDF 文件

步骤 3
  action:      wait_for
  selector:    [data-testid="upload-success-icon"]
  description: 等待上传完成

步骤 4
  action:      assert_visible
  selector:    .uploaded-file-name
  description: 验证文件名显示在列表
```

### 示例五：断言验证登录失败

```
步骤 1
  action:      fill
  selector:    [name="username"]
  value:       wrong_user
  description: 填写错误用户名

步骤 2
  action:      fill
  selector:    [name="password"]
  value:       wrong_pass
  description: 填写错误密码

步骤 3
  action:      click
  selector:    [data-testid="login-submit"]
  description: 点击登录

步骤 4
  action:      assert_visible
  selector:    .error-message
  description: 验证错误提示出现

步骤 5
  action:      assert_text
  selector:    .error-message
  expected:    /用户名或密码错误/
  description: 验证错误提示文本正确

步骤 6
  action:      assert_url
  expected:    **/login**
  description: 验证仍在登录页（未跳转）
```

---

## 12. 控制流（if / else / while）

步骤编辑器支持在用例中插入控制流块，让用例从「线性逐步执行」升级为条件分支与循环轮询。控制流以扁平步骤形式存储（`if / else / endif`、`while / endwhile` 关键字），执行引擎自动转换为嵌套树执行。

### 12.1 插入控制流

在步骤编辑器工具栏点击「插入控制流」下拉按钮，可选三种块：

| 类型 | 生成步骤 | 用途 |
| --- | --- | --- |
| if 块 | `if` … `endif` | 条件满足时执行内部步骤 |
| if-else 块 | `if` … `else` … `endif` | 二分支：满足执行 then，否则执行 else |
| while 块 | `while` … `endwhile` | 条件满足时循环执行内部步骤（轮询等待） |

也可以在任意步骤行的「+ 插入」下拉中，选择插入位置后添加控制流块。

### 12.2 条件表达式语法

`if` / `while` 步骤的 condition 输入框支持声明式 DSL，基于 `ast` 白名单安全求值（禁用 `eval`）：

- 元素查询：`exists(sel)`、`visible(sel)`、`hidden(sel)`、`count(sel)`、`text(sel)`
- 页面属性：`url`、`title`
- 比较：`==`、`!=`、`>`、`<`、`>=`、`<=`
- 逻辑：`and`、`or`、`not`、括号
- 包含：`contains(a, b)` 或 `a contains b`
- 变量：`{{key}}` 先替换为环境变量值再比较

```
visible("button[type=submit]")
not exists(".result-loaded")
count(".todo-item") > 0 and text(".status") contains "成功"
url contains "login"
```

> selector 参数可以不加引号（`visible(#submit)` 会自动引号化），但推荐加引号避免歧义。

### 12.3 while 参数

`while` 步骤额外提供两个参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `max_iter` | 10 | 最大循环次数，防止死循环 |
| `delay_ms` | 1000 | 每轮循环结束后等待的毫秒数 |

### 12.4 控制流示例

```
# if：页面有提交按钮才点击
if          condition: visible("button[type=submit]")
click       selector: button[type=submit]
endif

# if-else：登录成功跳转，失败截图
if          condition: visible("[data-testid='dashboard']")
assert_url  expected: **/dashboard**
else
screenshot  value: login-failed.png
endif

# while：轮询等待结果加载
while       condition: not exists(".result-loaded")  max_iter: 10  delay_ms: 1000
wait        value: 1000
endwhile
```

### 12.5 校验与边界

- 保存时自动校验控制流块配对（`if` 必须有 `endif`，`else` 必须在 `if` 内，`while` 必须有 `endwhile`），不配对会报错并阻止保存。
- `for / endfor / break / continue / elseif / try / goto / label` 已在设计文档规划（详见 `docs/webui-control-flow-design.md`），当前版本暂不支持，执行时遇到会明确报错而非静默当普通步骤执行。

---

## 13. 常见问题 FAQ

### Q1: 录制的步骤执行时找不到元素，怎么办？

**排查步骤：**
1. 检查步骤的 selector 评级，D 级说明该 selector 极不稳定
2. 点击 selector 胶囊，切换为评级更高的备选
3. 如所有备选都是 D 级，手动输入更稳定的 selector（参考第4章）
4. 检查页面是否有动态加载延迟，酌情增加 `timeout`

---

### Q2: `fill` 和 `type` 有什么区别，什么时候用哪个？

| | `fill` | `type` |
|--|--------|--------|
| 行为 | 清空原有内容后填写 | 逐字符模拟键盘输入 |
| 触发事件 | `input`、`change` | 每个字符触发 `keydown`、`keyup`、`keypress`、`input` |
| 适用场景 | 普通表单输入框（推荐） | 实时搜索框、自动补全输入框 |
| 速度 | 快 | 慢（逐字符） |

---

### Q3: 下拉框 `select` 没有反应怎么处理？

原生 `<select>` 用 `select` action；如果是自定义下拉（如 Element Plus `el-select`）：

```
# 方案一：点击触发下拉
步骤 1: click  →  .el-select
步骤 2: click  →  li:has-text("管理员")

# 方案二：录制后系统通常会自动识别
```

---

### Q4: 如何断言弹窗或 Toast 消息？

```
# Element Plus toast
selector:  .el-message--success
action:    assert_visible

# 含文本
selector:  .el-message--success
action:    assert_text
expected:  操作成功

# Ant Design toast
selector:  .ant-message-success
action:    assert_text
expected:  /成功/
```

---

### Q5: `optional: true` 的断言有什么用？

标记为 `optional` 的步骤：
- 失败时**不中断**整条用例，仅在报告中记录警告
- 适合健壮化自动插入的辅助断言（如等待加载完成的断言）
- 不适合核心业务验证（核心断言应保持 `optional: false`）

---

### Q6: 如何在录制后补充 assert 步骤？

在步骤编辑器中，点击「+ 添加步骤」按钮：
1. 选择 action 类型（如 `assert_text`）
2. 填写 selector 和 expected
3. 拖动步骤到目标位置
4. 保存用例

---

### Q7: Selector 里怎么写空格或特殊字符？

```css
/* 属性值含空格，用引号 */
[aria-label="Save and Exit"]
[placeholder="请输入 姓名"]

/* has-text 含特殊字符 */
button:has-text("删除（确认）")

/* XPath 含单引号，用双引号 */
//button[text()="Save 'now'"]
```

---

*文档版本：2026-08-17 | 对应平台版本：P2+*
