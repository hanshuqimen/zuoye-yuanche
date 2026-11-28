"""Atomic clears: records, privacy, conflicting retries and readonly recovery."""

import copy
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from crisis_v2_qa import create, set_time
from test_crisis_v2_battle_sessions import begin, pending
from test_crisis_v2_objective_transactions import source as objective_source
from test_crisis_v2_persistence import rows
from test_native_battle_finish import encoded
from test_native_replay import journal, packed

from terralocal.server.domain import crisis_v2, crisis_v2_clears, crisis_v2_exits, operators
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.protocol.crisis_v2_codec import CrisisFinishRequest
from terralocal.server.protocol.crisis_v2_counters import decode_counters, restore_counters
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import backup_existing_save, recover_backup
from terralocal.server.services.runtime import Runtime


def source():
    result = objective_source()
    result["character_table"]["char_synthetic"]["profession"] = "WARRIOR"
    for entry in result["crisis_v2_server_table"]["seasons"].values():
        for key, detail in entry["info"]["mapDetailDataMap"].items():
            if not key.endswith("_p"):
                detail["bagDataMap"] = {}
                detail["nodeDataMap"]["rune"]["slotPackId"] = None
                continue
            detail["commentDataMap"] = {
                "few": {"id": "few", "condition": "PassWithDeployLess", "paramList": ["9"], "sortId": 0},
                "cost": {"id": "cost", "condition": "PassWithEventLess", "paramList": ["COST", "10"], "sortId": 1}}
    return result


def setup(directory, *, tables=None):
    runtime, token = create(directory, source_tables=source() if tables is None else tables)
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        slots = [{"charInstId": ctx.rows(m.Operator)[0].id, "skillIndex": 0}]
        operators.formation(ctx, "1", slots)
    return runtime, token, {"map_id": "season_a_p", "squad_id": "1", "slots": slots,
                            "rune_slots": ["rune", "second"]}


@pytest.fixture
def ready(tmp_path):
    runtime, token, payload = setup(tmp_path)
    yield runtime, token, payload
    runtime.database.close()


def request(ident, payload, *, rank=3, stats=None, iv=b"synthetic-IV-001", interrupt=False, give_up=False):
    stage = "test_" + payload["map_id"]
    log = journal()
    log["journal"]["metadata"]["stageId"] = stage
    log["journal"]["squad"][0]["charInstId"] = payload["slots"][0]["charInstId"]
    body = encoded(ident, login_time=1001, state=rank, iv=iv,
        changes={"stageId": stage, "interrupt": interrupt, "giveUp": give_up},
        trace_changes={"stats": stats if stats is not None else {
            "charStats": [], "extraBattleInfo": {"SIMPLE,,COST": 10}, "access": "authored-unused-private-marker"}})
    return CrisisFinishRequest.model_validate(body | {"battleLog": packed(log)})


def finish(runtime, token, body, key="clear"):
    return runtime.mutate(token, None, key, "qa-crisis-v2-clear", body.model_dump(),
                          lambda ctx: crisis_v2_clears.finish(ctx, body))


def business(result):
    return {key: result[key] for key in crisis_v2_clears.ClearResult.model_fields}


def map_row(runtime, map_id="season_a_p"):
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.CrisisV2MapProgress, (1, "season_a", map_id))
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}


@pytest.mark.parametrize("rank", [2, 3])
def test_clear_atomically_records_frozen_scores_objectives_comments_and_terminal_receipt(ready, rank):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    before = rows(runtime.database.path)
    old_sync = runtime.sync(token)["user"]
    start_hash = pending(runtime, token, ident).crisis.start_hash
    result = finish(runtime, token, request(ident, payload, rank=rank))
    # Native scoring includes the empty daily bag's 0/0 display bonus. The
    # objective policy separately withholds its unverified empty completion.
    assert result["outcome"] == "CLEARED" and result["scoreCurrent"] == [10, 15, 7, 0, 0, 0]
    assert result["objectives"]["unverifiedEmptyPacks"] == ["daily"]
    assert result["axisRecordsBefore"] == [0]*6 and result["axisRecordsAfter"] == result["scoreCurrent"]
    assert result["newSingleRecord"] and result["singleRecordAfter"] == result["scoreCurrent"]
    assert result["completedRuneCountBefore"] == 0 and result["completedRuneCountAfter"] == 2
    assert result["newComments"] == ["few", "cost"] and result["previouslyEarnedComments"] == []
    value = map_row(runtime)
    assert value["cleared"] and value["comments"] == ["few", "cost"]
    assert value["rune_packs"] == {"bag": 1, "second": 1} and value["challenges"] == {"challenge": 1}
    assert value["rewards"] == {"treasure": {"state": 1, "progress": 2}}
    saved = pending(runtime, token, ident)
    assert saved.battle.state == "FINISHED" and saved.crisis.start_hash == start_hash
    assert saved.battle.settlement["version"] == crisis_v2_clears.VERSION
    after = rows(runtime.database.path)
    allowed = {"battle_sessions", "crisis_v2_maps", "crisis_v2_accounts", "receipts", "player_profiles"}
    assert all(after[k] == v for k, v in before.items() if k not in allowed)
    assert "authored-unused-private-marker" not in json.dumps(after)
    assert "battleLog" not in saved.battle.settlement and "battleData" not in saved.battle.settlement
    assert apply(old_sync, result["playerDataDelta"]) == runtime.sync(token)["user"]
    assert begin(runtime, token, payload, "next-battle")["battleId"] != ident


