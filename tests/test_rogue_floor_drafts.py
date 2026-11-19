"""Whole explicit sequence persistence; not real floor advance or official pools."""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
import test_rogue_shop_ending as ending_fixture
import test_roguelike_map_drafts as draft_fixture
from fastapi.testclient import TestClient
from test_rogue_ending import ending_runtime as ending_runtime
from test_rogue_shop_ending import shop_ending_runtime as shop_ending_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_map import plan
from test_roguelike_map_drafts import draft_runtime as draft_runtime
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_floors import FloorSequence, floor_seed, generate_sequence
from terralocal.server.domain.rogue_map import Column, Entry, Plan, generate
from terralocal.server.domain.rogue_map_drafts import prepare, prepare_floors, read_floors
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def floor_runtime(monkeypatch, request):
    original = draft_fixture.map_tables

    def tables():
        value = original()
        zones = value["roguelike_topic_table"]["details"]["rogue_1"]["zones"]
        for key in ("zone_2", "zone_3"):
            zones[key] = {"id": key, "isHiddenZone": False}
        return value

    monkeypatch.setattr(draft_fixture, "map_tables", tables)
    return request.getfixturevalue("draft_runtime")


def sequence():
    first = Plan("zone_1", (Column(1, 1, (Entry("INCIDENT", 1),)),), 0)
    return FloorSequence((first, replace(plan(), zone_id="zone_2"), replace(plan(), zone_id="zone_3")))


def save(runtime, spec=None):
    with runtime.database.transaction() as session:
        return prepare_floors(Context(session, runtime.data, 1), spec or sequence())


def test_all_floors_persist_without_unlocking_or_revealing_future_maps(floor_runtime):
    runtime, token = floor_runtime
    before = current(runtime, token)
    graphs = save(runtime)
    assert len(graphs) == 3
    assert current(runtime, token) == before
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        assert read_floors(ctx) == graphs
        seed = session.query(m.RogueTopicRun).one().seed
        assert graphs[0] == generate(runtime.data, sequence().floors[0], seed)
        with pytest.raises(DomainError, match="当前没有进行中的探索"):
            read_floors(Context(session, runtime.data, 2))
    saved = rows(runtime.database.path)
    assert save(runtime) == graphs and rows(runtime.database.path) == saved
    reopened = Runtime(runtime.settings)
    try:
        with reopened.database.transaction(write=False) as session:
            assert read_floors(Context(session, reopened.data, 1)) == graphs
        service = BackupService(reopened)
        backup = service.create()
        service.restore(backup["name"])
        assert rows(reopened.database.path) == saved
        assert current(reopened, token) == before
    finally:
        reopened.database.close()
    with TestClient(create_game_app(runtime)) as client:
        previous = runtime.sync(token)["user"]
        response = post(client, token, "finishEvent", {}, "activate-sequence")
        assert response.status_code == 200, response.text
        assert apply(previous, response.json()["playerDataDelta"]) == runtime.sync(token)["user"]
        state = current(runtime, token)
        assert state["map"]["zones"] == {"1": graphs[0].wire()}
        assert state["player"]["cursor"] == {"zone": 1, "position": None}
        stored = rows(runtime.database.path)
        assert post(client, token, "finishEvent", {}, "activate-sequence").json() == response.json()
        assert rows(runtime.database.path) == stored
        assert post(client, token, "finishEvent", {}, "activate-again").status_code == 200
        assert current(runtime, token) == state
        assert rows(runtime.database.path)["rlv2_map_drafts"] == stored["rlv2_map_drafts"]
    reopened = Runtime(runtime.settings)
    try:
        assert current(reopened, token) == state
    finally:
        reopened.database.close()


def test_future_recipe_replacement_and_single_sequence_conversion_are_rejected(floor_runtime):
    runtime, _ = floor_runtime
    spec = sequence()
    save(runtime, spec)
    before = rows(runtime.database.path)
    changed = FloorSequence(spec.floors[:1] + (replace(spec.floors[1], extra_edge_chance=0),) + spec.floors[2:])
    for other in (changed, FloorSequence(spec.floors[:1])):
        with pytest.raises(DomainError) as exc:
            save(runtime, other)
        assert exc.value.code == "ROGUE_MAP_DRAFT_CONFLICT"
        assert rows(runtime.database.path) == before
    with pytest.raises(DomainError) as exc:
        with runtime.database.transaction() as session:
            prepare(Context(session, runtime.data, 1), spec.floors[0])
    assert exc.value.code == "ROGUE_MAP_DRAFT_CONFLICT"
    assert rows(runtime.database.path) == before


def test_two_processes_and_failed_transaction_do_not_reroll_or_partially_save(floor_runtime):
    runtime, _ = floor_runtime
    before = rows(runtime.database.path)
    with pytest.raises(RuntimeError, match="injected"):
        with runtime.database.transaction() as session:
            prepare_floors(Context(session, runtime.data, 1), sequence())
            raise RuntimeError("injected before transaction commit")
    assert rows(runtime.database.path) == before
    other = Runtime(runtime.settings)
    try:
        with ThreadPoolExecutor(2) as pool:
            result = list(pool.map(save, (runtime, other)))
        assert result[0] == result[1]
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueMapDraft).count() == 1
    finally:
        other.database.close()


