"""
技能层初始化
"""
from skills.skill_loader import skill_loader, SkillLoader, SkillDefinition
from skills.skill_registry import skill_registry, SkillRegistry
from skills.case_generator import case_generator, CaseGenerator
from skills.test_executor import test_executor, TestExecutor
from skills.report_generator import report_generator, ReportGenerator

skill_registry.register_implementation("case_generator", case_generator)
skill_registry.register_implementation("test_executor", test_executor)
skill_registry.register_implementation("report_generator", report_generator)

__all__ = [
    "skill_loader",
    "SkillLoader",
    "SkillDefinition",
    "skill_registry",
    "SkillRegistry",
    "case_generator",
    "CaseGenerator",
    "test_executor",
    "TestExecutor",
    "report_generator",
    "ReportGenerator"
]
