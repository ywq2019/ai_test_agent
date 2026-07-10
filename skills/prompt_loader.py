"""
Prompt 配置加载器
将 skills/prompts/*.yaml 中的 prompt 加载到内存，供各 skill 文件读取。
支持 {变量} 格式的模板渲染。
"""
import os
from pathlib import Path
from functools import lru_cache
from typing import Dict, Any

try:
    import yaml
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml


PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=None)
def _load_yaml(file_name: str) -> Dict[str, Any]:
    """加载并缓存指定 YAML 文件（启动后不会重复读盘）。"""
    path = PROMPTS_DIR / file_name
    if not path.exists():
        raise FileNotFoundError(f"Prompt 配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_prompt(file_name: str, key: str) -> Dict[str, str]:
    """
    获取指定文件中某个 key 的 prompt 配置。

    返回 {"system": "...", "user_template": "..."} 字典。
    """
    data = _load_yaml(file_name)
    if key not in data:
        raise KeyError(f"Prompt key '{key}' 不存在于 {file_name}")
    entry = data[key]
    return {
        "system": entry.get("system", "").strip(),
        "user_template": entry.get("user_template", "").strip(),
    }


def render_user(file_name: str, key: str, **kwargs) -> str:
    """
    获取并渲染 user_template，将 {变量} 替换为 kwargs 中的值。

    示例：
        render_user("api_case_gen.yaml", "fill_descriptions", paths_text="...")
    """
    entry = get_prompt(file_name, key)
    template = entry["user_template"]
    # 使用 str.format_map 支持部分缺失的 key（不报错）
    return template.format_map(_SafeDict(**kwargs))


def get_system(file_name: str, key: str) -> str:
    """直接返回 system prompt 字符串。"""
    return get_prompt(file_name, key)["system"]


def reload_all():
    """清除缓存，重新从磁盘加载所有 YAML（开发调试用）。"""
    _load_yaml.cache_clear()


class _SafeDict(dict):
    """format_map 的安全字典：缺失 key 保留原始占位符不报错。"""
    def __missing__(self, key):
        return "{" + key + "}"
