"""Frozen Crisis V2 wire fields, including token-verified JsonProperty aliases."""

from typing import Annotated

from pydantic import ConfigDict, Field

from terralocal.server.api.schemas import Command

Count = Annotated[int, Field(ge=0, le=2**31 - 1)]
Timestamp = Annotated[int, Field(ge=0, le=2**63 - 1)]
Key = Annotated[str, Field(min_length=1, max_length=160)]
Scores = Annotated[list[Count], Field(min_length=6, max_length=6)]
RuneState = Annotated[int, Field(ge=0, le=3)]
NodeState = Annotated[int, Field(ge=0, le=2)]


class BasicMapInfo(Command):
    state: bool
    scoreTotal: Scores
    rune: dict[Key, RuneState]
    challenge: dict[Key, NodeState]


class RewardInfo(Command):
    state: NodeState
    progress: Count


class PermanentMapInfo(BasicMapInfo):
    scoreSingle: Scores
    comment: list[Key]
    exRunes: dict[Key, RuneState]
    runePack: dict[Key, NodeState]
    reward: dict[Key, RewardInfo]


class SocialInfo(Command):
    assistCnt: Count
    maxPnt: Count
    chars: list[dict]


class SeasonState(Command):
    coin: Count
    permanent: PermanentMapInfo
    temporary: dict[Key, BasicMapInfo]
    social: SocialInfo


class ShopState(Command):
    coin: Count
    info: list[dict]
    progressInfo: dict[Key, dict]


class CrisisV2State(Command):
    model_config = ConfigDict(populate_by_name=True)

    # Named PropertyName attributes, bound to fields 16005/16009 and the
    # JsonPropertyAttribute setter. CLR names are not the wire names.
    currentSeason: str = Field(alias="current", max_length=160)
    seasons: dict[Key, SeasonState]
    shop: ShopState
    newRecordTs: Timestamp
    nextRefreshTs: Timestamp = Field(alias="nst")
