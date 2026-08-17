"""
step_hardener.py — AI 健壮化模块

对录制/手动创建的 steps_json 进行健壮化增强：

1. selector_grade(sel)
   对单个 selector 按稳定性分级：
   A = data-testid / aria-label / name / placeholder（语义锚定，框架改动不影响）
   B = :has-text() / role / type=submit（行为语义，较稳定）
   C = .className / tag.class（视觉样式，重构易变）
   D = #id（动态 id）/ 纯 tag / 空（几乎不可靠）

2. generate_candidate_selectors(primary_sel, step_context)
   基于 primary selector + 步骤上下文，用规则推导更多候选 selector
   按 A→B→C→D 排序，primary 在同级末尾作为兜底

3. harden_steps(steps) → list
   批量处理 steps_json：
   - 为每个有 selector 的步骤填充 selectors[] 候选列表
   - 为每个步骤填充 robustness 字段（取 selectors[0] 的等级）
   - 检测"高风险空档"（click/submit 后连续无 assert/wait）
     自动插入 wait_for + assert（optional=True）
   - 返回增强后的 steps 列表，不修改原列表

4. ai_enrich_selectors(steps) → list   [可选，需调用 LLM]
   当步骤的 description/value/context 信息足够丰富时，
   让 AI 批量生成更多候选 selector（规则推导覆盖不到的场景）
"""

import re
import json
import uuid
from copy import deepcopy
from loguru import logger
from typing import Optional


# ── 1. Selector 评级 ──────────────────────────────────────────────────────────

# A 级：语义锚定，稳定性最高
_GRADE_A = [
    r'\[data-testid=',
    r'\[data-test=',
    r'\[data-cy=',
    r'\[data-',          # 通用 data-* 自定义属性（data-id / data-key / data-type 等均属语义锚点）
    r'\[aria-label=',
    r'\[name=',
    r'\[placeholder=',
    r'\[role="',
    r'getByRole\(',
    r'getByLabel\(',
    r'getByPlaceholder\(',
    r'getByTestId\(',
    r'getByAltText\(',
    r'^label=',          # 录制器生成：label=用户名
    r'^alt=',            # 录制器生成：alt=logo
]

# B 级：行为/内容语义，较稳定
_GRADE_B = [
    r':has-text\(',
    r'text=',
    r'\[type="submit"',
    r'\[type="button"',
    r'\[type="reset"',
    r':nth-child\(',
    r'\[aria-',
    r'\[role=',
    r'label\[for=',
    r'^role=',           # 录制器生成：role=button（不含方括号）
]

# D 级黑名单：几乎不可靠
_GRADE_D_PATTERNS = [
    r'^#[a-f0-9]{6,}$',                    # 纯 hex id
    r'^#\w+-\d{6,}$',                       # 带时间戳 id
    r'^\w+$',                               # 纯 tag name
    r'^\[class\*="[a-f0-9]{5,}"\]',        # 哈希 class
    r'--[a-f0-9]{4,}',                      # CSS Module 哈希
    r'_[a-z0-9]{5,}_',                      # Vue scoped 哈希
]


def selector_grade(sel: str) -> str:
    """
    对单个 selector 评级，返回 'A' / 'B' / 'C' / 'D'。
    空 selector 直接返回 'D'。
    """
    if not sel or not sel.strip():
        return "D"

    sel_s = sel.strip()

    # D 级黑名单优先判断
    for pat in _GRADE_D_PATTERNS:
        if re.search(pat, sel_s, re.IGNORECASE):
            return "D"

    # 动态数字 id：#xxx-123456（6位以上数字 → D）
    if re.match(r'^#\w*\d{5,}', sel_s):
        return "D"

    # A 级
    for pat in _GRADE_A:
        if re.search(pat, sel_s, re.IGNORECASE):
            return "A"

    # B 级
    for pat in _GRADE_B:
        if re.search(pat, sel_s, re.IGNORECASE):
            return "B"

    # C 级：带 class 的复合选择器
    if re.search(r'\.\w', sel_s) or re.search(r'\[class', sel_s):
        return "C"

    # 纯 #id（不含大量数字）→ C
    if re.match(r'^#[a-zA-Z][\w-]*$', sel_s):
        return "C"

    return "D"


# ── 2. 候选 Selector 推导 ─────────────────────────────────────────────────────

