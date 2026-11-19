"""Authored cross-floor HTTP/transaction contracts; no native combat claim."""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_native_replay import journal as make_journal
from test_rogue_defeat import defeat
from test_rogue_ending import ending_runtime as ending_runtime
from test_rogue_settlement import complete
from test_rogue_shop_ending import shop_ending_runtime as shop_ending_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_battle_start import begin
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_ending import FLOOR_POLICY
from terralocal.server.domain.rogue_floors import FloorSequence
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare_floors
from terralocal.server.domain.rogue_progress import binding
from terralocal.server.domain.rogue_shops import prepare as prepare_shops
from terralocal.server.domain.rogue_visits import choose
from terralocal.server.domain.rogue_visits import prepare as prepare_scenes
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def floors_runtime(monkeypatch, request):
    original = start_fixture.map_tables

    def maps():
        value = original()
        zones = value["roguelike_topic_table"]["details"]["rogue_1"]["zones"]
        for n in (2, 3):
            zones[f"zone_{n}"] = {"id": f"zone_{n}", "isHiddenZone": False}
        return value

    monkeypatch.setattr(start_fixture, "map_tables", maps)
    return request.getfixturevalue("shop_ending_runtime")


def setup(runtime, token, kinds=("BATTLE_NORMAL", "INCIDENT", "BATTLE_NORMAL")):
    spec = FloorSequence(tuple(Plan(f"zone_{i}", (Column(1, 1, (Entry(kind, 1,
        "ordinary" if kind == "BATTLE_NORMAL" else None),)),), 0) for i, kind in enumerate(kinds, 1)))
    with runtime.database.transaction() as session:
        prepare_floors(Context(session, runtime.data, 1), spec)
    with TestClient(create_game_app(runtime)) as client:
        response = post(client, token, "finishEvent", {}, "floors-activate")
        assert response.status_code == 200, response.text
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        for i, kind in enumerate(kinds, 1):
            if kind == "INCIDENT":
                prepare_scenes(ctx, {Point(0, 0): "rogue1-fixed-gold"}, zone_index=i)
            if kind == "SHOP":
                q = compile_shop(runtime.data, "floor-qa", (Offer("a", "ticket_medic", 1),),
                                 evidence="Explicit QA stock; not official supply")
                prepare_shops(ctx, {Point(0, 0): q}, zone_index=i)


def journal():
    value = make_journal()
    value["journal"]["metadata"]["stageId"] = "ordinary"
    member = value["journal"]["squad"][0]
    member["skillIndex"], member["skillId"] = 1, "s1"
    value["journal"]["squad"].append(member | {"charInstId": 2, "skillIndex": -1, "skillId": None})
    return value


def scene(client, token, prefix="scene"):
    assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, prefix + "-enter").status_code == 200
    reply = post(client, token, "selectChoice", {"choice": "choice_gold"}, prefix + "-gain")
    assert reply.status_code == 200, reply.text
    return post(client, token, "selectChoice", {"choice": "choice_leave"}, prefix + "-leave")


