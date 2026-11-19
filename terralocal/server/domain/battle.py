from __future__ import annotations

import math
import re
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.operator_limits import maximum_trust
from terralocal.server.domain.sessions import battle_binding
from terralocal.server.gamedata.conditions import required_stars
from terralocal.server.gamedata.drops import select_rewards
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.stage_start import requirements
from terralocal.server.gamedata.training import training_rule
from terralocal.server.persistence import models as m

NATIVE_CODEC_VERSION = "cn-android-2.7.71-battle-v1"
RECOVERY_POLICY = "native-battle-session-recovery-v1"


@dataclass(frozen=True)
class BattleMember:
    operator_id: int
    skill_index: int


def unlocked(ctx: Context, stage_id: str, *, progress: dict | None = None) -> bool:
    definition = ctx.data.stage(stage_id)

    def saved(key):
        return (ctx.session.get(m.StageProgress, (ctx.account_id, key))
                if progress is None else progress.get(key))

    current = saved(stage_id)
    if current and current.unlocked:
        return True
    zone_id = definition.get("zoneId")
    if zone_id and "zone_table" in ctx.data.manifest["tables"]:
        chapters = ctx.data.table("zone_table").get("mainlineAdditionInfo", {})
        chapter = chapters.get(zone_id)
        if chapter:
            if chapter.get("zoneOpenTime", -1) > ctx.now:
                return False
            previous = chapter.get("preposedZoneId")
            if previous:
                if previous not in chapters or not chapters[previous].get("endStageId"):
                    raise DomainError("GAMEDATA_INVALID", "主线章节前置定义不完整", 503)
                last_stage = chapters[previous]["endStageId"]
                row = saved(last_stage)
                if row is None or row.stars < 1:
                    return False
    return all((row := saved(cond["stageId"]))
               and row.stars >= required_stars(cond.get("completeState", "PASS"))
               for cond in definition.get("unlockCondition") or [])


def start(ctx: Context, stage_id: str, squad_id: str | None, practice: bool = False,
          *, predefined: bool = False, replay_members: tuple[BattleMember, ...] | None = None) -> dict:
    from terralocal.server.domain.rogue_battle import ensure_no_active

    ensure_no_active(ctx)
    definition = ctx.data.stage(stage_id)
    if definition.get("stageType") == "CAMPAIGN":
        raise DomainError("CAMPAIGN_BATTLE_UNSUPPORTED", "剿灭战斗需使用独立结算流程，当前未扣除理智", 501)
    if definition["isStoryOnly"]:
        raise DomainError("STORY_STAGE", "剧情关不能创建战斗")
    if not unlocked(ctx, stage_id):
        raise DomainError("STAGE_LOCKED", "尚未满足关卡解锁条件")
    if ctx.session.scalar(select(m.BattleSession.id).where(
        m.BattleSession.account_id == ctx.account_id, m.BattleSession.state == "STARTED")):
        raise DomainError("ACTIVE_BATTLE", "已有未结算战斗，请结算或放弃", 409)
    if practice and not definition["canPractice"]:
        raise DomainError("PRACTICE_UNAVAILABLE", "此关卡不允许演习")
    if predefined:
        training_rule(ctx.data, stage_id)
        if squad_id is not None or replay_members is not None:
            raise DomainError("PREDEFINED_SQUAD_CONFLICT", "固定阵容关卡不能使用玩家编队", 409)
        slots = []
    else:
        if definition.get("isPredefined") or definition.get("isHardPredefined"):
            raise DomainError("PREDEFINED_FORMATION_REQUIRED", "固定阵容关卡不能使用普通战斗流程", 501)
        if replay_members is not None:
            if practice or squad_id is not None:
                raise DomainError("REPLAY_SQUAD_CONFLICT", "代理阵容不能混用演习或保存编队", 409)
            slots = replay_members
        else:
            slots = sorted([s for s in ctx.rows(m.SquadSlot) if s.squad_id == squad_id], key=lambda s: s.slot)
    if not predefined and not slots:
        raise DomainError("EMPTY_SQUAD", "请选择有干员的编队")
    required = requirements(ctx.data, stage_id)
    progress = ctx.session.get(m.StageProgress, (ctx.account_id, stage_id))
    if required and not (required["first_pass_only"] and progress is not None and progress.stars > 0):
        # Native assists are rejected by the protocol adapter. Only the actual
        # owned formation (including a saved proxy formation) can satisfy this.
        operators = [ctx.operator(slot.operator_id) for slot in slots]
        if any(not any(op.char_id == cid and op.evolve_phase >= phase for op in operators)
               for cid, phase in required["operators"].items()):
            raise DomainError("STAGE_REQUIRED_OPERATOR", "编队未满足关卡要求的干员及精英阶段")
    sanity = ctx.sanity()
    cost = 0 if practice else definition["apCost"]
    if cost < 0:
        raise DomainError("UNSUPPORTED_STAGE_COST", "此关卡使用的特殊资源尚未实现", 501)
    if sanity.current < cost:
        raise DomainError("INSUFFICIENT_SANITY", "理智不足")
    if sanity.current >= sanity.maximum:
        sanity.last_recovery_at = ctx.now
    sanity.current -= cost
    snapshot = [{"charInstId": s.operator_id, "skillIndex": s.skill_index,
                 "charId": ctx.operator(s.operator_id).char_id,
                 "level": ctx.operator(s.operator_id).level,
                 "evolvePhase": ctx.operator(s.operator_id).evolve_phase} for s in slots]
    battle = m.BattleSession(id=str(uuid.uuid4()), account_id=ctx.account_id, stage_id=stage_id,
                             state="STARTED", sanity_cost=cost, practice=practice, started_at=ctx.now,
                             seed=secrets.randbelow(2**31), squad_snapshot=snapshot)
    ctx.session.add(battle)
    progress = ctx.session.get(m.StageProgress, (ctx.account_id, stage_id))
    if progress is None:
        progress = m.StageProgress(account_id=ctx.account_id, stage_id=stage_id, unlocked=True, start_count=0)
        ctx.session.add(progress)
    progress.start_count += 1
    return {"battleId": battle.id, "apFailReturn": definition["apFailReturn"],
            "inApProtectPeriod": False, "isApProtect": 0, "notifyPowerScoreNotEnoughIfFailed": False}


