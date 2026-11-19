"""Explicit SQLite transactions, serialized writes, and safe online backups."""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from terralocal.server.persistence.models import ServerClockState


class Database:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
            pool_size=5,
            max_overflow=0,
        )

        @event.listens_for(self.engine, "connect")
        def connection_setup(connection, _record):
            connection.isolation_level = None
            cursor = connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

        @event.listens_for(self.engine, "begin")
        def transaction_begin(connection):
            connection.exec_driver_sql("BEGIN IMMEDIATE" if connection.info.get("write") else "BEGIN")

    def initialize(self) -> None:
        from terralocal.server.persistence.migrations import upgrade

        upgrade(self.engine)
        with self.transaction() as session:
            if session.get(ServerClockState, 1) is None:
                session.add(ServerClockState(id=1, mode="realtime", offset=0))

    @contextmanager
    def transaction(self, *, write: bool = True) -> Iterator[Session]:
        with self.engine.connect() as connection:
            connection.info["write"] = write
            try:
                with Session(bind=connection, expire_on_commit=False) as session, session.begin():
                    yield session
                    session.flush()
            finally:
                connection.info["write"] = False

    def backup(self, destination: Path) -> Path:
        destination = destination.resolve()
        if destination == self.path:
            raise ValueError("备份目标不能是正在使用的数据库")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=destination.parent) as folder:
            temporary = Path(folder) / "backup.sqlite3"
            with (closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as source,
                  closing(sqlite3.connect(temporary)) as target):
                source.backup(target)
                result = target.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise ValueError("备份完整性校验失败")
            temporary.replace(destination)
        return destination

    def integrity(self) -> str:
        with closing(sqlite3.connect(self.path)) as connection:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])

    def close(self) -> None:
        self.engine.dispose()
