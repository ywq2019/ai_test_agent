# ── Stage 1：前端构建 ────────────────────────────────────────────────────
FROM node:18-alpine AS frontend-builder

WORKDIR /app/ui
COPY ui/package*.json ./
RUN npm ci --production=false
COPY ui/ ./
RUN npm run build

# ── Stage 2：生产镜像 ────────────────────────────────────────────────────
# 使用官方 Playwright Python 镜像，已内置 Chromium 及所有系统依赖
# 不需要再次执行 playwright install，镜像内置版本与 playwright==1.39.0 匹配
FROM mcr.microsoft.com/playwright/python:v1.39.0-jammy

WORKDIR /app

# 安装 curl（供 docker-compose healthcheck 使用）
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（跳过浏览器下载，镜像已内置）
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 从 Stage 1 拷贝前端构建产物
COPY --from=frontend-builder /app/ui/dist ./ui/dist

# 拷贝后端代码（排除不需要的目录）
COPY agent/       ./agent/
COPY api/         ./api/
COPY skills/      ./skills/
COPY tools/       ./tools/
COPY main.py      ./

# 创建数据目录（会被 Volume 挂载覆盖，此处仅做占位）
RUN mkdir -p /data/reports /data/screenshots /data/logs /data/uploads/documents /data/ai_cases

# 非 root 用户运行（安全最佳实践）
# 同时将官方镜像内置的 Playwright 浏览器目录授权给 appuser，避免 Permission denied
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app /data \
    && if [ -d /ms-playwright ]; then chown -R appuser:appuser /ms-playwright; fi
USER appuser

EXPOSE 4000

CMD ["python", "main.py"]
