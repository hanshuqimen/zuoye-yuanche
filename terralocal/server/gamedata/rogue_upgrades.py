"""Frozen first-theme upgrade-ticket filters and training ceilings.

These are static constraints, not promotion eligibility or a ticket grant.
Ownership, run mode, current upgrade state and an immutable promotion journal
belong to the domain adapter. Loading this catalog enables no game route.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.roguelike import invalid

PROFESSIONS = frozenset({"WARRIOR", "SNIPER", "TANK", "MEDIC", "SUPPORT", "CASTER", "SPECIAL", "PIONEER"})
RARITIES = frozenset("TIER_" + str(i) for i in range(1, 7))


@dataclass(frozen=True)
class TrainingCeiling:
    evolve_phase: int
    skill_level: int
    specialize_level: int


@dataclass(frozen=True)
class UpgradeTicket:
    id: str
    professions: frozenset[str]
    rarities: frozenset[str]

    def matches_definition(self, character: dict) -> bool:
        """Only table membership; never sufficient permission to promote."""
        if not isinstance(character, dict):
            raise invalid("进阶券筛选需要明确干员定义")
        profession, rarity = character.get("profession"), character.get("rarity")
        if type(rarity) is int and 0 <= rarity <= 5:
            rarity = "TIER_" + str(rarity + 1)
        if (not isinstance(profession, str) or profession not in PROFESSIONS
                or not isinstance(rarity, str) or rarity not in RARITIES):
            raise invalid("进阶券筛选的职业或稀有度不匹配")
        return profession in self.professions and rarity in self.rarities


class FirstThemeUpgradeRules:
    topic_id = "rogue_1"

    def __init__(self, data):
        data.rogue_topics.topic(self.topic_id)
        detail = data.table("roguelike_topic_table")["details"][self.topic_id]
        rows = detail.get("upgradeTickets")
        expected = {"rogue_1_upgrade_ticket_all": (PROFESSIONS, RARITIES, 639, "ALL"),
                    "rogue_1_upgrade_ticket_5star": (PROFESSIONS, RARITIES - {"TIER_6"}, 639, 31)}
        expected.update({"rogue_1_upgrade_ticket_" + p.lower(): (frozenset({p}), RARITIES, p, "ALL")
                         for p in sorted(PROFESSIONS)})
        if not isinstance(rows, dict) or rows.keys() != expected.keys():
            raise invalid("首主题进阶券目录不完整或出现未接纳类别")
        tickets = {}
        for key, (professions, rarities, profession_mask, rarity_mask) in expected.items():
            row = rows[key]
            if (not isinstance(row, dict)
                    or set(row) != {"id", "profession", "rarity", "professionList", "rarityList"}
                    or row["id"] != key
                    or type(row["profession"]) is not type(profession_mask) or row["profession"] != profession_mask
                    or type(row["rarity"]) is not type(rarity_mask) or row["rarity"] != rarity_mask):
                raise invalid("首主题进阶券标识、原始枚举或字段不匹配")
            for field, values in (("professionList", professions), ("rarityList", rarities)):
                value = row[field]
                if (not isinstance(value, list) or any(not isinstance(v, str) for v in value)
                        or len(value) != len(values) or frozenset(value) != values):
                    raise invalid("首主题进阶券展开筛选与原始枚举不匹配")
            item = detail.get("items", {}).get(key)
            if not isinstance(item, dict) or item.get("id") != key or item.get("type") != "UPGRADE_TICKET":
                raise invalid("首主题进阶券物品引用未匹配")
            tickets[key] = UpgradeTicket(key, professions, rarities)
        caps = detail.get("detailConst", {}).get("charUpgradeTable")
        expected_caps = {
            "0": {"evolvePhase": "PHASE_1", "skillLevel": 7, "skillSpecializeLevel": 0},
            "1": {"evolvePhase": "PHASE_2", "skillLevel": 7, "skillSpecializeLevel": 3},
        }
        # Canonical comparison is type-sensitive: True must not equal integer1.
        if fingerprint(caps) != fingerprint(expected_caps):
            raise invalid("首主题进阶养成上限不完整或版本不匹配")
        self.tickets = MappingProxyType(tickets)
        self.ceilings = (TrainingCeiling(1, 7, 0), TrainingCeiling(2, 7, 3))
        self.data_hash = data.manifest["hash"]
        self.fingerprint = fingerprint({"data": self.data_hash, "topic": self.topic_id,
                                        "tickets": rows, "ceilings": caps})
