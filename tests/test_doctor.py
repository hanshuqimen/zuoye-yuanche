"""Exercise the CLI against disposable static data and save files."""

import json
import shutil
import socket
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from conftest import miniature

from terralocal.cli import main
from terralocal.config import Settings
from terralocal.server.gamedata import import_data
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import REVISION, ROGUE_BANK_AWARDS_REVISION
from terralocal.server.services.tls import ensure_certificate


@pytest.fixture
def configured(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name, content in miniature().items():
        (source / f"{name}.json").write_text(json.dumps(content), "utf-8")
    data_dir = tmp_path / "local save"
    manifest = import_data(source, data_dir / "cache")
    with socket.socket() as game, socket.socket() as admin:
        game.bind(("127.0.0.1", 0))
        admin.bind(("127.0.0.1", 0))
        settings = Settings(data_dir=data_dir, game_host="127.0.0.1", game_port=game.getsockname()[1],
                            admin_port=admin.getsockname()[1], gamedata_hash=manifest["hash"])
    settings.save()
    return settings


def _doctor(data_dir, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["terralocal", "--data-dir", str(data_dir), "doctor"])
    exit_code = main()
    output = capsys.readouterr()
    assert not output.err
    return exit_code, json.loads(output.out)


def _files(directory):
    return {path.relative_to(directory): path.read_bytes() if path.is_file() else None
            for path in directory.rglob("*")}


def _initialized_save(settings):
    database = Database(settings.database_path)
    try:
        database.initialize()
    finally:
        database.close()


def test_absent_directory_remains_absent(tmp_path, monkeypatch, capsys):
    directory = tmp_path / "absent" / "data"
    code, report = _doctor(directory, monkeypatch, capsys)
    assert code == 1
    assert report["database"] == "not_initialized"
    assert not report["startup_ready"]
    assert "not_configured" in {issue["code"] for issue in report["issues"]}
    assert not directory.parent.exists()
    assert not list(tmp_path.iterdir())


def test_preflight_can_pass_before_first_run(configured, monkeypatch, capsys):
    before = _files(configured.data_dir)
    code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 0
    assert report["startup_ready"] and not report["client_verified"] and not report["ready_for_play"]
    assert report["database"] == "not_initialized"
    assert report["tls"] == "will_create"
    assert report["gamedata"]["hash"] == configured.gamedata_hash
    assert not report["issues"]
    assert _files(configured.data_dir) == before


def test_doctor_reports_tls_renewal_and_missing_authority_read_only(configured, monkeypatch, capsys):
    certificate, _ = ensure_certificate(configured)
    Path(certificate).write_bytes(b"damaged synthetic server certificate")
    before = _files(configured.data_dir)
    code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 0 and report["startup_ready"] and report["tls"] == "will_renew"
    assert _files(configured.data_dir) == before
    (configured.data_dir / "certs/ca.key").unlink()
    before = _files(configured.data_dir)
    code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 1 and not report["startup_ready"] and report["tls"] == "blocked"
    assert {(issue["area"], issue["code"]) for issue in report["issues"]} == {("tls", "invalid_certificate")}
    assert _files(configured.data_dir) == before
    configured.tls = False
    configured.save()
    code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 0 and report["tls"] == "disabled"


def test_current_database_and_its_directory_are_unchanged(configured, monkeypatch, capsys):
    _initialized_save(configured)
    before = _files(configured.data_dir)
    assert not any(path.name.endswith(("-wal", "-shm")) for path in before)
    code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 0
    assert report["database"] == "ok" and report["database_revision"] == REVISION
    assert _files(configured.data_dir) == before


def test_committed_wal_is_checked_without_migrating_or_touching_source(configured, monkeypatch, capsys):
    _initialized_save(configured)
    main_file = configured.database_path.read_bytes()
    with closing(sqlite3.connect(configured.database_path)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE alembic_version SET version_num = ?", (ROGUE_BANK_AWARDS_REVISION,))
        writer.commit()
        assert Path(str(configured.database_path) + "-wal").stat().st_size > 0
        assert configured.database_path.read_bytes() == main_file
        before = _files(configured.data_dir)
        code, report = _doctor(configured.data_dir, monkeypatch, capsys)
        assert code == 1 and not report["startup_ready"]
        assert report["database"] == "upgrade_required"
        assert report["database_revision"] == ROGUE_BANK_AWARDS_REVISION
        assert _files(configured.data_dir) == before


def test_save_modified_during_copy_cannot_pass(configured, monkeypatch, capsys):
    _initialized_save(configured)
    copyfile = shutil.copyfile

    def concurrent_write(source, target):
        result = copyfile(source, target)
        if source == configured.database_path:
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE another_writer (value INTEGER)")
                connection.commit()
        return result

    monkeypatch.setattr(shutil, "copyfile", concurrent_write)
    code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 1 and report["database"] == "changing"
    assert not report["startup_ready"]


def test_occupied_port_blocks_preflight(configured, monkeypatch, capsys):
    before = _files(configured.data_dir)
    with socket.socket() as listener:
        listener.bind((configured.game_host, configured.game_port))
        listener.listen()
        code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 1 and not report["startup_ready"]
    assert report["ports"] == {"game": "in_use", "admin": "available"}
    assert report["issues"][0]["code"] == "in_use"
    assert _files(configured.data_dir) == before


def test_corrupt_database_returns_json_and_preserves_file(configured, monkeypatch, capsys):
    configured.database_path.write_bytes(b"not an SQLite database")
    before = _files(configured.data_dir)
    code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 1 and not report["startup_ready"]
    assert report["database"] == "corrupt" and report["issues"][-1]["code"] == "corrupt"
    assert _files(configured.data_dir) == before


def test_current_stamp_does_not_hide_a_missing_table(configured, monkeypatch, capsys):
    with closing(sqlite3.connect(configured.database_path)) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (REVISION,))
        connection.commit()
    code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 1 and report["database"] == "schema_mismatch"


def test_invalid_foreign_key_does_not_pass_integrity(configured, monkeypatch, capsys):
    _initialized_save(configured)
    with closing(sqlite3.connect(configured.database_path)) as connection:
        connection.execute("CREATE TABLE diagnostic_fixture (account_id INTEGER REFERENCES accounts(id))")
        connection.execute("INSERT INTO diagnostic_fixture VALUES (1)")
        connection.commit()
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    before = _files(configured.data_dir)
    code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 1 and report["database"] == "foreign_key_error"
    assert _files(configured.data_dir) == before


def test_game_data_changes_are_detected_without_initializing_save(configured, monkeypatch, capsys):
    cache = configured.data_dir / "cache" / configured.gamedata_hash
    (cache / "character_table.json").write_text("{}", "utf-8")
    before = _files(configured.data_dir)
    code, report = _doctor(configured.data_dir, monkeypatch, capsys)
    assert code == 2 and not report["startup_ready"]
    assert report["database"] == "not_initialized"
    assert report["issues"][-1]["area"] == "startup_inputs"
    assert _files(configured.data_dir) == before


def test_invalid_settings_report_does_not_echo_input(tmp_path, monkeypatch, capsys):
    supplied = {"admin_port": "test-private-value"}
    (tmp_path / "settings.json").write_text(json.dumps(supplied), "utf-8")
    before = _files(tmp_path)
    code, report = _doctor(tmp_path, monkeypatch, capsys)
    assert code == 2 and not report["startup_ready"]
    assert report["issues"][-1]["code"] == "invalid_fields"
    assert supplied["admin_port"] not in json.dumps(report)
    assert _files(tmp_path) == before
