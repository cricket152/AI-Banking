import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from test_application import env as shared_env
from test_application import login, post, question

from ai_banking.agent import TOOLS, Agent
from ai_banking.tracing import trace_scope

__all__ = ["shared_env"]


@pytest.fixture
def intent_env(request):
    app, client, now, settings = request.getfixturevalue("shared_env")
    login(client)
    context = app.state.auth.authenticate(client.cookies.get("ai_banking_session"))
    conversation = post(client, "/api/conversations", {}).json()["id"]
    accounts = app.state.store.accounts(context.user_id)
    source = next(a for a in accounts if a["kind"] == "checking")["id"]
    target = next(a for a in accounts if a["kind"] == "savings")["id"]
    payee = next(p for p in app.state.bank.payees(context) if p["account_id"] == target)["id"]
    return SimpleNamespace(
        app=app,
        client=client,
        now=now,
        settings=settings,
        context=context,
        conversation=conversation,
        source=source,
        target=target,
        arguments={
            "source_id": source,
            "payee_id": payee,
            "amount_minor": 10000,
            "currency": "CNY",
        },
    )


def call(env, name="prepare_transfer", arguments=None, conversation=None):
    with trace_scope(uuid4().hex, conversation or env.conversation):
        return env.app.state.agent.tool(
            env.context, name, env.arguments if arguments is None else arguments
        )


def balances(env):
    return env.app.state.store.accounts(env.context.user_id)


def test_tools_preserve_query_prefix_and_expose_no_approval_or_execution():
    assert [tool["name"] for tool in TOOLS] == [
        "list_accounts",
        "get_transactions",
        "list_payees",
        "list_subscriptions",
        "get_billing_summary",
        "prepare_transfer",
        "prepare_subscription_cancellation",
        "get_operation",
    ]


def test_prepare_only_and_independent_approval_are_required(intent_env):
    env = intent_env
    before = balances(env)
    op = call(env)["operation"]
    assert op["state"] == "awaiting_confirmation"
    assert op["mode"] == "HUMAN_APPROVAL" and op["grant_id"] is None
    assert balances(env) == before
    assert post(env.client, f"/api/bank/operations/{op['id']}/execute", {}).status_code == 409
    with env.app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM bank_grants").fetchone()[0] == 0
    checkpoint = env.client.get(f"/api/conversations/{env.conversation}").json()["operation_task"]
    assert checkpoint["id"] == op["task_id"]
    assert checkpoint["steps"][0]["id"] == op["id"]
    assert "challenge" not in json.dumps(call(env, "get_operation", {"operation_id": op["id"]}))


def test_repeat_round_restart_and_concurrent_calls_reuse_one_intent(intent_env):
    env = intent_env
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: call(env)["operation"], range(4)))
    op = results[0]
    assert {item["id"] for item in results} == {op["id"]}
    assert call(env)["operation"]["id"] == op["id"]
    restarted = Agent(env.app.state.store, env.app.state.auth, env.settings)
    with trace_scope(uuid4().hex, env.conversation):
        assert (
            restarted.tool(env.context, "prepare_transfer", env.arguments)["operation"]["id"]
            == op["id"]
        )
    with env.app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_tasks").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM bank_operations").fetchone()[0] == 1


def test_changed_parameters_or_kind_cannot_create_another_step(intent_env):
    env = intent_env
    op = call(env)["operation"]
    assert call(env, arguments={**env.arguments, "amount_minor": 20000}) == {
        "error": "STEP_PARAMETERS_CONFLICT",
        "operation_id": op["id"],
    }
    subscription = env.client.get("/api/bank/subscriptions").json()["subscriptions"][0]
    assert call(
        env,
        "prepare_subscription_cancellation",
        {
            "source_id": subscription["account_id"],
            "subscription_id": subscription["id"],
            "currency": "CNY",
        },
    ) == {"error": "STEP_PARAMETERS_CONFLICT", "operation_id": op["id"]}
    assert call(env)["operation"]["id"] == op["id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"task_id": "a" * 32},
        {"step_key": "another_step"},
        {"mode": "PREAUTHORIZED"},
        {"grant_id": "a" * 32},
        {"confirmed": True},
        {"user_id": "a" * 32},
        {"amount_minor": 0},
        {"amount_minor": True},
        {"amount_minor": 1.5},
        {"currency": "USD"},
        {"source_id": "invalid"},
    ],
)
def test_model_cannot_override_binding_authorization_or_types(intent_env, changes):
    env = intent_env
    assert call(env, arguments={**env.arguments, **changes}) == {"error": "TOOL_ARGUMENTS_REJECTED"}
    with env.app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_tasks").fetchone()[0] == 0


@pytest.mark.parametrize(
    "name", ["execute_transfer", "execute", "approve", "create_grant", "reconcile"]
)
def test_execution_and_authorization_tools_are_unavailable(intent_env, name):
    assert call(intent_env, name, {}) == {"error": "TOOL_ARGUMENTS_REJECTED"}


