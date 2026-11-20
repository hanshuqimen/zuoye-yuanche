"""Authored graphs: per-battle thresholds, alternatives and clear gating."""

import pytest
from test_crisis_v2_rules import load, player, source

from terralocal.server.gamedata.crisis_v2_challenges import CrisisV2ChallengeRules


def compile_challenge(kind, params, slots=(), minimum=0):
    detail = source()
    detail["challengeNodeDataMap"] = {"bridge": {"slotId": "bridge", "missionType": kind,
        "missionParamList": params, "slotIdList": list(slots), "requiredSlotCount": minimum}}
    rules = load(detail)
    return rules, CrisisV2ChallengeRules(detail, rules)


def test_dimension_threshold_uses_only_named_axes_and_includes_equality():
    rules, challenges = compile_challenge("PassWithDimScore", ["1", "20"])
    below = rules.evaluate(["high"], player(), permanent=True)
    exact = rules.evaluate(["low", "end"], player(), permanent=True)
    assert below.total_score > 20
    assert challenges.satisfied(below, cleared=True) == frozenset()
    assert challenges.satisfied(exact, cleared=True) == {"bridge"}


def test_one_of_two_alternatives_does_not_require_both_mutex_slots():
    rules, challenges = compile_challenge("PassWithRunes", ["low;high", "1"], ["low", "high"], 1)
    for choice in ("low", "high"):
        selected = rules.evaluate([choice], player(), permanent=True)
        assert challenges.satisfied(selected, cleared=True) == {"bridge"}


def test_required_slot_count_cannot_be_inflated_by_repeated_request_ids():
    rules, challenges = compile_challenge("PassWithRunes", ["low;end", "2"], ["low", "end"], 2)
    repeated = rules.evaluate(["low", "low"], player(), permanent=True)
    both = rules.evaluate(["end", "low"], player(), permanent=True)
    assert challenges.satisfied(repeated, cleared=True) == frozenset()
    assert challenges.satisfied(both, cleared=True) == {"bridge"}


def test_defeat_never_completes_even_a_zero_threshold():
    rules, challenges = compile_challenge("PassWithDimScore", ["0", "0"])
    result = rules.evaluate([], player(), permanent=True)
    assert challenges.satisfied(result, cleared=False) == frozenset()
    assert challenges.satisfied(result, cleared=True) == {"bridge"}


def test_conditions_reject_an_evaluation_from_other_bound_data():
    _, challenges = compile_challenge("PassWithDimScore", ["0", "1"])
    other = load(data_hash="b" * 64).evaluate(["low"], player(), permanent=True)
    with pytest.raises(ValueError, match="匹配地图"):
        challenges.satisfied(other, cleared=True)


def test_mutated_conditions_cannot_be_bound_to_previously_compiled_map():
    detail = source()
    detail["challengeNodeDataMap"] = {"bridge": {"slotId": "bridge", "missionType": "PassWithDimScore",
        "missionParamList": ["0", "300"], "slotIdList": [], "requiredSlotCount": 0}}
    rules = load(detail)
    detail["challengeNodeDataMap"]["bridge"]["missionParamList"][1] = "0"
    with pytest.raises(ValueError, match="来源与已绑定地图不一致"):
        CrisisV2ChallengeRules(detail, rules)


@pytest.mark.parametrize("damage", ["unsupported", "count", "special", "dimensions"])
def test_unadmitted_condition_cannot_become_a_successful_completion(damage):
    kind, params, slots, minimum = "PassWithRunes", ["low;end", "2"], ["low", "end"], 2
    if damage == "unsupported":
        kind = "UnverifiedFutureCondition"
    elif damage == "count":
        minimum = 1
    elif damage == "special":
        params, slots = ["low;bridge", "2"], ["low", "bridge"]
    else:
        kind, params, slots, minimum = "PassWithDimScore", ["0;6", "1"], [], 0
    with pytest.raises(ValueError):
        compile_challenge(kind, params, slots, minimum)
