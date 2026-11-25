"""Read-only local history: never exports raw journals or login material."""

from copy import deepcopy

from sqlalchemy import select

from terralocal.server.domain import crisis_v2_battles
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence.models import BattleSession, CrisisV2Battle

VERSION = "local-crisis-v2-record-v1"


def _public(pending):
    battle, saved = pending.battle, pending.crisis
    if battle.state == "STARTED":
        raise DomainError("CRISIS_V2_RECORD_PENDING", "战斗尚未结算", 409)
    result = battle.settlement["result"]
    return {"version": VERSION, "battleId": battle.id, "seasonId": saved.season_id, "mapId": saved.map_id,
            "startedAt": battle.started_at, "finishedAt": battle.finished_at,
            "outcome": result["outcome"], "runeSlots": list(pending.evaluation.rune_slots),
            "score": list(pending.evaluation.dimension_scores),
            "comments": deepcopy(result.get("earnedComments", [])),
            "playableReplay": False}


def detail(ctx, battle_id: str):
    saved = ctx.session.get(CrisisV2Battle, battle_id)
    if saved is None or saved.account_id != ctx.account_id:
        raise DomainError("UNKNOWN_BATTLE", "战斗会话不存在", 404)
    return _public(crisis_v2_battles.context(ctx, battle_id))


def recent(ctx, *, offset: int, limit: int):
    parent_ids = list(ctx.session.scalars(select(BattleSession.id)
        .join(CrisisV2Battle, CrisisV2Battle.battle_id == BattleSession.id)
        .where(CrisisV2Battle.account_id == ctx.account_id, BattleSession.account_id == ctx.account_id,
               BattleSession.state.in_(("FINISHED", "ABORTED")))
        .order_by(BattleSession.finished_at.desc(), BattleSession.id.desc()).offset(offset).limit(limit + 1)))
    return {"records": [detail(ctx, ident) for ident in parent_ids[:limit]],
            "nextOffset": offset + limit if len(parent_ids) > limit else None}