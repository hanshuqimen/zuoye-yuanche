"""Native start requests must reserve AP once and use the saved formation."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import miniature
from fastapi.testclient import TestClient

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def battle_runtime(tmp_path):
    tables = miniature()
    for stage in tables["stage_table"]["stages"].values():
        stage.update(stageType="MAIN", difficulty="NORMAL", diffGroup="NONE",
                     apProtectTimes=0, isPredefined=False, isStagePatch=False)
    tables["stage_table"]["apProtectZoneInfo"] = {}
    for stage_id, changes in [
        ("protected", {"apProtectTimes": 1}),
        ("protected_zone", {"zoneId": "unverified_protection"}),
        ("special", {"stageType": "SUB"}),
        ("hard_predefined", {"isHardPredefined": True}),
    ]:
        tables["stage_table"]["stages"][stage_id] = {
            **tables["stage_table"]["stages"]["test_1"], "stageId": stage_id, **changes}
    tables["stage_table"]["apProtectZoneInfo"]["unverified_protection"] = {}
    source = tmp_path / "source"
    source.mkdir()
    for name, content in tables.items():
        (source / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    runtime.drop_rules = {"test_1": {"rewards": [], "first_rewards": []},
                          "test_2": {"rewards": [], "first_rewards": []}}
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
    yield runtime
    runtime.database.close()


def login(runtime):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name="Doctor")["secret"]


def body():
    return {"stageId": "test_1", "squad": {"squadId": "0", "name": "Formation 1", "slots": [
        {"charInstId": 1, "skillIndex": 0, "currentEquip": None}]},
        "usePracticeTicket": 0, "assistFriend": None, "isReplay": 0, "startTs": 1,
        "isRetro": 0, "pry": 0, "battleType": 0, "multiple": None, "extra": None}


def begin(client, token, payload, key="start"):
    return client.post("/quest/battleStart", headers={"secret": token, "seqnum": key}, json=payload)


def test_retry_concurrency_restart_and_delta(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=8) as workers:
            replies = list(workers.map(lambda _: begin(client, token, body()), range(8)))
        assert all(reply.status_code == 200 for reply in replies)
        response = replies[0].json()
        assert all(reply.json() == response for reply in replies)
        assert response["result"] == 0 and isinstance(response["battleId"], str)
        assert response["isApProtect"] is False and response["inApProtectPeriod"] is False
        assert response["apFailReturn"] == 5
        assert begin(client, token, body(), key="another-start").status_code == 409
        changed = body()
        changed["startTs"] = 2
        assert begin(client, token, changed).status_code == 409
    after = runtime.sync(token)
    assert after["user"]["status"]["ap"] == before["user"]["status"]["ap"] - 6
    assert after["revision"] == before["revision"] + 1
    assert apply(before["user"], response["playerDataDelta"]) == after["user"]
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, response["battleId"])
        assert row.started_at == 1_800_000_000  # Never the client's untrusted startTs.
        assert row.sanity_cost == 6 and row.state == "STARTED"
        assert row.squad_snapshot[0]["charInstId"] == 1
        assert session.query(m.BattleSession).count() == 1
        assert session.get(m.StageProgress, (1, "test_1")).start_count == 1
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == after
        with TestClient(create_game_app(restarted)) as client:
            assert begin(client, token, body()).json() == response
    finally:
        restarted.database.close()


@pytest.mark.parametrize("field,value", [
    ("usePracticeTicket", 1), ("isRetro", 1), ("pry", 1),
    ("battleType", 1), ("battleType", 2), ("assistFriend", {}), ("multiple", {}), ("extra", {}),
])
def test_unimplemented_modes_cannot_spend_ap(battle_runtime, field, value):
    runtime = battle_runtime
    token = login(runtime)
    before = runtime.sync(token)
    payload = body()
    payload[field] = value
    with TestClient(create_game_app(runtime)) as client:
        response = begin(client, token, payload)
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "BATTLE_MODE_UNSUPPORTED"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).count() == session.query(m.Receipt).count() == 0


@pytest.mark.parametrize("wire", [2, "0", 0.0, None])
def test_invalid_boolean_encoding_is_not_coerced(battle_runtime, wire):
    runtime = battle_runtime
    token = login(runtime)
    before = runtime.sync(token)
    payload = body()
    payload["isReplay"] = wire
    with TestClient(create_game_app(runtime)) as client:
        assert begin(client, token, payload).status_code == 422
    assert runtime.sync(token) == before


def test_stale_squad_foreign_operator_locked_stage_and_modules(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        for change, status in [({"charInstId": 2}, 409), ({"skillIndex": 1}, 409),
                               ({"currentEquip": "unverified"}, 501)]:
            payload = body()
            payload["squad"]["slots"][0].update(change)
            assert begin(client, token, payload).status_code == status
        locked = body()
        locked["stageId"] = "test_2"
        assert begin(client, token, locked).status_code == 400
        absent = body()
        absent["squad"]["squadId"] = "9"
        assert begin(client, token, absent).status_code == 404
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).count() == session.query(m.Receipt).count() == 0


def test_two_distinct_concurrent_starts_allow_only_one_battle(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=2) as workers:
            replies = list(workers.map(lambda key: begin(client, token, body(), key), ["a", "b"]))
    assert sorted(reply.status_code for reply in replies) == [200, 409]
    assert runtime.sync(token)["user"]["status"]["ap"] == before["user"]["status"]["ap"] - 6


def test_unverified_protection_and_special_stages_cannot_be_charged(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        for stage_id in ["protected", "protected_zone", "special", "hard_predefined"]:
            payload = body()
            payload["stageId"] = stage_id
            assert begin(client, token, payload).status_code == 501
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).count() == session.query(m.Receipt).count() == 0


def test_insufficient_ap_does_not_create_a_started_battle(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.get(m.SanityState, 1).current = 5
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        response = begin(client, token, body())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INSUFFICIENT_SANITY"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).count() == session.query(m.StageProgress).count() == 0


def test_response_failure_rolls_back_ap_battle_progress_and_receipt(battle_runtime, monkeypatch):
    runtime = battle_runtime
    token = login(runtime)
    before = runtime.sync(token)
    original = SyncDataAssembler.assemble
    calls = 0

    def fail_after_start(self):
        nonlocal calls
        calls += 1
        if calls == 2:
            assert self.ctx.session.query(m.BattleSession).count() == 1
            raise RuntimeError("Synthetic response failure")
        return original(self)

    with monkeypatch.context() as patch:
        patch.setattr(SyncDataAssembler, "assemble", fail_after_start)
        with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
            assert begin(client, token, body()).status_code == 500
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).count() == session.query(m.StageProgress).count() == 0
        assert session.query(m.Receipt).count() == 0


def test_native_start_keeps_local_api_separate(battle_runtime):
    runtime = battle_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        assert begin(client, token, {"stageId": "test_1", "squadId": "0"}).status_code == 422
        local = client.post("/local/v1/battle/start", headers={"secret": token, "seqnum": "local"},
                            json={"stageId": "test_1", "squadId": "0"})
        assert local.status_code == 200
