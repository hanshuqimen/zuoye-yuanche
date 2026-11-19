"""Six exact immediate squad-capacity relic effects in the frozen first theme.

Amounts, selectors, archive references and the target resource are bound to
reviewed definitions. This supplies no unlock, encounter or merchant weights.
"""

from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-immediate-squad-capacity-relics-v1"
TARGET = "rogue_1_squad_capacity"
SOURCES = MappingProxyType({
    "rogue_1_relic_a35": (1, "125c2bf3e2904bc98ea6b5caa08af3d664c06796c8e33069a6ec65b4dcb6d3a4"),
    "rogue_1_relic_a36": (1, "294e973ef2fb1f8c87a9b2bf5489beab207dcf4e3440bf5aa44490a1454eff49"),
    "rogue_1_relic_a37": (1, "6508b43b34f5212db30cd35df9bb129f8155e9aed6798151ab058297197b1573"),
    "rogue_1_relic_a38": (2, "37c39735942b6b014e65d410e10f376d164b6e7ab0a5eef6485f1e05444d7d3a"),
    "rogue_1_relic_a39": (2, "012459a20515d1c8a6e02dedf5e5a40cfc04598982f89df3aa457dc52bdd6a3c"),
    "rogue_1_relic_a40": (3, "63366813c61ea2a2a95e630c9537fc757685bd3bae758bc262cbc63e598942d3"),
})


def invalid():
    return ValueError("首主题编队上限收藏品与完整匹配定义不一致")


class FirstThemeCapacityRelics:
    def __init__(self, data):
        data.rogue_topics.topic("rogue_1")
        entries, sources = {}, {}
        try:
            detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
            for key, (amount, expected) in SOURCES.items():
                if key not in detail["items"]:
                    continue
                source = {"item": {f: detail["items"][key][f] for f in ("id", "type", "unlockCondDesc")},
                    "effect": detail["relics"][key], "conditions": detail["relicParams"][key],
                    "archive": detail["archiveComp"]["relic"]["relic"][key], "target": detail["items"][TARGET]}
                ref = data.rogue_relic_archive.entries[key]
                if (source["item"]["id"] != key or source["item"]["type"] != "RELIC"
                        or source["target"]["type"] != "SQUAD_CAPACITY" or source["target"]["id"] != TARGET
                        or detail["gameConst"]["squadCapacityItemId"] != TARGET
                        or fingerprint(source) != expected or ref.special or ref.enrollment is not None):
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

    def increase(self, key, value):
        amount = self.require(key)
        if type(value) is not int or not 0 <= value < 2**31 - amount:
            raise invalid()
        return value + amount


def supported(data, key):
    if key not in SOURCES:
        return False
    data.rogue_capacity_relics.require(key)
    return True
