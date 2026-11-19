"""Explicit originite supply and local-only purchase quotes for CN Android.

CashShopObject amounts are totals, not multipliers. The frozen SDK product
document establishes store IDs and minor-unit prices; it does not establish
the active GS supply or first-purchase reward totals.
"""
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.voucher_shop import Amount, Epoch, Hash, available


class CashOffer(Command):
    goodId: Identifier
    storeId: int = Field(ge=1, le=2**31 - 1)
    productName: str = Field(min_length=1, max_length=256)
    slotId: int = Field(ge=0, le=2**31 - 1)
    price: int = Field(ge=1, le=20_000_000)
    diamondNum: int = Field(ge=1, le=2_000_000_000)
    doubleCount: int = Field(ge=1, le=2_000_000_000)
    plusNum: Amount
    desc: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def reward_totals(self):
        if self.doubleCount < self.diamondNum or self.diamondNum + self.plusNum > 2_000_000_000:
            raise ValueError("源石首购或普通奖励数量无效")
        return self

    def native(self):
        return self.model_dump(exclude={"storeId", "productName"})


class CashShopCatalog(Command):
    schema_version: Literal[1]
    gamedata_hash: Hash
    client_profile: Identifier
    sdk_products_sha256: Hash
    catalog_id: Identifier
    mode: Literal["custom", "frozen-observation"]
    provenance: str = Field(min_length=1, max_length=2048)
    purchase_mode: Literal["local-simulated"]
    first_purchase_scope: Literal["good-id"]
    startTime: Epoch
    endTime: Epoch
    offers: list[CashOffer] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def window(self):
        if self.endTime != -1 and self.endTime <= max(0, self.startTime):
            raise ValueError("源石供给的结束时间必须晚于开始时间")
        for key in ("goodId", "storeId", "slotId"):
            if len({getattr(o, key) for o in self.offers}) != len(self.offers):
                raise ValueError("源石商品、SDK商品和排序标识必须唯一")
        return self

    def active(self, now):
        return available(now, self.startTime, self.endTime)

    def validate_data(self, data, client_profile, products, sdk_hash):
        if (self.gamedata_hash != data.manifest["hash"] or self.client_profile != client_profile
                or self.sdk_products_sha256 != sdk_hash):
            raise ValueError("源石目录与客户端、GameData 或 SDK 商品指纹不匹配")
        if data.item("4002")["itemType"] != "DIAMOND":
            raise ValueError("源石奖励钱包类型不匹配")
        rows = products.get("productList")
        if not isinstance(rows, list):
            raise ValueError("SDK 商品目录结构不匹配")
        for offer in self.offers:
            candidates = [r for r in rows if isinstance(r, dict) and r.get("product_id") == offer.goodId]
            if len(candidates) != 1:
                raise ValueError("源石商品必须唯一对应冻结 SDK 商品")
            raw = candidates[0]
            # This profile is CN official Android. Catalog price is the native
            # displayed yuan integer; U8's frozen product price is in fen.
            expected = {"store_id": offer.storeId, "price": offer.price * 100, "status": 1,
                        "platform": 1, "app_id": 1, "channel_id": 1}
            if any(type(raw.get(k)) is not int or raw[k] != v for k, v in expected.items()):
                raise ValueError("源石商品的渠道、SDK标识或价格单位不匹配")
            if type(raw.get("world_id")) is not int or raw["world_id"] not in (0, 1):
                raise ValueError("源石商品必须属于全局或当前 SDK 世界目录")
            if raw.get("name") != offer.productName:
                raise ValueError("源石商品名称与冻结 SDK 商品不匹配")

    def summary(self):
        return {"catalog_id": self.catalog_id, "mode": self.mode, "offers": len(self.offers),
                "gamedata_hash": self.gamedata_hash, "client_profile": self.client_profile,
                "sdk_products_sha256": self.sdk_products_sha256,
                "purchase_mode": self.purchase_mode, "first_purchase_scope": self.first_purchase_scope,
                "catalog_hash": fingerprint(self.model_dump()), "startTime": self.startTime,
                "endTime": self.endTime}


def frozen_products(settings):
    from terralocal.server.protocol.bootstrap import Bootstrap

    bootstrap = Bootstrap(settings)
    products = bootstrap.document("sdk_products")
    digest = hashlib.sha256((bootstrap.root / "sdk_products.json").read_bytes()).hexdigest()
    return products, digest


def read_catalog(path: Path, data, client_profile, products, sdk_hash):
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 1_000_000:
        raise ValueError("源石目录文件类型或大小无效")

    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("源石目录包含重复 JSON 字段")
            result[k] = v
        return result

    catalog = CashShopCatalog.model_validate(json.loads(path.read_text("utf-8-sig"), object_pairs_hook=unique))
    catalog.validate_data(data, client_profile, products, sdk_hash)
    return catalog


def write_catalog(catalog: CashShopCatalog, folder: Path):
    from terralocal.server.gamedata.drops import atomic_write

    snapshots, active = folder / "cash-catalogs", folder / "cash_shop.json"
    if any(p.is_symlink() or p.is_junction() for p in (snapshots, active)):
        raise ValueError("源石目录及快照不能使用链接")
    snapshots.mkdir(parents=True, exist_ok=True)

    def preserve(raw):
        target = snapshots / (hashlib.sha256(raw).hexdigest() + ".json")
        if target.is_symlink() or target.is_junction():
            raise ValueError("源石目录快照不能使用链接")
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError("源石目录快照与指纹不匹配")
        else:
            atomic_write(target, raw)
        return target

    if active.exists():
        if active.stat().st_size > 1_000_000:
            raise ValueError("原有源石目录超过大小限制")
        preserve(active.read_bytes())
    raw = canonical(catalog.model_dump())
    saved = preserve(raw)
    atomic_write(active, raw)
    return saved
