"""Frozen first-theme recruit_cost deltas, separate from acquisition/history.

This compiles four unconditional effects. It grants no relic, supplies no
unlocks or random pool, and is not enabled by a client's list of relic IDs.
The domain still has to bind its owned acquisition order to immutable offers.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_upgrades import PROFESSIONS, RARITIES

POLICY = "rogue1-four-recruit-cost-deltas-v1"
FILTERS = {
    "rogue_1_relic_r25": frozenset({"TIER_4"}),
    "rogue_1_relic_r26": frozenset({"TIER_5"}),
    "rogue_1_relic_r27": frozenset({"TIER_6"}),
    "rogue_1_relic_r28": frozenset({"TIER_4", "TIER_5", "TIER_6"}),
}


@dataclass(frozen=True)
class RecruitCostModifier:
    id: str
    rarities: frozenset[str]
    professions: frozenset[str]
    delta: int


@dataclass(frozen=True)
class RecruitCostQuote:
    base: int
    delta: int
    total: int
    applied: tuple[str, ...]
    snapshot: tuple[str, ...]
    rule_hash: str


def invalid():
    return ValueError("首主题招募费用效果未匹配明确的冻结规则")


def enum_filter(row, expected):
    raw = row["valueStr"]
    if type(raw) is not str or type(row["value"]) not in (int, float) or row["value"] != 0:
        raise invalid()
    values = raw.split(",")
    if len(values) != len(set(values)) or frozenset(values) != expected:
        raise invalid()
    return frozenset(values)


class FirstThemeRecruitCostRules:
    """Immutable compilation; descriptions never replace mechanical filters."""

    topic_id = "rogue_1"

    def __init__(self, data):
        data.rogue_topics.topic(self.topic_id)
        modifiers, sources = {}, {}
        try:
            detail = data.table("roguelike_topic_table")["details"][self.topic_id]
            for key, rarities in FILTERS.items():
                item = detail["items"][key]
                row, params = detail["relics"][key], detail["relicParams"][key]
                if (item.get("id") != key or item.get("type") != "RELIC"
                        or set(row) != {"id", "buffs"} or row["id"] != key
                        or type(row["buffs"]) is not list or len(row["buffs"]) != 1
                        or params != {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []}):
                    raise invalid()
                buff = row["buffs"][0]
                if (type(buff) is not dict or set(buff) != {"key", "blackboard"}
                        or buff["key"] != "recruit_cost" or type(buff["blackboard"]) is not list):
                    raise invalid()
                board = {}
                for value in buff["blackboard"]:
                    if (type(value) is not dict or set(value) != {"key", "value", "valueStr"}
                            or type(value["key"]) is not str or value["key"] in board):
                        raise invalid()
                    board[value["key"]] = value
                if set(board) != {"rarity", "profession", "delta"}:
                    raise invalid()
                enum_filter(board["rarity"], rarities)
                enum_filter(board["profession"], PROFESSIONS)
                delta = board["delta"]
                if type(delta["value"]) not in (int, float) or delta["value"] != -2 or delta["valueStr"] is not None:
                    raise invalid()
                modifiers[key] = RecruitCostModifier(key, rarities, PROFESSIONS, -2)
                sources[key] = {"effect": row, "conditions": params, "item_type": item["type"]}
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.modifiers = MappingProxyType(modifiers)
        self.data_hash = data.manifest["hash"]
        self.fingerprint = fingerprint({"policy": POLICY, "data": self.data_hash, "topic": self.topic_id,
                                        "sources": sources})

    def quote(self, base, *, profession, rarity, modifiers=(), operation="RECRUIT"):
        """Pure server-owned context; no database ownership or grants here.

        Add matching deltas, then clamp at zero. recruit_cost does not change
        upgrade fees. A zero-cost temporary recruit can never yield hope.
        Conditional/one-use effects and their ordering are not admitted.
        """
        if (type(base) is not int or not 0 <= base < 2**31
                or type(profession) is not str or profession not in PROFESSIONS
                or type(rarity) is not str or rarity not in RARITIES
                or type(operation) is not str or operation not in ("RECRUIT", "UPGRADE")
                or type(modifiers) is not tuple or any(type(key) is not str for key in modifiers)
                or len(set(modifiers)) != len(modifiers)
                or any(key not in self.modifiers for key in modifiers)):
            raise invalid()
        snapshot = tuple(sorted(modifiers))
        applied = tuple(key for key in snapshot if operation == "RECRUIT"
                        and rarity in self.modifiers[key].rarities and profession in self.modifiers[key].professions)
        delta = sum(self.modifiers[key].delta for key in applied)
        total = max(0, base + delta)
        digest = fingerprint({"policy": POLICY, "rules": self.fingerprint, "base": base,
            "profession": profession, "rarity": rarity, "operation": operation,
            "snapshot": snapshot, "applied": applied, "delta": delta, "total": total})
        return RecruitCostQuote(base, delta, total, applied, snapshot, digest)
