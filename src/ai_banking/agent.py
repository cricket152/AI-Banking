import re
import uuid
from datetime import date, timedelta
from threading import RLock

from .domain import amount_to_cents, money


AMOUNT_PATTERN = re.compile(
    r"(?:(?:人民币|￥|¥)\s*([+-]?\d[\d,]*(?:\.\d{1,2})?)(?:\s*(?:元|块))?"
    r"|([+-]?\d[\d,]*(?:\.\d{1,2})?)\s*(?:元|块))"
)


def parse_amount(text):
    match = AMOUNT_PATTERN.search(text.replace("，", ","))
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return amount_to_cents(value.replace(",", ""))


def _future_month_day(month, day):
    today = date.today()
    year = today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if candidate < today:
        try:
            candidate = date(year + 1, month, day)
        except ValueError:
            return None
    return candidate.isoformat()


def _date_from_text(text, default=None):
    iso = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).isoformat()
        except ValueError:
            return None
    month_day = re.search(r"(\d{1,2})月(\d{1,2})日?", text)
    if month_day:
        return _future_month_day(int(month_day.group(1)), int(month_day.group(2)))
    today = date.today()
    if "大后天" in text:
        return (today + timedelta(days=3)).isoformat()
    if "后天" in text:
        return (today + timedelta(days=2)).isoformat()
    if "明天" in text:
        return (today + timedelta(days=1)).isoformat()
    if "今天" in text or "今晚" in text:
        return today.isoformat()
    return default


