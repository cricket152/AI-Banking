"""本地用户、Argon2id 和持久化会话。"""

import hashlib
import re
import secrets
import sqlite3
from dataclasses import dataclass
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

from ai_banking.config import Settings
from ai_banking.store import Store

COOKIE = "ai_banking_session"
HASHER = PasswordHasher(
    time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))


class AuthError(Exception):
    def __init__(self, code: str, status: int = 401, retry_after: int | None = None):
        self.code, self.status, self.retry_after = code, status, retry_after


def username_key(value: str):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,31}", value):
        raise ValueError("用户名须为 3–32 位小写字母、数字或下划线，以字母开头")
    return value


def password_hash(password: str):
    if not 15 <= len(password) <= 128:
        raise ValueError("密码长度须为 15–128 个字符")
    return HASHER.hash(password)


def digest(token: str):
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    session_id: str
    auth_version: int


class Auth:
    def __init__(self, store: Store, settings: Settings):
        self.store, self.settings = store, settings

    def create_user(self, username: str, password: str):
        username, encoded = username_key(username), password_hash(password)
        user_id = uuid4().hex
        try:
            with self.store.transaction() as db:
                db.execute(
                    "INSERT INTO users (id, username, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, username, encoded, self.store.clock()),
                )
                self.store.seed_accounts(db, user_id)
        except sqlite3.IntegrityError as error:
            raise ValueError("用户名已存在") from error
        return user_id

    def change_user(self, username: str, password: str | None = None):
        username = username_key(username)
        encoded = password_hash(password) if password is not None else None
        with self.store.transaction() as db:
            row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if not row:
                raise ValueError("用户不存在")
            if encoded:
                db.execute(
                    "UPDATE users SET password_hash = ?, auth_version = auth_version + 1 "
                    "WHERE id = ?",
                    (encoded, row["id"]),
                )
            else:
                db.execute(
                    "UPDATE users SET enabled = 0, auth_version = auth_version + 1 WHERE id = ?",
                    (row["id"],),
                )
            db.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (row["id"],))

    def session(self, db, token: str | None, touch=False):
        if not token or len(token) > 128:
            return None
        row = db.execute(
            "SELECT s.*, u.username, u.enabled, u.auth_version AS current_version "
            "FROM sessions s LEFT JOIN users u ON u.id = s.user_id WHERE s.token_digest = ?",
            (digest(token),),
        ).fetchone()
        now = self.store.clock()
        if not row or row["revoked"] or now >= row["expires_at"]:
            return None
        if row["kind"] == "authenticated":
            if (
                not row["enabled"]
                or row["auth_version"] != row["current_version"]
                or now >= row["last_activity"] + self.settings.idle_seconds
            ):
                return None
            if touch:
                db.execute("UPDATE sessions SET last_activity = ? WHERE id = ?", (now, row["id"]))
        return dict(row)

    def authenticate(self, token: str | None, touch=False):
        with self.store.transaction() as db:
            row = self.session(db, token, touch)
        if not row or row["kind"] != "authenticated":
            raise AuthError("AUTH_REQUIRED")
        return AuthContext(row["user_id"], row["id"], row["auth_version"])

    def assert_current(self, context: AuthContext):
        with self.store.transaction() as db:
            return self.current_in_transaction(db, context)

    def current_in_transaction(self, db, context):
        row = db.execute(
            "SELECT s.*, u.enabled, u.auth_version AS current_version FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.id = ?",
            (context.session_id,),
        ).fetchone()
        now = self.store.clock()
        if (
            not row
            or row["revoked"]
            or not row["enabled"]
            or row["auth_version"] != row["current_version"]
            or row["user_id"] != context.user_id
            or row["auth_version"] != context.auth_version
            or now >= row["expires_at"]
            or now >= row["last_activity"] + self.settings.idle_seconds
        ):
            raise AuthError("AUTH_REQUIRED")
        return row

    def reauthenticate(self, context, password, peer):
        error = None
        with self.store.transaction() as db:
            self.current_in_transaction(db, context)
            scope = "reauth:" + context.user_id
            wait = self.rate(db, scope, 5, False) or self.rate(db, "reauth-peer:" + peer, 20, False)
            if wait:
                error = AuthError("AUTH_RATE_LIMITED", 429, wait)
            else:
                row = db.execute(
                    "SELECT password_hash FROM users WHERE id=?", (context.user_id,)
                ).fetchone()
                try:
                    verified = HASHER.verify(row["password_hash"], password)
                except (VerificationError, InvalidHashError):
                    verified = False
                if not verified:
                    self.rate(db, scope, 5, True)
                    self.rate(db, "reauth-peer:" + peer, 20, True)
                    error = AuthError("CREDENTIALS_INVALID")
        if error:
            raise error

    def new_session(self, db, user=None):
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), self.store.clock()
        db.execute(
            "INSERT INTO sessions (id, token_digest, kind, user_id, csrf_token, auth_version, "
            "created_at, last_activity, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uuid4().hex,
                digest(token),
                "authenticated" if user else "preauth",
                user["id"] if user else None,
                csrf,
                user["auth_version"] if user else None,
                now,
                now,
                now + (self.settings.absolute_seconds if user else 300),
            ),
        )
        return token, csrf

    def rate(self, db, scope: str, limit: int, consume: bool):
        now = self.store.clock()
        row = db.execute("SELECT * FROM rate_limits WHERE scope = ?", (scope,)).fetchone()
        if row and now < row["blocked_until"]:
            return max(1, int(row["blocked_until"] - now + 1))
        if not consume:
            return None
        count = row["attempts"] + 1 if row and now < row["started_at"] + 300 else 1
        started = row["started_at"] if row and now < row["started_at"] + 300 else now
        blocked = now + 300 if count >= limit else 0
        db.execute(
            "INSERT INTO rate_limits VALUES (?, ?, ?, ?) ON CONFLICT(scope) DO UPDATE SET "
            "started_at=excluded.started_at, attempts=excluded.attempts, "
            "blocked_until=excluded.blocked_until",
            (scope, started, count, blocked),
        )
        return None

    def csrf(self, token: str | None, peer: str):
        with self.store.transaction() as db:
            current = self.session(db, token)
            if current:
                return None, current["csrf_token"]
            wait = self.rate(db, f"preauth:{peer}", 60, False)
            if not wait:
                self.rate(db, f"preauth:{peer}", 60, True)
                created = self.new_session(db)
        if wait:
            raise AuthError("AUTH_RATE_LIMITED", 429, wait)
        return created

    def login(self, token: str | None, csrf: str, username: str, password: str, peer: str):
        try:
            username = username_key(username)
        except ValueError:
            username = "<invalid>"
        error = None
        result = None
        with self.store.transaction() as db:
            session = self.session(db, token)
            if not session or not secrets.compare_digest(session["csrf_token"], csrf):
                raise AuthError("CSRF_REJECTED", 403)
            if session["kind"] != "preauth":
                raise AuthError("ALREADY_AUTHENTICATED", 409)
            scopes = [(f"username:{username}", 5), (f"peer:{peer}", 20)]
            waits = [self.rate(db, scope, limit, False) or 0 for scope, limit in scopes]
            if max(waits):
                error = AuthError("AUTH_RATE_LIMITED", 429, max(waits))
            else:
                user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                try:
                    verified = HASHER.verify(
                        user["password_hash"] if user else DUMMY_HASH, password
                    )
                except (VerificationError, InvalidHashError):
                    verified = False
                if not verified or not user or not user["enabled"]:
                    for scope, limit in scopes:
                        self.rate(db, scope, limit, True)
                    error = AuthError("CREDENTIALS_INVALID")
                else:
                    db.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (session["id"],))
                    result = self.new_session(db, user)
        # 失败计数需先提交，不能因认证错误回滚。
        if error:
            raise error
        return result

    def csrf_check(self, token: str | None, csrf: str):
        with self.store.transaction() as db:
            row = self.session(db, token)
        if not row or not secrets.compare_digest(row["csrf_token"], csrf):
            raise AuthError("CSRF_REJECTED", 403)
        return row
