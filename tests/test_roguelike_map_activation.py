"""Initial-event handoff, no official floor weights or node/battle play claims."""

import copy
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_roguelike_initial import current, post
from test_roguelike_map import plan
from test_roguelike_map_drafts import save
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map_drafts import finish_initial
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import REVISION, ROGUE_MAP_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.roguelike import EXP_VIEW_KEY
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

pytest_plugins = ("test_roguelike_map_drafts",)


def test_finish_only_activates_saved_first_zone_and_retries_never_reroll(draft_runtime):
    runtime, token = draft_runtime
    with TestClient(create_game_app(runtime)) as client:
        saved = rows(runtime.database.path)
        assert post(client, token, "finishEvent", {}, "not-ready").status_code == 503
        assert rows(runtime.database.path) == saved
        graph = save(runtime, replace(plan(), zone_id="zone_1"))
        before = runtime.sync(token)["user"]
        first = post(client, token, "finishEvent", {}, "finish")
        assert first.status_code == 200
        after = runtime.sync(token)["user"]
        assert apply(before, first.json()["playerDataDelta"]) == after
        assert after["rlv2"]["current"]["player"]["state"] == "WAIT_MOVE"
        assert after["rlv2"]["current"]["player"]["pending"] == []
        assert after["rlv2"]["current"]["map"]["zones"] == {"1": graph.wire()}
        assert after["rlv2"]["current"]["player"]["cursor"] == {"zone": 1, "position": None}
        assert before["rlv2"]["current"]["inventory"] == after["rlv2"]["current"]["inventory"]
        assert {k: v for k, v in before.items() if k != "rlv2"} == {
            k: v for k, v in after.items() if k != "rlv2"}
        saved = rows(runtime.database.path)
        assert post(client, token, "finishEvent", {}, "finish").json() == first.json()
        assert rows(runtime.database.path) == saved
        assert post(client, token, "finishEvent", {}, "finish-again").status_code == 200
        assert current(runtime, token) == after["rlv2"]["current"]
        assert post(client, token, "activeRecruitTicket", {"id": "0"}, "no-old-recruit").status_code == 409
        backup = BackupService(runtime).create()
        saved = rows(runtime.database.path)
        BackupService(runtime).restore(backup["name"])
        assert rows(runtime.database.path) == saved
    reopened = Runtime(runtime.settings)
    try:
        assert current(reopened, token) == after["rlv2"]["current"]
    finally:
        reopened.database.close()


def test_handoff_and_receipt_rollback_together(draft_runtime):
    runtime, token = draft_runtime
    save(runtime, replace(plan(), zone_id="zone_1"))
    before = rows(runtime.database.path)
    def fail(ctx):
        finish_initial(ctx)
        raise DomainError("INJECTED", "injected handoff failure")
    with pytest.raises(DomainError, match="injected handoff"):
        runtime.mutate(token, None, "fail", "rogue-test", {}, fail)
    assert rows(runtime.database.path) == before


def test_legacy_zone_zero_receipt_is_adapted_without_reexecution_or_save_write(draft_runtime):
    runtime, token = draft_runtime
    graph = save(runtime, replace(plan(), zone_id="zone_1"))
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        first = post(client, token, "finishEvent", {}, "legacy-finish").json()
        old = copy.deepcopy(first)
        delta = old["playerDataDelta"]
        partial = delta["modified"]["rlv2"]["current"]
        partial["map"]["zones"] = {"0": partial["map"]["zones"]["1"]}
        partial["player"].pop("cursor")  # Old handoff left the initial cursor unchanged.
        with runtime.database.transaction() as session:
            # The HTTP adapter removes the current internal EXP-view marker.
            # Select the receipt by its public envelope, then replace it with
            # an explicitly unversioned historical handoff fixture below.
            receipt = next(r for r in session.query(m.Receipt)
                           if {k: v for k, v in r.result.items() if k != EXP_VIEW_KEY} == first)
            receipt.result = old
        saved = rows(runtime.database.path)
        replay = post(client, token, "finishEvent", {}, "legacy-finish")
        assert replay.status_code == 200
        repaired = replay.json()["playerDataDelta"]
        assert apply(before, repaired) == runtime.sync(token)["user"]
        stale = copy.deepcopy(before)
        stale["rlv2"]["current"]["map"]["zones"] = {"0": graph.wire()}
        assert apply(stale, repaired)["rlv2"]["current"]["map"]["zones"] == {"1": graph.wire()}
        assert rows(runtime.database.path) == saved


