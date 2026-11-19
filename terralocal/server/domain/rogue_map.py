"""Deterministic, bounded layered graphs from explicit first-theme plans.

This is a generation/codec component, not an official map distribution or an
activation shortcut. Runtime consumes only saved, validated plans through the
map transaction driver. Plans must supply all pools and weights, and their
regional battle candidates must pass the placement adapter.
"""

import hashlib
import random
from dataclasses import asdict, dataclass

from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.roguelike import invalid

LEGACY_POLICY = "rogue-layered-map-v1"
POLICY = "rogue-layered-map-v2"
DISTINCT_POLICY = "rogue-layered-map-v3"
POLICIES = frozenset({LEGACY_POLICY, POLICY, DISTINCT_POLICY})
# Local admission budgets, not claims about every game's coordinate limits.
MAX_DEPTH, MAX_WIDTH, MAX_POOL = 32, 8, 512


@dataclass(frozen=True, order=True)
class Point:
    x: int
    y: int

    @property
    def key(self):
        # Frozen M33652 GetNodeKeyByPos(depth,index), default branch.
        return str(self.x * 1000 + self.y)

    @property
    def legacy_key(self):
        return str(self.x * 100 + self.y)

    def validate(self):
        if type(self.x) is not int or type(self.y) is not int or not (
                0 <= self.x < MAX_DEPTH and 0 <= self.y < MAX_WIDTH):
            raise invalid("地图坐标超过已接纳的普通层图预算")

    def wire(self):
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class Entry:
    kind: str
    weight: int
    stage: str | None = None


@dataclass(frozen=True)
class Column:
    minimum: int
    maximum: int
    pool: tuple[Entry, ...]


@dataclass(frozen=True)
class Plan:
    zone_id: str
    columns: tuple[Column, ...]
    extra_edge_chance: int

    def validate(self, catalog):
        catalog.require_zone(self.zone_id)
        if type(self.columns) is not tuple or not 1 <= len(self.columns) <= MAX_DEPTH:
            raise invalid("地图方案必须明确给出有界列序列")
        if type(self.extra_edge_chance) is not int or not 0 <= self.extra_edge_chance <= 10000:
            raise invalid("额外连线概率必须为明确的万分比整数")
        for col in self.columns:
            if (not isinstance(col, Column) or type(col.minimum) is not int or type(col.maximum) is not int
                    or not 1 <= col.minimum <= col.maximum <= MAX_WIDTH):
                raise invalid("地图方案列宽非法")
            if type(col.pool) is not tuple or not 1 <= len(col.pool) <= MAX_POOL:
                raise invalid("地图方案必须明确给出非空候选池")
            seen, total = set(), 0
            for entry in col.pool:
                if not isinstance(entry, Entry) or type(entry.weight) is not int or not 1 <= entry.weight <= 1_000_000:
                    raise invalid("地图候选权重必须为明确正整数")
                catalog.require_placement(entry.kind, entry.stage, self.zone_id)
                key = entry.kind, entry.stage
                if key in seen:
                    raise invalid("地图池包含重复候选，不能隐式重复加权")
                seen.add(key)
                total += entry.weight
            if total > 2**31 - 1:
                raise invalid("地图候选总权重超过预算")


@dataclass(frozen=True)
class Node:
    pos: Point
    kind: str
    stage: str | None
    next: tuple[Point, ...]
    finished_at: int = 0

    def wire(self):
        return {"pos": self.pos.wire(), "next": [p.wire() | {"hidden": "SHOW", "key": False} for p in self.next],
                "type": self.kind, "nodeDisplaySubType": 0, "fts": self.finished_at,
                "realContent": None, "attach": [], "shop": None, "scenes": None, "stage": self.stage,
                "visibility": "NORMAL", "refresh": None}


