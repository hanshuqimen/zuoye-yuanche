"""Map topology and wire admission, not official generation/playability fixtures."""

import copy
import json
import random
from dataclasses import FrozenInstanceError, replace

import pytest
from conftest import miniature
from test_roguelike_topics import topic_table

from terralocal.server.domain.rogue_map import (
    Column,
    Entry,
    Plan,
    Point,
    admit_wire,
    generate,
    plan_fingerprint,
)
from terralocal.server.gamedata import GameData, import_data
from terralocal.server.gamedata.rogue_map import NODE_TYPES, FirstThemeMapCatalog
from terralocal.server.gamedata.rogue_placements import AUTHORED_POLICY, AUTHORED_TABLE


def authored_placements(value):
    """Explicit synthetic topology scope, never frozen official floor rules.

    The fixture deliberately permits its three authored stage types on each
    authored region to exercise geometry/base amounts independently.
    """
    detail = value["roguelike_topic_table"]["details"]["rogue_1"]
    zones = sorted(set(detail["zones"]) - set(detail["gameConst"]["portalZones"]))
    value[AUTHORED_TABLE] = {"schema": 1, "policy": AUTHORED_POLICY,
        "regions": {key: zones.copy() for key in detail["stages"]}}
    return value


def tables():
    table = topic_table()
    for section in ("topics", "details", "modules", "customizeData"):
        table[section]["rogue_1"] = table[section].pop("topic")
    table["topics"]["rogue_1"]["id"] = "rogue_1"
    d = table["details"]["rogue_1"]
    d["nodeTypeData"] = {key: {} for key in NODE_TYPES}
    for key, stage in d["stages"].items():
        stage.update(isBoss=0, isElite=int(key == "emergency"),
                     difficulty="FOUR_STAR" if key == "emergency" else "NORMAL")
    d["stages"]["boss"] = {"id": "boss", "levelId": "synthetic/boss", "linkedStageId": "",
                            "isBoss": 1, "isElite": 0, "difficulty": "NORMAL"}
    d["zones"]["floor"]["isHiddenZone"] = False
    d["zones"]["hidden"] = {"id": "hidden", "isHiddenZone": True}
    d["zones"]["portal"] = {"id": "portal", "isHiddenZone": False}
    d["gameConst"] = {"portalZones": ["portal"]}
    return authored_placements(miniature() | {"roguelike_topic_table": table})


