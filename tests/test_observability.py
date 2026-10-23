import asyncio
import json
import threading
from dataclasses import replace
from queue import Queue
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_application import ORIGIN, PASSWORD, login, post, question

from ai_banking.agent import Agent, AgentError
from ai_banking.app import create_app
from ai_banking.config import Settings
from ai_banking.observability import Observer, llm_inputs, llm_output
from ai_banking.tracing import trace_scope

MODEL_SECRET = "fixture-model-private-value"
TRACE_SECRET = "fixture-trace-private-value"
TRACE_ENDPOINT = "https://api.smith.langchain.com"


@pytest.fixture
def ingestion(monkeypatch):
    pytest.importorskip("langsmith")
    import requests

    received = []

    def send(session, request, **kwargs):
        assert request.url == TRACE_ENDPOINT + "/runs"
        assert request.headers["x-api-key"] == TRACE_SECRET
        received.append(json.loads(request.body))
        response = requests.Response()
        response.status_code, response._content = 201, b"{}"
        response.request = request
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    return received


def traced_settings(**changes):
    return Settings(
        local_http=True,
        model_key=MODEL_SECRET,
        langsmith_enabled=True,
        langsmith_key=TRACE_SECRET,
        **changes,
    )


def test_disabled_tracing_does_not_import_sdk_or_upload(monkeypatch):
    import builtins

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not name.startswith("langsmith"), "Disabled tracing imported SDK"
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    observer = Observer(Settings(local_http=True))
    observer.start()
    with observer.span("test", inputs={"password": "should-not-be-collected"}) as span:
        span.output({"answer": "works"})
    observer.close()
    assert observer.status()["status"] == "disabled" and observer.pending.empty()


def test_enabled_without_sdk_keeps_business_available(monkeypatch, caplog):
    import builtins

    original = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "langsmith":
            raise ImportError("fixture")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    observer = Observer(traced_settings())
    observer.start()
    with observer.span("test"):
        result = 123
    observer.close()
    assert result == 123 and observer.status()["status"] == "missing_sdk"
    assert "未安装可选 SDK" in caplog.text


@pytest.mark.parametrize(
    "values",
    [
        {"langsmith_key": ""},
        {"langsmith_endpoint": "http://example.com"},
        {"langsmith_endpoint": "https://secret@example.com"},
        {"langsmith_endpoint": "https://example.com?key=private"},
        {"langsmith_project": ""},
    ],
)
def test_configuration_rejects_missing_key_and_unsafe_endpoint(values):
    settings = Settings(local_http=True, langsmith_enabled=True, langsmith_key=TRACE_SECRET)
    with pytest.raises(ValueError):
        replace(settings, **values)
    assert TRACE_SECRET not in repr(settings)


def test_sdk_exports_parent_children_and_only_sanitized_copies(ingestion):
    observer = Observer(traced_settings())
    observer.start()
    source = {
        "messages": [{"role": "user", "content": MODEL_SECRET}],
        "password": "private-password",
        "encrypted_content": "private-encrypted",
        "client": SimpleNamespace(api_key="object-private"),
        "trace_key": TRACE_SECRET,
    }
    with observer.span("root", inputs=source, metadata={"thread_id": "conversation-1"}) as root:
        with observer.span("list_accounts", "tool", inputs={}) as child:
            child.output({"balance_minor": 12345, "csrf_token": "private-csrf"})
        root.output({"answer": TRACE_SECRET})
    observer.close()
    assert observer.status()["status"] == "connected"
    assert len(ingestion) == 2
    parent, child = ingestion
    assert child["parent_run_id"] == parent["id"]
    assert child["trace_id"] == parent["trace_id"] == parent["id"]
    assert child["extra"]["metadata"]["thread_id"] == "conversation-1"
    assert child["outputs"]["balance_minor"] == 12345
    assert source["messages"][0]["content"] == MODEL_SECRET
    assert "runtime" not in parent["extra"]
    body = json.dumps(ingestion)
    for value in (
        MODEL_SECRET,
        TRACE_SECRET,
        "private-password",
        "private-csrf",
        "private-encrypted",
        "object-private",
    ):
        assert value not in body


def test_metadata_only_preserves_usage_but_no_content(ingestion):
    observer = Observer(traced_settings(langsmith_content=False))
    observer.start()
    with observer.span("model", "llm", inputs={"messages": ["private-input"]}) as span:
        span.output({"answer": "private-output", "usage_metadata": {"input_tokens": 10}})
    observer.close()
    assert "private-input" not in json.dumps(ingestion)
    assert "private-output" not in json.dumps(ingestion)
    assert ingestion[0]["outputs"]["usage_metadata"]["input_tokens"] == 10


