"""
Mock 测试：用例自我修正 & 覆盖率补全

模拟数据覆盖三种场景：
  1. selector 找不到 → AI 修正 / 关键词兜底
  2. 断言/超时错误 → AI 分析修正
  3. 未覆盖元素 → 补全用例

运行方式：
  cd e:\ai_test_agent
  python -m tests.test_mock_self_correct
"""
import asyncio
import json
import sys
from unittest.mock import AsyncMock, patch
from pathlib import Path

# 确保项目根在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Mock 页面元素（模拟一个电商登录+搜索页面） ──
MOCK_PAGE_ELEMENTS = [
    # 登录区域
    {"tag": "input", "type": "text", "name": "username", "placeholder": "请输入用户名", "selector": "#username"},
    {"tag": "input", "type": "password", "name": "password", "placeholder": "请输入密码", "selector": "#password"},
    {"tag": "button", "type": "submit", "name": "", "text": "登录", "selector": "button.login-btn"},
    {"tag": "a", "type": "", "name": "", "text": "忘记密码", "selector": "a.forgot-pwd"},
    {"tag": "a", "type": "", "name": "", "text": "立即注册", "selector": "a.register-link"},
    # 搜索区域
    {"tag": "input", "type": "text", "name": "keyword", "placeholder": "搜索商品", "selector": "#search-input"},
    {"tag": "button", "type": "button", "name": "", "text": "搜索", "selector": "button.search-btn"},
    {"tag": "select", "type": "", "name": "category", "text": "", "selector": "#category-select"},
    # 商品列表
    {"tag": "a", "type": "", "name": "", "text": "iPhone 15 128GB", "selector": "a.product-item:nth-child(1)"},
    {"tag": "a", "type": "", "name": "", "text": "华为Mate 60 Pro", "selector": "a.product-item:nth-child(2)"},
    {"tag": "button", "type": "button", "name": "", "text": "加入购物车", "selector": "button.add-to-cart-1"},
    {"tag": "button", "type": "button", "name": "", "text": "立即购买", "selector": "button.buy-now-1"},
    {"tag": "input", "type": "number", "name": "quantity", "text": "数量", "selector": "#qty-input"},
    # 导航
    {"tag": "a", "type": "", "name": "", "text": "首页", "selector": "a.nav-home"},
    {"tag": "a", "type": "", "name": "", "text": "购物车", "selector": "a.nav-cart"},
    {"tag": "a", "type": "", "name": "", "text": "我的订单", "selector": "a.nav-orders"},
    # 文字节点
    {"tag": "span", "type": "", "name": "", "text": "热门商品", "selector": "span"},
    {"tag": "p", "type": "", "name": "", "text": "全场满199包邮", "selector": "p"},
    {"tag": "div", "type": "", "name": "", "text": "限时特惠", "selector": "div"},
]

# ── Mock 失败用例 ──
MOCK_FAILED_CASES = [
    # 场景1: selector 找不到（AI 匹配到 #username）
    {
        "case_name": "登录-有效账号-登录成功",
        "name": "登录-有效账号-登录成功",
        "module": "登录",
        "priority": "P0",
        "steps": "1. 找到用户名输入框（selector: #user-input），输入 'test@example.com'\n2. 找到密码输入框（selector: #passwd），输入 'Pass1234'\n3. 点击登录按钮（selector: button.submit）",
        "expected_results": "页面跳转到 /home，顶部导航栏显示用户名 'test'",
        "error_message": "TimeoutError: waiting for selector '#user-input' failed: timeout 30000ms exceeded",
    },
    # 场景2: selector 找不到（AI 匹配到 button.search-btn）
    {
        "case_name": "搜索-关键词搜索-显示结果",
        "name": "搜索-关键词搜索-显示结果",
        "module": "搜索",
        "priority": "P1",
        "steps": "1. 找到搜索输入框（selector: #search-box），输入 'iPhone'\n2. 点击搜索按钮（selector: #btn-search）",
        "expected_results": "页面显示含有 iPhone 的商品列表",
        "error_message": "Error: locator '#search-box' not found in page",
    },
    # 场景3: selector 找不到（AI 匹配到 #password、button.login-btn）
    {
        "case_name": "登录-密码错误-显示错误提示",
        "name": "登录-密码错误-显示错误提示",
        "module": "登录",
        "priority": "P1",
        "steps": "1. 找到用户名输入框（selector: #username），输入 'test@example.com'\n2. 找到密码输入框（selector: #pass_field），输入 'wrong'\n3. 点击登录按钮（selector: .login_submit）",
        "expected_results": "页面显示红色提示 '用户名或密码错误'",
        "error_message": "ElementNotFoundError: selector '#pass_field' not found. Did you mean '#password'?",
    },
    # 场景4: 断言/超时错误（非 selector 问题）
    {
        "case_name": "商品-加入到购物车-成功提示",
        "name": "商品-加入到购物车-成功提示",
        "module": "商品操作",
        "priority": "P0",
        "steps": "1. 找到「加入购物车」按钮（selector: button.add-to-cart-1），点击\n2. 等待提示弹窗出现",
        "expected_results": "页面顶部显示绿色提示 '已加入购物车'",
        "error_message": "AssertionError: Expected text '已加入购物车' but got '请先选择规格'",
    },
    # 场景5: 超时（非 selector 问题）
    {
        "case_name": "数量输入-超过库存-显示错误",
        "name": "数量输入-超过库存-显示错误",
        "module": "商品操作",
        "priority": "P1",
        "steps": "1. 找到数量输入框（#qty-input），输入 '999'\n2. 点击立即购买按钮（selector: button.buy-now-1）",
        "expected_results": "页面在 2 秒内显示 '库存不足' 弹窗",
        "error_message": "TimeoutError: waiting for dialog '.stock-warning' visible: timeout 2000ms exceeded",
    },
]

