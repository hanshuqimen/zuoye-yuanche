"""Explicitly supported modules of the current client's incremental refresh."""

from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.refresh import (
    Module,
    complete_refresh,
    is_calendar_refresh,
    last_refreshed_at,
    prepare,
)
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import diff
from terralocal.server.protocol.sync import SyncDataAssembler

SHOP_MODULE = int(Module.GOOD_PURCHASE_STATE)
# ShopPurchaseState.furnShop has JsonProperty("CASH") in this frozen
# client. PlayerShop uses a separate FURNI property for furniture saves.
Shop = Literal["LS", "HS", "ES", "CASH", "GP", "SOCIAL", "CLASSIC"]
Goods = Annotated[list[Identifier], Field(max_length=2048)]


class ShopRefresh(Command):
    goodIdMap: dict[Shop, Goods] = Field(default_factory=dict, max_length=7)


class Refresh(Command):
    modules: int = Field(ge=0, le=2**31 - 1)
    params: dict[str, ShopRefresh] = Field(default_factory=dict, max_length=1)


def router(runtime) -> APIRouter:
    api = APIRouter()

    @api.post("/account/syncStatus")
    def sync_status(payload: Refresh, request: Request):
        from terralocal.server.main import credentials

        # Module numbers are bounded public protocol enums, never credentials.
        request.state.sync_modules = payload.modules
        with runtime.maintenance, runtime.database.transaction() as session:
            account, _ = authenticate_session(session, *credentials(request))
            if set(payload.params) - {"16"} or (payload.params and not payload.modules & SHOP_MODULE):
                raise DomainError("INVALID_SYNC_MODULE", "刷新参数与所选模块不匹配")
            ctx = Context(session, runtime.require_data(), account.id)
            goods = payload.params["16"].goodIdMap if "16" in payload.params else {}
            result = prepare(ctx, payload.modules, goods)
            # A connected client can still hold the previous period's mission
            # view. Comparing two current-period views would lose those deletions
            # at rollover. Repeating this delta after a full snapshot is safe.
            period_at = last_refreshed_at(ctx) if is_calendar_refresh(payload.modules) else ctx.now
            before = SyncDataAssembler(ctx, period_at=period_at).assemble()
            ctx.sanity()
            complete_refresh(ctx, payload.modules)
            after = SyncDataAssembler(ctx).assemble()
            delta = diff(before, after)
            if delta["modified"] or delta["deleted"]:
                ctx.profile.revision += 1
            if ctx.rows(m.ShopState):
                if payload.modules & SHOP_MODULE:
                    # Refresh counters without changing unknown storefront cycle
                    # metadata. An untouched shop already has the full snapshot.
                    delta["modified"]["shop"] = {
                        key: ({section: {"info": row["info"]} for section, row in value.items()}
                              if key == "GP" else value)
                        for key, value in after["shop"].items()}
                elif payload.modules & Module.CASH_PURCHASE_STATE:
                    delta["modified"]["shop"] = {"CASH": after["shop"]["CASH"]}
            if payload.modules & (Module.UNREAD_MAILS | Module.FRIEND_REQ | Module.CLUE_STATE):
                delta["modified"]["pushFlags"] = after["pushFlags"]
            # Reassert the requested account branch even when the counters are
            # unchanged. Reads do not create purchases or rewards.
            return {"ts": ctx.now, "result": result, "playerDataDelta": delta}

    return api
