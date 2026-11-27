"""Crisis shop wire models bound to the frozen 2.7.71 metadata and REA calls.

Shop dates, initial stock and progression policies belong to the admitted
catalog, not to these DTOs. Common availCount is remaining stock on the wire.
"""

from typing import Annotated, Literal

from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.protocol.crisis_v2_state import Key

Amount = Annotated[int, Field(ge=1, le=2_000_000_000)]
Count = Annotated[int, Field(ge=0, le=2_000_000_000)]
Stock = Annotated[int, Field(ge=-1, le=2_000_000_000)]


class GetGoodList(Command):
    pass


class BuyGood(Command):
    goodId: Key
    count: Amount
    perm: Annotated[int, Field(ge=0, le=1)]


class Item(Command):
    id: Key
    type: Literal["MATERIAL", "GOLD", "CARD_EXP", "FURN", "CHAR_SKIN", "CHAR"]
    count: Amount


class CommonGood(Command):
    goodId: Key
    displayName: str | None = Field(default=None, max_length=256)
    item: Item | None
    progressGoodId: Key | None
    price: Count
    availCount: Stock
    itemSupplyTime: Annotated[int, Field(ge=-1, le=2**63 - 1)]


class PermanentGood(CommonGood):
    isSingle: Annotated[int, Field(ge=0, le=1)]
    slotId1: Count
    slotId2: Count
    seasonId: Key
    title: Literal["SEASON", "REMASTERED", "NONE"]


class SeasonGood(CommonGood):
    slotId: Count
    rarity: str = Field(min_length=1, max_length=64)


class ProgressGood(Command):
    item: Item
    displayName: str | None = Field(default=None, max_length=256)
    order: Amount
    price: Amount


class GoodList(Command):
    permanent: list[PermanentGood] = Field(max_length=4096)
    season: list[SeasonGood] = Field(max_length=4096)
    progressGoodList: dict[Key, list[ProgressGood]] = Field(max_length=4096)


class BoughtGood(Command):
    id: Key
    count: Amount


class GoodProgress(Command):
    count: Count
    order: Amount
