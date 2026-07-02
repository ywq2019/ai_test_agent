"""
接口参数动态解析器 — Tier 1 内置函数占位符 + Tier 2 自定义脚本函数

支持语法：{{function_name(arg1, arg2)}}
嵌套示例：prefix_{{uuid()}}  /  {{md5({{timestamp()}}+secret)}}
自定义脚本：{{my_func(arg)}}  →  在 custom_scripts 列表中查找并执行
全局变量：{{gvar:token}}    →  读取跨项目全局变量池（数据库）
局部变量：{{var:token}}     →  读取当前执行链的 var_store
"""
import json
import re
import hashlib
import string
import random
import time
import uuid as _uuid_module
import base64 as _b64_module
import os
from typing import Any, Dict, List, Optional
from loguru import logger

# 匹配 {{fn_name(args)}}，args 内不含 {}（先解析最内层）
_PLACEHOLDER = re.compile(r'\{\{(\w+)\(([^{}]*)\)\}\}')
# 匹配 {{gvar:name}} 全局变量
_GVAR = re.compile(r'\{\{gvar:(\w+)\}\}')


# ── 全局变量池同步读写（供执行器调用）────────────────────────────────────────

def get_global_var(name: str) -> Optional[str]:
    """同步读取全局变量（从内存缓存，执行器启动时加载）。"""
    return _gvar_cache.get(name)


def set_global_var(name: str, value: str, source_project: str = "") -> None:
    """同步写入全局变量缓存（执行器用）；异步持久化由执行器调用 flush_global_vars。"""
    _gvar_cache[name] = str(value)
    _gvar_dirty.add(name)
    logger.info(f"[gvar] 写入全局变量: {name} = {str(value)[:80]}  来源: {source_project}")


# 内存缓存，服务启动时由 load_global_vars_sync() 初始化
_gvar_cache: Dict[str, str] = {}
_gvar_dirty: set = set()   # 记录哪些变量需要持久化


async def load_global_vars() -> None:
    """服务启动时从数据库加载全局变量到内存缓存。"""
    try:
        from tools.database import async_session_maker, GlobalVariable
        from sqlalchemy import select
        async with async_session_maker() as db:
            result = await db.execute(select(GlobalVariable))
            for row in result.scalars().all():
                _gvar_cache[row.name] = row.value or ""
        logger.info(f"[gvar] 已加载 {len(_gvar_cache)} 个全局变量")
    except Exception as e:
        logger.warning(f"[gvar] 加载全局变量失败: {e}")


async def flush_global_vars(source_project: str = "") -> None:
    """将内存中脏标记的全局变量持久化到数据库。"""
    if not _gvar_dirty:
        return
    try:
        from tools.database import async_session_maker, GlobalVariable
        from sqlalchemy import select
        from datetime import datetime
        dirty = list(_gvar_dirty)
        async with async_session_maker() as db:
            for name in dirty:
                value = _gvar_cache.get(name, "")
                result = await db.execute(select(GlobalVariable).where(GlobalVariable.name == name))
                row = result.scalar_one_or_none()
                if row:
                    row.value = value
                    row.source_project = source_project
                    row.updated_at = datetime.utcnow()
                else:
                    db.add(GlobalVariable(
                        name=name, value=value,
                        source_project=source_project,
                        updated_at=datetime.utcnow()
                    ))
            await db.commit()
        _gvar_dirty.difference_update(dirty)
        logger.info(f"[gvar] 已持久化 {len(dirty)} 个全局变量")
    except Exception as e:
        logger.warning(f"[gvar] 持久化全局变量失败: {e}")


