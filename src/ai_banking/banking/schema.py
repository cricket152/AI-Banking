"""增量银行表；既有数据库只允许通过显式升级命令添加。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

SCHEMA = """
CREATE TABLE IF NOT EXISTS bank_meta (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bank_payees (
    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
    account_id TEXT NOT NULL REFERENCES accounts(id), name TEXT NOT NULL,
    UNIQUE(owner_id, account_id)
);
CREATE TABLE IF NOT EXISTS bank_grants (
    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
    source_id TEXT NOT NULL REFERENCES accounts(id), auth_version INTEGER NOT NULL,
    request_id TEXT NOT NULL, policy_digest TEXT NOT NULL,
    currency TEXT NOT NULL CHECK(currency = 'CNY'), payee_ids TEXT NOT NULL,
    kinds TEXT NOT NULL, limit_minor INTEGER NOT NULL CHECK(limit_minor >= 0),
    single_minor INTEGER NOT NULL CHECK(single_minor >= 0),
    minimum_minor INTEGER NOT NULL CHECK(minimum_minor >= 0),
    spent_minor INTEGER NOT NULL DEFAULT 0 CHECK(spent_minor >= 0),
    reserved_minor INTEGER NOT NULL DEFAULT 0 CHECK(reserved_minor >= 0),
    created_at REAL NOT NULL, expires_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    CHECK(spent_minor + reserved_minor <= limit_minor), UNIQUE(owner_id,request_id)
);
CREATE TABLE IF NOT EXISTS bank_tasks (
    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(owner_id, request_id)
);
CREATE TABLE IF NOT EXISTS bank_subscriptions (
    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
    account_id TEXT NOT NULL REFERENCES accounts(id), merchant TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
    next_charge_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'sample_registered',
    UNIQUE(owner_id, account_id, merchant)
);
CREATE TABLE IF NOT EXISTS bank_operations (
    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
    auth_version INTEGER NOT NULL,
    task_id TEXT NOT NULL REFERENCES bank_tasks(id), step_key TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES accounts(id), target_id TEXT REFERENCES accounts(id),
    payee_id TEXT REFERENCES bank_payees(id),
    subscription_id TEXT REFERENCES bank_subscriptions(id),
    amount_minor INTEGER NOT NULL CHECK(amount_minor >= 0), fee_minor INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL CHECK(currency = 'CNY'), parameters_digest TEXT NOT NULL,
    mode TEXT NOT NULL, grant_id TEXT REFERENCES bank_grants(id),
    state TEXT NOT NULL, reserved_minor INTEGER NOT NULL DEFAULT 0 CHECK(reserved_minor >= 0),
    created_at REAL NOT NULL, expires_at REAL NOT NULL,
    completed_at REAL, error_code TEXT,
    UNIQUE(task_id, step_key)
);
CREATE TABLE IF NOT EXISTS bank_ledger (
    id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES bank_operations(id),
    account_id TEXT NOT NULL REFERENCES accounts(id),
    entry_id TEXT NOT NULL UNIQUE REFERENCES entries(id), amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL CHECK(currency = 'CNY'), side TEXT NOT NULL,
    UNIQUE(operation_id, side), CHECK(side IN ('debit', 'credit')),
    CHECK((side='debit' AND amount_minor<0) OR (side='credit' AND amount_minor>0))
);
CREATE TABLE IF NOT EXISTS bank_challenges (
    operation_id TEXT PRIMARY KEY REFERENCES bank_operations(id),
    session_id TEXT NOT NULL REFERENCES sessions(id), token_digest TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bank_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, owner_id TEXT NOT NULL REFERENCES users(id),
    operation_id TEXT REFERENCES bank_operations(id), event TEXT NOT NULL,
    detail TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS bank_ops_owner ON bank_operations(owner_id, state);
CREATE INDEX IF NOT EXISTS bank_events_owner ON bank_events(owner_id, seq);
"""


def ready(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='bank_meta'").fetchone())


def create_schema(db, now):
    for statement in SCHEMA.split(";"):
        if statement.strip():
            db.execute(statement)
    if not db.execute("SELECT 1 FROM bank_meta").fetchone():
        db.execute("INSERT INTO bank_meta VALUES (1)")
    for row in db.execute("SELECT id FROM users").fetchall():
        seed_customer(db, row["id"], now)


def seed_customer(db, owner_id, now):
    for row in db.execute("SELECT * FROM accounts WHERE owner_id=?", (owner_id,)).fetchall():
        db.execute(
            "INSERT OR IGNORE INTO bank_payees VALUES (?, ?, ?, ?)",
            (uuid4().hex, owner_id, row["id"], "本人" + row["name"]),
        )
    account = db.execute(
        "SELECT id FROM accounts WHERE owner_id=? AND kind='checking' LIMIT 1", (owner_id,)
    ).fetchone()
    if account:
        date = (datetime.fromtimestamp(now, UTC) + timedelta(days=20)).isoformat()
        for merchant, amount in [("云音乐月度会员", 2500), ("云盘月度会员", 1500)]:
            db.execute(
                "INSERT OR IGNORE INTO bank_subscriptions "
                "(id,owner_id,account_id,merchant,amount_minor,next_charge_at) "
                "VALUES (?,?,?,?,?,?)",
                (uuid4().hex, owner_id, account["id"], merchant, amount, date),
            )
