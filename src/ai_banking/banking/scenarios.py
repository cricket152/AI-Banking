"""跨场景预算计划：纪念日/生日 + 预算 + 模拟下单（待人工确认的转账）。"""

import json
from datetime import date, datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from ai_banking.banking.service import MAX_MINOR, BankError, fingerprint

KINDS = {"birthday": "生日计划", "anniversary": "纪念日计划", "custom": "自定义场景"}
NOTE = "模拟跨场景计划：不连接外部商户、不定时扣款；下单只准备一笔待你确认的模拟转账。"
SHANGHAI = timezone(timedelta(hours=8))


def _today(seconds):
    return datetime.fromtimestamp(seconds, SHANGHAI).date()


def _public(detail, seconds):
    result = {key: value for key, value in detail.items() if key != "request_digest"}
    if result.get("status") == "active":
        occasion = date.fromisoformat(result["occasion_date"])
        days = (occasion - _today(seconds)).days
        result["days_until"] = days
        result["order_due"] = 0 <= days <= 2
        if days < 0:
            result["status"] = "expired"
    return result


def _saved(bank, context, db):
    plans = {}
    for row in db.execute(
        "SELECT event,detail FROM bank_events WHERE owner_id=? AND event IN "
        "('scenario_plan_created','scenario_ordered','scenario_cancelled') ORDER BY seq",
        (context.user_id,),
    ):
        detail = json.loads(row["detail"])
        scenario_id = detail["scenario_id"]
        if row["event"] == "scenario_plan_created":
            plans[scenario_id] = {
                **detail,
                "status": "active",
                "operation_id": None,
                "request_digest": detail.get("request_digest"),
            }
        elif scenario_id in plans:
            if row["event"] == "scenario_ordered":
                plans[scenario_id]["status"] = "ordered"
                plans[scenario_id]["operation_id"] = detail["operation_id"]
            else:
                plans[scenario_id]["status"] = "cancelled"
    return [
        _public(plan, bank.store.clock())
        for plan in sorted(plans.values(), key=lambda item: item.get("created_at", 0), reverse=True)
    ]


def list_scenarios(bank, context):
    with bank.store.transaction() as db:
        bank._guard(db, context)
        return {"scenarios": _saved(bank, context, db), "note": NOTE}


def create_scenario(bank, context, values):
    kind = values["kind"]
    if kind not in KINDS:
        raise BankError("INVALID_SCENARIO_KIND", 422)
    title = values["title"].strip()
    if not 1 <= len(title) <= 40:
        raise BankError("INVALID_SCENARIO_TITLE", 422)
    try:
        occasion = date.fromisoformat(values["occasion_date"])
    except (TypeError, ValueError) as error:
        raise BankError("INVALID_SCENARIO_DATE", 422) from error
    amount = values["budget_minor"]
    if type(amount) is not int or not 1 <= amount <= MAX_MINOR:
        raise BankError("INVALID_AMOUNT", 422)
    with bank.store.transaction() as db:
        bank._guard(db, context)
        if occasion < _today(bank.store.clock()):
            raise BankError("SCENARIO_DATE_PAST", 422)
        source = db.execute(
            "SELECT id,name,suffix FROM accounts WHERE id=? AND owner_id=?",
            (values["source_id"], context.user_id),
        ).fetchone()
        if source is None:
            raise BankError("RESOURCE_NOT_FOUND", 404)
        payee = db.execute(
            "SELECT id,account_id,name FROM bank_payees WHERE id=? AND owner_id=?",
            (values["payee_id"], context.user_id),
        ).fetchone()
        if payee is None:
            raise BankError("RESOURCE_NOT_FOUND", 404)
        if payee["account_id"] == source["id"]:
            raise BankError("INVALID_TRANSFER", 422)
        scenario_id = uuid4().hex
        detail = {
            "scenario_id": scenario_id,
            "kind": kind,
            "title": title,
            "occasion_date": occasion.isoformat(),
            "budget_minor": amount,
            "source_id": source["id"],
            "payee_id": payee["id"],
            "created_at": bank.store.clock(),
            "request_digest": fingerprint(values),
        }
        bank._event(db, context.user_id, "scenario_plan_created", **detail)
        plan = next(
            item for item in _saved(bank, context, db) if item["scenario_id"] == scenario_id
        )
        return {"scenario": plan}


def order_scenario(bank, context, scenario_id):
    with bank.store.transaction() as db:
        bank._guard(db, context)
        plan = next(
            (item for item in _saved(bank, context, db) if item["scenario_id"] == scenario_id),
            None,
        )
    if plan is None:
        raise BankError("RESOURCE_NOT_FOUND", 404)
    if plan["status"] == "cancelled":
        raise BankError("SCENARIO_CANCELLED", 409)
    if plan["status"] == "expired":
        raise BankError("SCENARIO_EXPIRED", 409)
    if plan["status"] == "ordered":
        return {"scenario": plan, "operation": bank.operation(context, plan["operation_id"])}
    request_id = uuid5(NAMESPACE_URL, "ai-banking:scenario:" + scenario_id).hex
    task = bank.task(context, request_id)
    operation = bank.prepare(
        context,
        {
            "task_id": task["id"],
            "step_key": "scenario_" + scenario_id,
            "source_id": plan["source_id"],
            "currency": "CNY",
            "mode": "HUMAN_APPROVAL",
            "grant_id": None,
            "confirmation_seconds": 300,
            "payee_id": plan["payee_id"],
            "amount_minor": plan["budget_minor"],
        },
        "transfer",
        exclusive_task=True,
    )
    with bank.store.transaction() as db:
        bank._guard(db, context)
        db.execute(
            "INSERT INTO bank_events (owner_id,operation_id,event,detail,created_at) "
            "VALUES (?,?,?,?,?)",
            (
                context.user_id,
                operation["id"],
                "scenario_ordered",
                json.dumps(
                    {"scenario_id": scenario_id, "operation_id": operation["id"]},
                    ensure_ascii=False,
                ),
                bank.store.clock(),
            ),
        )
        plan = next(
            item for item in _saved(bank, context, db) if item["scenario_id"] == scenario_id
        )
    return {"scenario": plan, "operation": operation}


def cancel_scenario(bank, context, scenario_id):
    with bank.store.transaction() as db:
        bank._guard(db, context)
        plan = next(
            (item for item in _saved(bank, context, db) if item["scenario_id"] == scenario_id),
            None,
        )
        if plan is None:
            raise BankError("RESOURCE_NOT_FOUND", 404)
        if plan["status"] == "ordered":
            raise BankError("SCENARIO_ALREADY_ORDERED", 409)
        if plan["status"] == "cancelled":
            return {"scenario": plan}
        bank._event(db, context.user_id, "scenario_cancelled", scenario_id=scenario_id)
        plan = next(
            item for item in _saved(bank, context, db) if item["scenario_id"] == scenario_id
        )
        return {"scenario": plan}
