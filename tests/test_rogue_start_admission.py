"""Prevent known unfinishable new battles; no native play or official pool claim."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_roguelike_battle_start import activate, begin, body
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current
from test_roguelike_state import rows

from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime


@pytest.mark.parametrize("kind,stage", [("BATTLE_ELITE", "emergency"), ("BATTLE_BOSS", "boss")])
def test_known_unfinishable_node_never_creates_pending_battle_or_receipt(rogue_battle_runtime, kind, stage):
    runtime, token = rogue_battle_runtime
    activate(runtime, token, kind, stage)
    before = current(runtime, token)
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        for key in ("reject-start", "reject-start", "different-sequence"):
            result = begin(client, token, body(stage), key=key)
            assert result.status_code == 501, result.text
            assert rows(runtime.database.path) == saved
            assert current(runtime, token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueBattle).count() == 0
        assert session.query(m.RogueBattleSettlement).count() == 0


@pytest.mark.parametrize("field", ["max_hp", "battle_char_limit"])
def test_unsupported_next_level_effect_is_rejected_before_combat(rogue_battle_runtime, monkeypatch, field):
    runtime, token = rogue_battle_runtime
    activate(runtime, token)
    curve = runtime.data.rogue_levels
    original = curve.gains
    monkeypatch.setattr(curve, "gains", lambda *args: replace(original(*args), **{field: 1}))
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        result = begin(client, token)
        assert result.status_code == 501 and result.json()["error"]["code"] == "ROGUE_LEVEL_EFFECT"
    assert rows(runtime.database.path) == saved


def test_old_started_unsupported_battle_keeps_its_snapshot_and_retry(rogue_battle_runtime, monkeypatch):
    from terralocal.server.domain import rogue_settlement

    runtime, token = rogue_battle_runtime
    activate(runtime, token, "BATTLE_ELITE", "emergency")
    # Reproduce the old admission on an authored save; do not edit a player's
    # rows or reinterpret it as a successfully supported elite outcome.
    with monkeypatch.context() as old:
        old.setattr(rogue_settlement, "admit_start", lambda *args: None)
        with TestClient(create_game_app(runtime)) as client:
            response = begin(client, token, body("emergency"))
            assert response.status_code == 200
    before = current(runtime, token)
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert rows(runtime.database.path) == saved
        assert current(reopened, token) == before
        with TestClient(create_game_app(reopened)) as client:
            assert begin(client, token, body("emergency")).json() == response.json()
            assert rows(runtime.database.path) == saved
            retry = begin(client, token, body("emergency"), key="old-start-new-sequence")
            assert retry.status_code == 200 and retry.json()["battleId"] == response.json()["battleId"]
        assert current(reopened, token) == before
        with reopened.database.transaction(write=False) as session:
            assert session.query(m.RogueBattle).count() == 1
            assert session.query(m.RogueBattleSettlement).count() == 0
    finally:
        reopened.database.close()
