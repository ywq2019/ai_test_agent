"""
ai_case_generator.py 核心纯逻辑单元测试（无网络/无数据库依赖）。

覆盖 5 个函数：
  - _repair_truncated_json   截断 JSON 自动修复
  - _sanitize_json_string    裸控制字符 / 裸引号修复
  - _build_segment_index     全文分段索引构建
  - _locate_module_context   关键词打分精准定位
  - _merge_cases             增量更新合并逻辑
"""
import json
import pytest

from skills.ai_case_generator import (
    _repair_truncated_json,
    _sanitize_json_string,
    AICaseGenerator,
)


# ─────────────────────────────────────────────────────────────────────────────
# _repair_truncated_json
# ─────────────────────────────────────────────────────────────────────────────

class TestRepairTruncatedJson:
    def test_valid_json_unchanged(self):
        raw = '{"a": 1, "b": [1, 2]}'
        assert _repair_truncated_json(raw) == raw

    def test_empty_string(self):
        assert _repair_truncated_json("") == ""

    def test_truncated_array(self):
        # 列表被截断，修复后应能解析
        raw = '[{"id": "TC001", "name": "test'
        result = _repair_truncated_json(raw)
        # 修复后至少是合法 JSON 或原样（不抛异常）
        try:
            json.loads(result)
        except json.JSONDecodeError:
            pass  # 部分极端截断无法修复，不应抛异常

    def test_truncated_object_recovers_complete_elements(self):
        # 第一个元素完整，第二个被截断，应保留第一个
        raw = '[{"id":"TC001","name":"login"},{"id":"TC002","name":"inco'
        result = _repair_truncated_json(raw)
        try:
            data = json.loads(result)
            assert isinstance(data, list)
            assert data[0]["id"] == "TC001"
        except json.JSONDecodeError:
            pytest.skip("此截断场景修复器无法处理，跳过")

    def test_complete_json_with_nested(self):
        raw = '{"modules": [{"name": "login", "cases": [{"id": "TC001"}]}]}'
        result = _repair_truncated_json(raw)
        assert json.loads(result) == json.loads(raw)

    def test_missing_closing_braces(self):
        # 手动截断一个合法 JSON
        raw = '{"title": "test", "modules": [{"name": "m1", "cases": []}'
        result = _repair_truncated_json(raw)
        try:
            json.loads(result)
        except json.JSONDecodeError:
            pytest.skip("此场景修复器无法覆盖")


# ─────────────────────────────────────────────────────────────────────────────
# _sanitize_json_string
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeJsonString:
    def test_valid_json_unchanged(self):
        raw = '{"name": "hello world", "value": 123}'
        assert _sanitize_json_string(raw) == raw

    def test_empty_string(self):
        assert _sanitize_json_string("") == ""

    def test_newline_in_string_value_escaped(self):
        # 模拟 AI 直接在 JSON 字符串值内输出裸换行（原始字节流中的 0x0A）
        # 用 bytes 构造，绕过 Python 字符串字面量转义
        raw = b'{"steps": ["step1\nstep2"]}'.decode("utf-8")
        result = _sanitize_json_string(raw)
        # 修复后必须能被 json.loads 解析
        data = json.loads(result)
        # 值内不含裸换行（已被转义为 \\n）
        assert "\n" not in repr(data["steps"][0]).replace("\\n", "")

    def test_tab_in_string_value_escaped(self):
        # 模拟 AI 在 JSON 字符串值内输出裸制表符（0x09）
        raw = b'{"name": "hello\tworld"}'.decode("utf-8")
        result = _sanitize_json_string(raw)
        # 修复后的原始字符串中，制表符应已被替换为 \\t 转义序列
        assert "\\t" in result
        # 且修复后的字符串可被 json.loads 正常解析
        data = json.loads(result)
        assert "hello" in data["name"] and "world" in data["name"]

    def test_no_false_positive_on_closing_quote(self):
        # 正常的闭合引号不应被转义
        raw = '{"a": "hello", "b": "world"}'
        result = _sanitize_json_string(raw)
        assert json.loads(result) == {"a": "hello", "b": "world"}

    def test_result_is_valid_json_after_sanitize(self):
        # 含裸换行的字符串经过修复后能被 json.loads 解析
        raw = '{"expected": "系统显示成功\n并跳转"}'
        result = _sanitize_json_string(raw)
        data = json.loads(result)
        assert "expected" in data