def _extract_text_from_sel(sel: str) -> str:
    """从 :has-text("xxx") 或 text="xxx" 里提取文本。"""
    m = re.search(r':has-text\(["\'](.+?)["\']\)', sel)
    if m:
        return m.group(1)
    m = re.search(r'text=["\'](.+?)["\']', sel)
    if m:
        return m.group(1)
    return ""


def _extract_id_from_sel(sel: str) -> str:
    """从 #xxx 里提取 id 值。"""
    m = re.match(r'^#([\w-]+)', sel)
    return m.group(1) if m else ""


def _extract_name_from_sel(sel: str) -> str:
    """从 [name="xxx"] 里提取 name 值。"""
    m = re.search(r'\[name=["\']?([^"\'>\]]+)["\']?\]', sel)
    return m.group(1) if m else ""


def _extract_placeholder_from_sel(sel: str) -> str:
    """从 [placeholder="xxx"] 里提取 placeholder。"""
    m = re.search(r'\[placeholder=["\']?([^"\'>\]]+)["\']?\]', sel)
    return m.group(1) if m else ""


def generate_candidate_selectors(step: dict) -> list[str]:
    """
    基于步骤信息（selector、selectors、description、value、action）
    用规则推导候选 selector 列表，按稳定性排序（A→B→C→D）。

    输入步骤已有的 selectors 会被保留并去重。
    """
    action      = step.get("action", "")
    primary     = (step.get("selector") or "").strip()
    existing    = [s.strip() for s in (step.get("selectors") or []) if s.strip()]
    description = step.get("description", "").strip()
    value       = step.get("value", "").strip()

    candidates_a: list[str] = []
    candidates_b: list[str] = []
    candidates_c: list[str] = []
    candidates_d: list[str] = []
    _seen: set = set(existing)   # O(1) 去重，避免每次调用重建列表

    def _add(sel: str):
        """按评级分桶，去重。"""
        if not sel:
            return
        sel = sel.strip()
        if sel in _seen:
            return
        _seen.add(sel)
        g = selector_grade(sel)
        if g == "A":
            candidates_a.append(sel)
        elif g == "B":
            candidates_b.append(sel)
        elif g == "C":
            candidates_c.append(sel)
        else:
            candidates_d.append(sel)

    # ── 从 primary selector 里提取语义，派生更高等级的候选 ──

    # 从 #id 推导 [name=] / [aria-label=] / :has-text()
    _id = _extract_id_from_sel(primary)
    if _id:
        _add(f'[name="{_id}"]')
        _add(f'[aria-label="{_id}"]')

    # 从 description 中提取关键词，生成 :has-text
    _desc_text = description
    for noise in ["点击", "填写", "输入", "选择", "断言", "等待", "导航", "提交", "勾选", "滚动"]:
        _desc_text = _desc_text.replace(noise, "")
    _desc_text = _desc_text.strip(" =→：:-「」《》()（）").strip()

    if _desc_text and len(_desc_text) >= 2 and action in (
        "click", "assert_text", "assert_visible", "hover"
    ):
        tag_hint = "button" if action == "click" else ""
        _add(f'{tag_hint}:has-text("{_desc_text}")' if tag_hint else f':has-text("{_desc_text}")')

    # fill/type：value 作为 placeholder 候选
    if action in ("fill", "type") and value:
        _add(f'input[placeholder="{value}"]')
        _add(f'textarea[placeholder="{value}"]')

    # 从 existing selectors 里提取语义，互相补充
    for esel in existing:
        _n = _extract_name_from_sel(esel)
        if _n:
            _add(f'[aria-label="{_n}"]')
            _add(f'[placeholder="{_n}"]')
        _p = _extract_placeholder_from_sel(esel)
        if _p:
            _add(f'[name="{_p}"]')
            _add(f'input[placeholder="{_p}"]')
            if action in ("click", "assert_text", "assert_visible"):
                _add(f':has-text("{_p}")')
        _t = _extract_text_from_sel(esel)
        if _t and action in ("click", "assert_text", "assert_visible"):
            _add(f'[aria-label="{_t}"]')

    # primary 本身按评级入桶（兜底）
    _add(primary)

    # 合并，A→B→C→D 排序
    result = candidates_a + candidates_b + candidates_c + candidates_d
    # 保留 existing 中不在 result 里的（录制已验证的，保留）
    for esel in existing:
        if esel not in result:
            result.append(esel)

    return result if result else ([primary] if primary else [])


