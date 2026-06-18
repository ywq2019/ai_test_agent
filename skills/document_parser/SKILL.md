# 文档解析技能

name: 需求文档解析
description: 解析PDF和Word格式的产品需求文档，提取功能点、业务规则、校验逻辑等结构化信息
version: 1.0.0
category: document-parsing

triggers:
  - 解析文档
  - 解析需求
  - 读取文档
  - 上传文档
  - 分析需求

parameters:
  file_path:
    type: string
    required: true
    description: 文档文件路径
  file_type:
    type: string
    enum: [pdf, docx, doc]
    description: 文档类型（自动检测）

actions:
  - type: extract_text
    description: 提取文档文本内容
  - type: structure_content
    description: 结构化内容解析
  - type: extract_rules
    description: 提取业务规则和校验逻辑

examples:
  - "解析这个需求文档"
  - "读取PDF文档"
  - "分析Word文档"

---

## 技能说明

本技能解析产品需求文档，提取可用于测试用例生成的结构化信息。

### 支持的格式
- **PDF**: .pdf文件
- **Word**: .docx, .doc文件

### 提取的内容

#### 1. 功能点 (functional_points)
从文档中识别的功能描述，例如：
- "用户登录功能"
- "商品添加到购物车"
- "订单支付流程"

#### 2. 校验规则 (validation_rules)
业务逻辑和数据校验规则，例如：
- "用户名不能为空"
- "密码长度至少8位"
- "邮箱格式必须正确"

#### 3. 业务流程 (business_flows)
操作步骤和流程描述，例如：
- "登录流程：输入账号 → 输入密码 → 点击登录"
- "下单流程：选择商品 → 确认订单 → 完成支付"

#### 4. 结构化章节 (sections)
按标题/编号组织的文档结构，便于理解需求层级关系。

### 使用场景
1. **需求理解**: 快速把握需求文档的核心内容
2. **用例生成**: 结合页面元素生成贴合业务的测试用例
3. **测试覆盖**: 确保测试用例覆盖所有功能点和业务规则
