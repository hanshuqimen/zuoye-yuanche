"""Owned scene transactions on authored rules, not official node pools."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_defeat import defeat
from test_rogue_ending import ending_runtime as ending_runtime
from test_rogue_settlement import complete
from test_roguelike_battle_start import begin, body
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_visits import prepare
from terralocal.server.gamedata import rogue_events
from terralocal.server.gamedata.rogue_events import Branch, Delta, EventSpec, Frame
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import REVISION, ROGUE_ENDING_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.roguelike_state import no_run
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def visits_runtime(monkeypatch, request):
    original = start_fixture.recruit_tables

    def tables():
        value = original()
        detail = value["roguelike_topic_table"]["details"]["rogue_1"]
        detail["choiceScenes"], detail["choices"] = {}, {}
        for name in ("hp", "gold", "hope"):
            for suffix in ("_enter", "_1"):
                key = "scene_" + name + suffix
                detail["choiceScenes"][key] = {"id": key, "title": "Authored scene",
                    "description": "Authored test line", "useHiddenMusic": False}
            key = "choice_" + name
            detail["choices"][key] = {"id": key, "type": "TRADE", "nextSceneId": "scene_" + name + "_1",
                "title": "Authored gain", "isHiddenChoice": False, "forceShowWhenOnlyLeave": False, "sortId": 0}
        detail["choices"]["choice_leave"] = {"id": "choice_leave", "type": "LEAVE", "nextSceneId": None,
            "title": "Authored exit", "isHiddenChoice": False, "forceShowWhenOnlyLeave": False, "sortId": 0}
        return value

    def programs(catalog):
        result = {}
        for name, delta in (("hp", Delta(hp=3)), ("gold", Delta(gold=5)), ("hope", Delta(hope_max=2))):
            cid, entry, target = "choice_" + name, "scene_" + name + "_enter", "scene_" + name + "_1"
            spec = EventSpec("rogue1-fixed-" + name, entry, (
                Frame(entry, (Branch(cid, catalog.choices[cid].digest, delta),)),
                Frame(target, (Branch("choice_leave", catalog.choices["choice_leave"].digest, Delta()),))),
                "Authored QA event rules; not official encounter eligibility")
            result[spec.id] = catalog.compile(spec)
        return result

    monkeypatch.setattr(start_fixture, "recruit_tables", tables)
    monkeypatch.setattr(rogue_events, "fixed_programs", programs)
    return request.getfixturevalue("ending_runtime")


def setup(runtime, token, sequence=("hp", "gold", "hope")):
    spec = Plan("zone_1", tuple(Column(1, 1, (Entry("BATTLE_NORMAL", 1, "ordinary") if v == "battle"
                                           else Entry("INCIDENT", 1),)) for v in sequence), 0)
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), spec)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "activate-map").status_code == 200
    with runtime.database.transaction() as session:
        bindings = {Point(x, 0): "rogue1-fixed-" + name for x, name in enumerate(sequence) if name != "battle"}
        prepare(Context(session, runtime.data, 1), bindings)


def move(client, token, x, seq):
    return post(client, token, "moveTo", {"to": {"x": x, "y": 0}}, seq)


def test_three_fixed_events_share_transactions_delta_retry_cursor_restart_restore(visits_runtime):
    runtime, token = visits_runtime
    setup(runtime, token)
    before_all = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        for x, name in enumerate(("hp", "gold", "hope")):
            assert move(client, token, x, "move" + name).status_code == 200
            state = current(runtime, token)
            assert state["player"]["cursor"]["position"] == {"x": x, "y": 0}
            assert state["player"]["pending"][0]["type"] == "SCENE"
            assert post(client, token, "finishEvent", {}, "early" + name).status_code == 409
            before = runtime.sync(token)["user"]
            reply = post(client, token, "selectChoice", {"choice": "choice_" + name}, "gain" + name)
            assert reply.status_code == 200, reply.text
            after = runtime.sync(token)["user"]
            assert apply(before, reply.json()["playerDataDelta"]) == after
            for seq in ("gain" + name, "gain-new" + name):
                assert post(client, token, "selectChoice", {"choice": "choice_" + name}, seq).status_code == 200
            assert runtime.sync(token)["user"] == after
            if x == 0:
                reopened = Runtime(runtime.settings)
                try:
                    assert reopened.sync(token)["user"] == after
                finally:
                    reopened.database.close()
            if x == 1:
                exit_reply = post(client, token, "selectChoice", {"choice": "choice_leave"}, "exit" + name)
            else:
                exit_reply = post(client, token, "finishEvent", {}, "exit" + name)
            assert exit_reply.status_code == 200, exit_reply.text
            assert current(runtime, token)["player"]["pending"] == []
            assert move(client, token, x, "move-retry" + name).status_code == 200
            assert post(client, token, "finishEvent", {}, "exit-retry" + name).status_code == 200
        final = runtime.sync(token)["user"]
    assert {k: v for k, v in before_all.items() if k != "rlv2"} == {k: v for k, v in final.items() if k != "rlv2"}
    props = final["rlv2"]["current"]["player"]["property"]
    assert props["hp"]["current"] == 7 and props["gold"] == 11
    assert props["population"] == {
        "cost": before_all["rlv2"]["current"]["player"]["property"]["population"]["cost"], "max": 8}
    assert len(final["rlv2"]["current"]["player"]["trace"]) == 3
    with runtime.database.transaction(write=False) as session:
        visits = session.query(m.RogueSceneVisit).all()
        assert len(visits) == 3 and all(v.state == "FINISHED" and len(v.steps) == 2 for v in visits)
        assert session.query(m.RogueBattle).count() == 0
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
        saved = rows(reopened.database.path)
        backups = BackupService(reopened)
        backup = backups.create()
        backups.restore(backup["name"])
        assert rows(reopened.database.path) == saved
    finally:
        reopened.database.close()


def test_hybrid_scene_clear_scene_defeat_keeps_path_effects_and_versioned_ending(visits_runtime):
    from test_native_replay import journal as make_journal

    runtime, token = visits_runtime
    setup(runtime, token, ("hp", "battle", "hope", "battle"))
    journal = make_journal()
    journal["journal"]["metadata"]["stageId"] = "ordinary"
    member = journal["journal"]["squad"][0]
    member["skillIndex"], member["skillId"] = 1, "s1"
    journal["journal"]["squad"].append(member | {"charInstId": 2, "skillIndex": -1, "skillId": None})
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "hp").status_code == 200
        assert begin(client, token, body() | {"to": {"x": 1, "y": 0}}, "too-early").status_code == 409
        assert post(client, token, "selectChoice", {"choice": "choice_hp"}, "gain").status_code == 200
        assert post(client, token, "finishEvent", {}, "exit").status_code == 200
        reply = begin(client, token, body() | {"to": {"x": 1, "y": 0}}, "battle1")
        assert reply.status_code == 200, reply.text
        assert complete(client, token, reply.json()["battleId"], journal, 11).status_code == 200
        assert move(client, token, 2, "reward-pending").status_code == 409
        assert post(client, token, "finishBattleReward", {}, "forfeit").status_code == 200
        assert move(client, token, 2, "hope").status_code == 200
        assert post(client, token, "selectChoice", {"choice": "choice_hope"}, "more-hope").status_code == 200
        assert post(client, token, "finishEvent", {}, "exit-hope").status_code == 200
        reply = begin(client, token, body() | {"to": {"x": 3, "y": 0}}, "battle2")
        assert reply.status_code == 200, reply.text
        assert defeat(client, token, reply.json()["battleId"], journal).status_code == 200
        reply = post(client, token, "gameSettle", {}, "end")
        assert reply.status_code == 200, reply.text
        assert reply.json()["game"]["score"]["score"] == 18
        assert reply.json()["game"]["record"]["cntArrivedNode"] == 4
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueGameSettlement).one().policy_version.endswith("scenes-v2")
        assert session.query(m.RogueBattle).count() == 2
        assert session.query(m.RogueSceneVisit).count() == 2
    reopened = Runtime(runtime.settings)
    reopened.database.close()


def test_concurrent_new_sequence_selection_grants_once_and_transaction_failure_rolls_back(visits_runtime):
    runtime, token = visits_runtime
    setup(runtime, token, ("hp",))
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "move").status_code == 200
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("CREATE TRIGGER reject_step BEFORE UPDATE ON rlv2_scene_visits BEGIN SELECT RAISE(ABORT,'QA'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "selectChoice", {"choice": "choice_hp"}, "rollback").status_code == 500
    assert rows(runtime.database.path) == saved
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TRIGGER reject_step")

    def choose(n):
        with TestClient(create_game_app(runtime)) as client:
            return post(client, token, "selectChoice", {"choice": "choice_hp"}, "concurrent" + str(n))

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(choose, (1, 2)))
    assert all(r.status_code == 200 for r in replies)
    assert current(runtime, token)["player"]["property"]["hp"]["current"] == 7
    with runtime.database.transaction(write=False) as session:
        assert len(session.query(m.RogueSceneVisit).one().steps) == 1


@pytest.mark.parametrize("damage", ["before", "choice", "prefix", "program", "state", "hp", "owner", "missing-table"])
def test_invalid_scene_or_path_is_rejected_before_startup_writes(visits_runtime, damage):
    runtime, token = visits_runtime
    setup(runtime, token, ("hp",))
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "move").status_code == 200
        assert post(client, token, "selectChoice", {"choice": "choice_hp"}, "gain").status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        if damage == "before":
            value = json.loads(con.execute('SELECT "before" FROM rlv2_scene_visits').fetchone()[0])
            value["hp"] += 1
            con.execute('UPDATE rlv2_scene_visits SET "before"=?', (json.dumps(value),))
        elif damage == "choice":
            con.execute("UPDATE rlv2_scene_visits SET steps=?", (json.dumps([{"choice": "missing", "at": 1_800_000_000}]),))
        elif damage == "prefix":
            con.execute("UPDATE rlv2_scene_visits SET recruit_count=999")
        elif damage == "program":
            con.execute("UPDATE rlv2_scene_visits SET program_id='missing'")
        elif damage == "state":
            con.execute("UPDATE rlv2_scene_visits SET state='FINISHED',ended_at=entered_at")
        elif damage == "hp":
            con.execute("UPDATE rlv2_runs SET hp=999")
        elif damage == "owner":
            con.execute("UPDATE rlv2_scene_visits SET account_id=2")
        else:
            con.execute("DROP TABLE rlv2_scene_visits")
    saved = rows(runtime.database.path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved


def test_no_client_program_selection_invalid_choice_and_unreachable_move_are_read_only(visits_runtime):
    runtime, token = visits_runtime
    setup(runtime, token)
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 2, "skip").status_code == 409
        assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}, "program": "rogue1-fixed-gold"}, "inject").status_code == 422
        assert post(client, token, "selectChoice", {"choice": "choice_gold"}, "no-scene").status_code == 409
    assert rows(runtime.database.path) == saved


def test_abandon_keeps_accepted_effects_and_clock_boundary_without_faking_exit(visits_runtime):
    runtime, token = visits_runtime
    setup(runtime, token, ("hp",))
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "move").status_code == 200
        assert post(client, token, "selectChoice", {"choice": "choice_hp"}, "hp").status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at -= 100
        assert post(client, token, "giveUpGame", {}, "abandon").status_code == 200
        assert current(runtime, token)["player"]["pending"][0]["type"] == "GAME_SETTLE"
        assert post(client, token, "gameSettle", {}, "confirm-abandon").status_code == 200
    assert current(runtime, token) == no_run()
    reopened = Runtime(runtime.settings)
    try:
        with reopened.database.transaction(write=False) as session:
            visit = session.query(m.RogueSceneVisit).one()
            assert visit.state == "ABANDONED" and len(visit.steps) == 1
            assert visit.ended_at == 1_800_000_000 and session.query(m.RogueTopicRun).one().hp == 7
    finally:
        reopened.database.close()


def test_0025_upgrade_and_failure_rollback_keep_old_rows(visits_runtime, monkeypatch):
    from terralocal.server.persistence.database import Database

    runtime, _ = visits_runtime
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        # Isolate post-0025 table additions and rollback. Later columns remain
        # present; their historical column migrations have separate tests.
        con.execute("DROP TABLE rlv2_bank_visits")
        con.execute("DROP TABLE rlv2_bank_wallets")
        con.execute("DROP TABLE rlv2_floor_cursors")
        con.execute("DROP TABLE rlv2_shop_visits")
        con.execute("DROP TABLE rlv2_scene_visits")
        con.execute("DROP TABLE rlv2_run_closures")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_ENDING_REVISION,))
    saved = rows(runtime.database.path)
    original = m.RogueSceneVisit.__table__.create

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("scene-migration-failure")

    monkeypatch.setattr(m.RogueSceneVisit.__table__, "create", fail)
    database = Database(runtime.database.path)
    try:
        with pytest.raises(RuntimeError, match="scene-migration-failure"):
            database.initialize()
    finally:
        database.close()
    assert rows(runtime.database.path) == saved
    monkeypatch.setattr(m.RogueSceneVisit.__table__, "create", original)
    reopened = Runtime(runtime.settings)
    try:
        changed = rows(reopened.database.path)
        assert len(saved) == 71 and len(changed) == 77
        assert changed["alembic_version"] == [(REVISION,)]
        assert all(changed[k] == v for k, v in saved.items() if k != "alembic_version")
    finally:
        reopened.database.close()
