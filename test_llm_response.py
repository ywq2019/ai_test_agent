"""临时测试：直接调用 LLM API，打印完整响应，诊断 case_generator 的 Expecting value 错误"""
import asyncio
import httpx
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

async def main():
    from tools.config import settings

    api_key  = settings.AI_API_KEY
    base_url = (settings.AI_API_URL or "").rstrip("/")
    model    = settings.AI_MODEL or "deepseek-v4-flash"

    print(f"API URL : {base_url}")
    print(f"Model   : {model}")
    print(f"API Key : {api_key[:8]}..." if api_key else "API Key : <empty>")

    url = f"{base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Output only valid JSON."},
            {"role": "user",   "content": 'Return this JSON exactly: {"test": "ok", "status": 200}'},
        ],
    }

    print("\n--- 发送请求 ---")
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        print(f"HTTP Status: {resp.status_code}")
        print(f"Response body ({len(resp.text)} chars):")
        print(resp.text[:2000])

        if resp.status_code == 200:
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"\n--- content 字段 ({len(content)} chars) ---")
            print(repr(content))
            if content.strip():
                try:
                    parsed = json.loads(content.strip())
                    print(f"\nJSON 解析成功: {parsed}")
                except Exception as e:
                    print(f"\nJSON 解析失败: {e}")
            else:
                print("\n*** content 为空！这是 Expecting value 错误的原因 ***")

asyncio.run(main())
