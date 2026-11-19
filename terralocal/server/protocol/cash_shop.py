"""Frozen cash list and GS order envelopes; virtual SDK callbacks are separate."""
from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain import cash_shop, local_payments
from terralocal.server.domain.context import Context
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.protocol.shop_state import purchase_counters


class CreateOrder(Command):
    storeId: int = Field(ge=1, le=2**31 - 1)
    goodId: Identifier


class ConfirmOrder(Command):
    orderId: Identifier
    enterTs: int = Field(ge=-1, le=253_402_271_999)


def router(runtime):
    api = APIRouter()

    @api.post("/shop/getCashGoodList")
    def goods(payload: Command, request: Request):
        from terralocal.server.main import credentials

        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account, _ = authenticate_session(session, *credentials(request))
            ctx = Context(session, runtime.require_data(), account.id)
            return {"result": 0, **cash_shop.list_goods(ctx), "ts": ctx.now,
                    "playerDataDelta": {"modified": {"shop": {"CASH": purchase_counters(ctx)["CASH"]}},
                                        "deleted": {}}}

    @api.post("/pay/createOrder")
    def create(payload: CreateOrder, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        result = runtime.mutate(*credentials(request), key, "local-cash-order", payload.model_dump(),
            lambda ctx: local_payments.create(ctx, payload.storeId, payload.goodId, runtime.protocol_profile))
        # The frozen create response is a plain object, not a delta response.
        return {k: result[k] for k in ("result", "orderId", "extension", "orderIdList", "alertMinor", "errMsg")}

    @api.post("/pay/confirmOrder")
    def confirm(payload: ConfirmOrder, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        token, uid = credentials(request)
        with runtime.maintenance:
            result = runtime.mutate(token, uid, key, "local-cash-confirm", payload.model_dump(),
                lambda ctx: local_payments.confirm(ctx, payload.orderId, runtime.protocol_profile))
            # The order itself makes confirmation idempotent across sessions.
            # Reassert current counters/wallet after a lost response, even if
            # a receipt is replayed after another purchase changed the balance.
            with runtime.database.transaction(write=False) as session:
                account, _ = authenticate_session(session, token, uid)
                ctx = Context(session, runtime.require_data(), account.id)
                from terralocal.server.protocol.gift_packs import current_purchase_response

                return current_purchase_response(ctx, result, payment=True)

    return api
