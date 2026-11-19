"""Financial-order counterexamples; authored plans, no banking HTTP claims."""

import copy
import json
from dataclasses import replace

import pytest

from terralocal.server.domain import rogue_bank_ledger as ledger
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_shop import Purchase
from terralocal.server.gamedata.rogue_bank import FirstThemeBankRules
from tests.test_rogue_bank_rules import bank, fixture_data
from tests.test_rogue_shop import shop


def fixture(*, gold=6, initial=None, faulted=False, costs=(1, 2, 4, 8, 16, 32), **terms):
    data, _ = fixture_data()
    data.rogue_bank = FirstThemeBankRules(data)
    q = shop()  # Authored ticket quote sharing fixture data hash and currency.
    t = ledger.compile_terms(data, q, mode="NORMAL", grade=0, withdrawal_costs=costs,
        evidence="Explicit QA costs/availability, not an official bank appearance or fault probability",
        **({"bank_open": True, "allow_deposit": True, "allow_withdraw": True} | terms))
    b = initial if initial is not None else bank(current=200, record=500, reward={"withdraw": 0})
    scope = ledger.Scope(20, "751ac5ae-24fc-49fa-9d48-246c544c4201", "970d875c-40ec-4989-bb2f-07621a873009")
    args = (data.rogue_bank, q, t, b, gold, 90, 3, scope)
    j = ledger.begin(*args, faulted_before=faulted)
    return args, j, faulted


def act(f, *, kind, key="s1:1", at=100, index=None, fault_after=None, pending=False):
    args, j, faulted = f
    new, state = ledger.decide(*args, j, faulted_before=faulted, key=key, kind=kind,
        at=at, index=index, fault_after=fault_after, recruit_pending=pending)
    return (args, new, faulted), state


def restore(f):
    args, journal, faulty = f
    saved = json.loads(json.dumps(ledger.dump(journal)))
    return ledger.replay(*args, ledger.load(saved), faulted_before=faulty)


def test_interleaved_payments_preserve_order_and_shared_game_gold_across_json_reload():
    f = fixture(gold=5)
    original = copy.deepcopy(f[0][3])
    f, _ = act(f, kind="PUT", fault_after=False)
    with pytest.raises(DomainError) as failure:
        act(f, kind="BUY", index="a", key="s1:2")
    assert failure.value.code == "ROGUE_SHOP_GOLD"
    f, _ = act(f, kind="WITHDRAW", key="s1:2")
    f, state = act(f, kind="BUY", index="a", key="s1:3")
    assert state.gold == 0 and state.current == 200 and state.record == 500 and state.total_put == 2001
    assert state.purchases == (Purchase("a", 100, 3),)
    assert restore(f) == state and f[0][3] == original
    projected = state.bank_snapshot(original)
    assert projected["reward"] == {"withdraw": 0} and projected["totalPut"] == 2001
    projected["reward"]["extra-a"] = 1
    assert f[0][3] == original  # Returned projections cannot modify input reward keys.


def test_future_withdrawal_cannot_pay_for_an_earlier_unaffordable_purchase():
    f = fixture(gold=4)
    f, _ = act(f, kind="WITHDRAW")
    f, state = act(f, kind="BUY", index="a", key="s1:2")
    assert state.gold == 0
    q = f[1]
    reordered = replace(q, actions=q.actions[::-1])
    with pytest.raises(DomainError) as failure:
        ledger.replay(*f[0], reordered, faulted_before=False)
    assert failure.value.code == "ROGUE_BANK_LEDGER_INCOMPATIBLE"


def test_new_empty_deposit_requests_are_distinct_but_scoped_key_retry_never_rerolls():
    f = fixture()
    f, state = act(f, kind="PUT", fault_after=False)
    same, retry = act(f, kind="PUT", fault_after=True, at=120, pending=True)
    assert same == f and retry == state and not retry.faulty
    f, state = act(f, kind="PUT", key="s1:2", fault_after=False)
    assert state.gold == 4 and state.current == 202 and state.total_put == 2002
    with pytest.raises(DomainError) as failure:
        act(f, kind="WITHDRAW", key="s1:1")
    assert failure.value.code == "IDEMPOTENCY_CONFLICT"


