"""
告警推送模块
支持：钉钉（dingtalk）/ 企业微信（wecom）/ 飞书（feishu）Webhook
特性：
  - 防抖：同一条消息 ALERT_RATE_LIMIT_SECONDS 内只推送一次
  - 异步友好：fire_alert() 是普通函数，内部用 httpx 同步发送（被 loguru sink 调用，无 event-loop 约束）
  - 失败静默：推送失败只打 WARNING 日志，不影响主流程
"""
import hashlib
import time
import threading
from typing import Optional

import httpx
from loguru import logger

from tools.config import settings

# ── 防抖缓存（key=消息摘要, value=上次推送时间戳） ─────────────────────────────
_CACHE: dict[str, float] = {}
_CACHE_LOCK = threading.Lock()

# 推送超时（秒）
_SEND_TIMEOUT = 8


def _dedup_key(text: str) -> str:
    """用消息前128字符的 md5 做去重 key，避免完全相同的错误刷屏。"""
    return hashlib.md5(text[:128].encode("utf-8", errors="replace")).hexdigest()


def _is_throttled(key: str, rate_limit: int) -> bool:
    """返回 True 表示该消息在限速窗口内已发过，本次跳过。"""
    now = time.time()
    with _CACHE_LOCK:
        last = _CACHE.get(key, 0)
        if now - last < rate_limit:
            return True
        _CACHE[key] = now
        # 顺手清理超期缓存，防止无限增长
        expired = [k for k, v in _CACHE.items() if now - v > rate_limit * 10]
        for k in expired:
            _CACHE.pop(k, None)
    return False


def _send_dingtalk(webhook: str, title: str, text: str) -> None:
    """钉钉自定义机器人 - markdown 消息。"""
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"### {title}\n\n{text}"
        }
    }
    resp = httpx.post(webhook, json=payload, timeout=_SEND_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"钉钉返回错误: {data}")


def _send_wecom(webhook: str, title: str, text: str) -> None:
    """企业微信群机器人 - markdown 消息。"""
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": f"**{title}**\n\n{text}"
        }
    }
    resp = httpx.post(webhook, json=payload, timeout=_SEND_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"企微返回错误: {data}")


def _send_feishu(webhook: str, title: str, text: str) -> None:
    """飞书自定义机器人 - card 消息。"""
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "red"
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": text}}
            ]
        }
    }
    resp = httpx.post(webhook, json=payload, timeout=_SEND_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"飞书返回错误: {data}")


# ── 公共入口 ─────────────────────────────────────────────────────────────────

def fire_alert(
    message: str,
    title: Optional[str] = None,
    webhook: Optional[str] = None,
    webhook_type: Optional[str] = None,
    rate_limit: Optional[int] = None,
    fingerprint: Optional[str] = None,
) -> None:
    """
    发送告警。参数全部有默认值，可直接调用 fire_alert(message)。

    :param message:       告警正文（Markdown）
    :param title:         标题，默认 "⚠️ AI测试平台 - 服务异常"
    :param webhook:       Webhook URL，默认取 settings.ALERT_WEBHOOK_URL
    :param webhook_type:  "dingtalk" / "wecom" / "feishu"，默认 settings.ALERT_WEBHOOK_TYPE
    :param rate_limit:    秒数，默认 settings.ALERT_RATE_LIMIT_SECONDS
    :param fingerprint:   防抖 key 的原始文本；传入时用它代替 message 做去重，
                          避免行号等元信息不同导致相同错误无法被合并限速。
    """
    url = webhook or settings.ALERT_WEBHOOK_URL
    if not url:
        return  # 未配置告警，静默跳过

    wtype = (webhook_type or settings.ALERT_WEBHOOK_TYPE or "wecom").lower()
    limit = rate_limit if rate_limit is not None else settings.ALERT_RATE_LIMIT_SECONDS
    ttl = title or "⚠️ AI测试平台 - 服务异常"

    # 防抖 key：优先用原始错误文本（fingerprint），其次降级到 message
    key = _dedup_key(fingerprint if fingerprint is not None else message)
    if _is_throttled(key, limit):
        return  # 防抖：限速窗口内已推送过，跳过

    try:
        if wtype == "dingtalk":
            _send_dingtalk(url, ttl, message)
        elif wtype == "feishu":
            _send_feishu(url, ttl, message)
        else:  # 默认企业微信
            _send_wecom(url, ttl, message)
    except Exception as e:
        # 告警失败只打 WARNING，不能递归触发告警
        logger.warning(f"[alerter] 推送告警失败 ({wtype}): {e}")
