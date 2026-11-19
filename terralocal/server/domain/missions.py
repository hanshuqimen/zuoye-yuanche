"""Single permanent countable missions from the frozen CN GameData.

Periodic points, timed missions and separate group rewards need their own
state machines. They are rejected here instead of silently granting a partial
reward or marking an unsupported group complete.
"""

from terralocal.server.domain.context import CURRENCY_TYPES, Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.mission_rules import PERMANENT_TEMPLATES, any_stage_rule, target
from terralocal.server.persistence import models as m

REWARD_TYPES = CURRENCY_TYPES | {
    "MATERIAL", "CARD_EXP", "EXP_PLAYER", "TKT_RECRUIT", "TKT_INST_FIN", "TKT_GACHA", "TKT_GACHA_10", "PLOT_ITEM",
}
CANDIDATE_REWARD_TYPES = REWARD_TYPES | {"CHAR", "CHAR_SKIN", "FURN"}


def _definition(table: dict, mission_id: str) -> dict:
    definition = table["missions"].get(mission_id)
    if definition is None:
        raise DomainError("UNKNOWN_MISSION", "当前游戏数据中没有此任务", 404)
    if not isinstance(definition, dict) or definition.get("id") != mission_id:
        raise DomainError("MISSION_DEFINITION_INVALID", "任务定义与任务编号不一致", 503)
    category = definition.get("type")
    supported_category = category in {"MAIN", "SUB", "GUIDE"} or (
        category == "RETRO" and definition.get("template") == "CompleteAnyStage")
    unlock = definition.get("unlockParam")
    stage_unlock = (definition.get("template") == "CompleteAnyStage"
                    and definition.get("unlockCondition") == "StageCondition"
                    and isinstance(unlock, list) and len(unlock) == 2
                    and unlock[0] in {"2", "3"} and isinstance(unlock[1], str))
    if (not supported_category
            or definition.get("template") not in PERMANENT_TEMPLATES
            or definition.get("periodicalPoint") != 0
            or definition.get("countEndTs") != -1
            or not stage_unlock and (definition.get("unlockCondition") is not None
                                      or definition.get("unlockParam") not in (None, []))):
        raise DomainError("MISSION_CONFIRM_UNSUPPORTED", "此任务的领取规则尚未完成适配", 501)
    target(definition)
    return definition


def _group(table: dict, definition: dict) -> dict:
    group = table.get("missionGroups", {}).get(definition.get("missionGroup"))
    if (not isinstance(group, dict) or group.get("id") != definition.get("missionGroup")
            or group.get("type") != definition["type"]
            or not isinstance(group.get("missionIds"), list)
            or not group["missionIds"] or any(not isinstance(ident, str) for ident in group["missionIds"])
            or len(set(group["missionIds"])) != len(group["missionIds"])
            or definition["id"] not in group["missionIds"]):
        raise DomainError("MISSION_DEFINITION_INVALID", "任务组定义缺失或不一致", 503)
    if group.get("period") is not None or group.get("startTs") != -1 or group.get("endTs") != -1:
        raise DomainError("MISSION_GROUP_UNSUPPORTED", "此任务组的时间规则尚未完成适配", 501)
    return group


def _claimed(ctx: Context, mission_ids: list[str]) -> bool:
    return bool(mission_ids) and all(
        (row := ctx.session.get(m.MissionProgress, (ctx.account_id, mission_id, "permanent"))) is not None
        and row.claimed for mission_id in mission_ids)


def _prerequisites(ctx: Context, table: dict, definition: dict, group: dict) -> None:
    if definition.get("unlockCondition") == "StageCondition":
        state, stage_id = definition["unlockParam"]
        if stage_id not in ctx.data.stages:
            raise DomainError("MISSION_DEFINITION_INVALID", "任务解锁关卡不在当前数据版本中", 503)
        row = ctx.session.get(m.StageProgress, (ctx.account_id, stage_id))
        if row is None or row.stars < (1 if state == "2" else 3):
            raise DomainError("MISSION_LOCKED", "尚未满足任务的关卡解锁条件", 409)
    required = definition.get("preMissionIds")
    if required is not None:
        if not isinstance(required, list) or any(ident not in table["missions"] for ident in required):
            raise DomainError("MISSION_DEFINITION_INVALID", "任务前置定义无效", 503)
        if required and not _claimed(ctx, required):
            raise DomainError("MISSION_LOCKED", "前置任务尚未领取", 409)
    predecessor = group.get("preMissionGroup")
    if predecessor is None:
        return
    previous = table.get("missionGroups", {}).get(predecessor)
    if not isinstance(previous, dict) or not isinstance(previous.get("missionIds"), list):
        raise DomainError("MISSION_DEFINITION_INVALID", "前置任务组定义无效", 503)
    if previous.get("rewards"):
        # Individual claims cannot prove that a distinct group reward was claimed.
        raise DomainError("MISSION_GROUP_UNSUPPORTED", "前置任务组奖励尚未完成适配", 501)
    if not _claimed(ctx, previous["missionIds"]):
        raise DomainError("MISSION_LOCKED", "前置任务组尚未完成领取", 409)


