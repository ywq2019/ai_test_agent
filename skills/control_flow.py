"""
control_flow — WebUI 用例控制流（第一阶段：if/else + while）

提供两层能力：
  1. 扁平 steps_json ↔ 嵌套步骤树 的无损转换（unflatten / flatten）
     - 扁平格式（持久化/存储）：控制流用 if/else/endif、while/endwhile 关键字表达
     - 树格式（执行 IR）：if / while 是容器节点，内含子步骤列表
  2. ConditionEvaluator — 安全的声明式条件表达式求值器（基于 ast 白名单，禁用 eval）

树节点结构：
  {"type": "root",  "children": [...]}
  {"type": "step",  "step": {...ActionStep...}}
  {"type": "if",    "id": str, "condition": str, "then": [...], "else": [...]}
  {"type": "while", "id": str, "condition": str, "body": [...], "max_iter": int?, "delay_ms": int?}

条件表达式支持的语法（第一阶段）：
  - 元素查询：exists(sel) / visible(sel) / hidden(sel) / count(sel) / text(sel)
  - 页面属性：url / title
  - 比较：== / != / > / < / >= / <=
  - 逻辑：and / or / not / 括号
  - 包含：contains(a, b) 或 a contains b
  - 变量：{{key}} 先替换为环境变量值
"""
import ast
import inspect
import json
import re
from typing import Any, Optional


# ── 变量替换（局部实现，避免与 action_runner 循环依赖） ────────────────────────
def resolve_vars(text: str, env: dict) -> str:
    """将 {{key}} 替换为 env 中的值；未找到的 key 保留原样。"""
    if not text or "{{" not in text:
        return text
    return re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: str(env.get(m.group(1), m.group(0))),
        text,
    )


# ── 扁平 ↔ 树 转换 ─────────────────────────────────────────────────────────────
# 第一阶段支持的控制流块关键字
_IF_START = "if"
_IF_ELSE = "else"
_IF_END = "endif"
_WHILE_START = "while"
_WHILE_END = "endwhile"

# 设计文档已规划、但第一阶段暂未实现的关键字，遇到时明确报错而非静默当作普通步骤
_UNSUPPORTED = {"elseif", "for", "endfor", "break", "continue",
                "try", "except", "endtry", "goto", "label"}


def unflatten(steps: list) -> dict:
    """将扁平 ActionStep 列表转换为嵌套步骤树（root 节点）。

    通过栈扫描配对 if/else/endif、while/endwhile；未配对时抛出 ValueError。
    """
    root: dict = {"type": "root", "children": []}
    stack: list[dict] = [{"kind": "root", "node": root, "branch": "children"}]

    def _append_child(top: dict, child: dict) -> None:
        kind = top["kind"]
        if kind == "if":
            top["node"][top["branch"]].append(child)
        elif kind == "while":
            top["node"]["body"].append(child)
        else:  # root
            top["node"]["children"].append(child)

    for step in steps:
        action = step.get("action", "")

        if action == _IF_START:
            if not step.get("condition"):
                raise ValueError(f"步骤 {step.get('id') or ''} 的 if 缺少 condition")
            node = {"type": "if", "id": step.get("id", ""),
                    "condition": step.get("condition", ""), "then": [], "else": []}
            _append_child(stack[-1], node)
            stack.append({"kind": "if", "node": node, "branch": "then"})

        elif action == _IF_ELSE:
            top = stack[-1]
            if top["kind"] != "if":
                raise ValueError("else 缺少匹配的 if")
            if top["branch"] == "else":
                raise ValueError("if 块出现重复的 else")
            top["branch"] = "else"

        elif action == _IF_END:
            if stack[-1]["kind"] != "if":
                raise ValueError("endif 缺少匹配的 if")
            stack.pop()

        elif action == _WHILE_START:
            if not step.get("condition"):
                raise ValueError(f"步骤 {step.get('id') or ''} 的 while 缺少 condition")
            node = {"type": "while", "id": step.get("id", ""),
                    "condition": step.get("condition", ""), "body": []}
            if step.get("max_iter") is not None:
                node["max_iter"] = int(step["max_iter"])
            if step.get("delay_ms"):
                node["delay_ms"] = int(step["delay_ms"])
            _append_child(stack[-1], node)
            stack.append({"kind": "while", "node": node, "branch": "body"})

        elif action == _WHILE_END:
            if stack[-1]["kind"] != "while":
                raise ValueError("endwhile 缺少匹配的 while")
            stack.pop()

        elif action in _UNSUPPORTED:
            raise ValueError(f"控制流 action {action!r} 第一阶段暂未支持")

        else:
            # 普通 ActionStep → 叶子节点
            _append_child(stack[-1], {"type": "step", "step": step})

    # 结束后栈内应只剩 root
    if len(stack) != 1:
        top = stack[-1]
        raise ValueError(f"控制流块未闭合：{top['kind']} 缺少结束关键字")
    return root


