"""Durable campaign sessions and explicit resource-tier settlement.

Training tiers without independent drops use their explicit resource gains.
Shard payouts and other unverified branches never receive an empty success.
"""

import re
import secrets
import uuid

from terralocal.server.domain import battle, campaign
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.operator_limits import maximum_trust
from terralocal.server.domain.sessions import battle_binding
from terralocal.server.gamedata.campaigns import MODES
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.protocol.battle_codec import DecodedCampaignFinish

CODEC_VERSION = "cn-android-2.7.71-campaign-battle-v1"
RECOVERY_POLICY = "campaign-new-session-zero-kill-abandon-v1"


def _rule(ctx, stage_id, mode):
    definition = ctx.data.campaigns.stage(stage_id)
    ladders = definition.gain_ladders[mode]
    if not ladders or ladders[0].kills != 0:
        raise DomainError("CAMPAIGN_ABORT_RULE_MISSING", "剿灭缺少明确的零击杀档位，尚未扣除理智", 503)
    gain = ladders[0]
    if gain.player_exp or gain.gold or gain.favor or gain.displayed_shards:
        raise DomainError("CAMPAIGN_ABORT_RULE_UNSUPPORTED", "此零击杀奖励规则尚未验证", 503)
    stage = ctx.data.stage(stage_id)
    campaign_definition = ctx.data.table("campaign_table")["campaigns"][stage_id]
    drops = campaign_definition["dropGains"][mode]["dropLadders"]
    if not drops or drops[0]["killCnt"] != 0 or any(
            drops[0]["dropInfo"][key] for key in ("firstPassRewards", "passRewards")):
        raise DomainError("CAMPAIGN_ABORT_RULE_UNSUPPORTED", "此零击杀物资规则尚未验证", 503)
    digest = fingerprint({"stage": campaign_definition,
                          "apCost": stage["apCost"], "mode": mode})
    return digest, gain.sanity_return


def _mode(ctx, stage_id):
    table = ctx.data.table("campaign_table")
    required = table["campaignConstTable"]["systemPreposedStage"]
    progress = ctx.session.get(m.StageProgress, (ctx.account_id, required))
    if progress is None or progress.stars < 1 or not battle.unlocked(ctx, stage_id):
        raise DomainError("STAGE_LOCKED", "尚未满足剿灭解锁条件")
    opening = ctx.data.campaigns.opening(ctx.now)
    # Frozen M32976 checks these lists in order, even if they overlap.
    if stage_id in opening.permanent:
        return "PERMANENT"
    if stage_id == opening.rotate:
        required = table["campaignConstTable"]["rotatePreposedStage"]
        progress = ctx.session.get(m.StageProgress, (ctx.account_id, required))
        if progress is None or progress.stars < 1:
            raise DomainError("STAGE_LOCKED", "尚未满足轮换剿灭解锁条件")
        return "ROTATE"
    if stage_id in opening.training or opening.training_all_group:
        return "TRAINING"
    raise DomainError("CAMPAIGN_CLOSED", "此剿灭关卡当前未开放")


