"""Two explicit roster-condition families in the frozen first theme.

Targets come from the matched item conditions, not from a generic Chinese-text
parser. Difficulty eligibility is a separate structured canUnlockItem gate.
No item effects, natural stock, promotions, battle squads or ending goals are
inferred from these counters.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_upgrades import RARITIES

POLICY = "rogue1-roster-and-total-recruit-unlocks-v1"
CONDITIONS = {
    "rogue_1_relic_r26": ("MAX_ROSTER", "TIER_5", 5, "在任意时刻拥有5个五星干员"),
    "rogue_1_relic_r27": ("MAX_ROSTER", "TIER_6", 4, "在任意时刻拥有4个六星干员"),
    "rogue_1_relic_r08": ("TOTAL_RECRUITS", None, 30, "在多局游戏中累计招募总共30名干员"),
    "rogue_1_relic_a38": ("TOTAL_RECRUITS", None, 70, "在多局游戏中累计招募总共70名干员"),
    "rogue_1_relic_a45": ("TOTAL_RECRUITS", None, 120, "在多局游戏中累计招募总共120名干员"),
}


def available(data):
    # Older QA profiles can define scoring difficulties without any unlock
    # gates. Only declared gate capability enables this contract. A declared
    # but malformed gate still reaches the strict compiler and is rejected.
    if data is None or "roguelike_topic_table" not in data.manifest["tables"]:
        return False
    detail = data.table("roguelike_topic_table")["details"].get("rogue_1", {})
    if "difficulties" not in detail:
        return False
    rows = detail["difficulties"]
    return type(rows) is not list or any(type(row) is not dict or "canUnlockItem" in row for row in rows)


def invalid():
    return ValueError("首主题招募收藏品条件或模式资格与匹配数据不一致")


@dataclass(frozen=True)
class RosterCondition:
    id: str
    kind: str
    rarity: str | None
    target: int


@dataclass(frozen=True)
class RunRoster:
    mode: str
    grade: int
    started_at: int
    characters: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class UnlockProgress:
    current: int
    target: int

    def wire(self):
        return {"state": int(self.current >= self.target), "progress": [self.current, self.target]}


class FirstThemeRosterUnlocks:
    def __init__(self, data):
        topic = data.rogue_topics.topic("rogue_1")
        conditions, modes, sources = {}, {}, {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            for key, (kind, rarity, target, description) in CONDITIONS.items():
                entry = data.rogue_relic_archive.entries[key]
                if entry.unlock_description != description or entry.enrollment is not None or entry.special:
                    raise invalid()
                conditions[key] = RosterCondition(key, kind, rarity, target)
                sources[key] = description
            if type(detail["difficulties"]) is not list:
                raise invalid()
            for row in detail["difficulties"]:
                if row.get("modeDifficulty") not in ("EASY", "NORMAL") or row.get("grade") != 0:
                    continue
                mode = row["modeDifficulty"]
                if (mode in modes or type(row["grade"]) is not int or type(row.get("canUnlockItem")) is not bool):
                    raise invalid()
                enrollment = row["enrollId"]
                enrolled_at = 0
                if enrollment is not None:
                    enroll = detail["enrolls"][enrollment]
                    enrolled_at = enroll["enrollTime"]
                    if (enroll["enrollId"] != enrollment or type(enrolled_at) is not int
                            or not 0 <= enrolled_at < 2**63):
                        raise invalid()
                modes[mode] = (row["canUnlockItem"], enrolled_at)
            if set(modes) != {"EASY", "NORMAL"} or modes["EASY"][0] or not modes["NORMAL"][0]:
                raise invalid()
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.conditions = MappingProxyType(conditions)
        self.modes = MappingProxyType(modes)
        self.topic_start = topic.start
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "archive": data.rogue_relic_archive.fingerprint, "conditions": sources,
            "modes": modes, "topic_start": self.topic_start})

    def allows(self, mode, grade, started_at):
        """Shared structured difficulty/time gate; never infer from a UI label."""
        if (type(mode) is not str or mode not in self.modes or type(grade) is not int or grade != 0
                or type(started_at) is not int or not 0 <= started_at < 2**63):
            raise invalid()
        allowed, enrolled_at = self.modes[mode]
        return allowed and started_at >= max(enrolled_at, self.topic_start)

    def evaluate(self, rosters):
        if type(rosters) is not tuple:
            raise invalid()
        maxima = {"TIER_5": 0, "TIER_6": 0}
        total = 0
        for roster in rosters:
            if (type(roster) is not RunRoster or type(roster.mode) is not str or roster.mode not in self.modes
                    or type(roster.grade) is not int or roster.grade != 0
                    or type(roster.started_at) is not int or not 0 <= roster.started_at < 2**63
                    or type(roster.characters) is not tuple
                    or any(type(c) is not tuple or len(c) != 2 or type(c[0]) is not str
                        or not 0 < len(c[0]) <= 128 or type(c[1]) is not str or c[1] not in RARITIES
                        for c in roster.characters)
                    or len({c[0] for c in roster.characters}) != len(roster.characters)):
                raise invalid()
            if not self.allows(roster.mode, roster.grade, roster.started_at):
                continue
            total += len(roster.characters)
            for rarity in maxima:
                maxima[rarity] = max(maxima[rarity], sum(c[1] == rarity for c in roster.characters))
        return MappingProxyType({key: UnlockProgress(min(rule.target,
            total if rule.kind == "TOTAL_RECRUITS" else maxima[rule.rarity]), rule.target)
            for key, rule in self.conditions.items()})
