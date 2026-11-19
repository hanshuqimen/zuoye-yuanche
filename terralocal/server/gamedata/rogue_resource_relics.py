"""Matched gold-dependent attack speed; the owned client recalculates layers.

M84565 calls M84566 at construction, dividing the current resource by the
blackboard step (bounded below by one). M84866 passes that layer to the shared
attribute-add path. Inventory layer is a base input, not a stored gold counter.
This catalog admits complete effects, never eligibility or natural supply.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-gold-layer-attack-speed-relics-v1"
SOURCES = MappingProxyType({
    "rogue_1_relic_q26": (3, "47e1c502c0e2e970afb5df4652740c8f7a63c6da0ca22eb639ad5f92ad227ffd"),
    "rogue_1_relic_q27": (5, "0db12b837ce35c37fc287c8116e13cf908c1da800d24f6a9995e3f37808aa5ea"),
    "rogue_1_relic_q28": (7, "6e2ec298bfbcc6d5b03026e4a0f3759e40b72414b080bb81bd840fe5c307ae40"),
})


def invalid():
    return ValueError("首主题源石锭分层攻速收藏品与完整匹配定义不一致")


@dataclass(frozen=True)
class ResourceAttackSpeed:
    per_layer: int
    step: int = 5

    def layers(self, gold):
        """Diagnostic counterpart of the reviewed native nonnegative branch.

        Not a permanent operator stat or a value to persist into inventory.
        """
        if type(gold) is not int or not 0 <= gold < 2**31:
            raise invalid()
        return gold // self.step


class FirstThemeResourceRelics:
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
                effect = {"id": key, "buffs": [{"key": "layer_char_attribute_add", "blackboard": [
                    {"key": "attack_speed", "value": float(amount), "valueStr": None},
                    {"key": "stack_by_res", "value": 0.0, "valueStr": gold},
                    {"key": "stack_by_res_cnt", "value": 5.0, "valueStr": None}]}]}
                if (source["item"]["id"] != key or source["item"]["type"] != "RELIC"
                        or source["gold"]["id"] != gold or source["gold"]["type"] != "GOLD"
                        or fingerprint(source) != expected or source["effect"] != effect
                        or type(amount) is not int or amount not in (3, 5, 7)
                        or ref.special or ref.enrollment is not None):
                    raise invalid()
                entries[key], sources[key] = ResourceAttackSpeed(amount), expected
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
    data.rogue_resource_relics.require(key)
    return True
