"""Owned floor-bound authored shop visits; no inferred official stock pool."""

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict
from types import SimpleNamespace

from sqlalchemy import select

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_giveup import confirmed_closure
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_progress import Layout, index, row_index, zone_for
from terralocal.server.domain.rogue_shop import Purchase, decide, invalid, replay
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_shops import POLICY, Offer, compile_shop
from terralocal.server.persistence import models as m


def rows(session, run_id):
    shops = session.scalars(select(m.RogueShopVisit).where(m.RogueShopVisit.run_id == run_id)
                           .order_by(m.RogueShopVisit.zone_index, m.RogueShopVisit.node_x,
                                     m.RogueShopVisit.node_y)).all()
    banks = {b.visit_id: b for b in session.scalars(select(m.RogueBankVisit).where(m.RogueBankVisit.run_id == run_id))}
    for shop in shops:
        shop._bank_visit = banks.get(shop.id)
    return shops


def read_rows(con, run_id):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='rlv2_shop_visits'").fetchone():
        return []
    from terralocal.server.domain.rogue_banks import read_visits

    banks, result = read_visits(con, run_id), []
    for raw in con.execute("SELECT * FROM rlv2_shop_visits WHERE run_id=? ORDER BY zone_index,node_x,node_y", (run_id,)):
        value = dict(raw)
        for key in ("quote", "before", "purchases"):
            value[key] = json.loads(value[key])
        result.append(SimpleNamespace(**value, _bank_visit=banks.get(value['id'])))
    return result


def quote(data, row):
    q = row.quote
    if (type(q) is not dict or set(q) != {"id", "offers", "evidence"}
            or type(q["offers"]) is not list or any(type(o) is not dict
                or set(o) not in ({"index", "item_id", "price"}, {"index", "item_id", "price", "elite_pool"},
                                  {"index", "item_id", "price", "direct_pool"},
                                  {"index", "item_id", "price", "relic_layer"})
                or "elite_pool" in o and (type(o["elite_pool"]) is not list or not o["elite_pool"])
                or "direct_pool" in o and (type(o["direct_pool"]) is not list or not o["direct_pool"])
                for o in q["offers"])):
        raise invalid()
    return compile_shop(data, q["id"], tuple(Offer(**(o | {k: tuple(o.get(k, [])) for k in ("elite_pool", "direct_pool")}))
                                           for o in q["offers"]), evidence=q["evidence"])


def offer_payload(offer):
    value = {"index": offer.index, "item_id": offer.item_id, "price": offer.price}
    if offer.elite_pool:
        value["elite_pool"] = list(offer.elite_pool)
    if offer.direct_pool:
        value["direct_pool"] = list(offer.direct_pool)
    if offer.relic_layer is not None:
        value["relic_layer"] = offer.relic_layer
    return value


def rule_hash(run, draft, row, q):
    return fingerprint({"policy": POLICY, "quote": q.digest, "run": run.id, "seed": run.seed,
        "map": draft.plan_hash, "zone": row.zone_index, "x": row.node_x, "y": row.node_y})


