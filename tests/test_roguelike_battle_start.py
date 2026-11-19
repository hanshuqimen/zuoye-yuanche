"""Independent first-node battle transactions; authored data, no native win claim."""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from rogue_qa_rules import add_base_score
from test_roguelike_initial import current, post
from test_roguelike_map import authored_placements
from test_roguelike_map import tables as map_tables
from test_roguelike_recruit import offered, prepare, recruit_tables
from test_roguelike_state import rows

from terralocal.config import Settings
from terralocal.server.domain import battle, campaign_battle, rogue_battle
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Column, Entry, Plan
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import REVISION, ROGUE_ACTIVATION_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def rogue_battle_runtime(tmp_path):
    tables = recruit_tables()
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    maps = map_tables()["roguelike_topic_table"]["details"]["rogue_1"]
    for key in ("stages", "zones", "nodeTypeData", "gameConst"):
        detail[key] = maps[key]
    # Closing a started exploration now requires a real score contract. These
    # are authored QA rules, shared by the battle/visit fixtures, not a server
    # fallback for missing GameData.
    add_base_score(tables)
    detail["zones"]["zone_1"] = {"id": "zone_1", "isHiddenZone": False}
    detail["items"]["test_gold"] = {"id": "test_gold", "type": "GOLD"}
    for row in detail["detailConst"]["playerLevelTable"].values():
        row.update(populationUp=0, squadCapacityUp=0, battleCharLimitUp=0, maxHpUp=0)
    detail["detailConst"]["playerLevelTable"]["2"]["populationUp"] = 4
    authored_placements(tables)
    source = tmp_path / "source"
    source.mkdir()
    for key, value in tables.items():
        (source / (key + ".json")).write_text(json.dumps(value), "utf8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        create_account(session, runtime.data, "RogueBattleDoctor")
        create_account(session, runtime.data, "OtherDoctor")
        ctx = Context(session, runtime.data, 1)
        op, _ = ctx.acquire_operator("char_six")
        op.evolve_phase, op.level, op.skill_level = 2, 1, 7
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=1, clear_count=1,
                                    first_clear_claimed=True, unlocked=True))
        token = login(session, settings, name="RogueBattleDoctor")["secret"]
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token)
        for index, cid in enumerate(("char_six", "char_reserve", None)):
            assert post(client, token, "activeRecruitTicket", {"id": str(index)}, "active" + str(index)).status_code == 200
            if cid:
                option = next(o for o in offered(runtime, token, str(index)) if o["charId"] == cid)
                response = post(client, token, "recruitChar", {"ticketIndex": str(index),
                    "optionId": str(option["instId"])}, "recruit" + str(index))
            else:
                response = post(client, token, "closeRecruitTicket", {"id": str(index)}, "close")
            assert response.status_code == 200
    yield runtime, token
    runtime.database.close()


def activate(runtime, token, kind="BATTLE_NORMAL", stage="ordinary"):
    spec = Plan("zone_1", (Column(1, 1, (Entry(kind, 1, stage),)),
                           Column(1, 1, (Entry("SHOP", 1),))), 0)
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), spec)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "finish-initial").status_code == 200


def body(stage="ordinary"):
    # Labels are optional in the frozen squad model; sparse slots stay sparse.
    return {"to": {"x": 0, "y": 0}, "stageId": stage, "squad": {"squadId": None, "name": None,
        "slots": [{"charInstId": 1, "skillIndex": 1, "currentEquip": None}, None,
                  {"charInstId": 2, "skillIndex": -1, "currentEquip": None}]}}


def begin(client, token, payload=None, key="battle-start"):
    return post(client, token, "moveAndBattleStart", body() if payload is None else payload, key)


