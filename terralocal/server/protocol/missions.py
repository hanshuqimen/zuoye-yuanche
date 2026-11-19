"""Frozen ConfirmMissionRequest / PlayerDeltaResponse contract."""

from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain import missions


class ConfirmMission(Command):
    missionId: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_.-]+$")


def router(runtime):
    api = APIRouter()

    @api.post("/mission/confirmMission")
    def confirm_mission(payload: ConfirmMission, request: Request):
        from terralocal.server.main import credentials

        return runtime.mutate(*credentials(request), request.headers.get("seqnum", ""),
                              "mission-confirm", payload.model_dump(),
                              lambda ctx: missions.confirm(ctx, payload.missionId))

    return api
