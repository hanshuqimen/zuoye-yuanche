"""Synthetic preference/sync transactions, not native exploration acceptance."""

import copy
import hashlib
import json
import sqlite3
from contextlib import closing

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from test_roguelike_topics import topic_table

from terralocal.config import Settings
from terralocal.server.compatibility.profile import ROGUE_CLIENT_PROFILE, native_profile
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.rogue_topics import pin, preflight, snapshot
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import REVISION, WEEK_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.roguelike_state import no_run
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def rows(path):
    with closing(sqlite3.connect(path)) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {name: conn.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall() for name in tables}


@pytest.fixture
def rogue_runtime(tmp_path):
    table = topic_table()
    for name in ("topics", "details", "modules", "customizeData"):
        table[name]["future"] = copy.deepcopy(table[name]["topic"])
    table["topics"]["future"].update(id="future", startTime=1_900_000_000)
    source = tmp_path / "source"
    source.mkdir()
    for name, value in (miniature() | {"roguelike_topic_table": table}).items():
        (source / (name + ".json")).write_text(json.dumps(value), "utf8")
    manifest = import_data(source, tmp_path / "data" / "cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        state = session.get(m.ServerClockState, 1)
        state.mode, state.fixed_at = "fixed", 1_800_000_000
        create_account(session, runtime.data, "RogueDoctor")
    yield runtime
    runtime.database.close()


@pytest.fixture
def rogue_token(rogue_runtime):
    with rogue_runtime.database.transaction() as session:
        return login(session, rogue_runtime.settings, name="RogueDoctor")["secret"]


def test_no_run_is_object_and_profiles_grant_no_history_or_collections(rogue_runtime, rogue_token):
    state = rogue_runtime.sync(rogue_token)["user"]["rlv2"]
    assert state["current"] == no_run() and isinstance(state["current"], dict)
    assert state["pinned"] is None
    assert set(state["outer"]) == {"topic", "future"}
    for outer in state["outer"].values():
        assert outer["bp"] == {"point": 0, "reward": {}}
        assert outer["collect"]["band"] == outer["collect"]["mode"] == {}
        assert outer["record"]["history"] == []
    before = rows(rogue_runtime.database.path)
    with rogue_runtime.database.transaction(write=False) as session:
        assert snapshot(Context(session, rogue_runtime.data, 1)) == state
        assert snapshot(Context(session, rogue_runtime.data, 1)) == state
    assert rows(rogue_runtime.database.path) == before


def test_native_pin_delta_retry_conflict_clear_and_account_isolation(rogue_runtime, rogue_token):
    with rogue_runtime.database.transaction() as session:
        other = create_account(session, rogue_runtime.data, "OtherDoctor")
        other_id = other.id
    before = rogue_runtime.sync(rogue_token)["user"]
    with TestClient(create_game_app(rogue_runtime)) as client:
        headers = {"secret": rogue_token, "seqnum": "pin1"}
        response = client.post("/rlv2/setPinned", json={"id": "topic"}, headers=headers)
        assert response.status_code == 200
        result = response.json()
        assert result["playerDataDelta"]["modified"]["rlv2"] == {"pinned": "topic"}
        assert apply(before, result["playerDataDelta"]) == rogue_runtime.sync(rogue_token)["user"]
        saved = rows(rogue_runtime.database.path)
        assert client.post("/rlv2/setPinned", json={"id": "topic"}, headers=headers).json() == result
        assert rows(rogue_runtime.database.path) == saved
        assert client.post("/rlv2/setPinned", json={"id": None}, headers=headers).status_code == 409
        assert rows(rogue_runtime.database.path) == saved
        assert client.post("/rlv2/setPinned", json={"id": None},
                           headers={"secret": rogue_token, "seqnum": "clear"}).status_code == 200
    assert rogue_runtime.sync(rogue_token)["user"]["rlv2"]["pinned"] is None
    with rogue_runtime.database.transaction(write=False) as session:
        assert snapshot(Context(session, rogue_runtime.data, other_id))["pinned"] is None


@pytest.mark.parametrize("topic,code", [("missing", "ROGUE_UNKNOWN_TOPIC"),
                                       ("future", "ROGUE_TOPIC_NOT_STARTED")])
def test_invalid_or_future_pin_rolls_back_every_table(rogue_runtime, rogue_token, topic, code):
    before = rows(rogue_runtime.database.path)
    with TestClient(create_game_app(rogue_runtime)) as client:
        response = client.post("/rlv2/setPinned", json={"id": topic},
                               headers={"secret": rogue_token, "seqnum": "invalid"})
    assert response.status_code == 400 and response.json()["error"]["code"] == code
    assert rows(rogue_runtime.database.path) == before


def test_strict_requests_and_unimplemented_create_cannot_grant_progress(rogue_runtime, rogue_token):
    before = rows(rogue_runtime.database.path)
    with TestClient(create_game_app(rogue_runtime)) as client:
        headers = {"secret": rogue_token, "seqnum": "bad"}
        for value in [{}, {"id": 1}, {"id": True}, {"id": "topic", "unlockAll": True}]:
            assert client.post("/rlv2/setPinned", json=value, headers=headers).status_code == 422
        assert client.post("/rlv2/setPinned", json={"id": "topic"}, headers={"seqnum": "auth"}).status_code == 401
        result = client.post("/rlv2/finishEvent", json={"id": "0"}, headers=headers)
        assert result.status_code == 422  # Frozen FinishEvent has no request members.
        result = client.post("/rlv2/finishEvent", json={}, headers=headers)
        assert result.status_code == 409 and result.json()["error"]["code"] == "ROGUE_NO_RUN"
    assert rows(rogue_runtime.database.path) == before


def test_pin_persists_through_restart_and_backup_restore(rogue_runtime, rogue_token):
    runtime = rogue_runtime
    runtime.mutate(rogue_token, None, "set", "pin", {},
                   lambda ctx: pin(ctx, "topic"))
    service = BackupService(runtime)
    backup = service.create("manual")
    runtime.mutate(rogue_token, None, "clear", "clear", {},
                   lambda ctx: pin(ctx, None))
    service.restore(backup["name"])
    expected = runtime.sync(rogue_token)
    assert expected["user"]["rlv2"]["pinned"] == "topic"
    before = rows(runtime.database.path)
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(rogue_token) == expected
        assert rows(reopened.database.path) == before
    finally:
        reopened.database.close()


@pytest.mark.parametrize("corruption", ["policy", "topic", "missing", "negative", "missing-field", "unknown-grade"])
def test_startup_rejects_incompatible_saved_state_before_writes(rogue_runtime, corruption):
    runtime = rogue_runtime
    with runtime.database.transaction() as session:
        if corruption == "policy":
            session.get(m.RogueTopicAccount, 1).policy_version = "unknown"
        elif corruption == "topic":
            session.get(m.RogueTopicAccount, 1).pinned = "missing"
        elif corruption == "missing":
            session.delete(session.get(m.RogueTopicOuter, (1, "topic")))
        else:
            row = session.get(m.RogueTopicOuter, (1, "topic"))
            value = copy.deepcopy(row.state)
            if corruption == "negative":
                value["bp"]["point"] = -1
            elif corruption == "unknown-grade":
                value["collect"]["modeGrade"] = {"NORMAL": {"0": {"state": 3}}}
            else:
                value.pop("bank")
            row.state = value
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="集成战略存档"):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def test_0017_migration_adds_empty_entities_without_changing_other_rows(rogue_runtime):
    runtime = rogue_runtime
    runtime.database.close()
    with closing(sqlite3.connect(runtime.database.path)) as conn:
        # Schema0017 predates every modern rlv2 entity, not just the profile.
        for table in reversed(m.Base.metadata.sorted_tables):
            if table.name.startswith("rlv2_"):
                conn.execute('DROP TABLE "' + table.name + '"')
        conn.execute("UPDATE alembic_version SET version_num=?", (WEEK_REVISION,))
        conn.commit()
    before = rows(runtime.database.path)
    database = Database(runtime.database.path)
    try:
        database.initialize()
        after = rows(database.path)
        assert after["rlv2_accounts"] == after["rlv2_topics"] == []
        assert after["alembic_version"] == [(REVISION,)]
        assert all(after[name] == value for name, value in before.items() if name != "alembic_version")
    finally:
        database.close()


