"""
api_executor 单元测试
覆盖：断言逻辑（_run_assertions / _eval_json_path / _flexible_equal / _jsonpath_get）
"""
import pytest
from unittest.mock import MagicMock


# ── 工具：构造假 Response ──────────────────────────────────────────────────────

def _make_resp(status_code: int, json_data: dict = None, text: str = ""):
    """构造一个最小化的模拟 httpx.Response。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = Exception("not json")
    return resp


def _executor():
    from skills.api_executor import ApiExecutor
    return ApiExecutor()


# ── _flexible_equal ───────────────────────────────────────────────────────────

def test_flexible_equal_exact():
    ex = _executor()
    assert ex._flexible_equal(1, 1)
    assert ex._flexible_equal("a", "a")


def test_flexible_equal_str_vs_int():
    ex = _executor()
    assert ex._flexible_equal(0, "0")
    assert ex._flexible_equal("1", 1)


def test_flexible_equal_float_str():
    ex = _executor()
    assert ex._flexible_equal(1.5, "1.5")
    assert ex._flexible_equal("2.0", 2.0)


def test_flexible_equal_mismatch():
    ex = _executor()
    assert not ex._flexible_equal(1, 2)
    assert not ex._flexible_equal("a", "b")


# ── _jsonpath_get ─────────────────────────────────────────────────────────────

def test_jsonpath_get_simple():
    ex = _executor()
    data = {"code": 0, "msg": "ok"}
    assert ex._jsonpath_get(data, "$.code") == 0
    assert ex._jsonpath_get(data, "$.msg") == "ok"


def test_jsonpath_get_nested():
    ex = _executor()
    data = {"data": {"user": {"id": 42}}}
    assert ex._jsonpath_get(data, "$.data.user.id") == 42


def test_jsonpath_get_array_index():
    ex = _executor()
    data = {"items": [10, 20, 30]}
    assert ex._jsonpath_get(data, "$.items[0]") == 10
    assert ex._jsonpath_get(data, "$.items[2]") == 30


def test_jsonpath_get_missing_key():
    ex = _executor()
    data = {"code": 0}
    with pytest.raises((KeyError, TypeError)):
        ex._jsonpath_get(data, "$.missing")


# ── _run_assertions ───────────────────────────────────────────────────────────

def test_run_assertions_status_code_pass():
    ex = _executor()
    resp = _make_resp(200)
    results = ex._run_assertions(resp, 100, [{"type": "status_code", "expected": 200}])
    assert len(results) == 1
    assert results[0]["passed"] is True


def test_run_assertions_status_code_fail():
    ex = _executor()
    resp = _make_resp(404)
    results = ex._run_assertions(resp, 100, [{"type": "status_code", "expected": 200}])
    assert results[0]["passed"] is False
    assert results[0]["actual"] == 404


def test_run_assertions_response_time_pass():
    ex = _executor()
    resp = _make_resp(200, {})
    results = ex._run_assertions(resp, 500, [{"type": "response_time", "max_ms": 1000}])
    assert results[0]["passed"] is True


def test_run_assertions_response_time_fail():
    ex = _executor()
    resp = _make_resp(200, {})
    results = ex._run_assertions(resp, 2000, [{"type": "response_time", "max_ms": 1000}])
    assert results[0]["passed"] is False


def test_run_assertions_empty_uses_2xx_fallback():
    """没有断言规则时，默认检查 2xx。"""
    ex = _executor()
    resp = _make_resp(200, {})
    results = ex._run_assertions(resp, 100, [])
    assert results[0]["passed"] is True

    resp2 = _make_resp(500, {})
    results2 = ex._run_assertions(resp2, 100, [])
    assert results2[0]["passed"] is False


# ── _eval_json_path ───────────────────────────────────────────────────────────

def test_eval_json_path_equals_pass():
    ex = _executor()
    resp = _make_resp(200, {"code": 0, "msg": "success"})
    a = {"type": "json_path", "path": "$.code", "expected": 0, "match_type": "equals"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is True
    assert r["actual"] == 0


def test_eval_json_path_equals_fail():
    ex = _executor()
    resp = _make_resp(200, {"code": 1})
    a = {"type": "json_path", "path": "$.code", "expected": 0, "match_type": "equals"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is False


def test_eval_json_path_contains():
    ex = _executor()
    resp = _make_resp(200, {"msg": "hello world"})
    a = {"type": "json_path", "path": "$.msg", "expected": "hello", "match_type": "contains"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is True


def test_eval_json_path_exists():
    ex = _executor()
    resp = _make_resp(200, {"token": "abc"})
    a = {"type": "json_path", "path": "$.token", "expected": None, "match_type": "exists"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is True


def test_eval_json_path_not_exists():
    ex = _executor()
    resp = _make_resp(200, {"code": 0})
    a = {"type": "json_path", "path": "$.token", "expected": None, "match_type": "not_exists"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is True


def test_eval_json_path_not_empty_pass():
    ex = _executor()
    resp = _make_resp(200, {"list": [1, 2, 3]})
    a = {"type": "json_path", "path": "$.list", "expected": None, "match_type": "not_empty"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is True


def test_eval_json_path_not_empty_fail():
    ex = _executor()
    resp = _make_resp(200, {"list": []})
    a = {"type": "json_path", "path": "$.list", "expected": None, "match_type": "not_empty"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is False


def test_eval_json_path_type_string():
    ex = _executor()
    resp = _make_resp(200, {"name": "alice"})
    a = {"type": "json_path", "path": "$.name", "expected": "string", "match_type": "type"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is True


def test_eval_json_path_type_number():
    ex = _executor()
    resp = _make_resp(200, {"count": 42})
    a = {"type": "json_path", "path": "$.count", "expected": "number", "match_type": "type"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is True


def test_eval_json_path_type_mismatch():
    ex = _executor()
    resp = _make_resp(200, {"flag": True})
    a = {"type": "json_path", "path": "$.flag", "expected": "string", "match_type": "type"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is False


def test_eval_json_path_regex_pass():
    ex = _executor()
    resp = _make_resp(200, {"phone": "13812345678"})
    a = {"type": "json_path", "path": "$.phone", "expected": r"^1\d{10}$", "match_type": "regex"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is True


def test_eval_json_path_regex_fail():
    ex = _executor()
    resp = _make_resp(200, {"phone": "not_a_phone"})
    a = {"type": "json_path", "path": "$.phone", "expected": r"^1\d{10}$", "match_type": "regex"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is False


def test_eval_json_path_non_json_response():
    ex = _executor()
    resp = _make_resp(200)   # json() 会抛 Exception
    a = {"type": "json_path", "path": "$.code", "expected": 0, "match_type": "equals"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is False
    assert "响应非JSON" in r.get("error", "")


def test_eval_json_path_missing_field():
    ex = _executor()
    resp = _make_resp(200, {"other": 1})
    a = {"type": "json_path", "path": "$.code", "expected": 0, "match_type": "equals"}
    r = ex._eval_json_path(resp, a)
    assert r["passed"] is False
    assert r["actual"] is None
