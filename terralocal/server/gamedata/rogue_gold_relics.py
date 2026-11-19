"""Exact first-theme immediate-gold effects, independent of unlocks/supply.

Only three reviewed complete definitions are admitted. The positive gain is
part of a compiled quote and its causal payment replay, never a client value.
No merchant availability or encounter probability follows from this catalog.
"""

from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-immediate-gold-relics-v1"
SOURCES = MappingProxyType({
    "rogue_1_relic_r11": (10, "29d65e0d13129cfa57d0906b44063a2f70c62ba3a3eb267b189500769a067e7e"),
    "rogue_1_relic_r12": (18, "84704051c971d3f7199b9dde925b6cbb09d0cf0fa937da930e220f1e61fe1ce1"),
    "rogue_1_relic_r13": (25, "fc041055f40f1a19982777666fead77636a1b7498acdf948db947a2857b90fd2"),
})


def invalid():
    return ValueError("首主题立即源石锭收藏品与完整匹配定义不一致")


class FirstThemeGoldRelics:
    def __init__(self, data):
        data.rogue_topics.topic("rogue_1")
        entries, sources = {}, {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            gold = detail["gameConst"]["goldItemId"]
            for key, (amount, expected) in SOURCES.items():
                if key not in detail["items"]:
                    continue
                source = {"item": {f: detail["items"][key][f] for f in ("id", "type", "unlockCondDesc")},
                    "effect": detail["relics"][key], "conditions": detail["relicParams"][key],
                    "archive": detail["archiveComp"]["relic"]["relic"][key], "gold": detail["items"][gold]}
                ref = data.rogue_relic_archive.entries[key]
                effect = {"id": key, "buffs": [{"key": "immediate_reward", "blackboard": [
                    {"key": "id", "value": 0.0, "valueStr": gold},
                    {"key": "count", "value": float(amount), "valueStr": None}]}]}
                if (source["item"]["id"] != key or source["item"]["type"] != "RELIC"
                        or source["gold"]["id"] != gold or source["gold"]["type"] != "GOLD"
                        or fingerprint(source) != expected or source["effect"] != effect
                        or ref.special or ref.enrollment is not None
                        or type(amount) is not int or not 0 < amount < 2**31):
                    raise invalid()
                entries[key], sources[key] = amount, expected
        except (KeyError, TypeError, AttributeError) as exc:
            raise invalid() from exc
        self.entries = MappingProxyType(entries)
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"], "sources": sources})

    def require(self, key):
        if type(key) is not str or key not in self.entries:
            raise invalid()
        return self.entries[key]


def supported(data, key):
    if key not in SOURCES:
        return False
    data.rogue_gold_relics.require(key)
    return True
