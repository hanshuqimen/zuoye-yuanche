"""Version-bound voucher storefronts with explicit, immutable cycle policies.

Client DTOs establish rendering and purchase fields, not the current official
supply or rollover calendar. Those inputs must accompany an imported catalog.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.gamedata.repository import canonical, fingerprint

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Epoch = Annotated[int, Field(ge=-1, le=253_402_271_999)]
Amount = Annotated[int, Field(ge=0, le=2_000_000_000)]
Period = Annotated[str, Field(min_length=1, max_length=32)]
Wallets = {"LS": ("4005", "LGG_SHD"), "HS": ("4004", "HGG_SHD"),
           "CLASSIC": ("classic_normal_ticket", "CLASSIC_SHD"), "ES": ("4006", "MATERIAL")}


def available(now: int, start: int, end: int) -> bool:
    return (start == -1 or start <= now) and (end == -1 or now < end)


class Bundle(Command):
    id: str = Field(min_length=1, max_length=128)
    count: int = Field(ge=1, le=2_000_000_000)
    type: Identifier


class QCOffer(Command):
    goodId: Identifier
    item: Bundle | None
    progressGoodId: Identifier | None = None
    originPrice: Amount
    price: Amount
    availCount: int = Field(ge=-1, le=2_000_000_000)
    discount: float = Field(ge=0, le=1, allow_inf_nan=False)
    number: int = Field(ge=0, le=2**31 - 1)
    slotId: int = Field(ge=0, le=2**31 - 1)
    groupId: Identifier | None = None
    goodStartTime: Epoch = -1
    goodEndTime: Epoch = -1
    goodType: Literal["NORMAL", "PROGRESS"] = "NORMAL"
    disableMax: bool = False

    @model_validator(mode="after")
    def coherent(self):
        if self.originPrice < self.price:
            raise ValueError("商店标价不能低于实际价格")
        if self.goodEndTime != -1 and self.goodEndTime <= max(0, self.goodStartTime):
            raise ValueError("商品结束时间必须晚于开始时间")
        if self.goodType == "NORMAL" and (self.item is None or self.progressGoodId is not None):
            raise ValueError("普通商品必须提供奖励且不能引用阶梯序列")
        if self.goodType == "PROGRESS" and (self.item is not None or self.progressGoodId is None):
            raise ValueError("阶梯商品必须引用序列，不能提供普通奖励")
        return self

    def active(self, now):
        return available(now, self.goodStartTime, self.goodEndTime)


class ProgressItem(Command):
    order: int = Field(ge=1, le=64)
    price: Amount
    displayName: str = Field(min_length=1, max_length=256)
    item: Bundle


class Cycle(Command):
    period: Period
    startTime: Epoch
    endTime: Epoch
    provenance: str = Field(min_length=1, max_length=2048)
    newFlag: list[Identifier] = Field(default_factory=list, max_length=4096)

    @model_validator(mode="after")
    def valid_window(self):
        if self.endTime != -1 and self.endTime <= max(0, self.startTime):
            raise ValueError("商店周期结束时间必须晚于开始时间")
        return self

    def active(self, now):
        return available(now, self.startTime, self.endTime)


class GroupUnlock(Command):
    groupId: Identifier
    lggThreshold: Amount


class LowCycle(Cycle):
    shop: Literal["LS"]
    shopId: Identifier
    groups: list[Identifier] = Field(min_length=1, max_length=16)
    groupsInfo: list[GroupUnlock] = Field(min_length=1, max_length=16)
    type: Literal[0, 1]
    # The loaded client accepts either representation; native readers alone
    # do not establish the official server's chosen accumulator policy.
    progressEncoding: Literal["stage-spend", "total-spend"] | None
    shopEndTime: Epoch
    goodList: list[QCOffer] = Field(min_length=1, max_length=4096)

    @field_validator("type", mode="before")
    @classmethod
    def integer_type(cls, value):
        if type(value) is not int:
            raise ValueError("Low type 必须为整数枚举")
        return value

    @model_validator(mode="after")
    def groups_valid(self):
        thresholds = {r.groupId: r.lggThreshold for r in self.groupsInfo}
        if (len(set(self.groups)) != len(self.groups) or len(thresholds) != len(self.groupsInfo)
                or set(thresholds) != set(self.groups)):
            raise ValueError("Low 分组和阈值必须唯一并完整对应")
        if self.type == 1:
            if self.progressEncoding is None or thresholds[self.groups[0]] != 0:
                raise ValueError("新版 Low 必须明确消费编码，第一组门槛为零")
            values = [thresholds[g] for g in self.groups[1:]]
            if any(value <= 0 for value in values) or (self.progressEncoding == "total-spend"
                    and values != sorted(set(values))):
                raise ValueError("新版 Low 阈值必须为正，累计编码的门槛必须严格递增")
        elif self.progressEncoding is not None:
            raise ValueError("旧版 Low 不使用消费解锁编码")
        if any(r.goodType != "NORMAL" or r.groupId not in thresholds for r in self.goodList):
            raise ValueError("Low 普通商品必须引用已定义的组")
        if not set(self.groups).issubset({r.groupId for r in self.goodList}):
            raise ValueError("Low 每个组必须有商品")
        if self.type == 0 and any(r.availCount == -1 and r.groupId != self.groups[-1] for r in self.goodList):
            raise ValueError("旧版 Low 的前置组不能含不限购商品")
        return self


class HighCycle(Cycle):
    shop: Literal["HS", "CLASSIC"]
    goodList: list[QCOffer] = Field(min_length=1, max_length=4096)
    progressGoodList: dict[Identifier, list[ProgressItem]] = Field(default_factory=dict, max_length=512)

    @model_validator(mode="after")
    def sequences_valid(self):
        refs = [r.progressGoodId for r in self.goodList if r.goodType == "PROGRESS"]
        if len(set(refs)) != len(refs) or set(refs) != set(self.progressGoodList):
            raise ValueError("阶梯目录只包含唯一且被当期商品引用的完整序列")
        for entries in self.progressGoodList.values():
            if not 1 <= len(entries) <= 64 or [r.order for r in entries] != list(range(1, len(entries) + 1)):
                raise ValueError("阶梯序列必须保留从一开始的连续原生展示顺序")
        return self


class ExtraOffer(Command):
    goodId: Identifier
    item: Bundle
    displayName: str = Field(min_length=1, max_length=256)
    slotId: int = Field(ge=0, le=2**31 - 1)
    originPrice: Amount
    price: Amount
    availCount: int = Field(ge=-1, le=2_000_000_000)
    discount: float = Field(ge=0, le=1, allow_inf_nan=False)
    goodEndTime: Epoch
    shopType: int = Field(ge=0, le=2**31 - 1)
    newFlagTimeStamp: Epoch

    @model_validator(mode="after")
    def valid_price(self):
        if self.originPrice < self.price:
            raise ValueError("商店标价不能低于实际价格")
        return self

    def active(self, now):
        return self.goodEndTime == -1 or now < self.goodEndTime


class ExtraCycle(Cycle):
    shop: Literal["ES"]
    goodList: list[ExtraOffer] = Field(min_length=1, max_length=4096)


StoreCycle = Annotated[LowCycle | HighCycle | ExtraCycle, Field(discriminator="shop")]


class VoucherShopCatalog(Command):
    schema_version: Literal[1]
    gamedata_hash: Hash
    client_profile: Identifier
    catalog_id: Identifier
    mode: Literal["custom", "frozen-observation"]
    provenance: str = Field(min_length=1, max_length=2048)
    cycles: list[StoreCycle] = Field(min_length=1, max_length=128)

    def validate_data(self, data, client_profile):
        if self.gamedata_hash != data.manifest["hash"] or self.client_profile != client_profile:
            raise ValueError("凭证商店目录与所选客户端或 GameData 指纹不同")
        if len({(r.shop, r.period) for r in self.cycles}) != len(self.cycles):
            raise ValueError("同一商店的周期标识不能重复")
        owners = {}
        for shop in Wallets:
            rows = sorted((c for c in self.cycles if c.shop == shop), key=lambda r: r.startTime)
            for left, right in zip(rows, rows[1:]):
                if left.endTime == -1 or left.endTime > max(right.startTime, 0):
                    raise ValueError("同一商店的供应周期不能重叠")
        for cycle in self.cycles:
            wallet, expected_type = Wallets[cycle.shop]
            if data.item(wallet)["itemType"] != expected_type:
                raise ValueError("凭证商店钱包类型不匹配")
            ids = [r.goodId for r in cycle.goodList]
            if len(set(ids)) != len(ids) or set(cycle.newFlag) - set(ids):
                raise ValueError("商品标识必须唯一，新商品提示必须引用当期商品")
            for offer in cycle.goodList:
                if offer.goodId in owners and owners[offer.goodId] != cycle.shop:
                    raise ValueError("不同商店不能复用同一商品标识")
                owners[offer.goodId] = cycle.shop
                if offer.item is not None:
                    self.validate_bundle(data, offer.item, offer.availCount, cycle.shop)
            for entries in getattr(cycle, "progressGoodList", {}).values():
                for entry in entries:
                    self.validate_bundle(data, entry.item, 1, cycle.shop)

    @staticmethod
    def validate_bundle(data, item, capacity, shop):
        definition = data.item(item.id)
        if item.type != definition["itemType"]:
            raise ValueError("商店奖励的类型与 GameData 不同")
        if item.type == "CHAR":
            character = data.character(item.id)
            if character.get("isNotObtainable") or item.count != 1 or not 0 <= capacity <= 6:
                raise ValueError("干员商品必须可获取、单包一个且限购不超过六次")
            token = character.get("classicPotentialItemId" if shop == "CLASSIC" else "potentialItemId")
            if not token or data.item(token)["itemType"] != "MATERIAL":
                raise ValueError("干员商品的获得来源和信物不匹配")
            if shop == "CLASSIC" and character.get("rarity") not in {"TIER_3", "TIER_4", "TIER_5", "TIER_6"}:
                raise ValueError("通用凭证干员商品的星级不匹配")
            if shop != "CLASSIC" and (data.item("4004")["itemType"] != "HGG_SHD"
                                     or data.item("4005")["itemType"] != "LGG_SHD"):
                raise ValueError("干员商品的标准获得凭证不匹配")
        if item.type == "CHAR_SKIN":
            from terralocal.server.domain.skins import definition as skin_definition

            if not skin_definition(data, item.id)["isBuySkin"] or item.count != 1 or capacity != 1:
                raise ValueError("服装奖励必须为已定义的单次商品外观")

    def active_cycle(self, shop, now):
        return next((c for c in self.cycles if c.shop == shop and c.active(now)), None)

    def cycle_hash(self, cycle):
        return fingerprint({"gamedata_hash": self.gamedata_hash, "client_profile": self.client_profile,
                            "cycle": cycle.model_dump()})

    def summary(self):
        return {"catalog_id": self.catalog_id, "mode": self.mode, "gamedata_hash": self.gamedata_hash,
                "client_profile": self.client_profile, "catalog_hash": fingerprint(self.model_dump()),
                "cycles": [{"shop": c.shop, "period": c.period, "offers": len(c.goodList),
                            "startTime": c.startTime, "endTime": c.endTime} for c in self.cycles]}


def read_catalog(path, data, client_profile):
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 8_000_000:
        raise ValueError("凭证商店目录文件类型或大小无效")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("凭证商店目录包含重复 JSON 字段")
            result[key] = value
        return result

    catalog = VoucherShopCatalog.model_validate(json.loads(path.read_text("utf-8-sig"), object_pairs_hook=unique))
    catalog.validate_data(data, client_profile)
    return catalog


def preflight_saved_catalog(catalog, path):
    """Reject a redefined admitted cycle before migrations touch the active save."""
    if catalog is None or not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        definitions = ({(r[0], r[1]): r[2] for r in con.execute(
            "SELECT shop_id, period, definition_hash FROM shop_catalog_cycles")}
            if "shop_catalog_cycles" in tables else {})
        if "shop_states" in tables:
            covered = {c.shop for c in catalog.cycles}
            old_periods = {(r[0], r[1]) for r in con.execute(
                "SELECT DISTINCT shop_id, period FROM shop_states WHERE bought > 0") if r[0] in covered}
            if old_periods - definitions.keys():
                raise ValueError("已有凭证商品购买记录缺少已接纳的周期目录，不能推算重置或解锁")
    for cycle in catalog.cycles:
        old = definitions.get((cycle.shop, cycle.period))
        if old is not None and old != catalog.cycle_hash(cycle):
            raise ValueError("已接纳的商店周期不能改写，请保留原目录并使用新周期标识")


def admit_catalog(catalog, database):
    if catalog is None:
        return
    from terralocal.server.persistence.models import ShopCatalogCycle

    with database.transaction() as session:
        for cycle in catalog.cycles:
            key, digest = (cycle.shop, cycle.period), catalog.cycle_hash(cycle)
            existing = session.get(ShopCatalogCycle, key)
            if existing and existing.definition_hash != digest:
                raise ValueError("已接纳的商店周期定义冲突")
            if existing is None:
                session.add(ShopCatalogCycle(shop_id=cycle.shop, period=cycle.period, definition_hash=digest))


def write_catalog(catalog, folder):
    from terralocal.server.gamedata.drops import atomic_write

    snapshots, active = folder / "voucher-catalogs", folder / "voucher_shop.json"
    if any(p.is_symlink() or p.is_junction() for p in (snapshots, active)):
        raise ValueError("商店目录和快照不能使用链接")
    preflight_saved_catalog(catalog, folder / "terralocal.sqlite3")
    snapshots.mkdir(parents=True, exist_ok=True)

    def preserve(raw):
        path = snapshots / (hashlib.sha256(raw).hexdigest() + ".json")
        if path.is_symlink() or path.is_junction() or (path.exists() and path.read_bytes() != raw):
            raise ValueError("商店目录快照内容或路径非法")
        if not path.exists():
            atomic_write(path, raw)
        return path

    if active.exists():
        if active.stat().st_size > 8_000_000:
            raise ValueError("原有商店目录超过大小限制")
        preserve(active.read_bytes())
    raw = canonical(catalog.model_dump())
    saved = preserve(raw)
    atomic_write(active, raw)
    return saved
