"""Counterexamples for the frozen native bank-reward notice consumer."""

import copy

import pytest

from terralocal.server.gamedata.rogue_bank import FirstThemeBankRules
from tests.test_rogue_bank_rules import bank, fixture_data


@pytest.mark.parametrize("count,expected", [(24, False), (25, True), (26, False), (999, False)])
def test_notice_requires_exact_threshold_not_high_balance_or_an_earlier_missing_key(count, expected):
    rules = FirstThemeBankRules(fixture_data()[0])
    value = bank(current=0, record=count, totalPut=2000)
    before = copy.deepcopy(value)
    assert rules.has_new_reward(value) is expected
    assert value == before


@pytest.mark.parametrize("key,value", [("extra-a", 0), ("item-a", 1), ("withdraw", 0)])
def test_all_reward_kinds_use_membership_even_when_saved_value_is_zero(key, value):
    rules = FirstThemeBankRules(fixture_data()[0])
    count = rules.rewards[key].threshold
    snapshot = bank(current=0, record=count)
    assert rules.has_new_reward(snapshot) is True
    assert rules.has_new_reward(snapshot | {"reward": {key: value}}) is False
    # Other claimed rewards cannot consume the current reward's notification.
    other = "extra-b" if key != "extra-b" else "extra-a"
    assert rules.has_new_reward(snapshot | {"reward": {other: 0}}) is True


def test_counter_selection_null_and_hidden_bank_are_distinct_from_notice_gates():
    record = FirstThemeBankRules(fixture_data()[0])
    cumulative = FirstThemeBankRules(fixture_data("TOTAL_SUM")[0])
    value = bank(show=False, current=0, record=25, totalPut=26)
    assert record.has_new_reward(value) is True
    assert cumulative.has_new_reward(value) is False
    value = bank(current=0, record=24, totalPut=25)
    assert record.has_new_reward(value) is False
    assert cumulative.has_new_reward(value) is True
    assert record.has_new_reward(None) is False


def test_multiple_rewards_at_same_threshold_do_not_hide_an_unseen_key():
    data, detail = fixture_data()
    detail["bankRewards"].append({"rewardId": "extra-c", "rewardType": "ADD_SHOP_POS", "unlockGoldCnt": 25})
    rules = FirstThemeBankRules(data)
    value = bank(record=25, current=0, reward={"extra-a": 0})
    assert rules.has_new_reward(value) is True
    assert rules.has_new_reward(value | {"reward": {"extra-a": 0, "extra-c": 0}}) is False


@pytest.mark.parametrize("change", [{"record": True}, {"reward": {"unknown": 1}}, {"current": 501}])
def test_invalid_snapshot_is_not_downgraded_to_a_successful_empty_notice(change):
    with pytest.raises(ValueError):
        FirstThemeBankRules(fixture_data()[0]).has_new_reward(bank(**change))
