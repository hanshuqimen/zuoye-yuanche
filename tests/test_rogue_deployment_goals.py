"""Matched deployment conditions; authored counters never claim native clears."""

import copy
import json
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from test_rogue_ending_variants import source as variant_source

from terralocal.server.domain import rogue_combat_records, rogue_deployment_goals
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_collection import FirstThemeRelicArchive
from terralocal.server.gamedata.rogue_deployment_goals import (
    GOALS,
    FirstThemeDeploymentGoals,
    RunDeployment,
    available,
)
from terralocal.server.gamedata.rogue_ending_unlocks import RunCompletion
from terralocal.server.protocol.rogue_battle_codec import decode_char_stats


def add_deployment_conditions(detail):
    for key, (name, n, sort, order) in GOALS.items():
        detail["items"][key] = {"id": key, "type": "RELIC", "name": name,
            "unlockCondDesc": f"累计在战斗中部署干员不小于{n}次的情况下完成游戏结局"}
        detail["relics"][key] = {"id": key, "buffs": []}
        detail["relicParams"][key] = {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []}
        detail["archiveComp"]["relic"]["relic"][key] = {"relicId": key, "enrollId": None,
            "isSpRelic": True, "relicGroupId": 7, "relicSortId": sort, "orderId": order}


def source():
    value = variant_source()
    add_deployment_conditions(value["details"]["rogue_1"])
    return value


def adapter(value):
    from test_rogue_ending_unlocks import load

    data = SimpleNamespace(table=lambda name: value, manifest={"hash": "a" * 64,
        "tables": {"roguelike_topic_table": "b" * 64}},
        rogue_topics=SimpleNamespace(topic=lambda key: key), rogue_ending_unlocks=load(value))
    data.rogue_relic_archive = FirstThemeRelicArchive(data)
    assert available(data)
    return FirstThemeDeploymentGoals(data)


def run(minimum=200, *, id="run-one", unknown=0, **completion):
    return RunDeployment(id, replace(RunCompletion("NORMAL", 0, 200, 500, 1, "ro_ending_1"), **completion), minimum, unknown)


@pytest.mark.parametrize("count,expected", [(0, set()), (99, set()), (100, {"rogue_1_relic_sp04"}),
    (199, {"rogue_1_relic_sp04"}), (200, set(GOALS)), (201, set(GOALS))])
def test_two_inclusive_thresholds_are_derived_from_one_success(count, expected):
    result = adapter(source()).evaluate((run(count),))
    assert {key for key, value in result.items() if value.current} == expected
    assert all(value.target == 1 for value in result.values())


def test_independent_runs_do_not_accumulate_and_unknown_is_only_a_lower_bound():
    rules = adapter(source())
    assert not any(v.current for v in rules.evaluate((run(99), run(99, id="run-two"))).values())
    assert rules.evaluate((run(100, unknown=1),))["rogue_1_relic_sp04"].current == 1
    assert rules.evaluate((run(0, unknown=1),))["rogue_1_relic_sp04"].current == 0
    with pytest.raises(ValueError):
        rules.evaluate((run(), run()))


@pytest.mark.parametrize("ending", ["ro_ending_" + str(i) for i in range(1, 5)])
def test_all_declared_endings_use_existing_mode_and_success_gates(ending):
    rules = adapter(source())
    assert all(v.current for v in rules.evaluate((run(ending=ending),)).values())
    for trial in (run(mode="EASY"), run(success=0, ending=None), run(started_at=0)):
        assert not any(v.current for v in rules.evaluate((trial,)).values())