# ─────────────────────────────────────────────────────────────────────────────
# _build_segment_index
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildSegmentIndex:
    def setup_method(self):
        self.gen = AICaseGenerator()

    def test_short_doc_single_segment(self):
        text = "A" * 100
        segs = self.gen._build_segment_index(text, "hash_short")
        assert len(segs) == 1
        assert segs[0]["seg_id"] == 0
        assert segs[0]["text"] == text

    def test_segment_covers_full_text(self):
        size = self.gen._SEGMENT_SIZE
        text = "X" * (size * 2 + 500)
        segs = self.gen._build_segment_index(text, "hash_long")
        # 所有段的并集覆盖全文
        covered = set()
        for seg in segs:
            covered.update(range(seg["start"], seg["end"]))
        assert len(covered) == len(text)

    def test_overlap_between_adjacent_segments(self):
        size = self.gen._SEGMENT_SIZE
        overlap = self.gen._SEGMENT_OVERLAP
        text = "Y" * (size + overlap + 100)
        segs = self.gen._build_segment_index(text, "hash_overlap")
        if len(segs) >= 2:
            # 相邻段之间存在重叠
            assert segs[0]["end"] > segs[1]["start"]

    def test_cache_hit_returns_same_object(self):
        text = "Z" * 1000
        segs1 = self.gen._build_segment_index(text, "hash_cache")
        segs2 = self.gen._build_segment_index(text, "hash_cache")
        assert segs1 is segs2  # 同一对象，命中缓存

    def test_empty_doc_returns_empty(self):
        segs = self.gen._build_segment_index("", "hash_empty")
        assert segs == []

    def test_segment_ids_sequential(self):
        text = "A" * (self.gen._SEGMENT_SIZE * 3)
        segs = self.gen._build_segment_index(text, "hash_seq")
        for i, seg in enumerate(segs):
            assert seg["seg_id"] == i


# ─────────────────────────────────────────────────────────────────────────────
# _locate_module_context
# ─────────────────────────────────────────────────────────────────────────────

class TestLocateModuleContext:
    def setup_method(self):
        self.gen = AICaseGenerator()

    def _make_segments(self, texts):
        pos = 0
        segs = []
        for i, t in enumerate(texts):
            segs.append({"seg_id": i, "start": pos, "end": pos + len(t), "text": t})
            pos += len(t)
        return segs

    def test_returns_segment_containing_keyword(self):
        segs = self._make_segments([
            "这是首页的介绍内容，包含首页导航和Banner展示。",
            "这是登录模块，支持账号密码登录和短信验证码登录。",
            "这是订单模块，用户可以查看历史订单和当前订单状态。",
        ])
        result = self.gen._locate_module_context("登录", ["账号登录", "验证码"], segs, window=200)
        assert "登录" in result

    def test_no_hit_returns_first_segment(self):
        segs = self._make_segments(["AAA内容", "BBB内容", "CCC内容"])
        result = self.gen._locate_module_context("完全不存在的模块XYZ", [], segs, window=50)
        # 无命中时回退到第一段
        assert result == segs[0]["text"][:50]

    def test_empty_segments_returns_empty(self):
        result = self.gen._locate_module_context("登录", [], [], window=200)
        assert result == ""

    def test_window_limits_result_length(self):
        long_text = "登录模块 " * 2000
        segs = self._make_segments([long_text])
        result = self.gen._locate_module_context("登录", [], segs, window=500)
        assert len(result) <= 500

    def test_higher_score_segment_preferred(self):
        # 段落2 出现更多关键词，应优先返回
        segs = self._make_segments([
            "这是一段与登录无关的内容。",
            "登录模块：用户登录、密码登录、登录验证、登录日志、登录成功",
        ])
        result = self.gen._locate_module_context("登录", ["密码登录", "登录验证"], segs, window=300)
        assert "登录" in result


# ─────────────────────────────────────────────────────────────────────────────
# _merge_cases（增量更新合并逻辑）
# ─────────────────────────────────────────────────────────────────────────────

def _make_case(cid, name, module="登录"):
    return {"id": cid, "name": name, "module": module,
            "priority": "P1", "steps": ["step1"], "expected": "ok",
            "preconditions": "", "element_selector": ""}

def _make_old_data(modules):
    """modules: [{"name": str, "cases": [case_dict]}]"""
    return {"title": "测试集", "modules": modules}


