"""
临时诊断：模拟 generate_cases 的完整流程
重现 Expecting value 错误并打印 LLM 实际收到的 prompt 内容
"""
import asyncio
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

async def main():
    # 1. 解析 PDF
    from tools.document_parser import DocumentParser
    parser = DocumentParser()
    doc = await parser.parse('uploads/documents/834481a98cfe9942.pdf')
    content = doc.get('content', '')
    print(f"[PDF] content 长度: {len(content)} 字")
    print(f"[PDF] 前200字: {content[:200]}")
    print()

    # 2. 模拟 _generate_doc_driven 里的 prompt 构建
    url = "https://m.hqwx.com/micropage/memberDay"
    doc_text = content

    if not doc_text or len(doc_text.strip()) < 30:
        print("[ERROR] 文档内容不足，无法生成用例")
        return

    prompt = f"""根据以下需求文档，为页面「{url}」生成功能测试用例（15-25条）。

需求文档：
---
{doc_text[:12000]}
---

覆盖要求：
1. 按功能模块分组，每模块3-6条用例
2. 覆盖正常流程(P0/P1)、边界值、异常分支(P2)
3. 步骤要具体可操作，预期结果可断言
4. 优先级：P0=核心主流程，P1=主要功能，P2=边界/异常

只输出纯JSON：
{{
  "cases": [
    {{
      "name": "模块-场景描述",
      "module": "所属功能模块",
      "priority": "P0",
      "preconditions": "前置条件",
      "steps": "1. 操作步骤",
      "expected_results": "可断言的预期结果",
      "element_selector": ""
    }}
  ]
}}"""

    print(f"[PROMPT] 长度: {len(prompt)} 字")
    print(f"[PROMPT] 前100字: {prompt[:100]}")
    print()

    # 3. 实际调用 LLM
    import httpx, json
    from tools.config import settings

    base_url = (settings.AI_API_URL or "").rstrip("/")
    api_key  = settings.AI_API_KEY
    model    = settings.AI_MODEL

    url_api  = f"{base_url}/v1/chat/completions"
    headers  = {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}
    payload  = {
        "model": model,
        "max_tokens": 8192,
        "messages": [
            {"role": "system", "content": "You are a senior QA engineer. Generate functional test cases based on requirements documents. Output ONLY a single valid JSON object. No markdown, no explanation."},
            {"role": "user",   "content": prompt},
        ],
    }

    print("[LLM] 发送请求...")
    async with httpx.AsyncClient(verify=False, timeout=120) as client:
        resp = await client.post(url_api, json=payload, headers=headers)
        print(f"[LLM] HTTP Status: {resp.status_code}")
        raw_response = resp.text
        print(f"[LLM] 响应体长度: {len(raw_response)}")

        if resp.status_code != 200:
            print(f"[LLM] 错误响应: {raw_response[:500]}")
            return

        data = resp.json()
        content_field = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"[LLM] content 字段长度: {len(content_field)}")
        print(f"[LLM] content 前200字: {content_field[:200]}")

        if not content_field.strip():
            print("[ERROR] content 为空！这就是 Expecting value 错误的原因")
            print("[LLM] 完整响应:", raw_response[:1000])
        else:
            # 尝试 JSON 解析
            raw = content_field.strip()
            if "```json" in raw:
                raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in raw:
                raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
            try:
                result = json.loads(raw)
                cases = result.get("cases", [])
                print(f"[OK] JSON 解析成功，生成 {len(cases)} 条用例")
                if cases:
                    print(f"[OK] 第1条: {cases[0].get('name','?')}")
            except Exception as e:
                print(f"[ERROR] JSON 解析失败: {e}")
                print(f"[ERROR] raw content: {raw[:300]}")

asyncio.run(main())
