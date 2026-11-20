"""Information transactions, wire aliases and actual SQLite persistence."""

import copy
import sqlite3
from types import SimpleNamespace

import pytest
from crisis_v2_qa import VERSION, create, set_time, tables
from fastapi.testclient import TestClient

from terralocal.server.domain.accounts import create_account, login
from terralocal.server.gamedata.crisis_v2_catalog import CrisisV2Catalog
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def crisis(tmp_path):
    runtime, token = create(tmp_path)
    yield runtime, token
    runtime.database.close()


def send(client, token, seq=1):
    return client.post("/crisisV2/getInfo", json={}, headers={"secret": token, "seqnum": str(seq)})


def test_get_info_root_aliases_and_zero_progress_are_consistent(crisis):
    runtime, token = crisis
    state = runtime.sync(token)["user"]["crisisV2"]
    assert state["current"] == "season_a" and state["nst"] == 1200
    assert "currentSeason" not in state and "nextRefreshTs" not in state
    season = state["seasons"]["season_a"]
    assert season["coin"] == state["shop"]["coin"] == state["newRecordTs"] == 0
    assert season["permanent"]["scoreTotal"] == season["permanent"]["scoreSingle"] == [0] * 6
    assert not season["permanent"]["state"] and season["permanent"]["exRunes"] == {}
    assert season["temporary"]["season_a_t"]["scoreTotal"] == [0] * 6
    before = copy.deepcopy(state)
    with TestClient(create_game_app(runtime)) as client:
        response = send(client, token)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["info"]["seasonId"] == state["current"]
        assert body["ts"] == 1001
        assert set(body["info"]["mapStageDataMap"]) == {"season_a_p", "season_a_t"}
        assert send(client, token).json() == body
    assert runtime.sync(token)["user"]["crisisV2"] == before


def test_calendar_transition_sends_short_key_delta_and_keeps_history(crisis):
    runtime, token = crisis
    with runtime.database.transaction() as session:
        row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
        row.cleared, row.score_total, row.runes = True, [10, 0, 0, 0, 0, 0], {"rune": 3}
    set_time(runtime, 1999)
    assert runtime.sync(token)["user"]["crisisV2"]["current"] == "season_a"
    set_time(runtime, 2000)
    with TestClient(create_game_app(runtime)) as client:
        result = send(client, token).json()
    assert result["result"] == 0 and result["info"] is None
    assert result["playerDataDelta"]["modified"]["crisisV2"]["current"] == ""
    state = runtime.sync(token)["user"]["crisisV2"]
    assert state["current"] == "" and state["nst"] == 3000
    assert state["seasons"]["season_a"]["permanent"]["scoreTotal"][0] == 10
    set_time(runtime, 1001)
    assert runtime.sync(token)["user"]["crisisV2"]["seasons"] == state["seasons"]


def test_restart_and_account_isolation_use_saved_records(crisis):
    runtime, token = crisis
    with runtime.database.transaction() as session:
        other = create_account(session, runtime.data, "OtherDoctor")
        second = login(session, runtime.settings, name=other.name)["secret"]
        row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
        row.score_total, row.runes = [10, 0, 0, 0, 0, 0], {"rune": 3}
    with TestClient(create_game_app(runtime)) as client:
        original = send(client, token).json()
    expected = runtime.sync(token)["user"]["crisisV2"]
    assert runtime.sync(second)["user"]["crisisV2"]["seasons"]["season_a"]["permanent"]["scoreTotal"] == [0] * 6
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"]["crisisV2"] == expected
        with TestClient(create_game_app(reopened)) as client:
            assert send(client, token).json() == original
    finally:
        reopened.database.close()


def test_missing_active_source_rolls_back_crisis_and_receipt_changes(crisis):
    runtime, token = crisis
    with sqlite3.connect(runtime.database.path) as connection:
        before = {name: connection.execute('SELECT * FROM "' + name + '" ORDER BY 1').fetchall()
                  for name in ("crisis_v2_accounts", "crisis_v2_seasons", "crisis_v2_maps", "receipts", "player_profiles")}
    set_time(runtime, 3001)
    with TestClient(create_game_app(runtime)) as client:
        response = send(client, token)
    assert response.status_code == 503 and "CRISIS_V2_INFO_MISSING" in response.text
    with sqlite3.connect(runtime.database.path) as connection:
        for name, rows in before.items():
            assert connection.execute('SELECT * FROM "' + name + '" ORDER BY 1').fetchall() == rows


def test_second_season_initialization_keeps_first_progress(tmp_path):
    runtime, token = create(tmp_path, second_info=True)
    try:
        set_time(runtime, 3001)
        state = runtime.sync(token)["user"]["crisisV2"]
        assert state["current"] == "season_b"
        assert set(state["seasons"]) == {"season_a", "season_b"}
        with runtime.database.transaction() as session:
            assert len(session.query(m.CrisisV2MapProgress).all()) == 4
    finally:
        runtime.database.close()


@pytest.mark.parametrize("damage", ["client", "version", "calendar", "source", "stage", "permanent", "coin"])
def test_invalid_information_source_cannot_be_admitted(damage):
    raw = tables()
    source = raw["crisis_v2_server_table"]
    if damage == "client":
        source["client_elf_sha256"] = "b" * 64
    elif damage == "version":
        source["data_version"] = "different"
    elif damage == "calendar":
        source["calendar_policy"] = "always-open"
    elif damage == "source":
        del source["seasons"]["season_a"]["source"]
    elif damage == "stage":
        del source["seasons"]["season_a"]["info"]["mapDetailDataMap"]["season_a_t"]
    elif damage == "permanent":
        source["seasons"]["season_a"]["info"]["mapStageDataMap"]["season_a_t"]["stageType"] = "PERMANENT"
    else:
        raw["crisis_v2_table"]["constData"]["shopCoinId"] = "missing"
    data = SimpleNamespace(table=raw.__getitem__, item=raw["item_table"]["items"].__getitem__,
                           manifest={"hash": "a" * 64, "version": VERSION})
    with pytest.raises(ValueError):
        CrisisV2Catalog(data)


def test_info_payload_does_not_alias_the_source_or_another_response(crisis):
    runtime, _ = crisis
    first = runtime.data.crisis_v2.info("season_a")
    first["mapDetailDataMap"].clear()
    assert len(runtime.data.crisis_v2.info("season_a")["mapDetailDataMap"]) == 2


def test_info_requires_authentication_and_rejects_unexpected_fields(crisis):
    runtime, token = crisis
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        denied = client.post("/crisisV2/getInfo", json={}, headers={"seqnum": "1"})
        assert denied.status_code == 401
        invalid = client.post("/crisisV2/getInfo", json={"coin": 999},
                              headers={"secret": token, "seqnum": "1"})
        assert invalid.status_code == 422
    assert runtime.sync(token) == before
    with runtime.database.transaction() as session:
        assert session.query(m.Receipt).count() == 0
