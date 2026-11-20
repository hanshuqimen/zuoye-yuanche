"""Reference-level CN fields. Client validation is tracked separately from domain tests."""

from sqlalchemy import select

from terralocal.server.domain.battle import unlocked
from terralocal.server.domain.campaign import available as campaign_available
from terralocal.server.domain.campaign import snapshot as campaign_snapshot
from terralocal.server.domain.context import Context
from terralocal.server.domain.crisis_v2 import available as crisis_available
from terralocal.server.domain.crisis_v2 import snapshot as crisis_snapshot
from terralocal.server.domain.headhunting import snapshot as headhunting_snapshot
from terralocal.server.domain.operators import check_condition
from terralocal.server.domain.progress import main_stage_progress
from terralocal.server.domain.recruitment import snapshot as recruit_snapshot
from terralocal.server.domain.refresh import last_refreshed_at, push_flags
from terralocal.server.domain.replays import available as replay_available
from terralocal.server.domain.rogue_topics import available as rogue_available
from terralocal.server.domain.rogue_topics import snapshot as rogue_snapshot
from terralocal.server.persistence import models as m
from terralocal.server.protocol.home import initial_display
from terralocal.server.protocol.mission_state import snapshot as mission_snapshot
from terralocal.server.protocol.shop_state import purchase_counters


