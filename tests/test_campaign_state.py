"""Synthetic state exercises native cap UI semantics, not campaign awards."""

import copy

import pytest
from pydantic import ValidationError
from test_campaign_catalog import campaign_tables

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.campaigns import validate_campaigns
from terralocal.server.protocol.campaign_state import CampaignState, claimable_break_indices, fee_view


def player(*, current=0, total=1200, rotate="", statuses=None, kills=0):
    return {"campaignCurrentFee": current, "campaignTotalFee": total, "activeGroupId": "",
            "open": {"permanent": ["camp_synthetic"], "training": [], "rotate": rotate,
                     "rotateGroup": "", "trainingGroup": "", "trainingAllOpenGroup": ""},
            "missions": {}, "instances": {"camp_synthetic": {
                "maxKills": kills, "rewardStatus": [0, 0] if statuses is None else statuses}},
            "sweepMaxKills": {}}


def view(raw, tables=None, initial=1200):
    return fee_view(validate_campaigns(campaign_tables() if tables is None else tables),
                    CampaignState.model_validate(raw), initial_fee=initial)


def test_campaign_internal_shape_round_trip_and_sweep_kept_separate():
    raw = player(kills=6)
    raw["sweepMaxKills"] = {"camp_synthetic": 3}
    state = CampaignState.model_validate(raw)
    assert state.model_dump() == raw
    assert state.instances["camp_synthetic"].maxKills == 6
    assert state.sweepMaxKills["camp_synthetic"] == 3
    raw["unproven_field"] = 0
    with pytest.raises(ValidationError):
        CampaignState.model_validate(raw)
    del raw["unproven_field"]
    del raw["open"]["trainingAllOpenGroup"]
    with pytest.raises(ValidationError):
        CampaignState.model_validate(raw)


def test_native_open_aliases_preserve_values_and_reject_duplicate_names():
    raw = player(rotate="camp_synthetic")
    raw["open"].update(rotateGroup="rotate_synthetic", trainingGroup="training_synthetic",
                       trainingAllOpenGroup=None)
    expected = copy.deepcopy(raw)
    for internal, wire in (("rotateGroup", "rGroup"), ("trainingGroup", "tGroup"),
                           ("trainingAllOpenGroup", "tAllOpen")):
        expected["open"][wire] = expected["open"].pop(internal)
    assert CampaignState.model_validate(raw).model_dump(by_alias=True) == expected
    assert CampaignState.model_validate(expected).model_dump() == raw
    ambiguous = copy.deepcopy(expected)
    ambiguous["open"]["rotateGroup"] = "other_group"
    with pytest.raises(ValidationError):
        CampaignState.model_validate(ambiguous)


def test_null_reference_strings_are_kept_and_rotation_stays_closed():
    raw = player(statuses=[1, 1])
    raw["activeGroupId"] = None
    for field in ("rotate", "rotateGroup", "trainingGroup", "trainingAllOpenGroup"):
        raw["open"][field] = None
    raw["missions"]["mission_synthetic"] = 1
    assert CampaignState.model_validate(raw).model_dump() == raw
    derived = view(raw)
    assert derived.achievable_total == 1215
    assert not derived.has_unconfirmed_break_fee


def test_full_is_unlocked_cap_not_earned_weekly_amount():
    # Synthetic stage cap adds 15; this says nothing about battle orundum.
    assert view(player(current=0, total=1215)).is_full
    assert view(player(current=1200, total=1200)).is_full is False
    assert view(player(current=1215, total=1215)).is_full
    assert view(player(total=1216)).is_full
    assert view(player()).achievable_total == 1215


@pytest.mark.parametrize("kills,statuses,pending", [
    (2, [0, 0], False), (3, [0, 0], True), (3, [1, 0], False),
    (3, [-1, 0], False), (6, [-1, 0], True), (6, [1, 2], False),
    (6, [], False), (6, [1], False), (6, [0], True),
])
def test_cap_indicator_uses_exact_zero_and_requires_status_array_entry(kills, statuses, pending):
    assert view(player(kills=kills, statuses=statuses)).has_unconfirmed_break_fee is pending


@pytest.mark.parametrize("state,expected", [(None, False), (0, False), (1, True), (2, False)])
def test_rotation_counts_all_static_missions_but_only_complete_is_pending(state, expected):
    raw = player(rotate="camp_synthetic", statuses=[1, 1])
    if state is not None:
        raw["missions"]["mission_synthetic"] = state
    derived = view(raw)
    assert derived.achievable_total == 1216
    assert derived.has_unconfirmed_break_fee is expected
    raw["open"]["rotate"] = ""
    assert view(raw).achievable_total == 1215
    assert not view(raw).has_unconfirmed_break_fee


