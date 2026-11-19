"""Frozen CN appearance requests; both replies use PlayerDeltaResponse."""

from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain import appearance


class AppearanceRequest(Command):
    charInstId: int = Field(ge=1, le=2**31 - 1)
    skinId: str = Field(min_length=1, max_length=128)


def router(runtime):
    api = APIRouter()

    def mutate(request, payload, operation, action):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return runtime.mutate(*credentials(request), key, operation, payload.model_dump(),
                              lambda ctx: action(ctx, payload.charInstId, payload.skinId))

    @api.post("/charBuild/changeCharSkin")
    def change_skin(payload: AppearanceRequest, request: Request):
        return mutate(request, payload, "appearance-skin", appearance.change_skin)

    @api.post("/user/changeSecretary")
    def change_secretary(payload: AppearanceRequest, request: Request):
        return mutate(request, payload, "appearance-secretary", appearance.change_secretary)

    return api
