from fastapi import APIRouter, Query, Request, Response
from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain import (
    crisis_v2,
    crisis_v2_battles,
    crisis_v2_claims,
    crisis_v2_history,
    crisis_v2_journals,
    crisis_v2_native,
    crisis_v2_native_shop,
    crisis_v2_shop,
    crisis_v2_unlocks,
)
from terralocal.server.protocol.battles import BattleSquad
from terralocal.server.protocol.crisis_v2_codec import CrisisFinishRequest
from terralocal.server.protocol.crisis_v2_missions import ConfirmMissions, handle_confirm_missions
from terralocal.server.protocol.crisis_v2_shop import BuyGood, GetGoodList
from terralocal.server.protocol.crisis_v2_state import Key


class GetInfo(Command):
    pass


class StartRequest(Command):
    mapId: Key
    runeSlots: list[Key] = Field(max_length=4096)
    squad: BattleSquad
    assistFriend: dict | None


class ClaimRequest(Command):
    seasonId: Key
    mapId: Key
    slotId: Key


class ShopCredit(Command):
    mapId: Key


class ShopBuy(Command):
    offerId: Key


def router(runtime):
    api = APIRouter()

    @api.post("/crisisV2/getInfo")
    def get_info(payload: GetInfo, request: Request):
        from terralocal.server.main import credentials

        return runtime.mutate(*credentials(request), request.headers.get("seqnum", ""),
                              "crisis-v2-get-info", payload.model_dump(), crisis_v2.get_info)

    @api.post("/crisisV2/battleStart")
    def start(payload: StartRequest, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return runtime.mutate(*credentials(request), key, "native-crisis-v2-start", payload.model_dump(),
            lambda ctx: crisis_v2_battles.start(ctx, payload.mapId, payload.squad.squadId,
                [slot.model_dump() if slot else None for slot in payload.squad.slots], payload.runeSlots,
                assist_friend=payload.assistFriend))

    @api.post("/crisisV2/battleFinish")
    def finish(payload: CrisisFinishRequest, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return runtime.mutate(*credentials(request), key, "native-crisis-v2-finish", payload.model_dump(),
                              lambda ctx: crisis_v2_native.finish(
                                  ctx, payload, archive_journal=runtime.settings.crisis_archive_replays),
                              preserve_result_ts=True)

    @api.post("/crisisV2/confirmMissions")
    def confirm_missions(payload: ConfirmMissions, request: Request):
        return handle_confirm_missions(runtime, payload, request)

    @api.post("/crisisV2/getGoodList")
    def native_shop_view(payload: GetGoodList, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return runtime.mutate(*credentials(request), key, "native-crisis-v2-shop-list", payload.model_dump(),
                              lambda ctx: crisis_v2_native_shop.view(
                                  ctx, runtime.crisis_v2_native_shop, local_shop=runtime.crisis_v2_local_shop))

    @api.post("/crisisV2/buyGood")
    def native_shop_buy(payload: BuyGood, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return runtime.mutate(*credentials(request), key, "native-crisis-v2-shop-buy", payload.model_dump(),
                              lambda ctx: crisis_v2_native_shop.buy(
                                  ctx, runtime.crisis_v2_native_shop, payload,
                                  local_shop=runtime.crisis_v2_local_shop))

    @api.post("/local/v1/crisis-v2/claim-treasure")
    def claim_treasure(payload: ClaimRequest, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key", "")
        return runtime.mutate(*credentials(request), key, "local-crisis-v2-claim-treasure", payload.model_dump(),
                              lambda ctx: crisis_v2_claims.claim(ctx, payload.seasonId, payload.mapId,
                                                                payload.slotId), account_scoped=True)


    @api.post("/local/v1/crisis-v2/unlock-rune")
    def unlock_rune(payload: ClaimRequest, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key", "")
        return runtime.mutate(*credentials(request), key, "local-crisis-v2-unlock-rune", payload.model_dump(),
                              lambda ctx: crisis_v2_unlocks.unlock(ctx, payload.seasonId, payload.mapId,
                                                                  payload.slotId), account_scoped=True)


    def read_history(request, action):
        from terralocal.server.domain.context import Context
        from terralocal.server.domain.sessions import authenticate_session
        from terralocal.server.main import credentials

        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account, local_session = authenticate_session(session, *credentials(request))
            ctx = Context(session, runtime.require_data(), account.id, local_session=local_session)
            return action(ctx)

    @api.get("/local/v1/crisis-v2/history")
    def recent_history(request: Request, offset: int = Query(0, ge=0, le=1_000_000),
                       limit: int = Query(20, ge=1, le=50)):
        return read_history(request, lambda ctx: crisis_v2_history.recent(ctx, limit=limit, offset=offset))

    @api.get("/local/v1/crisis-v2/history/{battle_id}")
    def battle_record(battle_id: str, request: Request):
        return read_history(request, lambda ctx: crisis_v2_history.detail(ctx, battle_id))


    @api.get("/local/v1/crisis-v2/shop")
    def shop_view(request: Request):
        return read_history(request, lambda ctx: crisis_v2_shop.view(ctx, runtime.crisis_v2_local_shop))

    @api.post("/local/v1/crisis-v2/shop/claim-credit")
    def shop_credit(payload: ShopCredit, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key", "")
        return runtime.mutate(*credentials(request), key, "local-crisis-shop-credit", payload.model_dump(),
                              lambda ctx: crisis_v2_shop.claim_credit(ctx, runtime.crisis_v2_local_shop,
                                                                      payload.mapId), account_scoped=True)

    @api.post("/local/v1/crisis-v2/shop/buy")
    def shop_buy(payload: ShopBuy, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key", "")
        return runtime.mutate(*credentials(request), key, "local-crisis-shop-buy", payload.model_dump(),
                              lambda ctx: crisis_v2_shop.buy(ctx, runtime.crisis_v2_local_shop, payload.offerId),
                              account_scoped=True)

    @api.get("/local/v1/crisis-v2/history/{battle_id}/journal")
    def battle_journal(battle_id: str, request: Request, response: Response):
        from terralocal.server.domain.errors import DomainError

        def load(ctx):
            if not runtime.settings.crisis_archive_replays:
                raise DomainError("CRISIS_V2_JOURNAL_NOT_FOUND", "此战斗没有已归档的原始日志", 404)
            return crisis_v2_journals.load(ctx, battle_id)

        response.headers["Cache-Control"] = "no-store"
        return read_history(request, load)

    return api
