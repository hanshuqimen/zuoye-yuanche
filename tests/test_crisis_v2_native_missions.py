"""Native mission transactions on owned fixtures; no official play or assets."""

import copy
import hashlib
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from crisis_v2_qa import set_time
from fastapi.testclient import TestClient
from test_crisis_v2_claims import ITEM, fixture_tables
from test_crisis_v2_clears import setup
from test_crisis_v2_persistence import rows

from terralocal.server.domain import crisis_v2_missions
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService, backup_existing_save, recover_backup
from terralocal.server.services.runtime import Runtime

PATH = "/crisisV2/confirmMissions"
BODY = {"mapId": "season_a_p", "missions": [{"id": "treasure", "type": 2}]}
SECOND = "authored-second-chair"


def prepare(directory, *, second=False):
    tables = fixture_tables()
    if second:
        tables["item_table"]["items"][SECOND] = {"itemId": SECOND, "itemType": "FURN", "name": "Second chair"}
        detail = tables["crisis_v2_server_table"]["seasons"]["season_a"]["info"]["mapDetailDataMap"][
            "season_a_p"
        ]
        detail["nodeDataMap"]["start"]["adjacentNodeList"].append("other")
        detail["nodeDataMap"]["other"] = copy.deepcopy(detail["nodeDataMap"]["treasure"])
        detail["rewardNodeDataMap"]["other"] = {
            **copy.deepcopy(detail["rewardNodeDataMap"]["treasure"]),
            "slotId": "other",
            "reward": {"id": SECOND, "type": "FURN", "count": 1},
        }
    runtime, token, _ = setup(directory, tables=tables)
    with runtime.database.transaction() as session:
        row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
        row.cleared = True
        row.rewards = {
            slot: {"state": 1, "progress": rule.required}
            for slot, rule in runtime.data.crisis_v2.objectives("season_a", "season_a_p").treasures.items()
        }
    return runtime, token


def send(client, token, key="mission", body=None):
    headers = {"secret": token}
    if key is not None:
        headers["seqnum"] = key
    return client.post(PATH, json=BODY if body is None else body, headers=headers)


def inventory(runtime, item=ITEM, account=1):
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.OwnedFurniture, (account, item))
        return row.count if row else 0


def test_native_delta_transport_retry_and_new_sequence_do_not_regrant(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            before = runtime.sync(token)["user"]
            result = send(client, token).raise_for_status().json()
            after = runtime.sync(token)["user"]
            assert result["rewards"] == [{"id": ITEM, "type": "FURN", "count": 1}]
            assert apply(before, result["playerDataDelta"]) == after
            assert after["crisisV2"]["seasons"]["season_a"]["permanent"]["reward"]["treasure"]["state"] == 2
            assert send(client, token).json() == result
            again = send(client, token, "new-sequence").raise_for_status().json()
            assert again["rewards"] == result["rewards"] and again["ts"] == result["ts"]
            assert again["playerDataDelta"] == {"modified": {}, "deleted": {}}
            assert inventory(runtime) == 1
            conflict = send(client, token, body=BODY | {"missions": [{"id": "unknown", "type": 2}]})
            assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    finally:
        runtime.database.close()


@pytest.mark.parametrize(
    "bad",
    [
        {"missions": []},
        {"missions": [{"id": "treasure", "type": True}]},
        {"missions": [{"id": "treasure", "type": "2"}]},
        {"missions": [{"id": "treasure", "type": 3}]},
        {"missions": [{"id": "treasure", "type": 2}] * 2},
        {"missions": [{"id": "treasure", "type": 2, "count": 99}]},
        {"rewards": [{"id": ITEM, "count": 99}]},
    ],
)
def test_malformed_native_requests_do_not_change_any_row(tmp_path, bad):
    runtime, token = prepare(tmp_path)
    try:
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            assert send(client, token, body=BODY | bad).status_code == 422
            assert send(client, token, key=None).status_code == 400
            assert send(client, "invalid-token").status_code == 401
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


@pytest.mark.parametrize("bad_last", ["unknown", "not-ready", "unsupported"])
def test_entire_batch_rolls_back_when_last_mission_cannot_be_claimed(tmp_path, bad_last):
    runtime, token = prepare(tmp_path, second=True)
    try:
        other = {"id": "other", "type": 2}
        if bad_last == "unknown":
            other["id"] = "unknown"
        elif bad_last == "unsupported":
            other["type"] = 1
        else:
            with runtime.database.transaction() as session:
                row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
                row.rewards = {**row.rewards, "other": {"state": 0, "progress": 0}}
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            response = send(client, token, body=BODY | {"missions": [*BODY["missions"], other]})
            assert response.status_code == {"unknown": 404, "not-ready": 409, "unsupported": 501}[bad_last]
        assert rows(runtime.database.path) == before
        assert inventory(runtime) == inventory(runtime, SECOND) == 0
    finally:
        runtime.database.close()


def test_batch_order_retry_and_overlapping_batch_conflict(tmp_path):
    runtime, token = prepare(tmp_path, second=True)
    body = BODY | {"missions": [*BODY["missions"], {"id": "other", "type": 2}]}
    try:
        with TestClient(create_game_app(runtime)) as client:
            result = send(client, token, body=body).raise_for_status().json()
            reversed_body = body | {"missions": list(reversed(body["missions"]))}
            again = send(client, token, "reverse", reversed_body).raise_for_status().json()
            assert again["rewards"] == result["rewards"]
            assert send(client, token, "overlap").status_code == 409
            assert inventory(runtime) == inventory(runtime, SECOND) == 1
    finally:
        runtime.database.close()


def test_exception_after_inventory_write_rolls_back_batch_and_both_receipts(tmp_path, monkeypatch):
    from terralocal.server.domain.errors import DomainError

    runtime, token = prepare(tmp_path, second=True)
    grant = Context.rewards

    def fail(ctx, entries):
        grant(ctx, entries)
        raise DomainError("QA_FAILURE", "Authored post-grant failure", 503)

    monkeypatch.setattr(Context, "rewards", fail)
    try:
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            assert (
                send(
                    client, token, body=BODY | {"missions": [*BODY["missions"], {"id": "other", "type": 2}]}
                ).status_code
                == 503
            )
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_simultaneous_native_batches_only_grant_once(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client, ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda key: send(client, token, key), ("one", "two")))
        assert [reply.status_code for reply in replies] == [200, 200]
        assert replies[0].json()["rewards"] == replies[1].json()["rewards"]
        assert inventory(runtime) == 1
    finally:
        runtime.database.close()


