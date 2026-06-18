# UI自动化测试Agent

基于 **LangChain + LangGraph** 的智能化、零代码Web UI自动化测试平台。

## 🎯 项目简介

自动化UI测试Agent是一款基于 **FastAPI + Vue3 + LangChain/LangGraph** 的企业级Web UI自动化测试平台，具有以下特点：

- **零代码测试**：只需输入URL即可自动生成测试用例
- **AI驱动**：基于大语言模型智能分析页面元素和需求文档
- **Agent架构**：标准的「大模型 + 思考决策逻辑 + 外部工具集」架构
- **技能扩展**：遵循企业级标准化技能目录规范，支持插件化扩展
- **可视化管理**：提供完整的任务、用例、执行和报告管理界面

## 🛠️ 技术栈

### 后端技术栈
| 技术 | 版本 | 说明 |
|------|------|------|
| Python | 3.11+ | 编程语言 |
| FastAPI | 0.109.0 | 高性能Web框架 |
| Uvicorn | 0.27.0 | ASGI服务器 |
| SQLAlchemy | 2.0.25 | 异步ORM框架 |
| **LangChain** | 1.3.9 | LLM应用开发框架 |
| **LangGraph** | 1.2.5 | 状态机工作流引擎 |
| **langchain-openai** | 1.3.2 | OpenAI兼容接口 |
| Playwright | 1.41.0 | 自动化测试工具 |
| SQLite | 内置 | 轻量级数据库 |

### 前端技术栈
| 技术 | 版本 | 说明 |
|------|------|------|
| Vue | 3.4+ | 前端框架 |
| Element Plus | 2.6+ | UI组件库 |
| Pinia | 2.1+ | 状态管理 |
| Vue Router | 4.3+ | 路由管理 |
| ECharts | 5.5+ | 图表库 |
| Vite | 5.4+ | 构建工具 |

## 🧠 Agent架构设计

### 核心架构
```
Agent = 大模型(LLM) + 思考决策逻辑(LangGraph) + 外部工具集(LangChain Tools)
```

### 大模型配置
```python
llm = ChatOpenAI(
    model="deepseek-chat",
    temperature=0.5,
    api_key=apikey,
    base_url=baseurl
)
```

### 工具调用机制
- 使用 `@tool` 装饰器定义工具
- LLM通过语义自主匹配、智能调用
- 告别关键词硬匹配

## ✨ 功能特性

### 核心功能
1. **任务管理**：创建、编辑、删除测试任务，支持URL和文档导入
2. **页面解析**：自动抓取页面元素，识别可交互元素（按钮、输入框、选择框等）
3. **用例生成**：基于页面元素和需求文档智能生成测试用例
4. **测试执行**：支持批量执行测试用例，实时显示进度（WebSocket推送）
5. **报告生成**：自动生成详细的测试报告，包含统计图表和截图

### 扩展功能
1. **技能管理**：标准化技能目录规范，支持自定义技能扩展
2. **大模型配置**：支持多模型切换和API配置
3. **自动技能发现**：启动时自动扫描技能目录，动态注册工具

## 📁 标准化技能目录规范

遵循主流开源企业级Agent工程规范：

```
skills/
└── <skill_name>/           # 独立可插拔技能目录
    ├── SKILL.md           # 技能说明文档（场景、约束、风险提示）
    ├── metadata.yaml      # 技能元数据（入参规范、输出格式）
    ├── examples/          # 使用示例和错误案例
    ├── templates/         # 模板文件
    ├── resources/         # 资源文件（白名单、权限规则）
    └── scripts/
        └── run.py         # 核心执行逻辑
```

### 已实现的技能
| 技能名称 | 描述 | 工具名 |
|----------|------|--------|
| 页面解析器 | 抓取网页可交互元素 | `parse_page` |
| 文档解析器 | 解析PDF/Word需求文档 | `parse_document` |
| 用例生成器 | 智能生成测试用例 | `generate_cases` |
| 测试执行器 | 执行测试用例 | `execute_tests` |
| 报告生成器 | 生成测试报告 | `generate_report` |

### 添加新技能
只需创建符合规范的技能目录，系统启动时自动发现并注册：
1. 创建目录 `skills/your_skill/`
2. 添加 `metadata.yaml` 定义元数据
3. 添加 `scripts/run.py` 实现核心逻辑
4. 重启服务即可自动注册

## 🚀 快速开始

### 环境要求
- Python 3.11+
- Node.js 18+
- npm 9+

