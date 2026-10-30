"""模拟理财持仓：事件记录申购/赎回，不连接真实产品。"""

import json

from ai_banking.banking.service import BankError
from ai_banking.catalog import WEALTH_PRODUCTS


def product(product_id):
    return next((dict(item) for item in WEALTH_PRODUCTS if item["id"] == product_id), None)


def holdings(db, owner_id):
    totals = {}
    for row in db.execute(
        "SELECT detail FROM bank_events WHERE owner_id=? AND event='wealth_holding_changed' "
        "ORDER BY seq",
        (owner_id,),
    ):
        detail = json.loads(row["detail"])
        product_id = detail["product_id"]
        totals[product_id] = totals.get(product_id, 0) + detail["delta_minor"]
    result = []
    for product_id, amount in totals.items():
        item = product(product_id)
        if item is None or amount <= 0:
            continue
        result.append(
            {
                "product": item,
                "amount_minor": amount,
            }
        )
    return result


def summary(bank, context):
    with bank.store.transaction() as db:
        bank._guard(db, context)
        return {
            "products": [dict(item) for item in WEALTH_PRODUCTS],
            "holdings": holdings(db, context.user_id),
            "note": "模拟理财目录与持仓；申购/赎回只影响本地模拟余额与持仓，不是真实产品。",
        }


def validate_product(db, owner_id, product_id, amount_minor):
    item = product(product_id)
    if item is None:
        raise BankError("RESOURCE_NOT_FOUND", 404)
    if type(amount_minor) is not int or amount_minor < item["min_amount_minor"]:
        raise BankError("INVALID_WEALTH_AMOUNT", 422)
    return item