# ── Mock 已有用例 ──
MOCK_EXISTING_CASES = [
    {
        "id": "TC001", "name": "登录-有效账号-登录成功", "module": "登录",
        "priority": "P0", "steps": "1. 输入用户名\n2. 输入密码\n3. 点击登录",
        "expected_results": "跳转到首页", "element_selector": "#username",
    },
    {
        "id": "TC002", "name": "登录-密码错误-显示错误提示", "module": "登录",
        "priority": "P1", "steps": "1. 输入用户名\n2. 输入错误密码\n3. 点击登录",
        "expected_results": "显示错误提示", "element_selector": "button.login-btn",
    },
    {
        "id": "TC003", "name": "搜索-关键词搜索-显示结果", "module": "搜索",
        "priority": "P0", "steps": "1. 输入关键词\n2. 点击搜索",
        "expected_results": "显示搜索结果列表", "element_selector": "#search-input",
    },
    {
        "id": "TC004", "name": "商品-加入购物车-成功", "module": "商品操作",
        "priority": "P0", "steps": "1. 点击加入购物车",
        "expected_results": "购物车数量+1", "element_selector": "button.add-to-cart-1",
    },
    {
        "id": "TC005", "name": "商品-立即购买-跳转订单页", "module": "商品操作",
        "priority": "P0", "steps": "1. 点击立即购买",
        "expected_results": "跳转到订单确认页", "element_selector": "button.buy-now-1",
    },
]

# ── Mock 执行结果 ──
MOCK_EXECUTION_RESULTS = [
    {"case_id": "TC001", "status": "failed", "error_message": "selector '#user-input' not found"},
    {"case_id": "TC002", "status": "passed"},
    {"case_id": "TC003", "status": "passed"},
    {"case_id": "TC004", "status": "passed"},
    {"case_id": "TC005", "status": "passed"},
]


# ── Mock LLM 响应 ──
def _mock_llm_selector_correction(system_prompt, prompt, **kwargs):
    """模拟 LLM 修正 selector 的响应。"""
    return json.dumps({
        "corrected_cases": [
            {
                "name": "登录-有效账号-登录成功",
                "corrected_steps": "1. 找到用户名输入框（selector: #username），输入 'test@example.com'\n2. 找到密码输入框（selector: #password），输入 'Pass1234'\n3. 点击登录按钮（selector: button.login-btn）",
                "fix_note": "将 selector #user-input 修正为 #username，#passwd 修正为 #password，button.submit 修正为 button.login-btn",
                "confidence": "high",
            },
            {
                "name": "搜索-关键词搜索-显示结果",
                "corrected_steps": "1. 找到搜索输入框（selector: #search-input），输入 'iPhone'\n2. 点击搜索按钮（selector: button.search-btn）",
                "fix_note": "将 selector #search-box 修正为 #search-input，#btn-search 修正为 button.search-btn",
                "confidence": "high",
            },
            {
                "name": "登录-密码错误-显示错误提示",
                "corrected_steps": "1. 找到用户名输入框（selector: #username），输入 'test@example.com'\n2. 找到密码输入框（selector: #password），输入 'wrong'\n3. 点击登录按钮（selector: button.login-btn）",
                "fix_note": "将 selector #pass_field 修正为 #password，.login_submit 修正为 button.login-btn",
                "confidence": "high",
            },
        ]
    }, ensure_ascii=False)