def start(ctx, stage_id, squad_id, slots, *, drop_rules):
    from terralocal.server.domain.rogue_battle import ensure_no_active

    ensure_no_active(ctx)
    if not campaign.available(ctx.data):
        raise DomainError("CAMPAIGN_DATA_UNAVAILABLE", "当前配置没有剿灭数据", 503)
    campaign_definition = ctx.data.campaigns.stage(stage_id)
    if campaign_definition.customized or campaign_definition.small_scale:
        raise DomainError("CAMPAIGN_STAGE_UNSUPPORTED", "此特殊剿灭分支尚未实现", 501)
    campaign.snapshot(ctx)  # Validate the account's data/policy binding.
    if ctx.session.get(m.CampaignStageProgress, (ctx.account_id, stage_id)) is None:
        raise DomainError("CAMPAIGN_UNDISCOVERED", "此账号尚未开放该剿灭实例")
    mode = _mode(ctx, stage_id)
    definition = ctx.data.stage(stage_id)
    if (definition.get("isPredefined") or definition.get("isHardPredefined")
            or definition.get("isStoryOnly") or definition.get("isStagePatch") or definition.get("apProtectTimes", 0)
            or definition.get("zoneId") in ctx.data.table("stage_table").get("apProtectZoneInfo", {})):
        raise DomainError("CAMPAIGN_STAGE_UNSUPPORTED", "此剿灭战斗分支尚未实现", 501)
    rule_hash, returned = _rule(ctx, stage_id, mode)
    formation = battle.saved_squad(ctx, squad_id, slots)
    if not formation:
        raise DomainError("EMPTY_SQUAD", "请选择有干员的编队")
    login_time = ctx.profile.flags.get("loginTime", ctx.profile.last_online_at)
    if type(login_time) is not int or not 0 <= login_time <= 253_402_271_999:
        raise DomainError("INVALID_LOGIN_TIME", "存档中的登录时间无效", 503)
    battle._recover_previous_session(ctx, drop_rules)
    sanity = ctx.sanity()
    cost = definition["apCost"]
    if sanity.current < cost:
        raise DomainError("INSUFFICIENT_SANITY", "理智不足")
    if sanity.current >= sanity.maximum:
        sanity.last_recovery_at = ctx.now
    sanity.current -= cost
    snapshot = []
    for slot in formation:
        operator = ctx.operator(slot.operator_id)
        snapshot.append({"charInstId": operator.id, "skillIndex": slot.skill_index,
                         "charId": operator.char_id, "level": operator.level, "evolvePhase": operator.evolve_phase})
    row = m.BattleSession(id=str(uuid.uuid4()), account_id=ctx.account_id, stage_id=stage_id,
        state="STARTED", sanity_cost=cost, practice=False, started_at=ctx.now,
        seed=secrets.randbelow(2**31), squad_snapshot=snapshot, native_context={
            "codec_version": CODEC_VERSION, "gamedata_hash": ctx.data.manifest["hash"],
            "login_time": login_time, "session_binding": battle_binding(ctx.local_session),
            "mode": mode, "rule_hash": rule_hash, "zero_kill_return": returned})
    ctx.session.add(row)
    ctx.session.flush()
    return {"battleId": row.id}


