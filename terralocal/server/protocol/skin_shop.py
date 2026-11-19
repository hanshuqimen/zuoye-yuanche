"""Frozen CN ordinary outfit catalog and one-outfit purchase contracts."""

from fastapi import APIRouter, Request
from pydantic import Field, field_validator

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain import skin_shop
from terralocal.server.domain.context import Context
from terralocal.server.domain.sessions import authenticate_session


class CatalogRequest(Command):
    charIdList: list[Identifier] | None = Field(default=None, max_length=1024)


class PurchaseRequest(Command):
    goodId: Identifier
    isSpecial: bool = False
    enterTs: int = Field(ge=-1, le=253_402_271_999)

    @field_validator("isSpecial", mode="before")
    @classmethod
    def native_boolean(cls, value):
        # The frozen client's actual ordinary purchase encodes its CLR bool
        # as an integer. Accept only that wire representation and real bools.
        if type(value) is int and value in (0, 1):
            return bool(value)
        return value


def router(runtime):
    api = APIRouter()

    @api.post("/shop/getSkinGoodList")
    def list_goods(payload: CatalogRequest, request: Request):
        from terralocal.server.main import credentials

        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account, _ = authenticate_session(session, *credentials(request))
            ctx = Context(session, runtime.require_data(), account.id)
            result = skin_shop.list_goods(ctx, runtime.skin_shop_catalog, payload.charIdList)
            return {"result": 0, **result, "ts": ctx.now,
                    "playerDataDelta": {"modified": {}, "deleted": {}}}

    @api.post("/shop/buySkinGood")
    def buy(payload: PurchaseRequest, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        # enterTs is observed UI metadata. Availability always uses server time;
        # client timestamps, prices and ownership never authorize a purchase.
        return runtime.mutate(*credentials(request), key, "skin-shop-buy", payload.model_dump(),
                              lambda ctx: skin_shop.buy(ctx, runtime.skin_shop_catalog,
                                                        payload.goodId, is_special=payload.isSpecial))

    return api
