"""理财目录与卡片信息的模拟只读查询；不涉及资金变动、申请或挂失。"""

import hashlib

CARD_NOTE = "模拟卡信息：不支持申请、调额、冻结或挂失。"
WEALTH_NOTE = "本地模拟产品目录与风险等级，仅用于查询演示；不支持申购、赎回或资金划转。"

WEALTH_PRODUCTS = (
    {
        "id": "wealth-cash-01",
        "name": "模拟货币基金·日日盈",
        "kind": "货币基金",
        "risk_level": "R1",
        "min_amount_minor": 100,
        "term_days": 0,
        "yield_hint": "年化约 1.8%–2.2%（模拟，不保证收益）",
    },
    {
        "id": "wealth-bond-01",
        "name": "模拟债券基金·稳健增利",
        "kind": "债券基金",
        "risk_level": "R2",
        "min_amount_minor": 10000,
        "term_days": 90,
        "yield_hint": "年化约 2.8%–3.5%（模拟，不保证收益）",
    },
    {
        "id": "wealth-mixed-01",
        "name": "模拟混合基金·平衡配置",
        "kind": "混合基金",
        "risk_level": "R3",
        "min_amount_minor": 10000,
        "term_days": 180,
        "yield_hint": "年化约 3.5%–5.0%（模拟，不保证收益）",
    },
)


def wealth_products():
    return {"products": [dict(product) for product in WEALTH_PRODUCTS], "note": WEALTH_NOTE}


def cards(store, owner_id):
    """按账户派生稳定的模拟借记卡；卡号脱敏，仅返回本人数据。"""
    result = []
    for account in store.accounts(owner_id):
        digest = hashlib.sha256(account["id"].encode()).hexdigest()
        digits = "".join(str(int(character, 16) % 10) for character in digest[:12])
        number = f"6222{digits}"
        result.append(
            {
                "id": f"card-{digest[:12]}",
                "account_id": account["id"],
                "account_name": account["name"],
                "masked_number": f"{number[:4]} **** **** {number[-4:]}",
                "kind": "借记卡",
                "status": "active",
                "daily_limit_minor": 500000,
                "contactless": True,
                "note": CARD_NOTE,
            }
        )
    return {"cards": result}
