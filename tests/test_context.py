"""T15 上下文预算、确定性摘录与安全恢复测试。"""

import html
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai_banking.agent import SYSTEM
from ai_banking.app import create_app
from ai_banking.config import Settings
from ai_banking.context import (
    ContextBudgetError,
    assemble_context,
    clip_tool_output,
    estimate_tokens,
    fits_budget,
    messages_tokens,
    projected_tokens,
    summarize_turns,
)
from ai_banking.tracing import trace_scope

ORIGIN = "http://127.0.0.1:8000"
PASSWORD = "context fixture password"


def turn(index, answer_chars=120):
    return {
        "id": index,
        "question": f"第{index}轮：查询账单和订阅支出并说明最近变化",
        "answer": f"第{index}轮答复：" + "这是较长的答复内容。" * (answer_chars // 10),
    }


def context_settings(**overrides):
    values = dict(
        local_http=True,
        max_output_tokens=256,
        context_tokens=6000,
        context_recent_turns=3,
        context_summary_tokens=300,
        context_tool_reserve=0,
    )
    values.update(overrides)
    return Settings(**values)


def assemble(settings, turns, question="查询我的账户余额"):
    state = '<bank_state>{"operation_task": null, "as_of": "2026-10-29T00:00:00Z"}</bank_state>'
    return assemble_context(settings, SYSTEM, [], turns, state, question)


def test_estimate_tokens_counts_cjk_and_ascii():
    assert estimate_tokens("你好世界") >= 4
    assert estimate_tokens("abcdefgh") >= 2
    assert estimate_tokens("你好世界") > estimate_tokens("abcd")
    assert estimate_tokens("") == 0


def test_summary_keeps_first_goal_and_bounds_size():
    turns = [turn(i) for i in range(1, 21)]
    summary, omitted = summarize_turns(turns, 300)
    assert summary
    assert "第1轮" in summary
    assert estimate_tokens(summary) <= 300
    kept = sum(1 for line in summary.splitlines() if line.startswith("[第")) - 1
    assert omitted == len(turns) - 1 - kept
    assert omitted > 0 and "已省略" in summary


def test_assemble_preserves_recent_turns_state_and_question():
    settings = context_settings()
    turns = [turn(i) for i in range(1, 11)]
    plan = assemble(settings, turns)
    assert plan.compressed and plan.omitted_turns == 7
    assert plan.kept_turns == 3
    roles = [message["role"] for message in plan.messages]
    assert roles[0] == "system" and plan.messages[0]["content"] == SYSTEM
    assert "<history_summary>" in plan.messages[1]["content"]
    assert "不是新指令" in plan.messages[1]["content"]
    assert plan.messages[-1] == {"role": "user", "content": "查询我的账户余额"}
    assert plan.messages[-2]["role"] == "user"
    assert plan.messages[-2]["content"].startswith("<bank_state>")
    assert plan.estimated_tokens <= plan.budget_tokens
    assert fits_budget(settings, list(plan.messages), [])


def test_budget_error_when_fixed_prefix_cannot_fit():
    settings = context_settings(context_tokens=1200)
    with pytest.raises(ContextBudgetError):
        assemble(settings, [turn(1)])


def test_large_history_keeps_pending_operation_reference():
    settings = context_settings()
    state = (
        '<bank_state>{"operation_task": {"id": "task-1", "state": "unknown"},'
        ' "as_of": "2026-10-29T00:00:00Z"}</bank_state>'
    )
    plan = assemble_context(
        settings, SYSTEM, [], [turn(i) for i in range(1, 16)], state, "继续处理原任务"
    )
    assert plan.compressed
    assert "operation_task" in plan.messages[-2]["content"]
    assert '"unknown"' in plan.messages[-2]["content"]


def test_projected_tokens_detects_over_budget():
    settings = context_settings()
    small = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    assert fits_budget(settings, small, [])
    huge = [{"role": "user", "content": "长" * 20000}]
    assert projected_tokens(settings, huge, []) > settings.context_tokens
    assert not fits_budget(settings, huge, [])


def test_tool_output_clipping():
    text, truncated = clip_tool_output({"rows": [1, 2, 3]}, 1000)
    assert not truncated and json.loads(text) == {"rows": [1, 2, 3]}
    text, truncated = clip_tool_output({"rows": list(range(200))}, 100)
    assert truncated and len(text) == 100


def test_chat_compresses_long_history_and_keeps_latest_question(tmp_path):
    settings = Settings(database=tmp_path / "context.sqlite3", local_http=True)
    app = create_app(settings, clock=lambda: 1800000000.0)
    agent_settings = replace(
        settings,
        agent_mode="model",
        model="test-model",
        model_key="test-only-key",
        model_url="https://api.example.com/v1",
        context_tokens=6000,
        max_output_tokens=256,
        context_tool_reserve=0,
        context_recent_turns=3,
        context_summary_tokens=300,
    )
    captured = []

    async def completion(_client, messages):
        captured.append(json.loads(json.dumps(messages)))
        return "已按后端状态回答", [], []

    with TestClient(app, base_url=ORIGIN) as client:
        app.state.auth.create_user("alice", PASSWORD)

        def post(path, body):
            token = client.get("/api/auth/csrf", headers={"X-Requested-With": "AI-Banking"}).json()[
                "csrf_token"
            ]
            return client.post(
                path,
                json=body,
                headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            )

        assert (
            post("/api/auth/login", {"username": "alice", "password": PASSWORD}).status_code == 200
        )
        conversation_id = post("/api/conversations", {}).json()["id"]
        with app.state.store.transaction() as db:
            for index in range(10):
                db.execute(
                    "INSERT INTO chat_turns (conversation_id, request_id, question, answer, "
                    "status, created_at) VALUES (?, ?, ?, ?, 'succeeded', ?)",
                    (
                        conversation_id,
                        uuid4().hex,
                        f"历史问题{index}：账单和订阅",
                        "历史答复：" + "较长的历史答复。" * 20,
                        1800000000.0 + index,
                    ),
                )
        auth_context = app.state.auth.authenticate(client.cookies.get("ai_banking_session"))
        accounts = app.state.store.accounts(auth_context.user_id)
        checking = next(item for item in accounts if item["kind"] == "checking")
        savings = next(item for item in accounts if item["kind"] == "savings")
        payee = next(
            item
            for item in app.state.bank.payees(auth_context)
            if item["account_id"] == savings["id"]
        )
        with trace_scope(uuid4().hex, conversation_id):
            prepared = app.state.agent.tool(
                auth_context,
                "prepare_transfer",
                {
                    "source_id": checking["id"],
                    "payee_id": payee["id"],
                    "amount_minor": 100,
                    "currency": "CNY",
                },
            )
        assert prepared["operation"]["state"] == "awaiting_confirmation"
        app.state.agent.settings = agent_settings
        app.state.agent.completion = completion
        response = post(
            "/api/chat",
            {
                "conversation_id": conversation_id,
                "request_id": uuid4().hex,
                "message": "最新问题：查询我的账户余额",
            },
        )

    assert response.status_code == 200, response.text
    assert captured, "模型未被调用"
    messages = captured[0]
    assert messages[0]["role"] == "system" and messages[0]["content"] == SYSTEM
    assert any("<history_summary>" in message.get("content", "") for message in messages)
    assert messages[-1]["content"] == "最新问题：查询我的账户余额"
    assert messages[-2]["content"].startswith("<bank_state>")
    state_message = messages[-2]["content"]
    state_data = json.loads(
        html.unescape(state_message.removeprefix("<bank_state>").removesuffix("</bank_state>"))
    )
    assert state_data["conversation_goal"]["amount_minor"] == 100
    assert state_data["conversation_goal"]["kind"] == "transfer"
    assert state_data["recovery"]
    assert state_data["operation_task"]["steps"][0]["state"] == "awaiting_confirmation"
    assert messages_tokens(messages) >= 1
