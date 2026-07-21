"""
统一 LLM 调用工具模块。

自动根据 API URL 和模型名判断接口格式：
  - anthropic.com → Anthropic 原生格式（/v1/messages，顶层 system）
  - 其他 URL + claude 模型（第三方代理）→ 顶层 system（/v1/chat/completions）
  - 其他 URL + 非 claude 模型（DeepSeek/Qwen/GPT 等）→ 标准 OpenAI 格式（messages[0] 放 system role）
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx
from loguru import logger


def _detect_format(base_url: str, model: str) -> str:
    """
    返回应使用的 API 格式：
      'anthropic'   → Anthropic 官方 /v1/messages
      'claude_proxy' → 第三方 Claude 代理，顶层 system + /v1/chat/completions
      'openai'      → 标准 OpenAI 兼容，system 放 messages[0]
    """
    if "anthropic.com" in base_url:
        return "anthropic"
    if "claude" in (model or "").lower():
        return "claude_proxy"
    return "openai"


def _build_request(
    fmt: str,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 8192,
    temperature: Optional[float] = None,
) -> tuple[str, dict, dict]:
    """
    返回 (url, headers, payload)。
    """
    extra = {}
    if temperature is not None:
        extra["temperature"] = temperature

    if fmt == "anthropic":
        url = f"{base_url}/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            **extra,
        }

    elif fmt == "claude_proxy":
        # 第三方 Claude 代理：要求 system 在顶层，不放 messages 数组里
        url = f"{base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            **extra,
        }

    else:  # openai
        # 标准 OpenAI 兼容：system 放 messages[0]
        url = f"{base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            **extra,
        }

    return url, headers, payload


def _parse_response(fmt: str, data: dict) -> str:
    """
    从响应 JSON 中提取文本内容，兼容多种代理响应格式。
    """
    if fmt == "anthropic":
        content_field = data.get("content")
        if not content_field:
            raise ValueError(f"Anthropic API 返回无 content 字段，响应: {str(data)[:200]}")

        if isinstance(content_field, str):
            return content_field

        if isinstance(content_field, list):
            # 过滤出 text block（跳过 thinking block 等）
            text_blocks = [
                b for b in content_field
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            if not text_blocks:
                raise ValueError(f"Anthropic API 未返回 text block，content={content_field}")
            block = text_blocks[0]
            text = (block.get("text", "") or block.get("content", "")
                    or block.get("value", "") or block.get("message", ""))
            if not text:
                raise ValueError(f"Anthropic text block 内容为空，block={block}")
            return text

        raise ValueError(f"Anthropic content 格式未知: {type(content_field)}")

    else:  # openai / claude_proxy 响应格式相同
        # 优先尝试 OpenAI choices 格式
        if data.get("choices"):
            return data["choices"][0]["message"]["content"]
        # 部分代理返回 Anthropic 格式响应
        if data.get("content"):
            content = data["content"]
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
                if text_blocks:
                    return text_blocks[0].get("text", "")
        raise ValueError(f"无法解析 LLM 响应格式，响应: {str(data)[:300]}")


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 8192,
    temperature: Optional[float] = None,
    timeout_secs: int = 90,
    retries: int = 3,
    semaphore: Optional[asyncio.Semaphore] = None,
    sem_timeout: float = 60.0,
) -> str:
    """
    统一 LLM 调用入口。

    自动从 settings 读取 AI_API_KEY / AI_API_URL / AI_MODEL，
    根据 URL 和模型名自动选择正确的请求格式和响应解析方式。

    参数：
        system_prompt  系统提示词
        user_prompt    用户提示词
        max_tokens     最大输出 token 数
        temperature    采样温度（None 则不传，让模型用默认值）
        timeout_secs   单次请求超时（秒）
        retries        可重试错误的最大重试次数
        semaphore      外部传入的并发信号量（None 则不限并发）
        sem_timeout    等待信号量的超时时间（秒）

    返回：
        模型输出的纯文本字符串

    异常：
        RuntimeError   配置缺失、信号量超时、全部重试耗尽
        ValueError     响应格式无法解析
        httpx.HTTPStatusError  API 返回 4xx/5xx 且不可重试
    """
    from tools.config import settings

    api_key  = settings.AI_API_KEY
    base_url = (settings.AI_API_URL or "").rstrip("/")
    model    = settings.AI_MODEL or "deepseek-v4-flash"

    if not api_key or not base_url:
        raise RuntimeError("未配置 AI_API_KEY 或 AI_API_URL，请在大模型配置页填写后重试")

    fmt = _detect_format(base_url, model)
    url, headers, payload = _build_request(
        fmt, base_url, api_key, model,
        system_prompt, user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    logger.info(f"[llm_client] fmt={fmt} url={url} model={model}")

    # 可选并发保护
    if semaphore is not None:
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=sem_timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"AI 服务繁忙，等待超过 {sem_timeout}s，请稍后重试"
            )

    _RETRYABLE = {502, 503, 504}
    last_exc: Exception = RuntimeError("未知错误")

    try:
        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(verify=False, timeout=timeout_secs) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code in _RETRYABLE:
                        raise httpx.HTTPStatusError(
                            f"Server error '{resp.status_code}' (retryable)",
                            request=resp.request, response=resp,
                        )
                    if resp.status_code >= 400:
                        logger.error(
                            f"[llm_client] API 返回错误 {resp.status_code}，"
                            f"响应体: {resp.text[:500]}"
                        )
                    resp.raise_for_status()
                    data = resp.json()
                break  # 成功退出重试

            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_exc = e
                is_retryable = isinstance(e, httpx.TimeoutException) or (
                    isinstance(e, httpx.HTTPStatusError)
                    and e.response.status_code in _RETRYABLE
                )
                if is_retryable and attempt < retries:
                    wait = attempt * 5
                    logger.warning(
                        f"[llm_client] 请求失败（第{attempt}次）: {e}，{wait}s 后重试..."
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        else:
            raise last_exc
    finally:
        if semaphore is not None:
            semaphore.release()

    return _parse_response(fmt, data)
