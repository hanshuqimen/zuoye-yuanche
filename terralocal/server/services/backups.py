from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import inspect, text
from sqlalchemy.exc import DatabaseError

from terralocal.config import Settings
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import REVISION, SUPPORTED_REVISIONS
from terralocal.server.persistence.models import Base

if TYPE_CHECKING:
    from terralocal.server.services.runtime import StartupInputs

STAMP = "%Y%m%dT%H%M%S.%fZ"
KINDS = frozenset({"manual", "daily", "weekly", "before-restore"})
BACKUP_NAME = re.compile(r"(?:manual|daily|weekly|before-restore)-([0-9]{8}T[0-9]{6}\.[0-9]{6}Z)\.sqlite3")


@contextmanager
def own_save_directory(directory: Path):
    """Hold the same OS-backed lock in the server and in an offline restore."""
    directory.mkdir(parents=True, exist_ok=True)
    try:
        owner = sqlite3.connect(directory / ".save-owner.sqlite3", timeout=0, check_same_thread=False)
    except sqlite3.Error as exc:
        raise ValueError("无法在数据目录建立存档锁") from exc
    with closing(owner):
        try:
            # This database carries only a filesystem lock. Closing the
            # connection releases it, including when its process exits.
            owner.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise ValueError("该数据目录正由 TerraLocal 服务或命令行恢复使用。请停止服务后再试，或在运行中的服务内恢复。") from exc
            raise ValueError("无法锁定数据目录") from exc
        yield


