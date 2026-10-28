"""单进程、同源 Web API；身份、任务绑定和资金审批由应用服务控制。"""

import asyncio
import json
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from ai_banking.agent import Agent, AgentError
from ai_banking.auth import COOKIE, Auth, AuthError
from ai_banking.banking.api import Identifier
from ai_banking.banking.api import router as bank_router
from ai_banking.banking.schema import ready
from ai_banking.banking.service import Bank, BankError
from ai_banking.config import Settings
from ai_banking.store import Store
from ai_banking.tracing import emit, trace_scope

WEB = Path(__file__).parent / "web"


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > 32768:
                return await JSONResponse({"code": "REQUEST_TOO_LARGE"}, 413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    conversation_id: str = Field(min_length=32, max_length=36)
    request_id: str = Field(min_length=32, max_length=36)
    message: str = Field(min_length=1, max_length=2000)


class ConversationPolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["HUMAN_APPROVAL", "PREAUTHORIZED"]
    grant_id: Identifier | None = None


class ContinueBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation_id: Identifier


def create_app(settings: Settings | None = None, clock=time.time):
    settings = settings or Settings.from_env()
    store = Store(settings.database, clock)
    auth = Auth(store, settings)
    agent = Agent(store, auth, settings)
    bank = Bank(store, auth)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        bank.recover_startup()
        agent.observer.start()
        try:
            yield
        finally:
            await asyncio.to_thread(agent.observer.close)

    app = FastAPI(
        title="AI-Banking 本地模拟环境",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store, app.state.auth, app.state.agent = store, auth, agent
    app.state.bank = bank
    app.add_middleware(BodyLimit)

    @app.exception_handler(AuthError)
    async def auth_error(request, error):
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else {}
        return JSONResponse({"code": error.code}, status_code=error.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse({"code": "INVALID_REQUEST"}, 422)

    @app.exception_handler(BankError)
    async def bank_error(request, error):
        return JSONResponse({"code": error.code, "operation_id": error.operation_id}, error.status)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        code = (
            "AUTH_UNAVAILABLE"
            if request.url.path.startswith("/api/auth/")
            else "STORAGE_UNAVAILABLE"
        )
        return JSONResponse({"code": code}, 503)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        expected_host = urlsplit(settings.origin).netloc
        if request.headers.get("host") != expected_host:
            response = JSONResponse({"code": "HOST_REJECTED"}, 400)
        elif request.headers.get("sec-fetch-site") == "cross-site":
            response = JSONResponse({"code": "ORIGIN_REJECTED"}, 403)
        elif request.headers.get("origin") not in {None, settings.origin}:
            response = JSONResponse({"code": "ORIGIN_REJECTED"}, 403)
        elif request.method == "POST" and request.headers.get("origin") != settings.origin:
            response = JSONResponse({"code": "ORIGIN_REJECTED"}, 403)
        elif (
            request.method == "POST"
            and request.headers.get("content-type", "").split(";")[0] != "application/json"
        ):
            response = JSONResponse({"code": "JSON_REQUIRED"}, 415)
        else:
            response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            }
        )
        return response

    def set_cookie(response, token):
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="strict",
            path="/",
            secure=not settings.local_http,
        )

    def peer(request):
        return request.client.host if request.client else "unknown"

    def identity(request: Request):
        return auth.authenticate(request.cookies.get(COOKIE), touch=True)

    def mutation(request: Request):
        auth.csrf_check(request.cookies.get(COOKIE), request.headers.get("x-csrf-token", ""))

    app.include_router(bank_router(bank, auth, identity, mutation))

    @app.get("/api/health")
    def health():
        with store.transaction() as db:
            has_users = bool(db.execute("SELECT 1 FROM users WHERE enabled = 1 LIMIT 1").fetchone())
            bank_ready = ready(db)
        return {
            "status": "ok",
            "setup_required": not has_users,
            "simulated": True,
            "agent_mode": settings.agent_mode,
            "model": settings.model if settings.model else None,
            "model_api": settings.model_api if settings.agent_mode == "model" else None,
            "bank_ready": bank_ready,
            "agent_funds_access": False,
            "agent_operation_preparation": settings.agent_mode == "model" and bank_ready,
            "agent_preauthorized_execution": settings.agent_mode == "model" and bank_ready,
            "langsmith": agent.observer.status(),
        }

    @app.get("/api/auth/csrf")
    def csrf(request: Request, response: Response):
        if request.headers.get("x-requested-with") != "AI-Banking":
            raise AuthError("CSRF_REJECTED", 403)
        token, csrf_token = auth.csrf(request.cookies.get(COOKIE), peer(request))
        if token:
            set_cookie(response, token)
        return {"csrf_token": csrf_token}

    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request, response: Response):
        token, csrf_token = auth.login(
            request.cookies.get(COOKIE),
            request.headers.get("x-csrf-token", ""),
            body.username,
            body.password,
            peer(request),
        )
        set_cookie(response, token)
        with store.transaction() as db:
            row = auth.session(db, token)
        return {
            "csrf_token": csrf_token,
            "username": row["username"],
            "expires_at": row["expires_at"],
        }

    @app.get("/api/auth/me")
    def me(request: Request):
        with store.transaction() as db:
            row = auth.session(db, request.cookies.get(COOKIE))
        if not row or row["kind"] != "authenticated":
            raise AuthError("AUTH_REQUIRED")
        return {
            "username": row["username"],
            "expires_at": row["expires_at"],
            "idle_expires_at": row["last_activity"] + settings.idle_seconds,
        }

    @app.post("/api/auth/logout", status_code=204)
    def logout(body: EmptyBody, request: Request):
        with store.transaction() as db:
            row = auth.session(db, request.cookies.get(COOKIE))
        if row:
            mutation(request)
            with store.transaction() as db:
                db.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (row["id"],))
        response = Response(status_code=204)
        response.delete_cookie(
            COOKIE, path="/", httponly=True, secure=not settings.local_http, samesite="strict"
        )
        return response

    @app.get("/api/accounts")
    def accounts(context=Depends(identity)):
        return agent.portfolio(context)

    @app.get("/api/accounts/{account_id}")
    def account(account_id: str, context=Depends(identity)):
        rows = [row for row in store.accounts(context.user_id) if row["id"] == account_id]
        if not rows:
            raise AuthError("RESOURCE_NOT_FOUND", 404)
        return rows[0]

    @app.get("/api/transactions")
    def transactions(
        account_id: str | None = None,
        limit: int = Query(30, ge=1, le=30),
        context=Depends(identity),
    ):
        rows = store.transactions(context.user_id, account_id, limit)
        if rows is None:
            raise AuthError("RESOURCE_NOT_FOUND", 404)
        return {"transactions": rows}

    def conversation(owner_id, conversation_id):
        with store.transaction() as db:
            row = db.execute(
                "SELECT * FROM conversations WHERE id = ? AND owner_id = ?",
                (conversation_id, owner_id),
            ).fetchone()
        if not row:
            raise AuthError("RESOURCE_NOT_FOUND", 404)
        return row

    @app.get("/api/conversations")
    def conversations(context=Depends(identity)):
        with store.transaction() as db:
            rows = db.execute(
                "SELECT id, created_at FROM conversations WHERE owner_id = ? "
                "ORDER BY created_at DESC LIMIT 20",
                (context.user_id,),
            ).fetchall()
        return {"conversations": [dict(row) for row in rows]}

    @app.post("/api/conversations", dependencies=[Depends(mutation)])
    def new_conversation(body: EmptyBody, context=Depends(identity)):
        conversation_id = uuid4().hex
        with store.transaction() as db:
            db.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, 0)",
                (conversation_id, context.user_id, clock()),
            )
        return {"id": conversation_id}

    @app.get("/api/conversations/{conversation_id}")
    def history(conversation_id: str, context=Depends(identity)):
        conversation(context.user_id, conversation_id)
        with store.transaction() as db:
            rows = db.execute(
                "SELECT question, answer, traces, status FROM chat_turns WHERE conversation_id = ? "
                "ORDER BY id DESC LIMIT 50",
                (conversation_id,),
            ).fetchall()
        return {
            "turns": [dict(row) for row in reversed(rows)],
            "operation_task": agent.operation_checkpoint(context, conversation_id),
            "execution_policy": agent.operations.policy(context, conversation_id),
        }

    @app.get("/api/conversations/{conversation_id}/policy")
    def conversation_policy(conversation_id: str, context=Depends(identity)):
        conversation(context.user_id, conversation_id)
        return agent.operations.policy(context, conversation_id)

    @app.post("/api/conversations/{conversation_id}/policy", dependencies=[Depends(mutation)])
    def select_conversation_policy(
        conversation_id: str, body: ConversationPolicyBody, context=Depends(identity)
    ):
        conversation(context.user_id, conversation_id)
        return agent.operations.select_policy(context, conversation_id, body.mode, body.grant_id)

    @app.post("/api/chat", dependencies=[Depends(mutation)])
    async def chat(body: ChatBody, context=Depends(identity)):
        if not body.message.strip():
            raise AuthError("INVALID_REQUEST", 422)
        try:
            UUID(body.request_id)
            UUID(body.conversation_id)
        except ValueError as error:
            raise AuthError("INVALID_REQUEST", 422) from error
        conversation(context.user_id, body.conversation_id)
        cached_operation_task = agent.operation_checkpoint(context, body.conversation_id)
        with store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM chat_turns WHERE conversation_id = ? AND request_id = ?",
                (body.conversation_id, body.request_id),
            ).fetchone()
            if existing:
                if existing["question"] != body.message:
                    raise AuthError("REQUEST_ID_CONFLICT", 409)
                if existing["status"] != "succeeded":
                    raise AuthError("REQUEST_ALREADY_HANDLED", 409)
                with trace_scope(body.request_id, body.conversation_id):
                    emit(settings, "cached", status="succeeded")
                return {
                    "answer": existing["answer"],
                    "traces": json.loads(existing["traces"]),
                    "mode": settings.agent_mode,
                    "operation_task": cached_operation_task,
                    "cached": True,
                }
            busy = db.execute(
                "UPDATE conversations SET busy_until = ? WHERE id = ? AND busy_until <= ?",
                (clock() + 180, body.conversation_id, clock()),
            )
            if not busy.rowcount:
                raise AuthError("CONVERSATION_BUSY", 409)
            rows = db.execute(
                "SELECT question, answer FROM chat_turns WHERE conversation_id = ? "
                "AND status = 'succeeded' ORDER BY id DESC LIMIT 12",
                (body.conversation_id,),
            ).fetchall()
            db.execute(
                "INSERT INTO chat_turns "
                "(conversation_id, request_id, question, status, created_at) "
                "VALUES (?, ?, ?, 'running', ?)",
                (body.conversation_id, body.request_id, body.message, clock()),
            )
        history_rows = list(reversed([dict(row) for row in rows]))
        # 只裁剪完整回合，不保留悬空工具调用；资金事实始终重新查询后端。
        while len(json.dumps(history_rows, ensure_ascii=False).encode()) > 20000:
            history_rows.pop(0)
        try:
            with trace_scope(body.request_id, body.conversation_id):
                answer, traces = await agent.answer(context, body.message, history_rows)
            auth.assert_current(context)
            with store.transaction() as db:
                db.execute(
                    "UPDATE chat_turns SET answer = ?, traces = ?, status = 'succeeded' "
                    "WHERE conversation_id = ? AND request_id = ?",
                    (answer, json.dumps(traces), body.conversation_id, body.request_id),
                )
            return {
                "answer": answer,
                "traces": traces,
                "mode": settings.agent_mode,
                "snapshot": agent.snapshot(context),
                "operation_task": agent.operation_checkpoint(context, body.conversation_id),
            }
        except Exception as error:
            known_error = isinstance(error, (AgentError, AuthError))
            code = error.code if known_error else "INTERNAL_ERROR"
            with trace_scope(body.request_id, body.conversation_id):
                emit(settings, "error", code=code, error_type=type(error).__name__)
            with store.transaction() as db:
                db.execute(
                    "UPDATE chat_turns SET status = 'failed' "
                    "WHERE conversation_id = ? AND request_id = ?",
                    (body.conversation_id, body.request_id),
                )
            if isinstance(error, AuthError):
                raise
            return JSONResponse({"code": code}, 502 if isinstance(error, AgentError) else 500)
        finally:
            with store.transaction() as db:
                db.execute(
                    "UPDATE conversations SET busy_until = 0 WHERE id = ?", (body.conversation_id,)
                )

    @app.post("/api/conversations/{conversation_id}/continue", dependencies=[Depends(mutation)])
    async def continue_conversation(
        conversation_id: str, body: ContinueBody, context=Depends(identity)
    ):
        conversation(context.user_id, conversation_id)
        request_id, message = agent.operations.continuation(
            context, conversation_id, body.operation_id
        )
        return await chat(
            ChatBody(conversation_id=conversation_id, request_id=request_id, message=message),
            context,
        )

    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    return app
