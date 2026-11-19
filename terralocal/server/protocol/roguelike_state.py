"""Modern topic outer-state fields from the frozen PlayerRoguelikeV2 model.

Zero balances and empty histories are local initial state, not a claim that the
official server grants every mode, relic, band or challenge to a fresh account.
The no-run value is an object with null members: EntryViewModel.LoadData reads
the current object before it builds the theme list.
"""

import builtins
from typing import Annotated

from pydantic import Field

from terralocal.server.api.schemas import Command

Count = Annotated[int, Field(ge=0, le=2**31 - 1)]


class BattlePass(Command):
    point: Count = 0
    reward: dict[str, Count] = Field(default_factory=dict)


class Buff(Command):
    pointOwned: Count = 0
    pointCost: Count = 0
    unlocked: dict[str, Count] = Field(default_factory=dict)


class Mission(Command):
    updateId: str | None = None
    refresh: Count = 0
    # Slots need their own admitted rules before monthly missions are enabled.
    list: builtins.list[dict] = Field(default_factory=builtins.list, max_length=64)


class ItemUnlock(Command):
    state: Annotated[int, Field(ge=0, le=2)]
    progress: list[Count] = Field(default_factory=list, max_length=64)


class GradeUnlock(Command):
    state: Annotated[int, Field(ge=0, le=2)]


class Totem(Command):
    totem: dict[str, ItemUnlock] = Field(default_factory=dict)
    affix: dict[str, ItemUnlock] = Field(default_factory=dict)


class Weather(Command):
    main: dict[str, ItemUnlock] = Field(default_factory=dict)
    sub: dict[str, ItemUnlock] = Field(default_factory=dict)


class Collection(Command):
    band: dict[str, ItemUnlock] = Field(default_factory=dict)
    relic: dict[str, ItemUnlock] = Field(default_factory=dict)
    capsule: dict[str, ItemUnlock] = Field(default_factory=dict)
    activeTool: dict[str, ItemUnlock] = Field(default_factory=dict)
    mode: dict[str, ItemUnlock] = Field(default_factory=dict)
    modeGrade: dict[str, dict[str, GradeUnlock]] = Field(default_factory=dict)
    recruitSet: dict[str, ItemUnlock] = Field(default_factory=dict)
    bgm: dict[str, Count] = Field(default_factory=dict)
    pic: dict[str, Count] = Field(default_factory=dict)
    chatV2: dict[str, list[str]] = Field(default_factory=dict)
    endbook: dict[str, ItemUnlock] = Field(default_factory=dict)
    buff: dict[str, ItemUnlock] = Field(default_factory=dict)
    totem: Totem = Field(default_factory=Totem)
    chaos: dict[str, ItemUnlock] = Field(default_factory=dict)
    fragment: dict[str, ItemUnlock] = Field(default_factory=dict)
    disaster: dict[str, ItemUnlock] = Field(default_factory=dict)
    nodeUpgrade: dict[str, dict] = Field(default_factory=dict)
    copper: dict[str, ItemUnlock] = Field(default_factory=dict)
    wrath: dict[str, ItemUnlock] = Field(default_factory=dict)
    scrap: dict[str, ItemUnlock] = Field(default_factory=dict)
    weather: Weather = Field(default_factory=Weather)


class Bank(Command):
    show: bool = False
    current: Count = 0
    record: Count = 0
    totalPut: Count = 0
    reward: dict[str, Count] = Field(default_factory=dict)


class Record(Command):
    last: Annotated[int, Field(ge=0, le=2**63 - 1)] = 0
    stageCnt: dict[str, Count] = Field(default_factory=dict)
    bandCnt: dict[str, dict[str, Count]] = Field(default_factory=dict)
    bandGrade: dict[str, dict[str, Count]] = Field(default_factory=dict)
    history: list[dict] = Field(default_factory=list, max_length=1000)
    legacy: list[str] = Field(default_factory=list, max_length=1000)


class MonthTeam(Command):
    reward: dict[str, Count] = Field(default_factory=dict)
    mission: dict[str, list[Count]] = Field(default_factory=dict)


class ChallengeCollection(Command):
    exploreTool: dict[str, ItemUnlock] = Field(default_factory=dict)


class Challenge(Command):
    reward: dict[str, Count] = Field(default_factory=dict)
    grade: dict[str, str] = Field(default_factory=dict)
    collect: ChallengeCollection = Field(default_factory=ChallengeCollection)


class Activity(Command):
    roguelikeActivitySeedModeDatas: dict[str, dict] = Field(default_factory=dict)


class OuterState(Command):
    bp: BattlePass = Field(default_factory=BattlePass)
    buff: Buff = Field(default_factory=Buff)
    mission: Mission = Field(default_factory=Mission)
    collect: Collection = Field(default_factory=Collection)
    bank: Bank = Field(default_factory=Bank)
    record: Record = Field(default_factory=Record)
    monthTeam: MonthTeam = Field(default_factory=MonthTeam)
    challenge: Challenge = Field(default_factory=Challenge)
    activity: Activity = Field(default_factory=Activity)


def no_run() -> dict:
    return dict.fromkeys(("player", "map", "inventory", "game", "troop", "buff", "module"))
