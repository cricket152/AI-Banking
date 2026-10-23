"""终端调试轨迹；不打印凭据、原始 HTTP 响应或不可见推理。"""

import json
import logging
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar

LOGGER = logging.getLogger("ai_banking.trace")
TURN = ContextVar("banking_turn", default="service")
CONVERSATION = ContextVar("banking_conversation", default=None)
LABELS = {
    "user": "用户输入",
    "model_request": "模型请求",
    "reasoning": "模型可见思考/摘要",
    "model_response": "模型响应",
    "tool_call": "工具调用",
    "tool_result": "工具结果",
    "assistant": "助手回复",
    "error": "运行错误",
    "cached": "重复请求/缓存回执",
    "bank_event": "银行事件",
}
SENSITIVE = re.compile(
    r"password|secret|api.?key|(?:^|_)token(?:$|_)|cookie|authorization|challenge|encrypted_content",
    re.I,
)


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE.search(str(key)) else redact(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, secrets) for item in value[:30]]
    if not isinstance(value, str):
        return value
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"\b(?:sk-[\w-]{8,}|gh[pousr]_[\w]{16,}|lsv2_[\w-]{8,})", "[REDACTED]", value)
    value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", value)
    value = re.sub(
        r"(?i)((?:password|api[_ -]?key|token|cookie|authorization|密码|密钥)"
        r"[\"']?\s*(?:是|为|[:=：])\s*)[^\r\n]+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"\b\d{11,19}\b", "[NUMBER_REDACTED]", value)
    value = "".join(
        char
        if char >= " " and char not in "\u202a\u202b\u202d\u202e\u2066\u2067\u2068\u2069"
        else f"\\u{ord(char):04x}"
        for char in value
    )
    return value[:4000] + ("…[截断]" if len(value) > 4000 else "")


def configure_terminal():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if not LOGGER.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)


@contextmanager
def trace_scope(turn_id, conversation_id=None):
    token = TURN.set(turn_id)
    conversation_token = CONVERSATION.set(conversation_id)
    try:
        yield
    finally:
        TURN.reset(token)
        CONVERSATION.reset(conversation_token)


def emit(settings, event, **data):
    if not settings.trace_enabled:
        return
    LOGGER.setLevel(logging.INFO)
    if not settings.trace_content:
        for key in ("text", "arguments", "result"):
            if key in data:
                data[key] = "[内容输出已关闭]"
    safe = redact(data, (settings.model_key, settings.langsmith_key))
    LOGGER.info(
        "[%s] [%s] %s",
        TURN.get(),
        LABELS.get(event, event),
        json.dumps(safe, ensure_ascii=False, default=str),
    )
