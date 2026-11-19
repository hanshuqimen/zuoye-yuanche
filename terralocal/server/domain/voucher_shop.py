"""Atomic voucher purchases and account-scoped catalog cycle projections."""

from terralocal.server.domain.errors import DomainError, NotImplementedFeature
from terralocal.server.gamedata.voucher_shop import Wallets
from terralocal.server.persistence import models as m


def catalog(ctx):
    return getattr(ctx.data, "voucher_shop_catalog", None)


def active_cycle(ctx, shop, *, at=None, required=False):
    source = catalog(ctx)
    cycle = source.active_cycle(shop, ctx.now if at is None else at) if source else None
    if cycle is None and required:
        raise DomainError("VOUCHER_CATALOG_NOT_READY", "请导入匹配版本和销售期间的凭证商店目录", 503)
    return cycle


def low_state(ctx, cycle):
    row = ctx.session.get(m.LowShopProgress, (ctx.account_id, cycle.period))
    group, spent = (row.cur_group_id, row.lgg_cost_total) if row else (cycle.groups[0], 0)
    if group not in cycle.groups or type(spent) is not int or not 0 <= spent <= 2_000_000_000:
        raise DomainError("INVALID_SHOP_STATE", "Low 消费进度与目录不一致", 503)
    return group, spent


def progress_state(ctx, cycle, progress_id):
    row = ctx.session.get(m.ShopProgress, (ctx.account_id, cycle.shop, progress_id, cycle.period))
    order, count = (row.order, row.count) if row else (1, 0)
    entries = cycle.progressGoodList[progress_id]
    if not 1 <= order <= len(entries) or count not in (0, 1) or (count and order != len(entries)):
        raise DomainError("INVALID_SHOP_STATE", "阶梯进度与目录不一致", 503)
    return {"order": order, "count": count}


def project(ctx, cycle):
    offers = {r.goodId: r for r in cycle.goodList}
    info = []
    for row in sorted(ctx.rows(m.ShopState), key=lambda r: r.offer_id):
        if row.shop_id != cycle.shop or row.period != cycle.period or row.offer_id not in offers:
            continue
        offer = offers[row.offer_id]
        if (type(row.bought) is not int or not 0 <= row.bought <= 2_000_000_000
                or getattr(offer, "goodType", "NORMAL") != "NORMAL"
                or (offer.availCount != -1 and row.bought > offer.availCount)):
            raise DomainError("INVALID_SHOP_STATE", "商品计数与已接纳的目录不一致", 503)
        info.append({"id": row.offer_id, "count": row.bought})
    result = {"info": info}
    if cycle.shop == "LS":
        group, spent = low_state(ctx, cycle)
        result.update(curShopId=cycle.shopId, curGroupId=group, lggCostTotal=spent)
    elif cycle.shop in {"HS", "CLASSIC"}:
        result["progressInfo"] = {key: progress_state(ctx, cycle, key) for key in cycle.progressGoodList}
    elif cycle.shop == "ES":
        result.update(progressInfo={}, lastClick=0)
    return result


def list_goods(ctx, shop):
    cycle = active_cycle(ctx, shop, required=True)
    result = {"goodList": [r.model_dump() for r in cycle.goodList if r.active(ctx.now)],
              "newFlag": list(cycle.newFlag)}
    if shop == "LS":
        result.update(groups=list(cycle.groups), groupsInfo=[r.model_dump() for r in cycle.groupsInfo],
                      shopEndTime=cycle.shopEndTime, type=cycle.type)
    elif shop in {"HS", "CLASSIC"}:
        keys = {r["progressGoodId"] for r in result["goodList"] if r["goodType"] == "PROGRESS"}
        result["progressGoodList"] = {k: [r.model_dump() for r in cycle.progressGoodList[k]]
                                      for k in cycle.progressGoodList if k in keys}
    elif shop == "ES":
        result["lastClick"] = 0
    return result


def purchase_limits(ctx, goods):
    """Only proven ordinary capacity semantics; specialized queries stay explicit."""
    result, recognized = {}, set()
    for shop, ids in goods.items():
        if shop not in Wallets:
            continue
        cycle = active_cycle(ctx, shop)
        if not cycle:
            continue
        offers = {row.goodId: row for row in cycle.goodList}
        for good_id in ids:
            offer = offers.get(good_id)
            if offer is None:
                continue
            if getattr(offer, "goodType", "NORMAL") == "PROGRESS":
                raise NotImplementedFeature("推荐页中阶梯商品的购买状态查询")
            result[good_id] = offer.availCount if offer.active(ctx.now) else 0
            recognized.add((shop, good_id))
    return result, recognized


def check_bans(ctx, good_id):
    bans = ctx.profile.flags.get("featureBans", {})
    if (not isinstance(bans, dict) or set(bans) - {"gacha", "shop"} or any(
            not isinstance(values, list) or len(values) > 2048 or any(
                not isinstance(value, str) or not 1 <= len(value) <= 96 for value in values)
            for values in bans.values())):
        raise DomainError("INVALID_LOCAL_RESTRICTIONS", "本地功能限制配置非法", 503)
    if good_id in bans.get("shop", []):
        raise DomainError("GOOD_FORBIDDEN", "此商品已被本地管理员停用", 403)