# ── 3. 高风险空档检测 ─────────────────────────────────────────────────────────

_TRIGGER_ACTIONS = {"click", "submit", "fill", "select", "check", "uncheck"}
_ASSERT_ACTIONS  = {"assert_text", "assert_visible", "assert_hidden",
                    "assert_url", "assert_title", "assert_count", "wait_for", "wait"}

# 提交语义关键词（用于判断是否是"关键操作"）
_SUBMIT_KEYWORDS = ["登录", "login", "提交", "submit", "确认", "confirm",
                    "保存", "save", "注册", "register", "搜索", "search", "删除", "delete"]


def _is_key_action(step: dict) -> bool:
    """是否是关键操作（点击/提交 + 语义关键词）。"""
    if step.get("action") not in ("click", "submit"):
        return False
    desc = (step.get("description", "") + step.get("selector", "")).lower()
    return any(kw in desc for kw in _SUBMIT_KEYWORDS)


def _make_wait_assert(prev_step: dict, idx: int) -> list[dict]:
    """在关键操作后插入 wait + assert（optional）。"""
    inserted = []
    base_id = prev_step.get("id", f"s{idx:03d}")

    # wait_for：等待网络稳定
    inserted.append({
        "id":          f"{base_id}_wait",
        "action":      "wait",
        "selector":    "",
        "value":       "",
        "url":         "",
        "expected":    "",
        "description": "等待操作响应",
        "timeout":     3000,
        "optional":    True,
        "robustness":  "A",
        "selectors":   [],
        "_auto_inserted": True,
    })

    # assert_url：验证有跳转（最轻量的验证）
    inserted.append({
        "id":          f"{base_id}_assert",
        "action":      "assert_visible",
        "selector":    ".el-message,.ant-message,.toast,[role='alert'],.success,.error",
        "selectors":   [
            "[role='alert']",
            ".el-message",
            ".ant-message",
            ".toast",
            ".success",
            ".error",
        ],
        "value":       "",
        "url":         "",
        "expected":    "",
        "description": "断言：出现操作反馈（提示/跳转）",
        "timeout":     5000,
        "optional":    True,
        "robustness":  "A",
        "_auto_inserted": True,
    })
    return inserted


# ── 4. 主入口：harden_steps ───────────────────────────────────────────────────

def harden_steps(steps: list) -> list:
    """
    对 steps_json 列表做完整健壮化处理，返回新列表（不修改原列表）。

    处理内容：
    1. 为每个有 selector 的步骤推导 selectors[] 候选列表
    2. 为每个步骤写入 robustness 字段
    3. 在"关键操作后无断言"的空档插入 wait + assert（optional）
    """
    if not steps:
        return steps

    result = []
    steps_cp = deepcopy(steps)

    for i, step in enumerate(steps_cp):
        action   = step.get("action", "")
        selector = step.get("selector", "").strip()

        # ── 推导候选 selectors ──
        if selector and action not in ("navigate", "wait", "wait_for",
                                       "assert_url", "assert_title",
                                       "screenshot", "evaluate", "press"):
            candidates = generate_candidate_selectors(step)
            step["selectors"] = candidates
            # robustness 取候选列表第一个的等级
            best_sel = candidates[0] if candidates else selector
            step["robustness"] = selector_grade(best_sel)
        else:
            # 无 selector 或 navigate 类：robustness 不适用，标 A
            step["robustness"] = "A"
            if "selectors" not in step:
                step["selectors"] = []

        result.append(step)

        # ── 关键操作后无断言 → 插入 wait + assert ──
        if _is_key_action(step):
            next_step = steps_cp[i + 1] if i + 1 < len(steps_cp) else None
            if next_step is None or next_step.get("action") not in _ASSERT_ACTIONS:
                for auto_step in _make_wait_assert(step, i + 1):
                    result.append(auto_step)

    # 重新编号 id（保持 s001, s002 格式，兼容已有 id）
    for idx, step in enumerate(result, 1):
        if not step.get("id") or step.get("_auto_inserted"):
            step["id"] = f"s{idx:03d}"
        step.pop("_auto_inserted", None)

    return result


# ── 5. AI 增强（可选，LLM 批量生成候选） ──────────────────────────────────────

