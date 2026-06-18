# 页面元素解析技能

name: 页面元素解析
description: 使用Playwright自动抓取网页的可交互UI元素，包括输入框、按钮、链接等
version: 1.0.0
category: page-parsing

triggers:
  - 解析页面
  - 抓取元素
  - 获取页面元素
  - 分析页面
  - 扫描页面

parameters:
  url:
    type: string
    required: true
    description: 要解析的页面URL
  browser:
    type: string
    default: chromium
    description: 使用的浏览器引擎
  wait_timeout:
    type: integer
    default: 5000
    description: 元素等待超时时间(毫秒)
  capture_screenshots:
    type: boolean
    default: false
    description: 是否截取页面截图

actions:
  - type: navigate
    description: 导航到目标页面
  - type: capture_elements
    description: 抓取页面元素
  - type: analyze_structure
    description: 分析页面结构

examples:
  - "解析这个页面"
  - "抓取页面元素"
  - "分析页面结构"

---

## 技能说明

本技能使用Playwright自动化工具抓取网页中的可交互UI元素。

### 抓取的元素类型
- **input**: 输入框（text, password, email, number等）
- **button**: 按钮
- **a**: 链接/锚点
- **select**: 下拉选择框
- **textarea**: 多行文本框
- **checkbox**: 复选框
- **radio**: 单选框

### 元素属性信息
每个抓取的元素包含：
- **tag**: HTML标签名
- **type**: 输入类型或子类型
- **name**: 元素名称(name属性)
- **id**: 元素ID
- **text**: 元素文本内容
- **placeholder**: 占位符文本
- **selector**: 可用于定位的CSS选择器
- **x, y, width, height**: 元素位置和尺寸

### 使用场景
1. **用例生成前置**: 为AI生成测试用例提供页面结构信息
2. **元素定位验证**: 确认特定元素在页面上的位置
3. **页面结构分析**: 了解页面的交互组件分布
