"""Reuse successful validation only inside one owned snapshot projection.

No result survives the call, transaction, failed projection or backup restore.
These scopes contain reads, never domain actions. Session writes invalidate
their entries so a later validation cannot trust an earlier view of a row.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps

from sqlalchemy import event
from sqlalchemy.orm import object_session

from terralocal.server.persistence import models as m

_CONTENT_SCOPE = object()


@dataclass
class ReadFacts:
    runs: dict = field(default_factory=dict)
    content: tuple | None = None
    history: tuple | None = None

    def clear(self, *_):
        self.runs.clear()
        self.content = None
        self.history = None


def facts(ctx):
    known = getattr(ctx, "_rogue_read_facts", None)
    if known is not None and (ctx.session.new or ctx.session.dirty or ctx.session.deleted):
        ctx.session.flush()  # before_flush invalidates even not-yet-flushed ORM edits.
    return known


def content_facts(data, run, draft):
    """Find the active projection's cache for its own ORM run and draft only."""
    if not isinstance(run, m.RogueTopicRun) or not isinstance(draft, m.RogueMapDraft):
        return None
    session = object_session(run)
    if session is None or object_session(draft) is not session:
        return None
    ctx = session.info.get(_CONTENT_SCOPE)
    if ctx is None or ctx.data is not data or run.account_id != ctx.account_id:
        return None
    return facts(ctx)


@contextmanager
def scope(ctx):
    if facts(ctx) is not None:
        yield facts(ctx)
        return
    ctx.session.flush()
    known = ReadFacts()

    def executing(state):
        if not state.is_select:
            known.clear()

    listeners = (("before_flush", known.clear), ("do_orm_execute", executing),
                 ("after_transaction_end", known.clear))
    for name, callback in listeners:
        event.listen(ctx.session, name, callback)
    ctx._rogue_read_facts = known
    previous = ctx.session.info.get(_CONTENT_SCOPE)
    ctx.session.info[_CONTENT_SCOPE] = ctx
    try:
        yield known
    finally:
        if previous is None:
            ctx.session.info.pop(_CONTENT_SCOPE)
        else:
            ctx.session.info[_CONTENT_SCOPE] = previous
        del ctx._rogue_read_facts
        for name, callback in listeners:
            event.remove(ctx.session, name, callback)


def snapshot_scope(project):
    @wraps(project)
    def scoped(ctx):
        with scope(ctx):
            return project(ctx)
    return scoped