def test_axis_records_best_single_ties_claims_and_retries_preserve_independent_history(ready):
    runtime, token, payload = ready
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        crisis_v2.initialize(ctx)
        row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
        # The native total-score reader treats state=false as no record,
        # regardless of the arrays. This case starts with a completed record.
        row.cleared = True
        row.score_total, row.score_single = [32, 0, 0, 0, 0, 0], [32, 0, 0, 0, 0, 0]
        row.comments, row.runes = ["few"], {"rune": 3}
        row.challenges, row.rune_packs = {"challenge": 2}, {"bag": 2}
        row.rewards = {"treasure": {"state": 2, "progress": 2}}
        session.get(m.CrisisV2Account, 1).new_record_ts = 2000
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident, payload)
    first = finish(runtime, token, body)
    assert not first["newSingleRecord"] and first["singleRecordAfter"] == [32, 0, 0, 0, 0, 0]
    assert first["axisRecordsAfter"] == [32, 15, 7, 0, 0, 0]
    assert first["newComments"] == ["cost"] and first["previouslyEarnedComments"] == ["few"]
    assert first["completedRuneCountBefore"] == 1 and first["completedRuneCountAfter"] == 2
    value = map_row(runtime)
    assert value["challenges"]["challenge"] == value["rune_packs"]["bag"] == value["rewards"]["treasure"]["state"] == 2
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.CrisisV2Account, 1).new_record_ts == 2001
    original = pending(runtime, token, ident).battle.settlement
    payload["rune_slots"] = ["second"]
    later = begin(runtime, token, payload, "later-battle")["battleId"]
    finish(runtime, token, request(later, payload), "later-clear")
    assert business(finish(runtime, token, body, "first-again")) == business(first)
    assert pending(runtime, token, ident).battle.settlement == original
    assert map_row(runtime)["score_total"] == [32, 15, 7, 0, 0, 0]


def test_equivalent_counter_shapes_iv_and_irrelevant_telemetry_share_one_business_receipt(ready):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident, payload)
    first = finish(runtime, token, body)
    assert finish(runtime, token, body) == first
    original = pending(runtime, token, ident).battle.settlement
    retry = request(ident, payload, iv=b"synthetic-IV-002", stats={"charStats": [],
        "extraBattleInfo": [{"Key": "SIMPLE,,COST", "Value": 10}], "different-unused": [1, 2, 3]})
    set_time(runtime, 1101)
    assert business(finish(runtime, token, retry, "new-sequence")) == business(first)
    assert pending(runtime, token, ident).battle.settlement == original


@pytest.mark.parametrize("change", ["cost", "deploy", "rank", "give-up", "missing-pool"])
def test_changed_business_facts_or_counters_cannot_reinterpret_finished_clear(ready, change):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    finish(runtime, token, request(ident, payload))
    stats = {"charStats": [], "extraBattleInfo": {"SIMPLE,,COST": 10}}
    if change == "cost":
        stats["extraBattleInfo"]["SIMPLE,,COST"] = 9
    elif change == "deploy":
        stats["charStats"] = [{"Key": {"charId": "char_synthetic", "counterType": "SPAWN"}, "Value": 1}]
    elif change == "missing-pool":
        del stats["charStats"]
    body = request(ident, payload, stats=stats, rank=2 if change == "rank" else 3, give_up=change == "give-up")
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        finish(runtime, token, body, "conflict")
    assert failure.value.code == "CRISIS_V2_FINISH_CONFLICT" and rows(runtime.database.path) == before


