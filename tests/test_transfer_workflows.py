from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from test_agent_workflow import mock_model
from test_application import PASSWORD, login, post, question
from test_banking import approve, balances, grant, preparation
from test_banking import bank_env as shared_bank_fixture

from ai_banking.banking.contacts import find_payees, load_demo_contacts
from ai_banking.banking.service import BankError
from ai_banking.banking.workflows import conversation_plan, create_plan

bank_env = shared_bank_fixture


def selected_values(env):
    subscriptions = env.client.get("/api/bank/subscriptions").json()["subscriptions"]
    return {
        "source_id": env.source,
        "payee_id": env.payee,
        "amount_minor": 100,
        "subscription_ids": [subscriptions[0]["id"]],
    }


def select_plan(env, values=None):
    values = values or selected_values(env)
    preview = post(env.client, "/api/bank/plans/preview", values)
    assert preview.status_code == 200, preview.text
    body = {
        **values,
        "request_id": uuid4().hex,
        "evidence_digest": preview.json()["evidence_digest"],
        "acknowledged": True,
    }
    response = post(env.client, "/api/bank/plans", body)
    assert response.status_code == 200, response.text
    return response.json(), body


def planned_prepare(env, plan, index, **changes):
    step = plan["steps"][index]
    values = {
        **step["arguments"],
        "task_id": plan["task_id"],
        "step_key": f"plan_{index}",
        "mode": "HUMAN_APPROVAL",
        "grant_id": None,
        "confirmation_seconds": 300,
        **changes,
    }
    return env.bank.prepare(env.context, values, step["kind"])


def test_demo_contacts_are_explicit_private_idempotent_and_cannot_login(bank_env):
    env = bank_env
    before = balances(env)
    assert env.client.post("/api/bank/payees/demo", json={"password": PASSWORD}).status_code == 403
    assert post(env.client, "/api/bank/payees/demo", {"password": "wrong"}).status_code == 401
    response = post(env.client, "/api/bank/payees/demo", {"password": PASSWORD})
    assert response.status_code == 200
    first = response.json()["payees"]
    assert len(first) == 5 and sum(p["kind"] == "demo" for p in first) == 3
    assert not any("balance_minor" in p or "owner_id" in p for p in first)
    assert (
        post(env.client, "/api/bank/payees/demo", {"password": PASSWORD}).json()["payees"] == first
    )
    assert balances(env) == before and env.bank.grants(env.context) == []
    with env.store.transaction() as db:
        demo = db.execute(
            "SELECT username,enabled FROM users WHERE username LIKE 'demo_%'"
        ).fetchall()
        assert len(demo) == 3 and all(not row["enabled"] for row in demo)
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 0
    foreign_account = next(p["account_id"] for p in first if p["kind"] == "demo")
    assert env.client.get(f"/api/accounts/{foreign_account}").status_code == 404
    post(env.client, "/api/auth/logout", {})
    assert (
        post(
            env.client, "/api/auth/login", {"username": demo[0]["username"], "password": PASSWORD}
        ).status_code
        == 401
    )


def test_payee_search_ambiguity_notes_and_user_isolation(bank_env):
    env = bank_env
    own = load_demo_contacts(env.bank, env.context)["payees"]
    result = find_payees(env.bank, env.context, "张明")
    assert result["resolution"] == "needs_clarification" and result["match_count"] == 2
    selected = find_payees(env.bank, env.context, "房东")
    assert selected["resolution"] == "unique" and selected["matches"][0]["suffix"] == "5938"
    assert find_payees(env.bank, env.context, " ４７１２ ")["match_count"] == 1
    assert find_payees(env.bank, env.context, "不存在")["resolution"] == "not_found"
    target = selected["matches"][0]
    updated = post(
        env.client,
        f"/api/bank/payees/{target['id']}/note",
        {"note": "<script>alter()</script> 房租", "password": PASSWORD},
    )
    assert updated.status_code == 200
    assert updated.json()["payee"]["account_id"] == target["account_id"]
    post(env.client, "/api/auth/logout", {})
    login(env.client, "bob")
    assert len(env.client.get("/api/bank/payees").json()["payees"]) == 2
    assert (
        post(
            env.client,
            f"/api/bank/payees/{target['id']}/note",
            {"note": "changed", "password": PASSWORD},
        ).status_code
        == 404
    )
    other = post(env.client, "/api/bank/payees/demo", {"password": PASSWORD}).json()["payees"]
    assert not {p["account_id"] for p in own} & {p["account_id"] for p in other}


