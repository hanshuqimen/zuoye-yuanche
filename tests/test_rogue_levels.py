"""Cumulative EXP boundaries differ from per-row costs; no gameplay fixture."""

import copy
from dataclasses import FrozenInstanceError

import pytest

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_levels import FirstThemeLevelCurve, LevelGains, LevelPosition


def levels():
    return {str(i): {"exp": cost, "populationUp": hope, "squadCapacityUp": capacity,
        "battleCharLimitUp": deployed, "maxHpUp": hp}
        for i, (cost, hope, capacity, deployed, hp) in enumerate([
            (0, 0, 0, 0, 0), (10, 4, 0, 0, 0), (24, 4, 1, 2, 1), (36, 5, 0, 1, 3)], 1)}


@pytest.mark.parametrize("exp,result", [
    (0, (1, 0, 10)), (9, (1, 9, 10)), (10, (2, 0, 24)), (24, (2, 14, 24)),
    (33, (2, 23, 24)), (34, (3, 0, 36)), (69, (3, 35, 36)), (70, (4, 0, None)),
    (71, (4, 1, None)), (2**31 - 1, (4, 2**31 - 1 - 70, None))])
def test_exp_subtracts_successive_costs_and_keeps_max_level_surplus(exp, result):
    curve = FirstThemeLevelCurve(levels())
    level, remainder, cost = result
    assert curve.at(exp) == LevelPosition(level, exp, remainder, cost)


def test_gains_cross_only_new_levels_and_keep_carry_deploy_and_hp_separate():
    curve = FirstThemeLevelCurve(levels())
    assert curve.gains(0, 9) == LevelGains(1, 1, 0, 0, 0, 0)
    assert curve.gains(9, 34) == LevelGains(1, 3, 8, 1, 2, 1)
    assert curve.gains(34, 70) == LevelGains(3, 4, 5, 0, 1, 3)
    assert curve.gains(70, 1000) == LevelGains(4, 4, 0, 0, 0, 0)
    with pytest.raises(DomainError, match="不能减少"):
        curve.gains(34, 33)


def test_catalog_freezes_source_values_and_has_no_mutable_row_aliases():
    source = levels()
    curve = FirstThemeLevelCurve(source)
    expected = curve.fingerprint
    source["2"]["exp"] = 1
    assert curve.at(9).level == 1 and curve.fingerprint == expected
    with pytest.raises(FrozenInstanceError):
        curve.steps[0].exp_cost = 100


@pytest.mark.parametrize("damage", ["gap", "key", "missing", "extra", "bool", "negative", "float", "initial", "zero", "overflow"])
def test_incomplete_or_unknown_level_rules_are_not_defaulted(damage):
    rows = copy.deepcopy(levels())
    if damage == "gap":
        del rows["2"]
    elif damage == "key":
        rows["02"] = rows.pop("2")
    elif damage == "missing":
        del rows["2"]["populationUp"]
    elif damage == "extra":
        rows["2"]["future"] = 1
    elif damage == "initial":
        rows["1"]["exp"] = 1
    else:
        rows["2"]["exp"] = {"bool": True, "negative": -1, "float": 10.0,
                            "zero": 0, "overflow": 2**31 - 1}[damage]
    with pytest.raises(ValueError):
        FirstThemeLevelCurve(rows)


@pytest.mark.parametrize("value", [-1, 2**31, True, 1.0, "10"])
def test_untrusted_exp_does_not_coerce_or_overflow(value):
    with pytest.raises(DomainError):
        FirstThemeLevelCurve(levels()).at(value)
