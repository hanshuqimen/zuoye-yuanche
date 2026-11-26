"""Save-only regression coverage for the isolated Crisis V2 profile."""

import sqlite3
from contextlib import closing

import pytest

from terralocal.server.domain.crisis_v2 import preflight


def test_crisis_qa_rejects_feature_tables_without_base_accounts(tmp_path):
    path = tmp_path / "damaged.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE crisis_v2_accounts (account_id, gamedata_hash, catalog_hash, policy_version)"
        )
        connection.execute("CREATE TABLE crisis_v2_seasons (account_id)")
        connection.execute("CREATE TABLE crisis_v2_maps (account_id)")
        connection.commit()
    before = path.read_bytes()

    with pytest.raises(ValueError, match="存档表不完整"):
        preflight(None, path, require_existing_binding=True)

    assert path.read_bytes() == before


@pytest.mark.parametrize("has_existing_account", [False, True])
def test_crisis_qa_distinguishes_empty_older_save_from_legacy_account(tmp_path, has_existing_account):
    path = tmp_path / "older.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY)")
        if has_existing_account:
            connection.execute("INSERT INTO accounts (id) VALUES (1)")
        connection.commit()
    before = path.read_bytes()

    if has_existing_account:
        with pytest.raises(ValueError, match="不转换已有账号"):
            preflight(None, path, require_existing_binding=True)
    else:
        preflight(None, path, require_existing_binding=True)

    preflight(None, path)
    assert path.read_bytes() == before
