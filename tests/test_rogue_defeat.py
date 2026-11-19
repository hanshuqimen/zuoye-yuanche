"""Authored analogue of native v16 defeat; native bytes remain outside Git."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_rogue_settlement import complete, prepared
from test_roguelike_battle_start import body
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_settlement
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def defeat(client, token, battle_id, journal, key="defeat"):
    # v16 observed rank1/non-interrupt/non-giveUp, percent2, validKills1,
    # leftHp0 and no actionKill rows. Do not substitute ordinary rank rules.
    return complete(client, token, battle_id, journal, 0, key,
        completeState=1, interrupt=0, giveUp=0, percent=2, killCnt=1, validKillCnt=1)


def test_natural_defeat_persists_zero_hp_ending_event_and_never_clear_rewards(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, _ = prepared(runtime, token)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        reply = defeat(client, token, battle_id, journal)
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        assert {k: v for k, v in before.items() if k != "rlv2"} == {
            k: v for k, v in after.items() if k != "rlv2"}
        state = after["rlv2"]["current"]
        props = state["player"]["property"]
        old_props = before["rlv2"]["current"]["player"]["property"]
        assert props == old_props | {"hp": {"current": 0, "max": old_props["hp"]["max"]}}
        assert state["player"]["state"] == "PENDING"
        pending = state["player"]["pending"]
        assert len(pending) == 1 and pending[0]["type"] == "GAME_SETTLE"
        brief = pending[0]["content"]["result"]["brief"]
        assert brief["success"] == 0 and brief["ending"] is None and brief["endZoneId"] == "zone_1"
        assert pending[0]["content"]["result"]["record"]["cntZone"] == 1
        for key in ("defeat", "new-defeat-sequence"):
            assert defeat(client, token, battle_id, journal, key).status_code == 200
        assert current(runtime, token) == state
        assert post(client, token, "chooseBattleReward", {"index": 0, "sub": 0}, "no-gold").status_code == 409
        assert post(client, token, "finishBattleReward", {}, "no-skip").status_code == 409
        assert post(client, token, "moveAndBattleStart", body(), "dead-start").status_code == 409
        assert post(client, token, "finishEvent", {}, "wrong-event").status_code == 409
    with runtime.database.transaction(write=False) as session:
        row = session.query(m.RogueBattleSettlement).one()
        assert row.loot == row.claims == [] and row.effects["outcome"] == "DEFEAT"
        assert row.completed_at is None and session.query(m.RogueBattle).one().state == "FINISHED"
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert current(reopened, token) == state
        service = BackupService(reopened)
        backup = service.create()
        service.restore(backup["name"])
        assert rows(runtime.database.path) == saved
    finally:
        reopened.database.close()


def test_close_after_defeat_preserves_pending_ending_without_reward_ack(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, _ = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert defeat(client, token, battle_id, journal).status_code == 200
        before = runtime.sync(token)["user"]
        for key in ("abandon", "abandon", "new-abandon-sequence"):
            reply = post(client, token, "giveUpGame", {}, key)
            assert reply.status_code == 200, reply.text
            assert apply(before, reply.json()["playerDataDelta"]) == before
            assert runtime.sync(token)["user"] == before
        assert post(client, token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0},
                    "cannot-replace-pending").status_code == 409
    reopened = Runtime(runtime.settings)
    try:
        with reopened.database.transaction(write=False) as session:
            run = session.query(m.RogueTopicRun).one()
            assert run.state == "MAP_READY" and run.ended_at is None
            assert session.query(m.RogueBattleSettlement).one().effects["outcome"] == "DEFEAT"
            assert session.query(m.RogueGameSettlement).count() == 0
        assert reopened.sync(token)["user"] == before
        saved = rows(reopened.database.path)
        service = BackupService(reopened)
        backup = service.create()
        service.restore(backup["name"])
        assert rows(reopened.database.path) == saved
        assert reopened.sync(token)["user"] == before
    finally:
        reopened.database.close()


def test_legacy_perfect_policy_replays_its_original_effect_shape(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert complete(client, token, battle_id, journal, hp).status_code == 200
    with runtime.database.transaction() as session:
        row = session.query(m.RogueBattleSettlement).one()
        run = session.query(m.RogueTopicRun).one()
        battle = session.query(m.RogueBattle).one()
        effects, loot, rule = rogue_settlement.compute(runtime.data, run, battle, "zone_1", "BATTLE_NORMAL",
            row.effects["before"], row.facts, policy=rogue_settlement.POLICY)
        assert "outcome" not in effects and "isPerfect" not in effects
        row.effects, row.loot, row.rule_hash, row.policy_version = effects, loot, rule, rogue_settlement.POLICY
    reopened = Runtime(runtime.settings)
    reopened.database.close()


@pytest.mark.parametrize("left_hp,permanent", [(7, 4), (4, 4), (3, 3), (1, 1)])
def test_rank2_clear_consumes_buffer_before_permanent_hp_and_keeps_rewards(rogue_battle_runtime, left_hp, permanent):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, _ = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        reply = complete(client, token, battle_id, journal, left_hp, "damaged", completeState=2)
        assert reply.status_code == 200, reply.text
        state = current(runtime, token)
        assert state["player"]["property"]["hp"]["current"] == permanent
        assert state["player"]["property"]["exp"] == 0
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueTopicRun).one().exp == 10
        reward = state["player"]["pending"][0]["content"]["battleReward"]
        assert reward["isPerfect"] == 0 and reward["earn"]["hp"] == permanent - 4
        assert len(reward["rewards"]) == 2 and not any(r["done"] for r in reward["rewards"])
    if left_hp == 3:
        reopened = Runtime(runtime.settings)
        try:
            assert current(reopened, token) == state
        finally:
            reopened.database.close()


@pytest.mark.parametrize("rank,left_hp", [(2, 8), (2, 0), (3, 7), (3, 9), (1, 1)])
def test_inconsistent_rank_and_life_do_not_commit_an_outcome(rogue_battle_runtime, rank, left_hp):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, _ = prepared(runtime, token)
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        reply = complete(client, token, battle_id, journal, left_hp, "conflicting", completeState=rank)
        assert reply.status_code == 501, reply.text
    assert rows(runtime.database.path) == before


def test_unused_buffer_cannot_heal_a_previously_damaged_exploration(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    prepared(runtime, token)
    with runtime.database.transaction(write=False) as session:
        run = session.query(m.RogueTopicRun).one()
        battle = session.query(m.RogueBattle).one()
        before = rogue_settlement.initial(runtime.data, run) | {"hp": 2}
        facts = {"rank": 2, "interrupt": False, "giveUp": False, "percent": 100,
                 "kills": 1, "validKills": 1, "duration": 20, "leftHp": 5,
                 "snapshot": "a" * 64, "journal": "b" * 64}
        effects, _, _ = rogue_settlement.compute(runtime.data, run, battle, "zone_1", "BATTLE_NORMAL", before, facts)
        assert effects["after"]["hp"] == 2 and effects["earn"]["hp"] == 0


@pytest.mark.parametrize("damage", ["hp", "loot", "outcome", "policy"])
def test_modified_defeat_cannot_turn_into_victory_or_loot_on_restart(rogue_battle_runtime, damage):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, _ = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert defeat(client, token, battle_id, journal).status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        if damage == "hp":
            con.execute("UPDATE rlv2_runs SET hp=1")
        elif damage == "loot":
            con.execute("UPDATE rlv2_battle_settlements SET loot=?", (json.dumps([{"id": "gold", "count": 99}]),))
        elif damage == "policy":
            con.execute("UPDATE rlv2_battle_settlements SET policy_version=?", (rogue_settlement.POLICY,))
        else:
            value = json.loads(con.execute("SELECT effects FROM rlv2_battle_settlements").fetchone()[0])
            value["outcome"] = "CLEAR"
            con.execute("UPDATE rlv2_battle_settlements SET effects=?", (json.dumps(value),))
    before = rows(runtime.database.path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before
