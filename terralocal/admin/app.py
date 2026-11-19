from __future__ import annotations

import secrets
import time
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, model_validator
from sqlalchemy import select

from terralocal.server.api import schemas as s
from terralocal.server.domain import accounts
from terralocal.server.domain.clock import ServerClock
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.backups import BackupService


class GM(s.Command):
    accountId: int = Field(ge=1)
    action: str
    id: str | None = Field(default=None, min_length=1, max_length=96, pattern=r"^\S+$")
    value: int = Field(default=0, ge=0, le=1_000_000_000)
    text: str | None = Field(default=None, max_length=8000)
    title: str | None = Field(default=None, max_length=256)
    rewards: list[s.ItemAmount] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def required_identifier(self):
        if self.action in {"grant-item", "set-item", "grant-operator", "set-acquisition-count", "unlock-stage"}:
            if self.id is None:
                raise ValueError("该 GM 操作需要标识")
        return self


def _catalog_text(value, fallback="") -> str:
    if value is None or value == "":
        return fallback
    if not isinstance(value, str):
        raise DomainError("GAMEDATA_INVALID", "目录显示字段不是字符串", 503)
    return value


def create_admin_app(runtime, request_log=None) -> FastAPI:
    settings = runtime.settings
    app = FastAPI(title="TerraLocal 管理", docs_url=None, redoc_url=None)
    static = Path(__file__).parent / "static"
    sessions, session_lock = {}, Lock()
    backups = BackupService(runtime)
    host_names = {"127.0.0.1", "localhost", settings.admin_host}

    @app.middleware("http")
    async def protect_origin(request, call_next):
        host = urlsplit("http://" + request.headers.get("host", "")).hostname
        origin = request.headers.get("origin")
        if host not in host_names or (origin and origin != f"http://{request.headers.get('host')}"):
            return JSONResponse({"error": "拒绝来自其他站点的管理请求"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": "拒绝跨站管理请求"}, status_code=403)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 128 * 1024:
                return JSONResponse({"error": "管理请求过大"}, status_code=413)
        request._body = bytes(body)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"error": exc.message, "code": exc.code}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        return JSONResponse({"error": "输入格式不正确", "fields": [list(e["loc"]) for e in exc.errors()]},
                            status_code=422)

    def authorize(request: Request):
        token = request.cookies.get("tl_admin", "")
        with session_lock:
            entry = sessions.get(token)
        if not entry or entry["expires"] < time.time():
            raise DomainError("ADMIN_LOGIN_REQUIRED", "请先登录管理面板", 401)
        if request.method not in {"GET", "HEAD"} and not secrets.compare_digest(
            request.headers.get("x-csrf-token", ""), entry["csrf"]):
            raise DomainError("CSRF_REJECTED", "管理请求校验失败，请刷新页面", 403)

    def issue_session():
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with session_lock:
            for old in [k for k, v in sessions.items() if v["expires"] < time.time()]:
                del sessions[old]
            sessions[token] = {"csrf": csrf, "expires": time.time() + 8 * 3600}
        response = JSONResponse({"authenticated": True, "csrf": csrf})
        response.set_cookie("tl_admin", token, httponly=True, samesite="strict", max_age=8 * 3600)
        return response

    @app.get("/api/session")
    def session():
        return JSONResponse({"authenticated": False}) if settings.admin_password_hash else issue_session()

    @app.post("/api/login")
    def login(payload: s.Login):
        if settings.admin_password_hash:
            try:
                accounts.PASSWORDS.verify(settings.admin_password_hash, payload.password or "")
            except VerificationError as exc:
                raise DomainError("ADMIN_LOGIN_FAILED", "管理密码错误", 401) from exc
        return issue_session()

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static), name="static")

    def audit(session, action, account_id=None, **detail):
        session.add(m.AuditLog(actor="admin", account_id=account_id, action=action, detail=detail,
                              created_at=ServerClock(session.get(m.ServerClockState, 1)).now()))

    @app.get("/api/dashboard", dependencies=[Depends(authorize)])
    def dashboard():
        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            clock = ServerClock(session.get(m.ServerClockState, 1))
            clock_status = {"mode": clock.state.mode, "now": None, "offset": clock.state.offset}
            try:
                clock_status["now"] = clock.now()
            except DomainError as error:
                if error.code != "INVALID_CLOCK_STATE":
                    raise
                # Keep the control panel usable so legacy invalid settings can
                # be repaired explicitly without silently changing game time.
                clock_status["error"] = error.message
            account_rows = session.scalars(select(m.Account)).all()
            return {"version": "0.1.0", "gameUrl": settings.advertised_url,
                    "clientProfile": settings.client_profile, "clientVerified": False,
                    "gamedata": runtime.data.manifest if runtime.data else None,
                    "database": runtime.database.integrity(), "accounts": len(account_rows),
                    "clock": clock_status,
                    "requests": request_log.snapshot()[:20] if request_log else [],
                    "logging": request_log.status() if request_log else None}

    @app.get("/api/accounts", dependencies=[Depends(authorize)])
    def get_accounts():
        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            return [{"id": a.id, "uid": a.uid, "name": a.name, "preset": a.preset,
                     "createdAt": a.created_at} for a in session.scalars(select(m.Account).order_by(m.Account.id))]

    @app.post("/api/accounts", dependencies=[Depends(authorize)])
    def add_account(payload: s.AccountCreate):
        with runtime.maintenance, runtime.database.transaction() as session:
            account = accounts.create_account(session, runtime.require_data(), **payload.model_dump())
            audit(session, "create-account", account.id, name=account.name, preset=account.preset)
            return {"id": account.id, "uid": account.uid}

    @app.get("/api/accounts/{account_id}", dependencies=[Depends(authorize)])
    def inspect_account(account_id: int):
        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            ctx = Context(session, runtime.require_data(), account_id)
            return {"accountId": account_id, "user": SyncDataAssembler(ctx).assemble(),
                    "mails": [{"id": r.id, "title": r.title, "rewards": r.rewards, "claimed": r.claimed,
                               "expiresAt": r.expires_at} for r in ctx.rows(m.Mail)],
                    "battles": [{"id": r.id, "stageId": r.stage_id, "state": r.state,
                                 "startedAt": r.started_at} for r in ctx.rows(m.BattleSession)]}

    @app.get("/api/catalog/{kind}", dependencies=[Depends(authorize)])
    def catalog(kind: str, q: str = "", limit: int = 100):
        data = runtime.require_data()
        if kind == "items":
            entries = data.items
        elif kind == "operators":
            entries = {k: v for k, v in data.characters.items() if k.startswith("char_") and not v["isNotObtainable"]}
        elif kind == "stages":
            entries = data.stages
        else:
            raise DomainError("UNKNOWN_CATALOG", "未知数据目录", 404)
        results = []
        needle = q.lower()
        for identifier, entry in entries.items():
            name, code = _catalog_text(entry.get("name"), identifier), _catalog_text(entry.get("code"))
            if needle in (identifier + name + code).lower():
                results.append({"id": identifier, "name": name, "code": code,
                                "type": entry.get("itemType", entry.get("stageType", entry.get("profession")))})
        return {"total": len(results), "entries": results[:min(max(limit, 1), 500)]}

    @app.post("/api/gm", dependencies=[Depends(authorize)])
    def gm(payload: GM):
        with runtime.maintenance, runtime.database.transaction() as session:
            ctx = Context(session, runtime.require_data(), payload.accountId)
            outcome = None
            if payload.action in {"grant-item", "set-item"}:
                ctx.change_item(payload.id, payload.value if payload.action == "grant-item" else
                                payload.value - ctx.balance(payload.id))
            elif payload.action == "grant-operator":
                ctx.acquire_operator(payload.id)
            elif payload.action == "complete-roster":
                outcome = accounts.complete_roster(ctx)
            elif payload.action == "set-acquisition-count":
                from terralocal.server.domain.acquisitions import set_verified_count

                outcome = set_verified_count(ctx, payload.id, payload.value, payload.title)
            elif payload.action == "set-sanity":
                state = ctx.sanity()
                state.current, state.last_recovery_at = payload.value, ctx.now
            elif payload.action == "unlock-stage":
                ctx.data.stage(payload.id)
                row = session.get(m.StageProgress, (ctx.account_id, payload.id))
                if row:
                    row.unlocked = True
                else:
                    session.add(m.StageProgress(account_id=ctx.account_id, stage_id=payload.id, unlocked=True))
            elif payload.action == "send-mail":
                rewards = [r.model_dump() for r in payload.rewards]
                for reward in rewards:
                    ctx.data.item(reward["id"])
                if not payload.title:
                    raise DomainError("MAIL_TITLE_REQUIRED", "请填写邮件标题")
                session.add(m.Mail(account_id=ctx.account_id, title=payload.title, body=payload.text or "",
                                   rewards=rewards, created_at=ctx.now))
            else:
                raise DomainError("NOT_IMPLEMENTED", "该 GM 操作尚未实现", 501)
            ctx.profile.revision += 1
            audit(session, payload.action, ctx.account_id, id=payload.id, value=payload.value,
                  title=payload.title, rewards=[r.model_dump() for r in payload.rewards], outcome=outcome)
            extra = ({"roster": outcome} if payload.action == "complete-roster" else
                     {"acquisition": outcome}) if outcome else {}
            return {"ok": True, "revision": ctx.profile.revision, **extra}

    @app.post("/api/clock", dependencies=[Depends(authorize)])
    def clock_set(payload: s.ClockSet):
        with runtime.maintenance, runtime.database.transaction() as session:
            state = session.get(m.ServerClockState, 1)
            clock = ServerClock(state)
            clock.configure(payload.mode, payload.value)
            audit(session, "set-clock", mode=payload.mode, value=payload.value)
            return {"mode": state.mode, "now": clock.now()}

    @app.get("/api/backups", dependencies=[Depends(authorize)])
    def list_backups():
        return backups.list()

    @app.post("/api/backups", dependencies=[Depends(authorize)])
    def create_backup():
        result = backups.create()
        with runtime.maintenance, runtime.database.transaction() as session:
            audit(session, "backup", name=result["name"])
        return result

    @app.post("/api/backups/{name}/restore", dependencies=[Depends(authorize)])
    def restore_backup(name: str):
        try:
            result = backups.restore(name)
        except ValueError as exc:
            raise DomainError("RESTORE_REJECTED", str(exc)) from exc
        with runtime.maintenance, runtime.database.transaction() as session:
            audit(session, "restore", **result)
        return result

    @app.get("/api/logs", dependencies=[Depends(authorize)])
    def logs():
        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            audit_rows = session.scalars(select(m.AuditLog).order_by(m.AuditLog.id.desc()).limit(100)).all()
            return {"requests": request_log.snapshot() if request_log else [],
                    "logging": request_log.status() if request_log else None, "audit": [
                {"id": r.id, "actor": r.actor, "accountId": r.account_id, "action": r.action,
                 "detail": r.detail, "createdAt": r.created_at} for r in audit_rows]}

    @app.get("/api/settings", dependencies=[Depends(authorize)])
    def get_settings():
        return settings.model_dump(mode="json", exclude={"admin_password_hash"})

    return app
