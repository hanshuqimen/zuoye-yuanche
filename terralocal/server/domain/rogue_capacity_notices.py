"""Owned through-run capacity eligibility boundary for versioned result pages."""

import json
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import select

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_ending_variants import boundary
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_capacity_unlocks import ITEM
from terralocal.server.persistence import models as m


def invalid():
    return DomainError("ROGUE_CAPACITY_NOTICE_INCOMPATIBLE", "容量解锁的历史边界不一致；请保留原存档", 503)


@dataclass(frozen=True)
class CapacityNotice:
    run_id: str
    before: bool
    after: bool
    attained: bool
    history_hash: str


def derive(data, target, entries):
    """Inputs must already have complete acquisition and resource validation."""
    boundary(data, target, tuple(run for run, _, _ in entries))
    ordered = sorted(entries, key=lambda entry: entry[0].created_at)
    if (not ordered or ordered[-1][0].id != target.id
            or len({r.id for r, _, _ in ordered}) != len(ordered)
            or len({r.created_at for r, _, _ in ordered}) != len(ordered)
            or any(type(owned) is not bool or (scope.mode, scope.grade, scope.started_at)
                   != (run.mode, run.grade, run.created_at) for run, scope, owned in ordered)):
        raise invalid()
    rules = data.rogue_capacity_unlocks
    scopes = tuple(scope for _, scope, _ in ordered)
    before = bool(rules.evaluate(scopes[:-1])[ITEM].wire()["state"])
    after = bool(rules.evaluate(scopes)[ITEM].wire()["state"])
    owned = any(attained for _, _, attained in ordered)
    return CapacityNotice(target.id, before, after, owned,
        fingerprint([[run.id, scope.mode, scope.grade, scope.started_at, scope.peak, attained]
                     for run, scope, attained in ordered]))


def in_session(ctx, target):
    from terralocal.server.domain.rogue_collection import capacity
    from terralocal.server.domain.rogue_runs import validated

    runs = ctx.session.scalars(select(m.RogueTopicRun).where(m.RogueTopicRun.account_id == target.account_id,
        m.RogueTopicRun.topic_id == target.topic_id, m.RogueTopicRun.created_at <= target.created_at)).all()
    boundary(ctx.data, target, runs)
    entries = []
    for run in runs:
        replayed = []
        children = validated(ctx, run, progress_out=replayed)
        entries.append((run, capacity(ctx.data, run, replayed[0]),
                        any(row.ordinal > 0 and row.item_id == ITEM for row in children[1])))
    return derive(ctx.data, target, tuple(entries))


def on_disk(data, connection, target):
    """The Runtime's complete retained-run preflight remains mandatory."""
    from terralocal.server.domain.rogue_collection import capacity
    from terralocal.server.domain.rogue_settlement import state_on_disk

    runs = [SimpleNamespace(**dict(raw)) for raw in connection.execute(
        "SELECT * FROM rlv2_runs WHERE account_id=? AND topic_id=? AND created_at<=?",
        (target.account_id, target.topic_id, target.created_at))]
    boundary(data, target, runs)
    entries = []
    for run in runs:
        tickets = []
        for row in connection.execute("SELECT * FROM rlv2_tickets WHERE run_id=? ORDER BY ordinal", (run.id,)):
            value = dict(row)
            for key in ("elite_pool", "direct_pool"):
                if key in value:
                    value[key] = json.loads(value[key])
            tickets.append(SimpleNamespace(**value))
        replayed = state_on_disk(data, connection, run, tickets)
        attained = connection.execute("SELECT 1 FROM rlv2_relics WHERE run_id=? AND ordinal>0 AND item_id=?",
                                      (run.id, ITEM)).fetchone() is not None
        entries.append((run, capacity(data, run, replayed), attained))
    return derive(data, target, tuple(entries))
