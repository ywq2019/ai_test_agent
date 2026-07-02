"""
test-case-pro-max 技能脚本
供技能管理页面"执行"按钮调用，展示技能能力说明
"""
import json
import sys
from pathlib import Path


def main():
    skill_dir = Path(__file__).parent.parent
    prompt_yaml = skill_dir / "prompt.yaml"

    info = {
        "skill": "test-case-pro-max",
        "version": "2.0.0",
        "status": "active",
        "prompt_config": str(prompt_yaml),
        "prompt_config_exists": prompt_yaml.exists(),
        "description": (
            "专业级AI测试用例生成技能。"
            "本技能通过 prompt.yaml 提供增强的系统提示词和用户提示词模板，"
            "ai_case_generator.py 在生成用例时会自动加载并使用本技能的配置。"
        ),
        "coverage_dimensions": [
            "功能测试（P0/P1）- 核心业务流程验证",
            "边界值测试（P2）- 数值/字符串/集合边界",
            "异常场景测试（P2）- 网络/并发/权限异常",
            "安全测试（P2）- SQL注入/XSS/越权/CSRF",
            "性能测试（P3）- 响应时间/并发/大数据量",
            "兼容性测试（P3）- 多浏览器/移动端/分辨率",
        ],
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
