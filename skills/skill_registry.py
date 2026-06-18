"""
技能注册表 - 将技能文档映射到实际实现
"""
import subprocess
import asyncio
from typing import Dict, Callable, Any, Optional, List
from pathlib import Path
from loguru import logger
from skills.skill_loader import skill_loader, SkillLoader, SkillDefinition


class SkillRegistry:
    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._skill_implementations: Dict[str, Any] = {}
        self._external_skills: Dict[str, Dict[str, Any]] = {}

    def register_handler(self, skill_name: str, handler: Callable):
        self._handlers[skill_name] = handler
        logger.info(f"Registered handler for skill: {skill_name}")

    def register_implementation(self, skill_name: str, impl: Any):
        self._skill_implementations[skill_name] = impl

    def register_external_skill(self, skill_name: str, skill_dir: str, config: Dict[str, Any] = None):
        self._external_skills[skill_name] = {
            "skill_dir": skill_dir,
            "config": config or {},
            "type": "external"
        }
        logger.info(f"Registered external skill: {skill_name} at {skill_dir}")

    def get_handler(self, skill_name: str) -> Optional[Callable]:
        return self._handlers.get(skill_name)

    def get_implementation(self, skill_name: str) -> Optional[Any]:
        return self._skill_implementations.get(skill_name)

    def is_external_skill(self, skill_name: str) -> bool:
        return skill_name in self._external_skills

    def get_external_skill_config(self, skill_name: str) -> Optional[Dict[str, Any]]:
        return self._external_skills.get(skill_name)

    async def execute_external_skill(
        self,
        skill_name: str,
        action: str = "test",
        params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        if skill_name not in self._external_skills:
            raise ValueError(f"External skill {skill_name} not found")

        skill_info = self._external_skills[skill_name]
        skill_dir = Path(skill_info["skill_dir"])
        params = params or {}

        if skill_name == "support_web_skill":
            return await self._execute_support_web_skill(skill_dir, action, params)

        return {"status": "error", "message": f"Unknown external skill: {skill_name}"}

    async def _execute_support_web_skill(
        self,
        skill_dir: Path,
        action: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Executing support_web_skill action: {action}")

        node_modules = skill_dir / "node_modules"
        if not node_modules.exists():
            logger.warning("node_modules not found, attempting to install dependencies...")
            proc = await asyncio.create_subprocess_shell(
                "npm install",
                cwd=str(skill_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return {
                    "status": "error",
                    "message": f"Failed to install dependencies: {stderr.decode()}"
                }

        test_suite = params.get("suite", "smoke")
        headless = params.get("headless", True)

        cmd = f'node tests/runner.js --suite {test_suite}'
        if headless:
            cmd += " --headless"

        logger.info(f"Running command: {cmd}")

        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(skill_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await proc.communicate()

        result = {
            "status": "success" if proc.returncode == 0 else "error",
            "return_code": proc.returncode,
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
            "suite": test_suite
        }

        return result

    def load_skills(self):
        skill_loader.load_all_skills()

        for skill in skill_loader.get_all_skills():
            impl_key = skill.name.replace(" ", "_").lower()
            if impl_key in self._skill_implementations:
                self.register_handler(skill.name, self._skill_implementations[impl_key])

            if skill.skill_dir and Path(skill.skill_dir).exists():
                pkg_json = Path(skill.skill_dir) / "package.json"
                if pkg_json.exists():
                    self.register_external_skill(skill.name, skill.skill_dir)

    def find_skill(self, message: str) -> tuple[Optional[SkillDefinition], Optional[Callable]]:
        skill_def, trigger = skill_loader.match_skill(message)
        if skill_def:
            handler = self.get_handler(skill_def.name)
            return skill_def, handler
        return None, None

    def list_skills(self) -> list:
        return skill_loader.get_all_skills()

    def get_skills_by_category(self, category: str) -> list:
        return [s for s in self.list_skills() if s.category == category]


skill_registry = SkillRegistry()
