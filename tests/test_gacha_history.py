"""Personal WebView records: auth, pagination, isolation and durable draw truth."""

import hashlib
import json
import time

import pytest
import test_standard_headhunting
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_headhunting import head_runtime, login, pull  # noqa: F401 -- dependent fixtures
from test_recruitment import recruit_runtime  # noqa: F401 -- dependent fixtures
from test_standard_headhunting import CLASSIC, DOUBLE

from terralocal.server.domain import accounts
from terralocal.server.domain.clock import MAX_TIMESTAMP
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

modern_runtime = test_standard_headhunting.modern_runtime


def u8_token(runtime, name="Doctor"):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name=name, kind="u8")["secret"]


def query(client, code, **params):
    return client.get("/api/gacha/history", params={"code": code, "category": "standard", **params})


def history_row(account_id, banner_id=DOUBLE, *, drawn_at=1_800_000_000, **changes):
    return m.GachaHistory(account_id=account_id, banner_id=banner_id, char_id="char_recruit_2",
                          rarity=2, is_new=False, drawn_at=drawn_at, **changes)


def gameplay(runtime):
    with runtime.database.transaction(write=False) as session:
        return {name: [tuple(row) for row in session.execute(table.select().order_by(*table.primary_key))]
                for name, table in m.Base.metadata.tables.items() if name != "alembic_version"}


def test_missing_original_webview_fails_explicitly_without_exporting_personal_records(client, runtime):
    response = client.get("/gacha", params={"pool_id": "unknown", "code": "NOT-AN-EMBEDDED-CREDENTIAL"})
    assert response.status_code == 503
    assert "NOT-AN-EMBEDDED-CREDENTIAL" not in response.text
    # The shell is public; the personal record API still requires a credential.
    assert client.get("/api/gacha/history", params={"category": "standard"}).status_code == 422


@pytest.mark.parametrize("kind", ["sdk", "game", "expired-u8", "invalid"])
def test_personal_records_require_valid_u8_stage_without_leaking_secrets(modern_runtime, kind):
    runtime = modern_runtime
    with runtime.database.transaction() as session:
        code = (accounts.login(session, runtime.settings, name="Doctor", kind=kind.removeprefix("expired-"))[
            "secret"] if kind != "invalid" else "INVALID-PRIVATE-CREDENTIAL")
        if kind == "expired-u8":
            row = session.scalar(select(m.LocalSession).where(
                m.LocalSession.token_hash == hashlib.sha256(code.encode()).hexdigest()))
            row.expires_at = int(time.time()) - 1
    before = gameplay(runtime)
    with TestClient(create_game_app(runtime)) as client:
        for path, params in (("/api/gacha/cate", {}), ("/api/gacha/history", {"category": "standard"})):
            response = client.get(path, params={"code": code, **params})
            assert response.status_code == 401 and code not in response.text
    assert gameplay(runtime) == before
    for path in (runtime.settings.data_dir / "logs").glob("*.jsonl"):
        assert code not in path.read_text("utf-8")


def test_category_activation_archived_records_and_account_scoping(modern_runtime):
    runtime = modern_runtime
    with runtime.database.transaction() as session:
        other = accounts.create_account(session, runtime.data, "Other")
        session.add_all([history_row(1), history_row(1, "OLD_POOL"), history_row(other.id, "FOREIGN_ONLY"),
                         history_row(1, "RECRUIT")])
    code = u8_token(runtime)
    before = gameplay(runtime)
    with TestClient(create_game_app(runtime)) as client:
        response = client.get("/api/gacha/cate", params={"code": code, "poolId": CLASSIC})
        assert response.status_code == 200 and response.json()["code"] == 0
        assert [item["id"] for item in response.json()["data"] if item["active"]] == ["classic"]
        assert client.get("/api/gacha/cate", params={"code": code, "poolId": "FOREIGN_ONLY"}).status_code == 404
        archived = client.get("/api/gacha/cate", params={"code": code, "poolId": "OLD_POOL"}).json()["data"]
        assert [item["id"] for item in archived if item["active"]] == ["archived"]
        history = query(client, code, category="archived").json()["data"]
        assert [item["poolName"] for item in history["list"]] == ["OLD_POOL"]
        normal = query(client, code).json()["data"]["list"]
        assert len(normal) == 1 and all(item["poolName"] != "RECRUIT" for item in normal)
        assert response.headers["cache-control"] == "no-store"
    assert gameplay(runtime) == before