def _build_elements_summary(page_elements: Optional[list]) -> str:
    """把页面元素压缩成给 LLM 的候选 selector 摘要（仅保留有真实 selector 的交互元素）。"""
    if not page_elements:
        return ""
    bare_tags = {"a", "button", "input", "select", "textarea", "div", "span", ""}
    lines = []
    for e in page_elements[:200]:
        selector = (e.get("selector") or "").strip()
        if not selector or selector in bare_tags:
            continue
        tag = e.get("tag", "")
        text = (e.get("text") or "").strip()[:40]
        placeholder = (e.get("placeholder") or "").strip()[:40]
        label = (e.get("label") or e.get("aria_label") or "").strip()[:40]
        name = (e.get("name") or "").strip()
        frame = (e.get("frame_selectors") or [])
        parts = [f"<{tag}"]
        if text:
            parts.append(f" text={text!r}")
        if placeholder:
            parts.append(f" placeholder={placeholder!r}")
        if label:
            parts.append(f" label={label!r}")
        if name:
            parts.append(f" name={name!r}")
        if frame:
            parts.append(f" frame={frame!r}")
        parts.append(f" selector={selector!r}>")
        lines.append("".join(parts))
    return "\n".join(lines)


def _slice_json_array(text: str) -> str:
    """从文本中截取第一个完整 JSON 数组（按括号/字符串配对），找不到返回空串。"""
    start = text.find('[')
    if start < 0:
        return ""
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ""


