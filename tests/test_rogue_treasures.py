"""Pure explicitly authored menus/outcomes, not official treasure probabilities."""

import copy
from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType

import pytest
from test_rogue_capacity_relics import AMOUNTS as CAPACITY
from test_rogue_capacity_relics import add_capacity
from test_rogue_gold_relics import R11, R13
from test_rogue_recruit_costs import R25
from test_rogue_resource_relics import Q28
from test_roguelike_state import rows

from terralocal.server.domain.rogue_events import Resources, decide, replay, scene_content
from terralocal.server.gamedata import GameData, import_data, rogue_treasures
from terralocal.server.gamedata.repository import canonical, fingerprint

pytest_plugins = ("test_rogue_resource_relics",)


@pytest.fixture
def treasure_data(resource_runtime, tmp_path, monkeypatch):
    runtime, _ = resource_runtime
    tables = {name: copy.deepcopy(runtime.data.table(name)) for name in runtime.data.manifest["tables"]}
    tables = add_capacity(tables, monkeypatch)
    authored_treasure_tables(tables, monkeypatch)
    source, cache = tmp_path / "treasure-source", tmp_path / "treasure-cache"
    source.mkdir()
    for key, value in tables.items():
        (source / (key + ".json")).write_bytes(canonical(value))
    manifest = import_data(source, cache)
    data = GameData(cache / manifest["hash"], expected_hash=manifest["hash"])
    data.verify()
    return data, runtime


def authored_treasure_tables(tables, monkeypatch):
    """Explicit QA text/hashes only, never replaces production fingerprints."""
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    scenes, choices = {}, {}
    for variant, (entry, result, options) in rogue_treasures.VARIANTS.items():
        for ident in (entry, result):
            row = {"id": ident, "title": "QA " + variant, "description": "Authored test scene", "useHiddenMusic": False}
            detail["choiceScenes"][ident] = row
            scenes[ident] = fingerprint(row)
        for ident in options:
            row = {"id": ident, "type": "TRADE", "title": "Authored random-relic choice", "description": "QA menu only",
                   "nextSceneId": result, "isHiddenChoice": False, "forceShowWhenOnlyLeave": False, "sortId": 0,
                   "displayData": {"type": "NORMAL", "itemId": None}}
            detail["choices"][ident] = row
            choices[ident] = fingerprint(row)
    monkeypatch.setattr(rogue_treasures, "SCENE_HASHES", MappingProxyType(scenes))
    monkeypatch.setattr(rogue_treasures, "CHOICE_HASHES", MappingProxyType(choices))
    monkeypatch.setattr(rogue_treasures, "LEAVE_DIGEST", fingerprint(detail["choices"]["choice_leave"]))


def recipe(variant="history", items=(R13,)):
    choices = rogue_treasures.VARIANTS[variant][2]
    return {"schema": 1, "policy": rogue_treasures.POLICY, "variant": variant,
            "rewards": [{"choice": choice, "item": item} for choice, item in zip(choices, items, strict=True)],
            "eligibility": list(dict.fromkeys(items)), "evidence": "Authored QA menu and preselected eligibility, no natural rates"}


def test_history_graph_grant_and_immediate_gold_are_complete_immutable_and_without_database_writes(treasure_data):
    data, runtime = treasure_data
    before = rows(runtime.database.path)
    value = recipe()
    compiled = rogue_treasures.compile_treasure(data, value, at=1_800_000_000)
    assert compiled.grants == {"choice_treasure1_1": R13} and compiled.reservations == frozenset({R13})
    initial = Resources(4, 8, 6, 0, 6)
    state = replay(compiled.program, initial, ())
    assert state.scene == "scene_treasure1_enter"
    assert scene_content(compiled.program, state)["choices"] == {"choice_treasure1_1": True}
    state = decide(compiled.program, initial, (), "choice_treasure1_1")
    assert state.scene == "scene_treasure1_1" and state.resources.gold == 33
    ended = decide(compiled.program, initial, state.steps, "choice_leave")
    assert ended.scene is None and ended.resources.gold == 33
    saved = compiled.source
    value["rewards"][0]["item"] = R11
    assert compiled.source == saved
    with pytest.raises(TypeError):
        compiled.grants["choice_treasure1_1"] = R11
    with pytest.raises(FrozenInstanceError):
        compiled.source = b"changed"
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("selected,item,gain", [("choice_treasure2_1", R11, 10), ("choice_treasure2_2", Q28, 0)])
def test_fate_explicit_alternatives_do_not_grant_the_unchosen_outcome(treasure_data, selected, item, gain):
    data, _ = treasure_data
    compiled = rogue_treasures.compile_treasure(data, recipe("fate", (R11, Q28)), at=1_800_000_000)
    assert compiled.grants[selected] == item and compiled.reservations == frozenset({R11, Q28})
    initial = Resources(4, 8, 6, 0, 6)
    state = decide(compiled.program, initial, (), selected)
    assert state.resources.gold == 8 + gain and state.resources.squad_capacity == 6
    assert state.scene == "scene_treasure2_1"
    assert scene_content(compiled.program, state)["choices"] == {"choice_leave": True}
    assert decide(compiled.program, initial, state.steps, "choice_leave").scene is None