def validate(data, run, draft, zone, row):
    from terralocal.server.domain.rogue_settlement import PROPERTIES

    try:
        zone = zone_for(zone, row)
        q = quote(data, row)
        from terralocal.server.gamedata.rogue_battle_effects import require_open, supported

        for offer in q.offers.values():
            if offer.relic_layer is not None and supported(data, offer.item_id):
                require_open(data, offer.item_id, run.created_at)
            if offer.index in q.support_indices:
                data.rogue_support_tools.require(offer.item_id, run.created_at)
        node = next(n for n in zone.nodes if n.pos == Point(row.node_x, row.node_y))
        if (run.topic_id != "rogue_1" or run.mode != "NORMAL" or run.grade != 0
                or q.data_hash != run.gamedata_hash or row.account_id != run.account_id
                or row.run_id != run.id
                or node.kind != "SHOP" or str(uuid.UUID(row.id)) != row.id
                or row.rule_hash != rule_hash(run, draft, row, q)
                or type(row.prepared_at) is not int or not run.created_at <= row.prepared_at < 2**63
                or type(row.purchases) is not list or len(row.purchases) > len(q.offers)):
            raise invalid()
        if row.state == "PREPARED":
            if row.before != {} or row.purchases or any(v is not None for v in (
                    row.first_ticket, row.entered_at, row.ended_at)):
                raise invalid()
            if run.ended_at is not None and row.prepared_at > run.ended_at:
                raise invalid()
            if getattr(row, "_bank_visit", None) is not None:
                from terralocal.server.domain.rogue_banks import financial

                financial(data, run, draft, row, row._bank_visit)
            return q, None
        if (row.state not in ("ACTIVE", "FINISHED", "ABANDONED")
                or type(row.before) is not dict or set(row.before) != set(PROPERTIES)
                or any(type(v) is not int or not 0 <= v < 2**31 for v in row.before.values())
                or type(row.entered_at) is not int
                or not max(row.prepared_at, draft.activated_at or 0) <= row.entered_at < 2**63):
            raise invalid()
        purchases = []
        for p in row.purchases:
            if type(p) is not dict or set(p) != {"index", "at", "ticket"}:
                raise invalid()
            purchases.append(Purchase(**p))
        if getattr(row, "_bank_visit", None) is not None:
            from terralocal.server.domain.rogue_banks import financial

            _, state = financial(data, run, draft, row, row._bank_visit)
        else:
            state = replay(q, row.before["gold"], row.entered_at, row.first_ticket,
                           tuple(purchases), row.ended_at)
        if row.state == "ACTIVE":
            if state.ended_at is not None or run.ended_at is not None:
                raise invalid()
        elif state.ended_at is None or row.state == "ABANDONED" and run.state != "ABANDONED" and not confirmed_closure(run):
            raise invalid()
        if run.ended_at is not None and max(row.entered_at, row.ended_at or 0) > run.ended_at:
            raise invalid()
        return q, state
    except (DomainError, ValueError, TypeError, KeyError, AttributeError, StopIteration) as exc:
        raise invalid() from exc


def prepare(ctx, bindings, *, zone_index=None):
    """Internal reviewed plans only; no client-supplied item/price path."""
    from terralocal.server.domain.rogue_visits import context

    run, _, zone, draft = context(ctx)
    number = index(zone) if zone_index is None else zone_index
    if type(number) is not int or number < index(zone):
        raise invalid()
    zone_for(zone, SimpleNamespace(zone_index=number))
    if type(bindings) is not dict or not 1 <= len(bindings) <= 32:
        raise invalid()
    planned_relics = set()
    for point, q in bindings.items():
        if not isinstance(point, Point):
            raise invalid()
        # Current nonstack supply admits each effect once. Validate authored
        # plans before exposing a slot, including stock on later floors.
        relic_ids = {o.item_id for o in q.offers.values() if o.relic_layer is not None}
        from terralocal.server.domain import rogue_loot_plans

        if relic_ids & rogue_loot_plans.candidate_ids(rogue_loot_plans.rows(ctx.session, run.id)):
            raise DomainError("ROGUE_RELIC_SUPPLY_CONFLICT", "收藏品已配置为战斗奖励，不能再配置到商店", 409)
        other_ids = {o.item_id for saved in rows(ctx.session, run.id)
                     if saved.zone_index != number or (saved.node_x, saved.node_y) != (point.x, point.y)
                     for o in quote(ctx.data, saved).offers.values() if o.relic_layer is not None}
        if relic_ids & (other_ids | planned_relics):
            raise DomainError("ROGUE_RELIC_SUPPLY_CONFLICT", "无叠层收藏品不能重复配置到多个商店", 409)
        planned_relics.update(relic_ids)
        old = next((r for r in rows(ctx.session, run.id) if r.zone_index == number
                    and (r.node_x, r.node_y) == (point.x, point.y)), None)
        payload = {"id": q.id, "offers": [offer_payload(o) for o in q.offers.values()], "evidence": q.evidence}
        if old:
            validate(ctx.data, run, draft, zone, old)
            if canonical(old.quote) != canonical(payload):
                raise DomainError("ROGUE_SHOP_PLAN_CONFLICT", "商店已有不同的持久报价", 409)
            continue
        row = m.RogueShopVisit(id=str(uuid.uuid4()), run_id=run.id, account_id=ctx.account_id,
            zone_index=number, node_x=point.x, node_y=point.y, quote=payload, rule_hash="", state="PREPARED",
            before={}, first_ticket=None, purchases=[], prepared_at=max(ctx.now, draft.activated_at),
            entered_at=None, ended_at=None)
        row.rule_hash = rule_hash(run, draft, row, q)
        validate(ctx.data, run, draft, zone, row)
        ctx.session.add(row)
    ctx.session.flush()


