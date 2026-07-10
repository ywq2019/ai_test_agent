"""
param_resolver 单元测试
覆盖：变量替换、内置函数、自定义脚本函数、递归解析
"""
import pytest
import re


# ── 测试 _apply_fn 内置函数 ────────────────────────────────────────────────────

def test_apply_fn_timestamp():
    from skills.param_resolver import _apply_fn
    result = _apply_fn("timestamp", "")
    assert result.isdigit()
    assert int(result) > 1_700_000_000   # 2023 年后


def test_apply_fn_timestamp_ms():
    from skills.param_resolver import _apply_fn
    result = _apply_fn("timestamp_ms", "")
    assert result.isdigit()
    assert int(result) > 1_700_000_000_000


def test_apply_fn_uuid():
    from skills.param_resolver import _apply_fn
    result = _apply_fn("uuid", "")
    assert re.match(r"[0-9a-f-]{36}", result)


def test_apply_fn_random_int_default():
    from skills.param_resolver import _apply_fn
    result = _apply_fn("random_int", "")
    assert 0 <= int(result) <= 9999


def test_apply_fn_random_int_range():
    from skills.param_resolver import _apply_fn
    for _ in range(20):
        result = int(_apply_fn("random_int", "5, 10"))
        assert 5 <= result <= 10


def test_apply_fn_random_str_default():
    from skills.param_resolver import _apply_fn
    result = _apply_fn("random_str", "")
    assert len(result) == 8
    assert result.isalnum()


def test_apply_fn_random_str_length():
    from skills.param_resolver import _apply_fn
    result = _apply_fn("random_str", "16")
    assert len(result) == 16


def test_apply_fn_random_phone():
    from skills.param_resolver import _apply_fn
    result = _apply_fn("random_phone", "")
    assert len(result) == 11
    assert result.isdigit()


def test_apply_fn_base64():
    from skills.param_resolver import _apply_fn
    import base64
    result = _apply_fn("base64", "hello")
    assert result == base64.b64encode(b"hello").decode()


def test_apply_fn_md5():
    from skills.param_resolver import _apply_fn
    import hashlib
    result = _apply_fn("md5", "hello")
    assert result == hashlib.md5(b"hello").hexdigest()


def test_apply_fn_upper():
    from skills.param_resolver import _apply_fn
    assert _apply_fn("upper", "hello") == "HELLO"


def test_apply_fn_lower():
    from skills.param_resolver import _apply_fn
    assert _apply_fn("lower", "WORLD") == "world"


def test_apply_fn_unknown():
    from skills.param_resolver import _apply_fn
    result = _apply_fn("nonexistent_fn", "arg1")
    assert "nonexistent_fn" in result   # 原样保留占位符


# ── 测试 resolve_str 变量替换 ─────────────────────────────────────────────────

def test_resolve_str_no_placeholder():
    from skills.param_resolver import resolve_str
    assert resolve_str("hello world") == "hello world"


def test_resolve_str_local_var():
    from skills.param_resolver import resolve_str
    result = resolve_str("{{var:token}}", var_store={"token": "abc123"})
    assert result == "abc123"


def test_resolve_str_local_var_missing():
    from skills.param_resolver import resolve_str
    result = resolve_str("{{var:missing}}", var_store={})
    assert "missing" in result   # 未找到则原样保留


def test_resolve_str_builtin_fn():
    from skills.param_resolver import resolve_str
    result = resolve_str("{{uuid()}}")
    assert re.match(r"[0-9a-f-]{36}", str(result))


def test_resolve_str_mixed():
    from skills.param_resolver import resolve_str
    result = resolve_str("Bearer {{var:token}}", var_store={"token": "my_token"})
    assert result == "Bearer my_token"


def test_resolve_str_json_type_inference():
    """整体是占位符时应做类型推断：返回 int 而非字符串。"""
    from skills.param_resolver import resolve_str
    result = resolve_str("{{var:count}}", var_store={"count": "42"})
    # resolve_str 对整体占位符做 json.loads，"42" → 42
    assert result == 42


def test_resolve_str_no_inference_when_mixed():
    """混合字符串不做类型推断，保持字符串。"""
    from skills.param_resolver import resolve_str
    result = resolve_str("count={{var:count}}", var_store={"count": "42"})
    assert result == "count=42"
    assert isinstance(result, str)


# ── 测试 resolve_obj 递归解析 ─────────────────────────────────────────────────

def test_resolve_obj_dict():
    from skills.param_resolver import resolve_obj
    obj = {"key": "{{var:name}}", "nested": {"val": "{{var:x}}"}}
    result = resolve_obj(obj, var_store={"name": "alice", "x": "99"})
    assert result == {"key": "alice", "nested": {"val": 99}}


def test_resolve_obj_list():
    from skills.param_resolver import resolve_obj
    obj = ["{{var:a}}", "{{var:b}}", "plain"]
    result = resolve_obj(obj, var_store={"a": "1", "b": "2"})
    assert result == [1, 2, "plain"]


def test_resolve_obj_passthrough():
    from skills.param_resolver import resolve_obj
    assert resolve_obj(42) == 42
    assert resolve_obj(None) is None
    assert resolve_obj(True) is True


# ── 测试 _exec_custom_fn 自定义脚本 ──────────────────────────────────────────

def test_custom_fn_named_function():
    from skills.param_resolver import _exec_custom_fn
    scripts = [{"name": "add", "code": "def add(*args): return int(args[0]) + int(args[1])"}]
    result = _exec_custom_fn("add", "3, 4", scripts)
    assert result == "7"


def test_custom_fn_result_variable():
    from skills.param_resolver import _exec_custom_fn
    scripts = [{"name": "greet", "code": "result = 'hello'"}]
    result = _exec_custom_fn("greet", "", scripts)
    assert result == "hello"


def test_custom_fn_not_found():
    from skills.param_resolver import _exec_custom_fn
    result = _exec_custom_fn("missing", "", [])
    assert result is None


def test_custom_fn_error():
    from skills.param_resolver import _exec_custom_fn
    scripts = [{"name": "bad", "code": "raise ValueError('oops')"}]
    result = _exec_custom_fn("bad", "", scripts)
    assert result is None   # 出错时返回 None，不抛出