def _rewards(ctx: Context, definition: dict) -> list[dict]:
    entries = definition.get("rewards")
    if not isinstance(entries, list):
        raise DomainError("MISSION_DEFINITION_INVALID", "任务奖励定义缺失", 503)
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                or type(entry.get("count")) is not int or not 1 <= entry["count"] <= 2_000_000_000):
            raise DomainError("MISSION_DEFINITION_INVALID", "任务奖励定义无效", 503)
        item_type = ctx.data.item(entry["id"])["itemType"]
        if entry.get("type") != item_type:
            raise DomainError("MISSION_DEFINITION_INVALID", "任务奖励类型与物品定义不一致", 503)
        allowed = CANDIDATE_REWARD_TYPES if definition.get("template") == "CompleteAnyStage" else REWARD_TYPES
        if item_type not in allowed:
            raise DomainError("MISSION_REWARD_UNSUPPORTED", "此任务奖励类型尚未完成适配", 501)
        if item_type in {"CHAR", "CHAR_SKIN"} and entry["count"] != 1:
            raise DomainError("MISSION_REWARD_UNSUPPORTED", "此任务的干员或服装奖励数量尚未完成适配", 501)
    return entries


def _activate_main_successors(ctx: Context, table: dict, group: dict) -> None:
    if group["type"] != "MAIN" or not _claimed(ctx, group["missionIds"]):
        return
    if group.get("rewards"):
        raise DomainError("MISSION_GROUP_UNSUPPORTED", "主线任务组奖励尚未完成适配", 501)
    for candidate in table.get("missionGroups", {}).values():
        if candidate.get("type") != "MAIN" or candidate.get("preMissionGroup") != group["id"]:
            continue
        for mission_id in candidate["missionIds"]:
            definition = _definition(table, mission_id)
            next_group = _group(table, definition)
            _prerequisites(ctx, table, definition, next_group)
            row = ctx.session.get(m.MissionProgress, (ctx.account_id, mission_id, "permanent"))
            if row is not None:
                continue
            progress = 0
            if definition["template"] == "CompleteMainStage":
                stage = ctx.session.get(m.StageProgress, (ctx.account_id, definition["param"][1]))
                progress = int(stage is not None and stage.stars > 0)
            elif definition["template"] == "CompleteAnyStage":
                rule = any_stage_rule(definition, ctx.data)
                progress = int(any((stage := ctx.session.get(m.StageProgress, (ctx.account_id, key))) is not None
                                   and stage.stars >= rule["minimum_stars"] for key in rule["stages"]))
            ctx.session.add(m.MissionProgress(account_id=ctx.account_id, mission_id=mission_id,
                                             period="permanent", progress=progress, claimed=False))


def confirm(ctx: Context, mission_id: str) -> dict:
    table = ctx.data.table("mission_table")
    definition = _definition(table, mission_id)
    group = _group(table, definition)
    row = ctx.session.get(m.MissionProgress, (ctx.account_id, mission_id, "permanent"))
    if row is None:
        raise DomainError("MISSION_NOT_ASSIGNED", "此账号没有领取中的该任务", 404)
    if row.claimed:
        return {}  # Native response declares only PlayerDeltaResponse fields.
    _prerequisites(ctx, table, definition, group)
    if definition["template"] == "CompleteAnyStage":
        from terralocal.server.domain.mission_stages import validate_claim

        validate_claim(ctx, table, definition, group)
    if row.progress < 0:
        raise DomainError("INVALID_MISSION_PROGRESS", "存档中的任务进度无效", 503)
    if definition["template"] == "CompleteAnyStage":
        row.progress = 1  # validate_claim proved the saved stage condition above.
    if row.progress < target(definition):
        raise DomainError("MISSION_NOT_COMPLETE", "任务尚未完成", 409)
    entries = _rewards(ctx, definition)
    ctx.rewards(entries)
    row.claimed = True
    _activate_main_successors(ctx, table, group)
    ctx.emit("MissionClaimed", mission_id=mission_id, category=definition["type"])
    return {}
