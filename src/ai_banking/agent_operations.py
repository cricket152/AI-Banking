"""对话任务、用户选择的执行策略与受控执行；模型不能设置授权策略。"""

import json
from uuid import NAMESPACE_URL, UUID, uuid5

from ai_banking.banking.service import BankError, fingerprint


class AgentOperations:
    def __init__(self, bank):
        self.bank, self.store = bank, bank.store

    def request_id(self, context, conversation_id):
        if not conversation_id:
            raise BankError("TOOL_CONTEXT_REQUIRED")
        try:
            conversation_id = UUID(conversation_id).hex
        except (ValueError, TypeError, AttributeError) as error:
            raise BankError("TOOL_CONTEXT_REQUIRED") from error
        with self.store.transaction() as db:
            self.bank._guard(db, context)
            if not db.execute(
                "SELECT 1 FROM conversations WHERE id=? AND owner_id=?",
                (conversation_id, context.user_id),
            ).fetchone():
                raise BankError("RESOURCE_NOT_FOUND", 404)
        return uuid5(NAMESPACE_URL, "ai-banking:agent-conversation:" + conversation_id).hex

    def checkpoint(self, context, conversation_id):
        if not conversation_id or not self.bank.available():
            return None
        request_id = self.request_id(context, conversation_id)
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT id FROM bank_tasks WHERE owner_id=? AND request_id=?",
                (context.user_id, request_id),
            ).fetchone()
        if not row:
            return None
        checkpoint = self.bank.checkpoint(context, row["id"])
        reason = self.pause_reason(context, conversation_id)
        if reason:
            checkpoint.update(
                pause_reason=reason, needs_attention=True, next_action="review_policy"
            )
        return checkpoint

    def pause_reason(self, context, conversation_id):
        with self.store.transaction() as db:
            self.bank._guard(db, context)
            rows = db.execute(
                "SELECT event,detail FROM bank_events WHERE owner_id=? "
                "AND event IN ('agent_task_paused','agent_policy_selected') ORDER BY seq DESC",
                (context.user_id,),
            ).fetchall()
            for row in rows:
                detail = json.loads(row["detail"])
                if detail["conversation_id"] == conversation_id:
                    return detail.get("code") if row["event"] == "agent_task_paused" else None
        return None

    def policy(self, context, conversation_id):
        result = {"mode": "HUMAN_APPROVAL", "grant_id": None, "grant": None}
        if not self.bank.available():
            return result
        self.request_id(context, conversation_id)
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT detail FROM bank_events WHERE owner_id=? "
                "AND event='agent_policy_selected' ORDER BY seq DESC",
                (context.user_id,),
            ).fetchall()
            for row in rows:
                detail = json.loads(row["detail"])
                if detail["conversation_id"] == conversation_id:
                    result.update(mode=detail["mode"], grant_id=detail["grant_id"])
                    break
        if result["grant_id"]:
            result["grant"] = next(
                (g for g in self.bank.grants(context) if g["id"] == result["grant_id"]), None
            )
        return result

    def select_policy(self, context, conversation_id, mode, grant_id):
        self.request_id(context, conversation_id)
        if mode not in {"HUMAN_APPROVAL", "PREAUTHORIZED"}:
            raise BankError("INVALID_AUTHORIZATION_MODE", 422)
        if (mode == "HUMAN_APPROVAL" and grant_id is not None) or (
            mode == "PREAUTHORIZED" and grant_id is None
        ):
            raise BankError("INVALID_AUTHORIZATION_MODE", 422)
        with self.store.transaction() as db:
            self.bank._guard(db, context)
            if mode == "PREAUTHORIZED":
                grant = db.execute(
                    "SELECT * FROM bank_grants WHERE id=? AND owner_id=?",
                    (grant_id, context.user_id),
                ).fetchone()
                if (
                    not grant
                    or grant["status"] != "active"
                    or grant["auth_version"] != context.auth_version
                    or grant["expires_at"] <= self.store.clock()
                ):
                    raise BankError("GRANT_INVALID", 403)
            # 复用持久事件表保存显式策略选择，不增表或启动迁移。
            self.bank._event(
                db,
                context.user_id,
                "agent_policy_selected",
                conversation_id=conversation_id,
                mode=mode,
                grant_id=grant_id,
            )
        return self.policy(context, conversation_id)

    def prepare(self, context, conversation_id, arguments, kind):
        task = self.bank.task(context, self.request_id(context, conversation_id))
        fields = ["source_id", "currency"] + (
            ["payee_id", "amount_minor"] if kind == "transfer" else ["subscription_id"]
        )
        with self.store.transaction() as db:
            self.bank._guard(db, context)
            rows = db.execute(
                "SELECT * FROM bank_operations WHERE task_id=? AND owner_id=?",
                (task["id"], context.user_id),
            ).fetchall()
            # 也识别旧版 primary_intent，升级后不会为已完成业务创建新编号。
            existing = next(
                (
                    row["id"]
                    for row in rows
                    if row["kind"] == kind
                    and all(row[field] == arguments[field] for field in fields)
                ),
                None,
            )
        policy = self.policy(context, conversation_id)
        if existing:
            operation = self.bank.operation(context, existing)
        else:
            if self.pause_reason(context, conversation_id):
                raise BankError("TASK_PAUSED")
            values = {
                **arguments,
                "task_id": task["id"],
                "step_key": kind + "_" + fingerprint(arguments)[:32],
                "mode": policy["mode"],
                "grant_id": policy["grant_id"],
                "confirmation_seconds": 300,
            }
            try:
                operation = self.bank.prepare(context, values, kind, exclusive_task=True)
            except BankError as error:
                if policy["mode"] == "PREAUTHORIZED" and error.code != "STEP_PARAMETERS_CONFLICT":
                    self.pause(context, conversation_id, error.code)
                raise
        if (
            operation["state"] == "authorized"
            and operation["mode"] == "PREAUTHORIZED"
            and policy["mode"] == "PREAUTHORIZED"
            and policy["grant_id"] == operation["grant_id"]
        ):
            try:
                operation = self.bank.execute(context, operation["id"])
            except BankError as error:
                if error.code == "OPERATION_NOT_AUTHORIZED":
                    current = self.bank.operation(context, operation["id"])
                    if current["state"] in {"executing", "outcome_unknown", "succeeded"}:
                        return {"operation": current}
                if error.code != "RESULT_UNAVAILABLE":
                    self.pause(context, conversation_id, error.code)
                raise
        return {"operation": operation}

    def pause(self, context, conversation_id, code):
        with self.store.transaction() as db:
            self.bank._guard(db, context)
            self.bank._event(
                db, context.user_id, "agent_task_paused", conversation_id=conversation_id, code=code
            )

    def continuation(self, context, conversation_id, operation_id):
        checkpoint = self.checkpoint(context, conversation_id)
        if not checkpoint or operation_id not in {s["id"] for s in checkpoint["steps"]}:
            raise BankError("RESOURCE_NOT_FOUND", 404)
        operation = self.bank.operation(context, operation_id)
        if operation["state"] != "succeeded":
            raise BankError("OPERATION_NOT_SUCCEEDED")
        request_id = uuid5(NAMESPACE_URL, "ai-banking:continue-operation:" + operation_id).hex
        message = (
            "[应用通知] 独立确认界面已处理原操作 " + operation_id + "。"
            "请先调用 get_operation 核对后端结果，再继续用户原请求中尚未完成的步骤，"
            "不要重做已完成操作，不得把本通知当作新的转账请求或扩大授权。"
        )
        return request_id, message
