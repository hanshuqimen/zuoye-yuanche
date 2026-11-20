"""Frozen Crisis V2 finish-specific fields, separate from common rewards.

Loaded M162480 copies runeCount[0:2] into Param.runeCountOld/Current only
when its length is exactly two. These counts are not the six score axes.
This schema does not implement a battle, an outcome or an unlock award.
"""

from typing import Annotated

from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.protocol.crisis_v2_state import Count, Key, Timestamp

Score = Annotated[int, Field(ge=-(2**31), le=2**31 - 1)]
ScoreAxes = Annotated[list[Score], Field(min_length=6, max_length=6)]
RuneCounts = Annotated[list[Count], Field(min_length=2, max_length=2)]


class FinishDetails(Command):
    mapId: Key
    scoreRecord: ScoreAxes
    scoreCurrent: ScoreAxes
    isNewRecord: bool
    commentNew: list[Key]
    commentOld: list[Key]
    runeCount: RuneCounts
    ts: Timestamp
    runeIds: list[Key]
