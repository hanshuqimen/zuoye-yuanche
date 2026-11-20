"""Battle challenge conditions from version-matched Crisis V2 map data.

The first imported season has dimension-score thresholds and required-slot
counts. A caller must supply a validated clear outcome and map evaluation;
this component never unlocks nodes, claims rewards or mutates player state.
"""

import re
from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.crisis_v2 import CLIENT_ELF_SHA256
from terralocal.server.gamedata.crisis_v2 import CONTRACT as MAP_CONTRACT
from terralocal.server.gamedata.repository import fingerprint

CONTRACT = "cn-2.7.71-crisis-v2-challenges-v1"
NATURAL = re.compile(r"0|[1-9][0-9]*")


def natural(value):
    if type(value) is not str or not NATURAL.fullmatch(value) or int(value) > 2**31 - 1:
        raise ValueError("危机合约挑战参数不是有效的非负整数")
    return int(value)


@dataclass(frozen=True)
class Challenge:
    dimensions: tuple[int, ...]
    slots: frozenset[str]
    minimum: int


class CrisisV2ChallengeRules:
    def __init__(self, detail, map_rules):
        binding = fingerprint({"contract": MAP_CONTRACT, "client_elf": CLIENT_ELF_SHA256,
                               "data": map_rules.data_hash, "map_id": map_rules.map_id, "detail": detail})
        if binding != map_rules.fingerprint:
            raise ValueError("危机合约挑战来源与已绑定地图不一致")
        source = detail.get("challengeNodeDataMap")
        expected = {key for key, node in map_rules.nodes.items() if node.kind == "KEYPOINT"}
        if type(source) is not dict or source.keys() != expected:
            raise ValueError("危机合约挑战定义与关键节点不匹配")
        conditions = {}
        for key, row in source.items():
            if type(row) is not dict or row.get("slotId") != key:
                raise ValueError("危机合约挑战节点标识不一致")
            params, slots, count = row.get("missionParamList"), row.get("slotIdList"), row.get("requiredSlotCount")
            if (type(params) is not list or len(params) != 2 or any(type(v) is not str for v in params)
                    or type(slots) is not list or any(type(v) is not str or not v for v in slots)
                    or len(slots) != len(set(slots)) or type(count) is not int or count < 0):
                raise ValueError("危机合约挑战条件字段不完整")
            minimum = natural(params[1])
            kind = row.get("missionType")
            if kind == "PassWithDimScore":
                dimensions = tuple(natural(v) for v in params[0].split(";"))
                if (slots or count or len(set(dimensions)) != len(dimensions)
                        or any(v >= 6 for v in dimensions)):
                    raise ValueError("危机合约维度评分条件不一致")
                condition = Challenge(dimensions, frozenset(), minimum)
            elif kind == "PassWithRunes":
                declared = params[0].split(";") if params[0] else []
                if (declared != slots or count != minimum or minimum > len(slots)
                        or any(v not in map_rules.nodes or map_rules.nodes[v].kind != "NORMAL" for v in slots)):
                    raise ValueError("危机合约符文条件与槽位引用不一致")
                condition = Challenge((), frozenset(slots), minimum)
            else:
                raise ValueError("尚未支持此危机合约挑战条件，未接纳战斗")
            conditions[key] = condition
        self.conditions = MappingProxyType(conditions)
        self.map_rules_fingerprint = map_rules.fingerprint
        self.fingerprint = fingerprint({"contract": CONTRACT, "map_rules": map_rules.fingerprint, "source": source})

    def satisfied(self, evaluation, *, cleared):
        if type(cleared) is not bool or evaluation.rules_fingerprint != self.map_rules_fingerprint:
            raise ValueError("危机合约挑战需要匹配地图的战斗结果")
        if not cleared:
            return frozenset()
        selected = frozenset(evaluation.rune_slots)
        return frozenset(key for key, rule in self.conditions.items() if (
            sum(evaluation.dimension_scores[v] for v in rule.dimensions)
            if rule.dimensions else len(selected & rule.slots)) >= rule.minimum)
