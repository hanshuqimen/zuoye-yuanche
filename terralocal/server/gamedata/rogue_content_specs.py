"""Owned full-run recipes, distinct from unavailable official spawn weights.

This compiler does not activate runs or supply a default. Every pool, price,
eligibility set and weight is an explicit trusted server input. Its immutable
result can be persisted and consumed by the run transaction orchestrator.
"""

import json
import random
from dataclasses import dataclass
from types import MappingProxyType

from terralocal.server.domain.rogue_floors import admit_sequence, generate_sequence
from terralocal.server.domain.rogue_map import Point
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_battle_loot import RelicGroups, compile_groups
from terralocal.server.gamedata.rogue_recreation import Recreation, compile_recreation
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.gamedata.rogue_treasures import Treasure, compile_treasure

POLICY = "rogue1-explicit-normal-content-spec-v1"
TREASURE_POLICY = "rogue1-explicit-normal-content-spec-v2"
RECREATION_POLICY = "rogue1-explicit-normal-content-spec-v3"
CAPSULE_POLICY = "rogue1-explicit-normal-content-spec-v4"
BASE_REWARD_POLICY = "rogue1-explicit-normal-content-spec-v5"
TYPED_POLICY = "rogue1-explicit-normal-content-spec-v6"
ROLES = ("incident", "rest", "shop", "battle")
KINDS = {"INCIDENT": "incident", "REST": "rest", "SHOP": "shop",
         "BATTLE_NORMAL": "battle", "BATTLE_ELITE": "battle", "BATTLE_BOSS": "battle", "TREASURE": "treasure",
         "ENTERTAINMENT": "recreation"}
MAX_POOL, MAX_SOURCE_BYTES = 64, 1_048_576


def invalid():
    return ValueError("普通探索内容方案缺少完整、匹配且有界的显式规则")


def exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise invalid()


def evidence(value):
    if type(value) is not str or not 1 <= len(value) <= 1024:
        raise invalid()
    return value


@dataclass(frozen=True)
class Candidate:
    id: str
    weight: int
    source: bytes
    proof: str
    reservations: frozenset[str]
    visit: Treasure | Recreation | None = None
    base_only: bool = False
    battle_kinds: frozenset[str] | None = None

    def supports(self, kind):
        return ((not self.base_only or kind == "BATTLE_NORMAL")
                and (self.battle_kinds is None or kind in self.battle_kinds))


@dataclass(frozen=True)
class ContentSpec:
    data_hash: str
    at: int
    source: bytes
    digest: str
    sequence: object
    pools: tuple
    policy: str = POLICY

    def generate(self, data, seed):
        if data.manifest["hash"] != self.data_hash:
            raise invalid()
        if self.policy == TYPED_POLICY:
            from terralocal.server.domain.rogue_map import DISTINCT_POLICY

            return generate_sequence(data, self.sequence, seed, map_policy=DISTINCT_POLICY)
        return generate_sequence(data, self.sequence, seed)

    def choose(self, zone_index, kind, point, seed, *, reserved=frozenset()):
        """Independent node RNG; callers bind coordinates to their saved map."""
        if (type(zone_index) is not int or not 1 <= zone_index <= 5 or type(point) is not Point
                or type(seed) is not int or not 0 <= seed < 2**63 or type(kind) is not str or kind not in KINDS):
            raise invalid()
        point.validate()
        if type(reserved) is not frozenset or any(type(key) is not str for key in reserved):
            raise invalid()
        if zone_index == 5 and kind == "BATTLE_BOSS":
            return None  # Existing default-ending transaction owns final rewards.
        role = KINDS[kind]
        pool = tuple(entry for entry in self.pools[zone_index - 1].get(role, ())
                     if entry.supports(kind) and not entry.reservations & reserved)
        if not pool:
            raise invalid()
        identity = {"policy": self.policy, "spec": self.digest, "seed": seed,
                    "zone": zone_index, "point": [point.x, point.y], "role": role}
        if reserved:
            identity["reserved"] = sorted(reserved)
        rng = random.Random(int(fingerprint(identity), 16))
        roll = rng.randrange(sum(entry.weight for entry in pool))
        for entry in pool:
            if roll < entry.weight:
                return entry
            roll -= entry.weight
        raise invalid()