def enter(ctx, run, children, zone, draft, point, boundary):
    from terralocal.server.domain.rogue_settlement import PROPERTIES

    row = next((r for r in rows(ctx.session, run.id) if r.zone_index == index(zone)
                and (r.node_x, r.node_y) == (point.x, point.y)), None)
    if row is None:
        raise DomainError("ROGUE_SHOP_PLAN_MISSING", "缺少此商店匹配版本的已保存报价", 503)
    if row.state != "PREPARED":
        raise DomainError("ROGUE_NODE_PASSED", "不能返回已离开的商店", 409)
    row.before = {key: getattr(run, key) for key in PROPERTIES}
    row.first_ticket = len(children[2])
    row.entered_at, row.state = max(ctx.now, row.prepared_at, boundary), "ACTIVE"
    from terralocal.server.domain.rogue_banks import enter as enter_bank

    enter_bank(ctx, run, draft, row)
    ctx.session.flush()
    validate(ctx.data, run, draft, zone, row)
    return {}


def action(ctx, buy, recycle, leave, *, bank_key=None):
    from terralocal.server.domain.rogue_visits import authorize, context, path_in_session

    authorize(ctx)
    run, children, zone, draft = context(ctx)
    entries, _, _, _ = path_in_session(ctx, run, zone)
    if not entries and isinstance(zone, Layout) and leave == 1 and not buy and not recycle:
        previous = path_in_session(ctx, run, zone, whole=True)[0]
        if previous and previous[-1][2] == "shop" and row_index(previous[-1][3]) == zone.index - 1:
            return {}  # Leave retry after advancing into an unvisited next floor.
    if not entries or entries[-1][2] != "shop":
        raise DomainError("ROGUE_SHOP_NOT_PENDING", "当前不是可处理的商店", 409)
    row = entries[-1][3]
    q, old = validate(ctx.data, run, draft, zone, row)
    if getattr(row, "_bank_visit", None) is not None:
        from terralocal.server.domain.rogue_banks import transact

        if recycle or len(buy) > 1 or leave and buy:
            raise DomainError("ROGUE_SHOP_BRANCH", "此商店交易分支尚未接通，未扣款或发奖", 501)
        if not leave and len(buy) != 1:
            raise DomainError("ROGUE_SHOP_ACTION", "请选择明确的购买或离开操作")
        state = transact(ctx, run, draft, row, key=bank_key, kind="LEAVE" if leave else "BUY",
                         index=buy[0] if buy else None)
    else:
        state = decide(q, row.before["gold"], row.entered_at, row.first_ticket, old.purchases, row.ended_at,
            buy=tuple(buy), recycle=tuple(recycle), leave=leave, at=ctx.now,
            recruit_pending=any(t.state != "DONE" for t in children[2]))
    if state == old:
        if row.state == "FINISHED":
            from terralocal.server.domain.rogue_progress import advance

            advance(ctx)
        return {}
    run.gold = state.gold
    row.purchases = [asdict(p) for p in state.purchases]
    if state.ended_at is not None:
        row.state, row.ended_at = "FINISHED", state.ended_at
    purchase = state.purchases[-1] if len(state.purchases) > len(old.purchases) else None
    if purchase:
        offer = q.offers[purchase.index]
        if purchase.index in q.support_indices:
            # The committed ordered purchase is the owned tool's authority.
            # Full history replay projects/replaces it; no relic/ticket row is created.
            ctx.data.rogue_support_tools.require(offer.item_id, run.created_at)
        elif purchase.ticket is None:
            if offer.relic_layer is None:
                raise DomainError("ROGUE_SHOP_GRANT_UNSUPPORTED", "此商品的完整发放尚未接通，未扣款或发奖", 501)
            if any(r.item_id == offer.item_id for r in children[1]):
                raise DomainError("ROGUE_RELIC_ALREADY_OWNED", "探索已拥有此无叠层收藏品，未购买", 409)
            ctx.session.add(m.RogueRunRelic(run_id=run.id, ordinal=len(children[1]), item_id=offer.item_id,
                count=1, layer=offer.relic_layer, acquired_at=purchase.at, used=False))
            from terralocal.server.domain.rogue_relics import resources_after_relic

            try:
                resources = resources_after_relic(ctx.data, offer.item_id,
                    {"gold": run.gold, "hope_max": run.hope_max, "squad_capacity": run.squad_capacity,
                     "hp": run.hp, "hp_max": run.hp_max}, credit_gold=False)
            except ValueError as exc:
                raise DomainError("ROGUE_SHOP_RESOURCE_LIMIT", "即时资源奖励超出范围，未购买", 409) from exc
            run.hope_max, run.squad_capacity = resources["hope_max"], resources["squad_capacity"]
            run.hp = resources["hp"]
        else:
            ctx.session.add(m.RogueRunTicket(run_id=run.id, ordinal=purchase.ticket,
                item_id=offer.item_id, state="CREATE", created_at=purchase.at,
                elite_pool=list(offer.elite_pool), direct_pool=list(offer.direct_pool)))
    ctx.session.flush()
    if purchase and purchase.ticket is not None:
        from terralocal.server.domain.rogue_recruit import activate

        activate(ctx, str(purchase.ticket))
    if row.state == "FINISHED":
        from terralocal.server.domain.rogue_progress import advance

        advance(ctx)
    return {}


