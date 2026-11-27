"""Native Crisis V2 purchases with catalog-bound stock and a debit ledger.

Transport sequence receipts deduplicate retries. A new sequence is a new
purchase intent, even when its body equals an earlier purchase. The finite
progress policy is explicit local behavior; it is not original backend code.
"""

import json
import sqlite3
from contextlib import closing
from typing import Annotated, Literal

from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain import crisis_v2
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.protocol.crisis_v2_shop import Amount, BoughtGood, GoodList, GoodProgress
from terralocal.server.protocol.crisis_v2_state import Key

VERSION = "cn-2.7.71-crisis-v2-native-shop-v1"
LEDGER = "crisis-v2-native-shop-ledger"


class Ledger(Command):
    version: Literal[VERSION]
    account_id: Amount
    gamedata_hash: str
    catalog_hash: str
    purchases: dict[Key, Amount]
    spent: Annotated[int, Field(ge=0, le=2**63 - 1)]
    hash: str


def _incompatible():
    return DomainError("CRISIS_V2_NATIVE_SHOP_INCOMPATIBLE", "原版危机合约商店账本或库存不一致", 503)


def _seal(account_id, catalog, purchases, spent):
    body = {
        "version": VERSION,
        "account_id": account_id,
        "gamedata_hash": catalog.gamedata_hash,
        "catalog_hash": catalog.fingerprint,
        "purchases": purchases,
        "spent": spent,
    }
    return body | {"hash": fingerprint(body)}


def _expected(catalog, purchases):
    offers = {row.goodId: row for _, row in catalog.goods()}
    spent, info, progress = 0, [], {}
    for good_id, quantity in sorted(purchases.items()):
        good = offers.get(good_id)
        if good is None:
            raise ValueError("已购商品不在绑定目录")
        if good.progressGoodId:
            tiers = catalog.progress[good.progressGoodId]
            if quantity > len(tiers):
                raise ValueError("分档商品超出有限档数")
            spent += sum(tier.price for tier in tiers[:quantity])
            # Keep the last valid order after completion. The list endpoint
            # removes completed finite goods, avoiding an absent order N+1.
            progress[good.progressGoodId] = GoodProgress(
                count=quantity, order=min(quantity + 1, len(tiers))
            ).model_dump()
        else:
            if good.availCount != -1 and quantity > good.availCount:
                raise ValueError("已购数量超出初始库存")
            spent += good.price * quantity
            info.append(BoughtGood(id=good_id, count=quantity).model_dump())
    return spent, info, progress


def _validated(account_id, catalog, record, info, progress):
    if type(info) is not list or type(progress) is not dict:
        raise ValueError("原版商店保存字段类型无效")
    info = [BoughtGood.model_validate(value).model_dump() for value in info]
    progress = {key: GoodProgress.model_validate(value).model_dump() for key, value in progress.items()}
    if record is None:
        if info != [] or progress != {}:
            raise ValueError("商店保存有购买记录但缺少目录账本")
        return {}, 0
    if catalog is None:
        raise ValueError("原版商店购买记录缺少原目录")
    saved = Ledger.model_validate(record["result"])
    spent, expected_info, expected_progress = _expected(catalog, saved.purchases)
    if (
        record["key"] != LEDGER
        or record["request_hash"] != catalog.fingerprint
        or saved.account_id != account_id
        or saved.gamedata_hash != catalog.gamedata_hash
        or saved.catalog_hash != catalog.fingerprint
        or saved.hash != fingerprint(saved.model_dump(exclude={"hash"}))
        or saved.spent != spent
        or type(record["created_at"]) is not int
        or record["created_at"] < catalog.valid_from
        or info != expected_info
        or progress != expected_progress
    ):
        raise ValueError("原版商店商品、支出或保存与目录不同")
    return dict(saved.purchases), spent