def test_two_runtimes_finish_the_same_saved_map_without_advancing(draft_runtime):
    runtime, _ = draft_runtime
    save(runtime, replace(plan(), zone_id="zone_1"))
    other = Runtime(runtime.settings)
    def finish(service):
        with service.database.transaction() as session:
            finish_initial(Context(session, service.data, 1))
    try:
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(finish, (runtime, other)))
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueMapDraft).count() == 1
            assert session.query(m.RogueTopicRun).one().state == "MAP_READY"
            assert session.query(m.RogueMapDraft).one().activated_at is not None
    finally:
        other.database.close()


@pytest.mark.parametrize("damage", ["missing", "timestamp", "uncompleted-event", "wrong-zone"])
def test_active_map_corruption_is_rejected_before_startup_writes(draft_runtime, damage):
    runtime, token = draft_runtime
    save(runtime, replace(plan(), zone_id="zone_1"))
    with runtime.database.transaction() as session:
        finish_initial(Context(session, runtime.data, 1))
    with runtime.database.transaction() as session:
        draft = session.query(m.RogueMapDraft).one()
        if damage == "missing":
            session.delete(draft)
        elif damage == "timestamp":
            draft.activated_at += 1
        elif damage == "uncompleted-event":
            session.query(m.RogueRunEvent).filter_by(ordinal=2).one().completed_at = None
        else:
            value = copy.deepcopy(draft.plan)
            value["zone_id"] = "floor"
            draft.plan = value
    runtime.database.close()
    before = rows(runtime.database.path)
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def downgrade_0021(runtime):
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        for name in ("rlv2_run_closures", "rlv2_floor_cursors", "rlv2_shop_visits", "rlv2_scene_visits",
                     "rlv2_game_settlements", "rlv2_battle_settlements", "rlv2_battles"):
            con.execute('DROP TABLE "' + name + '"')
        con.execute("ALTER TABLE rlv2_map_drafts DROP COLUMN activated_at")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_MAP_REVISION,))


def test_0021_parent_rebuild_keeps_children_indexes_and_foreign_key_guard(draft_runtime):
    runtime, token = draft_runtime
    save(runtime)
    before_state = current(runtime, token)
    downgrade_0021(runtime)
    before = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        after = rows(reopened.database.path)
        assert all(after[k] == v for k, v in before.items() if k not in ("alembic_version", "rlv2_map_drafts"))
        assert [r[:-1] for r in after["rlv2_map_drafts"]] == before["rlv2_map_drafts"]
        assert after["alembic_version"] == [(REVISION,)]
        assert current(reopened, token) == before_state
        with reopened.database.engine.connect() as con:
            assert con.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert con.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert con.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE name='uq_rlv2_active_run'").scalar_one() == 1
    finally:
        reopened.database.close()


def test_failed_0021_parent_rebuild_rolls_back_schema_children_and_version(draft_runtime, monkeypatch):
    runtime, _ = draft_runtime
    save(runtime)
    downgrade_0021(runtime)
    before = rows(runtime.database.path)
    from terralocal.server.persistence import migrations
    original = migrations._map_activation
    def fail(*args):
        original(*args)
        raise RuntimeError("injected parent-rebuild failure")
    monkeypatch.setattr(migrations, "_map_activation", fail)
    database = Database(runtime.database.path)
    try:
        with pytest.raises(RuntimeError, match="parent-rebuild"):
            database.initialize()
        assert rows(database.path) == before
        with database.engine.connect() as con:
            assert con.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    finally:
        database.close()