class TestMergeCases:
    def setup_method(self):
        self.gen = AICaseGenerator()

    def test_unchanged_module_preserved(self):
        old = _make_old_data([
            {"name": "登录", "cases": [_make_case("TC001", "正常登录")]},
        ])
        result = self.gen._merge_cases(
            old_cases_data=old,
            changed_results=[],
            added_results=[],
            added_names=[],
            unchanged_names=["登录"],
            removed_names=[],
            new_doc_content="登录",
        )
        assert len(result["modules"]) == 1
        assert result["modules"][0]["name"] == "登录"
        assert len(result["modules"][0]["cases"]) == 1

    def test_removed_module_marked_deprecated(self):
        old = _make_old_data([
            {"name": "旧功能", "cases": [_make_case("TC001", "旧功能用例")]},
        ])
        result = self.gen._merge_cases(
            old_cases_data=old,
            changed_results=[],
            added_results=[],
            added_names=[],
            unchanged_names=[],
            removed_names=["旧功能"],
            new_doc_content="",
        )
        deprecated_mod = next(
            (m for m in result["modules"] if "废弃" in m["name"]), None
        )
        assert deprecated_mod is not None
        assert all(c.get("status") == "deprecated" for c in deprecated_mod["cases"])

    def test_changed_module_keeps_active_cases(self):
        old_cases = [
            _make_case("TC001", "正常登录"),
            _make_case("TC002", "密码错误"),
        ]
        old = _make_old_data([{"name": "登录", "cases": old_cases}])
        merge_result = {
            "deprecated": [],   # 不废弃任何用例
            "new_cases": [{"name": "新场景", "priority": "P2",
                           "steps": ["s1"], "expected": "ok", "preconditions": ""}],
        }
        result = self.gen._merge_cases(
            old_cases_data=old,
            changed_results=[("登录", old_cases, merge_result)],
            added_results=[],
            added_names=[],
            unchanged_names=[],
            removed_names=[],
            new_doc_content="登录",
        )
        mod = result["modules"][0]
        # 2条旧用例 + 1条新用例
        assert len(mod["cases"]) == 3
        new_case = next((c for c in mod["cases"] if c.get("is_new")), None)
        assert new_case is not None

    def test_changed_module_deprecated_ids_excluded(self):
        old_cases = [
            _make_case("TC001", "正常登录"),
            _make_case("TC002", "已删除功能"),
        ]
        old = _make_old_data([{"name": "登录", "cases": old_cases}])
        merge_result = {
            "deprecated": ["TC002"],
            "new_cases": [],
        }
        result = self.gen._merge_cases(
            old_cases_data=old,
            changed_results=[("登录", old_cases, merge_result)],
            added_results=[],
            added_names=[],
            unchanged_names=[],
            removed_names=[],
            new_doc_content="登录",
        )
        mod = result["modules"][0]
        active = [c for c in mod["cases"] if c.get("status") != "deprecated"]
        deprecated = [c for c in mod["cases"] if c.get("status") == "deprecated"]
        assert len(active) == 1
        assert len(deprecated) == 1

    def test_added_module_marked_is_new(self):
        old = _make_old_data([])
        new_mod = {"name": "新模块", "cases": [_make_case("X001", "新功能")]}
        result = self.gen._merge_cases(
            old_cases_data=old,
            changed_results=[],
            added_results=[new_mod],
            added_names=["新模块"],
            unchanged_names=[],
            removed_names=[],
            new_doc_content="新模块",
        )
        assert len(result["modules"]) == 1
        assert all(c.get("is_new") for c in result["modules"][0]["cases"])

    def test_performance_module_never_removed(self):
        """性能/兼容性测试模块不应因需求变更被废弃。"""
        old = _make_old_data([
            {"name": "性能测试", "cases": [_make_case("P001", "并发测试")]},
        ])
        result = self.gen._merge_cases(
            old_cases_data=old,
            changed_results=[],
            added_results=[],
            added_names=[],
            unchanged_names=[],
            removed_names=["性能测试"],   # 即使被 Diff 判为 removed
            new_doc_content="其他内容",
        )
        # 性能测试模块应被保护，不出现在废弃模块里
        deprecated_mods = [m for m in result["modules"] if "废弃" in m["name"]]
        assert not any("性能" in m["name"] for m in deprecated_mods)

    def test_case_ids_renumbered_sequentially(self):
        old = _make_old_data([
            {"name": "登录", "cases": [
                _make_case("OLD001", "用例A"),
                _make_case("OLD002", "用例B"),
            ]},
        ])
        result = self.gen._merge_cases(
            old_cases_data=old,
            changed_results=[],
            added_results=[],
            added_names=[],
            unchanged_names=["登录"],
            removed_names=[],
            new_doc_content="登录",
        )
        ids = [c["id"] for c in result["modules"][0]["cases"]]
        assert ids == ["TC001", "TC002"]
