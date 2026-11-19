"""Frozen client's squad contract, separate from the local formation API."""

from fastapi import APIRouter, Request
from pydantic import Field, field_validator

from terralocal.server.api.schemas import Command, SquadSlot
from terralocal.server.domain import operators


class FormationRequest(Command):
    squadId: str = Field(min_length=1, max_length=16)
    slots: list[SquadSlot | None] = Field(max_length=12)
    changeSkill: bool

    @field_validator("changeSkill", mode="before")
    @classmethod
    def wire_boolean(cls, value):
        # The frozen request declares bool, but its observed JSON uses int.
        # Preserve strict validation elsewhere; accept only the two bool values.
        return bool(value) if type(value) is int and value in {0, 1} else value


def router(runtime) -> APIRouter:
    api = APIRouter()

    @api.post("/quest/squadFormation")
    def formation(payload: FormationRequest, request: Request):
        from terralocal.server.main import credentials

        token, uid = credentials(request)
        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")

        def save(ctx):
            operators.formation(ctx, payload.squadId,
                                [slot.model_dump() if slot else None for slot in payload.slots],
                                change_skill=payload.changeSkill)
            # SquadFormationResponse declares no fields beyond its delta parent.
            return {}

        return runtime.mutate(token, uid, key, "native-squad-formation", payload.model_dump(), save)

    return api