def test_failure_after_flushing_all_clear_changes_rolls_back_active_lock_and_every_table(ready):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident, payload)
    before = rows(runtime.database.path)

    def fail(ctx):
        crisis_v2_clears.finish(ctx, body)
        ctx.session.flush()
        raise DomainError("QA_ROLLBACK", "authored post-clear failure")

    with pytest.raises(DomainError, match="authored post-clear"):
        runtime.mutate(token, None, "rollback", "qa-clear", {}, fail)
    assert rows(runtime.database.path) == before and pending(runtime, token, ident).battle.state == "STARTED"
    assert finish(runtime, token, body)["outcome"] == "CLEARED"


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_clear_requests_commit_one_business_result(ready, same_key):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident, payload)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: finish(runtime, token, body, "one" if same_key else f"parallel-{n}"), range(4)))
    assert all(business(v) == business(results[0]) for v in results)
    assert map_row(runtime)["comments"] == ["few", "cost"]
    assert map_row(runtime)["rewards"] == {"treasure": {"state": 1, "progress": 2}}


def test_latest_login_reads_clear_but_does_not_take_pending_battle_or_other_account(ready):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident, payload)
    first = finish(runtime, token, body)
    next_id = begin(runtime, token, payload, "next")["battleId"]
    set_time(runtime, 1002)
    with runtime.database.transaction() as session:
        other = create_account(session, runtime.data, "OtherClearDoctor")
        other_token = login(session, runtime.settings, name=other.name)["secret"]
        new_token = login(session, runtime.settings, name="CrisisDoctor")["secret"]
    assert business(finish(runtime, new_token, body, "new-login")) == business(first)
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        finish(runtime, other_token, body, "other")
    assert failure.value.code == "UNKNOWN_BATTLE"
    with pytest.raises(DomainError) as failure:
        finish(runtime, new_token, request(next_id, payload), "pending")
    assert failure.value.code == "CRISIS_V2_SESSION_CONFLICT"
    assert rows(runtime.database.path) == before


def test_clear_and_exit_receipts_cannot_be_consumed_by_the_other_finisher(ready):
    runtime, token, payload = ready
    failed_id = begin(runtime, token, payload)["battleId"]
    failed = request(failed_id, payload, rank=1)
    runtime.mutate(token, None, "exit", "qa-exit", {}, lambda ctx: crisis_v2_exits.finish(ctx, failed))
    with pytest.raises(DomainError) as failure:
        finish(runtime, token, request(failed_id, payload), "cannot-clear-exit")
    assert failure.value.code == "CRISIS_V2_FINISH_CONFLICT"
    ident = begin(runtime, token, payload, "clear-start")["battleId"]
    body = request(ident, payload)
    finish(runtime, token, body)
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        runtime.mutate(token, None, "cannot-exit-clear", "qa-exit", {}, lambda ctx: crisis_v2_exits.finish(ctx, body))
    assert failure.value.code == "CRISIS_V2_FINISH_CONFLICT" and rows(runtime.database.path) == before


def test_temporary_clear_uses_its_own_axes_without_permanent_fields_or_comments(ready):
    runtime, token, payload = ready
    set_time(runtime, 1201)
    payload.update(map_id="season_a_t", rune_slots=["rune"])
    ident = begin(runtime, token, payload)["battleId"]
    before = map_row(runtime)
    result = finish(runtime, token, request(ident, payload, stats={}))
    value = map_row(runtime, "season_a_t")
    assert value["cleared"] and value["score_total"] == [10, 0, 0, 0, 0, 0]
    assert value["comments"] == [] and value["score_single"] == [0]*6 and value["rune_packs"] == {}
    assert result["singleRecordBefore"] is result["singleRecordAfter"] is None and not result["newSingleRecord"]
    assert map_row(runtime) == before


def test_finishing_bound_closed_season_records_history_without_reopening_the_calendar(ready):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    set_time(runtime, 2500)
    result = finish(runtime, token, request(ident, payload))
    snapshot = runtime.sync(token)["user"]["crisisV2"]
    assert snapshot["current"] == "" and snapshot["seasons"]["season_a"]["permanent"]["state"]
    assert result["finishedAt"] == 2500 and result["scoreCurrent"] == snapshot["seasons"]["season_a"]["permanent"]["scoreTotal"]


