"""Regional stage placement, separate from rewards, spawn weights and unlocks.

The frozen adapter was reviewed by stage name against the regional encounter
list. Never parse a stage ID to guess a floor or treat catalog membership as
eligibility. Synthetic/custom data must provide an explicit authored policy.
"""

from types import MappingProxyType

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint

POLICY = "rogue1-regional-stage-placement-v1"
AUTHORED_POLICY = "authored-rogue-stage-placement-v1"
AUTHORED_TABLE = "terralocal_rogue_placements"
STAGES_HASH = "44f23697998353e818ff60a8a73ce69b82585093073a7f7b2b409acf73ed0bda"
ZONES_HASH = "460d8705ff0637cf86e2a601b2d6751e1ea72540d1b603428ad308df8b667a3f"
SOURCE = "https://prts.wiki/w/傀影与猩红孤钻#关卡一览"

# Explicit reviewed sets, not an ID-prefix algorithm. Emergency variants
# inherit only through the frozen table's validated linkedStageId edges.
NORMALS = {
    "zone_1": ("ro1_n_1_1", "ro1_n_1_2", "ro1_n_1_3", "ro1_n_1_4", "ro1_n_1_5"),
    "zone_2": ("ro1_n_2_1", "ro1_n_2_2", "ro1_n_2_3", "ro1_n_2_4", "ro1_n_2_5"),
    "zone_3": ("ro1_n_3_1", "ro1_n_3_2", "ro1_n_3_3", "ro1_n_3_4", "ro1_n_3_5",
               "ro1_n_3_6", "ro1_n_3_7", "ro1_n_3_8"),
    "zone_4": ("ro1_n_4_1", "ro1_n_4_2", "ro1_n_4_3", "ro1_n_4_4", "ro1_n_4_5",
               "ro1_n_4_6", "ro1_n_4_7", "ro1_n_4_8"),
    "zone_5": ("ro1_n_5_1", "ro1_n_5_2", "ro1_n_5_3", "ro1_n_5_4", "ro1_n_5_5",
               "ro1_n_5_6", "ro1_n_5_7", "ro1_n_5_8"),
    "zone_6": ("ro1_n_6_1", "ro1_n_6_2"),
}
BOSSES = {
    "zone_3": ("ro1_b_1", "ro1_b_2", "ro1_b_3", "ro1_b_4", "ro1_b_5"),
    "zone_5": ("ro1_b_6", "ro1_b_7"), "zone_6": ("ro1_b_8", "ro1_b_9"),
}
EVENTS = frozenset({"ro1_t_1", "ro1_t_2", "ro1_t_3", "ro1_t_4", "ro1_ev_1", "ro1_ev_2",
                    "ro1_ev_3", "ro1_ev_4", "ro1_ev_5"})


def invalid():
    return DomainError("ROGUE_PLACEMENT_INCOMPATIBLE", "关卡区域规则未匹配当前导入版本；未生成或修改地图", 503)


class StagePlacements:
    def __init__(self, stages, zones, portals, value):
        if (type(value) is not dict or set(value) != {"schema", "policy", "regions"}
                or type(value["schema"]) is not int or value["schema"] != 1
                or value["policy"] not in (POLICY, AUTHORED_POLICY)
                or type(value["regions"]) is not dict or set(value["regions"]) != set(stages)):
            raise invalid()
        regions = {}
        for stage, names in value["regions"].items():
            if (type(names) is not list or len(names) > len(zones)
                    or any(type(n) is not str or n not in zones or n in portals for n in names)
                    or len(set(names)) != len(names)):
                raise invalid()
            # Empty is explicit exclusion from ordinary regional pools. It
            # grants no event/boss prerequisite or successful battle response.
            regions[stage] = tuple(names)
        self.regions, self.stages = MappingProxyType(regions), MappingProxyType(dict(stages))
        self.zones = frozenset(zones) - portals
        self.policy = value["policy"]

    def require(self, stage, zone):
        if zone not in self.regions.get(stage, ()):
            raise DomainError("ROGUE_STAGE_REGION", "此作战不属于当前区域的普通节点候选；未开战或发奖", 409)

    def pool(self, zone, kind):
        if zone not in self.zones or kind not in ("BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS"):
            raise invalid()
        return tuple(sorted(k for k, v in self.regions.items() if zone in v and self.stages[k].kind == kind))


def load(data, stages, zones, portals):
    """Admit the frozen rules or explicit authored rules; no unknown fallback."""
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    frozen = (fingerprint(detail["stages"]) == STAGES_HASH and fingerprint(detail["zones"]) == ZONES_HASH)
    if frozen:
        regions = {sid: [zone] for zone, values in NORMALS.items() for sid in values}
        regions.update({sid: [zone] for zone, values in BOSSES.items() for sid in values})
        for sid, definition in stages.items():
            if definition.linked_stage is not None:
                if definition.linked_stage not in regions:
                    raise invalid()
                regions[sid] = regions[definition.linked_stage].copy()
        if set(stages) - set(regions) != EVENTS:
            raise invalid()
        regions.update({sid: [] for sid in EVENTS})
        value = {"schema": 1, "policy": POLICY, "regions": regions}
    elif AUTHORED_TABLE in data.manifest["tables"]:
        value = data.table(AUTHORED_TABLE)
        if type(value) is not dict or value.get("policy") != AUTHORED_POLICY:
            raise invalid()
    else:
        raise invalid()
    return StagePlacements(stages, zones, portals, value)
