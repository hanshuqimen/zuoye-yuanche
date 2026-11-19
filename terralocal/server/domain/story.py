"""Story completion, requirements and one-time rewards from frozen GameData."""

from terralocal.server.domain import battle
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.story_stages import POLICY, story_stage
from terralocal.server.persistence import models as m


def stage_condition(ctx, requirement) -> bool:
    stage_id = requirement["stageId"]
    row = ctx.session.get(m.StageProgress, (ctx.account_id, stage_id))
    stars, starts = (row.stars, row.start_count) if row else (0, 0)
    minimum, maximum = requirement["minState"], requirement["maxState"]
    if minimum == "UNLOCKED":
        allowed = battle.unlocked(ctx, stage_id)
    elif minimum == "PASS":
        allowed = stars > 0
    else:
        raise DomainError("STORY_CONDITION_UNSUPPORTED", "剧情前置关卡条件尚未支持", 501)
    if maximum == "UNLOCKED":
        return allowed and starts == 0
    if maximum == "PLAYED":
        return allowed and stars == 0
    if maximum == "PASS":
        return allowed and stars < 3
    if maximum == "COMPLETE":
        return allowed
    raise DomainError("STORY_CONDITION_UNSUPPORTED", "剧情前置关卡条件尚未支持", 501)


def finish(ctx, story_id: str) -> dict:
    definition = ctx.data.table("story_table").get(story_id)
    if definition is None:
        raise DomainError("UNKNOWN_STORY", "剧情不在当前数据版本中", 404)
    if definition["disabled"] or not definition["needCommit"]:
        raise DomainError("STORY_NOT_COMMITTABLE", "此剧情没有可提交的完成状态")
    stage = story_stage(ctx.data, definition)
    existing = ctx.session.get(m.StoryCompletion, (ctx.account_id, story_id))
    if existing or ctx.profile.flags.get("story", {}).get(story_id):
        if stage is not None:
            # Legacy story flags establish completion, not whether an old
            # external/GM save already received its OP. Repair progression
            # without retrospectively paying an unprovable award.
            complete_stage(ctx, stage, legacy=True)
        return {"items": []}
    if stage is not None and not battle.unlocked(ctx, stage["stageId"]):
        raise DomainError("STORY_LOCKED", "尚未满足剧情关的解锁条件")
    flags = {**ctx.profile.flags.get("story", {}), **{r.story_id: 1 for r in ctx.rows(m.StoryCompletion)}}
    progress = ctx.profile.flags.get("progress", 0)
    condition = definition.get("condition") or {}
    minimum, maximum = condition.get("minProgress", -1), condition.get("maxProgress", -1)
    valid = ((minimum < 0 or progress >= minimum) and (maximum < 0 or progress <= maximum)
             and ctx.profile.level >= condition.get("minPlayerLevel", 1)
             and all(flags.get(key) for key in condition.get("requiredFlags", []))
             and not any(flags.get(key) for key in condition.get("excludedFlags", []))
             and all(stage_condition(ctx, requirement) for requirement in condition.get("requiredStages", [])))
    if not valid:
        raise DomainError("STORY_LOCKED", "尚未满足剧情的进度或关卡条件")
    rewards = list(definition.get("completedRewards") or [])
    if stage is not None:
        rewards += complete_stage(ctx, stage, legacy=False)
    ctx.rewards(rewards)
    ctx.session.add(m.StoryCompletion(account_id=ctx.account_id, story_id=story_id, completed_at=ctx.now))
    extra_flags = {key: 1 for key in definition.get("setFlags") or []}
    ctx.profile.flags = {**ctx.profile.flags, "progress": max(progress, definition["setProgress"]),
                         "story": {**ctx.profile.flags.get("story", {}), **extra_flags}}
    ctx.emit("StoryFinished", story_id=story_id)
    return {"items": rewards}


def complete_stage(ctx, definition, *, legacy):
    stage_id = definition["stageId"]
    row = ctx.session.get(m.StageProgress, (ctx.account_id, stage_id))
    if (row is not None and row.stars == 3 and row.first_clear_claimed
            and row.unlocked and row.clear_count >= 1):
        return []
    if row is None:
        row = m.StageProgress(account_id=ctx.account_id, stage_id=stage_id, unlocked=True,
                              stars=0, clear_count=0, start_count=0, first_clear_claimed=False)
        ctx.session.add(row)
    rewards = []
    if not legacy and not row.first_clear_claimed and definition.get("diamondOnceDrop", 0):
        rewards = [{"id": "4002", "type": "DIAMOND", "count": definition["diamondOnceDrop"]}]
    row.stars, row.unlocked, row.first_clear_claimed = 3, True, True
    row.clear_count = max(1, row.clear_count)
    ctx.emit("StoryStageFinished", stage_id=stage_id, policy=POLICY,
             legacy_progress_only=legacy, gamedata_hash=ctx.data.manifest["hash"])
    ctx.session.flush()
    return rewards


def reconcile_stages(ctx) -> bool:
    """Repair old read flags before sync: first-read clients won't recommit.

    Completion flags prove the story was read, but do not establish historical
    reward payments. This local recovery repairs progress without paying OP.
    """
    if "story_table" not in ctx.data.manifest["tables"]:
        return False
    completed = {r.story_id for r in ctx.rows(m.StoryCompletion)}
    completed.update(k for k, value in ctx.profile.flags.get("story", {}).items() if value)
    changed = False
    for story_id in sorted(completed):
        definition = ctx.data.table("story_table").get(story_id)
        if definition is None or definition.get("disabled") or not definition.get("needCommit"):
            continue
        try:
            stage = story_stage(ctx.data, definition)
        except DomainError as exc:
            if exc.code == "STORY_STAGE_UNSUPPORTED":
                continue
            raise
        if stage is None:
            continue
        row = ctx.session.get(m.StageProgress, (ctx.account_id, stage["stageId"]))
        if (row is None or row.stars < 3 or not row.first_clear_claimed
                or not row.unlocked or row.clear_count < 1):
            complete_stage(ctx, stage, legacy=True)
            changed = True
    return changed