async def ai_enrich_selectors(steps: list, timeout_secs: int = 30, page_elements: Optional[list] = None) -> list:
    """
    对规则推导覆盖不足的步骤，让 LLM 生成候选 selector。

    覆盖两类场景：
    1. robustness=D 且 selectors ≤1（有 selector 但等级低）
    2. selector 为空 且 description/value 有语义信息（AI 生成用例常见）

    传入 page_elements 时，LLM 会优先从真实页面元素里匹配 selector（准确率更高）；
    未传时退化为按 description/value 语义推断。

    失败时静默返回原列表，不影响主流程。
    """
    _skip_actions = ("navigate", "wait", "wait_for", "evaluate", "screenshot",
                     "assert_url", "assert_title", "press")
    need_ai = [
        (i, s) for i, s in enumerate(steps)
        if s.get("action") not in _skip_actions
        and (
            # 场景1：有 selector 但等级低
            (s.get("robustness") == "D"
             and len(s.get("selectors") or []) <= 1
             and s.get("selector"))
            or
            # 场景2：无 selector，但描述有足够语义（去掉标记前缀后有内容）
            (not s.get("selector")
             and (s.get("description", "").replace("[需补充selector]", "").strip()
                  or s.get("value", "").strip()))
        )
    ]
    if not need_ai:
        return steps

    elements_summary = _build_elements_summary(page_elements)

    try:
        from tools.llm_client import call_llm

        # 批量构建 prompt
        step_lines = []
        for idx, (i, s) in enumerate(need_ai):
            # 对空 selector 的步骤，description 是主要信息源
            desc = s.get("description", "").replace("[需补充selector]", "").strip()
            frame = s.get("frame_selectors") or []
            line = (
                f"{idx+1}. action={s['action']} "
                f"selector={s.get('selector','')!r} "
                f"description={desc!r} "
                f"value={s.get('value','')!r}"
            )
            if frame:
                line += f" frame={frame!r}"
            step_lines.append(line)

        if elements_summary:
            system = (
                "You are a Playwright/Selenium selector expert. "
                "For each step, generate 3-5 CSS selectors ordered by stability.\n"
                "  Priority 1: [data-testid=...], [aria-label=...], [name=...], [placeholder=...]\n"
                "  Priority 2: button:has-text('...'), input:has-text('...'), :has-text('...')\n"
                "  Priority 3: .className, tag[attr=...]\n"
                "  Priority 4: #id\n"
                "STRICT RULE: only pick selectors that appear in the 'Available page elements' list. "
                "Do NOT invent selectors not present in that list. "
                "Match each step to the most semantically relevant element (by text/placeholder/name/label). "
                "If the matched element carries a 'frame' field, it lives inside iframe(s); "
                "copy that exact frame array into the output 'frame' field. "
                "If no element matches a step, return selectors=[] for that step.\n"
                "Output ONLY valid JSON array of objects. No explanation."
            )
            user = (
                "Generate selectors for these test steps:\n"
                + "\n".join(step_lines)
                + "\n\nAvailable page elements (only use selectors from here):\n"
                + elements_summary
                + "\n\nOutput format (one object per step, same order): "
                + '[{"selectors": ["sel1","sel2",...], "frame": ["iframe#a", "iframe#b"]}, ...]'
                + "\n'frame' is optional; use [] when the element is not inside an iframe."
            )
        else:
            system = (
                "You are a Playwright/Selenium selector expert. "
                "For each step, generate 3-5 CSS selectors ordered by stability:\n"
                "  Priority 1: [data-testid=...], [aria-label=...], [name=...], [placeholder=...]\n"
                "  Priority 2: button:has-text('...'), input:has-text('...'), :has-text('...')\n"
                "  Priority 3: .className, tag[attr=...]\n"
                "  Priority 4: #id\n"
                "When selector is empty, infer from description and value fields.\n"
                "Output ONLY valid JSON array of objects. No explanation."
            )
            user = (
                "Generate selectors for these test steps:\n"
                + "\n".join(step_lines)
                + "\n\nOutput format (one object per step, same order): "
                + '[{"selectors": ["sel1","sel2",...], "frame": []}, ...]'
                + "\nUse 'frame': [] unless the step already provided a frame path."
            )

        raw = await call_llm(system, user, max_tokens=1200, timeout_secs=timeout_secs)
        raw = raw.strip()

        # 提取 JSON 数组（兼容对象数组 [{"selectors":...}] 与旧版嵌套数组 [[...]]）
        seg = _slice_json_array(raw)
        if not seg:
            return steps
        try:
            ai_candidates = json.loads(seg)
        except json.JSONDecodeError:
            return steps
        if not isinstance(ai_candidates, list):
            return steps

        steps_result = deepcopy(steps)
        for idx, (i, _) in enumerate(need_ai):
            if idx >= len(ai_candidates):
                break
            item = ai_candidates[idx]
            if isinstance(item, dict):
                new_cands = [c.strip() for c in (item.get("selectors") or []) if isinstance(c, str) and c.strip()]
                frame = item.get("frame") or item.get("frame_selectors") or []
            else:
                # 兼容旧版纯数组格式
                new_cands = [c.strip() for c in (item or []) if isinstance(c, str) and c.strip()]
                frame = []
            # 保留/回填 iframe 路径（LLM 返回非空时优先）
            if frame and isinstance(frame, list):
                cleaned_frame = [str(f).strip() for f in frame if str(f).strip()]
                if cleaned_frame:
                    steps_result[i]["frame_selectors"] = cleaned_frame
            if not new_cands:
                continue
            existing = steps_result[i].get("selectors") or []
            merged = []
            seen = set()
            for sel in new_cands + existing:
                if sel not in seen:
                    merged.append(sel)
                    seen.add(sel)
            merged.sort(key=lambda s: {"A": 0, "B": 1, "C": 2, "D": 3}.get(selector_grade(s), 4))
            steps_result[i]["selectors"] = merged
            # 同步更新 selector 主值（如果原来为空，取推导结果的第一个）
            if merged and not steps_result[i].get("selector"):
                steps_result[i]["selector"] = merged[0]
            if merged:
                steps_result[i]["robustness"] = selector_grade(merged[0])

        empty_count = sum(1 for _, s in need_ai if not s.get("selector"))
        logger.info(f"[step_hardener] AI 增强了 {len(need_ai)} 个步骤的候选 selector（含 {empty_count} 个空 selector）")
        return steps_result

    except Exception as e:
        logger.warning(f"[step_hardener] AI 增强 selector 失败（静默）: {e}")
        return steps


# ── 6. 便捷入口：harden_and_ai_enrich ────────────────────────────────────────

async def harden_and_enrich(steps: list, use_ai: bool = True, page_elements: Optional[list] = None) -> list:
    """
    完整健壮化流程：规则健壮化 → (可选) AI 增强 D 级 selector。
    recording/save 接口调用此函数。
    page_elements 传入后，AI 增强会优先从真实页面元素匹配 selector。
    """
    hardened = harden_steps(steps)
    if use_ai:
        hardened = await ai_enrich_selectors(hardened, page_elements=page_elements)
    return hardened
