"""日期区间采用 Asia/Shanghai 自然日、左闭右开；统计只使用整数分。"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import median_low
from zoneinfo import ZoneInfo

from ai_banking.banking.service import BankError

ZONE = ZoneInfo("Asia/Shanghai")


class Reports:
    def __init__(self, bank):
        self.bank, self.store = bank, bank.store

    def _entries(self, context, start: date, end: date, db=None):
        if end <= start or (end - start).days > 366:
            raise BankError("INVALID_DATE_RANGE", 422)
        beginning = datetime.combine(start, datetime.min.time(), ZONE).astimezone(UTC)
        ending = datetime.combine(end, datetime.min.time(), ZONE).astimezone(UTC)

        def read(connection):
            self.bank._guard(connection, context)
            return connection.execute(
                "SELECT e.* FROM entries e JOIN accounts a ON a.id=e.account_id "
                "WHERE a.owner_id=? ORDER BY e.happened_at,e.id",
                (context.user_id,),
            ).fetchall()

        if db is None:
            with self.store.transaction() as connection:
                rows = read(connection)
        else:
            rows = read(db)
        result = []
        for row in rows:
            happened = datetime.fromisoformat(row["happened_at"])
            if happened.tzinfo is None:
                raise BankError("INVALID_STORED_TIMESTAMP", 503)
            if beginning <= happened < ending:
                result.append(dict(row))
        return sorted(
            result, key=lambda row: (datetime.fromisoformat(row["happened_at"]), row["id"])
        )

    def bills(self, context, start: date, end: date, compare=True):
        with self.store.transaction() as db:
            return self._bills(context, start, end, db, compare)

    def _bills(self, context, start, end, db, compare):
        rows = self._entries(context, start, end, db)
        categories, merchants, months = defaultdict(int), defaultdict(int), defaultdict(int)
        income, expense, refunds, transfer_in, transfer_out, subscription = 0, 0, 0, 0, 0, 0
        references, possible_anomalies = [], []
        for row in rows:
            happened = datetime.fromisoformat(row["happened_at"])
            if happened.tzinfo is None:
                raise BankError("INVALID_STORED_TIMESTAMP", 503)
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
                    {
                        "entry_id": row["id"],
                        "amount_minor": amount,
                        "merchant": row["merchant"],
                        "reason": "单笔支出不少于1000元；请人工核对",
                    }
                )
        report = {
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
        if compare:
            try:
                previous_start = start - (end - start)
            except OverflowError as error:
                raise BankError("INVALID_DATE_RANGE", 422) from error
            previous = self._bills(context, previous_start, start, db, compare=False)
            previous_rows = self._entries(context, previous_start, start, db)
            baselines = defaultdict(list)
            for row in previous_rows:
                if row["amount_minor"] < 0 and row["category"] != "转账":
                    baselines[row["category"]].append(-row["amount_minor"])
            for row in rows:
                samples = baselines[row["category"]]
                amount = -row["amount_minor"]
                if row["category"] == "转账" or len(samples) < 3 or amount < 10000:
                    continue
                baseline = median_low(samples)
                if amount > 3 * baseline:
                    possible_anomalies.append(
                        {
                            "entry_id": row["id"],
                            "amount_minor": amount,
                            "merchant": row["merchant"],
                            "baseline_minor": baseline,
                            "baseline_count": len(samples),
                            "reason": (
                                "单笔支出超过前一等长区间同分类中位数的3倍，且不少于100元；请核对"
                            ),
                        }
                    )
            report["anomaly_rule"] += "；历史同分类至少3笔时，单笔>中位数3倍且>=10000分亦提示"
            report["comparison"] = {
                "basis": "前一等长自然日区间，非固定上月；无记录不代表没有消费",
                "start_inclusive": previous_start.isoformat(),
                "end_exclusive": start.isoformat(),
                "entry_count": len(previous["entry_ids"]),
                "expense_minor": previous["expense_minor"],
                "expense_delta_minor": expense - previous["expense_minor"],
                "net_expense_minor": previous["net_expense_minor"],
                "by_category": [
                    {
                        "category": category,
                        "current_minor": categories.get(category, 0),
                        "previous_minor": previous["by_category"].get(category, 0),
                        "delta_minor": categories.get(category, 0)
                        - previous["by_category"].get(category, 0),
                    }
                    for category in sorted(set(categories) | set(previous["by_category"]))
                ],
            }
        return report

    def entries(self, context, start, end, category=None, entry_id=None, offset=0, limit=20):
        if offset < 0 or not 1 <= limit <= 50:
            raise BankError("INVALID_REQUEST", 422)
        rows = self._entries(context, start, end)
        rows = [
            row
            for row in rows
            if (category is None or row["category"] == category)
            and (entry_id is None or row["id"] == entry_id)
        ]
        rows.reverse()
        return {
            "entries": rows[offset : offset + limit],
            "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "currency": "CNY",
            "timezone": "Asia/Shanghai",
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
            "inferred_candidates": self.candidates(context),
            "note": (
                "虚构订阅；疑似项须在界面确认登记。日期仅作提醒，无后台扣款或推送。取消不产生退款。"
            ),
        }

    def candidates(self, context, db=None):
        from ai_banking.banking.subscriptions import candidates

        return candidates(self, context, db)

    def confirm_candidate(self, context, candidate_id, evidence_digest):
        from ai_banking.banking.subscriptions import confirm_candidate

        return confirm_candidate(self, context, candidate_id, evidence_digest)