def _mock_llm_other_correction(system_prompt, prompt, **kwargs):
    """模拟 LLM 修正其他错误的响应。"""
    return json.dumps({
        "corrected_cases": [
            {
                "name": "商品-加入到购物车-成功提示",
                "corrected_steps": "1. 找到「加入购物车」按钮（selector: button.add-to-cart-1），点击\n2. 等待规格选择弹窗出现\n3. 选择默认规格\n4. 再次点击「加入购物车」按钮",
                "expected_results": "页面顶部显示绿色提示 '已加入购物车'，购物车角标数字+1",
                "fix_note": "增加了规格选择的中间步骤，修正了预期结果描述",
                "confidence": "medium",
            },
            {
                "name": "数量输入-超过库存-显示错误",
                "corrected_steps": "1. 找到数量输入框（selector: #qty-input），清除默认值，输入 '999'\n2. 点击立即购买按钮（selector: button.buy-now-1）\n3. 等待最多 10 秒直到页面出现库存不足提示",
                "expected_results": "页面显示 '库存不足' 或类似提示信息",
                "fix_note": "增加等待超时时间到 10 秒，放宽预期断言的匹配条件",
                "confidence": "medium",
            },
        ]
    }, ensure_ascii=False)


def _mock_llm_gap_fill(system_prompt, prompt, **kwargs):
    """模拟 LLM 补充覆盖用例的响应。"""
    return json.dumps({
        "cases": [
            {
                "name": "忘记密码-点击链接-跳转到重置页",
                "module": "补充覆盖",
                "priority": "P1",
                "preconditions": "用户处于登录页面",
                "steps": "1. 找到「忘记密码」链接（selector: a.forgot-pwd）\n2. 点击该链接",
                "expected_results": "页面跳转到密码重置页面，URL 包含 /reset-password",
                "element_selector": "a.forgot-pwd",
            },
            {
                "name": "注册-点击注册链接-跳转到注册页",
                "module": "补充覆盖",
                "priority": "P1",
                "preconditions": "用户处于登录页面",
                "steps": "1. 找到「立即注册」链接（selector: a.register-link）\n2. 点击该链接",
                "expected_results": "页面跳转到用户注册页面",
                "element_selector": "a.register-link",
            },
            {
                "name": "商品分类-选择分类-筛选商品",
                "module": "补充覆盖",
                "priority": "P1",
                "preconditions": "用户处于商品列表页",
                "steps": "1. 找到分类下拉框（selector: #category-select）\n2. 选择「电子产品」分类",
                "expected_results": "商品列表只显示电子产品分类的商品",
                "element_selector": "#category-select",
            },
            {
                "name": "导航-点击购物车-进入购物车页",
                "module": "补充覆盖",
                "priority": "P1",
                "preconditions": "用户已登录",
                "steps": "1. 找到购物车导航链接（selector: a.nav-cart）\n2. 点击该链接",
                "expected_results": "页面跳转到购物车页面",
                "element_selector": "a.nav-cart",
            },
            {
                "name": "导航-点击首页-返回首页",
                "module": "补充覆盖",
                "priority": "P2",
                "preconditions": "用户在任意子页面",
                "steps": "1. 找到首页导航链接（selector: a.nav-home）\n2. 点击该链接",
                "expected_results": "页面跳转到网站首页",
                "element_selector": "a.nav-home",
            },
            {
                "name": "导航-点击我的订单-查看订单列表",
                "module": "补充覆盖",
                "priority": "P2",
                "preconditions": "用户已登录",
                "steps": "1. 找到「我的订单」导航链接（selector: a.nav-orders）\n2. 点击该链接",
                "expected_results": "页面跳转到订单列表页面",
                "element_selector": "a.nav-orders",
            },
        ]
    }, ensure_ascii=False)


# ── 进度回调 ──
def print_progress(pct: int, stage: str, case_count: int = 0):
    print(f"  [{pct:3d}%] {stage}" + (f" (已生成 {case_count} 条)" if case_count else ""))


