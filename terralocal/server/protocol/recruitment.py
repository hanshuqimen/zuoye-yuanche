"""Frozen CN 2.7.71 public recruitment requests and inherited delta responses."""

from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain import recruitment
from terralocal.server.domain.context import Context
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.protocol.delta import diff
from terralocal.server.protocol.sync import SyncDataAssembler


class SlotRequest(Command):
    slotId: int = Field(ge=0, le=3)


class StartRequest(SlotRequest):
    tagList: list[int] = Field(max_length=3)
    specialTagId: int = -1
    duration: int = Field(ge=600, le=32400)


class BoostRequest(SlotRequest):
    buy: int = Field(ge=0, le=2)


def router(runtime):
    api = APIRouter()

    def mutate(request, payload, operation, action):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return runtime.mutate(*credentials(request), key, operation, payload.model_dump(), action)

    @api.post("/gacha/syncNormalGacha")
    def sync_recruit(payload: Command, request: Request):
        from terralocal.server.main import credentials

        with runtime.maintenance, runtime.database.transaction() as session:
            account, _ = authenticate_session(session, *credentials(request))
            ctx = Context(session, runtime.require_data(), account.id)
            before = SyncDataAssembler(ctx).assemble()
            recruitment.sync_slots(ctx)
            after = SyncDataAssembler(ctx).assemble()
            delta = diff(before, after)
            if delta["modified"] or delta["deleted"]:
                ctx.profile.revision += 1
            delta["modified"]["recruit"] = after["recruit"]
            return {"playerDataDelta": delta}

    @api.post("/gacha/normalGacha")
    def start(payload: StartRequest, request: Request):
        return mutate(request, payload, "recruit-start", lambda ctx: recruitment.start(
            ctx, payload.slotId, payload.tagList, payload.duration, payload.specialTagId))

    @api.post("/gacha/boostNormalGacha")
    def boost(payload: BoostRequest, request: Request):
        return mutate(request, payload, "recruit-boost", lambda ctx: recruitment.boost(ctx, payload.slotId, payload.buy))

    @api.post("/gacha/cancelNormalGacha")
    def cancel(payload: SlotRequest, request: Request):
        return mutate(request, payload, "recruit-cancel", lambda ctx: recruitment.cancel(ctx, payload.slotId))

    @api.post("/gacha/finishNormalGacha")
    def finish(payload: SlotRequest, request: Request):
        return mutate(request, payload, "recruit-finish", lambda ctx: recruitment.finish(ctx, payload.slotId))

    return api
