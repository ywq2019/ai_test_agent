# test-case-pro-max

name: test-case-pro-max
description: 专业级AI测试用例生成技能，覆盖功能/边界/安全/性能/兼容性全维度，生成高质量标准化测试用例集
version: 2.0.0
category: test-generation

triggers:
  - 高质量用例生成
  - 专业用例生成
  - pro-max生成
  - 全维度测试用例
  - 生成高质量测试用例
  - test-case-pro-max

parameters:
  max_cases:
    type: integer
    default: 200
    description: 最大生成用例数量
  priority_filter:
    type: array
    default: ["P0", "P1", "P2", "P3"]
    description: 包含的优先级列表
  coverage_dimensions:
    type: array
    default: ["functional", "boundary", "exception", "security", "performance", "compatibility"]
    description: 覆盖维度

actions:
  - type: parse_requirements
    description: 深度解析需求文档，提取功能点、业务规则、约束条件
  - type: generate_cases
    description: 生成覆盖6大维度的高质量测试用例
  - type: validate_cases
    description: 验证用例完整性、可操作性和可量化验证标准
  - type: coverage_analysis
    description: 分析用例覆盖度，确保无盲区

examples:
  - "生成高质量测试用例"
  - "使用pro-max技能生成测试用例"
  - "全维度测试用例生成"

---

## 技能说明

**test-case-pro-max** 是专业级AI测试用例生成技能，相比普通用例生成，本技能采用以下增强策略：

### 核心能力

| 维度 | 覆盖内容 |
|------|----------|
| **功能测试** | 主流程、分支流程、异步场景、状态机转换 |
| **边界值测试** | 最大值/最小值/临界值/空值/特殊字符/超长输入 |
| **异常测试** | 网络异常/超时/并发冲突/权限拒绝/数据损坏 |
| **安全测试** | SQL注入/XSS/CSRF/越权访问/敏感信息泄露 |
| **性能测试** | 大数据量/高并发/响应时间/内存泄漏 |
| **兼容性测试** | 多浏览器/多分辨率/移动端/不同系统版本 |

### 技能调用方式

本技能通过 `prompt.yaml` 提供增强的系统提示词和用户提示词模板，在 AI 用例生成时自动加载。

### 输出格式

生成包含以下字段的标准化测试用例：
- **id**: 用例唯一编号（TC001, TC002...）
- **name**: 清晰的用例名称（含测试目标和场景）
- **priority**: P0（核心主流程）/ P1（主要功能）/ P2（边界异常）/ P3（安全性能兼容）
- **type**: 功能测试 / 边界测试 / 异常测试 / 安全测试 / 性能测试 / 兼容测试
- **preconditions**: 前置条件和测试环境要求
- **steps**: 具体可操作的测试步骤
- **expected**: 可量化验证的预期结果

### 触发条件

AI用例生成模块会自动检测本技能是否存在，若存在则优先使用本技能的增强提示词生成更高质量的测试用例集。
