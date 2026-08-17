"""
极简越权漏洞靶场（用于端到端验证双账号横向越权检测）

启动：
    python mock_target.py          # http://127.0.0.1:9999

内置账号：
    账号 A：user_id=1001，token=token-A-1001
    账号 B：user_id=1002，token=token-B-1002

越权漏洞点：
    GET /api/user/{user_id} 仅校验 Authorization 是否有效（token 存在即通过），
    不校验 user_id 是否属于当前 token 对应的用户。
    → 用账号 B 的 token 访问 /api/user/1001（账号 A 的资源）也能成功返回 Alice 数据，
      即典型 IDOR / BOLA 横向越权。

登录接口（方便手动取 token）：
    GET /api/login/A   → {"token": "token-A-1001", "user_id": 1001}
    GET /api/login/B   → {"token": "token-B-1002", "user_id": 1002}
"""
from fastapi import FastAPI, Header, HTTPException
import uvicorn

app = FastAPI(title="越权漏洞靶场")

# token -> 账号身份
_ACCOUNTS = {
    "token-A-1001": {"user_id": 1001, "name": "Alice"},
    "token-B-1002": {"user_id": 1002, "name": "Bob"},
}

# 用户资源（模拟敏感数据）
_RESOURCES = {
    1001: {"user_id": 1001, "name": "Alice", "email": "alice@example.com",
           "balance": 10000, "secret": "alice_secret_data"},
    1002: {"user_id": 1002, "name": "Bob", "email": "bob@example.com",
           "balance": 200, "secret": "bob_secret_data"},
}


@app.get("/api/login/{who}")
def login(who: str):
    """登录：A/B 分别返回对应 token，方便手动取凭证。"""
    token = f"token-{who.upper()}-1001" if who.upper() == "A" else f"token-{who.upper()}-1002"
    if token not in _ACCOUNTS:
        raise HTTPException(status_code=404, detail="unknown account")
    return {"token": token, "user_id": _ACCOUNTS[token]["user_id"]}


@app.get("/api/user/{user_id}")
def get_user(user_id: int, authorization: str = Header(default="")):
    """
    BOLA 漏洞接口：
      1. 校验 token 是否存在（有效登录态）
      2. 但【不校验】user_id 是否属于该 token 用户 → 横向越权
    """
    token = authorization.replace("Bearer", "").strip()
    if token not in _ACCOUNTS:
        raise HTTPException(status_code=401, detail="unauthorized")
    if user_id not in _RESOURCES:
        raise HTTPException(status_code=404, detail="not found")
    return _RESOURCES[user_id]


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9999)
