"""Explicit local outfit offers, bound to a client profile and frozen data.

A catalog describes its own ordinary outfit supply. It is not evidence of the
current official shop. Voucher, avatar gifts and blindbox rules are separate.
"""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain.skins import definition
from terralocal.server.gamedata.repository import fingerprint

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class OutfitOffer(Command):
    goodId: Identifier
    skinId: str = Field(min_length=1, max_length=128)
    price: int = Field(ge=0, le=2_000_000_000)
    originPrice: int = Field(ge=0, le=2_000_000_000)
    discount: float = Field(ge=0, le=1)
    slotId: int = Field(ge=0, le=2**31 - 1)
    startDateTime: int = Field(ge=-1, le=253_402_271_999)
    endDateTime: int = Field(ge=-1, le=253_402_271_999)

    @model_validator(mode="after")
    def coherent_offer(self):
        if self.originPrice < self.price:
            raise ValueError("标价不能低于实际价格")
        if self.endDateTime != -1 and self.endDateTime <= max(self.startDateTime, 0):
            raise ValueError("服装销售结束时间必须晚于开始时间")
        return self

    def available(self, now: int) -> bool:
        return (self.startDateTime == -1 or self.startDateTime <= now) and (
            self.endDateTime == -1 or now < self.endDateTime)


class SkinShopCatalog(Command):
    schema_version: Literal[1]
    gamedata_hash: Hash
    client_profile: Identifier
    catalog_id: Identifier
    mode: Literal["custom", "frozen-observation"]
    provenance: str = Field(min_length=1, max_length=2048)
    # An empty blindbox list is allowed only as an explicit closed supply.
    blindbox_supply: Literal["closed"]
    offers: list[OutfitOffer] = Field(max_length=4096)

    def validate_data(self, data, client_profile: str) -> None:
        if (self.gamedata_hash != data.manifest["hash"] or
                self.client_profile != client_profile):
            raise ValueError("服装目录与所选客户端或 GameData 指纹不同")
        if data.item("4002")["itemType"] != "DIAMOND":
            raise ValueError("服装目录的源石钱包类型不同")
        for field in ("goodId", "skinId", "slotId"):
            if len({getattr(row, field) for row in self.offers}) != len(self.offers):
                raise ValueError("服装目录包含重复商品、外观或排序标识")
        for row in self.offers:
            if not definition(data, row.skinId)["isBuySkin"]:
                raise ValueError("默认外观不能配置为服装商品")
            raw = data.table("skin_table")["charSkins"][row.skinId]
            if raw.get("spDynIllustId") or raw.get("spIllustId"):
                raise ValueError("此目录尚不支持特殊插画外观的购买规则")

    def summary(self) -> dict:
        return {"catalog_id": self.catalog_id, "mode": self.mode, "offers": len(self.offers),
                "gamedata_hash": self.gamedata_hash, "client_profile": self.client_profile,
                "blindbox_supply": self.blindbox_supply,
                "catalog_hash": fingerprint(self.model_dump())}


def read_catalog(path: Path, data, client_profile: str) -> SkinShopCatalog:
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 4_000_000:
        raise ValueError("服装目录文件类型或大小无效")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("服装目录包含重复 JSON 字段")
            result[key] = value
        return result

    catalog = SkinShopCatalog.model_validate(json.loads(path.read_text("utf-8-sig"), object_pairs_hook=unique))
    catalog.validate_data(data, client_profile)
    return catalog


def write_catalog(catalog: SkinShopCatalog, folder: Path) -> Path:
    """Keep exact old catalog bytes and immutable new snapshots before activation."""
    from terralocal.server.gamedata.drops import atomic_write
    from terralocal.server.gamedata.repository import canonical

    snapshots, active = folder / "skin-catalogs", folder / "skin_shop.json"
    if snapshots.is_symlink() or snapshots.is_junction() or active.is_symlink() or active.is_junction():
        raise ValueError("服装目录及快照不能使用目录链接")
    snapshots.mkdir(parents=True, exist_ok=True)

    def preserve(raw):
        path = snapshots / (hashlib.sha256(raw).hexdigest() + ".json")
        if path.is_symlink() or path.is_junction():
            raise ValueError("服装目录快照不能使用链接")
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError("服装目录快照内容与指纹不同")
        else:
            atomic_write(path, raw)
        return path

    if active.exists():
        if active.stat().st_size > 4_000_000:
            raise ValueError("原有服装目录超过大小限制")
        preserve(active.read_bytes())
    raw = canonical(catalog.model_dump())
    saved = preserve(raw)
    atomic_write(active, raw)
    return saved
