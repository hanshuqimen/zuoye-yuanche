"""Ten complete scalar-currency relic effects, independent of natural supply.

Mixed HP, upgrade-ticket and battle-effect rewards remain separate contracts.
The vector is a server-authored consequence, never a client-supplied amount.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-immediate-scalar-currency-relics-v1"
CONSTANTS = MappingProxyType({"goldItemId": "rogue_1_gold", "populationItemId": "rogue_1_population",
                             "squadCapacityItemId": "rogue_1_squad_capacity"})


@dataclass(frozen=True)
class CurrencyGain:
    gold: int
    hope: int
    capacity: int


SOURCES = MappingProxyType({
    "rogue_1_relic_m17": (CurrencyGain(11, 3, 0), "5b5e78f421c856dfdc8ce7087016c1474b2cf6891d91719c8d19f66e81563a36"),
    "rogue_1_relic_q01": (CurrencyGain(0, 2, 1), "17a22c5f54ae939c189aa9a45d3bf4605383a79aba716ba1889c7ae740e408f3"),
    "rogue_1_relic_q03": (CurrencyGain(0, 4, 1), "0216b8f40f2b5c40e9b2d6579087d5cb11ca451cf4b1781cee062cfd249adefe"),
    "rogue_1_relic_q04": (CurrencyGain(0, 4, 1), "92e6982495020e95bf5463a3dfe9b6abc30e038b4d19abaf824f8b66f0fa988b"),
    "rogue_1_relic_q06": (CurrencyGain(0, 6, 2), "9682ed2cd967b4178bf346d07ada4b3e15dbf5cf69a974fe88f9e409eee2e0e7"),
    "rogue_1_relic_r06": (CurrencyGain(0, 4, 0), "09223b0f442f8dc64a5967e7d6735051969f4916fc5be5560db73c2d82d569e7"),
    "rogue_1_relic_r07": (CurrencyGain(0, 4, 0), "ed79d9714b2c219d6c20e0603a0e4b4a5ce02dc2a7265b65bf0f82db6bd2d142"),
    "rogue_1_relic_r08": (CurrencyGain(0, 4, 0), "a58637998fd71d03bbc47676905a27e37f071807cff8ac4b4147c434661311ed"),
    "rogue_1_relic_r09": (CurrencyGain(0, 6, 0), "ed71a633ac3f2959798b822396ab92dd13d7de321a678093d851b596d6627575"),
    "rogue_1_relic_r10": (CurrencyGain(0, 8, 0), "3e7e882c23645313ccbc43aa76c2ecf8eb3408b53c158d3bd8d3ac5172acf660"),
})


def invalid():
    return ValueError("首主题即时资源收藏品与完整匹配定义不一致")


def increase(value, amount):
    if (type(value) is not int or type(amount) is not int
            or not 0 <= value < 2**31 or not 0 <= amount < 2**31 or value + amount >= 2**31):
        raise ValueError("即时资源奖励超出客户端整数范围")
    return value + amount


class FirstThemeCurrencyRelics:
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
                amounts = dict.fromkeys(CONSTANTS.values(), 0)
                for buff in source["effect"]["buffs"]:
                    target, amount = buff["blackboard"][0]["valueStr"], buff["blackboard"][1]["value"]
                    if target not in amounts or type(amount) is not float or not amount.is_integer() or amount <= 0:
                        raise invalid()
                    amounts[target] += int(amount)
                actual = CurrencyGain(*(amounts[target] for target in CONSTANTS.values()))
                if actual != gain:
                    raise invalid()
                entries[key], sources[key] = gain, expected
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise invalid() from exc
        self.entries = MappingProxyType(entries)
        self.fingerprint = fingerprint({"policy": POLICY, "data": data.manifest["hash"], "sources": sources,
                                        "archive": data.rogue_relic_archive.fingerprint,
                                        "gains": {key: (v.gold, v.hope, v.capacity) for key, v in entries.items()}})

    def require(self, key):
        if type(key) is not str or key not in self.entries:
            raise invalid()
        return self.entries[key]


def supported(data, key):
    if type(key) is not str or key not in SOURCES:
        return False
    data.rogue_currency_relics.require(key)
    return True
