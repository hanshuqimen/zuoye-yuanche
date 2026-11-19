"""Authenticated local presence and notification-flag polling.

This does not fabricate event-specific push messages. Current local mail and
clue flags are projected from the save; unknown message types need adapters.
"""

from fastapi import APIRouter, Request

from terralocal.server.api.schemas import Command
from terralocal.server.domain.context import Context
from terralocal.server.domain.refresh import push_flags
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.protocol.delta import diff
from terralocal.server.protocol.sync import SyncDataAssembler


def router(runtime):
    api = APIRouter()

    @api.post("/account/syncPushMessage")
    def sync_push(_payload: Command, request: Request):
        from terralocal.server.main import credentials

        with runtime.maintenance, runtime.database.transaction() as session:
            account, _ = authenticate_session(session, *credentials(request))
            ctx = Context(session, runtime.require_data(), account.id)
            before = SyncDataAssembler(ctx).assemble()
            ctx.sanity()
            ctx.profile.last_online_at = max(ctx.profile.last_online_at, ctx.now)
            after = SyncDataAssembler(ctx).assemble()
            delta = diff(before, after)
            if delta["modified"] or delta["deleted"]:
                ctx.profile.revision += 1
            # Mail may have arrived through GM since the preceding full sync.
            # Reassert only the small, verified flag contract, not entire state.
            delta["modified"]["pushFlags"] = push_flags(ctx)
            return {"code": 200, "msg": "OK", "ts": ctx.now, "playerDataDelta": delta}

    return api
