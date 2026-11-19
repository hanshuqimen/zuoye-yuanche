"""Explicit complete content recipes; no natural-weight or gameplay claim."""

import copy
import json
import random
from dataclasses import FrozenInstanceError, asdict
from types import SimpleNamespace

import pytest
from test_rogue_recruit_costs import R25, R26, R27, R28
from test_roguelike_state import rows

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.gamedata.repository import canonical
from terralocal.server.gamedata.rogue_content_specs import POLICY, compile_spec

pytest_plugins = ("test_rogue_battle_loot",)


def authored(data):
    floors = [Plan("zone_" + str(i), (Column(1, 1, (
        Entry("BATTLE_BOSS", 1, "ro1_b_1" if i == 3 else "ro1_b_6") if i in (3, 5)
        else Entry("SHOP" if i == 4 else "INCIDENT", 1),)),), 0) for i in range(1, 6)]
    supplies = [{role: [] for role in ("incident", "rest", "shop", "battle")} for _ in floors]
    for i in (0, 1):
        supplies[i]["incident"] = [{"id": "gold-scene", "weight": 1, "content": {"program": "rogue1-fixed-gold"}}]
    ticket = next(iter(sorted(data.rogue_recruit.tickets)))
    for ident, price, weight in (("small", 1, 1), ("large", 2, 3)):
        supplies[3]["shop"].append({"id": ident, "weight": weight, "content": {
            "id": ident, "evidence": "Explicit QA quote, not a merchant distribution",
            "offers": [{"index": "ticket", "item_id": ticket, "price": price}]}})
    for ident, items in (("lower", (R25, R26)), ("higher", (R27, R28))):
        supplies[2]["battle"].append({"id": ident, "weight": 1, "content": {
            "groups": [list(items)], "eligibility": list(items), "evidence": "Explicit QA eligibility, not a drop pool"}})
    return {"schema": 1, "policy": POLICY, "theme": "rogue_1", "mode": "NORMAL", "grade": 0,
            "gamedata_hash": data.manifest["hash"], "evidence": "Authored finite content contract only",
            "floors": [asdict(p) for p in floors], "supplies": supplies}


def wire(data):
    return json.loads(canonical(authored(data)))


def test_all_floors_roles_and_complete_definitions_compile_without_writing_a_run(loot_boss_runtime):
    runtime, _ = loot_boss_runtime
    saved = rows(runtime.database.path)
    value = wire(runtime.data)
    spec = compile_spec(runtime.data, value, at=1_800_000_000)
    graphs = spec.generate(runtime.data, 77)
    assert tuple(g.id for g in graphs) == tuple("zone_" + str(i) for i in range(1, 6))
    assert graphs[2].nodes[-1].stage == "ro1_b_1" and graphs[4].nodes[-1].stage == "ro1_b_6"
    assert spec.choose(1, "INCIDENT", Point(0, 0), 77).id == "gold-scene"
    assert spec.choose(3, "BATTLE_BOSS", Point(0, 0), 77).id in ("lower", "higher")
    assert spec.choose(5, "BATTLE_BOSS", Point(0, 0), 77) is None
    assert rows(runtime.database.path) == saved


def test_node_randomness_is_stable_independent_and_does_not_touch_global_rng(loot_boss_runtime):
    runtime, _ = loot_boss_runtime
    value = wire(runtime.data)
    spec = compile_spec(runtime.data, value, at=1_800_000_000)
    state = random.getstate()
    first = spec.choose(4, "SHOP", Point(0, 0), 100)
    spec.generate(runtime.data, 999)
    spec.choose(3, "BATTLE_BOSS", Point(0, 0), 7)
    assert spec.choose(4, "SHOP", Point(0, 0), 100) == first
    assert compile_spec(runtime.data, copy.deepcopy(value), at=1_800_000_000).choose(4, "SHOP", Point(0, 0), 100) == first
    assert {spec.choose(4, "SHOP", Point(0, 0), seed).id for seed in range(128)} == {"small", "large"}
    assert random.getstate() == state


