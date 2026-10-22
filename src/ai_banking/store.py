"""SQLite 持久化、只读账户服务及隔离的虚构数据。"""

import sqlite3
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ai_banking.banking.schema import create_schema, ready, seed_customer


class Store:
    def __init__(self, path: Path, clock=time.time):
        self.path = path
        self.clock = clock

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            fresh = not db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
            sql = """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    auth_version INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, token_digest TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL, user_id TEXT REFERENCES users(id),
                    csrf_token TEXT NOT NULL, auth_version INTEGER,
                    created_at REAL NOT NULL, last_activity REAL NOT NULL,
                    expires_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS rate_limits (
                    scope TEXT PRIMARY KEY, started_at REAL NOT NULL,
                    attempts INTEGER NOT NULL, blocked_until REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL, kind TEXT NOT NULL, suffix TEXT NOT NULL,
                    currency TEXT NOT NULL CHECK(currency = 'CNY'),
                    opening_minor INTEGER NOT NULL CHECK(opening_minor >= 0),
                    balance_minor INTEGER NOT NULL CHECK(balance_minor >= 0)
                );
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
                    amount_minor INTEGER NOT NULL CHECK(amount_minor != 0),
                    merchant TEXT NOT NULL, category TEXT NOT NULL, happened_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
                    created_at REAL NOT NULL, busy_until REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS chat_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    request_id TEXT NOT NULL, question TEXT NOT NULL,
                    answer TEXT, traces TEXT, status TEXT NOT NULL,
                    created_at REAL NOT NULL, UNIQUE(conversation_id, request_id)
                );
                CREATE INDEX IF NOT EXISTS account_owner ON accounts(owner_id);
                CREATE INDEX IF NOT EXISTS entry_account ON entries(account_id, happened_at);
            """
            for statement in sql.split(";"):
                if statement.strip():
                    db.execute(statement)
            if fresh:
                create_schema(db, self.clock())

    def seed_accounts(self, db, owner_id: str):
        """仅在创建用户的同一事务执行，期初余额 + 流水 = 当前余额。"""
        now = datetime.fromtimestamp(self.clock(), UTC)
        current, savings = uuid4().hex, uuid4().hex
        rows = [
            (-2850, "街角咖啡", "餐饮", 0),
            (-6800, "城市超市", "购物", 1),
            (-2500, "城市交通", "交通", 2),
            (-2500, "云音乐月度会员", "订阅", 3),
            (-3200, "社区餐厅", "餐饮", 4),
            (1200000, "模拟薪资", "收入", 5),
            (-1500, "云盘月度会员", "订阅", 6),
        ]
        balance = 1286450
        for account_id, name, kind, suffix, opening, amount in [
            (current, "日常账户", "checking", "0826", balance - sum(r[0] for r in rows), balance),
            (savings, "储蓄账户", "savings", "0618", 3680000, 3680000),
        ]:
            db.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?, ?, 'CNY', ?, ?)",
                (account_id, owner_id, name, kind, suffix, opening, amount),
            )
        for amount, merchant, category, days in rows:
            db.execute(
                "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)",
                (
                    uuid4().hex,
                    current,
                    amount,
                    merchant,
                    category,
                    (now - timedelta(days=days)).isoformat(),
                ),
            )
        if ready(db):
            seed_customer(db, owner_id, self.clock())

    def accounts(self, owner_id: str):
        with self.transaction() as db:
            rows = db.execute(
                "SELECT id, name, kind, suffix, currency, balance_minor "
                "FROM accounts WHERE owner_id = ? ORDER BY kind, id",
                (owner_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def transactions(self, owner_id: str, account_id: str | None = None, limit: int = 30):
        with self.transaction() as db:
            if (
                account_id
                and not db.execute(
                    "SELECT 1 FROM accounts WHERE id = ? AND owner_id = ?", (account_id, owner_id)
                ).fetchone()
            ):
                return None
            rows = db.execute(
                "SELECT e.id, e.account_id, e.amount_minor, e.merchant, e.category, "
                "e.happened_at, a.name AS account_name, a.currency FROM entries e "
                "JOIN accounts a ON a.id = e.account_id WHERE a.owner_id = ? "
                "AND (? IS NULL OR a.id = ?) ORDER BY e.happened_at DESC LIMIT ?",
                (owner_id, account_id, account_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def snapshot(self, owner_id: str):
        accounts = self.accounts(owner_id)
        return {
            "version": "readonly-v1",
            "as_of": datetime.fromtimestamp(self.clock(), UTC).isoformat(),
            "currency": "CNY",
            "total_minor": sum(a["balance_minor"] for a in accounts),
            "account_count": len(accounts),
            "funds_mode": "READ_ONLY",
            "authorization": None,
            "spent_minor": 0,
            "reserved_minor": 0,
        }
