"""Ordinary originite outfit supply and atomic single-outfit purchases."""

from terralocal.server.domain.errors import DomainError, NotImplementedFeature
from terralocal.server.domain.skins import definition, grant
from terralocal.server.persistence import models as m


def require_catalog(catalog):
    if catalog is None:
        raise DomainError("SKIN_CATALOG_NOT_READY", "请导入匹配版本的服装销售目录", 503)
    return catalog


def list_goods(ctx, catalog, char_ids: list[str] | None) -> dict:
    catalog = require_catalog(catalog)
    selected = set(char_ids or [])
    for char_id in selected:
        ctx.data.character(char_id)
    goods = []
    for row in sorted(catalog.offers, key=lambda entry: entry.slotId):
        skin = definition(ctx.data, row.skinId)
        if not row.available(ctx.now) or (selected and skin["charId"] not in selected):
            continue
        goods.append({**row.model_dump(), "skinName": skin["name"], "currencyUnit": "DIAMOND",
                      "isRedeem": False, "giftAvatarId": None, "giftDesc": None})
    return {"goodList": goods, "gachaGoodList": []}


def buy(ctx, catalog, good_id: str, *, is_special: bool) -> dict:
    if is_special:
        raise NotImplementedFeature("服装特殊动态插画购买规则")
    catalog = require_catalog(catalog)
    row = next((r for r in catalog.offers if r.goodId == good_id), None)
    if row is None:
        raise DomainError("UNKNOWN_GOOD", "此服装商品不存在", 404)
    if not row.available(ctx.now):
        raise DomainError("GOOD_UNAVAILABLE", "此服装商品不在销售期间", 409)
    bans = ctx.profile.flags.get("featureBans", {})
    if (not isinstance(bans, dict) or set(bans) - {"gacha", "shop"} or any(
            not isinstance(values, list) or len(values) > 2048 or any(
                not isinstance(value, str) or not 1 <= len(value) <= 96 for value in values)
            for values in bans.values())):
        raise DomainError("INVALID_LOCAL_RESTRICTIONS", "本地功能限制配置非法", 503)
    if good_id in bans.get("shop", []):
        raise DomainError("GOOD_FORBIDDEN", "此商品已被本地管理员停用", 403)
    if ctx.session.get(m.OwnedSkin, (ctx.account_id, row.skinId)) is not None:
        raise DomainError("SKIN_ALREADY_OWNED", "该账号已拥有此服装", 409)
    key = (ctx.account_id, "SKIN", good_id, "permanent")
    if ctx.session.get(m.ShopState, key) is not None:
        raise DomainError("SKIN_PURCHASE_CONFLICT", "服装购买记录与持有状态不一致", 503)
    cost = [{"id": "4002", "count": row.price}] if row.price else []
    ctx.consume(cost)
    grant(ctx, row.skinId)
    ctx.session.add(m.ShopState(account_id=ctx.account_id, shop_id="SKIN", offer_id=good_id,
                                period="permanent", bought=1))
    ctx.session.add(m.PurchaseHistory(account_id=ctx.account_id, shop_id="SKIN", offer_id=good_id,
                                      count=1, cost={"items": cost}, purchased_at=ctx.now))
    return {}