def test_same_second_pagination_new_rows_and_server_time_reversal_have_no_missing_records(modern_runtime):
    runtime, code = modern_runtime, u8_token(modern_runtime)
    with runtime.database.transaction() as session:
        # Ten-pull batches share a timestamp; a second batch may share it too.
        session.add_all([history_row(1) for _ in range(25)] + [history_row(1, drawn_at=1_799_999_999)])
        session.flush()
        original = list(session.scalars(select(m.GachaHistory.id).order_by(
            m.GachaHistory.drawn_at.desc(), m.GachaHistory.id.desc())))
    with TestClient(create_game_app(runtime)) as client:
        first = query(client, code).json()["data"]
        assert len(first["list"]) == 10 and first["hasMore"] is True
        assert first["list"][0]["gachaTs"] == "1800000000000"
        with runtime.database.transaction() as session:
            session.add(history_row(1, drawn_at=1_800_000_001))
        records = first["list"]
        cursor = records[-1]
        while True:
            response = query(client, code, gachaTs=cursor["gachaTs"], pos=cursor["pos"])
            assert response.status_code == 200
            page = response.json()["data"]
            records += page["list"]
            if not page["hasMore"]:
                break
            cursor = page["list"][-1]
        assert [int(item["pos"]) for item in records] == original
        assert len({item["pos"] for item in records}) == 26
        assert query(client, code).json()["data"]["list"][0]["gachaTs"] == "1800000001000"


@pytest.mark.parametrize("params", [
    {"pos": "1"}, {"gachaTs": "1800000000000"}, {"pos": "0", "gachaTs": "1800000000000"},
    {"pos": "1", "gachaTs": "1800000000001"}, {"pos": "1", "gachaTs": "1800000001000"},
    {"pos": "999999", "gachaTs": "1800000000000"}, {"pos": "9223372036854775808", "gachaTs": "0"},
    {"pos": "1", "gachaTs": "-1"}, {"pos": "1 OR 1=1", "gachaTs": "1800000000000"},
    {"category": "NOT_A_CATEGORY"},
])
def test_invalid_and_partial_history_cursors_fail_without_writes(modern_runtime, params):
    runtime, code = modern_runtime, u8_token(modern_runtime)
    with runtime.database.transaction() as session:
        session.add(history_row(1))
    before = gameplay(runtime)
    with TestClient(create_game_app(runtime)) as client:
        assert query(client, code, **params).status_code in {400, 422}
    assert gameplay(runtime) == before


def test_foreign_account_and_other_category_cursors_cannot_read_or_skip_records(modern_runtime):
    runtime, code = modern_runtime, u8_token(modern_runtime)
    with runtime.database.transaction() as session:
        other = accounts.create_account(session, runtime.data, "Other")
        rows = [history_row(1), history_row(other.id), history_row(1, CLASSIC)]
        session.add_all(rows)
        session.flush()
        foreign_positions = [row.id for row in rows[1:]]
    with TestClient(create_game_app(runtime)) as client:
        for position in foreign_positions:
            assert query(client, code, pos=str(position), gachaTs="1800000000000").status_code == 400
        assert len(query(client, code).json()["data"]["list"]) == 1


def test_successful_read_and_empty_category_do_not_restore_sanity_or_mutate_progress(modern_runtime):
    runtime, code = modern_runtime, u8_token(modern_runtime)
    with runtime.database.transaction() as session:
        sanity = session.get(m.SanityState, 1)
        sanity.current, sanity.last_recovery_at = 0, 1_799_000_000
        session.add(history_row(1))
    before = gameplay(runtime)
    with TestClient(create_game_app(runtime)) as client:
        assert query(client, code).status_code == 200
        assert query(client, code, category="limited").json()["data"] == {"list": [], "hasMore": False}
    assert gameplay(runtime) == before


def test_real_draw_retries_preserve_exact_history_through_backup_restore_and_restart(modern_runtime):
    runtime, game_code = modern_runtime, login(modern_runtime)
    code = u8_token(runtime)
    with TestClient(create_game_app(runtime)) as client:
        responses = [pull(client, game_code, 77, count=10, poolId=DOUBLE) for _ in range(3)]
        assert all(response.status_code == 200 for response in responses)
        assert all(response.json() == responses[0].json() for response in responses)
        response = query(client, code)
        assert response.status_code == 200
        expected = response.json()
        assert len(expected["data"]["list"]) == 10 and expected["data"]["hasMore"] is False
        with runtime.database.transaction(write=False) as session:
            rows = list(session.scalars(select(m.GachaHistory).where(
                m.GachaHistory.account_id == 1).order_by(m.GachaHistory.id.desc())))
            assert len(rows) == 10
            assert [item["pos"] for item in expected["data"]["list"]] == [str(row.id) for row in rows]
            assert [item["isNew"] for item in expected["data"]["list"]] == [row.is_new for row in rows]
            assert [item["rarity"] for item in expected["data"]["list"]] == [row.rarity for row in rows]
            assert [item["charName"] for item in expected["data"]["list"]] == [
                runtime.data.characters[row.char_id]["name"] for row in rows]
        backup = BackupService(runtime).create()["name"]
        with runtime.database.transaction() as session:
            session.add(history_row(1))
        BackupService(runtime).restore(backup)
        assert query(client, code).json() == expected
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(restarted)) as client:
            assert query(client, code).json() == expected
    finally:
        restarted.database.close()


