"""Finite completion-goal family; synthetic facts are not played victories."""

import copy
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from test_rogue_floor_unlocks import source as floor_source
from test_rogue_roster_unlocks import add_conditions as add_roster_conditions

from terralocal.server.gamedata.rogue_collection import FirstThemeRelicArchive
from terralocal.server.gamedata.rogue_ending_unlocks import (
    CONDITIONS,
    FirstThemeEndingUnlocks,
    RunCompletion,
    available,
)
from terralocal.server.gamedata.rogue_roster_unlocks import FirstThemeRosterUnlocks


def add_completion_conditions(detail):
    difficulties = copy.deepcopy(detail.get("difficulties", []))
    detail.setdefault("enrolls", {})
    detail.setdefault("archiveComp", {}).setdefault("relic", {}).setdefault("relic", {})
    add_roster_conditions(detail)
    if difficulties:
        if not any(r.get("modeDifficulty") == "EASY" and r.get("grade") == 0 for r in difficulties):
            difficulties.append({"modeDifficulty": "EASY", "grade": 0, "scoreFactor": 0.5, "bpValue": -50})
        for row in difficulties:
            if row.get("modeDifficulty") in ("EASY", "NORMAL") and row.get("grade") == 0:
                row.update(canUnlockItem=row["modeDifficulty"] == "NORMAL", enrollId=None)
        detail["difficulties"] = difficulties
    for index, (key, (description, enrollment)) in enumerate(CONDITIONS.items(), 400):
        detail["items"].setdefault(key, {"id": key, "type": "RELIC"})["unlockCondDesc"] = description
        detail["relics"].setdefault(key, {"id": key, "buffs": []})
        detail["relicParams"].setdefault(key, {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []})
        detail["archiveComp"]["relic"]["relic"][key] = {
            "relicId": key, "enrollId": enrollment, "isSpRelic": False,
            "relicGroupId": 2, "relicSortId": index, "orderId": str(index)}
        if enrollment is not None:
            detail["enrolls"][enrollment] = {"enrollId": enrollment,
                "enrollTime": 300 if enrollment.endswith("_2") else 400,
                "enrollNoticeEndTime": 401, "enrollType": "DLC" if enrollment.endswith("_2") else "REVIEW"}


def source():
    value = floor_source()
    add_completion_conditions(value["details"]["rogue_1"])
    return value


def load(value):
    data = SimpleNamespace(table=lambda name: value,
        manifest={"hash": "a" * 64, "tables": {"roguelike_topic_table": "b" * 64}},
        rogue_topics=SimpleNamespace(topic=lambda key: SimpleNamespace(start=100)),
        rogue_endings=SimpleNamespace(fingerprint="endings", finals={
            "stage_" + str(i): (None, None, "ro_ending_" + str(i)) for i in range(1, 5)}))
    data.rogue_relic_archive = FirstThemeRelicArchive(data)
    data.rogue_roster_unlocks = FirstThemeRosterUnlocks(data)
    assert available(data)
    return FirstThemeEndingUnlocks(data)


def run(**changes):
    return replace(RunCompletion("NORMAL", 0, 200, 500, 1, "ro_ending_1"), **changes)


@pytest.mark.parametrize("ending", ["ro_ending_" + str(i) for i in range(1, 5)])
def test_all_twenty_goals_accept_valid_success_identities_without_granting_items(ending):
    rules = load(source())
    result = rules.evaluate((run(ending=ending),))
    assert set(result) == set(CONDITIONS) and len(result) == 20
    assert all(value.wire() == {"state": 1, "progress": [1, 1]} for value in result.values())


@pytest.mark.parametrize("ended,base,dlc,review", [(299, 1, 0, 0), (300, 1, 1, 0),
    (399, 1, 1, 0), (400, 1, 1, 1), (700, 1, 1, 1)])
def test_per_item_enrollment_uses_completed_time_and_does_not_expire_at_notice_end(ended, base, dlc, review):
    rules = load(source())
    result = rules.evaluate((run(ended_at=ended),))
    assert result["rogue_1_relic_m16"].current == base
    assert result["rogue_1_relic_n02"].current == dlc
    assert result["rogue_1_relic_c07"].current == review


def test_defeat_easy_empty_or_pre_topic_runs_never_satisfy_completion_goals():
    rules = load(source())
    for runs in ((), (run(success=0, ending=None),), (run(mode="EASY"),), (run(started_at=99),)):
        assert all(value.current == 0 for value in rules.evaluate(runs).values())
    assert all(value.current == 1 for value in rules.evaluate((run(), run(), run())).values())


def test_mode_enrollment_uses_run_start_even_when_item_enrollment_has_opened():
    value = source()
    detail = value["details"]["rogue_1"]
    detail["difficulties"][1]["enrollId"] = "mode-review"
    detail["enrolls"]["mode-review"] = {"enrollId": "mode-review", "enrollTime": 450}
    rules = load(value)
    assert all(v.current == 0 for v in rules.evaluate((run(started_at=449),)).values())
    assert all(v.current == 1 for v in rules.evaluate((run(started_at=450),)).values())


@pytest.mark.parametrize("changes", [dict(success=True), dict(success=2), dict(ending=None),
    dict(ending=[]), dict(success=0), dict(ending="unknown"), dict(grade=True), dict(grade=1),
    dict(mode="MONTH_TEAM"), dict(started_at=True), dict(ended_at=True), dict(ended_at=199)])
def test_malformed_or_unadmitted_endings_are_rejected(changes):
    with pytest.raises(ValueError):
        load(source()).evaluate((run(**changes),))


@pytest.mark.parametrize("damage", ["description", "special", "missing", "enrollment", "time",
    "bool_time", "type", "missing_mode_gate"])
def test_changed_completion_contract_or_enrollment_is_not_silently_accepted(damage):
    value = source()
    detail = value["details"]["rogue_1"]
    key = "rogue_1_relic_n02"
    if damage == "description":
        detail["items"][key]["unlockCondDesc"] = "After any battle"
    elif damage == "special":
        detail["archiveComp"]["relic"]["relic"][key]["isSpRelic"] = True
    elif damage == "missing":
        del detail["archiveComp"]["relic"]["relic"][key]
    elif damage == "enrollment":
        detail["archiveComp"]["relic"]["relic"][key]["enrollId"] = None
    elif damage in ("time", "bool_time", "type"):
        field, changed = {"time": ("enrollTime", -1), "bool_time": ("enrollTime", True),
                          "type": ("enrollType", "REVIEW")}[damage]
        detail["enrolls"]["rogue_1_enroll_2"][field] = changed
    else:
        del detail["difficulties"][1]["canUnlockItem"]
    with pytest.raises(ValueError):
        load(value)


def test_compiled_conditions_and_results_are_immutable_and_no_generic_text_parser_is_enabled():
    value = source()
    detail = value["details"]["rogue_1"]
    detail["items"]["unmatched-prose"] = {"id": "unmatched-prose", "type": "RELIC",
                                             "unlockCondDesc": "完成游戏结局"}
    rules = load(value)
    detail["enrolls"]["rogue_1_enroll_2"]["enrollTime"] = 99999
    result = rules.evaluate((run(),))
    assert len(result) == 20 and result["rogue_1_relic_n02"].current == 1
    with pytest.raises(TypeError):
        rules.enrolled["new"] = 0
    with pytest.raises(FrozenInstanceError):
        result["rogue_1_relic_n02"].current = 0
