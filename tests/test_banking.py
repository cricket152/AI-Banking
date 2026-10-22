import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_application import ORIGIN, PASSWORD, login, post

from ai_banking.app import create_app
from ai_banking.banking.cli import upgrade
from ai_banking.banking.reports import Reports
from ai_banking.banking.service import Bank, BankError
from ai_banking.config import Settings


@pytest.fixture
def bank_env(tmp_path):
    now = [1800000000.0]
    settings = Settings(database=tmp_path / "bank.sqlite3", local_http=True, trace_enabled=False)
    app = create_app(settings, lambda: now[0])
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.auth.create_user("alice", PASSWORD)
        app.state.auth.create_user("bob", PASSWORD)
        login(client)
        context = app.state.auth.authenticate(client.cookies.get("ai_banking_session"))
        accounts = app.state.store.accounts(context.user_id)
        source = next(a for a in accounts if a["kind"] == "checking")["id"]
        target = next(a for a in accounts if a["kind"] == "savings")["id"]
        payee = next(p for p in app.state.bank.payees(context) if p["account_id"] == target)["id"]
        yield SimpleNamespace(
            app=app,
            client=client,
            bank=app.state.bank,
            store=app.state.store,
            context=context,
            now=now,
            settings=settings,
            source=source,
            target=target,
            payee=payee,
        )


def preparation(env, amount=12345, **changes):
    task_id = env.bank.task(env.context, uuid4().hex)["id"]
    values = {
        "task_id": task_id,
        "step_key": "transfer_1",
        "source_id": env.source,
        "payee_id": env.payee,
        "amount_minor": amount,
        "currency": "CNY",
        "mode": "HUMAN_APPROVAL",
        "grant_id": None,
        "confirmation_seconds": 300,
    }
    return {**values, **changes}


def grant(env, **changes):
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
        "password": PASSWORD,
        **changes,
    }
    response = post(env.client, "/api/bank/grants", values)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def approve(env, operation_id):
    challenge = env.bank.challenge(env.context, operation_id)
    return env.bank.decide(
        env.context,
        operation_id,
        "approve",
        challenge["challenge"],
        challenge["summary"]["parameters_digest"],
    )


def balances(env):
    return {row["id"]: row["balance_minor"] for row in env.store.accounts(env.context.user_id)}


def test_manual_transfer_requires_real_bound_challenge_and_balances_ledger(bank_env):
    env = bank_env
    before = balances(env)
    op = env.bank.prepare(env.context, preparation(env))
    assert op["state"] == "awaiting_confirmation"
    assert balances(env) == before
    with pytest.raises(BankError):
        env.bank.execute(env.context, op["id"])
    with pytest.raises(BankError):
        env.bank.decide(env.context, op["id"], "approve", "fake-proof", op["parameters_digest"])
    assert approve(env, op["id"])["state"] == "succeeded"
    after = balances(env)
    assert after[env.source] == before[env.source] - 12345
    assert after[env.target] == before[env.target] + 12345
    assert sum(after.values()) == sum(before.values())
    with env.store.transaction() as db:
        rows = db.execute(
            "SELECT amount_minor FROM bank_ledger WHERE operation_id=?", (op["id"],)
        ).fetchall()
        assert len(rows) == 2 and sum(row[0] for row in rows) == 0
    assert env.bank.execute(env.context, op["id"])["state"] == "succeeded"
    assert balances(env) == after


@pytest.mark.parametrize("amount", [0, -1, 1.5, True, 10**12 + 1])
def test_internal_kernel_rejects_invalid_amounts(bank_env, amount):
    env = bank_env
    before = balances(env)
    with pytest.raises(BankError):
        env.bank.prepare(env.context, preparation(env, amount))
    assert balances(env) == before


def test_task_step_idempotency_and_parameter_binding(bank_env):
    env = bank_env
    values = preparation(env)
    with ThreadPoolExecutor(max_workers=6) as pool:
        ops = list(pool.map(lambda _: env.bank.prepare(env.context, values), range(12)))
    assert len({op["id"] for op in ops}) == 1
    with pytest.raises(BankError) as error:
        env.bank.prepare(env.context, {**values, "amount_minor": 888})
    assert error.value.code == "STEP_PARAMETERS_CONFLICT"
    task = env.bank.checkpoint(env.context, values["task_id"])
    assert len(task["steps"]) == 1 and task["needs_attention"]