def test_same_alternative_item_can_be_explicitly_reserved_once_and_time_is_bound(treasure_data):
    data, _ = treasure_data
    value = recipe("fate", (R25, R25))
    first = rogue_treasures.compile_treasure(data, value, at=1_800_000_000)
    assert first.reservations == frozenset({R25})
    assert first.program.digest == rogue_treasures.compile_treasure(data, copy.deepcopy(value), at=1_800_000_000).program.digest
    assert first.program.digest != rogue_treasures.compile_treasure(data, value, at=1_800_000_001).program.digest


@pytest.mark.parametrize("damage", ["schema", "policy", "variant", "extra", "empty-menu", "duplicate-choice",
    "foreign-choice", "missing-eligibility", "duplicate-eligibility", "ineligible", "unsupported-effect", "evidence",
    "too-many", "bool-item"])
def test_malformed_or_incomplete_outcomes_cannot_compile_or_write_game_state(treasure_data, damage):
    data, runtime = treasure_data
    value = recipe()
    if damage == "schema":
        value["schema"] = True
    elif damage in ("policy", "variant"):
        value[damage] = "unrecognized"
    elif damage == "extra":
        value["clientCanChooseItem"] = True
    elif damage == "empty-menu":
        value["rewards"] = []
    elif damage == "duplicate-choice":
        value["rewards"] *= 2
    elif damage == "foreign-choice":
        value["rewards"][0]["choice"] = "choice_treasure2_1"
    elif damage == "missing-eligibility":
        value["eligibility"] = []
    elif damage == "duplicate-eligibility":
        value["eligibility"] *= 2
    elif damage == "ineligible":
        value["eligibility"] = [R11]
    elif damage == "unsupported-effect":
        value["rewards"][0]["item"] = value["eligibility"][0] = "unimplemented_relic"
    elif damage == "evidence":
        value["evidence"] = ""
    elif damage == "too-many":
        value["rewards"] *= 3
    else:
        value["rewards"][0]["item"] = True
    saved = rows(runtime.database.path)
    with pytest.raises(ValueError):
        rogue_treasures.compile_treasure(data, value, at=1_800_000_000)
    assert rows(runtime.database.path) == saved


def test_changed_complete_scene_definition_is_not_silently_admitted(treasure_data):
    data, _ = treasure_data
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    detail["choiceScenes"]["scene_treasure1_1"]["description"] = "unreviewed replacement"
    with pytest.raises(ValueError):
        rogue_treasures.compile_treasure(data, recipe(), at=1_800_000_000)


@pytest.mark.parametrize("item,amount", list(CAPACITY.items()))
def test_each_capacity_outcome_is_in_the_scene_delta_once(treasure_data, item, amount):
    data, _ = treasure_data
    compiled = rogue_treasures.compile_treasure(data, recipe(items=(item,)), at=1_800_000_000)
    initial = Resources(4, 8, 6, 0, 6)
    state = decide(compiled.program, initial, (), "choice_treasure1_1")
    assert state.resources.squad_capacity == 6 + amount
    assert decide(compiled.program, initial, state.steps, "choice_leave").resources.squad_capacity == 6 + amount


def test_limited_archive_entry_is_not_admitted_as_an_ordinary_wish(treasure_data, monkeypatch):
    data, _ = treasure_data
    archive = data.rogue_relic_archive
    entries = dict(archive.entries)
    entries[R25] = replace(entries[R25], special=True)
    monkeypatch.setattr(archive, "entries", MappingProxyType(entries))
    with pytest.raises(ValueError):
        rogue_treasures.compile_treasure(data, recipe(items=(R25,)), at=1_800_000_000)