@dataclass(frozen=True)
class Zone:
    id: str
    nodes: tuple[Node, ...]

    def validate(self, catalog):
        catalog.require_zone(self.id)
        if type(self.nodes) is not tuple or not 1 <= len(self.nodes) <= MAX_DEPTH * MAX_WIDTH:
            raise invalid("地图必须包含有界节点序列")
        by_pos, columns = {}, {}
        for node in self.nodes:
            if not isinstance(node, Node) or not isinstance(node.pos, Point):
                raise invalid("地图节点结构非法")
            node.pos.validate()
            catalog.require_placement(node.kind, node.stage, self.id)
            if (type(node.finished_at) is not int or not 0 <= node.finished_at <= 2**63 - 1
                    or type(node.next) is not tuple or node.pos in by_pos):
                raise invalid("地图节点时间、坐标唯一性或连线结构非法")
            by_pos[node.pos] = node
            columns.setdefault(node.pos.x, []).append(node.pos.y)
        if set(columns) != set(range(max(columns) + 1)):
            raise invalid("普通层图有空列，未形成连续路线")
        for ys in columns.values():
            if sorted(ys) != list(range(len(ys))):
                raise invalid("普通层图的同行索引必须从0连续")
        incoming = set()
        for node in self.nodes:
            if any(not isinstance(target, Point) for target in node.next):
                raise invalid("地图连线坐标类型非法")
            for target in node.next:
                target.validate()
            if len(set(node.next)) != len(node.next):
                raise invalid("地图存在重复连线")
            if bool(node.next) != (node.pos.x < max(columns)):
                raise invalid("地图存在提前断路或出口继续连线")
            for target in node.next:
                if not isinstance(target, Point) or target not in by_pos or target.x != node.pos.x + 1:
                    raise invalid("普通层图连线必须指向实际存在的下一列")
                incoming.add(target)
        if any(p.x > 0 and p not in incoming for p in by_pos):
            raise invalid("地图有不可达节点")
        # With strictly forward edges, inbound/outbound coverage also proves
        # every root reaches an exit and every node lies on a complete route.
        for x in range(max(columns)):
            edges = [(n.pos.y, t.y) for n in self.nodes if n.pos.x == x for t in n.next]
            if any(a < b and c > d for a, c in edges for b, d in edges):
                raise invalid("普通层图包含交叉连线")

    def wire(self, *, legacy_keys=False):
        return {"id": self.id, "nodes": {
            n.pos.legacy_key if legacy_keys else n.pos.key: n.wire() for n in sorted(self.nodes, key=lambda n: n.pos)},
                "variation": [], "zoneType": "NORMAL"}

    def successors(self, pos: Point | None):
        """Geometry only; ticket/events/battle completion must be checked by the caller."""
        if pos is None:
            return tuple(n.pos for n in self.nodes if n.pos.x == 0)
        node = next((n for n in self.nodes if n.pos == pos), None)
        if node is None:
            raise invalid("当前位置不在地图中")
        return node.next


def _choose(rng, pool):
    roll = rng.randrange(sum(entry.weight for entry in pool))
    for entry in pool:
        if roll < entry.weight:
            return entry
        roll -= entry.weight
    raise AssertionError("Positive integer pool did not select an entry")


def _rank(i, source_width, target_width):
    return 0 if source_width == 1 else (
        i * (target_width - 1) * 2 + source_width - 1) // (2 * (source_width - 1))


def generate(data, plan: Plan, seed: int, *, policy=POLICY) -> Zone:
    catalog = data.rogue_map
    catalog.require_seed(seed)
    plan.validate(catalog)
    if policy not in POLICIES:
        raise invalid("地图生成策略版本未接纳")
    material = canonical({"policy": policy, "data": data.manifest["hash"], "plan": asdict(plan), "seed": seed})
    rng = random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))
    columns = []
    for x, col in enumerate(plan.columns):
        width = rng.randint(col.minimum, col.maximum)
        if policy != DISTINCT_POLICY:
            columns.append([Node(Point(x, y), entry.kind, entry.stage, ())
                            for y in range(width) for entry in [_choose(rng, col.pool)]])
            continue
        # A new policy only: preserve every historical v1/v2 RNG draw/hash.
        # Scene categories may repeat; a concrete battle cannot repeat in the
        # same column. Exhaustion is a configuration error, never a reroll.
        column, used = [], set()
        for y in range(width):
            pool = tuple(e for e in col.pool if e.stage is None or (e.kind, e.stage) not in used)
            if not pool:
                raise invalid("同列不重复战斗的候选不足；未发布地图")
            entry = _choose(rng, pool)
            column.append(Node(Point(x, y), entry.kind, entry.stage, ()))
            if entry.stage is not None:
                used.add((entry.kind, entry.stage))
        columns.append(column)
    edges = {}
    for left, right in zip(columns, columns[1:]):
        # Nearest normalized ranks preserve order. Cover both sides so neither
        # disappearing branches nor unreachable new branches can be emitted.
        pairs = {(i, _rank(i, len(left), len(right))) for i in range(len(left))}
        pairs.update((_rank(j, len(right), len(left)), j) for j in range(len(right)))
        optional = [(i, j) for i in range(len(left)) for j in range(len(right)) if (i, j) not in pairs]
        rng.shuffle(optional)
        for i, j in optional:
            if rng.randrange(10000) < plan.extra_edge_chance and not any(
                    (i - a) * (j - b) < 0 for a, b in pairs):
                pairs.add((i, j))
        for i, node in enumerate(left):
            edges[node.pos] = tuple(right[j].pos for a, j in sorted(pairs) if a == i)
    result = Zone(plan.zone_id, tuple(Node(n.pos, n.kind, n.stage, edges.get(n.pos, ()))
                                     for column in columns for n in column))
    result.validate(catalog)
    return result


