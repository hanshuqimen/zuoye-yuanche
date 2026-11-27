"""Explicit native shop supply, separate from map data and player saves.

The wire contract is recovered from the frozen client. Initial stock, prices,
dates and the finite progress policy must be supplied with provenance. A later
snapshot cannot silently become a historical season's catalog.
"""

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain import crisis_v2
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.protocol.crisis_v2_shop import PermanentGood, ProgressGood, SeasonGood
from terralocal.server.protocol.crisis_v2_state import Key, Timestamp

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SeasonSupply(Command):
    start_ts: Timestamp
    end_ts: Timestamp
    goods: list[SeasonGood] = Field(max_length=4096)


class Catalog(Command):
    schema_version: Literal[1]
    gamedata_hash: Hash
    client_profile: Key
    catalog_id: Key
    mode: Literal["custom", "frozen-observation", "reconstruction"]
    provenance: str = Field(min_length=1, max_length=4096)
    valid_from: Timestamp
    # This is a local, finite purchase policy, not a recovered backend rule.
    progress_policy: Literal["finite-tiers-v1"]
    permanent: list[PermanentGood] = Field(max_length=4096)
    seasons: dict[Key, SeasonSupply] = Field(max_length=256)
    progress: dict[Key, list[ProgressGood]] = Field(max_length=4096)

    def goods(self):
        return [(1, row) for row in self.permanent] + [
            (0, row) for supply in self.seasons.values() for row in supply.goods
        ]

    def validate_data(self, data, client_profile):
        if (
            not crisis_v2.available(data)
            or self.gamedata_hash != data.manifest["hash"]
            or self.client_profile != client_profile
        ):
            raise ValueError("原版危机合约商店缺少匹配的客户端和数据指纹")
        all_goods = self.goods()
        ids = [good.goodId for _, good in all_goods]
        if len(ids) != len(set(ids)):
            raise ValueError("原版危机合约商品标识不能跨目录重复")
        if len({(row.slotId1, row.slotId2) for row in self.permanent}) != len(self.permanent):
            raise ValueError("原版危机合约永久商品排序重复")
        for season, supply in self.seasons.items():
            source = data.crisis_v2.seasons.get(season)
            if (
                source is None
                or (supply.start_ts, supply.end_ts) != (source.start, source.end)
                or len({row.slotId for row in supply.goods}) != len(supply.goods)
            ):
                raise ValueError("原版危机合约赛季商品窗口或排序不匹配")
        used = []
        unique = data.table("item_table").get("uniqueInfo", {})
        if type(unique) is not dict:
            raise ValueError("唯一物品上限表无效")
        for _, row in all_goods:
            if isinstance(row, PermanentGood) and row.seasonId not in data.crisis_v2.seasons:
                raise ValueError("永久商品引用未知赛季")
            if row.progressGoodId:
                if row.item is not None or row.price != 0 or row.availCount != 0:
                    raise ValueError("分档基础商品必须使用空物品、零价格和零基础库存")
                used.append(row.progressGoodId)
            else:
                if row.item is None or row.price <= 0:
                    raise ValueError("普通商品缺少物品或有效价格")
                self._item(data, row.item)
                if row.item.type == "CHAR":
                    raise ValueError("干员获取目前只接入每次一份的分档商品")
                cap = unique.get(row.item.id)
                if cap is not None and (type(cap) is not int or cap < 1 or row.availCount == -1):
                    raise ValueError("唯一商品上限或无限库存配置不兼容")
        if len(set(used)) != len(used) or set(used) != set(self.progress):
            raise ValueError("分档目录存在未使用、重复或缺失的引用")
        for tiers in self.progress.values():
            if (
                not tiers
                or len(tiers) > 256
                or [tier.order for tier in tiers] != list(range(1, len(tiers) + 1))
            ):
                raise ValueError("分档商品必须从第一档连续排列")
            for tier in tiers:
                self._item(data, tier.item)

    @staticmethod
    def _item(data, item):
        try:
            definition = data.item(item.id)
            if definition["itemType"] != item.type:
                raise ValueError("原版危机合约商品类型不匹配")
            cap = data.table("item_table").get("uniqueInfo", {}).get(item.id)
            if cap is not None and (type(cap) is not int or cap < 1):
                raise ValueError("分档或普通商品的唯一上限无效")
            if item.type == "CHAR":
                if item.count != 1 or data.character(item.id).get("isNotObtainable"):
                    raise ValueError("干员商品必须为一个可获取干员")
                if cap is not None:
                    raise ValueError("干员商品的唯一持有上限尚未接入")
                for ident, kind in (("4004", "HGG_SHD"), ("4005", "LGG_SHD")):
                    if data.item(ident)["itemType"] != kind:
                        raise ValueError("干员商品缺少匹配的获得凭证定义")
                token = data.character(item.id).get("potentialItemId")
                if not token or data.item(token)["itemType"] != "MATERIAL":
                    raise ValueError("干员商品缺少匹配的潜能信物")
            if item.type == "CHAR_SKIN":
                from terralocal.server.domain.skins import definition as skin_definition

                if item.count != 1 or cap != 1 or not skin_definition(data, item.id)["isBuySkin"]:
                    raise ValueError("服装商品必须为一个可获取外观")
        except (DomainError, KeyError) as exc:
            raise ValueError("原版危机合约商品引用未匹配物品表") from exc

    @property
    def fingerprint(self):
        return fingerprint(self.model_dump())

    def supply(self, data, now):
        if now < self.valid_from or now < data.crisis_v2.system_start:
            raise DomainError("CRISIS_V2_NATIVE_SHOP_CLOSED", "商店目录尚未到达已记录的适用时间", 409)
        season = data.crisis_v2.current(now)
        if season and season not in self.seasons:
            raise DomainError("CRISIS_V2_NATIVE_SHOP_MISSING", "当前赛季尚未提供匹配的商品目录", 503)
        return season, self.seasons[season].goods if season else []


def read_catalog(path: Path, data, client_profile):
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 4_000_000:
        raise ValueError("原版危机合约商店目录文件类型或大小无效")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("原版危机合约商店目录含重复 JSON 字段")
            value[key] = item
        return value

    catalog = Catalog.model_validate(json.loads(path.read_text("utf-8-sig"), object_pairs_hook=unique))
    catalog.validate_data(data, client_profile)
    return catalog
