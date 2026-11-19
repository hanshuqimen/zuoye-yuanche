"""Ordinary GP transactions and native-shaped account purchase counters."""
import hashlib
import json
import secrets
import uuid

from pydantic import ValidationError
from sqlalchemy import and_, select

from terralocal.server.domain import cash_shop
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.voucher_shop import check_bans
from terralocal.server.gamedata.gift_packs import GiftPackOffer
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m


def catalog(ctx):
    source = getattr(ctx.data, "gift_pack_catalog", None)
    if source is None:
        raise DomainError("GIFT_PACKS_NOT_READY", "请先导入匹配版本的组合包目录", 503)
    return source


def find(ctx, good_id):
    entries = [(o, p, c) for o, p, c in catalog(ctx).active_entries(ctx.now) if o.goodId == good_id]
    if len(entries) != 1:
        raise DomainError("GIFT_PACK_UNAVAILABLE", "组合包不存在或不在销售期间", 404)
    return entries[0]


def counter(ctx, offer, period):
    row = ctx.session.get(m.ShopState, (ctx.account_id, "GP:" + offer.section, offer.goodId, period))
    bought = row.bought if row else 0
    if type(bought) is not int or not 0 <= bought <= 2_000_000_000:
        raise DomainError("INVALID_SHOP_STATE", "组合包购买计数无效", 503)
    return row, bought


def validate_purchase(ctx, offer, period, *, reservations=0):
    check_bans(ctx, offer.goodId)
    if offer.playerLevel is not None and ctx.profile.level < offer.playerLevel:
        raise DomainError("GIFT_PACK_LEVEL_LOCKED", "此等级组合包尚未解锁", 409)
    _, bought = counter(ctx, offer, period)
    if bought + reservations + 1 > 2_000_000_000 or (
            offer.availCount != -1 and bought + reservations + 1 > offer.availCount):
        raise DomainError("GOOD_SOLD_OUT", "组合包已达到限购次数", 409)
    return bought


def record(ctx, offer, period, cost):
    row, bought = counter(ctx, offer, period)
    if row is None:
        row = m.ShopState(account_id=ctx.account_id, shop_id="GP:" + offer.section,
                          offer_id=offer.goodId, period=period, bought=0)
        ctx.session.add(row)
    row.bought = bought + 1
    ctx.session.add(m.PurchaseHistory(account_id=ctx.account_id, shop_id="GP:" + offer.section,
        offer_id=offer.goodId, count=1, cost=cost, purchased_at=ctx.now))
    ctx.session.add(m.AuditLog(actor="local-client", account_id=ctx.account_id, action="gift-pack-purchase",
        detail={"goodId": offer.goodId, "section": offer.section, "period": period,
                "realPayment": False}, created_at=ctx.now))


def buy(ctx, good_id):
    offer, period, _ = find(ctx, good_id)
    if offer.currencyUnit == "CASH":
        raise DomainError("GIFT_PACK_REQUIRES_ORDER", "现金组合包需要本地 SDK 订单确认", 409)
    validate_purchase(ctx, offer, period)
    item_id = "4002"
    ctx.consume([{"id": item_id, "count": offer.price}])
    items = ctx.rewards([i.model_dump() for i in offer.items])
    record(ctx, offer, period, {"currencyUnit": offer.currencyUnit, "price": offer.price,
                               "catalog_hash": fingerprint(catalog(ctx).model_dump())})
    return {"items": items}


def project(ctx, at=None):
    """Only account progress; offer supply is returned by getGPGoodList."""
    now = ctx.now if at is None else at
    states = ctx.rows(m.ShopState)
    source = getattr(ctx.data, "gift_pack_catalog", None)
    periods = {"oneTime": "permanent", "level": "permanent", "choose": "permanent",
               "conditionChoose": "permanent", "weekly": ctx.clock.period("weekly", at=now),
               "monthly": ctx.clock.period("monthly", at=now)}
    if source:
        for cycle in source.cycles:
            if cycle.active(now):
                periods[cycle.section] = cycle.period
    return {section: {"info": [{"id": r.offer_id, "count": r.bought} for r in sorted(states,
                key=lambda r: r.offer_id) if r.shop_id == "GP:" + section and r.period == period],
                "valid": []} for section, period in periods.items()}


