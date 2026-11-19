"""Frozen UpgradeCharRequest / EvolveCharRequest, returning inherited player delta only."""

from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command, ItemAmount
from terralocal.server.domain import operators
from terralocal.server.domain.errors import DomainError


class UpgradeChar(Command):
    charInstId: int = Field(ge=1)
    expMats: list[ItemAmount] = Field(min_length=1, max_length=20)


class EvolveChar(Command):
    charInstId: int = Field(ge=1)
    destEvolvePhase: int = Field(ge=1, le=2)


def router(runtime):
    api = APIRouter()

    def mutate(request, payload, operation, action):
        from terralocal.server.main import credentials

        return runtime.mutate(*credentials(request), request.headers.get("seqnum", ""),
                              operation, payload.model_dump(), action)

    @api.post("/charBuild/upgradeChar")
    def upgrade(payload: UpgradeChar, request: Request):
        def action(ctx):
            operators.upgrade(ctx, payload.charInstId, [item.model_dump() for item in payload.expMats])
            return {}

        return mutate(request, payload, "native-operator-upgrade", action)

    @api.post("/charBuild/evolveChar")
    def evolve(payload: EvolveChar, request: Request):
        def action(ctx):
            op = ctx.operator(payload.charInstId)
            if payload.destEvolvePhase == op.evolve_phase:
                return {}  # The requested phase was already achieved; never charge it twice.
            if payload.destEvolvePhase != op.evolve_phase + 1:
                raise DomainError("EVOLVE_PHASE_CONFLICT", "精英化目标与当前阶段不一致", 409)
            operators.evolve(ctx, payload.charInstId)
            return {}

        return mutate(request, payload, "native-operator-evolve", action)

    return api
