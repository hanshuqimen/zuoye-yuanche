"""Authored HTTP boundaries for deployment unlocks; zero native stage replays."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_native_battle_finish import encoded
from test_native_replay import packed
from test_rogue_battle_codec import snapshot
from test_rogue_boss_ending import boss_runtime as boss_runtime
from test_rogue_boss_ending import completion_catalog as completion_catalog
from test_rogue_boss_ending import completion_runtime as completion_runtime
from test_rogue_boss_ending import ending_runtime as ending_runtime
from test_rogue_boss_ending import prepare_boss, restart_authored_run
from test_rogue_boss_ending import reward_catalog as reward_catalog
from test_rogue_boss_ending import reward_runtime as reward_runtime
from test_rogue_boss_ending import rogue_battle_runtime as rogue_battle_runtime
from test_rogue_boss_ending import shop_ending_runtime as shop_ending_runtime
from test_rogue_boss_ending import variant_catalog as variant_catalog
from test_rogue_boss_ending import variant_runtime as variant_runtime
from test_rogue_boss_ending import visits_runtime as visits_runtime
from test_rogue_deployment_goals import add_deployment_conditions
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_combat_records, rogue_ending
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_completion_rewards import DEPLOYMENT_POLICY, VARIANT_POLICY
from terralocal.server.gamedata.rogue_deployment_goals import GOALS
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.rogue_battle_codec import decode_char_stats
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def deployment_catalog(variant_catalog, monkeypatch):
    original = start_fixture.import_data
    def imported(folder, destination):
        path = folder / "roguelike_topic_table.json"
        value = json.loads(path.read_bytes())
        add_deployment_conditions(value["details"]["rogue_1"])
        path.write_text(json.dumps(value), "utf8")
        return original(folder, destination)
    monkeypatch.setattr(start_fixture, "import_data", imported)


@pytest.fixture
def deployment_runtime(deployment_catalog, variant_runtime):
    return variant_runtime


def counter_row(n, kind="SPAWN"):
    return {"Key": {"charId": "char_six", "counterType": kind}, "Value": n}


def pending(runtime, token, n, prefix="", *, rank=3):
    battle_id, trace = prepare_boss(runtime, token, prefix)
    hp = current(runtime, token)["player"]["property"]["hp"]["current"] + runtime.data.rogue_initial.battle_temporary_hp
    payload = encoded(battle_id, state=rank, changes={"stageId": "ro1_b_6", "percent": 100 if rank != 1 else 2,
                                                   "interrupt": 0},
        trace_changes={"stats": {"leftHp": hp if rank != 1 else 0,
            "charStats": None if n is None else [counter_row(n), counter_row(300, "DEAD"), counter_row(7, "WITHDRAW")]}})
    payload |= {"battleLog": packed(trace), "rlv2Data": {"battleSnapshot": snapshot()}}
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "battleFinish", payload, prefix + "finish")
        assert result.status_code == 200, result.text


@pytest.mark.parametrize("n,expected", [(99, set()), (100, {"rogue_1_relic_sp04"}),
    (199, {"rogue_1_relic_sp04"}), (200, set(GOALS))])
def test_success_thresholds_notification_delta_retry_and_restore(deployment_runtime, n, expected):
    runtime, token = deployment_runtime
    pending(runtime, token, n)
    before = runtime.sync(token)["user"]
    assert all(before["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][key]["state"] == 0 for key in GOALS)
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "gameSettle", {}, "deploy-first")
        assert result.status_code == 200, result.text
        result = result.json()
        after = runtime.sync(token)["user"]
        assert apply(before, result["playerDataDelta"]) == after
        assert set(result["outer"]["relicUnlock"]) & GOALS.keys() == expected
        assert len(result["outer"]["relicUnlock"]) == 21 + len(expected)
        assert result["outer"]["relicBp"]["cnt"] == 25 * (21 + len(expected))
        assert post(client, token, "gameSettle", {}, "deploy-first").json() == result
        retry = post(client, token, "gameSettle", {}, "deploy-again").json()
        assert retry["outer"] == result["outer"] and runtime.sync(token)["user"] == after
    with runtime.database.transaction(write=False) as session:
        row = session.query(m.RogueGameSettlement).one()
        assert row.policy_version == DEPLOYMENT_POLICY
        assert row.facts["combat"]["minimum"] == n and row.facts["combat"]["unknown"] == 0
        assert len(row.facts["combat"]["battles"]) == 1
        assert session.query(m.RogueRunRelic).count() == 1  # Eligibility never creates an item.
    assert {key for key in GOALS if after["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][key]["state"] == 1} == expected
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after
        backups = BackupService(reopened)
        backups.restore(backups.create()["name"])
        assert rows(runtime.database.path) == saved and reopened.sync(token)["user"] == after
    finally:
        reopened.database.close()


def test_independent_successes_cannot_combine_their_deployments(deployment_runtime):
    runtime, token = deployment_runtime
    pending(runtime, token, 99)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "gameSettle", {}, "first").status_code == 200
    restart_authored_run(runtime, token)
    pending(runtime, token, 99, "next-")
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "gameSettle", {}, "second")
        assert result.status_code == 200, result.text
        assert result.json()["outer"]["relicUnlock"] == []
    relics = runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["relic"]
    assert all(relics[key]["state"] == 0 for key in GOALS)


def test_older_v8_success_is_immutable_and_suppresses_retrospective_deployment_rewards(deployment_runtime, monkeypatch):
    runtime, token = deployment_runtime
    pending(runtime, token, 200)
    with monkeypatch.context() as patch:
        patch.setattr(rogue_ending, "deployments_available", lambda data: False)
        with TestClient(create_game_app(runtime)) as client:
            original = post(client, token, "gameSettle", {}, "old-v8").json()
    assert not set(original["outer"]["relicUnlock"]) & GOALS.keys()
    with runtime.database.transaction(write=False) as session:
        old = session.query(m.RogueGameSettlement).one()
        assert old.policy_version == VARIANT_POLICY and "combat" not in old.facts
        ident, facts, rule, response = old.run_id, copy.deepcopy(old.facts), old.rule_hash, copy.deepcopy(old.response)
    restart_authored_run(runtime, token)
    pending(runtime, token, 200, "next-")
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "new-v9")
        assert reply.status_code == 200, reply.text
        assert reply.json()["outer"]["relicUnlock"] == []
        assert reply.json()["outer"]["relicBp"]["cnt"] == 0
    with runtime.database.transaction(write=False) as session:
        old = session.get(m.RogueGameSettlement, ident)
        assert (old.facts, old.rule_hash, old.response) == (facts, rule, response)
        assert session.query(m.RogueGameSettlement).filter_by(policy_version=DEPLOYMENT_POLICY).count() == 1


def test_deployment_notice_and_rewards_roll_back_as_one_transaction(deployment_runtime):
    runtime, token = deployment_runtime
    pending(runtime, token, 200)
    stable = rows(runtime.database.path)
    before = runtime.sync(token)["user"]
    def fail(ctx):
        rogue_ending.settle(ctx)
        raise DomainError("INJECTED", "rollback deployment goals")
    with pytest.raises(DomainError, match="rollback deployment goals"):
        runtime.mutate(token, None, "deployment-rollback", "qa-deployment", {}, fail)
    assert rows(runtime.database.path) == stable and runtime.sync(token)["user"] == before
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "gameSettle", {}, "deployment-valid").status_code == 200


def test_rehashed_counter_edit_cannot_rewrite_an_already_confirmed_ending(deployment_runtime):
    runtime, token = deployment_runtime
    pending(runtime, token, 99)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "gameSettle", {}, "valid").status_code == 200
    with runtime.database.transaction() as session:
        battle = session.query(m.RogueBattle).one()
        row = session.query(m.RogueBattleSettlement).one()
        counters = decode_char_stats({"charStats": [counter_row(200)]})
        value = rogue_combat_records.archive(counters, battle_id=battle.id, run_id=battle.run_id,
                                              gamedata_hash=battle.gamedata_hash, facts=row.facts)
        row.records = row.records | {"counters": value}
    corrupt = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == corrupt


@pytest.mark.parametrize("n,rank,minimum,unknown", [(200, 1, 200, 0), (None, 3, 0, 1)])
def test_defeat_or_missing_counter_success_cannot_grant_deployment_goals(deployment_runtime, n, rank, minimum, unknown):
    runtime, token = deployment_runtime
    pending(runtime, token, n, rank=rank)
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "gameSettle", {}, "no-deployment-award")
        assert result.status_code == 200, result.text
        assert not set(result.json()["outer"]["relicUnlock"]) & GOALS.keys()
    with runtime.database.transaction(write=False) as session:
        row = session.query(m.RogueGameSettlement).one()
        assert (row.facts["combat"]["minimum"], row.facts["combat"]["unknown"]) == (minimum, unknown)


def test_concurrent_acknowledgements_grant_new_deployment_unlocks_only_once(deployment_runtime):
    runtime, token = deployment_runtime
    pending(runtime, token, 200)
    other = Runtime(runtime.settings)
    def acknowledge(instance):
        with TestClient(create_game_app(instance)) as client:
            result = post(client, token, "gameSettle", {}, "concurrent-deployment")
            assert result.status_code == 200, result.text
            return result.json()
    try:
        with ThreadPoolExecutor(2) as pool:
            first, second = pool.map(acknowledge, (runtime, other))
        assert first == second and set(first["outer"]["relicUnlock"]) & GOALS.keys() == set(GOALS)
        with runtime.database.transaction(write=False) as session:
            row = session.query(m.RogueGameSettlement).one()
            assert row.after["bp"] == 439 + 23 * 25
            assert row.facts["combat"]["minimum"] == 200
    finally:
        other.database.close()
