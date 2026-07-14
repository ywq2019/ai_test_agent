"""
快速诊断 LLM API 是否可用
运行方式：python test_api.py
"""
import asyncio
import json
import httpx


API_KEY  = "sk-Q8FnN4UgBVMd4PiSKHTO0gUaonjdmKwdb1jbRpvGOY8pBAEL"
BASE_URL = "https://aims.hqwx.com"
MODEL    = "claude-sonnet-4-6"


async def test():
    url = f"{BASE_URL}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": 100,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Reply in one sentence."},
            {"role": "user",   "content": "Say: OK"},
        ],
    }

    print(f"→ POST {url}")
    print(f"→ model: {MODEL}\n")

    try:
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            print(f"HTTP状态码: {resp.status_code}")
            data = resp.json()
            print(f"响应体: {json.dumps(data, ensure_ascii=False, indent=2)[:800]}")

            if resp.status_code == 200:
                text = data["choices"][0]["message"]["content"]
                print(f"\n✅ API正常，模型回复: {text}")
            else:
                print(f"\n❌ API返回错误: {data.get('error') or data}")
    except Exception as e:
        print(f"\n❌ 请求异常: {type(e).__name__}: {e}")


asyncio.run(test())
