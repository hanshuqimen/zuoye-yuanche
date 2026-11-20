"""SDK persistence, credential scope and additive migration regressions."""

import json
import sqlite3

import pytest
from sqlalchemy import select

from terralocal.server.domain import accounts
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import LEGACY_REVISION, REVISION
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def u8_login(client, name="Doctor"):
    sdk = client.post("/local/v1/sdk/login", json={"name": name}).json()
    return client.post("/u8/user/v1/getToken", json={"appId": "1", "platform": 1, "channelId": "1",
                       "extension": json.dumps({"code": sdk["code"]})}).json()["token"]


def notice(client, code):
    return client.get("/u8/user/auth/v1/agreement_version", params={"code": code})


def test_local_notice_requires_acceptance_is_idempotent_and_survives_restart(client, runtime):
    code = u8_login(client)
    initial = notice(client, code).json()["data"]
    assert initial["authorized"] is False and initial["isLatestUserAgreement"] is False
    for url in initial["agreementUrl"].values():
        assert url.startswith(runtime.settings.advertised_url + "/protocol/plain/ak/")
        page = client.get(url)
        assert page.status_code == 200 and "TerraLocal 本地存档说明" in page.text
    accepted = client.post("/u8/user/auth/v1/update_agreement", json={"code": code})
    assert accepted.json()["status"] == 0
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 3600
    assert client.post("/u8/user/auth/v1/update_agreement", json={"code": code}).status_code == 200
    assert notice(client, code).json()["data"]["isLatestUserAgreement"] is True
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.AgreementConsent, (1, 1)).accepted_at == 1_800_000_000
        assert len(list(session.scalars(select(m.AuditLog).where(
            m.AuditLog.action == "local-notice-accept")))) == 1
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with restarted.database.transaction(write=False) as session:
            assert session.get(m.AgreementConsent, (1, 1)).accepted_at == 1_800_000_000
    finally:
        restarted.database.close()


def test_notice_account_isolation_and_stale_versions(client, runtime):
    first = u8_login(client)
    with runtime.database.transaction() as session:
        second = accounts.create_account(session, runtime.data, "Second")
        session.add(m.AgreementConsent(account_id=second.id, version=0, accepted_at=123))
    second_code = u8_login(client, "Second")
    assert client.post("/u8/user/auth/v1/update_agreement", json={"code": first}).status_code == 200
    state = notice(client, second_code).json()["data"]
    assert state["authorized"] is True and state["isLatestUserAgreement"] is False
    assert state["updatedAgreement"] == '["service","privacy"]'
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.AgreementConsent, (second.id, 1)) is None


def test_notice_rejects_wrong_stage_expired_and_invalid_credentials_without_logging(client, runtime, token):
    assert notice(client, token).status_code == 401
    assert client.post("/u8/user/auth/v1/update_agreement", json={"code": token}).status_code == 401
    sdk = client.post("/local/v1/sdk/login", json={"name": "Doctor"}).json()["code"]
    assert notice(client, sdk).status_code == 401
    code = u8_login(client)
    with runtime.database.transaction() as session:
        row = session.scalar(select(m.LocalSession).where(m.LocalSession.kind == "u8"))
        row.expires_at = 0
    assert notice(client, code).status_code == 401
    secret = "SYNTHETIC-NOTICE-SECRET-DO-NOT-LOG"
    assert notice(client, secret).status_code == 401
    assert client.post("/u8/user/auth/v1/update_agreement", json={"code": secret}).status_code == 401
    assert client.post("/u8/user/auth/v1/update_agreement", json={"code": code, "uid": "other"}).status_code == 422
    for path in (runtime.settings.data_dir / "logs").glob("*.jsonl"):
        body = path.read_text("utf-8")
        assert secret not in body and code not in body
    with runtime.database.transaction(write=False) as session:
        assert session.scalar(select(m.AgreementConsent)) is None


def test_orders_are_account_scoped_reads_of_only_ready_orders(client, runtime, token):
    with runtime.database.transaction() as session:
        other = accounts.create_account(session, runtime.data, "Other")
        for owner, order_id, state, date in [
            (1, "later", "READY", 20), (1, "first", "READY", 10),
            (1, "done", "CONFIRMED", 0), (1, "cancelled", "CANCELLED", 0),
            (other.id, "foreign", "READY", 0),
        ]:
            session.add(m.LocalOrder(account_id=owner, order_id=order_id, product_id="local-product",
                                     state=state, created_at=date))
    before = runtime.sync(token)
    response = client.post("/pay/getUnconfirmedOrderIdList", json={}, headers={"secret": token})
    assert response.json() == {"orderIdList": ["first", "later"],
                               "playerDataDelta": {"modified": {}, "deleted": {}}}
    assert runtime.sync(token) == before
    assert client.post("/pay/getUnconfirmedOrderIdList", json={}).status_code == 401
    assert client.post("/pay/getUnconfirmedOrderIdList", json={}, headers={"secret": token,
                       "uid": other.uid}).status_code == 401
    assert client.post("/pay/getUnconfirmedOrderIdList", json={}, headers={
        "secret": u8_login(client)}).status_code == 401


def make_legacy_database(runtime):
    # Produce the actual old schema, retaining all old rows. Isolated fixture only.
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        from schema_legacy import remove_crisis_v2_tables

        remove_crisis_v2_tables(connection)
        connection.execute("DROP TABLE operator_acquisitions")
        connection.execute("DROP TABLE owned_furniture")
        connection.execute("ALTER TABLE battle_sessions DROP COLUMN native_context")
        connection.execute("DROP TABLE agreement_consents")
        connection.execute("DROP TABLE local_orders")
        connection.execute("DROP TABLE story_completions")
        connection.execute("ALTER TABLE operators DROP COLUMN voice_language")
        for column in ("policy_version", "gamedata_hash"):
            connection.execute(f"ALTER TABLE gacha_pity DROP COLUMN {column}")
        for column in ("duration_seconds", "max_finishes_at", "retained_tags", "result_char_id",
                       "policy_version", "gamedata_hash"):
            connection.execute(f"ALTER TABLE recruit_slots DROP COLUMN {column}")
        connection.execute("UPDATE alembic_version SET version_num = ?", (LEGACY_REVISION,))


def test_additive_migration_preserves_existing_player_state(runtime, token):
    before = runtime.sync(token)
    make_legacy_database(runtime)
    runtime.database.initialize()
    assert runtime.sync(token) == before
    with sqlite3.connect(runtime.database.path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
    runtime.database.initialize()
    assert runtime.sync(token) == before
    with sqlite3.connect(runtime.database.path) as connection:
        connection.execute("UPDATE alembic_version SET version_num = 'future-unknown'")
    unknown = Database(runtime.database.path)
    try:
        with pytest.raises(ValueError, match="不能覆盖或降级"):
            unknown.initialize()
    finally:
        unknown.close()


def test_legacy_backup_is_recorded_truthfully_and_upgraded_on_restore(runtime, token):
    before = runtime.sync(token)
    make_legacy_database(runtime)
    service = BackupService(runtime)
    saved = service.create()
    assert saved["database_revision"] == LEGACY_REVISION
    runtime.database.initialize()
    with runtime.database.transaction() as session:
        session.get(m.PlayerProfile, 1).nickname = "Changed"
    service.restore(saved["name"])
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.scalar(select(m.AgreementConsent)) is None
