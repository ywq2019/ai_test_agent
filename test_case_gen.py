"""
模拟 ai_case_generator._run_claude_subprocess 完整调用，打印真实错误
运行方式：python test_case_gen.py
"""
import asyncio
import json
import sys
import os

# 让项目模块可以 import
sys.path.insert(0, os.path.dirname(__file__))

async def test():
    # 1. 读取当前 settings（走 .env）
    from tools.config import settings
    api_key  = settings.AI_API_KEY
    base_url = (settings.AI_API_URL or "").rstrip("/")
    model    = settings.AI_MODEL or "deepseek-v4-flash"

    print(f"=== 当前 LLM 配置 ===")
    print(f"  AI_API_URL : {base_url}")
    print(f"  AI_MODEL   : {model}")
    print(f"  AI_API_KEY : {api_key[:12]}... (len={len(api_key)})")

    # 2. 走修复后的 is_anthropic 判断
    is_anthropic = "anthropic.com" in base_url
    print(f"  is_anthropic: {is_anthropic}")
    print()

    if is_anthropic:
        url     = f"{base_url}/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 100,
            "system": "Output ONLY valid JSON.",
            "messages": [{"role": "user", "content": 'Return this exact JSON: {"modules":[{"name":"test","features":["f1"]}]}'}],
        }
    else:
        url     = f"{base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 100,
            "messages": [
                {"role": "system", "content": "Output ONLY valid JSON."},
                {"role": "user",   "content": 'Return this exact JSON: {"modules":[{"name":"test","features":["f1"]}]}'},
            ],
        }

    print(f"=== 发送请求 ===")
    print(f"  POST {url}")

    import httpx
    try:
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            print(f"  HTTP {resp.status_code}")
            data = resp.json()
    except Exception as e:
        print(f"  [EXCEPTION] {type(e).__name__}: {e}")
        return

    print(f"\n=== 原始响应 ===")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:1000])

    # 3. 模拟解析逻辑
    print(f"\n=== 解析结果 ===")
    try:
        if is_anthropic:
            content_field = data.get("content")
            if not content_field:
                print(f"  [FAIL] Anthropic 无 content 字段")
                return
            if isinstance(content_field, list):
                text_blocks = [b for b in content_field if isinstance(b, dict) and b.get("type") == "text"]
                raw = text_blocks[0].get("text", "") if text_blocks else ""
            else:
                raw = content_field
        else:
            raw = data["choices"][0]["message"]["content"]

        raw = raw.strip()
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

        result = json.loads(raw)
        print(f"  [OK] JSON 解析成功: {json.dumps(result, ensure_ascii=False)}")
    except Exception as e:
        print(f"  [FAIL] 解析异常: {type(e).__name__}: {e}")
        print(f"  raw 内容: {repr(raw[:300]) if 'raw' in dir() else '(未拿到raw)'}")


asyncio.run(test())