def test_transfer_to_demo_has_bound_recipient_and_balanced_real_receipt(bank_env):
    env = bank_env
    load_demo_contacts(env.bank, env.context)
    target = find_payees(env.bank, env.context, "房东")["matches"][0]
    before = balances(env)
    operation = env.bank.prepare(env.context, preparation(env, amount=123, payee_id=target["id"]))
    challenge = env.bank.challenge(env.context, operation["id"])
    assert challenge["summary"]["recipient"]["suffix"] == "5938"
    assert challenge["summary"]["recipient"]["account_id"] == target["account_id"]
    assert balances(env) == before
    approve(env, operation["id"])
    with env.store.transaction() as db:
        assert (
            db.execute(
                "SELECT balance_minor FROM accounts WHERE id=?", (target["account_id"],)
            ).fetchone()[0]
            == 123
        )
        assert (
            db.execute(
                "SELECT SUM(amount_minor) FROM bank_ledger WHERE operation_id=?", (operation["id"],)
            ).fetchone()[0]
            == 0
        )
    assert len(balances(env)) == 2


def test_loading_contacts_does_not_expand_existing_grant(bank_env):
    env = bank_env
    grant_id = grant(env)
    before = balances(env)
    load_demo_contacts(env.bank, env.context)
    target = find_payees(env.bank, env.context, "房东")["matches"][0]
    with pytest.raises(BankError) as failure:
        env.bank.prepare(
            env.context,
            preparation(
                env, amount=100, payee_id=target["id"], mode="PREAUTHORIZED", grant_id=grant_id
            ),
        )
    assert failure.value.code == "POLICY_REJECTED"
    assert balances(env) == before
    assert env.bank.grants(env.context)[0]["spent_minor"] == 0
    assert env.bank.grants(env.context)[0]["reserved_minor"] == 0


def test_plan_preview_and_creation_do_not_move_funds_or_authorize(bank_env):
    env = bank_env
    before = balances(env)
    plan, body = select_plan(env)
    assert len(plan["steps"]) == 2
    assert all(s["state"] == "not_started" for s in plan["steps"])
    assert (
        plan["preview"]["estimated_balance_minor"] == plan["preview"]["current_balance_minor"] - 100
    )
    assert plan["preview"]["future_reduction_per_cycle_minor"] > 0
    assert (
        post(env.client, "/api/bank/plans", body).json()["conversation_id"]
        == plan["conversation_id"]
    )
    assert post(env.client, "/api/bank/plans", {**body, "amount_minor": 200}).status_code == 409
    assert post(env.client, "/api/bank/plans", {**body, "acknowledged": False}).status_code == 422
    assert post(env.client, "/api/bank/plans", {**body, "acknowledged": 1}).status_code == 422
    assert (
        env.app.state.agent.operations.policy(env.context, plan["conversation_id"])["mode"]
        == "HUMAN_APPROVAL"
    )
    assert balances(env) == before and env.bank.grants(env.context) == []
    assert not env.bank.operations(env.context)
    history = env.client.get(f"/api/conversations/{plan['conversation_id']}").json()
    assert history["workflow_plan"]["task_id"] == plan["task_id"]


def test_plan_creation_revalidates_balance_notes_and_subscription_evidence(bank_env):
    env = bank_env
    values = selected_values(env)
    preview = post(env.client, "/api/bank/plans/preview", values).json()
    body = {
        **values,
        "request_id": uuid4().hex,
        "evidence_digest": preview["evidence_digest"],
        "acknowledged": True,
    }
    post(
        env.client, f"/api/bank/payees/{env.payee}/note", {"note": "新的备注", "password": PASSWORD}
    )
    assert post(env.client, "/api/bank/plans", body).json()["code"] == "PLAN_EVIDENCE_CHANGED"
    assert env.client.post("/api/bank/plans", json=body).status_code == 403
    assert (
        post(
            env.client,
            "/api/bank/plans/preview",
            {**values, "subscription_ids": values["subscription_ids"] * 2},
        ).status_code
        == 422
    )
    other_payee = next(
        p["id"] for p in env.bank.payees(env.context) if p["account_id"] == env.source
    )
    assert (
        post(
            env.client,
            "/api/bank/plans/preview",
            {
                **values,
                "source_id": env.target,
                "payee_id": other_payee,
            },
        ).status_code
        == 409
    )


