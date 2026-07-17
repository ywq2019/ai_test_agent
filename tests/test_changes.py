"""
本次改动专项验证测试（Task 1-8）
运行方式：python -m pytest tests/test_changes.py -v
"""
import asyncio
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# Task 2/3  后台任务计数器 + Semaphore 超时
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateSlot:
    def test_acquire_and_release(self):
        """正常获取并释放槽位"""
        from skills.ai_case_generator import (
            acquire_generate_slot, release_generate_slot,
            get_active_generate_count, _MAX_ACTIVE_GENERATE,
        )
        async def _run():
            assert get_active_generate_count() == 0
            ok = await acquire_generate_slot()
            assert ok is True
            assert get_active_generate_count() == 1
            await release_generate_slot()
            assert get_active_generate_count() == 0
        asyncio.run(_run())

    def test_max_limit_rejected(self):
        """超出上限时返回 False"""
        from skills.ai_case_generator import (
            acquire_generate_slot, release_generate_slot,
            get_active_generate_count, _MAX_ACTIVE_GENERATE,
        )
        async def _run():
            # 先把槽位占满
            for _ in range(_MAX_ACTIVE_GENERATE):
                ok = await acquire_generate_slot()
                assert ok is True
            # 超出应返回 False
            over = await acquire_generate_slot()
            assert over is False
            assert get_active_generate_count() == _MAX_ACTIVE_GENERATE
            # 清理
            for _ in range(_MAX_ACTIVE_GENERATE):
                await release_generate_slot()
            assert get_active_generate_count() == 0
        asyncio.run(_run())

    def test_release_never_negative(self):
        """多次 release 不会让计数变负数"""
        from skills.ai_case_generator import release_generate_slot, get_active_generate_count
        async def _run():
            await release_generate_slot()
            await release_generate_slot()
            assert get_active_generate_count() == 0
        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# Task 3  Semaphore 超时配置
# ─────────────────────────────────────────────────────────────────────────────

class TestSemaphoreTimeout:
    def test_timeout_config_positive(self):
        from skills.ai_case_generator import _LLM_SEM_TIMEOUT
        assert _LLM_SEM_TIMEOUT > 0

    def test_timeout_env_override(self):
        """环境变量能覆盖默认值"""
        import importlib, os
        os.environ["LLM_SEM_TIMEOUT"] = "99"
        import skills.ai_case_generator as m
        importlib.reload(m)
        assert m._LLM_SEM_TIMEOUT == 99
        os.environ.pop("LLM_SEM_TIMEOUT", None)
        importlib.reload(m)


# ─────────────────────────────────────────────────────────────────────────────
# Task 4  gen_progress 字段
# ─────────────────────────────────────────────────────────────────────────────

class TestGenProgress:
    def test_response_model_has_gen_progress(self):
        """AICaseFileResponse 包含 gen_progress 字段且默认 0"""
        import sys, importlib
        # 避免循环 import，直接解析源文件
        import ast, re
        src = open("api/routes/ai_cases.py", encoding="utf-8").read()
        assert "gen_progress: int = 0" in src, "Response model 缺少 gen_progress 字段"

    def test_database_model_has_gen_progress(self):
        """AICaseFile ORM 模型有 gen_progress 列"""
        src = open("tools/database.py", encoding="utf-8").read()
        assert "gen_progress" in src
        assert "INTEGER DEFAULT 0" in src or "gen_progress = Column(Integer" in src

    def test_alter_table_in_migration(self):
        """旧库迁移 ALTER TABLE 包含 gen_progress"""
        src = open("tools/database.py", encoding="utf-8").read()
        assert "gen_progress INTEGER DEFAULT 0" in src


# ─────────────────────────────────────────────────────────────────────────────
# Task 5  文件清理
# ─────────────────────────────────────────────────────────────────────────────

class TestFileCleanup:
    def test_delete_case_files_helper_exists(self):
        src = open("api/routes/ai_cases.py", encoding="utf-8").read()
        assert "def _delete_case_files" in src

    def test_delete_walks_parent_chain(self):
        """删除接口遍历 parent_id 链"""
        src = open("api/routes/ai_cases.py", encoding="utf-8").read()
        assert "parent_id" in src
        assert "ids_to_delete" in src

    def test_orphan_cleanup_in_main(self):
        src = open("main.py", encoding="utf-8").read()
        assert "_clean_orphan_case_files" in src
        assert "AI_CASES_DIR" in src

    def test_orphan_cleanup_called_on_startup(self):
        """启动时立即执行一次孤儿文件清理"""
        src = open("main.py", encoding="utf-8").read()
        assert "await _clean_orphan_case_files()" in src


# ─────────────────────────────────────────────────────────────────────────────
# Task 6  权限隔离
# ─────────────────────────────────────────────────────────────────────────────

