"""Configured WISH publication/transactions; explicit QA menus, no natural pool."""

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_capacity_relics import A40, add_capacity
from test_rogue_content_specs import wire
from test_rogue_gold_relics import R11, R12, R13
from test_rogue_resource_relics import Q28
from test_rogue_treasures import authored_treasure_tables, recipe
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_content, rogue_topics
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_reads import scope
from terralocal.server.gamedata.rogue_content_specs import POLICY, TREASURE_POLICY
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

pytest_plugins = ("test_rogue_resource_relics", "test_rogue_battle_loot")


def profile(data):
    value = wire(data)
    value["policy"] = TREASURE_POLICY
    for supply in value["supplies"]:
        supply["treasure"] = []
    for floor in value["floors"][:2]:
        floor["columns"][0]["pool"][0] = {"kind": "TREASURE", "weight": 1, "stage": None}
    value["supplies"][0]["treasure"] = [{"id": "history", "weight": 1, "content": recipe(items=(R13,))}]
    value["supplies"][1]["treasure"] = [{"id": "fate", "weight": 1, "content": recipe("fate", (Q28, R12))}]
    return value


@pytest.fixture
def treasure_runtime(resource_tables, monkeypatch, request):
    original = start_fixture.import_data
    def imported(folder, cache):
        path = folder / "roguelike_topic_table.json"
        tables = {"roguelike_topic_table": json.loads(path.read_bytes())}
        add_capacity(tables, monkeypatch)
        authored_treasure_tables(tables, monkeypatch)
        path.write_text(json.dumps(tables["roguelike_topic_table"]), "utf8")
        return original(folder, cache)
    monkeypatch.setattr(start_fixture, "import_data", imported)
    runtime, token = request.getfixturevalue("loot_boss_runtime")
    (runtime.settings.data_dir / "rogue_content.json").write_bytes(json.dumps(profile(runtime.data)).encode())
    runtime.database.close()
    configured = Runtime(runtime.settings)
    try:
        yield configured, token
    finally:
        configured.database.close()


def open_map(runtime, token, client):
    result = post(client, token, "finishEvent", {}, "treasure-open")
    assert result.status_code == 200, result.text


def select(client, token, choice, key):
    return post(client, token, "selectChoice", {"choice": choice}, key)


def enter(runtime, token, client, key="treasure-enter"):
    result = post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, key)
    assert result.status_code == 200, result.text
    return current(runtime, token)["player"]["pending"][0]


def test_snapshot_validates_frozen_content_once_per_projection(treasure_runtime, monkeypatch):
    runtime, token = treasure_runtime
    with TestClient(create_game_app(runtime)) as client:
        open_map(runtime, token, client)
        enter(runtime, token, client)
    saved = rows(runtime.database.path)
    allocate, calls = rogue_content.allocate, []

    def count(data, run, source):
        calls.append(run.id)
        return allocate(data, run, source)

    monkeypatch.setattr(rogue_content, "allocate", count)
    with runtime.database.transaction(write=False) as session:
        run = session.query(m.RogueTopicRun).one()
        ctx = Context(session, runtime.data, run.account_id)
        expected = rogue_topics.snapshot.__wrapped__(ctx)
        assert len(calls) > 1
        calls.clear()
        for _ in range(2):
            assert rogue_topics.snapshot(ctx) == expected
            assert calls == [run.id]
            calls.clear()
    assert rows(runtime.database.path) == saved


@pytest.mark.parametrize("damage", ["in-place-plan", "in-place-graph", "orm-digest"])
def test_frozen_content_reuse_rejects_changed_inputs(treasure_runtime, damage):
    runtime, token = treasure_runtime
    with TestClient(create_game_app(runtime)) as client:
        open_map(runtime, token, client)
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError, match="持久绑定"), runtime.database.transaction() as session:
        run = session.query(m.RogueTopicRun).one()
        draft = session.get(m.RogueMapDraft, run.id)
        ctx = Context(session, runtime.data, run.account_id)
        with scope(ctx):
            rogue_content.validate(runtime.data, run, draft)
            if damage == "in-place-plan":
                draft.plan["source"]["evidence"] += " changed"
            elif damage == "in-place-graph":
                draft.graph["zones"].pop("1")
            else:
                draft.plan_hash = "0" * 64
            rogue_content.validate(runtime.data, run, draft)
    assert rows(runtime.database.path) == saved