@pytest.mark.parametrize("decision", ["reject", "expired", "maybe"])
def test_no_answer_rejection_ambiguous_and_expired_do_not_pay(bank_env, decision):
    env = bank_env
    before = balances(env)
    op = env.bank.prepare(env.context, preparation(env))
    proof = env.bank.challenge(env.context, op["id"])
    if decision == "expired":
        env.now[0] += 300
        assert env.bank.operation(env.context, op["id"])["state"] == "expired"
    elif decision == "maybe":
        with pytest.raises(BankError):
            env.bank.decide(
                env.context, op["id"], "maybe", proof["challenge"], op["parameters_digest"]
            )
        assert env.bank.operation(env.context, op["id"])["state"] == "awaiting_confirmation"
    else:
        assert (
            env.bank.decide(
                env.context, op["id"], "reject", proof["challenge"], op["parameters_digest"]
            )["state"]
            == "rejected"
        )
    assert balances(env) == before


def test_concurrent_balance_contention_never_overdraws(bank_env):
    env = bank_env
    ops = [env.bank.prepare(env.context, preparation(env, 800000)) for _ in range(2)]

    def run(op):
        try:
            return approve(env, op["id"])["state"]
        except BankError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ops))
    assert results.count("succeeded") == 1
    assert "INSUFFICIENT_BALANCE" in results
    assert balances(env)[env.source] == 1286450 - 800000


def test_preauthorization_requires_password_and_has_no_default(bank_env):
    env = bank_env
    assert env.bank.grants(env.context) == []
    assert post(env.client, "/api/bank/grants", {"password": PASSWORD}).status_code == 422
    grant_id = grant(env)
    assert env.bank.grants(env.context)[0]["id"] == grant_id
    assert PASSWORD not in str(env.bank.grants(env.context))


def test_reserved_budget_accumulates_and_receipts_do_not_replenish_it(bank_env):
    env = bank_env
    grant_id = grant(env)
    one = env.bank.prepare(
        env.context, preparation(env, 30000, mode="PREAUTHORIZED", grant_id=grant_id)
    )
    two_values = preparation(env, 20000, mode="PREAUTHORIZED", grant_id=grant_id)
    two = env.bank.prepare(env.context, two_values)
    assert env.bank.grants(env.context)[0]["reserved_minor"] == 50000
    with pytest.raises(BankError) as error:
        env.bank.prepare(env.context, preparation(env, 1, mode="PREAUTHORIZED", grant_id=grant_id))
    assert error.value.code == "GRANT_EXHAUSTED"
    assert env.bank.execute(env.context, one["id"])["state"] == "succeeded"
    assert env.bank.execute(env.context, two["id"])["state"] == "succeeded"
    policy = env.bank.grants(env.context)[0]
    assert policy["spent_minor"] == 50000 and policy["reserved_minor"] == 0
    assert policy["remaining_minor"] == 0
    # 自己账户之间转账并未增加总资产，支出预算仍消耗。
    assert sum(balances(env).values()) == 4966450


def test_concurrent_budget_reservations_cannot_exceed_limit(bank_env):
    env = bank_env
    grant_id = grant(env, limit_minor=30000, single_minor=30000)

    def reserve(_):
        try:
            return env.bank.prepare(
                env.context, preparation(env, 20000, mode="PREAUTHORIZED", grant_id=grant_id)
            )["state"]
        except BankError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(4)))
    assert results.count("authorized") == 1
    assert results.count("GRANT_EXHAUSTED") == 3
    assert env.bank.grants(env.context)[0]["reserved_minor"] == 20000


@pytest.mark.parametrize(
    "change,code",
    [
        ({"amount_minor": 30001}, "SINGLE_LIMIT_EXCEEDED"),
        ({"source_id": "wrong"}, "RESOURCE_NOT_FOUND"),
    ],
)
def test_policy_rejects_out_of_scope_requests(bank_env, change, code):
    env = bank_env
    grant_id = grant(env)
    values = preparation(env, mode="PREAUTHORIZED", grant_id=grant_id)
    with pytest.raises(BankError) as error:
        env.bank.prepare(env.context, {**values, **change})
    assert error.value.code == code


