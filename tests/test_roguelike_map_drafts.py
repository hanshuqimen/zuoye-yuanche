"""Draft storage counterexamples; explicit authored plans are not official floors."""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest
from fastapi.testclient import TestClient
from test_roguelike_initial import current, post
from test_roguelike_map import authored_placements, plan
from test_roguelike_map import tables as map_tables
from test_roguelike_recruit import prepare as initial_recruit
from test_roguelike_recruit import recruit_tables
from test_roguelike_state import rows

from terralocal.config import Settings
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import LEGACY_POLICY, admit_plan, generate, plan_fingerprint
from terralocal.server.domain.rogue_map_drafts import prepare, read
from terralocal.server.domain.rogue_runs import abandon, create
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import REVISION, ROGUE_RECRUIT_REVISION
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def draft_runtime(tmp_path):
    tables = recruit_tables()
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    maps = map_tables()["roguelike_topic_table"]["details"]["rogue_1"]
    for section in ("stages", "zones", "nodeTypeData", "gameConst"):
        detail[section] = maps[section]
    detail["zones"]["zone_1"] = {"id": "zone_1", "isHiddenZone": False}
    authored_placements(tables)
    source = tmp_path / "source"
    source.mkdir()
    for key, value in tables.items():
        (source / (key + ".json")).write_text(json.dumps(value), "utf8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        create_account(session, runtime.data, "MapDoctor")
        create_account(session, runtime.data, "OtherDoctor")
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=1, clear_count=1,
                                    first_clear_claimed=True, unlocked=True))
        token = login(session, settings, name="MapDoctor")["secret"]
    with TestClient(create_game_app(runtime)) as client:
        initial_recruit(client, token)
        for index in range(3):
            payload = {"id": str(index)}
            assert post(client, token, "activeRecruitTicket", payload, "active" + str(index)).status_code == 200
            assert post(client, token, "closeRecruitTicket", payload, "close" + str(index)).status_code == 200
    yield runtime, token
    runtime.database.close()


def save(runtime, spec=None):
    with runtime.database.transaction() as session:
        return prepare(Context(session, runtime.data, 1), spec or plan())


def test_saved_draft_survives_restart_backup_and_is_not_client_activation(draft_runtime):
    runtime, token = draft_runtime
    before = current(runtime, token)
    graph = save(runtime)
    assert current(runtime, token) == before
    assert before["player"]["state"] == "INIT" and before["map"]["zones"] == {}
    saved = rows(runtime.database.path)
    assert save(runtime) == graph and rows(runtime.database.path) == saved
    with runtime.database.transaction(write=False) as session:
        assert read(Context(session, runtime.data, 1)) == graph
        with pytest.raises(DomainError, match="当前没有进行中的探索"):
            read(Context(session, runtime.data, 2))
    reopened = Runtime(runtime.settings)
    try:
        assert current(reopened, token) == before
        with reopened.database.transaction(write=False) as session:
            assert read(Context(session, reopened.data, 1)) == graph
        assert rows(reopened.database.path) == saved
        backup = BackupService(reopened).create()
        BackupService(reopened).restore(backup["name"])
        assert rows(reopened.database.path) == saved
    finally:
        reopened.database.close()
    # There is still no success route that pretends a prepared graph is entered.
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "finish").status_code == 501


def test_conflicting_plan_and_outer_rollback_never_replace_a_saved_map(draft_runtime):
    runtime, _ = draft_runtime
    before = rows(runtime.database.path)
    with pytest.raises(RuntimeError, match="injected crash"):
        with runtime.database.transaction() as session:
            prepare(Context(session, runtime.data, 1), plan())
            raise RuntimeError("injected crash before commit")
    assert rows(runtime.database.path) == before
    save(runtime)
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError) as conflict:
        save(runtime, replace(plan(), extra_edge_chance=1))
    assert conflict.value.code == "ROGUE_MAP_DRAFT_CONFLICT" and rows(runtime.database.path) == saved


def test_two_runtimes_serialize_same_plan_without_duplicate_or_reroll(draft_runtime):
    runtime, _ = draft_runtime
    other = Runtime(runtime.settings)
    try:
        with ThreadPoolExecutor(2) as pool:
            graphs = list(pool.map(save, (runtime, other)))
        assert graphs[0] == graphs[1]
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueMapDraft).count() == 1
    finally:
        other.database.close()


def test_unresolved_ticket_blocks_preparation_without_writing(draft_runtime):
    runtime, _ = draft_runtime
    with runtime.database.transaction() as session:
        session.query(m.RogueRunTicket).filter_by(ordinal=2).one().state = "ACTIVE"
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as exc:
        save(runtime)
    assert exc.value.code == "ROGUE_MAP_DRAFT_NOT_READY"
    assert rows(runtime.database.path) == before


def test_abandoned_draft_is_retained_but_never_shared_with_a_new_run(draft_runtime):
    runtime, _ = draft_runtime
    graph = save(runtime)
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        abandon(ctx)
        session.get(m.ServerClockState, 1).fixed_at += 60
        ctx = Context(session, runtime.data, 1)
        create(ctx, "rogue_1", "NORMAL", 0, None, None)
        assert read(ctx) is None
        assert session.query(m.RogueMapDraft).one().graph == graph.wire()
    reopened = Runtime(runtime.settings)
    try:
        with reopened.database.transaction(write=False) as session:
            assert read(Context(session, reopened.data, 1)) is None
            assert session.query(m.RogueMapDraft).count() == 1
    finally:
        reopened.database.close()


