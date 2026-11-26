"""Local treasure claims, not a native client protocol adapter."""

from terralocal.server.domain import crisis_v2
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence.models import CrisisV2MapProgress

SUPPORTED_TYPES = frozenset({"CHAR_SKIN", "FURN", "ITEM_PACK"})


def _material_pack(data, pack_id):
    """Local policy: grant one flat material bundle, not a reusable pack item."""
    table = data.table("item_table").get("itemPackInfos")
    pack = table.get(pack_id) if type(table) is dict else None
    entries = pack.get("content") if type(pack) is dict and pack.get("packId") == pack_id else None
    missing = DomainError("CRISIS_V2_CLAIM_INCOMPATIBLE", "任务材料包缺少有效的同版本内容", 503)
    if type(entries) is not list or not 1 <= len(entries) <= 128:
        raise missing
    grant, seen = [], set()
    for entry in entries:
        if (type(entry) is not dict or set(entry) != {"id", "type", "count"}
                or entry["type"] != "MATERIAL" or type(entry["id"]) is not str or entry["id"] in seen
                or type(entry["count"]) is not int or not 1 <= entry["count"] <= 2_000_000_000):
            raise missing
        try:
            item_type = data.item(entry["id"])["itemType"]
        except (KeyError, DomainError) as exc:
            raise missing from exc
        if item_type != "MATERIAL":
            raise missing
        seen.add(entry["id"])
        grant.append(dict(entry))
    return grant


def resolve(data, season_id, map_id, slot_id, saved, now):
    """Resolve an earned treasure without changing inventory or mission state.

    Shared by the explicit local helper and the frozen native batch adapter.
    Material-pack expansion remains the documented local policy above.
    """
    if not crisis_v2.available(data):
        raise DomainError("CRISIS_V2_NOT_CONFIGURED", "尚未导入匹配的危机合约信息源", 503)
    catalog = data.crisis_v2
    if not season_id or catalog.current(now) != season_id:
        raise DomainError("CRISIS_V2_CLAIM_CLOSED", "本地领奖仅支持当前赛季", 409)
    if catalog.permanent.get(season_id) != map_id:
        raise DomainError("CRISIS_V2_CLAIM_MAP", "本地领奖仅支持该赛季的永久地图", 404)
    try:
        if saved is None:
            raise ValueError("missing permanent progress")
        objective = catalog.objectives(season_id, map_id).treasures.get(slot_id)
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("CRISIS_V2_CLAIM_INCOMPATIBLE", "任务条件或存档无法验证", 503) from exc
    if objective is None:
        raise DomainError("CRISIS_V2_CLAIM_UNKNOWN", "永久地图没有该宝藏任务", 404)
    entry = saved.reward.get(slot_id)
    if entry is None or entry.state == 0:
        raise DomainError("CRISIS_V2_CLAIM_NOT_READY", "尚未达到任务领奖条件", 409)
    if entry.progress < objective.required or not saved.state:
        raise DomainError("CRISIS_V2_CLAIM_INCOMPATIBLE", "可领取标记与完成进度不一致", 503)
    if entry.state == 2:
        raise DomainError("CRISIS_V2_CLAIM_ALREADY_TAKEN", "任务奖励已领取", 409)
    info = catalog.info(season_id)
    status = info["mapStageDataMap"][map_id]
    start, end = status["startTime"], status["rewardEndTime"]
    if (start != -1 and now < start) or (end != -1 and now > end):
        raise DomainError("CRISIS_V2_CLAIM_CLOSED", "不在该地图的本地领取窗口内", 409)

    detail = info["mapDetailDataMap"][map_id]
    reward = detail["rewardNodeDataMap"][slot_id].get("reward")
    if reward is None:
        raise DomainError("CRISIS_V2_CLAIM_UNSUPPORTED", "此任务没有已适配的明确奖励", 501)
    if (type(reward) is not dict or set(reward) != {"id", "type", "count"}
            or type(reward["id"]) is not str or not 1 <= len(reward["id"]) <= 160
            or type(reward["type"]) is not str or type(reward["count"]) is not int or reward["count"] != 1):
        raise DomainError("CRISIS_V2_CLAIM_INCOMPATIBLE", "任务奖励定义无效", 503)
    if reward["type"] not in SUPPORTED_TYPES:
        raise DomainError("CRISIS_V2_CLAIM_UNSUPPORTED", "此奖励类型尚未完成本地适配", 501)
    try:
        item_type = data.item(reward["id"])["itemType"]
    except (KeyError, DomainError) as exc:
        raise DomainError("CRISIS_V2_CLAIM_INCOMPATIBLE", "奖励物品不在匹配的数据版本", 503) from exc
    if item_type != reward["type"]:
        raise DomainError("CRISIS_V2_CLAIM_INCOMPATIBLE", "奖励类型与物品定义不一致", 503)
    return _material_pack(data, reward["id"]) if item_type == "ITEM_PACK" else [dict(reward)]


def claim(ctx, season_id: str, map_id: str, slot_id: str) -> dict:
    if not crisis_v2.available(ctx.data):
        raise DomainError("CRISIS_V2_NOT_CONFIGURED", "尚未导入匹配的危机合约信息源", 503)
    account = crisis_v2._account(ctx)
    if account.current_season != season_id:
        raise DomainError("CRISIS_V2_CLAIM_CLOSED", "本地领奖仅支持当前赛季", 409)
    progress = ctx.session.get(CrisisV2MapProgress, (ctx.account_id, season_id, map_id))
    saved = crisis_v2._map(ctx, progress) if progress is not None else None
    entries = resolve(ctx.data, season_id, map_id, slot_id, saved, ctx.now)
    granted = ctx.rewards(entries)
    progress.rewards = {**progress.rewards, slot_id: {"state": 2, "progress": saved.reward[slot_id].progress}}
    return {"seasonId": season_id, "mapId": map_id, "slotId": slot_id, "rewards": granted}
