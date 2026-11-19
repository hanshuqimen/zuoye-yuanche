"""Versioned explicit floor recipes, not official floor supply or progression.

All floors are persisted together. The first retains the admitted v2 map seed;
later floors have an index/data/recipe-bound seed, independent of other floors.
No cursor, transition entitlement, event completion or reward is granted here.
"""

from dataclasses import asdict, dataclass

from terralocal.server.domain.rogue_map import (
    Plan,
    admit_plan,
    admit_wire,
    generate,
)
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.roguelike import invalid

POLICY = "rogue-explicit-floor-sequence-v1"
CONTENT_POLICY = "rogue-normal-content-floors-v1"
FLOOR_POLICIES = frozenset({POLICY, CONTENT_POLICY})
MAP_POLICY = "rogue-layered-map-v2"  # Pinned; a future default must not rehash old sequences.
MAX_FLOORS, MAX_POOL_ENTRIES = 16, 4096  # Local storage budgets, not official limits.


@dataclass(frozen=True)
class FloorSequence:
    floors: tuple[Plan, ...]

    def validate(self, catalog):
        if (type(self.floors) is not tuple or not 1 <= len(self.floors) <= MAX_FLOORS
                or any(not isinstance(p, Plan) for p in self.floors)):
            raise invalid("多层方案必须明确给出有界的完整楼层序列")
        if self.floors[0].zone_id != "zone_1":
            raise invalid("首主题多层方案须从已接纳的首层区域开始")
        count = 0
        for plan in self.floors:
            plan.validate(catalog)
            count += sum(len(c.pool) for c in plan.columns)
        if count > MAX_POOL_ENTRIES:
            raise invalid("多层方案候选总量超过本地保存预算")

    def saved(self):
        return {"floors": [asdict(p) for p in self.floors]}


def plan_hash(spec):
    return fingerprint({"policy": POLICY, "map_policy": MAP_POLICY, "plan": spec.saved()})


def admit_sequence(catalog, value):
    if (type(value) is not dict or set(value) != {"floors"} or type(value["floors"]) is not list
            or not 1 <= len(value["floors"]) <= MAX_FLOORS):
        raise invalid("保存的多层方案结构不匹配")
    spec = FloorSequence(tuple(admit_plan(catalog, p) for p in value["floors"]))
    spec.validate(catalog)
    if canonical(spec.saved()) != canonical(value):
        raise invalid("保存的多层方案不能无损回读")
    return spec


def floor_seed(data, plan, seed, index, *, map_policy=MAP_POLICY):
    """Keep floor1 unchanged; bind later seeds to their own position and recipe."""
    if type(index) is not int or not 1 <= index <= MAX_FLOORS:
        raise invalid("楼层索引超过已接纳范围")
    data.rogue_map.require_seed(seed)
    if index == 1:
        return seed
    return int(fingerprint({"policy": POLICY, "map_policy": map_policy,
        "data": data.manifest["hash"], "seed": seed, "index": index, "plan": asdict(plan)})[:16], 16) % 2**63


def generate_sequence(data, spec, seed, *, map_policy=MAP_POLICY):
    spec.validate(data.rogue_map)
    data.rogue_map.require_seed(seed)
    return tuple(generate(data, p, floor_seed(data, p, seed, i, map_policy=map_policy), policy=map_policy)
                 for i, p in enumerate(spec.floors, 1))


def saved_graphs(zones):
    return {"zones": {str(i): zone.wire() for i, zone in enumerate(zones, 1)}}


def validate_graphs(data, spec, seed, value):
    if (type(value) is not dict or set(value) != {"zones"} or type(value["zones"]) is not dict
            or set(value["zones"]) != {str(i) for i in range(1, len(spec.floors) + 1)}):
        raise invalid("保存的楼层图索引不连续或不匹配")
    actual = tuple(admit_wire(data.rogue_map, value["zones"][str(i)])
                   for i in range(1, len(spec.floors) + 1))
    expected = generate_sequence(data, spec, seed)
    if canonical(saved_graphs(actual)) != canonical(saved_graphs(expected)):
        raise invalid("保存的楼层图与完整方案、索引或种子不匹配")
    return actual
