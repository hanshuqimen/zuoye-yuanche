from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain import crisis_v2, crisis_v2_battles, crisis_v2_native
from terralocal.server.protocol.battles import BattleSquad
from terralocal.server.protocol.crisis_v2_codec import CrisisFinishRequest
from terralocal.server.protocol.crisis_v2_state import Key


class GetInfo(Command):
    pass


class StartRequest(Command):
    mapId: Key
    runeSlots: list[Key] = Field(max_length=4096)
    squad: BattleSquad
    assistFriend: dict | None


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
                              lambda ctx: crisis_v2_native.finish(ctx, payload), preserve_result_ts=True)

    return api
