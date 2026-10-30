"""理财目录与卡片信息的模拟只读能力测试。"""

import json
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_application import env as shared_env
from test_application import login

from ai_banking.agent import TOOLS
from ai_banking.catalog import cards as card_list
from ai_banking.catalog import wealth_products
from ai_banking.tracing import trace_scope

__all__ = ["shared_env"]


@pytest.fixture
def catalog_env(request):
    app, client, _now, _settings = request.getfixturevalue("shared_env")
    login(client)
    context = app.state.auth.authenticate(client.cookies.get("ai_banking_session"))
    return SimpleNamespace(app=app, client=client, context=context)


def call(env, name, arguments=None):
    with trace_scope(uuid4().hex, uuid4().hex):
        return env.app.state.agent.tool(env.context, name, arguments or {})


def test_read_only_tools_are_appended_in_fixed_order():
    names = [tool["name"] for tool in TOOLS]
    assert names[8:10] == ["list_cards", "list_wealth_products"]
    assert names[10:] == ["get_billing_entries", "find_payees"]
    assert not any("wealth" in name and name.startswith("prepare") for name in names)
    assert not any(name in {"approve", "execute", "create_grant"} for name in names)


def test_cards_are_masked_deterministic_and_owned(catalog_env):
    env = catalog_env
    first = call(env, "list_cards")
    cards = first["cards"]
    assert cards
    assert not re.search(r"\d{16}", json.dumps(cards, ensure_ascii=False))
    for card in cards:
        assert re.fullmatch(r"6222 \*{4} \*{4} \d{4}", card["masked_number"])
        assert card["status"] == "active"
        assert card["daily_limit_minor"] > 0
        assert card["account_name"]
    assert call(env, "list_cards") == first
    owned = {account["id"] for account in env.app.state.store.accounts(env.context.user_id)}
    assert {card["account_id"] for card in cards} == owned


def test_cards_are_isolated_per_user(catalog_env):
    env = catalog_env
    with env.app.state.store.transaction() as db:
        bob_id = db.execute("SELECT id FROM users WHERE username = 'bob'").fetchone()["id"]
    alice_cards = card_list(env.app.state.store, env.context.user_id)["cards"]
    bob_cards = card_list(env.app.state.store, bob_id)["cards"]
    assert {card["id"] for card in alice_cards}.isdisjoint({card["id"] for card in bob_cards})
    bob_accounts = {account["id"] for account in env.app.state.store.accounts(bob_id)}
    assert {card["account_id"] for card in bob_cards} == bob_accounts


def test_wealth_catalog_is_static_and_explicitly_query_only(catalog_env):
    products = wealth_products()
    ids = [product["id"] for product in products["products"]]
    assert len(ids) == len(set(ids)) >= 3
    for product in products["products"]:
        assert product["risk_level"] in {"R1", "R2", "R3"}
        assert product["min_amount_minor"] > 0
        assert "模拟" in product["yield_hint"]
    assert "不支持申购" in products["note"]
    assert call(catalog_env, "list_wealth_products") == products


def test_read_only_tools_do_not_change_funds_or_operations(catalog_env):
    env = catalog_env
    before = env.app.state.store.accounts(env.context.user_id)
    with env.app.state.store.transaction() as db:
        operations_before = db.execute("SELECT COUNT(*) FROM bank_operations").fetchone()[0]
    call(env, "list_cards")
    call(env, "list_wealth_products")
    after = env.app.state.store.accounts(env.context.user_id)
    with env.app.state.store.transaction() as db:
        operations_after = db.execute("SELECT COUNT(*) FROM bank_operations").fetchone()[0]
    assert before == after
    assert operations_before == operations_after


def test_unimplemented_wealth_write_tools_are_rejected(catalog_env):
    for name in ("prepare_wealth_purchase", "redeem_wealth", "report_card_lost"):
        with trace_scope(uuid4().hex, uuid4().hex):
            assert catalog_env.app.state.agent.tool(catalog_env.context, name, {}) == {
                "error": "TOOL_ARGUMENTS_REJECTED"
            }