def native_start(ctx: Context, stage_id: str, squad_id: str | None, slots: list[dict | None] | None,
                 *, drop_rules: dict, replay: bool = False) -> dict:
    definition = ctx.data.stage(stage_id)
    predefined = bool(definition.get("isPredefined"))
    if (definition.get("stageType") != "MAIN"
            or definition.get("difficulty") != "NORMAL"
            or definition.get("diffGroup") != "NONE"
            or definition.get("isHardPredefined")
            or definition.get("isStagePatch")):
        raise DomainError("NATIVE_STAGE_UNSUPPORTED", "此关卡类型尚未完成游戏端适配", 501)
    protection = ctx.data.table("stage_table").get("apProtectZoneInfo", {})
    if definition.get("apProtectTimes", 0) != 0 or definition.get("zoneId") in protection:
        raise DomainError("AP_PROTECTION_UNSUPPORTED", "此关卡的理智保护规则尚未实现", 501)
    rule = training_rule(ctx.data, stage_id) if predefined else drop_rules.get(stage_id)
    if rule is None:
        raise DomainError("DROP_RULE_MISSING", "此关卡尚未准备掉落规则，未扣除理智", 503)
    if predefined:
        if replay or squad_id is not None or slots is not None:
            raise DomainError("PREDEFINED_SQUAD_CONFLICT", "固定阵容关卡不能提交玩家编队", 409)
    elif squad_id is None or slots is None:
        raise DomainError("MISSING_SQUAD", "普通关卡必须提交已保存的玩家编队")
    proxy = None
    if replay:
        from terralocal.server.domain.replays import proxy_formation

        proxy = proxy_formation(ctx, stage_id, squad_id, slots)
    _recover_previous_session(ctx, drop_rules)
    if predefined:
        result = start(ctx, stage_id, None, predefined=True)
    elif proxy is not None:
        result = start(ctx, stage_id, None, replay_members=proxy.members)
    else:
        result = _start_saved_squad(ctx, stage_id, squad_id, slots)
    login_time = ctx.profile.flags.get("loginTime", ctx.profile.last_online_at)
    if type(login_time) is not int or not 0 <= login_time <= 253_402_271_999:
        raise DomainError("INVALID_LOGIN_TIME", "存档中的登录时间无效", 503)
    get_session(ctx, result["battleId"]).native_context = {
        "codec_version": NATIVE_CODEC_VERSION, "gamedata_hash": ctx.data.manifest["hash"],
        "login_time": login_time, "drop_rule_hash": fingerprint(rule),
        "formation_mode": "AUTO_BATTLE" if proxy else "CLIENT_PREDEFINED" if predefined else "PLAYER_SQUAD",
        "session_binding": battle_binding(ctx.local_session),
        "level_id": definition.get("levelId"),
        "replay_generation": ctx.session.get(m.StageProgress, (ctx.account_id, stage_id)).start_count}
    if proxy is not None:
        get_session(ctx, result["battleId"]).native_context = {
            **get_session(ctx, result["battleId"]).native_context,
            "replay_source_sha256": proxy.sha256, "replay_source_battle_id": proxy.battle_id}
    # DefaultStartBattleResponse declares bool; AP protection above is excluded.
    return {**result, "isApProtect": False}