def test_export_error_cannot_retry_business_or_leak_error_body(ingestion, monkeypatch, caplog):
    import requests

    def fail(*args, **kwargs):
        raise RuntimeError(TRACE_SECRET + " " + MODEL_SECRET)

    monkeypatch.setattr(requests.Session, "send", fail)
    observer = Observer(traced_settings())
    observer.start()
    calls = []
    with observer.span("root") as span:
        calls.append("business-executed-once")
        span.output({"answer": "completed"})
    observer.close()
    assert calls == ["business-executed-once"]
    assert observer.status()["status"] == "upload_error"
    assert "上传失败" in caplog.text
    assert TRACE_SECRET not in caplog.text and MODEL_SECRET not in caplog.text


def test_span_failure_does_not_reexecute_or_hide_business_error(ingestion):
    observer = Observer(traced_settings())
    observer.start()
    with pytest.raises(AgentError):
        with observer.span("root"):
            raise AgentError("MODEL_TIMEOUT")
    observer.close()
    assert len(ingestion) == 1 and ingestion[0]["error"] == "MODEL_TIMEOUT"


def test_trace_queue_is_bounded_and_drops_instead_of_blocking(caplog):
    class FakeRun:
        def __init__(self, **kwargs):
            pass

        def end(self, **kwargs):
            pass

    observer = Observer(traced_settings())
    observer.run_type = FakeRun
    observer.pending = Queue(maxsize=1)
    for _ in range(2):
        with observer.span("test") as span:
            span.output({"result": "ok"})
    assert observer.pending.qsize() == 1 and observer.dropped == 1
    assert "队列已满" in caplog.text


def test_concurrent_turns_cannot_cross_parent_traces(ingestion):
    observer = Observer(traced_settings())
    observer.start()

    async def one(name):
        with observer.span(name, metadata={"thread_id": name}):
            await asyncio.sleep(0)
            with observer.span("child", "tool"):
                await asyncio.sleep(0)

    async def run():
        await asyncio.gather(one("a"), one("b"))

    asyncio.run(run())
    observer.close()
    roots = {row["id"]: row for row in ingestion if not row.get("parent_run_id")}
    assert len(roots) == 2 and len(ingestion) == 4
    for row in ingestion:
        if row.get("parent_run_id"):
            root = roots[row["parent_run_id"]]
            assert row["extra"]["metadata"]["thread_id"] == root["name"]


@pytest.mark.parametrize("api", ["chat", "responses"])
def test_agent_http_roundtrip_groups_model_tool_usage_without_changing_payload(
    ingestion, tmp_path, monkeypatch, api
):
    settings = traced_settings(
        database=tmp_path / "trace.sqlite3", agent_mode="model", model="test-model", model_api=api
    )
    app = create_app(settings)
    requests_sent = []
    original = httpx.AsyncClient

    def handle(request):
        payload = json.loads(request.content)
        requests_sent.append(payload)
        if api == "chat":
            message = (
                {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "公开摘要",
                    "tool_calls": [
                        {
                            "id": "call1",
                            "type": "function",
                            "function": {"name": "list_accounts", "arguments": "{}"},
                        }
                    ],
                }
                if len(requests_sent) == 1
                else {"role": "assistant", "content": "工具查询完成"}
            )
            body = {
                "choices": [{"message": message}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "completion_tokens_details": {"reasoning_tokens": 2},
                },
            }
        else:
            output = (
                [
                    {
                        "type": "reasoning",
                        "encrypted_content": "encrypted-private-value",
                        "summary": [{"type": "summary_text", "text": "公开摘要"}],
                    },
                    {
                        "type": "function_call",
                        "call_id": "call1",
                        "name": "list_accounts",
                        "arguments": "{}",
                    },
                ]
                if len(requests_sent) == 1
                else [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "工具查询完成"}],
                    }
                ]
            )
            body = {"output": output, "usage": {"input_tokens": 10, "output_tokens": 5}}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        "ai_banking.agent.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.auth.create_user("alice", PASSWORD)
        login(client)
        conversation = post(client, "/api/conversations", {}).json()["id"]
        request_id = uuid4().hex
        result = question(client, conversation=conversation, request_id=request_id)
        assert result.status_code == 200
        assert question(client, conversation=conversation, request_id=request_id).status_code == 200
    assert len(requests_sent) == 2 and len(ingestion) == 4
    root = next(row for row in ingestion if row["run_type"] == "chain")
    assert root["extra"]["metadata"]["thread_id"] == conversation
    assert root["extra"]["metadata"]["request_id"] == request_id
    assert {r["run_type"] for r in ingestion} == {"chain", "llm", "tool"}
    assert all(row["parent_run_id"] == root["id"] for row in ingestion if row is not root)
    for row in ingestion:
        if row["run_type"] == "llm":
            assert row["outputs"]["usage_metadata"]["input_tokens"] == 10
            assert row["outputs"]["usage_metadata"]["output_tokens"] == 5
    assert "公开摘要" in json.dumps(ingestion, ensure_ascii=False)
    for secret in (MODEL_SECRET, TRACE_SECRET, PASSWORD, "encrypted-private-value"):
        assert secret not in json.dumps(ingestion)
    messages = requests_sent[1]["messages" if api == "chat" else "input"]
    assert requests_sent[0]["tools"] == requests_sent[1]["tools"]
    if api == "responses":
        assert any(item.get("encrypted_content") == "encrypted-private-value" for item in messages)