def test_same_coordinate_battles_scene_crossings_ending_restart_and_backup(floors_runtime):
    runtime, token = floors_runtime
    setup(runtime, token)
    base = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        first = begin(client, token)
        assert first.status_code == 200, first.text
        hp = current(runtime, token)["player"]["property"]["hp"]["current"]
        reply = complete(client, token, first.json()["battleId"], journal(),
                         hp + runtime.data.rogue_initial.battle_temporary_hp)
        assert reply.status_code == 200, reply.text
        assert current(runtime, token)["player"]["cursor"]["zone"] == 1
        before = runtime.sync(token)["user"]
        reply = post(client, token, "finishBattleReward", {}, "floor1-close")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        state = after["rlv2"]["current"]
        assert state["player"]["cursor"] == {"zone": 2, "position": None}
        assert set(state["map"]["zones"]) == {"1", "2"} and state["player"]["pending"] == []
        assert post(client, token, "finishBattleReward", {}, "floor1-close-retry").status_code == 200
        assert runtime.sync(token)["user"] == after
        reopened = Runtime(runtime.settings)
        try:
            assert reopened.sync(token)["user"] == after
        finally:
            reopened.database.close()
        assert scene(client, token).status_code == 200
        state = current(runtime, token)
        assert state["player"]["cursor"] == {"zone": 3, "position": None}
        assert state["player"]["trace"] == [
            {"zone": i, "position": {"x": 0, "y": 0}} for i in (1, 2)]
        assert post(client, token, "selectChoice", {"choice": "choice_leave"}, "leave-retry").status_code == 200
        assert current(runtime, token) == state
        second = begin(client, token, key="floor3-battle")
        assert second.status_code == 200, second.text
        assert second.json()["battleId"] != first.json()["battleId"]
        rejected = post(client, token, "finishBattleReward", {}, "old-close-after-new-node")
        assert rejected.status_code == 409
        reply = defeat(client, token, second.json()["battleId"], journal(), "floor3-defeat")
        assert reply.status_code == 200, reply.text
        before = runtime.sync(token)["user"]
        reply = post(client, token, "gameSettle", {}, "floors-ending")
        assert reply.status_code == 200, reply.text
        result = reply.json()
        assert result["game"]["record"]["cntZone"] == 2
        assert result["game"]["record"]["cntArrivedNode"] == 3
        assert result["game"]["record"]["cntBattle"] == 1
        assert apply(before, result["playerDataDelta"]) == runtime.sync(token)["user"]
        assert post(client, token, "gameSettle", {}, "floors-ending-again").json()["game"] == result["game"]
    with runtime.database.transaction(write=False) as session:
        battles = session.query(m.RogueBattle).order_by(m.RogueBattle.zone_index).all()
        assert [b.zone_index for b in battles] == [1, 3]
        assert len({b.request_hash for b in battles}) == 2
        assert session.query(m.RogueFloorCursor).one().zone_index == 3
        assert session.query(m.RogueGameSettlement).one().policy_version == FLOOR_POLICY
    saved = rows(runtime.database.path)
    state = runtime.sync(token)["user"]
    assert {k: v for k, v in base.items() if k != "rlv2"} == {k: v for k, v in state.items() if k != "rlv2"}
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == state
        backup = BackupService(reopened)
        backup.restore(backup.create()["name"])
        assert rows(reopened.database.path) == saved
    finally:
        reopened.database.close()


def test_shop_pending_ticket_barrier_and_last_supplied_floor_does_not_invent_ending(floors_runtime):
    runtime, token = floors_runtime
    setup(runtime, token, ("SHOP", "SHOP"))
    with TestClient(create_game_app(runtime)) as client:
        for n in (1, 2):
            assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, f"enter-{n}").status_code == 200
            assert post(client, token, "shopAction", {"buy": ["a"], "recycle": [], "leave": 0},
                        f"buy-{n}").status_code == 200
            saved = rows(runtime.database.path)
            assert post(client, token, "shopAction", {"buy": [], "recycle": [], "leave": 1},
                        f"early-{n}").status_code == 409
            assert rows(runtime.database.path) == saved
            assert current(runtime, token)["player"]["cursor"]["zone"] == n
            assert post(client, token, "closeRecruitTicket", {"id": str(n + 2)}, f"ticket-{n}").status_code == 200
            before = runtime.sync(token)["user"]
            reply = post(client, token, "shopAction", {"buy": [], "recycle": [], "leave": 1}, f"leave-{n}")
            assert reply.status_code == 200, reply.text
            assert apply(before, reply.json()["playerDataDelta"]) == runtime.sync(token)["user"]
            state = current(runtime, token)
            assert state["player"]["cursor"]["zone"] == 2
            assert post(client, token, "shopAction", {"buy": [], "recycle": [], "leave": 1},
                        f"leave-retry-{n}").status_code == 200
            assert current(runtime, token) == state
        assert post(client, token, "gameSettle", {}, "no-fabricated-ending").status_code == 501
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert current(reopened, token) == state and rows(reopened.database.path) == saved
    finally:
        reopened.database.close()


