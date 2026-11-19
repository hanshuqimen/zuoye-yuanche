"""First-theme special-ticket contracts and explicit predefined candidate pools.

Catalog membership is not a ticket grant, probability, training template or an
enabled recruitment effect. The domain must implement the complete effect
before admitting any of these tickets into a shop or reward plan.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_upgrades import PROFESSIONS, RARITIES, UpgradeTicket
from terralocal.server.gamedata.roguelike import invalid


@dataclass(frozen=True)
class SpecialTicket(UpgradeTicket):
    effect: str
    free_rarities: frozenset[str]
    elite_count: int
    reserves: tuple[str, ...]


@dataclass(frozen=True)
class PredefinedCandidate:
    char_id: str
    kind: str
    profession: str
    rarity: str
    module_id: str | None


def expected_tickets():
    result = {}
    for profession in sorted(PROFESSIONS):
        for suffix, rarity in (("red", "TIER_6"), ("sp", "TIER_4")):
            # The frozen identifier really is redecial_red, not special_red.
            name = "redecial" if profession == "SPECIAL" and suffix == "red" else profession.lower()
            result[name + "_" + suffix] = (
                profession, frozenset({profession}), "FREE_TEMP_GUARANTEED", frozenset({rarity}), 0)
    result["all_premium"] = (639, PROFESSIONS, "ELITE_TEMP_GUARANTEED", frozenset(), 1)
    result["all_discount"] = (639, PROFESSIONS, "DIRECT_UPGRADE_RANDOM", frozenset(), 0)
    result["quad_melee_discount"] = (
        581, frozenset({"WARRIOR", "TANK", "SPECIAL", "PIONEER"}), "DIRECT_UPGRADE_RANDOM", frozenset(), 0)
    result["quad_ranged_discount"] = (
        58, frozenset({"SNIPER", "MEDIC", "SUPPORT", "CASTER"}), "DIRECT_UPGRADE_RANDOM", frozenset(), 0)
    return result


FREE_TICKET_IDS = frozenset("rogue_1_recruit_ticket_" + key for key, value in expected_tickets().items()
                            if value[2] == "FREE_TEMP_GUARANTEED")
ELITE_TICKET_ID = "rogue_1_recruit_ticket_all_premium"
DIRECT_TICKET_IDS = frozenset("rogue_1_recruit_ticket_" + key for key, value in expected_tickets().items()
                              if value[2] == "DIRECT_UPGRADE_RANDOM")


class FirstThemeSpecialRecruitRules:
    topic_id = "rogue_1"

    def __init__(self, data):
        self._data = data
        data.rogue_topics.topic(self.topic_id)
        table = data.table("roguelike_topic_table")
        detail = table["details"][self.topic_id]
        rows, predefined = detail.get("recruitTickets"), table["constant"].get("predefinedChars")
        if not isinstance(rows, dict) or not isinstance(predefined, dict):
            raise invalid("特殊招募券或预定义候选目录不完整")
        candidates = {}
        for key, row in predefined.items():
            if (not isinstance(row, dict) or row.get("charId") != key
                    or row.get("recruitType") not in ("FREE", "THIRD_LOW", "THIRD")
                    or type(row.get("canBeFree")) is not bool
                    or row.get("uniEquipId") is not None and type(row["uniEquipId"]) is not str):
                raise invalid("特殊招募预定义干员引用或类别不匹配")
            kind = row["recruitType"]
            if kind == "THIRD_LOW" or kind == "FREE" and not row["canBeFree"]:
                continue
            char = data.character(key)
            profession, rarity = char.get("profession"), char.get("rarity")
            if type(rarity) is int and 0 <= rarity <= 5:
                rarity = "TIER_" + str(rarity + 1)
            if (type(profession) is not str or profession not in PROFESSIONS
                    or type(rarity) is not str or rarity not in {"TIER_4", "TIER_5", "TIER_6"}
                    or type(char.get("phases")) is not list or len(char["phases"]) < 3
                    or kind == "FREE" and char.get("isNotObtainable")):
                raise invalid("特殊招募候选职业、稀有度或两级养成引用不匹配")
            candidates[key] = PredefinedCandidate(key, kind, profession, rarity, row.get("uniEquipId"))
        tickets, source = {}, {}
        for suffix, (mask, professions, effect, free, elite) in expected_tickets().items():
            key = "rogue_1_recruit_ticket_" + suffix
            row = rows.get(key)
            if (not isinstance(row, dict) or set(row) != {"id", "profession", "rarity", "professionList", "rarityList",
                    "extraEliteNum", "extraFreeRarity", "extraCharIds"} or row.get("id") != key
                    or type(row.get("profession")) is not type(mask) or row["profession"] != mask
                    or row.get("rarity") != "ALL"
                    or type(row.get("extraEliteNum")) is not int or row["extraEliteNum"] != elite):
                raise invalid("特殊招募券标识、原始枚举或效果参数不匹配")
            for field, expected in (("professionList", professions), ("rarityList", RARITIES), ("extraFreeRarity", free)):
                value = row.get(field)
                if (type(value) is not list or any(type(v) is not str for v in value)
                        or len(value) != len(expected) or frozenset(value) != expected):
                    raise invalid("特殊招募券展开筛选或保证临时稀有度不匹配")
            reserves = row.get("extraCharIds")
            if type(reserves) is not list or any(type(v) is not str for v in reserves) or len(set(reserves)) != len(reserves):
                raise invalid("特殊招募券备用列表不明确或重复")
            for char_id in reserves:
                value = predefined.get(char_id)
                if (not isinstance(value, dict) or value.get("charId") != char_id
                        or value.get("recruitType") != "THIRD_LOW" or len(data.character(char_id)["phases"]) < 2):
                    raise invalid("特殊招募券备用引用未匹配THIRD_LOW")
            item = detail.get("items", {}).get(key)
            if not isinstance(item, dict) or item.get("id") != key or item.get("type") != "RECRUIT_TICKET":
                raise invalid("特殊招募券物品引用不匹配")
            ticket = SpecialTicket(key, professions, RARITIES, effect, free, elite, tuple(reserves))
            if (free and any(not any(c.kind == "FREE" and c.rarity == rarity and c.profession in professions
                                    for c in candidates.values()) for rarity in free)
                    or elite and not any(c.kind == "THIRD" and c.profession in professions for c in candidates.values())):
                raise invalid("特殊招募券保证效果没有匹配的预定义候选")
            tickets[key], source[key] = ticket, row
        self.tickets = MappingProxyType(tickets)
        self.candidates = MappingProxyType(candidates)
        self.data_hash = data.manifest["hash"]
        self.fingerprint = fingerprint({"data": self.data_hash, "topic": self.topic_id, "tickets": source,
                                        "predefined": predefined})

    def pool(self, ticket_id, *, kind, rarity=None, excluded=()):
        """Eligible references only; no draw, official weight or training grant."""
        if ticket_id not in self.tickets or kind not in ("FREE", "THIRD"):
            raise invalid("特殊招募池需要明确票券及候选类别")
        ticket = self.tickets[ticket_id]
        if (kind == "FREE" and rarity not in ticket.free_rarities
                or kind == "THIRD" and (not ticket.elite_count or rarity is not None)):
            raise invalid("此票券未保证所请求的临时类别或稀有度")
        if type(excluded) not in (tuple, frozenset) or any(type(v) is not str for v in excluded):
            raise invalid("特殊招募已用候选排除必须是明确标识")
        return tuple(c for key, c in sorted(self.candidates.items()) if key not in excluded and c.kind == kind
                     and c.profession in ticket.professions and (rarity is None or c.rarity == rarity))

    def elite_scope(self, ticket_id, scope):
        """Validate a reviewed supply scope, without inventing a theme-wide pool.

        Global predefined membership alone does not establish that a character
        can appear in this topic/mode/account. Until generation is recovered,
        the trusted supply plan must declare that eligible range explicitly.
        """
        if (ticket_id != ELITE_TICKET_ID or type(scope) is not tuple or not scope
                or any(type(key) is not str for key in scope) or len(set(scope)) != len(scope)):
            raise ValueError("精英招募必须由供给方案明确指定唯一的候选范围")
        inventory = {c.char_id: c for c in self.pool(ticket_id, kind="THIRD")}
        if any(key not in inventory or inventory[key].module_id is not None for key in scope):
            raise ValueError("精英候选未匹配预定义THIRD或包含尚未接纳的模组")
        return tuple(inventory[key] for key in scope)

    def direct_scope(self, ticket_id, scope):
        """Validate an explicit supply outcome; this is not a random algorithm.

        The frozen ticket description promises partially advanced candidates,
        but contains no draw count or probability. A trusted supply plan must
        bind the outcome until that generation contract is recovered.
        """
        if (ticket_id not in DIRECT_TICKET_IDS or type(scope) is not tuple or not scope
                or any(type(key) is not str for key in scope) or len(set(scope)) != len(scope)):
            raise ValueError("直升招募必须由供给方案明确指定唯一的候选范围")
        ticket = self.tickets[ticket_id]
        for key in scope:
            if key not in self._data.table("character_table"):
                raise ValueError("直升候选引用了未知干员")
            char = self._data.character(key)
            rarity = self._data.rarity(char)
            if (not ticket.matches_definition(char) or char.get("isNotObtainable")
                    or rarity < 3 or len(char["phases"]) < 3):
                raise ValueError("直升候选必须匹配此券的可招募四星以上干员")
        return scope
