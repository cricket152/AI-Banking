"""模拟理财申购/赎回：受人工确认、余额与持仓一致、无真实产品。"""

from test_application import env as shared_env
from test_application import login, post

__all__ = ["shared_env"]


def setup(app, client):
    login(client)
    context = app.state.auth.authenticate(client.cookies.get("ai_banking_session"))
    accounts = app.state.store.accounts(context.user_id)
    return context, accounts[0]


def order(client, source, product_id, action, amount):
    response = post(
        client,
        "/api/bank/wealth/orders",
        {
            "product_id": product_id,
            "action": action,
            "source_id": source["id"],
            "amount_minor": amount,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["operation"]


def approve(client, operation):
    challenge = post(client, f"/api/bank/operations/{operation['id']}/challenge", {}).json()
    return post(
        client,
        f"/api/bank/operations/{operation['id']}/decision",
        {
            "decision": "approve",
            "challenge": challenge["challenge"],
            "parameters_digest": challenge["summary"]["parameters_digest"],
        },
    )


def test_wealth_purchase_and_redeem_require_confirmation_and_hold_funds(shared_env):
    app, client, _, _ = shared_env
    context, source = setup(app, client)
    wealth = client.get("/api/bank/wealth").json()
    product = wealth["products"][0]
    assert wealth["holdings"] == []
    before = app.state.store.accounts(context.user_id)[0]["balance_minor"]

    operation = order(client, source, product["id"], "purchase", 10000)
    assert operation["state"] == "awaiting_confirmation"
    challenge = post(client, f"/api/bank/operations/{operation['id']}/challenge", {}).json()
    assert challenge["summary"]["wealth_product"]["id"] == product["id"]
    assert challenge["summary"]["holding_before_minor"] == 0
    response = approve(client, operation)
    assert response.status_code == 200 and response.json()["state"] == "succeeded"

    after_buy = app.state.store.accounts(context.user_id)[0]["balance_minor"]
    assert after_buy == before - 10000
    holdings = client.get("/api/bank/wealth").json()["holdings"]
    assert holdings[0]["product"]["id"] == product["id"]
    assert holdings[0]["amount_minor"] == 10000

    redeem = order(client, source, product["id"], "redeem", 10000)
    assert approve(client, redeem).json()["state"] == "succeeded"
    after_sell = app.state.store.accounts(context.user_id)[0]["balance_minor"]
    assert after_sell == before
    assert client.get("/api/bank/wealth").json()["holdings"] == []


def test_wealth_rejects_insufficient_holding_and_minimum(shared_env):
    app, client, _, _ = shared_env
    context, source = setup(app, client)
    product = client.get("/api/bank/wealth").json()["products"][0]
    invalid = post(
        client,
        "/api/bank/wealth/orders",
        {
            "product_id": product["id"],
            "action": "purchase",
            "source_id": source["id"],
            "amount_minor": 1,
        },
    )
    assert invalid.status_code == 422
    operation = order(client, source, product["id"], "redeem", 100)
    assert approve(client, operation).status_code in {409, 422}


def test_wealth_operations_are_isolated(shared_env):
    app, client, _, _ = shared_env
    context, source = setup(app, client)
    product = client.get("/api/bank/wealth").json()["products"][0]
    operation = order(client, source, product["id"], "purchase", 10000)
    client.cookies.clear()
    login(client, "bob")
    response = post(client, f"/api/bank/operations/{operation['id']}/challenge", {})
    assert response.status_code == 404
    assert client.get("/api/bank/wealth").json()["holdings"] == []
