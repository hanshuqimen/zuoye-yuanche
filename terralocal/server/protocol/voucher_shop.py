"""Frozen Low/High/Classic/Extra list and purchase DTOs."""

from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain import voucher_shop
from terralocal.server.domain.context import Context
from terralocal.server.domain.refresh import Module, prepare
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.protocol.status import ShopRefresh


class Purchase(Command):
    goodId: Identifier
    count: int = Field(ge=1, le=2_000_000_000)


def router(runtime):
    api = APIRouter()

    def add(shop, name):
        def list_goods(payload: Command, request: Request):
            from terralocal.server.main import credentials

            with runtime.maintenance, runtime.database.transaction(write=False) as session:
                account, _ = authenticate_session(session, *credentials(request))
                ctx = Context(session, runtime.require_data(), account.id)
                result = voucher_shop.list_goods(ctx, shop)
                cycle = voucher_shop.active_cycle(ctx, shop, required=True)
                return {"result": 0, **result, "ts": ctx.now,
                        "playerDataDelta": {"modified": {"shop": {shop: voucher_shop.project(ctx, cycle)}},
                                            "deleted": {}}}

        def buy(payload: Purchase, request: Request):
            from terralocal.server.main import credentials

            key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
            return runtime.mutate(*credentials(request), key, "voucher-buy-" + shop, payload.model_dump(),
                lambda ctx: voucher_shop.buy(ctx, shop, payload.goodId, payload.count))

        api.add_api_route("/shop/get" + name + "GoodList", list_goods, methods=["POST"])
        api.add_api_route("/shop/buy" + name + "Good", buy, methods=["POST"])

    for shop, name in (("LS", "Low"), ("HS", "High"), ("CLASSIC", "Classic"), ("ES", "Extra")):
        add(shop, name)

    @api.post("/shop/getGoodPurchaseState")
    def purchase_state(payload: ShopRefresh, request: Request):
        from terralocal.server.main import credentials

        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account, _ = authenticate_session(session, *credentials(request))
            ctx = Context(session, runtime.require_data(), account.id)
            derived = prepare(ctx, int(Module.GOOD_PURCHASE_STATE), payload.goodIdMap)
            return {**derived["16"]["goodPurchaseState"], "ts": ctx.now}

    return api