def test_minimum_balance_expiry_and_revoke_release_only_unexecuted_reservations(bank_env):
    env = bank_env
    grant_id = grant(env, minimum_minor=1280000)
    with pytest.raises(BankError) as error:
        env.bank.prepare(
            env.context, preparation(env, 10000, mode="PREAUTHORIZED", grant_id=grant_id)
        )
    assert error.value.code == "INSUFFICIENT_BALANCE"
    op = env.bank.prepare(
        env.context, preparation(env, 1000, mode="PREAUTHORIZED", grant_id=grant_id)
    )
    env.bank.revoke(env.context, grant_id)
    assert env.bank.operation(env.context, op["id"])["state"] == "expired"
    assert env.bank.grants(env.context)[0]["reserved_minor"] == 0
    assert balances(env)[env.source] == 1286450


@pytest.mark.parametrize("point", ["before_transaction", "after_debit", "before_commit"])
def test_fault_rollback_unknown_result_preserves_reservation_until_reconciled(bank_env, point):
    env = bank_env
    grant_id = grant(env)
    op = env.bank.prepare(env.context, preparation(env, mode="PREAUTHORIZED", grant_id=grant_id))

    def fail(current):
        if current == point:
            raise RuntimeError("injected test-only failure")

    env.bank.fault_hook = fail
    with pytest.raises(BankError) as error:
        env.bank.execute(env.context, op["id"])
    assert error.value.code == "OUTCOME_UNKNOWN"
    assert env.bank.operation(env.context, op["id"])["state"] == "outcome_unknown"
    assert balances(env)[env.source] == 1286450
    assert env.bank.grants(env.context)[0]["reserved_minor"] == 12345
    with env.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 0
    with pytest.raises(BankError):
        env.bank.prepare(
            env.context, preparation(env, 100, mode="PREAUTHORIZED", grant_id=grant_id)
        )
    resolved = env.bank.reconcile(env.context, op["id"])
    assert resolved["state"] == "failed" and resolved["error_code"] == "RECONCILED_NOT_EXECUTED"
    assert env.bank.grants(env.context)[0]["reserved_minor"] == 0


def test_lost_response_after_commit_queries_original_operation_and_does_not_pay_twice(bank_env):
    env = bank_env
    op = env.bank.prepare(env.context, preparation(env))

    def lost(point):
        if point == "after_commit":
            raise TimeoutError("response lost")

    env.bank.fault_hook = lost
    with pytest.raises(BankError) as error:
        approve(env, op["id"])
    assert error.value.code == "RESULT_UNAVAILABLE"
    assert env.bank.operation(env.context, op["id"])["state"] == "succeeded"
    env.bank.execute(env.context, op["id"])
    assert balances(env)[env.source] == 1286450 - 12345
    with env.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 2


def test_crash_restart_checkpoints_and_unknown_state_are_persisted(bank_env):
    env = bank_env
    values = preparation(env)
    op = env.bank.prepare(env.context, values)

    class Crash(BaseException):
        pass

    def crash(point):
        if point == "before_transaction":
            raise Crash()

    env.bank.fault_hook = crash
    with pytest.raises(Crash):
        approve(env, op["id"])
    restarted = Bank(env.store, env.app.state.auth)
    restarted.recover_startup()
    assert restarted.operation(env.context, op["id"])["state"] == "outcome_unknown"
    assert restarted.checkpoint(env.context, values["task_id"])["steps"][0]["id"] == op["id"]
    assert restarted.prepare(env.context, values)["id"] == op["id"]
    assert restarted.reconcile(env.context, op["id"])["state"] == "failed"


def test_subscriptions_cancel_is_explicit_idempotent_and_does_not_refund(bank_env):
    env = bank_env
    subscription = Reports(env.bank).subscriptions(env.context)["subscriptions"][0]
    values = preparation(env)
    values.pop("payee_id")
    values.pop("amount_minor")
    values["subscription_id"] = subscription["id"]
    op = env.bank.prepare(env.context, values, "cancel_subscription")
    assert approve(env, op["id"])["state"] == "succeeded"
    assert env.bank.prepare(env.context, values, "cancel_subscription")["id"] == op["id"]
    assert Reports(env.bank).subscriptions(env.context)["subscriptions"][0]["status"] == "cancelled"
    assert sum(balances(env).values()) == 4966450
    assert env.bank.execute(env.context, op["id"])["state"] == "succeeded"