### 安装依赖

#### 后端依赖
```bash
cd ai_uitest_agent
pip install -r requirements.txt
playwright install
```

#### 前端依赖
```bash
cd ui
npm install
```

### 配置大模型

编辑 `.env` 文件：
```ini
# 大模型配置
AI_API_KEY=your_api_key_here
AI_API_URL=https://api.deepseek.com/v1/chat/completions
AI_MODEL=deepseek-chat
AI_MODEL_NAME=deepseek-chat
```

### 运行项目

#### 启动后端服务
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 4000
```

#### 启动前端服务
```bash
cd ui
npm run dev
```

### 访问地址
| 服务 | 地址 |
|------|------|
| 前端页面 | http://localhost:8090 |
| 后端API | http://localhost:4000 |
| API文档 | http://localhost:4000/docs |

## 📁 项目结构

```
ai_uitest_agent/
├── agent/                    # Agent核心模块
│   ├── __init__.py
│   ├── core.py               # 代理核心逻辑
│   └── langgraph_agent.py    # LangGraph状态机代理
├── api/                      # API接口模块
│   ├── __init__.py
│   ├── routes.py             # REST API路由
│   ├── schemas.py            # 数据模型定义
│   ├── websocket.py          # WebSocket处理
│   └── websocket_manager.py  # WebSocket连接管理
├── skills/                   # 技能模块（标准化结构）
│   ├── __init__.py
│   ├── langchain_tools.py    # LangChain工具注册
│   ├── page_parser/          # 页面解析器技能
│   │   ├── SKILL.md
│   │   ├── metadata.yaml
│   │   └── scripts/run.py
│   ├── document_parser/      # 文档解析器技能
│   │   ├── SKILL.md
│   │   ├── metadata.yaml
│   │   └── scripts/run.py
│   ├── case_generator/       # 用例生成器技能
│   │   ├── SKILL.md
│   │   ├── metadata.yaml
│   │   └── scripts/run.py
│   ├── test_executor/        # 测试执行器技能
│   │   ├── SKILL.md
│   │   ├── metadata.yaml
│   │   └── scripts/run.py
│   └── report_generator/     # 报告生成器技能
│       ├── SKILL.md
│       ├── metadata.yaml
│       └── scripts/run.py
├── tools/                    # 工具模块
│   ├── __init__.py
│   ├── browser.py            # 浏览器操作工具
│   ├── config.py             # 配置管理
│   ├── database.py           # 数据库操作
│   ├── document_parser.py    # 文档解析工具
│   └── logger.py             # 日志管理
├── ui/                       # 前端模块
│   ├── src/
│   │   ├── api/              # API调用封装
│   │   ├── router/           # 路由配置
│   │   ├── stores/           # 状态管理
│   │   ├── views/            # 页面组件
│   │   ├── App.vue           # 根组件
│   │   └── main.js           # 入口文件
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── .env                      # 环境变量配置
├── main.py                   # 应用入口
├── requirements.txt          # Python依赖
└── uitest_agent.db           # SQLite数据库文件
```

## 🔧 配置说明

### 环境变量配置 (.env)

```ini
# 应用配置
APP_NAME=自动化UI测试Agent
APP_VERSION=1.0.0
DEBUG=True

# 服务配置
HOST=0.0.0.0
PORT=4000

# 跨域配置
CORS_ORIGINS=["*"]

# 大模型配置
AI_API_KEY=your_api_key
AI_API_URL=https://api.deepseek.com/v1/chat/completions
AI_MODEL=deepseek-chat
AI_MODEL_NAME=deepseek-chat

# 路径配置
SCREENSHOT_DIR=./screenshots
REPORT_OUTPUT_DIR=./reports
LOG_DIR=./logs

# 数据库配置
DATABASE_URL=sqlite+aiosqlite:///./uitest_agent.db
```

### 支持的大模型
- DeepSeek (deepseek-chat)
- OpenAI (gpt-3.5-turbo, gpt-4)
- 智谱AI (chatglm)
- 豆包
- 其他OpenAI兼容接口

## 📦 打包部署

### 后端打包

#### 使用 PyInstaller
```bash
pip install pyinstaller
pyinstaller --onefile --name uitest-agent main.py
```

#### 生成的文件
- `dist/uitest-agent.exe` (Windows)
- `dist/uitest-agent` (Linux/Mac)

### 前端打包

```bash
cd ui
npm run build
```

打包产物位于 `ui/dist` 目录。

### 部署方案

#### 方案一：独立运行（开发环境）
```bash
# 后端
python -m uvicorn main:app --host 0.0.0.0 --port 4000

