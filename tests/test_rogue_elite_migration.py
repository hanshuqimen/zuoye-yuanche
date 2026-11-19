"""Schema0031 FREE history survives explicit elite-supply migration or rollback."""

import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient
from rogue_qa_rules import add_empty_closure_ledger
from test_rogue_paid_training import buy, leave, promote
from test_rogue_temporary import install_temporary as install_temporary  # noqa: F401
from test_rogue_temporary import prepare
from test_rogue_temporary import temporary_runtime as temporary_runtime  # noqa: F401
from test_rogue_training import choice, move
from test_rogue_training import training_runtime as training_runtime  # noqa: F401
from test_roguelike_initial import current
from test_roguelike_state import rows

from terralocal.server.main import create_game_app
from terralocal.server.persistence import migrations
from terralocal.server.services.runtime import Runtime


def schema_0031(path):
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("CREATE TABLE rlv2_options_0031 (run_id VARCHAR(36) NOT NULL, ticket_ordinal INTEGER NOT NULL, "
            "ordinal INTEGER NOT NULL, source_operator_id INTEGER, kind VARCHAR(16) NOT NULL, "
            "hope_cost INTEGER NOT NULL, character JSON NOT NULL, target_char_ordinal INTEGER, "
            "PRIMARY KEY(run_id,ticket_ordinal,ordinal), "
            "FOREIGN KEY(run_id,ticket_ordinal) REFERENCES rlv2_tickets(run_id,ordinal) ON DELETE CASCADE, "
            "CONSTRAINT rlv2_option_values CHECK(ordinal>=0 AND hope_cost>=0 AND kind IN ('NORMAL','THIRD_LOW','UPGRADE','UPGRADE_PAID','FREE')), "
            "CONSTRAINT rlv2_free_source CHECK(kind!='FREE' OR (hope_cost=0 AND source_operator_id IS NULL)), "
            "CONSTRAINT rlv2_upgrade_target CHECK((kind='UPGRADE' AND target_char_ordinal IS NOT NULL AND target_char_ordinal>=1 AND hope_cost=0) OR "
            "(kind='UPGRADE_PAID' AND target_char_ordinal IS NOT NULL AND target_char_ordinal>=1 AND hope_cost>0) OR "
            "(kind NOT IN ('UPGRADE','UPGRADE_PAID') AND target_char_ordinal IS NULL)))")
        con.execute("INSERT INTO rlv2_options_0031 SELECT * FROM rlv2_recruit_options")
        con.execute("DROP TABLE rlv2_recruit_options")
        con.execute("ALTER TABLE rlv2_options_0031 RENAME TO rlv2_recruit_options")
        assert con.execute("SELECT count(*) FROM rlv2_tickets WHERE elite_pool!='[]'").fetchone()[0] == 0
        con.execute("ALTER TABLE rlv2_tickets DROP COLUMN elite_pool")
        con.execute("ALTER TABLE rlv2_tickets DROP COLUMN direct_pool")
        con.execute("DROP TABLE rlv2_run_closures")
        for name in ("rlv2_bank_visits", "rlv2_bank_wallets"):
            assert con.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0] == 0
            con.execute('DROP TABLE "' + name + '"')
        con.execute("UPDATE alembic_version SET version_num=?", (migrations.ROGUE_FREE_REVISION,))
        assert not con.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("rollback", [False, True])
def test_free_training_history_and_all_old_columns_survive_0031_or_atomic_rollback(temporary_runtime, monkeypatch, rollback):
    runtime, token = temporary_runtime
    prepare(runtime, token, "rogue_1_recruit_ticket_pioneer_sp", extended=True)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        free = next(c for c in current(runtime, token)["inventory"]["recruit"]["3"]["list"] if c["type"] == "FREE")
        assert promote(client, token, free["instId"]).status_code == 200
        assert leave(client, token).status_code == 200
        assert move(client, token, 1, "rest").status_code == 200
        assert choice(client, token, "choice_rest_3", "hope").status_code == 200
        assert choice(client, token, "choice_leave", "rest-leave").status_code == 200
        assert move(client, token, 2, "later").status_code == 200
        assert buy(client, token, "later-buy").status_code == 200
        option = next(c for c in current(runtime, token)["inventory"]["recruit"]["4"]["list"] if c["type"] == "FREE")
        assert promote(client, token, option["instId"], ticket="4", seq="upgrade").status_code == 200
        assert leave(client, token, "later-leave").status_code == 200
    expected = runtime.sync(token)["user"]
    runtime.database.close()
    schema_0031(runtime.database.path)
    before = rows(runtime.database.path)
    if rollback:
        original = migrations._elite_recruit_schema

        def fail(connection, operations):
            original(connection, operations)
            raise ValueError("Authored elite migration failure after column and constraint rebuild")

        monkeypatch.setattr(migrations, "_elite_recruit_schema", fail)
        with pytest.raises(ValueError, match="after column"):
            Runtime(runtime.settings)
        assert rows(runtime.database.path) == before
        monkeypatch.setattr(migrations, "_elite_recruit_schema", original)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected
        after = rows(runtime.database.path)
        assert len(before) == 74 and len(after) == 77
        assert after["rlv2_bank_visits"] == after["rlv2_bank_wallets"] == []
        for name, old in before.items():
            if name == "alembic_version":
                assert after[name] == [(migrations.REVISION,)]
            elif name == "rlv2_tickets":
                assert [r[:-2] for r in after[name]] == old
                assert all(r[-2:] == ("[]", "[]") for r in after[name])
            else:
                assert after[name] == old
    finally:
        reopened.database.close()


@pytest.mark.parametrize("current_revision", migrations.CURRENT_REVISIONS)
def test_current_stamp_with_0031_schema_is_rejected_before_writes(temporary_runtime, current_revision):
    runtime, _ = temporary_runtime
    runtime.database.close()
    schema_0031(runtime.database.path)
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("UPDATE alembic_version SET version_num=?", (current_revision,))
        if current_revision == migrations.REVISION:
            add_empty_closure_ledger(con)
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before
