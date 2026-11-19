"""Frozen single/ten headhunting request contracts and transactional responses."""

from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain import headhunting, standard_headhunting
from terralocal.server.domain.context import Context
from terralocal.server.domain.sessions import authenticate_session


class SingleRequest(Command):
    poolId: Identifier
    useTkt: int = Field(ge=-1, le=9)
    itemId: str | None = Field(default=None, max_length=96)


class CombineItem(Command):
    id: Identifier
    count: int = Field(ge=1, le=2_000_000_000)


class TenRequest(Command):
    poolId: Identifier
    useTkt: int = Field(ge=-1, le=9)
    itemList: list[CombineItem] | None = Field(default=None, max_length=10)


class DetailRequest(Command):
    poolId: Identifier
    gachaObjGroupType: int = Field(ge=0, le=4)


class ChooseRequest(Command):
    poolId: Identifier
    chooseChar: dict[str, list[Identifier]] = Field(max_length=2)


def router(runtime):
    api = APIRouter()

    def mutate(request, payload, count):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        operation = "headhunting-single" if count == 1 else "headhunting-ten"
        body = payload.model_dump()
        def action(ctx):
            draw = (headhunting.draw_newcomer if payload.poolId in ctx.data.headhunting.newcomer
                    else standard_headhunting.draw)
            return draw(ctx, payload.poolId, payload.useTkt, count,
                        body.get("itemId"), body.get("itemList"))

        return runtime.mutate(*credentials(request), key, operation, body, action)

    @api.post("/gacha/advancedGacha")
    def single(payload: SingleRequest, request: Request):
        return mutate(request, payload, 1)

    @api.post("/gacha/tenAdvancedGacha")
    def ten(payload: TenRequest, request: Request):
        return mutate(request, payload, 10)

    @api.post("/gacha/choosePoolUp")
    def choose(payload: ChooseRequest, request: Request):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return runtime.mutate(*credentials(request), key, "headhunting-select", payload.model_dump(),
                              lambda ctx: standard_headhunting.choose(ctx, payload.poolId, payload.chooseChar))

    @api.post("/gacha/getPoolDetail")
    def detail(payload: DetailRequest, request: Request):
        from terralocal.server.main import credentials

        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account, _ = authenticate_session(session, *credentials(request))
            ctx = Context(session, runtime.require_data(), account.id)
            return headhunting.pool_detail(ctx, payload.poolId, payload.gachaObjGroupType)

    return api
