"""Owned exits: normalized receipts, rollback, retries and damaged-save refusal."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from itertools import product

import pytest
from crisis_v2_qa import set_time
from test_crisis_v2_battle_sessions import begin
from test_crisis_v2_battle_sessions import ready as ready
from test_crisis_v2_persistence import rows
from test_native_battle_finish import encoded

from terralocal.server.domain import battle, crisis_v2_battles, crisis_v2_exits, crisis_v2_objectives
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence.database import Database
from terralocal.server.protocol.crisis_v2_codec import CrisisFinishRequest
from terralocal.server.services.runtime import Runtime


def request(battle_id, *, rank=1, interrupt=False, give_up=False, iv=b"synthetic-IV-001", stats=None, **changes):
    body = encoded(battle_id, login_time=1001, state=rank, iv=iv,
        changes={"stageId": "test_season_a_p", "interrupt": interrupt, "giveUp": give_up, **changes},
        trace_changes={} if stats is None else {"stats": stats})
    return CrisisFinishRequest.model_validate(body)


def finish(runtime, token, body, key="finish"):
    return runtime.mutate(token, None, key, "qa-crisis-v2-exit", body.model_dump(),
        lambda ctx: crisis_v2_exits.finish(ctx, body))


def business(result):
    return {key: result[key] for key in ("battleId", "outcome", "finishedAt")}


def bound(runtime, token, ident):
    with runtime.database.transaction(write=False) as session:
        account, local = authenticate_session(session, token)
        return crisis_v2_battles.context(Context(session, runtime.data, account.id, local_session=local),
                                        ident, require_session=True)


@pytest.mark.parametrize("rank,interrupt,give_up", list(product((1, 2, 3), (False, True), (False, True))))
def test_normalized_rank_flags_are_not_ordinary_stars_or_automatic_progress(rank, interrupt, give_up):
    facts = crisis_v2_exits.FinishFacts(battleId="00000000-0000-4000-8000-000000000001", stageId="test",
        rank=rank, interrupt=interrupt, giveUp=give_up, percent=100., kills=100, validKills=99, duration=20)
    expected = "ABORTED" if interrupt or give_up else "FAILED" if rank == 1 else "CLEAR_CANDIDATE"
    assert crisis_v2_exits.outcome(facts) == expected


@pytest.mark.parametrize("rank,interrupt,give_up,outcome,state", [
    (1, False, False, "FAILED", "FINISHED"), (1, True, False, "ABORTED", "ABORTED"),
    (2, True, False, "ABORTED", "ABORTED"), (3, False, True, "ABORTED", "ABORTED")])
def test_exit_finishes_only_owned_battle_and_never_stores_telemetry_or_grants_progress(
        ready, rank, interrupt, give_up, outcome, state):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    before = rows(runtime.database.path)
    body = request(ident, rank=rank, interrupt=interrupt, give_up=give_up,
        percent=100, killCnt=600, validKillCnt=500, stats={"access": "authored-unused-telemetry"})
    result = finish(runtime, token, body)
    saved = bound(runtime, token, ident)
    assert saved.battle.state == state and result["outcome"] == outcome
    assert saved.battle.finished_at == result["finishedAt"] == 1001
    assert saved.battle.settlement["facts"]["validKills"] == 500
    after = rows(runtime.database.path)
    assert all(after[k] == v for k, v in before.items() if k not in {"battle_sessions", "player_profiles", "receipts"})
    assert "authored-unused-telemetry" not in json.dumps(after)
    assert saved.crisis.start_hash == before["crisis_v2_battles"][0][-1]
    assert begin(runtime, token, payload, "next-battle")["battleId"] != ident


def test_same_key_and_different_iv_sequence_retries_keep_original_business_receipt(ready):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident)
    result = finish(runtime, token, body)
    assert finish(runtime, token, body) == result
    original = bound(runtime, token, ident).battle.settlement
    set_time(runtime, 1101)
    retry = request(ident, iv=b"synthetic-IV-002", stats={"anything": [1, 2]})
    assert business(finish(runtime, token, retry, "different-iv")) == business(result)
    assert bound(runtime, token, ident).battle.settlement == original


@pytest.mark.parametrize("change", [{"rank": 2}, {"interrupt": True}, {"percent": 50},
    {"killCnt": 1}, {"validKillCnt": 1}])
def test_changed_business_facts_cannot_reinterpret_a_finished_exit(ready, change):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    finish(runtime, token, request(ident))
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as error:
        finish(runtime, token, request(ident, **change), "conflict")
    assert error.value.code == "CRISIS_V2_FINISH_CONFLICT"
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("rank", [2, 3])
def test_clear_candidate_is_not_replaced_by_an_empty_successful_exit(ready, rank):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as error:
        finish(runtime, token, request(ident, rank=rank))
    assert error.value.code == "CRISIS_V2_CLEAR_UNSUPPORTED" and error.value.status == 501
    assert rows(runtime.database.path) == before


def test_caller_failure_rolls_back_exit_and_preserves_active_lock(ready):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident)
    before = rows(runtime.database.path)

    def fail(ctx):
        crisis_v2_exits.finish(ctx, body)
        ctx.session.flush()
        raise DomainError("QA_ROLLBACK", "authored failure after receipt")

    with pytest.raises(DomainError, match="authored failure"):
        runtime.mutate(token, None, "rollback", "qa-exit", {}, fail)
    assert rows(runtime.database.path) == before
    assert bound(runtime, token, ident).battle.state == "STARTED"
    assert finish(runtime, token, body)["outcome"] == "FAILED"


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_exits_have_one_durable_business_receipt_and_no_grants(ready, same_key):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    before = rows(runtime.database.path)
    body = request(ident, rank=3, interrupt=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: finish(runtime, token, body, "same" if same_key else f"seq-{n}"), range(4)))
    assert all(business(r) == business(results[0]) for r in results)
    after = rows(runtime.database.path)
    assert all(after[k] == v for k, v in before.items() if k not in {"battle_sessions", "player_profiles", "receipts"})
    assert bound(runtime, token, ident).battle.state == "ABORTED"


def test_latest_login_can_read_finished_receipt_but_cannot_claim_old_pending_battle(ready):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident)
    result = finish(runtime, token, body)
    pending_id = begin(runtime, token, payload, "new-battle")["battleId"]
    set_time(runtime, 1002)
    with runtime.database.transaction() as session:
        new = login(session, runtime.settings, name="CrisisDoctor")["secret"]
    assert business(finish(runtime, new, body, "after-login")) == business(result)
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as error:
        finish(runtime, new, request(pending_id), "old-pending")
    assert error.value.code == "CRISIS_V2_SESSION_CONFLICT"
    assert rows(runtime.database.path) == before


def test_finished_exit_rejects_other_account_and_later_objectives_or_ordinary_settlement(ready):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    finish(runtime, token, request(ident))
    with runtime.database.transaction() as session:
        other = create_account(session, runtime.data, "OtherExitDoctor")
        other_token = login(session, runtime.settings, name=other.name)["secret"]
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as error:
        finish(runtime, other_token, request(ident), "other")
    assert error.value.code == "UNKNOWN_BATTLE"
    with pytest.raises(DomainError) as error:
        runtime.mutate(token, None, "objectives", "qa-objectives", {},
            lambda ctx: crisis_v2_objectives.record(ctx, ident, cleared=True))
    assert error.value.code == "CRISIS_V2_BATTLE_ALREADY_FINISHED"
    with runtime.database.transaction() as session, pytest.raises(DomainError) as error:
        battle.native_finish(Context(session, runtime.data, 1), ident, "test_season_a_p",
            complete_state=1, interrupted=True, give_up=False, percent=0, kills=0, valid_kills=0,
            duration=20, drop_rules=None)
    assert error.value.code == "NATIVE_CONTEXT_UNAVAILABLE"
    assert rows(runtime.database.path) == before


def test_restart_preserves_exit_receipt_without_regranting_or_overwriting_a_new_battle(ready):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident, give_up=True)
    result = finish(runtime, token, body)
    next_id = begin(runtime, token, payload, "next-battle")["battleId"]
    before = rows(runtime.database.path)
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert rows(restarted.database.path) == before
        assert finish(restarted, token, body) == result
        assert rows(restarted.database.path) == before
        assert bound(restarted, token, next_id).battle.state == "STARTED"
    finally:
        restarted.database.close()


@pytest.mark.parametrize("damage", ["request-hash", "finish-time", "start-hash", "receipt-hash",
    "version", "response", "facts", "clear", "missing"])
def test_damaged_exit_refuses_startup_before_writable_initialization(ready, monkeypatch, damage):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    finish(runtime, token, request(ident))
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as db:
        if damage == "request-hash":
            db.execute("UPDATE battle_sessions SET request_hash='invalid' WHERE id=?", (ident,))
        elif damage == "finish-time":
            db.execute("UPDATE battle_sessions SET finished_at=finished_at+1 WHERE id=?", (ident,))
        elif damage == "start-hash":
            db.execute("UPDATE crisis_v2_battles SET start_hash=? WHERE battle_id=?", ("0"*64, ident))
        else:
            value = json.loads(db.execute("SELECT settlement FROM battle_sessions WHERE id=?", (ident,)).fetchone()[0])
            if damage == "receipt-hash":
                value["hash"] = "0"*64
            elif damage == "version":
                value["version"] = "unverified"
            elif damage == "response":
                value["result"]["outcome"] = "ABORTED"
            elif damage == "facts":
                value["facts"]["kills"] = 1
            elif damage == "clear":
                value["facts"]["rank"] = 3
                value["hash"] = fingerprint({k: v for k, v in value.items() if k != "hash"})
            else:
                value = None
            db.execute("UPDATE battle_sessions SET settlement=? WHERE id=?", (json.dumps(value), ident))
    before = runtime.database.path.read_bytes()
    writable = []
    monkeypatch.setattr(Database, "initialize", lambda database: writable.append(True))
    with pytest.raises(ValueError, match="危机合约战斗保存不兼容"):
        Runtime(runtime.settings)
    assert writable == [] and runtime.database.path.read_bytes() == before
