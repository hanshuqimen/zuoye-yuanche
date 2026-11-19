"""Unlocked stage views without fabricated gameplay or persistence writes."""

import json
from copy import deepcopy

import pytest
from conftest import miniature
from fastapi.testclient import TestClient

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def mainline_runtime(tmp_path):
    tables = miniature()
    tables["gamedata_const"]["playerApMap"] = [20, 22, 24]
    stages = tables["stage_table"]["stages"]
    for row in stages.values():
        row.update(stageType="MAIN", zoneId="main_0")
    stages["test_2"]["unlockCondition"][0]["completeState"] = "PASS"
    for stage_id, zone_id in [("chapter_2", "main_1"), ("timed", "main_time")]:
        stages[stage_id] = {**deepcopy(stages["test_1"]), "stageId": stage_id,
                            "zoneId": zone_id, "unlockCondition": []}
    for index, stage_id in enumerate(("test_1", "test_2", "chapter_2", "timed"), 1):
        stages[stage_id].update(slProgress=index, difficulty="NORMAL", diffGroup="NONE")
    tables["zone_table"] = {
        "zones": {key: {"zoneID": key, "type": "MAINLINE"} for key in ["main_0", "main_1", "main_time"]},
        "mainlineAdditionInfo": {
            "main_0": {"zoneOpenTime": -1, "preposedZoneId": None,
                       "startStageId": "test_1", "endStageId": "test_2"},
            "main_1": {"zoneOpenTime": -1, "preposedZoneId": "main_0",
                       "startStageId": "chapter_2", "endStageId": "chapter_2"},
            "main_time": {"zoneOpenTime": 1_800_086_400, "preposedZoneId": None,
                          "startStageId": "timed", "endStageId": "timed"}}}
    source = tmp_path / "source"
    source.mkdir()
    for name, content in tables.items():
        (source / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    runtime.drop_rules = {key: {"rewards": [], "first_rewards": []} for key in stages}
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
    yield runtime
    runtime.database.close()


def login(runtime, name="Doctor"):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name=name)["secret"]


def play(client, token, stage_id, stars):
    start = client.post("/local/v1/battle/start", headers={
        "secret": token, "seqnum": f"start-{stage_id}"}, json={"stageId": stage_id})
    assert start.status_code == 200
    finish = client.post("/local/v1/battle/finish", headers={
        "secret": token, "seqnum": f"finish-{stage_id}"}, json={
            "battleId": start.json()["battleId"], "stars": stars, "kills": 1, "duration": 30.0})
    assert finish.status_code == 200
    return finish.json()


def test_first_stage_is_unlocked_without_creating_progress(mainline_runtime):
    runtime = mainline_runtime
    token = login(runtime)
    snapshot = runtime.sync(token)
    stages = snapshot["user"]["dungeon"]["stages"]
    assert set(stages) == {"test_1"}
    assert stages["test_1"] == {"stageId": "test_1", "state": 0, "completeTimes": 0,
                               "startTimes": 0, "practiceTimes": 0, "hasBattleReplay": 0, "noCostCnt": 0}
    assert runtime.sync(token) == snapshot
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.StageProgress).count() == 0
        assert session.query(m.BattleSession).count() == 0
        assert session.query(m.DomainEvent).count() == 0
        assert session.get(m.PlayerProfile, 1).revision == 0


@pytest.mark.parametrize("stars", [1, 3])
def test_battle_delta_opens_next_stage_without_fabricating_a_clear(mainline_runtime, stars):
    runtime = mainline_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        start = client.post("/local/v1/battle/start", headers={"secret": token, "seqnum": "start"},
                            json={"stageId": "test_1"})
        assert start.status_code == 200
        started = runtime.sync(token)["user"]
        assert started["dungeon"]["stages"]["test_1"]["state"] == 1
        finish = client.post("/local/v1/battle/finish", headers={"secret": token, "seqnum": "finish"},
                             json={"battleId": start.json()["battleId"], "stars": stars})
    assert finish.status_code == 200
    after = runtime.sync(token)["user"]
    assert apply(started, finish.json()["playerDataDelta"]) == after
    assert after["dungeon"]["stages"]["test_1"]["state"] == (3 if stars == 3 else 2)
    next_stage = after["dungeon"]["stages"]["test_2"]
    assert next_stage["state"] == next_stage["startTimes"] == next_stage["completeTimes"] == 0
    with runtime.database.transaction(write=False) as session:
        # The existing settlement service records newly unlocked successors.
        # That is a legitimate unlock, with no fabricated start or clear.
        row = session.get(m.StageProgress, (1, "test_2"))
        assert row.unlocked and row.stars == row.start_count == row.clear_count == 0


def test_chapter_and_time_conditions_with_account_isolation(mainline_runtime):
    runtime = mainline_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
    other = login(runtime, "Other")
    with TestClient(create_game_app(runtime)) as client:
        play(client, token, "test_1", 1)
        play(client, token, "test_2", 1)
    snapshot = runtime.sync(token)
    assert "chapter_2" in snapshot["user"]["dungeon"]["stages"]
    assert "timed" not in snapshot["user"]["dungeon"]["stages"]
    assert set(runtime.sync(other)["user"]["dungeon"]["stages"]) == {"test_1"}
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.StageProgress, (1, "chapter_2")) is None
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == snapshot
        with restarted.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at = 1_800_086_400
        assert "timed" in restarted.sync(token)["user"]["dungeon"]["stages"]
        with restarted.database.transaction(write=False) as session:
            assert session.get(m.StageProgress, (1, "timed")) is None
    finally:
        restarted.database.close()
