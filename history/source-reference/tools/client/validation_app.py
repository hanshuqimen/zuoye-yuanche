"""Reloadable, loopback-only game server for the isolated Android test instance.

Uses the same transactional local save. It has no management listener and does
not replace the user's launcher or stop an existing service.
"""

from contextlib import asynccontextmanager

from terralocal.config import load_settings
from terralocal.server.main import create_game_app
from terralocal.server.services.runtime import Runtime


def create_app():
    settings = load_settings()
    runtime = Runtime(settings)
    app = create_game_app(runtime)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            runtime.database.close()

    app.router.lifespan_context = lifespan
    return app
