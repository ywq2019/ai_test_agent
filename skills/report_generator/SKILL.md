# 测试报告生成技能

name: 测试报告生成
description: 生成可视化HTML测试报告，包含测试结果统计、通过率图表、失败用例详情和截图
version: 1.0.0
category: reporting

triggers:
  - 生成报告
  - 查看报告
  - 导出报告
  - 测试报告

parameters:
  task_id:
    type: integer
    required: true
    description: 测试任务ID
  format:
    type: string
    default: html
    description: 报告格式
  include_screenshots:
    type: boolean
    default: true
    description: 是否包含截图

actions:
  - type: collect_results
    description: 收集测试结果数据
  - type: calculate_summary
    description: 计算统计数据
  - type: generate_html
    description: 生成HTML报告

examples:
  - "生成测试报告"
  - "查看报告"
  - "导出报告"

---

## 技能说明

本技能生成结构化的可视化测试报告。

### 报告内容

#### 1. 测试摘要
- 测试任务名称
- 执行时间范围
- 测试环境信息
- 浏览器类型

#### 2. 统计数据
- 总用例数
- 通过数/失败数/跳过数
- 通过率
- 总耗时

#### 3. 图表可视化
- **通过率饼图**: 展示通过/失败/跳过的比例
- **状态柱状图**: 展示各状态用例数量

#### 4. 失败用例详情
每个失败用例包含：
- 用例名称
- 错误信息
- 错误截图（如果有）
- 执行耗时

#### 5. 用例执行详情表
完整的执行记录表格，可查看每个用例的执行状态和详细信息。

### 导出格式
- **HTML**: 可直接在浏览器中打开，带样式和图表
- **JSON**: 原始数据，便于程序处理

### 报告查看
生成的HTML报告支持：
- 浏览器直接预览
- 打印为PDF
- 保存到本地
