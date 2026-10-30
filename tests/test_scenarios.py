"""跨场景预算计划：纪念日/生日 + 模拟下单，不连接外部商户。"""

from uuid import uuid4

from test_application import env as shared_env
from test_application import login, post

__all__ = ["shared_env"]


def context(app, client):
    return app.state.auth.authenticate(client.cookies.get("ai_banking_session"))


def setup(app, client):
    login(client)
    ctx = context(app, client)
    accounts = app.state.store.accounts(ctx.user_id)
    payees = client.get("/api/bank/payees").json()["payees"]
    source = accounts[0]
    payee = next(item for item in payees if item["account_id"] != source["id"])
    return ctx, source, payee


def create(client, source, payee, **changes):
    values = {
        "request_id": uuid4().hex,
        "kind": "birthday",
        "title": "生日预算",
        "occasion_date": "2027-01-16",
        "budget_minor": 100000,
        "source_id": source["id"],
        "payee_id": payee["id"],
        **changes,
    }
    response = post(client, "/api/bank/scenarios", values)
    assert response.status_code == 200, response.text
    return response.json()["scenario"]


def test_create_and_list_scenario_plan_without_moving_or_reserving_funds(shared_env):
    app, client, _, _ = shared_env
    ctx, source, payee = setup(app, client)
    with app.state.store.transaction() as db:
        ledger = db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0]
    scenario = create(client, source, payee)
    assert scenario["status"] == "active"
    assert scenario["days_until"] == 1
    assert scenario["order_due"] is True
    assert scenario["budget_minor"] == 100000
    with app.state.store.transaction() as db:
        # A saved plan is not a balance reservation; only real operation
        # reservations and the requested amount affect available funds.
        app.state.bank._available(
            db,
            ctx.user_id,
            source["id"],
            source["balance_minor"] - 100000 + 1,
        )
    listing = client.get("/api/bank/scenarios").json()["scenarios"]
    assert any(item["scenario_id"] == scenario["scenario_id"] for item in listing)
    with app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == ledger


def test_multiple_scenario_budgets_are_validated_independently(shared_env):
    app, client, _, _ = shared_env
    _, source, payee = setup(app, client)
    budget = source["balance_minor"] * 2 // 3
    first = create(client, source, payee, budget_minor=budget, title="第一笔预算")
    second = create(client, source, payee, budget_minor=budget, title="第二笔预算")
    assert first["status"] == second["status"] == "active"
    assert (
        len(
            [
                item
                for item in client.get("/api/bank/scenarios").json()["scenarios"]
                if item["status"] == "active"
            ]
        )
        == 2
    )


def test_order_execution_rechecks_current_balance(shared_env):
    app, client, _, _ = shared_env
    _, source, payee = setup(app, client)
    budget = source["balance_minor"] * 2 // 3
    first = create(client, source, payee, budget_minor=budget, title="先执行")
    second = create(client, source, payee, budget_minor=budget, title="后执行")

    first_order = post(client, f"/api/bank/scenarios/{first['scenario_id']}/order", {})
    first_operation = first_order.json()["operation"]
    first_challenge = post(
        client, f"/api/bank/operations/{first_operation['id']}/challenge", {}
    ).json()
    approved = post(
        client,
        f"/api/bank/operations/{first_operation['id']}/decision",
        {
            "decision": "approve",
            "challenge": first_challenge["challenge"],
            "parameters_digest": first_challenge["summary"]["parameters_digest"],
        },
    )
    assert approved.status_code == 200 and approved.json()["state"] == "succeeded"

    second_order = post(client, f"/api/bank/scenarios/{second['scenario_id']}/order", {})
    second_operation = second_order.json()["operation"]
    second_challenge = post(
        client, f"/api/bank/operations/{second_operation['id']}/challenge", {}
    ).json()
    failed = post(
        client,
        f"/api/bank/operations/{second_operation['id']}/decision",
        {
            "decision": "approve",
            "challenge": second_challenge["challenge"],
            "parameters_digest": second_challenge["summary"]["parameters_digest"],
        },
    )
    assert failed.status_code == 409
    assert failed.json()["code"] == "INSUFFICIENT_BALANCE"
    persisted = client.get(f"/api/bank/operations/{second_operation['id']}")
    assert persisted.status_code == 200
    assert persisted.json()["state"] == "failed"
    assert persisted.json()["error_code"] == "INSUFFICIENT_BALANCE"


def test_order_scenario_creates_single_confirmed_transfer(shared_env):
    app, client, _, _ = shared_env
    ctx, source, payee = setup(app, client)
    scenario = create(client, source, payee)
    response = post(client, f"/api/bank/scenarios/{scenario['scenario_id']}/order", {})
    assert response.status_code == 200, response.text
    operation = response.json()["operation"]
    assert operation["state"] == "awaiting_confirmation"
    same = post(client, f"/api/bank/scenarios/{scenario['scenario_id']}/order", {})
    assert same.json()["operation"]["id"] == operation["id"]
    ordered = next(
        item
        for item in client.get("/api/bank/scenarios").json()["scenarios"]
        if item["scenario_id"] == scenario["scenario_id"]
    )
    assert ordered["operation_state"] == "awaiting_confirmation"

    challenge = post(client, f"/api/bank/operations/{operation['id']}/challenge", {}).json()
    decided = post(
        client,
        f"/api/bank/operations/{operation['id']}/decision",
        {
            "decision": "approve",
            "challenge": challenge["challenge"],
            "parameters_digest": challenge["summary"]["parameters_digest"],
        },
    )
    assert decided.status_code == 200 and decided.json()["state"] == "succeeded"
    with app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 2


def test_scenario_validation_and_cross_user_isolation(shared_env):
    app, client, _, _ = shared_env
    ctx, source, payee = setup(app, client)
    past = post(
        client,
        "/api/bank/scenarios",
        {
            "request_id": uuid4().hex,
            "kind": "birthday",
            "title": "过期",
            "occasion_date": "2020-01-01",
            "budget_minor": 100,
            "source_id": source["id"],
            "payee_id": payee["id"],
        },
    )
    assert past.status_code == 422
    scenario = create(client, source, payee, title="纪念日")
    client.cookies.clear()
    login(client, "bob")
    bob_ctx = context(app, client)
    bob_source = app.state.store.accounts(bob_ctx.user_id)[0]
    bob_payee = next(
        item
        for item in client.get("/api/bank/payees").json()["payees"]
        if item["account_id"] != bob_source["id"]
    )
    foreign = post(
        client,
        "/api/bank/scenarios",
        {
            "request_id": uuid4().hex,
            "kind": "birthday",
            "title": "越权",
            "occasion_date": "2027-01-16",
            "budget_minor": 100,
            "source_id": bob_source["id"],
            "payee_id": bob_payee["id"],
        },
    )
    assert foreign.status_code == 200
    assert (
        post(
            client,
            f"/api/bank/scenarios/{scenario['scenario_id']}/order",
            {},
        ).status_code
        == 404
    )


def test_cancel_and_past_budget_are_honest(shared_env):
    app, client, _, _ = shared_env
    ctx, source, payee = setup(app, client)
    scenario = create(client, source, payee)
    cancelled = post(client, f"/api/bank/scenarios/{scenario['scenario_id']}/cancel", {})
    assert cancelled.status_code == 200
    assert cancelled.json()["scenario"]["status"] == "cancelled"
    assert (
        post(
            client,
            f"/api/bank/scenarios/{scenario['scenario_id']}/order",
            {},
        ).status_code
        == 409
    )
