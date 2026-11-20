"""Authored map objectives: same-battle requirements, locked bags and binding."""

import pytest
from test_crisis_v2_rules import load, player, source

from terralocal.server.gamedata.crisis_v2_objectives import CrisisV2ObjectiveRules


def detail():
    value = source()
    value["bagDataMap"]["bag"]["slotPackType"] = "HIGHEST_TOTAL_SCORE"
    value["challengeNodeDataMap"] = {"bridge": {"slotId": "bridge", "missionType": "PassWithDimScore",
        "missionParamList": ["0;1", "30"], "slotIdList": [], "requiredSlotCount": 0}}
    value["rewardNodeDataMap"] = {"reward": {"slotId": "reward", "requestBagIdList": ["bag"], "requestBagCnt": 1}}
    return value


def compile_rules(value=None):
    value = detail() if value is None else value
    rules = load(value)
    return rules, CrisisV2ObjectiveRules(value, rules)


def test_stronger_mutex_alternative_completes_bag_without_default_or_all_members():
    rules, objectives = compile_rules()
    evaluation = rules.evaluate(["high"], player(), permanent=True)
    result = objectives.evaluate(evaluation, cleared=True)
    assert result.runes == {"high"}
    assert result.challenges == {"bridge"}
    assert result.packs == {"bag"}
    assert dict(result.treasure_progress) == {"reward": 1}


def test_partial_bag_does_not_earn_treasure_and_defeat_does_not_earn_any_objective():
    rules, objectives = compile_rules()
    partial = objectives.evaluate(rules.evaluate(["low"], player(), permanent=True), cleared=True)
    assert partial.packs == partial.challenges == frozenset()
    assert dict(partial.treasure_progress) == {"reward": 0}
    defeat = objectives.evaluate(rules.evaluate(["high"], player(), permanent=True), cleared=False)
    assert not any((defeat.runes, defeat.challenges, defeat.packs, defeat.treasure_progress))


def test_unknown_locked_zero_over_zero_bag_is_separate_from_earned_objectives():
    value = detail()
    value["nodeDataMap"]["locked"]["slotPackId"] = "daily"
    value["bagDataMap"]["daily"] = {**value["bagDataMap"]["bag"], "slotPackId": "daily"}
    rules, objectives = compile_rules(value)
    locked = rules.evaluate(["high"], player(), permanent=True)
    assert locked.bag_progress["daily"].complete
    result = objectives.evaluate(locked, cleared=True)
    assert result.packs == {"bag"} and result.empty_packs == {"daily"}
    unlocked = objectives.evaluate(rules.evaluate(["high", "locked"], player(locked=2), permanent=True), cleared=True)
    assert unlocked.packs == {"bag", "daily"} and not unlocked.empty_packs


@pytest.mark.parametrize("damage", ["type", "unknown-bag", "duplicate-bag", "count", "bool-count",
    "missing-treasure", "wrong-id", "unknown-challenge"])
def test_unknown_or_inconsistent_mission_data_is_not_a_ready_objective(damage):
    value = detail()
    reward = value["rewardNodeDataMap"]["reward"]
    if damage == "type":
        value["bagDataMap"]["bag"]["slotPackType"] = "UNVERIFIED"
    elif damage == "unknown-bag":
        reward["requestBagIdList"] = ["absent"]
    elif damage == "duplicate-bag":
        reward["requestBagIdList"] = ["bag", "bag"]
    elif damage == "count":
        reward["requestBagCnt"] = 2
    elif damage == "bool-count":
        reward["requestBagCnt"] = True
    elif damage == "missing-treasure":
        value["rewardNodeDataMap"] = {}
    elif damage == "wrong-id":
        reward["slotId"] = "other"
    else:
        value["challengeNodeDataMap"]["bridge"]["missionType"] = "UNVERIFIED"
    with pytest.raises(ValueError):
        compile_rules(value)


def test_objectives_reject_other_map_version_and_changed_reward_source():
    value = detail()
    rules, objectives = compile_rules(value)
    other = load(value, data_hash="b" * 64).evaluate(["high"], player(), permanent=True)
    with pytest.raises(ValueError, match="匹配地图"):
        objectives.evaluate(other, cleared=True)
    value["rewardNodeDataMap"]["reward"]["requestBagCnt"] = 0
    with pytest.raises(ValueError, match="来源与已绑定"):
        CrisisV2ObjectiveRules(value, rules)
    with pytest.raises(ValueError, match="明确战斗结果"):
        objectives.evaluate(rules.evaluate(["high"], player(), permanent=True), cleared=1)
