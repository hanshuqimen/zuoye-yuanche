"""Owned native settlement retries, refunds and atomic reward boundaries.

Only synthetic IDs, tables and telemetry are encrypted here. These tests do not
establish official drop probabilities or native successful-play validation.
"""

import base64
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient
from test_native_battle_start import battle_runtime as battle_runtime
from test_native_battle_start import begin, body, login

from terralocal.server.domain import accounts
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import HEADHUNTING_REVISION, REVISION
from terralocal.server.protocol.battle_codec import FinishRequest, decode_finish
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime


def encoded(battle_id, *, login_time=1_800_000_000, state=1, changes=None, trace_changes=None,
            raw=None, iv=b"synthetic-IV-001"):
    signature = base64.b64encode(bytes((value + 7) % 256 for value in battle_id.encode())).decode()
    trace = {"isCheat": signature, "completeTime": 20,
             "stats": {"leftHp": 20, "fixedPlayTime": 20_399, "killedEnemiesCnt": 0,
                       "access": "synthetic-not-an-auth-token"}}
    trace.update(trace_changes or {})
    payload = {"battleId": battle_id, "stageId": "test_1", "completeState": state,
               "interrupt": 1 if state == 1 else 0, "giveUp": 0,
               "percent": 0 if state == 1 else 100, "killCnt": 0, "validKillCnt": 0,
               "platform": 1, "battleData": trace}
    payload.update(changes or {})
    raw = raw or json.dumps(payload, separators=(",", ":"))
    # Independent fixture construction with the observed wire encoding.
    key = hashlib.md5(("pM6Umv*^hVQuB6t&" + str(login_time)).encode(), usedforsecurity=False).digest()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(raw.encode()) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    data = (cipher.update(padded) + cipher.finalize() + iv).hex()
    return {"data": data, "battleData": {"isCheat": signature, "completeTime": 20, "stats": {}}}


def complete(client, token, payload, key="finish"):
    return client.post("/quest/battleFinish", json=payload, headers={"secret": token, "seqnum": key})


def start_native(client, runtime, token):
    response = begin(client, token, body())
    assert response.status_code == 200
    with runtime.database.transaction(write=False) as session:
        context = session.get(m.BattleSession, response.json()["battleId"]).native_context
        assert context["login_time"] == 1_800_000_000
        assert context["gamedata_hash"] == runtime.data.manifest["hash"]
    return response.json()["battleId"]


def test_abort_refund_once_across_concurrency_new_iv_new_login_and_restart(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    before_start = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = start_native(client, runtime, token)
        before_finish = runtime.sync(token)
        payload = encoded(battle_id)
        with ThreadPoolExecutor(max_workers=8) as workers:
            replies = list(workers.map(lambda _: complete(client, token, payload), range(8)))
        response = replies[0].json()
        assert all(reply.status_code == 200 and reply.json() == response for reply in replies)
        assert response["result"] == 0 and response["apFailReturn"] == 5
        assert response["goldScale"] == response["expScale"] == 1.0
        assert response["extra"] is None and "stars" not in response
        for name in ("rewards", "firstRewards", "itemReturn", "overrideRewards", "unusualRewards",
                     "additionalRewards", "diamondMaterialRewards", "furnitureRewards", "unlockStages"):
            assert response[name] == []
        after = runtime.sync(token)
        assert apply(before_finish["user"], response["playerDataDelta"]) == after["user"]
        assert after["user"]["status"]["ap"] == before_start["user"]["status"]["ap"] - 1
        reencrypted = encoded(battle_id, iv=b"synthetic-IV-002")
        assert complete(client, token, reencrypted, "another-seq").status_code == 200
        assert complete(client, token, reencrypted).json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        # Another login advances the profile flag; the old key is still pinned.
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += 1
        second_token = login(runtime)
        assert complete(client, second_token, payload, "finish").status_code == 200
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, battle_id)
        assert row.state == "ABORTED" and row.native_context.get("settlement_hash")
        progress = session.get(m.StageProgress, (1, "test_1"))
        assert progress.stars == progress.clear_count == 0 and not progress.first_clear_claimed
        assert session.get(m.SanityState, 1).current == 9
        assert session.query(m.StageReplay).count() == 0
        assert all("synthetic-not-an-auth-token" not in json.dumps(r.result) for r in session.query(m.Receipt))
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(restarted)) as client:
            assert complete(client, second_token, payload, "finish").status_code == 200
        with restarted.database.transaction(write=False) as session:
            assert session.get(m.SanityState, 1).current == 9
    finally:
        restarted.database.close()


