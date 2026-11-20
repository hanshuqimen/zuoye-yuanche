"""Version-bound battle objectives; claiming and outcome admission are separate.

The native map arithmetic establishes a bag's current/target and the client
consumes mission states 0/1/2. Treating a carried, completed bag as a battle
objective is a local policy, not recovered official backend code. An empty
0/0 display is reported separately and never awards an objective here.
"""

from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.gamedata.crisis_v2 import CLIENT_ELF_SHA256
from terralocal.server.gamedata.crisis_v2 import CONTRACT as MAP_CONTRACT
from terralocal.server.gamedata.crisis_v2_challenges import CrisisV2ChallengeRules
from terralocal.server.gamedata.repository import fingerprint

CONTRACT = "cn-2.7.71-crisis-v2-carried-objectives-v1"


@dataclass(frozen=True)
class Treasure:
    bags: frozenset[str]
    required: int


@dataclass(frozen=True)
class ObjectiveResult:
    runes: frozenset[str]
    challenges: frozenset[str]
    packs: frozenset[str]
    treasure_progress: tuple[tuple[str, int], ...]
    empty_packs: frozenset[str]


class CrisisV2ObjectiveRules:
    def __init__(self, detail, map_rules):
        binding = fingerprint({"contract": MAP_CONTRACT, "client_elf": CLIENT_ELF_SHA256,
                               "data": map_rules.data_hash, "map_id": map_rules.map_id, "detail": detail})
        if binding != map_rules.fingerprint:
            raise ValueError("危机合约任务来源与已绑定地图不一致")
        challenges = CrisisV2ChallengeRules(detail, map_rules)
        for row in detail["bagDataMap"].values():
            if row.get("slotPackType") != "HIGHEST_TOTAL_SCORE":
                raise ValueError("危机合约符文组任务类型尚未适配")
        source = detail.get("rewardNodeDataMap")
        expected = {key for key, node in map_rules.nodes.items() if node.kind == "TREASURE"}
        if type(source) is not dict or source.keys() != expected:
            raise ValueError("危机合约奖励任务与宝藏节点不匹配")
        treasures = {}
        for key, row in source.items():
            if type(row) is not dict or row.get("slotId") != key:
                raise ValueError("危机合约奖励任务标识不一致")
            bags, required = row.get("requestBagIdList"), row.get("requestBagCnt")
            if (type(bags) is not list or any(type(v) is not str or v not in map_rules.bags for v in bags)
                    or len(bags) != len(set(bags)) or type(required) is not int or not 1 <= required <= len(bags)):
                raise ValueError("危机合约奖励任务的指标集条件无效")
            treasures[key] = Treasure(frozenset(bags), required)
        self.map_rules = map_rules
        self.challenges = challenges
        self.treasures = MappingProxyType(treasures)
        self.fingerprint = fingerprint({"contract": CONTRACT, "map_rules": map_rules.fingerprint})

    def evaluate(self, evaluation, *, cleared):
        if type(cleared) is not bool or evaluation.rules_fingerprint != self.map_rules.fingerprint:
            raise ValueError("危机合约任务需要匹配地图的明确战斗结果")
        if not cleared:
            return ObjectiveResult(frozenset(), frozenset(), frozenset(), (), frozenset())
        selected = frozenset(evaluation.rune_slots)
        completed, empty = set(), set()
        for key, bag in self.map_rules.bags.items():
            progress = evaluation.bag_progress[key]
            if not progress.complete:
                continue
            if not selected.intersection(bag.members):
                empty.add(key)
            else:
                completed.add(key)
        return ObjectiveResult(selected, self.challenges.satisfied(evaluation, cleared=True),
            frozenset(completed), tuple((key, len(rule.bags.intersection(completed)))
                for key, rule in self.treasures.items()), frozenset(empty))
