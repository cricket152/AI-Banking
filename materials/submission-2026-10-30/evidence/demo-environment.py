"""仅用于本轮独立浏览器验收，不读取 .env 或修改运行库。"""

import getpass
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import uvicorn

from ai_banking.app import create_app
from ai_banking.banking.workflows import conversation_plan
from ai_banking.config import Settings
from ai_banking.tracing import CONVERSATION


def create_demo_app(password, database=Path(".local/materials-reproduction-2026-10-30.sqlite3")):
    app = create_app(
        Settings(
            database=database,
            origin="http://127.0.0.1:8003",
            local_http=True,
            agent_mode="model",
            model="脚本化演示（不调用供应商）",
            model_key="qa-fixture-not-real",
            trace_enabled=False,
        )
    )
    app.state.store.initialize()
    with app.state.store.transaction() as db:
        exists = db.execute("SELECT 1 FROM users WHERE username='reviewer'").fetchone()
    if not exists:
        app.state.auth.create_user("reviewer", password)
        with app.state.store.transaction() as db:
            account = db.execute(
                "SELECT a.id FROM accounts a JOIN users u ON a.owner_id=u.id "
                "WHERE u.username='reviewer' AND a.kind='checking'"
            ).fetchone()[0]
            now = datetime.fromtimestamp(time.time(), UTC)
            for days, amount, merchant, category in [
                (65, -990, "周期演示服务", "服务"),
                (35, -990, "周期演示服务", "服务"),
                (5, -990, "周期演示服务", "服务"),
                (1, -150000, "演示大额购物", "购物"),
                (45, -1000, "演示餐厅", "餐饮"),
                (40, -2000, "演示餐厅", "餐饮"),
                (35, -3000, "演示餐厅", "餐饮"),
                (2, -20000, "演示餐厅", "餐饮"),
            ]:
                db.execute(
                    "INSERT INTO entries VALUES (?,?,?,?,?,?)",
                    (
                        uuid4().hex,
                        account,
                        amount,
                        merchant,
                        category,
                        (now - timedelta(days=days)).isoformat(),
                    ),
                )
                db.execute(
                    "UPDATE accounts SET balance_minor=balance_minor+? WHERE id=?",
                    (amount, account),
                )

    async def scripted_answer(context, question, history):
        agent = app.state.agent
        plan = conversation_plan(app.state.bank, context, CONVERSATION.get())
        if not plan:
            agent.tool(context, "find_payees", {"query": "张明"})
            return "脚本化验收：发现两位同名张明，请按备注和尾号选择。", ["find_payees"]
        for step in plan["steps"]:
            if step["state"] == "not_started":
                tool = (
                    "prepare_transfer"
                    if step["kind"] == "transfer"
                    else "prepare_subscription_cancellation"
                )
                result = agent.tool(context, tool, step["arguments"])
                if result.get("error"):
                    return "脚本化验收：后端拒绝了操作，请核对原操作。", [tool]
                return "脚本化验收：已准备下一步，尚待独立确认。请核对后端确认单。", [tool]
            if step["state"] != "succeeded":
                agent.tool(context, "get_operation", {"operation_id": step["operation_id"]})
                return "脚本化验收：原操作尚未成功，不执行后续步骤。", ["get_operation"]
        return "脚本化验收：订阅取消与转账均已核对成功，方案完成。", []

    app.state.agent.model_answer = scripted_answer
    return app


if __name__ == "__main__":
    demo_password = getpass.getpass("设置本次虚构账号密码（不进入模型）：")
    uvicorn.run(create_demo_app(demo_password), host="127.0.0.1", port=8003, access_log=False)