# ══════════════════════════════════════════════════════════════════════
# 测试 1: self_correct_cases（AI 修正模式）
# ══════════════════════════════════════════════════════════════════════
async def test_self_correct_with_mock_llm():
    print("\n" + "=" * 60)
    print("  测试 1: 用例自我修正（Mock LLM 响应）")
    print("=" * 60)
    print(f"\n  输入: {len(MOCK_FAILED_CASES)} 条失败用例")
    for fc in MOCK_FAILED_CASES:
        err_short = (fc['error_message'])[:60]
        print(f"    - {fc['case_name']}: {err_short}...")

    # 使用 patch 替换 LLM 调用
    _call_idx = {"n": 0}

    def _side_effect(*args, **kwargs):
        _call_idx["n"] += 1
        # _correct_selector_errors 的 system_prompt 含 "fixing broken selectors"
        sp = args[0] if args else kwargs.get("system_prompt", "")
        if "fixing broken selectors" in str(sp):
            return _mock_llm_selector_correction(sp, *(args[1:] if len(args) > 1 else []), **kwargs)
        return _mock_llm_other_correction(sp, *(args[1:] if len(args) > 1 else []), **kwargs)

    from skills.case_generator import CaseGenerator
    cg = CaseGenerator()

    with patch.object(cg, "_run_claude_subprocess", new=AsyncMock(side_effect=_side_effect)):
        corrected = await cg.self_correct_cases(
            failed_cases=MOCK_FAILED_CASES,
            page_elements=MOCK_PAGE_ELEMENTS,
            url="https://shop.example.com/login",
            progress_cb=print_progress,
        )

    print(f"\n  输出: {len(corrected)} 条修正结果")
    for c in corrected:
        conf = c.get("confidence", "?")
        name = c.get("case_name", c.get("name", "?"))
        fix_note = c.get("fix_note", "无说明")
        has_new_steps = bool(c.get("corrected_steps"))
        print(f"    [{conf.upper()}] {name}")
        print(f"        修正说明: {fix_note}")
        if has_new_steps:
            steps_preview = c["corrected_steps"][:120].replace("\n", " / ")
            print(f"        修正步骤: {steps_preview}...")
        print()
    return corrected


# ══════════════════════════════════════════════════════════════════════
# 测试 2: self_correct_cases（AI 失败 → 关键词兜底）
# ══════════════════════════════════════════════════════════════════════
async def test_self_correct_fallback():
    print("\n" + "=" * 60)
    print("  测试 2: 用例自我修正（LLM 失败 → 关键词兜底）")
    print("=" * 60)

    from skills.case_generator import CaseGenerator
    cg = CaseGenerator()

    # Mock LLM 抛异常，触发 fallback
    with patch.object(cg, "_run_claude_subprocess", new=AsyncMock(side_effect=Exception("Mock LLM service unavailable"))):
        corrected = await cg.self_correct_cases(
            failed_cases=MOCK_FAILED_CASES[:3],  # 只取 selector 类
            page_elements=MOCK_PAGE_ELEMENTS,
            url="https://shop.example.com/login",
        )

    print(f"\n  输出: {len(corrected)} 条兜底修正结果")
    for c in corrected:
        conf = c.get("confidence", "?")
        name = c.get("case_name", c.get("name", "?"))
        fix_note = c.get("fix_note", "无说明")
        print(f"    [{conf.upper()}] {name}")
        print(f"        兜底说明: {fix_note}")
        if c.get("corrected_steps"):
            print(f"        修正后步骤: {c['corrected_steps'][:120]}...")
        print()
    return corrected


# ══════════════════════════════════════════════════════════════════════
# 测试 3: fill_coverage_gaps（覆盖率补全）
# ══════════════════════════════════════════════════════════════════════
async def test_fill_coverage_gaps():
    print("\n" + "=" * 60)
    print("  测试 3: 覆盖率补全（Mock LLM 响应）")
    print("=" * 60)

    from skills.case_generator import CaseGenerator
    cg = CaseGenerator()

    # 统计输入
    existing_names = set(c["name"] for c in MOCK_EXISTING_CASES)
    print(f"\n  输入: {len(MOCK_EXISTING_CASES)} 条已有用例, {len(MOCK_PAGE_ELEMENTS)} 个页面元素")

    # 手动计算预期未覆盖元素
    touches = set()
    for c in MOCK_EXISTING_CASES:
        sel = c.get("element_selector", "")
        if sel:
            touches.add(sel)
    uncovered = [e for e in MOCK_PAGE_ELEMENTS
                 if e.get("tag") in {"input", "button", "a", "select", "textarea"}
                 and e.get("selector", "") not in touches
                 and e.get("selector")]
    print(f"  预期未覆盖: {len(uncovered)} 个元素")
    for u in uncovered:
        print(f"    - [{u['tag']}] {u.get('name','') or u.get('text','')} ({u['selector']})")

    with patch.object(cg, "_run_claude_subprocess", new=AsyncMock(side_effect=_mock_llm_gap_fill)):
        new_cases = await cg.fill_coverage_gaps(
            existing_cases=MOCK_EXISTING_CASES,
            execution_results=MOCK_EXECUTION_RESULTS,
            page_elements=MOCK_PAGE_ELEMENTS,
            url="https://shop.example.com/products",
            progress_cb=print_progress,
        )

    print(f"\n  输出: {len(new_cases)} 条补充用例")
    for nc in new_cases:
        print(f"    [{nc.get('priority','?')}] {nc['name']}")
        print(f"        selector: {nc.get('element_selector','?')}")
    return new_cases