@pytest.mark.parametrize("damage", ["policy", "data-hash", "plan-hash", "plan-pool", "wrong-seed", "graph-stage",
                                    "future-json", "timestamp", "unresolved-ticket", "orphan"])
def test_startup_refuses_corruption_before_writing_or_regenerating(draft_runtime, damage):
    runtime, _ = draft_runtime
    save(runtime)
    with runtime.database.transaction() as session:
        row = session.query(m.RogueMapDraft).one()
        if damage == "policy":
            row.policy_version = "future-policy"
        elif damage == "data-hash":
            row.gamedata_hash = "0" * 64
        elif damage == "plan-hash":
            row.plan_hash = "0" * 64
        elif damage == "plan-pool":
            value = copy.deepcopy(row.plan)
            del value["columns"][0]["pool"][0]["weight"]
            row.plan = value
        elif damage == "wrong-seed":
            run = session.query(m.RogueTopicRun).one()
            run.seed = 0 if run.seed else 1
        elif damage == "graph-stage":
            value = copy.deepcopy(row.graph)
            value["nodes"]["0"]["stage"] = "missing"
            row.graph = value
        elif damage == "future-json":
            row.plan = row.plan | {"new_rule": True}
        elif damage == "timestamp":
            row.prepared_at = 0
        elif damage == "unresolved-ticket":
            session.query(m.RogueRunTicket).first().state = "ACTIVE"
    runtime.database.close()
    if damage == "orphan":
        with sqlite3.connect(runtime.database.path) as con:
            con.execute("UPDATE rlv2_map_drafts SET run_id='missing'")
    before = rows(runtime.database.path)
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def test_0020_upgrade_keeps_every_old_row_and_migration_rollback(draft_runtime, monkeypatch):
    runtime, token = draft_runtime
    state = current(runtime, token)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TABLE rlv2_battle_settlements")
        con.execute("DROP TABLE rlv2_battles")
        con.execute("DROP TABLE rlv2_map_drafts")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_RECRUIT_REVISION,))
    old = rows(runtime.database.path)
    original = m.RogueMapDraft.__table__.create

    def fail_after_create(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected migration crash")

    monkeypatch.setattr(m.RogueMapDraft.__table__, "create", fail_after_create)
    db = Database(runtime.database.path)
    try:
        with pytest.raises(RuntimeError, match="injected migration crash"):
            db.initialize()
    finally:
        db.close()
    assert rows(runtime.database.path) == old
    monkeypatch.setattr(m.RogueMapDraft.__table__, "create", original)
    reopened = Runtime(runtime.settings)
    try:
        after = rows(runtime.database.path)
        assert {k: v for k, v in after.items() if k not in ("alembic_version", "rlv2_map_drafts", "rlv2_battles", "rlv2_battle_settlements")} == {
            k: v for k, v in old.items() if k != "alembic_version"}
        assert after["alembic_version"] == [(REVISION,)] and after["rlv2_map_drafts"] == []
        assert current(reopened, token) == state
    finally:
        reopened.database.close()


def test_new_schema_missing_draft_table_is_not_repaired_silently(draft_runtime):
    runtime, _ = draft_runtime
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TABLE rlv2_map_drafts")
    before = rows(runtime.database.path)
    with pytest.raises(ValueError, match="地图准备记录"):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before


def test_invalid_candidate_backup_is_rejected_before_touching_current_save(draft_runtime):
    runtime, _ = draft_runtime
    save(runtime)
    service = BackupService(runtime)
    backup = service.create()
    path = service.directory / backup["name"]
    with sqlite3.connect(path) as con:
        con.execute("UPDATE rlv2_map_drafts SET plan_hash=?", ("0" * 64,))
    metadata = path.with_suffix(".json")
    info = json.loads(metadata.read_bytes())
    info["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(info), "utf8")
    before = rows(runtime.database.path)
    with pytest.raises(ValueError, match="地图准备记录"):
        service.restore(backup["name"])
    assert rows(runtime.database.path) == before
    assert not list(service.directory.glob("before-restore-*"))


def test_legacy_100_key_draft_is_read_without_rewriting_or_rerolling(draft_runtime):
    runtime, _ = draft_runtime
    save(runtime)
    with runtime.database.transaction() as session:
        row = session.query(m.RogueMapDraft).one()
        old = generate(runtime.data, plan(), row.seed, policy=LEGACY_POLICY)
        row.policy_version, row.plan_hash = LEGACY_POLICY, plan_fingerprint(plan(), policy=LEGACY_POLICY)
        row.graph = old.wire(legacy_keys=True)
    before = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert save(reopened) == old
        with reopened.database.transaction(write=False) as session:
            assert read(Context(session, reopened.data, 1)).wire() == old.wire()
        assert rows(runtime.database.path) == before
    finally:
        reopened.database.close()


@pytest.mark.parametrize("change", ["missing-weight", "boolean-width", "unknown-plan-field", "oversize-pool"])
def test_saved_recipe_cannot_drop_unknown_rules_or_default_bad_values(draft_runtime, change):
    runtime, _ = draft_runtime
    value = json.loads(json.dumps(asdict(plan())))
    if change == "missing-weight":
        del value["columns"][0]["pool"][0]["weight"]
    elif change == "boolean-width":
        value["columns"][0]["minimum"] = True
    elif change == "unknown-plan-field":
        value["unknown"] = 1
    else:
        value["columns"][0]["pool"] *= 200
    with pytest.raises(ValueError):
        admit_plan(runtime.data.rogue_map, value)
