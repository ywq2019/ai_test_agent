# ── Stage 1：前端构建 ────────────────────────────────────────────────────────
FROM node:18-alpine AS frontend-builder

WORKDIR /app/ui
COPY ui/package*.json ./
RUN npm ci --production=false
COPY ui/ ./
RUN npm run build

# ── Stage 2：生产镜像 ────────────────────────────────────────────────────────
# 使用官方 Playwright Python 镜像，已内置 Chromium 及所有系统依赖
# 版本与 requirements.txt 中 playwright==1.39.0 严格对应，不要随意升级
FROM mcr.microsoft.com/playwright/python:v1.39.0-jammy

WORKDIR /app

# ── 系统依赖 ──────────────────────────────────────────────────────────────────
# curl：healthcheck 使用
# fonts-noto-cjk：PDF 导出中文字体支持
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# ── Python 环境变量 ──────────────────────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# ── Python 依赖（Playwright 浏览器已内置，跳过下载）──────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── 拷贝前端构建产物 ──────────────────────────────────────────────────────────
COPY --from=frontend-builder /app/ui/dist ./ui/dist

# ── 拷贝后端代码 ──────────────────────────────────────────────────────────────
COPY agent/   ./agent/
COPY api/     ./api/
COPY skills/  ./skills/
COPY tools/   ./tools/
COPY main.py  ./

# ── 数据目录（会被 Volume 挂载覆盖，此处仅做占位）───────────────────────────
RUN mkdir -p \
        /data/reports \
        /data/screenshots \
        /data/logs \
        /data/uploads/documents \
        /data/ai_cases

# ── 非 root 用户运行（安全最佳实践）──────────────────────────────────────────
# 同时将官方镜像内置的 Playwright 浏览器目录授权给 appuser
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app /data \
    && if [ -d /ms-playwright ]; then chown -R appuser:appuser /ms-playwright; fi

USER appuser

EXPOSE 4000

# ── 健康检查 ──────────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:4000/api/v1/health || exit 1

# ── 启动命令 ──────────────────────────────────────────────────────────────────
# ⚠️ 必须单进程（workers=1）
#    全局 LLM Semaphore / 后台任务计数器均为进程内对象
#    多 worker 会导致并发保护失效
#    横向扩展请部署多容器实例，并用 Redis 共享 Semaphore
CMD ["python", "main.py"]
