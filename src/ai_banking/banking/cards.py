"""模拟卡片管理：事件承载状态，不连接卡组织，不产生真实信用记录。"""

import hashlib
import json
from uuid import uuid4

from ai_banking.banking.service import BankError

CARD_KINDS = {"debit": "借记卡", "credit": "信用卡"}
CARD_STATUSES = {"active", "frozen", "lost"}
DEFAULT_LIMIT_MINOR = 500000
MAX_LIMIT_MINOR = 10_000_000
NOTE = "模拟卡管理：申请、调额、冻结、挂失仅作用于本地虚构卡；不连接真实卡组织或信用系统。"
STATUS_LABELS = {"active": "正常", "frozen": "已冻结", "lost": "已挂失"}
EVENTS = ("card_applied", "card_limit_updated", "card_status_changed")


def _mask(seed):
    digest = hashlib.sha256(seed.encode()).hexdigest()
    digits = "".join(str(int(character, 16) % 10) for character in digest[:12])
    return f"6222 **** **** {digits[-4:]}", digits[-4:]


def _base_card(account):
    digest = hashlib.sha256(account["id"].encode()).hexdigest()
    masked, suffix = _mask(account["id"])
    return {
        "id": f"card-{digest[:12]}",
        "account_id": account["id"],
        "account_name": account["name"],
        "masked_number": masked,
        "kind": "借记卡",
        "status": "active",
        "daily_limit_minor": DEFAULT_LIMIT_MINOR,
        "contactless": True,
        "note": NOTE,
        "suffix": suffix,
    }


def _cards(bank, context, db):
    cards = {}
    for row in db.execute(
        "SELECT id,name,kind,suffix FROM accounts WHERE owner_id=? ORDER BY kind,id",
        (context.user_id,),
    ):
        account = dict(row)
        card = _base_card(account)
        cards[card["id"]] = card
    for row in db.execute(
        "SELECT event,detail FROM bank_events WHERE owner_id=? "
        "AND event IN ('card_applied','card_limit_updated','card_status_changed') ORDER BY seq",
        (context.user_id,),
    ):
        detail = json.loads(row["detail"])
        card_id = detail.get("card_id")
        if row["event"] == "card_applied":
            account = db.execute(
                "SELECT id,name FROM accounts WHERE id=? AND owner_id=?",
                (detail["account_id"], context.user_id),
            ).fetchone()
            if account is None:
                continue
            masked, suffix = _mask(detail["card_id"])
            cards[card_id] = {
                "id": card_id,
                "account_id": account["id"],
                "account_name": account["name"],
                "masked_number": masked,
                "kind": CARD_KINDS.get(detail.get("kind"), "借记卡"),
                "status": "active",
                "daily_limit_minor": detail.get("daily_limit_minor", DEFAULT_LIMIT_MINOR),
                "contactless": True,
                "note": NOTE,
                "suffix": suffix,
            }
        elif card_id in cards:
            if row["event"] == "card_limit_updated":
                cards[card_id]["daily_limit_minor"] = detail["daily_limit_minor"]
            else:
                cards[card_id]["status"] = detail["status"]
    return [cards[key] for key in sorted(cards)]


def list_cards(bank, context, db=None):
    if db is not None:
        return {"cards": _cards(bank, context, db)}
    with bank.store.transaction() as db:
        bank._guard(db, context)
        return {"cards": _cards(bank, context, db)}


def _find(bank, context, db, card_id):
    card = next((item for item in _cards(bank, context, db) if item["id"] == card_id), None)
    if card is None:
        raise BankError("RESOURCE_NOT_FOUND", 404)
    return card


def apply_card(bank, context, account_id, kind="debit", daily_limit_minor=DEFAULT_LIMIT_MINOR):
    if kind not in CARD_KINDS:
        raise BankError("INVALID_CARD_KIND", 422)
    if type(daily_limit_minor) is not int or not 0 <= daily_limit_minor <= MAX_LIMIT_MINOR:
        raise BankError("INVALID_CARD_LIMIT", 422)
    with bank.store.transaction() as db:
        bank._guard(db, context)
        if not db.execute(
            "SELECT 1 FROM accounts WHERE id=? AND owner_id=?", (account_id, context.user_id)
        ).fetchone():
            raise BankError("RESOURCE_NOT_FOUND", 404)
        card_id = "card-" + uuid4().hex[:16]
        bank._event(
            db,
            context.user_id,
            "card_applied",
            card_id=card_id,
            account_id=account_id,
            kind=kind,
            daily_limit_minor=daily_limit_minor,
        )
        return {"card": _find(bank, context, db, card_id)}


def update_limit(bank, context, card_id, daily_limit_minor):
    if type(daily_limit_minor) is not int or not 0 <= daily_limit_minor <= MAX_LIMIT_MINOR:
        raise BankError("INVALID_CARD_LIMIT", 422)
    with bank.store.transaction() as db:
        bank._guard(db, context)
        card = _find(bank, context, db, card_id)
        if card["status"] == "lost":
            raise BankError("CARD_LOST", 409)
        bank._event(
            db,
            context.user_id,
            "card_limit_updated",
            card_id=card_id,
            daily_limit_minor=daily_limit_minor,
        )
        return {"card": _find(bank, context, db, card_id)}


def set_status(bank, context, card_id, status):
    if status not in CARD_STATUSES:
        raise BankError("INVALID_CARD_STATUS", 422)
    with bank.store.transaction() as db:
        bank._guard(db, context)
        card = _find(bank, context, db, card_id)
        if card["status"] == "lost":
            if status != "lost":
                raise BankError("CARD_LOST", 409)
            return {"card": card}
        if status == card["status"]:
            return {"card": card}
        bank._event(db, context.user_id, "card_status_changed", card_id=card_id, status=status)
        return {"card": _find(bank, context, db, card_id)}
