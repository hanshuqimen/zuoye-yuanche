"""Restore failures must preserve authoritative state and leave the server usable."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event

import pytest

from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import REVISION, ROGUE_BANK_AWARDS_REVISION
from terralocal.server.services import backups
from terralocal.server.services.backups import BackupService, recover_backup, restore_existing_save
from terralocal.server.services.runtime import Runtime


def prepare_restore(runtime, token):
    service = BackupService(runtime)
    saved = service.create()
    with runtime.database.transaction() as session:
        session.get(m.Currency, (1, "4001")).balance = 777
        session.get(m.PlayerProfile, 1).nickname = "Progress after backup"
    return service, saved, runtime.sync(token)


def assert_preserved_and_writable(runtime, token, expected):
    assert runtime.sync(token) == expected
    assert not list(runtime.database.path.parent.glob(".restore-*"))
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == expected
        with restarted.database.transaction() as session:
            session.get(m.Currency, (1, "4001")).balance += 1
        assert restarted.sync(token)["user"]["status"]["gold"] == 778
    finally:
        restarted.database.close()


def test_archived_database_is_standalone_and_does_not_change_live_wal(runtime, token):
    service, saved, before = prepare_restore(runtime, token)
    path = service.directory / saved["name"]
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        connection.execute("UPDATE currencies SET balance=666 WHERE item_id='4001'")
        connection.commit()
        # Inspect a copy while the editor is still open: all committed rows
        # must be in the one archived file, with no WAL dependency.
        copied = path.parent / "standalone.sqlite3"
        copied.write_bytes(path.read_bytes())
        with closing(sqlite3.connect(copied)) as reader:
            assert reader.execute("SELECT balance FROM currencies WHERE item_id='4001'").fetchone() == (666,)
    with closing(sqlite3.connect(runtime.database.path)) as live:
        assert live.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    assert runtime.sync(token) == before


@pytest.mark.parametrize("entry", ["online", "in-place", "output"])
@pytest.mark.parametrize("journal", ["wal", "rollback"])
def test_unarchived_sqlite_journal_never_reaches_restore(runtime, token, tmp_path, entry, journal):
    service, saved, before = prepare_restore(runtime, token)
    path = service.directory / saved["name"]
    metadata = path.with_suffix(".json")
    output = tmp_path / "restored.sqlite3"
    with closing(sqlite3.connect(path)) as writer:
        if journal == "wal":
            assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("UPDATE currencies SET balance=666 WHERE item_id='4001'")
        if journal == "wal":
            writer.commit()
        suffix = "-wal" if journal == "wal" else "-journal"
        assert path.with_name(path.name + suffix).stat().st_size > 0
        info = json.loads(metadata.read_text("utf8"))
        info["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        metadata.write_text(json.dumps(info), "utf8")
        original = path.read_bytes(), metadata.read_bytes()
        assert service.list() == []
        with pytest.raises(ValueError, match="SQLite 日志"):
            if entry == "online":
                service.restore(saved["name"])
            elif entry == "in-place":
                restore_existing_save(runtime.settings, saved["name"])
            else:
                recover_backup(runtime.settings, saved["name"], output)
        assert not output.exists()
        assert not list(service.directory.glob("before-restore-*"))
        assert original == (path.read_bytes(), metadata.read_bytes())
        assert runtime.sync(token) == before
        writer.rollback()


def test_legacy_wal_archive_without_pending_frames_can_still_restore(runtime, token):
    service, saved, _ = prepare_restore(runtime, token)
    path = service.directory / saved["name"]
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    assert not path.with_name(path.name + "-wal").exists()
    metadata = path.with_suffix(".json")
    info = json.loads(metadata.read_text("utf8"))
    info["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(info), "utf8")
    original = path.read_bytes()
    service.restore(saved["name"])
    assert runtime.sync(token)["user"]["status"]["gold"] == 1000
    assert path.read_bytes() == original


@pytest.mark.parametrize("entry", ["online", "in-place", "output"])
def test_snapshot_journal_appearing_during_copy_never_activates(runtime, token, tmp_path, monkeypatch, entry):
    service, saved, before = prepare_restore(runtime, token)
    path = service.directory / saved["name"]
    output = tmp_path / "restored.sqlite3"
    original_copy = backups.shutil.copyfile
    writer = None

    def copy_then_commit(source, destination):
        nonlocal writer
        result = original_copy(source, destination)
        if source == path:
            writer = sqlite3.connect(path)
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("UPDATE currencies SET balance=666 WHERE item_id='4001'")
            writer.commit()
        return result

    monkeypatch.setattr(backups.shutil, "copyfile", copy_then_commit)
    try:
        with pytest.raises(ValueError, match="SQLite 日志"):
            if entry == "online":
                service.restore(saved["name"])
            elif entry == "in-place":
                restore_existing_save(runtime.settings, saved["name"])
            else:
                recover_backup(runtime.settings, saved["name"], output)
        assert writer is not None
        assert not output.exists()
        assert not list(service.directory.glob("before-restore-*"))
        assert runtime.sync(token) == before
    finally:
        if writer is not None:
            writer.close()


def test_candidate_migration_failure_never_replaces_active_save(runtime, token, monkeypatch):
    service, saved, before = prepare_restore(runtime, token)
    initialize = Database.initialize

    def fail_after_migration(database):
        initialize(database)
        if database.path != runtime.database.path:
            raise RuntimeError("candidate migration failure")

    monkeypatch.setattr(Database, "initialize", fail_after_migration)
    with pytest.raises(RuntimeError, match="candidate migration failure"):
        service.restore(saved["name"])
    assert len(service.list()) == 1  # No activation or before-restore snapshot.
    assert_preserved_and_writable(runtime, token, before)


def test_post_activation_initialize_failure_restores_previous_state(runtime, token, monkeypatch):
    service, saved, before = prepare_restore(runtime, token)

    def fail():
        raise RuntimeError("active initialization failure")

    monkeypatch.setattr(runtime.database, "initialize", fail)
    with pytest.raises(RuntimeError, match="active initialization failure"):
        service.restore(saved["name"])
    previous = [item for item in service.list() if item["name"].startswith("before-restore-")]
    assert len(previous) == 1
    with closing(sqlite3.connect(service.directory / previous[0]["name"])) as connection:
        assert connection.execute("SELECT balance FROM currencies WHERE item_id='4001'").fetchone()[0] == 777
    assert_preserved_and_writable(runtime, token, before)


def test_copy_error_after_destination_commit_automatically_rolls_back(runtime, token, monkeypatch):
    service, saved, before = prepare_restore(runtime, token)
    copy = backups._copy_database

    def fail_after_copy(source, target):
        copy(source, target)
        if source.name == "candidate.sqlite3" and target == runtime.database.path:
            raise OSError("activation copy failed after commit")

    monkeypatch.setattr(backups, "_copy_database", fail_after_copy)
    with pytest.raises(OSError, match="activation copy failed"):
        service.restore(saved["name"])
    assert_preserved_and_writable(runtime, token, before)


@pytest.mark.parametrize("fault, message", [
    ("table", "必要数据表"), ("column", "必要字段"),
    ("foreign-key", "实体引用"), ("revision", "数据库版本")])
def test_invalid_migrated_candidate_never_activates(runtime, token, monkeypatch, fault, message):
    service, saved, before = prepare_restore(runtime, token)
    initialize = Database.initialize

    def damage_candidate(database):
        initialize(database)
        if database.path == runtime.database.path:
            return
        database.close()
        with closing(sqlite3.connect(database.path)) as connection:
            if fault == "table":
                connection.execute("DROP TABLE receipts")
            elif fault == "column":
                connection.execute("ALTER TABLE player_profiles DROP COLUMN nickname")
            elif fault == "foreign-key":
                connection.execute("INSERT INTO currencies(account_id,item_id,balance) VALUES (999,'4001',10)")
            else:
                connection.execute("UPDATE alembic_version SET version_num='future-schema'")
            connection.commit()

    monkeypatch.setattr(Database, "initialize", damage_candidate)
    with pytest.raises(ValueError, match=message):
        service.restore(saved["name"])
    assert_preserved_and_writable(runtime, token, before)


@pytest.mark.parametrize("fail", [False, True])
def test_concurrent_write_waits_for_activation_or_rollback(runtime, token, monkeypatch, fail):
    service, saved, before = prepare_restore(runtime, token)
    entered, release, writer_ready = Event(), Event(), Event()
    initialize = runtime.database.initialize

    def pause_activation():
        entered.set()
        assert release.wait(10)
        if fail:
            raise RuntimeError("activation failure")
        initialize()

    def write():
        writer_ready.set()
        return runtime.mutate(token, None, "write-after-restore", "grant", {},
                              lambda ctx: (ctx.change_item("4001", 10) or {}))

    monkeypatch.setattr(runtime.database, "initialize", pause_activation)
    with ThreadPoolExecutor(max_workers=2) as pool:
        restoring = pool.submit(service.restore, saved["name"])
        try:
            assert entered.wait(10)
            writing = pool.submit(write)
            assert writer_ready.wait(10)
            assert not writing.done()
        finally:
            release.set()
        if fail:
            with pytest.raises(RuntimeError, match="activation failure"):
                restoring.result(timeout=10)
        else:
            restoring.result(timeout=10)
        writing.result(timeout=10)
    state = runtime.sync(token)["user"]["status"]
    assert state["gold"] == (before["user"]["status"]["gold"] if fail else 1000) + 10
    assert not list(runtime.database.path.parent.glob(".restore-*"))


def test_successful_restore_preserves_old_snapshot_and_survives_restart(runtime, token):
    service = BackupService(runtime)
    expected = runtime.sync(token)
    saved = service.create()
    with runtime.database.transaction() as session:
        session.get(m.Currency, (1, "4001")).balance = 777
    outcome = service.restore(saved["name"])
    assert outcome["restored"] == saved["name"]
    assert outcome["previous"].startswith("before-restore-")
    assert runtime.sync(token) == expected
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == expected
    finally:
        restarted.database.close()
    assert not list(runtime.database.path.parent.glob(".restore-*"))
    assert not list(service.directory.glob("*.tmp"))


def test_sqlite_copy_accepts_paths_containing_uri_characters(tmp_path):
    folder = tmp_path / "data # percent% space"
    folder.mkdir()
    source, target = folder / "source.sqlite3", folder / "target.sqlite3"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE progress (value INTEGER)")
        connection.execute("INSERT INTO progress VALUES (32)")
        connection.commit()
    backups._copy_database(source, target)
    with closing(sqlite3.connect(target)) as connection:
        assert connection.execute("SELECT value FROM progress").fetchone()[0] == 32


def use_legacy_schema(connection):
    connection.execute("DROP TABLE rlv2_battle_loot_plans")
    connection.execute("UPDATE alembic_version SET version_num = ?", (ROGUE_BANK_AWARDS_REVISION,))
    connection.commit()


def saved_revision_and_gold(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        return connection.execute("SELECT version_num, balance FROM alembic_version, currencies "
                                  "WHERE item_id = '4001'").fetchone()


@pytest.mark.parametrize("valid", [False, True], ids=["bad-checksum", "valid-backup"])
def test_cli_restore_preserves_the_legacy_save_until_activation(runtime, token, tmp_path, valid):
    service, saved, _ = prepare_restore(runtime, token)
    runtime.database.close()
    active = runtime.database.path
    with closing(sqlite3.connect(active)) as connection:
        use_legacy_schema(connection)
    original = active.read_bytes()
    selected = service.directory / saved["name"]
    metadata = selected.with_suffix(".json")
    if not valid:
        metadata.write_text(json.dumps({**saved, "sha256": "0" * 64}), encoding="utf-8")
    backup_bytes, metadata_bytes = selected.read_bytes(), metadata.read_bytes()

    result = subprocess.run([sys.executable, "-m", "terralocal", "--data-dir", str(runtime.settings.data_dir),
                             "restore", saved["name"]], capture_output=True, encoding="utf-8", timeout=25)
    if valid:
        assert result.returncode == 0, result.stderr
        previous = service.directory / json.loads(result.stdout)["previous"]
        assert saved_revision_and_gold(active) == (REVISION, 1000)
        assert saved_revision_and_gold(previous) == (ROGUE_BANK_AWARDS_REVISION, 777)
        previous_index = json.loads(previous.with_suffix(".json").read_bytes())
        assert previous_index["database_revision"] == ROGUE_BANK_AWARDS_REVISION

        recovered = tmp_path / "recovered-previous.sqlite3"
        recover_backup(runtime.settings, previous.name, recovered)
        assert saved_revision_and_gold(recovered) == (REVISION, 777)
    else:
        assert result.returncode == 2 and "备份哈希" in result.stderr
        assert active.read_bytes() == original
        assert saved_revision_and_gold(active) == (ROGUE_BANK_AWARDS_REVISION, 777)
        assert not list(service.directory.glob("before-restore-*"))
    assert selected.read_bytes() == backup_bytes and metadata.read_bytes() == metadata_bytes
    assert not list(runtime.settings.data_dir.glob(".restore-*"))


def test_offline_activation_failure_rolls_back_the_legacy_save(runtime, token, monkeypatch):
    service, saved, _ = prepare_restore(runtime, token)
    runtime.database.close()
    with closing(sqlite3.connect(runtime.database.path)) as connection:
        use_legacy_schema(connection)
    copy = backups._copy_database

    def fail_after_commit(source, target):
        copy(source, target)
        if source.name == "candidate.sqlite3":
            raise OSError("activation copy failed after commit")

    monkeypatch.setattr(backups, "_copy_database", fail_after_commit)
    with pytest.raises(OSError, match="activation copy failed"):
        restore_existing_save(runtime.settings, saved["name"])
    assert saved_revision_and_gold(runtime.database.path) == (ROGUE_BANK_AWARDS_REVISION, 777)
    previous, = service.directory.glob("before-restore-*.sqlite3")
    assert saved_revision_and_gold(previous) == (ROGUE_BANK_AWARDS_REVISION, 777)


def test_offline_restore_into_a_missing_save_does_not_create_a_previous_snapshot(runtime):
    service = BackupService(runtime)
    saved = service.create()
    runtime.database.close()
    active = runtime.database.path
    archived = active.with_name("original.sqlite3")
    active.rename(archived)
    before = archived.read_bytes()
    journal = active.with_name(active.name + "-journal")
    journal.write_bytes(b"Synthetic journal evidence")

    with pytest.raises(ValueError, match="附属文件"):
        restore_existing_save(runtime.settings, saved["name"])
    assert not active.exists() and journal.read_bytes() == b"Synthetic journal evidence"

    journal.rename(journal.with_name("original.sqlite3-journal"))
    result = restore_existing_save(runtime.settings, saved["name"])
    assert result == {"restored": saved["name"], "previous": None}
    assert saved_revision_and_gold(active) == (REVISION, 1000)
    assert archived.read_bytes() == before
    assert not list(service.directory.glob("before-restore-*"))


def test_cli_recovers_old_backup_to_new_file_while_source_is_corrupt(runtime, tmp_path):
    settings = runtime.settings
    service = BackupService(runtime)
    runtime.database.close()
    with closing(sqlite3.connect(settings.database_path)) as connection:
        connection.execute("UPDATE player_profiles SET nickname = 'Saved before damage'")
        use_legacy_schema(connection)
    snapshot = service.create()
    assert snapshot["database_revision"] == ROGUE_BANK_AWARDS_REVISION
    settings.database_path.write_bytes(b"Synthetic corrupt database")
    journal = settings.database_path.with_name(settings.database_path.name + "-wal")
    journal.write_bytes(b"Synthetic journal evidence")
    inputs = {path: path.read_bytes() for path in (
        settings.database_path, journal, service.directory / snapshot["name"],
        (service.directory / snapshot["name"]).with_suffix(".json"))}
    recovered = tmp_path / "recovered save #1" / "terralocal.sqlite3"
    command = [sys.executable, "-m", "terralocal", "--data-dir", str(settings.data_dir), "restore", snapshot["name"]]
    direct = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=25)
    assert direct.returncode == 2 and "restore --output" in direct.stderr and "Traceback" not in direct.stderr
    result = subprocess.run([*command, "--output", str(recovered)],
                            capture_output=True, text=True, encoding="utf-8", timeout=25)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["output"] == str(recovered) and report["database_revision"] == REVISION
    assert report["sha256"] == hashlib.sha256(recovered.read_bytes()).hexdigest()
    assert report["bytes"] == recovered.stat().st_size
    assert list(recovered.parent.iterdir()) == [recovered]
    with closing(sqlite3.connect(recovered.as_uri() + "?mode=ro", uri=True)) as connection:
        assert connection.execute("SELECT nickname FROM player_profiles").fetchone() == ("Saved before damage",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (REVISION,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    assert all(path.read_bytes() == expected for path, expected in inputs.items())


@pytest.mark.parametrize(("fault", "message"), [
    ("checksum", "备份哈希"), ("configuration", "不同的 GameData"), ("target", "目标"),
    ("journal", "附属文件"),
])
def test_offline_recovery_rejects_invalid_inputs_before_publishing(runtime, tmp_path, fault, message):
    service = BackupService(runtime)
    saved = service.create()
    source = service.directory / saved["name"]
    target = tmp_path / "recovered.sqlite3"
    if fault == "checksum":
        raw = source.read_bytes()
        source.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    elif fault == "configuration":
        saved["gamedata_hash"] = "f" * 64
        source.with_suffix(".json").write_text(json.dumps(saved), "utf-8")
    else:
        existing = target.with_name(target.name + "-journal") if fault == "journal" else target
        existing.write_bytes(b"previous file")
    with pytest.raises(ValueError, match=message):
        recover_backup(runtime.settings, saved["name"], target)
    if fault in {"target", "journal"}:
        assert existing.read_bytes() == b"previous file"
    assert target.exists() == (fault == "target")
    assert not list(tmp_path.glob(".recover-*"))
