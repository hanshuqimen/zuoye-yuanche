"""Backup rotation and restore use only verified, owned snapshots."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from sqlite3 import connect
from threading import Barrier, Event

import pytest

from terralocal.launcher import service as launcher_service
from terralocal.server.gamedata.repository import import_data
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import ROGUE_BANK_AWARDS_REVISION
from terralocal.server.services import backups
from terralocal.server.services.backups import (
    BackupService,
    backup_existing_save,
    own_save_directory,
    recover_backup,
)
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def wall_clock(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 12, 27, 12, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz)

    monkeypatch.setattr(backups, "datetime", Clock)
    return Clock


def names(service, prefix):
    return [item["name"] for item in service.list() if item["name"].startswith(prefix + "-")]


@pytest.mark.parametrize("failure", ["invalid-json", "missing-file", "short-file", "same-size-corruption"])
def test_broken_backup_does_not_suppress_both_schedules(runtime, wall_clock, failure):
    service = BackupService(runtime)
    broken = service.directory / service.create("daily")["name"]
    metadata = broken.with_suffix(".json")
    if failure == "invalid-json":
        metadata.write_text("{", "utf-8")
    elif failure == "missing-file":
        broken.rename(broken.with_suffix(".withheld"))
    else:
        raw = broken.read_bytes()
        data = raw[:100] if failure == "short-file" else raw[:-1] + bytes([raw[-1] ^ 1])
        broken.write_bytes(data)
    saved_sidecar = metadata.read_bytes()
    saved_contents = broken.read_bytes() if broken.exists() else None

    service.automatic()
    first_daily = names(service, "daily")
    assert len(first_daily) == len(names(service, "weekly")) == 1
    assert broken.name not in first_daily
    restarted = Runtime(runtime.settings)
    try:
        other = BackupService(restarted)
        other.automatic()
        assert names(other, "daily") == first_daily
        assert len(names(other, "weekly")) == 1
    finally:
        restarted.database.close()
    assert metadata.read_bytes() == saved_sidecar
    assert (broken.read_bytes() if broken.exists() else None) == saved_contents


def test_rotation_covers_seven_dates_and_four_iso_weeks(runtime, token, wall_clock):
    service = BackupService(runtime)
    manual = service.create()
    guard = service.create("before-restore")
    start = wall_clock.current
    dates = [start + timedelta(days=day) for day in (0, 1, 2, 6, 7, 14, 21, 28, 29)]
    for moment in dates:
        wall_clock.current = moment
        service.automatic()
    daily = names(service, "daily")
    weekly = names(service, "weekly")
    assert [name[6:14] for name in daily] == [d.strftime("%Y%m%d") for d in reversed(dates[-7:])]
    expected_weeks = sorted({d.isocalendar()[:2] for d in dates}, reverse=True)[:4]
    actual_weeks = [datetime.strptime(name[7:15], "%Y%m%d").isocalendar()[:2] for name in weekly]
    assert actual_weeks == expected_weeks
    assert set(names(service, "manual")) == {manual["name"]}
    assert set(names(service, "before-restore")) == {guard["name"]}

    # A host-clock correction needs a backup today even if seven newer dates exist.
    wall_clock.current = start - timedelta(days=2)
    service.automatic()
    assert len(daily := names(service, "daily")) == 7 and any("20261225" in name for name in daily)
    assert len(weekly := names(service, "weekly")) == 4 and any("20261225" in name for name in weekly)
    assert len(list(service.directory.glob("daily-*.sqlite3"))) == 7
    assert len(list(service.directory.glob("weekly-*.sqlite3"))) == 4
    expected = runtime.sync(token)
    with runtime.database.transaction() as session:
        session.get(m.PlayerProfile, 1).nickname = "After the retained snapshot"
    service.restore(daily[0])
    assert runtime.sync(token) == expected


def test_rotation_after_data_version_change_restores_both_versions(runtime, tmp_path, wall_clock):
    previous = BackupService(runtime)
    previous.automatic()
    previous_backups = previous.list()
    prior_files = {path: path.read_bytes() for path in previous.directory.iterdir() if path.is_file()}
    source = tmp_path / "source"
    (source / "data_version.txt").write_text("synthetic-revision-2", "utf-8")
    manifest = import_data(source, runtime.settings.data_dir / "cache")
    assert manifest["hash"] != runtime.settings.gamedata_hash
    settings = runtime.settings.model_copy(update={"gamedata_hash": manifest["hash"]})
    settings.save()
    runtime.database.close()
    restarted = Runtime(settings)
    try:
        service = BackupService(restarted)

        def active_backups():
            return [item for item in service.list() if item["gamedata_hash"] == manifest["hash"]]

        with restarted.database.transaction() as session:
            session.get(m.PlayerProfile, 1).nickname = "Progress under the new configuration"
        service.automatic()
        created = active_backups()
        assert sorted(item["name"].split("-", 1)[0] for item in created) == ["daily", "weekly"]
        service.automatic()
        assert active_backups() == created
        daily = next(item for item in created if item["name"].startswith("daily-"))
        with restarted.database.transaction() as session:
            session.get(m.PlayerProfile, 1).nickname = "Progress after backup"
        service.restore(daily["name"])
        with restarted.database.transaction(write=False) as session:
            assert session.get(m.PlayerProfile, 1).nickname == "Progress under the new configuration"

        for _ in range(8):
            wall_clock.current += timedelta(days=7)
            service.automatic()
        retained = active_backups()
        assert sum(item["name"].startswith("daily-") for item in retained) == 7
        assert sum(item["name"].startswith("weekly-") for item in retained) == 4
        assert all(path.read_bytes() == original for path, original in prior_files.items())
        target = tmp_path / "old-version-recovery.sqlite3"
        recover_backup(runtime.settings, previous_backups[0]["name"], target)
        with closing(connect(target)) as connection:
            assert connection.execute("SELECT nickname FROM player_profiles").fetchone() == ("Doctor",)
    finally:
        restarted.database.close()


def test_rotation_compares_optional_rules_and_reuses_legacy_empty_marker(runtime, wall_clock):
    service = BackupService(runtime)
    daily = service.create("daily")
    weekly = service.create("weekly")
    daily.pop("drop_catalog_hash")
    weekly["drop_catalog_hash"] = "a" * 64
    for info in (daily, weekly):
        (service.directory / info["name"]).with_suffix(".json").write_text(json.dumps(info), "utf-8")
    service.automatic()
    assert names(service, "daily") == [daily["name"]]
    [replacement] = [item for item in service.list()
                     if item["name"].startswith("weekly-") and item["name"] != weekly["name"]]
    assert replacement["drop_catalog_hash"] is None
    assert service.restore(replacement["name"])["restored"] == replacement["name"]
    with pytest.raises(ValueError, match="不同的掉落规则"):
        service.restore(weekly["name"])


def test_duplicate_period_and_orphan_do_not_displace_verified_dates(runtime, wall_clock):
    service = BackupService(runtime)
    start = wall_clock.current
    first = service.create("daily")
    for offset in range(1, 7):
        wall_clock.current = start + timedelta(days=offset)
        service.create("daily")
    duplicate = service.create("daily")
    orphan = service.directory / "daily-20270110T120000.000000Z.sqlite3"
    orphan.write_bytes(b"incomplete synthetic candidate")

    service.automatic()
    retained = names(service, "daily")
    assert len(retained) == 7 and len({name[6:14] for name in retained}) == 7
    assert first["name"] in retained and duplicate["name"] in retained
    assert orphan.read_bytes() == b"incomplete synthetic candidate"


def test_rotation_can_remove_source_after_restore_has_staged_it(runtime, token, wall_clock, monkeypatch):
    service = BackupService(runtime)
    expected = runtime.sync(token)
    selected = service.directory / service.create("daily")["name"]
    start = wall_clock.current
    for offset in range(1, 8):
        wall_clock.current = start + timedelta(days=offset)
        service.create("daily")
    with runtime.database.transaction() as session:
        session.get(m.PlayerProfile, 1).nickname = "After the selected snapshot"

    copy_started, release_copy, rotated = Event(), Event(), Event()
    copyfile = backups.shutil.copyfile
    initialize = Database.initialize

    def pause_copy(source, target):
        if source == selected:
            copy_started.set()
            assert release_copy.wait(10)
        return copyfile(source, target)

    def finish_rotation_first(database):
        if database.path.name == "candidate.sqlite3":
            assert rotated.wait(10)
            assert not selected.exists()
        return initialize(database)

    def rotate():
        service.automatic()
        rotated.set()

    monkeypatch.setattr(backups.shutil, "copyfile", pause_copy)
    monkeypatch.setattr(Database, "initialize", finish_rotation_first)
    with ThreadPoolExecutor(max_workers=2) as pool:
        restoring = pool.submit(service.restore, selected.name)
        try:
            assert copy_started.wait(10)
            rotation = pool.submit(rotate)
            assert selected.is_file()
        finally:
            release_copy.set()
        rotation.result(timeout=10)
        restoring.result(timeout=10)
    assert runtime.sync(token) == expected


def test_restore_preserves_a_copy_of_a_damaged_active_database(runtime, token):
    service = BackupService(runtime)
    valid = service.create()
    expected = runtime.sync(token)
    with closing(connect(runtime.database.path)) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("INSERT INTO currencies(account_id,item_id,balance) VALUES (999,'4001',10)")
        connection.commit()
    restored = service.restore(valid["name"])
    with closing(connect(service.directory / restored["previous"])) as previous:
        assert previous.execute("PRAGMA foreign_key_check").fetchone() is not None
    with closing(connect(runtime.database.path)) as active:
        assert active.execute("PRAGMA foreign_key_check").fetchone() is None
    assert runtime.sync(token) == expected


def test_cli_restore_waits_for_service_shutdown_but_backup_still_works(runtime, token):
    service = BackupService(runtime)
    original = runtime.sync(token)
    saved = service.create()
    with runtime.database.transaction() as session:
        session.get(m.PlayerProfile, 1).nickname = "Committed while the server is running"
    active = runtime.sync(token)

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "terralocal", "--data-dir", str(runtime.settings.data_dir),
                               *args], capture_output=True, encoding="utf-8", timeout=25)

    with own_save_directory(runtime.settings.data_dir):
        rejected = cli("restore", saved["name"])
        assert rejected.returncode == 2 and "数据目录正由" in rejected.stderr
        assert runtime.sync(token) == active
        assert not names(service, "before-restore")
        online = cli("backup")
        assert online.returncode == 0, online.stderr
        assert json.loads(online.stdout)["name"] in names(service, "manual")

    runtime.database.close()
    restored = cli("restore", saved["name"])
    assert restored.returncode == 0, restored.stderr
    assert json.loads(restored.stdout)["restored"] == saved["name"]
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == original
    finally:
        reopened.database.close()


def test_cli_backup_preserves_legacy_revision_and_committed_wal(runtime):
    settings = runtime.settings
    runtime.database.close()
    path = settings.database_path
    journal = path.with_name(path.name + "-wal")
    latest_table = m.RogueBattleLootPlan.__tablename__
    clock_table = m.ServerClockState.__tablename__
    with own_save_directory(settings.data_dir), closing(connect(path)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(f"DROP TABLE {latest_table}")
        writer.execute("UPDATE alembic_version SET version_num = ?", (ROGUE_BANK_AWARDS_REVISION,))
        writer.execute(f"UPDATE {clock_table} SET offset = 451 WHERE id = 1")
        writer.commit()
        assert journal.stat().st_size > 32
        original = path.read_bytes(), journal.read_bytes()
        result = subprocess.run([sys.executable, "-m", "terralocal", "--data-dir", str(settings.data_dir), "backup"],
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        assert result.returncode == 0, result.stderr
        saved = json.loads(result.stdout)
        assert saved["database_revision"] == ROGUE_BANK_AWARDS_REVISION
        assert (path.read_bytes(), journal.read_bytes()) == original
        assert writer.execute("SELECT version_num FROM alembic_version").fetchone() == (ROGUE_BANK_AWARDS_REVISION,)
        snapshot = settings.data_dir / "backups" / saved["name"]
        with closing(connect(snapshot.as_uri() + "?mode=ro", uri=True)) as copy:
            assert copy.execute("SELECT version_num FROM alembic_version").fetchone() == (ROGUE_BANK_AWARDS_REVISION,)
            assert copy.execute(f"SELECT offset FROM {clock_table} WHERE id = 1").fetchone() == (451,)
            assert copy.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (latest_table,)).fetchone() is None


def test_cli_backup_requires_an_existing_save(tmp_path):
    empty = tmp_path / "uninitialized"
    result = subprocess.run([sys.executable, "-m", "terralocal", "--data-dir", str(empty), "backup"],
                            capture_output=True, text=True, encoding="utf-8", timeout=25)
    assert result.returncode == 2 and "当前目录没有存档" in result.stderr
    assert not empty.exists()


def test_cli_and_service_backups_can_publish_at_the_same_timestamp(runtime, wall_clock, monkeypatch):
    service = BackupService(runtime)
    publish = backups._publish_new_file
    at_publication = Barrier(2, timeout=10)
    first_target = f"manual-{wall_clock.current.strftime(backups.STAMP)}.sqlite3"

    def publish_together(staged, target):
        if target.name == first_target:
            at_publication.wait()
        publish(staged, target)

    monkeypatch.setattr(backups, "_publish_new_file", publish_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        from_cli = pool.submit(backup_existing_save, runtime.settings)
        from_service = pool.submit(service.create)
        saved = [from_cli.result(timeout=15), from_service.result(timeout=15)]
    assert len({item["name"] for item in saved}) == 2
    assert first_target in {item["name"] for item in saved}
    assert service.list() == sorted(saved, key=lambda item: item["name"], reverse=True)
    assert not list(service.directory.glob(".backup-*"))


def test_backup_worker_recovers_from_directory_unavailable(runtime, monkeypatch):
    group = launcher_service.ServerGroup(runtime.settings)
    group.runtime = runtime
    directory = runtime.settings.data_dir / "backups"
    directory.rmdir()
    directory.write_text("temporary path conflict", "utf-8")

    def wait(_seconds):
        if directory.is_file():
            directory.unlink()
        else:
            group.stop_event.set()
        return group.stop_event.is_set()

    monkeypatch.setattr(group.stop_event, "wait", wait)
    group._backup_loop()
    service = BackupService(runtime)
    assert len(names(service, "daily")) == len(names(service, "weekly")) == 1


def test_automatic_checksum_does_not_block_sync_or_a_ledger_write(runtime, token, monkeypatch):
    service = BackupService(runtime)
    service.automatic()
    expected = runtime.sync(token)
    entered, complete = Event(), Event()
    sha256 = backups._sha256

    def pause_hash(path):
        if path.name.startswith("daily-"):
            entered.set()
            assert complete.wait(10)
        return sha256(path)

    def mutate():
        def credit(ctx):
            ctx.change_item("material", 3)
            return {}

        return runtime.mutate(token, None, "backup-hash-overlap", "credit-test", {}, credit)

    monkeypatch.setattr(backups, "_sha256", pause_hash)
    with ThreadPoolExecutor(max_workers=2) as pool:
        checking = pool.submit(service.automatic)
        try:
            assert entered.wait(5)
            assert pool.submit(runtime.sync, token).result(timeout=5) == expected
            assert pool.submit(mutate).result(timeout=5)["revision"] == expected["revision"] + 1
            assert not checking.done()
        finally:
            complete.set()
        checking.result(timeout=5)
    assert runtime.sync(token)["user"]["inventory"]["material"] == 3


def test_online_backup_uses_only_committed_rows_while_a_write_is_in_progress(runtime):
    service = BackupService(runtime)
    prepared, commit = Event(), Event()

    def pending_write():
        with runtime.maintenance, runtime.database.transaction() as session:
            session.get(m.PlayerProfile, 1).nickname = "After commit"
            session.get(m.Currency, (1, "4001")).balance = 271
            session.flush()
            prepared.set()
            assert commit.wait(10)

    def saved_values(path):
        with closing(connect(path)) as connection:
            profile = connection.execute("SELECT nickname FROM player_profiles WHERE account_id=1").fetchone()[0]
            gold = connection.execute("SELECT balance FROM currencies WHERE account_id=1 AND item_id='4001'").fetchone()[0]
        return profile, gold

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(pending_write)
        try:
            assert prepared.wait(5)
            first = pool.submit(service.create).result(timeout=5)
            assert saved_values(service.directory / first["name"]) == ("Doctor", 1000)
        finally:
            commit.set()
        writer.result(timeout=5)
    second = service.create()
    assert saved_values(service.directory / second["name"]) == ("After commit", 271)
