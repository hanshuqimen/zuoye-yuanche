"""Frozen home preset DTOs. Route names require native verification per profile."""

from fastapi import APIRouter, Request
from pydantic import Field, field_validator

from terralocal.server.api.schemas import Command
from terralocal.server.domain import home_rotation


class PresetRequest(Command):
    instId: str = Field(min_length=1, max_length=128)


class Slot(Command):
    charId: str = Field(min_length=1, max_length=96)
    skinId: str = Field(min_length=1, max_length=128)
    skinSp: bool = False

    @field_validator("skinSp", mode="before")
    @classmethod
    def native_boolean(cls, value):
        return bool(value) if type(value) is int and value in (0, 1) else value


class PresetData(Command):
    name: str | None = Field(default=None, max_length=64)
    background: str | None = Field(default=None, max_length=128)
    homeTheme: str | None = Field(default=None, max_length=128)
    profile: str | None = Field(default=None, max_length=128)
    profileInst: str | None = Field(default=None, max_length=10)
    profileSp: bool | None = None
    slots: list[Slot] | None = Field(default=None, max_length=1024)

    @field_validator("profileSp", mode="before")
    @classmethod
    def native_boolean(cls, value):
        return bool(value) if type(value) is int and value in (0, 1) else value


class UpdateRequest(PresetRequest):
    flag: int = Field(ge=1, le=31)
    data: PresetData


def router(runtime):
    api = APIRouter()

    def mutate(request, payload, operation, action):
        from terralocal.server.main import credentials

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        body = payload.model_dump()
        return runtime.mutate(*credentials(request), key, operation, body, lambda ctx: action(ctx, **body))

    @api.post("/charRotation/createPreset")
    def create(payload: Command, request: Request):
        return mutate(request, payload, "home-preset-create", home_rotation.create)

    @api.post("/charRotation/deletePreset")
    def remove(payload: PresetRequest, request: Request):
        return mutate(request, payload, "home-preset-delete", lambda ctx, instId: home_rotation.remove(ctx, instId))

    @api.post("/charRotation/setCurrent")
    def set_current(payload: PresetRequest, request: Request):
        return mutate(request, payload, "home-preset-current", lambda ctx, instId: home_rotation.set_current(ctx, instId))

    @api.post("/charRotation/updatePreset")
    def update(payload: UpdateRequest, request: Request):
        return mutate(request, payload, "home-preset-update",
                      lambda ctx, instId, flag, data: home_rotation.update(ctx, instId, flag, data))

    return api
