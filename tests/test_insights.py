from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from test_application import login, post
from test_banking import approve, balances, preparation
from test_banking import bank_env as shared_bank_fixture

from ai_banking.banking.reports import Reports
from ai_banking.banking.service import BankError
from ai_banking.banking.subscriptions import next_month

bank_env = shared_bank_fixture


def entry(env, amount, merchant="周期测试服务", category="服务", happened=None, account=None):
    identifier = uuid4().hex
    with env.store.transaction() as db:
        db.execute(
            "INSERT INTO entries VALUES (?,?,?,?,?,?)",
            (
                identifier,
                account or env.source,
                amount,
                merchant,
                category,
                happened or datetime.fromtimestamp(env.now[0], UTC).isoformat(),
            ),
        )
        db.execute(
            "UPDATE accounts SET balance_minor=balance_minor+? WHERE id=?",
            (amount, account or env.source),
        )
    return identifier


def recurring(env, gaps=(65, 35, 5), **kwargs):
    return [
        entry(
            env,
            -990,
            happened=datetime.fromtimestamp(env.now[0] - days * 86400, UTC).isoformat(),
            **kwargs,
        )
        for days in gaps
    ]


def confirmation(candidate):
    return {"evidence_digest": candidate["evidence_digest"], "acknowledged": True}


def confirm_url(candidate):
    return f"/api/bank/subscriptions/candidates/{candidate['candidate_id']}/confirm"


def test_report_comparison_refunds_transfers_and_evidence(bank_env):
    env = bank_env
    ids = [
        entry(env, amount, category=category, happened=timestamp)
        for amount, category, timestamp in [
            (-1000, "餐饮", "2026-07-01T02:00:00+00:00"),
            (-2000, "餐饮", "2026-07-01T03:00:00+00:00"),
            (-3000, "餐饮", "2026-07-01T04:00:00+00:00"),
            (-20000, "餐饮", "2026-07-02T02:00:00+00:00"),
            (500, "退款", "2026-07-02T03:00:00+00:00"),
            (-100000, "转账", "2026-07-02T04:00:00+00:00"),
        ]
    ]
    reports = Reports(env.bank)
    report = reports.bills(env.context, date(2026, 7, 2), date(2026, 7, 3))
    assert report["expense_minor"] == 20000
    assert report["net_expense_minor"] == 19500
    assert report["transfer_out_minor"] == 100000
    assert report["comparison"]["expense_delta_minor"] == 14000
    anomaly = report["possible_anomalies"][0]
    assert anomaly["entry_id"] == ids[3] and anomaly["baseline_minor"] == 2000
    assert anomaly["baseline_count"] == 3
    evidence = reports.entries(env.context, date(2026, 7, 2), date(2026, 7, 3), entry_id=ids[3])
    assert [row["id"] for row in evidence["entries"]] == [ids[3]]
    assert evidence["entries"][0]["amount_minor"] == -20000


def test_evidence_pages_are_complete_scoped_and_validate_dates(bank_env):
    env = bank_env
    ids = {entry(env, -10, happened=f"2026-07-01T01:{minute:02d}:00+00:00") for minute in range(45)}
    url = "/api/bank/reports/entries?start=2026-07-01&end=2026-07-02&limit=20"
    first = env.client.get(url).json()
    second = env.client.get(url + "&offset=20").json()
    third = env.client.get(url + "&offset=40").json()
    assert first["total"] == 45 and third["next_offset"] is None
    assert {r["id"] for page in [first, second, third] for r in page["entries"]} == ids
    assert env.client.get(url + "&limit=51").status_code == 422
    assert env.client.get("/api/bank/reports?start=2026-07-02&end=2026-07-01").status_code == 422
    assert env.client.get("/api/bank/reports?start=2025-01-01&end=2026-02-01").status_code == 422
    post(env.client, "/api/auth/logout", {})
    login(env.client, "bob")
    assert env.client.get(url).json()["total"] == 0


