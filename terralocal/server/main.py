from __future__ import annotations

import json
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException

from terralocal import __version__
from terralocal.server.api import schemas as s
from terralocal.server.domain import accounts, battle, mail, operators
from terralocal.server.domain.errors import DomainError
from terralocal.server.observability import RequestLog, schema
from terralocal.server.services.runtime import Runtime


def credentials(request: Request) -> tuple[str, str | None]:
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else (
        request.headers.get("secret", ""))
    return token, request.headers.get("uid")


def create_game_app(runtime: Runtime) -> FastAPI:
    settings = runtime.settings
    log = RequestLog(settings.data_dir / "logs")
    app = FastAPI(title="TerraLocal Game API", version=__version__, docs_url=None, redoc_url=None)
    app.state.runtime, app.state.request_log = runtime, log

    @app.middleware("http")
    async def observe(request: Request, call_next):
        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        # Buffer a bounded body once; a dishonest Content-Length cannot bypass this limit.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > settings.request_limit:
                return JSONResponse({"error": {"code": "REQUEST_TOO_LARGE"}, "result": 1}, status_code=413)
        request._body = bytes(body)
        request.state.body = bytes(body)
        try:
            response = await call_next(request)
        except Exception:
            log.append({"request_id": request_id, "route": request.url.path, "method": request.method,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2), "status": 500})
            raise
        response.headers["X-Request-ID"] = request_id
        entry = {"request_id": request_id, "route": request.url.path, "method": request.method,
                 "latency_ms": round((time.perf_counter() - started) * 1000, 2), "status": response.status_code}
        # Public bounded module enums help diagnose client-side failure even
        # when the corresponding HTTP response was 200. No body values or
        # authentication headers are included.
        if type(getattr(request.state, "sync_modules", None)) is int:
            entry["sync_modules"] = request.state.sync_modules
        if response.status_code >= 400:
            entry["host"] = request.url.hostname
            entry["query_keys"] = sorted(request.query_params.keys())
            if getattr(request.state, "error_code", None):
                entry["error_code"] = request.state.error_code
            if getattr(request.state, "auth_stage", None) in {"sdk", "u8", "game"}:
                entry["auth_stage"] = request.state.auth_stage
            try:
                entry["body_schema"] = schema(json.loads(request.state.body or b"{}"))
            except (ValueError, UnicodeError):
                entry["body_schema"] = "bytes"
        log.append(entry)
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        request.state.error_code = exc.code
        request.state.auth_stage = getattr(exc, "auth_stage", None)
        return JSONResponse({"result": 1, "error": {"code": exc.code, "message": exc.message}},
                            status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic errors include input values; never echo credentials or raw client bodies.
        return JSONResponse({"result": 1, "error": {"code": "INVALID_REQUEST", "fields": [
            {"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]}}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if exc.status_code != 404:
            return JSONResponse({"result": 1, "error": {"code": "HTTP_ERROR"}}, status_code=exc.status_code)
        try:
            body_schema = schema(json.loads(request.state.body or b"{}"))
        except (ValueError, UnicodeError):
            body_schema = {"type": "bytes"}
        log.append({"route": request.url.path, "method": request.method,
                    "host": request.url.hostname,
                    "headers_schema": sorted(request.headers.keys()), "body_schema": body_schema,
                    "query_keys": sorted(request.query_params.keys()),
                    "client_profile": settings.client_profile, "status": 501}, unknown=True)
        return JSONResponse({"result": 1, "error": {"code": "NOT_IMPLEMENTED", "route": request.url.path}},
                            status_code=501)

    @app.get("/health")
    def health():
        return {"server": "TerraLocal", "version": __version__, "database": runtime.database.integrity(),
                "gamedata": runtime.data.manifest if runtime.data else None,
                "client_profile": settings.client_profile, "client_verified": False,
                "logging": log.status()}

    @app.post("/local/v1/login")
    def local_login(payload: s.Login, request: Request):
        with runtime.maintenance, runtime.database.transaction() as session:
            return accounts.login(session, settings, **payload.model_dump(exclude_none=True))

    @app.post("/account/syncData")
    @app.post("/local/v1/sync")
    def sync(request: Request):
        return runtime.sync(*credentials(request))

    def mutate(request, payload, operation, action):
        token, uid = credentials(request)
        explicit_key = request.headers.get("idempotency-key")
        key = explicit_key or request.headers.get("seqnum", "")
        return runtime.mutate(token, uid, key, operation, payload.model_dump(), action,
                              account_scoped=bool(explicit_key))

    @app.post("/local/v1/operators/upgrade")
    def upgrade(payload: s.Upgrade, request: Request):
        return mutate(request, payload, "operator-upgrade", lambda ctx: operators.upgrade(
            ctx, payload.operatorId, [r.model_dump() for r in payload.materials]))

    @app.post("/local/v1/operators/evolve")
    def evolve(payload: s.OperatorId, request: Request):
        return mutate(request, payload, "operator-evolve", lambda ctx: operators.evolve(ctx, payload.operatorId))

    @app.post("/local/v1/operators/skill")
    def skill(payload: s.OperatorId, request: Request):
        return mutate(request, payload, "operator-skill", lambda ctx: operators.skill_level(ctx, payload.operatorId))

    @app.post("/local/v1/squads/formation")
    def formation(payload: s.Formation, request: Request):
        return mutate(request, payload, "formation", lambda ctx: operators.formation(
            ctx, payload.squadId, [r.model_dump() if r else None for r in payload.slots], payload.name))

    @app.post("/local/v1/battle/start")
    def battle_start(payload: s.BattleStart, request: Request):
        return mutate(request, payload, "battle-start", lambda ctx: battle.start(
            ctx, payload.stageId, payload.squadId, payload.practice))

    @app.post("/local/v1/battle/finish")
    def battle_finish(payload: s.BattleFinish, request: Request):
        return mutate(request, payload, "battle-finish", lambda ctx: battle.finish(
            ctx, payload.battleId, payload.stars, drop_rules=runtime.drop_rules,
            kills=payload.kills, duration=payload.duration))

    @app.post("/local/v1/battle/replay")
    def replay(payload: s.ReplaySave, request: Request):
        return mutate(request, payload, "battle-replay", lambda ctx: battle.save_replay(
            ctx, payload.battleId, payload.replay))

    @app.get("/local/v1/mail")
    def get_mail(request: Request):
        from terralocal.server.domain.context import Context
        from terralocal.server.domain.sessions import authenticate_session

        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            token, uid = credentials(request)
            account, _ = authenticate_session(session, token, uid)
            return {"mails": mail.list_mail(Context(session, runtime.require_data(), account.id))}

    @app.post("/local/v1/mail/claim")
    def claim_mail(payload: s.MailClaim, request: Request):
        return mutate(request, payload, "mail-claim", lambda ctx: mail.claim(ctx, payload.mailIds))

    @app.get("/assetbundle/official/Android/assets/{version}/{filename}")
    def asset(version: str, filename: str):
        return FileResponse(resources.file(version, filename))

    from terralocal.server.services.assets import FrozenAssets

    resources = FrozenAssets(settings)

    from terralocal.server.protocol import (
        appearance,
        auth,
        battles,
        bootstrap,
        campaign_battles,
        campaign_claims,
        cash_shop,
        gacha_history,
        gift_packs,
        headhunting,
        home_rotation,
        missions,
        operator_build,
        push,
        recruitment,
        roguelike,
        sdk,
        skin_shop,
        squads,
        status,
        story,
        voice,
        voucher_shop,
    )

    app.include_router(bootstrap.router(runtime))
    app.include_router(auth.router(runtime))
    app.include_router(sdk.router(runtime))
    app.include_router(voice.router(runtime))
    app.include_router(operator_build.router(runtime))
    app.include_router(appearance.router(runtime))
    app.include_router(home_rotation.router(runtime))
    app.include_router(skin_shop.router(runtime))
    app.include_router(voucher_shop.router(runtime))
    app.include_router(cash_shop.router(runtime))
    app.include_router(gift_packs.router(runtime))
    app.include_router(status.router(runtime))
    app.include_router(story.router(runtime))
    app.include_router(push.router(runtime))
    app.include_router(recruitment.router(runtime))
    app.include_router(headhunting.router(runtime))
    app.include_router(gacha_history.router(runtime))
    app.include_router(squads.router(runtime))
    app.include_router(battles.router(runtime))
    app.include_router(campaign_battles.router(runtime))
    app.include_router(campaign_claims.router(runtime))
    app.include_router(missions.router(runtime))
    app.include_router(roguelike.router(runtime))

    return app