def test_crossing_is_atomic_concurrent_and_clock_rewind_safe(floors_runtime):
    runtime, token = floors_runtime
    setup(runtime, token, ("INCIDENT", "INCIDENT", "INCIDENT"))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, "enter").status_code == 200
        assert post(client, token, "selectChoice", {"choice": "choice_gold"}, "gain").status_code == 200
    before = rows(runtime.database.path)

    def fail(ctx):
        choose(ctx, "choice_leave")
        raise DomainError("INJECTED", "injected after floor advance")

    with pytest.raises(DomainError, match="injected"):
        runtime.mutate(token, None, "rollback", "floor-test", {}, fail)
    assert rows(runtime.database.path) == before
    other = Runtime(runtime.settings)

    def leave(service):
        with TestClient(create_game_app(service)) as client:
            return post(client, token, "selectChoice", {"choice": "choice_leave"}, "leave" + str(id(service))).status_code

    try:
        with ThreadPoolExecutor(2) as pool:
            assert list(pool.map(leave, (runtime, other))) == [200, 200]
    finally:
        other.database.close()
    with runtime.database.transaction() as session:
        cursor = session.query(m.RogueFloorCursor).one()
        assert len(cursor.journal) == 1 and cursor.zone_index == 2
        session.get(m.ServerClockState, 1).fixed_at -= 500
    with TestClient(create_game_app(runtime)) as client:
        reply = scene(client, token, "rewound")
        assert reply.status_code == 200, reply.text
    with runtime.database.transaction(write=False) as session:
        cursor = session.query(m.RogueFloorCursor).one()
        assert len(cursor.journal) == 2 and cursor.journal[1]["at"] >= cursor.journal[0]["at"]


@pytest.mark.parametrize("damage", ["missing", "hash", "jump", "wrong-node", "pending", "wrong-kind", "wrong-id", "time"])
def test_cursor_tampering_refuses_startup_readonly_even_with_rehashed_journal(floors_runtime, damage):
    runtime, token = floors_runtime
    setup(runtime, token, ("INCIDENT", "INCIDENT", "INCIDENT"))
    with TestClient(create_game_app(runtime)) as client:
        assert scene(client, token).status_code == 200
    with runtime.database.transaction() as session:
        cursor = session.query(m.RogueFloorCursor).one()
        value = copy.deepcopy(cursor.journal)
        if damage == "missing":
            session.delete(cursor)
        elif damage == "hash":
            cursor.rule_hash = "0" * 64
        else:
            if damage == "jump":
                cursor.zone_index = 3
            elif damage == "wrong-node":
                value[0]["x"] = 1
            elif damage == "wrong-kind":
                value[0]["kind"] = "battle"
            elif damage == "wrong-id":
                value[0]["record_id"] = "00000000-0000-0000-0000-000000000000"
            elif damage == "time":
                value[0]["at"] -= 1
            elif damage == "pending":
                row = session.query(m.RogueSceneVisit).filter_by(zone_index=1).one()
                row.state, row.ended_at, row.steps = "ACTIVE", None, row.steps[:1]
            cursor.journal = value
            cursor.rule_hash = binding(session.query(m.RogueTopicRun).one(), session.query(m.RogueMapDraft).one(), cursor)
    runtime.database.close()
    saved = rows(runtime.database.path)
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def old_schema(runtime):
    """Reconstruct the exact pre-zone battle columns with real child rows kept."""
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("PRAGMA foreign_keys=OFF")
        sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='rlv2_battles'").fetchone()[0]
        indexes = [r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE type='index' "
                                            "AND tbl_name='rlv2_battles' AND sql IS NOT NULL")]
        columns = [r[1] for r in con.execute("PRAGMA table_info(rlv2_battles)") if r[1] != "zone_index"]
        old = sql.replace("CREATE TABLE rlv2_battles", "CREATE TABLE old_battles")
        old = old.replace("\tzone_index INTEGER DEFAULT '1' NOT NULL, \n", "")
        old = old.replace("UNIQUE (run_id, zone_index, node_x, node_y)", "UNIQUE (run_id, node_x, node_y)")
        old = old.replace("zone_index >= 1 AND ", "")
        assert old != sql and "zone_index" not in old and "CREATE TABLE old_battles" in old
        con.execute(old)
        keys = ",".join(columns)
        con.execute(f"INSERT INTO old_battles({keys}) SELECT {keys} FROM rlv2_battles")
        con.execute("DROP TABLE rlv2_battles")
        con.execute("ALTER TABLE old_battles RENAME TO rlv2_battles")
        for index in indexes:
            con.execute(index)
        con.execute("DROP TABLE rlv2_floor_cursors")
        con.execute("DROP TABLE rlv2_run_closures")
        con.execute("UPDATE alembic_version SET version_num='0027_rogue_shop_visits'")
        assert con.execute("PRAGMA foreign_key_check").fetchone() is None
    return columns


