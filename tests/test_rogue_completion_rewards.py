"""Causal ordering and one-time unlock rewards, with no native replay."""

import copy
from types import SimpleNamespace

import pytest
from test_rogue_ending_unlocks import load, source

from terralocal.server.domain import rogue_completion_rewards as rewards
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_collection import FirstThemeRelicArchive

LEGACY = frozenset({"legacy"})


def data():
    table = source()
    adapter = SimpleNamespace(table=lambda name: table, manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda key: key))
    return SimpleNamespace(rogue_ending_unlocks=load(table), rogue_relic_archive=FirstThemeRelicArchive(adapter))


def pair(name, n, *, policy="legacy", sequence=None, previous=None, at=None, success=0):
    run = SimpleNamespace(id=name, account_id=1, topic_id="rogue_1", created_at=at if at is not None else n,
                          mode="NORMAL", grade=0, state="SETTLED")
    known = {"ended": max(500, run.created_at), "success": success,
             "ending": "ro_ending_1" if success else None}
    if policy == rewards.POLICY:
        known["notification"] = {"sequence": sequence, "previous": previous}
    row = SimpleNamespace(run_id=name, rule_hash=name + "-hash", policy_version=policy, facts=known,
                          before={"balance": n}, after={"balance": n + 1})
    return run, row


def test_new_history_uses_bounded_predecessors_not_timestamp_or_uuid_order():
    old = pair("z-old", 0, at=1000)
    first = pair("z-new", 1, policy=rewards.POLICY, sequence=1,
                 previous={"run": "z-old", "hash": "z-old-hash"}, at=10)
    second = pair("a-new", 2, policy=rewards.POLICY, sequence=2,
                  previous={"run": "z-new", "hash": "z-new-hash"}, at=10)
    assert rewards.ordered_groups((second, first, old), LEGACY)[1, "rogue_1"] == (old, first, second)


@pytest.mark.parametrize("damage", ["sequence", "bool_sequence", "duplicate_sequence", "hash", "self",
    "missing_previous", "balance", "cross_account", "duplicate_id", "unknown_policy", "late_legacy"])
def test_broken_branched_or_cross_account_history_is_rejected(damage):
    old = pair("old", 0)
    new = pair("new", 1, policy=rewards.POLICY, sequence=1, previous={"run": "old", "hash": "old-hash"})
    entries = [old, new]
    note = new[1].facts["notification"]
    if damage in ("sequence", "bool_sequence"):
        note["sequence"] = True if damage == "bool_sequence" else 2
    elif damage == "duplicate_sequence":
        entries.append(pair("other", 2, policy=rewards.POLICY, sequence=1, previous=note["previous"]))
    elif damage == "hash":
        note["previous"]["hash"] = "changed"
    elif damage == "self":
        note["previous"] = {"run": "new", "hash": "new-hash"}
    elif damage == "missing_previous":
        del note["previous"]
    elif damage == "balance":
        new[1].before = {"balance": 9}
    elif damage == "cross_account":
        new[0].account_id = 2
    elif damage == "duplicate_id":
        entries.append(copy.deepcopy(new))
    elif damage == "unknown_policy":
        new[1].policy_version = "unknown"
    else:
        entries.append(pair("late", 2))
    with pytest.raises(DomainError):
        rewards.ordered_groups(entries, LEGACY)


def test_first_success_emits_twenty_ids_and_repeated_or_legacy_success_never_reemits():
    adapter = data()
    current, row = pair("current", 200, success=1)
    current.state = "MAP_READY"
    note = rewards.notification(adapter, current, row.facts, "legacy", ())
    assert len(note["unlocks"]) == 20 and len(set(note["unlocks"])) == 20
    assert note["sequence"] == 0 and note["previous"] is None
    old = pair("old", 200, success=1)
    # A legacy success already made these goals eligible; upgrading never
    # rewrites that immutable old response or grants it a retrospective payout.
    assert rewards.notification(adapter, current, row.facts, "legacy", (old,))["unlocks"] == []
    old[1].policy_version = rewards.POLICY
    old[1].facts["notification"] = note
    assert rewards.notification(adapter, current, row.facts, "legacy", (old,))["unlocks"] == []
    old[1].facts.update(success=0, ending=None)
    assert len(rewards.notification(adapter, current, row.facts, "legacy", (old,))["unlocks"]) == 20


@pytest.mark.parametrize("damage", ["account", "topic", "state", "self", "duplicate"])
def test_notification_prefix_requires_actual_owned_closed_history(damage):
    current, row = pair("current", 200, success=1)
    old = pair("old", 200)
    prefix = [old]
    if damage == "account":
        old[0].account_id = 2
    elif damage == "topic":
        old[0].topic_id = "rogue_2"
    elif damage == "state":
        old[0].state = "ABANDONED"
    elif damage == "self":
        prefix = [(current, row)]
    else:
        prefix.append(old)
    with pytest.raises(DomainError):
        rewards.notification(data(), current, row.facts, "legacy", tuple(prefix))


@pytest.mark.parametrize("bp,grow,n,cap,expected,gp", [
    (439, 43, 20, 2000, 500, 50), (9, 0, 1, 2000, 25, 3),
    (1999, 50, 20, 2000, 1, 1), (2100, 50, 20, 2000, 0, 0),
    (0, 1899, 20, 2000, 500, 1), (0, 1900, 20, 2000, 500, 0),
    (0, 0, 0, 2000, 0, 0),
])
def test_unlock_candles_respect_cap_preserve_old_excess_and_carry_inspiration(bp, grow, n, cap, expected, gp):
    score = SimpleNamespace(updates=[{"updateTime": 0, "endTime": -1, "maxBpCount": cap}], grow_cap=1900)
    known = {"ended": 500, "notification": {"unlocks": [str(i) for i in range(n)]}}
    bonus, gained_gp = rewards.grant(score, known, {"bp": bp, "grow": grow})
    assert bonus == {"cnt": expected, "from": bp, "to": bp + expected} and gained_gp == gp


@pytest.mark.parametrize("keys", [["same", "same"], list(map(str, range(21)))])
def test_reward_list_is_finite_and_never_accepts_duplicate_payout_ids(keys):
    score = SimpleNamespace(updates=[{"updateTime": 0, "endTime": -1, "maxBpCount": 2000}], grow_cap=1900)
    with pytest.raises(DomainError):
        rewards.grant(score, {"ended": 500, "notification": {"unlocks": keys}}, {"bp": 0, "grow": 0})