def _apply_fn(fn_name: str, raw_args: str) -> str:
    """执行一个内置函数，返回字符串结果。"""
    args = [a.strip() for a in raw_args.split(',') if a.strip()] if raw_args.strip() else []

    try:
        if fn_name == 'timestamp':
            return str(int(time.time()))

        elif fn_name == 'timestamp_ms':
            return str(int(time.time() * 1000))

        elif fn_name == 'uuid':
            return str(_uuid_module.uuid4())

        elif fn_name == 'random_int':
            lo = int(args[0]) if len(args) > 0 else 0
            hi = int(args[1]) if len(args) > 1 else 9999
            return str(random.randint(lo, hi))

        elif fn_name == 'random_str':
            n = int(args[0]) if args else 8
            chars = string.ascii_letters + string.digits
            return ''.join(random.choices(chars, k=n))

        elif fn_name == 'random_phone':
            prefixes = ['138', '139', '150', '151', '152', '158',
                        '159', '186', '187', '188', '189', '176', '177', '178']
            suffix = ''.join(str(random.randint(0, 9)) for _ in range(8))
            return random.choice(prefixes) + suffix

        elif fn_name == 'env':
            key = args[0] if args else ''
            return os.environ.get(key, '')

        elif fn_name == 'base64':
            val = args[0] if args else ''
            return _b64_module.b64encode(val.encode('utf-8')).decode('utf-8')

        elif fn_name == 'md5':
            val = args[0] if args else ''
            return hashlib.md5(val.encode('utf-8')).hexdigest()

        elif fn_name == 'sha256':
            val = args[0] if args else ''
            return hashlib.sha256(val.encode('utf-8')).hexdigest()

        elif fn_name == 'upper':
            return (args[0] if args else '').upper()

        elif fn_name == 'lower':
            return (args[0] if args else '').lower()

        else:
            logger.warning(f"param_resolver: unknown function '{fn_name}'")
            return f'{{{{{fn_name}({raw_args})}}}}'   # 未知函数原样保留

    except Exception as e:
        logger.warning(f"param_resolver: error in {fn_name}({raw_args}): {e}")
        return f'{{{{{fn_name}({raw_args})}}}}'


def _exec_custom_fn(fn_name: str, raw_args: str, custom_scripts: List[Dict]) -> Optional[str]:
    """执行自定义脚本函数，返回字符串结果；找不到或出错返回 None。"""
    script = next((s for s in custom_scripts if s.get('name') == fn_name), None)
    if not script:
        return None

    args = [a.strip() for a in raw_args.split(',') if a.strip()] if raw_args.strip() else []
    code = script.get('code', '')

    # 允许的模块白名单
    safe_globals: Dict[str, Any] = {
        '__builtins__': {
            'str': str, 'int': int, 'float': float, 'bool': bool, 'bytes': bytes,
            'len': len, 'range': range, 'list': list, 'dict': dict, 'tuple': tuple,
            'set': set, 'abs': abs, 'round': round, 'min': min, 'max': max,
            'sum': sum, 'sorted': sorted, 'reversed': reversed, 'enumerate': enumerate,
            'zip': zip, 'map': map, 'filter': filter, 'any': any, 'all': all,
            'isinstance': isinstance, 'type': type, 'repr': repr, 'print': print,
            'True': True, 'False': False, 'None': None,
            '__import__': __import__,   # 允许 import
        },
        'args': args,
        'time': time,
        'random': random,
        'hashlib': hashlib,
        'base64': _b64_module,
        'json': json,
        'uuid': _uuid_module,
        'os': os,
        're': re,
    }
    # 补充常用标准库，避免脚本里 import 时找不到
    import urllib.parse as _urllib_parse
    import urllib as _urllib
    safe_globals['urllib'] = _urllib
    safe_globals['urllib.parse'] = _urllib_parse
    try:
        import requests as _req
        safe_globals['requests'] = _req
    except ImportError:
        pass

    local_vars: Dict = {}
    try:
        exec(compile(code, f'<custom:{fn_name}>', 'exec'), safe_globals, local_vars)
        # 优先：代码中定义了同名函数
        if fn_name in local_vars and callable(local_vars[fn_name]):
            result = local_vars[fn_name](*args)
            return str(result)
        # 备选：代码直接设置了 result 变量
        if 'result' in local_vars:
            return str(local_vars['result'])
        logger.warning(f"custom script '{fn_name}': neither function nor result defined")
        return None
    except Exception as e:
        logger.warning(f"custom script '{fn_name}' exec error: {e}")
        return None


