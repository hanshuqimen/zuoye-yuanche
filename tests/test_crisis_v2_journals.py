"""Opt-in preserves the original owned journal, never errors on older missing archives."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_crisis_v2_clears import request, setup
from test_crisis_v2_native_battles import finish, source, start

from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.crisis_v2_journals import PREFIX
from terralocal.server.main import create_game_app
from terralocal.server.services.runtime import Runtime


@pytest.mark.parametrize("enabled", [False, True])
def test_clear_archive_is_opt_in_and_owner_only(tmp_path, enabled):
    initial, _, payload = setup(tmp_path, tables=source())
    settings = initial.settings.model_copy(update={"crisis_archive_replays": enabled})
    initial.database.close()
    runtime = Runtime(settings)
    try:
        with runtime.database.transaction() as session:
            token = login(session, settings, name="CrisisDoctor")["secret"]
            create_account(session, runtime.data, "JournalOther")
            other = login(session, settings, name="JournalOther")["secret"]
        with TestClient(create_game_app(runtime)) as client:
            ident = start(client, token, payload).raise_for_status().json()["battleId"]
            body = request(ident, payload)
            response = finish(client, token, body).raise_for_status().json()
            path = f"/local/v1/crisis-v2/history/{ident}/journal"
            assert "battleLog" not in response
            assert client.get(path, headers={"secret": other}).status_code == 404
            archived = client.get(path, headers={"secret": token})
            if enabled:
                assert archived.raise_for_status().json()["battleLog"] == body.battleLog
                assert archived.headers["cache-control"] == "no-store"
                assert finish(client, token, body, key="repeat").raise_for_status().json()["ts"] == response["ts"]
            else:
                assert archived.status_code == 404
    finally:
        runtime.database.close()
    if enabled:
        cold = Runtime(settings)
        cold.database.close()
        with sqlite3.connect(settings.database_path) as connection:
            connection.execute("UPDATE receipts SET result=? WHERE key=?",
                               (json.dumps({"version": "wrong", "battleLog": "abc"}), PREFIX + ident))
        before = settings.database_path.read_bytes()
        with pytest.raises(ValueError, match="战斗保存不兼容"):
            Runtime(settings)
        assert settings.database_path.read_bytes() == before