"""Conditional completion facts and stable acquisition boundary for notices."""

from sqlalchemy import select

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_ending_unlocks import RunCompletion
from terralocal.server.gamedata.rogue_ending_variants import CONDITIONS, RunEndingVariant
from terralocal.server.persistence import models as m


def invalid():
    return DomainError("ROGUE_ENDING_VARIANT_INCOMPATIBLE", "通关附加条件或先前获得边界不一致；请保留原存档", 503)


def facts(run, known):
    return RunEndingVariant(RunCompletion(run.mode, run.grade, run.created_at, known["ended"],
        known.get("success", 0), known.get("ending")), run.band_id, run.hope_max - run.hope_cost,
        run.hope_max, known["counts"][6], run.gold)


def boundary(data, target, runs):
    # A positive frozen reopening cooldown and one active exploration guarantee
    # strictly increasing start timestamps. Old closed runs cannot gain later
    # items. Equal-start ambiguous QA histories are rejected, never UUID-sorted.
    if data.rogue_initial.cooldown <= 0:
        raise invalid()
    for run in runs:
        if (run.account_id != target.account_id or run.topic_id != target.topic_id
                or run.id != target.id and (run.created_at >= target.created_at
                                             or run.state not in ("ABANDONED", "SETTLED"))):
            raise invalid()


def attained_through_run(ctx, target):
    from terralocal.server.domain.rogue_runs import validated

    runs = ctx.session.scalars(select(m.RogueTopicRun).where(m.RogueTopicRun.account_id == target.account_id,
        m.RogueTopicRun.topic_id == target.topic_id, m.RogueTopicRun.created_at <= target.created_at)).all()
    boundary(ctx.data, target, runs)
    found = set()
    for run in runs:
        children = validated(ctx, run)
        found.update(row.item_id for row in children[1] if row.ordinal > 0 and row.item_id in CONDITIONS)
    return tuple(sorted(found))


def attained_on_disk(data, con, target):
    from types import SimpleNamespace

    runs = [SimpleNamespace(**dict(raw)) for raw in con.execute(
        "SELECT * FROM rlv2_runs WHERE account_id=? AND topic_id=? AND created_at<=?",
        (target.account_id, target.topic_id, target.created_at))]
    boundary(data, target, runs)
    # Called before retained-run preflight finishes, but that preflight still
    # validates every acquisition/source before Runtime can write or serve.
    found = {item for item, in con.execute(
        "SELECT l.item_id FROM rlv2_relics l JOIN rlv2_runs r ON l.run_id=r.id "
        "WHERE r.account_id=? AND r.topic_id=? AND r.created_at<=? AND l.ordinal>0",
        (target.account_id, target.topic_id, target.created_at)) if item in CONDITIONS}
    return tuple(sorted(found))
