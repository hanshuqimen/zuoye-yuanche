"""Isolated owned fixtures: transactions, restart, restore and mode isolation."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from crisis_v2_qa import create, set_time, tables
from fastapi.testclient import TestClient
from test_crisis_v2_persistence import rows

from terralocal.server.domain import battle, crisis_v2_battles, operators
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.main import create_game_app
from terralocal.server.persistence import migrations
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.services.backups import backup_existing_save, recover_backup
from terralocal.server.services.runtime import Runtime


def source(*, unknown_condition=False):
    result = tables()
    char = result["character_table"]["char_synthetic"]
    char["skills"].append({"skillId": "locked", "unlockCond": {"phase": "PHASE_1", "level": 1}})
    result["skill_table"]["locked"] = {}
    for entry in result["crisis_v2_server_table"]["seasons"].values():
        for detail in entry["info"]["mapDetailDataMap"].values():
            detail["challengeNodeDataMap"] = {"challenge": {"slotId": "challenge",
                "missionType": "Unverified" if unknown_condition else "PassWithDimScore",
                "missionParamList": ["0;1", "15"], "slotIdList": [], "requiredSlotCount": 0}}
    return result


def prepare(directory, **kwargs):
    runtime, token = create(directory, source_tables=source(**kwargs))
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        op = ctx.rows(m.Operator)[0]
        slots = [{"charInstId": op.id, "skillIndex": 0}]
        operators.formation(ctx, "1", slots)
    payload = {"map_id": "season_a_p", "squad_id": "1", "slots": slots, "rune_slots": ["rune", "rune"]}
    return runtime, token, payload


@pytest.fixture
def ready(tmp_path):
    runtime, token, payload = prepare(tmp_path)
    yield runtime, token, payload
    runtime.database.close()


def begin(runtime, token, payload, key="start"):
    return runtime.mutate(token, None, key, "qa-crisis-v2-start", payload,
                          lambda ctx: crisis_v2_battles.start(ctx, **payload))


def pending(runtime, token, battle_id, **kwargs):
    with runtime.database.transaction(write=False) as session:
        account, local = authenticate_session(session, token)
        ctx = Context(session, runtime.data, account.id, local_session=local)
        return crisis_v2_battles.context(ctx, battle_id, **kwargs)


def test_start_freezes_selection_and_formation_without_ordinary_rewards_or_progress(ready):
    runtime, token, payload = ready
    before = rows(runtime.database.path)
    result = begin(runtime, token, payload)
    saved = pending(runtime, token, result["battleId"], require_session=True)
    assert saved.battle.stage_id not in runtime.data.stages
    assert saved.crisis.level_id == "synthetic/season_a_p"
    assert saved.evaluation.rune_slots == ("rune",)
    assert saved.evaluation.dimension_scores == (10, 5, 0, 0, 0, 0)
    assert saved.battle.squad_snapshot[0]["charInstId"] == payload["slots"][0]["charInstId"]
    assert saved.battle.squad_snapshot[0]["slot"] == 0
    after = rows(runtime.database.path)
    for table in ("sanity_states", "currencies", "inventory_items", "operators", "stage_progress",
                  "crisis_v2_maps", "crisis_v2_seasons"):
        assert after[table] == before[table]
    assert len(after["crisis_v2_battles"]) == len(after["battle_sessions"]) == 1
    assert "session_binding" not in json.dumps(result)


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_retry_creates_exactly_one_battle_and_receipt(ready, same_key):
    runtime, token, payload = ready
    revision = runtime.sync(token)["revision"]

    def attempt(index):
        try:
            return begin(runtime, token, payload, "same" if same_key else str(index))
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    successes = [row for row in results if isinstance(row, dict)]
    assert len(successes) == (6 if same_key else 1)
    assert len({row["battleId"] for row in successes}) == 1
    assert all(row == successes[0] for row in successes)
    assert all(row == "ACTIVE_BATTLE" for row in results if isinstance(row, str))
    assert runtime.sync(token)["revision"] == revision + 1
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.CrisisV2Battle).count() == session.query(m.BattleSession).count() == 1
        assert session.query(m.Receipt).count() == 1


@pytest.mark.parametrize("problem,code", [
    ("unknown-map", "UNKNOWN_CRISIS_V2_MAP"), ("special-slot", "CRISIS_V2_SELECTION_INVALID"),
    ("unknown-slot", "CRISIS_V2_SELECTION_INVALID"), ("wrong-squad", "SQUAD_CONFLICT"),
    ("assist", "CRISIS_V2_ASSIST_UNSUPPORTED"), ("empty", "EMPTY_SQUAD"),
    ("locked-skill", "SKILL_LOCKED"), ("malformed", "INVALID_CRISIS_V2_START"),
])
def test_rejected_starts_preserve_all_rows(ready, problem, code):
    runtime, token, original = ready
    payload = copy.deepcopy(original)
    if problem == "unknown-map":
        payload["map_id"] = "unknown"
    elif problem in {"special-slot", "unknown-slot"}:
        payload["rune_slots"] = ["start" if problem == "special-slot" else "other"]
    elif problem == "wrong-squad":
        payload["slots"] = []
    elif problem == "assist":
        payload["assist_friend"] = {}
    elif problem == "malformed":
        payload["slots"][0]["charInstId"] = True
    else:
        with runtime.database.transaction() as session:
            if problem == "empty":
                operators.formation(Context(session, runtime.data, 1), "1", [])
                payload["slots"] = []
            else:
                session.get(m.SquadSlot, (1, "1", 0)).skill_index = 1
                payload["slots"][0]["skillIndex"] = 1
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        begin(runtime, token, payload)
    assert failure.value.code == code
    assert rows(runtime.database.path) == before


def test_unknown_challenge_configuration_cannot_strand_an_unsettleable_battle(tmp_path):
    runtime, token, payload = prepare(tmp_path, unknown_condition=True)
    try:
        before = rows(runtime.database.path)
        with pytest.raises(DomainError) as failure:
            begin(runtime, token, payload)
        assert failure.value.code == "CRISIS_V2_RULES_UNSUPPORTED" and failure.value.status == 503
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


@pytest.mark.parametrize("at,expected", [(1199, "CRISIS_V2_MAP_NOT_STARTED"), (1200, None), (1700, None),
                                         (2000, "CRISIS_V2_SEASON_CLOSED"), (3000, "CRISIS_V2_INFO_MISSING")])
def test_explicit_local_calendar_does_not_confuse_reward_end_with_battle_close(ready, at, expected):
    runtime, token, payload = ready
    set_time(runtime, at)
    payload["map_id"] = "season_a_t"
    before = rows(runtime.database.path)
    if expected:
        with pytest.raises(DomainError) as failure:
            begin(runtime, token, payload)
        assert failure.value.code == expected
        assert rows(runtime.database.path) == before
    else:
        result = begin(runtime, token, payload)
        assert pending(runtime, token, result["battleId"]).crisis.map_id == "season_a_t"


def test_failure_after_both_rows_flush_rolls_back_the_entire_command(ready):
    runtime, token, payload = ready
    before = rows(runtime.database.path)

    def fail(ctx):
        crisis_v2_battles.start(ctx, **payload)
        ctx.session.flush()
        raise ValueError("authored failure after parent and child insertion")

    with pytest.raises(ValueError, match="authored failure"):
        runtime.mutate(token, None, "failure", "qa-crisis-v2-start", payload, fail)
    assert rows(runtime.database.path) == before


def test_pending_crisis_blocks_normal_start_finish_recovery_and_replay_before_decode(ready):
    runtime, token, payload = ready
    result = begin(runtime, token, payload)
    with runtime.database.transaction() as session:
        new_token = login(session, runtime.settings, name="CrisisDoctor")["secret"]
    before = rows(runtime.database.path)
    for name, action, expected in (
        ("start", lambda ctx: battle.start(ctx, "test_1", "1"), "ACTIVE_BATTLE"),
        ("finish", lambda ctx: battle.finish(ctx, result["battleId"], 3, drop_rules={}),
         "CRISIS_V2_BATTLE_REQUIRES_DEDICATED_FLOW"),
        ("recover", lambda ctx: battle._recover_previous_session(ctx, {}),
         "CRISIS_V2_BATTLE_REQUIRES_DEDICATED_FLOW"),
    ):
        with pytest.raises(DomainError) as failure:
            runtime.mutate(new_token, None, name, "qa-other-mode", {}, action)
        assert failure.value.code == expected
    with TestClient(create_game_app(runtime)) as client:
        response = client.post("/quest/saveBattleReplay", headers={"secret": new_token, "seqnum": "replay"},
            json={"battleId": result["battleId"], "battleReplay": "deliberately invalid compressed data"})
    assert response.status_code == 501
    assert rows(runtime.database.path) == before


def test_normal_battle_blocks_crisis_start(ready):
    runtime, token, payload = ready
    runtime.mutate(token, None, "ordinary", "qa-ordinary-start", {}, lambda ctx: battle.start(ctx, "test_1", "1"))
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        begin(runtime, token, payload)
    assert failure.value.code == "ACTIVE_BATTLE"
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("guard", ["child-row", "parent-marker"])
def test_mode_guard_precedes_colliding_stage_id_and_cached_ordinary_settlement(ready, guard):
    runtime, token, payload = ready
    result = begin(runtime, token, payload)
    with runtime.database.transaction() as session:
        parent = session.get(m.BattleSession, result["battleId"])
        parent.stage_id, parent.state, parent.settlement = "test_1", "FINISHED", {"rewards": []}
        if guard == "child-row":
            parent.native_context = None
        else:
            session.delete(session.get(m.CrisisV2Battle, parent.id))
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        runtime.mutate(token, None, "wrong-finish", "qa-other-mode", {},
            lambda ctx: battle.finish(ctx, result["battleId"], 3, drop_rules={}))
    assert failure.value.code == "CRISIS_V2_BATTLE_REQUIRES_DEDICATED_FLOW"
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("invalid_slot", [-1, 12])
def test_corrupt_saved_squad_slot_fails_without_inserting_a_battle(ready, invalid_slot):
    runtime, token, payload = ready
    with runtime.database.transaction() as session:
        session.get(m.SquadSlot, (1, "1", 0)).slot = invalid_slot
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        begin(runtime, token, payload)
    assert failure.value.code == "INVALID_SQUAD_STATE" and failure.value.status == 503
    assert rows(runtime.database.path) == before


def test_same_sequence_with_changed_selection_is_a_conflict_and_keeps_original_battle(ready):
    runtime, token, payload = ready
    original = begin(runtime, token, payload)
    before = rows(runtime.database.path)
    changed = {**payload, "rune_slots": []}
    with pytest.raises(DomainError) as failure:
        begin(runtime, token, changed)
    assert failure.value.code == "IDEMPOTENCY_CONFLICT"
    assert pending(runtime, token, original["battleId"]).evaluation.rune_slots == ("rune",)
    assert rows(runtime.database.path) == before


def test_context_is_owned_and_new_login_does_not_automatically_abandon_it(ready):
    runtime, token, payload = ready
    result = begin(runtime, token, payload)
    with runtime.database.transaction() as session:
        other = create_account(session, runtime.data, "OtherDoctor")
        other_token = login(session, runtime.settings, name=other.name)["secret"]
        new_token = login(session, runtime.settings, name="CrisisDoctor")["secret"]
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        pending(runtime, other_token, result["battleId"])
    assert failure.value.code == "UNKNOWN_BATTLE"
    with pytest.raises(DomainError) as failure:
        pending(runtime, token, result["battleId"], require_session=True)
    assert failure.value.code == "INVALID_SESSION"
    with pytest.raises(DomainError) as failure:
        pending(runtime, new_token, result["battleId"], require_session=True)
    assert failure.value.code == "CRISIS_V2_SESSION_CONFLICT"
    assert pending(runtime, new_token, result["battleId"]).battle.state == "STARTED"
    assert rows(runtime.database.path) == before


def test_cold_restart_and_fresh_backup_restore_keep_original_selection_and_receipt(ready, tmp_path):
    runtime, token, payload = ready
    result = begin(runtime, token, payload)
    original_hash = pending(runtime, token, result["battleId"]).crisis.start_hash
    with runtime.database.transaction() as session:
        row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
        row.runes, row.challenges = {"rune": 3}, {"challenge": 1}
        session.get(m.Operator, payload["slots"][0]["charInstId"]).trust = 123
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert begin(restarted, token, payload) == result
        saved = pending(restarted, token, result["battleId"], require_session=True)
        assert saved.crisis.start_hash == original_hash
        assert saved.crisis.selection["map_inputs"]["challenge"] == {}
        assert saved.battle.squad_snapshot[0]["trust"] == 0
        before = rows(restarted.database.path)
        archive = backup_existing_save(restarted.settings)
        target = tmp_path / "independent-recovery" / "save.sqlite3"
        recover_backup(restarted.settings, archive["name"], target)
        assert rows(target) == before
        with closing(Database(target)) as recovered:
            recovered.initialize()
            with recovered.transaction(write=False) as session:
                account, local = authenticate_session(session, token)
                ctx = Context(session, restarted.data, account.id, local_session=local)
                saved = crisis_v2_battles.context(ctx, result["battleId"], require_session=True)
                assert saved.crisis.start_hash == original_hash
                assert saved.evaluation.dimension_scores == (10, 5, 0, 0, 0, 0)
        assert rows(restarted.database.path) == before
    finally:
        restarted.database.close()


@pytest.mark.parametrize("damage", ["selection", "hash", "owner", "map", "policy", "parent", "child"])
def test_corrupt_pending_battle_fails_before_any_writable_startup(ready, monkeypatch, damage):
    runtime, token, payload = ready
    result = begin(runtime, token, payload)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        if damage == "selection":
            value = json.loads(connection.execute("SELECT selection FROM crisis_v2_battles").fetchone()[0])
            value["scores"][0] = True
            connection.execute("UPDATE crisis_v2_battles SET selection=?", (json.dumps(value),))
        elif damage in {"hash", "map", "policy"}:
            column = {"hash": "start_hash", "map": "map_hash", "policy": "policy_version"}[damage]
            connection.execute('UPDATE crisis_v2_battles SET "' + column + '"=?', ("invalid",))
        elif damage == "owner":
            connection.execute("UPDATE battle_sessions SET account_id=999")
        else:
            table = "battle_sessions" if damage == "parent" else "crisis_v2_battles"
            connection.execute('DELETE FROM "' + table + '"')
    before = runtime.database.path.read_bytes()
    writable = []
    monkeypatch.setattr(Database, "initialize", lambda database: writable.append(True))
    with pytest.raises(ValueError, match="战斗保存不兼容"):
        Runtime(runtime.settings)
    assert writable == [] and runtime.database.path.read_bytes() == before
    assert result["battleId"]  # Never reinterpret or replace the damaged pending session.


@pytest.mark.parametrize("rollback", [False, True])
def test_0038_upgrade_adds_only_battle_table_and_preserves_every_existing_row(ready, monkeypatch, rollback):
    runtime, _, _ = ready
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        connection.execute("DROP TABLE crisis_v2_battles")
        connection.execute("UPDATE alembic_version SET version_num=?", (migrations.CRISIS_V2_REVISION,))
    before = rows(runtime.database.path)
    original = migrations._crisis_v2_tables
    if rollback:
        def fail(connection):
            original(connection)
            raise ValueError("authored failure after additive 0039 DDL")

        monkeypatch.setattr(migrations, "_crisis_v2_tables", fail)
        with closing(Database(runtime.database.path)) as database, pytest.raises(ValueError, match="authored failure"):
            database.initialize()
        assert rows(runtime.database.path) == before
        monkeypatch.setattr(migrations, "_crisis_v2_tables", original)
    restarted = Runtime(runtime.settings)
    try:
        after = rows(restarted.database.path)
        assert set(after) - set(before) == {"crisis_v2_battles"}
        for table, values in before.items():
            assert after[table] == ([(migrations.REVISION,)] if table == "alembic_version" else values)
        assert after["crisis_v2_battles"] == []
    finally:
        restarted.database.close()


def test_damaged_0038_missing_all_feature_tables_is_not_treated_as_pre_feature_save(ready, monkeypatch):
    runtime, _, _ = ready
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        for name in ("crisis_v2_battles", "crisis_v2_maps", "crisis_v2_seasons", "crisis_v2_accounts"):
            connection.execute('DROP TABLE "' + name + '"')
        connection.execute("UPDATE alembic_version SET version_num=?", (migrations.CRISIS_V2_REVISION,))
    before = runtime.database.path.read_bytes()
    writable = []
    monkeypatch.setattr(Database, "initialize", lambda database: writable.append(True))
    with pytest.raises(ValueError, match="存档表不完整"):
        Runtime(runtime.settings)
    assert writable == [] and runtime.database.path.read_bytes() == before
