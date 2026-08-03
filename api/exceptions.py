"""
统一业务异常体系

错误码设计：
  4xxx → 客户端错误（与 HTTP 4xx 对应）
  5xxx → 服务端错误（与 HTTP 5xx 对应）

使用方式：
    raise AppError.NOT_FOUND("任务")
    raise AppError.LLM_TIMEOUT()
    raise AppException(code=4001, message="xxx", status_code=400)
"""

from fastapi import HTTPException


class AppException(HTTPException):
    """统一业务异常，继承 HTTPException 确保全局 handler 能直接处理。

    额外字段：
        code    — 业务错误码，前端可按此做分支处理
        message — 用户可见的中文说明（同时作为 HTTPException.detail）
    """

    def __init__(self, code: int, message: str, status_code: int, detail: str | None = None):
        super().__init__(status_code=status_code, detail=detail or message)
        self.code = code
        self.message = message


# ── 快捷工厂 ──────────────────────────────────────────────────────────────────
class AppError:
    """
    所有业务错误的入口，统一命名规范：
        AppError.NOT_FOUND("任务")      → 404, code=4004
        AppError.FORBIDDEN("工作空间")  → 403, code=4003
        AppError.CONFLICT("任务已在执行") → 409, code=4009
        AppError.PARAM("请提供文档路径") → 400, code=4001
        AppError.LLM_TIMEOUT()          → 503, code=5001
        AppError.INTERNAL("文件写入失败") → 500, code=5000
    """

    # ── 4xx ──────────────────────────────────────────────────────────────────

    @staticmethod
    def PARAM(message: str = "请求参数有误") -> AppException:
        """400 参数错误 / 业务校验失败"""
        return AppException(code=4001, message=message, status_code=400)

    @staticmethod
    def UNAUTHORIZED(message: str = "未登录或 Token 已过期") -> AppException:
        """401 未鉴权"""
        return AppException(code=4011, message=message, status_code=401)

    @staticmethod
    def FORBIDDEN(resource: str = "记录") -> AppException:
        """403 权限不足"""
        return AppException(code=4003, message=f"无权访问此{resource}", status_code=403)

    @staticmethod
    def NOT_FOUND(resource: str = "记录") -> AppException:
        """404 资源不存在"""
        return AppException(code=4004, message=f"{resource}不存在", status_code=404)

    @staticmethod
    def CONFLICT(message: str = "操作冲突，请稍后重试") -> AppException:
        """409 并发冲突（如同一任务重复执行）"""
        return AppException(code=4009, message=message, status_code=409)

    @staticmethod
    def TOO_MANY(message: str = "请求过于频繁，请稍后重试") -> AppException:
        """429 限流 / 并发任务超限"""
        return AppException(code=4029, message=message, status_code=429)

    # ── 5xx ──────────────────────────────────────────────────────────────────

    @staticmethod
    def INTERNAL(message: str = "服务器内部错误，请稍后重试") -> AppException:
        """500 未预期的服务端错误"""
        return AppException(code=5000, message=message, status_code=500)

    @staticmethod
    def LLM_TIMEOUT(message: str = "AI 服务响应超时，请稍后重试") -> AppException:
        """503 LLM 调用失败 / 超时"""
        return AppException(code=5001, message=message, status_code=503)

    @staticmethod
    def FILE_ERROR(message: str = "文件处理失败，请稍后重试") -> AppException:
        """500 文件读写 / 解析失败"""
        return AppException(code=5002, message=message, status_code=500)
