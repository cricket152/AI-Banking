from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from threading import RLock


def money(cents):
    whole, fraction = divmod(abs(cents), 100)
    sign = "-" if cents < 0 else ""
    return f"{sign}¥{whole:,}.{fraction:02d}"


def amount_to_cents(value):
    return int(
        (Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def _seed_transactions(today):
    samples = [
        ("澄鲜超市", "餐饮", 18650, "out", "日常采购"),
        ("云听音乐", "订阅", 1800, "out", "月度会员"),
        ("城市交通", "交通", 4200, "out", "通勤"),
        ("周明", "转账", 8800, "out", "午餐 AA"),
        ("栖木咖啡", "餐饮", 5600, "out", "咖啡"),
        ("数码优选", "购物", 128000, "out", "待核验的大额消费"),
        ("工资入账", "收入", 1280000, "in", "月度工资"),
        ("鲜花订阅", "订阅", 9900, "out", "鲜花月卡"),
        ("澄鲜超市", "餐饮", 9230, "out", "食材"),
        ("城市交通", "交通", 2600, "out", "地铁"),
        ("视频会员", "订阅", 2500, "out", "月度会员"),
        ("林小满", "转账", 12000, "in", "共同生活费"),
    ]
    transactions = []
    for index, (merchant, category, amount, direction, note) in enumerate(samples):
        offset = index * 2 + 1
        when = today - timedelta(days=offset)
        transactions.append(
            {
                "id": f"TX-{today:%Y%m}-{index + 1:03d}",
                "date": when.isoformat(),
                "merchant": merchant,
                "category": category,
                "amount_cents": amount,
                "direction": direction,
                "note": note,
                "anomaly": merchant == "数码优选",
            }
        )
    return transactions


def _seed_state():
    today = date.today()
    birthday = date(today.year, 11, 5)
    if birthday < today:
        birthday = date(today.year + 1, 11, 5)
    return {
        "profile": {
            "name": "林知夏",
            "risk_profile": "稳健型",
            "partner_birthday": birthday.isoformat(),
        },
        "accounts": [
            {
                "id": "checking",
                "name": "日常账户",
                "number": "**** 2861",
                "kind": "活期",
                "balance_cents": 1863050,
                "held_cents": 0,
                "color": "green",
            },
            {
                "id": "savings",
                "name": "安心储蓄",
                "number": "**** 9038",
                "kind": "储蓄",
                "balance_cents": 3000000,
                "held_cents": 0,
                "color": "blue",
            },
        ],
        "contacts": [
            {
                "name": "周明",
                "phone": "13800138001",
                "aliases": ["明明", "同事周明"],
                "note": "项目协作",
            },
            {
                "name": "林小满",
                "phone": "13900139002",
                "aliases": ["小满", "爱人", "老婆"],
                "note": "家庭联系人",
            },
            {
                "name": "妈妈",
                "phone": "13700137003",
                "aliases": ["妈", "母亲"],
                "note": "家人",
            },
        ],
        "cards": [
            {
                "id": "CARD-2861",
                "name": "澄明白金卡",
                "number": "**** **** **** 2861",
                "kind": "Visa Signature",
                "status": "active",
                "limit_cents": 5000000,
                "used_cents": 126800,
                "daily_limit_cents": 1000000,
                "color": "dark",
            },
            {
                "id": "CARD-9038",
                "name": "澄明生活卡",
                "number": "**** **** **** 9038",
                "kind": "银联借记卡",
                "status": "active",
                "limit_cents": 2000000,
                "used_cents": 38200,
                "daily_limit_cents": 500000,
                "color": "mint",
            },
        ],
        "subscriptions": [
            {
                "id": "SUB-01",
                "name": "云听音乐",
                "amount_cents": 1800,
                "period": "每月",
                "next_charge": (today + timedelta(days=3)).isoformat(),
                "status": "active",
                "category": "音乐",
                "reminder": False,
            },
            {
                "id": "SUB-02",
                "name": "视频会员",
                "amount_cents": 2500,
                "period": "每月",
                "next_charge": (today + timedelta(days=5)).isoformat(),
                "status": "active",
                "category": "视频",
                "reminder": False,
            },
            {
                "id": "SUB-03",
                "name": "鲜花订阅",
                "amount_cents": 9900,
                "period": "每月",
                "next_charge": (today + timedelta(days=9)).isoformat(),
                "status": "active",
                "category": "生活",
                "reminder": False,
            },
            {
                "id": "SUB-04",
                "name": "云空间",
                "amount_cents": 1200,
                "period": "每月",
                "next_charge": (today + timedelta(days=12)).isoformat(),
                "status": "active",
                "category": "工具",
                "reminder": False,
            },
        ],
        "funds": [
            {
                "id": "FUND-01",
                "name": "澄明短债精选",
                "category": "纯债基金",
                "risk": 2,
                "annual_return": 0.032,
                "volatility": 0.018,
                "min_amount_cents": 10000,
                "holding_cents": 862000,
                "description": "以中短久期债券为主，净值波动相对较低。",
            },
            {
                "id": "FUND-02",
                "name": "沪深 300 指数",
                "category": "宽基指数",
                "risk": 4,
                "annual_return": 0.071,
                "volatility": 0.186,
                "min_amount_cents": 10000,
                "holding_cents": 506000,
                "description": "跟踪大盘股票指数，收益与回撤均可能较大。",
            },
            {
                "id": "FUND-03",
                "name": "全球科技成长",
                "category": "行业股票",
                "risk": 5,
                "annual_return": 0.104,
                "volatility": 0.294,
                "min_amount_cents": 10000,
                "holding_cents": 200000,
                "description": "科技行业集中度较高，适合承受较大波动的投资者。",
            },
        ],
        "transactions": _seed_transactions(today),
        "scheduled_transfers": [],
        "collection_requests": [],
        "reminders": [],
        "birthday_plans": [],
        "audit_log": [],
    }


class BankingDemo:
    def __init__(self):
        self._lock = RLock()
        self._state = _seed_state()

    def reset(self):
        with self._lock:
            self._state = _seed_state()
            return self.get_state()

    def get_state(self):
        with self._lock:
            self._process_due_transfers()
            state = deepcopy(self._state)
            checking = next(
                account for account in state["accounts"] if account["id"] == "checking"
            )
            state["checking_available_cents"] = (
                checking["balance_cents"] - checking["held_cents"]
            )
            state["monthly_spending_cents"] = sum(
                item["amount_cents"]
                for item in state["transactions"]
                if item["direction"] == "out"
                and item["category"] not in ("转账", "理财")
                and item["date"][:7] == date.today().strftime("%Y-%m")
            )
            categories = {}
            for item in state["transactions"]:
                if (
                    item["direction"] == "out"
                    and item["category"] not in ("转账", "理财")
                    and item["date"][:7] == date.today().strftime("%Y-%m")
                ):
                    categories[item["category"]] = (
                        categories.get(item["category"], 0) + item["amount_cents"]
                    )
            state["monthly_categories"] = [
                {"name": name, "amount_cents": amount}
                for name, amount in sorted(
                    categories.items(), key=lambda entry: entry[1], reverse=True
                )
            ]
            state["anomalies"] = [
                item for item in state["transactions"] if item.get("anomaly")
            ]
            state["net_assets_cents"] = (
                sum(account["balance_cents"] for account in state["accounts"])
                + sum(fund["holding_cents"] for fund in state["funds"])
            )
            state["active_subscription_total_cents"] = sum(
                item["amount_cents"]
                for item in state["subscriptions"]
                if item["status"] == "active"
            )
            return state

    def _process_due_transfers(self):
        today = date.today().isoformat()
        for scheduled in self._state["scheduled_transfers"]:
            if scheduled["status"] != "scheduled" or scheduled["date"] > today:
                continue
            try:
                self._transfer(
                    {
                        "recipient": scheduled["recipient"],
                        "amount_cents": scheduled["amount_cents"],
                        "note": scheduled["note"],
                    }
                )
                scheduled["status"] = "completed"
                scheduled["completed_at"] = datetime.now().isoformat(timespec="seconds")
            except ValueError as error:
                scheduled["status"] = "failed"
                scheduled["error"] = str(error)
                self._add_audit(
                    "scheduled_transfer_failed",
                    f"{scheduled['recipient']} {money(scheduled['amount_cents'])}: {error}",
                )

    def execute(self, action):
        with self._lock:
            kind = action["kind"]
            payload = action["payload"]
            if kind == "transfer":
                return self._transfer(payload)
            if kind == "scheduled_transfer":
                return self._schedule_transfer(payload)
            if kind == "split_aa":
                return self._split_aa(payload)
            if kind == "birthday_bundle":
                return self._birthday_bundle(payload)
            if kind == "card_lock":
                return self._card_status(payload, "locked")
            if kind == "card_unlock":
                return self._card_status(payload, "active")
            if kind == "card_limit":
                return self._card_limit(payload)
            if kind == "card_daily_limit":
                return self._card_daily_limit(payload)
            if kind == "card_apply":
                return self._card_apply()
            if kind == "fund_purchase":
                return self._fund_purchase(payload)
            if kind == "fund_redeem":
                return self._fund_redeem(payload)
            if kind == "subscription_cancel":
                return self._subscription_cancel(payload)
            if kind == "subscription_reminder":
                return self._subscription_reminder(payload)
            raise ValueError("不支持的演示操作。")

    def _add_audit(self, operation, detail):
        self._state["audit_log"].append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "operation": operation,
                "detail": detail,
                "status": "completed",
            }
        )

    def _add_transaction(self, merchant, category, amount_cents, direction, note):
        self._state["transactions"].insert(
            0,
            {
                "id": f"TX-{datetime.now():%Y%m%d%H%M%S}-{len(self._state['transactions'])}",
                "date": date.today().isoformat(),
                "merchant": merchant,
                "category": category,
                "amount_cents": amount_cents,
                "direction": direction,
                "note": note,
                "anomaly": False,
            },
        )

    def _transfer(self, payload):
        amount = payload["amount_cents"]
        if amount <= 0:
            raise ValueError("转账金额必须大于 0 元。")
        account = next(item for item in self._state["accounts"] if item["id"] == "checking")
        if account["balance_cents"] - account["held_cents"] < amount:
            raise ValueError("日常账户可用余额不足，未执行转账。")
        account["balance_cents"] -= amount
        self._add_transaction(
            payload["recipient"],
            "转账",
            amount,
            "out",
            payload.get("note", "AI 助手转账"),
        )
        self._add_audit(
            "transfer",
            f"{payload['recipient']} {money(amount)} {payload.get('note', '')}".strip(),
        )
        return f"已从日常账户向 {payload['recipient']} 转出 {money(amount)}。"

    def _schedule_transfer(self, payload):
        self._state["scheduled_transfers"].append(
            {
                "id": f"ST-{len(self._state['scheduled_transfers']) + 1:03d}",
                "recipient": payload["recipient"],
                "amount_cents": payload["amount_cents"],
                "date": payload["date"],
                "note": payload.get("note", "预约转账"),
                "status": "scheduled",
            }
        )
        self._add_audit(
            "scheduled_transfer",
            f"{payload['recipient']} {money(payload['amount_cents'])} {payload['date']}",
        )
        return (
            f"已创建预约转账：{payload['date']} 向 {payload['recipient']} 转出 "
            f"{money(payload['amount_cents'])}。到期前仍可在演示数据中查看。"
        )

    def _split_aa(self, payload):
        amount = payload["amount_cents"]
        people = payload["people"]
        if amount <= 0 or people < 2:
            raise ValueError("AA 总额须大于 0 元，人数至少为 2 人。")
        share, remainder = divmod(amount, people)
        participants = payload["participants"]
        if len(participants) != people - 1:
            raise ValueError("AA 收款人数量必须等于总人数减去你本人。")
        requests = []
        for index, name in enumerate(participants):
            requests.append(
                {
                    "name": name,
                    "amount_cents": share + (1 if index + 1 < remainder else 0),
                }
            )
        collection = {
            "id": f"AA-{len(self._state['collection_requests']) + 1:03d}",
            "title": payload.get("title", "AA 收款"),
            "total_cents": amount,
            "people": people,
            "share_cents": share,
            "payer_share_cents": share + (1 if remainder else 0),
            "participants": requests,
            "status": "created",
        }
        self._state["collection_requests"].append(collection)
        self._add_audit("split_aa", f"{money(amount)} / {people} 人")
        return (
            f"AA 收款单已创建，总额 {money(amount)}，共 {people} 人，"
            f"每人约 {money(share)}；余数已平均分配到前几位。"
        )

    def _birthday_bundle(self, payload):
        amount = payload["amount_cents"]
        if amount <= 0:
            raise ValueError("生日预留金额必须大于 0 元。")
        account = next(item for item in self._state["accounts"] if item["id"] == "checking")
        if account["balance_cents"] - account["held_cents"] < amount:
            raise ValueError("可用余额不足，生日安排未创建。")
        account["held_cents"] += amount
        plan = {
            "id": f"BD-{len(self._state['birthday_plans']) + 1:03d}",
            "date": payload["birthday"],
            "reserve_cents": amount,
            "recipient": payload["recipient"],
            "gifts": payload["gifts"],
            "gift_order_date": (
                date.fromisoformat(payload["birthday"]) - timedelta(days=2)
            ).isoformat(),
            "status": "scheduled",
        }
        self._state["birthday_plans"].append(plan)
        self._state["reminders"].append(
            {
                "date": plan["gift_order_date"],
                "title": f"为{plan['recipient']}预订鲜花和蛋糕",
                "status": "scheduled",
            }
        )
        self._add_audit(
            "birthday_bundle",
            f"{payload['recipient']} {payload['birthday']} 锁定 {money(amount)}",
        )
        return (
            f"生日联动已安排：{payload['birthday']} 为{payload['recipient']}预留 "
            f"{money(amount)}，并在 {plan['gift_order_date']} 提醒订购鲜花和蛋糕。"
        )

    def _card_status(self, payload, status):
        card = self._find_card(payload.get("card_id"))
        card["status"] = status
        label = "已锁定" if status == "locked" else "已解锁"
        self._add_audit("card_status", f"{card['name']} {label}")
        return f"{card['name']} {label}。"

    def _card_limit(self, payload):
        card = self._find_card(payload.get("card_id"))
        limit = payload["limit_cents"]
        if limit <= 0 or limit < card["used_cents"]:
            raise ValueError("新额度必须大于 0，且不能低于当前已用额度。")
        card["limit_cents"] = limit
        self._add_audit("card_limit", f"{card['name']} 调整至 {money(limit)}")
        return f"{card['name']}额度已调整为 {money(limit)}。"

    def _card_daily_limit(self, payload):
        card = self._find_card(payload.get("card_id"))
        limit = payload["limit_cents"]
        if limit <= 0:
            raise ValueError("单日交易限额必须大于 0 元。")
        card["daily_limit_cents"] = limit
        self._add_audit("card_daily_limit", f"{card['name']} 单日限额 {money(limit)}")
        return f"{card['name']}单日交易限额已调整为 {money(limit)}。"

    def _card_apply(self):
        card_number = len(self._state["cards"]) + 1
        card = {
            "id": f"CARD-NEW-{card_number}",
            "name": "澄明数字卡",
            "number": f"**** **** **** {7000 + card_number}",
            "kind": "银联数字卡",
            "status": "active",
            "limit_cents": 1000000,
            "used_cents": 0,
            "daily_limit_cents": 200000,
            "color": "mint",
        }
        self._state["cards"].append(card)
        self._add_audit("card_apply", card["name"])
        return f"演示数字卡已申请并添加至卡片列表：{card['number']}。"

    def _fund_purchase(self, payload):
        amount = payload["amount_cents"]
        fund = self._find_fund(payload["fund_id"])
        account = next(item for item in self._state["accounts"] if item["id"] == "checking")
        if amount < fund["min_amount_cents"]:
            raise ValueError(
                f"{fund['name']}起投金额为 {money(fund['min_amount_cents'])}。"
            )
        if account["balance_cents"] - account["held_cents"] < amount:
            raise ValueError("可用余额不足，未提交申购。")
        account["balance_cents"] -= amount
        fund["holding_cents"] += amount
        self._add_transaction(fund["name"], "理财", amount, "out", "基金申购")
        self._add_audit("fund_purchase", f"{fund['name']} {money(amount)}")
        return f"已完成演示申购：{fund['name']} {money(amount)}。"

    def _fund_redeem(self, payload):
        amount = payload["amount_cents"]
        fund = self._find_fund(payload["fund_id"])
        if amount <= 0 or fund["holding_cents"] < amount:
            raise ValueError("赎回金额无效或超过当前持仓。")
        fund["holding_cents"] -= amount
        account = next(item for item in self._state["accounts"] if item["id"] == "checking")
        account["balance_cents"] += amount
        self._add_transaction(fund["name"], "理财", amount, "in", "基金赎回")
        self._add_audit("fund_redeem", f"{fund['name']} {money(amount)}")
        return f"已完成演示赎回：{fund['name']} {money(amount)}。"

    def _subscription_cancel(self, payload):
        subscription = self._find_subscription(payload.get("subscription_id"))
        subscription["status"] = "cancelled"
        self._add_audit("subscription_cancel", subscription["name"])
        return f"已在演示数据中取消「{subscription['name']}」的后续续费。"

    def _subscription_reminder(self, payload):
        subscription = self._find_subscription(payload.get("subscription_id"))
        subscription["reminder"] = True
        self._state["reminders"].append(
            {
                "date": subscription["next_charge"],
                "title": f"{subscription['name']}续费提醒",
                "status": "scheduled",
            }
        )
        self._add_audit("subscription_reminder", subscription["name"])
        return f"已设置「{subscription['name']}」续费提醒：{subscription['next_charge']}。"

    def _find_card(self, card_id=None):
        cards = self._state["cards"]
        if card_id:
            for card in cards:
                if card["id"] == card_id:
                    return card
            raise ValueError("没有找到对应卡片。")
        return cards[0]

    def _find_fund(self, fund_id):
        for fund in self._state["funds"]:
            if fund["id"] == fund_id:
                return fund
        raise ValueError("没有找到对应理财产品。")

    def _find_subscription(self, subscription_id=None):
        subscriptions = self._state["subscriptions"]
        if subscription_id:
            for subscription in subscriptions:
                if subscription["id"] == subscription_id:
                    return subscription
            raise ValueError("没有找到对应订阅。")
        for subscription in subscriptions:
            if subscription["status"] == "active":
                return subscription
        raise ValueError("没有仍在续费的订阅。")
