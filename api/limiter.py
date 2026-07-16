"""
全局限流器，供各路由文件装饰器使用。
使用方式：
    from api.limiter import limiter
    @router.post("/xxx")
    @limiter.limit("3/minute")
    async def my_endpoint(request: Request, ...):

IP 识别策略（优先级从高到低）：
  1. X-Real-IP      — Nginx 用 $remote_addr 设置，客户端无法伪造
  2. X-Forwarded-For 首段 — 多级代理链时取最左侧（最原始）客户端 IP
  3. TCP 直连 IP    — 无反向代理时的兜底
"""
from slowapi import Limiter
from slowapi.util import get_remote_address


def _get_real_ip(request) -> str:
    """从请求头中提取真实客户端 IP，兼容 Nginx/Caddy 等反向代理场景。"""
    # X-Real-IP 由 Nginx proxy_set_header X-Real-IP $remote_addr 写入，最可信
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    # X-Forwarded-For 可能是逗号分隔的链路，取第一段（最原始客户端）
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    # 无反向代理时直接用 TCP 连接地址
    return get_remote_address(request)


limiter = Limiter(key_func=_get_real_ip, default_limits=[])
