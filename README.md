# 自动化UI测试Agent

智能化、零代码的Web UI自动化测试工具，基于大语言模型和Playwright实现。
注： 当前项目部分功能实现了，但UI 及 交互还没时间来做优化，大家时间充足可自行优化！

## 🎯 项目简介

自动化UI测试Agent是一款基于FastAPI + Vue3的Web UI自动化测试平台，具有以下特点：

- **零代码测试**：只需输入URL即可自动生成测试用例
- **AI驱动**：基于大语言模型智能分析页面元素和需求文档
- **可视化管理**：提供完整的任务、用例、执行和报告管理界面
- **技能扩展**：支持插件化技能系统，可灵活扩展功能

## 🛠️ 技术栈

### 后端技术栈
| 技术 | 版本 | 说明 |
|------|------|------|
| Python | 3.11+ | 编程语言 |
| FastAPI | 0.109.0 | 高性能Web框架 |
| Uvicorn | 0.27.0 | ASGI服务器 |
| SQLAlchemy | 2.0.25 | 异步ORM框架 |
| Playwright | 1.41.0 | 自动化测试工具 |
| SQLite | 内置 | 轻量级数据库 |
| WebSocket | 原生 | 实时通信 |

### 前端技术栈
| 技术 | 版本 | 说明 |
|------|------|------|
| Vue | 3.4+ | 前端框架 |
| Element Plus | 2.6+ | UI组件库 |
| Pinia | 2.1+ | 状态管理 |
| Vue Router | 4.3+ | 路由管理 |
| ECharts | 5.5+ | 图表库 |
| Vite | 5.4+ | 构建工具 |

## ✨ 功能特性

### 核心功能
1. **任务管理**：创建、编辑、删除测试任务，支持URL和文档导入
2. **页面解析**：自动抓取页面元素，识别可交互元素（按钮、输入框、选择框等）
3. **用例生成**：基于页面元素智能生成测试用例
4. **测试执行**：支持批量执行测试用例，实时显示进度
5. **报告生成**：自动生成详细的测试报告，包含统计图表和截图

### 扩展功能
1. **技能管理**：插件化技能系统，支持自定义技能扩展
2. **大模型配置**：支持多大模型切换和API配置
3. **WebSocket通信**：实时推送执行进度和状态

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
- **前端页面**: http://localhost:8090
- **后端API**: http://localhost:4000
- **API文档**: http://localhost:4000/docs

## 📁 项目结构

```
ai_uitest_agent/
├── agent/                    # 代理核心模块
│   ├── __init__.py
│   └── core.py               # 代理核心逻辑
├── api/                      # API接口模块
│   ├── __init__.py
│   ├── routes.py             # REST API路由
│   ├── schemas.py            # 数据模型定义
│   ├── websocket.py          # WebSocket处理
│   └── websocket_manager.py  # WebSocket连接管理
├── skills/                   # 技能模块
│   ├── __init__.py
│   ├── case_generator.py     # 测试用例生成器
│   ├── report_generator.py   # 报告生成器
│   ├── skill_loader.py       # 技能加载器
│   ├── skill_registry.py     # 技能注册表
│   ├── test_executor.py      # 测试执行器
│   └── */                    # 各技能的SKILL.md配置
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
LLM_TYPE=openai
LLM_API_KEY=your_api_key
LLM_API_URL=https://api.openai.com/v1/chat/completions
LLM_MODEL=gpt-3.5-turbo

# 路径配置
SCREENSHOT_DIR=./screenshots
REPORT_OUTPUT_DIR=./reports
LOG_DIR=./logs

# 数据库配置
DATABASE_URL=sqlite+aiosqlite:///./uitest_agent.db
```

### 大模型配置

支持多种大模型：
- OpenAI (gpt-3.5-turbo, gpt-4)
- 国产大模型 (如智谱、豆包等)
- 本地部署模型

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
3. 点击「生成用例」

### 4. 执行测试
1. 切换到「测试执行」页面
2. 选择任务
3. 点击「执行全部」或选择部分用例执行

### 5. 查看报告
1. 切换到「测试报告」页面
2. 从列表中选择报告
3. 查看统计图表和详细结果

## 🧪 测试

### 运行测试用例
```bash
# 安装测试依赖
pip install pytest pytest-asyncio

# 运行测试
pytest tests/ -v
```


## 📄 许可证

本项目采用 MIT 许可证，详见 LICENSE 文件。

## 📞 联系方式

如有问题或建议，请通过以下方式联系：

- 项目地址：https://gitee.com/fxlysm/ai_uitest_agent.git
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