@pytest.mark.parametrize("change", [{"validKillCnt": 1}, {"giveUp": 1}, {"interrupt": 0}, {"percent": 1}])
def test_different_outcome_after_settlement_cannot_refund_again(battle_runtime, change):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = start_native(client, runtime, token)
        assert complete(client, token, encoded(battle_id)).status_code == 200
        before = runtime.sync(token)
        response = complete(client, token, encoded(battle_id, changes=change), "conflict")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SETTLEMENT_CONFLICT"
    assert runtime.sync(token) == before


def test_foreign_account_and_sdk_session_cannot_refund_owned_battle(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
        other = accounts.login(session, runtime.settings, name="Other")["secret"]
        sdk = accounts.login(session, runtime.settings, name="Doctor", kind="sdk")["secret"]
    with TestClient(create_game_app(runtime)) as client:
        battle_id = start_native(client, runtime, token)
        before = runtime.sync(token)
        assert complete(client, other, encoded(battle_id)).status_code == 404
        assert complete(client, sdk, encoded(battle_id)).status_code == 401
        assert complete(client, "", encoded(battle_id)).status_code == 401
    assert runtime.sync(token) == before


@pytest.mark.parametrize("kind", ["wrong-key", "bad-padding", "partial-block", "odd-hex", "signature", "duration",
                                  "inner-id", "inner-signature", "unknown-field", "interrupted-win",
                                  "bool-enum", "nonfinite", "duplicate-json"])
def test_invalid_finish_cannot_refund_or_change_progress(battle_runtime, kind):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = start_native(client, runtime, token)
        before = runtime.sync(token)
        payload = encoded(battle_id)
        if kind == "wrong-key":
            payload = encoded(battle_id, login_time=123)
        elif kind == "bad-padding":
            data = bytearray.fromhex(payload["data"])
            data[-33] ^= 1
            payload["data"] = data.hex()
        elif kind == "partial-block":
            payload["data"] = payload["data"][:-2]
        elif kind == "odd-hex":
            payload["data"] = payload["data"][:-1]
        elif kind == "signature":
            payload["battleData"]["isCheat"] = "invalid"
        elif kind == "duration":
            payload["battleData"]["completeTime"] += 1
        elif kind == "inner-id":
            payload = encoded(battle_id, changes={"battleId": "10000000-0000-0000-0000-000000000001"})
        elif kind == "inner-signature":
            payload = encoded(battle_id, trace_changes={"isCheat": "invalid"})
        elif kind == "unknown-field":
            payload = encoded(battle_id, changes={"unverifiedBattleMode": 1})
        elif kind == "interrupted-win":
            payload = encoded(battle_id, state=3, changes={"interrupt": 1})
        elif kind == "bool-enum":
            payload = encoded(battle_id, changes={"completeState": True})
        elif kind == "nonfinite":
            payload = encoded(battle_id, changes={"percent": float("nan")})
        elif kind == "duplicate-json":
            payload = encoded(battle_id, raw='{"battleId":"a","battleId":"b"}')
        response = complete(client, token, payload)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_NATIVE_FINISH"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, battle_id)
        assert row.state == "STARTED" and row.settlement is None
        assert "settlement_hash" not in row.native_context
        assert session.query(m.Receipt).count() == 1  # Start only.


def test_current_login_key_also_decodes_without_changing_server_clock(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = start_native(client, runtime, token)
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += 1
        new_token = login(runtime)
        request = encoded(battle_id, login_time=1_800_000_001,
                          trace_changes={"stats": {"beginTs": 1, "endTs": 10**12}})
        assert complete(client, new_token, request).status_code == 200
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.ServerClockState, 1).fixed_at == 1_800_000_001
        assert session.get(m.BattleSession, battle_id).finished_at == 1_800_000_001


def test_stage_and_version_conflicts_roll_back_and_abort_does_not_require_drop_policy(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = start_native(client, runtime, token)
        before = runtime.sync(token)
        response = complete(client, token, encoded(battle_id, changes={"stageId": "test_2"}))
        assert response.status_code == 409
        original = runtime.data.manifest["hash"]
        runtime.data.manifest["hash"] = "other-version"
        assert complete(client, token, encoded(battle_id)).json()["error"]["code"] == "BATTLE_DATA_CHANGED"
        runtime.data.manifest["hash"] = original
        assert runtime.sync(token) == before
        runtime.drop_rules = {"test_1": {"rewards": []}}
        assert complete(client, token, encoded(battle_id, state=3)).json()["error"]["code"] == "BATTLE_DROP_RULE_CHANGED"
        assert runtime.sync(token) == before
        assert complete(client, token, encoded(battle_id)).status_code == 200


def test_missing_drop_rules_reject_start_before_spending_ap(battle_runtime):
    runtime = battle_runtime
    runtime.drop_rules = {}
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        response = begin(client, token, body())
        assert response.status_code == 503 and response.json()["error"]["code"] == "DROP_RULE_MISSING"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).count() == 0


def test_synthetic_three_star_rewards_first_clear_unlock_and_concurrent_retry_once(battle_runtime):
    runtime = battle_runtime
    runtime.drop_rules = {"test_1": {"rewards": [{"id": "material", "count": 1}], "first_rewards": []}}
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = start_native(client, runtime, token)
        before = runtime.sync(token)
        with ThreadPoolExecutor(max_workers=8) as workers:
            # Distinct transport keys still share one domain settlement.
            replies = list(workers.map(lambda i: complete(client, token, encoded(battle_id, state=3), str(i)), range(8)))
        assert all(reply.status_code == 200 for reply in replies)
        result = next(reply.json() for reply in replies if reply.json()["playerDataDelta"]["modified"])
        assert result["rewards"] == [
            {"id": "material", "count": 1, "type": "MATERIAL", "charGet": None},
            {"id": "4001", "count": 12, "type": "GOLD", "charGet": None}]
        assert result["firstRewards"] == [{"id": "4002", "count": 1, "type": "DIAMOND", "charGet": None}]
        assert result["unlockStages"] == ["test_2"]
        after = runtime.sync(token)
        # The first delta matches the single settlement, even if receipts have
        # increased revision by the time the final snapshot is read.
        assert apply(before["user"], result["playerDataDelta"]) == after["user"]
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.StageProgress, (1, "test_1")).clear_count == 1
        assert session.get(m.StageProgress, (1, "test_1")).first_clear_claimed
        assert session.get(m.InventoryItem, (1, "material")).count == 1
        assert session.get(m.Currency, (1, "4002")).balance == 1
        assert session.get(m.Operator, 1).trust == 2
        assert session.get(m.PlayerProfile, 1).exp == 12
        assert {r["id"]: r["count"] for r in session.get(m.BattleSession, battle_id).settlement["rewards"]} == {
            "material": 1, "4001": 12, "5001": 12}


