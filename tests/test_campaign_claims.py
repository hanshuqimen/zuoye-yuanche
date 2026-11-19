"""Authored eligibility fixtures, not evidence of native battle qualification."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from test_campaign_persistence import camp_runtime as camp_runtime

from terralocal.server.domain import accounts
from terralocal.server.domain.context import Context
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def login(runtime, name="CampaignDoctor"):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name=name)["secret"]


def eligible(runtime, kills=6):
    # Explicit test ledger setup; never presented as a natural battle clear.
    with runtime.database.transaction() as session:
        session.get(m.CampaignStageProgress, (1, "camp_synthetic")).max_kills = kills


def claim(client, token, indices=None, *, stage="camp_synthetic", key="claim"):
    return client.post("/campaignV2/getBreakReward", headers={"secret": token, "seqnum": key},
        json={"stageId": stage, "indexList": [0, 1] if indices is None else indices})


def test_atomic_batch_claim_delta_concurrency_restart_and_restore(camp_runtime):
    runtime = camp_runtime
    eligible(runtime)
    token = login(runtime)
    before = runtime.sync(token)
    backup = BackupService(runtime).create()
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda _: claim(client, token), range(8)))
        assert all(r.status_code == 200 and r.json() == replies[0].json() for r in replies)
        result = replies[0].json()
        assert result["feeAdd"] == 15
        assert result["items"] == [
            {"type": "MATERIAL", "id": "material", "count": 2, "charGet": None},
            {"type": "FURN", "id": "furn_synthetic", "count": 1, "charGet": None}]
        after = runtime.sync(token)
        assert apply(before["user"], result["playerDataDelta"]) == after["user"]
        state = after["user"]["campaignsV2"]
        assert state["campaignTotalFee"] == 1215 and state["campaignCurrentFee"] == 0
        assert state["instances"]["camp_synthetic"] == {"maxKills": 6, "rewardStatus": [1, 1]}
        assert state["sweepMaxKills"] == {} and state["missions"] == {"mission_synthetic": 0}
        assert after["user"]["dungeon"] == before["user"]["dungeon"]
        assert after["user"]["status"]["ap"] == before["user"]["status"]["ap"]
        assert claim(client, token, key="duplicate").status_code == 409
        assert claim(client, token, [0], key="claim").status_code == 409
        assert runtime.sync(token) == after
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.CampaignBreakClaim).count() == 2
        assert session.query(m.Receipt).count() == 1
        assert session.query(m.StageProgress).count() == session.query(m.StageReplay).count() == 0
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == after
        with TestClient(create_game_app(restarted)) as client:
            assert claim(client, token).json() == result
            assert claim(client, token, key="after-restart").status_code == 409
        BackupService(restarted).restore(backup["name"])
        assert restarted.sync(token) == before
        with TestClient(create_game_app(restarted)) as client:
            assert claim(client, token).json() == result
        assert restarted.sync(token) == after
    finally:
        restarted.database.close()


@pytest.mark.parametrize("indices,status", [([], 422), ([True], 422), (["0"], 422),
    ([-1], 422), ([128], 422), ([0] * 129, 422), ([0, 0], 400), ([0, 2], 400), ([0, 1], 400)])
def test_invalid_or_ineligible_batch_changes_nothing(camp_runtime, indices, status):
    runtime = camp_runtime
    eligible(runtime, 3)
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        result = claim(client, token, indices)
        assert result.status_code == status
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.CampaignBreakClaim).count() == session.query(m.Receipt).count() == 0


def test_other_account_cannot_borrow_eligibility_and_partial_duplicates_are_atomic(camp_runtime):
    runtime = camp_runtime
    eligible(runtime)
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "OtherCampaign")
    other = login(runtime, "OtherCampaign")
    other_before = runtime.sync(other)
    with TestClient(create_game_app(runtime)) as client:
        assert claim(client, other).status_code == 400
        assert claim(client, token, [0]).status_code == 200
        before = runtime.sync(token)
        assert claim(client, token, [1, 0], key="mixed").status_code == 409
        assert runtime.sync(token) == before and runtime.sync(other) == other_before
        assert claim(client, token, [1], key="second").json()["feeAdd"] == 5
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.CampaignBreakClaim).filter_by(account_id=2).count() == 0


def test_inventory_limit_rolls_back_earlier_furniture_and_fee_claim(camp_runtime):
    runtime = camp_runtime
    eligible(runtime)
    token = login(runtime)
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).change_item("material", 2_000_000_000)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert claim(client, token, [1, 0]).status_code == 400
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert Context(session, runtime.data, 1).balance("furn_synthetic") == 0
        assert session.query(m.CampaignBreakClaim).count() == session.query(m.Receipt).count() == 0


def test_database_failure_rolls_back_wallet_claim_fee_delta_and_receipt(camp_runtime):
    runtime = camp_runtime
    eligible(runtime)
    token = login(runtime)
    before = runtime.sync(token)

    def fail_insert(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO campaign_break_claims"):
            raise RuntimeError("synthetic claim write failure")

    event.listen(runtime.database.engine, "before_cursor_execute", fail_insert)
    try:
        with TestClient(create_game_app(runtime)) as client:
            with pytest.raises(RuntimeError, match="synthetic claim write failure"):
                claim(client, token)
    finally:
        event.remove(runtime.database.engine, "before_cursor_execute", fail_insert)
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.CampaignBreakClaim).count() == session.query(m.Receipt).count() == 0


def test_old_profile_and_unknown_stage_have_explicit_errors(camp_runtime, runtime, token):
    with TestClient(create_game_app(runtime)) as client:
        response = claim(client, token)
        assert response.status_code == 503 and response.json()["error"]["code"] == "CAMPAIGN_DATA_UNAVAILABLE"
    token = login(camp_runtime)
    before = camp_runtime.sync(token)
    with TestClient(create_game_app(camp_runtime)) as client:
        assert claim(client, token, [0], stage="missing").status_code == 400
    assert camp_runtime.sync(token) == before
