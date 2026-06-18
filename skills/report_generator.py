"""
测试报告生成技能
"""
import json
from datetime import datetime
from typing import Dict, List, Any
from pathlib import Path
from loguru import logger
from tools.config import settings


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

        report = {
            "task_id": task_id,
            "task_name": task_name,
            "summary": summary,
            "charts": charts,
            "details": details,
            "metadata": metadata or {},
            "generated_at": datetime.utcnow().isoformat()
        }

        report_path = self.report_dir / f"report_{task_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"Report saved to {report_path}")

        html_path = await self._generate_html_report(report, task_name)

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

    async def _generate_html_report(self, report: Dict[str, Any], task_name: str) -> Path:
        html_content = self._build_html_template(report, task_name)

        html_path = self.report_dir / f"report_{report['task_id']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
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

            screenshot_cell = ""
            if detail.get("screenshot"):
                screenshot_cell = f'<td><a href="{detail["screenshot"]}" target="_blank">查看截图</a></td>'
            else:
                screenshot_cell = "<td>-</td>"

            error_cell = detail.get("error_message", "-")
            if error_cell and len(error_cell) > 100:
                error_cell = error_cell[:100] + "..."

            details_rows += f"""
            <tr>
                <td>{detail['id']}</td>
                <td>{detail['case_name']}</td>
                <td><span class="badge bg-{status_class}">{detail['status']}</span></td>
                <td>{detail['duration']}s</td>
                <td>{error_cell}</td>
                {screenshot_cell}
            </tr>
            """

        return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>测试报告 - {task_name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: white; padding: 24px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .header h1 {{ color: #333; margin-bottom: 8px; }}
        .meta {{ color: #666; font-size: 14px; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 20px; }}
        .summary-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .summary-card h3 {{ color: #666; font-size: 14px; margin-bottom: 8px; }}
        .summary-card .value {{ font-size: 32px; font-weight: bold; color: #333; }}
        .summary-card .value.success {{ color: #52c41a; }}
        .summary-card .value.danger {{ color: #ff4d4f; }}
        .summary-card .value.warning {{ color: #faad14; }}
        .chart-section {{ background: white; padding: 24px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .chart-section h2 {{ margin-bottom: 16px; color: #333; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #fafafa; font-weight: 600; color: #333; }}
        .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 12px; }}
        .bg-success {{ background: #d9f7be; color: #52c41a; }}
        .bg-danger {{ background: #fff1f0; color: #ff4d4f; }}
        .bg-warning {{ background: #fffbe6; color: #faad14; }}
        .bg-secondary {{ background: #f5f5f5; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{task_name}</h1>
            <p class="meta">生成时间: {report['generated_at']}</p>
        </div>

        <div class="summary-grid">
            <div class="summary-card">
                <h3>总用例数</h3>
                <div class="value">{summary['total']}</div>
            </div>
            <div class="summary-card">
                <h3>通过率</h3>
                <div class="value success">{summary['pass_rate']}%</div>
            </div>
            <div class="summary-card">
                <h3>通过</h3>
                <div class="value success">{summary['passed']}</div>
            </div>
            <div class="summary-card">
                <h3>失败</h3>
                <div class="value danger">{summary['failed']}</div>
            </div>
            <div class="summary-card">
                <h3>跳过</h3>
                <div class="value warning">{summary['skipped']}</div>
            </div>
            <div class="summary-card">
                <h3>总耗时</h3>
                <div class="value">{summary['total_duration']}s</div>
            </div>
        </div>

        <div class="chart-section">
            <h2>用例详情</h2>
            <table>
                <thead>
                    <tr>
                        <th>序号</th>
                        <th>用例名称</th>
                        <th>状态</th>
                        <th>耗时</th>
                        <th>错误信息</th>
                        <th>截图</th>
                    </tr>
                </thead>
                <tbody>
                    {details_rows}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
        """


report_generator = ReportGenerator()