def test_history_and_fate_publish_transact_advance_restart_and_restore(treasure_runtime):
    runtime, token = treasure_runtime
    with TestClient(create_game_app(runtime)) as client:
        open_map(runtime, token, client)
        pending = enter(runtime, token, client)
        assert pending["type"] == "SCENE" and pending["content"]["scene"]["id"] == "scene_treasure1_enter"
        assert pending["content"]["scene"]["choices"] == {"choice_treasure1_1": True}
        gold = current(runtime, token)["player"]["property"]["gold"]
        before = runtime.sync(token)["user"]
        reply = select(client, token, "choice_treasure1_1", "history-choose")
        assert reply.status_code == 200, reply.text
        assert apply(before, reply.json()["playerDataDelta"]) == runtime.sync(token)["user"]
        assert current(runtime, token)["player"]["property"]["gold"] == gold + 25
        saved = rows(runtime.database.path)
        assert select(client, token, "choice_treasure1_1", "history-choose").json() == reply.json()
        assert rows(runtime.database.path) == saved
        assert select(client, token, "choice_treasure1_1", "history-retry").status_code == 200
        assert current(runtime, token)["player"]["property"]["gold"] == gold + 25
        assert select(client, token, "choice_leave", "history-leave").status_code == 200
        assert current(runtime, token)["player"]["cursor"]["zone"] == 2
        fate = enter(runtime, token, client, "fate-enter")
        assert set(fate["content"]["scene"]["choices"]) == {"choice_treasure2_1", "choice_treasure2_2"}
        reply = select(client, token, "choice_treasure2_1", "fate-choose")
        assert reply.status_code == 200, reply.text
        saved = rows(runtime.database.path)
        assert select(client, token, "choice_treasure2_2", "fate-other").status_code == 409
        assert rows(runtime.database.path) == saved
        inventory = list(current(runtime, token)["inventory"]["relic"].values())
        assert [r["id"] for r in inventory[1:]] == [R13, Q28] and all(r["layer"] == 0 for r in inventory)
        assert current(runtime, token)["player"]["property"]["gold"] == gold + 25
        assert select(client, token, "choice_leave", "fate-leave").status_code == 200
        assert current(runtime, token)["player"]["cursor"]["zone"] == 3
    expected, saved = runtime.sync(token)["user"], rows(runtime.database.path)
    (runtime.settings.data_dir / "rogue_content.json").unlink()
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected
        backups = BackupService(reopened)
        backups.restore(backups.create()["name"])
        assert reopened.sync(token)["user"] == expected and rows(reopened.database.path) == saved
    finally:
        reopened.database.close()


def test_capacity_and_shared_reservations_are_applied_once(treasure_runtime):
    runtime, token = treasure_runtime
    value = profile(runtime.data)
    value["supplies"][0]["treasure"][0]["content"] = recipe(items=(A40,))
    runtime.data.rogue_content_source = json.dumps(value).encode()
    with TestClient(create_game_app(runtime)) as client:
        open_map(runtime, token, client)
        enter(runtime, token, client)
        before = current(runtime, token)["player"]["property"]["capacity"]
        result = select(client, token, "choice_treasure1_1", "capacity")
        assert result.status_code == 200, result.text
        assert current(runtime, token)["player"]["property"]["capacity"] == before + 3
        assert select(client, token, "choice_treasure1_1", "capacity-again").status_code == 200
        assert current(runtime, token)["player"]["property"]["capacity"] == before + 3


def test_fate_unselected_branch_and_battle_plan_cannot_reserve_same_relic(treasure_runtime):
    runtime, token = treasure_runtime
    value = profile(runtime.data)
    value["supplies"][2]["battle"] = [{"id": "conflict", "weight": 1, "content": {
        "groups": [[R12]], "eligibility": [R12], "evidence": "Explicit QA overlap with unchosen fate alternative"}}]
    runtime.data.rogue_content_source = json.dumps(value).encode()
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "finishEvent", {}, "overlap")
        assert result.status_code == 503
    assert rows(runtime.database.path) == before


def test_concurrent_scene_choices_award_gold_once(treasure_runtime):
    runtime, token = treasure_runtime
    with TestClient(create_game_app(runtime)) as client:
        open_map(runtime, token, client)
        enter(runtime, token, client)
    gold = current(runtime, token)["player"]["property"]["gold"]
    def choose(i):
        with TestClient(create_game_app(runtime)) as client:
            return select(client, token, "choice_treasure1_1", "concurrent-" + str(i)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(choose, (1, 2))) == [200, 200]
    assert current(runtime, token)["player"]["property"]["gold"] == gold + 25


@pytest.mark.parametrize("damage", ["row-kind", "outcome", "missing", "gold", "inventory"])
def test_treasure_tampering_is_rejected_before_startup_writes(treasure_runtime, damage):
    runtime, token = treasure_runtime
    with TestClient(create_game_app(runtime)) as client:
        open_map(runtime, token, client)
        enter(runtime, token, client)
        assert select(client, token, "choice_treasure1_1", "claim").status_code == 200
    with runtime.database.transaction() as session:
        row = session.query(m.RogueSceneVisit).filter_by(zone_index=1).one()
        if damage == "row-kind":
            row.program_id = "rogue1-fixed-gold"
        elif damage == "outcome":
            draft = session.query(m.RogueMapDraft).one()
            value = copy.deepcopy(draft.plan)
            value["source"]["supplies"][0]["treasure"][0]["content"]["rewards"][0]["item"] = R11
            draft.plan = value
        elif damage == "missing":
            session.delete(row)
        elif damage == "gold":
            session.query(m.RogueTopicRun).one().gold -= 1
        else:
            session.query(m.RogueRunRelic).filter_by(item_id=R13).one().item_id = R11
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def test_v1_recipe_cannot_silently_acquire_new_treasure_node_semantics(treasure_runtime):
    runtime, token = treasure_runtime
    value = profile(runtime.data)
    value["policy"] = POLICY
    for supply in value["supplies"]:
        supply.pop("treasure")
    runtime.data.rogue_content_source = json.dumps(value).encode()
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "wrong-version").status_code == 503
    assert rows(runtime.database.path) == saved
