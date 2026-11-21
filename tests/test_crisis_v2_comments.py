"""Imported condition arithmetic, explicit unknowns, roster and death semantics."""

import pytest
from test_crisis_v2_counters import enemy
from test_crisis_v2_rules import load, player, source

from terralocal.server.gamedata.crisis_v2_comments import CrisisV2CommentRules
from terralocal.server.protocol.crisis_v2_counters import decode_counters


def detail():
    value = source()
    specs = [("score", "PassWithDimensionScoreMore", ["1", "20"]),
        ("few", "PassWithDeployLess", ["9"]), ("many", "PassWithDeployMore", ["20"]),
        ("profession", "PassWithSpecProf", ["SNIPER", "4"]),
        ("reed", "PassWithEventLess", ["not_build_at_reed", "0"]),
        ("cost", "PassWithEventLess", ["COST", "10"]),
        ("expensive", "PassWithAttrExistMore", ["COST", "90"]),
        ("low_hp", "PassWithAttrAllLess", ["HP_RATIO", "0.01"]),
        ("kill", "KillWithSpecSlot", ["high", "1", "enemy_synthetic", "30"])]
    value["commentDataMap"] = {key: {"id": key, "condition": kind, "paramList": params, "sortId": n}
                                for n, (key, kind, params) in enumerate(specs)}
    return value


def compile_rules(value=None):
    value = detail() if value is None else value
    rules = load(value)
    return rules, CrisisV2CommentRules(value, rules)


def counters(*, spawns=0, extra=None, enemies=()):
    return decode_counters({"charStats": [{"Key": {"charId": "char_authored", "counterType": "SPAWN"}, "Value": spawns},
        {"Key": {"charId": "char_authored", "counterType": "DEAD"}, "Value": 100}],
        "enemyStats": list(enemies), "extraBattleInfo": {"SIMPLE,,COST": 10} | (extra or {})})


def test_all_actual_condition_kinds_use_specific_inputs_and_inclusive_thresholds():
    rules, comments = compile_rules()
    result = comments.evaluate(rules.evaluate(["high", "end"], player(), permanent=True),
        counters(spawns=20, extra={"ATTRIBUTE,actor,COST,90": 1, "ATTRIBUTE,enemy,HP_RATIO,0.010": 1},
                 enemies=[enemy(value=15), enemy(value=15, flag=True), enemy("ENCOUNTER", 100)]),
        ("SNIPER",)*4, cleared=True)
    assert result.earned == ("score", "many", "profession", "reed", "cost", "expensive", "low_hp", "kill")
    assert result.unavailable == ()


def test_profession_is_frozen_roster_not_deployment_and_deaths_are_not_more_spawns():
    rules, comments = compile_rules()
    result = comments.evaluate(rules.evaluate(["low"], player(), permanent=True),
        counters(spawns=9), ("SNIPER",)*4, cleared=True)
    assert "profession" in result.earned and "few" in result.earned and "many" not in result.earned
    assert "score" not in result.earned  # High total cannot replace the named dimension.


def test_missing_pools_remain_unavailable_instead_of_earning_sparse_or_low_deployment_comments():
    rules, comments = compile_rules()
    result = comments.evaluate(rules.evaluate(["high"], player(), permanent=True),
        decode_counters({}), ("WARRIOR",), cleared=True)
    assert result.earned == ()
    assert set(result.unavailable) == {"few", "many", "reed", "cost", "expensive", "low_hp", "kill"}
    empty = comments.evaluate(rules.evaluate(["low"], player(), permanent=True),
        decode_counters({"charStats": [], "enemyStats": [], "extraBattleInfo": {}}), ("WARRIOR",), cleared=True)
    assert empty.earned == ("few",) and "reed" in empty.unavailable and "kill" not in empty.unavailable