def owns_pending_ticket(ctx, run, ordinal):
    from terralocal.server.domain.rogue_progress import in_session
    from terralocal.server.domain.rogue_visits import path_in_session

    zone = in_session(ctx, run)
    entries = path_in_session(ctx, run, zone)[0]
    return bool(entries and entries[-1][2] == "shop" and entries[-1][3].state == "ACTIVE"
                and any(p["ticket"] == ordinal for p in entries[-1][3].purchases))


def pending(ctx, run, zone):
    from terralocal.server.domain.rogue_visits import path_in_session

    entries, point, _, _ = path_in_session(ctx, run, zone)
    if not entries or entries[-1][2] != "shop":
        return None
    row = entries[-1][3]
    if row.state == "FINISHED":
        return point.wire(), None
    q, state = validate(ctx.data, run, ctx.session.get(m.RogueMapDraft, run.id), zone, row)
    sold = {p.index for p in state.purchases}
    payload = {"index": row.id, "type": "SHOP", "content": {"shop": {
        "bank": {"cost": 0, "open": False, "canPut": False, "canWithdraw": False,
                 "withdraw": 0, "withdrawLimit": 0}, "id": q.id,
        # Frozen default ParseGoodsItemFromGoodsData maps count<1 to isSoldout;
        # retain slot order rather than making later items shift after buying.
        "goods": [{"index": o.index, "itemId": o.item_id, "count": int(o.index not in sold), "priceId": q.gold_id,
                   "priceCount": o.price, "origCost": o.price, "displayPriceChg": False, "ban": 0}
                  for o in q.offers.values()],
        "canBattle": False, "hasBoss": False, "showRefresh": False, "refreshCnt": 0, "refreshCost": 0,
        "recycleGoods": [], "recycleCount": 0, "buyLimit": 0, "hasBuyLimit": False}, "done": False}}
    from terralocal.server.domain.rogue_banks import pending as bank_pending

    bank = bank_pending(ctx.data, run, ctx.session.get(m.RogueMapDraft, run.id), row)
    if bank:
        payload["content"]["shop"]["bank"], payload["content"]["shop"]["hasBoss"] = bank
    return point.wire(), payload


def abandon(ctx, run):
    boundary = run.created_at
    for row in rows(ctx.session, run.id):
        boundary = max(boundary, row.prepared_at, row.ended_at or row.entered_at or 0,
                       getattr(getattr(row, "_bank_visit", None), "prepared_at", 0),
                       *(p["at"] for p in row.purchases))
        if row.state == "ACTIVE":
            if getattr(row, "_bank_visit", None) is not None:
                from terralocal.server.domain.rogue_banks import transact

                transact(ctx, run, ctx.session.get(m.RogueMapDraft, run.id), row,
                         key="give-up:" + row.id, kind="LEAVE", forced_close=True)
            row.state, row.ended_at = "ABANDONED", max(ctx.now, boundary)
            if getattr(row, "_bank_visit", None) is not None:
                # The financial close may be clamped by a later bank action.
                row.ended_at = max(row.ended_at, row._bank_visit.journal["actions"][-1]["at"])
            boundary = row.ended_at
    return boundary


def preflight(path):
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='rlv2_shop_visits'").fetchone():
            from terralocal.server.persistence.migrations import CURRENT_REVISIONS

            v = con.execute("SELECT version_num FROM alembic_version").fetchone() if con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone() else None
            if v and v[0] in CURRENT_REVISIONS:
                raise ValueError(invalid().message)
            return
        if con.execute("SELECT 1 FROM rlv2_shop_visits s LEFT JOIN rlv2_runs r ON s.run_id=r.id "
                       "WHERE r.id IS NULL OR s.account_id!=r.account_id LIMIT 1").fetchone():
            raise ValueError(invalid().message)