# ══════════════════════════════════════════════════════════════════════
# 测试 4: 一键修正补全（组合测试）
# ══════════════════════════════════════════════════════════════════════
async def test_auto_fix_combined():
    print("\n" + "=" * 60)
    print("  测试 4: 一键修正补全（全流程组合）")
    print("=" * 60)

    from skills.case_generator import CaseGenerator
    cg = CaseGenerator()

    # 场景：部分用例执行失败，整体覆盖不完整
    call_count = {"n": 0}

    def _combined_llm(*args, **kwargs):
        call_count["n"] += 1
        sp = args[0] if args else kwargs.get("system_prompt", "")
        if "fixing broken selectors" in str(sp):
            return _mock_llm_selector_correction(sp, *(args[1:] if len(args) > 1 else []), **kwargs)
        elif "执行失败" in str(sp) or "failed test cases" in str(sp):
            return _mock_llm_other_correction(sp, *(args[1:] if len(args) > 1 else []), **kwargs)
        return _mock_llm_gap_fill(sp, *(args[1:] if len(args) > 1 else []), **kwargs)

    with patch.object(cg, "_run_claude_subprocess", new=AsyncMock(side_effect=_combined_llm)):
        # 模拟 auto_fix 两步调用
        # Step 1: 修正
        corrected = await cg.self_correct_cases(
            failed_cases=MOCK_FAILED_CASES,
            page_elements=MOCK_PAGE_ELEMENTS,
            url="https://shop.example.com",
            progress_cb=lambda p, s, c=0: print(f"  [修正][{p:3d}%] {s}"),
        )
        print(f"\n  Step 1 修正: {len(corrected)} 条")

        # Step 2: 补全
        new_cases = await cg.fill_coverage_gaps(
            existing_cases=MOCK_EXISTING_CASES,
            execution_results=MOCK_EXECUTION_RESULTS,
            page_elements=MOCK_PAGE_ELEMENTS,
            url="https://shop.example.com",
            progress_cb=lambda p, s, c=0: print(f"  [补全][{p:3d}%] {s}"),
        )
        print(f"  Step 2 补全: {len(new_cases)} 条")

    print(f"\n  总计: {len(corrected)} 条修正 + {len(new_cases)} 条补充")
    print(f"  LLM 调用次数: {call_count['n']}")
    print(f"  高置信度修正: {sum(1 for c in corrected if c.get('confidence') == 'high')} 条")
    print(f"  中置信度修正: {sum(1 for c in corrected if c.get('confidence') == 'medium')} 条")
    print(f"  低置信度修正: {sum(1 for c in corrected if c.get('confidence') == 'low')} 条")


# ══════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════
async def main():
    print("=" * 60)
    print("  AI Test Agent — 用例修正 & 补全 Mock 测试")
    print("=" * 60)
    print(f"\n  测试概况:")
    print(f"    Mock 页面元素: {len(MOCK_PAGE_ELEMENTS)} 个")
    print(f"    Mock 失败用例:     {len(MOCK_FAILED_CASES)} 条")
    print(f"    Mock 已有用例:     {len(MOCK_EXISTING_CASES)} 条")
    print(f"    Mock 执行结果:     {len(MOCK_EXECUTION_RESULTS)} 条")

    await test_self_correct_with_mock_llm()
    await test_self_correct_fallback()
    await test_fill_coverage_gaps()
    await test_auto_fix_combined()

    print("\n" + "=" * 60)
    print("  All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