@pytest.fixture
def map_data(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name, value in tables().items():
        (source / (name + ".json")).write_text(json.dumps(value), "utf8")
    manifest = import_data(source, tmp_path / "cache")
    return GameData(tmp_path / "cache" / manifest["hash"])


def plan(width=3, depth=6):
    pool = (Entry("BATTLE_NORMAL", 6, "ordinary"), Entry("INCIDENT", 3), Entry("REST", 1))
    return Plan("floor", (Column(1, width, pool),) * (depth - 1) + (
        Column(1, 1, (Entry("BATTLE_BOSS", 1, "boss"),)),), 3500)


def assert_reachability(zone):
    by_pos = {n.pos: n for n in zone.nodes}
    frontier = list(zone.successors(None))
    visited = set()
    while frontier:
        pos = frontier.pop()
        if pos in visited:
            continue
        visited.add(pos)
        frontier.extend(by_pos[pos].next)
    assert visited == set(by_pos)
    for start in by_pos:
        frontier, seen, exits = [start], set(), []
        while frontier:
            pos = frontier.pop()
            if pos in seen:
                continue
            seen.add(pos)
            if not by_pos[pos].next:
                exits.append(pos)
            frontier.extend(by_pos[pos].next)
        assert exits and all(p.x == max(q.x for q in by_pos) for p in exits)


def test_seed_is_deterministic_immutable_and_does_not_touch_global_rng(map_data):
    before = random.getstate()
    first = generate(map_data, plan(), 1729)
    assert first == generate(map_data, plan(), 1729)
    assert random.getstate() == before
    assert len({json.dumps(generate(map_data, plan(), seed).wire(), sort_keys=True) for seed in range(20)}) > 1
    with pytest.raises(FrozenInstanceError):
        first.nodes[0].kind = "SHOP"
    assert admit_wire(map_data.rogue_map, json.loads(json.dumps(first.wire()))) == first
    assert_reachability(first)


def test_every_width_transition_and_seed_has_no_dead_branch_or_crossing(map_data):
    for left in range(1, 9):
        for right in range(1, 9):
            spec = Plan("floor", (Column(left, left, (Entry("REST", 1),)),
                                  Column(right, right, (Entry("TREASURE", 1),)),
                                  Column(1, 1, (Entry("SHOP", 1),))), 10000)
            for seed in range(5):
                zone = generate(map_data, spec, seed)
                assert_reachability(zone)
                assert admit_wire(map_data.rogue_map, zone.wire()) == zone


@pytest.mark.parametrize("change", ["dangling", "backward", "duplicate-edge", "hole", "unreachable",
                                    "wrong-stage", "wrong-key", "boolean-position", "boolean-time", "extra",
                                    "key-edge", "hidden-edge", "variation", "scene", "premature-exit"])
def test_bad_wire_is_rejected_instead_of_repaired_or_erased(map_data, change):
    spec = Plan("floor", (Column(1, 1, (Entry("REST", 1),)), Column(2, 2, (Entry("INCIDENT", 1),)),
                          Column(1, 1, (Entry("SHOP", 1),))), 0)
    value = generate(map_data, spec, 0).wire()
    first, middle = value["nodes"]["0"], value["nodes"]["1000"]
    if change == "dangling":
        first["next"][0]["y"] = 7
    elif change == "backward":
        middle["next"][0]["x"] = 0
    elif change == "duplicate-edge":
        first["next"].append(copy.deepcopy(first["next"][0]))
    elif change == "hole":
        del value["nodes"]["1000"]
        del value["nodes"]["1001"]
    elif change == "unreachable":
        first["next"] = [e for e in first["next"] if e["y"] == 0]
    elif change == "wrong-stage":
        first["type"], first["stage"] = "BATTLE_BOSS", "ordinary"
    elif change == "wrong-key":
        value["nodes"]["001"] = value["nodes"].pop("0")
    elif change == "boolean-position":
        first["pos"]["x"] = False
    elif change == "boolean-time":
        first["fts"] = False
    elif change == "extra":
        first["unknown"] = {}
    elif change == "key-edge":
        first["next"][0]["key"] = True
    elif change == "hidden-edge":
        first["next"][0]["hidden"] = "HIDE"
    elif change == "variation":
        value["variation"] = ["unadmitted"]
    elif change == "scene":
        first["scenes"] = [{"id": "unadmitted"}]
    elif change == "premature-exit":
        middle["next"] = []
    with pytest.raises(ValueError, match="roguelike_topic_table"):
        admit_wire(map_data.rogue_map, value)


@pytest.mark.parametrize("spec", [Plan("missing", (Column(1, 1, (Entry("REST", 1),)),), 0),
    Plan("floor", (), 0), Plan("floor", (Column(1, 9, (Entry("REST", 1),)),), 0),
    Plan("floor", (Column(1, 1, ()),), 0),
    Plan("floor", (Column(1, 1, (Entry("REST", True),)),), 0),
    Plan("floor", (Column(1, 1, (Entry("REST", 0),)),), 0),
    Plan("floor", (Column(1, 1, (Entry("BATTLE_NORMAL", 1, "boss"),)),), 0),
    Plan("floor", (Column(1, 1, (Entry("REST", 1, "ordinary"),)),), 0),
    Plan("floor", (Column(1, 1, (Entry("UNKNOWN", 1),)),), 0),
    Plan("floor", (Column(1, 1, (Entry("REST", 1), Entry("REST", 2))),), 0),
    Plan("floor", (Column(1, 1, (Entry("REST", 1),)),), True)])
def test_plan_requires_explicit_valid_pools_budgets_and_weights(map_data, spec):
    with pytest.raises(ValueError, match="roguelike_topic_table"):
        generate(map_data, spec, 0)


@pytest.mark.parametrize("seed", [-1, True, 2**63, "1"])
def test_invalid_seeds_do_not_silently_coerce(map_data, seed):
    with pytest.raises(ValueError):
        generate(map_data, plan(), seed)


def test_catalog_keeps_explicit_links_and_does_not_promote_membership_to_unlocks(map_data):
    catalog = map_data.rogue_map
    assert catalog.emergency_variants == {"ordinary": "emergency"}
    assert catalog.zones["hidden"] is True
    with pytest.raises(TypeError):
        catalog.emergency_variants["ordinary"] = "boss"
    spec = plan()
    assert plan_fingerprint(spec) != plan_fingerprint(replace(spec, extra_edge_chance=0))
    # The classifier cannot turn a boss into a normal stage by an arbitrary ID.
    with pytest.raises(ValueError):
        catalog.require_node("BATTLE_NORMAL", "boss")
    with pytest.raises(ValueError):
        catalog.require_zone("portal")


def test_direct_graph_validation_rejects_boolean_target_coordinates(map_data):
    zone = generate(map_data, plan(), 0)
    altered = replace(zone.nodes[0], next=(Point(True, 0),))
    with pytest.raises(ValueError):
        replace(zone, nodes=(altered, *zone.nodes[1:])).validate(map_data.rogue_map)


@pytest.mark.parametrize("field,value", [("isBoss", True), ("isElite", 2), ("difficulty", "unknown")])
def test_invalid_real_data_classification_is_not_defaulted(map_data, field, value):
    table = copy.deepcopy(map_data.table("roguelike_topic_table"))
    table["details"]["rogue_1"]["stages"]["ordinary"][field] = value
    class Source:
        rogue_topics = map_data.rogue_topics
        def table(self, name):
            return table
    with pytest.raises(ValueError):
        FirstThemeMapCatalog(Source())


def test_wire_contains_native_fields_and_no_test_teleports(map_data):
    zone = generate(map_data, plan(width=3), 3)
    assert set(zone.wire()) == {"id", "nodes", "variation", "zoneType"}
    for n in zone.nodes:
        assert "zone_end" not in n.wire() and "index" not in n.wire()
        assert all(p.x == n.pos.x + 1 for p in n.next)
    assert zone.successors(None) == tuple(n.pos for n in zone.nodes if n.pos.x == 0)
    with pytest.raises(ValueError):
        zone.successors(Point(31, 7))


def test_native_node_keys_use_depth_times_1000_plus_index(map_data):
    zone = generate(map_data, plan(), 3)
    for node in zone.nodes:
        assert node.pos.key == str(node.pos.x * 1000 + node.pos.y)
        assert node.pos.key in zone.wire()["nodes"]
    old = zone.wire(legacy_keys=True)
    assert admit_wire(map_data.rogue_map, old, legacy_keys=True) == zone
    with pytest.raises(ValueError):
        admit_wire(map_data.rogue_map, old)