def test_plan_blocks_out_of_order_changed_amount_and_new_id_replay(bank_env):
    env = bank_env
    plan, _ = select_plan(env)
    with pytest.raises(BankError) as failure:
        planned_prepare(env, plan, 1)
    assert failure.value.code == "PLAN_PARAMETERS_CONFLICT"
    cancellation = planned_prepare(env, plan, 0)
    with pytest.raises(BankError) as failure:
        planned_prepare(env, plan, 1)
    assert failure.value.code == "PLAN_STEP_BLOCKED"
    approve(env, cancellation["id"])
    with pytest.raises(BankError) as failure:
        planned_prepare(env, plan, 1, amount_minor=200)
    assert failure.value.code == "PLAN_PARAMETERS_CONFLICT"
    transfer = planned_prepare(env, plan, 1)
    approve(env, transfer["id"])
    assert planned_prepare(env, plan, 1)["id"] == transfer["id"]
    with pytest.raises(BankError) as failure:
        planned_prepare(env, plan, 1, step_key="new_id_to_repeat_payment")
    assert failure.value.code == "PLAN_PARAMETERS_CONFLICT"
    assert conversation_plan(env.bank, env.context, plan["conversation_id"])["completed"]
    with env.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 2


@pytest.mark.parametrize("state", ["rejected", "failed", "expired", "outcome_unknown"])
def test_unsuccessful_plan_step_stops_following_payment(bank_env, state):
    env = bank_env
    plan, _ = select_plan(env)
    operation = planned_prepare(env, plan, 0)
    with env.store.transaction() as db:
        db.execute("UPDATE bank_operations SET state=? WHERE id=?", (state, operation["id"]))
    with pytest.raises(BankError) as failure:
        planned_prepare(env, plan, 1)
    assert failure.value.code == "PLAN_STEP_BLOCKED"


def test_preauthorized_plan_still_rechecks_scope_and_only_executes_selected_steps(bank_env):
    env = bank_env
    plan, body = select_plan(env)
    grant_id = grant(
        env,
        allowed_operations=["transfer", "cancel_subscription"],
        subscription_ids=body["subscription_ids"],
    )
    operations = env.app.state.agent.operations
    operations.select_policy(env.context, plan["conversation_id"], "PREAUTHORIZED", grant_id)
    first = operations.prepare(
        env.context, plan["conversation_id"], plan["steps"][0]["arguments"], "cancel_subscription"
    )
    assert first["operation"]["state"] == "succeeded"
    with pytest.raises(BankError) as failure:
        operations.prepare(
            env.context,
            plan["conversation_id"],
            {**plan["steps"][1]["arguments"], "amount_minor": 200},
            "transfer",
        )
    assert failure.value.code == "PLAN_PARAMETERS_CONFLICT"
    assert env.bank.grants(env.context)[0]["spent_minor"] == 0
    assert (
        operations.pause_reason(env.context, plan["conversation_id"]) == "PLAN_PARAMETERS_CONFLICT"
    )
    operations.select_policy(env.context, plan["conversation_id"], "PREAUTHORIZED", grant_id)
    transfer = operations.prepare(
        env.context, plan["conversation_id"], plan["steps"][1]["arguments"], "transfer"
    )
    assert transfer["operation"]["state"] == "succeeded"
    assert (
        operations.prepare(
            env.context, plan["conversation_id"], plan["steps"][1]["arguments"], "transfer"
        )["operation"]["id"]
        == transfer["operation"]["id"]
    )
    assert env.bank.grants(env.context)[0]["spent_minor"] == 100