def test_telemetry_formatter_failure_does_not_prevent_model_request(ingestion, monkeypatch):
    agent = Agent(None, None, traced_settings(model="test-model", agent_mode="model"))
    agent.observer.start()

    def fail(*args):
        raise RuntimeError("formatter error")

    monkeypatch.setattr("ai_banking.agent.llm_inputs", fail)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "output": [
                            {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}
                        ]
                    },
                )
            )
        ) as client:
            return await agent.completion(client, [{"role": "user", "content": "hello"}])

    assert asyncio.run(run())[0] == "ok"
    agent.observer.close()
    assert agent.observer.failed == 1


def test_formatter_masks_json_arguments_and_does_not_invent_usage():
    inputs = llm_inputs(
        [
            {
                "type": "function_call",
                "call_id": "1",
                "name": "unknown",
                "arguments": '{"password":"private"}',
            }
        ]
    )
    safe = Observer(traced_settings()).safe(inputs)
    assert "private" not in json.dumps(safe)
    result = llm_output("hello", [], [], None)
    assert "usage_metadata" not in result
    inputs = llm_inputs(
        [{"type": "message", "content": [{"type": "output_text", "text": "hello"}]}]
    )
    assert inputs["messages"] == [
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}
    ]


def test_terminal_scope_restores_after_nested_context():
    from ai_banking.tracing import CONVERSATION, TURN

    with trace_scope("a", "thread-a"):
        with trace_scope("b", "thread-b"):
            assert TURN.get() == "b" and CONVERSATION.get() == "thread-b"
        assert TURN.get() == "a" and CONVERSATION.get() == "thread-a"


def test_blocked_upload_does_not_block_business_and_shutdown_is_bounded(
    ingestion, monkeypatch, caplog
):
    import requests

    entered, release = threading.Event(), threading.Event()
    original = requests.Session.send

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(requests.Session, "send", blocked)
    observer = Observer(traced_settings())
    observer.start()
    try:
        with observer.span("first"):
            pass
        assert entered.wait(timeout=2)
        with observer.span("second") as span:
            span.output({"answer": "business-completed-while-upload-blocked"})
        observer.close(timeout=0.01)
        assert observer.worker.is_alive()
        assert "未上传的调试追踪可能丢失" in caplog.text
    finally:
        release.set()
        observer.close()
    assert len(ingestion) == 2


def test_connection_check_uploads_only_synthetic_trace(ingestion, monkeypatch, capsys):
    from ai_banking.observability import main

    monkeypatch.setattr("ai_banking.config.Settings.from_env", lambda: traced_settings())
    monkeypatch.setattr("ai_banking.tracing.configure_terminal", lambda: None)
    monkeypatch.setattr("sys.argv", ["observability", "check"])
    main()
    assert "上传成功" in capsys.readouterr().out
    assert len(ingestion) == 1 and ingestion[0]["name"] == "LangSmith 连接自检"
    assert ingestion[0]["extra"]["metadata"]["check"] == "connectivity"


def test_connection_check_refuses_when_disabled(monkeypatch):
    from ai_banking.observability import main

    monkeypatch.setattr("ai_banking.config.Settings.from_env", lambda: Settings(local_http=True))
    monkeypatch.setattr("ai_banking.tracing.configure_terminal", lambda: None)
    monkeypatch.setattr("sys.argv", ["observability", "check"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
