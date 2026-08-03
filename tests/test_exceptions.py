"""
api/exceptions.py 单元测试

覆盖：
  - AppException 结构（code / message / status_code / detail）
  - AppError 工厂方法各返回值
  - AppException 继承自 HTTPException（全局 handler 兼容性）
"""
import pytest
from fastapi import HTTPException

from api.exceptions import AppException, AppError


class TestAppException:
    def test_inherits_http_exception(self):
        exc = AppException(code=4001, message="参数错误", status_code=400)
        assert isinstance(exc, HTTPException)

    def test_fields_set_correctly(self):
        exc = AppException(code=5000, message="内部错误", status_code=500)
        assert exc.code == 5000
        assert exc.message == "内部错误"
        assert exc.status_code == 500
        assert exc.detail == "内部错误"   # detail 默认等于 message

    def test_custom_detail_overrides_message(self):
        exc = AppException(code=4001, message="参数错误", status_code=400, detail="字段 X 不能为空")
        assert exc.detail == "字段 X 不能为空"
        assert exc.message == "参数错误"

    def test_status_code_accessible(self):
        exc = AppException(code=4004, message="不存在", status_code=404)
        assert exc.status_code == 404


class TestAppErrorFactories:
    def test_param(self):
        exc = AppError.PARAM("用户名不能为空")
        assert exc.status_code == 400
        assert exc.code == 4001
        assert "用户名" in exc.message

    def test_param_default_message(self):
        exc = AppError.PARAM()
        assert exc.status_code == 400
        assert len(exc.message) > 0

    def test_unauthorized(self):
        exc = AppError.UNAUTHORIZED()
        assert exc.status_code == 401
        assert exc.code == 4011

    def test_unauthorized_custom_message(self):
        exc = AppError.UNAUTHORIZED("Token 已过期")
        assert "Token" in exc.message

    def test_forbidden(self):
        exc = AppError.FORBIDDEN("工作空间")
        assert exc.status_code == 403
        assert exc.code == 4003
        assert "工作空间" in exc.message

    def test_not_found(self):
        exc = AppError.NOT_FOUND("任务")
        assert exc.status_code == 404
        assert exc.code == 4004
        assert "任务" in exc.message

    def test_not_found_default(self):
        exc = AppError.NOT_FOUND()
        assert exc.status_code == 404

    def test_conflict(self):
        exc = AppError.CONFLICT("任务已在执行中")
        assert exc.status_code == 409
        assert exc.code == 4009
        assert "任务" in exc.message

    def test_too_many(self):
        exc = AppError.TOO_MANY()
        assert exc.status_code == 429
        assert exc.code == 4029

    def test_internal(self):
        exc = AppError.INTERNAL()
        assert exc.status_code == 500
        assert exc.code == 5000

    def test_llm_timeout(self):
        exc = AppError.LLM_TIMEOUT()
        assert exc.status_code == 503
        assert exc.code == 5001

    def test_file_error(self):
        exc = AppError.FILE_ERROR("文档解析失败")
        assert exc.status_code == 500
        assert exc.code == 5002
        assert "文档" in exc.message

    def test_all_factories_return_app_exception(self):
        factories = [
            AppError.PARAM, AppError.UNAUTHORIZED, AppError.FORBIDDEN,
            AppError.NOT_FOUND, AppError.CONFLICT, AppError.TOO_MANY,
            AppError.INTERNAL, AppError.LLM_TIMEOUT, AppError.FILE_ERROR,
        ]
        for factory in factories:
            exc = factory()
            assert isinstance(exc, AppException)
            assert isinstance(exc, HTTPException)

    def test_raisable(self):
        """AppException 应能被 raise/catch，行为与 HTTPException 一致。"""
        with pytest.raises(AppException) as exc_info:
            raise AppError.NOT_FOUND("用例")
        assert exc_info.value.status_code == 404

    def test_caught_as_http_exception(self):
        """由于继承关系，也可被 except HTTPException 捕获。"""
        with pytest.raises(HTTPException):
            raise AppError.INTERNAL()