def plan_fingerprint(plan: Plan, *, policy=POLICY):
    if policy not in POLICIES:
        raise invalid("地图方案策略版本未接纳")
    return fingerprint({"policy": policy, "plan": asdict(plan)})


def admit_plan(catalog, value: dict) -> Plan:
    """Read the complete saved recipe; never default missing pools or weights."""
    try:
        if (type(value) is not dict or set(value) != {"zone_id", "columns", "extra_edge_chance"}
                or type(value["columns"]) is not list or not 1 <= len(value["columns"]) <= MAX_DEPTH):
            raise invalid("保存的地图方案结构不匹配")
        columns = []
        for col in value["columns"]:
            if (type(col) is not dict or set(col) != {"minimum", "maximum", "pool"}
                    or type(col["pool"]) is not list or not 1 <= len(col["pool"]) <= MAX_POOL):
                raise invalid("保存的地图列结构不匹配")
            entries = []
            for entry in col["pool"]:
                if type(entry) is not dict or set(entry) != {"kind", "weight", "stage"}:
                    raise invalid("保存的地图候选结构不匹配")
                entries.append(Entry(**entry))
            columns.append(Column(col["minimum"], col["maximum"], tuple(entries)))
        plan = Plan(value["zone_id"], tuple(columns), value["extra_edge_chance"])
        plan.validate(catalog)
        if canonical(asdict(plan)) != canonical(value):
            raise invalid("保存的地图方案不能无损回读")
        return plan
    except (KeyError, TypeError, ValueError) as exc:
        raise invalid("保存的地图方案无法完整读取") from exc


def admit_wire(catalog, value: dict, *, legacy_keys=False) -> Zone:
    """Read only the admitted ordinary graph shape; never erase unknown contents."""
    if (not isinstance(value, dict) or set(value) != {"id", "nodes", "variation", "zoneType"}
            or value["variation"] != [] or value["zoneType"] != "NORMAL" or not isinstance(value["nodes"], dict)
            or not 1 <= len(value["nodes"]) <= MAX_DEPTH * MAX_WIDTH):
        raise invalid("普通区域地图结构或未接纳的变体不匹配")
    nodes = []
    try:
        for key, raw in value["nodes"].items():
            if (not isinstance(raw, dict) or not isinstance(raw.get("pos"), dict)
                    or set(raw["pos"]) != {"x", "y"} or type(raw.get("next")) is not list
                    or len(raw["next"]) > MAX_WIDTH):
                raise invalid("地图节点坐标或连线结构非法")
            pos = Point(**raw["pos"])
            pos.validate()
            if key != (pos.legacy_key if legacy_keys else pos.key):
                raise invalid("节点键与当前坐标适配不符")
            targets = []
            for edge in raw["next"]:
                if (not isinstance(edge, dict) or set(edge) != {"x", "y", "hidden", "key"}
                        or edge["hidden"] != "SHOW" or edge["key"] is not False):
                    raise invalid("普通层图含未接纳的隐藏/钥匙连线")
                target = Point(edge["x"], edge["y"])
                target.validate()
                targets.append(target)
            node = Node(pos, raw["type"], raw["stage"], tuple(targets), raw["fts"])
            if canonical(node.wire()) != canonical(raw):
                raise invalid("节点字段类型或未接纳内容不匹配")
            nodes.append(node)
        result = Zone(value["id"], tuple(sorted(nodes, key=lambda n: n.pos)))
        result.validate(catalog)
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise invalid("普通区域地图无法完整读取") from exc
