"""模拟卡片管理：申请、调额、冻结、挂失与归属隔离。"""

import re
from uuid import uuid4

from test_application import PASSWORD, login, post
from test_application import env as shared_env

from ai_banking.tracing import trace_scope

__all__ = ["shared_env"]


def cards(client):
    return client.get("/api/bank/cards").json()["cards"]


def apply_card(client, account_id, **changes):
    values = {
        "account_id": account_id,
        "kind": "credit",
        "daily_limit_minor": 123400,
        "password": PASSWORD,
        **changes,
    }
    response = post(client, "/api/bank/cards/apply", values)
    assert response.status_code == 200, response.text
    return response.json()["card"]


def test_base_cards_are_masked_and_do_not_move_funds(shared_env):
    app, client, _, _ = shared_env
    login(client)
    before = cards(client)
    assert len(before) >= 2
    for card in before:
        assert re.fullmatch(r"6222 \*{4} \*{4} \d{4}", card["masked_number"])
        assert card["status"] == "active"
        assert card["daily_limit_minor"] > 0
    with app.state.store.transaction() as db:
        ledger = db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0]
    assert ledger == 0 and cards(client) == before


def test_card_lifecycle_requires_password_and_preserves_funds(shared_env):
    app, client, _, _ = shared_env
    login(client)
    account = app.state.store.accounts(
        app.state.auth.authenticate(client.cookies.get("ai_banking_session")).user_id
    )[0]
    assert post(
        client,
        "/api/bank/cards/apply",
        {
            "account_id": account["id"],
            "kind": "credit",
            "daily_limit_minor": 100,
            "password": "wrong",
        },
    ).status_code in {401, 403}
    card = apply_card(client, account["id"])
    assert card["kind"] == "信用卡" and card["daily_limit_minor"] == 123400
    assert card["id"] in {item["id"] for item in cards(client)}

    updated = post(
        client,
        f"/api/bank/cards/{card['id']}/limit",
        {"daily_limit_minor": 250000, "password": PASSWORD},
    )
    assert updated.status_code == 200 and updated.json()["card"]["daily_limit_minor"] == 250000
    assert (
        post(
            client,
            f"/api/bank/cards/{card['id']}/status",
            {"status": "frozen", "password": PASSWORD},
        ).json()["card"]["status"]
        == "frozen"
    )
    assert (
        post(
            client,
            f"/api/bank/cards/{card['id']}/status",
            {"status": "active", "password": PASSWORD},
        ).json()["card"]["status"]
        == "active"
    )
    assert (
        post(
            client,
            f"/api/bank/cards/{card['id']}/status",
            {"status": "lost", "password": PASSWORD},
        ).json()["card"]["status"]
        == "lost"
    )
    assert (
        post(
            client,
            f"/api/bank/cards/{card['id']}/limit",
            {"daily_limit_minor": 300000, "password": PASSWORD},
        ).status_code
        == 409
    )
    with app.state.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 0


def test_card_is_isolated_and_agent_lists_dynamic_state(shared_env):
    app, client, _, _ = shared_env
    login(client)
    account = app.state.store.accounts(
        app.state.auth.authenticate(client.cookies.get("ai_banking_session")).user_id
    )[0]
    card = apply_card(client, account["id"])
    post(
        client,
        f"/api/bank/cards/{card['id']}/status",
        {"status": "frozen", "password": PASSWORD},
    )
    context = app.state.auth.authenticate(client.cookies.get("ai_banking_session"))
    with trace_scope(uuid4().hex, uuid4().hex):
        listed = app.state.agent.tool(context, "list_cards", {})
    assert any(item["id"] == card["id"] and item["status"] == "frozen" for item in listed["cards"])

    client.cookies.clear()
    login(client, "bob")
    assert (
        post(
            client,
            f"/api/bank/cards/{card['id']}/limit",
            {"daily_limit_minor": 300000, "password": PASSWORD},
        ).status_code
        == 404
    )
    bob_cards = cards(client)
    assert card["id"] not in {item["id"] for item in bob_cards}
