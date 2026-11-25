"""Local unlock policy: time gate plus a clear on the attached temporary map."""

from terralocal.server.domain import crisis_v2
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence.models import CrisisV2MapProgress


def unlock(ctx, season_id: str, map_id: str, slot_id: str) -> dict:
    if not crisis_v2.available(ctx.data):
        raise DomainError("CRISIS_V2_NOT_CONFIGURED", "尚未导入匹配的危机合约信息源", 503)
    account = crisis_v2._account(ctx)
    catalog = ctx.data.crisis_v2
    if catalog.current(ctx.now) != season_id or account.current_season != season_id:
        raise DomainError("CRISIS_V2_UNLOCK_CLOSED", "符文解锁仅支持当前本地赛季", 409)
    if catalog.permanent.get(season_id) != map_id:
        raise DomainError("CRISIS_V2_UNLOCK_MAP", "额外符文只属于该赛季的永久地图", 404)

    info = catalog.info(season_id)
    locks = info["mapDetailDataMap"][map_id]["dailyRuneUnlcokDataMap"]
    node = catalog.rules[(season_id, map_id)].nodes.get(slot_id)
    if not node or node.kind != "NORMAL" or not node.lockable or node.rune is None:
        raise DomainError("CRISIS_V2_UNLOCK_UNKNOWN", "没有此额外符文", 404)
    rule = locks.get(slot_id)
    malformed = DomainError("CRISIS_V2_UNLOCK_INCOMPATIBLE", "符文解锁配置或存档无法验证", 503)
    if type(rule) is not dict:
        raise malformed
    attached, starts = rule.get("mapAttachOn"), rule.get("startTs")
    if (type(attached) is not str or attached not in catalog.temporary[season_id]
            or type(starts) is not int or not 0 <= starts < 2**63):
        raise malformed
    if ctx.now < starts:
        raise DomainError("CRISIS_V2_UNLOCK_NOT_OPEN", "尚未到达额外符文开放时间", 409)

    permanent = ctx.session.get(CrisisV2MapProgress, (ctx.account_id, season_id, map_id))
    temporary = ctx.session.get(CrisisV2MapProgress, (ctx.account_id, season_id, attached))
    try:
        if permanent is None or temporary is None:
            raise ValueError("incomplete account maps")
        own_map = crisis_v2._map(ctx, permanent)
        source_map = crisis_v2._map(ctx, temporary)
    except (ValueError, TypeError, KeyError) as exc:
        raise malformed from exc
    if own_map.exRunes.get(slot_id, 0) >= 2:
        raise DomainError("CRISIS_V2_UNLOCK_ALREADY_OPEN", "该符文已解锁", 409)
    if not source_map.state:
        raise DomainError("CRISIS_V2_UNLOCK_NOT_READY", "需通关关联临时地图", 409)
    permanent.extra_runes = {**permanent.extra_runes, slot_id: 2}
    return {"seasonId": season_id, "mapId": map_id, "slotId": slot_id,
            "sourceMapId": attached, "state": 2}