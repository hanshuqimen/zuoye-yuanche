"""Native claims: reward conservation, dependency transitions and rollback."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import miniature
from fastapi.testclient import TestClient

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def claim_runtime(tmp_path):
    tables = miniature()
    definitions, groups = {}, {}
    for ident, stage, predecessor in (("main_1", "test_1", None), ("main_2", "test_2", "main_1")):
        definitions[ident] = {"id": ident, "type": "MAIN", "template": "CompleteMainStage",
                              "param": ["1", stage, "1"], "missionGroup": ident, "periodicalPoint": 0,
                              "preMissionIds": None, "unlockCondition": None, "unlockParam": None,
                              "countEndTs": -1, "rewards": [{"id": "2001", "type": "CARD_EXP", "count": 5}]}
        groups[ident] = {"id": ident, "type": "MAIN", "missionIds": [ident],
                         "preMissionGroup": predecessor, "rewards": None, "period": None,
                         "startTs": -1, "endTs": -1}
    tables["mission_table"] = {"missions": definitions, "missionGroups": groups}
    source = tmp_path / "source"
    source.mkdir()
    for name, table in tables.items():
        (source / f"{name}.json").write_text(json.dumps(table), encoding="utf-8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        accounts.create_account(session, runtime.data, "Other")
        session.add(m.MissionProgress(account_id=1, mission_id="main_1", period="permanent",
                                      progress=1, claimed=False))
    yield runtime
    runtime.database.close()


def login(runtime, name="Doctor", kind="game"):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name=name, kind=kind)["secret"]


def claim(client, token, ident="main_1", key="claim"):
    return client.post("/mission/confirmMission", headers={"secret": token, "seqnum": key},
                       json={"missionId": ident})


def test_concurrent_claim_retry_new_session_delta_and_restart(claim_runtime):
    runtime = claim_runtime
    token = login(runtime)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=4) as workers:
            responses = list(workers.map(lambda _: claim(client, token), range(6)))
        assert all(response.status_code == 200 and response.json() == responses[0].json()
                   for response in responses)
        result = responses[0].json()
        assert set(result) == {"result", "playerDataDelta", "ts", "revision"}
        after = runtime.sync(token)["user"]
        assert apply(before, result["playerDataDelta"]) == after
        assert after["inventory"]["2001"] == 5
        assert after["mission"]["missionGroups"] == {"main_1": 1, "main_2": 0}
        assert after["mission"]["missions"]["MAIN"]["main_1"]["state"] == 3
        assert after["mission"]["missions"]["MAIN"]["main_2"] == {
            "state": 2, "progress": [{"target": 1, "value": 0, "compare": ">="}]}
        not_ready = claim(client, token, ident="main_2", key="claim-not-ready")
        assert not_ready.status_code == 409 and not_ready.json()["error"]["code"] == "MISSION_NOT_COMPLETE"
        assert runtime.sync(token)["user"] == after
        assert claim(client, token, key="new-sequence").status_code == 200
        assert runtime.sync(token)["user"] == after
        new_token = login(runtime)
        assert claim(client, new_token).status_code == 200
        assert runtime.sync(new_token)["user"] == after
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(new_token)["user"] == after
    finally:
        restarted.database.close()


def test_claim_cannot_use_another_accounts_completed_mission(claim_runtime):
    runtime = claim_runtime
    token = login(runtime, "Other")
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        response = claim(client, token)
    assert response.status_code == 404 and response.json()["error"]["code"] == "MISSION_NOT_ASSIGNED"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert not session.get(m.MissionProgress, (1, "main_1", "permanent")).claimed


@pytest.mark.parametrize("failure,status,code", [
    ("incomplete", 409, "MISSION_NOT_COMPLETE"), ("unknown", 404, "UNKNOWN_MISSION"),
    ("points", 501, "MISSION_CONFIRM_UNSUPPORTED"), ("deadline", 501, "MISSION_CONFIRM_UNSUPPORTED"),
    ("reward-type", 503, "MISSION_DEFINITION_INVALID"), ("reward-count", 503, "MISSION_DEFINITION_INVALID"),
    ("unsupported-successor", 501, "MISSION_CONFIRM_UNSUPPORTED"),
    ("inventory-cap", 400, "INVENTORY_LIMIT"), ("group-reward", 501, "MISSION_GROUP_UNSUPPORTED"),
])
def test_failed_claim_rolls_back_rewards_progress_and_receipt(claim_runtime, failure, status, code):
    runtime = claim_runtime
    token = login(runtime)
    table = runtime.data.table("mission_table")
    definition = table["missions"]["main_1"]
    if failure == "incomplete":
        with runtime.database.transaction() as session:
            session.get(m.MissionProgress, (1, "main_1", "permanent")).progress = 0
    elif failure == "points":
        definition["periodicalPoint"] = 10
    elif failure == "deadline":
        definition["countEndTs"] = 1_900_000_000
    elif failure == "reward-type":
        definition["rewards"][0]["type"] = "GOLD"
    elif failure == "reward-count":
        definition["rewards"][0]["count"] = True
    elif failure == "unsupported-successor":
        table["missions"]["main_2"]["template"] = "HasRoom"
    elif failure == "inventory-cap":
        with runtime.database.transaction() as session:
            session.add(m.InventoryItem(account_id=1, item_id="2001", count=2_000_000_000))
    elif failure == "group-reward":
        table["missionGroups"]["main_1"]["rewards"] = [{"id": "2001", "count": 1, "type": "CARD_EXP"}]
    before = runtime.sync(token)
    with runtime.database.transaction(write=False) as session:
        receipts = session.query(m.Receipt).count()
    with TestClient(create_game_app(runtime)) as client:
        response = claim(client, token, ident="unknown" if failure == "unknown" else "main_1")
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.Receipt).count() == receipts
        assert not session.get(m.MissionProgress, (1, "main_1", "permanent")).claimed
        assert session.get(m.MissionProgress, (1, "main_2", "permanent")) is None


def test_response_assembly_failure_rolls_back_the_whole_claim(claim_runtime, monkeypatch):
    runtime = claim_runtime
    token = login(runtime)
    before = runtime.sync(token)
    original = SyncDataAssembler.assemble
    calls = 0

    def failed_after(self):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DomainError("SYNTHETIC_ASSEMBLY_FAILURE", "synthetic rollback probe", 503)
        return original(self)

    with TestClient(create_game_app(runtime)) as client, monkeypatch.context() as patch:
        patch.setattr(SyncDataAssembler, "assemble", failed_after)
        response = claim(client, token)
    assert response.status_code == 503
    assert runtime.sync(token) == before


def test_successor_uses_saved_clear_without_resetting_existing_progress(claim_runtime):
    runtime = claim_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_2", stars=3, clear_count=1))
    with TestClient(create_game_app(runtime)) as client:
        assert claim(client, token).status_code == 200
        assert runtime.sync(token)["user"]["mission"]["missions"]["MAIN"]["main_2"]["state"] == 2
        assert claim(client, token, ident="main_2", key="claim-second").status_code == 200
    assert runtime.sync(token)["user"]["inventory"]["2001"] == 10


def test_future_mission_cannot_be_claimed_before_predecessor(claim_runtime):
    runtime = claim_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.add(m.MissionProgress(account_id=1, mission_id="main_2", period="permanent",
                                      progress=1, claimed=False))
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        response = claim(client, token, ident="main_2")
    assert response.status_code == 409 and response.json()["error"]["code"] == "MISSION_LOCKED"
    assert runtime.sync(token) == before


def test_sdk_session_cannot_claim(claim_runtime):
    runtime = claim_runtime
    token = login(runtime, kind="sdk")
    with TestClient(create_game_app(runtime)) as client:
        assert claim(client, token).status_code == 401