@pytest.mark.parametrize("damage", ["name", "description", "special", "group", "sort", "order", "enroll", "missing"])
def test_partial_or_changed_special_family_never_uses_generic_defaults(damage):
    value = source()
    detail = value["details"]["rogue_1"]
    item = detail["items"]["rogue_1_relic_sp02"]
    archive = detail["archiveComp"]["relic"]["relic"]["rogue_1_relic_sp02"]
    if damage == "name":
        item["name"] = "other"
    elif damage == "description":
        item["unlockCondDesc"] += "other"
    elif damage == "missing":
        del detail["archiveComp"]["relic"]["relic"]["rogue_1_relic_sp04"]
    else:
        field, wrong = {"special": ("isSpRelic", False), "group": ("relicGroupId", 2),
            "sort": ("relicSortId", 4), "order": ("orderId", "PCS06"), "enroll": ("enrollId", "rogue_1_enroll_2")}[damage]
        archive[field] = wrong
    with pytest.raises(ValueError):
        adapter(value)


@pytest.mark.parametrize("field,value", [("minimum", True), ("minimum", -1), ("minimum", 51200001),
    ("minimum", "200"), ("unknown", True), ("unknown", -1), ("unknown", 513), ("id", "")])
def test_counter_facts_are_typed_and_bounded(field, value):
    with pytest.raises(ValueError):
        adapter(source()).evaluate((replace(run(), **{field: value}),))


def test_deployment_carrier_and_catalog_are_immutable_and_legacy_capability_is_unchanged():
    with pytest.raises(FrozenInstanceError):
        run().minimum = 0
    result = adapter(source()).evaluate((run(),))
    with pytest.raises(TypeError):
        result["rogue_1_relic_sp02"] = None
    assert not available(SimpleNamespace(table=lambda name: variant_source(),
        manifest={"tables": {"roguelike_topic_table": "b" * 64}}))


def scope_fixture():
    data = SimpleNamespace(manifest={"hash": "a" * 64})
    owner = SimpleNamespace(id="owned-run", account_id=1, gamedata_hash="a" * 64, topic_id="rogue_1")
    records, sources = [], []
    for index, count in enumerate((70, 40, None)):
        ident, facts = "battle-" + str(index), {"rank": 3, "journal": "b" * 64}
        record = SimpleNamespace(battle_id=ident, ordinal=index, run_id=owner.id, facts=facts)
        if count is None:
            kind, encoded = None, None
        else:
            pool = decode_char_stats({"charStats": [
                {"Key": {"charId": "synthetic-predefined-ally", "counterType": "SPAWN"}, "Value": count},
                {"Key": {"charId": "synthetic-predefined-ally", "counterType": "DEAD"}, "Value": 300}]})
            value = rogue_combat_records.archive(pool, battle_id=ident, run_id=owner.id,
                                                 gamedata_hash=owner.gamedata_hash, facts=facts)
            kind, encoded = "object", json.dumps(value)
        records.append(record)
        sources.append([ident, 1, owner.id, owner.gamedata_hash, "FINISHED", kind, encoded])
    return data, owner, records, sources


def test_same_run_ordered_bound_battles_accumulate_spawns_without_counting_deaths_or_inventing_old_stats():
    scope = rogue_deployment_goals._scope(*scope_fixture())
    assert scope["minimum"] == 110 and scope["unknown"] == 1
    assert scope["battles"][-1] == ["battle-2", None]


@pytest.mark.parametrize("damage", ["owner", "run", "data", "state", "order", "null", "counter"])
def test_foreign_reordered_or_damaged_battle_counters_cannot_support_an_unlock(damage):
    data, owner, records, sources = scope_fixture()
    if damage == "order":
        sources.reverse()
    elif damage == "null":
        sources[-1][-2:] = ["null", "null"]
    elif damage == "counter":
        value = json.loads(sources[0][-1])
        value["charStats"][0]["Value"] = 200
        sources[0][-1] = json.dumps(value)
    else:
        index, value = {"owner": (1, 2), "run": (2, "other"), "data": (3, "c" * 64), "state": (4, "STARTED")}[damage]
        sources[0][index] = value
    original = copy.deepcopy((records, sources))
    with pytest.raises(DomainError):
        rogue_deployment_goals._scope(data, owner, records, sources)
    assert sources == original[1]
