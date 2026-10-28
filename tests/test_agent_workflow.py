import json
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from test_agent_intents import call
from test_agent_intents import intent_env as workflow_env
from test_application import PASSWORD, login, post, question
from test_application import env as shared_env

from ai_banking.agent import Agent
from ai_banking.tracing import trace_scope

__all__ = ["workflow_env", "shared_env"]


def create_grant(env, **changes):
    values = {
        "request_id": uuid4().hex,
        "source_id": env.source,
        "currency": "CNY",
        "payee_ids": [env.arguments["payee_id"]],
        "allowed_operations": ["transfer"],
        "subscription_ids": [],
        "limit_minor": 30000,
        "single_minor": 20000,
        "minimum_minor": 100000,
        "expires_at": env.now[0] + 3600,
        "password": PASSWORD,
        **changes,
    }
    response = post(env.client, "/api/bank/grants", values)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def select_policy(env, grant_id=None):
    response = post(
        env.client,
        f"/api/conversations/{env.conversation}/policy",
        {"mode": "PREAUTHORIZED" if grant_id else "HUMAN_APPROVAL", "grant_id": grant_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def decide(env, operation_id, decision="approve"):
    approval = post(env.client, f"/api/bank/operations/{operation_id}/challenge", {}).json()
    return post(
        env.client,
        f"/api/bank/operations/{operation_id}/decision",
        {
            "decision": decision,
            "challenge": approval["challenge"],
            "parameters_digest": approval["summary"]["parameters_digest"],
        },
    )


def mock_model(env, monkeypatch, script, api_style="responses"):
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
        item = script[len(captured) - 1]
        if callable(item):
            item = item()
        if isinstance(item, str):
            output = [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": item}],
                }
            ]
            message = {"role": "assistant", "content": item}
        else:
            name, arguments = item
            output = [
                {
                    "type": "function_call",
                    "call_id": f"call{len(captured)}",
                    "name": name,
                    "arguments": json.dumps(arguments),
                }
            ]
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call{len(captured)}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            }
        return httpx.Response(
            200,
            json={"output": output}
            if api_style == "responses"
            else {"choices": [{"message": message}]},
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "ai_banking.agent.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return captured


@pytest.mark.parametrize("api_style", ["responses", "chat"])
def test_manual_multi_step_confirmation_continuation_and_final_receipts(
    workflow_env, monkeypatch, api_style
):
    env = workflow_env
    subscription = env.client.get("/api/bank/subscriptions").json()["subscriptions"][0]
    cancel_args = {
        "source_id": subscription["account_id"],
        "subscription_id": subscription["id"],
        "currency": "CNY",
    }
    op_ids = []
    captured = mock_model(
        env,
        monkeypatch,
        [
            ("prepare_transfer", env.arguments),
            "转账已准备，请在确认单批准。",
            lambda: ("get_operation", {"operation_id": op_ids[0]}),
            ("prepare_subscription_cancellation", cancel_args),
            "转账已核实成功；订阅取消等待确认。",
            lambda: ("get_operation", {"operation_id": op_ids[1]}),
            "两步均已完成，转账100元，订阅已取消，不退款。",
        ],
        api_style,
    )
    first = question(env.client, "向本人储蓄账户转100元，然后取消指定订阅", env.conversation)
    assert first.status_code == 200
    op_ids.append(first.json()["operation_task"]["steps"][0]["id"])
    assert (
        post(
            env.client,
            f"/api/conversations/{env.conversation}/continue",
            {"operation_id": op_ids[0]},
        ).status_code
        == 409
    )
    assert len(captured) == 2
    assert decide(env, op_ids[0]).json()["state"] == "succeeded"
    next_step = post(
        env.client, f"/api/conversations/{env.conversation}/continue", {"operation_id": op_ids[0]}
    )
    assert next_step.status_code == 200
    steps = next_step.json()["operation_task"]["steps"]
    op_ids.append(next(s["id"] for s in steps if s["kind"] == "cancel_subscription"))
    assert len(steps) == 2
    assert (
        env.client.get("/api/bank/subscriptions").json()["subscriptions"][0]["status"] == "active"
    )
    replay = post(
        env.client, f"/api/conversations/{env.conversation}/continue", {"operation_id": op_ids[0]}
    )
    assert replay.status_code == 200 and len(captured) == 5
    assert replay.json()["cached"] is True
    assert decide(env, op_ids[1]).json()["state"] == "succeeded"
    final = post(
        env.client, f"/api/conversations/{env.conversation}/continue", {"operation_id": op_ids[1]}
    )
    assert final.status_code == 200
    assert all(s["state"] == "succeeded" for s in final.json()["operation_task"]["steps"])
    assert call(env)["operation"]["id"] == op_ids[0]
    accounts = env.client.get("/api/accounts").json()["accounts"]
    assert next(a for a in accounts if a["id"] == env.source)["balance_minor"] == 1276450
    assert next(a for a in accounts if a["id"] == env.target)["balance_minor"] == 3690000
    task_id = first.json()["operation_task"]["id"]
    assert len(env.client.get(f"/api/bank/operations?task_id={task_id}").json()["operations"]) == 2
    operations = env.client.get("/api/bank/operations").json()["operations"]
    assert len(operations) == 2 and "owner_id" not in json.dumps(operations)


def test_preauthorization_requires_explicit_policy_and_survives_restart(workflow_env):
    env = workflow_env
    grant_id = create_grant(env)
    assert (
        env.client.get(f"/api/conversations/{env.conversation}/policy").json()["mode"]
        == "HUMAN_APPROVAL"
    )
    op = call(env)["operation"]
    assert op["state"] == "awaiting_confirmation"
    select_policy(env, grant_id)
    assert call(env)["operation"]["state"] == "awaiting_confirmation"
    assert decide(env, op["id"]).json()["state"] == "succeeded"
    restarted = Agent(env.app.state.store, env.app.state.auth, env.settings)
    assert restarted.operations.policy(env.context, env.conversation)["grant_id"] == grant_id
    with trace_scope(uuid4().hex, env.conversation):
        result = restarted.tool(
            env.context, "prepare_transfer", {**env.arguments, "amount_minor": 15000}
        )
    assert result["operation"]["state"] == "succeeded"
    assert result["operation"]["mode"] == "PREAUTHORIZED"
    assert (
        restarted.operations.checkpoint(env.context, env.conversation)["steps"][-1]["state"]
        == "succeeded"
    )
    assert env.client.get("/api/bank/grants").json()["grants"][0]["spent_minor"] == 15000


def test_autonomous_budget_scope_and_revoke_are_rechecked(workflow_env):
    env = workflow_env
    grant_id = create_grant(env)
    select_policy(env, grant_id)
    args = {**env.arguments, "amount_minor": 15000}
    op = call(env, arguments=args)["operation"]
    assert op["state"] == "succeeded"
    assert call(env, arguments=args)["operation"]["id"] == op["id"]
    assert (
        call(env, arguments={**env.arguments, "amount_minor": 20100})["error"]
        == "SINGLE_LIMIT_EXCEEDED"
    )
    assert call(env, arguments={**env.arguments, "amount_minor": 1000})["error"] == "TASK_PAUSED"
    assert (
        env.app.state.agent.operation_checkpoint(env.context, env.conversation)["pause_reason"]
        == "SINGLE_LIMIT_EXCEEDED"
    )
    select_policy(env, grant_id)
    assert (
        call(env, arguments={**env.arguments, "amount_minor": 20000})["error"] == "GRANT_EXHAUSTED"
    )
    select_policy(env, grant_id)
    post(env.client, f"/api/bank/grants/{grant_id}/revoke", {})
    assert call(env, arguments={**env.arguments, "amount_minor": 1000})["error"] == "GRANT_INVALID"
    assert call(env, arguments=args)["operation"]["state"] == "succeeded"
    grant = env.client.get("/api/bank/grants").json()["grants"][0]
    assert grant["spent_minor"] == 15000 and grant["reserved_minor"] == 0


@pytest.mark.parametrize("api_style", ["responses", "chat"])
def test_authorized_model_can_finish_bill_cancel_and_transfer_without_extra_approval(
    workflow_env, monkeypatch, api_style
):
    env = workflow_env
    subscription = env.client.get("/api/bank/subscriptions").json()["subscriptions"][0]
    grant_id = create_grant(
        env,
        allowed_operations=["transfer", "cancel_subscription"],
        subscription_ids=[subscription["id"]],
    )
    select_policy(env, grant_id)
    captured = mock_model(
        env,
        monkeypatch,
        [
            ("get_billing_summary", {"start": "2026-01-01", "end": "2027-01-01"}),
            (
                "prepare_subscription_cancellation",
                {
                    "source_id": subscription["account_id"],
                    "subscription_id": subscription["id"],
                    "currency": "CNY",
                },
            ),
            ("prepare_transfer", env.arguments),
            "账单查询完成，指定订阅已取消，已从现有余额转账100元。",
        ],
        api_style,
    )
    response = question(
        env.client, "查询账单、取消指定订阅，再从现有余额转账100元", env.conversation
    )
    assert response.status_code == 200 and len(captured) == 4
    assert all(s["state"] == "succeeded" for s in response.json()["operation_task"]["steps"])
    assert (
        env.client.get("/api/bank/subscriptions").json()["subscriptions"][0]["status"]
        == "cancelled"
    )
    assert env.client.get("/api/bank/grants").json()["grants"][0]["spent_minor"] == 10000
    assert "PREAUTHORIZED" in json.dumps(captured[0])


@pytest.mark.parametrize(
    "point,expected", [("after_debit", "outcome_unknown"), ("after_commit", "succeeded")]
)
def test_unknown_or_lost_response_never_reexecutes_payment(workflow_env, point, expected):
    env = workflow_env
    select_policy(env, create_grant(env))

    def fail(current):
        if current == point:
            raise TimeoutError("test-only injected interruption")

    env.app.state.agent.bank.fault_hook = fail
    failed = call(env)
    assert failed["error"] in {"OUTCOME_UNKNOWN", "RESULT_UNAVAILABLE"}
    operation_id = failed["operation_id"]
    env.app.state.agent.bank.fault_hook = None
    assert call(env)["operation"]["id"] == operation_id
    assert call(env)["operation"]["state"] == expected
    with env.app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == (
            2 if expected == "succeeded" else 0
        )
    if expected == "outcome_unknown":
        assert (
            call(env, arguments={**env.arguments, "amount_minor": 1000})["error"] == "TASK_PAUSED"
        )
        assert env.client.get("/api/bank/grants").json()["grants"][0]["reserved_minor"] == 10000


def test_rejection_stops_new_steps_and_cannot_be_continued(workflow_env):
    env = workflow_env
    op = call(env)["operation"]
    assert decide(env, op["id"], "reject").json()["state"] == "rejected"
    assert (
        call(env, arguments={**env.arguments, "amount_minor": 1000})["error"]
        == "STEP_PARAMETERS_CONFLICT"
    )
    assert (
        post(
            env.client,
            f"/api/conversations/{env.conversation}/continue",
            {"operation_id": op["id"]},
        ).status_code
        == 409
    )
    assert env.client.get("/api/bank/operations").json()["operations"][0]["state"] == "rejected"


def test_policy_list_and_continuation_respect_identity_csrf_and_strict_inputs(workflow_env):
    env = workflow_env
    grant_id = create_grant(env)
    op = call(env)["operation"]
    assert (
        post(
            env.client, f"/api/conversations/{env.conversation}/policy", {"mode": "AUTO"}
        ).status_code
        == 422
    )
    assert (
        post(
            env.client, f"/api/conversations/{env.conversation}/policy", {"mode": "PREAUTHORIZED"}
        ).status_code
        == 422
    )
    assert (
        post(
            env.client,
            f"/api/conversations/{env.conversation}/continue",
            {"operation_id": op["id"], "confirmed": True},
        ).status_code
        == 422
    )
    assert (
        env.client.post(
            f"/api/conversations/{env.conversation}/policy",
            json={"mode": "PREAUTHORIZED", "grant_id": grant_id},
        ).status_code
        == 403
    )
    task_id = op["task_id"]
    post(env.client, "/api/auth/logout", {})
    login(env.client, "bob")
    assert env.client.get("/api/bank/operations").json()["operations"] == []
    assert env.client.get(f"/api/bank/operations?task_id={task_id}").status_code == 404
    assert env.client.get(f"/api/conversations/{env.conversation}/policy").status_code == 404
    assert (
        post(
            env.client,
            f"/api/conversations/{env.conversation}/policy",
            {"mode": "PREAUTHORIZED", "grant_id": grant_id},
        ).status_code
        == 404
    )


def test_existing_primary_intent_is_reused_after_workflow_upgrade(workflow_env):
    env = workflow_env
    bank = env.app.state.bank
    request_id = env.app.state.agent.conversation_request_id(env.context, env.conversation)
    task_id = bank.task(env.context, request_id)["id"]
    legacy = bank.prepare(
        env.context,
        {
            **env.arguments,
            "task_id": task_id,
            "step_key": "primary_intent",
            "mode": "HUMAN_APPROVAL",
            "grant_id": None,
            "confirmation_seconds": 300,
        },
    )
    assert call(env)["operation"]["id"] == legacy["id"]
    assert len(env.client.get("/api/bank/operations").json()["operations"]) == 1


def test_concurrent_authorized_replay_returns_original_state_without_pausing(workflow_env):
    env = workflow_env
    select_policy(env, create_grant(env))
    barrier, started, release = threading.Barrier(2), threading.Event(), threading.Event()
    bank = env.app.state.agent.bank
    original = bank.execute

    def synchronized_execute(context, operation_id):
        barrier.wait(timeout=5)
        return original(context, operation_id)

    def hold_before_transaction(point):
        if point == "before_transaction":
            started.set()
            assert release.wait(timeout=5)

    bank.execute = synchronized_execute
    bank.fault_hook = hold_before_transaction
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call, env) for _ in range(2)]
        try:
            assert started.wait(timeout=5)
            completed, _ = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
            assert completed
            first = next(iter(completed)).result()
            assert first["operation"]["state"] == "executing"
        finally:
            release.set()
        results = [future.result(timeout=5) for future in futures]
    assert len({result["operation"]["id"] for result in results}) == 1
    assert bank.operation(env.context, results[0]["operation"]["id"])["state"] == "succeeded"
    assert env.app.state.agent.operations.pause_reason(env.context, env.conversation) is None
    assert env.client.get("/api/bank/grants").json()["grants"][0]["spent_minor"] == 10000
    with env.app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 2