def test_unknown_and_missing_instances_keep_native_zero_contribution():
    raw = player(kills=6)
    raw["open"]["permanent"].append("removed_synthetic")
    del raw["instances"]["camp_synthetic"]
    derived = view(raw)
    assert derived.achievable_total == 1215
    assert not derived.has_unconfirmed_break_fee
    assert derived.unresolved_permanent_stages == ("removed_synthetic",)
    raw["open"]["permanent"] = ["removed_synthetic"]
    assert view(raw).achievable_total == 1200


def test_zero_fee_breaks_and_missions_do_not_signal_cap_claims():
    tables = campaign_tables()
    definition = tables["campaign_table"]["campaigns"]["camp_synthetic"]
    for ladder in definition["breakLadders"]:
        ladder["breakFeeAdd"] = 0
    tables["campaign_table"]["campaignMissions"]["mission_synthetic"]["breakFeeAdd"] = 0
    raw = player(rotate="camp_synthetic", kills=6)
    raw["missions"]["mission_synthetic"] = 1
    assert view(raw, tables).achievable_total == 1200
    assert not view(raw, tables).has_unconfirmed_break_fee


def test_rotation_training_and_unknown_player_missions_are_not_permanent_cap_upgrades():
    raw = player(rotate="camp_synthetic", kills=6)
    raw["open"]["permanent"] = []
    raw["open"]["training"] = ["camp_synthetic"]
    raw["missions"]["unknown_synthetic"] = 1
    derived = view(raw)
    assert derived.achievable_total == 1201
    assert not derived.has_unconfirmed_break_fee


def test_reward_list_can_offer_breaks_without_a_cap_hint():
    catalog = validate_campaigns(campaign_tables())
    state = CampaignState.model_validate(player(kills=6, statuses=[-1]))
    assert claimable_break_indices(catalog, state, "camp_synthetic") == (0, 1)
    assert not fee_view(catalog, state, initial_fee=1200).has_unconfirmed_break_fee
    state = CampaignState.model_validate(player(kills=3, statuses=[1]))
    assert claimable_break_indices(catalog, state, "camp_synthetic") == ()


def test_reward_list_missing_instance_and_zero_fee_rewards():
    tables = campaign_tables()
    for row in tables["campaign_table"]["campaigns"]["camp_synthetic"]["breakLadders"]:
        row["breakFeeAdd"] = 0
    catalog = validate_campaigns(tables)
    state = CampaignState.model_validate(player(kills=6))
    assert claimable_break_indices(catalog, state, "camp_synthetic") == (0, 1)
    state.instances.clear()
    assert claimable_break_indices(catalog, state, "camp_synthetic") == ()


def test_lookup_retains_inputs_and_immutable_mission_definitions():
    tables = campaign_tables()
    catalog = validate_campaigns(tables)
    raw = player(kills=6)
    state = CampaignState.model_validate(raw)
    before = copy.deepcopy(raw)
    fee_view(catalog, state, initial_fee=1200)
    assert state.model_dump() == raw == before
    with pytest.raises(TypeError):
        catalog.mission_fees["mission_synthetic"] = 99
    tables["campaign_table"]["campaignMissions"]["mission_synthetic"]["breakFeeAdd"] = 99
    assert catalog.mission_fees["mission_synthetic"] == 1


@pytest.mark.parametrize("path,value", [
    (("campaignCurrentFee",), True), (("campaignTotalFee",), -1),
    (("open", "permanent"), None), (("missions", "mission_synthetic"), True),
    (("missions", "mission_synthetic"), 3), (("missions", "mission_synthetic"), "1"),
    (("instances", "camp_synthetic", "maxKills"), -1),
    (("instances", "camp_synthetic", "rewardStatus"), None),
    (("instances", "camp_synthetic", "rewardStatus"), [False]),
    (("sweepMaxKills", "camp_synthetic"), True),
])
def test_invalid_sync_state_is_not_silently_repaired(path, value):
    raw = player()
    target = raw
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        CampaignState.model_validate(raw)


@pytest.mark.parametrize("initial", [-1, True, "1200", 2**31])
def test_invalid_initial_cap_fails_without_payout(initial):
    with pytest.raises(DomainError) as error:
        view(player(), initial=initial)
    assert error.value.code == "INVALID_CAMPAIGN_INITIAL_FEE" and error.value.status == 503


def test_cap_overflow_is_explicit():
    with pytest.raises(DomainError) as error:
        view(player(), initial=2**31 - 1)
    assert error.value.code == "CAMPAIGN_FEE_OVERFLOW" and error.value.status == 503