def _recover_previous_session(ctx: Context, drop_rules: dict) -> None:
    """Starting after a new login abandons an interrupted, older native battle.

    Login alone never discards a pending finish. Recovery and the replacement
    start share the caller's transaction, including any failed-start rollback.
    Frozen clocks and same-second logins cannot be distinguished by loginTime.
    """
    local = ctx.local_session
    if local is None or local.kind != "game" or local.account_id != ctx.account_id:
        raise DomainError("INVALID_SESSION", "请重新登录后开始战斗", 401)
    latest = ctx.session.scalar(select(m.LocalSession.id).where(
        m.LocalSession.account_id == ctx.account_id, m.LocalSession.kind == "game")
        .order_by(m.LocalSession.id.desc()).limit(1))
    if latest != local.id:
        raise DomainError("INVALID_SESSION", "此账号已重新登录，请刷新客户端", 401)
    active = ctx.session.scalars(select(m.BattleSession).where(
        m.BattleSession.account_id == ctx.account_id, m.BattleSession.state == "STARTED")).all()
    if not active:
        return
    if len(active) != 1:
        raise DomainError("INVALID_BATTLE_STATE", "存档存在多个未结算战斗，请检查存档", 503)
    previous = active[0]
    if ctx.data.stage(previous.stage_id).get("stageType") == "CAMPAIGN":
        from terralocal.server.domain.campaign_battle import recover

        recover(ctx, previous)
        return
    context = native_context(ctx, previous.id)
    binding = context.get("session_binding")
    basis = "recorded-session-binding"
    if binding is None:
        # Pre-binding native versions retained the start receipt and its local
        # session row. No session cleanup exists in those versions. Recover
        # only an unambiguous, account-owned game session from that receipt.
        origins = set()
        receipts = ctx.session.scalars(select(m.Receipt).where(
            m.Receipt.account_id == ctx.account_id,
            m.Receipt.result["battleId"].as_string() == previous.id)).all()
        for receipt in receipts:
            match = re.fullmatch(r"session:([1-9][0-9]*):[0-9a-f]{64}", receipt.key)
            result = receipt.result
            if (match and receipt.created_at == previous.started_at and result.get("result") == 0
                    and "apFailReturn" in result and "isApProtect" in result):
                origins.add(int(match[1]))
        if len(origins) != 1:
            raise DomainError("BATTLE_RECOVERY_UNAVAILABLE", "旧战斗缺少确定的登录记录，未修改存档", 503)
        origin = ctx.session.get(m.LocalSession, origins.pop())
        if origin is None or origin.account_id != ctx.account_id or origin.kind != "game":
            raise DomainError("BATTLE_RECOVERY_UNAVAILABLE", "旧战斗的登录记录不可验证，未修改存档", 503)
        binding, basis = battle_binding(origin), "legacy-start-receipt"
    if not isinstance(binding, str) or not re.fullmatch(r"[0-9a-f]{64}", binding):
        raise DomainError("BATTLE_RECOVERY_UNAVAILABLE", "战斗的登录记录无效，未修改存档", 503)
    if binding == battle_binding(local):
        raise DomainError("ACTIVE_BATTLE", "已有未结算战斗，请结算或放弃", 409)
    native_finish(ctx, previous.id, previous.stage_id, complete_state=1, interrupted=True,
                  give_up=True, percent=0, kills=0, valid_kills=0, duration=0, drop_rules=drop_rules)
    previous.native_context = {**previous.native_context, "recovery": {
        "policy": RECOVERY_POLICY, "basis": basis, "reason": "new-game-session-start", "at": ctx.now}}
    ctx.emit("BattleRecovered", battle_id=previous.id, stage_id=previous.stage_id,
             policy=RECOVERY_POLICY, returned_sanity=previous.settlement["apFailReturn"])
    ctx.session.flush()


