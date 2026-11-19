"""Five complete immediate life relics for the first theme's uncapped HP.

This does not establish natural supply or rules for themes with a life cap.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_currency_relics import increase

POLICY = "rogue1-immediate-uncapped-life-relics-v1"
CONSTANTS = MappingProxyType({"hpItemId": "rogue_1_hp", "maxHpItemId": None,
                             "populationItemId": "rogue_1_population"})


@dataclass(frozen=True)
class LifeGain:
    hp: int
    hope: int


SOURCES = MappingProxyType({
    "rogue_1_relic_r01": (LifeGain(2, 1), "3590f04b9c10cdaf0120f92a254b570e480d23858c40c18ae875fb39f4171e53"),
    "rogue_1_relic_r02": (LifeGain(6, 0), "dd09e664cd558ad03d82b1eba8a29db996d4750cc9e671356503db0ee9bc9764"),
    "rogue_1_relic_r03": (LifeGain(6, 0), "cc226320443d16cfd202df4d874ef0e88dc4fa85f547c2a10d3c298c10c52837"),
    "rogue_1_relic_r04": (LifeGain(8, 0), "3f05b72532dd9d371e95ec617c5dd61a541b57f4f85f7e67e8378f974071997a"),
    "rogue_1_relic_r05": (LifeGain(10, 0), "d8c87876f620976a5f5c4826a8b5e7df32b0c99886eb0373370af8e24853c0a3"),
})


def invalid():
    return ValueError("首主题即时生命收藏品与完整匹配定义不一致")


class FirstThemeLifeRelics:
    def __init__(self, data):
        data.rogue_topics.topic("rogue_1")
        entries, sources = {}, {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            for key, (gain, expected) in SOURCES.items():
                if key not in detail["items"]:
                    continue
                targets = {buff["blackboard"][0]["valueStr"] for buff in detail["relics"][key]["buffs"]}
                source = {"effect": detail["relics"][key], "conditions": detail["relicParams"][key],
                          "item_type": detail["items"][key]["type"],
                          "constants": {field: detail["gameConst"][field] for field in CONSTANTS},
                          "targets": {target: {field: detail["items"][target][field] for field in ("id", "type")}
                                      for target in targets}}
                ref = data.rogue_relic_archive.entries[key]
                if (source["constants"] != CONSTANTS or detail["items"][key].get("id") != key
                        or source["item_type"] != "RELIC" or source["effect"].get("id") != key
                        or fingerprint(source) != expected or ref.special or ref.enrollment is not None):
                    raise invalid()
                amounts = {CONSTANTS["hpItemId"]: 0, CONSTANTS["populationItemId"]: 0}
                for buff in source["effect"]["buffs"]:
                    target, amount = buff["blackboard"][0]["valueStr"], buff["blackboard"][1]["value"]
                    if target not in amounts or type(amount) is not float or not amount.is_integer() or amount <= 0:
                        raise invalid()
                    amounts[target] += int(amount)
                if LifeGain(*amounts.values()) != gain:
                    raise invalid()
                entries[key], sources[key] = gain, expected
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise invalid() from exc
        self.entries = MappingProxyType(entries)
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"], "sources": sources,
                                        "archive": data.rogue_relic_archive.fingerprint,
                                        "gains": {key: (v.hp, v.hope) for key, v in entries.items()}})

    def require(self, key):
        if type(key) is not str or key not in self.entries:
            raise invalid()
        return self.entries[key]

    def apply(self, key, hp, hp_max, hope_max):
        gain = self.require(key)
        # The frozen first theme has no max-HP item and initialMaxHp=0.
        # A positive cap requires a separate complete rule, never a guess.
        if type(hp_max) is not int or hp_max != 0:
            raise invalid()
        return increase(hp, gain.hp), increase(hope_max, gain.hope)


def supported(data, key):
    if type(key) is not str or key not in SOURCES:
        return False
    data.rogue_life_relics.require(key)
    return True
