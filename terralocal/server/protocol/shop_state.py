"""Purchase counters, assembled independently of storefront offer definitions.

The info lists represent purchases in this save, not purchasable offers. Active
storefronts and purchasing remain separately tracked features until implemented.
"""

from terralocal.server.domain.voucher_shop import active_cycle, project
from terralocal.server.persistence import models as m


def purchase_counters(ctx, *, at: int | None = None) -> dict:
    state = ctx.rows(m.ShopState)
    period_at = ctx.now if at is None else at

    def info(shop, period="permanent"):
        return [{"id": row.offer_id, "count": row.bought} for row in sorted(
            state, key=lambda row: row.offer_id) if row.shop_id == shop and row.period == period]

    cycles = ctx.profile.flags.get("shopCycles", {})
    result = {"CASH": {"info": info("CASH")}, "FURNI": {"info": info("FURNI")},
              "SKIN": {"info": info("SKIN"), "gachaGood": {"info": []}}}
    for shop in ("LS", "HS", "ES", "SOCIAL", "CLASSIC"):
        cycle = cycles.get(shop, {})
        result[shop] = {"curShopId": cycle.get("shopId", ""),
                        "info": info(shop, cycle.get("period", "permanent"))}
    result["LS"]["curGroupId"] = cycles.get("LS", {}).get("groupId", "")
    result["LS"]["lggCostTotal"] = 0
    # The frozen Android client deserializes this into
    # Dictionary<string, PlayerGoodProgressData>, not a purchase list.
    for shop in ("HS", "CLASSIC", "ES", "SOCIAL"):
        # These frozen types do not inherit PlayerCommonShopProgressData.
        result[shop].pop("curShopId")
    for shop in ("HS", "CLASSIC", "ES"):
        result[shop]["progressInfo"] = {}
    result["ES"]["lastClick"] = 0
    for shop in ("LS", "HS", "CLASSIC", "ES"):
        cycle = active_cycle(ctx, shop, at=period_at)
        if cycle:
            result[shop] = project(ctx, cycle)
    from terralocal.server.domain.gift_packs import project as gift_progress

    result["GP"] = gift_progress(ctx, at=period_at)
    return result
