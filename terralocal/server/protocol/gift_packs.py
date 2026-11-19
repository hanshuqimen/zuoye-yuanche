"""Frozen normal GP request envelopes; purchase fulfillment is transactional."""
from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain import gift_packs
from terralocal.server.domain.context import Context
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.protocol.sync import SyncDataAssembler


class BuyGiftPack(Command):
    goodId: Identifier
    enterTs: int = Field(ge=-1, le=253_402_271_999)


def current_purchase_response(ctx, result, *, payment=False):
    """A receipt preserves rewards but must not roll the native model back."""
    user = SyncDataAssembler(ctx).assemble()
    modified = dict(result["playerDataDelta"]["modified"])
    for key in list(modified):
        if key in user:
            modified[key] = user[key]
    modified["shop"] = {**modified.get("shop", {}), "GP": user["shop"]["GP"]}
    if payment:
        modified["status"] = user["status"]
        modified["shop"]["CASH"] = user["shop"]["CASH"]
    # GP purchases never delete an owned entity. If a historic receipt holds
    # deletions from a cost reaching zero, reassert the full current container.
    def still_deleted(current, removed):
        result = {}
        for key, value in removed.items():
            if key not in current:
                result[key] = value
            elif isinstance(value, dict) and isinstance(current[key], dict):
                nested = still_deleted(current[key], value)
                if nested:
                    result[key] = nested
        return result

    deleted = still_deleted(user, result["playerDataDelta"]["deleted"])
    return {**result, "ts": ctx.now, "revision": ctx.profile.revision,
            "playerDataDelta": {"modified": modified, "deleted": deleted}}


def router(runtime):
    api = APIRouter()

    @api.post("/shop/getGPGoodList")
    def goods(payload: Command, request: Request):
        from terralocal.server.main import credentials

        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account, _ = authenticate_session(session, *credentials(request))
            ctx = Context(session, runtime.require_data(), account.id)
            return {"result": 0, **gift_packs.list_goods(ctx), "ts": ctx.now,
                    "playerDataDelta": {"modified": {"shop": {"GP": gift_packs.project(ctx)}}, "deleted": {}}}

    @api.post("/shop/buyGPGood")
    def buy(payload: BuyGiftPack, request: Request):
        from terralocal.server.main import credentials

        token, uid = credentials(request)
        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        with runtime.maintenance:
            result = runtime.mutate(token, uid, key, "gift-pack-buy", payload.model_dump(),
                                    lambda ctx: gift_packs.buy(ctx, payload.goodId))
            with runtime.database.transaction(write=False) as session:
                account, _ = authenticate_session(session, token, uid)
                return current_purchase_response(Context(session, runtime.require_data(), account.id), result)

    return api
