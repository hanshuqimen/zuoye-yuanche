"""Pure shop payment/stock replay, used by the owned transaction adapter.

No HTTP route, account mutation, database write or reward is performed here.
The caller must bind an admitted quote to an owned node, journal purchases and
apply their admitted effects atomically before publishing a response. A
non-ticket receipt has no ticket index; it never reserves an empty ticket.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_shops import Shop


@dataclass(frozen=True)
class Purchase:
    index: str
    at: int
    ticket: int | None


@dataclass(frozen=True)
class State:
    gold: int
    purchases: tuple[Purchase, ...] = ()
    ended_at: int | None = None


def invalid():
    return DomainError("ROGUE_SHOP_INCOMPATIBLE", "商店报价或交易记录不一致；请保留原存档", 503)


def replay(shop: Shop, gold: int, entered_at: int, first_ticket: int,
           purchases: tuple[Purchase, ...], ended_at: int | None = None) -> State:
    """Reject corrupt stock, payments, time order and reward ordinal bindings."""
    if (type(gold) is not int or not 0 <= gold < 2**31
            or type(entered_at) is not int or not 0 <= entered_at < 2**63
            or type(first_ticket) is not int or not 3 <= first_ticket < 2**31
            or type(purchases) is not tuple or len(purchases) > len(shop.offers)
            or type(shop.ticket_indices) is not frozenset or not shop.ticket_indices <= shop.offers.keys()
            or type(shop.support_indices) is not frozenset or not shop.support_indices <= shop.offers.keys()
            or shop.support_indices & shop.ticket_indices
            or any(shop.offers[i].relic_layer is not None for i in shop.support_indices)
            or not isinstance(shop.gold_gains, Mapping) or not shop.gold_gains.keys() <= shop.offers.keys()
            or any(index in shop.ticket_indices or shop.offers[index].relic_layer != 0
                   or type(amount) is not int or not 0 < amount < 2**31
                   for index, amount in shop.gold_gains.items())):
        raise invalid()
    seen, boundary, balance, ticket_count = set(), entered_at, gold, 0
    for purchase in purchases:
        if (not isinstance(purchase, Purchase) or type(purchase.index) is not str
                or purchase.index not in shop.offers or purchase.index in seen
                or type(purchase.at) is not int
                or not boundary <= purchase.at < 2**63):
            raise invalid()
        if purchase.index in shop.ticket_indices:
            if (type(purchase.ticket) is not int or purchase.ticket != first_ticket + ticket_count
                    or purchase.ticket >= 2**31):
                raise invalid()
            ticket_count += 1
        elif purchase.ticket is not None:
            raise invalid()
        price = shop.offers[purchase.index].price
        if price > balance:
            raise invalid()
        seen.add(purchase.index)
        # A reward cannot finance its own upfront price. Apply it only after
        # paying this unique stock slot, including interleaved bank replay.
        boundary, balance = purchase.at, balance - price + shop.gold_gains.get(purchase.index, 0)
        if balance >= 2**31:
            raise invalid()
    if ended_at is not None and (type(ended_at) is not int or not boundary <= ended_at < 2**63):
        raise invalid()
    return State(balance, purchases, ended_at)


def decide(shop: Shop, gold: int, entered_at: int, first_ticket: int,
           purchases: tuple[Purchase, ...], ended_at: int | None, *, buy: tuple[str, ...],
           recycle: tuple[str, ...], leave: int, at: int, recruit_pending: bool = False) -> State:
    """One observed buy or leave branch; retries never spend/grant twice.

    Recycling, mixed actions and bulk purchases are explicitly unsupported.
    A clock rewind is bounded by the last committed operation. A purchased
    ticket must be resolved before another purchase or leaving the node.
    """
    state = replay(shop, gold, entered_at, first_ticket, purchases, ended_at)
    if (type(buy) is not tuple or type(recycle) is not tuple
            or any(type(v) is not str or not 1 <= len(v) <= 128 for v in buy + recycle)
            or type(leave) is not int or leave not in (0, 1)
            or type(at) is not int or not 0 <= at < 2**63 or type(recruit_pending) is not bool):
        raise DomainError("ROGUE_SHOP_ACTION", "商店操作格式无效")
    if recycle or len(buy) > 1 or leave and buy:
        raise DomainError("ROGUE_SHOP_BRANCH", "此商店交易分支尚未接通，未扣款或发奖", 501)
    boundary = max([entered_at, *(p.at for p in purchases)])
    if leave:
        if state.ended_at is not None:
            return state
        if recruit_pending:
            raise DomainError("ROGUE_RECRUIT_PENDING", "请先处理当前招募", 409)
        return State(state.gold, state.purchases, max(at, boundary))
    if len(buy) != 1:
        raise DomainError("ROGUE_SHOP_ACTION", "请选择明确的购买或离开操作")
    index = buy[0]
    if index not in shop.offers:
        raise DomainError("ROGUE_SHOP_GOOD", "商品不属于此商店")
    if state.ended_at is not None:
        raise DomainError("ROGUE_SHOP_CLOSED", "已经离开此商店", 409)
    if any(p.index == index for p in purchases):
        return state  # New sequence retries the original one-stock purchase.
    if recruit_pending:
        raise DomainError("ROGUE_RECRUIT_PENDING", "请先处理当前招募", 409)
    if shop.offers[index].price > state.gold:
        raise DomainError("ROGUE_SHOP_GOLD", "源石锭不足，未购买商品", 409)
    ticket = first_ticket + sum(p.ticket is not None for p in purchases) if index in shop.ticket_indices else None
    updated = purchases + (Purchase(index, max(at, boundary), ticket),)
    return replay(shop, gold, entered_at, first_ticket, updated)