def _start_saved_squad(ctx, stage_id, squad_id, slots):
    saved_squad(ctx, squad_id, slots)
    return start(ctx, stage_id, squad_id)


def saved_squad(ctx, squad_id, slots):
    """Validate a native formation without starting a particular battle mode."""
    if ctx.session.get(m.Squad, (ctx.account_id, squad_id)) is None:
        raise DomainError("UNKNOWN_SQUAD", "编队不存在", 404)
    expected = [None] * 12
    for row in ctx.rows(m.SquadSlot):
        if row.squad_id == squad_id:
            if row.module_id:
                raise DomainError("MODULE_UNSUPPORTED", "模组战斗适配尚未实现", 501)
            expected[row.slot] = {"charInstId": row.operator_id, "skillIndex": row.skill_index}
    actual = []
    for slot in slots:
        if slot is not None and slot.get("currentEquip"):
            raise DomainError("MODULE_UNSUPPORTED", "模组战斗适配尚未实现", 501)
        actual.append(None if slot is None else {
            "charInstId": slot["charInstId"], "skillIndex": slot["skillIndex"]})
    actual += [None] * (12 - len(actual))
    if actual != expected:
        raise DomainError("SQUAD_CONFLICT", "战斗编队与已保存编队不一致，请重新保存", 409)
    return sorted((row for row in ctx.rows(m.SquadSlot) if row.squad_id == squad_id), key=lambda row: row.slot)


def get_session(ctx, battle_id):
    battle = ctx.session.get(m.BattleSession, battle_id)
    if battle is None or battle.account_id != ctx.account_id:
        raise DomainError("UNKNOWN_BATTLE", "战斗会话不存在", 404)
    return battle


