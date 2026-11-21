"""Selected counters only: snapshot field, two declared shapes and exact F3."""

import pytest

from terralocal.server.domain.errors import DomainError
from terralocal.server.protocol.crisis_v2_counters import decode_counters


def enemy(kind="HP_ZERO", value=1, flag=False, ident="enemy_synthetic"):
    return {"Key": {"enemyId": ident, "counterType": kind, "isInvalidKilled": flag}, "Value": value}


def test_missing_null_and_empty_pools_are_distinct_and_runtime_pool_is_not_a_fallback():
    for stats in ({}, {"charStats": None, "enemyStats": None, "extraBattleInfo": None},
                  {"extraBattleInfoStats": {"SIMPLE,,COST": 5}}):
        facts = decode_counters(stats)
        assert facts.characters is facts.enemies is facts.extra is None
        assert not facts.has_end_marker
    facts = decode_counters({"charStats": [], "enemyStats": [], "extraBattleInfo": []})
    assert facts.characters.spawns == 0 and facts.enemies == facts.extra == ()
    assert not facts.has_end_marker


def test_two_explicit_listdict_admissions_produce_same_selected_facts_and_ignore_private_fields():
    values = {"SIMPLE,,COST": 0, "ATTRIBUTE,actor,COST,90": 1, "ATTRIBUTE,enemy,HP_RATIO,0.010": 1,
              "SIMPLE,,unrelated-private-marker": 42}
    a = decode_counters({"extraBattleInfo": values, "access": "authored-private-value"})
    b = decode_counters({"extraBattleInfo": [{"Key": k, "Value": v} for k, v in reversed(values.items())]})
    assert a.canonical() == b.canonical() and a.extra_encoding == "object" and b.extra_encoding == "list"
    assert a.has_end_marker and "private" not in repr(a.canonical())
    assert next(r for r in a.extra if r.name == "HP_RATIO").sample == 10


def test_enemy_categories_and_invalid_kill_flag_are_independent_bounded_counters():
    facts = decode_counters({"enemyStats": [enemy(value=15), enemy(value=15, flag=True), enemy("ENCOUNTER", 100)]})
    assert sum(r.value for r in facts.enemies if r.kind == "HP_ZERO") == 30
    assert sum(r.value for r in facts.enemies if r.kind == "ENCOUNTER") == 100


@pytest.mark.parametrize("pool", [
    [enemy(), enemy()], [enemy(kind=0)], [enemy(kind="DEAD")], [enemy(flag=1)], [enemy(value=True)],
    [enemy(value=-1)], [enemy(value=100001)], [enemy(ident="")], [{"Key": {}, "Value": 1}], {},
])
def test_ambiguous_or_mistyped_enemy_counter_is_not_zero(pool):
    with pytest.raises(DomainError) as error:
        decode_counters({"enemyStats": pool})
    assert error.value.code == "INVALID_CRISIS_V2_COUNTERS"


@pytest.mark.parametrize("value", [
    {"SIMPLE,,COST": True}, {"SIMPLE,,COST": "1"}, {"SIMPLE,,COST": 2**31},
    {"1,,COST": 1}, {"3,a,COST,90": 1}, {"SIMPLE,a,COST": 1},
    {"ATTRIBUTE,a,COST,90.0": 1}, {"ATTRIBUTE,a,HP_RATIO,0.01": 1},
    {"ATTRIBUTE,a,HP_RATIO,NaN": 1}, {"ATTRIBUTE,a,HP_RATIO,1.001": 1},
    {"ATTRIBUTE,a,HP_RATIO,0.010": -1}, {"SIMPLE,,not_build_at_reed": -1},
    [{"Key": "SIMPLE,,COST", "Value": 1}, {"Key": "SIMPLE,,COST", "Value": 2}],
    [{"key": "SIMPLE,,COST", "Value": 1}], "invalid",
])
def test_invalid_relevant_key_or_value_cannot_disappear_into_a_sparse_zero(value):
    with pytest.raises(DomainError) as error:
        decode_counters({"extraBattleInfo": value})
    assert error.value.code == "INVALID_CRISIS_V2_COUNTERS"


def test_total_row_and_occurrence_budgets_are_enforced_before_projection():
    with pytest.raises(DomainError):
        decode_counters({"extraBattleInfo": {f"unused-{n}": 0 for n in range(4097)}})
    with pytest.raises(DomainError):
        decode_counters({"extraBattleInfo": {"ATTRIBUTE,a,COST,90": 100000, "ATTRIBUTE,b,COST,90": 1}})
    with pytest.raises(DomainError):
        decode_counters({"enemyStats": [enemy(value=100000), enemy(value=1, flag=True)]})
