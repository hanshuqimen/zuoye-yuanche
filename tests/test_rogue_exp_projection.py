"""Frozen normal-style EXP consumption, not an official server drop fixture."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_rogue_levels import levels
from test_rogue_settlement import complete, prepared
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_state import rows

from terralocal.server.domain import rogue_runs, rogue_topics
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_levels import FirstThemeLevelCurve
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.roguelike import legacy_response
from terralocal.server.services.runtime import Runtime

KEY = "_terralocal_rogue_exp_view"
VERSION = "in-level-v1"


@pytest.fixture
def wire_data(monkeypatch):
    monkeypatch.setattr(rogue_topics, "available", lambda _: True)
    return SimpleNamespace(rogue_recruit=SimpleNamespace(catalog={}), rogue_levels=FirstThemeLevelCurve(levels()))


def envelope(exp, *, tag=None, level=None):
    value = {"exp": exp}
    if level is not None:
        value["level"] = level
    result = {"result": 0, "playerDataDelta": {"modified": {"rlv2": {"current": {
        "player": {"property": value}}}}, "deleted": {}}}
    if tag is not None:
        result[KEY] = tag
    return result


@pytest.mark.parametrize("total,expected", [(0, 0), (9, 9), (10, 0), (24, 14), (32, 22),
    (34, 0), (69, 35), (70, 0), (71, 1), (2**31 - 1, 2**31 - 1 - 70)])
def test_legacy_receipt_exp_is_adapted_without_mutating_saved_bytes_or_requiring_level(wire_data, total, expected):
    saved = envelope(total)
    original = deepcopy(saved)
    actual = legacy_response(wire_data, saved)
    wanted = deepcopy(saved)
    wanted["playerDataDelta"]["modified"]["rlv2"]["current"]["player"]["property"]["exp"] = expected
    assert actual == wanted and saved == original
    assert rogue_runs.wire_exp(wire_data, total) == expected


@pytest.mark.parametrize("exp", [0, 14, 22, 35, 100])
def test_tagged_remainder_is_not_converted_twice_and_private_tag_never_leaks(wire_data, exp):
    saved = envelope(exp, tag=VERSION)
    expected = deepcopy(saved)
    expected.pop(KEY)
    assert legacy_response(wire_data, saved) == expected
    assert saved[KEY] == VERSION


@pytest.mark.parametrize("shape", [None, {}, {"player": None}, {"player": {"property": None}},
    {"player": {"property": {"gold": 5}}}])
def test_reference_clears_and_partial_non_exp_receipts_keep_their_original_meaning(wire_data, shape):
    saved = {"playerDataDelta": {"modified": {"rlv2": {"current": shape}}, "deleted": {}}}
    before = deepcopy(saved)
    assert legacy_response(wire_data, saved) == before and saved == before


@pytest.mark.parametrize("exp", [True, False, -1, 2**31, 1.0, "32"])
def test_malformed_legacy_exp_is_rejected_instead_of_coerced(wire_data, exp):
    with pytest.raises(DomainError):
        legacy_response(wire_data, envelope(exp))


def test_unknown_receipt_exp_version_is_rejected_without_editing_it(wire_data):
    value = envelope(22, tag="future-unknown")
    original = deepcopy(value)
    with pytest.raises(DomainError):
        legacy_response(wire_data, value)
    assert value == original


def test_native_player_uses_level_remainder_only_and_retains_total_and_old_finish_receipt(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        response = complete(client, token, battle_id, journal, hp, "exp-finish")
        assert response.status_code == 200, response.text
        actual = runtime.sync(token)["user"]
        assert actual["rlv2"]["current"]["player"]["property"]["exp"] == 0
        assert actual["rlv2"]["current"]["player"]["property"]["level"] == 2
        assert apply(before, response.json()["playerDataDelta"]) == actual
        assert KEY not in response.json()
        with runtime.database.transaction() as session:
            run = session.query(m.RogueTopicRun).one()
            settled = session.query(m.RogueBattleSettlement).one()
            assert run.exp == settled.effects["after"]["exp"] == 10
            receipt = next(row for row in session.query(m.Receipt).filter_by(account_id=1)
                           if row.result["revision"] == response.json()["revision"])
            assert receipt.result[KEY] == VERSION
            legacy = deepcopy(receipt.result)
            legacy.pop(KEY)
            legacy["playerDataDelta"]["modified"]["rlv2"]["current"]["player"]["property"]["exp"] = 10
            receipt.result = legacy  # Authored previous-server receipt, not a runtime backfill.
        saved = rows(runtime.database.path)
        replay = complete(client, token, battle_id, journal, hp, "exp-finish")
        expected_replay = deepcopy(response.json())
        # The old delta explicitly set cumulative EXP10. Its adapter retains
        # that field as remainder0, while the new 0->0 delta can omit it.
        expected_replay["playerDataDelta"]["modified"]["rlv2"]["current"]["player"]["property"]["exp"] = 0
        assert replay.json() == expected_replay and rows(runtime.database.path) == saved
        assert apply(before, replay.json()["playerDataDelta"]) == actual
        assert runtime.sync(token)["user"] == actual
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == actual
        with TestClient(create_game_app(reopened)) as client:
            assert complete(client, token, battle_id, journal, hp, "exp-finish").json() == expected_replay
        assert rows(runtime.database.path) == saved
    finally:
        reopened.database.close()
