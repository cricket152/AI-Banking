from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_application import ORIGIN, PASSWORD, login, post
from test_banking import approve, balances, grant, preparation
from test_banking import bank_env as shared_bank_fixture

from ai_banking.banking.reports import Reports
from ai_banking.banking.service import Bank, BankError

bank_env = shared_bank_fixture


def test_report_shanghai_boundaries_and_refunds(bank_env):
    env = bank_env
    with env.store.transaction() as db:
        for amount, category, timestamp in [
            (-100, "购物", "2026-06-30T15:59:59+00:00"),
            (-200, "购物", "2026-06-30T16:00:00+00:00"),
            (50, "退款", "2026-07-01T15:59:59+00:00"),
            (-300, "购物", "2026-07-01T16:00:00+00:00"),
        ]:
            db.execute(
                "INSERT INTO entries VALUES (?,?,?,?,?,?)",
                (uuid4().hex, env.source, amount, "测试商户", category, timestamp),
            )
            db.execute(
                "UPDATE accounts SET balance_minor=balance_minor+? WHERE id=?", (amount, env.source)
            )
    report = Reports(env.bank).bills(env.context, date(2026, 7, 1), date(2026, 7, 2))
    assert report["expense_minor"] == 200 and report["refund_minor"] == 50
    assert report["net_expense_minor"] == 150 and len(report["entry_ids"]) == 2
    assert report["by_month"] == {"2026-07": 200}


def test_policy_creation_deduplicates_and_cannot_replace_active_policy(bank_env):
    env = bank_env
    request_id = uuid4().hex
    first = grant(env, request_id=request_id)
    assert grant(env, request_id=request_id) == first
    with pytest.raises(AssertionError, match="POLICY_REQUEST_CONFLICT"):
        grant(env, request_id=request_id, limit_minor=60000)
    with pytest.raises(AssertionError, match="ACTIVE_GRANT_EXISTS"):
        grant(env)
    assert len(env.bank.grants(env.context)) == 1


def test_other_payee_rejected_then_explicit_manual_transfer_updates_recipient(bank_env):
    env = bank_env
    with env.store.transaction() as db:
        owner, target = db.execute(
            "SELECT a.owner_id,a.id FROM accounts a JOIN users u ON u.id=a.owner_id "
            "WHERE u.username='bob' LIMIT 1"
        ).fetchone()
    payee = env.bank.add_payee(env.context, "Bob", target)["id"]
    grant_id = grant(env)
    with pytest.raises(BankError) as error:
        env.bank.prepare(
            env.context, preparation(env, mode="PREAUTHORIZED", grant_id=grant_id, payee_id=payee)
        )
    assert error.value.code == "POLICY_REJECTED"
    op = env.bank.prepare(env.context, preparation(env, payee_id=payee))
    approve(env, op["id"])
    with env.store.transaction() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM bank_events WHERE owner_id=? AND event='transfer_received'",
                (owner,),
            ).fetchone()[0]
            == 1
        )
    assert sum(balances(env).values()) == 4966450 - 12345


def test_policy_budget_survives_logout_and_restart(bank_env):
    env = bank_env
    grant_id = grant(env)
    op = env.bank.prepare(
        env.context, preparation(env, 30000, mode="PREAUTHORIZED", grant_id=grant_id)
    )
    env.bank.execute(env.context, op["id"])
    post(env.client, "/api/auth/logout", {})
    login(env.client)
    env.context = env.app.state.auth.authenticate(env.client.cookies.get("ai_banking_session"))
    restarted = Bank(env.store, env.app.state.auth)
    restarted.recover_startup()
    assert restarted.grants(env.context)[0]["spent_minor"] == 30000
    assert restarted.grants(env.context)[0]["remaining_minor"] == 20000
    with pytest.raises(BankError) as error:
        restarted.prepare(
            env.context, preparation(env, 20001, mode="PREAUTHORIZED", grant_id=grant_id)
        )
    assert error.value.code == "GRANT_EXHAUSTED"


def test_expired_grant_releases_only_pending_reservations(bank_env):
    env = bank_env
    grant_id = grant(env, expires_at=env.now[0] + 60)
    op = env.bank.prepare(env.context, preparation(env, mode="PREAUTHORIZED", grant_id=grant_id))
    env.now[0] += 60
    assert env.bank.operation(env.context, op["id"])["state"] == "expired"
    policy = env.bank.grants(env.context)[0]
    assert policy["status"] == "expired" and policy["reserved_minor"] == 0


def test_reset_invalidates_policies_and_pending_approvals(bank_env):
    env = bank_env
    grant_id = grant(env)
    pending = env.bank.prepare(env.context, preparation(env))
    env.app.state.auth.change_user("alice", PASSWORD + "new")
    login(env.client, password=PASSWORD + "new")
    env.context = env.app.state.auth.authenticate(env.client.cookies.get("ai_banking_session"))
    assert env.bank.grants(env.context)[0]["status"] == "invalidated"
    assert env.bank.operation(env.context, pending["id"])["state"] == "expired"
    with pytest.raises(BankError):
        env.bank.prepare(env.context, preparation(env, mode="PREAUTHORIZED", grant_id=grant_id))