class TestOwnerIsolation:
    def test_owner_filter_admin_returns_none(self):
        """admin 用户 owner_filter 返回 None（不过滤）"""
        from api.auth import owner_filter
        from tools.database import AICaseFile, User

        admin = User()
        admin.role = "admin"
        admin.username = "admin"

        result = owner_filter(AICaseFile, admin)
        assert result is None

    def test_owner_filter_user_returns_condition(self):
        """普通用户 owner_filter 返回非 None 条件"""
        from api.auth import owner_filter
        from tools.database import AICaseFile, User

        user = User()
        user.role = "user"
        user.username = "alice"

        result = owner_filter(AICaseFile, user)
        assert result is not None

    def test_check_owner_admin_passes(self):
        """admin 访问任何记录不抛异常"""
        from api.auth import check_owner
        from tools.database import AICaseFile, User

        admin = User()
        admin.role = "admin"
        admin.username = "admin"

        record = AICaseFile()
        record.created_by = "other_user"

        # 不应该抛出异常
        check_owner(record, admin, "AI用例")

    def test_check_owner_user_own_record_passes(self):
        """用户访问自己的记录不抛异常"""
        from api.auth import check_owner
        from tools.database import AICaseFile, User

        user = User()
        user.role = "user"
        user.username = "alice"

        record = AICaseFile()
        record.created_by = "alice"

        check_owner(record, user, "AI用例")

    def test_check_owner_user_null_created_by_passes(self):
        """created_by=NULL 的历史数据对所有人可见"""
        from api.auth import check_owner
        from tools.database import AICaseFile, User
        from fastapi import HTTPException

        user = User()
        user.role = "user"
        user.username = "alice"

        record = AICaseFile()
        record.created_by = None

        check_owner(record, user, "AI用例")  # 不应抛出

    def test_check_owner_user_other_record_raises_403(self):
        """普通用户访问他人数据抛出 403"""
        from api.auth import check_owner
        from tools.database import AICaseFile, User
        from fastapi import HTTPException

        user = User()
        user.role = "user"
        user.username = "alice"

        record = AICaseFile()
        record.created_by = "bob"

        with pytest.raises(HTTPException) as exc:
            check_owner(record, user, "AI用例")
        assert exc.value.status_code == 403

    def test_created_by_fields_in_db(self):
        """四张核心表都有 created_by 字段"""
        src = open("tools/database.py", encoding="utf-8").read()
        for table in ["TestTask", "AICaseFile", "ApiProject", "TestPlan"]:
            assert f"created_by" in src, f"{table} 缺少 created_by"
        assert src.count("created_by = Column") >= 4


# ─────────────────────────────────────────────────────────────────────────────
# Task 7  CI/CD Webhook
# ─────────────────────────────────────────────────────────────────────────────

class TestWebhook:
    def test_webhook_token_field_in_db(self):
        src = open("tools/database.py", encoding="utf-8").read()
        assert "webhook_token" in src
        assert "ALTER TABLE test_plans ADD COLUMN webhook_token" in src

    def test_trigger_endpoint_exists(self):
        src = open("api/routes/api_test.py", encoding="utf-8").read()
        assert "def trigger_test_plan" in src
        assert "token: str" in src
        assert "callback_url" in src

    def test_token_management_endpoints_exist(self):
        src = open("api/routes/api_test.py", encoding="utf-8").read()
        assert "def set_webhook_token" in src
        assert "def revoke_webhook_token" in src
        assert "secrets.token_urlsafe" in src

    def test_jwt_bypass_in_main(self):
        src = open("main.py", encoding="utf-8").read()
        assert "_WEBHOOK_PATTERNS" in src
        assert '"/trigger"' in src

    def test_callback_url_implemented(self):
        src = open("api/routes/api_test.py", encoding="utf-8").read()
        assert "callback_url" in src
        assert "_httpx.AsyncClient" in src
        assert "await _c.post(callback_url" in src

    def test_plan_dict_returns_webhook_token(self):
        src = open("api/routes/api_test.py", encoding="utf-8").read()
        assert '"webhook_token"' in src
        assert "p.webhook_token" in src

    def test_token_min_length_check(self):
        """token 长度检查，防止弱 token"""
        src = open("api/routes/api_test.py", encoding="utf-8").read()
        assert "len(new_token) < 16" in src


# ─────────────────────────────────────────────────────────────────────────────
# Task 8  PDF 导出
# ─────────────────────────────────────────────────────────────────────────────

