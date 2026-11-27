"""Configured local Crisis V2 shop. No official catalog or implied prices."""

import json
import sqlite3
from contextlib import closing
from typing import Annotated, Literal

from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain import crisis_v2
from terralocal.server.domain.crisis_v2_claims import _material_pack
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.protocol.crisis_v2_state import Key

LEDGER = "crisis-v2-local-shop-ledger"
Bounded = Annotated[int, Field(ge=1, le=1_000_000)]


class Offer(Command):
    id: Key
    price: Bounded
    stock: Annotated[int, Field(ge=1, le=1000)]
    itemId: Key
    itemType: Literal["FURN", "CHAR_SKIN", "ITEM_PACK", "MATERIAL"]


class Shop(Command):
    schemaVersion: Literal[1]
    gameDataHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seasonId: Key
    credits: dict[Key, Bounded] = Field(min_length=1, max_length=50)
    offers: list[Offer] = Field(min_length=1, max_length=100)


def read_catalog(path, data):
    if not crisis_v2.available(data) or path.is_symlink():
        raise ValueError("本地商店需要匹配的危机合约数据和普通设置文件")
    with path.open("rb") as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("本地商店设置过大")
    catalog = Shop.model_validate_json(raw)
    rules = data.crisis_v2
    if (
        data.manifest["hash"] != catalog.gameDataHash
        or catalog.seasonId not in rules.permanent
        or len({offer.id for offer in catalog.offers}) != len(catalog.offers)
    ):
        raise ValueError("本地商店的版本、赛季或商品标识不匹配")
    maps = {rules.permanent[catalog.seasonId], *rules.temporary[catalog.seasonId]}
    if not set(catalog.credits) <= maps:
        raise ValueError("本地商店的代币奖励引用未知地图")
    try:
        for offer in catalog.offers:
            item = data.item(offer.itemId)
            if (
                item["itemType"] != offer.itemType
                or offer.itemType == "CHAR_SKIN"
                and (not item.get("isBuySkin") or offer.stock != 1)
            ):
                raise ValueError("本地商店商品类型或库存无效")
            if offer.itemType == "ITEM_PACK":
                _material_pack(data, offer.itemId)
    except (DomainError, KeyError) as exc:
        raise ValueError("本地商店商品未匹配静态物品表") from exc
    return catalog


def preflight(catalog, database):
    """Never reinterpret spent balances when the explicit catalog is changed."""
    if not database.exists():
        return
    expected = fingerprint(catalog.model_dump()) if catalog else None
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='receipts'").fetchone():
            if conn.execute(
                "SELECT 1 FROM receipts WHERE key=? AND request_hash IS NOT ? LIMIT 1", (LEDGER, expected)
            ).fetchone():
                raise ValueError("存档使用不同的危机合约本地商店配置；请保留配置和存档")
            if (
                catalog is not None
                and conn.execute("SELECT 1 FROM receipts WHERE key=? LIMIT 1", (LEDGER,)).fetchone()
            ):
                from terralocal.server.domain.crisis_v2_missions import stored_coin_total
                from terralocal.server.domain.crisis_v2_native_shop import stored_spent_total

                for account_id, coin, body in conn.execute(
                    """SELECT r.account_id,a.shop_coin,r.result FROM receipts r
                        LEFT JOIN crisis_v2_accounts a ON a.account_id=r.account_id WHERE r.key=?""",
                    (LEDGER,),
                ):
                    try:
                        if coin is None:
                            raise _mismatch()
                        _validated_state(
                            catalog,
                            coin - stored_coin_total(conn, account_id) + stored_spent_total(conn, account_id),
                            json.loads(body),
                        )
                    except (DomainError, ValueError, TypeError) as exc:
                        raise ValueError("本地商店余额或库存账本不一致；请保留原存档") from exc


def _validated_state(catalog, coin, state):
    offers = {offer.id: offer for offer in catalog.offers}
    if (
        type(state) is not dict
        or set(state) != {"credits", "purchases"}
        or type(state["credits"]) is not list
        or type(state["purchases"]) is not dict
    ):
        raise _mismatch()
    credits, purchases = state["credits"], state["purchases"]
    if (
        any(type(key) is not str or key not in catalog.credits for key in credits)
        or len(set(credits)) != len(credits)
        or any(
            key not in offers or type(qty) is not int or not 1 <= qty <= offers[key].stock
            for key, qty in purchases.items()
        )
        or sum(catalog.credits[key] for key in credits)
        - sum(offers[key].price * qty for key, qty in purchases.items())
        != coin
    ):
        raise _mismatch()
    return {"credits": list(credits), "purchases": dict(purchases)}, offers