def list_goods(ctx):
    source = catalog(ctx)
    # The frozen InitData unconditionally calls both group consumers. They
    # dereference packages before iteration; null groups or null dictionaries
    # produce a native fault even when no periodic supply was admitted.
    def empty_group():
        return {"groupId": "", "startDateTime": 0, "endDateTime": 0, "packages": {}}

    result = {"weeklyGroup": empty_group(), "monthlyGroup": empty_group(), "monthlySub": [], "levelGP": [],
              "oneTimeGP": [], "chooseGroup": [], "condtionTriggerGroup": [], "conditionChooseGroup": []}
    for cycle in source.cycles:
        if cycle.active(ctx.now):
            result[cycle.section + "Group"] = {"groupId": cycle.groupId,
                "startDateTime": cycle.startDateTime, "endDateTime": cycle.endDateTime, "packages": {}}
    for offer, period, cycle in source.active_entries(ctx.now):
        _, bought = counter(ctx, offer, period)
        native = offer.native(bought, cycle.groupId if cycle else None)
        if cycle:
            result[cycle.section + "Group"]["packages"][offer.goodId] = native
        else:
            result[{"oneTime": "oneTimeGP", "level": "levelGP"}[offer.section]].append(native)
    return result


def purchase_limits(ctx, goods):
    source = getattr(ctx.data, "gift_pack_catalog", None)
    if source is None:
        return {}, set()
    active = {o.goodId: o for o, _, _ in source.active_entries(ctx.now)}
    known = {o.goodId for o in source.all_offers()}
    result, recognized = {}, set()
    for good_id in goods.get("GP", []):
        if good_id in known:
            offer = active.get(good_id)
            result[good_id] = (offer.availCount if offer and (offer.playerLevel is None
                or ctx.profile.level >= offer.playerLevel) else 0)
            recognized.add(("GP", good_id))
    return result, recognized


def has_free_level_pack(ctx):
    source = getattr(ctx.data, "gift_pack_catalog", None)
    if source is None:
        return False
    for offer, period, _ in source.active_entries(ctx.now):
        if offer.section != "level" or offer.price != 0 or ctx.profile.level < offer.playerLevel:
            continue
        _, bought = counter(ctx, offer, period)
        if offer.availCount == -1 or bought < offer.availCount:
            return True
    return False


def create(ctx, store_id, good_id, client_profile):
    offer, period, cycle = find(ctx, good_id)
    if offer.currencyUnit != "CASH" or offer.storeId != store_id:
        raise DomainError("UNKNOWN_CASH_GOOD", "组合包与冻结 SDK 商品标识不匹配", 404)
    pending = list(ctx.session.execute(select(m.LocalOrder, m.LocalPackOrder).join(m.LocalPackOrder, and_(
        m.LocalOrder.account_id == m.LocalPackOrder.account_id,
        m.LocalOrder.order_id == m.LocalPackOrder.order_id)).where(
        m.LocalOrder.account_id == ctx.account_id, m.LocalOrder.state == "READY")).all())
    reservations = 0
    for old, quote in pending:
        if quote.approved_at is None and quote.expires_at <= ctx.now:
            old.state = "CANCELLED"
        elif old.product_id == good_id and quote.period == period:
            reservations += 1
    validate_purchase(ctx, offer, period, reservations=reservations)
    order_id, capability = "TL-" + uuid.uuid4().hex, secrets.token_urlsafe(32)
    order = m.LocalOrder(account_id=ctx.account_id, order_id=order_id, product_id=good_id,
                         state="READY", created_at=ctx.now)
    ctx.session.add(order)
    ctx.session.flush()
    quoted = offer.model_dump()
    expiry = min(ctx.now + 3600, 253_402_271_999,
        offer.endDateTime if offer.endDateTime != -1 else 253_402_271_999,
        cycle.endDateTime if cycle else 253_402_271_999)
    ctx.session.add(m.LocalPackOrder(account_id=ctx.account_id, order_id=order_id,
        gamedata_hash=ctx.data.manifest["hash"], client_profile=client_profile,
        catalog_hash=fingerprint(catalog(ctx).model_dump()), offer=quoted, period=period,
        quote_hash=fingerprint({"offer": quoted, "period": period}),
        callback_secret_hash=hashlib.sha256(capability.encode()).hexdigest(), expires_at=expiry))
    ctx.session.add(m.AuditLog(actor="local-client", account_id=ctx.account_id, action="local-pack-order",
        detail={"goodId": good_id, "mode": "local-simulated", "period": period}, created_at=ctx.now))
    return {"orderId": order_id, "extension": json.dumps({"terralocal": True, "orderId": order_id,
        "goodId": good_id, "receipt": capability}, separators=(",", ":")),
        "orderIdList": [], "alertMinor": False, "errMsg": ""}