def quote(data, value):
    exact(value, ("id", "evidence", "offers"))
    if type(value["offers"]) is not list or not 1 <= len(value["offers"]) <= 32:
        raise invalid()
    offers = []
    for row in value["offers"]:
        if (type(row) is not dict or not {"index", "item_id", "price"} <= set(row)
                or set(row) - {"index", "item_id", "price", "elite_pool", "direct_pool", "relic_layer"}):
            raise invalid()
        for name in ("elite_pool", "direct_pool"):
            if name in row and (type(row[name]) is not list or any(type(x) is not str for x in row[name])):
                raise invalid()
        offers.append(Offer(row["index"], row["item_id"], row["price"],
            tuple(row.get("elite_pool", ())), tuple(row.get("direct_pool", ())), row.get("relic_layer")))
    return compile_shop(data, value["id"], tuple(offers), evidence=evidence(value["evidence"]))


def candidate(data, role, value, at, *, capsules=False, base_rewards=False, typed_battles=False):
    exact(value, ("id", "weight", "content"))
    from terralocal.server.gamedata.roguelike import identifier

    identifier(value["id"], "内容候选")
    if type(value["weight"]) is not int or not 1 <= value["weight"] <= 1_000_000:
        raise invalid()
    content = value["content"]
    reservations = frozenset()
    visit = None
    base_only = False
    battle_kinds = None
    if role in ("incident", "rest"):
        from terralocal.server.domain.rogue_visits import REST_PROGRAMS, program_for

        exact(content, ("program",))
        if type(content["program"]) is not str or (content["program"] in REST_PROGRAMS) != (role == "rest"):
            raise invalid()
        program = program_for(data, content["program"])
        if program is None or program.data_hash != data.manifest["hash"]:
            raise invalid()
        proof = program.digest
        from terralocal.server.gamedata.rogue_relic_events import RELICS

        reservations = frozenset(item for (key, _), item in RELICS.items() if key == content["program"])
    elif role == "shop":
        shop = quote(data, content)
        proof = shop.digest
        reservations = frozenset(o.item_id for o in shop.offers.values() if o.relic_layer is not None)
    elif role in ("treasure", "recreation"):
        compile_visit = compile_treasure if role == "treasure" else compile_recreation
        visit = compile_visit(data, content, at=at)
        proof, reservations = visit.program.digest, visit.reservations
    else:
        exact(content, {"groups", "eligibility", "evidence"} | ({"capsule"} if capsules and "capsule" in content else set())
              | ({"base_only"} if base_rewards and "base_only" in content else set())
              | ({"kinds"} if typed_battles else set()))
        if typed_battles:
            kinds = content["kinds"]
            if (type(kinds) is not list or not 1 <= len(kinds) <= 3
                    or any(type(k) is not str or k not in ("BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS") for k in kinds)
                    or len(set(kinds)) != len(kinds)):
                raise invalid()
            battle_kinds = frozenset(kinds)
        if "base_only" in content and content["base_only"] is not True:
            raise invalid()
        base_only = content.get("base_only", False)
        if base_only and battle_kinds is not None and battle_kinds != {"BATTLE_NORMAL"}:
            raise invalid()
        if (type(content["groups"]) is not list or any(type(g) is not list for g in content["groups"])
                or type(content["eligibility"]) is not list or any(type(k) is not str for k in content["eligibility"])
                or len(set(content["eligibility"])) != len(content["eligibility"])):
            raise invalid()
        _, proof = compile_groups(data, RelicGroups(tuple(tuple(g) for g in content["groups"]),
            frozenset(content["eligibility"]), evidence(content["evidence"]), content.get("capsule"), base_only), at=at)
        reservations = frozenset(key for group in content["groups"] for key in group)
    return Candidate(value["id"], value["weight"], canonical(content), proof, reservations, visit, base_only, battle_kinds)


