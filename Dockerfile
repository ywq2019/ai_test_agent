# ── Stage 1：前端构建 ────────────────────────────────────────────────────
FROM node:18-alpine AS frontend-builder

WORKDIR /app/ui
COPY ui/package*.json ./
RUN npm ci --production=false
COPY ui/ ./
RUN npm run build

# ── Stage 2：生产镜像 ────────────────────────────────────────────────────
# 使用官方 Playwright Python 镜像，已内置 Chromium 及所有系统依赖
FROM mcr.microsoft.com/playwright/python:v1.39.0-jammy

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium --with-deps

# 从 Stage 1 拷贝前端构建产物
COPY --from=frontend-builder /app/ui/dist ./ui/dist

# 拷贝后端代码（排除不需要的目录）
COPY agent/       ./agent/
COPY api/         ./api/
COPY skills/      ./skills/
COPY tools/       ./tools/
COPY main.py      ./

# 创建数据目录（会被 Volume 挂载覆盖，此处仅做占位）
RUN mkdir -p /data/reports /data/screenshots /data/logs /data/uploads/documents

# 非 root 用户运行（安全最佳实践）
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 4000

CMD ["python", "main.py"]