@pytest.mark.parametrize("stars", [2, 3])
@pytest.mark.parametrize("initial_exp", [0, 95])
def test_native_exp_visual_uses_delta_without_losing_gold_cards_or_first_exp(
        battle_runtime, stars, initial_exp):
    runtime = battle_runtime
    runtime.drop_rules = {"test_1": {
        "rewards": [{"id": "2001", "count": 2}],
        "first_rewards": [{"id": "5001", "count": 7}]}}
    with runtime.database.transaction() as session:
        session.get(m.PlayerProfile, 1).exp = initial_exp
    token = login(runtime)
    base_gain = 12 if stars == 3 else 10
    gained_exp = base_gain + (7 if stars == 3 else 0)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = start_native(client, runtime, token)
        before = runtime.sync(token)["user"]
        payload = encoded(battle_id, state=stars)
        response = complete(client, token, payload, "visual-finish")
        assert response.status_code == 200
        result = response.json()
        assert result["rewards"] == [
            {"id": "2001", "count": 2, "type": "CARD_EXP", "charGet": None},
            {"id": "4001", "count": base_gain, "type": "GOLD", "charGet": None}]
        assert result["firstRewards"] == (
            [{"id": "4002", "count": 1, "type": "DIAMOND", "charGet": None}] if stars == 3 else [])
        assert not any(r["type"] == "EXP_PLAYER" for field in (
            "rewards", "firstRewards", "furnitureRewards") for r in result[field])
        after = runtime.sync(token)["user"]
        assert apply(before, result["playerDataDelta"]) == after
        assert (after["status"]["level"], after["status"]["exp"]) == (
            (2, initial_exp + gained_exp - 100) if initial_exp + gained_exp >= 100
            else (1, initial_exp + gained_exp))
        assert after["status"]["gold"] == before["status"]["gold"] + base_gain
        assert complete(client, token, payload, "visual-finish").json() == result
        retry = complete(client, token, payload, "visual-finish-new-key")
        assert retry.status_code == 200
        assert retry.json()["playerDataDelta"] == {"modified": {}, "deleted": {}}
        assert runtime.sync(token)["user"] == after
    with runtime.database.transaction(write=False) as session:
        settlement = session.get(m.BattleSession, battle_id).settlement
        assert {r["id"]: r["count"] for r in settlement["rewards"]} == {
            "2001": 2, "4001": base_gain, "5001": base_gain}
        assert sum(r["count"] for r in settlement["firstRewards"] if r["id"] == "5001") == (
            7 if stars == 3 else 0)
        assert session.get(m.StageProgress, (1, "test_1")).clear_count == 1
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == after
        with TestClient(create_game_app(restarted)) as client:
            assert complete(client, token, payload, "visual-finish").json() == result
        assert restarted.sync(token)["user"] == after
    finally:
        restarted.database.close()


