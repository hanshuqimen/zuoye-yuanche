"""Account-scoped refresh of known data and uninitialized system state.

Refreshing an empty base/event/medal save does not implement those systems.
Existing state that requires unavailable settlement is rejected explicitly.
"""

from enum import IntFlag

from terralocal.server.domain.errors import DomainError, NotImplementedFeature
from terralocal.server.persistence import models as m


class Module(IntFlag):
    # Read from Torappu.PlayerSyncModuleMask in the frozen 2.7.71 metadata.
    UNREAD_MAILS = 1
    FRIEND_REQ = 2
    ANNOUNCE_VER = 4
    REFRESH_USER_CARD = 8
    GOOD_PURCHASE_STATE = 16
    CASH_PURCHASE_STATE = 32
    CLUE_STATE = 64
    SYNC_BUILDING = 128
    SYNC_CRISIS = 256
    SYNC_ACTIVITY = 512
    SYNC_MEDAL = 1024
    CHECK_FORBIDDEN = 2048
    SYNC_ACTIVITY_FIXED_INTERVAL = 4096


SUPPORTED = sum(int(value) for value in Module if value != Module.SYNC_CRISIS)
ANNOUNCEMENT_VERSION = "1"
# Frozen startup uses 3807; native cross-day return to home uses 3207.
# Accept that observed calendar checkpoint explicitly, without treating an
# arbitrary smaller subset as a successful cross-day refresh.
COMPLETE_REFRESH_MODULES = int(Module.UNREAD_MAILS | Module.FRIEND_REQ | Module.ANNOUNCE_VER
                               | Module.REFRESH_USER_CARD | Module.GOOD_PURCHASE_STATE
                               | Module.CLUE_STATE | Module.SYNC_BUILDING | Module.SYNC_ACTIVITY
                               | Module.SYNC_MEDAL | Module.CHECK_FORBIDDEN)
HOME_REFRESH_MODULES = int(Module.UNREAD_MAILS | Module.FRIEND_REQ | Module.ANNOUNCE_VER
                          | Module.SYNC_BUILDING | Module.SYNC_MEDAL | Module.CHECK_FORBIDDEN)


def is_calendar_refresh(modules: int) -> bool:
    return modules == HOME_REFRESH_MODULES or modules & COMPLETE_REFRESH_MODULES == COMPLETE_REFRESH_MODULES


def last_refreshed_at(ctx) -> int:
    value = ctx.profile.flags.get("lastRefreshTs", ctx.profile.registered_at)
    # Largest UTC timestamp that still fits DateTime in the client's UTC+8 zone.
    if type(value) is not int or not 0 <= value <= 253_402_271_999:
        raise DomainError("INVALID_REFRESH_STATE", "存档中的刷新时间非法", 503)
    return value


def complete_refresh(ctx, modules: int) -> None:
    """Record an observed successful calendar refresh in its transaction.

    Call only after prepare has validated all requested modules. Period-scoped
    mission/shop views select the current period without deleting history.
    Existing base/event/medal states needing unknown settlement still fail in
    prepare; this checkpoint grants no rewards and implements no such systems.
    A clock rewind changes this acknowledgement, never reward/claim history.
    """
    if not is_calendar_refresh(modules):
        return
    from terralocal.server.domain.campaign import initialize
    from terralocal.server.domain.campaign_weeks import advance

    initialize(ctx)
    advance(ctx)
    previous = last_refreshed_at(ctx)
    if ctx.clock.period("daily", at=previous) != ctx.clock.period("daily", at=ctx.now):
        ctx.profile.flags = {**ctx.profile.flags, "lastRefreshTs": ctx.now}


