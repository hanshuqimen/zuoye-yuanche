"""Base relic quotes from validated account history and the current run.

No persisted/client-supplied collection claim is an eligibility authority.
Selection remains a server-authored plan; natural sampling is a separate rule.
"""

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_shops import compile_shop

POLICY = "rogue1-history-backed-merchant-quote-v1"


def quote(ctx, shop_id, slots):
    """Compile explicitly selected stock without changing any saved quote.

    A planner passes only slot/item IDs. Account, run, time, eligibility,
    ownership and price come from verified server state. Missing eligibility
    remains unknown, even for items with no textual unlock condition.
    """
    from terralocal.server.domain.rogue_collection import facts, project
    from terralocal.server.domain.rogue_visits import context

    run, children, _, _ = context(ctx)
    ctx.data.rogue_topics.topic(run.topic_id, at=run.created_at)
    found = facts(ctx)
    collection = project({"collect": {"relic": {}}}, found.attained, found.eligibility)
    # Bank discovery alone is not qualification. These two items may have
    # originated in an explicit QA/event source before the bank was unlocked.
    from terralocal.server.gamedata.rogue_bank_items import SOURCES as BANK_ITEMS

    bank_scope = None
    bank_slots = type(slots) is tuple and all(type(slot) is tuple and len(slot) == 2
                                            and all(type(v) is str for v in slot) for slot in slots)
    if bank_slots and any(key in BANK_ITEMS for _, key in slots):
        from terralocal.server.domain.rogue_bank_items import qualification

        bank = qualification(ctx, run)
        bank_scope = bank.digest
        for key in BANK_ITEMS:
            collection["collect"]["relic"].pop(key, None)
            if key in bank.items:
                collection["collect"]["relic"][key] = {"state": 1, "progress": []}
    try:
        catalog = ctx.data.rogue_merchant_relics
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DomainError("ROGUE_MERCHANT_INCOMPATIBLE", "商店基础报价与匹配数据不一致；请保留原数据", 503) from exc
    try:
        base = catalog.compile(shop_id, slots,
            topic=run.topic_id, mode=run.mode, grade=run.grade, at=run.created_at,
            collection=collection["collect"]["relic"],
            owned=frozenset(r.item_id for r in children[1] if r.ordinal > 0))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DomainError("ROGUE_MERCHANT_ELIGIBILITY_MISSING",
                          "所选商品缺少匹配的探索资格、基础报价或完整效果；未生成报价", 409) from exc
    scope = fingerprint({"policy": POLICY, "account": ctx.account_id, "run": run.id,
                         "seed": run.seed, "quote": base.digest})
    if bank_scope is not None:
        scope = fingerprint({"merchant": scope, "bank_qualification": bank_scope})
    from terralocal.server.gamedata.rogue_base_relics import SOURCES as BASE_ITEMS
    from terralocal.server.gamedata.rogue_base_relics import available as base_available

    if bank_slots and any(key in BASE_ITEMS for _, key in slots) and base_available(ctx.data):
        scope = fingerprint({"merchant": scope, "base_availability": ctx.data.rogue_base_relics.fingerprint})
    return compile_shop(ctx.data, base.id, tuple(base.offers.values()),
                        evidence=base.evidence + "; driver=" + POLICY + "; scope=" + scope)
