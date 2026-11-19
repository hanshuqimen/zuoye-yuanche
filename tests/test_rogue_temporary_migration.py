"""0030 paid history survives FREE constraint admission, including rollback."""

import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient
from rogue_qa_rules import add_empty_closure_ledger
from test_rogue_paid_training import buy, candidate, leave, promote, shop
from test_rogue_training import move
from test_rogue_training import training_runtime as training_runtime  # noqa: F401
from test_roguelike_state import rows

from terralocal.server.main import create_game_app
from terralocal.server.persistence import migrations
from terralocal.server.services.runtime import Runtime


def schema_0030(path):
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("CREATE TABLE rlv2_options_0030 (run_id VARCHAR(36) NOT NULL, ticket_ordinal INTEGER NOT NULL, "
            "ordinal INTEGER NOT NULL, source_operator_id INTEGER, kind VARCHAR(16) NOT NULL, "
            "hope_cost INTEGER NOT NULL, character JSON NOT NULL, target_char_ordinal INTEGER, "
            "PRIMARY KEY(run_id,ticket_ordinal,ordinal), "
            "FOREIGN KEY(run_id,ticket_ordinal) REFERENCES rlv2_tickets(run_id,ordinal) ON DELETE CASCADE, "
            "CONSTRAINT rlv2_option_values CHECK(ordinal>=0 AND hope_cost>=0 AND kind IN ('NORMAL','THIRD_LOW','UPGRADE','UPGRADE_PAID')), "
            "CONSTRAINT rlv2_upgrade_target CHECK((kind='UPGRADE' AND target_char_ordinal IS NOT NULL AND target_char_ordinal>=1 AND hope_cost=0) OR "
            "(kind='UPGRADE_PAID' AND target_char_ordinal IS NOT NULL AND target_char_ordinal>=1 AND hope_cost>0) OR "
            "(kind NOT IN ('UPGRADE','UPGRADE_PAID') AND target_char_ordinal IS NULL)))")
        con.execute("INSERT INTO rlv2_options_0030 SELECT * FROM rlv2_recruit_options")
        con.execute("DROP TABLE rlv2_recruit_options")
        con.execute("ALTER TABLE rlv2_options_0030 RENAME TO rlv2_recruit_options")
        con.execute("DROP TABLE rlv2_run_closures")
        for name in ("rlv2_bank_visits", "rlv2_bank_wallets", "rlv2_battle_loot_plans"):
            assert con.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0] == 0
            con.execute('DROP TABLE "' + name + '"')
        con.execute("UPDATE alembic_version SET version_num=?", (migrations.ROGUE_PAID_REVISION,))
        assert not con.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("training_runtime", [("PIONEER", 4)], indirect=True)
@pytest.mark.parametrize("rollback", [False, True])
def test_paid_history_and_all_rows_survive_0030_upgrade_or_atomic_rollback(training_runtime, monkeypatch, rollback):
    runtime, token = training_runtime
    shop(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        assert promote(client, token, candidate(runtime, token)["instId"]).status_code == 200
        assert leave(client, token).status_code == 200
    expected = runtime.sync(token)["user"]
    runtime.database.close()
    schema_0030(runtime.database.path)
    before = rows(runtime.database.path)
    if rollback:
        original = migrations._free_recruit_schema

        def fail(connection, operations):
            original(connection, operations)
            raise ValueError("Authored FREE migration failure after rebuild")

        monkeypatch.setattr(migrations, "_free_recruit_schema", fail)
        with pytest.raises(ValueError, match="after rebuild"):
            Runtime(runtime.settings)
        assert rows(runtime.database.path) == before
        monkeypatch.setattr(migrations, "_free_recruit_schema", original)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected
        after = rows(runtime.database.path)
        assert len(before) == 74 and len(after) == 78
        assert after["rlv2_bank_visits"] == after["rlv2_bank_wallets"] == []
        assert after["rlv2_battle_loot_plans"] == []
        assert after["rlv2_run_closures"] == []
        assert after["alembic_version"] == [(migrations.REVISION,)]
        assert {name: after[name] for name in before if name != "alembic_version"} == {
            name: values for name, values in before.items() if name != "alembic_version"}
    finally:
        reopened.database.close()


@pytest.mark.parametrize("current_revision", migrations.CURRENT_REVISIONS)
def test_latest_stamp_with_0030_constraints_is_rejected_before_writes(training_runtime, current_revision):
    runtime, _ = training_runtime
    runtime.database.close()
    schema_0030(runtime.database.path)
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("UPDATE alembic_version SET version_num=?", (current_revision,))
        if current_revision == migrations.REVISION:
            add_empty_closure_ledger(con)
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before
