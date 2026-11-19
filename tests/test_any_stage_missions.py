"""Candidate-stage tasks: clear-state proof, chapter availability and atomic claims."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from test_native_battle_finish import complete, encoded
from test_native_battle_start import begin, body, login
from test_native_mission_claim import claim
from test_story_completion import finish

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.gamedata import import_data
from terralocal.server.gamedata.repository import canonical
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def candidate_runtime(tmp_path):
    tables = miniature()
    stages = tables["stage_table"]["stages"]
    for stage in stages.values():
        stage.update(stageType="MAIN", difficulty="NORMAL", diffGroup="NONE", zoneId="chapter_1",
                     apProtectTimes=0, isPredefined=False, isStagePatch=False)
    stages["plot"] = {**deepcopy(stages["test_1"]), "stageId": "plot", "zoneId": "chapter_2",
                      "isStoryOnly": True, "levelId": None, "apCost": 0, "apFailReturn": 0,
                      "goldGain": 0, "expGain": 0, "passFavor": 0, "completeFavor": 0,
                      "stageDropInfo": {}, "unlockCondition": []}
    tables["story_table"]["plot"] = {
        **deepcopy(tables["story_table"]["synthetic_intro"]), "id": "plot", "completedRewards": [],
        "trigger": {"key": "plot", "type": "BEFORE_BATTLE", "useRegex": False}}
    tables["item_table"]["items"]["plot_reward"] = {
        "itemId": "plot_reward", "name": "Synthetic plot item", "itemType": "PLOT_ITEM"}
    for key, kind in (("4004", "HGG_SHD"), ("4005", "LGG_SHD"), ("reward_token", "MATERIAL")):
        tables["item_table"]["items"][key] = {"itemId": key, "name": key, "itemType": kind}
    tables["character_table"]["char_reward"] = {
        **deepcopy(tables["character_table"]["char_synthetic"]), "rarity": "TIER_3",
        "potentialItemId": "reward_token"}
    tables["charword_table"]["voiceLangDict"]["char_reward"] = deepcopy(
        tables["charword_table"]["voiceLangDict"]["char_synthetic"])
    tables["charword_table"]["charDefaultTypeDict"]["char_reward"] = "JP"
    tables["skin_table"] = {"charSkins": {
        "char_synthetic#1": {"skinId": "char_synthetic#1", "charId": "char_synthetic", "isBuySkin": False},
        "char_reward#1": {"skinId": "char_reward#1", "charId": "char_reward", "isBuySkin": False},
        "char_synthetic@reward#1": {
            "skinId": "char_synthetic@reward#1", "charId": "char_synthetic", "isBuySkin": True}},
        "buildinEvolveMap": {key: {"0": f"{key}#1"} for key in ("char_synthetic", "char_reward")},
        "buildinPatchMap": {}}
    for row in tables["skin_table"]["charSkins"].values():
        row["displaySkin"] = {"skinName": "Synthetic costume"}
    tables["building_data"] = {"customData": {"furnitures": {
        "furniture_reward": {"name": "Synthetic furniture", "rarity": 1}}}}
    definitions, groups = {}, {}
    for key, category, candidates, state in [
            ("any_pass", "MAIN", "test_1^test_2", "2"),
            ("any_complete", "GUIDE", "test_1^test_2", "3"),
            ("retro_plot", "RETRO", "plot", "2")]:
        definitions[key] = {"id": key, "type": category, "template": "CompleteAnyStage", "templateType": "0",
                            "param": ["0", candidates, state], "missionGroup": key,
                            "periodicalPoint": 0, "countEndTs": -1, "unlockCondition": None,
                            "unlockParam": None, "preMissionIds": None,
                            "rewards": [{"id": "plot_reward", "type": "PLOT_ITEM", "count": 1}]}
        groups[key] = {"id": key, "type": category, "missionIds": [key], "preMissionGroup": None,
                       "rewards": [], "period": None, "startTs": -1, "endTs": -1}
    definitions["any_complete"]["rewards"] += [
        {"id": "char_synthetic@reward#1", "type": "CHAR_SKIN", "count": 1},
        {"id": "furniture_reward", "type": "FURN", "count": 1},
        {"id": "char_reward", "type": "CHAR", "count": 1}]
    tables["mission_table"] = {"missions": definitions, "missionGroups": groups}
    tables["zone_table"] = {"zones": {}, "mainlineAdditionInfo": {
        "chapter_1": {"endStageId": "test_1", "preposedZoneId": None, "zoneOpenTime": -1},
        "chapter_2": {"endStageId": "plot", "preposedZoneId": "chapter_1", "zoneOpenTime": -1}}}
    source = tmp_path / "source"
    source.mkdir()
    for key, value in tables.items():
        (source / f"{key}.json").write_bytes(canonical(value))
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
        session.get(m.SanityState, 1).current = 100
    yield runtime
    runtime.database.close()


def test_battle_and_story_update_candidate_tasks_and_claim_plot_item_once(candidate_runtime):
    runtime = candidate_runtime
    token = login(runtime)
    before = runtime.sync(token)
    assert before["user"]["mission"]["missions"]["RETRO"] == {}
    with TestClient(create_game_app(runtime)) as client:
        battle_id = begin(client, token, body()).json()["battleId"]
        before_finish = runtime.sync(token)["user"]
        result = complete(client, token, encoded(battle_id, state=2)).json()
        state = runtime.sync(token)["user"]
        assert apply(before_finish, result["playerDataDelta"]) == state
        mission = state["mission"]["missions"]
        assert mission["MAIN"]["any_pass"]["progress"] == [{"target": 1, "value": 1, "compare": ">="}]
        assert mission["GUIDE"]["any_complete"]["progress"][0]["value"] == 0
        assert mission["RETRO"]["retro_plot"]["progress"][0]["value"] == 0
        assert finish(client, token, "plot", "plot-finish").status_code == 200
        before_claim = runtime.sync(token)["user"]
        with ThreadPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(lambda i: claim(client, token, "retro_plot", f"claim-{i}"), range(4)))
        assert all(r.status_code == 200 for r in replies)
        changed = [r.json() for r in replies if r.json()["playerDataDelta"]["modified"]]
        assert len(changed) == 1
        after = runtime.sync(token)["user"]
        assert apply(before_claim, changed[0]["playerDataDelta"]) == after
        assert after["inventory"]["plot_reward"] == 1
        assert after["mission"]["missionGroups"]["retro_plot"] == 1
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.MissionProgress, (1, "any_pass", "permanent")).progress == 1
        assert session.query(m.MissionProgress).filter_by(account_id=2).count() == 0
    expected = runtime.sync(token)
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == expected
    finally:
        restarted.database.close()


def test_other_candidate_qualifies_but_pass_does_not_count_as_complete(candidate_runtime):
    runtime = candidate_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_2", stars=2, clear_count=1))
    state = runtime.sync(token)["user"]["mission"]["missions"]
    assert state["MAIN"]["any_pass"]["progress"][0]["value"] == 1
    assert state["GUIDE"]["any_complete"]["progress"][0]["value"] == 0
    with runtime.database.transaction() as session:
        session.get(m.StageProgress, (1, "test_2")).stars = 3
    assert runtime.sync(token)["user"]["mission"]["missions"]["GUIDE"]["any_complete"]["progress"][0]["value"] == 1


def test_fake_progress_cannot_claim_without_saved_stage_condition(candidate_runtime):
    runtime = candidate_runtime
    token = login(runtime)
    runtime.sync(token)
    with runtime.database.transaction() as session:
        session.get(m.MissionProgress, (1, "any_complete", "permanent")).progress = 100
    with TestClient(create_game_app(runtime)) as client:
        assert claim(client, token, "any_complete").json()["error"]["code"] == "MISSION_NOT_COMPLETE"
    assert runtime.sync(token)["user"]["mission"]["missions"]["GUIDE"]["any_complete"]["progress"][0]["value"] == 0


def test_future_chapter_and_unsupported_group_rewards_do_not_assign(candidate_runtime):
    runtime = candidate_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=3))
    chapter = runtime.data.table("zone_table")["mainlineAdditionInfo"]["chapter_2"]
    chapter["zoneOpenTime"] = 1_800_000_001
    assert runtime.sync(token)["user"]["mission"]["missions"]["RETRO"] == {}
    chapter["zoneOpenTime"] = -1
    runtime.data.table("mission_table")["missionGroups"]["retro_plot"]["rewards"] = [
        {"id": "material", "type": "MATERIAL", "count": 1}]
    assert runtime.sync(token)["user"]["mission"]["missions"]["RETRO"] == {}


def test_claim_reward_failure_rolls_back_new_plot_item_and_claim_flag(candidate_runtime, monkeypatch):
    runtime = candidate_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=3))
    runtime.sync(token)
    from terralocal.server.domain.context import Context

    original = Context.rewards

    def fail(ctx, entries, multiplier=1):
        original(ctx, entries, multiplier)
        raise RuntimeError("synthetic plot claim failure")

    monkeypatch.setattr(Context, "rewards", fail)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        before = runtime.sync(token)
        assert claim(client, token, "any_pass").status_code == 500
        assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert not session.get(m.MissionProgress, (1, "any_pass", "permanent")).claimed
        assert session.get(m.InventoryItem, (1, "plot_reward")) is None


def test_candidate_mission_grants_typed_skin_furniture_and_operator_once(candidate_runtime):
    runtime = candidate_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_2", stars=3))
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        reply = claim(client, token, "any_complete", "typed-reward")
        assert reply.status_code == 200, reply.text
        assert apply(before, reply.json()["playerDataDelta"]) == runtime.sync(token)["user"]
        assert claim(client, token, "any_complete", "typed-reward-again").status_code == 200
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.OwnedSkin, (1, "char_synthetic@reward#1")) is not None
        assert session.get(m.OwnedFurniture, (1, "furniture_reward")).count == 1
        assert session.get(m.OperatorAcquisition, (1, "char_reward", "STANDARD")).count == 1
        assert session.get(m.InventoryItem, (1, "char_synthetic@reward#1")) is None
        assert session.get(m.InventoryItem, (1, "furniture_reward")) is None


def test_stage_unlock_requirement_is_separate_from_candidate_clear(candidate_runtime):
    runtime = candidate_runtime
    definition = runtime.data.table("mission_table")["missions"]["any_complete"]
    definition.update(unlockCondition="StageCondition", unlockParam=["2", "test_1"])
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_2", stars=3))
    assert runtime.sync(token)["user"]["mission"]["missions"]["GUIDE"] == {}
    with runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=2))
    state = runtime.sync(token)["user"]["mission"]["missions"]["GUIDE"]
    assert state["any_complete"]["progress"][0]["value"] == 1
    with TestClient(create_game_app(runtime)) as client:
        assert claim(client, token, "any_complete").status_code == 200


def test_main_successor_uses_existing_candidate_clear_in_claim_delta(candidate_runtime):
    runtime = candidate_runtime
    table = runtime.data.table("mission_table")
    table["missions"]["any_complete"]["type"] = "MAIN"
    table["missionGroups"]["any_complete"].update(type="MAIN", preMissionGroup="any_pass")
    with runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_2", stars=3))
    token = login(runtime)
    before = runtime.sync(token)["user"]
    assert "any_complete" not in before["mission"]["missions"]["MAIN"]
    with TestClient(create_game_app(runtime)) as client:
        reply = claim(client, token, "any_pass")
        assert reply.status_code == 200
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        assert after["mission"]["missions"]["MAIN"]["any_complete"]["progress"][0]["value"] == 1
