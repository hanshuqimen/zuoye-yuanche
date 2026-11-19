"""Snapshot-local reuse must preserve corruption rejection and save isolation."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update
from test_rogue_cost_relics import buy, configure
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_training import training_runtime as training_runtime
from test_roguelike_initial import init_runtime as init_runtime
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_runs, rogue_topics
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_reads import facts, scope
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m


def test_archive_projection_matches_without_scope_and_validates_each_run_once(cost_runtime, monkeypatch):
    runtime, token = cost_runtime
    configure(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "buy").status_code == 200
        assert post(client, token, "giveUpGame", {}, "giveup").status_code == 200
        assert post(client, token, "gameSettle", {}, "confirm").status_code == 200
    saved = rows(runtime.database.path)
    original, seen = rogue_runs.validate_run, []

    def count(data, run, *args, **kwargs):
        seen.append(run.id)
        return original(data, run, *args, **kwargs)

    monkeypatch.setattr(rogue_runs, "validate_run", count)
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        expected = rogue_topics.snapshot.__wrapped__(ctx)
        uncached_count = len(seen)
        seen.clear()
        assert rogue_topics.snapshot(ctx) == expected
        assert len(seen) < uncached_count and len(seen) == len(set(seen))
        assert facts(ctx) is None
        # A fresh snapshot must validate again, even with the same Context.
        seen.clear()
        assert rogue_topics.snapshot(ctx) == expected and seen
    assert rows(runtime.database.path) == saved
    # Previously valid archived rows may become corrupt; no cross-call result
    # is allowed to hide that damage or supply an attained entry from it.
    with runtime.database.transaction() as session:
        session.query(m.RogueRunRelic).filter_by(ordinal=1).one().count = 2
    corrupt = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == corrupt


@pytest.mark.parametrize("write", ["orm_pending", "orm_flush", "core_update", "core_delete"])
def test_session_writes_invalidate_an_already_validated_run(init_runtime, write):
    runtime = init_runtime
    with runtime.database.transaction() as session:
        rogue_runs.create(Context(session, runtime.data, 1), "rogue_1", "NORMAL", 0, None, None)
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError), runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        run = session.query(m.RogueTopicRun).one()
        with scope(ctx):
            rogue_runs.validated(ctx, run)
            if write in ("orm_pending", "orm_flush"):
                run.gold += 1
                if write == "orm_flush":
                    session.flush()
            elif write == "core_update":
                session.execute(update(m.RogueTopicRun).where(m.RogueTopicRun.id == run.id)
                                .values(gold=run.gold + 1))
            else:
                session.execute(delete(m.RogueRunEvent).where(m.RogueRunEvent.run_id == run.id,
                                                             m.RogueRunEvent.ordinal == 0))
            rogue_runs.validated(ctx, run)
    assert facts(ctx) is None and rows(runtime.database.path) == saved


def test_failed_projection_discards_its_entries_and_cannot_hide_later_damage(init_runtime):
    runtime = init_runtime
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        rogue_runs.create(ctx, "rogue_1", "NORMAL", 0, None, None)
        run = session.query(m.RogueTopicRun).one()
        with pytest.raises(RuntimeError, match="projection failed"), scope(ctx):
            rogue_runs.validated(ctx, run)
            raise RuntimeError("projection failed")
        assert facts(ctx) is None
        run.gold += 1
        session.flush()
        with pytest.raises(DomainError), scope(ctx):
            rogue_runs.validated(ctx, run)
        assert facts(ctx) is None
        session.rollback()
