"""Local originite orders, account-scoped quotes and atomic fulfillment.

No financial API or official credential participates. A random capability
links the local SDK callback to an authenticated game's previously issued
quote. Confirmation consumes the first-purchase bonus at commit time.
"""
import hashlib
import hmac
import json
import secrets
import uuid

from pydantic import Field, ValidationError
from sqlalchemy import and_, select

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.voucher_shop import check_bans
from terralocal.server.gamedata.cash_shop import CashOffer
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m


class LocalPaymentProof(Command):
    terralocal: bool
    orderId: Identifier
    goodId: Identifier
    receipt: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


def list_goods(ctx):
    catalog = getattr(ctx.data, "cash_shop_catalog", None)
    if catalog is None:
        raise DomainError("CASH_SHOP_NOT_READY", "请先导入匹配的本地源石目录", 503)
    return {"goodList": [o.native() for o in catalog.offers] if catalog.active(ctx.now) else []}


def create(ctx, store_id, good_id, client_profile):
    catalog = getattr(ctx.data, "cash_shop_catalog", None)
    if catalog is None:
        raise DomainError("CASH_SHOP_NOT_READY", "请先导入匹配的本地源石目录", 503)
    if not catalog.active(ctx.now):
        raise DomainError("CASH_SUPPLY_CLOSED", "本地源石供给未开放", 409)
    offer = next((o for o in catalog.offers if o.goodId == good_id and o.storeId == store_id), None)
    if offer is None:
        raise DomainError("UNKNOWN_CASH_GOOD", "商品与冻结 SDK 标识不匹配", 404)
    check_bans(ctx, good_id)
    outstanding = ctx.session.execute(select(m.LocalOrder, m.LocalCashOrder).join(m.LocalCashOrder, and_(
        m.LocalOrder.account_id == m.LocalCashOrder.account_id,
        m.LocalOrder.order_id == m.LocalCashOrder.order_id)).outerjoin(m.LocalCashClaim, and_(
        m.LocalOrder.account_id == m.LocalCashClaim.account_id,
        m.LocalOrder.order_id == m.LocalCashClaim.order_id)).where(
            m.LocalOrder.account_id == ctx.account_id, m.LocalOrder.state.in_(("READY", "CONFIRMED")),
            m.LocalCashClaim.order_id.is_(None))).all()
    count = 0
    approved_ids = []
    for pending, quote in outstanding:
        if quote.approved_at is None and quote.expires_at <= ctx.now:
            pending.state = "CANCELLED"
        else:
            count += 1
            if quote.approved_at is not None:
                approved_ids.append(pending.order_id)
    if approved_ids:
        return {"result": 2, "orderId": "", "extension": "", "orderIdList": sorted(approved_ids),
                "alertMinor": False, "errMsg": ""}
    if count >= 64:
        raise DomainError("TOO_MANY_LOCAL_ORDERS", "本地待处理订单数量已达上限", 409)
    order_id, capability = "TL-" + uuid.uuid4().hex, secrets.token_urlsafe(32)
    order = m.LocalOrder(account_id=ctx.account_id, order_id=order_id, product_id=good_id,
                         state="READY", created_at=ctx.now)
    ctx.session.add(order)
    ctx.session.flush()
    quoted = offer.model_dump()
    ctx.session.add(m.LocalCashOrder(account_id=ctx.account_id, order_id=order_id,
        gamedata_hash=ctx.data.manifest["hash"], client_profile=client_profile,
        catalog_hash=fingerprint(catalog.model_dump()), offer=quoted, quote_hash=fingerprint(quoted),
        callback_secret_hash=hashlib.sha256(capability.encode()).hexdigest(),
        expires_at=ctx.now + 3600))
    ctx.session.add(m.AuditLog(actor="local-client", account_id=ctx.account_id, action="local-cash-order",
        detail={"mode": "local-simulated", "goodId": good_id, "catalog": catalog.catalog_id}, created_at=ctx.now))
    # result=2 has a different native meaning: existing paid orders need
    # confirmation. New unapproved orders must not trigger that branch.
    return {"orderId": order_id, "extension": json.dumps({"terralocal": True, "orderId": order_id,
            "goodId": good_id, "receipt": capability}, separators=(",", ":")),
            "orderIdList": [], "alertMinor": False, "errMsg": ""}


def approve(ctx, order_id, extension):
    order, quote = pair(ctx, order_id)
    approve_quote(ctx, order, quote, extension)


def approve_quote(ctx, order, quote, extension):
    order_id = order.order_id
    try:
        proof = LocalPaymentProof.model_validate(json.loads(extension))
    except (ValueError, TypeError, ValidationError) as exc:
        raise DomainError("INVALID_LOCAL_PAYMENT", "本地订单回调凭据无效", 401) from exc
    expected = hashlib.sha256(proof.receipt.encode()).hexdigest()
    if (proof.terralocal is not True or proof.orderId != order_id or proof.goodId != order.product_id
            or not hmac.compare_digest(expected, quote.callback_secret_hash)):
        raise DomainError("INVALID_LOCAL_PAYMENT", "本地订单回调凭据无效", 401)
    if order.state == "CANCELLED" or (quote.approved_at is None and quote.expires_at <= ctx.now):
        raise DomainError("LOCAL_ORDER_EXPIRED", "本地未确认订单已过期", 409)
    if quote.approved_at is None:
        quote.approved_at = ctx.now


def pair(ctx, order_id):
    order = ctx.session.get(m.LocalOrder, (ctx.account_id, order_id))
    quote = ctx.session.get(m.LocalCashOrder, (ctx.account_id, order_id))
    if order is None:
        raise DomainError("UNKNOWN_LOCAL_ORDER", "本地订单不存在", 404)
    if quote is None:
        raise DomainError("LOCAL_ORDER_QUOTE_MISSING", "旧本地队列缺少可验证的商品报价", 409)
    if quote.quote_hash != fingerprint(quote.offer):
        raise DomainError("INVALID_LOCAL_ORDER_QUOTE", "本地商品报价指纹不匹配", 503)
    return order, quote


def fulfill(ctx, order_id, client_profile):
    order, quote = pair(ctx, order_id)
    if quote.gamedata_hash != ctx.data.manifest["hash"] or quote.client_profile != client_profile:
        raise DomainError("LOCAL_ORDER_PROFILE_MISMATCH", "本地订单与当前兼容配置不匹配", 409)
    if order.state == "CANCELLED":
        raise DomainError("LOCAL_ORDER_CANCELLED", "本地订单已取消", 409)
    if order.state == "CONFIRMED":
        if not isinstance(quote.fulfillment, dict):
            raise DomainError("INVALID_LOCAL_ORDER_STATE", "已确认订单缺少履约记录", 503)
        return quote.fulfillment
    if quote.approved_at is None:
        raise DomainError("LOCAL_ORDER_NOT_APPROVED", "本地订单尚未取得 SDK 回调确认", 409)
    try:
        offer = CashOffer.model_validate(quote.offer)
    except ValidationError as exc:
        raise DomainError("INVALID_LOCAL_ORDER_QUOTE", "本地商品报价格式无效", 503) from exc
    if offer.goodId != order.product_id:
        raise DomainError("INVALID_LOCAL_ORDER_QUOTE", "本地订单商品与报价不同", 503)
    counter = ctx.session.get(m.ShopState, (ctx.account_id, "CASH", offer.goodId, "permanent"))
    first = counter is None or counter.bought == 0
    if counter and counter.bought >= 2_000_000_000:
        raise DomainError("PURCHASE_LIMIT", "本地源石购买次数超出范围", 409)
    amount = offer.doubleCount if first else offer.diamondNum + offer.plusNum
    items = ctx.rewards([{"id": "4002", "type": "DIAMOND", "count": amount}])
    if counter is None:
        counter = m.ShopState(account_id=ctx.account_id, shop_id="CASH", offer_id=offer.goodId,
                              period="permanent", bought=0)
        ctx.session.add(counter)
    counter.bought += 1
    result = {"goodId": offer.goodId, "receiveItems": {"items": items, "checkInItems": []}}
    quote.fulfillment = result
    order.state, order.confirmed_at = "CONFIRMED", ctx.now
    ctx.session.add(m.PurchaseHistory(account_id=ctx.account_id, shop_id="CASH", offer_id=offer.goodId,
        count=1, cost={"mode": "local-simulated", "catalog_hash": quote.catalog_hash,
                      "first": first, "price": offer.price, "realPayment": False}, purchased_at=ctx.now))
    ctx.session.add(m.AuditLog(actor="local-client", account_id=ctx.account_id, action="local-cash-confirm",
        detail={"goodId": offer.goodId, "first": first, "quantity": amount, "realPayment": False},
        created_at=ctx.now))
    return result


def confirm(ctx, order_id, client_profile):
    result = fulfill(ctx, order_id, client_profile)
    if ctx.session.get(m.LocalCashClaim, (ctx.account_id, order_id)) is None:
        ctx.session.add(m.LocalCashClaim(account_id=ctx.account_id, order_id=order_id, acknowledged_at=ctx.now))
        order, _ = pair(ctx, order_id)
        ctx.session.add(m.AuditLog(actor="local-client", account_id=ctx.account_id, action="local-cash-acknowledge",
            detail={"goodId": order.product_id, "mode": "local-simulated"}, created_at=ctx.now))
    return result


def reconcile_before_sync(ctx, client_profile):
    """Include approved recoverable rewards in the first native login snapshot.

    The native login recovery builds its home display before its later claim
    response. Keep rewards pending for the original notice/animation until
    confirm acknowledges them; repeated sync or claim never credits twice.
    SDK approval and unpaid quotes still grant no inventory by themselves.
    """
    orders = list(ctx.session.scalars(select(m.LocalOrder.order_id).join(m.LocalCashOrder, and_(
        m.LocalOrder.account_id == m.LocalCashOrder.account_id,
        m.LocalOrder.order_id == m.LocalCashOrder.order_id)).where(
            m.LocalOrder.account_id == ctx.account_id, m.LocalOrder.state == "READY",
            m.LocalCashOrder.approved_at.is_not(None)).order_by(m.LocalOrder.created_at, m.LocalOrder.order_id)))
    for order_id in orders:
        fulfill(ctx, order_id, client_profile)
        # Autoflush is disabled. A later quote in this same transaction must
        # see the counter created by an earlier first purchase.
        ctx.session.flush()
    if orders:
        ctx.profile.revision += 1
        ctx.session.flush()
