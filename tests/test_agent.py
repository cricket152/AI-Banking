import sys
import unittest
from datetime import date
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_banking.agent import BankingAgent, parse_amount
from ai_banking.domain import BankingDemo


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.bank = BankingDemo()
        self.agent = BankingAgent(self.bank)

    def test_amount_parser_ignores_dates_and_reads_money(self):
        self.assertEqual(parse_amount("安排生日：11月5日锁定1000元"), 100000)
        self.assertEqual(parse_amount("转账 1,280.50 元"), 128050)
        self.assertEqual(parse_amount("￥88"), 8800)
        self.assertEqual(parse_amount("转 -88 元"), -8800)
        self.assertIsNone(parse_amount("转给 13800138001"))

    def test_transfer_waits_for_confirmation_and_cannot_repeat(self):
        before = self.bank.get_state()["checking_available_cents"]
        proposal = self.agent.handle("转 88 元给周明")
        self.assertEqual(proposal["intent"], "transfer")
        self.assertEqual(self.bank.get_state()["checking_available_cents"], before)

        result = self.agent.confirm(proposal["pending_action"]["id"])
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["state"]["checking_available_cents"], before - 8800
        )
        self.assertFalse(self.agent.confirm(proposal["pending_action"]["id"])["ok"])

    def test_transfer_resolves_phone_and_contact_note(self):
        by_phone = self.agent.handle("给 13800138001 转 50 元")
        self.assertIn("周明", by_phone["reply"])
        by_note = self.agent.handle("转 50 元给项目协作")
        self.assertIn("周明", by_note["reply"])

    def test_rejected_transfer_does_not_change_balance(self):
        before = self.bank.get_state()["checking_available_cents"]
        proposal = self.agent.handle("转 88 元给妈妈")
        result = self.agent.reject(proposal["pending_action"]["id"])
        self.assertTrue(result["ok"])
        self.assertEqual(self.bank.get_state()["checking_available_cents"], before)

    def test_insufficient_transfer_is_not_proposed(self):
        proposal = self.agent.handle("转 999999 元给周明")
        self.assertNotIn("pending_action", proposal)
        self.assertIn("超出可用余额", proposal["reply"])

    def test_scheduled_transfer_does_not_debit_now(self):
        before = self.bank.get_state()["checking_available_cents"]
        proposal = self.agent.handle("预约明天转 88 元给周明")
        self.assertEqual(proposal["intent"], "scheduled_transfer")
        self.agent.confirm(proposal["pending_action"]["id"])
        state = self.bank.get_state()
        self.assertEqual(state["checking_available_cents"], before)
        self.assertEqual(len(state["scheduled_transfers"]), 1)

    def test_due_scheduled_transfer_executes_when_state_is_read(self):
        before = self.bank.get_state()["checking_available_cents"]
        self.bank.execute(
            {
                "kind": "scheduled_transfer",
                "payload": {
                    "recipient": "周明",
                    "amount_cents": 5000,
                    "date": date.today().isoformat(),
                    "note": "到期测试",
                },
            }
        )
        state = self.bank.get_state()
        self.assertEqual(state["scheduled_transfers"][0]["status"], "completed")
        self.assertEqual(state["checking_available_cents"], before - 5000)

    def test_due_scheduled_transfer_fails_if_balance_was_spent(self):
        balance = self.bank.get_state()["checking_available_cents"]
        today = date.today().isoformat()
        self.bank.execute(
            {
                "kind": "scheduled_transfer",
                "payload": {
                    "recipient": "周明",
                    "amount_cents": 5000,
                    "date": today,
                    "note": "余额不足测试",
                },
            }
        )
        self.bank.execute(
            {
                "kind": "transfer",
                "payload": {
                    "recipient": "妈妈",
                    "amount_cents": balance,
                    "note": "用完余额",
                },
            }
        )
        state = self.bank.get_state()
        self.assertEqual(state["scheduled_transfers"][0]["status"], "failed")
        self.assertIn("余额不足", state["scheduled_transfers"][0]["error"])

    def test_aa_split_requires_all_recipients_and_balances_to_total(self):
        incomplete = self.agent.handle("把 100.01 元拆成 3 人 AA，邀请周明")
        self.assertNotIn("pending_action", incomplete)
        self.assertIn("还需提供 1 位", incomplete["reply"])

        proposal = self.agent.handle(
            "把 100.01 元拆成 3 人 AA，邀请周明和妈妈"
        )
        self.agent.confirm(proposal["pending_action"]["id"])
        request = self.bank.get_state()["collection_requests"][0]
        self.assertEqual(
            request["payer_share_cents"]
            + sum(person["amount_cents"] for person in request["participants"]),
            10001,
        )
        self.assertEqual(len(request["participants"]), 2)

    def test_aa_split_accepts_chinese_count_and_rejects_negative_total(self):
        proposal = self.agent.handle("把 306 元拆成三人 AA，邀请周明和妈妈")
        self.assertEqual(proposal["intent"], "split_aa")
        negative = self.agent.handle("把 -30 元拆成三人 AA，邀请周明和妈妈")
        self.assertNotIn("pending_action", negative)
        self.assertIn("必须大于 0", negative["reply"])

    def test_bill_analysis_reports_categories_and_anomaly(self):
        response = self.agent.handle("分析本月账单并检查异常交易")
        self.assertEqual(response["intent"], "bill_analysis")
        self.assertGreater(response["data"]["total_cents"], 0)
        self.assertTrue(response["data"]["anomalies"])
        self.assertIn("不代表已确认欺诈", response["reply"])

    def test_annual_report_uses_year_to_date_data(self):
        response = self.agent.handle("生成年度账单年报")
        self.assertIn("年度已记录演示数据", response["reply"])
        self.assertIn("记录的非转账支出共", response["reply"])

    def test_investment_purchase_requires_confirmation(self):
        before = self.bank.get_state()
        proposal = self.agent.handle("申购澄明短债精选 500 元")
        self.assertEqual(proposal["intent"], "fund_purchase")
        self.assertEqual(
            self.bank.get_state()["checking_available_cents"],
            before["checking_available_cents"],
        )
        result = self.agent.confirm(proposal["pending_action"]["id"])
        self.assertTrue(result["ok"])
        after = result["state"]
        self.assertEqual(
            after["checking_available_cents"],
            before["checking_available_cents"] - 50000,
        )

    def test_investment_comparison_includes_risk_disclaimer(self):
        response = self.agent.handle("比较适合稳健型的理财产品")
        self.assertEqual(response["intent"], "investment_comparison")
        self.assertEqual(response["data"]["funds"][0]["risk"], 2)
        self.assertIn("不构成投资建议", response["reply"])

    def test_card_lock_daily_limit_and_unlock(self):
        lock = self.agent.handle("锁定澄明白金卡")
        self.assertEqual(lock["intent"], "card_lock")
        self.agent.confirm(lock["pending_action"]["id"])
        self.assertEqual(self.bank.get_state()["cards"][0]["status"], "locked")

        unlock = self.agent.handle("解锁澄明白金卡")
        self.assertEqual(unlock["intent"], "card_unlock")
        self.agent.confirm(unlock["pending_action"]["id"])

        limit = self.agent.handle("澄明白金卡单日交易限额调到 3000 元")
        self.assertEqual(limit["intent"], "card_daily_limit")
        self.agent.confirm(limit["pending_action"]["id"])
        self.assertEqual(
            self.bank.get_state()["cards"][0]["daily_limit_cents"], 300000
        )

    def test_card_limit_cannot_fall_below_used_amount(self):
        proposal = self.agent.handle("信用卡额度调到 100 元")
        result = self.agent.confirm(proposal["pending_action"]["id"])
        self.assertFalse(result["ok"])
        self.assertIn("不能低于", result["message"])

    def test_card_application_adds_demo_card_after_confirmation(self):
        proposal = self.agent.handle("申请一张新卡")
        self.assertEqual(proposal["intent"], "card_apply")
        result = self.agent.confirm(proposal["pending_action"]["id"])
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["state"]["cards"]), 3)

    def test_subscription_cancel_and_renewal_reminder(self):
        cancel = self.agent.handle("取消云听音乐订阅")
        self.agent.confirm(cancel["pending_action"]["id"])
        state = self.bank.get_state()
        self.assertEqual(state["subscriptions"][0]["status"], "cancelled")

        reminder = self.agent.handle("提醒我视频会员续费")
        self.agent.confirm(reminder["pending_action"]["id"])
        state = self.bank.get_state()
        self.assertTrue(state["subscriptions"][1]["reminder"])

    def test_birthday_bundle_reserves_money_and_schedules_gift_reminder(self):
        before = self.bank.get_state()
        proposal = self.agent.handle(
            "安排爱人生日：11月5日锁定1000元，提前订鲜花和蛋糕"
        )
        self.assertEqual(proposal["intent"], "birthday_bundle")
        self.assertEqual(proposal["pending_action"]["kind"], "birthday_bundle")
        result = self.agent.confirm(proposal["pending_action"]["id"])
        self.assertTrue(result["ok"])
        after = result["state"]
        self.assertEqual(after["accounts"][0]["held_cents"], 100000)
        self.assertEqual(
            after["checking_available_cents"],
            before["checking_available_cents"] - 100000,
        )
        self.assertEqual(len(after["reminders"]), 1)

    def test_birthday_bundle_rejects_past_date(self):
        response = self.agent.handle(
            "安排生日：2020-01-01 预留 1000 元并订鲜花蛋糕"
        )
        self.assertNotIn("pending_action", response)
        self.assertIn("日期已过", response["reply"])

    def test_unknown_intent_returns_guidance(self):
        response = self.agent.handle("讲个故事")
        self.assertNotIn("pending_action", response)
        self.assertIn("还没识别", response["reply"])


if __name__ == "__main__":
    unittest.main()