@pytest.mark.parametrize("damage", ["future-weight", "future-region", "future-graph", "future-key",
                                    "truncated-graphs", "graph-extra", "graph-index", "plan-extra",
                                    "plan-hash", "seed", "too-many-floors", "empty-floors"])
def test_bad_future_floor_blocks_startup_readonly_before_any_repair(floor_runtime, damage):
    runtime, _ = floor_runtime
    save(runtime)
    with runtime.database.transaction() as session:
        draft = session.query(m.RogueMapDraft).one()
        recipe, graphs = copy.deepcopy(draft.plan), copy.deepcopy(draft.graph)
        if damage == "future-weight":
            del recipe["floors"][1]["columns"][0]["pool"][0]["weight"]
        elif damage == "future-region":
            recipe["floors"][1]["zone_id"] = "portal"
        elif damage == "future-graph":
            graphs["zones"]["3"]["nodes"]["0"]["type"] = "TREASURE"
        elif damage == "future-key":
            graphs["zones"]["2"]["nodes"]["100"] = graphs["zones"]["2"]["nodes"].pop("1000")
        elif damage == "truncated-graphs":
            del graphs["zones"]["3"]
        elif damage == "graph-extra":
            graphs["unexpected"] = {}
        elif damage == "graph-index":
            graphs["zones"]["02"] = graphs["zones"].pop("2")
        elif damage == "plan-extra":
            recipe["official_weights"] = True
        elif damage == "plan-hash":
            draft.plan_hash = "0" * 64
        elif damage == "seed":
            draft.seed += 1
        elif damage == "too-many-floors":
            recipe["floors"] *= 6
        elif damage == "empty-floors":
            recipe["floors"] = []
        draft.plan, draft.graph = recipe, graphs
    runtime.database.close()
    before = rows(runtime.database.path)
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="地图准备记录"):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def test_corrupt_future_candidate_backup_leaves_live_database_intact(floor_runtime):
    runtime, _ = floor_runtime
    save(runtime)
    service = BackupService(runtime)
    backup = service.create()
    path = service.directory / backup["name"]
    with sqlite3.connect(path) as con:
        value = json.loads(con.execute("SELECT graph FROM rlv2_map_drafts").fetchone()[0])
        del value["zones"]["2"]
        con.execute("UPDATE rlv2_map_drafts SET graph=?", (json.dumps(value),))
    metadata = path.with_suffix(".json")
    value = json.loads(metadata.read_bytes())
    value["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(value), "utf8")
    before = rows(runtime.database.path)
    with pytest.raises(ValueError, match="地图准备记录"):
        service.restore(backup["name"])
    assert rows(runtime.database.path) == before
    assert not list(service.directory.glob("before-restore-*"))


def test_first_floor_seed_is_compatible_later_seed_and_recipe_are_independent(floor_runtime):
    runtime, _ = floor_runtime
    spec = sequence()
    graphs = generate_sequence(runtime.data, spec, 314159)
    assert graphs[0] == generate(runtime.data, spec.floors[0], 314159)
    assert floor_seed(runtime.data, spec.floors[1], 314159, 2) != floor_seed(runtime.data, spec.floors[1], 314159, 3)
    changed = FloorSequence(spec.floors[:2] + (replace(spec.floors[2], extra_edge_chance=0),))
    assert generate_sequence(runtime.data, changed, 314159)[:2] == graphs[:2]
    for value in (True, 0, -1, 17):
        with pytest.raises(ValueError):
            floor_seed(runtime.data, spec.floors[1], 314159, value)


def test_old_single_floor_remains_readonly_and_cannot_be_extended_in_place(floor_runtime):
    runtime, _ = floor_runtime
    with runtime.database.transaction() as session:
        graph = prepare(Context(session, runtime.data, 1), sequence().floors[0])
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as exc:
        save(runtime)
    assert exc.value.code == "ROGUE_MAP_DRAFT_CONFLICT"
    reopened = Runtime(runtime.settings)
    try:
        with reopened.database.transaction(write=False) as session:
            assert read_floors(Context(session, reopened.data, 1)) == (graph,)
        assert rows(runtime.database.path) == before
    finally:
        reopened.database.close()


def test_sequence_first_floor_scene_shop_defeat_and_ending_still_compose(shop_ending_runtime, monkeypatch):
    runtime, token = shop_ending_runtime

    def save_whole(ctx, first):
        # Same admitted zone may have different authored plans at distinct indices.
        # This fixture asserts no official repeated-region route or floor eligibility.
        future = Plan("zone_1", (Column(1, 1, (Entry("INCIDENT", 1),)),), 0)
        return prepare_floors(ctx, FloorSequence((first, future)))[0]

    monkeypatch.setattr(ending_fixture, "save_map", save_whole)
    ending_fixture.to_defeat(runtime, token, scene=True)
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "sequence-first-floor-ending")
        assert reply.status_code == 200, reply.text
        assert reply.json()["game"]["score"]["score"] == 7
        assert reply.json()["game"]["record"]["cntArrivedNode"] == 3
    final = runtime.sync(token)
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == final
        assert rows(runtime.database.path) == saved
    finally:
        reopened.database.close()
