"""Static calendar selection policy, not observed official server behavior."""

import copy

import pytest
from test_campaign_catalog import campaign_tables

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.campaigns import validate_campaigns


@pytest.mark.parametrize("now,permanent,rotate,training", [
    (9, False, False, False), (10, True, False, False), (19, True, False, False),
    (20, True, True, False), (21, False, True, False), (29, False, True, False),
    (30, False, True, True), (31, False, False, True), (40, False, False, True), (41, False, False, False),
])
def test_inclusive_endpoints_and_gaps(now, permanent, rotate, training):
    opening = validate_campaigns(campaign_tables()).opening(now)
    assert bool(opening.permanent) is permanent
    assert bool(opening.active_group) is permanent
    assert bool(opening.rotate) is rotate
    assert bool(opening.rotate_group) is rotate
    assert bool(opening.training) is training
    assert bool(opening.training_group) is training


def test_adjacent_rotation_switches_without_overlap_or_old_stage_leak():
    tables = campaign_tables()
    rows = tables["campaign_table"]["campaignRotateStageOpenTimes"]
    rows.append({**rows[0], "groupId": "next_rotation", "startTs": 31, "endTs": 40})
    tables["campaign_table"]["campaignTrainingAllOpenTimes"] = [
        {"groupId": "all_training", "startTs": 35, "endTs": 45}]
    catalog = validate_campaigns(tables)
    assert catalog.opening(30).rotate_group == "rotate_synthetic"
    assert catalog.opening(31).rotate_group == "next_rotation"
    assert catalog.opening(35).training_all_group == "all_training"
    assert catalog.opening(45).training_all_group == "all_training"
    assert catalog.opening(46).training_all_group is None
    with pytest.raises(TypeError):
        catalog.introduced["unverified"] = 0
    with pytest.raises(TypeError):
        catalog.schedules["rotate"] = ()


@pytest.mark.parametrize("section", ["campaignGroups", "campaignRotateStageOpenTimes", "campaignTrainingStageOpenTimes", "campaignTrainingAllOpenTimes"])
@pytest.mark.parametrize("fault", ["overlap", "duplicate_id"])
def test_ambiguous_windows_are_rejected(section, fault):
    tables = campaign_tables()
    rows = tables["campaign_table"][section]
    if section == "campaignTrainingAllOpenTimes":
        rows.append({"groupId": "first_all", "startTs": 10, "endTs": 20})
    first = next(iter(rows.values())) if isinstance(rows, dict) else rows[0]
    duplicate = {**copy.deepcopy(first), "groupId": "new_group", "startTs": first["endTs"], "endTs": first["endTs"] + 10}
    if fault == "duplicate_id":
        duplicate.update(groupId=first["groupId"], startTs=first["endTs"] + 1)
    if isinstance(rows, dict):
        if fault == "duplicate_id":
            # Dict keys are unique; inconsistent embedded identifiers must fail.
            rows["new_group"] = duplicate
        else:
            rows[duplicate["groupId"]] = duplicate
    else:
        rows.append(duplicate)
    with pytest.raises(ValueError, match="campaign_table"):
        validate_campaigns(tables)


@pytest.mark.parametrize("value", [True, -1, 2.5, "20", 253_402_272_000])
def test_invalid_calendar_timestamp_is_not_coerced(value):
    with pytest.raises(DomainError) as error:
        validate_campaigns(campaign_tables()).opening(value)
    assert error.value.code == "INVALID_CAMPAIGN_TIME"