def compile_spec(data, value, *, at):
    exact(value, ("schema", "policy", "theme", "mode", "grade", "gamedata_hash", "evidence", "floors", "supplies"))
    if (type(value["schema"]) is not int or value["schema"] != 1
            or type(value["policy"]) is not str or value["policy"] not in (
                POLICY, TREASURE_POLICY, RECREATION_POLICY, CAPSULE_POLICY, BASE_REWARD_POLICY, TYPED_POLICY)
            or value["theme"] != "rogue_1" or value["mode"] != "NORMAL"
            or type(value["grade"]) is not int or value["grade"] != 0
            or value["gamedata_hash"] != data.manifest["hash"] or type(at) is not int or not 0 <= at < 2**63):
        raise invalid()
    evidence(value["evidence"])
    source = canonical(value)
    if len(source) > MAX_SOURCE_BYTES:
        raise invalid()
    data.rogue_topics.topic("rogue_1", at=at)
    sequence = admit_sequence(data.rogue_map, {"floors": value["floors"]})
    if (tuple(p.zone_id for p in sequence.floors) != tuple("zone_" + str(i) for i in range(1, 6))
            or type(value["supplies"]) is not list or len(value["supplies"]) != 5):
        raise invalid()
    pools, proofs = [], []
    roles = ROLES
    if value["policy"] in (TREASURE_POLICY, RECREATION_POLICY, CAPSULE_POLICY, BASE_REWARD_POLICY, TYPED_POLICY):
        roles += ("treasure",)
    if value["policy"] in (RECREATION_POLICY, CAPSULE_POLICY, BASE_REWARD_POLICY, TYPED_POLICY):
        roles += ("recreation",)
    for number, (plan, supply) in enumerate(zip(sequence.floors, value["supplies"], strict=True), 1):
        exact(supply, roles)
        needed, needed_kinds = set(), set()
        for x, column in enumerate(plan.columns):
            for entry in column.pool:
                if entry.kind not in KINDS or KINDS[entry.kind] not in roles:
                    raise invalid()  # Do not publish buttons whose content driver is absent.
                if entry.kind == "BATTLE_BOSS":
                    if (number not in (3, 5) or x != len(plan.columns) - 1
                            or column.minimum != column.maximum or column.maximum != 1):
                        raise invalid()
                    transition = data.rogue_endings.cleared(entry.stage, plan.zone_id, ())
                    if number == 3 and transition.next_zone != "zone_4":
                        raise invalid()
                    if number == 5:
                        if entry.stage != "ro1_b_6" or transition.ending != "ro_ending_1":
                            raise invalid()  # Hidden endings need their independent acquisition chain.
                        continue
                needed.add(KINDS[entry.kind])
                needed_kinds.add(entry.kind)
        # Every route in canonical middle/final floors must terminate at its Boss.
        if number in (3, 5) and any(e.kind != "BATTLE_BOSS" for e in plan.columns[-1].pool):
            raise invalid()
        parsed = {}
        for role in roles:
            items = supply[role]
            if type(items) is not list or len(items) > MAX_POOL or (not items and role in needed):
                raise invalid()
            parsed[role] = tuple(candidate(data, role, item, at,
                capsules=value["policy"] in (CAPSULE_POLICY, BASE_REWARD_POLICY, TYPED_POLICY),
                base_rewards=value["policy"] in (BASE_REWARD_POLICY, TYPED_POLICY),
                typed_battles=value["policy"] == TYPED_POLICY) for item in items)
            if (len({item.id for item in parsed[role]}) != len(items)
                    or len({item.source for item in parsed[role]}) != len(items)
                    or sum(item.weight for item in parsed[role]) > 2**31 - 1):
                raise invalid()
            proofs.append([[item.id, item.weight, item.proof] for item in parsed[role]])
        if any(not any(item.supports(kind) for item in parsed[KINDS[kind]]) for kind in needed_kinds):
            raise invalid()
        pools.append(MappingProxyType(parsed))
    digest = fingerprint({"policy": value["policy"], "source": json.loads(source), "at": at, "proofs": proofs})
    return ContentSpec(data.manifest["hash"], at, source, digest, sequence, tuple(pools), value["policy"])


def read_source(data, path, database_path):
    """Bounded trusted configuration, checked before startup writes.

    Opening uses the run's own timestamp again. Existing runs instead recompile
    their saved source, independently of changes to this optional file.
    """
    import sqlite3
    import time
    from contextlib import closing
    from types import SimpleNamespace

    from terralocal.server.domain.clock import ServerClock

    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise invalid()
            result[key] = item
        return result

    with path.open("rb") as stream:
        source = stream.read(MAX_SOURCE_BYTES + 1)
    if len(source) > MAX_SOURCE_BYTES:
        raise invalid()
    value = json.loads(source, object_pairs_hook=unique)
    at = int(time.time())
    if database_path.exists():
        with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='server_clock'").fetchone():
                row = con.execute("SELECT * FROM server_clock WHERE id=1").fetchone()
                if row is None:
                    raise invalid()
                at = ServerClock(SimpleNamespace(**dict(row))).now()
    return compile_spec(data, value, at=at).source
