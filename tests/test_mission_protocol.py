"""Reproduce nonempty mission updates using the frozen nested list contract."""

import json

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from test_native_battle_finish import complete, encoded
from test_native_battle_start import begin, body, login

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.domain.clock import ServerClock
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def mission_runtime(tmp_path):
    tables = miniature()
    for stage in tables["stage_table"]["stages"].values():
        stage.update(stageType="MAIN", difficulty="NORMAL", diffGroup="NONE", apProtectTimes=0,
                     isPredefined=False, isHardPredefined=False, isStagePatch=False)
    tables["gamedata_const"]["playerApMap"] = [100, 112, 114]
    definitions = {"main_first": ("MAIN", "CompleteMainStage", ["1", "test_1", "1"]),
                   "guide_stars": ("GUIDE", "CompleteStage", ["2", "3", "1"]),
                   "guide_practice": ("GUIDE", "CompleteStage", ["3", "1"]),
                   "sub_other": ("SUB", "CompleteStage", ["0", "test_2", "1"]),
                   "daily_assigned": ("DAILY", "CompleteStageAnyType", ["0", "4", "2"]),
                   "daily_not_assigned": ("DAILY", "CompleteStageAnyType", ["0", "4", "2"])}
    tables["mission_table"] = {"missions": {key: {"id": key, "type": category, "template": template,
                                                    "param": params}
                                           for key, (category, template, params) in definitions.items()}}
    source = tmp_path / "source"
    source.mkdir()
    for name, table in tables.items():
        (source / f"{name}.json").write_text(json.dumps(table), encoding="utf-8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    runtime.drop_rules = {"test_1": {"rewards": [], "first_rewards": []}}
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        accounts.create_account(session, runtime.data, "Other")
        period = ServerClock(clock).period("daily")
        session.add(m.MissionProgress(account_id=1, mission_id="daily_assigned", period=period,
                                      progress=0, claimed=False))
    yield runtime
    runtime.database.close()


def assert_native_groups(snapshot):
    # Independent structural expectations from native metadata: every group
    # value is a dictionary of state objects; progress is a list of calc states.
    groups = snapshot["mission"]["missions"]
    assert set(groups) >= {"MAIN", "SUB", "GUIDE", "DAILY", "WEEKLY"}
    for category, entries in groups.items():
        assert category.isupper() and isinstance(entries, dict)
        for info in entries.values():
            assert type(info["state"]) is int and info["state"] in range(4)
            assert isinstance(info["progress"], list)
            for calc in info["progress"]:
                assert set(calc) == {"target", "value", "compare"}
                assert type(calc["value"]) is int and type(calc["target"]) is int


def test_two_star_then_three_star_updates_correct_missions_with_native_lists_and_delta(mission_runtime):
    runtime = mission_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        for index, stars in enumerate((2, 3)):
            battle_id = begin(client, token, body(), f"start-{index}").json()["battleId"]
            before = runtime.sync(token)["user"]
            response = complete(client, token, encoded(battle_id, state=stars), f"finish-{index}")
            assert response.status_code == 200
            after = runtime.sync(token)["user"]
            assert apply(before, response.json()["playerDataDelta"]) == after
            assert_native_groups(after)
            groups = after["mission"]["missions"]
            assert groups["MAIN"]["main_first"] == {
                "state": 2, "progress": [{"target": 1, "value": 1, "compare": ">="}]}
            assert "sub_other" not in groups["SUB"]
            assert "guide_practice" not in groups["GUIDE"]
            assert ("guide_stars" in groups["GUIDE"]) == (stars == 3)
            assert groups["DAILY"]["daily_assigned"] == {
                "state": 2, "progress": [{"target": 4, "value": index + 1, "compare": ">="}]}
            assert "daily_not_assigned" not in groups["DAILY"]
            assert complete(client, token, encoded(battle_id, state=stars), f"retry-{index}").status_code == 200
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.MissionProgress).filter_by(account_id=2).count() == 0
        assert session.get(m.MissionProgress, (1, "main_first", "permanent")).progress == 2
    expected = runtime.sync(token)
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == expected
    finally:
        restarted.database.close()


def test_practice_advances_only_practice_guide_and_does_not_grant_rewards(mission_runtime):
    runtime = mission_runtime
    token = login(runtime)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        start = client.post("/local/v1/battle/start", json={"stageId": "test_1", "practice": True},
                            headers={"secret": token, "seqnum": "practice-start"})
        assert start.status_code == 200
        response = client.post("/local/v1/battle/finish", json={"battleId": start.json()["battleId"], "stars": 3},
                               headers={"secret": token, "seqnum": "practice-finish"})
        assert response.status_code == 200
        assert response.json()["rewards"] == response.json()["firstRewards"] == []
    after = runtime.sync(token)["user"]
    assert after["status"]["ap"] == before["status"]["ap"]
    groups = after["mission"]["missions"]
    assert groups["GUIDE"]["guide_practice"]["state"] == 2
    assert "guide_stars" not in groups["GUIDE"] and groups["MAIN"] == {}
    assert groups["DAILY"]["daily_assigned"]["progress"][0]["value"] == 0


def test_claimed_enum_and_progress_cap_match_native_holding_states(mission_runtime):
    runtime = mission_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.add(m.MissionProgress(account_id=1, mission_id="guide_stars", period="permanent",
                                      progress=10, claimed=True))
    info = runtime.sync(token)["user"]["mission"]["missions"]["GUIDE"]["guide_stars"]
    assert info == {"state": 3, "progress": [{"target": 1, "value": 1, "compare": ">="}]}


def test_unknown_saved_mission_fails_explicitly_instead_of_flattening_or_guessing(mission_runtime):
    runtime = mission_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.add(m.MissionProgress(account_id=1, mission_id="undefined", period="permanent",
                                      progress=1, claimed=False))
    with pytest.raises(DomainError) as raised:
        runtime.sync(token)
    assert raised.value.code == "UNKNOWN_SAVED_MISSION"
