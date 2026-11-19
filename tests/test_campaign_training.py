"""Authored training rules; lookup defaults never authorize absent mode data."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import MappingProxyType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from test_campaign_battles import (
    begin,
    body,
    campaign_journal,
    login,
)
from test_campaign_battles import (
    campaign_runtime as campaign_runtime,
)
from test_campaign_catalog import campaign_tables
from test_campaign_persistence import NOW
from test_campaign_persistence import camp_runtime as camp_runtime
from test_native_battle_finish import encoded
from test_native_replay import packed, save

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.gamedata.repository import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def training_runtime(tmp_path, request):
    tables = campaign_tables()
    table = tables["campaign_table"]
    table["campaignTrainingStageOpenTimes"][0].update(startTs=NOW - 10, endTs=NOW + 300)
    gains = copy.deepcopy(table["campaigns"]["camp_synthetic"]["dropGains"]["PERMANENT"]["gainLadders"])
    gains[0]["apFailReturn"] = 6  # Explicit full-refund training tier; not ordinary refund5.
    if getattr(request, "param", None) == "resources":
        for gain in gains:
            gain["displayDiamondShdNum"] = 0
    table["campaigns"]["camp_synthetic"]["dropGains"]["TRAINING"]["gainLadders"] = gains
    source = tmp_path / "training-source"
    source.mkdir()
    for name, value in tables.items():
        (source / (name + ".json")).write_text(json.dumps(value), "utf-8")
    manifest = import_data(source, tmp_path / "training-data" / "cache")
    settings = Settings(data_dir=tmp_path / "training-data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", NOW
        accounts.create_account(session, runtime.data, "CampaignDoctor")
        session.add(m.StageProgress(account_id=1, stage_id="test_1", unlocked=True, stars=1))
    yield runtime
    runtime.database.close()


def training_start(client, token, key="training-start"):
    return begin(client, token, {**body(), "stageId": "camp_synthetic"}, key=key)


def finish(client, token, battle_id, key="training-finish", **changes):
    payload = encoded(battle_id, login_time=NOW, state=2, changes={
        "stageId": "camp_synthetic", "interrupt": 1, "giveUp": 0, "percent": 0, **changes})
    return client.post("/campaignV2/battleFinish", headers={"secret": token, "seqnum": key}, json=payload)


@pytest.mark.parametrize("kills", [0, 2])
@pytest.mark.parametrize("interrupted", [0, 1])
def test_training_explicit_refund_and_atomic_retry_restart_restore(training_runtime, kills, interrupted):
    runtime = training_runtime
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=8) as workers:
            started = list(workers.map(lambda _: training_start(client, token), range(8)))
        assert all(r.status_code == 200 and r.json() == started[0].json() for r in started)
        identifier = started[0].json()["battleId"]
        pending = runtime.sync(token)
        assert pending["user"]["status"]["ap"] == before["user"]["status"]["ap"] - 6
        assert apply(before["user"], started[0].json()["playerDataDelta"]) == pending["user"]
        backup = BackupService(runtime).create()
        with ThreadPoolExecutor(max_workers=8) as workers:
            replies = list(workers.map(lambda _: finish(client, token, identifier,
                stageId="camp_synthetic", killCnt=kills, validKillCnt=kills, interrupt=interrupted), range(8)))
        assert all(r.status_code == 200 and r.json() == replies[0].json() for r in replies)
        result = replies[0].json()
        assert result["apFailReturn"] == 6 and result["rewards"] == []
        assert result["currentFeeBefore"] == result["currentFeeAfter"] == 0
        after = runtime.sync(token)
        assert apply(pending["user"], result["playerDataDelta"]) == after["user"]
        assert after["user"]["status"]["ap"] == before["user"]["status"]["ap"]
        assert after["user"]["inventory"] == before["user"]["inventory"]
        assert after["user"]["campaignsV2"]["instances"]["camp_synthetic"] == {
            "maxKills": kills, "rewardStatus": [0, 0]}
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, identifier)
        assert row.state == "ABORTED" and row.sanity_cost == 6
        assert row.native_context["mode"] == "TRAINING" and row.native_context["zero_kill_return"] == 6
        assert session.query(m.CampaignBreakClaim).count() == 0
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == after
        with TestClient(create_game_app(reopened)) as client:
            assert finish(client, token, identifier, key="restarted", stageId="camp_synthetic",
                          killCnt=kills, validKillCnt=kills, interrupt=interrupted).status_code == 200
        settled = reopened.sync(token)
        BackupService(reopened).restore(backup["name"])
        assert reopened.sync(token) == pending
        with TestClient(create_game_app(reopened)) as client:
            assert finish(client, token, identifier, stageId="camp_synthetic",
                          killCnt=kills, validKillCnt=kills, interrupt=interrupted).status_code == 200
        assert reopened.sync(token)["user"] == settled["user"]
    finally:
        reopened.database.close()


def test_training_finish_keeps_saved_mode_after_window_closes(training_runtime):
    runtime = training_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        started = training_start(client, token)
        assert started.status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at = NOW + 400
        result = finish(client, token, started.json()["battleId"], stageId="camp_synthetic")
        assert result.status_code == 200 and result.json()["apFailReturn"] == 6


def test_training_does_not_authorize_unimplemented_breakthrough_or_full_result(training_runtime):
    runtime = training_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        started = training_start(client, token)
        assert started.status_code == 200
        before = runtime.sync(token)
        identifier = started.json()["battleId"]
        for key, changes in (("break", {"killCnt": 3, "validKillCnt": 3}),
                             ("full", {"completeState": 1, "interrupt": 0})):
            result = finish(client, token, identifier, key=key, stageId="camp_synthetic", **changes)
            assert result.status_code == 501
            assert runtime.sync(token) == before


def test_training_refund_cannot_hide_a_separate_drop_rule(training_runtime, monkeypatch):
    runtime = training_runtime
    token = login(runtime)
    before = runtime.sync(token)
    original = runtime.data.table
    table = copy.deepcopy(original("campaign_table"))
    table["campaigns"]["camp_synthetic"]["dropGains"]["TRAINING"]["dropLadders"][0]["dropInfo"][
        "passRewards"] = [{"id": "material", "count": 1, "type": "MATERIAL"}]
    monkeypatch.setattr(runtime.data, "table", lambda name: table if name == "campaign_table" else original(name))
    with TestClient(create_game_app(runtime)) as client:
        result = training_start(client, token)
        assert result.status_code == 503 and result.json()["error"]["code"] == "CAMPAIGN_ABORT_RULE_UNSUPPORTED"
    assert runtime.sync(token) == before


@pytest.mark.parametrize("mode", ["PERMANENT", "TRAINING"])
def test_missing_gain_remains_an_error(campaign_runtime, training_runtime, monkeypatch, mode):
    runtime = training_runtime if mode == "TRAINING" else campaign_runtime
    token = login(runtime)
    before = runtime.sync(token)
    catalog = runtime.data.campaigns
    definition = catalog.stage("camp_synthetic")
    definitions = dict(catalog.definitions)
    definitions["camp_synthetic"] = replace(definition,
        gain_ladders=MappingProxyType({**definition.gain_ladders, mode: ()}))
    monkeypatch.setattr(catalog, "definitions", MappingProxyType(definitions))
    with TestClient(create_game_app(runtime)) as client:
        result = begin(client, token)
        assert result.status_code == 503 and result.json()["error"]["code"] == "CAMPAIGN_ABORT_RULE_MISSING"
    assert runtime.sync(token) == before


@pytest.mark.parametrize("training_runtime", ["resources"], indirect=True)
@pytest.mark.parametrize("rank,interrupted", [(2, 0), (2, 1), (3, 0)])
@pytest.mark.parametrize("kills,returned,gold,exp,favor", [(3, 1, 9, 6, 3), (5, 1, 9, 6, 3),
                                                       (6, 0, 18, 12, 6)])
def test_training_resource_tiers_retry_levelup_trust_and_restore(
        training_runtime, kills, returned, gold, exp, favor, rank, interrupted):
    runtime = training_runtime
    token = login(runtime)
    initial_trust = 25569 if kills == 3 else 7
    with runtime.database.transaction() as session:
        session.get(m.PlayerProfile, 1).exp = 99
        session.get(m.Operator, 1).trust = initial_trust
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        started = training_start(client, token)
        assert started.status_code == 200
        identifier = started.json()["battleId"]
        pending = runtime.sync(token)
        backup = BackupService(runtime).create()
        # Effective kills select the tier; raw kills/rounded percent are independent.
        changes = {"killCnt": 1, "validKillCnt": kills, "percent": 0, "interrupt": interrupted,
                   "completeState": rank}
        with ThreadPoolExecutor(max_workers=8) as workers:
            replies = list(workers.map(lambda _: finish(client, token, identifier, **changes), range(8)))
        assert all(r.status_code == 200 and r.json() == replies[0].json() for r in replies)
        result = replies[0].json()
        assert result["apFailReturn"] == returned
        assert result["rewards"] == [{"id": "4001", "count": gold, "type": "GOLD", "charGet": None}]
        assert result["currentFeeBefore"] == result["currentFeeAfter"] == 0
        after = runtime.sync(token)
        assert apply(pending["user"], result["playerDataDelta"]) == after["user"]
        assert after["user"]["status"]["level"] == 2
        assert after["user"]["status"]["exp"] == exp - 1
        assert after["user"]["status"]["ap"] == pending["user"]["status"]["ap"] + returned + 12
        assert after["user"]["status"]["gold"] == before["user"]["status"]["gold"] + gold
        assert after["user"]["status"]["diamondShard"] == before["user"]["status"]["diamondShard"]
        assert after["user"]["troop"]["chars"]["1"]["favorPoint"] == min(25570, initial_trust + favor)
        assert after["user"]["campaignsV2"]["instances"]["camp_synthetic"] == {
            "maxKills": kills, "rewardStatus": [0, 0]}
        assert finish(client, token, identifier, key="another", **changes).status_code == 200
        settled = runtime.sync(token)
        assert settled["user"] == after["user"]
        assert settled["revision"] == after["revision"] + 1  # New request receipt, no second award.
        conflict = finish(client, token, identifier, key="conflict", **{**changes, "validKillCnt": kills + 1})
        assert conflict.status_code == 409 and runtime.sync(token) == settled
        if rank == 3:
            conflict = finish(client, token, identifier, key="rank-conflict", **{**changes, "completeState": 2})
            assert conflict.status_code == 409 and runtime.sync(token) == settled
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, identifier)
        assert row.state == ("FINISHED" if rank == 3 else "ABORTED")
        assert row.settlement["rewards"] == [{"id": "4001", "count": gold, "type": "GOLD"},
                                              {"id": "5001", "count": exp, "type": "EXP_PLAYER"}]
        assert session.query(m.CampaignBreakClaim).count() == session.query(m.StageReplay).count() == 0
        assert session.get(m.StageProgress, (1, "test_1")).stars == 1
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == settled
        with TestClient(create_game_app(reopened)) as client:
            assert finish(client, token, identifier, key="reopened", **changes).status_code == 200
        assert reopened.sync(token)["user"] == after["user"]
        BackupService(reopened).restore(backup["name"])
        assert reopened.sync(token) == pending
        with TestClient(create_game_app(reopened)) as client:
            assert finish(client, token, identifier, **changes).status_code == 200
        assert reopened.sync(token)["user"] == after["user"]
    finally:
        reopened.database.close()


@pytest.mark.parametrize("training_runtime", ["resources"], indirect=True)
@pytest.mark.parametrize("rank", [2, 3])
def test_training_resources_rollback_before_commit(training_runtime, rank):
    runtime = training_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        started = training_start(client, token)
        assert started.status_code == 200
        pending = runtime.sync(token)
        def fail_commit(connection):
            raise RuntimeError("authored transaction failure")
        event.listen(runtime.database.engine, "commit", fail_commit)
        try:
            result = finish(client, token, started.json()["battleId"], completeState=rank, interrupt=0,
                            killCnt=3, validKillCnt=3)
            assert result.status_code == 500
        finally:
            event.remove(runtime.database.engine, "commit", fail_commit)
        assert runtime.sync(token) == pending
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.BattleSession, started.json()["battleId"]).state == "STARTED"
        assert finish(client, token, started.json()["battleId"], completeState=rank, interrupt=0,
                      killCnt=3, validKillCnt=3).status_code == 200


@pytest.mark.parametrize("training_runtime", ["resources"], indirect=True)
@pytest.mark.parametrize("rank", [2, 3])
def test_training_natural_result_keeps_journal_without_proxy(training_runtime, rank):
    runtime = training_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        started = training_start(client, token)
        identifier = started.json()["battleId"]
        assert finish(client, token, identifier, completeState=rank, interrupt=0, killCnt=3, validKillCnt=3).status_code == 200
        settled = runtime.sync(token)["user"]
        wire = packed(campaign_journal())
        assert save(client, token, identifier, wire).status_code == 200
        assert save(client, token, identifier, wire, key="repeat-natural-journal").status_code == 200
        assert runtime.sync(token)["user"] == settled
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, identifier)
        assert row.native_context["outcome"]["interrupt"] is False
        assert row.state == ("FINISHED" if rank == 3 else "ABORTED")
        assert row.native_context["campaign_journal"]["kind"] == (
            "campaign-finish-journal-v1" if rank == 3 else "campaign-abort-journal-v1")
        assert row.native_context["campaign_journal"]["battleReplay"] == wire
        assert session.query(m.StageReplay).count() == 0


@pytest.mark.parametrize("training_runtime", ["resources"], indirect=True)
@pytest.mark.parametrize("changes", [{"interrupt": 1}, {"giveUp": 1}])
def test_training_complete_rejects_interrupt_or_giveup_without_awards(training_runtime, changes):
    runtime = training_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        started = training_start(client, token)
        pending = runtime.sync(token)
        result = finish(client, token, started.json()["battleId"], completeState=3,
                        killCnt=6, validKillCnt=6, **{"interrupt": 0, **changes})
        assert result.status_code == 400 and result.json()["error"]["code"] == "INVALID_NATIVE_FINISH"
        assert runtime.sync(token) == pending
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, started.json()["battleId"]).state == "STARTED"


def test_complete_is_not_enabled_for_other_campaign_modes(campaign_runtime):
    token = login(campaign_runtime)
    with TestClient(create_game_app(campaign_runtime)) as client:
        started = begin(client, token)
        pending = campaign_runtime.sync(token)
        result = finish(client, token, started.json()["battleId"], completeState=3, interrupt=0)
        assert result.status_code == 501 and campaign_runtime.sync(token) == pending


@pytest.mark.parametrize("training_runtime", ["resources"], indirect=True)
def test_completed_training_is_not_recovered_after_new_login(training_runtime):
    runtime = training_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.get(m.SanityState, 1).current = 30
    with TestClient(create_game_app(runtime)) as client:
        started = training_start(client, token)
        identifier = started.json()["battleId"]
        assert finish(client, token, identifier, completeState=3, interrupt=0,
                      killCnt=6, validKillCnt=6).status_code == 200
        settled = runtime.sync(token)["user"]
        assert settled["status"]["ap"] == 24
        next_token = login(runtime)
        assert training_start(client, next_token, key="next-training").status_code == 200
        after = runtime.sync(next_token)["user"]
        assert after["status"]["ap"] == 18
        for key in ("exp", "gold", "diamondShard"):
            assert after["status"][key] == settled["status"][key]
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, identifier)
        assert row.state == "FINISHED" and "recovery" not in row.native_context
