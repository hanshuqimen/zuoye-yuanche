"""First-theme NORMAL/0 ordinary tickets; no cost modifiers or random offers.

The modern table defines training limits and explicit reserve candidates, but
does not contain the hope-cost table. Costs below are the IS2 base adapter
(0/2/3/6), not the legacy roguelike table's obsolete five-star cost of four.
Evidence and the remaining native check are recorded in the project ledger.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.rogue_upgrades import PROFESSIONS, RARITIES, UpgradeTicket

# Explicit plain variants only. Similar suffixes may add temporary or direct
# promotion effects; matching masks alone never admits those tickets.
VARIANTS = {
    "all": (639, PROFESSIONS, "ALL", RARITIES),
    "5star": (639, PROFESSIONS, 31, RARITIES - {"TIER_6"}),
    "double_1": (513, frozenset({"WARRIOR", "PIONEER"}), "ALL", RARITIES),
    "double_2": (20, frozenset({"TANK", "SUPPORT"}), "ALL", RARITIES),
    "double_3": (10, frozenset({"SNIPER", "MEDIC"}), "ALL", RARITIES),
    "double_4": (96, frozenset({"CASTER", "SPECIAL"}), "ALL", RARITIES),
    "quad_melee": (581, frozenset({"WARRIOR", "TANK", "SPECIAL", "PIONEER"}), "ALL", RARITIES),
    "quad_ranged": (58, frozenset({"SNIPER", "MEDIC", "SUPPORT", "CASTER"}), "ALL", RARITIES),
}


@dataclass(frozen=True)
class RecruitTicket(UpgradeTicket):
    reserves: tuple[str, ...]


class FirstThemeRecruitRules:
    costs = (0, 0, 0, 2, 3, 6)
    # First-theme base adapter, not a field inferred from the modern table.
    # Four/five/six-star promotion costs1/2/3 are documented alongside the
    # matching recruit costs by the 2022 IS2 guide; modifiers need their own
    # contracts. The frozen client consumes the server's candidate.population.
    upgrade_costs = (None, None, None, 1, 2, 3)

    def __init__(self, data):
        initial = data.rogue_initial
        table = data.table("roguelike_topic_table")
        detail = table["details"][initial.topic_id]
        cap = detail.get("detailConst", {}).get("charUpgradeTable", {}).get("0")
        if cap != {"evolvePhase": "PHASE_1", "skillLevel": 7, "skillSpecializeLevel": 0}:
            raise ValueError("首主题普通招募的初始养成上限未匹配")
        predefined = table["constant"].get("predefinedChars", {})
        tickets, catalog = {}, {}

        def reserves_for(definition):
            reserves = definition.get("extraCharIds")
            if (not isinstance(reserves, list) or any(not isinstance(c, str) for c in reserves)
                    or len(set(reserves)) != len(reserves)):
                raise ValueError("普通招募券备用候选必须是明确、唯一的干员列表")
            for char_id in reserves:
                char = data.character(char_id)
                entry = predefined.get(char_id)
                if (not isinstance(entry, dict) or entry.get("charId") != char_id
                        or entry.get("recruitType") != "THIRD_LOW" or len(char["phases"]) < 2):
                    raise ValueError("备用候选未匹配明确的THIRD_LOW预定义干员")
            return tuple(reserves)

        for key in sorted({t for group in initial.groups.values() for t in group}):
            definition = detail["recruitTickets"][key]
            reserves = reserves_for(definition)
            tickets[key] = (definition["profession"], reserves)
            catalog[key] = RecruitTicket(key, frozenset({definition["profession"]}), RARITIES, reserves)
        for suffix, (mask, professions, rarity_mask, rarities) in VARIANTS.items():
            key = "rogue_1_recruit_ticket_" + suffix
            if key not in detail["recruitTickets"]:
                continue  # Older minimal imports need not contain these variants.
            row = detail["recruitTickets"][key]
            if (not isinstance(row, dict) or set(row) != {"id", "profession", "rarity", "professionList", "rarityList",
                    "extraEliteNum", "extraFreeRarity", "extraCharIds"} or row.get("id") != key
                    or type(row.get("profession")) is not type(mask) or row["profession"] != mask
                    or type(row.get("rarity")) is not type(rarity_mask) or row["rarity"] != rarity_mask
                    or type(row.get("extraEliteNum")) is not int or row["extraEliteNum"] != 0
                    or row.get("extraFreeRarity") != []):
                raise ValueError("普通多职业招募券标识、枚举或特殊效果不匹配")
            for field, expected in (("professionList", professions), ("rarityList", rarities)):
                value = row.get(field)
                if (not isinstance(value, list) or any(type(v) is not str for v in value)
                        or len(value) != len(expected) or frozenset(value) != expected):
                    raise ValueError("普通多职业招募券展开筛选与枚举不匹配")
            item = detail["items"].get(key)
            if not isinstance(item, dict) or item.get("id") != key or item.get("type") != "RECRUIT_TICKET":
                raise ValueError("普通多职业招募券物品引用不匹配")
            catalog[key] = RecruitTicket(key, professions, rarities, reserves_for(row))
        # Legacy recipes and deterministic battle-reward hashes keep their
        # original eight-ticket pool. Catalog admission does not grant a drop.
        self.tickets = MappingProxyType(tickets)
        self.catalog = MappingProxyType(catalog)
        self.phase, self.skill_level = 1, 7