def native_context(ctx: Context, battle_id: str) -> dict:
    battle = get_session(ctx, battle_id)
    context = battle.native_context
    if (not isinstance(context, dict) or context.get("codec_version") != NATIVE_CODEC_VERSION
            or type(context.get("login_time")) is not int
            or not 0 <= context["login_time"] <= 253_402_271_999
            or not isinstance(context.get("gamedata_hash"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", context["gamedata_hash"])
            or not isinstance(context.get("drop_rule_hash"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", context["drop_rule_hash"])):
        raise DomainError("NATIVE_CONTEXT_UNAVAILABLE", "此战斗没有经过验证的游戏端版本记录", 503)
    return context


def native_finish(ctx: Context, battle_id: str, stage_id: str, *, complete_state: int,
                  interrupted: bool, give_up: bool, percent: float, kills: int, valid_kills: int,
                  duration: int, drop_rules: dict) -> dict:
    if (type(complete_state) is not int or complete_state not in {1, 2, 3}
            or type(interrupted) is not bool or type(give_up) is not bool
            or type(percent) not in (int, float) or not 0 <= percent <= 100 or not math.isfinite(percent)
            or type(kills) is not int or not 0 <= kills <= 100_000
            or type(valid_kills) is not int or not 0 <= valid_kills <= 100_000
            or type(duration) is not int or not 0 <= duration <= 86400
            or complete_state != 1 and (interrupted or give_up)):
        raise DomainError("INVALID_NATIVE_FINISH", "战斗提交数据无效，尚未提交结算")
    percent = float(percent)
    battle = get_session(ctx, battle_id)
    context = native_context(ctx, battle_id)
    if stage_id != battle.stage_id:
        raise DomainError("BATTLE_STAGE_CONFLICT", "结算关卡与战斗记录不一致", 409)
    # This hash covers outcome facts only, not random IVs or private telemetry.
    outcome_hash = fingerprint({"stage": stage_id, "rank": complete_state, "interrupted": interrupted,
                                "give_up": give_up, "percent": percent, "kills": kills,
                                "valid_kills": valid_kills, "duration": duration})
    if battle.state in {"FINISHED", "ABORTED"}:
        if context.get("settlement_hash") != outcome_hash:
            raise DomainError("SETTLEMENT_CONFLICT", "重复结算的战斗结果不一致", 409)
        if not isinstance(battle.settlement, dict):
            raise DomainError("INVALID_BATTLE_SETTLEMENT", "存档中的战斗结算记录无效", 503)
        result = battle.settlement
    else:
        if context["gamedata_hash"] != ctx.data.manifest["hash"]:
            raise DomainError("BATTLE_DATA_CHANGED", "战斗期间 GameData 版本发生变化，尚未提交结算", 503)
        stars = 0 if complete_state == 1 else complete_state
        rule = (training_rule(ctx.data, stage_id) if context.get("formation_mode") == "CLIENT_PREDEFINED"
                else drop_rules.get(stage_id))
        if stars and context["drop_rule_hash"] != fingerprint(rule):
            raise DomainError("BATTLE_DROP_RULE_CHANGED", "战斗期间掉落规则发生变化，尚未提交结算", 503)
        result = finish(ctx, battle_id, stars, drop_rules=drop_rules, kills=kills, duration=duration)
        battle.native_context = {**context, "settlement_hash": outcome_hash}
    # Expose the verified native response fields. Extra battle modes were
    # excluded at start, so their optional rewards/data are empty here.
    response = {key: value for key, value in result.items() if key != "stars"}
    response.update(itemReturn=[], overrideRewards=[], diamondMaterialRewards=[], extra=None)
    for name in ("rewards", "firstRewards", "furnitureRewards"):
        # The frozen native finish view inserts its EXP icon from the actual
        # before/after player experience difference. Sending EXP_PLAYER again
        # adds a second icon. Keep the award in the persisted settlement/delta;
        # only omit that redundant service item from the native visual lists.
        # GOLD has no matching native insertion and must remain here.
        response[name] = [{**reward, "type": reward.get("type", ctx.data.item(reward["id"])["itemType"]),
                           "charGet": reward.get("charGet")} for reward in response[name]
                          if ctx.data.item(reward["id"])["itemType"] != "EXP_PLAYER"]
    response["expScale"], response["goldScale"] = float(response["expScale"]), float(response["goldScale"])
    return response


def finish(ctx: Context, battle_id: str, stars: int, *, drop_rules: dict,
           kills: int = 0, duration: float = 0) -> dict:
    if (type(stars) is not int or stars not in range(4)
            or type(kills) is not int or not 0 <= kills <= 100_000
            or type(duration) not in (int, float) or not 0 <= duration <= 86400
            or not math.isfinite(duration)):
        raise DomainError("INVALID_BATTLE_RESULT", "战斗结算数据非法")
    battle = get_session(ctx, battle_id)
    duration = float(duration) if duration else 0.0
    request_hash = fingerprint({"stars": stars, "kills": kills, "duration": duration})
    if battle.state in {"FINISHED", "ABORTED"}:
        compatible_hashes = {request_hash}
        # Existing saves used the JSON number representation before duration normalization.
        if duration.is_integer():
            compatible_hashes.add(fingerprint({"stars": stars, "kills": kills, "duration": int(duration)}))
        if duration == 0:
            compatible_hashes.add(fingerprint({"stars": stars, "kills": kills, "duration": -0.0}))
        if battle.request_hash not in compatible_hashes:
            raise DomainError("SETTLEMENT_CONFLICT", "重复结算的战斗结果不一致", 409)
        return battle.settlement
    if battle.state != "STARTED":
        raise DomainError("INVALID_BATTLE_STATE", "战斗会话状态不允许结算", 409)
    definition = ctx.data.stage(battle.stage_id)
    if definition.get("stageType") == "CAMPAIGN":
        raise DomainError("CAMPAIGN_BATTLE_UNSUPPORTED", "剿灭需使用独立结算流程，尚未提交此结算", 501)
    progress = ctx.session.get(m.StageProgress, (ctx.account_id, battle.stage_id))
    rewards, first_rewards = [], []
    returned, new_unlocks = 0, []
    if not battle.practice:
        if stars == 0:
            returned = min(battle.sanity_cost, definition["apFailReturn"])
            ctx.sanity().current += returned
        else:
            rule = (training_rule(ctx.data, battle.stage_id)
                    if battle.native_context and battle.native_context.get("formation_mode") == "CLIENT_PREDEFINED"
                    else drop_rules.get(battle.stage_id))
            if rule is None:
                raise DomainError("DROP_RULE_MISSING", "缺少经过确认的关卡掉落规则，未提交结算", 503)
            versioned = rule.get("kind") == "versioned-drops-v1"
            rewards = (select_rewards(rule, battle.seed, ctx.data) if versioned
                       else [dict(r) for r in rule.get("rewards", [])])
            first_pass_rule = versioned or rule.get("kind") == "predefined-training-v1"
            if first_pass_rule and progress.clear_count == 0 and progress.stars == 0:
                first_rewards = [dict(r) for r in rule["first_pass_rewards"]]
            scale = ctx.data.constants["completeGainBonus"] if stars == 3 else 1
            for item_id, key in (("4001", "goldGain"), ("5001", "expGain")):
                count = int(definition[key] * scale)
                if count:
                    rewards.append({"id": item_id, "count": count, "type": ctx.data.item(item_id)["itemType"]})
            if not progress.first_clear_claimed and stars == 3:
                first_rewards += [dict(r) for r in rule.get(
                    "first_complete_rewards" if first_pass_rule else "first_rewards", [])]
                if definition["diamondOnceDrop"] > 0:
                    first_rewards.append({"id": "4002", "count": definition["diamondOnceDrop"], "type": "DIAMOND"})
                progress.first_clear_claimed = True
            rewards = ctx.rewards(rewards)
            first_rewards = ctx.rewards(first_rewards)
            progress.stars = max(progress.stars, stars)
            progress.clear_count += 1
            trust_limit = maximum_trust(ctx.data)
            trust_gain = definition["completeFavor" if stars == 3 else "passFavor"]
            for op in battle.squad_snapshot:
                operator = ctx.operator(op["charInstId"])
                operator.trust = min(trust_limit, operator.trust + trust_gain)
            ctx.emit("BattleFinished", stage_id=battle.stage_id, kills=kills, stars=stars, practice=False)
            ctx.session.flush()
            for stage_id, stage in ctx.data.stages.items():
                if any(c["stageId"] == battle.stage_id for c in stage.get("unlockCondition") or []):
                    if unlocked(ctx, stage_id):
                        row = ctx.session.get(m.StageProgress, (ctx.account_id, stage_id))
                        if row is None:
                            ctx.session.add(m.StageProgress(account_id=ctx.account_id, stage_id=stage_id, unlocked=True))
                            new_unlocks.append(stage_id)
                        elif not row.unlocked:
                            row.unlocked = True
                            new_unlocks.append(stage_id)
    if battle.practice and stars:
        ctx.emit("BattleFinished", stage_id=battle.stage_id, kills=kills, stars=stars, practice=True)
    furniture_rewards = [reward for reward in rewards if ctx.data.item(reward["id"])["itemType"] == "FURN"]
    rewards = [reward for reward in rewards if ctx.data.item(reward["id"])["itemType"] != "FURN"]
    result = {"stars": stars, "apFailReturn": returned, "expScale": scale if stars and not battle.practice else 1,
              "goldScale": scale if stars and not battle.practice else 1, "rewards": rewards,
              "firstRewards": first_rewards, "unlockStages": new_unlocks, "unusualRewards": [],
              "additionalRewards": [], "furnitureRewards": furniture_rewards, "alert": [], "suggestFriend": False,
              "pryResult": []}
    battle.state = "FINISHED" if stars else "ABORTED"
    battle.finished_at, battle.request_hash, battle.settlement = ctx.now, request_hash, result
    return result


def save_replay(ctx: Context, battle_id: str, replay: dict) -> dict:
    battle = get_session(ctx, battle_id)
    if (battle.state != "FINISHED" or battle.practice
            or not battle.settlement or battle.settlement.get("stars") != 3):
        raise DomainError("REPLAY_UNAVAILABLE", "只有非演习三星通关可以保存代理记录")
    row = ctx.session.get(m.StageReplay, (ctx.account_id, battle.stage_id))
    if row is None:
        ctx.session.add(m.StageReplay(account_id=ctx.account_id, stage_id=battle.stage_id,
                                      battle_id=battle_id, replay=replay, created_at=ctx.now))
    else:
        row.battle_id, row.replay, row.created_at = battle_id, replay, ctx.now
    return {"stageId": battle.stage_id}
