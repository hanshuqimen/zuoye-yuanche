"""Owned discovery, not a synthetic claim that unlock quests are completed."""

import copy
import hashlib
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy, configure
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_recruit_costs import R25, R26, R27, R28, source
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_topics import snapshot
from terralocal.server.gamedata.rogue_collection import FirstThemeRelicArchive
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def catalog(table):
    return FirstThemeRelicArchive(SimpleNamespace(table=lambda name: table,
        manifest={"hash": "a" * 64}, rogue_topics=SimpleNamespace(topic=lambda topic: topic)))


def collection(runtime, token):
    return runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["relic"]


@pytest.mark.parametrize("relic", [R25, R26, R27, R28])
def test_purchase_projects_one_attained_entry_without_unlocking_the_other_family(cost_runtime, relic):
    runtime, token = cost_runtime
    configure(runtime, token, relic)
    assert collection(runtime, token) == {}
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)["user"]
        reply = buy(client, token, "relic", "archive-relic")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        assert collection(runtime, token) == {relic: {"state": 2, "progress": []}}
        assert buy(client, token, "relic", "retry").status_code == 200
        assert runtime.sync(token)["user"] == after
    # Read-only projection does not rewrite the saved outer structure.
    saved = rows(runtime.database.path)
    with runtime.database.transaction(write=False) as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        assert outer.state["collect"]["relic"] == {}
        assert snapshot(Context(session, runtime.data, 1)) == after["rlv2"]
    assert rows(runtime.database.path) == saved


def test_discovery_survives_abandon_reentry_restart_backup_and_is_account_owned(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, R26)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "relic").status_code == 200
        assert post(client, token, "giveUpGame", {}, "abandon").status_code == 200
        assert post(client, token, "gameSettle", {}, "confirm-abandon").status_code == 200
    earned = {R26: {"state": 2, "progress": []}}
    assert collection(runtime, token) == earned
    with runtime.database.transaction() as session:
        other = create_account(session, runtime.data, "OtherArchiveDoctor")
        other_token = login(session, runtime.settings, name=other.name)["secret"]
        session.get(m.ServerClockState, 1).fixed_at += runtime.data.rogue_initial.cooldown
    assert collection(runtime, other_token) == {}
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0},
                    "new-run").status_code == 200
    final = runtime.sync(token)["user"]
    assert collection(runtime, token) == earned
    assert final["rlv2"]["current"]["inventory"]["relic"] == {}
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
        assert collection(reopened, other_token) == {}
    finally:
        reopened.database.close()
    backups = BackupService(runtime)
    backup = backups.create()
    saved = rows(runtime.database.path)
    backups.restore(backup["name"])
    assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == final


def test_archived_corrupt_source_cannot_supply_permanent_discovery_or_rewrite_save(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "relic").status_code == 200
        assert post(client, token, "giveUpGame", {}, "abandon").status_code == 200
    with runtime.database.transaction() as session:
        session.query(m.RogueRunRelic).filter_by(ordinal=1).one().count = 2
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError):
        collection(runtime, token)
    assert rows(runtime.database.path) == saved
    runtime.database.close()
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


def test_saved_claim_without_acquisition_does_not_grant_an_attained_archive_entry(cost_runtime):
    runtime, token = cost_runtime
    with runtime.database.transaction() as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        state = copy.deepcopy(outer.state)
        state["collect"]["relic"][R26] = {"state": 2, "progress": []}
        outer.state = state
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError, match="图鉴"):
        collection(runtime, token)
    assert rows(runtime.database.path) == saved


def test_claim_without_acquisition_is_rejected_before_startup_writes(cost_runtime):
    runtime, _ = cost_runtime
    with runtime.database.transaction() as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        state = copy.deepcopy(outer.state)
        state["collect"]["relic"][R27] = {"state": 2, "progress": []}
        outer.state = state
    runtime.database.close()
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


def test_archive_compilation_is_immutable_and_does_not_interpret_unlock_descriptions():
    table = source()
    item = table["details"]["rogue_1"]["items"][R26]
    item["unlockCondDesc"] = "Unmet QA condition; never interpret this prose as an earned grant"
    rules = catalog(table)
    entry = rules.entries[R26]
    old_hash = rules.fingerprint
    item["unlockCondDesc"] = None
    assert entry.unlock_description is not None and rules.fingerprint == old_hash
    assert catalog(table).fingerprint != old_hash
    with pytest.raises(TypeError):
        rules.entries[R26] = None
    with pytest.raises(FrozenInstanceError):
        entry.order = "changed"


@pytest.mark.parametrize("mutation", ["missing_item", "missing_effect", "identity", "bool_group", "unknown_enroll"])
def test_bad_archive_references_are_not_admitted(mutation):
    table = source()
    detail = table["details"]["rogue_1"]
    row = detail["archiveComp"]["relic"]["relic"][R26]
    if mutation == "missing_item":
        del detail["items"][R26]
    elif mutation == "missing_effect":
        del detail["relics"][R26]
    elif mutation == "identity":
        row["relicId"] = R25
    elif mutation == "bool_group":
        row["relicGroupId"] = True
    else:
        row["enrollId"] = "future-unknown"
    with pytest.raises(ValueError):
        catalog(table)