def resolve_str(val: str, var_store: Optional[Dict] = None, custom_scripts: Optional[List] = None) -> Any:
    """
    解析单个字符串中的所有占位符：
      {{fn()}}       内置/自定义函数
      {{var:name}}   当前执行链局部变量
      {{gvar:name}}  跨项目全局变量池
    支持嵌套（最多 8 层）
    """
    if not isinstance(val, str) or '{{' not in val:
        return val

    original = val
    result = val

    def _replace(m: re.Match) -> str:
        fn = m.group(1)
        raw = m.group(2)
        original_placeholder = '{{' + fn + '(' + raw + ')}}'
        # 先试内置
        r = _apply_fn(fn, raw)
        if r != original_placeholder:   # 内置处理了（未返回原样）
            return r
        # 再试自定义脚本
        if custom_scripts:
            cr = _exec_custom_fn(fn, raw, custom_scripts)
            if cr is not None:
                return cr
        return r   # 原样保留

    for _ in range(8):
        prev = result
        # 替换 {{var:name}}（局部变量）
        if var_store:
            result = re.sub(
                r'\{\{var:(\w+)\}\}',
                lambda m: str(var_store.get(m.group(1), m.group(0))),
                result,
            )
        # 替换 {{gvar:name}}（全局变量池）
        result = _GVAR.sub(
            lambda m: str(_gvar_cache.get(m.group(1), m.group(0))),
            result,
        )
        # 替换函数占位符
        result = _PLACEHOLDER.sub(_replace, result)
        if result == prev:
            break

    # 整体是占位符时做类型推断
    if original.strip().startswith('{{') and original.strip().endswith('}}') \
            and '{{' not in result:
        try:
            return json.loads(result)
        except Exception:
            pass

    return result


def resolve_obj(obj: Any, var_store: Optional[Dict] = None, custom_scripts: Optional[List] = None) -> Any:
    """
    递归遍历 dict / list，对所有字符串值执行 resolve_str。
    """
    if isinstance(obj, dict):
        return {k: resolve_obj(v, var_store, custom_scripts) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_obj(item, var_store, custom_scripts) for item in obj]
    if isinstance(obj, str):
        return resolve_str(obj, var_store, custom_scripts)
    return obj


# ── 内置函数目录（提供给前端展示） ──────────────────────────────────────────

BUILTIN_FUNCTIONS = [
    {"value": "{{timestamp()}}",        "desc": "当前 Unix 时间戳（秒）",      "category": "时间"},
    {"value": "{{timestamp_ms()}}",     "desc": "当前 Unix 时间戳（毫秒）",    "category": "时间"},
    {"value": "{{uuid()}}",             "desc": "随机 UUID v4",                "category": "随机"},
    {"value": "{{random_int(1,9999)}}", "desc": "随机整数，可自定义范围",       "category": "随机"},
    {"value": "{{random_str(8)}}",      "desc": "随机字母数字字符串，可指定长度","category": "随机"},
    {"value": "{{random_phone()}}",     "desc": "随机中国大陆手机号",           "category": "随机"},
    {"value": "{{env(KEY)}}",           "desc": "读取系统环境变量",             "category": "环境"},
    {"value": "{{base64(str)}}",        "desc": "Base64 编码",                 "category": "加密"},
    {"value": "{{md5(str)}}",           "desc": "MD5 哈希（小写十六进制）",    "category": "加密"},
    {"value": "{{sha256(str)}}",        "desc": "SHA-256 哈希",                "category": "加密"},
    {"value": "{{upper(str)}}",         "desc": "转大写",                      "category": "字符串"},
    {"value": "{{lower(str)}}",         "desc": "转小写",                      "category": "字符串"},
]