def test_closed_window_and_other_account_cannot_claim_but_old_receipt_remains_readable(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            with runtime.database.transaction() as session:
                create_account(session, runtime.data, "OtherDoctor")
                other = login(session, runtime.settings, name="OtherDoctor")["secret"]
            assert send(client, other).status_code == 409
            set_time(runtime, 2000)
            before = rows(runtime.database.path)
            assert send(client, token, "closed").status_code == 409
            assert rows(runtime.database.path) == before
            set_time(runtime, 1001)
            reply = send(client, token).raise_for_status().json()
            set_time(runtime, 2000)
            again = send(client, token, "after-close").raise_for_status().json()
            assert again["rewards"] == reply["rewards"] and inventory(runtime) == 1
    finally:
        runtime.database.close()


def test_new_login_cold_restart_and_backup_recovery_keep_first_reward_receipt(tmp_path):
    runtime, token = prepare(tmp_path)
    with TestClient(create_game_app(runtime)) as client:
        result = send(client, token).raise_for_status().json()
    settings = runtime.settings
    runtime.database.close()
    backup = backup_existing_save(settings)
    recovered = settings.data_dir / "recovered.sqlite3"
    recover_backup(settings, backup["name"], recovered)
    restored_dir = tmp_path / "restored"
    shutil.copytree(settings.data_dir / "cache", restored_dir / "cache")
    shutil.copyfile(recovered, restored_dir / "terralocal.sqlite3")
    restored = Runtime(settings.model_copy(update={"data_dir": restored_dir}))
    try:
        with restored.database.transaction() as session:
            fresh = login(session, restored.settings, name="CrisisDoctor")["secret"]
        with TestClient(create_game_app(restored)) as client:
            reply = send(client, fresh, "different-session").raise_for_status().json()
        assert reply["rewards"] == result["rewards"] and reply["ts"] == result["ts"]
        assert inventory(restored) == 1
    finally:
        restored.database.close()


@pytest.mark.parametrize("field", ["response", "account_id", "source_map", "hash", "claimed_state"])
def test_damaged_business_receipt_is_rejected_before_startup_writes(tmp_path, field):
    runtime, token = prepare(tmp_path)
    with TestClient(create_game_app(runtime)) as client:
        send(client, token).raise_for_status()
    settings = runtime.settings
    runtime.database.close()
    with sqlite3.connect(settings.database_path) as connection:
        key, raw = connection.execute(
            "SELECT key,result FROM receipts WHERE substr(key,1,?)=?",
            (len(crisis_v2_missions.PREFIX), crisis_v2_missions.PREFIX),
        ).fetchone()
        value = json.loads(raw)
        if field == "response":
            value["response"]["rewards"][0]["count"] = 2
        elif field == "account_id":
            value["account_id"] = 2
        elif field == "source_map":
            value["source_map"]["reward"]["treasure"]["progress"] = 1
        elif field == "hash":
            value["hash"] = "0" * 64
        else:
            connection.execute(
                "UPDATE crisis_v2_maps SET rewards=? WHERE account_id=1 AND map_id='season_a_p'",
                (json.dumps({"treasure": {"state": 1, "progress": 2}}),),
            )
        connection.execute(
            "UPDATE receipts SET result=? WHERE account_id=1 AND key=?", (json.dumps(value), key)
        )
    before = hashlib.sha256(settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="任务回执"):
        Runtime(settings)
    assert hashlib.sha256(settings.database_path.read_bytes()).hexdigest() == before


def test_online_restore_rejects_damaged_native_receipt_without_changing_current_save(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            send(client, token).raise_for_status()
        service = BackupService(runtime)
        backup = service.create()
        path = service.directory / backup["name"]
        with sqlite3.connect(path) as connection:
            key, raw = connection.execute(
                "SELECT key,result FROM receipts WHERE substr(key,1,?)=?",
                (len(crisis_v2_missions.PREFIX), crisis_v2_missions.PREFIX),
            ).fetchone()
            value = json.loads(raw)
            value["response"]["rewards"][0]["count"] = 2
            connection.execute(
                "UPDATE receipts SET result=? WHERE account_id=1 AND key=?", (json.dumps(value), key)
            )
        metadata = json.loads(path.with_suffix(".json").read_bytes())
        metadata["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        metadata["bytes"] = path.stat().st_size
        path.with_suffix(".json").write_text(json.dumps(metadata), "utf8")
        before = rows(runtime.database.path)
        with pytest.raises(ValueError, match="任务回执"):
            service.restore(backup["name"])
        assert rows(runtime.database.path) == before and inventory(runtime) == 1
    finally:
        runtime.database.close()