def test_other_users_grant_cannot_be_selected_even_for_own_conversation(workflow_env):
    env = workflow_env
    grant_id = create_grant(env)
    post(env.client, "/api/auth/logout", {})
    login(env.client, "bob")
    conversation = post(env.client, "/api/conversations", {}).json()["id"]
    response = post(
        env.client,
        f"/api/conversations/{conversation}/policy",
        {"mode": "PREAUTHORIZED", "grant_id": grant_id},
    )
    assert response.status_code == 403 and response.json()["code"] == "GRANT_INVALID"
    assert (
        env.client.get(f"/api/conversations/{conversation}/policy").json()["mode"]
        == "HUMAN_APPROVAL"
    )
    assert env.client.get("/api/bank/operations?limit=101").status_code == 422


def test_model_round_budget_is_bounded_without_hiding_partial_state(workflow_env, monkeypatch):
    env = workflow_env
    captured = mock_model(env, monkeypatch, [("list_accounts", {})] * 8)
    response = question(env.client, "反复查询账户", env.conversation)
    assert response.status_code == 502 and response.json()["code"] == "TOOL_LIMIT"
    assert len(captured) == 8
    assert env.client.get("/api/bank/operations").json()["operations"] == []
    turns = env.client.get(f"/api/conversations/{env.conversation}").json()["turns"]
    assert turns[-1]["status"] == "failed"