def test_reports_use_complete_range_and_exclude_transfers_from_consumption(bank_env):
    env = bank_env
    op = env.bank.prepare(env.context, preparation(env))
    approve(env, op["id"])
    today = datetime.fromtimestamp(env.now[0], UTC).date()
    report = Reports(env.bank).bills(
        env.context, today - timedelta(days=10), today + timedelta(days=1)
    )
    assert report["expense_minor"] == 19350 and report["income_minor"] == 1200000
    assert report["subscription_expense_minor"] == 4000
    assert report["transfer_in_minor"] == report["transfer_out_minor"] == 12345
    assert sum(report["by_category"].values()) == 19350
    assert len(report["entry_ids"]) == 9
    with pytest.raises(BankError):
        Reports(env.bank).bills(env.context, date(2026, 1, 1), date(2026, 1, 1))


def test_cross_user_operations_grants_tasks_and_reports_are_isolated(bank_env):
    env = bank_env
    values = preparation(env)
    op = env.bank.prepare(env.context, values)
    grant_id = grant(env)
    post(env.client, "/api/auth/logout", {})
    login(env.client, "bob")
    for path in [f"/api/bank/operations/{op['id']}", f"/api/bank/tasks/{op['task_id']}"]:
        assert env.client.get(path).status_code == 404
    assert post(env.client, f"/api/bank/grants/{grant_id}/revoke", {}).status_code == 404
    assert post(env.client, f"/api/bank/operations/{op['id']}/execute", {}).status_code == 404
    assert post(env.client, "/api/bank/transfers/prepare", values).status_code == 404
    assert "owner_id" not in env.client.get("/api/bank/grants").text


def test_bank_api_strict_inputs_csrf_and_audit_never_contain_password(bank_env):
    env = bank_env
    values = preparation(env)
    assert (
        post(env.client, "/api/bank/transfers/prepare", {**values, "confirmed": True}).status_code
        == 422
    )
    assert (
        post(
            env.client, "/api/bank/transfers/prepare", {**values, "amount_minor": True}
        ).status_code
        == 422
    )
    assert env.client.post("/api/bank/transfers/prepare", json=values).status_code == 403
    response = post(env.client, "/api/bank/transfers/prepare", values)
    assert response.status_code == 200
    operation_id = response.json()["id"]
    proof = post(env.client, f"/api/bank/operations/{operation_id}/challenge", {}).json()
    body = {
        "decision": "approve",
        "challenge": proof["challenge"],
        "parameters_digest": proof["summary"]["parameters_digest"],
    }
    response = post(env.client, f"/api/bank/operations/{operation_id}/decision", body)
    assert response.status_code == 200 and response.json()["state"] == "succeeded"
    events = env.client.get("/api/bank/events").json()
    assert events["next_after"] > 0
    assert PASSWORD not in str(events) and proof["challenge"] not in str(events)


def test_upgrade_requires_explicit_command_preserves_old_rows_and_makes_backup(
    tmp_path, monkeypatch
):
    settings = Settings(database=tmp_path / "legacy.sqlite3", local_http=True, trace_enabled=False)
    with monkeypatch.context() as patch:
        patch.setattr("ai_banking.store.create_schema", lambda *args: None)
        app = create_app(settings)
        with TestClient(app, base_url=ORIGIN) as client:
            app.state.auth.create_user("alice", PASSWORD)
            login(client)
            before = client.get("/api/accounts").json()["accounts"]
            assert client.get("/api/bank/payees").status_code == 503
    with sqlite3.connect(settings.database) as db:
        original = {
            table: db.execute(f"SELECT * FROM {table}").fetchall()
            for table in ["users", "accounts", "entries", "sessions"]
        }
    backup = upgrade(app.state.store)
    assert backup.is_file()
    with sqlite3.connect(settings.database) as db:
        for table, rows in original.items():
            assert db.execute(f"SELECT * FROM {table}").fetchall() == rows
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        login(client)
        assert client.get("/api/accounts").json()["accounts"] == before
        assert len(client.get("/api/bank/payees").json()["payees"]) == 2
    assert upgrade(app.state.store) is None
