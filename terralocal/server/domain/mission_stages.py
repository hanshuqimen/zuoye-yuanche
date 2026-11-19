"""CompleteAnyStage progress derives from saved clears, including story stages."""

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.mission_rules import any_stage_rule
from terralocal.server.persistence import models as m


def eligible(ctx, table, definition, group, progress):
    from terralocal.server.domain.missions import _prerequisites

    _prerequisites(ctx, table, definition, group)
    if definition["type"] != "RETRO":
        return True
    # Permanent chapter missions are not timed activity missions. Derive the
    # chapter from every member's actual candidate stages, never a name prefix.
    if group.get("rewards"):
        raise DomainError("MISSION_GROUP_UNSUPPORTED", "此回顾任务组含独立奖励", 501)
    zone_ids = set()
    for key in group["missionIds"]:
        member = table["missions"].get(key)
        if not member or member.get("template") != "CompleteAnyStage":
            raise DomainError("MISSION_GROUP_UNSUPPORTED", "此回顾任务组包含其他任务规则", 501)
        for stage_id in any_stage_rule(member, ctx.data)["stages"]:
            stage = ctx.data.stage(stage_id)
            if stage.get("stageType") != "MAIN":
                raise DomainError("MISSION_GROUP_UNSUPPORTED", "此回顾任务组不属于永久主线章节", 501)
            zone_ids.add(stage.get("zoneId"))
    if len(zone_ids) != 1 or "zone_table" not in ctx.data.manifest["tables"]:
        raise DomainError("MISSION_GROUP_UNSUPPORTED", "此回顾任务组的章节开放规则尚未完成适配", 501)
    zone_id = next(iter(zone_ids))
    chapters = ctx.data.table("zone_table").get("mainlineAdditionInfo", {})
    chapter = chapters.get(zone_id)
    if chapter is None:
        raise DomainError("MISSION_GROUP_UNSUPPORTED", "此回顾任务组缺少主线章节定义", 501)
    if chapter.get("zoneOpenTime", -1) > ctx.now:
        return False
    previous = chapter.get("preposedZoneId")
    if not previous:
        return True
    if previous not in chapters or chapters[previous].get("endStageId") not in ctx.data.stages:
        raise DomainError("GAMEDATA_INVALID", "回顾任务前置章节定义无效", 503)
    row = progress.get(chapters[previous]["endStageId"])
    return row is not None and row.stars > 0


def reconcile(ctx) -> bool:
    from terralocal.server.domain.missions import _definition, _group

    if "mission_table" not in ctx.data.manifest["tables"]:
        return False
    table = ctx.data.table("mission_table")
    candidates = {key: value for key, value in table["missions"].items()
                  if value.get("template") == "CompleteAnyStage"}
    if not candidates:
        return False
    stages = {row.stage_id: row for row in ctx.rows(m.StageProgress)}
    saved = {row.mission_id: row for row in ctx.rows(m.MissionProgress) if row.period == "permanent"}
    changed = False
    for key, definition in candidates.items():
        try:
            checked = _definition(table, key)
            group = _group(table, checked)
            if not eligible(ctx, table, checked, group, stages):
                continue
        except DomainError as error:
            if error.code in {"MISSION_LOCKED", "MISSION_CONFIRM_UNSUPPORTED", "MISSION_GROUP_UNSUPPORTED"}:
                continue
            raise
        rule = any_stage_rule(definition, ctx.data)
        value = int(any(stage_id in stages and stages[stage_id].stars >= rule["minimum_stars"]
                        for stage_id in rule["stages"]))
        row = saved.get(key)
        if row is None:
            row = m.MissionProgress(account_id=ctx.account_id, mission_id=key,
                                    period="permanent", progress=value, claimed=False)
            ctx.session.add(row)
            changed = True
        elif not row.claimed and row.progress != value:
            row.progress = value
            changed = True
    ctx.session.flush()
    return changed


def validate_claim(ctx, table, definition, group):
    stages = {row.stage_id: row for row in ctx.rows(m.StageProgress)}
    if not eligible(ctx, table, definition, group, stages):
        raise DomainError("MISSION_LOCKED", "任务所属主线章节尚未开放", 409)
    rule = any_stage_rule(definition, ctx.data)
    if not any(stage_id in stages and stages[stage_id].stars >= rule["minimum_stars"]
               for stage_id in rule["stages"]):
        raise DomainError("MISSION_NOT_COMPLETE", "尚未按要求完成候选关卡", 409)