def test_history_errors_and_responses_never_embed_query_credentials_in_logs(modern_runtime):
    runtime, code = modern_runtime, u8_token(modern_runtime)
    with TestClient(create_game_app(runtime)) as client:
        assert query(client, code, category="invalid").status_code == 400
        assert query(client, code).status_code == 200
    for path in (runtime.settings.data_dir / "logs").glob("*.jsonl"):
        records = path.read_text("utf-8")
        assert code not in records
        for line in records.splitlines():
            entry = json.loads(line)
            if entry.get("status") == 400:
                assert entry["query_keys"] == ["category", "code"]


def test_actual_classic_and_newcomer_draws_follow_their_record_categories(modern_runtime):
    runtime, game_code = modern_runtime, login(modern_runtime)
    code = u8_token(runtime)
    with TestClient(create_game_app(runtime)) as client:
        for sequence, pool_id in enumerate((DOUBLE, CLASSIC, "BOOT_0_1_3"), start=1):
            assert pull(client, game_code, sequence, poolId=pool_id).status_code == 200
        normal = query(client, code).json()["data"]["list"]
        classic = query(client, code, category="classic").json()["data"]["list"]
        assert {item["poolName"] for item in normal} == {DOUBLE, "BOOT_0_1_3"}
        assert [item["poolName"] for item in classic] == [CLASSIC]


@pytest.mark.parametrize("field,value", [("rarity", -1), ("rarity", 6), ("drawn_at", -1),
                                         ("drawn_at", MAX_TIMESTAMP + 1),
                                         ("drawn_at", 253402300800)])
def test_corrupt_history_is_an_explicit_error_instead_of_empty_success(modern_runtime, field, value):
    runtime, code = modern_runtime, u8_token(modern_runtime)
    with runtime.database.transaction() as session:
        row = history_row(1)
        setattr(row, field, value)
        session.add(row)
    before = gameplay(runtime)
    with TestClient(create_game_app(runtime)) as client:
        response = query(client, code)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "INVALID_GACHA_HISTORY"
    assert gameplay(runtime) == before


def test_ninety_day_display_window_preserves_stored_history_and_follows_the_server_clock(modern_runtime):
    runtime, code = modern_runtime, u8_token(modern_runtime)
    cutoff = 1_800_000_000 - 90 * 86400
    with runtime.database.transaction() as session:
        old, edge, recent = [history_row(1, drawn_at=at) for at in (cutoff - 1, cutoff, cutoff + 1)]
        session.add_all([old, edge, recent])
        session.flush()
        ids = [str(row.id) for row in (old, edge, recent)]
    before = gameplay(runtime)
    with TestClient(create_game_app(runtime)) as client:
        records = query(client, code).json()["data"]["list"]
        assert [row["pos"] for row in records] == ids[:0:-1]
        assert gameplay(runtime) == before
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += 1
        changed = gameplay(runtime)
        assert [row["pos"] for row in query(client, code).json()["data"]["list"]] == [ids[2]]
        assert gameplay(runtime) == changed
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at = cutoff
        rewind = gameplay(runtime)
        assert [row["pos"] for row in query(client, code).json()["data"]["list"]] == ids[::-1]
        assert gameplay(runtime) == rewind


def test_expiring_display_cursor_returns_empty_tail_without_deleting_older_history(modern_runtime):
    runtime, code = modern_runtime, u8_token(modern_runtime)
    cutoff = 1_800_000_000 - 90 * 86400
    with runtime.database.transaction() as session:
        row = history_row(1, drawn_at=cutoff)
        session.add(row)
        session.flush()
        cursor = {"gachaTs": str(cutoff * 1000), "pos": str(row.id)}
        session.get(m.ServerClockState, 1).fixed_at += 1
    before = gameplay(runtime)
    with TestClient(create_game_app(runtime)) as client:
        response = query(client, code, **cursor)
        assert response.status_code == 200 and response.json()["data"] == {"list": [], "hasMore": False}
    assert gameplay(runtime) == before
