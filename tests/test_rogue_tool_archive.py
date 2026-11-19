"""Permanent tool discovery survives replacement, settlement and new runs."""

import copy
import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_support_tools import A, B, configure, rule_data
from test_rogue_support_tools import support_runtime as support_runtime
from test_rogue_support_tools import support_tables as support_tables
from test_rogue_training import training_runtime as training_runtime
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_tool_archive
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_support_tools import FirstThemeSupportTools
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.roguelike_state import OuterState
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def archive(runtime, token):
    return runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["activeTool"]


def expected(*found):
    return {key: {"state": 2 if key in found else 1, "progress": []} for key in (A, B)}


def test_missing_entry_is_projected_unattained_not_locked_without_equipping(support_runtime):
    runtime, token = support_runtime
    before = rows(runtime.database.path)
    assert archive(runtime, token) == expected()
    assert rows(runtime.database.path) == before
    configure(runtime, token)
    user = runtime.sync(token)["user"]
    assert user["rlv2"]["current"]["inventory"]["trap"] is None
    assert archive(runtime, token) == expected()


def test_replacement_retains_both_acquisitions_and_delta_without_rewriting_outer(support_runtime):
    runtime, token = support_runtime
    configure(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)["user"]
        first = buy(client, token, "early", "archive-tool-a")
        assert first.status_code == 200, first.text
        assert apply(before, first.json()["playerDataDelta"]) == runtime.sync(token)["user"]
        assert archive(runtime, token) == expected(A)
        second = buy(client, token, "later", "archive-tool-b")
        assert second.status_code == 200, second.text
        final = runtime.sync(token)["user"]
        assert archive(runtime, token) == expected(A, B)
        assert final["rlv2"]["current"]["inventory"]["trap"]["id"] == B
        assert buy(client, token, "early", "archive-retry-a").status_code == 200
        assert runtime.sync(token)["user"] == final
    with runtime.database.transaction(write=False) as ss:
        assert ss.get(m.RogueTopicOuter, (1, "rogue_1")).state["collect"]["activeTool"] == {}


def test_discovery_survives_settlement_new_run_restart_backup_and_account_isolation(support_runtime):
    runtime, token = support_runtime
    configure(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "early", "archive-first").status_code == 200
        assert post(client, token, "giveUpGame", {}, "archive-giveup").status_code == 200
        assert post(client, token, "gameSettle", {}, "archive-confirm").status_code == 200
    assert archive(runtime, token) == expected(A)
    with runtime.database.transaction() as ss:
        other = create_account(ss, runtime.data, "OtherToolArchiveDoctor")
        other_token = login(ss, runtime.settings, name=other.name)["secret"]
        ss.get(m.ServerClockState, 1).fixed_at += runtime.data.rogue_initial.cooldown
    assert archive(runtime, other_token) == expected()
    with TestClient(create_game_app(runtime)) as client:
        response = post(client, token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0}, "archive-new-run")
        assert response.status_code == 200, response.text
    final = runtime.sync(token)["user"]
    assert final["rlv2"]["current"]["inventory"]["trap"] is None
    assert archive(runtime, token) == expected(A)
    saved = rows(runtime.database.path)
    backup = BackupService(runtime).create()
    BackupService(runtime).restore(backup["name"])
    assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == final
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final and archive(reopened, other_token) == expected()
    finally:
        reopened.database.close()


@pytest.mark.parametrize("entry", [
    (A, {"state": 2, "progress": []}),
    ("unknown_tool", {"state": 1, "progress": []}),
    (A, {"state": 1, "progress": [1, 1]}),
])
def test_unproven_claims_are_rejected_live_and_before_startup_writes(support_runtime, entry):
    runtime, token = support_runtime
    with runtime.database.transaction() as ss:
        outer = ss.get(m.RogueTopicOuter, (1, "rogue_1"))
        state = copy.deepcopy(outer.state)
        state["collect"]["activeTool"][entry[0]] = entry[1]
        outer.state = state
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError, match="工具图鉴"):
        archive(runtime, token)
    assert rows(runtime.database.path) == saved
    runtime.database.close()
    before = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == before


def test_projection_failure_rolls_back_new_discovery_payment_and_source(support_runtime, monkeypatch):
    runtime, token = support_runtime
    configure(runtime, token)
    before = rows(runtime.database.path)
    original = rogue_tool_archive.project
    def fail(data, state, found, at):
        if found:
            raise DomainError("QA_TOOL_ARCHIVE_PROJECTION", "Authored projection failure", 503)
        return original(data, state, found, at)
    monkeypatch.setattr(rogue_tool_archive, "project", fail)
    with TestClient(create_game_app(runtime)) as client:
        response = buy(client, token, "early", "archive-rollback")
        assert response.status_code == 503, response.text
    assert rows(runtime.database.path) == before and archive(runtime, token) == expected()


def test_reviewed_opening_does_not_infer_attainment_or_drop_historical_discovery(monkeypatch):
    data, detail = rule_data(monkeypatch)
    data.manifest["tables"] = {"roguelike_topic_table": {}}
    data.rogue_support_tools = FirstThemeSupportTools(data)
    closed = rogue_tool_archive.project(data, OuterState().model_dump(), frozenset(), 99)
    assert {r["state"] for r in closed["collect"]["activeTool"].values()} == {0}
    opened = rogue_tool_archive.project(data, OuterState().model_dump(), frozenset(), 100)
    assert opened["collect"]["activeTool"] == expected()
    past = rogue_tool_archive.project(data, OuterState().model_dump(), frozenset({A}), 99)
    assert past["collect"]["activeTool"][A]["state"] == 2
    assert detail["archiveComp"]["trap"]["trap"][A]["enrollId"] is None
    empty = SimpleNamespace(manifest={"tables": {}})
    assert rogue_tool_archive.project(empty, OuterState().model_dump(), (), 100)["collect"]["activeTool"] == {}
