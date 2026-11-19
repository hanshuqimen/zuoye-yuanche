"""Authored ordinary perfect results; no native clear or official loot proof."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from test_native_battle_finish import encoded
from test_native_replay import packed
from test_rogue_battle_codec import snapshot
from test_rogue_finish_inspection import setup
from test_roguelike_battle_start import begin, body
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_map_drafts import rows

from terralocal.server.domain import rogue_settlement
from terralocal.server.domain.context import Context
from terralocal.server.domain.rogue_map import Column, Entry, Plan
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import ROGUE_BATTLE_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def prepared(runtime, token):
    payload, journal = setup(runtime, token)
    with runtime.database.transaction(write=False) as session:
        battle_id = session.query(m.RogueBattle).one().id
        run = session.query(m.RogueTopicRun).one()
        hp = run.hp + runtime.data.rogue_initial.battle_temporary_hp
    return payload, journal, battle_id, hp


def complete(client, token, battle_id, journal, hp, key="finish", **changes):
    trace = {"isCheat": None, "completeTime": 20, "stats": {"leftHp": hp}}
    payload = encoded(battle_id, state=3, changes={"stageId": "ordinary"} | changes)
    trace["isCheat"] = payload["battleData"]["isCheat"]
    payload = encoded(battle_id, state=3, changes={"stageId": "ordinary"} | changes, trace_changes=trace)
    return post(client, token, "battleFinish", payload | {"battleLog": packed(journal),
        "rlv2Data": {"battleSnapshot": snapshot()}}, key)


def test_perfect_exp_then_claim_gold_once_delta_restart_and_restore(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        reply = complete(client, token, battle_id, journal, hp)
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        assert {k: v for k, v in before.items() if k != "rlv2"} == {
            k: v for k, v in after.items() if k != "rlv2"}
        prop = after["rlv2"]["current"]["player"]["property"]
        assert prop["exp"] == 0 and prop["level"] == 2 and prop["population"]["max"] == 10
        assert prop["gold"] == before["rlv2"]["current"]["player"]["property"]["gold"]
        assert after["rlv2"]["current"]["player"]["pending"][0]["type"] == "BATTLE_REWARD"
        for key in ("finish", "new-sequence"):
            assert complete(client, token, battle_id, journal, hp, key).status_code == 200
        assert post(client, token, "moveAndBattleStart", body(), "too-early").status_code == 409
        assert post(client, token, "finishEvent", {}, "wrong-event").status_code == 409
        for seq in ("gold", "gold-again"):
            reply = post(client, token, "chooseBattleReward", {"index": 0, "sub": 0}, seq)
            assert reply.status_code == 200, reply.text
        assert current(runtime, token)["player"]["property"]["gold"] == prop["gold"] + 3
        # Close explicitly forfeits the unclaimed recruitment ticket.
        assert post(client, token, "finishBattleReward", {}, "close-reward").status_code == 200
        state = current(runtime, token)
        assert state["player"]["state"] == "WAIT_MOVE"
        assert state["player"]["cursor"]["position"] == {"x": 0, "y": 0}
        assert state["player"]["pending"] == [] and len(state["inventory"]["recruit"]) == 3
        assert state["map"]["zones"]["1"]["nodes"]["0"]["fts"] == 1_800_000_000
    saved = rows(runtime.database.path)
    with runtime.database.transaction(write=False) as session:
        settled = session.query(m.RogueBattleSettlement).one()
        assert "access" not in json.dumps(settled.facts) and "stats" not in json.dumps(settled.facts)
        assert "records" in inspect(settled).unloaded
        assert settled.records == {"journal": packed(journal), "snapshot": snapshot()}
        assert session.query(m.RogueBattle).one().state == "FINISHED"
    reopened = Runtime(runtime.settings)
    try:
        assert current(reopened, token) == state
        service = BackupService(reopened)
        backup = service.create()
        service.restore(backup["name"])
        assert rows(reopened.database.path) == saved
    finally:
        reopened.database.close()


@pytest.fixture
def settlement_ticket_runtime(monkeypatch, request):
    import test_roguelike_battle_start as start_fixture
    from test_rogue_upgrade_rules import source as upgrade_source

    original = start_fixture.import_data

    def imported(folder, cache):
        path = folder / "roguelike_topic_table.json"
        table = json.loads(path.read_bytes())
        detail = table["details"]["rogue_1"]
        upgrade = upgrade_source()
        # An ordinary reward ticket can offer the already-recruited operator
        # a paid upgrade. Supply that branch's complete authored definitions.
        detail["items"].update(upgrade["items"])
        detail["upgradeTickets"] = upgrade["upgradeTickets"]
        detail["detailConst"]["charUpgradeTable"] = upgrade["detailConst"]["charUpgradeTable"]
        path.write_text(json.dumps(table), "utf8")
        return original(folder, cache)

    monkeypatch.setattr(start_fixture, "import_data", imported)
    return request.getfixturevalue("rogue_battle_runtime")


def test_claim_ticket_offer_close_and_no_second_claim(settlement_ticket_runtime):
    runtime, token = settlement_ticket_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert complete(client, token, battle_id, journal, hp).status_code == 200
        for seq in ("ticket", "ticket-again"):
            reply = post(client, token, "chooseBattleReward", {"index": 1, "sub": 0}, seq)
            assert reply.status_code == 200, reply.text
        state = current(runtime, token)
        assert [p["type"] for p in state["player"]["pending"]] == ["RECRUIT", "BATTLE_REWARD"]
        assert state["inventory"]["recruit"]["3"]["state"] == "ACTIVE"
        assert post(client, token, "finishBattleReward", {}, "too-early").status_code == 409
        assert post(client, token, "closeRecruitTicket", {"id": "3"}, "decline").status_code == 200
        assert post(client, token, "chooseBattleReward", {"index": 0, "sub": 0}, "gold").status_code == 200
        assert post(client, token, "finishBattleReward", {}, "done").status_code == 200
        assert len(current(runtime, token)["inventory"]["recruit"]) == 4
    reopened = Runtime(runtime.settings)
    reopened.database.close()


def test_successive_nodes_use_saved_edges_and_keep_old_retry_harmless(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    spec = Plan("zone_1", (Column(1, 1, (Entry("BATTLE_NORMAL", 1, "ordinary"),)),) * 3, 0)
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), spec)
    from test_native_replay import journal as make_journal

    journal = make_journal()
    journal["journal"]["metadata"]["stageId"] = "ordinary"
    member = journal["journal"]["squad"][0]
    member["skillIndex"], member["skillId"] = 1, "s1"
    journal["journal"]["squad"].append(member | {"charInstId": 2, "skillIndex": -1, "skillId": None})
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "initial").status_code == 200
        ids = []
        for x in range(3):
            payload = body() | {"to": {"x": x, "y": 0}}
            reply = begin(client, token, payload, "start-" + str(x))
            assert reply.status_code == 200, reply.text
            ids.append(reply.json()["battleId"])
            state = current(runtime, token)
            hp = state["player"]["property"]["hp"]["current"] + runtime.data.rogue_initial.battle_temporary_hp
            assert complete(client, token, ids[-1], journal, hp, "finish-" + str(x)).status_code == 200
            assert post(client, token, "finishBattleReward", {}, "close-" + str(x)).status_code == 200
            if x == 0:
                with runtime.database.transaction() as session:
                    session.get(m.ServerClockState, 1).fixed_at -= 10
        state = current(runtime, token)
        # This authored table ends at level2. Keep surplus within that level;
        # the retained run and settlement records still store total EXP30.
        assert state["player"]["property"]["exp"] == 20
        assert state["player"]["cursor"]["position"] == {"x": 2, "y": 0}
        assert len(state["player"]["trace"]) == 3
        assert complete(client, token, ids[0], journal, hp, "old-finish-retry").status_code == 200
        assert current(runtime, token) == state
        assert begin(client, token, body(), "old-node").status_code == 409
    reopened = Runtime(runtime.settings)
    try:
        assert current(reopened, token) == state
    finally:
        reopened.database.close()


def test_0023_upgrade_keeps_started_battle_indices_and_rolls_back(rogue_battle_runtime, monkeypatch):
    runtime, token = rogue_battle_runtime
    prepared(runtime, token)
    runtime.database.close()
    # Recreate the exact old CHECK shape in an authored disposable save.
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TABLE rlv2_battle_loot_plans")
        con.execute("DROP TABLE rlv2_bank_visits")
        con.execute("DROP TABLE rlv2_bank_wallets")
        con.execute("DROP TABLE rlv2_floor_cursors")
        con.execute("DROP TABLE rlv2_shop_visits")
        con.execute("DROP TABLE rlv2_scene_visits")
        con.execute("DROP TABLE rlv2_game_settlements")
        con.execute("DROP TABLE rlv2_battle_settlements")
        ddl = con.execute("SELECT sql FROM sqlite_master WHERE name='rlv2_battles'").fetchone()[0]
        indices = [r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE tbl_name='rlv2_battles' "
                                           "AND type='index' AND sql IS NOT NULL")]
        con.execute("ALTER TABLE rlv2_battles RENAME TO old_battles")
        for name, in con.execute("SELECT name FROM sqlite_master WHERE tbl_name='old_battles' "
                                "AND type='index' AND sql IS NOT NULL").fetchall():
            con.execute('DROP INDEX "' + name + '"')
        con.execute(ddl.replace("'STARTED','FINISHED','ABANDONED'", "'STARTED','ABANDONED'"))
        con.execute("INSERT INTO rlv2_battles SELECT * FROM old_battles")
        con.execute("DROP TABLE old_battles")
        for ddl in indices:
            con.execute(ddl)
        con.execute("DROP TABLE rlv2_run_closures")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_BATTLE_REVISION,))
    before = rows(runtime.database.path)
    original = m.RogueBattleSettlement.__table__.create
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic-migration-failure")
    monkeypatch.setattr(m.RogueBattleSettlement.__table__, "create", fail)
    db = Database(runtime.database.path)
    with pytest.raises(RuntimeError, match="synthetic-migration-failure"):
        db.initialize()
    db.close()
    assert rows(runtime.database.path) == before
    monkeypatch.setattr(m.RogueBattleSettlement.__table__, "create", original)
    reopened = Runtime(runtime.settings)
    try:
        after = rows(runtime.database.path)
        assert len(before) == 69 and len(after) == 78
        assert all(v == after[k] for k, v in before.items() if k != "alembic_version")
        with sqlite3.connect(runtime.database.path) as con:
            assert not con.execute("PRAGMA foreign_key_check").fetchall()
            sql = con.execute("SELECT sql FROM sqlite_master WHERE name='uq_rlv2_account_active_battle'").fetchone()[0]
            assert "WHERE state='STARTED'" in sql
    finally:
        reopened.database.close()


@pytest.mark.parametrize("change", [{"completeState": 2}, {"interrupt": 1}, {"giveUp": 1}, {"percent": 50}])
def test_unadmitted_outcomes_preserve_started_battle_and_all_rewards(rogue_battle_runtime, change):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        reply = complete(client, token, battle_id, journal, hp, **change)
        assert reply.status_code in (400, 501), reply.text
    assert rows(runtime.database.path) == before


def test_concurrent_claims_and_finish_rollback_are_atomic(rogue_battle_runtime, monkeypatch):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    before = rows(runtime.database.path)
    original = rogue_settlement.response
    def failure():
        raise RuntimeError("synthetic-after-writes-before-commit")
    monkeypatch.setattr(rogue_settlement, "response", failure)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert complete(client, token, battle_id, journal, hp).status_code == 500
        assert rows(runtime.database.path) == before
        monkeypatch.setattr(rogue_settlement, "response", original)
        assert complete(client, token, battle_id, journal, hp).status_code == 200
        with ThreadPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(lambda i: post(client, token, "chooseBattleReward",
                {"index": 0, "sub": 0}, "claim-" + str(i)), range(4)))
        assert all(r.status_code == 200 for r in replies)
    with runtime.database.transaction(write=False) as session:
        assert len(session.query(m.RogueBattleSettlement).one().claims) == 1


def test_ticket_offer_failure_rolls_back_claim_and_new_ticket(rogue_battle_runtime, monkeypatch):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert complete(client, token, battle_id, journal, hp).status_code == 200
        before = rows(runtime.database.path)
        def failure(*args):
            raise RuntimeError("synthetic-offer-failure")
        monkeypatch.setattr("terralocal.server.domain.rogue_recruit.activate", failure)
        reply = post(client, token, "chooseBattleReward", {"index": 1, "sub": 0}, "ticket")
        assert reply.status_code == 500 and rows(runtime.database.path) == before


def test_conflicting_finish_invalid_choice_and_rewound_abandon_keep_consistency(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert complete(client, token, battle_id, journal, hp).status_code == 200
        saved = rows(runtime.database.path)
        assert complete(client, token, battle_id, journal, hp, "conflict", killCnt=1).status_code == 409
        for fields in ({"index": 2, "sub": 0}, {"index": 0, "sub": 1}):
            assert post(client, token, "chooseBattleReward", fields, "bad-" + str(fields)).status_code == 400
        assert rows(runtime.database.path) == saved
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += 30
        assert post(client, token, "chooseBattleReward", {"index": 0, "sub": 0}, "claim").status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at -= 100
        assert post(client, token, "giveUpGame", {}, "abandon").status_code == 200
    reopened = Runtime(runtime.settings)
    reopened.database.close()


@pytest.mark.parametrize("damage", ["exp", "loot", "claim", "facts", "records", "missing"])
def test_corrupt_settlement_rejected_before_runtime_writes(rogue_battle_runtime, damage):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert complete(client, token, battle_id, journal, hp).status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        if damage == "exp":
            con.execute("UPDATE rlv2_runs SET exp=exp+1")
        elif damage == "missing":
            con.execute("DELETE FROM rlv2_battle_settlements")
        else:
            value = json.loads(con.execute("SELECT " + damage + " FROM rlv2_battle_settlements").fetchone()[0]) \
                if damage != "claim" else [{"index": 0, "at": 1_800_000_000, "ticket": 999}]
            if damage == "loot":
                value[0]["count"] += 1
            elif damage == "facts":
                value["rank"] = 2
            elif damage == "records":
                value["journal"] = "A" + value["journal"][1:]
            con.execute("UPDATE rlv2_battle_settlements SET " + ("claims" if damage == "claim" else damage) + "=?",
                        (json.dumps(value),))
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest
