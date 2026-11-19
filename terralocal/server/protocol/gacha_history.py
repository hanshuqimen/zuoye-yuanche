"""Frozen `/gacha` WebView shell and its observed personal-history contracts.

The native SDKv2 bridge was verified to pass its U8 credential on 2026-10-12.
Game mutations retain their separate game-session authentication requirements.
"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from terralocal.server.domain import gacha_history
from terralocal.server.protocol.auth import authenticate_kind
from terralocal.server.services.gacha_webview import VERSION, FrozenGachaWebview


def router(runtime) -> APIRouter:
    api = APIRouter()
    webview = FrozenGachaWebview(runtime.settings)

    @api.get("/gacha")
    def page():
        return webview.response(VERSION, "index.html", page=True)

    @api.get("/webview/gacha/{version}/{filename:path}")
    def asset(version: str, filename: str):
        return webview.response(version, filename)

    @api.get("/api/gacha/cate")
    def categories(code: str = Query(min_length=1, max_length=256),
                   poolId: str | None = Query(default=None, min_length=1, max_length=96)):
        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account = authenticate_kind(session, code, None, "u8")
            data = gacha_history.categories(session, runtime.require_data(), account.id, poolId)
        return JSONResponse({"code": 0, "data": data, "msg": ""}, headers={"Cache-Control": "no-store"})

    @api.get("/api/gacha/history")
    def history(code: str = Query(min_length=1, max_length=256),
                category: str = Query(min_length=1, max_length=32),
                gachaTs: str | None = Query(default=None, pattern=r"^(0|[1-9][0-9]{0,18})$"),
                pos: str | None = Query(default=None, pattern=r"^[1-9][0-9]{0,18}$")):
        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account = authenticate_kind(session, code, None, "u8")
            data = gacha_history.history(session, runtime.require_data(), account.id, category,
                                        int(gachaTs) if gachaTs is not None else None,
                                        int(pos) if pos is not None else None)
        return JSONResponse({"code": 0, "data": data, "msg": ""}, headers={"Cache-Control": "no-store"})

    return api
