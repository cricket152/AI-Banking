"""从本人流水推断月度候选；仅界面明确确认后登记，不创建扣款或授权。"""

import calendar
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ai_banking.banking.reports import ZONE
from ai_banking.banking.service import BankError, fingerprint


def next_month(value):
    year = value.year + (value.month == 12)
    month = value.month % 12 + 1
    return value.replace(
        year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1])
    )


def candidates(reports, context, db=None):
    if db is None:
        with reports.store.transaction() as connection:
            return candidates(reports, context, connection)
    reports.bank._guard(db, context)
    today = datetime.fromtimestamp(reports.store.clock(), UTC).astimezone(ZONE).date()
    rows = reports._entries(context, today - timedelta(days=365), today + timedelta(days=1), db)
    registered = {
        (row["account_id"], row["merchant"])
        for row in db.execute(
            "SELECT account_id,merchant FROM bank_subscriptions WHERE owner_id=?",
            (context.user_id,),
        )
    }
    groups = defaultdict(list)
    now = datetime.fromtimestamp(reports.store.clock(), UTC)
    for row in rows:
        if (
            row["amount_minor"] < 0
            and row["category"] != "转账"
            and datetime.fromisoformat(row["happened_at"]) <= now
            and (row["account_id"], row["merchant"]) not in registered
        ):
            groups[(row["account_id"], row["merchant"])].append(row)
    result = []
    for (account_id, merchant), evidence in sorted(groups.items()):
        # 同商户的额外扣费会破坏周期，宁可漏报也不把任意重复消费当作订阅。
        if len(evidence) < 3:
            continue
        amounts = {-row["amount_minor"] for row in evidence}
        dates = [datetime.fromisoformat(row["happened_at"]).astimezone(ZONE) for row in evidence]
        intervals = [(right.date() - left.date()).days for left, right in zip(dates, dates[1:])]
        if len(amounts) != 1 or not all(25 <= days <= 35 for days in intervals):
            continue
        if (today - dates[-1].date()).days > 45 or len(merchant) > 128:
            continue
        estimate = next_month(dates[-1])
        result.append(
            {
                "candidate_id": fingerprint({"account_id": account_id, "merchant": merchant})[:32],
                "evidence_digest": fingerprint(evidence),
                "account_id": account_id,
                "merchant": merchant,
                "amount_minor": amounts.pop(),
                "status": "inferred",
                "cadence": "monthly",
                "charge_count": len(evidence),
                "interval_days": intervals,
                "estimated_next_charge_at": estimate.astimezone(UTC).isoformat(),
                "estimate_overdue": estimate < now,
                "reason": (
                    "最近一年同账户、同商户至少3次等额支出，相邻间隔均为25–35天，最近45天有扣费。"
                ),
                "evidence": evidence,
                "note": "周期性支出线索，不证明存在自动续费；下次日期为估计，确认登记不会扣款。",
            }
        )
    return result


def confirm_candidate(reports, context, candidate_id, evidence_digest):
    with reports.store.transaction() as db:
        reports.bank._guard(db, context)
        # 已成功的同一证据请求可安全回放，不恢复已取消的订阅。
        for row in db.execute(
            "SELECT detail FROM bank_events WHERE owner_id=? AND event='subscription_registered'",
            (context.user_id,),
        ):
            detail = json.loads(row["detail"])
            if (
                detail.get("candidate_id") == candidate_id
                and detail.get("evidence_digest") == evidence_digest
            ):
                subscription = db.execute(
                    "SELECT * FROM bank_subscriptions WHERE id=? AND owner_id=?",
                    (detail["subscription_id"], context.user_id),
                ).fetchone()
                if subscription:
                    return {"subscription": dict(subscription), "replayed": True}
        candidate = next(
            (
                item
                for item in candidates(reports, context, db)
                if item["candidate_id"] == candidate_id
            ),
            None,
        )
        if candidate is None or candidate["evidence_digest"] != evidence_digest:
            raise BankError("SUBSCRIPTION_EVIDENCE_CHANGED", 409)
        subscription_id = uuid4().hex
        db.execute(
            "INSERT INTO bank_subscriptions "
            "(id,owner_id,account_id,merchant,amount_minor,next_charge_at,source) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                subscription_id,
                context.user_id,
                candidate["account_id"],
                candidate["merchant"],
                candidate["amount_minor"],
                candidate["estimated_next_charge_at"],
                "inferred_confirmed",
            ),
        )
        reports.bank._event(
            db,
            context.user_id,
            "subscription_registered",
            candidate_id=candidate_id,
            evidence_digest=evidence_digest,
            subscription_id=subscription_id,
            entry_ids=[row["id"] for row in candidate["evidence"]],
        )
        return {
            "subscription": dict(
                db.execute(
                    "SELECT * FROM bank_subscriptions WHERE id=?", (subscription_id,)
                ).fetchone()
            ),
            "replayed": False,
        }
