"""Frozen confirmMissions request and its reward consumer (ELF 3ece1e7b).

REA VM constructors bind RUNEPACK=0, CHALLENGE=1 and TREASURE=2. A real
original-client treasure request also confirms integer 2. Reward values always
come from the matching map. Timed grants use the documented local policy.
"""

from typing import Annotated, Literal

from fastapi import Request
from pydantic import Field, field_validator

from terralocal.server.api.schemas import Command
from terralocal.server.protocol.crisis_v2_state import Key, Timestamp


class Mission(Command):
    id: Key
    type: Annotated[int, Field(ge=0, le=2)]


class ConfirmMissions(Command):
    mapId: Key
    missions: list[Mission] = Field(min_length=1, max_length=256)

    @field_validator("missions")
    @classmethod
    def unique_missions(cls, value):
        if len({(item.type, item.id) for item in value}) != len(value):
            raise ValueError("任务不能重复")
        return value

    def canonical(self):
        return self.model_copy(
            update={"missions": sorted(self.missions, key=lambda item: (item.type, item.id))}
        )


class MissionReward(Command):
    id: Key
    type: Literal["FURN", "CHAR_SKIN", "MATERIAL", "GOLD", "CARD_EXP", "CRS_SHOP_COIN_V2"]
    count: Annotated[int, Field(ge=1, le=2_000_000_000)]


class MissionResponse(Command):
    rewards: list[MissionReward] = Field(min_length=1, max_length=4096)
    ts: Timestamp


def handle_confirm_missions(runtime, payload: ConfirmMissions, request: Request):
    from terralocal.server.domain import crisis_v2_missions
    from terralocal.server.main import credentials

    payload = payload.canonical()
    key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
    # Transport retries retain their original delta. A new sequence/session
    # resolves the durable business receipt without applying a stale delta.
    return runtime.mutate(
        *credentials(request),
        key,
        "native-crisis-v2-missions",
        payload.model_dump(),
        lambda ctx: crisis_v2_missions.claim(ctx, payload, shop=runtime.crisis_v2_local_shop),
        preserve_result_ts=True,
    )
