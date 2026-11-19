"""Newcomer pools and client guarantee counters from the frozen gacha table."""

import re
from decimal import Decimal

from terralocal.server.domain.errors import DomainError


def advanced_crystal_cost(constants: dict) -> int:
    price = constants.get("advancedGachaCrystalCost")
    if type(price) is not int or not 1 <= price <= 2_000_000_000:
        raise ValueError("寻访合成玉单价必须是余额范围内的正整数")
    return price


class HeadHuntingCatalog:
    def __init__(self, data, rules=None):
        if "advancedGachaCrystalCost" in data.constants:
            advanced_crystal_cost(data.constants)
        try:
            table = data.table("gacha_table")
            names = {}
            for char_id, char in data.characters.items():
                if char_id.startswith("char_") and not char.get("isNotObtainable"):
                    names.setdefault((char.get("name"), data.rarity(char)), []).append(char_id)
            self.newcomer = {}
            indexes = set()
            for row in table.get("newbeeGachaPoolClient", []):
                pool_id, index = row["gachaPoolId"], row["gachaIndex"]
                if (not isinstance(pool_id, str) or not re.fullmatch(r"BOOT_[A-Za-z0-9_]{1,80}", pool_id)
                        or pool_id in self.newcomer or type(index) is not int or index < 0 or index in indexes
                        or any(type(row[key]) is not int or not 1 <= row[key] <= 10000
                               for key in ("gachaTimes", "gachaPrice"))):
                    raise ValueError("Invalid newcomer pool identity or limits")
                indexes.add(index)
                text = re.sub(r"<[^>]+>", "", row["gachaPoolDetail"]).replace("\\n", "\n")
                sections = re.split(r"(★{3,6})\(([0-9.]+)%\)\n", text)
                if len(sections) != 13:
                    raise ValueError("Newcomer pool must list four rarity groups")
                characters, weights = {}, {}
                for pos in range(1, len(sections), 3):
                    rarity = len(sections[pos]) - 1
                    weight = Decimal(sections[pos + 1]) * 100
                    if rarity in characters or weight != int(weight) or not 0 < weight <= 10000:
                        raise ValueError("Invalid newcomer rarity probability")
                    weights[rarity] = int(weight)
                    block = sections[pos + 2].split("---", 1)[0].split("\n\n", 1)[0].strip()
                    ids = []
                    for name in block.split(" / "):
                        matched = names.get((name.strip(), rarity), [])
                        if len(matched) != 1 or matched[0] in ids:
                            raise ValueError("Newcomer character reference is missing or ambiguous")
                        ids.append(matched[0])
                    characters[rarity] = sorted(ids)
                if set(characters) != {2, 3, 4, 5} or sum(weights.values()) != 10000:
                    raise ValueError("Newcomer rarity groups or probabilities do not add up")
                self.newcomer[pool_id] = {"index": index, "limit": row["gachaTimes"],
                                           "price": row["gachaPrice"], "characters": characters,
                                           "weights": weights,
                                           "name": row.get("gachaPoolName", "新人特惠寻访"),
                                           "intro": sections[0].strip(),
                                           "description": sections[-1].partition("\n\n")[2].strip()}
            self.default_newcomer = max(self.newcomer, key=lambda key: self.newcomer[key]["index"], default=None)
            self.normal = {}
            for row in table.get("gachaPoolClient", []):
                pool_id, count, available = row["gachaPoolId"], row["guarantee5Count"], row["guarantee5Avail"]
                if (not isinstance(pool_id, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,96}", pool_id)
                        or pool_id in self.normal or type(count) is not int or not 0 <= count <= 10000
                        or type(available) is not int or available not in {0, 1}):
                    raise ValueError("Invalid headhunting guarantee definition")
                self.normal[pool_id] = {"maximum": count, "available": bool(available)}
            self.pools = rules.validate_data(data) if rules is not None else {}
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise DomainError("INVALID_HEADHUNTING_DATA", "寻访卡池、概率或干员引用非法", 503) from exc
