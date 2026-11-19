"""Recruit catalog resolved from the selected client data, not the full roster."""

import re
from collections import defaultdict

from terralocal.server.domain.errors import DomainError

PROFESSION_TAG = {"WARRIOR": 1, "SNIPER": 2, "TANK": 3, "MEDIC": 4,
                  "SUPPORT": 5, "CASTER": 6, "SPECIAL": 7, "PIONEER": 8}


class RecruitCatalog:
    def __init__(self, data):
        self.data = data
        table = data.table("gacha_table")
        try:
            definitions = table["gachaTags"]
            if (not isinstance(definitions, list) or any(not isinstance(row, dict)
                    or type(row.get("tagId")) is not int or row["tagId"] <= 0
                    or not isinstance(row.get("tagName"), str) or not row["tagName"] for row in definitions)
                    or len({row["tagId"] for row in definitions}) != len(definitions)):
                raise ValueError("Invalid recruit tags")
            self.tags = {row["tagId"]: row["tagName"] for row in table["gachaTags"] if row["tagId"] < 1000}
            constants = table["recruitPool"]["recruitConstants"]
            self.maximum_minutes = constants["maxRecruitTime"]
            self.tag_prices = {int(key): value for key, value in constants["tagPriceList"].items()}
            self.prices = {row["timeLength"]: row["recruitPrice"]
                           for row in table["recruitPool"]["recruitTimeTable"]}
            self.rarity_ranges = {int(key): (value["rarityStart"], value["rarityEnd"])
                                  for key, value in table["recruitRarityTable"].items()}
            self.special_rarities = {int(key): value for key, value in table["specialTagRarityTable"].items()}
            self.initial_tags = data.constants["initRecruitTagList"]
            if (len(self.tags) < 5 or not isinstance(self.initial_tags, list)
                    or any(type(tag) is not int for tag in self.initial_tags)
                    or len(self.initial_tags) != 5 or len(set(self.initial_tags)) != 5
                    or any(tag not in self.tags for tag in self.initial_tags)
                    or type(self.maximum_minutes) is not int or self.maximum_minutes < 10
                    or set(self.prices) != set(self.rarity_ranges)
                    or self.maximum_minutes not in self.prices
                    or any(type(v) is not int or v < 0 for v in [*self.prices.values(), *self.tag_prices.values()])
                    or any(k <= 0 or k > self.maximum_minutes or k % 10 for k in self.prices)
                    or set(self.tag_prices) != {0, 1, 2, 3}
                    or any(type(low) is not int or type(high) is not int or not 0 <= low <= high <= 5
                           for low, high in self.rarity_ranges.values())
                    or any(tag not in self.tags or not isinstance(levels, list) or not levels
                           or any(type(level) is not int or level not in range(6) for level in levels)
                           or len(set(levels)) != len(levels) for tag, levels in self.special_rarities.items())):
                raise ValueError("Invalid recruit configuration")
            by_name = defaultdict(list)
            for char_id, char in data.characters.items():
                if char_id.startswith("char_") and not char.get("isNotObtainable"):
                    by_name[(char["name"], data.rarity(char))].append(char_id)
            # The client publishes its current pool as six rarity sections. All
            # entries must resolve uniquely; do not silently admit other banners.
            sections = re.split(r"(★{1,6})\\n", table["recruitDetail"])
            if len(sections) != 13:
                raise ValueError("Missing recruit rarity sections")
            self.characters = {}
            for stars, block in zip(sections[1::2], sections[2::2], strict=True):
                names = re.sub(r"<[^>]*>", "", block.split("-----", 1)[0])
                for name in names.split(" / "):
                    matches = by_name.get((name.strip(), len(stars) - 1), [])
                    if len(matches) != 1 or matches[0] in self.characters:
                        raise ValueError("Ambiguous or missing recruit character")
                    char_id = matches[0]
                    char = data.character(char_id)
                    char_tags = {tag for tag, label in self.tags.items() if label in char.get("tagList", [])}
                    char_tags.add(PROFESSION_TAG[char["profession"]])
                    char_tags.add({"MELEE": 9, "RANGED": 10}[char["position"]])
                    rarity = data.rarity(char)
                    char_tags.update(tag for tag, levels in self.special_rarities.items() if rarity in levels)
                    self.characters[char_id] = (rarity, char_tags)
            for item in ("7001", "7002"):
                data.item(item)
        except (KeyError, TypeError, ValueError) as exc:
            raise DomainError("INVALID_RECRUIT_DATA", "公开招募数据或干员引用不完整", 503) from exc

    def candidates(self, tags: list[int], rarities: set[int]) -> list[str]:
        selected = set(tags)
        return sorted(char_id for char_id, (rarity, char_tags) in self.characters.items()
                      if rarity in rarities and selected <= char_tags)

    def cost(self, duration: int, tags: list[int]) -> int:
        if duration % 60 or duration // 60 not in self.prices:
            raise DomainError("INVALID_RECRUIT_TIME", "招募时间必须采用当前数据定义的十分钟档位")
        return self.prices[duration // 60] + self.tag_prices[len(tags)]