def test_native_v12_request_shape_with_unvoiced_reserve(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    # v12 captured to/stageId/squad and null labels, two contiguous slots.
    # Substitute only the authored stage ID; no client/auth/resource fixture.
    payload = body()
    payload["squad"]["slots"] = [
        {"charInstId": 1, "skillIndex": 0, "currentEquip": None},
        {"charInstId": 2, "skillIndex": -1, "currentEquip": None}]
    with TestClient(create_game_app(runtime)) as client:
        response = begin(client, token, payload)
        assert response.status_code == 200, response.text
    with runtime.database.transaction(write=False) as session:
        saved = session.query(m.RogueBattle).one()
        assert saved.squad[1]["character"]["defaultSkillIndex"] == -1


def test_start_delta_persistence_retry_and_no_permanent_rewards(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    before = runtime.sync(token)["user"]
    old_rows = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        first = begin(client, token)
        assert first.status_code == 200, first.text
        response = first.json()
        after = runtime.sync(token)["user"]
        assert apply(before, response["playerDataDelta"]) == after
        assert {k: v for k, v in before.items() if k != "rlv2"} == {
            k: v for k, v in after.items() if k != "rlv2"}
        state = after["rlv2"]["current"]
        assert state["player"]["state"] == "PENDING"
        assert state["player"]["cursor"] == {"zone": 1, "position": {"x": 0, "y": 0}}
        assert state["player"]["pending"][0]["type"] == "BATTLE"
        saved = rows(runtime.database.path)
        assert begin(client, token).json() == response and rows(runtime.database.path) == saved
        retry = begin(client, token, key="new-sequence")
        assert retry.status_code == 200 and retry.json()["battleId"] == response["battleId"]
        changed = body()
        changed["squad"]["slots"][0]["skillIndex"] = 0
        assert begin(client, token, changed).status_code == 409  # Existing receipt mismatch.
        assert begin(client, token, changed, "new-formation").status_code == 409
    saved = rows(runtime.database.path)
    changed_tables = {k for k in saved if saved[k] != old_rows[k]}
    assert changed_tables <= {"rlv2_battles", "player_profiles", "receipts"}
    assert len(saved["rlv2_battles"]) == 1 and saved["battle_sessions"] == old_rows["battle_sessions"]
    with runtime.database.transaction(write=False) as session:
        row = session.query(m.RogueBattle).one()
        assert row.squad[1] is None and row.squad[0]["character"]["evolvePhase"] == 1
        assert row.squad[0]["character"]["defaultSkillIndex"] == 1
        assert row.squad[2]["character"]["voiceLan"] == "NONE"
        assert row.session_binding not in json.dumps(response)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after
        service = BackupService(reopened)
        backup = service.create()
        service.restore(backup["name"])
        assert rows(runtime.database.path) == saved
    finally:
        reopened.database.close()


@pytest.mark.parametrize("kind,stage,status", [("BATTLE_NORMAL", "ordinary", 200),
    ("BATTLE_ELITE", "emergency", 501), ("BATTLE_BOSS", "boss", 501)])
def test_battle_kind_reuses_bound_node_and_data(rogue_battle_runtime, kind, stage, status):
    runtime, token = rogue_battle_runtime
    activate(runtime, token, kind, stage)
    with TestClient(create_game_app(runtime)) as client:
        assert begin(client, token, body(stage)).status_code == status
    with runtime.database.transaction(write=False) as session:
        if status == 200:
            assert session.query(m.RogueBattle).one().stage_id == stage
        else:
            assert session.query(m.RogueBattle).count() == 0


@pytest.mark.parametrize("damage,status", [("target", 409), ("stage", 400), ("empty", 400),
    ("duplicate", 400), ("permanent-id", 400), ("skill-locked", 400), ("reserve-skill", 400),
    ("reserve-zero", 400), ("module", 501), ("resume", 501), ("bool-coordinate", 422), ("extra", 422),
    ("extra-slot-field", 422), ("too-many-slots", 422)])
def test_bad_request_never_writes_battle_or_receipt(rogue_battle_runtime, damage, status):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    payload = body()
    slots = payload["squad"]["slots"]
    if damage == "target":
        payload["to"]["x"] = 1
    elif damage == "stage":
        payload["stageId"] = "boss"
    elif damage == "empty":
        payload["squad"]["slots"] = [None]
    elif damage == "duplicate":
        slots[2] = copy.deepcopy(slots[0])
    elif damage == "permanent-id":
        slots[0]["charInstId"] = 999
    elif damage == "skill-locked":
        slots[0]["skillIndex"] = 2
    elif damage == "reserve-skill":
        slots[2]["skillIndex"] = 1
    elif damage == "reserve-zero":
        slots[2]["skillIndex"] = 0
    elif damage == "module":
        slots[0]["currentEquip"] = "module"
    elif damage == "resume":
        payload["to"] = None
    elif damage == "bool-coordinate":
        payload["to"]["x"] = False
    elif damage == "extra":
        payload["rewards"] = [{"id": "4001", "count": 1}]
    elif damage == "extra-slot-field":
        slots[0]["level"] = 90
    else:
        payload["squad"]["slots"] = [None] * 13
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        response = begin(client, token, payload)
        assert response.status_code == status, response.text
    assert rows(runtime.database.path) == saved


def test_nonbattle_node_owner_and_login_guards(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    with runtime.database.transaction() as session:
        other = login(session, runtime.settings, name="OtherDoctor")["secret"]
    activate(runtime, token, "REST", None)
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        assert begin(client, other).status_code == 409
        response = begin(client, token)
        assert response.status_code == 400 and response.json()["error"]["code"] == "ROGUE_NODE_NOT_BATTLE"
    assert rows(runtime.database.path) == saved


def test_parallel_runtimes_and_outer_failure(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    def action(ctx):
        payload = body()
        return rogue_battle.start(ctx, payload["to"], payload["stageId"], payload["squad"]["slots"])
    def fail(ctx):
        action(ctx)
        raise RuntimeError("injected before commit")
    before = rows(runtime.database.path)
    with pytest.raises(RuntimeError, match="injected"):
        runtime.mutate(token, None, "failure", "rogue-battle-test", {}, fail)
    assert rows(runtime.database.path) == before
    other = Runtime(runtime.settings)
    try:
        def invoke(service):
            return service.mutate(token, None, "same", "rogue-battle-test", {}, action)
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(invoke, (runtime, other)))
        assert replies[0] == replies[1]
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueBattle).count() == 1
    finally:
        other.database.close()


def test_cross_mode_start_blocking_and_abandon_without_rewards(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert begin(client, token).status_code == 200
        saved = rows(runtime.database.path)
        for start in (lambda ctx: battle.start(ctx, "test_1", "0", False),
                      lambda ctx: campaign_battle.start(ctx, "missing", "0", [], drop_rules={})):
            with runtime.database.transaction() as session:
                with pytest.raises(DomainError) as exc:
                    start(Context(session, runtime.data, 1))
                assert exc.value.code == "ROGUE_BATTLE_ACTIVE"
        assert rows(runtime.database.path) == saved
        before = runtime.sync(token)["user"]
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at -= 100
        assert post(client, token, "giveUpGame", {}, "abandon").status_code == 200
        after = runtime.sync(token)["user"]
        for key in ("troop", "inventory", "dungeon", "mission"):
            assert before[key] == after[key]
    with runtime.database.transaction(write=False) as session:
        row = session.query(m.RogueBattle).one()
        run = session.query(m.RogueTopicRun).one()
        assert row.state == run.state == "ABANDONED"
        assert run.ended_at >= row.ended_at >= row.started_at
    reopened = Runtime(runtime.settings)
    reopened.database.close()


def test_new_login_preserves_old_battle_and_refuses_guessing_resume(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        with runtime.database.transaction() as session:
            newer = login(session, runtime.settings, name="RogueBattleDoctor")["secret"]
        assert begin(client, token).status_code == 401
        assert begin(client, newer).status_code == 200
        with runtime.database.transaction() as session:
            newest = login(session, runtime.settings, name="RogueBattleDoctor")["secret"]
        saved = rows(runtime.database.path)
        assert begin(client, newest).status_code == 501
        assert rows(runtime.database.path) == saved


def test_ordinary_battle_blocks_rogue_start_without_charging(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    with runtime.database.transaction() as session:
        session.add(m.BattleSession(id="existing-ordinary", account_id=1, stage_id="test_1", state="STARTED",
            sanity_cost=6, started_at=1_800_000_000, seed=1, squad_snapshot=[]))
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        response = begin(client, token)
        assert response.status_code == 409 and response.json()["error"]["code"] == "ACTIVE_BATTLE"
    assert rows(runtime.database.path) == saved


def test_corrupt_backup_and_missing_current_table_preserve_original(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert begin(client, token).status_code == 200
    service = BackupService(runtime)
    backup = service.create()
    candidate = service.directory / backup["name"]
    with sqlite3.connect(candidate) as con:
        con.execute("UPDATE rlv2_battles SET session_binding=?", ("0" * 64,))
    metadata = candidate.with_suffix(".json")
    info = json.loads(metadata.read_bytes())
    info["sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(info), "utf8")
    saved = rows(runtime.database.path)
    with pytest.raises(ValueError, match="探索战斗记录"):
        service.restore(backup["name"])
    assert rows(runtime.database.path) == saved and not list(service.directory.glob("before-restore-*"))
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TABLE rlv2_battle_settlements")
        con.execute("DROP TABLE rlv2_battles")
    saved = rows(runtime.database.path)
    with pytest.raises(ValueError, match="探索结算或领取记录"):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved


@pytest.mark.parametrize("damage", ["stage", "node", "owner", "policy", "data", "squad", "session", "seed", "hash", "time"])
def test_corrupt_battle_rejected_before_startup_write(rogue_battle_runtime, damage):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert begin(client, token).status_code == 200
    with runtime.database.transaction() as session:
        row = session.query(m.RogueBattle).one()
        if damage == "stage":
            row.stage_id = "boss"
        elif damage == "node":
            row.node_x = 1
        elif damage == "owner":
            row.account_id = 2
        elif damage == "policy":
            row.policy_version = "future"
        elif damage == "data":
            row.gamedata_hash = "0" * 64
        elif damage == "squad":
            value = copy.deepcopy(row.squad)
            value[0]["character"]["level"] += 1
            row.squad = value
        elif damage == "session":
            row.session_binding = "0" * 64
        elif damage == "seed":
            pass  # Damage the file below; a normal transaction rejects this value.
        elif damage == "hash":
            row.request_hash = "0" * 64
        else:
            row.started_at = 0
    runtime.database.close()
    if damage == "seed":
        with sqlite3.connect(runtime.database.path) as con:
            con.execute("PRAGMA ignore_check_constraints=ON")
            con.execute("UPDATE rlv2_battles SET seed=?", (2**31,))
    saved = rows(runtime.database.path)
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    # Shared path replay also checks started visits before battle preflight.
    message = "探索战斗记录|探索记录与已接纳" if damage == "node" else "探索战斗记录"
    with pytest.raises(ValueError, match=message):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def test_0022_upgrade_and_rollback_keep_every_existing_row(rogue_battle_runtime, monkeypatch):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    state = current(runtime, token)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TABLE rlv2_battle_loot_plans")
        con.execute("DROP TABLE rlv2_bank_visits")
        con.execute("DROP TABLE rlv2_bank_wallets")
        con.execute("DROP TABLE rlv2_floor_cursors")
        con.execute("DROP TABLE rlv2_shop_visits")
        con.execute("DROP TABLE rlv2_scene_visits")
        con.execute("DROP TABLE rlv2_game_settlements")
        con.execute("DROP TABLE rlv2_battle_settlements")
        con.execute("DROP TABLE rlv2_battles")
        con.execute("DROP TABLE rlv2_run_closures")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_ACTIVATION_REVISION,))
    before = rows(runtime.database.path)
    original = m.RogueBattle.__table__.create
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected table creation failure")
    monkeypatch.setattr(m.RogueBattle.__table__, "create", fail)
    db = Database(runtime.database.path)
    try:
        with pytest.raises(RuntimeError, match="injected table creation"):
            db.initialize()
        assert rows(db.path) == before
    finally:
        db.close()
    monkeypatch.setattr(m.RogueBattle.__table__, "create", original)
    reopened = Runtime(runtime.settings)
    try:
        after = rows(reopened.database.path)
        assert len(before) == 68 and len(after) == 78
        assert all(after[k] == v for k, v in before.items() if k != "alembic_version")
        assert after["alembic_version"] == [(REVISION,)] and not after["rlv2_battles"]
        assert current(reopened, token) == state
    finally:
        reopened.database.close()
