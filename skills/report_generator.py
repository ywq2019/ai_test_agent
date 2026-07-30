"""
测试报告生成技能
"""
import json
import base64
import mimetypes
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from pathlib import Path
from loguru import logger
from tools.config import settings

_TZ_CST = timezone(timedelta(hours=8))


def _fmt_dt_cst(dt_or_str) -> str:
    """将 UTC naive datetime 或 ISO 字符串格式化为 CST（UTC+8）可读时间。"""
    if not dt_or_str:
        return "—"
    if isinstance(dt_or_str, str):
        try:
            dt_or_str = datetime.fromisoformat(dt_or_str)
        except ValueError:
            return dt_or_str
    if dt_or_str.tzinfo is None:
        dt_or_str = dt_or_str.replace(tzinfo=timezone.utc)
    return dt_or_str.astimezone(_TZ_CST).strftime("%Y-%m-%d %H:%M:%S")


def _screenshot_data_uri(shot: str) -> str:
    """把截图路径/URL 转成 base64 data URI，供 HTML/PDF 内嵌。"""
    if not shot:
        return shot
    if shot.startswith("/screenshots/"):
        filename = shot[len("/screenshots/"):]
        disk_path = Path(settings.SCREENSHOT_DIR) / filename
    elif shot.startswith("http://") or shot.startswith("https://"):
        return shot  # 远程 URL 无法内嵌
    else:
        disk_path = Path(shot)

    try:
        if not disk_path.is_absolute():
            disk_path = Path(__file__).parent.parent / disk_path
        with open(disk_path, "rb") as fh:
            raw = fh.read()
        mime = mimetypes.guess_type(str(disk_path))[0] or "image/png"
        b64  = base64.b64encode(raw).decode()
        return f"data:{mime};base64,{b64}"
    except Exception:
        return shot