class SyncDataAssembler:
    def __init__(self, ctx: Context, *, period_at: int | None = None):
        self.ctx = ctx
        self.period_at = ctx.now if period_at is None else period_at

    def operator(self, op, skills: dict[int, list]) -> dict:
        definition = self.ctx.data.character(op.char_id)
        progress = {s.skill_id: s for s in skills.get(op.id, [])}
        result = []
        for skill in definition["skills"]:
            row = progress.get(skill["skillId"])
            result.append({"skillId": skill["skillId"], "unlock": int(check_condition(op, skill["unlockCond"])),
                           "state": 1 if row and row.training_complete_at else 0,
                           "specializeLevel": row.mastery if row else 0,
                           "completeUpgradeTime": row.training_complete_at if row and row.training_complete_at else -1})
        return {"instId": op.id, "charId": op.char_id, "favorPoint": op.trust, "potentialRank": op.potential,
                "mainSkillLvl": op.skill_level, "skin": op.skin, "level": op.level, "exp": op.exp,
                "evolvePhase": op.evolve_phase, "defaultSkillIndex": op.default_skill, "gainTime": op.gained_at,
                           "skills": result, "voiceLan": op.voice_language,
                           "currentEquip": op.current_module, "equip": {},
                "starMark": int(op.locked)}

    def assemble(self) -> dict:
        ctx, profile = self.ctx, self.ctx.profile
        account = ctx.session.get(m.Account, ctx.account_id)
        sanity = ctx.session.get(m.SanityState, ctx.account_id)
        operators = ctx.read_rows(m.Operator)
        skills = {}
        if operators:
            for row in ctx.session.execute(select(m.OperatorSkill.__table__).join(
                m.Operator, m.OperatorSkill.operator_id == m.Operator.id).where(m.Operator.account_id == ctx.account_id)):
                skills.setdefault(row.operator_id, []).append(row)
        currencies = {r.item_id: r.balance for r in ctx.read_rows(m.Currency)}
        slots = ctx.read_rows(m.SquadSlot)
        squads = {}
        for squad in ctx.read_rows(m.Squad):
            squad_slots = [None] * 12
            for slot in slots:
                if slot.squad_id == squad.squad_id:
                    squad_slots[slot.slot] = {"charInstId": slot.operator_id, "skillIndex": slot.skill_index,
                                             "currentEquip": slot.module_id}
            squads[squad.squad_id] = {"squadId": squad.squad_id, "name": squad.name, "slots": squad_slots}
        replays = {r.stage_id for r in ctx.read_rows(m.StageReplay) if replay_available(ctx, r)}
        progress = {r.stage_id: r for r in ctx.read_rows(m.StageProgress)}
        campaign = campaign_snapshot(ctx, at=self.period_at) if campaign_available(ctx.data) else None
        stages = {r.stage_id: {"stageId": r.stage_id,
                               "state": 3 if r.stars == 3 else 2 if r.stars else int(r.start_count > 0),
                               "completeTimes": r.clear_count,
                               "startTimes": r.start_count, "practiceTimes": 0,
                               "hasBattleReplay": r.stage_id in replays, "noCostCnt": 0}
                  for r in progress.values()}
        # An unlocked, unplayed mainline stage also has a PlayerStage entry.
        # Missing entries make the frozen client treat the first chapter as
        # locked. Derive these views from the same rules used for battle start;
        # reading the save must not invent a start, clear or persisted progress.
        for stage_id, definition in ctx.data.table("stage_table")["stages"].items():
            known_campaign = campaign is not None and stage_id in campaign["instances"]
            if ((definition.get("stageType") == "MAIN" or known_campaign) and stage_id not in stages
                    and unlocked(ctx, stage_id, progress=progress)):
                stages[stage_id] = {"stageId": stage_id, "state": 0, "completeTimes": 0,
                                    "startTimes": 0, "practiceTimes": 0, "hasBattleReplay": False, "noCostCnt": 0}
        inventory = {r.item_id: r.count for r in ctx.read_rows(m.InventoryItem)}
        furniture = ctx.read_rows(m.OwnedFurniture)
        skins = ctx.read_rows(m.OwnedSkin)
        status = {"uid": account.uid, "nickName": profile.nickname, "level": profile.level, "exp": profile.exp,
                  "socialPoint": currencies.get("SOCIAL_PT", 0), "gold": currencies.get("4001", 0),
                  "diamondShard": currencies.get("4003", 0), "payDiamond": 0,
                  "freeDiamond": currencies.get("4002", 0), "hggShard": currencies.get("4004", 0),
                  "lggShard": currencies.get("4005", 0), "ap": sanity.current,
                  "maxAp": sanity.maximum, "lastApAddTime": sanity.last_recovery_at,
                  "lastOnlineTs": profile.last_online_at, "registerTs": profile.registered_at,
                  "secretary": profile.secretary, "secretarySkinId": profile.secretary_skin,
                  "avatar": profile.avatar, "resume": profile.resume,
                  "flags": {**profile.flags.get("story", {}),
                            **{row.story_id: 1 for row in ctx.read_rows(m.StoryCompletion)}},
                  "nickNumber": "0001", "lastRefreshTs": last_refreshed_at(ctx),
                  "buyApRemainTimes": 0,
                  "practiceTicket": 0, "apLimitUpFlag": 0, "avatarId": "0",
                  "globalVoiceLan": profile.flags.get("voiceLan", "JP"),
                  "mainStageProgress": main_stage_progress(ctx, progress),
                  "progress": profile.flags.get("progress", 0),
                  "serverName": "TerraLocal",
                  "monthlySubscriptionStartTime": 0, "monthlySubscriptionEndTime": 0,
                  "tipMonthlyCardExpireTs": 0,
                  "androidDiamond": currencies.get("4002", 0), "iosDiamond": currencies.get("4002", 0),
                  "gachaTicket": inventory.get("7003", 0), "tenGachaTicket": inventory.get("7004", 0),
                  "classicShard": inventory.get("classic_normal_ticket", 0),
                  "classicGachaTicket": inventory.get("classic_gacha", 0),
                  "classicTenGachaTicket": inventory.get("classic_gacha_10", 0),
                  "recruitLicense": inventory.get("7001", 0), "instantFinishTicket": inventory.get("7002", 0),
                  "friendNumLimit": ctx.data.constants.get("baseMaxFriendNum", 0)}
        return {"status": status,
                # PlayerDataModel.campaign has JsonProperty("campaignsV2").
                **({"campaignsV2": campaign} if campaign is not None else {}),
                **({"rlv2": rogue_snapshot(ctx)} if rogue_available(ctx.data) else {}),
                **({"crisisV2": crisis_snapshot(ctx)} if crisis_available(ctx.data) else {}),
                **({"recruit": recruit_snapshot(ctx)} if "gacha_table" in ctx.data.manifest["tables"] else {}),
                **({"gacha": headhunting_snapshot(ctx)} if "gacha_table" in ctx.data.manifest["tables"] else {}),
                **initial_display(ctx),
                **({"building": {"furniture": {row.item_id: {"count": row.count, "inUse": 0}
                                               for row in furniture}}} if furniture else {}),
                "troop": {"chars": {str(o.id): self.operator(o, skills) for o in operators}, "squads": squads,
                          "curCharInstId": max((o.id for o in operators), default=0),
                          "curSquadCount": len(squads), "charGroup": {}},
                "inventory": inventory, "dungeon": {"stages": stages},
                "shop": purchase_counters(ctx, at=self.period_at),
                "skin": {"characterSkins": {r.skin_id: 1 for r in skins},
                         "skinTs": {r.skin_id: r.obtained_at for r in skins}, "skinSp": {}},
                "pushFlags": push_flags(ctx), "storyreview": {"groups": {}, "tags": {}},
                "mission": mission_snapshot(ctx, at=self.period_at)}