@pytest.mark.parametrize("rollback", [False, True])
def test_27_migration_preserves_battle_children_and_adds_only_initial_cursor(floors_runtime, monkeypatch, rollback):
    runtime, token = floors_runtime
    setup(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        started = begin(client, token)
        assert started.status_code == 200
        hp = current(runtime, token)["player"]["property"]["hp"]["current"]
        assert complete(client, token, started.json()["battleId"], journal(),
                        hp + runtime.data.rogue_initial.battle_temporary_hp).status_code == 200
    snapshot = runtime.sync(token)["user"]
    columns = old_schema(runtime)
    before = rows(runtime.database.path)
    if rollback:
        from terralocal.server.persistence import migrations

        original = migrations._floor_schema

        def fail(con, ops):
            original(con, ops)
            raise RuntimeError("injected after battle rebuild and cursor insert")

        monkeypatch.setattr(migrations, "_floor_schema", fail)
        with pytest.raises(RuntimeError, match="injected"):
            Runtime(runtime.settings)
        assert rows(runtime.database.path) == before
        monkeypatch.setattr(migrations, "_floor_schema", original)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == snapshot
        after = rows(reopened.database.path)
        for table, values in before.items():
            if table not in ("alembic_version", "rlv2_battles"):
                assert after[table] == values
        with sqlite3.connect(reopened.database.path) as con:
            assert con.execute("SELECT " + ",".join(columns) + " FROM rlv2_battles").fetchall() == list(before["rlv2_battles"])
            assert con.execute("SELECT zone_index FROM rlv2_battles").fetchall() == [(1,)]
            cursor = con.execute("SELECT zone_index,journal FROM rlv2_floor_cursors").fetchone()
            assert cursor[0] == 1 and json.loads(cursor[1]) == []
            assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert not con.execute("PRAGMA foreign_key_check").fetchall()
        assert set(after) == set(before) | {"rlv2_floor_cursors", "rlv2_run_closures"}
        assert after["rlv2_run_closures"] == []
    finally:
        reopened.database.close()


def test_floor_timestamp_bounds_abandon_after_clock_rewind(floors_runtime):
    runtime, token = floors_runtime
    setup(runtime, token, ("INCIDENT", "INCIDENT"))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, "enter").status_code == 200
        assert post(client, token, "selectChoice", {"choice": "choice_gold"}, "gain").status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += 100
        assert post(client, token, "selectChoice", {"choice": "choice_leave"}, "exit").status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at -= 500
        reply = post(client, token, "giveUpGame", {}, "abandon-rewound")
        assert reply.status_code == 200, reply.text
    reopened = Runtime(runtime.settings)
    try:
        with reopened.database.transaction(write=False) as session:
            assert session.query(m.RogueTopicRun).one().ended_at >= session.query(m.RogueFloorCursor).one().journal[0]["at"]
    finally:
        reopened.database.close()


def test_corrupt_cursor_backup_never_replaces_live_save(floors_runtime):
    runtime, token = floors_runtime
    setup(runtime, token, ("INCIDENT", "INCIDENT"))
    with TestClient(create_game_app(runtime)) as client:
        assert scene(client, token).status_code == 200
    service = BackupService(runtime)
    backup = service.create()
    path = service.directory / backup["name"]
    with sqlite3.connect(path) as con:
        con.execute("UPDATE rlv2_floor_cursors SET rule_hash=?", ("0" * 64,))
    metadata = path.with_suffix(".json")
    info = json.loads(metadata.read_bytes())
    info["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(info), "utf8")
    before = rows(runtime.database.path)
    with pytest.raises(ValueError, match="楼层游标"):
        service.restore(backup["name"])
    assert rows(runtime.database.path) == before
    assert not list(service.directory.glob("before-restore-*"))