def context(ctx, battle_id):
    row = battle.get_session(ctx, battle_id)
    saved = row.native_context
    if (not isinstance(saved, dict) or saved.get("codec_version") != CODEC_VERSION
            or type(row.sanity_cost) is not int or row.sanity_cost < 0
            or not isinstance(saved.get("mode"), str) or saved["mode"] not in MODES
            or type(saved.get("login_time")) is not int or not 0 <= saved["login_time"] <= 253_402_271_999
            or type(saved.get("zero_kill_return")) is not int
            or not 0 <= saved["zero_kill_return"] <= row.sanity_cost
            or ctx.data.stage(row.stage_id).get("stageType") != "CAMPAIGN"
            or row.practice
            or any(not isinstance(saved.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", saved[key])
                   for key in ("gamedata_hash", "rule_hash", "session_binding"))):
        raise DomainError("CAMPAIGN_CONTEXT_UNAVAILABLE", "剿灭战斗缺少有效的版本或规则记录", 503)
    return saved


def _resource_gain(ctx, row, saved, kills):
    # The native pause menu selects by validKilledEnemiesCnt, independently
    # of raw kills, processed enemies and the rounded progress percentage.
    gain = ctx.data.campaigns.gain(row.stage_id, saved["mode"], kills)
    drops = ctx.data.table("campaign_table")["campaigns"][row.stage_id]["dropGains"][saved["mode"]]["dropLadders"]
    drop = next((entry for entry in reversed(drops) if entry["killCnt"] <= kills), None)
    if (gain.displayed_shards or drop is None
            or any(drop["dropInfo"][key] for key in ("firstPassRewards", "passRewards"))
            or saved["mode"] != "TRAINING" and (
                gain.kills != 0 or gain.player_exp or gain.gold or gain.favor
                or any(kills >= ladder.kills for ladder in ctx.data.campaigns.stage(row.stage_id).break_ladders))):
        raise DomainError("CAMPAIGN_SETTLEMENT_UNIMPLEMENTED", "此剿灭结果的奖励结算尚未实现，战斗记录已保留", 501)
    return gain


def _partial_outcome(saved, outcome):
    # Frozen TRAINING natural defeat is rank2 with interrupt=false, just as
    # voluntary retirement is rank2 with interrupt=true. Other modes still
    # require their own observed natural-outcome contract.
    return (outcome.get("completeState") == 2 and outcome.get("giveUp") is False
            and (outcome.get("interrupt") is True
                 or saved["mode"] == "TRAINING" and outcome.get("interrupt") is False))


def _full_training_outcome(saved, outcome):
    # The shared campaign request uses PlayerBattleRank.COMPLETE (3).
    # Frozen DefaultGameMode's non-hotfix path keeps that completion rank;
    # its Campaign exception promotes failure to PASS, not COMPLETE.
    return (saved["mode"] == "TRAINING" and outcome.get("completeState") == 3
            and outcome.get("interrupt") is False and outcome.get("giveUp") is False)


def _supported_outcome(saved, outcome):
    return _partial_outcome(saved, outcome) or _full_training_outcome(saved, outcome)


def _settle(ctx, row, saved, outcome, *, recovery=False):
    digest = fingerprint(outcome)
    state_after = "FINISHED" if not recovery and _full_training_outcome(saved, outcome) else "ABORTED"
    if row.state in {"ABORTED", "FINISHED"}:
        if row.state != state_after or row.request_hash != digest:
            raise DomainError("SETTLEMENT_CONFLICT", "重复剿灭结算的结果不一致", 409)
        if not isinstance(row.settlement, dict):
            raise DomainError("INVALID_BATTLE_SETTLEMENT", "剿灭结算存档无效", 503)
        return row.settlement
    if row.state != "STARTED":
        raise DomainError("SETTLEMENT_CONFLICT", "此剿灭战斗已结束", 409)
    if saved["gamedata_hash"] != ctx.data.manifest["hash"]:
        raise DomainError("BATTLE_DATA_CHANGED", "剿灭战斗期间数据版本发生变化", 503)
    rule_hash, returned = _rule(ctx, row.stage_id, saved["mode"])
    if (rule_hash != saved["rule_hash"] or returned != saved["zero_kill_return"]
            or row.sanity_cost != ctx.data.stage(row.stage_id)["apCost"]):
        raise DomainError("CAMPAIGN_RULE_CHANGED", "剿灭战斗期间规则发生变化", 503)
    kills = 0 if recovery else outcome["validKillCnt"]
    gain = _resource_gain(ctx, row, saved, kills)
    returned = gain.sanity_return
    state = campaign.snapshot(ctx)
    sanity = ctx.sanity()
    if sanity.current + returned > 2_000_000_000:
        raise DomainError("SANITY_LIMIT", "返还理智超出存档范围")
    sanity.current += returned
    rewards = ctx.rewards([{"id": item, "count": count} for item, count in (
        ("4001", gain.gold), ("5001", gain.player_exp)) if count])
    if gain.favor:
        limit = maximum_trust(ctx.data)
        for member in row.squad_snapshot:
            operator = ctx.operator(member["charInstId"])
            operator.trust = min(limit, operator.trust + gain.favor)
    result = {"apFailReturn": returned, "currentFeeBefore": state["campaignCurrentFee"],
              "currentFeeAfter": state["campaignCurrentFee"], "unlockStages": [], "alert": []}
    for name in ("itemReturn", "rewards", "unusualRewards", "overrideRewards", "additionalRewards",
                 "diamondMaterialRewards", "furnitureRewards"):
        result[name] = []
    result["rewards"] = rewards
    row.state, row.finished_at = state_after, ctx.now
    row.request_hash, row.settlement = digest, result
    row.native_context = {**saved, "outcome": outcome, **({"recovery": {
        "policy": RECOVERY_POLICY, "at": ctx.now}} if recovery else {})}
    if not recovery:
        progress = ctx.session.get(m.CampaignStageProgress, (ctx.account_id, row.stage_id))
        if progress is None:
            raise DomainError("CAMPAIGN_UNDISCOVERED", "此账号尚未开放该剿灭实例")
        progress.max_kills = max(progress.max_kills, kills)
    return result


def finish(ctx, data: DecodedCampaignFinish):
    row = battle.get_session(ctx, data.battleId)
    saved = context(ctx, row.id)
    if data.stageId != row.stage_id:
        raise DomainError("BATTLE_STAGE_CONFLICT", "剿灭结算关卡不匹配", 409)
    outcome = {name: getattr(data, name) for name in (
        "completeState", "interrupt", "giveUp", "percent", "killCnt", "validKillCnt", "platform")}
    outcome["duration"] = data.battleData.completeTime
    if not _supported_outcome(saved, outcome):
        raise DomainError("CAMPAIGN_SETTLEMENT_UNIMPLEMENTED", "此剿灭结果的奖励结算尚未实现，战斗记录已保留", 501)
    result = _settle(ctx, row, saved, outcome)
    # The shared finish coroutine inserts EXP from the actual status delta.
    # Keep the award in the durable settlement but avoid a second native icon.
    return {**result, "rewards": [{**reward, "charGet": reward.get("charGet")}
            for reward in result["rewards"] if reward["type"] != "EXP_PLAYER"]}


def recover(ctx, row):
    saved = context(ctx, row.id)
    if saved["session_binding"] == battle_binding(ctx.local_session):
        raise DomainError("ACTIVE_BATTLE", "已有未结算剿灭战斗", 409)
    _settle(ctx, row, saved, {"reason": "new-game-session-start", "kills_assumed": 0}, recovery=True)
    ctx.session.flush()


def save_journal(ctx, battle_id, record):
    """Keep the supported campaign's real journal without advertising a proxy.

    The native result screen uses quest/saveBattleReplay for rank2 aborts.
    Keep a COMPLETE training journal distinct from those aborts, without
    inventing a StageReplay or unverified proxy eligibility.
    """
    from terralocal.server.domain import replays

    row = battle.get_session(ctx, battle_id)
    saved = context(ctx, battle_id)
    facts = saved.get("outcome")
    if (not isinstance(facts, dict) or not _supported_outcome(saved, facts)
            or row.state != ("FINISHED" if _full_training_outcome(saved, facts) else "ABORTED")
            or type(facts.get("killCnt")) is not int or not 0 <= facts["killCnt"] <= 100_000
            or type(facts.get("validKillCnt")) is not int or not 0 <= facts["validKillCnt"] <= 100_000
            or not isinstance(row.settlement, dict)):
        raise DomainError("REPLAY_UNAVAILABLE", "此剿灭战斗尚无可保存的实际结束记录", 409)
    if saved["gamedata_hash"] != ctx.data.manifest["hash"]:
        raise DomainError("BATTLE_DATA_CHANGED", "剿灭战斗记录的数据版本不匹配", 503)
    _resource_gain(ctx, row, saved, facts["validKillCnt"])
    if record.stage_id != row.stage_id:
        raise DomainError("REPLAY_STAGE_CONFLICT", "剿灭战斗记录的关卡不匹配", 409)
    replays._members(ctx, record, row)
    kind = "campaign-finish-journal-v1" if _full_training_outcome(saved, facts) else "campaign-abort-journal-v1"
    old = saved.get("campaign_journal")
    if old is not None:
        if (not isinstance(old, dict) or old.get("kind") != kind
                or old.get("codec_version") != replays.NATIVE_REPLAY_VERSION
                or old.get("gamedata_hash") != saved["gamedata_hash"]
                or old.get("sha256") != record.sha256 or old.get("battleReplay") != record.encoded):
            raise DomainError("REPLAY_CONFLICT", "同一剿灭战斗不能覆盖不同战斗记录", 409)
        return {}
    row.native_context = {**saved, "campaign_journal": {
        "kind": kind, "codec_version": replays.NATIVE_REPLAY_VERSION,
        "gamedata_hash": saved["gamedata_hash"], "battleReplay": record.encoded,
        "sha256": record.sha256, "stored_at": ctx.now}}
    return {}
