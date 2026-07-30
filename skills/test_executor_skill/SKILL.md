# 测试执行控制技能

name: 测试执行控制
description: 通过自然语言控制测试用例的执行过程，包括启动、暂停、继续、停止、重试等操作
version: 1.0.0
category: execution-control

triggers:
  - 执行测试
  - 运行测试
  - 开始测试
  - 暂停测试
  - 继续测试
  - 停止测试
  - 重试
  - 重新运行
  - 执行用例
  - 全量执行
  - 执行全部

parameters:
  browser:
    type: string
    default: chromium
    description: 执行的浏览器类型
  timeout:
    type: integer
    default: 30000
    description: 单个用例超时时间(毫秒)
  retry_count:
    type: integer
    default: 2
    description: 失败重试次数

actions:
  - type: execute
    description: 执行测试用例
  - type: pause
    description: 暂停执行
  - type: resume
    description: 继续执行
  - type: stop
    description: 停止执行
  - type: retry
    description: 重试失败用例

examples:
  - "执行全部用例"
  - "暂停测试"
  - "继续执行"
  - "停止测试"
  - "重试失败的用例"
  - "重新运行"

---

## 技能说明

本技能提供自然语言驱动的测试执行控制能力。

### 支持的操作

| 操作 | 命令示例 | 说明 |
|------|---------|------|
| 全量执行 | 执行全部用例/运行所有测试 | 按顺序执行所有启用的用例 |
| 单条执行 | 执行第一个用例 | 运行指定的单个用例 |
| 暂停 | 暂停测试/暂停执行 | 暂停当前执行流程 |
| 继续 | 继续测试/继续执行 | 恢复暂停的测试 |
| 停止 | 停止测试/终止执行 | 完全停止测试任务 |
| 重试 | 重试/重试失败用例 | 重新执行失败的用例 |

### 执行状态
- **pending**: 待执行
- **running**: 执行中
- **paused**: 已暂停
- **passed**: 执行成功
- **failed**: 执行失败
- **skipped**: 已跳过

### 实时反馈
执行过程中会实时推送：
- 当前执行进度
- 正在执行的用例信息
- 执行结果（成功/失败）
- 错误信息和截图