class TestPdfExport:
    def test_pdf_exporter_module_importable(self):
        from tools.pdf_exporter import html_to_pdf
        assert callable(html_to_pdf)

    def test_html_to_pdf_raises_on_empty_input(self):
        from tools.pdf_exporter import html_to_pdf
        async def _run():
            with pytest.raises(ValueError, match="至少提供一个"):
                await html_to_pdf()
        asyncio.run(_run())

    def test_html_to_pdf_raises_on_missing_file(self):
        from tools.pdf_exporter import html_to_pdf
        async def _run():
            with pytest.raises(RuntimeError, match="HTML 文件不存在"):
                await html_to_pdf(html_path="/nonexistent/path/report.html")
        asyncio.run(_run())

    def test_html_str_mode_generates_pdf(self):
        """html_str 模式实际生成有效 PDF"""
        from tools.pdf_exporter import html_to_pdf
        html = """<!DOCTYPE html><html><head><meta charset="UTF-8">
        <title>Test</title></head><body><h1>PDF Test</h1>
        <p>验证 PDF 生成功能正常</p></body></html>"""
        async def _run():
            pdf = await html_to_pdf(html_str=html)
            # PDF 文件头是 %PDF-
            assert pdf[:4] == b"%PDF", "返回内容不是有效的 PDF"
            assert len(pdf) > 5000, f"PDF 过小({len(pdf)} bytes)，可能渲染失败"
            return pdf
        pdf = asyncio.run(_run())
        print(f"\n    PDF 大小: {len(pdf)} bytes")

    def test_webui_pdf_endpoint_registered(self):
        src = open("api/routes/webui.py", encoding="utf-8").read()
        assert '"/reports/{report_id}/pdf"' in src or "reports/{report_id}/pdf" in src
        assert "html_to_pdf" in src
        assert "application/pdf" in src

    def test_api_report_pdf_endpoint_registered(self):
        src = open("api/routes/api_test.py", encoding="utf-8").read()
        assert "/api-test/reports/{report_id}/pdf" in src
        assert "/test-plans/reports/{report_id}/pdf" in src

    def test_pdf_uses_a4_format(self):
        src = open("tools/pdf_exporter.py", encoding="utf-8").read()
        assert 'format="A4"' in src

    def test_tmp_file_cleanup(self):
        """html_str 模式用完临时文件后清理"""
        src = open("tools/pdf_exporter.py", encoding="utf-8").read()
        assert "unlink(missing_ok=True)" in src
        assert "finally:" in src

    def test_pdf_endpoint_in_main_download_whitelist(self):
        """PDF / export 接口是浏览器直跳下载，必须在 _DOWNLOAD_PATTERNS 白名单里"""
        main_src = open("main.py", encoding="utf-8").read()
        assert '"/download"' in main_src
        assert '"/export"' in main_src   # 导出 HTML 报告
        assert '"/pdf"' in main_src      # 导出 PDF 报告


# ─────────────────────────────────────────────────────────────────────────────
# Task 1  重启状态修复
# ─────────────────────────────────────────────────────────────────────────────

class TestRestartRecovery:
    def test_startup_scans_generating_status(self):
        src = open("main.py", encoding="utf-8").read()
        assert 'gen_status == "generating"' in src
        assert 'gen_status="failed"' in src or "gen_status = 'failed'" in src or 'values(gen_status="failed")' in src

    def test_startup_sends_ws_notification(self):
        src = open("main.py", encoding="utf-8").read()
        assert "服务重启" in src
        assert "ws_manager.broadcast" in src

    def test_returning_sql_update(self):
        """用 RETURNING 一次查出所有被重置的 id"""
        src = open("main.py", encoding="utf-8").read()
        assert ".returning(" in src


# ─────────────────────────────────────────────────────────────────────────────
# IP 限流
# ─────────────────────────────────────────────────────────────────────────────

class TestIpLimiter:
    def test_get_real_ip_prefers_x_real_ip(self):
        from api.limiter import _get_real_ip

        class FakeRequest:
            class headers:
                _h = {"X-Real-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"}
                @classmethod
                def get(cls, k, d=""):
                    return cls._h.get(k, d)
            class client:
                host = "127.0.0.1"

        assert _get_real_ip(FakeRequest()) == "1.2.3.4"

    def test_get_real_ip_falls_back_to_forwarded_for(self):
        from api.limiter import _get_real_ip

        class FakeRequest:
            class headers:
                _h = {"X-Forwarded-For": "9.8.7.6, 10.0.0.1"}
                @classmethod
                def get(cls, k, d=""):
                    return cls._h.get(k, d)
            class client:
                host = "127.0.0.1"

        assert _get_real_ip(FakeRequest()) == "9.8.7.6"

    def test_get_real_ip_falls_back_to_tcp(self):
        from api.limiter import _get_real_ip

        class FakeRequest:
            class headers:
                @classmethod
                def get(cls, k, d=""):
                    return d
            class client:
                host = "192.168.1.5"

        assert _get_real_ip(FakeRequest()) == "192.168.1.5"
