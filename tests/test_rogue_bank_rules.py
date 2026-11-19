"""Bank-slot counterexamples from native consumers, separate from payments."""

import copy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from terralocal.server.gamedata.rogue_bank import FirstThemeBankRules


def fixture_data(counter="HIGHEST_RECORD"):
    # Authored small records, not copied client resources.
    detail = {"gameConst": {"goldItemId": "gold", "bankMaxGold": 999, "bankRewardCountType": counter},
        "items": {"gold": {"id": "gold", "type": "GOLD"}},
        "bankRewards": [{"rewardId": k, "rewardType": t, "unlockGoldCnt": n} for k, t, n in (
            ("extra-b", "ADD_SHOP_POS", 500), ("item-b", "UNLOCK_ITEM", 325),
            ("withdraw", "UNLOCK_WITHDRAW", 200), ("item-a", "UNLOCK_ITEM", 100),
            ("extra-a", "ADD_SHOP_POS", 25))]}
    return SimpleNamespace(rogue_topics=SimpleNamespace(topic=lambda _: None), manifest={"hash": "a" * 64},
        table=lambda _: {"details": {"rogue_1": detail}}), detail


def bank(**updates):
    return {"show": True, "current": 1, "record": 500, "totalPut": 2000, "reward": {}} | updates


def test_slot_keys_and_counter_are_distinct_from_balance_threshold_or_reward_value():
    rules = FirstThemeBankRules(fixture_data()[0])
    original = bank()
    assert rules.accumulated(original) == 500
    assert rules.locked_slots(original, normal_mode=True, has_boss=True) == 2
    # Even high balances do not manufacture a claimed reward ID.
    assert rules.locked_slots(bank(current=999, record=999), normal_mode=True, has_boss=True) == 2
    assert rules.locked_slots(bank(reward={"extra-a": 0}), normal_mode=True, has_boss=True) == 1
    assert rules.locked_slots(bank(reward={"extra-a": 0, "extra-b": 1}),
                              normal_mode=True, has_boss=True) == 0
    assert original == bank()


@pytest.mark.parametrize("normal,boss,show", [(False, True, True), (True, False, True), (True, True, False)])
def test_native_gates_suppress_lock_placeholders(normal, boss, show):
    rules = FirstThemeBankRules(fixture_data()[0])
    assert rules.locked_slots(bank(show=show), normal_mode=normal, has_boss=boss) == 0
    assert rules.locked_slots(None, normal_mode=True, has_boss=True) == rules.accumulated(None) == 0


def test_non_slot_rewards_do_not_remove_a_locked_slot_and_data_remains_immutable():
    data, detail = fixture_data()
    before = copy.deepcopy(detail)
    rules = FirstThemeBankRules(data)
    assert rules.locked_slots(bank(reward={"item-a": 1, "withdraw": 1}),
                              normal_mode=True, has_boss=True) == 2
    with pytest.raises(TypeError):
        rules.rewards["extra-a"] = None
    with pytest.raises(FrozenInstanceError):
        rules.rewards["extra-a"].threshold = 0
    assert detail == before


def test_cumulative_counter_is_independent_and_can_have_threshold_above_balance_cap():
    data, detail = fixture_data("TOTAL_SUM")
    detail["bankRewards"][0]["unlockGoldCnt"] = 1000
    assert FirstThemeBankRules(data).accumulated(bank()) == 2000
    assert FirstThemeBankRules(fixture_data()[0]).accumulated(bank(current=0)) == 500


@pytest.mark.parametrize("change", [
    {"show": 1}, {"current": True}, {"current": 501}, {"record": 1000}, {"totalPut": 499},
    {"reward": {"unknown": 1}}, {"reward": {"extra-a": True}}, {"reward": {"extra-a": -1}},
])
def test_invalid_bank_snapshot_never_becomes_an_unlocked_stock_limit(change):
    with pytest.raises(ValueError):
        FirstThemeBankRules(fixture_data()[0]).locked_slots(bank(**change), normal_mode=True, has_boss=True)


def test_missing_saved_fields_and_non_boolean_native_gates_are_rejected():
    rules = FirstThemeBankRules(fixture_data()[0])
    with pytest.raises(ValueError):
        rules.accumulated({})
    for context in ({"normal_mode": 1, "has_boss": True}, {"normal_mode": True, "has_boss": 0}):
        with pytest.raises(ValueError):
            rules.locked_slots(bank(), **context)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown", "boolean", "over_cap", "currency"])
def test_changed_or_incomplete_table_does_not_silently_receive_default_rules(kind):
    data, detail = fixture_data()
    if kind == "missing":
        del detail["gameConst"]["bankRewardCountType"]
    elif kind == "duplicate":
        detail["bankRewards"].append(copy.deepcopy(detail["bankRewards"][0]))
    elif kind == "unknown":
        detail["bankRewards"][0]["rewardType"] = "FUTURE_EFFECT"
    elif kind == "boolean":
        detail["bankRewards"][0]["unlockGoldCnt"] = True
    elif kind == "over_cap":
        detail["bankRewards"][0]["unlockGoldCnt"] = 1000
    else:
        detail["items"]["gold"]["type"] = "RELIC"
    with pytest.raises(ValueError):
        FirstThemeBankRules(data)
