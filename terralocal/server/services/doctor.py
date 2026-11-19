"""Read-only startup diagnostics for the local server."""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import socket
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from pydantic import ValidationError

from terralocal import __version__
from terralocal.config import Settings, default_data_dir, load_settings
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence.migrations import REVISION, SUPPORTED_REVISIONS
from terralocal.server.persistence.models import Base
from terralocal.server.services.runtime import StartupInputs
from terralocal.server.services.tls import CertificateError, certificate_status

DATABASE_FINDINGS = {
    "changing": "无法取得一致的存档副本。请停止写入后重试",
    "corrupt": "存档未通过 SQLite 完整性校验",
    "foreign_key_error": "存档包含无效的实体引用",
    "unsupported": "存档没有受支持的 TerraLocal 版本标记",
    "schema_mismatch": "存档缺少其版本所需的表或字段",
    "upgrade_required": "存档版本受支持，启动服务时将执行迁移",
}


def _signature(path: Path) -> tuple[int, int, int, int, bytes] | None:
    try:
        with path.open("rb") as stream:
            stat = os.fstat(stream.fileno())
            digest = hashlib.file_digest(stream, "sha256").digest()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, digest


def _copy_save(source: Path, target: Path) -> bool:
    # SQLite may create WAL/SHM files on a read-only connection. Recover and
    # inspect a private copy, including the original journal if present.
    suffixes = ("", "-wal", "-journal")
    original = [source.with_name(source.name + suffix) for suffix in suffixes]
    before = [_signature(path) for path in original]
    if before[0] is None and any(before[1:]):
        return False
    for path, suffix, signature in zip(original, suffixes, before, strict=True):
        if signature is None:
            continue
        copy = target.with_name(target.name + suffix)
        try:
            shutil.copyfile(path, copy)
        except FileNotFoundError:
            return False
        with copy.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").digest() != signature[-1]:
                return False
    return before == [_signature(path) for path in original]


def _scratch(directory: Path) -> tempfile.TemporaryDirectory:
    parent = next((p for p in directory.parents if p.is_dir()), None)
    try:
        return tempfile.TemporaryDirectory(prefix=".terralocal-doctor-", dir=parent)
    except (PermissionError, FileNotFoundError):
        return tempfile.TemporaryDirectory(prefix=".terralocal-doctor-")


def _inspect_save(path: Path) -> tuple[str, str | None]:
    if not path.exists():
        return "not_initialized", None
    try:
        with closing(sqlite3.connect(path)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                return "corrupt", None
            tables = {name for name, in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            if "alembic_version" not in tables:
                return "unsupported", None
            columns = {name for name, in connection.execute("SELECT name FROM pragma_table_info('alembic_version')")}
            if "version_num" not in columns:
                return "unsupported", None
            rows = connection.execute("SELECT version_num FROM alembic_version LIMIT 2").fetchall()
            if len(rows) != 1 or rows[0][0] not in SUPPORTED_REVISIONS:
                return "unsupported", None
            revision = rows[0][0]
            if revision == REVISION:
                for table in Base.metadata.tables.values():
                    names = {name for name, in connection.execute("SELECT name FROM pragma_table_info(?)", (table.name,))}
                    if table.name not in tables or set(table.columns.keys()) - names:
                        return "schema_mismatch", revision
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                return "foreign_key_error", revision
            return ("ok" if revision == REVISION else "upgrade_required"), revision
    except sqlite3.DatabaseError as exc:
        primary_code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
        if primary_code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
            return "corrupt", None
        raise


def _port_status(host: str, port: int) -> str:
    try:
        with socket.socket() as listener:
            listener.bind((host, port))
    except OSError as exc:
        if exc.errno in {errno.EADDRINUSE, 10048} or getattr(exc, "winerror", None) == 10048:
            return "in_use"
        return "unavailable"
    return "available"


def _issue(report: dict, area: str, code: str, message: str) -> None:
    report["issues"].append({"area": area, "code": code, "message": message})


def diagnose(data_dir: Path | None) -> tuple[dict, int]:
    report = {
        "version": __version__, "data_dir": data_dir, "client_profile": None,
        "ports": {}, "database": "not_checked", "database_revision": None, "gamedata": None,
        "skin_shop": None, "voucher_shop": None, "cash_shop": None, "gift_packs": None,
        "tls": "not_checked", "issues": [], "startup_ready": False, "client_verified": False, "ready_for_play": False,
    }
    try:
        directory = (data_dir or default_data_dir()).resolve()
        report["data_dir"] = directory
        if directory.exists() and not directory.is_dir():
            raise ValueError("数据目录必须是目录")
        settings = load_settings(directory)
        settings.validate_startup()
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False)
        fields = sorted({error["loc"][0] for error in errors
                         if error["loc"] and error["loc"][0] in Settings.model_fields})
        message = f"启动配置有 {len(errors)} 个无效字段"
        if fields:
            message += f"（{', '.join(fields)}）"
        _issue(report, "settings", "invalid_fields", message)
        return report, 2
    except (ValueError, OSError) as exc:
        _issue(report, "settings", "invalid_settings", str(exc))
        return report, 2

    report["client_profile"] = settings.client_profile
    for name, host, port in (("game", settings.game_host, settings.game_port),
                             ("admin", settings.admin_host, settings.admin_port)):
        status = report["ports"][name] = _port_status(host, port)
        if status != "available":
            reason = "已被占用" if status == "in_use" else "无法绑定"
            _issue(report, name, status, f"{host}:{port} {reason}")

    try:
        report["tls"] = certificate_status(settings)
    except CertificateError as exc:
        report["tls"] = "blocked"
        _issue(report, "tls", "invalid_certificate", str(exc))
    except OSError:
        report["tls"] = "blocked"
        _issue(report, "tls", "unreadable_certificate", "无法读取本地证书目录。")

    area = "database"
    try:
        with _scratch(directory) as folder:
            staged_save = Path(folder) / settings.database_path.name
            if not _copy_save(settings.database_path, staged_save):
                report["database"] = "changing"
            else:
                report["database"], report["database_revision"] = _inspect_save(staged_save)
            state = report["database"]
            if state in DATABASE_FINDINGS:
                _issue(report, area, state, DATABASE_FINDINGS[state])
            if state not in {"ok", "not_initialized", "upgrade_required"}:
                return report, 1
            area = "startup_inputs"
            inputs = StartupInputs(settings, staged_save)
    except ValidationError:
        _issue(report, area, "invalid_fields", "静态数据或目录配置字段无效")
        return report, 2
    except (ValueError, OSError, DomainError, sqlite3.DatabaseError) as exc:
        _issue(report, area, "check_failed", str(exc))
        return report, 2

    if inputs.data is None:
        _issue(report, "gamedata", "not_configured", "请先导入并选择静态数据")
    else:
        report["gamedata"] = inputs.data.manifest
    for name, catalog in (("skin_shop", inputs.skin_shop_catalog), ("voucher_shop", inputs.voucher_shop_catalog),
                          ("cash_shop", inputs.cash_shop_catalog), ("gift_packs", inputs.gift_pack_catalog)):
        if catalog is not None:
            report[name] = catalog.summary()
    report["startup_ready"] = not report["issues"]
    return report, 0 if report["startup_ready"] else 1
