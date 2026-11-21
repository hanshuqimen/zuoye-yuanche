"""Transaction participant for admitted battle objectives, not final settlement.

No route calls this component yet. Its eventual caller must admit the outcome,
handle records/comments, finish the battle and commit in the same transaction.
It neither grants rewards nor releases the active-battle lock on its own.
"""

from copy import deepcopy

from terralocal.server.domain import crisis_v2, crisis_v2_battles
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m


def project(before, rules, result, *, cleared):
    """Pure progression projection shared by settlement and readonly recovery."""
    permanent = "scoreSingle" in before
    if not permanent and (rules.map_rules.bags or rules.treasures):
        raise ValueError("临时地图含未适配的永久任务")
    after = deepcopy(before)
    if cleared:
        after["state"] = True
        ordinary = {v for v in result.runes if not rules.map_rules.nodes[v].lockable}
        after["rune"] |= dict.fromkeys(ordinary, 3)
        if permanent:
            after["exRunes"] |= dict.fromkeys(result.runes - ordinary, 3)
            after["runePack"] |= {v: max(1, after["runePack"].get(v, 0)) for v in result.packs}
            for ident, progress in result.treasure_progress:
                old = after["reward"].get(ident, {"state": 0, "progress": 0})
                progress = max(progress, old["progress"])
                after["reward"][ident] = {"state": max(int(progress >= rules.treasures[ident].required), old["state"]),
                                           "progress": progress}
        after["challenge"] |= {v: max(1, after["challenge"].get(v, 0)) for v in result.challenges}
    return after


def apply(row, value):
    # Reassign each JSON field: in-place mutation is not tracked by SQLAlchemy.
    for attr, key in (("cleared", "state"), ("score_total", "scoreTotal"), ("runes", "rune"),
                      ("challenges", "challenge"), ("score_single", "scoreSingle"), ("comments", "comment"),
                      ("extra_runes", "exRunes"), ("rune_packs", "runePack"), ("rewards", "reward")):
        if key in value:
            setattr(row, attr, deepcopy(value[key]))


def summary(map_id, result):
    return {"mapId": map_id, "completedRunes": sorted(result.runes),
        "completedChallenges": sorted(result.challenges), "completedPacks": sorted(result.packs),
        "treasureProgress": dict(result.treasure_progress), "unverifiedEmptyPacks": sorted(result.empty_packs)}


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
        before = crisis_v2._map(ctx, row).model_dump()
        after = project(before, rules, result, cleared=cleared)
    except (ValueError, TypeError, AttributeError) as exc:
        raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约地图保存字段无效", 503) from exc
    apply(row, after)
    return summary(key[1], result)
