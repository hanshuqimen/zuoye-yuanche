"""Matched conditional endings; pure facts never assert native victories."""

import copy
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from test_rogue_ending_unlocks import load as load_base
from test_rogue_ending_unlocks import run as completion
from test_rogue_ending_unlocks import source as base_source

from terralocal.server.gamedata.rogue_collection import FirstThemeRelicArchive
from terralocal.server.gamedata.rogue_ending_variants import (
    BAND_GOALS,
    BANDS,
    CONDITIONS,
    THRESHOLDS,
    FirstThemeEndingVariants,
    RunEndingVariant,
    available,
)


def add_variant_conditions(detail):
    for key, name in BANDS.items():
        detail["items"].setdefault(key, {}).update(id=key, type="BAND", name=name)
    for index, (key, text) in enumerate(CONDITIONS.items(), 500):
        detail["items"].setdefault(key, {"id": key, "type": "RELIC"})["unlockCondDesc"] = text
        detail["relics"].setdefault(key, {"id": key, "buffs": []})
        detail["relicParams"].setdefault(key, {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []})
        detail["archiveComp"]["relic"]["relic"][key] = {"relicId": key, "enrollId": None,
            "isSpRelic": False, "relicGroupId": 2, "relicSortId": index, "orderId": str(index)}


def source():
    value = base_source()
    add_variant_conditions(value["details"]["rogue_1"])
    return value


def adapter(value):
    data = SimpleNamespace(table=lambda name: value, manifest={"hash": "a" * 64,
        "tables": {"roguelike_topic_table": "b" * 64}},
        rogue_topics=SimpleNamespace(topic=lambda key: key), rogue_ending_unlocks=load_base(value))
    data.rogue_relic_archive = FirstThemeRelicArchive(data)
    assert available(data)
    return FirstThemeEndingVariants(data)


def run(**changes):
    return replace(RunEndingVariant(completion(), "rogue_1_band_1", 0, 6, 1, 0), **changes)


@pytest.mark.parametrize("goal,band", BAND_GOALS.items())
def test_all_ten_band_identities_match_exactly_one_success_goal(goal, band):
    result = adapter(source()).evaluate((run(band=band),))
    assert {k for k, v in result.items() if v.current} == {goal}
    assert all(v.target == 1 for v in result.values())


@pytest.mark.parametrize("goal", THRESHOLDS)
def test_each_threshold_is_inclusive_and_uses_one_complete_run(goal):
    rules = adapter(source())
    field, target, _ = THRESHOLDS[goal]
    changes = {field: target}
    if field == "hope_left":
        changes["hope_max"] = target
    at = run(**changes)
    below = replace(at, **{field: target - 1})
    assert rules.evaluate((at,))[goal].wire() == {"state": 1, "progress": [1, 1]}
    assert rules.evaluate((below, below))[goal].wire() == {"state": 0, "progress": [0, 1]}


@pytest.mark.parametrize("ending", ["ro_ending_" + str(i) for i in range(1, 5)])
def test_all_valid_endings_qualify_but_easy_and_defeat_never_do(ending):
    rules = adapter(source())
    full = run(completion=completion(ending=ending), hope_left=8, hope_max=60, characters=15, gold=50)
    assert sum(v.current for v in rules.evaluate((full,)).values()) == 5
    for record in (completion(mode="EASY"), completion(success=0, ending=None)):
        assert not any(v.current for v in rules.evaluate((replace(full, completion=record),)).values())


@pytest.mark.parametrize("damage", ["name", "type", "band_id", "description", "special", "enrollment", "missing"])
def test_changed_catalog_or_partial_family_is_rejected(damage):
    value = source()
    detail = value["details"]["rogue_1"]
    if damage in ("name", "type", "band_id"):
        detail["items"]["rogue_1_band_1"]["id" if damage == "band_id" else damage] = "changed"
    elif damage == "description":
        detail["items"]["rogue_1_relic_q05"]["unlockCondDesc"] += "changed"
    elif damage == "missing":
        del detail["archiveComp"]["relic"]["relic"]["rogue_1_relic_q05"]
    else:
        detail["archiveComp"]["relic"]["relic"]["rogue_1_relic_q05"][
            "isSpRelic" if damage == "special" else "enrollId"] = True if damage == "special" else "rogue_1_enroll_2"
    with pytest.raises(ValueError):
        adapter(value)


