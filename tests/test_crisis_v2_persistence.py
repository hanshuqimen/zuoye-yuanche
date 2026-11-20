"""Atomic 0037 upgrades and backup recovery on isolated synthetic saves."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from crisis_v2_qa import VERSION, create, tables
from schema_legacy import remove_crisis_v2_tables

from terralocal.server.domain import crisis_v2
from terralocal.server.gamedata import import_data
from terralocal.server.persistence import migrations
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.services.backups import backup_existing_save, recover_backup
from terralocal.server.services.runtime import Runtime


def rows(path):
    with sqlite3.connect(path) as connection:
        names = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: connection.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall() for name in names}


@pytest.mark.parametrize("rollback", [False, True])
def test_0037_additive_upgrade_preserves_every_old_row(runtime, monkeypatch, rollback):
    path = runtime.database.path
    runtime.database.close()
    with sqlite3.connect(path) as connection:
        remove_crisis_v2_tables(connection)
        connection.execute("UPDATE alembic_version SET version_num=?", (migrations.ROGUE_LOOT_REVISION,))
    before = rows(path)
    if rollback:
        original = migrations._crisis_v2_tables

        def fail(connection):
            original(connection)
            raise ValueError("Authored failure after creating all Crisis V2 tables")

        monkeypatch.setattr(migrations, "_crisis_v2_tables", fail)
        with closing(Database(path)) as database:
            with pytest.raises(ValueError, match="Authored failure"):
                database.initialize()
        assert rows(path) == before
        monkeypatch.setattr(migrations, "_crisis_v2_tables", original)
    with closing(Database(path)) as database:
        database.initialize()
    after = rows(path)
    assert set(after) - set(before) == {
        "crisis_v2_accounts", "crisis_v2_seasons", "crisis_v2_maps", "crisis_v2_battles"}
    for name, values in before.items():
        assert after[name] == ([(migrations.REVISION,)] if name == "alembic_version" else values)
    assert after["crisis_v2_accounts"] == after["crisis_v2_seasons"] == after["crisis_v2_maps"] == after["crisis_v2_battles"] == []


def test_information_retry_is_atomic_under_concurrency(tmp_path):
    runtime, token = create(tmp_path)
    try:
        before = runtime.sync(token)["revision"]
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: runtime.mutate(
                token, None, "1", "crisis-v2-get-info", {}, crisis_v2.get_info), range(6)))
        assert all(result == results[0] for result in results)
        assert runtime.sync(token)["revision"] == before + 1
        with runtime.database.transaction() as session:
            assert session.query(m.CrisisV2Account).count() == 1
            assert session.query(m.CrisisV2Season).count() == 1
            assert session.query(m.CrisisV2MapProgress).count() == 2
            assert session.query(m.Receipt).count() == 1
    finally:
        runtime.database.close()


def test_crisis_progress_survives_backup_and_independent_recovery(tmp_path):
    runtime, _ = create(tmp_path)
    try:
        with runtime.database.transaction() as session:
            row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
            row.score_total, row.runes, row.cleared = [10, 0, 0, 0, 0, 0], {"rune": 3}, True
        before = rows(runtime.database.path)
        archive = backup_existing_save(runtime.settings)
        restored = tmp_path / "recovered" / "independent.sqlite3"
        recover_backup(runtime.settings, archive["name"], restored)
        recovered = rows(restored)
        assert set(recovered) == set(before)
        for name in ("crisis_v2_accounts", "crisis_v2_seasons", "crisis_v2_maps", "currencies", "operators"):
            assert recovered[name] == before[name]
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_changed_information_source_fails_before_writable_startup(tmp_path, monkeypatch):
    runtime, _ = create(tmp_path / "original")
    try:
        new_source = tmp_path / "new-source"
        new_source.mkdir()
        for name, value in tables(second_info=True).items():
            (new_source / (name + ".json")).write_text(json.dumps(value), encoding="utf8")
        (new_source / "data_version.txt").write_text(VERSION, encoding="utf8")
        manifest = import_data(new_source, runtime.settings.data_dir / "cache")
        settings = runtime.settings.model_copy(update={"gamedata_hash": manifest["hash"]})
        before = rows(runtime.database.path)
        touched = []
        original = Database.initialize

        def initialize(database):
            touched.append(True)
            return original(database)

        monkeypatch.setattr(Database, "initialize", initialize)
        with pytest.raises(ValueError, match="绑定了其他"):
            Runtime(settings)
        assert touched == [] and rows(runtime.database.path) == before
    finally:
        runtime.database.close()


@pytest.mark.parametrize("missing", [
    ("crisis_v2_battles",),
    ("crisis_v2_accounts",), ("crisis_v2_seasons",), ("crisis_v2_maps",),
    ("crisis_v2_maps", "crisis_v2_seasons", "crisis_v2_accounts"),
])
def test_incomplete_current_schema_fails_without_writable_startup(tmp_path, monkeypatch, missing):
    runtime, _ = create(tmp_path)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        for name in missing:
            connection.execute('DROP TABLE "' + name + '"')
    before = rows(runtime.database.path)
    raw_before = runtime.database.path.read_bytes()
    touched = []
    original = Database.initialize

    def initialize(database):
        touched.append(True)
        return original(database)

    monkeypatch.setattr(Database, "initialize", initialize)
    with pytest.raises(ValueError, match="存档表不完整"):
        Runtime(runtime.settings)
    assert touched == []
    assert runtime.database.path.read_bytes() == raw_before
    assert rows(runtime.database.path) == before