def test_approval_challenge_bound_to_session_and_exact_summary(bank_env):
    env = bank_env
    op = env.bank.prepare(env.context, preparation(env))
    proof = env.bank.challenge(env.context, op["id"])
    with pytest.raises(BankError) as error:
        env.bank.decide(env.context, op["id"], "approve", proof["challenge"], "0" * 64)
    assert error.value.code == "APPROVAL_PROOF_REJECTED"
    with TestClient(env.app, base_url=ORIGIN) as second:
        login(second)
        context = env.app.state.auth.authenticate(second.cookies.get("ai_banking_session"))
        with pytest.raises(BankError):
            env.bank.decide(
                context, op["id"], "approve", proof["challenge"], op["parameters_digest"]
            )
    assert balances(env)[env.source] == 1286450


def test_zero_budget_policy_can_cancel_only_named_subscription(bank_env):
    env = bank_env
    subscriptions = Reports(env.bank).subscriptions(env.context)["subscriptions"]
    grant_id = grant(
        env,
        allowed_operations=["cancel_subscription"],
        payee_ids=[],
        subscription_ids=[subscriptions[0]["id"]],
        limit_minor=0,
        single_minor=0,
    )
    values = preparation(env, mode="PREAUTHORIZED", grant_id=grant_id)
    values.pop("payee_id")
    values.pop("amount_minor")
    values["subscription_id"] = subscriptions[1]["id"]
    with pytest.raises(BankError) as error:
        env.bank.prepare(env.context, values, "cancel_subscription")
    assert error.value.code == "POLICY_REJECTED"
    values["subscription_id"] = subscriptions[0]["id"]
    op = env.bank.prepare(env.context, values, "cancel_subscription")
    assert env.bank.execute(env.context, op["id"])["state"] == "succeeded"
    assert env.bank.grants(env.context)[0]["spent_minor"] == 0
    assert sum(balances(env).values()) == 4966450


def test_business_tools_consistent_snapshot_and_no_model_write_access(bank_env):
    env = bank_env
    agent = env.app.state.agent
    assert len(agent.tool(env.context, "list_subscriptions", {})["subscriptions"]) == 2
    assert len(agent.tool(env.context, "list_payees", {})["payees"]) == 2
    result = agent.tool(
        env.context, "get_billing_summary", {"start": "2026-01-01", "end": "2027-01-01"}
    )
    assert result["expense_minor"] == 0
    assert agent.tool(env.context, "get_billing_summary", {"start": "bad", "end": "bad"})["error"]
    assert agent.tool(env.context, "execute_transfer", {})["error"] == "TOOL_ARGUMENTS_REJECTED"
    portfolio = agent.tool(env.context, "list_accounts", {})
    assert (
        sum(a["balance_minor"] for a in portfolio["accounts"])
        == portfolio["snapshot"]["total_minor"]
    )
    assert portfolio["snapshot"]["agent_funds_access"] is False
    op = env.bank.prepare(env.context, preparation(env))
    assert (
        post(
            env.client, f"/api/bank/operations/{op['id']}/decision", {"confirmed": True}
        ).status_code
        == 422
    )
    assert balances(env)[env.source] == 1286450


def test_report_aggregates_more_than_recent_thirty_entries(bank_env):
    env = bank_env
    timestamp = "2026-07-01T00:00:00+00:00"
    with env.store.transaction() as db:
        for _ in range(45):
            db.execute(
                "INSERT INTO entries VALUES (?,?,?,?,?,?)",
                (uuid4().hex, env.source, -1, "测试商户", "购物", timestamp),
            )
        db.execute("UPDATE accounts SET balance_minor=balance_minor-45 WHERE id=?", (env.source,))
    report = Reports(env.bank).bills(env.context, date(2026, 7, 1), date(2026, 7, 2))
    assert report["expense_minor"] == 45 and len(report["entry_ids"]) == 45


def test_reauthentication_failure_cannot_enable_grant(bank_env):
    env = bank_env
    values = {
        "request_id": uuid4().hex,
        "source_id": env.source,
        "currency": "CNY",
        "payee_ids": [env.payee],
        "allowed_operations": ["transfer"],
        "subscription_ids": [],
        "limit_minor": 50000,
        "single_minor": 30000,
        "minimum_minor": 0,
        "expires_at": env.now[0] + 3600,
        "password": "wrong",
    }
    for _ in range(5):
        assert post(env.client, "/api/bank/grants", values).status_code == 401
    values["password"] = PASSWORD
    assert post(env.client, "/api/bank/grants", values).status_code == 429
    assert env.bank.grants(env.context) == []
    assert env.client.get("/api/auth/me").status_code == 200
    env.now[0] += 301
    assert post(env.client, "/api/bank/grants", values).status_code == 200