def test_candidates_explain_evidence_without_writing(bank_env):
    env = bank_env
    ids = recurring(env)
    before = balances(env)
    candidates = Reports(env.bank).subscriptions(env.context)["inferred_candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["charge_count"] == 3 and candidate["interval_days"] == [30, 30]
    assert [row["id"] for row in candidate["evidence"]] == ids
    assert candidate["status"] == "inferred"
    assert Reports(env.bank).candidates(env.context) == candidates
    assert balances(env) == before
    with env.store.transaction() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM bank_subscriptions WHERE source='inferred_confirmed'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "gaps,category",
    [((65, 5), "服务"), ((10, 8, 5), "服务"), ((65, 35, 5), "转账"), ((120, 90, 60), "服务")],
)
def test_irregular_sparse_old_or_transfer_rows_are_not_candidates(bank_env, gaps, category):
    recurring(bank_env, gaps=gaps, category=category)
    assert Reports(bank_env.bank).candidates(bank_env.context) == []


def test_different_amounts_and_accounts_do_not_form_subscription(bank_env):
    env = bank_env
    recurring(env, gaps=(65, 35))
    entry(env, -1000, happened=datetime.fromtimestamp(env.now[0] - 5 * 86400, UTC).isoformat())
    recurring(env, gaps=(65, 35), merchant="分账户服务")
    recurring(env, gaps=(5,), merchant="分账户服务", account=env.target)
    assert Reports(env.bank).candidates(env.context) == []


def test_registered_or_cancelled_merchant_is_not_suggested_again(bank_env):
    env = bank_env
    recurring(env, merchant="云音乐月度会员")
    with env.store.transaction() as db:
        db.execute(
            "UPDATE bank_subscriptions SET status='cancelled' WHERE owner_id=?",
            (env.context.user_id,),
        )
    assert Reports(env.bank).candidates(env.context) == []


def test_confirm_is_explicit_idempotent_and_does_not_grant_or_move_funds(bank_env):
    env = bank_env
    recurring(env, merchant="<img src=x onerror=alert(1)>")
    candidate = Reports(env.bank).candidates(env.context)[0]
    before = balances(env)
    url, body = confirm_url(candidate), confirmation(candidate)
    assert post(env.client, url, {**body, "acknowledged": False}).status_code == 422
    assert post(env.client, url, {**body, "acknowledged": 1}).status_code == 422
    assert post(env.client, url, {**body, "owner_id": env.context.user_id}).status_code == 422
    assert env.client.post(url, json=body).status_code == 403
    assert post(env.client, url, body, origin="http://evil.test").status_code == 403
    first = post(env.client, url, body)
    assert first.status_code == 200
    subscription = first.json()["subscription"]
    assert subscription["source"] == "inferred_confirmed" and subscription["status"] == "active"
    again = post(env.client, url, body).json()
    assert again["replayed"] and again["subscription"]["id"] == subscription["id"]
    assert balances(env) == before
    assert env.bank.grants(env.context) == []
    with env.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM bank_ledger").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT COUNT(*) FROM bank_events WHERE event='subscription_registered'"
            ).fetchone()[0]
            == 1
        )
        db.execute(
            "UPDATE bank_subscriptions SET status='cancelled' WHERE id=?", (subscription["id"],)
        )
    assert post(env.client, url, body).json()["subscription"]["status"] == "cancelled"


def test_candidate_confirmation_rejects_foreign_and_changed_evidence(bank_env):
    env = bank_env
    recurring(env)
    candidate = Reports(env.bank).candidates(env.context)[0]
    url, body = confirm_url(candidate), confirmation(candidate)
    post(env.client, "/api/auth/logout", {})
    login(env.client, "bob")
    assert post(env.client, url, body).status_code == 409
    assert env.client.get("/api/bank/subscriptions").json()["inferred_candidates"] == []
    post(env.client, "/api/auth/logout", {})
    login(env.client)
    entry(env, -990)
    assert post(env.client, url, body).json()["code"] == "SUBSCRIPTION_EVIDENCE_CHANGED"
    with env.store.transaction() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM bank_subscriptions WHERE source='inferred_confirmed'"
            ).fetchone()[0]
            == 0
        )