def test_compiled_recipe_has_no_mutable_aliases_and_is_bound_to_data_and_time(loot_boss_runtime):
    runtime, _ = loot_boss_runtime
    value = wire(runtime.data)
    spec = compile_spec(runtime.data, value, at=1_800_000_000)
    before = spec.source
    value["supplies"][2]["battle"][0]["content"]["groups"][0][0] = "tampered"
    assert spec.source == before
    with pytest.raises(TypeError):
        spec.pools[0]["incident"] = ()
    with pytest.raises(FrozenInstanceError):
        spec.choose(1, "INCIDENT", Point(0, 0), 1).weight = 99
    with pytest.raises(ValueError):
        spec.generate(SimpleNamespace(manifest={"hash": "0" * 64}), 1)
    assert spec.digest != compile_spec(runtime.data, wire(runtime.data), at=1_800_000_001).digest


def test_conditional_selection_reserves_all_possible_nonstack_outcomes(loot_boss_runtime):
    runtime, _ = loot_boss_runtime
    spec = compile_spec(runtime.data, wire(runtime.data), at=1_800_000_000)
    first = spec.choose(3, "BATTLE_BOSS", Point(0, 0), 12)
    assert len(first.reservations) == 2
    second = spec.choose(3, "BATTLE_BOSS", Point(0, 0), 12, reserved=first.reservations)
    assert not first.reservations & second.reservations
    assert second == spec.choose(3, "BATTLE_BOSS", Point(0, 0), 12, reserved=first.reservations)
    with pytest.raises(ValueError):
        spec.choose(3, "BATTLE_BOSS", Point(0, 0), 12, reserved=first.reservations | second.reservations)
    with pytest.raises(ValueError):
        spec.choose(3, "BATTLE_BOSS", Point(0, 0), 12, reserved=set())


@pytest.mark.parametrize("damage", ["schema", "grade", "mode", "data", "source", "extra", "four-floors",
    "empty-pool", "unknown-role", "unknown-program", "wrong-role", "duplicate-id", "duplicate-content",
    "zero-weight", "bool-weight", "float-weight", "bool-price", "ineligible", "unused-bad-pool",
    "middle-no-boss", "hidden-ending"])
def test_incomplete_or_unsupported_content_never_becomes_a_compiled_recipe(loot_boss_runtime, damage):
    runtime, _ = loot_boss_runtime
    value = wire(runtime.data)
    if damage in ("schema", "grade"):
        value[damage] = True
    elif damage == "mode":
        value["mode"] = "HARD"
    elif damage == "data":
        value["gamedata_hash"] = "0" * 64
    elif damage == "source":
        value["evidence"] = ""
    elif damage == "extra":
        value["clientSuccess"] = True
    elif damage == "four-floors":
        value["floors"].pop()
    elif damage == "empty-pool":
        value["supplies"][0]["incident"] = []
    elif damage == "unknown-role":
        value["supplies"][0]["treasure"] = []
    elif damage == "unknown-program":
        value["supplies"][0]["incident"][0]["content"]["program"] = "missing"
    elif damage == "wrong-role":
        value["supplies"][0]["rest"] = value["supplies"][0]["incident"]
    elif damage.startswith("duplicate"):
        duplicate = copy.deepcopy(value["supplies"][0]["incident"][0])
        if damage == "duplicate-content":
            duplicate["id"] = "different-id-same-content"
        value["supplies"][0]["incident"].append(duplicate)
    elif damage.endswith("weight"):
        value["supplies"][0]["incident"][0]["weight"] = {"zero-weight": 0, "bool-weight": True, "float-weight": 1.0}[damage]
    elif damage == "bool-price":
        value["supplies"][3]["shop"][0]["content"]["offers"][0]["price"] = False
    elif damage == "ineligible":
        value["supplies"][2]["battle"][0]["content"]["eligibility"] = []
    elif damage == "unused-bad-pool":
        value["supplies"][4]["battle"] = [{"id": "missing-content", "weight": 1, "content": {}}]
    elif damage == "middle-no-boss":
        value["floors"][2]["columns"][0]["pool"][0] = {"kind": "INCIDENT", "stage": None, "weight": 1}
    else:
        value["floors"][4]["columns"][0]["pool"][0]["stage"] = "ro1_b_7"
    saved = rows(runtime.database.path)
    with pytest.raises((ValueError, DomainError)):
        compile_spec(runtime.data, value, at=1_800_000_000)
    assert rows(runtime.database.path) == saved
