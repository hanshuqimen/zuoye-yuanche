"""Transaction participant for admitted battle objectives, not final settlement.

No route calls this component yet. Its eventual caller must admit the outcome,
handle records/comments, finish the battle and commit in the same transaction.
It neither grants rewards nor releases the active-battle lock on its own.
"""

from terralocal.server.domain import crisis_v2, crisis_v2_battles
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m


def record(ctx, battle_id, *, cleared):
    pending = crisis_v2_battles.context(ctx, battle_id, require_session=True)
    if pending.battle.state != "STARTED":
        raise DomainError("CRISIS_V2_BATTLE_ALREADY_FINISHED", "已结算战斗不能再写入任务进度", 409)
    key = (pending.crisis.season_id, pending.crisis.map_id)
    catalog = ctx.data.crisis_v2
    try:
        rules = catalog.objectives(*key)
        result = rules.evaluate(pending.evaluation, cleared=cleared)
    except (ValueError, TypeError, KeyError) as exc:
        raise DomainError("CRISIS_V2_OBJECTIVES_UNSUPPORTED", "危机合约任务条件尚未完成适配", 503) from exc
    row = ctx.session.get(m.CrisisV2MapProgress, (ctx.account_id, *key))
    try:
        crisis_v2._map(ctx, row)
    except (ValueError, TypeError, AttributeError) as exc:
        raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约地图保存字段无效", 503) from exc
    permanent = row.kind == "PERMANENT"
    if not permanent and (rules.map_rules.bags or rules.treasures):
        raise DomainError("CRISIS_V2_OBJECTIVES_UNSUPPORTED", "临时地图含未适配的永久任务", 503)
    # Reassign JSON values so SQLAlchemy records each change. Preserve claimed
    # state 2 and greater historical per-battle progress, even on a later retry.
    if cleared:
        row.cleared = True
        ordinary = {v for v in result.runes if not rules.map_rules.nodes[v].lockable}
        extra = result.runes - ordinary
        row.runes = row.runes | dict.fromkeys(ordinary, 3)
        if permanent:
            row.extra_runes = row.extra_runes | dict.fromkeys(extra, 3)
            row.rune_packs = row.rune_packs | {v: max(1, row.rune_packs.get(v, 0)) for v in result.packs}
            rewards = dict(row.rewards)
            for ident, progress in result.treasure_progress:
                old = rewards.get(ident, {"state": 0, "progress": 0})
                progress = max(progress, old["progress"])
                ready = int(progress >= rules.treasures[ident].required)
                rewards[ident] = {"state": max(ready, old["state"]), "progress": progress}
            row.rewards = rewards
        row.challenges = row.challenges | {v: max(1, row.challenges.get(v, 0)) for v in result.challenges}
    return {"mapId": key[1], "completedRunes": sorted(result.runes),
        "completedChallenges": sorted(result.challenges), "completedPacks": sorted(result.packs),
        "treasureProgress": dict(result.treasure_progress), "unverifiedEmptyPacks": sorted(result.empty_packs)}
