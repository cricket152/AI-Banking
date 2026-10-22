import asyncio
import json
from dataclasses import replace

import httpx

from ai_banking.agent import Agent
from ai_banking.config import Settings
from ai_banking.tracing import emit, redact, trace_scope


def test_trace_separates_events_and_redacts_secrets(caplog):
    settings = Settings(local_http=True, model_key="test-key-known-to-redactor")
    with trace_scope("request-123"):
        emit(settings, "user", text="MODEL_API_KEY=test-key-known-to-redactor")
        emit(settings, "tool_call", name="list_accounts", arguments={})
        emit(settings, "tool_result", result={"password": "private-value", "amount_minor": 123})
    text = caplog.text
    assert "用户输入" in text and "工具调用" in text and "工具结果" in text
    assert "request-123" in text and "123" in text
    assert "test-key-known-to-redactor" not in text and "private-value" not in text
    assert redact("\x1b[31m\n伪造日志") == "\\u001b[31m\\u000a伪造日志"
    assert redact({"csrf_token": "private"}) == {"csrf_token": "[REDACTED]"}


def test_metadata_only_and_disabled_trace(caplog):
    settings = Settings(local_http=True, trace_content=False)
    emit(settings, "user", text="不应输出的内容")
    assert "不应输出的内容" not in caplog.text
    caplog.clear()
    emit(replace(settings, trace_enabled=False), "user", text="anything")
    assert not caplog.text


def test_visible_reasoning_and_chat_roundtrip_are_preserved(caplog):
    settings = Settings(local_http=True, model_api="chat")
    agent = Agent(None, None, settings)

    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "公开的测试思考摘要",
                            "tool_calls": [
                                {
                                    "id": "call1",
                                    "type": "function",
                                    "function": {"name": "list_accounts", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await agent.completion(client, [{"role": "user", "content": "余额"}])

    _, calls, raw = asyncio.run(run())
    assert calls[0][1] == "list_accounts"
    assert raw[0]["reasoning_content"] == "公开的测试思考摘要"
    assert "模型可见思考/摘要" in caplog.text
    assert "公开的测试思考摘要" in caplog.text
    assert "Authorization" not in caplog.text
    assert json.dumps(raw)


def test_encrypted_reasoning_is_never_logged_or_decrypted(caplog):
    settings = Settings(local_http=True, model_api="responses")
    agent = Agent(None, None, settings)

    def handler(request):
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "reasoning",
                        "encrypted_content": "hidden-encrypted-test-content",
                        "summary": [{"type": "summary_text", "text": "公开测试摘要"}],
                    },
                    {"type": "message", "content": [{"type": "output_text", "text": "你好"}]},
                ],
                "usage": {"input_tokens": 123, "output_tokens": 45},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await agent.completion(client, [{"role": "user", "content": "你好"}])

    asyncio.run(run())
    assert "公开测试摘要" in caplog.text and "hidden-encrypted-test-content" not in caplog.text
    assert '"input_tokens": 123' in caplog.text
