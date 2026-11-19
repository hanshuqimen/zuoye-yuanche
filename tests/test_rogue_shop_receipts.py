"""Mixed receipt contracts and rejection of missing acquisition facts."""

from dataclasses import replace
from types import MappingProxyType

import pytest
from test_rogue_shop import data

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_shop import Purchase, decide, replay
from terralocal.server.gamedata.rogue_shops import Offer, Shop, compile_shop


def mixed():
    # Pure synthetic effect-contract fixture, deliberately not compile_shop:
    # the actual compiler must keep rejecting relics until the grant exists.
    offers = tuple(Offer(index, "synthetic-" + index, price)
                   for index, price in (("r1", 1), ("t1", 2), ("r2", 3), ("t2", 4)))
    return Shop("synthetic", "a" * 64, "gold", MappingProxyType({o.index: o for o in offers}),
                "b" * 64, "Pure receipt fixture; not an admitted game stock", frozenset({"t1", "t2"}))


def buy(q, purchases, index, *, at=100, pending=False):
    return decide(q, 10, 90, 3, purchases, None, buy=(index,), recycle=(), leave=0,
                  at=at, recruit_pending=pending)


def test_interleaved_same_second_receipts_preserve_ticket_sequence_and_full_payment_order():
    q, purchases = mixed(), ()
    for index in ("r1", "t1", "r2", "t2"):
        state = buy(q, purchases, index)
        purchases = state.purchases
    assert purchases == (Purchase("r1", 100, None), Purchase("t1", 100, 3),
                         Purchase("r2", 100, None), Purchase("t2", 100, 4))
    assert state.gold == 0 and replay(q, 10, 90, 3, purchases) == state
    assert tuple(p.index for p in purchases) == ("r1", "t1", "r2", "t2")


def test_non_ticket_retry_after_later_ticket_does_not_spend_or_allocate_again():
    q = mixed()
    first = buy(q, (), "r1")
    second = buy(q, first.purchases, "t1")
    assert buy(q, second.purchases, "r1", at=200, pending=True) == second
    with pytest.raises(DomainError, match="当前招募"):
        buy(q, second.purchases, "r2", pending=True)


def test_clock_rewind_does_not_reorder_effects_or_allocate_non_ticket_indices():
    q = mixed()
    first = buy(q, (), "r1", at=110)
    second = buy(q, first.purchases, "r2", at=80)
    third = buy(q, second.purchases, "t1", at=70)
    assert [p.at for p in third.purchases] == [110, 110, 110]
    assert [p.ticket for p in third.purchases] == [None, None, 3]


@pytest.mark.parametrize("purchases", [
    (Purchase("r1", 100, 3),), (Purchase("r1", 100, True),),
    (Purchase("t1", 100, None),), (Purchase("t1", 100, True),),
    (Purchase("r1", 100, None), Purchase("t1", 100, 4)),
    (Purchase("t1", 100, 3), Purchase("r1", 100, None), Purchase("t2", 100, 5)),
    (Purchase("r1", 100, None), Purchase("r1", 100, None)),
])
def test_wrong_effect_kind_ticket_gaps_and_duplicate_effects_are_corrupt_history(purchases):
    with pytest.raises(DomainError):
        replay(mixed(), 10, 90, 3, purchases)


@pytest.mark.parametrize("indices", [{"t1"}, frozenset({"unknown"})])
def test_ambiguous_or_unbound_reward_classification_is_rejected(indices):
    with pytest.raises(DomainError):
        replay(replace(mixed(), ticket_indices=indices), 10, 90, 3, ())


def test_all_existing_compiled_tickets_are_classified_from_the_imported_kind():
    d = data()
    offers = tuple(Offer(str(i), key, 1) for i, key in enumerate(d.rogue_recruit.tickets))
    q = compile_shop(d, "existing", offers, evidence="QA ordinary class coverage")
    assert q.ticket_indices == frozenset(q.offers)


@pytest.mark.parametrize("key", ["rogue_1_relic_r25", "rogue_1_relic_r26", "rogue_1_relic_r27", "rogue_1_relic_r28"])
def test_relic_admission_requires_an_explicit_supported_layer_contract(key):
    d = data()
    d.table("roguelike_topic_table")["details"]["rogue_1"]["items"][key] = {"type": "RELIC"}
    with pytest.raises(ValueError, match="无叠层"):
        compile_shop(d, "not-enabled", (Offer("r", key, 1),), evidence="Must not grant unknown effects")
