"""Verified ordinary battle start contract of the frozen Android client."""

from fastapi import APIRouter, Request
from pydantic import Field, field_validator

from terralocal.server.api.schemas import Command, Identifier, SquadSlot
from terralocal.server.domain import battle, replays
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.protocol.battle_codec import FinishRequest, decode_finish, signature_battle_id
from terralocal.server.protocol.replay_codec import MAX_WIRE, decode_replay


class BattleSquad(Command):
    squadId: str = Field(min_length=1, max_length=16)
    name: str | None = Field(max_length=64)
    slots: list[SquadSlot | None] = Field(max_length=12)


class StartRequest(Command):
    stageId: Identifier
    squad: BattleSquad | None
    usePracticeTicket: bool
    assistFriend: dict | None
    isReplay: bool
    startTs: int = Field(ge=0, le=2**63 - 1)
    isRetro: bool
    pry: int = Field(ge=0)
    battleType: int = Field(ge=0, le=2)
    multiple: dict | None
    extra: dict | None

    @field_validator("usePracticeTicket", "isReplay", "isRetro", mode="before")
    @classmethod
    def wire_boolean(cls, value):
        return bool(value) if type(value) is int and value in {0, 1} else value


class SaveReplayRequest(Command):
    battleId: str = Field(min_length=36, max_length=36, pattern=r"^[0-9a-f-]+$")
    battleReplay: str = Field(min_length=1, max_length=MAX_WIRE)


class LoadReplayRequest(Command):
    stageId: Identifier


def router(runtime) -> APIRouter:
    api = APIRouter()

    @api.post("/quest/getBattleReplay")
    def load_replay(payload: LoadReplayRequest, request: Request):
        from terralocal.server.main import credentials

        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account, local_session = authenticate_session(session, *credentials(request))
            ctx = Context(session, runtime.require_data(), account.id, local_session=local_session)
            return {"result": 0, **replays.load_native(ctx, payload.stageId), "ts": ctx.now,
                    "playerDataDelta": {"modified": {}, "deleted": {}}}

    @api.post("/quest/battleStart")
    def start(payload: StartRequest, request: Request):
        from terralocal.server.main import credentials

        token, uid = credentials(request)
        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")

        def begin(ctx):
            # Enum constants are frozen metadata: Common=0, Continuous=1,
            # MULTIPLE=2. None of the additional modes is silently discarded.
            if (payload.usePracticeTicket or payload.isRetro
                    or payload.pry != 0 or payload.battleType != 0
                    or payload.assistFriend is not None or payload.multiple is not None
                    or payload.extra is not None):
                raise DomainError("BATTLE_MODE_UNSUPPORTED", "此战斗模式尚未实现", 501)
            # The frozen proxy UI sends name:null and an independent squad.
            # Display labels/startTs do not change formation or server time.
            return battle.native_start(ctx, payload.stageId, payload.squad.squadId if payload.squad else None,
                                       [slot.model_dump() if slot else None
                                        for slot in payload.squad.slots] if payload.squad else None,
                                       drop_rules=runtime.drop_rules, replay=payload.isReplay)

        return runtime.mutate(token, uid, key, "native-battle-start", payload.model_dump(), begin)

    @api.post("/quest/battleFinish")
    def finish(payload: FinishRequest, request: Request):
        from terralocal.server.main import credentials

        token, uid = credentials(request)
        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")

        def settle(ctx):
            battle_id = signature_battle_id(payload.battleData.isCheat)
            context = battle.native_context(ctx, battle_id)  # Includes ownership check.
            data = decode_finish(payload, [context["login_time"],
                                          ctx.profile.flags.get("loginTime", ctx.profile.last_online_at)])
            return battle.native_finish(
                ctx, data.battleId, data.stageId, complete_state=data.completeState,
                interrupted=data.interrupt, give_up=data.giveUp, percent=data.percent,
                kills=data.killCnt, valid_kills=data.validKillCnt,
                duration=data.battleData.completeTime, drop_rules=runtime.drop_rules)

        return runtime.mutate(token, uid, key, "native-battle-finish", payload.model_dump(), settle)

    @api.post("/quest/saveBattleReplay")
    def save_replay(payload: SaveReplayRequest, request: Request):
        from terralocal.server.main import credentials

        token, uid = credentials(request)
        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")

        def save(ctx):
            # Authenticate and check ownership before decompressing client data.
            source = battle.get_session(ctx, payload.battleId)
            record = decode_replay(payload.battleReplay)
            if ctx.data.stage(source.stage_id).get("stageType") == "CAMPAIGN":
                from terralocal.server.domain.campaign_battle import save_journal

                return save_journal(ctx, payload.battleId, record)
            return replays.save_native(ctx, payload.battleId, record)

        return runtime.mutate(token, uid, key, "native-replay-save", payload.model_dump(), save)

    return api
