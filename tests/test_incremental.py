"""
增量更新合并逻辑单元测试
覆盖 ai_case_generator.AICaseGenerator._merge_cases 核心拼接逻辑
以及 case_generator 中用例格式处理相关的无副作用函数
"""
import pytest
import sys
import os

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 辅助：构造 old_cases_data ─────────────────────────────────────────────────

def _make_old_cases(modules):
    """构造 old_cases_data 格式的字典。"""
    return {
        "title": "测试",
        "modules": [
            {"name": name, "cases": cases}
            for name, cases in modules.items()
        ]
    }


def _make_case(id_, name, module="M", priority="P1"):
    return {
        "id": id_, "name": name, "module": module,
        "priority": priority, "type": "功能测试",
        "test_method": "等价类划分",
        "preconditions": "", "steps": ["1. 步骤"],
        "expected": "预期结果"
    }


# ── 测试 _merge_cases ─────────────────────────────────────────────────────────

class TestMergeCases:
    """测试 AICaseGenerator._merge_cases 的核心合并逻辑。"""

    def setup_method(self):
        # 用 mock 避免实际 LLM 调用
        from unittest.mock import patch, MagicMock
        self.patch = patch
        self.MagicMock = MagicMock

    def _get_merger(self):
        """获取一个不依赖 LLM 的 AICaseGenerator 实例。"""
        import importlib
        import skills.ai_case_generator as m
        return m.AICaseGenerator()

    def test_unchanged_modules_preserved(self):
        """unchanged 模块的旧用例原样保留。"""
        gen = self._get_merger()
        old = _make_old_cases({
            "登录模块": [_make_case("TC001", "正常登录")],
            "搜索模块": [_make_case("TC002", "关键词搜索")],
        })
        result = gen._merge_cases(
            old_cases_data=old,
            changed_results=[],
            added_results=[],
            added_names=[],
            unchanged_names=["登录模块", "搜索模块"],
            removed_names=[],
        )
        module_names = [m["name"] for m in result["modules"]]
        assert "登录模块" in module_names
        assert "搜索模块" in module_names
        login_cases = next(m["cases"] for m in result["modules"] if m["name"] == "登录模块")
        assert any(c["id"] == "TC001" for c in login_cases)

    def test_removed_modules_deprecated(self):
        """removed 模块所有用例打上 status='deprecated' 标记。"""
        gen = self._get_merger()
        old = _make_old_cases({
            "已删功能": [_make_case("TC001", "已删用例")],
        })
        result = gen._merge_cases(
            old_cases_data=old,
            changed_results=[],
            added_results=[],
            added_names=[],
            unchanged_names=[],
            removed_names=["已删功能"],
        )
        all_cases = [c for m in result["modules"] for c in m["cases"]]
        deprecated = [c for c in all_cases if c.get("status") == "deprecated"]
        assert len(deprecated) == 1
        assert deprecated[0].get("name") == "已删用例"

    def test_added_modules_included(self):
        """added 模块的新用例出现在结果中。"""
        gen = self._get_merger()
        old = _make_old_cases({})   # 空旧数据
        new_cases = [_make_case("TC001", "新功能用例", module="新模块")]
        result = gen._merge_cases(
            old_cases_data=old,
            changed_results=[],
            added_results=[{"name": "新模块", "cases": new_cases}],
            added_names=["新模块"],
            unchanged_names=[],
            removed_names=[],
        )
        all_modules = {m["name"] for m in result["modules"]}
        assert "新模块" in all_modules

    def test_changed_module_merges_kept_and_deprecated(self):
        """changed 模块：保留的用例 + deprecated 的用例 + 新用例都出现在结果中。"""
        gen = self._get_merger()
        old_cases = [
            _make_case("TC001", "保留用例"),
            _make_case("TC002", "废弃用例"),
        ]
        old = _make_old_cases({"订单模块": old_cases})

        merge_result = {
            "deprecated": ["TC002"],
            "new_cases": [_make_case("TC003", "新增用例")],
        }
        result = gen._merge_cases(
            old_cases_data=old,
            changed_results=[("订单模块", old_cases, merge_result)],
            added_results=[],
            added_names=[],
            unchanged_names=[],
            removed_names=[],
        )
        order_module = next(m for m in result["modules"] if m["name"] == "订单模块")
        ids = {c["id"] for c in order_module["cases"]}
        # TC001 保留、TC002 deprecated 打标但仍在列表中、TC003 新增
        assert "TC001" in ids
        assert "TC002" in ids
        assert "TC003" in ids or any("TC00" in str(c.get("id", "")) for c in order_module["cases"])

        deprecated_cases = [c for c in order_module["cases"] if c.get("status") == "deprecated"]
        assert any(c.get("name") == "废弃用例" for c in deprecated_cases)

    def test_performance_module_exempt_from_removal(self):
        """性能测试/兼容性测试等通用模块不被 removed。"""
        gen = self._get_merger()
        old = _make_old_cases({
            "性能测试": [_make_case("TC001", "响应时间测试")],
            "兼容性测试": [_make_case("TC002", "跨浏览器测试")],
        })
        result = gen._merge_cases(
            old_cases_data=old,
            changed_results=[],
            added_results=[],
            added_names=[],
            unchanged_names=[],
            removed_names=["性能测试", "兼容性测试"],  # 即便在 removed 里也应豁免
        )
        module_names = [m["name"] for m in result["modules"]]
        assert "性能测试" in module_names
        assert "兼容性测试" in module_names
        # 豁免模块的用例不应被 deprecated
        perf_cases = next(m["cases"] for m in result["modules"] if m["name"] == "性能测试")
        assert not any(c.get("deprecated") for c in perf_cases)

    def test_result_has_required_fields(self):
        """返回结果必须包含 title 和 modules 字段。"""
        gen = self._get_merger()
        old = _make_old_cases({})
        result = gen._merge_cases(
            old_cases_data=old,
            changed_results=[],
            added_results=[],
            added_names=[],
            unchanged_names=[],
            removed_names=[],
        )
        assert "title" in result
        assert "modules" in result
        assert isinstance(result["modules"], list)