class BankingAgent:
    def __init__(self, bank):
        self.bank = bank
        self._lock = RLock()
        self._pending = {}

    def handle(self, message):
        text = (message or "").strip()
        if not text:
            return self._answer("说说你想办理什么，我可以协助处理转账、账单、理财、卡片和订阅。")
        state = self.bank.get_state()
        if self._is_birthday_request(text):
            return self._birthday(text, state)
        if any(word in text for word in ("AA", "aa", "平摊", "拆分", "收款")) and any(
            word in text for word in ("人", "聚餐", "账单", "收款", "AA", "aa")
        ):
            return self._split_aa(text, state)
        if any(word in text for word in ("账单", "消费", "支出", "月报", "年报", "异常交易")):
            return self._bill_analysis(text, state)
        if any(word in text for word in ("订阅", "会员", "续费", "扣费")):
            return self._subscriptions(text, state)
        if any(
            word in text
            for word in (
                "卡",
                "额度",
                "限额",
                "交易限制",
                "挂失",
                "盗刷",
                "冻结",
                "解锁",
                "锁定",
            )
        ):
            return self._cards(text, state)
        if any(word in text for word in ("理财", "基金", "申购", "赎回", "风险偏好", "收益率")):
            return self._investments(text, state)
        if any(word in text for word in ("转账", "转给", "汇给", "打给", "付款", "转")):
            return self._transfer(text, state)
        return self._answer(
            "我还没识别出具体意图。可以试试「转 88 元给周明」、"
            "「分析本月账单」或「锁定信用卡」。"
        )

    def confirm(self, action_id):
        with self._lock:
            action = self._pending.pop(action_id, None)
        if not action:
            return {"ok": False, "message": "这项待确认操作不存在或已处理，请重新发起。"}
        try:
            result = self.bank.execute(action)
        except ValueError as error:
            return {"ok": False, "message": str(error)}
        return {"ok": True, "message": result, "state": self.bank.get_state()}

    def reject(self, action_id):
        with self._lock:
            action = self._pending.pop(action_id, None)
        if not action:
            return {"ok": False, "message": "这项待确认操作不存在或已处理。"}
        return {"ok": True, "message": "已取消操作，账户数据没有变化。"}

    def _answer(self, reply, **extra):
        return {"reply": reply, "plan": [], "tools": [], **extra}

    def _is_birthday_request(self, text):
        return "生日" in text and any(
            word in text for word in ("花", "蛋糕", "礼物", "锁定", "预留", "安排")
        )

    def _birthday(self, text, state):
        birthday = _date_from_text(text, state["profile"]["partner_birthday"])
        if not birthday:
            return self._answer("生日日期格式不正确，请使用「11月5日」或「2026-11-05」。")
        if date.fromisoformat(birthday) < date.today():
            return self._answer("生日日期已过，请提供一个未来的日期。")
        parsed_amount = parse_amount(text)
        amount = 100000 if parsed_amount is None else parsed_amount
        if amount <= 0:
            return self._answer("生日预留金额必须大于 0 元。")
        recipient = next(
            (person["name"] for person in state["contacts"] if any(
                alias in text for alias in [person["name"], *person["aliases"]]
            )),
            "林小满",
        )
        gifts = ["鲜花", "蛋糕"]
        payload = {
            "birthday": birthday,
            "amount_cents": amount,
            "recipient": recipient,
            "gifts": gifts,
        }
        return self._propose(
            "birthday_bundle",
            payload,
            f"我会在 {birthday} 为{recipient}从日常账户预留 {money(amount)}，"
            f"并提前两天设置鲜花和蛋糕提醒。",
            [
                "核对联系人生日与提醒日期",
                f"检查日常账户可用余额是否覆盖 {money(amount)}",
                "建立生日资金预留及礼物提醒",
            ],
            risk="预留金额会从日常可用余额中扣除；礼物提醒不会自动下单。",
        )

    def _split_aa(self, text, state):
        amount = parse_amount(text)
        people_match = re.search(r"(\d+)\s*人", text)
        people = int(people_match.group(1)) if people_match else None
        if people is None:
            people = next(
                (
                    value
                    for phrase, value in (
                        ("两人", 2),
                        ("二人", 2),
                        ("三人", 3),
                        ("四人", 4),
                        ("五人", 5),
                        ("六人", 6),
                        ("七人", 7),
                        ("八人", 8),
                        ("九人", 9),
                        ("十人", 10),
                    )
                    if phrase in text
                ),
                None,
            )
        if amount is None or people is None:
            return self._answer("创建 AA 收款单需要总金额和人数，例如「把 306 元拆成 3 人 AA」。")
        if amount <= 0:
            return self._answer("AA 总额必须大于 0 元。")
        mentioned = self._mentioned_contacts(text, state)
        if people < 2:
            return self._answer("AA 人数至少为 2 人，人数包含你本人。")
        required_contacts = people - 1
        if len(mentioned) < required_contacts:
            missing = required_contacts - len(mentioned)
            return self._answer(
                f"总人数包含你本人，还需提供 {missing} 位收款联系人的姓名、手机号或备注，"
                "我再生成 AA 收款单。"
            )
        participants = [contact["name"] for contact in mentioned[:required_contacts]]
        return self._propose(
            "split_aa",
            {
                "amount_cents": amount,
                "people": people,
                "participants": participants,
                "title": "聚餐 AA 收款",
            },
            f"我会创建总额 {money(amount)}、{people} 人的 AA 收款单，"
            f"其中包含你本人和 {len(participants)} 位收款人；仅生成收款单，不会自动催款。",
            [
                "解析账单总额与参与人数",
                "计算每位参与人的应付金额",
                "生成待发送的 AA 收款单",
            ],
            risk="收款请求需要你之后自行发送，当前不会发起真实扣款。",
        )

    def _bill_analysis(self, text, state):
        if "年报" in text or "年度" in text:
            year_prefix = date.today().strftime("%Y")
            year_transactions = [
                item
                for item in state["transactions"]
                if item["date"].startswith(year_prefix)
                and item["direction"] == "out"
                and item["category"] not in ("转账", "理财")
            ]
            year_categories = {}
            for item in year_transactions:
                year_categories[item["category"]] = (
                    year_categories.get(item["category"], 0) + item["amount_cents"]
                )
            categories = [
                {"name": name, "amount_cents": amount}
                for name, amount in sorted(
                    year_categories.items(), key=lambda entry: entry[1], reverse=True
                )
            ]
            total = sum(item["amount_cents"] for item in year_transactions)
            period = f"{date.today().year} 年度已记录演示数据"
        else:
            categories = state["monthly_categories"]
            total = state["monthly_spending_cents"]
            period = f"{date.today():%Y-%m} 月度演示汇总"
        category_lines = "、".join(
            f"{item['name']} {money(item['amount_cents'])}" for item in categories
        ) or "本月暂无分类支出"
        anomaly_lines = "；".join(
            f"{item['merchant']} {money(item['amount_cents'])}（{item['note']}）"
            for item in state["anomalies"]
        ) or "暂未发现标记的异常交易"
        return self._answer(
            f"{period}：记录的非转账支出共 {money(total)}。"
            f"分类为：{category_lines}。异常核验提示：{anomaly_lines}。"
            "异常标记仅用于演示，不代表已确认欺诈。",
            intent="bill_analysis",
            plan=["读取演示交易", "按类别汇总支出", "标记需人工核对的高额交易"],
            tools=[
                {"name": "transactions.list", "status": "完成"},
                {"name": "analytics.monthly_summary", "status": "完成"},
            ],
            data={
                "categories": categories,
                "anomalies": state["anomalies"],
                "total_cents": total,
            },
        )

    def _subscriptions(self, text, state):
        active = [
            item for item in state["subscriptions"] if item["status"] == "active"
        ]
        target = next(
            (item for item in active if item["name"] in text or item["category"] in text),
            None,
        )
        if any(word in text for word in ("取消", "退订", "停止")):
            if not target:
                return self._answer("请告诉我想取消哪项订阅，例如「取消云听音乐订阅」。")
            return self._propose(
                "subscription_cancel",
                {"subscription_id": target["id"]},
                f"我会取消「{target['name']}」的后续续费，当前订阅不会立即退款。",
                ["核对订阅名称与续费状态", "停止后续自动续费"],
                risk="此操作只模拟停止未来续费，不会处理退款。",
            )
        if any(word in text for word in ("提醒", "续费")) and target:
            return self._propose(
                "subscription_reminder",
                {"subscription_id": target["id"]},
                f"我会在 {target['next_charge']} 提醒你「{target['name']}」续费。",
                ["读取订阅续费日期", "创建续费提醒"],
            )
        total = sum(item["amount_cents"] for item in active)
        rows = "；".join(
            f"{item['name']} {money(item['amount_cents'])}/{item['period']}，"
            f"下次扣费 {item['next_charge']}"
            for item in active
        )
        return self._answer(
            f"识别到 {len(active)} 项活跃订阅，按月合计 {money(total)}：{rows}。"
            "可说「提醒我云听音乐续费」或「取消视频会员」。",
            intent="subscription_analysis",
            plan=["从演示订阅清单中识别周期扣费", "汇总活跃订阅费用"],
            tools=[{"name": "subscriptions.list", "status": "完成"}],
            data={"subscriptions": active, "monthly_total_cents": total},
        )

    def _cards(self, text, state):
        card = next(
            (
                item for item in state["cards"]
                if item["name"] in text or item["number"][-4:] in text
            ),
            state["cards"][0],
        )
        if any(word in text for word in ("挂失", "盗刷", "丢了", "丢失", "锁定", "冻结")):
            if card["status"] == "locked":
                return self._answer(f"{card['name']} 当前已经锁定。")
            return self._propose(
                "card_lock",
                {"card_id": card["id"]},
                f"我会立即锁定 {card['name']}（{card['number']}），锁定后新交易将被拒绝。",
                ["核对目标卡片", "检查卡片状态", "提交锁卡操作"],
                risk="演示锁卡会立即改变卡片状态，解锁需再次确认。",
            )
        if any(word in text for word in ("解锁", "恢复", "解除冻结")):
            if card["status"] == "active":
                return self._answer(f"{card['name']} 当前已经处于正常状态。")
            return self._propose(
                "card_unlock",
                {"card_id": card["id"]},
                f"我会解锁 {card['name']}（{card['number']}）。",
                ["核对目标卡片", "提交解锁操作"],
                risk="请确认卡片由你本人持有且安全。",
            )
        if (
            "额度" in text
            or "限额" in text
            or "单日" in text
            or ("交易" in text and "限制" in text)
        ):
            amount = parse_amount(text)
            if any(word in text for word in ("交易限制", "单笔", "每日", "日限额", "单日")):
                if amount is not None:
                    if amount <= 0:
                        return self._answer("单日交易限额必须大于 0 元。")
                    return self._propose(
                        "card_daily_limit",
                        {"card_id": card["id"], "limit_cents": amount},
                        f"我会将 {card['name']}单日交易限额调整为 {money(amount)}。",
                        ["核对卡片及新单日限额", "提交交易限额调整"],
                        risk="单日限额变更会影响后续卡片交易，请确认金额正确。",
                    )
                return self._answer(
                    f"{card['name']}当前单日交易限额为 "
                    f"{money(card['daily_limit_cents'])}。可说「单日限额调到 3000 元」。"
                )
            if amount is None:
                return self._answer(
                    f"{card['name']}当前总额度为 {money(card['limit_cents'])}，"
                    f"已使用 {money(card['used_cents'])}。可以说「信用卡额度调到 60000 元」。"
                )
            if amount <= 0:
                return self._answer("卡片额度必须大于 0 元。")
            return self._propose(
                "card_limit",
                {"card_id": card["id"], "limit_cents": amount},
                f"我会将 {card['name']}额度调整为 {money(amount)}。",
                ["校验新额度大于当前已用额度", "提交额度调整"],
                risk="额度变更需遵循发卡机构审批规则；演示环境会即时更新。",
            )
        if any(word in text for word in ("申请", "办一张", "新卡")):
            return self._propose(
                "card_apply",
                {},
                "我会为你申请一张演示用澄明数字卡，虚拟卡将添加到卡片列表。",
                ["检查卡片申请入口", "创建演示数字卡"],
                risk="本地演示不会向银行提交真实申请。",
            )
        cards = "；".join(
            f"{item['name']}（{item['number']}）状态："
            f"{'正常' if item['status'] == 'active' else '已锁定'}，"
            f"额度 {money(item['limit_cents'])}"
            for item in state["cards"]
        )
        return self._answer(
            f"当前有 {len(state['cards'])} 张卡：{cards}。"
            "可说「锁定白金卡」「解锁白金卡」或「额度调到 60000 元」。",
            intent="card_overview",
            plan=["读取卡片状态与额度"],
            tools=[{"name": "cards.list", "status": "完成"}],
        )

    def _investments(self, text, state):
        fund = next(
            (item for item in state["funds"] if item["name"] in text),
            None,
        )
        if any(word in text for word in ("赎回", "卖出")):
            if not fund:
                return self._answer("请指定要赎回的产品名称，例如「赎回澄明短债精选 500 元」。")
            amount = parse_amount(text)
            if amount is None:
                return self._answer(
                    f"「{fund['name']}」当前持仓 {money(fund['holding_cents'])}，"
                    "请补充赎回金额。"
                )
            return self._propose(
                "fund_redeem",
                {"fund_id": fund["id"], "amount_cents": amount},
                f"我会从「{fund['name']}」赎回 {money(amount)} 至日常账户。",
                ["核对基金名称与当前持仓", "提交演示赎回"],
                risk="基金赎回到账时间和净值以真实产品规则为准；此处仅更新模拟数据。",
            )
        if any(word in text for word in ("申购", "买入", "购买")):
            if not fund:
                return self._answer("请指定要申购的产品名称，例如「申购澄明短债精选 500 元」。")
            amount = parse_amount(text)
            if amount is None:
                return self._answer("请补充申购金额，例如「申购澄明短债精选 500 元」。")
            if amount <= 0:
                return self._answer("申购金额必须大于 0 元。")
            return self._propose(
                "fund_purchase",
                {"fund_id": fund["id"], "amount_cents": amount},
                f"我会使用日常账户申购「{fund['name']}」{money(amount)}。",
                ["核对产品起投金额和余额", "提交演示申购"],
                risk="历史年化展示不代表未来收益；基金净值可能下跌。",
            )
        products = sorted(
            state["funds"],
            key=lambda item: (
                abs(item["risk"] - 2) * 0.08
                + item["volatility"] * 0.5
                - item["annual_return"] * 0.1
            ),
        )
        lines = "；".join(
            f"{item['name']}，风险 {item['risk']}/5，"
            f"演示年化 {item['annual_return']:.1%}，"
            f"波动率 {item['volatility']:.1%}，持仓 {money(item['holding_cents'])}"
            for item in products
        )
        return self._answer(
            f"按你的{state['profile']['risk_profile']}风险偏好排序：{lines}。"
            "以上为静态演示数据，不构成投资建议或未来收益承诺。",
            intent="investment_comparison",
            plan=["读取演示产品风险与历史指标", "按稳健型偏好排序产品"],
            tools=[{"name": "portfolio.compare", "status": "完成"}],
            data={"funds": products},
        )

    def _transfer(self, text, state):
        amount = parse_amount(text)
        recipient = self._mentioned_contacts(text, state)
        if not recipient:
            return self._answer("我没有匹配到收款人。请使用已登记联系人姓名，例如「转 88 元给周明」。")
        if amount is None:
            return self._answer("请补充转账金额，例如「转 88 元给周明」。")
        if amount <= 0:
            return self._answer("转账金额必须大于 0 元。")
        if amount > state["checking_available_cents"]:
            return self._answer(
                f"日常账户可用余额为 {money(state['checking_available_cents'])}，"
                "这笔转账超出可用余额，未创建操作。"
            )
        recipient_name = recipient[0]["name"]
        scheduled_date = _date_from_text(text)
        explicit_date = re.search(
            r"(?:20\d{2}[-/年]\d{1,2}|(?:\d{1,2}月)?\d{1,2}日)", text
        )
        if scheduled_date and date.fromisoformat(scheduled_date) < date.today():
            return self._answer("预约日期已过，请提供今天或未来的日期。")
        if scheduled_date and (
            explicit_date
            or any(word in text for word in ("预约", "定时", "明天", "后天", "大后天"))
        ):
            kind = "scheduled_transfer"
            payload = {
                "recipient": recipient_name,
                "amount_cents": amount,
                "date": scheduled_date,
                "note": "自然语言预约转账",
            }
            summary = (
                f"我会预约在 {scheduled_date} 从日常账户向 {recipient_name} "
                f"转出 {money(amount)}。"
            )
            steps = ["核对联系人与预约日期", "检查日常账户可用余额", "创建预约转账"]
        else:
            kind = "transfer"
            payload = {
                "recipient": recipient_name,
                "amount_cents": amount,
                "note": "自然语言转账",
            }
            summary = f"我会从日常账户向 {recipient_name} 转出 {money(amount)}。"
            steps = ["核对收款人姓名与登记手机号", "检查日常账户可用余额", "提交转账"]
        return self._propose(
            kind,
            payload,
            summary,
            steps,
            risk="提交后会改变模拟账户余额；请确认收款人和金额无误。",
        )

    def _mentioned_contacts(self, text, state):
        found = []
        for contact in state["contacts"]:
            if any(
                value in text
                for value in [
                    contact["name"],
                    contact["phone"],
                    *contact["aliases"],
                    contact.get("note", ""),
                ]
            ):
                found.append(contact)
        return found

    def _propose(self, kind, payload, summary, steps, risk=None):
        action_id = uuid.uuid4().hex
        with self._lock:
            self._pending[action_id] = {"kind": kind, "payload": payload}
        return {
            "reply": summary,
            "intent": kind,
            "plan": steps,
            "tools": [{"name": "banking." + kind, "status": "待确认"}],
            "pending_action": {
                "id": action_id,
                "kind": kind,
                "summary": summary,
                "risk": risk,
            },
        }