def _ledger(ctx, catalog):
    account = crisis_v2._account(ctx)
    row = ctx.session.get(m.Receipt, (ctx.account_id, LEDGER))
    record = (
        None
        if row is None
        else {key: getattr(row, key) for key in ("key", "request_hash", "result", "created_at")}
    )
    try:
        purchases, spent = _validated(
            ctx.account_id, catalog, record, account.shop_info, account.shop_progress
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise _incompatible() from exc
    return account, row, purchases, spent


def spent_total(ctx):
    """Validate the native debit side without recursively validating wallets."""
    return _ledger(ctx, getattr(ctx.data, "crisis_v2_native_shop", None))[3]


def stored_spent_total(connection, account_id):
    """Read sealed totals; full catalog/stock validation follows at startup."""
    row = connection.execute(
        "SELECT result FROM receipts WHERE account_id=? AND key=?", (account_id, LEDGER)
    ).fetchone()
    if row is None:
        return 0
    saved = Ledger.model_validate_json(row[0])
    if saved.account_id != account_id or saved.hash != fingerprint(saved.model_dump(exclude={"hash"})):
        raise ValueError("原版商店支出回执校验失败")
    return saved.spent


def _state(ctx, catalog, local_shop):
    if catalog is None:
        raise DomainError("CRISIS_V2_NATIVE_SHOP_NOT_CONFIGURED", "尚未提供匹配的原版危机合约商品目录", 503)
    account, row, purchases, spent = _ledger(ctx, catalog)
    from terralocal.server.domain.crisis_v2_missions import LOCAL_LEDGER, coin_total

    if local_shop is not None:
        from terralocal.server.domain.crisis_v2_shop import _state as local_state

        local_state(ctx, local_shop)
    elif ctx.session.get(
        m.Receipt, (ctx.account_id, LOCAL_LEDGER)
    ) is not None or account.shop_coin + spent != coin_total(ctx):
        raise _incompatible()
    return account, row, purchases, spent


def _remaining(ctx, good, purchases):
    quantity = purchases.get(good.goodId, 0)
    remaining = good.availCount if good.availCount == -1 else good.availCount - quantity
    cap = ctx.data.table("item_table").get("uniqueInfo", {}).get(good.item.id)
    if cap is not None:
        remaining = min(remaining, max(0, cap - ctx.balance(good.item.id)) // good.item.count)
    return remaining


def view(ctx, catalog, *, local_shop=None):
    _, _, purchases, _ = _state(ctx, catalog, local_shop)
    _, seasonal = catalog.supply(ctx.data, ctx.now)

    def rows(goods):
        values = []
        for good in goods:
            if good.progressGoodId:
                if purchases.get(good.goodId, 0) >= len(catalog.progress[good.progressGoodId]):
                    continue
                values.append(good.model_dump())
            else:
                values.append(good.model_dump() | {"availCount": _remaining(ctx, good, purchases)})
        return values

    return GoodList(
        permanent=rows(catalog.permanent),
        season=rows(seasonal),
        progressGoodList=catalog.progress,
    ).model_dump()


def buy(ctx, catalog, request, *, local_shop=None):
    account, row, purchases, spent = _state(ctx, catalog, local_shop)
    _, seasonal = catalog.supply(ctx.data, ctx.now)
    active = catalog.permanent if request.perm == 1 else seasonal
    good = next((good for good in active if good.goodId == request.goodId), None)
    if good is None:
        raise DomainError("CRISIS_V2_NATIVE_SHOP_UNKNOWN_GOOD", "商品不属于当前可用目录", 404)
    old_count = purchases.get(good.goodId, 0)
    if good.progressGoodId:
        tiers = catalog.progress[good.progressGoodId]
        if request.count != 1:
            raise DomainError("CRISIS_V2_NATIVE_SHOP_PROGRESS_COUNT", "分档商品每次只能兑换一档", 409)
        if old_count >= len(tiers):
            raise DomainError("CRISIS_V2_NATIVE_SHOP_SOLD_OUT", "分档商品已兑换完毕", 409)
        tier = tiers[old_count]
        item, cost = tier.item, tier.price
        quantity = 1
        cap = ctx.data.table("item_table").get("uniqueInfo", {}).get(item.id)
        if cap is not None and ctx.balance(item.id) + item.count > cap:
            raise DomainError("CRISIS_V2_NATIVE_SHOP_SOLD_OUT", "唯一物品已达到持有上限", 409)
    else:
        remaining = _remaining(ctx, good, purchases)
        if remaining != -1 and request.count > remaining:
            raise DomainError("CRISIS_V2_NATIVE_SHOP_SOLD_OUT", "商品剩余库存不足", 409)
        item, cost, quantity = good.item, good.price * request.count, request.count
    if old_count + quantity > 2_000_000_000 or spent + cost > 2**63 - 1:
        raise DomainError("CRISIS_V2_NATIVE_SHOP_LIMIT", "商店累计购买或支出超出范围", 409)
    if cost > account.shop_coin:
        raise DomainError("CRISIS_V2_NATIVE_SHOP_INSUFFICIENT", "危机合约商店代币不足", 409)
    if item.count * quantity > 2_000_000_000:
        raise DomainError("INVENTORY_LIMIT", "商品发放数量超出范围", 409)
    rewards = ctx.rewards([item.model_dump()], multiplier=quantity)
    if (
        type(rewards) is not list
        or len(rewards) != 1
        or type(rewards[0]) is not dict
        or type(rewards[0].get("count")) is not int
        or {key: rewards[0].get(key) for key in ("id", "type", "count")}
        != {"id": item.id, "type": item.type, "count": item.count * quantity}
        or item.type == "CHAR"
        and type(rewards[0].get("charGet")) is not dict
    ):
        raise _incompatible()
    purchases[good.goodId] = old_count + quantity
    expected_spent, info, progress = _expected(catalog, purchases)
    if expected_spent != spent + cost:
        raise _incompatible()
    account.shop_coin -= cost
    account.shop_info, account.shop_progress = info, progress
    body = _seal(ctx.account_id, catalog, purchases, expected_spent)
    if row is None:
        ctx.session.add(
            m.Receipt(
                account_id=ctx.account_id,
                key=LEDGER,
                request_hash=catalog.fingerprint,
                result=body,
                created_at=ctx.now,
            )
        )
    else:
        row.result = body
    ctx.emit(
        "CrisisV2ShopPurchased", good_id=good.goodId, count=quantity, cost=cost, catalog=catalog.fingerprint
    )
    return {"items": rewards}


def preflight(catalog, database):
    """Reject missing/replaced catalogs and stock drift before writable open."""
    if not database.exists():
        return
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "receipts" not in tables:
            return
        records = {
            row[0]: {
                "key": LEDGER,
                "request_hash": row[1],
                "result": json.loads(row[2]),
                "created_at": row[3],
            }
            for row in connection.execute(
                "SELECT account_id,request_hash,result,created_at FROM receipts WHERE key=?", (LEDGER,)
            )
        }
        if "crisis_v2_accounts" not in tables:
            if records:
                raise ValueError("原版危机合约商店账本缺少账号")
            return
        try:
            for account, info, progress in connection.execute(
                "SELECT account_id,shop_info,shop_progress FROM crisis_v2_accounts"
            ):
                _validated(
                    account, catalog, records.pop(account, None), json.loads(info), json.loads(progress)
                )
            if records:
                raise ValueError("原版商店存在未归属的购买账本")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError("原版危机合约商店目录或库存账本不兼容；请保留原配置和存档") from exc