@pytest.mark.parametrize("changes", [{"band": "rogue_2_band_1"}, {"hope_left": True},
    {"hope_left": 7}, {"hope_max": -1}, {"characters": False}, {"gold": 2**31},
    {"completion": completion(success=True)}, {"completion": completion(success=0)}])
def test_malformed_or_inconsistent_ending_facts_never_unlock(changes):
    with pytest.raises(ValueError):
        adapter(source()).evaluate((run(**changes),))


def test_results_and_carrier_are_immutable_and_old_catalog_has_no_new_capability():
    record = run()
    with pytest.raises(FrozenInstanceError):
        record.gold = 50
    rules = adapter(source())
    with pytest.raises(TypeError):
        rules.evaluate((record,))["rogue_1_relic_a03"] = None
    value = base_source()
    assert not available(SimpleNamespace(table=lambda name: value, manifest={
        "tables": {"roguelike_topic_table": "b" * 64}}))
    with pytest.raises(ValueError):
        rules.evaluate([record])
    assert rules.evaluate((record,)) == rules.evaluate((copy.deepcopy(record),))


def test_new_notification_respects_existing_acquisition_and_legacy_twenty_id_policy():
    from terralocal.server.domain import rogue_completion_rewards as rewards
    from terralocal.server.domain.errors import DomainError

    table = source()
    variants = adapter(table)
    data = SimpleNamespace(rogue_ending_unlocks=variants.base, rogue_ending_variants=variants,
        rogue_relic_archive=FirstThemeRelicArchive(SimpleNamespace(table=lambda name: table,
            manifest={"hash": "a" * 64}, rogue_topics=SimpleNamespace(topic=lambda key: key))))
    current = SimpleNamespace(id="current", account_id=1, topic_id="rogue_1", mode="NORMAL", grade=0,
        created_at=200, band_id="rogue_1_band_1", hope_max=60, hope_cost=52, gold=50)
    known = {"ended": 500, "success": 1, "ending": "ro_ending_1", "counts": [0, 0, 0, 0, 0, 0, 15]}
    legacy = rewards.notification(data, current, known, "base", ())
    assert len(legacy["unlocks"]) == 20 and "variant_rules" not in legacy and "attained" not in legacy
    fresh = rewards.notification(data, current, known, "base", (), policy=rewards.VARIANT_POLICY)
    assert len(fresh["unlocks"]) == 25
    found = rewards.notification(data, current, known, "base", (), policy=rewards.VARIANT_POLICY,
                                 attained=("rogue_1_relic_r28",))
    assert len(found["unlocks"]) == 24 and "rogue_1_relic_r28" not in found["unlocks"]
    assert found["attained"] == ["rogue_1_relic_r28"]
    score = SimpleNamespace(updates=[{"updateTime": 0, "endTime": -1, "maxBpCount": 2000}], grow_cap=1900)
    bonus, gp = rewards.grant(score, known | {"notification": found}, {"bp": 0, "grow": 0}, max_items=34)
    assert bonus == {"cnt": 600, "from": 0, "to": 600} and gp == 60
    with pytest.raises(DomainError) as error:
        rewards.grant(score, known | {"notification": found}, {"bp": 0, "grow": 0})
    assert error.value.code == "ROGUE_COMPLETION_REWARD_INCOMPATIBLE"


@pytest.mark.parametrize("damage", ["same_start", "future", "owner", "active", "zero_cooldown"])
def test_attainment_boundary_never_guesses_uuid_order_or_accepts_unclosed_prior_runs(damage):
    from terralocal.server.domain.errors import DomainError
    from terralocal.server.domain.rogue_ending_variants import boundary

    target = SimpleNamespace(id="target", account_id=1, topic_id="rogue_1", created_at=500, state="MAP_READY")
    old = SimpleNamespace(id="earlier", account_id=1, topic_id="rogue_1", created_at=100, state="ABANDONED")
    data = SimpleNamespace(rogue_initial=SimpleNamespace(cooldown=60))
    boundary(data, target, [old, target])
    if damage == "same_start":
        old.created_at = target.created_at
    elif damage == "future":
        old.created_at = target.created_at + 60
    elif damage == "owner":
        old.account_id = 2
    elif damage == "active":
        old.state = "MAP_READY"
    else:
        data.rogue_initial.cooldown = 0
    with pytest.raises(DomainError):
        boundary(data, target, [old, target])
