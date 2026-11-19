"""Exact story-trigger bindings for ordinary mainline story-only stages."""

from terralocal.server.domain.errors import DomainError

POLICY = "mainline-story-stage-v1"


def story_stage(data, story: dict) -> dict | None:
    trigger = story.get("trigger") or {}
    stage = data.stages.get(trigger.get("key"))
    if (trigger.get("type") != "BEFORE_BATTLE" or trigger.get("useRegex") is not False
            or stage is None or stage.get("stageType") != "MAIN" or not stage.get("isStoryOnly")):
        return None
    if (stage.get("difficulty") != "NORMAL" or stage.get("diffGroup") not in {"NONE", "ALL"}
            or stage.get("isPredefined") or stage.get("isHardPredefined") or stage.get("isStagePatch")
            or stage.get("levelId") is not None
            or any(stage.get(key, 0) != 0 for key in (
                "apCost", "apFailReturn", "apProtectTimes", "goldGain", "expGain", "passFavor", "completeFavor"))):
        raise DomainError("STORY_STAGE_UNSUPPORTED", "此剧情关的环境或结算规则尚未完成适配", 501)
    if stage.get("diffGroup") == "ALL":
        groups = data.table("stage_table").get("storyStageShowGroup", {}).get(stage["stageId"])
        if not isinstance(groups, dict) or not groups or any(
                key not in {"EASY", "NORMAL", "TOUGH"} or not isinstance(value, dict)
                or value.get("stageId") != stage["stageId"]
                or value.get("diffGroup") != key
                or value.get("accordingStageId") is not None and value["accordingStageId"] not in data.stages
                for key, value in groups.items()):
            raise DomainError("GAMEDATA_INVALID", "共享剧情关的环境引用无效", 503)
    drop = stage.get("stageDropInfo") or {}
    if any(drop.get(key) for key in (
            "firstPassRewards", "firstCompleteRewards", "passRewards", "completeRewards")):
        raise DomainError("STORY_STAGE_UNSUPPORTED", "此剧情关包含额外奖励规则", 501)
    for reward in drop.get("displayDetailRewards") or []:
        if (reward.get("id") != "4002" or reward.get("type") != "DIAMOND"
                or reward.get("dropType") != "COMPLETE" or reward.get("occPercent") != "ALWAYS"):
            raise DomainError("STORY_STAGE_UNSUPPORTED", "此剧情关包含额外掉落规则", 501)
    diamonds = stage.get("diamondOnceDrop", 0)
    if type(diamonds) is not int or not 0 <= diamonds <= 100_000:
        raise DomainError("GAMEDATA_INVALID", "剧情关首次源石数量无效", 503)
    if diamonds and (data.item("4002")["itemType"] != "DIAMOND"
                     or any(r.get("id") == "4002" for r in story.get("completedRewards") or [])):
        raise DomainError("GAMEDATA_INVALID", "剧情关首次源石定义冲突", 503)
    return stage