@dataclass(frozen=True)
class _Snapshot:
    path: Path
    created_at: datetime
    info: dict


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read_snapshot(path: Path, *, require_canonical_name: bool = True) -> _Snapshot:
    metadata = path.with_suffix(".json")
    if (path.is_symlink() or metadata.is_symlink() or not path.is_file() or not metadata.is_file()):
        raise ValueError("备份数据库或索引缺失")
    info = json.loads(metadata.read_text("utf-8"))
    if (not isinstance(info, dict) or "gamedata_hash" not in info
            or type(info.get("created_at")) is not str
            or type(info.get("bytes")) is not int or info["bytes"] <= 0
            or not isinstance(info.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", info["sha256"])):
        raise ValueError("备份索引格式无效")
    created = datetime.strptime(info["created_at"], STAMP).replace(tzinfo=UTC)
    if require_canonical_name:
        match = BACKUP_NAME.fullmatch(path.name)
        if not match or match[1] != info["created_at"] or info.get("name") != path.name:
            raise ValueError("备份索引与文件名不一致")
    if path.stat().st_size != info["bytes"]:
        raise ValueError("备份大小或哈希不一致，拒绝使用")
    return _Snapshot(path, created, info)


def _matches_digest(snapshot: _Snapshot) -> bool:
    try:
        return _sha256(snapshot.path) == snapshot.info["sha256"]
    except OSError:
        return False


def _period(prefix: str, stamp: datetime) -> tuple[int, ...]:
    if prefix == "daily":
        return stamp.year, stamp.month, stamp.day
    year, week, _ = stamp.isocalendar()
    return year, week


def _open_readonly(path: Path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)


def _check_integrity(connection, revisions=SUPPORTED_REVISIONS) -> None:
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("备份数据库损坏")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("备份存在无效实体引用")
    rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    if len(rows) != 1 or rows[0][0] not in revisions:
        raise ValueError("不支持此数据库版本")


def _check_schema(database: Database) -> None:
    with database.engine.connect() as connection:
        schema = inspect(connection)
        existing = set(schema.get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                raise ValueError(f"备份缺少必要数据表: {table.name}")
            columns = {column["name"] for column in schema.get_columns(table.name)}
            if set(table.columns.keys()) - columns:
                raise ValueError(f"备份缺少必要字段: {table.name}")


def _copy_database(source: Path, target: Path) -> None:
    # SQLite backup commits the destination in one SQLite transaction. Keep the
    # existing filename instead of replacing a database underneath WAL readers.
    with closing(_open_readonly(source)) as original, closing(sqlite3.connect(target, timeout=10)) as destination:
        original.backup(destination)


def _backup_path(directory: Path, name: str) -> Path:
    path = directory / name
    if path.name != name or path.resolve().parent != directory.resolve() or path.suffix != ".sqlite3":
        raise ValueError("只能恢复备份目录中的存档")
    return path


def _check_copied_database(snapshot: _Snapshot, candidate_path: Path) -> None:
    if _sha256(candidate_path) != snapshot.info["sha256"]:
        raise ValueError("备份哈希不一致，拒绝恢复")
    try:
        with closing(_open_readonly(candidate_path)) as source:
            _check_integrity(source)
    except sqlite3.DatabaseError as exc:
        raise ValueError("备份数据库无法读取，拒绝恢复") from exc


def _configuration_hashes(inputs: StartupInputs) -> dict[str, str | None]:
    catalogs = {
        "drop_catalog_hash": inputs.drop_catalog,
        "headhunting_catalog_hash": inputs.headhunting_rules,
        "skin_catalog_hash": inputs.skin_shop_catalog,
        "voucher_catalog_hash": inputs.voucher_shop_catalog,
        "cash_catalog_hash": inputs.cash_shop_catalog,
        "gift_pack_catalog_hash": inputs.gift_pack_catalog,
    }
    source = inputs.rogue_content_source
    return {
        "gamedata_hash": inputs.settings.gamedata_hash,
        "rogue_content_hash": fingerprint(json.loads(source)) if source is not None else None,
        **{name: fingerprint(catalog.model_dump()) if catalog else None for name, catalog in catalogs.items()},
    }


def _check_compatibility(inputs: StartupInputs, info: dict) -> None:
    names = {"rogue_content_hash": "探索内容方案", "drop_catalog_hash": "掉落规则", "headhunting_catalog_hash": "寻访规则"}
    for field, expected in _configuration_hashes(inputs).items():
        # Older indexes might not record every optional catalog. Candidate
        # validation still checks the saved data before activating a restore.
        if field in info and info[field] != expected:
            if field == "gamedata_hash":
                raise ValueError("备份使用不同的 GameData，请先选择对应兼容配置")
            raise ValueError(f"备份使用不同的{names.get(field, '商店目录')}，请先导入对应快照并重启服务")


def _publish_new_file(staged: Path, target: Path) -> None:
    # Windows rename and POSIX link both fail if a concurrent writer wins.
    if os.name == "nt":
        staged.rename(target)
    else:
        os.link(staged, target)


def _publish_backup(staged: Path, directory: Path, prefix: str, now: datetime,
                    configuration: dict[str, str | None]) -> dict:
    with closing(_open_readonly(staged)) as source:
        revisions = source.execute("SELECT version_num FROM alembic_version").fetchall()
    if len(revisions) != 1 or revisions[0][0] not in SUPPORTED_REVISIONS:
        raise ValueError("不支持此数据库版本")
    digest = _sha256(staged)
    size = staged.stat().st_size
    staged_index = staged.with_suffix(".json")
    while True:
        stamp = now.strftime(STAMP)
        path = directory / f"{prefix}-{stamp}.sqlite3"
        metadata = path.with_suffix(".json")
        if any(item.exists() or item.is_symlink() for item in (path, metadata)):
            now += timedelta(microseconds=1)
            continue
        info = {"name": path.name, "sha256": digest, "bytes": size,
                "database_revision": revisions[0][0], "created_at": stamp, **configuration}
        with staged_index.open("w", encoding="utf-8") as stream:
            json.dump(info, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            _publish_new_file(staged, path)
        except FileExistsError:
            now += timedelta(microseconds=1)
            continue
        _publish_new_file(staged_index, metadata)
        return info


def _archive_existing_save(settings: Settings, prefix: str) -> dict:
    from terralocal.server.services.runtime import StartupInputs

    if not settings.database_path.is_file():
        raise ValueError("当前目录没有存档，请先启动服务创建存档")
    directory = settings.data_dir / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix=".backup-", dir=directory) as folder:
        staged = Path(folder) / "backup.sqlite3"
        with closing(Database(settings.database_path)) as source:
            source.backup(staged)
        inputs = StartupInputs(settings, staged)
        return _publish_backup(staged, directory, prefix, now, _configuration_hashes(inputs))


def backup_existing_save(settings: Settings) -> dict:
    """Capture committed state from an existing save without running startup migrations."""
    try:
        return _archive_existing_save(settings, "manual")
    except sqlite3.DatabaseError as exc:
        raise ValueError("无法读取当前存档，未创建备份") from exc


def _prepare_recovery(settings: Settings, source: Path, staged: Path) -> StartupInputs:
    from terralocal.server.services.runtime import StartupInputs

    snapshot = _read_snapshot(source, require_canonical_name=False)
    # Rotation may remove the source while it is being copied. The copied
    # bytes still have to match the index before they reach SQLite.
    shutil.copyfile(source, staged)
    _check_copied_database(snapshot, staged)
    try:
        inputs = StartupInputs(settings, staged)
        _check_compatibility(inputs, snapshot.info)
        with closing(Database(staged)) as database:
            inputs.initialize_database(database)
            _check_schema(database)
        with closing(sqlite3.connect(staged, timeout=10)) as connection:
            # Commit all changes to the one file that will be published.
            if connection.execute("PRAGMA journal_mode=DELETE").fetchone() != ("delete",):
                raise ValueError("无法将恢复结果保存为独立的 SQLite 文件")
            _check_integrity(connection, {REVISION})
    except (sqlite3.DatabaseError, DatabaseError) as exc:
        raise ValueError("无法验证恢复后的数据库") from exc
    return inputs


def _require_unused_output(target: Path) -> None:
    adjacent = [target.with_name(target.name + suffix) for suffix in ("", "-wal", "-shm", "-journal")]
    if any(path.exists() or path.is_symlink() for path in adjacent):
        raise ValueError("恢复目标或其 SQLite 附属文件已存在")


def _publish_recovery(staged: Path, target: Path) -> tuple[int, str]:
    with staged.open("r+b") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        size = os.fstat(stream.fileno()).st_size
        os.fsync(stream.fileno())
    _require_unused_output(target)
    try:
        _publish_new_file(staged, target)
    except FileExistsError as exc:
        raise ValueError("恢复目标已存在") from exc
    return size, digest


def recover_backup(settings: Settings, name: str, output_path: Path) -> dict:
    """Publish a validated standalone save without opening the original save."""
    source = _backup_path(settings.data_dir / "backups", name)
    target = output_path.parent.resolve() / output_path.name
    if target.suffix != ".sqlite3" or target == settings.database_path.resolve():
        raise ValueError("请选择新的 .sqlite3 输出文件")
    _require_unused_output(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".recover-", dir=target.parent) as folder:
        staged = Path(folder) / target.name
        _prepare_recovery(settings, source, staged)
        size, digest = _publish_recovery(staged, target)
    return {"restored": name, "output": str(target), "bytes": size, "sha256": digest,
            "database_revision": REVISION}


def _activate_restore(database: Database, candidate: Path, previous: Path) -> None:
    try:
        database.close()
        _copy_database(candidate, database.path)
        database.initialize()
    except BaseException:
        try:
            database.close()
            _copy_database(previous, database.path)
            # Reopening the previous snapshot must not upgrade its schema.
            with database.transaction(write=False) as session:
                session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        except BaseException as rollback_error:
            raise RuntimeError(f"恢复失败且自动还原未完成；原存档保留在备份 {previous.name}") from rollback_error
        raise


def restore_existing_save(settings: Settings, name: str) -> dict:
    """Restore offline without initializing the current save before archiving it."""
    directory = settings.data_dir / "backups"
    source = _backup_path(directory, name)
    target = settings.database_path
    with (own_save_directory(settings.data_dir),
          tempfile.TemporaryDirectory(prefix=".restore-", dir=settings.data_dir) as folder):
        staged = Path(folder) / "candidate.sqlite3"
        inputs = _prepare_recovery(settings, source, staged)
        if not target.is_file():
            _publish_recovery(staged, target)
            return {"restored": name, "previous": None}
        try:
            previous = _archive_existing_save(settings, "before-restore")
        except sqlite3.DatabaseError as exc:
            code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
            if code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
                raise ValueError("当前存档损坏，可用 restore --output 将备份恢复到新文件") from exc
            raise ValueError("无法读取并保留当前存档") from exc
        _check_compatibility(inputs, previous)
        with closing(Database(target)) as database:
            _activate_restore(database, staged, directory / previous["name"])
    return {"restored": name, "previous": previous["name"]}


class BackupService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.directory = runtime.settings.data_dir / "backups"
        self.directory.mkdir(parents=True, exist_ok=True)

    def create(self, prefix: str = "manual") -> dict:
        if prefix not in KINDS:
            raise ValueError("非法备份类型")
        with self.runtime.backup_files:
            return self._create(prefix, datetime.now(UTC), _configuration_hashes(self.runtime))

    def _create(self, prefix: str, now: datetime, configuration: dict[str, str | None]) -> dict:
        with tempfile.TemporaryDirectory(prefix=".backup-", dir=self.directory) as folder:
            staged = self.runtime.database.backup(Path(folder) / "backup.sqlite3")
            return _publish_backup(staged, self.directory, prefix, now, configuration)

    def _snapshots(self, prefix: str = "") -> list[_Snapshot]:
        snapshots = []
        for metadata in sorted(self.directory.glob(f"{prefix}*.json"), reverse=True):
            if not BACKUP_NAME.fullmatch(metadata.with_suffix(".sqlite3").name):
                continue
            try:
                snapshots.append(_read_snapshot(metadata.with_suffix(".sqlite3")))
            except (ValueError, OSError):
                # An incomplete pair is excluded from scheduling and pruning.
                continue
        return snapshots

    def list(self) -> list[dict]:
        with self.runtime.backup_files:
            return [snapshot.info for snapshot in self._snapshots() if _matches_digest(snapshot)]

    def restore(self, name: str) -> dict:
        path = _backup_path(self.directory, name)
        # Migrations and validation are performed only on the candidate. They
        # must finish before taking a current snapshot and touching active data.
        with tempfile.TemporaryDirectory(prefix=".restore-", dir=self.runtime.database.path.parent) as folder:
            candidate_path = Path(folder) / "candidate.sqlite3"
            # The lock pins the selected files during the copy, even if a
            # scheduled rotation would otherwise discard this snapshot.
            with self.runtime.backup_files:
                snapshot = _read_snapshot(path, require_canonical_name=False)
                _check_compatibility(self.runtime, snapshot.info)
                shutil.copyfile(path, candidate_path)
            _check_copied_database(snapshot, candidate_path)
            candidate = Database(candidate_path)
            try:
                from terralocal.server.compatibility.profile import (
                    CAMPAIGN_CLIENT_PROFILE,
                    ROGUE_CLIENT_PROFILE,
                )
                from terralocal.server.domain.campaign import preflight as preflight_campaign
                from terralocal.server.domain.rogue_topics import preflight as preflight_rogue

                preflight_campaign(self.runtime.data, candidate.path,
                    require_existing_binding=self.runtime.settings.client_profile == CAMPAIGN_CLIENT_PROFILE)
                preflight_rogue(self.runtime.data, candidate.path,
                    require_existing_binding=self.runtime.settings.client_profile == ROGUE_CLIENT_PROFILE)
                candidate.initialize()
                from terralocal.server.gamedata.voucher_shop import admit_catalog, preflight_saved_catalog

                preflight_saved_catalog(self.runtime.voucher_shop_catalog, candidate.path)
                admit_catalog(self.runtime.voucher_shop_catalog, candidate)
                from terralocal.server.gamedata.gift_packs import admit_catalog as admit_packs
                from terralocal.server.gamedata.gift_packs import preflight_saved_catalog as preflight_packs

                preflight_packs(self.runtime.gift_pack_catalog, candidate.path)
                admit_packs(self.runtime.gift_pack_catalog, candidate)
                self.runtime.initialize_home(candidate)
                self.runtime.initialize_campaign(candidate)
                self.runtime.initialize_rogue_topics(candidate)
                _check_schema(candidate)
                with closing(_open_readonly(candidate.path)) as source:
                    _check_integrity(source, {REVISION})
            finally:
                candidate.close()
            # Acquire file access before blocking API writes. The snapshot and
            # replacement must still share one uninterrupted maintenance window.
            with self.runtime.backup_files, self.runtime.maintenance:
                previous = self._create("before-restore", datetime.now(UTC), _configuration_hashes(self.runtime))
                _activate_restore(self.runtime.database, candidate.path, self.directory / previous["name"])
        return {"restored": name, "previous": previous["name"]}

    def automatic(self) -> None:
        with self.runtime.backup_files:
            now = datetime.now(UTC)
            configuration = _configuration_hashes(self.runtime)
            for prefix, keep in (("daily", 7), ("weekly", 4)):
                self._rotate(prefix, keep, now, configuration)

    def _rotate(self, prefix: str, keep: int, now: datetime, configuration: dict[str, str | None]) -> None:
        period = _period(prefix, now)
        # Each configuration has its own window. Keep previous versions
        # available so a return to that configuration can use its backups.
        snapshots = [snapshot for snapshot in self._snapshots(prefix + "-")
                     if all(snapshot.info.get(name) == value for name, value in configuration.items())]
        if not any(_period(prefix, s.created_at) == period and _matches_digest(s) for s in snapshots):
            info = self._create(prefix, now, configuration)
            snapshots.append(_read_snapshot(self.directory / info["name"]))
        if len(snapshots) <= keep:
            return
        # Keep today's or this week's verified snapshot even if the system
        # clock has moved backwards. Prefer coverage of different periods.
        snapshots.sort(key=lambda s: (_period(prefix, s.created_at) == period, s.created_at), reverse=True)
        periods = set()
        distinct, extra = [], []
        for snapshot in snapshots:
            if not _matches_digest(snapshot):
                continue
            key = _period(prefix, snapshot.created_at)
            if key in periods:
                extra.append(snapshot)
            else:
                periods.add(key)
                distinct.append(snapshot)
        for old in (distinct + extra)[keep:]:
            old.path.unlink()
            old.path.with_suffix(".json").unlink(missing_ok=True)
