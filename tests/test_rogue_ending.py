"""Authored ending contracts; native results are kept in local QA evidence."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_defeat import defeat
from test_rogue_settlement import prepared
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.gamedata.rogue_score import FirstThemeScore
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import REVISION, ROGUE_SETTLEMENT_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.roguelike_state import no_run
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def ending_runtime(monkeypatch, request):
    original = start_fixture.recruit_tables

    def tables():
        value = original()
        table = value["roguelike_topic_table"]
        table["constant"].update(milestoneTokenRatio=1, outerBuffTokenRatio=10)
        detail = table["details"]["rogue_1"]
        detail["difficulties"] = [{"modeDifficulty": "NORMAL", "grade": 0, "scoreFactor": 1, "bpValue": 0}]
        detail["detailConst"].update(historicalRecordsMode="NONE", historicalRecordsCount=0, outerBuffTokenSum=100)
        detail["milestoneUpdates"] = [{"updateTime": 0, "endTime": -1, "maxBpCount": 200}]
        # The base fixture replaces gameConst with map fixtures afterwards.
        return value

    old_maps = start_fixture.map_tables

    def maps():
        value = old_maps()
        value["roguelike_topic_table"]["details"]["rogue_1"]["gameConst"]["gpScoreRatio"] = 0
        return value

    monkeypatch.setattr(start_fixture, "recruit_tables", tables)
    monkeypatch.setattr(start_fixture, "map_tables", maps)
    return request.getfixturevalue("rogue_battle_runtime")


def pending(runtime, token):
    _, journal, battle_id, _ = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert defeat(client, token, battle_id, journal).status_code == 200


def test_ack_is_atomic_and_retry_does_not_duplicate_points_delta_restart_restore(ending_runtime):
    runtime, token = ending_runtime
    pending(runtime, token)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        for key in ("close-before-ack", "close-before-ack", "another-close"):
            close = post(client, token, "giveUpGame", {}, key)
            assert close.status_code == 200, close.text
            assert apply(before, close.json()["playerDataDelta"]) == before
            assert runtime.sync(token)["user"] == before
        reply = post(client, token, "gameSettle", {}, "ending")
        assert reply.status_code == 200, reply.text
        result = reply.json()
        assert result["game"]["score"]["detail"] == [[0, 0], [1, 1], [0, 0], [0, 0], [0, 0], [0, 0], [2, 4]]
        assert result["game"]["score"]["bp"] == {"cnt": 5, "from": 0, "to": 5}
        after = runtime.sync(token)["user"]
        assert after["rlv2"]["current"] == no_run()
        assert after["rlv2"]["outer"]["rogue_1"]["bp"]["point"] == 5
        assert after["rlv2"]["outer"]["rogue_1"]["record"]["history"] == []
        assert {k: v for k, v in before.items() if k != "rlv2"} == {
            k: v for k, v in after.items() if k != "rlv2"}
        assert apply(before, result["playerDataDelta"]) == after
        saved = rows(runtime.database.path)
        assert post(client, token, "gameSettle", {}, "ending").json() == result
        assert rows(runtime.database.path) == saved
        retry = post(client, token, "gameSettle", {}, "new-sequence")
        assert retry.status_code == 200 and retry.json()["game"] == result["game"]
        assert runtime.sync(token)["user"] == after
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueTopicRun).one().state == "SETTLED"
        assert session.query(m.RogueGameSettlement).count() == 1
        assert session.query(m.RogueBattleSettlement).one().loot == []
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after
        service = BackupService(reopened)
        saved = rows(reopened.database.path)
        backup = service.create()
        service.restore(backup["name"])
        assert rows(reopened.database.path) == saved
    finally:
        reopened.database.close()


def test_two_sequences_concurrently_ack_one_ending(ending_runtime):
    runtime, token = ending_runtime
    pending(runtime, token)

    def ack(n):
        with TestClient(create_game_app(runtime)) as client:
            return post(client, token, "gameSettle", {}, str(n))

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(ack, (1, 2)))
    assert all(r.status_code == 200 for r in replies)
    assert runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["bp"]["point"] == 5
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueGameSettlement).count() == 1


def test_no_pending_and_unknown_fields_cannot_ack_or_end_a_live_run(ending_runtime):
    runtime, token = ending_runtime
    prepared(runtime, token)
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "gameSettle", {"score": 999}, "bad-fields").status_code == 422
        assert post(client, token, "gameSettle", {}, "not-ending").status_code == 501
    assert rows(runtime.database.path) == before


def test_close_and_settle_on_two_runtimes_never_lose_or_duplicate_result(ending_runtime):
    runtime, token = ending_runtime
    pending(runtime, token)
    other = Runtime(runtime.settings)

    def command(pair):
        service, route = pair
        with TestClient(create_game_app(service)) as client:
            return post(client, token, route, {}, "race-" + route)

    try:
        with ThreadPoolExecutor(2) as pool:
            close, ack = pool.map(command, ((other, "giveUpGame"), (runtime, "gameSettle")))
        assert close.status_code in (200, 409), close.text
        assert ack.status_code == 200, ack.text
        after = runtime.sync(token)["user"]
        assert after["rlv2"]["current"] == no_run()
        assert after["rlv2"]["outer"]["rogue_1"]["bp"]["point"] == 5
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueGameSettlement).count() == 1
            assert session.query(m.RogueTopicRun).one().state == "SETTLED"
        assert other.sync(token)["user"] == after
    finally:
        other.database.close()


def test_legacy_abandoned_defeat_is_not_reopened_or_rewarded(ending_runtime):
    runtime, token = ending_runtime
    pending(runtime, token)
    # A pre-fix save could close this natural defeat without acknowledgement.
    # Preserve that historical decision; the repair applies to new requests.
    with runtime.database.transaction() as session:
        run = session.query(m.RogueTopicRun).one()
        result = session.query(m.RogueBattleSettlement).one()
        run.state, run.ended_at = "ABANDONED", result.created_at
    saved = rows(runtime.database.path)
    other = Runtime(runtime.settings)
    try:
        before = other.sync(token)["user"]
        assert before["rlv2"]["current"] == no_run()
        with TestClient(create_game_app(other)) as client:
            assert post(client, token, "giveUpGame", {}, "old-close").status_code == 409
            assert post(client, token, "gameSettle", {}, "old-ack").status_code == 409
        assert other.sync(token)["user"] == before
        assert rows(other.database.path) == saved
    finally:
        other.database.close()


def test_ack_trigger_failure_rolls_back_ledger_balance_run_and_receipt(ending_runtime):
    runtime, token = ending_runtime
    pending(runtime, token)
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("CREATE TRIGGER reject_end BEFORE INSERT ON rlv2_game_settlements BEGIN SELECT RAISE(ABORT,'QA'); END")
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "gameSettle", {}, "rollback").status_code == 500
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("damage", ["score", "facts", "after", "bp", "state", "missing"])
def test_corrupt_ending_rejected_before_startup_writes(ending_runtime, damage):
    runtime, token = ending_runtime
    pending(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "gameSettle", {}, "ack").status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        if damage in ("score", "facts", "after"):
            column = "response" if damage == "score" else damage
            value = json.loads(con.execute(f'SELECT "{column}" FROM rlv2_game_settlements').fetchone()[0])
            if damage == "score":
                value["game"]["score"]["score"] = 999
            elif damage == "facts":
                value["counts"][0] = 1
            else:
                value["grow"] = 99
            con.execute(f'UPDATE rlv2_game_settlements SET "{column}"=?', (json.dumps(value),))
        elif damage == "bp":
            value = json.loads(con.execute("SELECT state FROM rlv2_topics WHERE topic_id='rogue_1' AND account_id=1").fetchone()[0])
            value["bp"]["point"] = 999
            con.execute("UPDATE rlv2_topics SET state=? WHERE topic_id='rogue_1' AND account_id=1", (json.dumps(value),))
        elif damage == "state":
            con.execute("UPDATE rlv2_runs SET state='ABANDONED'")
        else:
            con.execute("DELETE FROM rlv2_game_settlements")
    saved = rows(runtime.database.path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved


def test_0024_migration_keeps_every_existing_row_and_foreign_key(ending_runtime):
    runtime, token = ending_runtime
    pending(runtime, token)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TABLE rlv2_shop_visits")
        con.execute("DROP TABLE rlv2_scene_visits")
        con.execute("DROP TABLE rlv2_game_settlements")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_SETTLEMENT_REVISION,))
    before = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        after = rows(reopened.database.path)
        assert after["alembic_version"] == [(REVISION,)]
        assert len(after) == len(before) + 3
        assert all(after[n] == values for n, values in before.items() if n != "alembic_version")
        with sqlite3.connect(reopened.database.path) as con:
            assert con.execute("PRAGMA foreign_key_check").fetchall() == []
            assert "SETTLED" in con.execute("SELECT sql FROM sqlite_master WHERE name='rlv2_runs'").fetchone()[0]
    finally:
        reopened.database.close()


@pytest.mark.parametrize("bp,grow,expected", [(8, 0, (13, 1)), (199, 0, (200, 1)), (200, 1, (200, 1)), (8, 100, (13, 100))])
def test_score_conversion_preserves_remainders_and_caps(ending_runtime, bp, grow, expected):
    runtime, _ = ending_runtime
    _, _, gain, gp = FirstThemeScore(runtime.data).calculate([0, 1, 0, 0, 0, 0, 2],
                                                            {"bp": bp, "grow": grow}, 1_800_000_000)
    assert (bp + gain, grow + gp) == expected


def test_new_active_run_cannot_replay_last_ending_with_a_new_sequence(ending_runtime):
    from terralocal.server.domain.accounts import login

    runtime, token = ending_runtime
    pending(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "gameSettle", {}, "ack").status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += 61
            new_token = login(session, runtime.settings, name="RogueBattleDoctor")["secret"]
        reply = post(client, new_token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0,
                                                    "predefinedId": None, "activityId": None}, "new-game")
        assert reply.status_code == 200, reply.text
        saved = rows(runtime.database.path)
        assert post(client, new_token, "gameSettle", {}, "old-ending").status_code == 501
        assert rows(runtime.database.path) == saved


def test_game_settle_migration_failure_keeps_old_database(ending_runtime, monkeypatch):
    from terralocal.server.persistence.database import Database

    runtime, token = ending_runtime
    pending(runtime, token)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TABLE rlv2_shop_visits")
        con.execute("DROP TABLE rlv2_scene_visits")
        con.execute("DROP TABLE rlv2_game_settlements")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_SETTLEMENT_REVISION,))
    saved = rows(runtime.database.path)
    create = m.RogueGameSettlement.__table__.create

    def fail(*args, **kwargs):
        create(*args, **kwargs)
        raise RuntimeError("ending-migration-failure")

    monkeypatch.setattr(m.RogueGameSettlement.__table__, "create", fail)
    db = Database(runtime.database.path)
    try:
        with pytest.raises(RuntimeError, match="ending-migration-failure"):
            db.initialize()
    finally:
        db.close()
    assert rows(runtime.database.path) == saved


def test_prior_clear_counts_once_failed_node_never_counts_as_clear_and_rewind_keeps_end(ending_runtime):
    from test_native_replay import journal as make_journal
    from test_rogue_settlement import complete
    from test_roguelike_battle_start import begin, body

    from terralocal.server.domain.context import Context
    from terralocal.server.domain.rogue_map import Column, Entry, Plan
    from terralocal.server.domain.rogue_map_drafts import prepare

    runtime, token = ending_runtime
    spec = Plan("zone_1", (Column(1, 1, (Entry("BATTLE_NORMAL", 1, "ordinary"),)),) * 2, 0)
    with runtime.database.transaction() as session:
        prepare(Context(session, runtime.data, 1), spec)
    journal = make_journal()
    journal["journal"]["metadata"]["stageId"] = "ordinary"
    member = journal["journal"]["squad"][0]
    member["skillIndex"], member["skillId"] = 1, "s1"
    journal["journal"]["squad"].append(member | {"charInstId": 2, "skillIndex": -1, "skillId": None})
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "initial").status_code == 200
        first = begin(client, token, body(), "first").json()["battleId"]
        assert complete(client, token, first, journal, 8).status_code == 200
        assert post(client, token, "finishBattleReward", {}, "forfeit").status_code == 200
        second = begin(client, token, body() | {"to": {"x": 1, "y": 0}}, "second").json()["battleId"]
        assert defeat(client, token, second, journal).status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at -= 100
        reply = post(client, token, "gameSettle", {}, "ending")
        assert reply.status_code == 200, reply.text
        assert reply.json()["game"]["score"]["score"] == 16
    outer = runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]
    assert outer["bp"]["point"] == 16 and outer["buff"]["pointOwned"] == 1
    assert outer["record"]["stageCnt"] == {"ordinary": 1}
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueTopicRun).one().ended_at == 1_800_000_000
    reopened = Runtime(runtime.settings)
    reopened.database.close()