@pytest.mark.parametrize("api_style", ["responses", "chat"])
def test_model_plan_continues_after_each_independent_approval(bank_env, monkeypatch, api_style):
    env = bank_env
    plan, _ = select_plan(env)
    captured = mock_model(
        env,
        monkeypatch,
        [
            ("prepare_subscription_cancellation", plan["steps"][0]["arguments"]),
            "取消已准备，请核对确认单。",
            ("prepare_transfer", plan["steps"][1]["arguments"]),
            "转账已准备，请核对确认单。",
            "原操作已成功，方案已完成。",
        ],
        api_style,
    )
    response = question(env.client, "按界面选定的方案办理", conversation=plan["conversation_id"])
    assert response.status_code == 200, response.text
    cancellation = env.bank.operations(env.context, task_id=plan["task_id"])[0]
    assert cancellation["state"] == "awaiting_confirmation"
    approve(env, cancellation["id"])
    response = post(
        env.client,
        f"/api/conversations/{plan['conversation_id']}/continue",
        {"operation_id": cancellation["id"]},
    )
    assert response.status_code == 200, response.text
    transfer = next(
        op
        for op in env.bank.operations(env.context, task_id=plan["task_id"])
        if op["kind"] == "transfer"
    )
    assert transfer["state"] == "awaiting_confirmation"
    approve(env, transfer["id"])
    response = post(
        env.client,
        f"/api/conversations/{plan['conversation_id']}/continue",
        {"operation_id": transfer["id"]},
    )
    assert response.status_code == 200, response.text
    assert conversation_plan(env.bank, env.context, plan["conversation_id"])["completed"]
    assert "workflow_plan" in str(captured[0])
    turns = env.client.get(f"/api/conversations/{plan['conversation_id']}").json()["turns"]
    assert [turn["application_notice"] for turn in turns] == [False, True, True]


def test_plan_does_not_use_future_savings_as_current_money(bank_env):
    env = bank_env
    values = selected_values(env)
    balance = balances(env)[env.source]
    response = post(env.client, "/api/bank/plans/preview", {**values, "amount_minor": balance + 1})
    assert response.status_code == 409 and response.json()["code"] == "INSUFFICIENT_BALANCE"
    with env.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_operations").fetchone()[0] == 0


def test_concurrent_plan_creation_replays_same_conversation(bank_env):
    env = bank_env
    values = selected_values(env)
    preview = post(env.client, "/api/bank/plans/preview", values).json()
    body = {
        **values,
        "request_id": uuid4().hex,
        "evidence_digest": preview["evidence_digest"],
        "acknowledged": True,
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        plans = list(pool.map(lambda _: create_plan(env.bank, env.context, body), range(2)))
    assert plans[0]["conversation_id"] == plans[1]["conversation_id"]
    with env.store.transaction() as db:
        count = db.execute("SELECT COUNT(*) FROM bank_events WHERE event='workflow_plan_selected'")
        assert count.fetchone()[0] == 1


def test_subscription_date_change_invalidates_reviewed_plan(bank_env):
    env = bank_env
    values = selected_values(env)
    preview = post(env.client, "/api/bank/plans/preview", values).json()
    body = {
        **values,
        "request_id": uuid4().hex,
        "evidence_digest": preview["evidence_digest"],
        "acknowledged": True,
    }
    with env.store.transaction() as db:
        db.execute(
            "UPDATE bank_subscriptions SET next_charge_at='2030-01-01T00:00:00+00:00' WHERE id=?",
            (values["subscription_ids"][0],),
        )
    assert post(env.client, "/api/bank/plans", body).json()["code"] == "PLAN_EVIDENCE_CHANGED"


def test_plan_and_search_interfaces_reject_cross_user_or_extra_identity(bank_env):
    env = bank_env
    plan, _ = select_plan(env)
    assert (
        env.app.state.agent.dispatch(
            env.context, "find_payees", {"query": "本人", "owner_id": "bob"}
        )["error"]
        == "TOOL_ARGUMENTS_REJECTED"
    )
    post(env.client, "/api/auth/logout", {})
    login(env.client, "bob")
    assert env.client.get(f"/api/conversations/{plan['conversation_id']}").status_code == 404
    assert post(env.client, "/api/bank/plans/preview", selected_values(env)).status_code in {
        404,
        409,
    }
