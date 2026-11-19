"""Campaign AP/session transactions with authored tables and encrypted facts."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from test_campaign_persistence import NOW
from test_campaign_persistence import camp_runtime as camp_runtime
from test_native_battle_finish import encoded
from test_native_replay import journal, packed, save

from terralocal.server.domain import accounts, battle
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def campaign_runtime(camp_runtime):
    with camp_runtime.database.transaction() as session:
        row = session.get(m.StageProgress, (1, "test_1"))
        if row is None:
            row = m.StageProgress(account_id=1, stage_id="test_1", unlocked=True)
            session.add(row)
        row.stars = 1  # Explicit synthetic prerequisite, not a natural clear.
    return camp_runtime


def login(runtime, name="CampaignDoctor"):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name=name)["secret"]


def body():
    return {"usePracticeTicket": 0, "stageId": "camp_synthetic", "squad": {
        "squadId": "0", "name": "Synthetic", "slots": [
            {"charInstId": 1, "skillIndex": 0, "currentEquip": None}]},
        "assistFriend": None, "isReplay": 0, "startTs": 1}


def begin(client, token, payload=None, key="start"):
    return client.post("/campaignV2/battleStart", headers={"secret": token, "seqnum": key}, json=payload or body())


def abort(battle_id, **changes):
    trace_changes = changes.pop("trace_changes", None)
    iv = changes.pop("iv", b"synthetic-IV-001")
    result = encoded(battle_id, state=2, iv=iv, trace_changes=trace_changes, changes={"stageId": "camp_synthetic", "interrupt": 1,
        "giveUp": 0, "percent": 0, **changes})
    if trace_changes and "completeTime" in trace_changes:
        result["battleData"]["completeTime"] = trace_changes["completeTime"]
    return result


def finish(client, token, battle_id, key="finish", **changes):
    return client.post("/campaignV2/battleFinish", headers={"secret": token, "seqnum": key},
                       json=abort(battle_id, **changes))


def test_concurrent_charge_abort_refund_delta_and_ordinary_progress_isolation(campaign_runtime):
    runtime = campaign_runtime
    token = login(runtime)
    before = runtime.sync(token)
    with runtime.database.transaction(write=False) as session:
        ordinary = [(r.stage_id, r.stars, r.start_count, r.clear_count) for r in session.query(m.StageProgress)]
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=8) as workers:
            replies = list(workers.map(lambda _: begin(client, token), range(8)))
        assert all(r.status_code == 200 and r.json() == replies[0].json() for r in replies)
        started = replies[0].json()
        after_start = runtime.sync(token)
        assert after_start["user"]["status"]["ap"] == before["user"]["status"]["ap"] - 6
        assert apply(before["user"], started["playerDataDelta"]) == after_start["user"]
        assert begin(client, token, key="new-sequence").status_code == 409
        with ThreadPoolExecutor(max_workers=8) as workers:
            replies = list(workers.map(lambda _: finish(client, token, started["battleId"]), range(8)))
        assert all(r.status_code == 200 and r.json() == replies[0].json() for r in replies)
        result = replies[0].json()
        # Synthetic campaign refund2 differs from ordinary Stage.apFailReturn5.
        assert result["apFailReturn"] == 2 and result["rewards"] == []
        assert result["currentFeeBefore"] == result["currentFeeAfter"] == 0
        after = runtime.sync(token)
        assert after["user"]["status"]["ap"] == before["user"]["status"]["ap"] - 4
        assert apply(after_start["user"], result["playerDataDelta"]) == after["user"]
        assert after["user"]["campaignsV2"] == before["user"]["campaignsV2"]
        assert finish(client, token, started["battleId"], key="another-iv", iv=b"synthetic-IV-002").status_code == 200
        assert runtime.sync(token)["user"] == after["user"]
        assert finish(client, token, started["battleId"], key="changed", trace_changes={"completeTime": 21}).status_code == 409
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, started["battleId"])
        assert row.state == "ABORTED" and row.sanity_cost == 6 and row.started_at == NOW
        assert row.squad_snapshot[0]["charInstId"] == 1
        assert "stats" not in row.native_context["outcome"]
        assert ordinary == [(r.stage_id, r.stars, r.start_count, r.clear_count) for r in session.query(m.StageProgress)]
        assert session.query(m.BattleSession).count() == 1


def test_pending_and_finished_campaign_survive_restart_backup_and_new_login(campaign_runtime):
    runtime = campaign_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
    started = runtime.sync(token)
    path = BackupService(runtime).create()
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == started
        with TestClient(create_game_app(restarted)) as client:
            result = finish(client, token, identifier)
            assert result.status_code == 200
            settled = restarted.sync(token)
            again = login(restarted)
            assert finish(client, again, identifier, key="new-login").status_code == 200
            assert restarted.sync(again)["user"] == settled["user"]
        BackupService(restarted).restore(path["name"])
        assert restarted.sync(token) == started
        with TestClient(create_game_app(restarted)) as client:
            assert finish(client, token, identifier).status_code == 200
        assert restarted.sync(token)["user"] == settled["user"]
    finally:
        restarted.database.close()


@pytest.mark.parametrize("change,status", [
    ({"usePracticeTicket": 1}, 501), ({"isReplay": 1}, 501), ({"assistFriend": {}}, 501),
    ({"unknown": 1}, 422), ({"usePracticeTicket": "1"}, 422), ({"stageId": "test_1"}, 400),
    ({"stageId": "camp_rotate"}, 400),
])
def test_unsupported_or_closed_start_does_not_charge(campaign_runtime, change, status):
    runtime = campaign_runtime
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert begin(client, token, {**body(), **change}).status_code == status
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).count() == 0


@pytest.mark.parametrize("change", [{"validKillCnt": 3}, {"validKillCnt": 6},
                                   {"interrupt": 0}, {"giveUp": 1}, {"completeState": 1}])
def test_unverified_result_keeps_pending_session_without_empty_success(campaign_runtime, change):
    runtime = campaign_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        before = runtime.sync(token)
        response = finish(client, token, identifier, **change)
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "CAMPAIGN_SETTLEMENT_UNIMPLEMENTED"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, identifier).state == "STARTED"


@pytest.mark.parametrize("raw,valid,percent", [(17, 2, 1), (1, 2, 50), (0, 0, 50)])
def test_abort_selects_valid_kill_tier_and_persists_progress_without_reward(campaign_runtime, raw, valid, percent):
    runtime = campaign_runtime
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        started = runtime.sync(token)
        changes = {"killCnt": raw, "validKillCnt": valid, "percent": percent}
        with ThreadPoolExecutor(max_workers=8) as workers:
            replies = list(workers.map(lambda _: finish(client, token, identifier, **changes), range(8)))
        assert all(r.status_code == 200 and r.json() == replies[0].json() for r in replies)
        result = replies[0].json()
        assert result["apFailReturn"] == 2 and result["rewards"] == []
        after = runtime.sync(token)
        assert apply(started["user"], result["playerDataDelta"]) == after["user"]
        assert after["user"]["status"]["ap"] == before["user"]["status"]["ap"] - 4
        stage = after["user"]["campaignsV2"]["instances"]["camp_synthetic"]
        assert stage["maxKills"] == valid and stage["rewardStatus"] == [0, 0]
        assert after["user"]["campaignsV2"]["campaignCurrentFee"] == 0
        assert after["user"]["campaignsV2"]["sweepMaxKills"] == {}
        assert after["user"]["inventory"] == before["user"]["inventory"]
        assert finish(client, token, identifier, key="retry", **changes).status_code == 200
        assert runtime.sync(token)["user"] == after["user"]
        assert finish(client, token, identifier, key="conflict", **{**changes, "percent": percent + 1}).status_code == 409
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, identifier)
        assert row.native_context["outcome"]["killCnt"] == raw
        assert row.native_context["outcome"]["validKillCnt"] == valid
        assert row.state == "ABORTED"
        assert session.query(m.CampaignBreakClaim).count() == 0
    settled = runtime.sync(token)
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == settled
        with TestClient(create_game_app(restarted)) as client:
            lower = begin(client, token, key="lower-start").json()["battleId"]
            assert finish(client, token, lower, key="lower-finish").status_code == 200
        assert restarted.sync(token)["user"]["campaignsV2"]["instances"]["camp_synthetic"]["maxKills"] == valid
    finally:
        restarted.database.close()


def test_zero_gain_does_not_hide_a_separate_item_drop_threshold(campaign_runtime, monkeypatch):
    import copy

    runtime = campaign_runtime
    token = login(runtime)
    original = runtime.data.table
    table = copy.deepcopy(original("campaign_table"))
    table["campaigns"]["camp_synthetic"]["dropGains"]["PERMANENT"]["dropLadders"].append({
        "killCnt": 1, "dropInfo": {"firstPassRewards": None,
            "passRewards": [{"id": "material", "count": 1, "type": "MATERIAL"}], "displayDetailRewards": None}})
    monkeypatch.setattr(runtime.data, "table", lambda name: table if name == "campaign_table" else original(name))
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        before = runtime.sync(token)
        response = finish(client, token, identifier, killCnt=2, validKillCnt=2, percent=1)
        assert response.status_code == 501
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.BattleSession, identifier).state == "STARTED"


def test_account_stage_signature_and_rule_changes_are_rejected_atomically(campaign_runtime):
    runtime = campaign_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "OtherCampaign")
    other = login(runtime, "OtherCampaign")
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        before = runtime.sync(token)
        assert finish(client, other, identifier).status_code == 404
        assert finish(client, token, identifier, stageId="camp_rotate").status_code == 409
        with runtime.database.transaction() as session:
            row = session.get(m.BattleSession, identifier)
            row.native_context = {**row.native_context, "rule_hash": "0" * 64}
        assert finish(client, token, identifier).status_code == 503
    assert runtime.sync(token) == before


def test_new_game_session_recovery_refunds_only_once_and_interoperates_with_ordinary(campaign_runtime):
    runtime = campaign_runtime
    with runtime.database.transaction() as session:
        session.get(m.SanityState, 1).current = 30
    token = login(runtime)
    before = runtime.sync(token)["user"]["status"]["ap"]
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        again = login(runtime)
        assert begin(client, token, key="stale").status_code == 401
        next_id = begin(client, again, key="fresh").json()["battleId"]
        assert next_id != identifier
    assert runtime.sync(again)["user"]["status"]["ap"] == before - 6 + 2 - 6
    latest = login(runtime)

    def ordinary(ctx):
        battle._recover_previous_session(ctx, runtime.drop_rules)
        return battle.start(ctx, "test_1", "0")

    runtime.mutate(latest, None, "ordinary", "test-ordinary-recovery", {}, ordinary)
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, identifier).state == "ABORTED"
        assert session.get(m.BattleSession, next_id).state == "ABORTED"
        assert session.get(m.BattleSession, next_id).native_context["recovery"]["policy"]
        assert session.query(m.BattleSession).filter_by(state="STARTED").count() == 1


def test_finish_uses_start_mode_after_calendar_switch(campaign_runtime):
    runtime = campaign_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at = NOW + 200
        assert runtime.sync(token)["user"]["campaignsV2"]["open"]["tGroup"] == "training_synthetic"
        result = finish(client, token, identifier)
        assert result.status_code == 200 and result.json()["apFailReturn"] == 2
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, identifier).native_context["mode"] == "PERMANENT"


def test_overlapping_lists_keep_native_permanent_priority(campaign_runtime, monkeypatch):
    runtime = campaign_runtime
    token = login(runtime)
    catalog = runtime.data.campaigns
    opening = replace(catalog.opening(NOW), rotate="camp_synthetic",
                      training=("camp_synthetic",), training_all_group="all_synthetic")
    monkeypatch.setattr(catalog, "opening", lambda _now: opening)
    with TestClient(create_game_app(runtime)) as client:
        response = begin(client, token)
        assert response.status_code == 200
        identifier = response.json()["battleId"]
        # Rotation prerequisite is deliberately absent; permanent wins first.
        assert finish(client, token, identifier).json()["apFailReturn"] == 2
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, identifier).native_context["mode"] == "PERMANENT"


@pytest.mark.parametrize("key,value", [("mode", []), ("login_time", True), ("zero_kill_return", -1),
                                      ("session_binding", "invalid"), ("codec_version", "ordinary")])
def test_corrupt_session_context_fails_without_refund_or_server_error(campaign_runtime, key, value):
    runtime = campaign_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        with runtime.database.transaction() as session:
            row = session.get(m.BattleSession, identifier)
            row.native_context = {**row.native_context, key: value}
        before = runtime.sync(token)
        result = finish(client, token, identifier)
        assert result.status_code == 503 and result.json()["error"]["code"] == "CAMPAIGN_CONTEXT_UNAVAILABLE"
    assert runtime.sync(token) == before


@pytest.mark.parametrize("kills", [0, 2])
def test_database_failure_rolls_back_refund_session_revision_and_receipt(campaign_runtime, kills):
    runtime = campaign_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        before = runtime.sync(token)

        def fail_settlement(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.startswith("UPDATE battle_sessions"):
                raise RuntimeError("synthetic settlement write failure")

        event.listen(runtime.database.engine, "before_cursor_execute", fail_settlement)
        try:
            with pytest.raises(RuntimeError, match="synthetic settlement write failure"):
                finish(client, token, identifier, killCnt=kills, validKillCnt=kills, percent=1)
        finally:
            event.remove(runtime.database.engine, "before_cursor_execute", fail_settlement)
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.BattleSession, identifier).state == "STARTED"
            assert session.query(m.Receipt).count() == 1
        assert finish(client, token, identifier, killCnt=kills, validKillCnt=kills, percent=1).status_code == 200


def campaign_journal():
    data = journal()
    data["campaignOnlyVersion"] = 1
    data["journal"]["metadata"].update(stageId="camp_synthetic", gameResult=2)
    return data


@pytest.mark.parametrize("kills", [0, 2])
def test_aborted_campaign_journal_is_saved_once_restarted_and_never_advertised_as_proxy(campaign_runtime, kills):
    runtime = campaign_runtime
    token = login(runtime)
    wire = packed(campaign_journal())
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        assert finish(client, token, identifier, killCnt=kills, validKillCnt=kills, percent=1).status_code == 200
        before = runtime.sync(token)
        with ThreadPoolExecutor(max_workers=8) as workers:
            replies = list(workers.map(lambda _: save(client, token, identifier, wire), range(8)))
        assert all(r.status_code == 200 and r.json() == replies[0].json() for r in replies)
        assert runtime.sync(token)["user"] == before["user"]
    with runtime.database.transaction(write=False) as session:
        stored = session.get(m.BattleSession, identifier).native_context["campaign_journal"]
        assert stored["battleReplay"] == wire and stored["kind"] == "campaign-abort-journal-v1"
        assert session.query(m.StageReplay).count() == 0
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(restarted)) as client:
            assert save(client, token, identifier, wire, key="retry-new-sequence").status_code == 200
            changed = campaign_journal()
            changed["journal"]["randomSeed"] += 1
            assert save(client, token, identifier, packed(changed), key="changed").status_code == 409
            load = client.post("/quest/getBattleReplay", headers={"secret": token}, json={"stageId": "camp_synthetic"})
            assert load.status_code == 404
        with restarted.database.transaction(write=False) as session:
            assert session.get(m.BattleSession, identifier).native_context["campaign_journal"] == stored
    finally:
        restarted.database.close()


@pytest.mark.parametrize("change,status", [
    ({"stage": "camp_rotate"}, 409), ({"member": {"charInstId": 2}}, 409),
    ({"member": {"skillIndex": 2}}, 409), ({"member": {"isAssistChar": True}}, 409),
    ({"member": {"uniequipId": "unverified-module"}}, 501), ({"bad_wire": True}, 400),
])
def test_campaign_journal_conflicts_do_not_create_a_record(campaign_runtime, change, status):
    runtime = campaign_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        assert finish(client, token, identifier).status_code == 200
        data = campaign_journal()
        if "stage" in change:
            data["journal"]["metadata"]["stageId"] = change["stage"]
        data["journal"]["squad"][0].update(change.get("member", {}))
        before = runtime.sync(token)
        response = save(client, token, identifier, "invalid" if change.get("bad_wire") else packed(data))
        assert response.status_code == status
        assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert "campaign_journal" not in session.get(m.BattleSession, identifier).native_context


def test_campaign_journal_requires_an_actual_finished_owned_battle(campaign_runtime):
    runtime = campaign_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "OtherCampaign")
    other = login(runtime, "OtherCampaign")
    wire = packed(campaign_journal())
    with TestClient(create_game_app(runtime)) as client:
        identifier = begin(client, token).json()["battleId"]
        assert save(client, token, identifier, wire).status_code == 409
        assert save(client, other, identifier, wire).status_code == 404
        assert finish(client, token, identifier).status_code == 200
        assert save(client, token, identifier, wire, key="finished-save").status_code == 200
