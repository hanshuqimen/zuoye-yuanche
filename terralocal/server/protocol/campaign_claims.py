"""Frozen CampaignConfirmBreakRewardRequest and its dedicated transaction."""

from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain import campaign_claims


class BreakRewardRequest(Command):
    stageId: Identifier
    indexList: list[Annotated[int, Field(ge=0, le=127)]] = Field(min_length=1, max_length=128)


def router(runtime):
    api = APIRouter()

    @api.post("/campaignV2/getBreakReward")
    def claim(payload: BreakRewardRequest, request: Request):
        from terralocal.server.main import credentials

        token, uid = credentials(request)
        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return runtime.mutate(token, uid, key, "campaign-break-reward", payload.model_dump(),
            lambda ctx: campaign_claims.claim_breaks(ctx, payload.stageId, payload.indexList))

    return api
