"""Deterministic, zero-cost predefined training stages from matching GameData."""

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint


def training_rule(data, stage_id: str) -> dict:
    stage = data.stage(stage_id)
    if (stage.get("stageType") != "MAIN" or stage.get("appearanceStyle") != "TRAINING"
            or not stage.get("isPredefined") or stage.get("difficulty") != "NORMAL"
            or stage.get("diffGroup") != "NONE" or stage.get("isHardPredefined")
            or stage.get("isStagePatch") or stage.get("isSkillSelectablePredefined")
            or stage.get("isStoryOnly") or stage.get("canPractice")
            or stage.get("canBattleReplay") or stage.get("canMultipleBattle")
            or any(stage.get(key, 0) != 0 for key in (
                "apCost", "apFailReturn", "apProtectTimes", "expGain", "goldGain", "passFavor", "completeFavor"))
            or not isinstance(stage.get("levelId"), str) or not stage["levelId"]):
        raise DomainError("NATIVE_STAGE_UNSUPPORTED", "此固定阵容关卡尚未完成游戏端适配", 501)
    info = stage.get("stageDropInfo") or {}
    if any(info.get(key) for key in ("passRewards", "completeRewards", "firstCompleteRewards")):
        raise DomainError("TRAINING_REWARD_UNSUPPORTED", "训练关包含尚未验证的额外结算规则", 501)
    declared = info.get("firstPassRewards")
    first = []
    if declared:
        for reward in declared:
            if (type(reward.get("count")) is not int or not 1 <= reward["count"] <= 100_000
                    or data.item(reward["id"])["itemType"] != reward["type"]):
                raise DomainError("GAMEDATA_INVALID", "训练关首次奖励定义无效", 503)
            first.append(dict(reward))
    else:
        # The frozen stage table provides ONCE contract IDs but no quantity.
        # A single contract is the explicit local fallback, recorded in the
        # rule hash and implementation notes; never infer random drop counts.
        for reward in info.get("displayDetailRewards") or []:
            if reward["dropType"] == "COMPLETE" and reward["id"] == "4002":
                continue  # diamondOnceDrop is granted by the settlement once.
            if (reward["dropType"] != "ONCE" or reward.get("occPercent") != "ALWAYS"
                    or reward["type"] != "CHAR"
                    or data.item(reward["id"])["itemType"] != "CHAR"):
                raise DomainError("TRAINING_REWARD_UNSUPPORTED", "训练关奖励缺少确定的数量依据", 501)
            first.append({"id": reward["id"], "type": "CHAR", "count": 1})
    return {"kind": "predefined-training-v1", "gamedata_hash": data.manifest["hash"],
            "stage_hash": fingerprint(stage), "level_id": stage["levelId"],
            "first_pass_basis": "explicit-firstPassRewards-or-single-ONCE-contract",
            "rewards": [], "first_pass_rewards": first, "first_complete_rewards": []}