def test_missing_or_other_users_conversation_cannot_bind_a_task(intent_env):
    env = intent_env
    assert env.app.state.agent.tool(env.context, "prepare_transfer", env.arguments) == {
        "error": "TOOL_CONTEXT_REQUIRED"
    }
    post(env.client, "/api/auth/logout", {})
    login(env.client, "bob")
    other_conversation = post(env.client, "/api/conversations", {}).json()["id"]
    env.context = env.app.state.auth.authenticate(env.client.cookies.get("ai_banking_session"))
    assert call(env) == {"error": "RESOURCE_NOT_FOUND"}
    assert call(env, conversation=other_conversation) == {"error": "RESOURCE_NOT_FOUND"}
    with env.app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_operations").fetchone()[0] == 0


def test_operation_query_remains_owner_isolated(intent_env):
    env = intent_env
    op = call(env)["operation"]
    post(env.client, "/api/auth/logout", {})
    login(env.client, "bob")
    env.context = env.app.state.auth.authenticate(env.client.cookies.get("ai_banking_session"))
    assert call(env, "get_operation", {"operation_id": op["id"]}) == {"error": "RESOURCE_NOT_FOUND"}
    assert env.client.get(f"/api/conversations/{env.conversation}").status_code == 404


def test_approval_result_is_queried_and_not_reexecuted_by_agent(intent_env):
    env = intent_env
    op = call(env)["operation"]
    approval = post(env.client, f"/api/bank/operations/{op['id']}/challenge", {}).json()
    result = post(
        env.client,
        f"/api/bank/operations/{op['id']}/decision",
        {
            "decision": "approve",
            "challenge": approval["challenge"],
            "parameters_digest": op["parameters_digest"],
        },
    )
    assert result.status_code == 200 and result.json()["state"] == "succeeded"
    after = balances(env)
    assert call(env)["operation"]["id"] == op["id"]
    assert (
        call(env, "get_operation", {"operation_id": op["id"]})["operation"]["state"] == "succeeded"
    )
    assert balances(env) == after
    assert next(a for a in after if a["id"] == env.source)["balance_minor"] == 1276450
    with env.app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 2


def test_cancellation_is_only_prepared_and_expired_operation_is_not_recreated(intent_env):
    env = intent_env
    subscription = env.client.get("/api/bank/subscriptions").json()["subscriptions"][0]
    arguments = {
        "source_id": subscription["account_id"],
        "subscription_id": subscription["id"],
        "currency": "CNY",
    }
    before = balances(env)
    op = call(env, "prepare_subscription_cancellation", arguments)["operation"]
    assert op["state"] == "awaiting_confirmation"
    assert all(
        s["status"] == "active"
        for s in env.client.get("/api/bank/subscriptions").json()["subscriptions"]
    )
    env.now[0] += 301
    repeated = call(env, "prepare_subscription_cancellation", arguments)["operation"]
    assert repeated["id"] == op["id"] and repeated["state"] == "expired"
    assert balances(env) == before


@pytest.mark.parametrize("api_style", ["responses", "chat"])
@pytest.mark.parametrize("fail_after_prepare", [False, True])
def test_model_intent_roundtrip_replay_and_failure_recovery(
    intent_env, monkeypatch, api_style, fail_after_prepare
):
    env = intent_env
    env.app.state.agent.settings = replace(
        env.settings,
        agent_mode="model",
        model="test-model",
        model_key="test-only-key",
        model_api=api_style,
    )
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        if len(captured) == 2 and fail_after_prepare:
            return httpx.Response(503)
        preparing = len(captured) % 2 == 1
        if api_style == "responses":
            output = [
                {
                    "type": "function_call",
                    "call_id": "intent_call",
                    "name": "prepare_transfer",
                    "arguments": json.dumps(env.arguments),
                }
                if preparing
                else {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "操作已准备，等待独立人工审批。"}],
                }
            ]
            return httpx.Response(200, json={"output": output})
        message = (
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "intent_call",
                        "type": "function",
                        "function": {
                            "name": "prepare_transfer",
                            "arguments": json.dumps(env.arguments),
                        },
                    }
                ],
            }
            if preparing
            else {"role": "assistant", "content": "操作已准备，等待独立人工审批。"}
        )
        return httpx.Response(200, json={"choices": [{"message": message}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "ai_banking.agent.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    before = balances(env)
    request_id = uuid4().hex
    first = question(env.client, "从日常账户向本人储蓄账户转账100元", env.conversation, request_id)
    assert first.status_code == (502 if fail_after_prepare else 200)
    checkpoint = env.client.get(f"/api/conversations/{env.conversation}").json()["operation_task"]
    op_id = checkpoint["steps"][0]["id"]
    assert checkpoint["steps"][0]["state"] == "awaiting_confirmation"
    cached = question(env.client, "从日常账户向本人储蓄账户转账100元", env.conversation, request_id)
    assert cached.status_code == (409 if fail_after_prepare else 200)
    assert len(captured) == 2
    if not fail_after_prepare:
        assert first.json()["operation_task"] == cached.json()["operation_task"] == checkpoint
    second = question(env.client, "再查一下刚才的意图，不要执行", env.conversation)
    assert second.status_code == 200
    assert second.json()["operation_task"]["steps"][0]["id"] == op_id
    assert op_id in json.dumps(captured[2])
    assert captured[0]["tools"] == captured[2]["tools"]
    assert balances(env) == before
    with env.app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_operations").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 0
