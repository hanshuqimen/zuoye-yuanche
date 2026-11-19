"""Real0032 column/constraint layout and elite offers survive the current schema."""

import hashlib
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient
from rogue_qa_rules import add_empty_closure_ledger
from test_rogue_elite import prepare
from test_rogue_paid_training import buy
from test_rogue_temporary import install_temporary as install_temporary  # noqa: F401
from test_rogue_temporary import temporary_runtime as temporary_runtime  # noqa: F401
from test_rogue_training import move
from test_rogue_training import training_runtime as training_runtime  # noqa: F401
from test_roguelike_state import rows

from terralocal.server.main import create_game_app
from terralocal.server.persistence import migrations
from terralocal.server.services.runtime import Runtime


def schema_0032(path):
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA foreign_keys=OFF")
        sql = con.execute("SELECT sql FROM sqlite_master WHERE name='rlv2_recruit_options'").fetchone()[0]
        sql, count = re.subn(r",\s*CONSTRAINT rlv2_direct_source CHECK \([^)]*\)", "", sql)
        assert count == 1 and "'DIRECT'" in sql
        con.execute(sql.replace("rlv2_recruit_options", "rlv2_options_0032", 1).replace(",'DIRECT'", ""))
        con.execute("INSERT INTO rlv2_options_0032 SELECT * FROM rlv2_recruit_options")
        con.execute("DROP TABLE rlv2_recruit_options")
        con.execute("ALTER TABLE rlv2_options_0032 RENAME TO rlv2_recruit_options")
        assert not con.execute("SELECT 1 FROM rlv2_tickets WHERE direct_pool!='[]'").fetchall()
        con.execute("ALTER TABLE rlv2_tickets DROP COLUMN direct_pool")
        con.execute("DROP TABLE rlv2_run_closures")
        # These tables did not exist in0032. Never leave future tables in the
        # simulated legacy source or merely inflate the expected old count.
        for name in ("rlv2_bank_visits", "rlv2_bank_wallets"):
            assert con.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0] == 0
            con.execute('DROP TABLE "' + name + '"')
        con.execute("UPDATE alembic_version SET version_num=?", (migrations.ROGUE_ELITE_REVISION,))
        assert not con.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("rollback", [False, True])
def test_schema32_elite_offer_scope_and_all_old_columns_survive_atomic_migration(temporary_runtime, monkeypatch, rollback):
    runtime, token = temporary_runtime
    prepare(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
    expected = runtime.sync(token)["user"]
    runtime.database.close()
    schema_0032(runtime.database.path)
    before = rows(runtime.database.path)
    if rollback:
        original = migrations._direct_recruit_schema

        def fail(connection, operations):
            original(connection, operations)
            raise ValueError("Authored rollback after direct column and constraints")

        monkeypatch.setattr(migrations, "_direct_recruit_schema", fail)
        with pytest.raises(ValueError, match="after direct"):
            Runtime(runtime.settings)
        assert rows(runtime.database.path) == before
        monkeypatch.setattr(migrations, "_direct_recruit_schema", original)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected
        after = rows(runtime.database.path)
        assert len(before) == 74 and len(after) == 77
        assert after["rlv2_bank_visits"] == after["rlv2_bank_wallets"] == []
        for name, values in before.items():
            if name == "alembic_version":
                assert after[name] == [(migrations.REVISION,)]
            elif name == "rlv2_tickets":
                assert [row[:-1] for row in after[name]] == values
                assert all(row[-1] == "[]" for row in after[name])
            else:
                assert after[name] == values
    finally:
        reopened.database.close()


@pytest.mark.parametrize("current_revision", migrations.CURRENT_REVISIONS)
def test_latest_stamp_with_schema32_is_rejected_before_writes(temporary_runtime, current_revision):
    runtime, _ = temporary_runtime
    runtime.database.close()
    schema_0032(runtime.database.path)
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("UPDATE alembic_version SET version_num=?", (current_revision,))
        if current_revision == migrations.REVISION:
            add_empty_closure_ledger(con)
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before
