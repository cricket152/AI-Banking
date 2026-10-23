"""日期区间采用 Asia/Shanghai 自然日、左闭右开；统计只使用整数分。"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ai_banking.banking.service import BankError

ZONE = ZoneInfo("Asia/Shanghai")


class Reports:
    def __init__(self, bank):
        self.bank, self.store = bank, bank.store

    def bills(self, context, start: date, end: date):
        if end <= start or (end - start).days > 366:
            raise BankError("INVALID_DATE_RANGE", 422)
        beginning = datetime.combine(start, datetime.min.time(), ZONE).astimezone(UTC)
        ending = datetime.combine(end, datetime.min.time(), ZONE).astimezone(UTC)
        with self.store.transaction() as db:
            self.bank._guard(db, context)
            rows = db.execute(
                "SELECT e.* FROM entries e JOIN accounts a ON a.id=e.account_id "
                "WHERE a.owner_id=? ORDER BY e.happened_at,e.id",
                (context.user_id,),
            ).fetchall()
        categories, merchants, months = defaultdict(int), defaultdict(int), defaultdict(int)
        income, expense, refunds, transfer_in, transfer_out, subscription = 0, 0, 0, 0, 0, 0
        references, possible_anomalies = [], []
        for row in rows:
            happened = datetime.fromisoformat(row["happened_at"])
            if happened.tzinfo is None:
                raise BankError("INVALID_STORED_TIMESTAMP", 503)
            if not beginning <= happened < ending:
                continue
            amount = row["amount_minor"]
            references.append(row["id"])
            if row["category"] == "转账":
                transfer_in += max(0, amount)
                transfer_out -= min(0, amount)
                continue
            if amount > 0:
                if row["category"] == "退款":
                    refunds += amount
                else:
                    income += amount
                continue
            amount = -amount
            expense += amount
            categories[row["category"]] += amount
            merchants[row["merchant"]] += amount
            months[happened.astimezone(ZONE).strftime("%Y-%m")] += amount
            if row["category"] == "订阅":
                subscription += amount
            # 明确可复算的启发式提示，不将其判定为欺诈。
            if amount >= 100000:
                possible_anomalies.append(
                    {"entry_id": row["id"], "reason": "单笔支出不少于1000元；请人工核对"}
                )
        return {
            "currency": "CNY",
            "start_inclusive": start.isoformat(),
            "end_exclusive": end.isoformat(),
            "timezone": "Asia/Shanghai",
            "income_minor": income,
            "expense_minor": expense,
            "refund_minor": refunds,
            "net_expense_minor": expense - refunds,
            "transfer_in_minor": transfer_in,
            "transfer_out_minor": transfer_out,
            "subscription_expense_minor": subscription,
            "by_category": dict(categories),
            "by_merchant": dict(merchants),
            "by_month": dict(months),
            "entry_ids": references,
            "possible_anomalies": possible_anomalies,
            "anomaly_rule": "项目演示启发式：单笔非转账支出>=100000分；不是欺诈结论",
        }

    def subscriptions(self, context):
        with self.store.transaction() as db:
            self.bank._guard(db, context)
            rows = db.execute(
                "SELECT id,account_id,merchant,amount_minor,next_charge_at,status,source "
                "FROM bank_subscriptions WHERE owner_id=? ORDER BY merchant,id",
                (context.user_id,),
            ).fetchall()
        now = datetime.fromtimestamp(self.store.clock(), UTC)
        items = []
        for row in rows:
            item = dict(row)
            due = datetime.fromisoformat(item["next_charge_at"])
            item["renewal_due_soon"] = item["status"] == "active" and now <= due <= now + timedelta(
                days=7
            )
            item["reminder_window_days"] = 7
            items.append(item)
        return {
            "subscriptions": items,
            "currency": "CNY",
            "inferred_candidates": [],
            "note": "虚构登记订阅；提醒由查询时计算，无后台扣款或推送。取消不产生退款。",
        }