def advance_low(ctx, cycle, cost):
    group, spent = low_state(ctx, cycle)
    if spent + cost > 2_000_000_000:
        raise DomainError("SHOP_SPEND_LIMIT", "资质凭证消费累计超出范围")
    spent += cost
    index = cycle.groups.index(group)
    thresholds = {r.groupId: r.lggThreshold for r in cycle.groupsInfo}
    purchases = {r.offer_id: r.bought for r in ctx.rows(m.ShopState)
                 if r.shop_id == "LS" and r.period == cycle.period}
    while index + 1 < len(cycle.groups):
        next_group = cycle.groups[index + 1]
        if cycle.type == 0:
            entries = [r for r in cycle.goodList if r.groupId == cycle.groups[index]]
            unlock = all(purchases.get(r.goodId, 0) >= r.availCount for r in entries)
        else:
            unlock = spent >= thresholds[next_group]
        if not unlock:
            break
        if cycle.type == 1 and cycle.progressEncoding == "stage-spend":
            spent -= thresholds[next_group]
        index += 1
    row = ctx.session.get(m.LowShopProgress, (ctx.account_id, cycle.period))
    if row is None:
        row = m.LowShopProgress(account_id=ctx.account_id, period=cycle.period)
        ctx.session.add(row)
    row.cur_group_id, row.lgg_cost_total = cycle.groups[index], spent


def buy(ctx, shop, good_id, count):
    if type(count) is not int or not 1 <= count <= 2_000_000_000:
        raise DomainError("INVALID_PURCHASE_COUNT", "购买数量必须为正整数")
    cycle = active_cycle(ctx, shop, required=True)
    offer = next((row for row in cycle.goodList if row.goodId == good_id), None)
    if offer is None:
        raise DomainError("UNKNOWN_GOOD", "此凭证商品不存在", 404)
    if not offer.active(ctx.now):
        raise DomainError("GOOD_UNAVAILABLE", "此商品不在销售期间", 409)
    check_bans(ctx, good_id)
    if shop == "LS" and cycle.groups.index(offer.groupId) > cycle.groups.index(low_state(ctx, cycle)[0]):
        raise DomainError("SHOP_GROUP_LOCKED", "此资质凭证购买阶段尚未解锁", 409)
    progress = None
    if getattr(offer, "goodType", "NORMAL") == "PROGRESS":
        if count != 1:
            raise DomainError("INVALID_PROGRESS_COUNT", "阶梯商品每次只购买当前档位", 409)
        state = progress_state(ctx, cycle, offer.progressGoodId)
        if state["count"]:
            raise DomainError("GOOD_SOLD_OUT", "此阶梯商品已全部购买", 409)
        current = cycle.progressGoodList[offer.progressGoodId][state["order"] - 1]
        item, price = current.item, current.price
        progress = ctx.session.get(m.ShopProgress, (ctx.account_id, shop, offer.progressGoodId, cycle.period))
    else:
        normal = ctx.session.get(m.ShopState, (ctx.account_id, shop, good_id, cycle.period))
        bought = normal.bought if normal else 0
        if type(bought) is not int or bought < 0 or bought + count > 2_000_000_000:
            raise DomainError("INVALID_SHOP_STATE", "商品购买次数超出范围", 503)
        if offer.availCount != -1 and bought + count > offer.availCount:
            raise DomainError("GOOD_SOLD_OUT", "购买数量超过剩余库存", 409)
        item, price = offer.item, offer.price
    total = price * count
    if total > 2_000_000_000 or item.count * count > 2_000_000_000:
        raise DomainError("PURCHASE_LIMIT", "单次交易数量超出范围")
    if item.type == "CHAR_SKIN" and ctx.balance(item.id):
        raise DomainError("SKIN_ALREADY_OWNED", "该账号已拥有此服装", 409)
    wallet = Wallets[shop][0]
    cost = [{"id": wallet, "count": total}] if total else []
    ctx.consume(cost)
    if shop == "CLASSIC" and item.type == "CHAR":
        from terralocal.server.domain.acquisitions import acquire_classic

        items = [{"id": item.id, "type": "CHAR", "count": 1,
                  "charGet": acquire_classic(ctx, item.id)} for _ in range(count)]
    else:
        items = ctx.rewards([item.model_dump()], count)
    if getattr(offer, "goodType", "NORMAL") == "PROGRESS":
        if progress is None:
            progress = m.ShopProgress(account_id=ctx.account_id, shop_id=shop,
                progress_id=offer.progressGoodId, period=cycle.period)
            ctx.session.add(progress)
        last = len(cycle.progressGoodList[offer.progressGoodId])
        progress.order = min(current.order + 1, last)
        progress.count = int(current.order == last)
    else:
        if normal is None:
            normal = m.ShopState(account_id=ctx.account_id, shop_id=shop, offer_id=good_id,
                                period=cycle.period, bought=0)
            ctx.session.add(normal)
        normal.bought += count
    ctx.session.flush()
    if shop == "LS":
        advance_low(ctx, cycle, total)
    history = {"items": cost, "period": cycle.period}
    if getattr(offer, "goodType", "NORMAL") == "PROGRESS":
        history.update(progressId=offer.progressGoodId, order=current.order)
    ctx.session.add(m.PurchaseHistory(account_id=ctx.account_id, shop_id=shop, offer_id=good_id,
                                      count=count, cost=history, purchased_at=ctx.now))
    return {"items": items}