def flatten(tree: dict) -> list:
    """将嵌套步骤树（root 节点）转换回扁平 ActionStep 列表。"""
    out: list = []

    def _flatten_node(node: dict) -> None:
        t = node["type"]
        if t == "step":
            out.append(node["step"])
        elif t == "if":
            if_node = {"action": "if", "condition": node.get("condition", "")}
            if node.get("id"):
                if_node["id"] = node["id"]
            out.append(if_node)
            for child in node.get("then", []):
                _flatten_node(child)
            if node.get("else"):
                out.append({"action": "else"})
                for child in node["else"]:
                    _flatten_node(child)
            out.append({"action": "endif"})
        elif t == "while":
            while_node = {"action": "while", "condition": node.get("condition", "")}
            if node.get("id"):
                while_node["id"] = node["id"]
            if node.get("max_iter") is not None:
                while_node["max_iter"] = node["max_iter"]
            if node.get("delay_ms"):
                while_node["delay_ms"] = node["delay_ms"]
            out.append(while_node)
            for child in node.get("body", []):
                _flatten_node(child)
            out.append({"action": "endwhile"})
        else:
            raise ValueError(f"未知树节点类型: {t!r}")

    for child in tree.get("children", []):
        _flatten_node(child)
    return out


# ── 条件表达式求值器 ───────────────────────────────────────────────────────────
# 允许以裸 selector 作为参数的元素查询函数（这些函数的参数会被自动引号化）
_SELECTOR_FUNCS = {"exists", "visible", "hidden", "count", "text"}


