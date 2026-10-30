"""收款人展示、备注与显式载入的独立虚构联系人；不暴露对方资产。"""

import json
import secrets
import unicodedata
from uuid import uuid4

from ai_banking.auth import password_hash
from ai_banking.banking.service import BankError

DEMO_CONTACTS = (
    ("colleague", "张明", "同事 · 午餐分摊", "4712"),
    ("landlord", "张明", "房东 · 房租", "5938"),
    ("friend", "林晓", "朋友 · 日常往来", "8620"),
)


def list_payees(bank, context, db=None):
    if db is None:
        with bank.store.transaction() as connection:
            return list_payees(bank, context, connection)
    bank._guard(db, context)
    metadata = {}
    for event in db.execute(
        "SELECT event,detail FROM bank_events WHERE owner_id=? "
        "AND event IN ('demo_payee_created','payee_note_updated') ORDER BY seq",
        (context.user_id,),
    ):
        detail = json.loads(event["detail"])
        metadata.setdefault(detail["payee_id"], {}).update(detail)
    items = []
    for row in db.execute(
        "SELECT p.id,p.name,p.account_id,a.suffix,a.currency,"
        "(a.owner_id=p.owner_id) AS is_self FROM bank_payees p "
        "JOIN accounts a ON a.id=p.account_id WHERE p.owner_id=? ORDER BY p.name,p.id",
        (context.user_id,),
    ):
        item = dict(row)
        extra = metadata.get(item["id"], {})
        item.update(
            note=extra.get("note", ""),
            bank_name="模拟银行",
            kind="self" if item.pop("is_self") else "demo" if "demo_key" in extra else "registered",
        )
        items.append(item)
    return items


def find_payees(bank, context, query):
    needle = unicodedata.normalize("NFKC", query).strip().casefold()
    if not needle or len(needle) > 64:
        raise BankError("INVALID_PAYEE_QUERY", 422)
    matches = [
        p
        for p in list_payees(bank, context)
        if needle
        in unicodedata.normalize("NFKC", p["name"] + " " + p["note"] + " " + p["suffix"]).casefold()
    ]
    return {
        "matches": matches,
        "match_count": len(matches),
        "resolution": "not_found"
        if not matches
        else "unique"
        if len(matches) == 1
        else "needs_clarification",
        "note": "匹配不代表授权；多条匹配须请用户按备注或账户尾号选择，不自动选第一条。",
    }


def set_note(bank, context, payee_id, note):
    with bank.store.transaction() as db:
        bank._guard(db, context)
        if not db.execute(
            "SELECT 1 FROM bank_payees WHERE id=? AND owner_id=?", (payee_id, context.user_id)
        ).fetchone():
            raise BankError("RESOURCE_NOT_FOUND", 404)
        bank._event(db, context.user_id, "payee_note_updated", payee_id=payee_id, note=note.strip())
    return {"payee": next(p for p in list_payees(bank, context) if p["id"] == payee_id)}


def load_demo_contacts(bank, context):
    with bank.store.transaction() as db:
        bank._guard(db, context)
        existing = {
            json.loads(row["detail"])["demo_key"]
            for row in db.execute(
                "SELECT detail FROM bank_events WHERE owner_id=? AND event='demo_payee_created'",
                (context.user_id,),
            )
        }
        for key, name, note, suffix in DEMO_CONTACTS:
            if key in existing:
                continue
            owner, account, payee_id = uuid4().hex, uuid4().hex, uuid4().hex
            # 禁用登录的独立虚构收款主体；随机密码不返回、不记录，初始资金为零。
            db.execute(
                "INSERT INTO users (id,username,password_hash,enabled,created_at) "
                "VALUES (?,?,?,0,?)",
                (
                    owner,
                    "demo_" + owner[:24],
                    password_hash(secrets.token_urlsafe(32)),
                    bank.store.clock(),
                ),
            )
            db.execute(
                "INSERT INTO accounts VALUES (?,?,?,?,?,'CNY',0,0)",
                (account, owner, "模拟收款账户", "checking", suffix),
            )
            db.execute(
                "INSERT INTO bank_payees VALUES (?,?,?,?)",
                (payee_id, context.user_id, account, name),
            )
            bank._event(
                db,
                context.user_id,
                "demo_payee_created",
                payee_id=payee_id,
                demo_key=key,
                note=note,
            )
    return {"payees": list_payees(bank, context)}
