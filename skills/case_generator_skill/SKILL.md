# AI测试用例生成技能

name: AI测试用例生成
description: 智能分析需求文档和页面元素，自动生成全面的UI测试用例
version: 1.0.0
category: test-generation

triggers:
  - 生成测试用例
  - 生成用例
  - 创建测试用例
  - AI生成
  - 自动生成用例

parameters:
  max_cases:
    type: integer
    default: 100
    description: 最大生成用例数量
  priority_filter:
    type: array
    default: ["P0", "P1", "P2"]
    description: 包含的优先级列表
  include_edge_cases:
    type: boolean
    default: true
    description: 是否包含边界测试用例

actions:
  - type: parse_requirements
    description: 解析需求文档和页面元素
  - type: generate_cases
    description: 生成标准化测试用例
  - type: validate_cases
    description: 验证用例完整性和可执行性

examples:
  - "生成测试用例"
  - "帮我创建一些测试用例"
  - "根据页面元素生成用例"

---

## 技能说明

本技能用于根据解析的需求文档和页面元素，自动生成全面、规范的UI测试用例。

### 输入要求
- 已解析的页面元素列表
- 可选的需求文档结构化数据

### 输出格式
生成包含以下字段的测试用例：
- **用例名称**: 清晰描述测试目标
- **所属模块**: 根据元素位置或功能模块分类
- **优先级**: P0(核心)/P1(常规)/P2(次要)
- **前置条件**: 测试执行前的环境准备
- **操作步骤**: 详细的操作流程
- **预期结果**: 明确的验证标准

### 用例生成策略
1. **正常场景**: 验证核心功能的正常流程
2. **异常场景**: 验证输入验证、错误处理
3. **边界场景**: 验证边界值、空值、超长输入
4. **兼容场景**: 验证不同浏览器、分辨率下的表现
