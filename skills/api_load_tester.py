"""
接口压力测试引擎
asyncio + Semaphore 并发控制，每秒采样推送 TPS / 延迟 / 错误率
"""
import asyncio
import time
import statistics
from typing import List, Dict, Any, Optional, Callable
from loguru import logger


class ApiLoadTester:
    def __init__(self):
        self._stop = False

    def stop(self):
        self._stop = True

    async def run(
        self,
        project: Dict,
        cases: List[Dict],
        config: Dict,
        metrics_cb: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        import httpx
        from skills.api_executor import ApiExecutor

        self._stop = False
        executor = ApiExecutor()
        auth_headers = executor.build_auth_headers(project)
        global_headers = project.get("global_headers") or {}
        base_url = (project.get("base_url") or "").rstrip("/")
        project_name = project.get("name", "")
        project_id = project.get("id")

        enabled = [c for c in cases if c.get("enabled", True)]
        if not enabled:
            return {"error": "没有启用的用例"}

        concurrent = max(1, config.get("concurrent_users", 10))
        duration = max(1, config.get("duration", 60))
        ramp_up = max(0, config.get("ramp_up", 10))

        # ── 加载当前项目的自定义脚本（供动态参数 {{fn()}} 使用）────────────
        custom_scripts: List[Dict] = []
        if project_id:
            try:
                from tools.database import async_session_maker, CustomScript
                from sqlalchemy import select, or_
                async with async_session_maker() as s:
                    q = select(CustomScript).where(
                        or_(CustomScript.project_id == project_id,
                            CustomScript.project_id == None)
                    )
                    scripts = (await s.execute(q)).scalars().all()
                    custom_scripts = [{"name": sc.name, "code": sc.code} for sc in scripts]
                logger.debug(f"[load] 已加载 {len(custom_scripts)} 个自定义脚本")
            except Exception as e:
                logger.warning(f"[load] 加载自定义脚本失败: {e}")

        all_results: List[Dict] = []
        window: List[Dict] = []
        start_time = time.time()
        case_idx = [0]
        sem = asyncio.Semaphore(concurrent)

        # ── 共享 AsyncClient（利用连接池，避免高并发下每次新建连接）─────────
        shared_client = httpx.AsyncClient(verify=False, timeout=30.0)

        async def one_req():
            case = enabled[case_idx[0] % len(enabled)]
            case_idx[0] += 1
            async with sem:
                return await executor._run_case(
                    shared_client, base_url, case, auth_headers, global_headers,
                    custom_scripts=custom_scripts, project_name=project_name,
                )

        async def worker():
            while not self._stop:
                elapsed = time.time() - start_time
                if elapsed >= duration:
                    break
                if ramp_up > 0 and elapsed < ramp_up:
                    await asyncio.sleep(ramp_up / concurrent / 10)
                r = await one_req()
                all_results.append(r)
                window.append(r)

        async def sampler():
            while not self._stop and (time.time() - start_time) < duration:
                await asyncio.sleep(1.0)
                if not metrics_cb:
                    continue
                snap, window[:] = window[:], []
                if not snap:
                    continue
                elapsed = round(time.time() - start_time, 1)
                durations = [r["duration_ms"] for r in snap if r.get("duration_ms") is not None]
                errors = sum(1 for r in snap if r["status"] == "failed")
                await metrics_cb({
                    "elapsed": elapsed,
                    "tps": len(snap),
                    "avg_ms": round(statistics.mean(durations), 1) if durations else 0,
                    "p95_ms": round(self._pct(durations, 95), 1) if durations else 0,
                    "error_rate": round(errors / len(snap) * 100, 1),
                    "total_requests": len(all_results),
                })

        workers = [worker() for _ in range(concurrent)]
        try:
            await asyncio.gather(*workers, sampler(), return_exceptions=True)
        finally:
            await shared_client.aclose()

        elapsed = time.time() - start_time
        return self._report(all_results, elapsed, config)

    def _report(self, results: List[Dict], elapsed: float, config: Dict) -> Dict:
        if not results:
            return {"total_requests": 0, "passed": 0, "failed": 0}
        passed = [r for r in results if r["status"] == "passed"]
        durations = [r["duration_ms"] for r in results if r.get("duration_ms") is not None]
        return {
            "total_requests": len(results),
            "passed": len(passed),
            "failed": len(results) - len(passed),
            "success_rate": round(len(passed) / len(results) * 100, 1),
            "avg_tps": round(len(results) / elapsed, 2) if elapsed else 0,
            "avg_ms": round(statistics.mean(durations), 1) if durations else 0,
            "min_ms": min(durations) if durations else 0,
            "max_ms": max(durations) if durations else 0,
            "p50_ms": round(self._pct(durations, 50), 1) if durations else 0,
            "p95_ms": round(self._pct(durations, 95), 1) if durations else 0,
            "p99_ms": round(self._pct(durations, 99), 1) if durations else 0,
            "duration_secs": round(elapsed, 1),
            "config": config,
        }

    def _pct(self, data: List, p: int) -> float:
        if not data:
            return 0
        s = sorted(data)
        return s[max(0, int(len(s) * p / 100) - 1)]


api_load_tester = ApiLoadTester()
