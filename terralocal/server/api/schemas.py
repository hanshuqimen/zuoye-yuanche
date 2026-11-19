from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(min_length=1, max_length=96)]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Login(Command):
    name: str | None = Field(default=None, max_length=64)
    uid: str | None = Field(default=None, max_length=32)
    password: str | None = Field(default=None, max_length=256)
    token: str | None = Field(default=None, max_length=256)


class AccountCreate(Command):
    name: str = Field(min_length=1, max_length=64)
    preset: str = "Vanilla"
    password: str | None = Field(default=None, max_length=256)


class ItemAmount(Command):
    id: Identifier
    count: int = Field(ge=1, le=1_000_000)


class Upgrade(Command):
    operatorId: int = Field(ge=1)
    materials: list[ItemAmount] = Field(min_length=1, max_length=20)


class OperatorId(Command):
    operatorId: int = Field(ge=1)


class SquadSlot(Command):
    charInstId: int = Field(ge=1)
    skillIndex: int = Field(default=0, ge=-1, le=2)
    currentEquip: str | None = None


class Formation(Command):
    squadId: str = Field(min_length=1, max_length=16)
    slots: list[SquadSlot | None] = Field(max_length=12)
    name: str | None = Field(default=None, min_length=1, max_length=32)


class BattleStart(Command):
    stageId: Identifier
    squadId: str = "0"
    practice: bool = False


class BattleFinish(Command):
    battleId: str = Field(min_length=1, max_length=36)
    stars: int = Field(ge=0, le=3)
    kills: int = Field(default=0, ge=0, le=100_000)
    duration: float = Field(default=0.0, ge=0, le=86400, allow_inf_nan=False)

    @field_validator("duration")
    @classmethod
    def normalize_zero_duration(cls, value: float) -> float:
        return 0.0 if value == 0 else value


class ReplaySave(Command):
    battleId: str = Field(min_length=1, max_length=36)
    replay: dict


class MailClaim(Command):
    mailIds: list[int] = Field(min_length=1, max_length=100)


class ClockSet(Command):
    mode: Literal["realtime", "fixed", "offset"]
    value: int = 0