@pytest.mark.parametrize("issue", ["objectives", "negative-axis"])
def test_unadmitted_record_definitions_never_partially_commit_a_clear(tmp_path, issue):
    tables = source()
    detail = tables["crisis_v2_server_table"]["seasons"]["season_a"]["info"]["mapDetailDataMap"]["season_a_p"]
    if issue == "objectives":
        detail["bagDataMap"]["bag"]["slotPackType"] = "UnverifiedObjective"
    else:
        detail["runeDataMap"]["test"]["score"] = -10
    runtime, token, payload = setup(tmp_path, tables=tables)
    try:
        ident = begin(runtime, token, payload)["battleId"]
        before = rows(runtime.database.path)
        with pytest.raises(DomainError) as failure:
            finish(runtime, token, request(ident, payload))
        assert failure.value.code == "CRISIS_V2_CLEAR_UNSUPPORTED" and rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_cold_restart_new_directory_backup_restore_and_later_receipt_retry_are_identical(ready, tmp_path):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident, payload)
    first = finish(runtime, token, body)
    next_id = begin(runtime, token, payload, "next-battle")["battleId"]
    before = rows(runtime.database.path)
    settings = runtime.settings
    runtime.database.close()
    restarted = Runtime(settings)
    try:
        assert rows(restarted.database.path) == before
        assert finish(restarted, token, body) == first
        assert pending(restarted, token, next_id).battle.state == "STARTED"
        archive = backup_existing_save(settings)
        destination = tmp_path / "restored-clear"
        recover_backup(settings, archive["name"], destination / "terralocal.sqlite3")
        shutil.copytree(settings.data_dir / "cache", destination / "cache")
        restored_settings = settings.model_copy(update={"data_dir": destination})
        restored = Runtime(restored_settings)
        try:
            assert rows(restored.database.path) == before
            assert finish(restored, token, body) == first
            assert rows(restored.database.path) == before
        finally:
            restored.database.close()
    finally:
        restarted.database.close()


@pytest.mark.parametrize("damage", ["request-hash", "finish-time", "version", "counter", "result", "after-map",
                                   "rule-hash", "journal-hash", "timestamp", "exit-state"])
def test_damaged_clear_is_rejected_before_writable_startup_even_with_rehashed_body(ready, monkeypatch, damage):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    finish(runtime, token, request(ident, payload))
    settings = runtime.settings
    runtime.database.close()
    with sqlite3.connect(settings.database_path) as db:
        row = json.loads(db.execute("SELECT settlement FROM battle_sessions WHERE id=?", (ident,)).fetchone()[0])
        if damage == "request-hash":
            db.execute("UPDATE battle_sessions SET request_hash=? WHERE id=?", ("0"*64, ident))
        elif damage == "finish-time":
            db.execute("UPDATE battle_sessions SET finished_at=finished_at+1 WHERE id=?", (ident,))
        elif damage == "exit-state":
            db.execute("UPDATE battle_sessions SET state='ABORTED' WHERE id=?", (ident,))
        else:
            if damage == "version":
                row["version"] = "unknown-clear-version"
            elif damage == "counter":
                row["counters"]["extra"][0][4] = 9
            elif damage == "result":
                row["result"]["scoreCurrent"][0] += 1
            elif damage == "after-map":
                row["map_after"]["challenge"]["challenge"] = 2
            elif damage == "rule-hash":
                row["comments_hash"] = "0"*64
            elif damage == "journal-hash":
                row["journal_hash"] = "not-a-digest"
            else:
                row["record_ts_after"] += 1
            row["hash"] = fingerprint({k: v for k, v in row.items() if k != "hash"})
            db.execute("UPDATE battle_sessions SET settlement=? WHERE id=?", (json.dumps(row), ident))
    before = settings.database_path.read_bytes()
    writable = []
    monkeypatch.setattr(Database, "initialize", lambda database: writable.append(True))
    with pytest.raises(ValueError, match="危机合约战斗保存不兼容"):
        Runtime(settings)
    assert writable == [] and settings.database_path.read_bytes() == before


def test_selected_counter_receipt_round_trip_and_noncanonical_values_are_not_admitted():
    counters = decode_counters({"charStats": [], "enemyStats": [], "extraBattleInfo": {
        "ATTRIBUTE,enemy,HP_RATIO,0.010": 2, "SIMPLE,,COST": 10}})
    value = counters.canonical()
    assert restore_counters(value).canonical() == value
    cases = [value | {"codec": "unknown"}, value | {"unexpected": 1},
             value | {"extra": list(reversed(value["extra"]))}]
    duplicate = copy.deepcopy(value)
    duplicate["extra"].append(duplicate["extra"][0])
    cases.append(duplicate)
    wrong = copy.deepcopy(value)
    wrong["extra"][0][3] = True
    cases.append(wrong)
    for invalid in cases:
        with pytest.raises(ValueError, match="回执计数"):
            restore_counters(invalid)