def prepare(ctx, modules: int, goods: dict[str, list[str]] | None = None) -> dict:
    if modules & ~SUPPORTED:
        raise NotImplementedFeature("syncStatus 的未支持模块")
    selected = Module(modules)
    if selected & Module.FRIEND_REQ and ctx.profile.flags.get("friendRequests"):
        raise NotImplementedFeature("好友申请刷新")
    building = ctx.session.get(m.Building, ctx.account_id)
    if selected & Module.SYNC_BUILDING and (building or ctx.rows(m.BuildingRoom)
                                           or ctx.rows(m.BuildingOperatorAssignment)):
        raise NotImplementedFeature("已有基建的离线结算")
    if selected & (Module.SYNC_ACTIVITY | Module.SYNC_ACTIVITY_FIXED_INTERVAL) and ctx.rows(m.EventProgress):
        raise NotImplementedFeature("已有活动的刷新")
    if selected & Module.SYNC_MEDAL and ctx.profile.flags.get("medals"):
        raise NotImplementedFeature("已有蚀刻章的刷新")
    # These named modules use the fieldless PlayerSyncResult base contract;
    # their actual account state is supplied in playerDataDelta. The three
    # derived result contracts must include their own fields below.
    result = {str(int(module)): {} for module in Module if selected & module}
    if selected & Module.ANNOUNCE_VER:
        result[str(int(Module.ANNOUNCE_VER))] = {
            "announcementPopUpVersion": ANNOUNCEMENT_VERSION, "announcementVersion": ANNOUNCEMENT_VERSION}
    if selected & Module.GOOD_PURCHASE_STATE:
        from terralocal.server.domain.voucher_shop import purchase_limits

        requested = goods or {}
        capacities, recognized = purchase_limits(ctx, requested)
        from terralocal.server.domain.gift_packs import purchase_limits as pack_limits

        pack_capacities, pack_recognized = pack_limits(ctx, requested)
        capacities.update(pack_capacities)
        recognized.update(pack_recognized)
        for row in ctx.rows(m.ShopState):
            category = ("GP" if row.shop_id.startswith("GP:") else
                        "CASH" if row.shop_id == "FURNI" else row.shop_id)
            if (row.bought and row.offer_id in requested.get(category, [])
                    and (category, row.offer_id) not in recognized):
                raise NotImplementedFeature("已购买商品的 goodPurchaseState 响应")
        # Known ordinary offers report total capacity, never bought/remaining.
        # Unknown specialized queried purchases still need their own contract.
        # ELF-resolved field type is GetGoodPurchaseStateResponse, whose result
        # field is Dictionary<string, int>. Omitting this wrapper leaves the
        # client's dictionary null even when no queried purchases exist.
        result[str(int(Module.GOOD_PURCHASE_STATE))] = {"goodPurchaseState": {"result": capacities}}
    if selected & Module.CHECK_FORBIDDEN:
        bans = ctx.profile.flags.get("featureBans", {})
        if (not isinstance(bans, dict) or set(bans) - {"gacha", "shop"} or any(
                not isinstance(values, list) or len(values) > 2048 or any(
                    not isinstance(value, str) or not 1 <= len(value) <= 96 for value in values)
                for values in bans.values())):
            raise DomainError("INVALID_LOCAL_RESTRICTIONS", "本地功能限制配置非法", 503)
        result[str(int(Module.CHECK_FORBIDDEN))] = {key: bans.get(key, []) for key in ("gacha", "shop")}
    # No rewards, event enrollment or base production are invented here.
    # complete_refresh records the validated checkpoint separately, between
    # the before/after snapshots so the client receives its timestamp delta.
    return result


def push_flags(ctx) -> dict:
    from terralocal.server.domain.gift_packs import has_free_level_pack

    unread = any(not row.read and (row.expires_at is None or row.expires_at > ctx.now) for row in ctx.rows(m.Mail))
    building = ctx.session.get(m.Building, ctx.account_id)
    return {"status": ctx.profile.flags.get("loginTime", ctx.profile.last_online_at),
            "hasGifts": unread, "hasClues": bool(building and building.clues),
            "hasFriendRequest": bool(ctx.profile.flags.get("friendRequests")),
            "hasFreeLevelGP": has_free_level_pack(ctx)}
