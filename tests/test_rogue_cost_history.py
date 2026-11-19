"""Offer-time history contracts; these do not exercise grants or native UI."""

from dataclasses import FrozenInstanceError

import pytest
from test_rogue_recruit_costs import R25, R26, R27, R28, load, source

from terralocal.server.domain.rogue_cost_history import (
    AcquireCostRelic as Acquire,
)
from terralocal.server.domain.rogue_cost_history import (
    OpenRecruitOffer as Open,
)
from terralocal.server.domain.rogue_cost_history import (
    RecruitCostHistory,
)


def history(events):
    return RecruitCostHistory(load(source()), events)


def price(value, ticket, *, operation="RECRUIT"):
    return value.quote(ticket, 3, profession="SNIPER", rarity="TIER_5", operation=operation)


def test_offer_before_between_and_after_relics_uses_transaction_order_without_a_clock():
    # All could occur within one clock tick; timestamps cannot resolve this.
    h = history((Open(0), Acquire(R26), Open(3), Acquire(R28), Open(4)))
    assert [price(h, i).total for i in (0, 3, 4)] == [3, 1, 0]
    assert [h.context(i).modifiers for i in (0, 3, 4)] == [(), (R26,), (R26, R28)]
    assert h.final_modifiers == (R26, R28)


def test_later_acquisition_and_reopen_preserve_old_offer_quote_and_prefix():
    prefix = (Acquire(R26), Open(7))
    old = history(prefix)
    new = history(prefix + (Acquire(R28), Open(8)))
    assert old.context(7) == new.context(7)
    assert price(old, 7) == price(new, 7)
    assert new.context(7) != new.context(8)
    assert history(prefix + (Acquire(R28), Open(8))).fingerprint == new.fingerprint


def test_ticket_created_earlier_can_open_later_without_backdating_its_cost_context():
    # Creation sequence and offer-open sequence need not be the same.
    h = history((Open(9), Acquire(R26), Open(3)))
    assert price(h, 9).total == 3 and price(h, 3).total == 1


def test_only_recruitment_changes_and_zero_cost_never_credits_hope():
    h = history((Acquire(R26), Acquire(R28), Open(3)))
    assert price(h, 3).total == 0
    assert price(h, 3, operation="UPGRADE").total == 3
    assert h.quote(3, 0, profession="SNIPER", rarity="TIER_5").total == 0


def test_nonmatching_relic_is_preserved_and_acquisition_order_binds_evidence():
    first = history((Acquire(R25), Acquire(R27), Open(3)))
    second = history((Acquire(R27), Acquire(R25), Open(3)))
    assert price(first, 3).total == price(second, 3).total == 3
    assert first.context(3).modifiers == second.context(3).modifiers == (R25, R27)
    assert first.context(3).prefix_hash != second.context(3).prefix_hash


def test_contexts_are_immutable_and_external_source_edits_cannot_reprice_them():
    table = source()
    h = RecruitCostHistory(load(table), (Acquire(R26), Open(3)))
    before = price(h, 3)
    table["details"]["rogue_1"]["relics"].clear()
    assert price(h, 3) == before
    with pytest.raises(TypeError):
        h.contexts[3] = None
    with pytest.raises(FrozenInstanceError):
        h.context(3).modifiers = ()


@pytest.mark.parametrize("events", [
    [Open(3)], ({"open": 3},), (None,), (Acquire(None),), (Acquire("unknown"),),
    (Acquire(R26), Acquire(R26)), (Open(3), Open(3)), (Open(True),), (Open(-1),),
    (Open(2**31),), (Open(3.0),), (Open("3"),), (Open(None),),
    tuple(Open(i) for i in range(260)),
])
def test_ambiguous_unknown_or_duplicate_history_fails_without_base_cost_fallback(events):
    with pytest.raises(ValueError):
        history(events)


@pytest.mark.parametrize("ticket", [0, 4, True, "3", 3.0, None])
def test_absent_or_untyped_offer_context_is_not_treated_as_an_unmodified_offer(ticket):
    h = history((Acquire(R26), Open(3)))
    with pytest.raises(ValueError):
        price(h, ticket)


def test_existing_ticket_budget_and_all_four_effects_are_admitted_together():
    events = tuple(Acquire(k) for k in (R25, R26, R27, R28)) + tuple(Open(i) for i in range(259))
    h = history(events)
    assert len(h.contexts) == 259 and price(h, 258).total == 0


def test_rules_are_required_even_for_empty_history():
    with pytest.raises(ValueError):
        RecruitCostHistory(None, ())
