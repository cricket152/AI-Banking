"""用户选定的订阅整理 / 转账方案；计划不产生交易授权。"""

import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from ai_banking.banking.contacts import list_payees
from ai_banking.banking.service import BankError, fingerprint


def _saved_plan(db, owner_id, *, conversation_id=None, task_id=None):
    for row in db.execute(
        "SELECT detail FROM bank_events WHERE owner_id=? "
        "AND event='workflow_plan_selected' ORDER BY seq DESC",
        (owner_id,),
    ):
        plan = json.loads(row["detail"])
        if (conversation_id is not None and plan["conversation_id"] == conversation_id) or (
            task_id is not None and plan["task_id"] == task_id
        ):
            return plan
    return None


def _matches(step, operation):
    return step["kind"] == operation["kind"] and all(
        operation[field] == value for field, value in step["arguments"].items()
    )


def _public_plan(db, owner_id, plan):
    operations = db.execute(
        "SELECT * FROM bank_operations WHERE task_id=? AND owner_id=?", (plan["task_id"], owner_id)
    ).fetchall()
    steps = []
    for step in plan["steps"]:
        operation = next((op for op in operations if _matches(step, op)), None)
        steps.append(
            {
                **step,
                "state": operation["state"] if operation else "not_started",
                "operation_id": operation["id"] if operation else None,
            }
        )
    return {
        "conversation_id": plan["conversation_id"],
        "task_id": plan["task_id"],
        "steps": steps,
        "preview": plan["preview"],
        "completed": all(step["state"] == "succeeded" for step in steps),
    }


def conversation_plan(bank, context, conversation_id):
    with bank.store.transaction() as db:
        bank._guard(db, context)
        plan = _saved_plan(db, context.user_id, conversation_id=conversation_id)
        return _public_plan(db, context.user_id, plan) if plan else None


def _preview(bank, context, values, db):
    source = bank._account(db, context.user_id, values["source_id"])
    payee = next((p for p in list_payees(bank, context, db) if p["id"] == values["payee_id"]), None)
    if payee is None:
        raise BankError("RESOURCE_NOT_FOUND", 404)
    if payee["account_id"] == source["id"]:
        raise BankError("INVALID_TRANSFER", 422)
    bank._available(db, context.user_id, source["id"], values["amount_minor"], 0)
    identifiers = values["subscription_ids"]
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise BankError("INVALID_PLAN", 422)
    subscriptions = []
    for identifier in identifiers:
        row = db.execute(
            "SELECT * FROM bank_subscriptions WHERE id=? AND owner_id=? "
            "AND account_id=? AND status='active'",
            (identifier, context.user_id, source["id"]),
        ).fetchone()
        if row is None:
            raise BankError("PLAN_EVIDENCE_CHANGED", 409)
        subscriptions.append(dict(row))
    steps = [
        {
            "kind": "cancel_subscription",
            "arguments": {"source_id": source["id"], "subscription_id": s["id"], "currency": "CNY"},
            "label": "取消 " + s["merchant"],
        }
        for s in subscriptions
    ]
    steps.append(
        {
            "kind": "transfer",
            "arguments": {
                "source_id": source["id"],
                "payee_id": payee["id"],
                "amount_minor": values["amount_minor"],
                "currency": "CNY",
            },
            "label": "转账给 " + payee["name"] + " · 尾号 " + payee["suffix"],
        }
    )
    preview = {
        "steps": steps,
        "subscriptions": [
            {
                field: subscription[field]
                for field in ("id", "merchant", "amount_minor", "next_charge_at", "source")
            }
            for subscription in subscriptions
        ],
        "source": {"name": source["name"], "suffix": source["suffix"]},
        "recipient": payee,
        "transfer_minor": values["amount_minor"],
        "current_balance_minor": source["balance_minor"],
        "estimated_balance_minor": source["balance_minor"] - values["amount_minor"],
        "future_reduction_per_cycle_minor": sum(s["amount_minor"] for s in subscriptions),
        "note": (
            "取消不退款；每期少支出是估计，不作为当前到账。"
            "余额为当前预览，执行时重新校验；创建方案不会扣款或授予权限。"
        ),
    }
    return {**preview, "evidence_digest": fingerprint(preview)}


def preview_plan(bank, context, values):
    with bank.store.transaction() as db:
        bank._guard(db, context)
        return _preview(bank, context, values, db)


def create_plan(bank, context, values):
    with bank.store.transaction() as db:
        bank._guard(db, context)
        request_digest = fingerprint(values)
        for row in db.execute(
            "SELECT detail FROM bank_events WHERE owner_id=? AND event='workflow_plan_selected'",
            (context.user_id,),
        ):
            old = json.loads(row["detail"])
            if old["request_id"] == values["request_id"]:
                if old["request_digest"] != request_digest:
                    raise BankError("PLAN_REQUEST_CONFLICT", 409)
                return _public_plan(db, context.user_id, old)
        preview = _preview(bank, context, values, db)
        if preview["evidence_digest"] != values["evidence_digest"]:
            raise BankError("PLAN_EVIDENCE_CHANGED", 409)
        conversation_id = uuid4().hex
        task_id = uuid4().hex
        request_id = uuid5(NAMESPACE_URL, "ai-banking:agent-conversation:" + conversation_id).hex
        db.execute(
            "INSERT INTO conversations VALUES (?,?,?,0)",
            (conversation_id, context.user_id, bank.store.clock()),
        )
        db.execute(
            "INSERT INTO bank_tasks VALUES (?,?,?,?)",
            (task_id, context.user_id, request_id, bank.store.clock()),
        )
        plan = {
            "conversation_id": conversation_id,
            "task_id": task_id,
            "request_id": values["request_id"],
            "request_digest": request_digest,
            "steps": preview["steps"],
            "preview": preview,
        }
        bank._event(db, context.user_id, "workflow_plan_selected", **plan)
        return _public_plan(db, context.user_id, plan)


def validate_plan(db, owner_id, values, kind):
    """在原准备事务内约束顺序和参数；现有步骤回放仍由原幂等规则处理。"""
    plan = _saved_plan(db, owner_id, task_id=values["task_id"])
    if plan is None:
        return
    rows = db.execute(
        "SELECT * FROM bank_operations WHERE task_id=? AND owner_id=?",
        (values["task_id"], owner_id),
    ).fetchall()
    proposed = {"kind": kind, **values}
    for step in plan["steps"]:
        old = next((row for row in rows if _matches(step, row)), None)
        if old is not None and _matches(step, proposed):
            if values["step_key"] != old["step_key"]:
                raise BankError("PLAN_PARAMETERS_CONFLICT", 409)
            return
        if old is not None:
            if old["state"] != "succeeded":
                raise BankError("PLAN_STEP_BLOCKED", 409)
            continue
        if not _matches(step, proposed):
            raise BankError("PLAN_PARAMETERS_CONFLICT", 409)
        return
    raise BankError("PLAN_ALREADY_COMPLETED", 409)
