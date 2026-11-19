"""Version-bound GP supply. DTO declarations do not establish live supply.

Normal, level and periodic packages share one purchase contract. Monthly
subscriptions and selectable/conditional packages require additional rules;
they are not admitted as ordinary packages by this catalog revision.
"""
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.voucher_shop import Amount, Bundle, Epoch, Hash, Period, available


class SpecialItemInfo(Command):
    showPreview: bool
    specialDesc: str = Field(max_length=2048)
    specialBtnText: str = Field(max_length=256)


class PackageImage(Command):
    picId: Identifier
    index: int = Field(ge=0, le=2**31 - 1)


class GiftPackOffer(Command):
    section: Literal["oneTime", "level", "weekly", "monthly"]
    goodId: Identifier
    giftPackageId: Identifier
    priority: int = Field(ge=0, le=2**31 - 1)
    displayName: str = Field(min_length=1, max_length=256)
    currencyUnit: Literal["CASH", "DIAMOND"]
    availCount: int = Field(ge=-1, le=2_000_000_000)
    price: Amount
    originPrice: Amount
    discount: float = Field(ge=0, le=1, allow_inf_nan=False)
    items: list[Bundle] = Field(min_length=1, max_length=256)
    specialItemInfos: dict[Identifier, SpecialItemInfo] = Field(default_factory=dict, max_length=256)
    startDateTime: Epoch
    endDateTime: Epoch
    tab: list[Identifier] = Field(min_length=1, max_length=32)
    # Ticket coupons use another native request. They cannot be silently
    # converted into a normal purchase or an arbitrary inventory item.
    gpTicketIdList: list[Identifier] = Field(default_factory=list, max_length=0)
    imgDisplayDataList: list[PackageImage] = Field(default_factory=list, max_length=32)
    playerLevel: int | None = Field(default=None, ge=1, le=2**31 - 1)
    storeId: int | None = Field(default=None, ge=1, le=2**31 - 1)
    productName: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def coherent(self):
        if self.originPrice < self.price:
            raise ValueError("组合包标价不能低于实际价格")
        if self.endDateTime != -1 and self.endDateTime <= max(0, self.startDateTime):
            raise ValueError("组合包结束时间必须晚于开始时间")
        if (self.section == "level") != (self.playerLevel is not None):
            raise ValueError("等级组合包必须明确解锁等级，其他套餐不能带等级条件")
        if self.currencyUnit == "CASH":
            if self.storeId is None or self.productName is None or self.price < 1:
                raise ValueError("现金组合包必须明确冻结 SDK 商品与价格")
        elif self.storeId is not None or self.productName is not None:
            raise ValueError("非现金组合包不能引用 SDK 商品")
        if len(set(self.tab)) != len(self.tab):
            raise ValueError("组合包标签不能重复")
        if set(self.specialItemInfos) - {i.id for i in self.items}:
            raise ValueError("组合包特殊说明引用不存在的奖励")
        return self

    def active(self, now):
        return available(now, self.startDateTime, self.endDateTime)

    def native(self, bought, group_id=None):
        result = self.model_dump(exclude={"section", "storeId", "productName", "playerLevel"})
        result["buyCount"] = bought
        if self.playerLevel is not None:
            result["playerLevel"] = self.playerLevel
        if group_id is not None:
            result["groupId"] = group_id
        return result


class GiftPackCycle(Command):
    section: Literal["weekly", "monthly"]
    period: Period
    groupId: Identifier
    startDateTime: int = Field(ge=0, le=253_402_271_999)
    endDateTime: int = Field(ge=1, le=253_402_271_999)
    offers: list[GiftPackOffer] = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def coherent(self):
        if self.endDateTime <= self.startDateTime or self.period == "permanent":
            raise ValueError("周期组合包必须使用有界时间和独立周期标识")
        if any(o.section != self.section for o in self.offers):
            raise ValueError("周期组合包分类与周期不匹配")
        if len({o.goodId for o in self.offers}) != len(self.offers):
            raise ValueError("周期组合包商品标识重复")
        return self

    def active(self, now):
        return available(now, self.startDateTime, self.endDateTime)