def _find_matching_paren(expr: str, start: int) -> int:
    """从 start（位于 '(' 之后）扫描，返回与最外层 '(' 匹配的 ')' 索引；找不到返回 -1。"""
    depth = 1
    i = start
    n = len(expr)
    while i < n:
        c = expr[i]
        if c == '"' or c == "'":
            quote = c
            i += 1
            while i < n and expr[i] != quote:
                if expr[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _quote_selector_args(expr: str) -> str:
    """把元素查询函数的裸 selector 参数引号化，使其能被 Python ast 解析。

    visible(#a)          → visible("#a")
    count(button[type=x])→ count("button[type=x]")
    已是字符串字面量的参数（visible("#a")）保持原样。
    """
    pattern = re.compile(r"([A-Za-z_]\w*)\s*\(")
    out: list[str] = []
    i = 0
    n = len(expr)
    while i < n:
        m = pattern.match(expr, i)
        if m and m.group(1) in _SELECTOR_FUNCS:
            name = m.group(1)
            arg_start = m.end()  # '(' 之后
            arg_end = _find_matching_paren(expr, arg_start)
            if arg_end == -1:
                out.append(expr[i:])
                break
            arg_raw = expr[arg_start:arg_end].strip()
            if len(arg_raw) >= 2 and arg_raw[0] == arg_raw[-1] and arg_raw[0] in ('"', "'"):
                out.append(f"{name}({arg_raw})")
            else:
                out.append(f"{name}({json.dumps(arg_raw, ensure_ascii=False)})")
            i = arg_end + 1  # 跳过 ')'
        else:
            out.append(expr[i])
            i += 1
    return "".join(out)


class ConditionEvaluator:
    """安全求值声明式条件表达式，返回 bool。

    使用 ast 白名单解析，只允许白名单内的节点/函数/运算符；
    函数查询依赖 Playwright Page（async），因此 eval 为 async。
    """

    def __init__(self, page: Any):
        self.page = page

    async def eval(self, condition: str, env: Optional[dict] = None) -> bool:
        env = env or {}
        expr = resolve_vars(condition, env)
        expr = _quote_selector_args(expr)
        expr = self._rewrite_contains(expr)
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"条件表达式语法错误: {condition!r} -> {e}")
        return bool(await self._eval_node(tree.body))

    @staticmethod
    def _rewrite_contains(expr: str) -> str:
        """中缀 contains 转函数：a contains b -> __contains__(a, b)。"""
        atom = r'"[^"]*"|\'[^\']*\'|[A-Za-z_]\w*(?:\([^()]*\))?'
        return re.sub(
            rf"({atom})\s+contains\s+({atom})",
            r"__contains__(\1, \2)",
            expr,
        )

    async def _eval_node(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            if node.id == "url":
                return self.page.url
            if node.id == "title":
                return await self.page.title()
            raise ValueError(f"条件表达式中未知变量: {node.id!r}")

        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for v in node.values:
                    if not await self._eval_node(v):
                        return False
                return True
            if isinstance(node.op, ast.Or):
                for v in node.values:
                    if await self._eval_node(v):
                        return True
                return False
            raise ValueError(f"不支持的逻辑运算符: {type(node.op).__name__}")

        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return not await self._eval_node(node.operand)
            raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")

        if isinstance(node, ast.Compare):
            left = await self._eval_node(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = await self._eval_node(comp)
                if not self._compare(left, op, right):
                    return False
                left = right
            return True

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError(f"不支持的函数调用形式: {type(node.func).__name__}")
            fn_name = node.func.id
            args = [await self._eval_node(a) for a in node.args]
            return await self._call(fn_name, args)

        raise ValueError(f"不支持的条件表达式节点: {type(node).__name__}")

    @staticmethod
    def _compare(left: Any, op: ast.cmpop, right: Any) -> bool:
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.GtE):
            return left >= right
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        raise ValueError(f"不支持的比较运算符: {type(op).__name__}")

    async def _call(self, name: str, args: list) -> Any:
        if name in ("exists", "visible", "hidden", "count", "text"):
            if not args:
                raise ValueError(f"{name}() 需要一个 selector 参数")
            return await self._element_op(name, str(args[0]))
        if name == "__contains__":
            if len(args) != 2:
                raise ValueError("contains 需要两个参数")
            return str(args[1]) in str(args[0])
        raise ValueError(f"不支持的条件函数: {name!r}")

    async def _element_op(self, name: str, selector: str) -> Any:
        locator = self.page.locator(selector)
        if name == "exists":
            return (await locator.count()) > 0
        if name == "count":
            return await locator.count()
        if name == "visible":
            try:
                return await self._is_visible(locator.first)
            except Exception:
                return False
        if name == "hidden":
            try:
                cnt = await locator.count()
                if cnt == 0:
                    return True
                return not await self._is_visible(locator.first)
            except Exception:
                return True
        if name == "text":
            try:
                cnt = await locator.count()
                if cnt == 0:
                    return ""
                return await locator.first.inner_text()
            except Exception:
                return ""
        raise ValueError(f"未知元素操作: {name!r}")

    @staticmethod
    async def _is_visible(locator: Any) -> bool:
        """兼容不同 Playwright 版本：is_visible 可能是同步或 async。"""
        result = locator.is_visible()
        if inspect.isawaitable(result):
            result = await result
        return bool(result)
