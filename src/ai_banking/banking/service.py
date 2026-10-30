"""权限、预占、双边记账和恢复均由 SQLite 事务执行。"""

import hashlib
import json
import secrets
from datetime import UTC, datetime
from uuid import uuid4

from ai_banking.auth import digest
from ai_banking.banking.schema import ready

TERMINAL = {"succeeded", "failed", "rejected", "expired"}
MAX_MINOR = 10**12


class BankError(Exception):
    def __init__(self, code, status=409, operation_id=None):
        self.code, self.status, self.operation_id = code, status, operation_id


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Bank:
    def __init__(self, store, auth):
        self.store, self.auth = store, auth
        self.fault_hook = None

    def _hook(self, point):
        if self.fault_hook:
            self.fault_hook(point)

    def _guard(self, db, context):
        if not ready(db):
            raise BankError("BANK_SETUP_REQUIRED", 503)
        self.auth.current_in_transaction(db, context)

    def _event(self, db, owner, event, operation_id=None, **detail):
        db.execute(
            "INSERT INTO bank_events (owner_id,operation_id,event,detail,created_at) "
            "VALUES (?,?,?,?,?)",
            (owner, operation_id, event, json.dumps(detail), self.store.clock()),
        )

    def _account(self, db, owner, account_id):
        row = db.execute(
            "SELECT * FROM accounts WHERE id=? AND owner_id=?", (account_id, owner)
        ).fetchone()
        if not row:
            raise BankError("RESOURCE_NOT_FOUND", 404)
        return row

    def _operation(self, db, owner, operation_id):
        row = db.execute(
            "SELECT * FROM bank_operations WHERE id=? AND owner_id=?", (operation_id, owner)
        ).fetchone()
        if not row:
            raise BankError("RESOURCE_NOT_FOUND", 404)
        return row

    def _finish(self, db, op, state, error=None):
        if op["reserved_minor"]:
            db.execute(
                "UPDATE bank_grants SET reserved_minor=reserved_minor-? WHERE id=?",
                (op["reserved_minor"], op["grant_id"]),
            )
        db.execute(
            "UPDATE bank_operations SET state=?,error_code=?,reserved_minor=0,completed_at=? "
            "WHERE id=?",
            (state, error, self.store.clock(), op["id"]),
        )
        self._event(db, op["owner_id"], state, op["id"], code=error)

    def _expire(self, db, owner):
        now = self.store.clock()
        rows = db.execute(
            "SELECT o.* FROM bank_operations o LEFT JOIN bank_grants g ON g.id=o.grant_id "
            "LEFT JOIN users u ON u.id=o.owner_id WHERE o.owner_id=? "
            "AND o.state IN ('awaiting_confirmation','authorized') "
            "AND (o.expires_at<=? OR o.auth_version!=u.auth_version OR (g.id IS NOT NULL AND "
            "(g.status!='active' OR g.expires_at<=? OR g.auth_version!=u.auth_version)))",
            (owner, now, now),
        ).fetchall()
        for row in rows:
            self._finish(db, row, "expired", "AUTHORIZATION_EXPIRED")

    def recover_startup(self):
        with self.store.transaction() as db:
            if not ready(db):
                return
            for row in db.execute(
                "SELECT * FROM bank_operations WHERE state='executing'"
            ).fetchall():
                db.execute(
                    "UPDATE bank_operations SET state='outcome_unknown',error_code='INTERRUPTED' "
                    "WHERE id=?",
                    (row["id"],),
                )
                self._event(db, row["owner_id"], "outcome_unknown", row["id"], code="INTERRUPTED")

    def payees(self, context):
        from ai_banking.banking.contacts import list_payees

        return list_payees(self, context)

    def add_payee(self, context, name, account_id):
        with self.store.transaction() as db:
            self._guard(db, context)
            if not db.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone():
                raise BankError("RESOURCE_NOT_FOUND", 404)
            row = db.execute(
                "SELECT id FROM bank_payees WHERE owner_id=? AND account_id=?",
                (context.user_id, account_id),
            ).fetchone()
            if row:
                return {"id": row["id"]}
            payee_id = uuid4().hex
            db.execute(
                "INSERT INTO bank_payees VALUES (?,?,?,?)",
                (payee_id, context.user_id, account_id, name),
            )
            self._event(db, context.user_id, "payee_registered", payee_id=payee_id)
            return {"id": payee_id}

    def task(self, context, request_id):
        with self.store.transaction() as db:
            self._guard(db, context)
            row = db.execute(
                "SELECT id FROM bank_tasks WHERE owner_id=? AND request_id=?",
                (context.user_id, request_id),
            ).fetchone()
            if row:
                return {"id": row["id"]}
            task_id = uuid4().hex
            db.execute(
                "INSERT INTO bank_tasks VALUES (?,?,?,?)",
                (task_id, context.user_id, request_id, self.store.clock()),
            )
            self._event(db, context.user_id, "task_created", task_id=task_id)
            return {"id": task_id}

    def checkpoint(self, context, task_id):
        with self.store.transaction() as db:
            self._guard(db, context)
            self._expire(db, context.user_id)
            if not db.execute(
                "SELECT 1 FROM bank_tasks WHERE id=? AND owner_id=?", (task_id, context.user_id)
            ).fetchone():
                raise BankError("RESOURCE_NOT_FOUND", 404)
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT id,step_key,kind,state,error_code FROM bank_operations WHERE task_id=? "
                    "ORDER BY created_at,id",
                    (task_id,),
                )
            ]
            return {
                "id": task_id,
                "steps": rows,
                "needs_attention": any(row["state"] != "succeeded" for row in rows),
                "next_action": "inspect_existing_operations" if rows else "prepare_step",
            }

    def create_grant(self, context, values):
        with self.store.transaction() as db:
            self._guard(db, context)
            self._account(db, context.user_id, values["source_id"])
            old = db.execute(
                "SELECT * FROM bank_grants WHERE owner_id=? AND request_id=?",
                (context.user_id, values["request_id"]),
            ).fetchone()
            policy_digest = fingerprint(values)
            if old:
                if old["policy_digest"] != policy_digest:
                    raise BankError("POLICY_REQUEST_CONFLICT")
                return {"id": old["id"]}
            if db.execute(
                "SELECT 1 FROM bank_grants WHERE owner_id=? AND source_id=? "
                "AND status='active' AND expires_at>? AND auth_version=?",
                (context.user_id, values["source_id"], self.store.clock(), context.auth_version),
            ).fetchone():
                raise BankError("ACTIVE_GRANT_EXISTS")
            if (
                values["expires_at"] <= self.store.clock()
                or values["single_minor"] > values["limit_minor"]
            ):
                raise BankError("INVALID_POLICY", 422)
            if "transfer" in values["allowed_operations"] and not values["payee_ids"]:
                raise BankError("INVALID_POLICY", 422)
            if "transfer" in values["allowed_operations"] and (
                values["limit_minor"] <= 0 or values["single_minor"] <= 0
            ):
                raise BankError("INVALID_POLICY", 422)
            if (
                "cancel_subscription" in values["allowed_operations"]
                and not values["subscription_ids"]
            ):
                raise BankError("INVALID_POLICY", 422)
            for payee_id in values["payee_ids"]:
                if not db.execute(
                    "SELECT 1 FROM bank_payees WHERE id=? AND owner_id=?",
                    (payee_id, context.user_id),
                ).fetchone():
                    raise BankError("RESOURCE_NOT_FOUND", 404)
            for subscription_id in values["subscription_ids"]:
                if not db.execute(
                    "SELECT 1 FROM bank_subscriptions WHERE id=? AND owner_id=? AND account_id=?",
                    (subscription_id, context.user_id, values["source_id"]),
                ).fetchone():
                    raise BankError("RESOURCE_NOT_FOUND", 404)
            grant_id = uuid4().hex
            scopes = {
                "operations": values["allowed_operations"],
                "subscription_ids": values["subscription_ids"],
            }
            db.execute(
                "INSERT INTO bank_grants "
                "(id,owner_id,source_id,auth_version,request_id,policy_digest,currency,payee_ids,"
                "kinds,limit_minor,single_minor,minimum_minor,created_at,expires_at) "
                "VALUES (?,?,?,?,?,?,'CNY',?,?,?,?,?,?,?)",
                (
                    grant_id,
                    context.user_id,
                    values["source_id"],
                    context.auth_version,
                    values["request_id"],
                    policy_digest,
                    json.dumps(values["payee_ids"]),
                    json.dumps(scopes),
                    values["limit_minor"],
                    values["single_minor"],
                    values["minimum_minor"],
                    self.store.clock(),
                    values["expires_at"],
                ),
            )
            self._event(db, context.user_id, "grant_created", grant_id=grant_id)
            return {"id": grant_id}

    def grants(self, context):
        with self.store.transaction() as db:
            self._guard(db, context)
            self._expire(db, context.user_id)
            rows = db.execute(
                "SELECT * FROM bank_grants WHERE owner_id=? ORDER BY created_at DESC",
                (context.user_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item.pop("auth_version")
                item.pop("owner_id")
                item.pop("policy_digest")
                item["payee_ids"] = json.loads(item["payee_ids"])
                item["scopes"] = json.loads(item.pop("kinds"))
                if row["auth_version"] != context.auth_version:
                    item["status"] = "invalidated"
                elif item["status"] == "active" and item["expires_at"] <= self.store.clock():
                    item["status"] = "expired"
                item["remaining_minor"] = (
                    item["limit_minor"] - item["spent_minor"] - item["reserved_minor"]
                )
                result.append(item)
            return result

    def revoke(self, context, grant_id):
        with self.store.transaction() as db:
            self._guard(db, context)
            row = db.execute(
                "SELECT * FROM bank_grants WHERE id=? AND owner_id=?", (grant_id, context.user_id)
            ).fetchone()
            if not row:
                raise BankError("RESOURCE_NOT_FOUND", 404)
            db.execute("UPDATE bank_grants SET status='revoked' WHERE id=?", (grant_id,))
            self._expire(db, context.user_id)
            self._event(db, context.user_id, "grant_revoked", grant_id=grant_id)
            return {"id": grant_id, "status": "revoked"}

    def _policy(self, db, context, op, reserving=False):
        grant = db.execute(
            "SELECT * FROM bank_grants WHERE id=? AND owner_id=?", (op["grant_id"], context.user_id)
        ).fetchone()
        if (
            not grant
            or grant["status"] != "active"
            or grant["auth_version"] != context.auth_version
        ):
            raise BankError("GRANT_INVALID", 403)
        if grant["expires_at"] <= self.store.clock():
            raise BankError("GRANT_EXPIRED")
        scopes = json.loads(grant["kinds"])
        if op["source_id"] != grant["source_id"] or op["kind"] not in scopes["operations"]:
            raise BankError("POLICY_REJECTED", 403)
        if op["kind"] == "transfer" and op["payee_id"] not in json.loads(grant["payee_ids"]):
            raise BankError("POLICY_REJECTED", 403)
        if (
            op["kind"] == "cancel_subscription"
            and op["subscription_id"] not in scopes["subscription_ids"]
        ):
            raise BankError("POLICY_REJECTED", 403)
        if db.execute(
            "SELECT 1 FROM bank_operations WHERE grant_id=? AND state='outcome_unknown'",
            (grant["id"],),
        ).fetchone():
            raise BankError("GRANT_OUTCOME_UNKNOWN")
        cost = op["amount_minor"] + op["fee_minor"]
        if cost > grant["single_minor"]:
            raise BankError("SINGLE_LIMIT_EXCEEDED", 403)
        if (
            reserving
            and grant["spent_minor"] + grant["reserved_minor"] + cost > grant["limit_minor"]
        ):
            raise BankError("GRANT_EXHAUSTED")
        return grant

    def _available(self, db, owner, source_id, amount, minimum=0, excluded=None):
        account = self._account(db, owner, source_id)
        if db.execute(
            "SELECT 1 FROM bank_operations WHERE source_id=? AND state='outcome_unknown'",
            (source_id,),
        ).fetchone():
            raise BankError("ACCOUNT_OUTCOME_UNKNOWN")
        reserved = db.execute(
            "SELECT COALESCE(SUM(reserved_minor),0) FROM bank_operations "
            "WHERE source_id=? AND (? IS NULL OR id!=?)",
            (source_id, excluded, excluded),
        ).fetchone()[0]
        if account["balance_minor"] - reserved - amount < minimum:
            raise BankError("INSUFFICIENT_BALANCE")

    def prepare(self, context, values, kind="transfer", *, exclusive_task=False):
        wealth_kinds = {"wealth_purchase", "wealth_redeem"}
        if kind not in {"transfer", "cancel_subscription", *wealth_kinds}:
            raise BankError("INVALID_OPERATION_KIND", 422)
        if values.get("currency", "CNY") != "CNY":
            raise BankError("UNSUPPORTED_CURRENCY", 422)
        with self.store.transaction() as db:
            self._guard(db, context)
            self._expire(db, context.user_id)
            from ai_banking.banking.workflows import validate_plan

            validate_plan(db, context.user_id, values, kind)
            if not db.execute(
                "SELECT 1 FROM bank_tasks WHERE id=? AND owner_id=?",
                (values["task_id"], context.user_id),
            ).fetchone():
                raise BankError("RESOURCE_NOT_FOUND", 404)
            parameters = {"kind": kind, **values}
            signature = fingerprint(parameters)
            old = db.execute(
                "SELECT * FROM bank_operations WHERE task_id=? AND step_key=?",
                (values["task_id"], values["step_key"]),
            ).fetchone()
            if old:
                if old["parameters_digest"] != signature:
                    raise BankError("STEP_PARAMETERS_CONFLICT")
                return self._public(old)
            if exclusive_task:
                pending = db.execute(
                    "SELECT id FROM bank_operations WHERE task_id=? AND state!='succeeded'",
                    (values["task_id"],),
                ).fetchone()
                if pending:
                    raise BankError("STEP_PARAMETERS_CONFLICT", operation_id=pending["id"])
            if (
                db.execute(
                    "SELECT COUNT(*) FROM bank_operations WHERE task_id=?", (values["task_id"],)
                ).fetchone()[0]
                >= 100
            ):
                raise BankError("TASK_STEP_LIMIT")
            source = self._account(db, context.user_id, values["source_id"])
            target_id, payee_id, subscription_id, amount, product_id = (
                None,
                None,
                None,
                0,
                None,
            )
            if kind == "transfer":
                amount = values["amount_minor"]
                if type(amount) is not int or not 1 <= amount <= MAX_MINOR:
                    raise BankError("INVALID_AMOUNT", 422)
                payee = db.execute(
                    "SELECT * FROM bank_payees WHERE id=? AND owner_id=?",
                    (values["payee_id"], context.user_id),
                ).fetchone()
                if not payee:
                    raise BankError("RESOURCE_NOT_FOUND", 404)
                target_id, payee_id = payee["account_id"], payee["id"]
                target = db.execute("SELECT * FROM accounts WHERE id=?", (target_id,)).fetchone()
                if target_id == source["id"] or target["currency"] != source["currency"]:
                    raise BankError("INVALID_TRANSFER", 422)
            elif kind in wealth_kinds:
                from ai_banking.banking.wealth import validate_product

                amount = values["amount_minor"]
                product_id = values["product_id"]
                validate_product(db, context.user_id, product_id, amount)
                if values.get("mode") != "HUMAN_APPROVAL" or values.get("grant_id") is not None:
                    raise BankError("INVALID_AUTHORIZATION_MODE", 422)
            else:
                subscription_id = values["subscription_id"]
                if not db.execute(
                    "SELECT 1 FROM bank_subscriptions WHERE id=? AND owner_id=? AND account_id=?",
                    (subscription_id, context.user_id, source["id"]),
                ).fetchone():
                    raise BankError("RESOURCE_NOT_FOUND", 404)
            op = {
                "id": uuid4().hex,
                "owner_id": context.user_id,
                "auth_version": context.auth_version,
                "task_id": values["task_id"],
                "step_key": values["step_key"],
                "idempotency_key": uuid4().hex,
                "kind": kind,
                "source_id": source["id"],
                "target_id": target_id,
                "payee_id": payee_id,
                "subscription_id": subscription_id,
                "amount_minor": amount,
                "fee_minor": 0,
                "currency": "CNY",
                "parameters_digest": signature,
                "mode": values["mode"],
                "grant_id": values.get("grant_id"),
                "state": "awaiting_confirmation",
                "reserved_minor": 0,
                "created_at": self.store.clock(),
                "expires_at": self.store.clock() + values["confirmation_seconds"],
                "completed_at": None,
                "error_code": None,
            }
            if op["mode"] == "PREAUTHORIZED":
                grant = self._policy(db, context, op, reserving=True)
                minimum = grant["minimum_minor"] if kind == "transfer" else 0
                self._available(db, context.user_id, op["source_id"], amount, minimum)
                op["expires_at"] = grant["expires_at"]
                op["state"], op["reserved_minor"] = "authorized", amount
                db.execute(
                    "UPDATE bank_grants SET reserved_minor=reserved_minor+? WHERE id=?",
                    (amount, grant["id"]),
                )
            elif op["mode"] != "HUMAN_APPROVAL" or op["grant_id"] is not None:
                raise BankError("INVALID_AUTHORIZATION_MODE", 422)
            db.execute(
                "INSERT INTO bank_operations ("
                + ",".join(op)
                + ") VALUES ("
                + ",".join("?" for _ in op)
                + ")",
                tuple(op.values()),
            )
            self._event(db, context.user_id, op["state"], op["id"], amount_minor=amount)
            if kind in wealth_kinds:
                self._event(
                    db,
                    context.user_id,
                    "wealth_order_prepared",
                    op["id"],
                    product_id=product_id,
                    action=kind,
                )
            return self._public(op)

    def _public(self, row):
        item = dict(row)
        item.pop("owner_id", None)
        item.pop("auth_version", None)
        item.pop("idempotency_key", None)
        return item

    def operation(self, context, operation_id):
        with self.store.transaction() as db:
            self._guard(db, context)
            self._expire(db, context.user_id)
            return self._public(self._operation(db, context.user_id, operation_id))

    def operations(self, context, limit=50, task_id=None):
        with self.store.transaction() as db:
            self._guard(db, context)
            self._expire(db, context.user_id)
            if (
                task_id
                and not db.execute(
                    "SELECT 1 FROM bank_tasks WHERE id=? AND owner_id=?", (task_id, context.user_id)
                ).fetchone()
            ):
                raise BankError("RESOURCE_NOT_FOUND", 404)
            rows = db.execute(
                "SELECT * FROM bank_operations WHERE owner_id=? AND (? IS NULL OR task_id=?) "
                "ORDER BY created_at DESC,id DESC LIMIT ?",
                (context.user_id, task_id, task_id, limit),
            ).fetchall()
            return [self._public(row) for row in rows]

    def challenge(self, context, operation_id):
        with self.store.transaction() as db:
            self._guard(db, context)
            self._expire(db, context.user_id)
            op = self._operation(db, context.user_id, operation_id)
            if op["state"] != "awaiting_confirmation":
                raise BankError("NOT_AWAITING_CONFIRMATION")
            token = secrets.token_urlsafe(32)
            db.execute(
                "INSERT INTO bank_challenges VALUES (?,?,?,?) ON CONFLICT(operation_id) "
                "DO UPDATE SET session_id=excluded.session_id,token_digest=excluded.token_digest,"
                "expires_at=excluded.expires_at",
                (operation_id, context.session_id, digest(token), op["expires_at"]),
            )
            summary = self._public(op)
            source = self._account(db, context.user_id, op["source_id"])
            summary["source_display"] = {"name": source["name"], "suffix": source["suffix"]}
            if op["kind"] == "transfer":
                from ai_banking.banking.contacts import list_payees

                summary["recipient"] = next(
                    p for p in list_payees(self, context, db) if p["id"] == op["payee_id"]
                )
                summary["balance_before_minor"] = source["balance_minor"]
                summary["balance_after_minor"] = source["balance_minor"] - op["amount_minor"]
            elif op["kind"] in {"wealth_purchase", "wealth_redeem"}:
                from ai_banking.banking.wealth import holdings, product

                row = db.execute(
                    "SELECT detail FROM bank_events WHERE operation_id=? "
                    "AND event='wealth_order_prepared' ORDER BY seq DESC LIMIT 1",
                    (op["id"],),
                ).fetchone()
                if row is not None:
                    item = product(json.loads(row["detail"])["product_id"])
                    holding = next(
                        (
                            holding["amount_minor"]
                            for holding in holdings(db, context.user_id)
                            if item and holding["product"]["id"] == item["id"]
                        ),
                        0,
                    )
                    summary["wealth_product"] = item
                    summary["holding_before_minor"] = holding
            return {"challenge": token, "summary": summary}

    def decide(self, context, operation_id, decision, token, parameters_digest):
        if decision not in {"approve", "reject"}:
            raise BankError("EXPLICIT_DECISION_REQUIRED", 422)
        with self.store.transaction() as db:
            self._guard(db, context)
            self._expire(db, context.user_id)
            op = self._operation(db, context.user_id, operation_id)
            proof = db.execute(
                "SELECT * FROM bank_challenges WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if (
                not proof
                or proof["session_id"] != context.session_id
                or not secrets.compare_digest(proof["token_digest"], digest(token))
                or op["parameters_digest"] != parameters_digest
            ):
                raise BankError("APPROVAL_PROOF_REJECTED", 403)
            if op["state"] in TERMINAL:
                return self._public(op)
            if op["state"] != "awaiting_confirmation" or self.store.clock() >= proof["expires_at"]:
                raise BankError("OPERATION_NOT_CONFIRMABLE")
            if decision == "reject":
                self._finish(db, op, "rejected")
            else:
                db.execute(
                    "UPDATE bank_operations SET state='authorized' WHERE id=?", (operation_id,)
                )
                self._event(db, context.user_id, "approved", operation_id)
        return (
            self.execute(context, operation_id)
            if decision == "approve"
            else self.operation(context, operation_id)
        )

    def execute(self, context, operation_id):
        with self.store.transaction() as db:
            self._guard(db, context)
            self._expire(db, context.user_id)
            op = self._operation(db, context.user_id, operation_id)
            if op["state"] in TERMINAL:
                return self._public(op)
            if op["state"] != "authorized":
                raise BankError("OPERATION_NOT_AUTHORIZED", operation_id=operation_id)
            if op["mode"] == "PREAUTHORIZED":
                self._policy(db, context, op)
            db.execute("UPDATE bank_operations SET state='executing' WHERE id=?", (operation_id,))
            self._event(db, context.user_id, "executing", operation_id)
        try:
            self._hook("before_transaction")
            with self.store.transaction() as db:
                self._guard(db, context)
                op = self._operation(db, context.user_id, operation_id)
                if op["state"] != "executing":
                    raise BankError("OPERATION_STATE_CHANGED")
                if op["expires_at"] <= self.store.clock():
                    raise BankError("OPERATION_EXPIRED")
                minimum = 0
                if op["mode"] == "PREAUTHORIZED":
                    minimum = self._policy(db, context, op)["minimum_minor"]
                    if op["kind"] != "transfer":
                        minimum = 0
                if op["kind"] != "wealth_redeem":
                    self._available(
                        db, context.user_id, op["source_id"], op["amount_minor"], minimum, op["id"]
                    )
                if op["kind"] == "transfer":
                    self._transfer(db, op)
                elif op["kind"] in {"wealth_purchase", "wealth_redeem"}:
                    self._wealth(db, context, op)
                else:
                    db.execute(
                        "UPDATE bank_subscriptions SET status='cancelled' WHERE id=?",
                        (op["subscription_id"],),
                    )
                if op["grant_id"]:
                    db.execute(
                        "UPDATE bank_grants SET reserved_minor=reserved_minor-?,"
                        "spent_minor=spent_minor+? "
                        "WHERE id=?",
                        (op["reserved_minor"], op["amount_minor"], op["grant_id"]),
                    )
                db.execute(
                    "UPDATE bank_operations SET state='succeeded',reserved_minor=0,completed_at=?,"
                    "error_code=NULL WHERE id=?",
                    (self.store.clock(), operation_id),
                )
                self._event(
                    db, context.user_id, "succeeded", operation_id, amount_minor=op["amount_minor"]
                )
                self._hook("before_commit")
        except BankError as error:
            with self.store.transaction() as db:
                op = self._operation(db, context.user_id, operation_id)
                self._finish(db, op, "failed", error.code)
            raise BankError(error.code, error.status, operation_id) from error
        except Exception as error:
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE bank_operations SET state='outcome_unknown',"
                    "error_code='EXECUTION_INTERRUPTED' "
                    "WHERE id=? AND state='executing'",
                    (operation_id,),
                )
                self._event(db, context.user_id, "outcome_unknown", operation_id)
            raise BankError("OUTCOME_UNKNOWN", operation_id=operation_id) from error
        try:
            self._hook("after_commit")
        except Exception as error:
            raise BankError("RESULT_UNAVAILABLE", 503, operation_id) from error
        return self.operation(context, operation_id)

    def _transfer(self, db, op):
        target = db.execute(
            "SELECT balance_minor,owner_id FROM accounts WHERE id=?", (op["target_id"],)
        ).fetchone()
        if not target or target["balance_minor"] + op["amount_minor"] > MAX_MINOR:
            raise BankError("TARGET_BALANCE_LIMIT")
        now = datetime.fromtimestamp(self.store.clock(), UTC).isoformat()
        for side, account_id, amount in [
            ("debit", op["source_id"], -op["amount_minor"]),
            ("credit", op["target_id"], op["amount_minor"]),
        ]:
            entry_id = uuid4().hex
            db.execute(
                "UPDATE accounts SET balance_minor=balance_minor+? WHERE id=?", (amount, account_id)
            )
            db.execute(
                "INSERT INTO entries VALUES (?,?,?,?,?,?)",
                (
                    entry_id,
                    account_id,
                    amount,
                    "模拟转账支出" if amount < 0 else "模拟转账收入",
                    "转账",
                    now,
                ),
            )
            db.execute(
                "INSERT INTO bank_ledger VALUES (?,?,?,?,?,?,?)",
                (uuid4().hex, op["id"], account_id, entry_id, amount, "CNY", side),
            )
            if side == "debit":
                self._hook("after_debit")
        if target["owner_id"] != op["owner_id"]:
            self._event(
                db,
                target["owner_id"],
                "transfer_received",
                op["id"],
                amount_minor=op["amount_minor"],
            )

    def _wealth(self, db, context, op):
        from ai_banking.banking.wealth import holdings, product

        row = db.execute(
            "SELECT detail FROM bank_events WHERE operation_id=? AND event='wealth_order_prepared' "
            "ORDER BY seq DESC LIMIT 1",
            (op["id"],),
        ).fetchone()
        if row is None:
            raise BankError("WEALTH_ORDER_NOT_FOUND")
        detail = json.loads(row["detail"])
        product_id = detail["product_id"]
        item = product(product_id)
        if item is None:
            raise BankError("WEALTH_PRODUCT_NOT_FOUND", 404)
        amount = op["amount_minor"]
        account = self._account(db, context.user_id, op["source_id"])
        now = datetime.fromtimestamp(self.store.clock(), UTC).isoformat()
        if op["kind"] == "wealth_purchase":
            if account["balance_minor"] < amount:
                raise BankError("INSUFFICIENT_BALANCE")
            db.execute(
                "UPDATE accounts SET balance_minor=balance_minor-? WHERE id=?",
                (amount, account["id"]),
            )
            db.execute(
                "INSERT INTO entries VALUES (?,?,?,?,?,?)",
                (uuid4().hex, account["id"], -amount, "理财申购 · " + item["name"], "理财", now),
            )
            delta = amount
        else:
            current = next(
                (
                    holding["amount_minor"]
                    for holding in holdings(db, context.user_id)
                    if holding["product"]["id"] == product_id
                ),
                0,
            )
            if amount > current:
                raise BankError("INSUFFICIENT_WEALTH_HOLDING")
            if account["balance_minor"] + amount > MAX_MINOR:
                raise BankError("TARGET_BALANCE_LIMIT")
            db.execute(
                "UPDATE accounts SET balance_minor=balance_minor+? WHERE id=?",
                (amount, account["id"]),
            )
            db.execute(
                "INSERT INTO entries VALUES (?,?,?,?,?,?)",
                (uuid4().hex, account["id"], amount, "理财赎回 · " + item["name"], "理财", now),
            )
            delta = -amount
        self._event(
            db,
            context.user_id,
            "wealth_holding_changed",
            op["id"],
            product_id=product_id,
            delta_minor=delta,
        )

    def reconcile(self, context, operation_id):
        with self.store.transaction() as db:
            self._guard(db, context)
            op = self._operation(db, context.user_id, operation_id)
            if op["state"] != "outcome_unknown":
                return self._public(op)
            rows = db.execute(
                "SELECT * FROM bank_ledger WHERE operation_id=?", (operation_id,)
            ).fetchall()
            consistent = not db.execute(
                "SELECT 1 FROM accounts a WHERE a.balance_minor != a.opening_minor + "
                "(SELECT COALESCE(SUM(e.amount_minor),0) FROM entries e "
                "WHERE e.account_id=a.id) LIMIT 1"
            ).fetchone()
            if rows or not consistent:
                # 本地事务若提交，操作、业务状态和回执也已提交；出现矛盾时不猜测修复。
                raise BankError("RECONCILIATION_REQUIRES_REVIEW", operation_id=operation_id)
            self._finish(db, op, "failed", "RECONCILED_NOT_EXECUTED")
        return self.operation(context, operation_id)

    def available(self):
        with self.store.transaction() as db:
            return ready(db)

    def portfolio(self, context):
        with self.store.transaction() as db:
            self._guard(db, context)
            self._expire(db, context.user_id)
            now = self.store.clock()
            accounts = db.execute(
                "SELECT id,name,kind,suffix,currency,balance_minor FROM accounts "
                "WHERE owner_id=? ORDER BY kind,id",
                (context.user_id,),
            ).fetchall()
            grants = db.execute(
                "SELECT id,limit_minor,spent_minor,reserved_minor,expires_at "
                "FROM bank_grants WHERE owner_id=? AND status='active' "
                "AND auth_version=? AND expires_at>?",
                (context.user_id, context.auth_version, now),
            ).fetchall()
            totals = db.execute(
                "SELECT COALESCE(SUM(spent_minor),0),COALESCE(SUM(reserved_minor),0) "
                "FROM bank_grants WHERE owner_id=?",
                (context.user_id,),
            ).fetchone()
            version = db.execute(
                "SELECT COALESCE(MAX(seq),0) FROM bank_events WHERE owner_id=?", (context.user_id,)
            ).fetchone()[0]
            states = {
                row["state"]: row["count"]
                for row in db.execute(
                    "SELECT state,COUNT(*) AS count FROM bank_operations "
                    "WHERE owner_id=? GROUP BY state",
                    (context.user_id,),
                )
            }
            snapshot = {
                "version": version,
                "as_of": datetime.fromtimestamp(now, UTC).isoformat(),
                "currency": "CNY",
                "total_minor": sum(a["balance_minor"] for a in accounts),
                "account_count": len(accounts),
                "funds_mode": "READ_ONLY",
                "banking_mode": "PREAUTHORIZED" if grants else "HUMAN_APPROVAL",
                "authorization": [dict(row) for row in grants] or None,
                "spent_minor": totals[0],
                "reserved_minor": totals[1],
                "operation_states": states,
                "agent_funds_access": False,
            }
            return {"accounts": [dict(row) for row in accounts], "snapshot": snapshot}

    def snapshot(self, context):
        return self.portfolio(context)["snapshot"]

    def events(self, context, after=0, limit=50):
        with self.store.transaction() as db:
            self._guard(db, context)
            return [
                dict(row)
                for row in db.execute(
                    "SELECT seq,operation_id,event,detail,created_at FROM bank_events "
                    "WHERE owner_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (context.user_id, after, limit),
                )
            ]