def test_response_failure_rolls_back_refund_settlement_context_and_receipt(battle_runtime, monkeypatch):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        battle_id = start_native(client, runtime, token)
        before = runtime.sync(token)
        original = SyncDataAssembler.assemble
        calls = 0

        def fail_after_refund(self):
            nonlocal calls
            calls += 1
            if calls == 2:
                assert self.ctx.session.get(m.BattleSession, battle_id).state == "ABORTED"
                raise RuntimeError("Synthetic assembly failure")
            return original(self)

        with monkeypatch.context() as patch:
            patch.setattr(SyncDataAssembler, "assemble", fail_after_refund)
            assert complete(client, token, encoded(battle_id)).status_code == 500
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, battle_id)
        assert row.state == "STARTED" and row.settlement is None
        assert "settlement_hash" not in row.native_context
        assert session.query(m.Receipt).count() == 1


def test_0006_upgrade_preserves_started_local_battle_without_fabricating_context(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        result = client.post("/local/v1/battle/start", json={"stageId": "test_1", "squadId": "0"},
                             headers={"secret": token, "seqnum": "local"})
        assert result.status_code == 200
        battle_id = result.json()["battleId"]
    before = runtime.sync(token)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        # This fixture predates Crisis V2. Keep its historical shape instead
        # of leaving new empty mode tables beside a pre-context parent.
        from schema_legacy import remove_crisis_v2_tables

        remove_crisis_v2_tables(connection)
        connection.execute("DROP TABLE operator_acquisitions")
        connection.execute("DROP TABLE owned_furniture")
        connection.execute("ALTER TABLE battle_sessions DROP COLUMN native_context")
        connection.execute("UPDATE alembic_version SET version_num=?", (HEADHUNTING_REVISION,))
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == before
        with restarted.database.transaction(write=False) as session:
            row = session.get(m.BattleSession, battle_id)
            assert row.state == "STARTED" and row.native_context is None
            assert session.connection().exec_driver_sql("select version_num from alembic_version").scalar() == REVISION
        with TestClient(create_game_app(restarted)) as client:
            response = complete(client, token, encoded(battle_id))
            assert response.status_code == 503 and response.json()["error"]["code"] == "NATIVE_CONTEXT_UNAVAILABLE"
        assert restarted.sync(token) == before and restarted.database.integrity() == "ok"
        restarted.database.initialize()
    finally:
        restarted.database.close()


def test_native_finish_requires_native_request_shape_and_version(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = start_native(client, runtime, token)
        assert complete(client, token, {"battleId": battle_id, "stars": 0}).status_code == 422
        with runtime.database.transaction() as session:
            row = session.get(m.BattleSession, battle_id)
            row.native_context = {**row.native_context, "codec_version": "unverified-next-version"}
        before = runtime.sync(token)
        response = complete(client, token, encoded(battle_id))
        assert response.status_code == 503 and response.json()["error"]["code"] == "NATIVE_CONTEXT_UNAVAILABLE"
    assert runtime.sync(token) == before


def test_synthetic_abort_fixture_decodes_nested_stats_without_publishing_them():
    battle_id = "10000000-0000-0000-0000-000000000001"
    request = FinishRequest.model_validate(encoded(battle_id))
    parsed = decode_finish(request, [1_800_000_000])
    assert parsed.battleId == battle_id and parsed.interrupt and parsed.completeState == 1
    assert parsed.battleData.completeTime == 20 and parsed.percent == 0


def test_common_campaign_finish_fields_keep_distinct_scheduler_counts():
    # Frozen CampaignFinishBattleRequest binds the same generic common parser.
    # This synthetic encoding tests the field contract, not a campaign award.
    battle_id = "10000000-0000-0000-0000-000000000002"
    request = FinishRequest.model_validate(encoded(
        battle_id, changes={"stageId": "camp_synthetic", "killCnt": 17, "validKillCnt": 11, "giveUp": 1},
        trace_changes={"stats": {"killedEnemiesCnt": 99, "nested": {"kills": 100}}}))
    parsed = decode_finish(request, [1_800_000_000])
    assert parsed.stageId == "camp_synthetic" and parsed.giveUp
    assert parsed.killCnt == 17 and parsed.validKillCnt == 11
    assert parsed.battleData.stats["killedEnemiesCnt"] == 99
    assert request.battleData.stats == {}
