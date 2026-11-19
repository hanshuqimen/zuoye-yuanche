"""Offline pool-detail snapshots, separate from the immutable client GameData.

Client excel does not contain modern headhunting rosters. Additional snapshots
are explicitly bound to that GameData and validated before opening a save.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Literal

from pydantic import Field

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain.clock import MAX_TIMESTAMP
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.headhunting import advanced_crystal_cost
from terralocal.server.gamedata.repository import fingerprint


class PoolRule(Command):
    rule_type: Literal["SINGLE", "DOUBLE", "CLASSIC_DOUBLE", "SPECIAL"]
    detail: dict


class HeadHuntingRules(Command):
    schema_version: Literal[1]
    gamedata_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str = Field(min_length=1, max_length=1024)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pools: dict[Identifier, PoolRule] = Field(min_length=1, max_length=1024)

    def validate_data(self, data) -> dict:
        try:
            return self._validate_data(data)
        except (KeyError, TypeError, IndexError, DomainError) as exc:
            raise ValueError(f"寻访快照字段或干员引用不完整：{exc}") from exc

    def _validate_data(self, data) -> dict:
        if self.gamedata_hash != data.manifest["hash"]:
            raise ValueError("寻访快照与 GameData 指纹不同")
        price = advanced_crystal_cost(data.constants)
        definitions = {row["gachaPoolId"]: row for row in data.table("gacha_table")["gachaPoolClient"]}
        result = {}
        for pool_id, row in self.pools.items():
            definition = definitions.get(pool_id)
            if definition is None or definition.get("gachaRuleType") != row.rule_type:
                raise ValueError(f"寻访卡池类型不匹配：{pool_id}")
            opens, closes = definition.get("openTime"), definition.get("endTime")
            if type(opens) is not int or type(closes) is not int or not 0 <= opens <= closes <= MAX_TIMESTAMP:
                raise ValueError(f"寻访卡池开放时间无效：{pool_id}")
            guarantee = definition["guarantee5Count"] if definition["guarantee5Avail"] else None
            if guarantee == 0:
                raise ValueError(f"寻访卡池已启用首轮五星保底，但保底次数为零：{pool_id}")
            detail = row.detail
            if (set(detail) != {"detailInfo", "gachaObjGroupType", "hasRateUp"}
                    or type(detail["gachaObjGroupType"]) is not int or detail["gachaObjGroupType"] != 0
                    or type(detail["hasRateUp"]) is not bool):
                raise ValueError("寻访详情响应形状不匹配")
            info = detail["detailInfo"]
            objects = info["gachaObjList"]
            groups = info.get("gachaObjGroups")
            if groups is None:
                groups = []
            if not isinstance(objects, list) or not 1 <= len(objects) <= 256 or not isinstance(groups, list):
                raise ValueError("寻访详情显示对象或分组非法")
            used, types = [], set()
            for group in groups:
                kind, start, end = group["groupType"], group["startIndex"], group["endIndex"]
                if (set(group) != {"groupType", "startIndex", "endIndex"}
                        or any(type(v) is not int for v in (kind, start, end))
                        or kind not in {0, 3, 4} or kind in types or not 0 <= start < end <= len(objects)):
                    raise ValueError("寻访详情显示分组非法")
                types.add(kind)
                used.extend(range(start, end))
            if groups and sorted(used) != list(range(len(objects))):
                raise ValueError("寻访详情显示分组有重叠或遗漏")
            if row.rule_type == "SPECIAL" and types != {3, 4}:
                raise ValueError("甄选寻访详情缺少选择前后分组")
            characters, weights = {}, {}
            for entry in info["availCharInfo"]["perAvailList"]:
                rarity, ids, percent = entry["rarityRank"], entry["charIdList"], entry["totalPercent"]
                if (type(rarity) is not int or rarity not in {2, 3, 4, 5} or rarity in characters
                        or not isinstance(ids, list) or not ids or any(not isinstance(v, str) for v in ids)
                        or len(ids) != len(set(ids))
                        or type(percent) not in {int, float} or not math.isfinite(percent)
                        or not math.isclose(percent, {2: .4, 3: .5, 4: .08, 5: .02}[rarity])):
                    raise ValueError("寻访名单或概率非法")
                for char_id in ids:
                    char = data.character(char_id)
                    if char.get("isNotObtainable") or data.rarity(char) != rarity:
                        raise ValueError("寻访引用的干员或星级非法")
                    token = char.get("classicPotentialItemId" if row.rule_type == "CLASSIC_DOUBLE"
                                     else "potentialItemId")
                    if not token or data.item(token)["itemType"] != "MATERIAL":
                        raise ValueError("寻访信物引用不匹配")
                characters[rarity], weights[rarity] = list(ids), round(percent * 10000)
            if set(characters) != {2, 3, 4, 5} or info.get("limitedChar") or info.get("weightUpCharInfoList"):
                raise ValueError("当前规则不支持此稀有度或限定权重")
            single = row.rule_type == "SINGLE"
            featured_counts = {3: 1, 4: 2, 5: 1} if single else {4: 3, 5: 2}
            up, up_rates = {}, {}
            for entry in info["upCharInfo"]["perCharList"]:
                rarity, ids = entry["rarityRank"], entry["charIdList"]
                percent = entry["percent"]
                if (type(rarity) is not int or rarity not in featured_counts or rarity in up or not isinstance(ids, list)
                        or any(not isinstance(v, str) for v in ids)
                        or len(ids) != featured_counts[rarity]
                        or type(entry["count"]) is not int or entry["count"] != len(ids)
                        or len(set(ids)) != len(ids) or not set(ids) < set(characters[rarity])
                        or type(percent) not in {int, float} or not math.isfinite(percent)
                        or not math.isclose(percent * len(ids), .2 if rarity == 3 else .5, abs_tol=1e-6)):
                    raise ValueError("寻访概率提升名单非法")
                up[rarity] = list(ids)
                up_rates[rarity] = round(percent * len(ids) * 10000)
            if row.rule_type == "SPECIAL":
                candidates = definition["dynMeta"]["rarityPickCharDict"]
                if up or set(characters[5]) != set(candidates["TIER_6"]):
                    raise ValueError("甄选六星名单不同")
                for rarity in (4, 5):
                    ids = candidates[f"TIER_{rarity + 1}"]
                    if len(ids) != 6 or len(set(ids)) != 6 or not set(ids) <= set(characters[rarity]):
                        raise ValueError("甄选候选不完整")
            elif not {4, 5} <= up.keys():
                raise ValueError("寻访缺少五星或六星概率提升名单")
            if single and (groups or definition.get("guaranteeName") != "定向选调"
                           or any(definition.get(k) is not None for k in ("dynMeta", "limitParam", "linkageParam", "linkageRuleId"))):
                raise ValueError("此单 UP 寻访的选调或附加规则尚未匹配")
            if row.rule_type == "CLASSIC_DOUBLE":
                meta = definition["dynMeta"]
                if (set(up[5]) != {meta["main6RarityCharId"], meta["sub6RarityCharId"]}
                        or set(up[4]) != set(meta["rare5CharList"])):
                    raise ValueError("中坚 UP 与客户端元数据不同")
            result[pool_id] = {"characters": characters, "weights": weights, "up": up, "price": price,
                               "rule_type": row.rule_type, "up_rates": up_rates,
                               "group": "CLASSIC" if row.rule_type == "CLASSIC_DOUBLE" else "STANDARD",
                               "start": opens, "end": closes, "first_guarantee": guarantee,
                               "definition": deepcopy(definition), "detail": deepcopy(detail),
                               "hash": fingerprint({"rule": row.model_dump(), "definition": definition})}
        return result


def read_rules(path: Path, data) -> HeadHuntingRules:
    from terralocal.server.gamedata.drops import unique_object

    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("寻访快照超过大小限制")
    rules = HeadHuntingRules.model_validate(json.loads(path.read_text("utf-8-sig"), object_pairs_hook=unique_object))
    rules.validate_data(data)
    return rules