def test_explicit_credited_then_faulted_outcome_survives_reload_and_next_visit():
    # This post-credit outcome is a trusted QA stimulus, not a discovered
    # official probability or proof of the real fault timing.
    f, state = act(fixture(), kind="PUT", fault_after=True)
    assert state.faulty and state.gold == 5 and state.current == 201
    with pytest.raises(DomainError, match="不能继续投资"):
        act(f, kind="PUT", key="s1:2", fault_after=False)
    f, state = act(f, kind="WITHDRAW", key="s1:2")
    assert state.faulty and state.gold == 6 and state.current == 200 and restore(f) == state
    next_visit = fixture(gold=state.gold, initial=state.bank_snapshot(f[0][3]), faulted=state.faulty)
    with pytest.raises(DomainError, match="不能继续投资"):
        act(next_visit, kind="PUT", fault_after=False)
    _, withdrawn = act(next_visit, kind="WITHDRAW")
    assert withdrawn.current == 199 and withdrawn.withdrawals == 1


def test_explicit_cost_schedule_caps_without_an_unbounded_shift_and_resets_per_visit():
    f = fixture(gold=0, initial=bank(current=999, record=999, reward={"withdraw": 1}))
    for n in range(8):
        f, state = act(f, kind="WITHDRAW", key=f"s1:{n}")
    assert state.current == 999 - (1 + 2 + 4 + 8 + 16 + 32 + 32 + 32)
    assert state.gold == state.withdrawals == 8 and state.record == 999 and state.total_put == 2000
    assert ledger.withdrawal_cost(f[0][2], 2**31) == 32
    other = fixture(gold=state.gold, initial=state.bank_snapshot(f[0][3]))
    _, again = act(other, kind="WITHDRAW")
    assert again.current == state.current - 1 and again.withdrawals == 1


def test_peak_and_total_deposits_remain_distinct_and_no_threshold_crossing_claims_reward():
    f = fixture(initial=bank(current=24, record=24, totalPut=24), allow_withdraw=False)
    f, state = act(f, kind="PUT", fault_after=False)
    assert (state.current, state.record, state.total_put) == (25, 25, 25)
    projected = state.bank_snapshot(f[0][3])
    assert projected["reward"] == {} and f[0][0].has_new_reward(projected)
    with pytest.raises(DomainError, match="未解锁"):
        act(f, kind="WITHDRAW", key="s1:2")
    # Having enough record/balance alone never creates a withdrawal permission.
    f = fixture(initial=bank(current=999, record=999, reward={}), allow_withdraw=False)
    with pytest.raises(DomainError, match="未解锁"):
        act(f, kind="WITHDRAW")


@pytest.mark.parametrize("rewards", [{}, {"withdraw": 0}, {"withdraw": 1}])
def test_reward_key_values_do_not_substitute_for_explicit_verified_withdraw_authorization(rewards):
    value = bank(current=200, record=200, reward=rewards)
    with pytest.raises(DomainError, match="未解锁"):
        act(fixture(initial=value, allow_withdraw=False), kind="WITHDRAW")
    # Forced QA authorization; this is not evidence that an earned real bank
    # may withdraw without a reward key. The persistent entitlement is pending.
    _, state = act(fixture(initial=value, allow_withdraw=True), kind="WITHDRAW")
    assert state.current == 199 and state.gold == 7


@pytest.mark.parametrize("initial,gold,kind,code", [
    (bank(current=999, record=999), 1, "PUT", "ROGUE_BANK_FULL"),
    (bank(totalPut=2**31 - 1), 1, "PUT", "ROGUE_BANK_FULL"),
    (bank(), 0, "PUT", "ROGUE_BANK_GOLD"),
    (bank(current=0, reward={"withdraw": 0}), 0, "WITHDRAW", "ROGUE_BANK_BALANCE"),
    (bank(current=200, reward={"withdraw": 0}), 2**31 - 1, "WITHDRAW", "ROGUE_BANK_GOLD_LIMIT"),
])
def test_limits_fail_before_any_new_journal_or_balance_is_returned(initial, gold, kind, code):
    f = fixture(initial=initial, gold=gold)
    before = ledger.dump(f[1])
    with pytest.raises(DomainError) as failure:
        act(f, kind=kind, fault_after=False if kind == "PUT" else None)
    assert failure.value.code == code and ledger.dump(f[1]) == before


def test_closed_bank_does_not_disable_ordinary_shop_payment_and_clock_rewind_is_bounded():
    f = fixture(bank_open=False, allow_deposit=False, allow_withdraw=False)
    f, state = act(f, kind="BUY", index="a", at=80)
    assert state.purchases == (Purchase("a", 90, 3),) and state.gold == 1
    with pytest.raises(DomainError, match="未开放"):
        act(f, kind="PUT", key="s1:2", fault_after=False)
    f, state = act(f, kind="LEAVE", key="s1:2", at=70)
    assert state.ended_at == 90 and restore(f) == state
    same, _ = act(f, kind="BUY", index="a", key="s1:1", at=200, pending=True)
    assert same == f
    same, _ = act(f, kind="LEAVE", key="s1:3")
    assert same == f
    with pytest.raises(DomainError, match="已经离开"):
        act(f, kind="WITHDRAW", key="s1:3")


