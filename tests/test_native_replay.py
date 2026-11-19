"""Synthetic ZIP journals: owned records, rollback, ordering and bounded parsing."""

import base64
import copy
import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_native_battle_finish import complete, encoded
from test_native_battle_start import battle_runtime as battle_runtime
from test_native_battle_start import begin, body, login

from terralocal.server.domain import accounts, battle
from terralocal.server.domain.errors import DomainError
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.replay_codec import decode_replay
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime


def journal(seed=1):
    return {"campaignOnlyVersion": 0, "timestamp": "synthetic", "journal": {
        "metadata": {"stageId": "test_1", "gameResult": 3}, "randomSeed": seed,
        "squad": [{"charInstId": 1, "tmplId": None, "skillId": "skill", "skillIndex": 0,
                   "isAssistChar": False, "uniequipId": "", "uniequipLevel": 0}],
        "logs": [], "runeList": []}, "battleMeta": None}


def packed(data=None, *, raw=None, extra=False, compression=zipfile.ZIP_DEFLATED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as archive:
        entry = zipfile.ZipInfo("journal", date_time=(2020, 1, 1, 0, 0, 0))
        entry.compress_type = compression
        archive.writestr(entry, raw if raw is not None else json.dumps(data or journal()))
        if extra:
            archive.writestr(zipfile.ZipInfo("second", date_time=(2020, 1, 1, 0, 0, 0)), "{}")
    return base64.b64encode(stream.getvalue()).decode()


def save(client, token, battle_id, replay=None, key="save"):
    return client.post("/quest/saveBattleReplay", headers={"secret": token, "seqnum": key},
                       json={"battleId": battle_id, "battleReplay": replay or packed()})


def load(client, token, stage="test_1", **headers):
    return client.post("/quest/getBattleReplay", headers={"secret": token, **headers}, json={"stageId": stage})


def cleared(client, token, prefix="first", stars=3):
    started = begin(client, token, body(), key=prefix + "-start")
    assert started.status_code == 200
    battle_id = started.json()["battleId"]
    assert complete(client, token, encoded(battle_id, state=stars), prefix + "-finish").status_code == 200
    return battle_id


def test_native_replay_concurrency_delta_and_restart(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = cleared(client, token)
        before = runtime.sync(token)["user"]
        with ThreadPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(lambda _: save(client, token, battle_id), range(6)))
        assert all(reply.status_code == 200 and reply.json() == replies[0].json() for reply in replies)
        response = replies[0].json()
        assert response["result"] == 0
        assert response["playerDataDelta"]["modified"]["dungeon"]["stages"]["test_1"] == {
            "hasBattleReplay": True}
        after = runtime.sync(token)["user"]
        assert apply(before, response["playerDataDelta"]) == after
        assert before["status"] == after["status"] and before["inventory"] == after["inventory"]
        assert save(client, token, battle_id, key="again").json()["playerDataDelta"] == {
            "modified": {}, "deleted": {}}
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.StageReplay, (1, "test_1"))
        assert row.battle_id == battle_id and row.replay["battleReplay"] == packed()
        assert row.replay["replay_generation"] == 1
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == after
        with TestClient(create_game_app(restarted)) as client:
            assert save(client, token, battle_id).json() == response
    finally:
        restarted.database.close()


@pytest.mark.parametrize("state", [1, 2])
def test_failed_or_two_star_battle_cannot_create_proxy_record(battle_runtime, state):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = cleared(client, token, stars=state)
        before = runtime.sync(token)
        response = save(client, token, battle_id)
        assert response.status_code == 400 and response.json()["error"]["code"] == "REPLAY_UNAVAILABLE"
        assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.StageReplay).count() == 0