class GiftPackCatalog(Command):
    schema_version: Literal[1]
    gamedata_hash: Hash
    client_profile: Identifier
    sdk_products_sha256: Hash
    catalog_id: Identifier
    mode: Literal["custom", "frozen-observation"]
    provenance: str = Field(min_length=1, max_length=2048)
    purchase_mode: Literal["local-simulated"]
    offers: list[GiftPackOffer] = Field(default_factory=list, max_length=4096)
    cycles: list[GiftPackCycle] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def coherent(self):
        if not self.offers and not self.cycles:
            raise ValueError("组合包目录必须包含实际供给")
        if any(o.section not in {"oneTime", "level"} for o in self.offers):
            raise ValueError("周/月组合包必须放入版本化周期")
        ids = [o.goodId for o in self.offers]
        if len(ids) != len(set(ids)):
            raise ValueError("长期组合包商品标识重复")
        keys = [(c.section, c.period) for c in self.cycles]
        if len(keys) != len(set(keys)):
            raise ValueError("组合包周期标识重复")
        for section in ("weekly", "monthly"):
            rows = sorted((c for c in self.cycles if c.section == section), key=lambda c: c.startDateTime)
            if any(a.endDateTime > b.startDateTime for a, b in zip(rows, rows[1:])):
                raise ValueError("同类组合包销售周期不能重叠")
        owners = {}
        store_owners = {}
        for offer in self.all_offers():
            previous = owners.setdefault(offer.goodId, offer.section)
            if previous != offer.section:
                raise ValueError("同一组合包商品不能跨分类")
            if offer.storeId is not None and store_owners.setdefault(offer.storeId, offer.goodId) != offer.goodId:
                raise ValueError("SDK 商品标识不能绑定多个组合包")
        return self

    def all_offers(self):
        return [*self.offers, *(o for c in self.cycles for o in c.offers)]

    def active_entries(self, now):
        return [(o, "permanent", None) for o in self.offers if o.active(now)] + [
            (o, c.period, c) for c in self.cycles if c.active(now) for o in c.offers if o.active(now)]

    def validate_data(self, data, client_profile, products, sdk_hash):
        if (self.gamedata_hash != data.manifest["hash"] or self.client_profile != client_profile
                or self.sdk_products_sha256 != sdk_hash):
            raise ValueError("组合包目录与客户端、GameData 或 SDK 指纹不匹配")
        from terralocal.server.gamedata.voucher_shop import VoucherShopCatalog

        rows = products.get("productList")
        if not isinstance(rows, list):
            raise ValueError("SDK 商品目录结构不匹配")
        for offer in self.all_offers():
            if "shop_client_table" in data.manifest["tables"]:
                display = data.table("shop_client_table")
                row = display.get("shopGPDataDict", {}).get(offer.goodId)
                if (not isinstance(row, dict) or row.get("giftPackageId") != offer.giftPackageId
                        or row.get("displayName") != offer.displayName or row.get("condTrigPackageType") != "NONE"
                        or any(tab not in display.get("tabDisplayData", {}) for tab in offer.tab)):
                    raise ValueError("组合包标识、名称、分类或标签与冻结客户端展示表不匹配")
                if display.get("shopUnlockDict", {}).get(offer.goodId) != "ALWAYS_UNLOCK":
                    raise ValueError("此组合包需要额外功能解锁合同，不能当作普通无条件套餐导入")
            for item in offer.items:
                VoucherShopCatalog.validate_bundle(data, item, offer.availCount, "GP")
                definition = data.item(item.id)
                table = data.table("item_table")
                if (definition.get("hasTs") or table.get("apSupplies", {}).get(item.id, {}).get("hasTs")
                        or item.id in table.get("apSupplyOutOfDateDict", {})):
                    raise ValueError("限时奖励需要独立实例与到期政策，不能作为永久物品入账")
            if offer.playerLevel is not None and offer.playerLevel > data.constants["maxPlayerLevel"]:
                raise ValueError("组合包解锁等级超出 GameData 范围")
            if offer.currencyUnit != "CASH":
                item_id, kind = "4002", "DIAMOND"
                if data.item(item_id)["itemType"] != kind:
                    raise ValueError("组合包价格钱包与 GameData 不匹配")
                continue
            candidates = [r for r in rows if isinstance(r, dict) and r.get("product_id") == offer.goodId]
            expected = {"store_id": offer.storeId, "price": offer.price * 100, "status": 1,
                        "platform": 1, "app_id": 1, "channel_id": 1}
            if len(candidates) != 1 or any(type(candidates[0].get(k)) is not int or candidates[0][k] != v
                                            for k, v in expected.items()):
                raise ValueError("现金组合包与冻结 SDK 标识、渠道或价格单位不匹配")
            raw = candidates[0]
            if (type(raw.get("world_id")) is not int or raw["world_id"] not in (0, 1)
                    or raw.get("name") != offer.productName):
                raise ValueError("现金组合包名称或 SDK 世界目录不匹配")

    def summary(self):
        return {"catalog_id": self.catalog_id, "mode": self.mode, "offers": len(self.all_offers()),
                "cycles": len(self.cycles), "gamedata_hash": self.gamedata_hash,
                "client_profile": self.client_profile, "sdk_products_sha256": self.sdk_products_sha256,
                "catalog_hash": fingerprint(self.model_dump()), "purchase_mode": self.purchase_mode,
                "sections": sorted({o.section for o in self.all_offers()}),
                "pending_sections": ["monthlySub", "chooseGroup", "condtionTriggerGroup", "conditionChooseGroup"],
                "pending_currency_paths": ["TICKET", "DIAMOND_SHD", "gpTicketIdList"],
                "pending_unlock_paths": ["FURN_UNLOCK"]}


