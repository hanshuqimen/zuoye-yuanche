"""Pure quote/payment boundaries; no claim of HTTP or native shop acceptance."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_shop import Purchase, decide, replay
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.protocol.roguelike import ShopAction


def data():
    tickets = {"ticket_" + name: (name, ()) for name in (
        "guard", "sniper", "defender", "medic", "supporter", "caster", "specialist", "vanguard")}
    detail = {"gameConst": {"goldItemId": "gold"}, "items": {
        "gold": {"type": "GOLD"}, **{key: {"type": "RECRUIT_TICKET"} for key in tickets}}}
    return SimpleNamespace(manifest={"hash": "a" * 64}, rogue_recruit=SimpleNamespace(tickets=tickets, catalog=tickets),
                           table=lambda name: {"details": {"rogue_1": detail}})


def shop():
    return compile_shop(data(), "qa-shop", (Offer("a", "ticket_medic", 5), Offer("b", "ticket_caster", 2)),
                        evidence="Authored prices/stock; not an official pool or current opening rule")


def action(quote, *, gold=6, purchases=(), ended=None, buy=("a",), recycle=(), leave=0,
           at=100, pending=False):
    return decide(quote, gold, 90, 3, purchases, ended, buy=buy, recycle=recycle, leave=leave,
                  at=at, recruit_pending=pending)


def test_observed_request_is_strict_and_has_no_reward_price_fields():
    body = {"buy": ["qa-medic-1"], "recycle": [], "leave": 0}
    assert ShopAction.model_validate(body).model_dump() == body
    for bad in (body | {"price": 0}, body | {"leave": True}, body | {"leave": "0"},
                body | {"buy": [1]}, body | {"buy": [""]}):
        with pytest.raises(ValidationError):
            ShopAction.model_validate(bad)


def test_all_eight_ordinary_ticket_quotes_bind_data_and_remain_immutable():
    d = data()
    offers = tuple(Offer(str(n), key, n) for n, key in enumerate(d.rogue_recruit.tickets))
    q = compile_shop(d, "authored", offers, evidence="QA reference coverage only")
    assert len(q.offers) == 8 and q.data_hash == "a" * 64
    with pytest.raises(TypeError):
        q.offers["new"] = offers[0]
    assert q.digest != compile_shop(d, "authored", offers[::-1], evidence=q.evidence).digest
    d.manifest["hash"] = "b" * 64
    assert q.digest != compile_shop(d, "authored", offers, evidence=q.evidence).digest


@pytest.mark.parametrize("offers", [(), (Offer("a", "ticket_medic", -1),),
    (Offer("a", "ticket_medic", True),), (Offer("a", "ticket_medic", 2**31),),
    (Offer("a", "ticket_medic", 5), Offer("a", "ticket_caster", 2)),
    (Offer("a", "unknown-relic", 1),)])
def test_bad_stock_is_rejected_before_it_can_be_used(offers):
    with pytest.raises(ValueError):
        compile_shop(data(), "qa", offers, evidence="QA")


def test_purchase_uses_saved_price_and_retries_preserve_the_original_reward_binding():
    q = shop()
    first = action(q)
    assert first.gold == 1 and first.purchases == (Purchase("a", 100, 3),)
    assert action(q, purchases=first.purchases, at=200, pending=True) == first
    assert replay(q, 6, 90, 3, first.purchases) == first
    assert q.offers["a"].price == 5
    with pytest.raises(DomainError, match="源石锭不足"):
        action(q, purchases=first.purchases, buy=("b",))
    # The failed operation cannot consume another slot or allocate a ticket.
    assert replay(q, 6, 90, 3, first.purchases) == first


def test_exact_balance_and_free_offer_do_not_underflow_or_repeat_grant():
    q = shop()
    assert action(q, gold=5).gold == 0
    free = compile_shop(data(), "free-qa", (Offer("a", "ticket_medic", 0),), evidence="Explicit QA free quote")
    first = action(free, gold=0)
    assert first.gold == 0 and len(first.purchases) == 1
    assert action(free, gold=0, purchases=first.purchases) == first


def test_pending_recruit_prevents_new_purchase_and_leave_but_not_retry():
    q = shop()
    first = action(q, gold=7)
    for kwargs in ({"buy": ("b",)}, {"buy": (), "leave": 1}):
        with pytest.raises(DomainError, match="当前招募"):
            action(q, gold=7, purchases=first.purchases, pending=True, **kwargs)
    second = action(q, gold=7, purchases=first.purchases, buy=("b",), at=80)
    assert second.gold == 0 and second.purchases[-1] == Purchase("b", 100, 4)
    closed = action(q, gold=7, purchases=second.purchases, buy=(), leave=1, at=70)
    assert closed.ended_at == 100
    assert action(q, gold=7, purchases=closed.purchases, ended=100, buy=(), leave=1, at=300) == closed
    with pytest.raises(DomainError, match="已经离开"):
        action(q, gold=7, purchases=closed.purchases, ended=100)


@pytest.mark.parametrize("purchases,ended", [
    ((Purchase("a", 100, 3), Purchase("a", 101, 4)), None),
    ((Purchase("unknown", 100, 3),), None), ((Purchase("a", 100, 4),), None),
    ((Purchase("a", 89, 3),), None), ((Purchase("a", 100, 3),), 99),
    ((Purchase("a", 100, 3), Purchase("b", 101, 4)), None),
])
def test_corrupt_or_unpaid_history_is_rejected(purchases, ended):
    with pytest.raises(DomainError) as failure:
        replay(shop(), 6, 90, 3, purchases, ended)
    assert failure.value.code == "ROGUE_SHOP_INCOMPATIBLE"


@pytest.mark.parametrize("kwargs", [{"buy": ("a", "b")}, {"recycle": ("a",)},
                                  {"leave": 1}, {"buy": (), "recycle": ("a",)}])
def test_unimplemented_action_branches_never_become_empty_success(kwargs):
    with pytest.raises(DomainError) as failure:
        action(shop(), **kwargs)
    assert failure.value.status == 501


def test_unknown_item_empty_action_and_bool_leave_do_not_change_stock():
    for kwargs in ({"buy": ("unknown",)}, {"buy": ()}, {"leave": True}):
        with pytest.raises(DomainError):
            action(shop(), **kwargs)
    assert replay(shop(), 6, 90, 3, ()).gold == 6