def test_concurrent_confirm_only_registers_once(bank_env):
    env = bank_env
    recurring(env)
    reports = Reports(env.bank)
    candidate = reports.candidates(env.context)[0]

    def confirm(_):
        return reports.confirm_candidate(
            env.context, candidate["candidate_id"], candidate["evidence_digest"]
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, range(2)))
    assert len({r["subscription"]["id"] for r in results}) == 1
    assert sum(r["replayed"] for r in results) == 1


def test_candidate_cannot_be_cancelled_before_registration(bank_env):
    env = bank_env
    recurring(env)
    candidate = Reports(env.bank).candidates(env.context)[0]
    values = preparation(env)
    values.pop("amount_minor")
    values.pop("payee_id")
    values["subscription_id"] = candidate["candidate_id"]
    with pytest.raises(BankError) as error:
        env.bank.prepare(env.context, values, "cancel_subscription")
    assert error.value.code == "RESOURCE_NOT_FOUND"


def test_estimated_next_month_handles_month_end():
    assert next_month(datetime(2028, 1, 31, tzinfo=UTC)).date() == date(2028, 2, 29)
    assert next_month(datetime(2026, 12, 31, tzinfo=UTC)).date() == date(2027, 1, 31)


def test_still_periodic_but_changed_evidence_needs_new_confirmation(bank_env):
    env = bank_env
    identifiers = recurring(env)
    reports = Reports(env.bank)
    candidate = reports.candidates(env.context)[0]
    with env.store.transaction() as db:
        original = db.execute(
            "SELECT happened_at FROM entries WHERE id=?", (identifiers[0],)
        ).fetchone()[0]
        corrected = (datetime.fromisoformat(original) + timedelta(seconds=1)).isoformat()
        db.execute("UPDATE entries SET happened_at=? WHERE id=?", (corrected, identifiers[0]))
    refreshed = reports.candidates(env.context)[0]
    assert refreshed["candidate_id"] == candidate["candidate_id"]
    assert refreshed["evidence_digest"] != candidate["evidence_digest"]
    assert post(env.client, confirm_url(candidate), confirmation(candidate)).status_code == 409
    assert post(env.client, confirm_url(refreshed), confirmation(refreshed)).status_code == 200


def test_confirmed_candidate_uses_existing_cancel_approval_without_refund(bank_env):
    env = bank_env
    recurring(env)
    reports = Reports(env.bank)
    candidate = reports.candidates(env.context)[0]
    response = post(env.client, confirm_url(candidate), confirmation(candidate)).json()
    subscription = response["subscription"]
    before = balances(env)
    values = preparation(env)
    values.pop("amount_minor")
    values.pop("payee_id")
    values["subscription_id"] = subscription["id"]
    operation = env.bank.prepare(env.context, values, "cancel_subscription")
    assert operation["state"] == "awaiting_confirmation"

    def status():
        return next(
            s["status"]
            for s in reports.subscriptions(env.context)["subscriptions"]
            if s["id"] == subscription["id"]
        )

    assert status() == "active"
    approve(env, operation["id"])
    assert status() == "cancelled"
    assert balances(env) == before


def test_agent_evidence_contract_is_read_only_and_strict(bank_env):
    env = bank_env
    identifier = entry(env, -1234, happened="2026-07-01T04:00:00+00:00")
    arguments = {
        "start": "2026-07-01",
        "end": "2026-07-02",
        "category": None,
        "entry_id": identifier,
        "offset": 0,
        "limit": 20,
    }
    agent = env.app.state.agent
    assert (
        agent.dispatch(env.context, "get_billing_entries", arguments)["entries"][0]["id"]
        == identifier
    )
    assert (
        agent.dispatch(env.context, "get_billing_entries", {**arguments, "owner_id": "bob"})[
            "error"
        ]
        == "TOOL_ARGUMENTS_REJECTED"
    )
    assert (
        agent.dispatch(env.context, "confirm_subscription", {})["error"]
        == "TOOL_ARGUMENTS_REJECTED"
    )
