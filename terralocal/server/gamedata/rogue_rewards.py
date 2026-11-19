"""IS2 base reward adapter, explicitly separate from official drop tables.

Amounts are the unboosted regional/event values documented by PRTS, not a
server fixture. Stage membership, variant links and zones are checked against
the imported client data; regional ordinary placement is checked separately.
This does not establish encounter rates, unlocks, random loot weights, elite
relics, outer buffs, difficulty modifiers or boss endings.
"""

from dataclasses import dataclass

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-base-rewards-prts-v1"
SOURCE = "https://prts.wiki/w/傀影与猩红孤钻#区域"
# None means absent evidence, never a zero-reward fallback.
REGIONS = {
    "zone_1": ((10, 3), (12, 4), None),
    "zone_2": ((12, 3), (18, 4), None),
    "zone_3": ((16, 3), (24, 5), (32, 6)),
    "zone_4": ((20, 4), (30, 5), None),
    "zone_5": ((25, 4), (38, 6), (50, 7)),
    "zone_6": ((25, 4), (45, 6), None),
}
EVENTS = {
    "ro1_t_1": (3, 1), "ro1_t_2": (6, 2), "ro1_t_3": (7, 3), "ro1_t_4": (9, 5),
    "ro1_ev_1": (40, 10), "ro1_ev_2": (24, 5), "ro1_ev_3": (32, 7),
    "ro1_ev_4": (24, 5), "ro1_ev_5": (32, 7),
}


@dataclass(frozen=True)
class BaseReward:
    exp: int
    gold: int
    rule_hash: str


class FirstThemeBattleRewards:
    def __init__(self, data):
        self.maps, self.data_hash = data.rogue_map, data.manifest["hash"]

    def base(self, *, topic, mode, grade, zone, kind, stage, event=None):
        if topic != "rogue_1" or mode != "NORMAL" or type(grade) is not int or grade != 0:
            raise DomainError("ROGUE_REWARD_MODE", "此奖励适配只接纳傀影普通难度0级基础奖励", 501)
        self.maps.require_zone(zone)
        self.maps.require_node(kind, stage)
        definition = self.maps.stages[stage]
        if event is None:
            self.maps.placements.require(stage, zone)
        if event is not None:
            # An event must explicitly name the same special battle. A null
            # specialNodeId or a normal-looking prefix proves no such context.
            amount = EVENTS.get(stage) if event == stage else None
            if definition.kind != "BATTLE_NORMAL":
                amount = None
        elif stage in self.maps.emergency_variants or definition.kind in ("BATTLE_ELITE", "BATTLE_BOSS"):
            row = REGIONS.get(zone)
            amount = row[("BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS").index(kind)] if row else None
        else:
            amount = None
        if amount is None:
            raise DomainError("ROGUE_REWARD_CONTEXT", "此区域、事件及作战组合的奖励依据未接通", 501)
        digest = fingerprint({"policy": POLICY, "data": self.data_hash, "topic": topic, "mode": mode,
            "grade": grade, "zone": zone, "kind": kind, "stage": stage, "event": event,
            "level": definition.level_id, "exp": amount[0], "gold": amount[1]})
        return BaseReward(*amount, digest)
