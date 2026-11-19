"""Frozen six-field campaign start and shared encrypted finish envelope."""

from fastapi import APIRouter, Request
from pydantic import Field, field_validator

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain import campaign_battle
from terralocal.server.domain.errors import DomainError
from terralocal.server.protocol.battle_codec import FinishRequest, decode_campaign_finish, signature_battle_id
from terralocal.server.protocol.battles import BattleSquad


class StartRequest(Command):
    usePracticeTicket: bool
    stageId: Identifier
    squad: BattleSquad
    assistFriend: dict | None
    isReplay: bool
    startTs: int = Field(ge=0, le=2**63 - 1)

    @field_validator("usePracticeTicket", "isReplay", mode="before")
    @classmethod
    def wire_boolean(cls, value):
        return bool(value) if type(value) is int and value in {0, 1} else value


def router(runtime):
    api = APIRouter()

    @api.post("/campaignV2/battleStart")
    def start(payload: StartRequest, request: Request):
        from terralocal.server.main import credentials

        def begin(ctx):
            if payload.usePracticeTicket or payload.isReplay or payload.assistFriend is not None:
                raise DomainError("CAMPAIGN_MODE_UNSUPPORTED", "此剿灭战斗模式尚未实现", 501)
            return campaign_battle.start(ctx, payload.stageId, payload.squad.squadId,
                [slot.model_dump() if slot else None for slot in payload.squad.slots], drop_rules=runtime.drop_rules)

        token, uid = credentials(request)
        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return runtime.mutate(token, uid, key, "campaign-battle-start", payload.model_dump(), begin)

    @api.post("/campaignV2/battleFinish")
    def finish(payload: FinishRequest, request: Request):
        from terralocal.server.main import credentials

        def settle(ctx):
            battle_id = signature_battle_id(payload.battleData.isCheat)
            saved = campaign_battle.context(ctx, battle_id)
            data = decode_campaign_finish(payload, [saved["login_time"],
                ctx.profile.flags.get("loginTime", ctx.profile.last_online_at)])
            return campaign_battle.finish(ctx, data)

        token, uid = credentials(request)
        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return runtime.mutate(token, uid, key, "campaign-battle-finish", payload.model_dump(), settle)

    return api