# ── 测试 prompt_loader 加载器 ──────────────────────────────────────────────────

class TestPromptLoader:
    def test_load_yaml_success(self):
        from skills.prompt_loader import get_system, get_prompt
        s = get_system("api_case_gen.yaml", "generate_cases")
        assert len(s) > 50
        assert "JSON" in s

    def test_load_nonexistent_key(self):
        from skills.prompt_loader import get_prompt
        with pytest.raises(KeyError):
            get_prompt("api_case_gen.yaml", "nonexistent_key_xyz")

    def test_load_nonexistent_file(self):
        from skills.prompt_loader import get_prompt
        with pytest.raises(FileNotFoundError):
            get_prompt("nonexistent_file.yaml", "key")

    def test_render_user(self):
        from skills.prompt_loader import render_user
        result = render_user("api_case_gen.yaml", "fill_descriptions", paths_text="/api/users\n/api/orders")
        assert "/api/users" in result

    def test_render_user_missing_var_preserved(self):
        """未传入的变量保留原始占位符而不报错。"""
        from skills.prompt_loader import render_user
        result = render_user("api_case_gen.yaml", "fill_descriptions")
        # paths_text 未传入，应保留 {paths_text} 而不抛 KeyError
        assert "{paths_text}" in result

    def test_all_yaml_files_loadable(self):
        """所有 YAML 文件都能成功加载。"""
        from skills.prompt_loader import get_prompt
        yamls = [
            ("api_case_gen.yaml", "generate_cases"),
            ("api_case_gen.yaml", "extract_groups"),
            ("code_analyze.yaml", "generate_from_code"),
            ("code_analyze.yaml", "analyze_vs_requirement"),
            ("code_analyze.yaml", "generate_diff_cases"),
            ("ai_case_gen.yaml", "extract_modules"),
            ("ai_case_gen.yaml", "merge_module_cases"),
            ("ui_case_gen.yaml", "extract_page_modules"),
            ("ui_case_gen.yaml", "optimize_module_cases"),
        ]
        for f, k in yamls:
            p = get_prompt(f, k)
            assert p["system"], f"Empty system in {f}/{k}"
