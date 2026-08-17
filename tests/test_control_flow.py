"""
control_flow 控制流（第一阶段：if/else + while）单元测试

覆盖：
  - unflatten / flatten 无损往返（线性 / if-else / while / 嵌套）
  - unflatten 对未配对 / 暂不支持关键字的报错
  - ConditionEvaluator 条件表达式求值（mock Page）
  - ActionRunner 控制流执行（if 分支选择、while 循环、max_iter 防死循环）
"""
import asyncio

import pytest

from skills.action_runner import ActionRunner
from skills.control_flow import ConditionEvaluator, flatten, unflatten


# ── unflatten / flatten 往返 ───────────────────────────────────────────────────

def test_roundtrip_linear():
    steps = [
        {"id": "s1", "action": "navigate", "url": "http://x"},
        {"id": "s2", "action": "click", "selector": "#a"},
    ]
    assert flatten(unflatten(steps)) == steps


def test_roundtrip_if_else():
    steps = [
        {"id": "s1", "action": "if", "condition": "visible(#a)"},
        {"id": "s2", "action": "click", "selector": "#a"},
        {"action": "else"},
        {"id": "s4", "action": "click", "selector": "#b"},
        {"action": "endif"},
    ]
    tree = unflatten(steps)
    assert tree["type"] == "root"
    assert tree["children"][0]["type"] == "if"
    assert len(tree["children"][0]["then"]) == 1
    assert len(tree["children"][0]["else"]) == 1
    assert flatten(tree) == steps


def test_roundtrip_while():
    steps = [
        {"id": "w1", "action": "while", "condition": "not exists(.done)", "max_iter": 10, "delay_ms": 500},
        {"id": "b1", "action": "click", "selector": "#refresh"},
        {"action": "endwhile"},
    ]
    assert flatten(unflatten(steps)) == steps


def test_roundtrip_nested():
    steps = [
        {"id": "s1", "action": "if", "condition": "visible(#a)"},
        {"id": "w1", "action": "while", "condition": "not exists(.done)", "max_iter": 5},
        {"id": "b1", "action": "click", "selector": "#r"},
        {"action": "endwhile"},
        {"action": "else"},
        {"id": "s9", "action": "click", "selector": "#b"},
        {"action": "endif"},
    ]
    assert flatten(unflatten(steps)) == steps


# ── unflatten 报错 ─────────────────────────────────────────────────────────────

def test_unflatten_unclosed_if():
    steps = [
        {"id": "s1", "action": "if", "condition": "visible(#a)"},
        {"id": "s2", "action": "click", "selector": "#a"},
    ]
    with pytest.raises(ValueError):
        unflatten(steps)


def test_unflatten_else_without_if():
    with pytest.raises(ValueError):
        unflatten([{"action": "else"}])


def test_unflatten_if_missing_condition():
    with pytest.raises(ValueError):
        unflatten([{"id": "s1", "action": "if"}, {"action": "endif"}])


def test_unflatten_unsupported_keyword():
    with pytest.raises(ValueError):
        unflatten([{"id": "s1", "action": "for", "condition": "x in y"}])


# ── ConditionEvaluator（mock Page） ────────────────────────────────────────────

class FakeLocator:
    def __init__(self, count=0, visible=False, text=""):
        self._count = count
        self._visible = visible
        self._text = text

    async def count(self):
        return self._count

    def is_visible(self):
        return self._visible

    async def inner_text(self):
        return self._text

    @property
    def first(self):
        return self


class FakePage:
    def __init__(self, url="http://x", title="T", locator_map=None):
        self.url = url
        self._title = title
        self._locator_map = locator_map or {}

    async def title(self):
        return self._title

    def locator(self, selector):
        return self._locator_map.get(selector, FakeLocator())


def _eval(condition, page):
    return asyncio.run(ConditionEvaluator(page).eval(condition))


def test_condition_visible_true():
    page = FakePage(locator_map={"#a": FakeLocator(count=1, visible=True)})
    assert _eval("visible(#a)", page) is True


def test_condition_not_exists():
    page = FakePage(locator_map={})  # 未注册 selector → count=0
    assert _eval("not exists(.none)", page) is True


def test_condition_count_eq():
    page = FakePage(locator_map={".item": FakeLocator(count=3)})
    assert _eval("count(.item) == 3", page) is True


