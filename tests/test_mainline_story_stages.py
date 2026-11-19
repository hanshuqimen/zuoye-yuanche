"""Representative story-only progression; synthetic data, no repeated gameplay."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from test_story_completion import finish

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.gamedata import import_data
from terralocal.server.gamedata.repository import canonical
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def plot_runtime(tmp_path):
    tables = miniature()
    stages = tables["stage_table"]["stages"]
    for index in (1, 2):
        key = f"plot_{index}"
        stages[key] = {**deepcopy(stages["test_1"]), "stageId": key, "stageType": "MAIN",
                       "difficulty": "NORMAL", "diffGroup": "NONE", "zoneId": f"chapter_{index}",
                       "isStoryOnly": True, "levelId": None, "apCost": 0, "apFailReturn": 0,
                       "goldGain": 0, "expGain": 0, "passFavor": 0, "completeFavor": 0,
                       "canPractice": False, "canBattleReplay": False,
                       "unlockCondition": [{"stageId": "test_1", "completeState": "PASS"}] if index == 1 else [],
                       "stageDropInfo": {"displayDetailRewards": [
                           {"id": "4002", "type": "DIAMOND", "dropType": "COMPLETE", "occPercent": "ALWAYS"}]}}
        tables["story_table"][key] = {
            **deepcopy(tables["story_table"]["synthetic_intro"]), "id": key, "completedRewards": [],
            "setProgress": -1, "trigger": {"type": "BEFORE_BATTLE", "key": key, "useRegex": False}}
    stages["test_2"].update(stageType="MAIN", zoneId="chapter_2",
                            unlockCondition=[{"stageId": "plot_2", "completeState": "PASS"}])
    stages["plot_2"]["diffGroup"] = "ALL"
    tables["stage_table"]["storyStageShowGroup"] = {"plot_2": {
        key: {"stageId": "plot_2", "diffGroup": key, "accordingStageId": None}
        for key in ("EASY", "NORMAL", "TOUGH")}}
    tables["zone_table"] = {"zones": {}, "mainlineAdditionInfo": {
        "chapter_1": {"endStageId": "plot_1", "preposedZoneId": None, "zoneOpenTime": -1},
        "chapter_2": {"endStageId": "plot_2", "preposedZoneId": "chapter_1", "zoneOpenTime": -1}}}
    source = tmp_path / "source"
    source.mkdir()
    for name, value in tables.items():
        (source / f"{name}.json").write_bytes(canonical(value))
    manifest = import_data(source, tmp_path / "data/cache")
    runtime = Runtime(Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False))
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=3, clear_count=1))
    yield runtime
    runtime.database.close()


def login(runtime):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name="Doctor")["secret"]


def test_story_stage_clear_once_unlocks_next_chapter_and_persists(plot_runtime):
    runtime = plot_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)["user"]
        assert "plot_2" not in before["dungeon"]["stages"]
        first = finish(client, token, "plot_1", 1)
        assert first.status_code == 200
        result = first.json()
        assert result["items"] == [{"id": "4002", "type": "DIAMOND", "count": 1}]
        after = runtime.sync(token)["user"]
        assert apply(before, result["playerDataDelta"]) == after
        assert after["dungeon"]["stages"]["plot_1"]["state"] == 3
        assert after["dungeon"]["stages"]["plot_2"]["state"] == 0
        assert after["status"]["ap"] == before["status"]["ap"]
        assert finish(client, token, "plot_1", 1).json() == result
        assert finish(client, token, "plot_1", 2).json()["items"] == []
        assert finish(client, token, "plot_2", 3).status_code == 200
        assert runtime.sync(token)["user"]["dungeon"]["stages"]["test_2"]["state"] == 0
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.Currency, (1, "4002")).balance == 2
        assert session.get(m.StageProgress, (1, "plot_1")).clear_count == 1
        assert session.get(m.StageProgress, (1, "plot_1")).start_count == 0
        assert session.get(m.StageProgress, (2, "plot_1")) is None
        assert session.query(m.BattleSession).count() == session.query(m.StageReplay).count() == 0
    expected = runtime.sync(token)
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == expected
    finally:
        reopened.database.close()


def test_locked_or_future_chapter_cannot_be_cleared_by_story_id(plot_runtime):
    runtime = plot_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)
        assert finish(client, token, "plot_2", 1).json()["error"]["code"] == "STORY_LOCKED"
        assert runtime.sync(token) == before
        finish(client, token, "plot_1", 2)
        runtime.data.table("zone_table")["mainlineAdditionInfo"]["chapter_2"]["zoneOpenTime"] = 1_800_000_001
        assert finish(client, token, "plot_2", 3).json()["error"]["code"] == "STORY_LOCKED"


def test_legacy_story_completion_repairs_stage_without_retroactive_payment(plot_runtime):
    runtime = plot_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.add(m.StoryCompletion(account_id=1, story_id="plot_1", completed_at=1_700_000_000))
    with TestClient(create_game_app(runtime)) as client:
        assert finish(client, token, "plot_1", 1).json()["items"] == []
        assert finish(client, token, "plot_1", 2).json()["items"] == []
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.StageProgress, (1, "plot_1"))
        assert row.stars == 3 and row.first_clear_claimed and row.clear_count == 1
        assert session.get(m.Currency, (1, "4002")) is None


def test_failed_story_reward_rolls_back_stage_flag_and_diamond(plot_runtime, monkeypatch):
    runtime = plot_runtime
    token = login(runtime)
    from terralocal.server.domain.context import Context

    original = Context.rewards

    def fail_after_reward(ctx, entries, multiplier=1):
        original(ctx, entries, multiplier)
        raise RuntimeError("synthetic story reward fault")

    monkeypatch.setattr(Context, "rewards", fail_after_reward)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        before = runtime.sync(token)
        assert finish(client, token, "plot_1", 1).status_code == 500
        assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.StageProgress, (1, "plot_1")) is None
        assert session.get(m.StoryCompletion, (1, "plot_1")) is None


@pytest.mark.parametrize("change", [{"difficulty": "FOUR_STAR"}, {"apCost": 1}])
def test_distinct_story_stage_rules_fail_before_mutation(plot_runtime, change):
    runtime = plot_runtime
    runtime.data.stages["plot_1"].update(change)
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)
        assert finish(client, token, "plot_1", 1).status_code == 501
        assert runtime.sync(token) == before


def test_sync_repairs_legacy_flags_once_without_waiting_for_client_recommit(plot_runtime):
    runtime = plot_runtime
    token = login(runtime)
    before = runtime.sync(token)
    with runtime.database.transaction() as session:
        session.get(m.PlayerProfile, 1).flags = {"story": {"plot_1": 1}}
    after = runtime.sync(token)
    assert after["revision"] == before["revision"] + 1
    assert after["user"]["dungeon"]["stages"]["plot_1"]["state"] == 3
    assert after["user"]["dungeon"]["stages"]["plot_2"]["state"] == 0
    assert after["user"]["status"]["freeDiamond"] == before["user"]["status"]["freeDiamond"]
    assert runtime.sync(token) == after


def test_concurrent_story_clear_and_backup_restore_preserve_single_award(plot_runtime):
    runtime = plot_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=6) as workers:
            replies = list(workers.map(lambda seq: finish(client, token, "plot_1", seq), range(6)))
        assert all(r.status_code == 200 for r in replies)
        assert sum(len(r.json()["items"]) for r in replies) == 1
        expected = runtime.sync(token)
        backup = BackupService(runtime)
        saved = backup.create()
        assert finish(client, token, "plot_2", 10).status_code == 200
        backup.restore(saved["name"])
        assert runtime.sync(token) == expected
        assert finish(client, token, "plot_1", 11).json()["items"] == []
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.Currency, (1, "4002")).balance == 1
        assert session.get(m.StageProgress, (1, "plot_1")).clear_count == 1


def test_reading_ordinary_battle_intro_never_completes_that_battle(plot_runtime):
    runtime = plot_runtime
    definition = runtime.data.table("story_table")["synthetic_intro"]
    definition["trigger"] = {"type": "BEFORE_BATTLE", "key": "test_2", "useRegex": False}
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        assert finish(client, token, "synthetic_intro", 1).status_code == 200
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.StageProgress, (1, "test_2")) is None
        assert session.get(m.Currency, (1, "4002")) is None
        assert session.query(m.BattleSession).count() == 0
