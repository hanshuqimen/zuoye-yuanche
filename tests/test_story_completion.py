import pytest
from sqlalchemy import select

from terralocal.server.domain import accounts
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


def finish(client, token, story_id, seq):
    return client.post("/story/finishStory", json={"storyId": story_id},
                       headers={"secret": token, "seqnum": str(seq)})


def test_story_rewards_flags_progress_delta_and_restart(client, runtime, token):
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
        other_token = accounts.login(session, runtime.settings, name="Other")["secret"]
    before = runtime.sync(token)["user"]
    response = finish(client, token, "synthetic_intro", 1)
    assert response.status_code == 200
    after = runtime.sync(token)["user"]
    assert after["inventory"]["material"] == 2
    assert after["status"]["progress"] == 10
    assert after["status"]["flags"]["synthetic_intro"] == 1
    assert apply(before, response.json()["playerDataDelta"]) == after
    assert finish(client, token, "synthetic_intro", 1).json() == response.json()
    assert finish(client, token, "synthetic_intro", 2).json()["items"] == []
    assert runtime.sync(token)["user"]["inventory"]["material"] == 2
    assert runtime.sync(other_token)["user"]["status"]["flags"] == {}
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == after
    finally:
        restarted.database.close()


def test_story_requires_progress_flags_and_stage_clear(client, runtime, token):
    before = runtime.sync(token)
    assert finish(client, token, "synthetic_sequel", 1).status_code == 400
    assert runtime.sync(token) == before
    assert finish(client, token, "synthetic_intro", 2).status_code == 200
    assert finish(client, token, "synthetic_sequel", 3).status_code == 400
    with runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_1", unlocked=True, stars=2))
    assert finish(client, token, "synthetic_sequel", 4).status_code == 200
    assert runtime.sync(token)["user"]["status"]["progress"] == 20
    assert finish(client, token, "synthetic_intro", 5).status_code == 200
    assert runtime.sync(token)["user"]["status"]["progress"] == 20


def test_story_rewards_roll_back_after_partial_failure(client, runtime, token):
    runtime.data.table("story_table")["synthetic_intro"]["completedRewards"].append({
        "id": "unknown-item", "count": 1})
    before = runtime.sync(token)
    assert finish(client, token, "synthetic_intro", 1).status_code == 400
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.scalar(select(m.StoryCompletion)) is None


def test_story_legacy_completion_does_not_grant_rewards_again(client, runtime, token):
    with runtime.database.transaction() as session:
        session.get(m.PlayerProfile, 1).flags = {"story": {"synthetic_intro": 1}, "progress": 30}
    assert finish(client, token, "synthetic_intro", 1).json()["items"] == []
    user = runtime.sync(token)["user"]
    assert "material" not in user["inventory"] and user["status"]["progress"] == 30
    assert finish(client, token, "unknown", 2).status_code == 404
    assert finish(client, "invalid", "synthetic_intro", 3).status_code == 401


def test_free_originite_platform_totals_derive_from_the_same_balance(runtime, token):
    with runtime.database.transaction() as session:
        session.add(m.Currency(account_id=1, item_id="4002", balance=123))
    status = runtime.sync(token)["user"]["status"]
    assert status["freeDiamond"] == status["androidDiamond"] == status["iosDiamond"] == 123
    assert status["payDiamond"] == 0


def test_story_catalog_import_rejects_reward_and_stage_reference_errors():
    from conftest import miniature

    from terralocal.server.gamedata.repository import validate_tables

    tables = miniature()
    tables["story_table"]["synthetic_intro"]["completedRewards"][0]["id"] = "unknown"
    with pytest.raises(ValueError, match="剧情奖励"):
        validate_tables(tables)
    tables = miniature()
    tables["story_table"]["synthetic_sequel"]["condition"]["requiredStages"][0]["stageId"] = "unknown"
    with pytest.raises(ValueError, match="前置关卡"):
        validate_tables(tables)