class ReportGenerator:
    def __init__(self):
        self.report_dir = Path(settings.REPORT_OUTPUT_DIR)
        self.report_dir.mkdir(exist_ok=True)

    async def generate_report(
        self,
        task_id: int,
        task_name: str,
        results: List[Dict[str, Any]],
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        logger.info(f"Generating report for task {task_id}")

        summary = self._calculate_summary(results)
        charts = self._generate_charts_data(summary)
        details = self._prepare_details(results)

        now_cst = datetime.now(_TZ_CST)
        report = {
            "task_id": task_id,
            "task_name": task_name,
            "summary": summary,
            "charts": charts,
            "details": details,
            "metadata": metadata or {},
            "generated_at": now_cst.strftime("%Y-%m-%d %H:%M:%S")
        }

        ts = now_cst.strftime('%Y%m%d_%H%M%S')
        report_path = self.report_dir / f"report_{task_id}_{ts}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"Report saved to {report_path}")

        html_path = await self._generate_html_report(report, task_name, ts)

        return {
            "report": report,
            "report_path": str(report_path),
            "html_path": str(html_path)
        }

    def _calculate_summary(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(results)
        passed = sum(1 for r in results if r.get("status") == "passed")
        failed = sum(1 for r in results if r.get("status") == "failed")
        skipped = sum(1 for r in results if r.get("status") == "skipped")

        pass_rate = (passed / total * 100) if total > 0 else 0

        total_duration = sum(r.get("duration", 0) for r in results)

        failed_cases = [
            {
                "case_name": r.get("case_name", "Unknown"),
                "error": r.get("error_message", "Unknown error"),
                "duration": r.get("duration", 0)
            }
            for r in results if r.get("status") == "failed"
        ]

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pass_rate": round(pass_rate, 2),
            "total_duration": round(total_duration, 2),
            "failed_cases": failed_cases
        }

    def _generate_charts_data(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "pass_rate_pie": {
                "title": "用例通过率",
                "data": [
                    {"name": "通过", "value": summary["passed"]},
                    {"name": "失败", "value": summary["failed"]},
                    {"name": "跳过", "value": summary["skipped"]}
                ]
            },
            "status_bar": {
                "title": "用例执行状态",
                "categories": ["通过", "失败", "跳过"],
                "data": [summary["passed"], summary["failed"], summary["skipped"]]
            }
        }

    def _prepare_details(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        details = []
        for idx, result in enumerate(results, 1):
            details.append({
                "id": idx,
                "case_name": result.get("case_name", "Unknown"),
                "status": result.get("status", "unknown"),
                "duration": round(result.get("duration", 0), 2),
                "error_message": result.get("error_message"),
                "screenshot": result.get("screenshot_path"),
                "start_time": result.get("start_time"),
                "end_time": result.get("end_time")
            })
        return details

    async def _generate_html_report(self, report: Dict[str, Any], task_name: str, ts: str = None) -> Path:
        html_content = self._build_html_template(report, task_name)

        if ts is None:
            ts = datetime.now(_TZ_CST).strftime('%Y%m%d_%H%M%S')
        html_path = self.report_dir / f"report_{report['task_id']}_{ts}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return html_path

    def _build_html_template(self, report: Dict[str, Any], task_name: str) -> str:
        summary = report["summary"]

        details_rows = ""
        for detail in report["details"]:
            status_class = {
                "passed": "success",
                "failed": "danger",
                "skipped": "warning"
            }.get(detail["status"], "secondary")
            status_label = {
                "passed": "通过",
                "failed": "失败",
                "skipped": "跳过"
            }.get(detail["status"], detail["status"])

            screenshot_cell = ""
            if detail.get("screenshot"):
                data_uri = _screenshot_data_uri(detail["screenshot"])
                screenshot_cell = (
                    f'<td><a href="{data_uri}" target="_blank" style="display:inline-block">'
                    f'<img src="{data_uri}" style="max-width:120px;max-height:80px;'
                    f'border-radius:4px;border:1px solid #e8e8e8;cursor:pointer" title="点击查看原图"/>'
                    f'</a></td>'
                )
            else:
                screenshot_cell = "<td style='color:#ccc'>-</td>"

            error_cell = detail.get("error_message", "-")
            if error_cell and len(error_cell) > 100:
                error_cell = error_cell[:100] + "..."

            details_rows += f"""
            <tr>
                <td>{detail['id']}</td>
                <td>{detail['case_name']}</td>
                <td><span class="badge bg-{status_class}">{status_label}</span></td>
                <td>{detail['duration']}s</td>
                <td>{error_cell}</td>
                {screenshot_cell}
            </tr>
            """

        pass_rate = summary['pass_rate']
        pr_color = "#52c41a" if pass_rate >= 80 else "#ff4d4f"
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>测试报告 - {task_name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f0f2f5;padding:24px;color:#1a1a1a}}
.container{{max-width:1100px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1a2a4a 0%,#2d4a7a 100%);color:#fff;padding:32px 36px;border-radius:10px;margin-bottom:20px;box-shadow:0 4px 12px rgba(0,0,0,.15)}}
.header h1{{font-size:24px;font-weight:700;margin-bottom:6px}}
.header .meta{{font-size:12px;opacity:.6;margin-top:12px}}
.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:20px}}
.card{{background:#fff;padding:18px 12px;border-radius:8px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.card .num{{font-size:28px;font-weight:700;margin-bottom:4px}}
.card .lbl{{font-size:12px;color:#888}}
.section{{background:#fff;padding:24px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.06);margin-bottom:20px}}
.section h2{{font-size:15px;font-weight:700;padding-left:10px;border-left:4px solid #1890ff;margin-bottom:16px;color:#1a1a1a}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:9px 12px;text-align:left;border-bottom:1px solid #f0f0f0;font-size:12px;vertical-align:top}}
th{{background:#f7f8fa;font-weight:600;color:#555;border-bottom:2px solid #e8e8e8}}
tr:hover td{{background:#fafbff}}
.badge{{display:inline-block;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:600}}
.bg-success{{background:#f6ffed;color:#389e0d;border:1px solid #b7eb8f}}
.bg-danger{{background:#fff1f0;color:#cf1322;border:1px solid #ffa39e}}
.bg-warning{{background:#fffbe6;color:#ad6800;border:1px solid #ffe58f}}
.bg-secondary{{background:#f5f5f5;color:#666;border:1px solid #d9d9d9}}
.footer{{text-align:center;color:#bbb;font-size:11px;padding:16px 0 4px}}
@media print{{body{{background:#fff;padding:0}}@page{{margin:1.5cm}}}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>{task_name}</h1>
    <div style="font-size:13px;opacity:.75;margin-top:8px">
      通过率：<b style="color:{'#73d13d' if pass_rate >= 80 else '#ff7875'};font-size:18px">{pass_rate}%</b>
      &nbsp;&nbsp;总用例：{summary['total']}
    </div>
    <div class="meta">生成时间：{report['generated_at']}（北京时间）</div>
  </div>
  <div class="cards">
    <div class="card"><div class="num" style="color:#1890ff">{summary['total']}</div><div class="lbl">总用例数</div></div>
    <div class="card"><div class="num" style="color:#52c41a">{summary['passed']}</div><div class="lbl">通过</div></div>
    <div class="card"><div class="num" style="color:#ff4d4f">{summary['failed']}</div><div class="lbl">失败</div></div>
    <div class="card"><div class="num" style="color:#faad14">{summary['skipped']}</div><div class="lbl">跳过</div></div>
    <div class="card"><div class="num" style="color:{pr_color}">{pass_rate}%</div><div class="lbl">通过率</div></div>
    <div class="card"><div class="num">{summary['total_duration']}s</div><div class="lbl">总耗时</div></div>
  </div>
  <div class="section">
    <h2>用例执行详情</h2>
    <table>
      <thead><tr><th style="width:40px">#</th><th>用例名称</th><th style="width:64px">状态</th><th style="width:72px">耗时</th><th>错误信息</th><th style="width:56px">截图</th></tr></thead>
      <tbody>{details_rows if details_rows else '<tr><td colspan="6" style="text-align:center;color:#aaa;padding:24px">暂无执行数据</td></tr>'}</tbody>
    </table>
  </div>
  <div class="footer">本报告由 AI 测试平台自动生成 · {report['generated_at']}（北京时间）</div>
</div>
</body>
</html>"""


report_generator = ReportGenerator()
