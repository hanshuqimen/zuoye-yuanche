"""Authored encrypted fixtures matching observed campaign-abort field types.

No real telemetry, credentials, battle IDs or encrypted client payloads are
included. Protocol acceptance here is not a campaign reward implementation.
"""
import pytest
from test_native_battle_finish import encoded

from terralocal.server.domain.errors import DomainError
from terralocal.server.protocol.battle_codec import (
    DecodedCampaignFinish,
    FinishRequest,
    decode_campaign_finish,
    decode_finish,
)

BATTLE = "10000000-0000-0000-0000-000000000007"
LOGIN = 1_800_000_000


def campaign_request(**changes):
    return FinishRequest.model_validate(encoded(BATTLE, state=2, changes={
        "stageId": "camp_synthetic", "interrupt": 1, "giveUp": 0, "percent": 0, **changes}))


def test_observed_partial_abort_is_campaign_facts_not_ordinary_success():
    request = campaign_request()
    result = decode_campaign_finish(request, [LOGIN])
    assert isinstance(result, DecodedCampaignFinish)
    assert result.completeState == 2 and result.interrupt and not result.giveUp
    assert result.killCnt == result.validKillCnt == 0 and result.percent == 0
    assert result.stageId == "camp_synthetic"
    with pytest.raises(DomainError, match="战斗提交数据无效"):
        decode_finish(request, [LOGIN])


def test_campaign_scheduler_fields_and_nested_telemetry_stay_separate():
    request = campaign_request(killCnt=17, validKillCnt=11)
    parsed = decode_campaign_finish(request, [LOGIN])
    assert parsed.killCnt == 17 and parsed.validKillCnt == 11
    assert parsed.battleData.stats["killedEnemiesCnt"] == 0
    assert request.battleData.stats == {}


@pytest.mark.parametrize("kills,percent", [(3, 1), (100, 25)])
def test_native_positive_abort_shape_keeps_percentage_independent_of_kills(kills, percent):
    # v11/v14 observed scalar shapes, re-authored encryption/identity/telemetry.
    result = decode_campaign_finish(campaign_request(killCnt=kills, validKillCnt=kills, percent=percent), [LOGIN])
    assert result.completeState == 2 and result.interrupt and not result.giveUp
    assert result.killCnt == result.validKillCnt == kills and result.percent == percent
    assert result.battleData.stats["killedEnemiesCnt"] == 0
    # Native overrideKillCnt can weight the valid counter independently.
    weighted = decode_campaign_finish(campaign_request(killCnt=1, validKillCnt=2, percent=1), [LOGIN])
    assert weighted.killCnt == 1 and weighted.validKillCnt == 2


@pytest.mark.parametrize("change", [
    {"completeState": 3}, {"completeState": True}, {"interrupt": 2},
    {"giveUp": "1"}, {"validKillCnt": -1}, {"platform": True},
    {"unverifiedField": 0},
])
def test_campaign_parser_keeps_strict_bounds_and_completed_rank_guard(change):
    with pytest.raises(DomainError):
        decode_campaign_finish(campaign_request(**change), [LOGIN])


def test_campaign_login_key_candidates_and_outer_signature_still_bind_payload():
    request = campaign_request()
    with pytest.raises(DomainError):
        decode_campaign_finish(request, [LOGIN + 1])
    assert decode_campaign_finish(request, [LOGIN + 1, LOGIN]).battleId == BATTLE
    changed = request.model_copy(deep=True)
    changed.battleData.completeTime += 1
    with pytest.raises(DomainError):
        decode_campaign_finish(changed, [LOGIN])
    conflicting = campaign_request(battleId="10000000-0000-0000-0000-000000000008")
    with pytest.raises(DomainError):
        decode_campaign_finish(conflicting, [LOGIN])
