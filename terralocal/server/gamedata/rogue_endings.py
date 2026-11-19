"""Frozen IS2 boss identities and two structured change_stage effects.

Client tables/signed level projections identify stages and bosses. Terminal
route conditions are a versioned PRTS community adapter, not official server
code. This catalog grants neither a route relic nor a map/battle reward.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-boss-ending-routes-prts-v1"
SOURCE = "https://prts.wiki/w/傀影与猩红孤钻#结局"
FINAL = {
    "ro1_b_6": ("zone_5", "覆水难收", "ro_ending_1", "舞会终场", None, 0),
    "ro1_b_7": ("zone_5", "别无所求", "ro_ending_2", "滑稽喜剧", "boss_csdoll", 1),
    "ro1_b_8": ("zone_6", "诸事不顺", "ro_ending_3", "盛大揭幕", "boss_cshost", 2),
    "ro1_b_9": ("zone_6", "再启新篇", "ro_ending_4", "沉默之章", "boss_cswrtr", 3),
}
CHANGES = {
    "rogue_1_relic_m16": ("残破的玩偶", "ro1_b_6", "ro1_b_7"),
    "rogue_1_relic_n02": ("初幕", "ro1_b_8", "ro1_b_9"),
}
REALIZATION = "rogue_1_relic_m21"


def available(data):
    return (data is not None and "roguelike_topic_table" in data.manifest["tables"]
            and "endings" in data.table("roguelike_topic_table")["details"].get("rogue_1", {}))


def invalid():
    return ValueError("首主题Boss、结局或分歧藏品定义未匹配")


@dataclass(frozen=True)
class BossRoute:
    ending: str | None
    next_zone: str | None
    next_boss: str | None


class FirstThemeEndings:
    def __init__(self, data):
        data.rogue_topics.topic("rogue_1")
        detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
        try:
            for stage, (zone, name, ending, title, icon, priority) in FINAL.items():
                row, end = detail["stages"][stage], detail["endings"][ending]
                if (row["id"] != stage or row["name"] != name
                        or row["levelId"] != "Obt/Roguelike/RO1/level_rogue1_b-" + stage.removeprefix("ro1_b_")
                        or type(row["isBoss"]) is not int or row["isBoss"] != 1
                        or type(row["isElite"]) is not int or row["isElite"] != 0
                        or end["id"] != ending or end["name"] != title or end["bossIconId"] != icon
                        or type(end["priority"]) is not int or end["priority"] != priority):
                    raise invalid()
                data.rogue_map.require_placement("BATTLE_BOSS", stage, zone)
            if set(detail["endings"]) != {row[2] for row in FINAL.values()}:
                raise invalid()
            for key, (name, before, after) in CHANGES.items():
                item = detail["items"][key]
                buffs = detail["relics"][key]["buffs"]
                changes = [b for b in buffs if b["key"] == "change_stage"]
                expected = {"key": "change_stage", "blackboard": [
                    {"key": "from", "value": 0.0, "valueStr": before},
                    {"key": "to", "value": 0.0, "valueStr": after}]}
                params = detail["relicParams"][key]
                if (item["id"] != key or item["type"] != "RELIC" or item["name"] != name
                        or detail["relics"][key]["id"] != key or params["id"] != key or changes != [expected]
                        or any(type(v["value"]) not in (int, float) for v in changes[0]["blackboard"])
                        or params["checkCharBoxParams"] != [] or params["checkCharBoxTypes"] != []):
                    raise invalid()
            declared = {key for key, row in detail["relics"].items()
                        if any(b["key"] == "change_stage" for b in row["buffs"])}
            if declared != set(CHANGES):
                raise invalid()
            realized = detail["items"][REALIZATION]
            if realized["id"] != REALIZATION or realized["name"] != "恍悟" or realized["type"] != "RELIC":
                raise invalid()
            intermediate = {"ro1_b_" + str(i) for i in range(1, 6)}
            for stage in intermediate:
                data.rogue_map.require_placement("BATTLE_BOSS", stage, "zone_3")
            relics = frozenset(key for key, row in detail["items"].items() if row.get("type") == "RELIC")
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.finals = MappingProxyType(dict(FINAL))
        self.changes = MappingProxyType(dict(CHANGES))
        self.intermediate, self.relics = frozenset(intermediate), relics
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"],
            "finals": dict(self.finals), "changes": dict(self.changes), "realization": REALIZATION})

    def carried(self, relics):
        if (type(relics) is not tuple or any(type(k) is not str or k not in self.relics for k in relics)
                or len(set(relics)) != len(relics)):
            raise invalid()
        return frozenset(relics)

    def stage(self, original, relics):
        carried = self.carried(relics)
        if original not in self.finals and original not in self.intermediate:
            raise invalid()
        for key, (_, before, after) in self.changes.items():
            if key in carried and original == before:
                return after
        return original

    def cleared(self, stage, zone, relics):
        carried = self.carried(relics)
        if stage in self.intermediate:
            if zone != "zone_3":
                raise invalid()
            return BossRoute(None, "zone_4", None)
        if stage not in self.finals or self.finals[stage][0] != zone:
            raise invalid()
        if stage in ("ro1_b_6", "ro1_b_7"):
            if stage != self.stage("ro1_b_6", relics):
                raise invalid()
            if REALIZATION in carried or "rogue_1_relic_n02" in carried:
                return BossRoute(None, "zone_6", self.stage("ro1_b_8", relics))
        elif (stage != self.stage("ro1_b_8", relics)
                or not (REALIZATION in carried or "rogue_1_relic_n02" in carried)):
            raise invalid()
        return BossRoute(self.finals[stage][2], None, None)
