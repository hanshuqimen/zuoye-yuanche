"""Dispatch owned virtual payment quotes without consulting financial APIs."""
from sqlalchemy import select

from terralocal.server.domain import cash_shop, gift_packs, sdk
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.voucher_shop import check_bans
from terralocal.server.persistence import models as m


def handler(ctx, order_id):
    cash = ctx.session.get(m.LocalCashOrder, (ctx.account_id, order_id))
    pack = ctx.session.get(m.LocalPackOrder, (ctx.account_id, order_id))
    if cash is not None and pack is not None:
        raise DomainError("INVALID_LOCAL_ORDER_STATE", "本地订单不能同时引用两类报价", 503)
    return gift_packs if pack is not None else cash_shop


def pair(ctx, order_id):
    return handler(ctx, order_id).pair(ctx, order_id)


def approve(ctx, order_id, extension):
    return handler(ctx, order_id).approve(ctx, order_id, extension)


def confirm(ctx, order_id, client_profile):
    return handler(ctx, order_id).confirm(ctx, order_id, client_profile)


def create(ctx, store_id, good_id, client_profile):
    pack_catalog = getattr(ctx.data, "gift_pack_catalog", None)
    is_pack = pack_catalog is not None and any(o.goodId == good_id for o in pack_catalog.all_offers())
    target = gift_packs if is_pack else cash_shop
    if is_pack:
        offer, _, _ = gift_packs.find(ctx, good_id)
        if offer.currencyUnit != "CASH" or offer.storeId != store_id:
            raise DomainError("UNKNOWN_CASH_GOOD", "组合包与冻结 SDK 商品标识不匹配", 404)
    else:
        source = getattr(ctx.data, "cash_shop_catalog", None)
        if source is None:
            raise DomainError("CASH_SHOP_NOT_READY", "请先导入匹配的本地源石目录", 503)
        if not source.active(ctx.now):
            raise DomainError("CASH_SUPPLY_CLOSED", "本地源石供给未开放", 409)
        if not any(o.goodId == good_id and o.storeId == store_id for o in source.offers):
            raise DomainError("UNKNOWN_CASH_GOOD", "商品与冻结 SDK 标识不匹配", 404)
    check_bans(ctx, good_id)
    # Recoverable approved orders are shared by the native payment center.
    # Do not mistake an unpaid pack quote for a legacy recovery fixture.
    pending = [order_id for order_id in sdk.unconfirmed_orders(ctx.session, ctx.account_id)
        if ctx.session.get(m.LocalCashOrder, (ctx.account_id, order_id)) is not None
        or ctx.session.get(m.LocalPackOrder, (ctx.account_id, order_id)) is not None]
    if pending:
        return {"result": 2, "orderId": "", "extension": "", "orderIdList": pending,
                "alertMinor": False, "errMsg": ""}
    rows = list(ctx.session.scalars(select(m.LocalOrder).where(
        m.LocalOrder.account_id == ctx.account_id, m.LocalOrder.state == "READY")))
    count = 0
    for row in rows:
        quote = (ctx.session.get(m.LocalCashOrder, (ctx.account_id, row.order_id))
                 or ctx.session.get(m.LocalPackOrder, (ctx.account_id, row.order_id)))
        if quote is not None and quote.approved_at is None and quote.expires_at <= ctx.now:
            row.state = "CANCELLED"
        else:
            count += 1
    if count >= 64:
        raise DomainError("TOO_MANY_LOCAL_ORDERS", "本地待处理订单数量已达上限", 409)
    return target.create(ctx, store_id, good_id, client_profile)