def test_no_escaped_enemy_and_zero_occurrence_rows_do_not_vacuously_earn_low_hp():
    rules, comments = compile_rules()
    evaluation = rules.evaluate(["low"], player(), permanent=True)
    for extra in ({}, {"ATTRIBUTE,a,HP_RATIO,0.001": 0}, {"ATTRIBUTE,a,HP_RATIO,0.011": 1}):
        result = comments.evaluate(evaluation, counters(extra=extra), ("WARRIOR",), cleared=True)
        assert "low_hp" not in result.earned
    result = comments.evaluate(evaluation, counters(extra={"ATTRIBUTE,a,HP_RATIO,0.010": 1,
        "ATTRIBUTE,b,HP_RATIO,0.001": 1}), ("WARRIOR",), cleared=True)
    assert "low_hp" in result.earned


def test_marker_frequencies_and_end_cost_do_not_mix_with_attribute_cost():
    rules, comments = compile_rules()
    result = comments.evaluate(rules.evaluate(["low"], player(), permanent=True),
        counters(extra={"SIMPLE,,COST": 11, "SIMPLE,,not_build_at_reed": 1, "ATTRIBUTE,a,COST,99": 1}),
        ("WARRIOR",), cleared=True)
    assert "expensive" in result.earned and "cost" not in result.earned and "reed" not in result.earned


def test_kill_requires_selected_prerequisite_and_only_target_hp_zero_including_self_deaths():
    rules, comments = compile_rules()
    only_encounters = counters(enemies=[enemy("ENCOUNTER", 100), enemy("REACH_EXIT", 100),
        enemy(value=100, ident="other_enemy")])
    result = comments.evaluate(rules.evaluate(["high"], player(), permanent=True), only_encounters,
        ("WARRIOR",), cleared=True)
    assert "kill" not in result.earned
    valid = counters(enemies=[enemy(value=30, flag=True)])
    assert "kill" in comments.evaluate(rules.evaluate(["high"], player(), permanent=True),
        valid, ("WARRIOR",), cleared=True).earned
    assert "kill" not in comments.evaluate(rules.evaluate(["low"], player(), permanent=True),
        valid, ("WARRIOR",), cleared=True).earned


@pytest.mark.parametrize("damage", ["unknown", "axis", "numeric", "profession", "kill-count", "attribute", "nan", "marker"])
def test_unadmitted_condition_is_not_a_successful_default(damage):
    value = detail()
    if damage == "unknown":
        value["commentDataMap"]["few"]["condition"] = "UNVERIFIED"
    elif damage == "axis":
        value["commentDataMap"]["score"]["paramList"][0] = "6"
    elif damage == "numeric":
        value["commentDataMap"]["score"]["paramList"][1] = "20.5"
    elif damage == "profession":
        value["commentDataMap"]["profession"]["paramList"][0] = "TOKEN"
    elif damage == "kill-count":
        value["commentDataMap"]["kill"]["paramList"][1] = "2"
    elif damage == "attribute":
        value["commentDataMap"]["low_hp"]["paramList"][0] = "SP"
    elif damage == "nan":
        value["commentDataMap"]["low_hp"]["paramList"][1] = "NaN"
    else:
        value["commentDataMap"]["reed"]["paramList"][0] = "UNVERIFIED"
    with pytest.raises(ValueError):
        compile_rules(value)


def test_map_binding_source_changes_and_non_clear_outcomes_never_earn_comments():
    value = detail()
    rules, comments = compile_rules(value)
    evaluation = rules.evaluate(["high", "end"], player(), permanent=True)
    assert comments.evaluate(evaluation, counters(), ("WARRIOR",), cleared=False).earned == ()
    with pytest.raises(ValueError):
        comments.evaluate(evaluation, counters(), ("WARRIOR",), cleared=1)
    with pytest.raises(ValueError):
        comments.evaluate(load(value, data_hash="b"*64).evaluate(["high"], player(), permanent=True),
            counters(), ("WARRIOR",), cleared=True)
    value["commentDataMap"]["few"]["paramList"] = ["0"]
    with pytest.raises(ValueError, match="来源与绑定"):
        CrisisV2CommentRules(value, rules)
