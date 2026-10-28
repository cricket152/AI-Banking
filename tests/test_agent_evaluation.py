import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from test_application import env as shared_env
from test_application import login, post, question

from ai_banking.config import Settings
from ai_banking.evaluation import EvaluationSession, load_cases, main, run_case

__all__ = ["shared_env"]


def replay(script):
    class ScriptedSession(EvaluationSession):
        def __enter__(self):
            super().__enter__()
            queue = iter(script(self))

            async def completion(client, messages):
                self.model_calls += 1
                item = next(queue)
                if isinstance(item, str):
                    return item, [], []
                name, arguments = item
                call_id = uuid4().hex
                call = {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": json.dumps(arguments),
                }
                return None, [(call_id, name, call["arguments"])], [call]

            self.app.state.agent.completion = completion
            return self

    return ScriptedSession


def transfer_script(session, amount=10000):
    return [
        ("list_accounts", {}),
        ("list_payees", {}),
        (
            "prepare_transfer",
            {
                "source_id": session.source,
                "payee_id": session.payee,
                "amount_minor": amount,
                "currency": "CNY",
            },
        ),
        "请核对后端操作状态。",
    ]


@pytest.fixture
def eval_settings():
    return Settings(
        local_http=True,
        agent_mode="model",
        model="fixture-model",
        model_key="fixture-only",
        trace_enabled=False,
    )


def case(case_id):
    return deepcopy(next(item for item in load_cases() if item["id"] == case_id))


def test_listing_never_loads_credentials_or_calls_provider(monkeypatch, capsys):
    def forbidden():
        raise AssertionError("不应读取配置")

    monkeypatch.setattr(Settings, "from_env", forbidden)
    assert main(["--cases", "C01,Q01"]) == 0
    assert "未调用供应商" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["path", "assertion", "action"])
def test_invalid_corpus_is_rejected_before_any_execution(tmp_path, change):
    item = case("Q01")
    if change == "path":
        item["id"] = "../../outside"
    elif change == "assertion":
        item["expect"]["source_dleta"] = 0
    else:
        item["actions"][0]["type"] = "silent_approve"
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [item]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(path)


def test_checker_rejects_canned_answer_without_required_queries(eval_settings, tmp_path):
    result = run_case(
        eval_settings, case("Q01"), tmp_path / "query", replay(lambda _: ["总资产为49664.50元"])
    )
    assert not result["checks_passed"]
    assert "缺少工具：list_accounts" in result["issues"]
    assert result["operations"] == []


@pytest.mark.parametrize("amount,passed", [(10000, True), (100, False)])
def test_checker_detects_wrong_unit_and_preserves_pending_funds(
    eval_settings, tmp_path, amount, passed
):
    result = run_case(
        eval_settings,
        case("T01"),
        tmp_path / "manual",
        replay(lambda session: transfer_script(session, amount)),
    )
    assert result["checks_passed"] == passed
    assert result["operations"][0]["state"] == "awaiting_confirmation"
    assert result["review_status"] == "pending"


def test_no_write_case_fails_even_when_unapproved_prepare_does_not_debit(eval_settings, tmp_path):
    result = run_case(
        eval_settings,
        case("C01"),
        tmp_path / "clarification",
        replay(transfer_script),
    )
    assert not result["checks_passed"]
    assert "不应调用写工具：prepare_transfer" in result["issues"]


def test_preauthorized_replay_and_budget_are_checked_on_real_ledger(eval_settings, tmp_path):
    result = run_case(
        eval_settings,
        case("R02"),
        tmp_path / "replay",
        replay(lambda session: transfer_script(session, 5000) * 2),
    )
    assert result["checks_passed"]
    assert len(result["operations"]) == 1
    assert result["operations"][0]["state"] == "succeeded"


def test_failed_model_call_keeps_prepared_operation_in_report(eval_settings, tmp_path):
    result = run_case(
        eval_settings,
        case("T01"),
        tmp_path / "interrupted",
        replay(lambda session: transfer_script(session)[:-1]),
    )
    assert not result["checks_passed"]
    assert result["operations"][0]["state"] == "awaiting_confirmation"
    assert any(issue.startswith("执行未完成") for issue in result["issues"])


def test_expired_operation_is_queried_instead_of_recreated(eval_settings, tmp_path):
    def script(session):
        # seed_pending 动作发生在执行模型之前，因此调用时再读取持久操作。
        class LazyScript:
            def __iter__(self):
                operation = session.app.state.bank.operations(session.context)[0]
                yield ("get_operation", {"operation_id": operation["id"]})
                yield "原操作已过期，未执行，不重新付款。"

        return LazyScript()

    result = run_case(eval_settings, case("R05"), tmp_path / "expired", replay(script))
    assert result["checks_passed"]
    assert result["operations"][0]["state"] == "expired"


@pytest.mark.parametrize("style", ["responses", "chat"])
@pytest.mark.parametrize("after_prepare", [False, True])
def test_incomplete_response_never_executes_tool_calls_or_hides_existing_operation(
    shared_env, monkeypatch, style, after_prepare
):
    app, client, _, settings = shared_env
    login(client)
    agent = app.state.agent
    agent.settings = replace(
        settings, agent_mode="model", model="fixture", model_key="fixture", model_api=style
    )
    accounts = client.get("/api/accounts").json()["accounts"]
    source = next(a["id"] for a in accounts if a["kind"] == "checking")
    target = next(a["id"] for a in accounts if a["kind"] == "savings")
    payee = next(
        p["id"]
        for p in client.get("/api/bank/payees").json()["payees"]
        if p["account_id"] == target
    )
    arguments = json.dumps(
        {"source_id": source, "payee_id": payee, "amount_minor": 10000, "currency": "CNY"}
    )
    requests = []

    def handler(request):
        requests.append(request)
        incomplete = not after_prepare or len(requests) > 1
        if style == "responses":
            body = {
                "status": "incomplete" if incomplete else "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "fixture-call",
                        "name": "prepare_transfer",
                        "arguments": arguments,
                    }
                ],
            }
        else:
            body = {
                "choices": [
                    {
                        "finish_reason": "length" if incomplete else "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "fixture-call",
                                    "type": "function",
                                    "function": {
                                        "name": "prepare_transfer",
                                        "arguments": arguments,
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        return httpx.Response(200, json=body)

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "ai_banking.agent.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    conversation = post(client, "/api/conversations", {}).json()["id"]
    response = question(client, "从日常账户向本人储蓄账户转100元", conversation)
    assert response.status_code == 502
    assert response.json()["code"] == "MODEL_RESPONSE_INCOMPLETE"
    assert len(requests) == (2 if after_prepare else 1)
    operations = client.get("/api/bank/operations").json()["operations"]
    assert len(operations) == int(after_prepare)
    assert all(op["state"] == "awaiting_confirmation" for op in operations)
    assert client.get("/api/accounts").json()["accounts"] == accounts
