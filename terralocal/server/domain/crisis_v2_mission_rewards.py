"""Resolve rune-pack/challenge rewards from the bound map, without writes.

Native M163914 hides timed items when rewardEndTime - now <= 0. Applying
that visibility cutoff to grants is an explicit local backend policy; the
original backend algorithm is not present in the client. Permanent treasures
keep their previously verified adapter and receipt policy.
"""

from terralocal.server.domain import crisis_v2
from terralocal.server.domain.errors import DomainError
from terralocal.server.protocol.crisis_v2_state import PermanentMapInfo

COIN = "CRS_SHOP_COIN_V2"
TYPES = frozenset({COIN, "GOLD", "CARD_EXP", "MATERIAL"})


def _incompatible():
    return DomainError("CRISIS_V2_MISSIONS_INCOMPATIBLE", "任务奖励或资格与匹配地图不一致", 503)


def _reward(data, value):
    if (
        type(value) is not dict
        or set(value) != {"id", "type", "count"}
        or type(value["id"]) is not str
        or not 1 <= len(value["id"]) <= 160
        or type(value["type"]) is not str
        or type(value["count"]) is not int
        or not 1 <= value["count"] <= 2_000_000_000
    ):
        raise _incompatible()
    if value["type"] not in TYPES:
        raise DomainError("CRISIS_V2_MISSION_REWARD_UNSUPPORTED", "此任务奖励类型尚未适配", 501)
    try:
        item = data.item(value["id"])
    except (KeyError, DomainError) as exc:
        raise _incompatible() from exc
    if (
        item["itemType"] != value["type"]
        or value["type"] == COIN
        and value["id"] != data.crisis_v2.shop_coin_id
    ):
        raise _incompatible()
    return dict(value)


def resolve(data, season_id, map_id, mission, saved, now):
    if not crisis_v2.available(data):
        raise DomainError("CRISIS_V2_NOT_CONFIGURED", "尚未导入匹配的危机合约信息源", 503)
    catalog = data.crisis_v2
    if not season_id or catalog.current(now) != season_id:
        raise DomainError("CRISIS_V2_CLAIM_CLOSED", "领奖仅支持当前赛季", 409)
    if (season_id, map_id) not in catalog.rules:
        raise DomainError("CRISIS_V2_CLAIM_MAP", "当前赛季没有此地图", 404)
    info = catalog.info(season_id)
    stage, detail = info["mapStageDataMap"][map_id], info["mapDetailDataMap"][map_id]
    if stage["startTime"] != -1 and now < stage["startTime"]:
        raise DomainError("CRISIS_V2_CLAIM_CLOSED", "地图尚未开放", 409)
    if mission.type == 0:
        if not isinstance(saved, PermanentMapInfo):
            raise DomainError("CRISIS_V2_CLAIM_UNKNOWN", "该地图没有永久指标集任务", 404)
        bag = catalog.rules[(season_id, map_id)].bags.get(mission.id)
        if bag is None:
            raise DomainError("CRISIS_V2_CLAIM_UNKNOWN", "地图没有此指标集任务", 404)
        state = saved.runePack.get(mission.id, 0)
        # A displayed empty 0/0 group is not an earned objective.
        if not bag.members:
            raise DomainError("CRISIS_V2_CLAIM_NOT_READY", "空指标集不是已完成的任务", 409)
        entries = detail["bagDataMap"][mission.id].get("slotPackRewards")
        timed = False
    elif mission.type == 1:
        if mission.id not in catalog.challenges(season_id, map_id).conditions:
            raise DomainError("CRISIS_V2_CLAIM_UNKNOWN", "地图没有此挑战任务", 404)
        state = saved.challenge.get(mission.id, 0) if saved is not None else 0
        entries = detail["challengeNodeDataMap"][mission.id].get("rewardList")
        timed = True
    else:
        raise ValueError("This resolver accepts rune packs and challenges only")
    if saved is None or not saved.state or state == 0:
        raise DomainError("CRISIS_V2_CLAIM_NOT_READY", "尚未达到任务领奖条件", 409)
    if state == 2:
        raise DomainError("CRISIS_V2_CLAIM_ALREADY_TAKEN", "任务奖励已领取", 409)
    if type(entries) is not list or not 1 <= len(entries) <= 128:
        raise _incompatible()
    result = []
    for entry in entries:
        if timed:
            if (
                type(entry) is not dict
                or set(entry) != {"isTimeLimit", "reward"}
                or type(entry["isTimeLimit"]) is not bool
            ):
                raise _incompatible()
            reward = _reward(data, entry["reward"])
            if entry["isTimeLimit"]:
                if stage["rewardEndTime"] == -1:
                    raise _incompatible()
                if now >= stage["rewardEndTime"]:
                    continue
        else:
            reward = _reward(data, entry)
        result.append(reward)
    if not result:
        raise DomainError("CRISIS_V2_CLAIM_CLOSED", "此任务的限时奖励已到期", 409)
    return result