def test_foreign_and_intermediate_sessions_cannot_store_replay(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
        other = accounts.login(session, runtime.settings, name="Other")["secret"]
        sdk = accounts.login(session, runtime.settings, name="Doctor", kind="sdk")["secret"]
    with TestClient(create_game_app(runtime)) as client:
        battle_id = cleared(client, token)
        before = runtime.sync(token)
        assert save(client, other, battle_id).status_code == 404
        assert save(client, sdk, battle_id).status_code == 401
        assert runtime.sync(token) == before


def test_newer_record_replaces_older_but_delayed_or_conflicting_saves_do_not(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.get(m.SanityState, 1).current = 30
    with TestClient(create_game_app(runtime)) as client:
        old = cleared(client, token, "old")
        assert save(client, token, old).status_code == 200
        new = cleared(client, token, "new")
        assert save(client, token, new, packed(journal(2)), "new-save").status_code == 200
        before = runtime.sync(token)
        stale = save(client, token, old, key="delayed-old")
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "REPLAY_STALE"
        conflict = save(client, token, new, packed(journal(3)), "conflict")
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "REPLAY_CONFLICT"
        assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.StageReplay, (1, "test_1")).battle_id == new


@pytest.mark.parametrize("bad", ["base64", "not-zip", "multi", "duplicate", "nonfinite", "structure", "bzip",
                                 "timestamp-missing", "timestamp-empty", "timestamp-null", "timestamp-number"])
def test_malformed_replay_cannot_create_flag_or_change_save(battle_runtime, bad):
    runtime = battle_runtime
    token = login(runtime)
    broken = {
        "base64": "%%%",
        "not-zip": base64.b64encode(b"not an archive").decode(),
        "multi": packed(extra=True),
        "duplicate": packed(raw='{"journal":{},"journal":{}}'),
        "nonfinite": packed(raw='{"journal":{"randomSeed":NaN}}'),
        "structure": packed({"journal": []}),
        "bzip": packed(compression=zipfile.ZIP_BZIP2),
        "timestamp-missing": packed({k: v for k, v in journal().items() if k != "timestamp"}),
        "timestamp-empty": packed({**journal(), "timestamp": ""}),
        "timestamp-null": packed({**journal(), "timestamp": None}),
        "timestamp-number": packed({**journal(), "timestamp": 1}),
    }[bad]
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        battle_id = cleared(client, token)
        before = runtime.sync(token)
        response = save(client, token, battle_id, broken)
        assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_NATIVE_REPLAY"
        assert runtime.sync(token) == before


def test_wrong_stage_and_response_failure_preserve_no_replay(battle_runtime, monkeypatch):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        battle_id = cleared(client, token)
        wrong = copy.deepcopy(journal())
        wrong["journal"]["metadata"]["stageId"] = "test_2"
        before = runtime.sync(token)
        assert save(client, token, battle_id, packed(wrong)).status_code == 409
        original = SyncDataAssembler.assemble
        calls = 0

        def fail_after_save(self):
            nonlocal calls
            calls += 1
            if calls == 2:
                assert self.ctx.session.get(m.StageReplay, (1, "test_1")) is not None
                raise RuntimeError("Synthetic replay assembly failure")
            return original(self)

        with monkeypatch.context() as patch:
            patch.setattr(SyncDataAssembler, "assemble", fail_after_save)
            assert save(client, token, battle_id).status_code == 500
        assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.StageReplay).count() == 0


def test_zip_size_bound_and_legacy_local_record_does_not_advertise_native_proxy(runtime, token, monkeypatch):
    from terralocal.server.protocol import replay_codec

    with monkeypatch.context() as patch:
        patch.setattr(replay_codec, "MAX_JSON", 64)
        with pytest.raises(DomainError, match="代理记录格式无效"):
            decode_replay(packed())
    started = runtime.mutate(token, None, "start", "start", {}, lambda ctx: battle.start(ctx, "test_1", "0"))
    battle_id = started["battleId"]
    runtime.mutate(token, None, "finish", "finish", {},
                   lambda ctx: battle.finish(ctx, battle_id, 3, drop_rules=runtime.drop_rules))
    runtime.mutate(token, None, "local-replay", "local-replay", {},
                   lambda ctx: battle.save_replay(ctx, battle_id, {"events": []}))
    assert runtime.sync(token)["user"]["dungeon"]["stages"]["test_1"]["hasBattleReplay"] is False


