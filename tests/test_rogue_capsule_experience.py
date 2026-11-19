"""One-use battle EXP capsules across outcomes, retries and crash recovery."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
import test_rogue_training as training_fixture
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_battle_loot import finish_new
from test_rogue_floor_progress import journal, scene
from test_rogue_recruit_costs import R25, R26
from test_rogue_settlement import complete
from test_roguelike_battle_start import begin, body
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_settlement
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_floors import FloorSequence
from terralocal.server.domain.rogue_loot_plans import prepare
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_map_drafts import prepare_floors
from terralocal.server.domain.rogue_visits import prepare as save_scenes
from terralocal.server.gamedata import rogue_capsules as rules
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_battle_loot import RelicGroups
from terralocal.server.gamedata.rogue_rewards import FirstThemeBattleRewards
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

pytest_plugins = ("test_rogue_capsules",)
C3 = "rogue_1_capsule_3"


@pytest.fixture
def battle_capsule_runtime(monkeypatch, request):
    original = training_fixture.import_data

    def imported(folder, cache):
        path = folder / "roguelike_topic_table.json"
        table = json.loads(path.read_bytes())
        detail = table["details"]["rogue_1"]
        item = {"id": C3, "type": "CAPSULE", "subType": "NONE", "name": "Authored EXP capsule",
                "usage": "Authored double battle EXP fixture", "description": "No official data"}
        capsule = {"itemId": C3, "maskType": "BATTLES", "innerColor": "ffffff"}
        detail["items"][C3] = item
        detail.setdefault("capsuleDict", {})[C3] = capsule
        monkeypatch.setattr(rules, "EXP_SOURCES", {C3: (fingerprint(item), fingerprint(capsule))})
        path.write_text(json.dumps(table), "utf8")
        return original(folder, cache)

    monkeypatch.setattr(training_fixture, "import_data", imported)
    return request.getfixturevalue("capsule_runtime")


def configured(runtime, token, kind="BATTLE_NORMAL"):
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), Plan("zone_1", tuple(
            Column(1, 1, (Entry(k, 1, stage),)) for k, stage in (
                ("BATTLE_NORMAL", "ordinary"), (kind, "emergency" if kind == "BATTLE_ELITE" else "ordinary"),
                ("BATTLE_NORMAL", "ordinary"), ("SHOP", None))), 0))
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "finishEvent", {}, "exp-map")
        assert result.status_code == 200, result.text
    with runtime.database.transaction() as session:
        sources = {
            Point(0, 0): RelicGroups((), frozenset(), "Authored EXP capsule", C3),
            Point(1, 0): RelicGroups(((R25,),), frozenset({R25}), "Authored full reward plan"),
            Point(2, 0): RelicGroups(((R26,),), frozenset({R26}), "Authored later reward plan"),
        }
        prepare(Context(session, runtime.data, 1), sources)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client, key="source")
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "get-exp").status_code == 200
        assert post(client, token, "finishBattleReward", {}, "source-leave").status_code == 200


def start_next(client, token, stage="ordinary"):
    payload = body(stage)
    payload["to"]["x"] = 1
    payload["squad"]["slots"] = [{"charInstId": 1, "skillIndex": 1, "currentEquip": None}]
    return begin(client, token, payload, key="exp-battle")


def finish_started(runtime, client, token, battle_id, stage, rank, key):
    with runtime.database.transaction(write=False) as session:
        hp = session.query(m.RogueTopicRun).one().hp + runtime.data.rogue_initial.battle_temporary_hp
    trace = journal()
    trace["journal"]["squad"] = trace["journal"]["squad"][:1]
    trace["journal"]["metadata"]["stageId"] = stage
    return complete(client, token, battle_id, trace, hp if rank == 3 else 1 if rank == 2 else 0,
                    key, stageId=stage, completeState=rank, percent=100 if rank != 1 else 2)


@pytest.mark.parametrize("kind,stage", [("BATTLE_NORMAL", "ordinary"), ("BATTLE_ELITE", "emergency")])
@pytest.mark.parametrize("rank", [3, 2, 1])
def test_battle_capsule_activates_once_and_only_doubles_successful_exp(battle_capsule_runtime, kind, stage, rank):
    runtime, token = battle_capsule_runtime
    configured(runtime, token, kind)
    with runtime.database.transaction(write=False) as session:
        before_exp = session.query(m.RogueTopicRun).one().exp
    with TestClient(create_game_app(runtime)) as client:
        result = start_next(client, token, stage)
        assert result.status_code == 200, result.text
        battle_id = result.json()["battleId"]
        active = current(runtime, token)
        assert active["buff"]["capsule"]["id"] == C3 and active["buff"]["capsule"]["active"] is True
        reopened = Runtime(runtime.settings)
        try:
            assert current(reopened, token) == active
        finally:
            reopened.database.close()
        before = runtime.sync(token)["user"]
        result = finish_started(runtime, client, token, battle_id, stage, rank, "exp-finish")
        assert result.status_code == 200, result.text
        after = runtime.sync(token)["user"]
        assert apply(before, result.json()["playerDataDelta"]) == after
        state = current(runtime, token)
        assert state["buff"]["capsule"] is None
        gain = FirstThemeBattleRewards(runtime.data).base(topic="rogue_1", mode="NORMAL", grade=0,
                    zone="zone_1", kind=kind, stage=stage).exp * 2 if rank != 1 else 0
        with runtime.database.transaction(write=False) as session:
            run = session.query(m.RogueTopicRun).one()
            settlement = session.get(m.RogueBattleSettlement, battle_id)
            assert run.exp == before_exp + gain and settlement.effects["earn"]["exp"] == gain
        saved = rows(runtime.database.path)
        assert finish_started(runtime, client, token, battle_id, stage, rank, "exp-finish").json() == result.json()
        assert rows(runtime.database.path) == saved
        assert finish_started(runtime, client, token, battle_id, stage, rank, "exp-finish-new-seq").status_code == 200
        assert current(runtime, token) == state
        if kind == "BATTLE_NORMAL" and rank == 3:
            assert post(client, token, "finishBattleReward", {}, "exp-leave").status_code == 200
            third = finish_new(runtime, token, client, x=2, key="ordinary-again")
            assert third["earn"]["exp"] * 2 == gain
            assert current(runtime, token)["buff"]["capsule"] is None
    users, raw = copy.deepcopy(runtime.sync(token)["user"]), rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == users
        backup = BackupService(reopened)
        backup.restore(backup.create()["name"])
        assert reopened.sync(token)["user"] == users and rows(runtime.database.path) == raw
    finally:
        reopened.database.close()


def test_doubled_level_effect_is_checked_before_start_without_spending_capsule(battle_capsule_runtime, monkeypatch):
    runtime, token = battle_capsule_runtime
    configured(runtime, token)
    with runtime.database.transaction(write=False) as session:
        old_exp = session.query(m.RogueTopicRun).one().exp
    base = FirstThemeBattleRewards(runtime.data).base(topic="rogue_1", mode="NORMAL", grade=0,
                zone="zone_1", kind="BATTLE_NORMAL", stage="ordinary").exp
    original = runtime.data.rogue_levels.gains

    def unsupported(old, new):
        result = original(old, new)
        return replace(result, max_hp=1) if old == old_exp and new == old + base * 2 else result

    monkeypatch.setattr(runtime.data.rogue_levels, "gains", unsupported)
    before, raw = current(runtime, token), rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        result = start_next(client, token)
        assert result.status_code == 501 and result.json()["error"]["code"] == "ROGUE_LEVEL_EFFECT"
    assert current(runtime, token) == before and rows(runtime.database.path) == raw


def test_capsule_finish_rollback_keeps_active_battle_and_unearned_exp(battle_capsule_runtime):
    runtime, token = battle_capsule_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        result = start_next(client, token)
        assert result.status_code == 200
        battle_id = result.json()["battleId"]
        before, raw = runtime.sync(token)["user"], rows(runtime.database.path)
        with pytest.MonkeyPatch.context() as patch:
            def fail():
                raise DomainError("INJECTED", "rollback EXP capsule")
            patch.setattr(rogue_settlement, "response", fail)
            result = finish_started(runtime, client, token, battle_id, "ordinary", 3, "rollback-finish")
            assert result.status_code == 400
        assert runtime.sync(token)["user"] == before and rows(runtime.database.path) == raw


def test_saved_doubled_experience_tampering_is_cold_rejected(battle_capsule_runtime):
    runtime, token = battle_capsule_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client, x=1, key="exp")
    with runtime.database.transaction() as session:
        settlement = session.query(m.RogueBattleSettlement).order_by(m.RogueBattleSettlement.ordinal.desc()).first()
        value = copy.deepcopy(settlement.effects)
        value["earn"]["exp"] += 1
        settlement.effects = value
    runtime.database.close()
    before = rows(runtime.database.path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before


def test_ambiguous_legacy_gold_is_rejected_before_capsule_battle_starts(battle_capsule_runtime):
    runtime, token = battle_capsule_runtime
    configured(runtime, token)
    with runtime.database.transaction() as session:
        run = session.query(m.RogueTopicRun).one()
        session.delete(session.get(m.RogueBattleLootPlan, (run.id, 1, 1, 0)))
    before, raw = current(runtime, token), rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        result = start_next(client, token)
        assert result.status_code == 503 and result.json()["error"]["code"] == "ROGUE_GOLD_ITEM"
    assert current(runtime, token) == before and rows(runtime.database.path) == raw


def test_concurrent_finishes_cannot_duplicate_the_exp_gain(battle_capsule_runtime):
    runtime, token = battle_capsule_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        started = start_next(client, token)
        assert started.status_code == 200
    battle_id = started.json()["battleId"]
    with runtime.database.transaction(write=False) as session:
        old_exp = session.query(m.RogueTopicRun).one().exp
    other = Runtime(runtime.settings)
    try:
        def attempt(candidate):
            with TestClient(create_game_app(candidate)) as client:
                return finish_started(candidate, client, token, battle_id, "ordinary", 3, "concurrent-exp")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, (runtime, other)))
        assert all(r.status_code == 200 for r in results)
        assert results[0].json() == results[1].json()
        with runtime.database.transaction(write=False) as session:
            settlement = session.get(m.RogueBattleSettlement, battle_id)
            assert session.query(m.RogueTopicRun).one().exp == old_exp + settlement.effects["earn"]["exp"]
            assert session.query(m.RogueBattleSettlement).count() == 2
    finally:
        other.database.close()


@pytest.fixture
def capsule_boss_runtime(cost_tables, monkeypatch, request):
    original = start_fixture.import_data

    def imported(folder, cache):
        path = folder / "roguelike_topic_table.json"
        table = json.loads(path.read_bytes())
        detail = table["details"]["rogue_1"]
        item = {"id": C3, "type": "CAPSULE", "subType": "NONE", "name": "Authored EXP capsule"}
        capsule = {"itemId": C3, "maskType": "BATTLES", "innerColor": "ffffff"}
        detail["items"][C3] = item
        detail.setdefault("capsuleDict", {})[C3] = capsule
        monkeypatch.setattr(rules, "EXP_SOURCES", {C3: (fingerprint(item), fingerprint(capsule))})
        path.write_text(json.dumps(table), "utf8")
        path = folder / "terralocal_rogue_placements.json"
        placements = json.loads(path.read_bytes())
        placements["regions"]["ordinary"] = ["zone_1", "zone_3", "zone_5"]
        path.write_text(json.dumps(placements), "utf8")
        return original(folder, cache)

    monkeypatch.setattr(start_fixture, "import_data", imported)
    return request.getfixturevalue("boss_runtime")


@pytest.mark.parametrize("number,stage", [(3, "ro1_b_1"), (5, "ro1_b_6")])
def test_capsule_covers_middle_and_default_terminal_boss(capsule_boss_runtime, number, stage):
    runtime, token = capsule_boss_runtime
    sequence = FloorSequence(tuple(Plan("zone_" + str(i), tuple(
        Column(1, 1, (entry,)) for entry in (
            (Entry("BATTLE_NORMAL", 1, "ordinary"), Entry("BATTLE_BOSS", 1, stage))
            if i == number else (Entry("INCIDENT", 1),))), 0) for i in range(1, 6)))
    with runtime.database.transaction() as session:
        prepare_floors(Context(session, runtime.data, 1), sequence)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "boss-exp-map").status_code == 200
    with runtime.database.transaction() as session:
        for i in range(1, number):
            save_scenes(Context(session, runtime.data, 1), {Point(0, 0): "rogue1-fixed-gold"}, zone_index=i)
        sources = {Point(0, 0): RelicGroups((), frozenset(), "Authored same-floor EXP capsule", C3)}
        if number == 3:
            sources[Point(1, 0)] = RelicGroups(((R25,),), frozenset({R25}), "Authored middle boss")
        prepare(Context(session, runtime.data, 1), sources, zone_index=number)
    with TestClient(create_game_app(runtime)) as client:
        for i in range(1, number):
            assert scene(client, token, "exp-floor-" + str(i)).status_code == 200
        finish_new(runtime, token, client, key="boss-capsule-source")
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "boss-capsule").status_code == 200
        assert post(client, token, "finishBattleReward", {}, "boss-capsule-close").status_code == 200
        with runtime.database.transaction(write=False) as session:
            old_exp = session.query(m.RogueTopicRun).one().exp
        started = start_next(client, token, stage)
        assert started.status_code == 200, started.text
        assert current(runtime, token)["buff"]["capsule"]["active"]
        result = finish_started(runtime, client, token, started.json()["battleId"], stage, 3, "boss-exp-finish")
        assert result.status_code == 200, result.text
        gain = FirstThemeBattleRewards(runtime.data).base(topic="rogue_1", mode="NORMAL", grade=0,
            zone="zone_" + str(number), kind="BATTLE_BOSS", stage=stage).exp * 2
        with runtime.database.transaction(write=False) as session:
            settlement = session.get(m.RogueBattleSettlement, started.json()["battleId"])
            assert session.query(m.RogueTopicRun).one().exp == old_exp + gain
            assert settlement.effects["earn"]["exp"] == gain
        state = current(runtime, token)
        assert state["buff"]["capsule"] is None
        if number == 5:
            assert state["player"]["pending"][0]["content"]["result"]["record"]["capsuleList"] == [C3]
    reopened = Runtime(runtime.settings)
    try:
        assert current(reopened, token) == state
    finally:
        reopened.database.close()
