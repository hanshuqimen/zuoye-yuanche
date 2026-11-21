"""Native HTTP contracts with authored journals; no client gameplay claim."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from crisis_v2_qa import set_time
from fastapi.testclient import TestClient
from test_crisis_v2_battle_sessions import pending
from test_crisis_v2_clears import request, setup
from test_crisis_v2_clears import source as clear_source
from test_crisis_v2_persistence import rows

from terralocal.server.domain import crisis_v2_native
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.protocol.crisis_v2_battle import FinishResponse
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


def source(*, missing_effect=False):
    result = clear_source()
    for entry in result["crisis_v2_server_table"]["seasons"].values():
        for detail in entry["info"]["mapDetailDataMap"].values():
            for ident, rune in detail["runeDataMap"].items():
                if not missing_effect:
                    rune["packedRune"] = {"id": ident, "points": 0.0, "runes": []}
    return result


@pytest.fixture
def ready(tmp_path):
    runtime, token, payload = setup(tmp_path, tables=source())
    with TestClient(create_game_app(runtime)) as client:
        yield runtime, client, token, payload
    runtime.database.close()


def start(client, token, payload, key="native-start", **changes):
    body = {"mapId": payload["map_id"], "runeSlots": payload["rune_slots"], "assistFriend": None,
            "squad": {"squadId": payload["squad_id"], "name": None, "slots": payload["slots"]}} | changes
    return client.post("/crisisV2/battleStart", json=body, headers={"secret": token, "seqnum": key})


def finish(client, token, body, key="native-finish"):
    return client.post("/crisisV2/battleFinish", json=body.model_dump(), headers={"secret": token, "seqnum": key})


def native(body):
    return FinishResponse.model_validate({key: body[key] for key in FinishResponse.model_fields}).model_dump()


def cache(runtime, ident):
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.Receipt, (1, crisis_v2_native.PREFIX+ident))
        return copy.deepcopy(row.result)


@pytest.mark.parametrize("rank,interrupt,give_up", [(3, False, False), (2, False, False),
                                                   (1, False, False), (3, True, False), (3, False, True)])
def test_native_start_and_finish_use_real_ids_two_counts_and_atomic_player_delta(ready, rank, interrupt, give_up):
    runtime, client, token, payload = ready
    started = start(client, token, payload)
    assert started.status_code == 200, started.text
    ident = started.json()["battleId"]
    old_sync = runtime.sync(token)["user"]
    result = finish(client, token, request(ident, payload, rank=rank, interrupt=interrupt, give_up=give_up))
    assert result.status_code == 200, result.text
    body = result.json()
    projected = native(body)
    cleared = rank > 1 and not interrupt and not give_up
    assert projected["mapId"] == payload["map_id"] and projected["runeIds"] == ["test", "second"]
    assert projected["scoreCurrent"] == [10, 15, 7, 0, 0, 0] and projected["scoreRecord"] == [0]*6
    assert projected["runeCount"] == [0, 2 if cleared else 0]
    assert projected["commentNew"] == (["few", "cost"] if cleared else []) and projected["isNewRecord"] == cleared
    assert projected["ts"] == 1001
    assert "outcome" not in body and "axisRecordsBefore" not in body
    assert all(projected[name] == [] for name in ("rewards", "itemReturn", "overrideRewards", "additionalRewards"))
    assert apply(old_sync, body["playerDataDelta"]) == runtime.sync(token)["user"]
    assert cache(runtime, ident)["response"] == projected
    assert pending(runtime, token, ident).battle.state == ("ABORTED" if interrupt or give_up else "FINISHED")
    assert start(client, token, payload, "following-start").status_code == 200


@pytest.mark.parametrize("cleared", [True, False])
def test_new_sequences_iv_and_later_progress_keep_first_native_response_including_finish_time(ready, cleared):
    runtime, client, token, payload = ready
    ident = start(client, token, payload).json()["battleId"]
    body = request(ident, payload, rank=3 if cleared else 1)
    first = finish(client, token, body)
    assert first.status_code == 200
    assert finish(client, token, body).json() == first.json()
    original = cache(runtime, ident)
    # Subsequent progress must not replace the original failure's diagram.
    with runtime.database.transaction() as session:
        row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
        row.score_total = [60, 50, 40, 30, 20, 10]
    set_time(runtime, 1101)
    repeated = finish(client, token, request(ident, payload, rank=3 if cleared else 1,
                                            iv=b"synthetic-IV-002"), "different-iv")
    assert repeated.status_code == 200, repeated.text
    assert native(repeated.json()) == native(first.json()) and repeated.json()["ts"] == 1001
    assert cache(runtime, ident) == original


def test_concurrent_sequences_have_one_protocol_receipt_and_one_progression(ready):
    runtime, client, token, payload = ready
    ident = start(client, token, payload).json()["battleId"]
    body = request(ident, payload)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: finish(client, token, body, f"finish-{n}"), range(4)))
    assert all(r.status_code == 200 for r in results)
    assert all(native(r.json()) == native(results[0].json()) for r in results)
    with runtime.database.transaction(write=False) as session:
        values = session.query(m.Receipt).filter(m.Receipt.key.like(crisis_v2_native.PREFIX+"%")).all()
        assert len(values) == 1
        assert session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p")).comments == ["few", "cost"]


def test_start_strict_contract_modes_authentication_and_idempotency_are_enforced(ready):
    runtime, client, token, payload = ready
    before = rows(runtime.database.path)
    assert start(client, "invalid", payload).status_code == 401
    assert start(client, token, payload, extraUnknown=1).status_code == 422
    assert start(client, token, payload, assistFriend={"unknown": 1}).status_code == 501
    assert rows(runtime.database.path) == before
    first = start(client, token, payload)
    assert start(client, token, payload).json() == first.json()
    assert start(client, token, payload, runeSlots=[]).status_code == 409


def test_foreign_account_and_changed_outcome_cannot_consume_protocol_receipt(ready):
    runtime, client, token, payload = ready
    ident = start(client, token, payload).json()["battleId"]
    body = request(ident, payload)
    assert finish(client, token, body).status_code == 200
    with runtime.database.transaction() as session:
        other = create_account(session, runtime.data, "NativeOtherDoctor")
        other_token = login(session, runtime.settings, name=other.name)["secret"]
    before = rows(runtime.database.path)
    assert finish(client, other_token, body, "foreign").status_code == 404
    assert finish(client, token, request(ident, payload, rank=1), "changed-rank").status_code == 409
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("problem", ["missing", "wrong-id", "wrong-key-alias"])
def test_formatter_error_rolls_back_terminal_progress_and_generic_receipt(tmp_path, problem):
    tables = source(missing_effect=problem == "missing")
    if problem != "missing":
        for entry in tables["crisis_v2_server_table"]["seasons"].values():
            for detail in entry["info"]["mapDetailDataMap"].values():
                for ident, rune in detail["runeDataMap"].items():
                    rune["packedRune"] = {"id": "mismatched"} if problem == "wrong-id" else {"key": ident}
    runtime, token, payload = setup(tmp_path, tables=tables)
    try:
        with TestClient(create_game_app(runtime)) as client:
            ident = start(client, token, payload).json()["battleId"]
            before = rows(runtime.database.path)
            response = finish(client, token, request(ident, payload))
            assert response.status_code == 503 and response.json()["error"]["code"] == "CRISIS_V2_RESPONSE_UNSUPPORTED"
            assert rows(runtime.database.path) == before
            assert pending(runtime, token, ident).battle.state == "STARTED"
    finally:
        runtime.database.close()


def test_response_time_opt_in_rejects_missing_time_and_rolls_back(ready):
    runtime, client, token, payload = ready
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        runtime.mutate(token, None, "bad-time", "qa-response-ts", {}, lambda ctx: {}, preserve_result_ts=True)
    assert failure.value.code == "INVALID_RESPONSE_TIMESTAMP" and rows(runtime.database.path) == before


def test_cold_restart_keeps_protocol_receipt_and_original_timestamp(ready):
    runtime, client, token, payload = ready
    ident = start(client, token, payload).json()["battleId"]
    body = request(ident, payload)
    result = finish(client, token, body).json()
    before = rows(runtime.database.path)
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(restarted)) as new_client:
            assert rows(restarted.database.path) == before
            assert finish(new_client, token, body).json() == result
            set_time(restarted, 1201)
            assert native(finish(new_client, token, body, "after-restart").json()) == native(result)
    finally:
        restarted.database.close()


@pytest.mark.parametrize("damage", ["response", "time", "source-map", "binding", "owner", "orphan", "version"])
def test_damaged_or_orphan_protocol_receipts_fail_readonly_startup(ready, monkeypatch, damage):
    runtime, client, token, payload = ready
    ident = start(client, token, payload).json()["battleId"]
    assert finish(client, token, request(ident, payload)).status_code == 200
    settings = runtime.settings
    runtime.database.close()
    key = crisis_v2_native.PREFIX+ident
    with sqlite3.connect(settings.database_path) as db:
        value = json.loads(db.execute("SELECT result FROM receipts WHERE account_id=1 AND key=?", (key,)).fetchone()[0])
        if damage == "binding":
            db.execute("UPDATE receipts SET request_hash=? WHERE account_id=1 AND key=?", ("0"*64, key))
        elif damage == "orphan":
            db.execute("UPDATE receipts SET key=? WHERE account_id=1 AND key=?", (crisis_v2_native.PREFIX+"unknown", key))
        elif damage == "owner":
            db.execute("UPDATE receipts SET account_id=123 WHERE account_id=1 AND key=?", (key,))
        else:
            if damage == "response":
                value["response"]["runeIds"] = ["rune"]
            elif damage == "time":
                value["response"]["ts"] += 1
            elif damage == "source-map":
                value["source_map"] = {}
            else:
                value["version"] = "unverified"
            value["hash"] = fingerprint({k: v for k, v in value.items() if k != "hash"})
            db.execute("UPDATE receipts SET result=? WHERE account_id=1 AND key=?", (json.dumps(value), key))
    before = settings.database_path.read_bytes()
    writable = []
    monkeypatch.setattr(Database, "initialize", lambda database: writable.append(True))
    with pytest.raises(ValueError, match="危机合约战斗保存不兼容"):
        Runtime(settings)
    assert writable == [] and settings.database_path.read_bytes() == before