def test_native_load_is_exact_read_only_and_does_not_cache_an_old_generation(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.get(m.SanityState, 1).current = 30
    with TestClient(create_game_app(runtime)) as client:
        first = cleared(client, token, "read-first")
        assert save(client, token, first).status_code == 200
        before = runtime.sync(token)
        with runtime.database.transaction(write=False) as session:
            receipts = session.query(m.Receipt).count()
        with ThreadPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(lambda _: load(client, token, seqnum="reused-read"), range(6)))
        assert all(r.status_code == 200 and r.json() == replies[0].json() for r in replies)
        assert replies[0].json() == {"result": 0, "battleReplay": packed(), "ts": 1_800_000_000,
                                     "playerDataDelta": {"modified": {}, "deleted": {}}}
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.Receipt).count() == receipts
        second = cleared(client, token, "read-second")
        latest = packed(journal(2))
        assert save(client, token, second, latest, "read-new-save").status_code == 200
        after = runtime.sync(token)
        assert load(client, token, seqnum="reused-read").json()["battleReplay"] == latest
        assert runtime.sync(token) == after
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(reopened)) as client:
            assert load(client, token).json()["battleReplay"] == latest
        assert reopened.sync(token) == after
    finally:
        reopened.database.close()


def test_load_requires_game_session_and_account_owned_stage_record(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        other_account = accounts.create_account(session, runtime.data, "Other")
        other_token = accounts.login(session, runtime.settings, name="Other")["secret"]
        other_uid = other_account.uid
        sdk_token = accounts.login(session, runtime.settings, name="Doctor", kind="sdk")["secret"]
        u8_token = accounts.login(session, runtime.settings, name="Doctor", kind="u8")["secret"]
    with TestClient(create_game_app(runtime)) as client:
        for invalid in ("", "missing", sdk_token, u8_token):
            assert load(client, invalid).status_code == 401
        assert load(client, token).status_code == 404
        battle_id = cleared(client, token)
        assert save(client, token, battle_id).status_code == 200
        before = runtime.sync(token)
        assert load(client, other_token).status_code == 404
        assert load(client, token, uid=other_uid).status_code == 401
        assert load(client, token, "missing-stage").status_code == 400
        assert client.post("/quest/getBattleReplay", headers={"secret": token},
                           json={"stageId": "test_1", "accountId": 1}).status_code == 422
        assert runtime.sync(token) == before


@pytest.mark.parametrize("damage", ["fingerprint", "wrong-stage", "archive", "oversize", "legacy", "version",
                                    "not-complete", "practice", "wrong-battle-stage"])
def test_damaged_or_ineligible_saved_record_is_not_returned_or_repaired(battle_runtime, damage):
    from terralocal.server.domain.context import Context
    from terralocal.server.domain.replays import available

    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = cleared(client, token)
        assert save(client, token, battle_id).status_code == 200
        with runtime.database.transaction() as session:
            row = session.get(m.StageReplay, (1, "test_1"))
            stored = copy.deepcopy(row.replay)
            battle_row = session.get(m.BattleSession, battle_id)
            if damage == "fingerprint":
                stored["sha256"] = "0" * 64
            elif damage == "wrong-stage":
                wrong = journal()
                wrong["journal"]["metadata"]["stageId"] = "test_2"
                stored["battleReplay"] = packed(wrong)
                stored["sha256"] = hashlib.sha256(stored["battleReplay"].encode()).hexdigest()
            elif damage == "archive":
                stored["battleReplay"] = "not-base64"
                stored["sha256"] = hashlib.sha256(stored["battleReplay"].encode()).hexdigest()
            elif damage == "oversize":
                stored["battleReplay"] = "A" * 1_000_001
                stored["sha256"] = hashlib.sha256(stored["battleReplay"].encode()).hexdigest()
            elif damage == "legacy":
                stored = {"events": []}
            elif damage == "version":
                stored["gamedata_hash"] = "0" * 64
            elif damage == "not-complete":
                battle_row.settlement = {**battle_row.settlement, "stars": 2}
            elif damage == "practice":
                battle_row.practice = True
            else:
                battle_row.stage_id = "test_2"
            row.replay = stored
            if damage in {"fingerprint", "oversize", "legacy", "version"}:
                assert available(Context(session, runtime.data, 1), row) is False
        before = runtime.sync(token)
        response = load(client, token)
        assert response.status_code == 503 and response.json()["error"]["code"] == "INVALID_REPLAY_STATE"
        assert "battleReplay" not in response.json()
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.StageReplay, (1, "test_1")).replay == stored