def pair(ctx, order_id):
    order = ctx.session.get(m.LocalOrder, (ctx.account_id, order_id))
    quote = ctx.session.get(m.LocalPackOrder, (ctx.account_id, order_id))
    if order is None:
        raise DomainError("UNKNOWN_LOCAL_ORDER", "本地订单不存在", 404)
    if quote is None:
        raise DomainError("LOCAL_ORDER_QUOTE_MISSING", "本地订单缺少组合包报价", 409)
    if quote.quote_hash != fingerprint({"offer": quote.offer, "period": quote.period}):
        raise DomainError("INVALID_LOCAL_ORDER_QUOTE", "组合包报价或周期指纹不匹配", 503)
    return order, quote


def approve(ctx, order_id, extension):
    order, quote = pair(ctx, order_id)
    cash_shop.approve_quote(ctx, order, quote, extension)


def fulfill(ctx, order_id, client_profile):
    order, quote = pair(ctx, order_id)
    if quote.gamedata_hash != ctx.data.manifest["hash"] or quote.client_profile != client_profile:
        raise DomainError("LOCAL_ORDER_PROFILE_MISMATCH", "组合包报价与当前兼容配置不匹配", 409)
    if order.state == "CANCELLED":
        raise DomainError("LOCAL_ORDER_CANCELLED", "本地订单已取消", 409)
    if order.state == "CONFIRMED":
        if not isinstance(quote.fulfillment, dict):
            raise DomainError("INVALID_LOCAL_ORDER_STATE", "组合包订单缺少履约记录", 503)
        return quote.fulfillment
    if quote.approved_at is None:
        raise DomainError("LOCAL_ORDER_NOT_APPROVED", "本地订单尚未取得 SDK 回调确认", 409)
    try:
        offer = GiftPackOffer.model_validate(quote.offer)
    except ValidationError as exc:
        raise DomainError("INVALID_LOCAL_ORDER_QUOTE", "组合包报价结构无效", 503) from exc
    if offer.goodId != order.product_id or offer.currencyUnit != "CASH":
        raise DomainError("INVALID_LOCAL_ORDER_QUOTE", "组合包订单商品与报价不匹配", 503)
    # A paid reservation retains its quoted cycle even after rollover. Do not
    # charge the new cycle or rewrite already approved reward amounts.
    _, bought = counter(ctx, offer, quote.period)
    if bought + 1 > 2_000_000_000 or offer.availCount != -1 and bought + 1 > offer.availCount:
        raise DomainError("GOOD_SOLD_OUT", "组合包报价对应的限购已用尽", 409)
    items = ctx.rewards([i.model_dump() for i in offer.items])
    record(ctx, offer, quote.period, {"mode": "local-simulated", "price": offer.price,
        "catalog_hash": quote.catalog_hash, "realPayment": False})
    result = {"goodId": offer.goodId, "receiveItems": {"items": items, "checkInItems": []}}
    quote.fulfillment = result
    order.state, order.confirmed_at = "CONFIRMED", ctx.now
    return result


def confirm(ctx, order_id, client_profile):
    result = fulfill(ctx, order_id, client_profile)
    if ctx.session.get(m.LocalPackClaim, (ctx.account_id, order_id)) is None:
        ctx.session.add(m.LocalPackClaim(account_id=ctx.account_id, order_id=order_id, acknowledged_at=ctx.now))
        ctx.session.add(m.AuditLog(actor="local-client", account_id=ctx.account_id,
            action="local-pack-acknowledge", detail={"goodId": result["goodId"]}, created_at=ctx.now))
    return result


def reconcile_before_sync(ctx, client_profile):
    orders = list(ctx.session.scalars(select(m.LocalOrder.order_id).join(m.LocalPackOrder, and_(
        m.LocalOrder.account_id == m.LocalPackOrder.account_id,
        m.LocalOrder.order_id == m.LocalPackOrder.order_id)).where(
        m.LocalOrder.account_id == ctx.account_id, m.LocalOrder.state == "READY",
        m.LocalPackOrder.approved_at.is_not(None)).order_by(m.LocalOrder.created_at, m.LocalOrder.order_id)))
    for order_id in orders:
        fulfill(ctx, order_id, client_profile)
        ctx.session.flush()
    if orders:
        ctx.profile.revision += 1
        ctx.session.flush()