# 前端（开发模式）
cd ui
npm run dev
```

#### 方案二：Nginx反向代理（生产环境）

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态文件
    location / {
        root /path/to/ui/dist;
        try_files $uri $uri/ /index.html;
    }

    # 后端API
    location /api/ {
        proxy_pass http://127.0.0.1:4000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # WebSocket
    location /ws {
        proxy_pass http://127.0.0.1:4000/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

#### 方案三：Docker部署

创建 `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 4000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4000"]
```

构建并运行：
```bash
docker build -t uitest-agent .
docker run -p 4000:4000 uitest-agent
```

## 📋 使用流程

### 1. 创建任务
1. 进入「任务管理」页面
2. 点击「新建任务」
3. 填写任务名称和目标URL
4. 选择浏览器类型（Chrome/Firefox/WebKit）

### 2. 解析页面
1. 在任务列表中选择任务
2. 点击「解析页面」
3. 等待页面元素抓取完成

### 3. 生成用例
1. 切换到「用例管理」页面
2. 选择任务
3. 点击「生成用例」（可导入需求文档辅助生成）

### 4. 执行测试
1. 切换到「测试执行」页面
2. 选择任务
3. 点击「执行全部」或选择部分用例执行
4. 实时查看执行进度

### 5. 查看报告
1. 切换到「测试报告」页面
2. 从列表中选择报告
3. 查看统计图表、详细结果和截图

## 🔌 技能开发指南

### 技能元数据规范 (metadata.yaml)
```yaml
name: "技能名称"
version: "1.0.0"
category: "技能类别"
description: "技能描述"
parameters:
  param_name:
    type: string
    required: true
    description: "参数说明"
output:
  type: object
  properties:
    field_name:
      type: string
```

### 执行脚本规范 (scripts/run.py)
```python
async def execute(**kwargs) -> dict:
    """
    技能核心执行逻辑
    
    Returns:
        dict: 执行结果
    """
    return {
        "status": "success",
        "data": ...
    }
```



## 📄 许可证

本项目采用 MIT 许可证，详见 LICENSE 文件。

## 📞 联系方式

如有问题或建议，请通过以下方式联系：

- 项目地址：https://gitee.com/fxlysm/ai_uitest_agent.git
- 微信公众号：魅力测试
- 邮箱：fxlysm@126.com
- 当离职状态，若深圳武汉大家有公司介绍，求推荐
---

**注意**：本项目仅供学习和研究使用，生产环境使用前请进行充分测试。


## 截图

<table>
    <tr>
        <td><img src="https://gitee.com/fxlysm/ai_uitest_agent/raw/master/image/001.png"/></td>
        <td><img src="https://gitee.com/fxlysm/ai_uitest_agent/raw/master/image/002.png"/></td>
    </tr>
    <tr>
                <td><img src="https://gitee.com/fxlysm/ai_uitest_agent/raw/master/image/003.png"/></td>
        <td><img src="https://gitee.com/fxlysm/ai_uitest_agent/raw/master/image/004.png"/></td>
    </tr>
    <tr>
              <td><img src="https://gitee.com/fxlysm/ai_uitest_agent/raw/master/image/005.png"/></td>
        <td><img src="https://gitee.com/fxlysm/ai_uitest_agent/raw/master/image/006.png"/></td>
    </tr>
	<tr>
           <td><img src="https://gitee.com/fxlysm/ai_uitest_agent/raw/master/image/007.png"/></td>
        <td><img src="https://gitee.com/fxlysm/ai_uitest_agent/raw/master/image/008.png"/></td>
    </tr>	 

</table>


## 捐赠支持

😀 你可以请作者喝杯咖啡表示鼓励

- 有捐赠的小伙伴（金额不限）可以联系作者领取一份 **独家提升开发技能的文档**
- 加QQ814380399或者邮件到 fxlysm@126.com邮箱 *注明 领取开发技能提升文档*
- 文档宗旨在于提升测试人员的测试理论及测试开发相关技术，讲述**如何测试**，高质量测试，**如何开发测试平台**等

<table>
    <tr>
        <td><img src="https://gitee.com/fxlysm/ai_uitest_agent/raw/master/image/0010.jpg"/></td>
        <td><img src="https://gitee.com/fxlysm/ai_uitest_agent/raw/master/image/0011.png"/></td>
    </tr>  
</table>