"""Mainline cursor follows real clears, native deltas, isolation and restart."""

from copy import deepcopy

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from test_native_battle_start import begin
from test_native_training import training_body, training_finish
from test_native_training import training_runtime as training_runtime
from test_unplayed_mainline import login, play
from test_unplayed_mainline import mainline_runtime as mainline_runtime

from terralocal.server.domain import accounts
from terralocal.server.gamedata.repository import validate_tables
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


def cursor(runtime, token):
    return runtime.sync(token)["user"]["status"]["mainStageProgress"]


def test_first_cursor_is_a_stage_id_and_reads_create_no_progress(mainline_runtime):
    runtime = mainline_runtime
    token = login(runtime)
    assert cursor(runtime, token) == "test_1"
    with runtime.database.transaction() as session:
        profile = session.get(m.PlayerProfile, 1)
        profile.level = 3
        profile.flags = {**profile.flags, "mainStageProgress": {"invented": "chapter"}}
    assert cursor(runtime, token) == "test_1"
    assert cursor(runtime, token) == "test_1"
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.StageProgress).count() == 0
        assert session.query(m.BattleSession).count() == 0
        assert session.query(m.DomainEvent).count() == 0
        assert session.get(m.PlayerProfile, 1).revision == 0


@pytest.mark.parametrize("stars", [1, 2, 3])
def test_actual_clear_moves_cursor_in_the_same_delta(mainline_runtime, stars):
    runtime = mainline_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        started = client.post("/local/v1/battle/start", headers={"secret": token, "seqnum": "start"},
                              json={"stageId": "test_1"})
        assert started.status_code == 200 and cursor(runtime, token) == "test_1"
        before = runtime.sync(token)["user"]
        finished = client.post("/local/v1/battle/finish", headers={"secret": token, "seqnum": "finish"},
                               json={"battleId": started.json()["battleId"], "stars": stars})
        assert finished.status_code == 200
        result = finished.json()
        assert result["playerDataDelta"]["modified"]["status"]["mainStageProgress"] == "test_2"
        after = runtime.sync(token)["user"]
        assert apply(before, result["playerDataDelta"]) == after
        assert after["dungeon"]["stages"]["test_2"]["state"] == 0
        repeated = client.post("/local/v1/battle/finish", headers={"secret": token, "seqnum": "finish"},
                               json={"battleId": started.json()["battleId"], "stars": stars})
        assert repeated.json() == result and runtime.sync(token)["user"] == after


@pytest.mark.parametrize("practice,stars", [(False, 0), (True, 3)])
def test_failure_and_practice_do_not_advance_the_cursor(mainline_runtime, practice, stars):
    runtime = mainline_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        started = client.post("/local/v1/battle/start", headers={"secret": token, "seqnum": "start"},
                              json={"stageId": "test_1", "practice": practice})
        assert started.status_code == 200
        result = client.post("/local/v1/battle/finish", headers={"secret": token, "seqnum": "finish"},
                             json={"battleId": started.json()["battleId"], "stars": stars})
        assert result.status_code == 200
    assert cursor(runtime, token) == "test_1"
    assert "mainStageProgress" not in result.json()["playerDataDelta"]["modified"].get("status", {})


def test_chapter_gate_time_account_isolation_and_restart(mainline_runtime):
    runtime = mainline_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
    other = login(runtime, "Other")
    with TestClient(create_game_app(runtime)) as client:
        play(client, token, "test_1", 1)
        assert cursor(runtime, token) == "test_2"
        play(client, token, "test_2", 1)
        assert cursor(runtime, token) == "chapter_2"
        play(client, token, "chapter_2", 1)
        assert cursor(runtime, token) is None  # The timed chapter has not opened.
    assert cursor(runtime, other) == "test_1"
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert cursor(restarted, token) is None
        with restarted.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += 86400
        assert cursor(restarted, token) == "timed"
        assert cursor(restarted, other) == "test_1"
        with restarted.database.transaction(write=False) as session:
            assert session.get(m.StageProgress, (1, "timed")) is None
    finally:
        restarted.database.close()


def test_sort_is_from_gamedata_and_excludes_other_modes(mainline_runtime):
    runtime = mainline_runtime
    token = login(runtime)
    data = runtime.data
    base = deepcopy(data.stages["test_1"])
    # Deliberately reverse dictionary order; cosmetic IDs are not the sequence.
    entries = {k: v for k, v in reversed(list(data.stages.items()))}
    for sid, changes in [("a-event", {"stageType": "ACTIVITY"}),
                         ("a-hard", {"difficulty": "FOUR_STAR"}),
                         ("a-easy", {"diffGroup": "EASY"}),
                         ("a-zero", {"slProgress": 0})]:
        entries[sid] = {**deepcopy(base), "stageId": sid, **changes}
    data._tables["stage_table"]["stages"] = entries
    data.__dict__.pop("stages", None)
    data.__dict__.pop("mainline_progress_order", None)
    assert cursor(runtime, token) == "test_1"


def test_native_fixed_training_clear_updates_the_cursor(training_runtime):
    runtime = training_runtime
    for stage_id, index in [("test_1", 1), ("training", 2), ("test_2", 3)]:
        runtime.data.stages[stage_id]["slProgress"] = index
    runtime.data.stages["test_2"]["unlockCondition"] = [{"stageId": "training", "completeState": "PASS"}]
    token = login(runtime)
    assert cursor(runtime, token) == "training"
    with TestClient(create_game_app(runtime)) as client:
        started = begin(client, token, training_body())
        assert started.status_code == 200 and cursor(runtime, token) == "training"
        before = runtime.sync(token)["user"]
        finished = training_finish(client, token, started.json()["battleId"], state=2)
        assert finished.status_code == 200
        assert finished.json()["playerDataDelta"]["modified"]["status"]["mainStageProgress"] == "test_2"
        assert apply(before, finished.json()["playerDataDelta"]) == runtime.sync(token)["user"]


@pytest.mark.parametrize("bad", [True, "1", -1, 2**31])
def test_import_rejects_invalid_client_progress_numbers(bad):
    tables = miniature()
    tables["stage_table"]["stages"]["test_1"]["slProgress"] = bad
    with pytest.raises(ValueError, match="主线排序值非法"):
        validate_tables(tables)


def test_ambiguous_order_fails_without_granting_progress(mainline_runtime):
    runtime = mainline_runtime
    token = login(runtime)
    runtime.data.stages["test_2"]["slProgress"] = 1
    with TestClient(create_game_app(runtime)) as client:
        response = client.post("/account/syncData", headers={"secret": token}, json={})
    assert response.status_code == 503 and response.json()["error"]["code"] == "GAMEDATA_INVALID"
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.StageProgress).count() == 0
        assert session.get(m.PlayerProfile, 1).revision == 0