def read_catalog(path: Path, data, client_profile, products, sdk_hash):
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 8_000_000:
        raise ValueError("组合包目录文件类型或大小无效")

    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("组合包目录包含重复 JSON 字段")
            result[k] = v
        return result

    catalog = GiftPackCatalog.model_validate(json.loads(path.read_text("utf-8-sig"), object_pairs_hook=unique))
    catalog.validate_data(data, client_profile, products, sdk_hash)
    return catalog


def write_catalog(catalog, folder):
    from terralocal.server.gamedata.drops import atomic_write

    snapshots, active = folder / "gift-pack-catalogs", folder / "gift_packs.json"
    if any(p.is_symlink() or p.is_junction() for p in (snapshots, active)):
        raise ValueError("组合包目录及快照不能使用链接")
    preflight_saved_catalog(catalog, folder / "terralocal.sqlite3")
    snapshots.mkdir(parents=True, exist_ok=True)

    def preserve(raw):
        path = snapshots / (hashlib.sha256(raw).hexdigest() + ".json")
        if path.is_symlink() or path.is_junction() or (path.exists() and path.read_bytes() != raw):
            raise ValueError("组合包快照内容或路径非法")
        if not path.exists():
            atomic_write(path, raw)
        return path

    if active.exists():
        if active.stat().st_size > 8_000_000:
            raise ValueError("原有组合包目录超过大小限制")
        preserve(active.read_bytes())
    saved = preserve(raw := canonical(catalog.model_dump()))
    atomic_write(active, raw)
    return saved


def cycle_hash(catalog, cycle):
    return fingerprint({"gamedata_hash": catalog.gamedata_hash, "client_profile": catalog.client_profile,
                        "cycle": cycle.model_dump()})


def preflight_saved_catalog(catalog, path):
    """Keep admitted periodic identities immutable before touching a save."""
    if catalog is None or not path.exists():
        return
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        definitions = (dict(((s, p), h) for s, p, h in con.execute(
            "SELECT shop_id, period, definition_hash FROM shop_catalog_cycles"))
            if "shop_catalog_cycles" in tables else {})
        if "shop_states" in tables:
            legacy = {(s, p) for s, p in con.execute(
                "SELECT DISTINCT shop_id, period FROM shop_states WHERE bought > 0")
                if s in {"GP:weekly", "GP:monthly"}}
            if legacy - definitions.keys():
                raise ValueError("已有周期组合包记录缺少已接纳的周期定义，不能推算重置")
    for cycle in catalog.cycles:
        old = definitions.get(("GP:" + cycle.section, cycle.period))
        if old is not None and old != cycle_hash(catalog, cycle):
            raise ValueError("已接纳的组合包周期不能改写，请使用新的周期标识")


def admit_catalog(catalog, database):
    if catalog is None:
        return
    from terralocal.server.persistence.models import ShopCatalogCycle

    with database.transaction() as session:
        for cycle in catalog.cycles:
            key, digest = ("GP:" + cycle.section, cycle.period), cycle_hash(catalog, cycle)
            row = session.get(ShopCatalogCycle, key)
            if row and row.definition_hash != digest:
                raise ValueError("已接纳的组合包周期定义冲突")
            if row is None:
                session.add(ShopCatalogCycle(shop_id=key[0], period=key[1], definition_hash=digest))
