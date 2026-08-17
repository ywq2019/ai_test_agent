"""
一键端到端验证：双账号横向越权（P0）置信度分级（P1）

前提：
  1. 越权靶场 mock_target.py 已启动（默认 http://127.0.0.1:9999）
  2. 平台后端 main.py 已启动（默认 http://localhost:4000）

流程：
  登录 → 建工作空间 → 建接口项目(账号A) → 建用例(GET /api/user/1001)
  → 建任务A(带第二账号B凭证) → 执行 → 查 findings → 期望 confidence=confirmed
  → 建任务B(不带第二账号)   → 执行 → 查 findings → 期望 confidence=suspected

用法：
  python verify_idor_e2e.py [--base http://localhost:4000] [--target http://127.0.0.1:9999]
"""
import argparse
import json
import sys
import time

import httpx

# 靶场内置账号
TOKEN_A = "token-A-1001"   # 账号 A（资源所有者，user_id=1001）
TOKEN_B = "token-B-1002"   # 账号 B（攻击者，user_id=1002）


class Client:
    def __init__(self, base: str, token: str):
        self.c = httpx.Client(base_url=base.rstrip("/"), verify=False, timeout=30)
        self.c.headers["Authorization"] = f"Bearer {token}"

    def post(self, path, **kw):
        r = self.c.post(path, **kw)
        return self._check(r)

    def get(self, path, **kw):
        r = self.c.get(path, **kw)
        return self._check(r)

    @staticmethod
    def _check(r: httpx.Response):
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} {r.request.method} {r.request.url}: {r.text[:300]}")
        return r.json()


def wait_task_done(cli: Client, workspace_id: int, task_id: int, timeout: float = 90.0):
    """轮询任务状态，直到 done/failed/cancelled，返回任务 dict。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        tasks = cli.get("/api/v1/pentest/tasks", params={"workspace_id": workspace_id})
        t = next((x for x in tasks if x["id"] == task_id), None)
        if t and t["status"] in ("done", "failed", "cancelled"):
            return t
        time.sleep(1.5)
    raise TimeoutError(f"任务 {task_id} 在 {timeout}s 内未完成")


def run_one_case(cli: Client, workspace_id: int, project_id: int, case_id: int,
                 second_headers: dict | None, label: str) -> list:
    """创建并执行一个渗透任务，返回 findings 列表。"""
    body = {
        "name": f"验证-{label}",
        "workspace_id": workspace_id,
        "project_id": project_id,
        "scan_modules": ["idor"],
        "case_ids": [case_id],
        "concurrency": 1,
    }
    if second_headers:
        body["second_headers"] = second_headers

    task = cli.post("/api/v1/pentest/tasks", json=body)
    task_id = task["id"]
    cli.post(f"/api/v1/pentest/tasks/{task_id}/run")
    final = wait_task_done(cli, workspace_id, task_id)
    if final["status"] != "done":
        print(f"  [{label}] 任务状态异常: {final['status']}", file=sys.stderr)
        return []
    findings = cli.get(f"/api/v1/pentest/tasks/{task_id}/findings")
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:4000")
    ap.add_argument("--target", default="http://127.0.0.1:9999")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="admin123")
    args = ap.parse_args()

    # 1. 登录
    anon = httpx.Client(base_url=args.base.rstrip("/"), verify=False, timeout=30)
    r = anon.post("/api/v1/auth/login", json={"username": args.username, "password": args.password})
    if r.status_code != 200:
        raise SystemExit(f"登录失败: {r.status_code} {r.text}")
    token = r.json()["access_token"]
    cli = Client(args.base, token)
    print(f"[1] 登录成功，用户={args.username}")

    # 2. 建工作空间
    ws = cli.post("/api/v1/workspaces", json={"name": f"idor验证_{int(time.time())}"})
    ws_id = ws["id"]
    print(f"[2] 工作空间创建 id={ws_id}")

    # 3. 建接口项目（账号A身份）
    proj = cli.post("/api/v1/api-test/projects", json={
        "name": "越权靶场",
        "base_url": args.target.rstrip("/"),
        "workspace_id": ws_id,
        "auth_type": "none",
        "global_headers": {"Authorization": f"Bearer {TOKEN_A}"},
    })
    proj_id = proj["id"]
    print(f"[3] 接口项目创建 id={proj_id} base_url={args.target}")

    # 4. 建用例：账号A自己的资源 /api/user/1001
    case = cli.post("/api/v1/api-test/cases", json={
        "project_id": proj_id,
        "name": "查询本人资料(账号A)",
        "method": "GET",
        "path": "/api/user/1001",
    })
    case_id = case["id"]
    print(f"[4] 用例创建 id={case_id} GET /api/user/1001")

    # 5. 场景A：带第二账号 → 期望 confirmed
    print("\n== 场景A：配置第二账号B凭证（期望 confirmed）==")
    findings_a = run_one_case(
        cli, ws_id, proj_id, case_id,
        second_headers={"Authorization": f"Bearer {TOKEN_B}"},
        label="双账号越权",
    )

    # 6. 场景B：不带第二账号 → 期望 suspected
    print("\n== 场景B：不配置第二账号（期望 suspected）==")
    findings_b = run_one_case(
        cli, ws_id, proj_id, case_id,
        second_headers=None,
        label="单账号ID替换",
    )

    # 7. 汇总结果
    print("\n" + "=" * 70)
    print("验证结果汇总")
    print("=" * 70)
    for label, findings in (("A-双账号越权", findings_a), ("B-单账号ID替换", findings_b)):
        print(f"\n【{label}】发现 {len(findings)} 条")
        if not findings:
            print("  （无 findings，请检查靶场是否在运行）")
            continue
        for f in findings:
            conf = f.get("confidence", "?")
            mark = "[确定]" if conf == "confirmed" else ("[疑似]" if conf == "suspected" else "[?]")
            print(f"  {mark} [{f['severity']}] {f['vuln_type']} confidence={conf}")
            print(f"      payload: {f.get('payload')}")

    # 8. 断言
    conf_a = {f.get("confidence") for f in findings_a}
    conf_b = {f.get("confidence") for f in findings_b}
    ok_a = "confirmed" in conf_a
    ok_b = "suspected" in conf_b and "confirmed" not in conf_b
    print("\n" + "=" * 70)
    print(f"场景A 命中 confirmed：{'[PASS]' if ok_a else '[FAIL]'}  (实际: {conf_a or '无'})")
    print(f"场景B 命中 suspected：{'[PASS]' if ok_b else '[FAIL]'}  (实际: {conf_b or '无'})")
    print("=" * 70)
    print(f"\n资源ID（可到 UI 查看，workspace_id={ws_id}）")

    if not (ok_a and ok_b):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