def test_pending_recruit_blocks_new_money_operations_but_keeps_committed_stock_retry():
    f, _ = act(fixture(), kind="BUY", index="a")
    same, _ = act(f, kind="BUY", index="a", key="s1:2", pending=True)
    assert same == f
    for kind in ("PUT", "WITHDRAW", "LEAVE"):
        with pytest.raises(DomainError, match="当前招募"):
            act(f, kind=kind, key="s1:2", pending=True, fault_after=False if kind == "PUT" else None)


@pytest.mark.parametrize("change", ["bank", "quote", "cost", "time", "fault", "rules", "account", "run", "visit"])
def test_journal_cannot_move_to_different_balances_terms_source_or_initial_time(change):
    f, _ = act(fixture(), kind="PUT", fault_after=False)
    args, journal, faulty = f
    args = list(args)
    if change == "bank":
        args[3] = args[3] | {"current": 201}
    elif change == "quote":
        args[1] = replace(args[1], digest="b" * 64)
    elif change == "cost":
        args[2] = replace(args[2], withdrawal_costs=(7,))
    elif change == "time":
        args[5] += 1
    elif change == "fault":
        faulty = True
    elif change == "rules":
        args[2] = replace(args[2], rules_hash="c" * 64)
    elif change == "account":
        args[7] = replace(args[7], account_id=21)
    elif change == "run":
        args[7] = replace(args[7], run_id="751ac5ae-24fc-49fa-9d48-246c544c4202")
    else:
        args[7] = replace(args[7], visit_id="970d875c-40ec-4989-bb2f-07621a873008")
    with pytest.raises(DomainError):
        ledger.replay(*args, journal, faulted_before=faulty)


@pytest.mark.parametrize("change", ["extra", "missing", "future", "duplicate", "bool", "order", "post_close"])
def test_corrupt_or_future_saved_records_are_not_silently_repaired(change):
    f, _ = act(fixture(), kind="PUT", fault_after=False)
    saved = ledger.dump(f[1])
    if change == "extra":
        saved["actions"][0]["amount"] = 999
    elif change == "missing":
        del saved["actions"][0]["fault_after"]
    elif change == "future":
        saved["policy"] = "future-version"
    elif change == "duplicate":
        saved["actions"] += copy.deepcopy(saved["actions"])
    elif change == "bool":
        saved["actions"][0]["at"] = True
    elif change == "order":
        saved["actions"][0]["at"] = 89
    else:
        saved["actions"] = [ledger.dump(act(fixture(), kind="LEAVE")[0][1])["actions"][0],
                             saved["actions"][0] | {"key": "different"}]
    with pytest.raises(DomainError):
        ledger.replay(*f[0], ledger.load(saved), faulted_before=False)


@pytest.mark.parametrize("terms", [{"mode": "EASY"}, {"grade": True}, {"bank_open": 1},
    {"withdrawal_costs": ()}, {"withdrawal_costs": (0,)}, {"withdrawal_costs": (True,)},
    {"bank_open": False}, {"evidence": ""}])
def test_incomplete_or_unknown_terms_do_not_receive_implicit_costs_or_opening(terms):
    args = fixture()[0]
    d, _ = fixture_data()
    d.rogue_bank = args[0]
    values = {"mode": "NORMAL", "grade": 0, "bank_open": True, "allow_deposit": True,
        "allow_withdraw": True, "withdrawal_costs": (1, 2, 4, 8, 16, 32), "evidence": "Explicit QA"} | terms
    with pytest.raises(DomainError):
        ledger.compile_terms(d, args[1], **values)


@pytest.mark.parametrize("kwargs", [{"fault_after": None}, {"fault_after": 0}, {"at": True},
                                  {"key": ""}, {"key": "contains space"}])
def test_deposit_outcome_and_scoped_key_must_be_explicit(kwargs):
    with pytest.raises(DomainError):
        act(fixture(), **({"kind": "PUT", "fault_after": False} | kwargs))


@pytest.mark.parametrize("scope", [ledger.Scope(True, "x", "y"), ledger.Scope(0, "x", "y"),
    ledger.Scope(20, "not-a-run", "970d875c-40ec-4989-bb2f-07621a873009"), None])
def test_invalid_or_missing_owned_scope_cannot_begin_a_ledger(scope):
    args, _, _ = fixture()
    with pytest.raises(DomainError):
        ledger.begin(*args[:7], scope, faulted_before=False)