def _state(ctx, catalog):
    from terralocal.server.domain.crisis_v2_missions import coin_total
    from terralocal.server.domain.crisis_v2_native_shop import spent_total

    if catalog is None:
        raise DomainError("CRISIS_V2_SHOP_NOT_CONFIGURED", "尚未提供自定义危机合约本地商店目录", 503)
    account = crisis_v2._account(ctx)
    digest = fingerprint(catalog.model_dump())
    row = ctx.session.get(m.Receipt, (ctx.account_id, LEDGER))
    if row is not None and row.request_hash != digest:
        raise _mismatch()
    state, offers = _validated_state(
        catalog,
        account.shop_coin - coin_total(ctx) + spent_total(ctx),
        {"credits": [], "purchases": {}} if row is None else row.result,
    )
    return account, digest, row, state, offers


def _mismatch():
    return DomainError("CRISIS_V2_SHOP_INCOMPATIBLE", "本地商店目录或代币账本不一致", 503)


def _save(ctx, digest, row, state):
    if row is None:
        ctx.session.add(
            m.Receipt(
                account_id=ctx.account_id, key=LEDGER, request_hash=digest, result=state, created_at=ctx.now
            )
        )
    else:
        row.result = state


def _open(ctx, catalog, account):
    if ctx.data.crisis_v2.current(ctx.now) != catalog.seasonId or account.current_season != catalog.seasonId:
        raise DomainError("CRISIS_V2_SHOP_CLOSED", "本地商店仅在配置的赛季内可交易", 409)


def view(ctx, catalog):
    account, _, _, state, offers = _state(ctx, catalog)
    return {
        "source": "local-config",
        "seasonId": catalog.seasonId,
        "coin": account.shop_coin,
        "claimedMaps": state["credits"],
        "offers": [
            offer.model_dump() | {"remaining": offer.stock - state["purchases"].get(offer.id, 0)}
            for offer in offers.values()
        ],
    }


def claim_credit(ctx, catalog, map_id):
    account, digest, row, state, _ = _state(ctx, catalog)
    _open(ctx, catalog, account)
    if map_id not in catalog.credits:
        raise DomainError("CRISIS_V2_SHOP_UNKNOWN_MAP", "该地图无本地商店代币奖励", 404)
    progress = ctx.session.get(m.CrisisV2MapProgress, (ctx.account_id, catalog.seasonId, map_id))
    if progress is None or not crisis_v2._map(ctx, progress).state:
        raise DomainError("CRISIS_V2_SHOP_NOT_READY", "需先通关对应地图", 409)
    if map_id in state["credits"]:
        raise DomainError("CRISIS_V2_SHOP_CREDIT_TAKEN", "该地图代币已领取", 409)
    earned = catalog.credits[map_id]
    account.shop_coin += earned
    state["credits"].append(map_id)
    _save(ctx, digest, row, state)
    return {"mapId": map_id, "earned": earned, "coin": account.shop_coin}


def buy(ctx, catalog, offer_id):
    account, digest, row, state, offers = _state(ctx, catalog)
    _open(ctx, catalog, account)
    offer = offers.get(offer_id)
    if offer is None:
        raise DomainError("CRISIS_V2_SHOP_UNKNOWN_OFFER", "本地商店无该商品", 404)
    count = state["purchases"].get(offer_id, 0)
    if count >= offer.stock:
        raise DomainError("CRISIS_V2_SHOP_SOLD_OUT", "本地库存不足", 409)
    if account.shop_coin < offer.price:
        raise DomainError("CRISIS_V2_SHOP_INSUFFICIENT", "本地商店代币不足", 409)
    entries = (
        _material_pack(ctx.data, offer.itemId)
        if offer.itemType == "ITEM_PACK"
        else [{"id": offer.itemId, "type": offer.itemType, "count": 1}]
    )
    rewards = ctx.rewards(entries)
    account.shop_coin -= offer.price
    state["purchases"][offer_id] = count + 1
    _save(ctx, digest, row, state)
    return {"offerId": offer_id, "cost": offer.price, "coin": account.shop_coin, "rewards": rewards}