def test_condition_text_contains():
    page = FakePage(locator_map={".status": FakeLocator(count=1, text="保存成功")})
    assert _eval('text(.status) contains "成功"', page) is True


def test_condition_url_eq():
    page = FakePage(url="http://x/home")
    assert _eval('url == "http://x/home"', page) is True


def test_condition_and_or():
    page = FakePage(locator_map={
        "#a": FakeLocator(count=1, visible=True),
        ".item": FakeLocator(count=3),
    })
    assert _eval('visible(#a) and count(.item) > 0', page) is True
    assert _eval('visible(#a) or count(.none) > 10', page) is True


def test_condition_bad_syntax_raises():
    page = FakePage()
    with pytest.raises(ValueError):
        _eval("visible(#a", page)


# ── ActionRunner 控制流执行 ───────────────────────────────────────────────────

def _passed_result(step):
    return {"id": step["id"], "action": step["action"], "passed": True,
            "error": "", "duration_ms": 0, "screenshot": ""}


def test_runner_if_then_branch(monkeypatch):
    executed = []

    async def fake_run_step(step, page):
        executed.append(step["id"])
        return _passed_result(step)

    async def fake_eval(self, condition, env=None):
        return True

    runner = ActionRunner(task_id=0)
    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(ConditionEvaluator, "eval", fake_eval)

    steps = [
        {"id": "s1", "action": "if", "condition": "visible(#a)"},
        {"id": "s2", "action": "click", "selector": "#a"},
        {"action": "else"},
        {"id": "s4", "action": "click", "selector": "#b"},
        {"action": "endif"},
    ]
    result = asyncio.run(runner.run_case({"id": 1, "name": "t", "steps_json": steps}, None))
    assert executed == ["s2"]
    assert result["status"] == "passed"


def test_runner_if_else_branch(monkeypatch):
    executed = []

    async def fake_run_step(step, page):
        executed.append(step["id"])
        return _passed_result(step)

    async def fake_eval(self, condition, env=None):
        return False

    runner = ActionRunner(task_id=0)
    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(ConditionEvaluator, "eval", fake_eval)

    steps = [
        {"id": "s1", "action": "if", "condition": "visible(#a)"},
        {"id": "s2", "action": "click", "selector": "#a"},
        {"action": "else"},
        {"id": "s4", "action": "click", "selector": "#b"},
        {"action": "endif"},
    ]
    result = asyncio.run(runner.run_case({"id": 1, "name": "t", "steps_json": steps}, None))
    assert executed == ["s4"]
    assert result["status"] == "passed"


def test_runner_while_loop(monkeypatch):
    executed = []
    counter = {"n": 0}

    async def fake_run_step(step, page):
        executed.append(step["id"])
        return _passed_result(step)

    async def fake_eval(self, condition, env=None):
        counter["n"] += 1
        return counter["n"] <= 2  # 前两次真 → 执行两次 body

    runner = ActionRunner(task_id=0)
    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(ConditionEvaluator, "eval", fake_eval)

    steps = [
        {"id": "w1", "action": "while", "condition": "not exists(.done)", "max_iter": 5},
        {"id": "b1", "action": "click", "selector": "#refresh"},
        {"action": "endwhile"},
    ]
    result = asyncio.run(runner.run_case({"id": 2, "name": "w", "steps_json": steps}, None))
    assert executed == ["b1", "b1"]
    assert result["status"] == "passed"


def test_runner_while_max_iter(monkeypatch):
    executed = []

    async def fake_run_step(step, page):
        executed.append(step["id"])
        return _passed_result(step)

    async def fake_eval(self, condition, env=None):
        return True  # 永远真 → 触发 max_iter 上限

    runner = ActionRunner(task_id=0)
    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(ConditionEvaluator, "eval", fake_eval)

    steps = [
        {"id": "w1", "action": "while", "condition": "exists(.always)", "max_iter": 3},
        {"id": "b1", "action": "click", "selector": "#x"},
        {"action": "endwhile"},
    ]
    result = asyncio.run(runner.run_case({"id": 3, "name": "w", "steps_json": steps}, None))
    assert len(executed) == 3  # body 执行 3 次后超限
    assert result["status"] == "failed"