def test_0017_failed_migration_rolls_back_both_tables_and_version(rogue_runtime, monkeypatch):
    runtime = rogue_runtime
    runtime.database.close()
    with closing(sqlite3.connect(runtime.database.path)) as conn:
        # Schema0017 predates every modern rlv2 entity, not just the profile.
        for table in reversed(m.Base.metadata.sorted_tables):
            if table.name.startswith("rlv2_"):
                conn.execute('DROP TABLE "' + table.name + '"')
        conn.execute("UPDATE alembic_version SET version_num=?", (WEEK_REVISION,))
        conn.commit()
    before = rows(runtime.database.path)
    def fail(*args, **kwargs):
        raise RuntimeError("injected topic migration failure")
    monkeypatch.setattr(m.RogueTopicOuter.__table__, "create", fail)
    database = Database(runtime.database.path)
    try:
        with pytest.raises(RuntimeError, match="injected topic migration"):
            database.initialize()
        assert rows(database.path) == before
    finally:
        database.close()


def test_corrupt_candidate_backup_cannot_replace_active_save(rogue_runtime, rogue_token):
    runtime = rogue_runtime
    service = BackupService(runtime)
    backup = service.create("manual")
    path = service.directory / backup["name"]
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("DELETE FROM rlv2_topics WHERE topic_id='topic'")
        conn.commit()
    metadata = path.with_suffix(".json")
    info = json.loads(metadata.read_bytes())
    info["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(info), "utf8")
    before = rows(runtime.database.path)
    names = {item["name"] for item in service.list()}
    with pytest.raises(ValueError, match="集成战略存档"):
        service.restore(backup["name"])
    assert rows(runtime.database.path) == before
    assert {item["name"] for item in service.list()} == names


def test_removing_modern_table_cannot_silently_hide_existing_topic_progress(rogue_runtime, tmp_path):
    runtime = rogue_runtime
    source = tmp_path / "base-source"
    source.mkdir()
    for name, value in miniature().items():
        (source / (name + ".json")).write_text(json.dumps(value), "utf8")
    base = import_data(source, runtime.settings.data_dir / "cache")
    settings = runtime.settings.model_copy(update={"gamedata_hash": base["hash"]})
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="集成战略存档"):
        Runtime(settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def test_frozen_rogue_profile_rejects_other_data_before_opening_save(rogue_runtime):
    runtime = rogue_runtime
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    settings = runtime.settings.model_copy(update={"client_profile": ROGUE_CLIENT_PROFILE})
    with pytest.raises(ValueError, match="已冻结的现代主题19表"):
        Runtime(settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest
    assert native_profile(ROGUE_CLIENT_PROFILE) == "cn-android-2.7.71-display"


def test_frozen_qa_preflight_refuses_to_rebind_old_accounts(rogue_runtime):
    runtime = rogue_runtime
    with runtime.database.transaction() as session:
        session.delete(session.get(m.RogueTopicAccount, 1))
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="不能自动转换已有账号"):
        preflight(runtime.data, runtime.database.path, require_existing_binding=True)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest
