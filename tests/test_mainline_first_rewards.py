"""Ordinary-stage operator rewards share the existing acquisition transaction."""

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from test_drops import activate
from test_native_battle_finish import complete, encoded
from test_native_battle_start import begin, body, login

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.domain.context import Context
from terralocal.server.gamedata import import_data
from terralocal.server.gamedata.penguin import compile_penguin
from terralocal.server.gamedata.repository import canonical
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def reward_runtime(tmp_path):
    tables = miniature()
    for item_id, item_type in (("4004", "HGG_SHD"), ("4005", "LGG_SHD")):
        tables["item_table"]["items"][item_id] = {"itemId": item_id, "name": item_id, "itemType": item_type}
    tables["character_table"]["char_tier_3"] = {
        **tables["character_table"]["char_synthetic"], "rarity": "TIER_3"}
    tables["charword_table"]["voiceLangDict"]["char_tier_3"] = {
        "dict": {"JP": {"voiceLangType": "JP"}}}
    tables["charword_table"]["charDefaultTypeDict"]["char_tier_3"] = "JP"
    for stage_id, stage in tables["stage_table"]["stages"].items():
        stage.update(stageType="MAIN", difficulty="NORMAL", diffGroup="NONE",
                     isPredefined=False, appearanceStyle="SUB" if stage_id == "test_2" else "MAIN_NORMAL",
                     stageDropInfo={
                         "firstPassRewards": None, "firstCompleteRewards": None,
                         "displayRewards": [{"id": "char_tier_3", "dropType": "ONCE"}],
                         "displayDetailRewards": [{"id": "material", "dropType": "NORMAL"}]})
    source = tmp_path / "source"
    source.mkdir()
    for name, table in tables.items():
        (source / f"{name}.json").write_bytes(canonical(table))
    manifest = import_data(source, tmp_path / "data/cache")
    runtime = Runtime(Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False))
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        session.get(m.SanityState, 1).current = 100
    yield runtime
    runtime.database.close()


def prepare(runtime):
    patterns, stages = [], []
    for stage_id, stage in runtime.data.stages.items():
        patterns.append({"stageId": stage_id, "start": 1, "end": None, "times": 1,
                         "quantity": 1, "pattern": {"drops": [{"itemId": "material", "quantity": 1}]}})
        stages.append({"stageId": stage_id, "stageType": "SUB" if stage_id == "test_2" else "MAIN",
                       "apCost": stage["apCost"],
                       "existence": {"CN": {"exist": True}},
                       "dropInfos": [{"itemId": "material", "bounds": {"lower": 1, "upper": 1}}]})
    folder = runtime.settings.data_dir / "synthetic-source"
    folder.mkdir()
    paths = folder / "patterns.json", folder / "stages.json"
    paths[0].write_bytes(canonical({"pattern_matrix": patterns}))
    paths[1].write_bytes(canonical(stages))
    value, report = compile_penguin(*paths, runtime.data)
    activate(runtime, value)
    return paths, report


@pytest.mark.parametrize("owned", [False, True])
def test_ordinary_first_pass_operator_once_delta_retry_and_reopen(reward_runtime, owned):
    runtime = reward_runtime
    _, report = prepare(runtime)
    assert report["supported_stages"] == 2 and report["excluded_stages"] == {}
    with runtime.database.transaction() as session:
        if owned:
            Context(session, runtime.data, 1).acquire_operator("char_tier_3")
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        started = begin(client, token, body(), "ordinary-start")
        assert started.status_code == 200
        battle_id = started.json()["battleId"]
        before = runtime.sync(token)["user"]
        payload = encoded(battle_id, state=2)
        reply = complete(client, token, payload, "ordinary-finish")
        assert reply.status_code == 200
        result = reply.json()
        char = result["firstRewards"][0]
        assert char["id"] == "char_tier_3" and char["charGet"]["isNew"] is not owned
        assert char["charGet"]["itemGet"][-1]["id"] == ("4005" if owned else "4004")
        assert apply(before, result["playerDataDelta"]) == runtime.sync(token)["user"]
        assert complete(client, token, payload, "ordinary-retry").json()["firstRewards"] == [char]
        again = begin(client, token, body(), "ordinary-second-start").json()["battleId"]
        second = complete(client, token, encoded(again, state=3), "ordinary-second-finish").json()
        assert [r["id"] for r in second["firstRewards"]] == ["4002"]
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.OperatorAcquisition, (1, "char_tier_3", "STANDARD")).count == 1 + owned
        assert session.get(m.StageProgress, (1, "test_1")).clear_count == 2
    # Reopen checks the saved catalog and receipt, without rewriting GameData.
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        with reopened.database.transaction(write=False) as session:
            assert session.get(m.OperatorAcquisition, (1, "char_tier_3", "STANDARD")).count == 1 + owned
            assert session.get(m.BattleSession, battle_id).settlement["firstRewards"][0] == char
    finally:
        reopened.database.close()


def test_unobtainable_operator_excludes_stage_before_catalog_activation(reward_runtime):
    runtime = reward_runtime
    paths, _ = prepare(runtime)
    runtime.data.characters["char_tier_3"]["isNotObtainable"] = True
    with pytest.raises(ValueError, match="没有与 GameData 匹配"):
        compile_penguin(*paths, runtime.data)


@pytest.mark.parametrize("change", [{"stageType": "ACTIVITY"}, {"apCost": 999}])
def test_side_stage_mapping_still_requires_matching_class_and_cost(reward_runtime, change):
    import json

    runtime = reward_runtime
    paths, _ = prepare(runtime)
    rows = json.loads(paths[1].read_bytes())
    rows[1].update(change)
    paths[1].write_bytes(canonical(rows))
    value, report = compile_penguin(*paths, runtime.data)
    assert set(value.stages) == {"test_1"}
    assert set(report["excluded_stages"]) == {"test_2"}


def test_side_stage_uses_same_native_start_finish_and_first_reward(reward_runtime):
    runtime = reward_runtime
    prepare(runtime)
    with runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=3, clear_count=1))
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        request = {**body(), "stageId": "test_2"}
        start = begin(client, token, request)
        assert start.status_code == 200
        result = complete(client, token, encoded(start.json()["battleId"], state=3,
                                                changes={"stageId": "test_2"})).json()
        assert result["firstRewards"][0]["charGet"]["charId"] == "char_tier_3"
        assert runtime.sync(token)["user"]["dungeon"]["stages"]["test_2"]["state"] == 3


def test_operator_reward_failure_rolls_back_entire_ordinary_settlement(reward_runtime, monkeypatch):
    runtime = reward_runtime
    prepare(runtime)
    token = login(runtime)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        battle_id = begin(client, token, body()).json()["battleId"]
        before = runtime.sync(token)
        original = Context.rewards

        def fail_after_award(ctx, rewards, multiplier=1):
            result = original(ctx, rewards, multiplier)
            if any(r["id"] == "char_tier_3" for r in rewards):
                raise RuntimeError("synthetic post-acquisition failure")
            return result

        monkeypatch.setattr(Context, "rewards", fail_after_award)
        assert complete(client, token, encoded(battle_id, state=3)).status_code == 500
        assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, battle_id).state == "STARTED"
        assert session.get(m.OperatorAcquisition, (1, "char_tier_3", "STANDARD")) is None
