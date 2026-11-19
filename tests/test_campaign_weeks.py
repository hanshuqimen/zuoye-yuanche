"""Authored income fixtures validate reset transactions, not native payouts."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from test_campaign_persistence import camp_runtime as camp_runtime
from test_campaign_persistence import camp_token as camp_token
from test_campaign_persistence import (
    database_rows,
    seed_observed_state,
    set_time,
    user,
)

from terralocal.server.domain.accounts import create_account
from terralocal.server.domain.campaign_weeks import active_week
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import CAMPAIGN_REVISION, REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def next_boundary(runtime):
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        period = active_week(ctx, session.get(m.CampaignAccount, 1)).period
    start = datetime.fromisoformat(period).replace(hour=4, tzinfo=timezone(timedelta(hours=8)))
    return int((start + timedelta(days=7) - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds())


def ledger(runtime):
    with runtime.database.transaction(write=False) as session:
        return [(r.period, r.earned_fee, r.closed_at) for r in
                sorted(Context(session, runtime.data, 1).read_rows(m.CampaignWeek), key=lambda r: r.period)]


def test_monday_0400_resets_income_once_preserves_cap_claims_wallet_and_history(camp_runtime, camp_token):
    seed_observed_state(camp_runtime)
    boundary = next_boundary(camp_runtime)
    set_time(camp_runtime, boundary - 1)
    before = user(camp_runtime, camp_token)
    assert before['campaignsV2']['campaignCurrentFee'] == 100
    original = ledger(camp_runtime)
    set_time(camp_runtime, boundary)
    first = camp_runtime.sync(camp_token)
    expected = before['campaignsV2'] | {'campaignCurrentFee': 0}
    assert first['user']['campaignsV2'] == expected
    assert first['user']['status']['gold'] == before['status']['gold']
    assert first['user']['status']['diamondShard'] == before['status']['diamondShard']
    period = (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=boundary)).astimezone(
        timezone(timedelta(hours=8))).date().isoformat()
    assert ledger(camp_runtime) == [(original[0][0], 100, boundary),
                                  (period, 0, None)]
    # No second reset, revision bump, claim clearing or wallet payout.
    rows = database_rows(camp_runtime.database.path)
    assert camp_runtime.sync(camp_token) == first
    assert database_rows(camp_runtime.database.path) == rows


def test_mutation_delta_includes_week_reset_and_retries_are_idempotent(camp_runtime, camp_token):
    seed_observed_state(camp_runtime)
    before = user(camp_runtime, camp_token)
    set_time(camp_runtime, next_boundary(camp_runtime))
    response = camp_runtime.mutate(camp_token, None, 'week-reset', 'week-check', {}, lambda ctx: {})
    assert response['playerDataDelta']['modified']['campaignsV2']['campaignCurrentFee'] == 0
    assert apply(before, response['playerDataDelta']) == user(camp_runtime, camp_token)
    assert camp_runtime.mutate(camp_token, None, 'week-reset', 'week-check', {}, lambda ctx: {}) == response
    assert len(ledger(camp_runtime)) == 2


def test_clock_rewind_and_return_do_not_reopen_old_income_allowance(camp_runtime, camp_token):
    seed_observed_state(camp_runtime)
    boundary = next_boundary(camp_runtime)
    set_time(camp_runtime, boundary)
    user(camp_runtime, camp_token)
    with camp_runtime.database.transaction() as session:
        ctx = Context(session, camp_runtime.data, 1)
        account = session.get(m.CampaignAccount, 1)
        period = active_week(ctx, account).period
        session.get(m.CampaignWeek, (1, period)).earned_fee = account.current_fee = 77
    retained = ledger(camp_runtime)
    for timestamp in (boundary - 86400, boundary, boundary + 1):
        set_time(camp_runtime, timestamp)
        assert user(camp_runtime, camp_token)['campaignsV2']['campaignCurrentFee'] == 77
        assert ledger(camp_runtime) == retained
    set_time(camp_runtime, boundary + 21 * 86400)
    assert user(camp_runtime, camp_token)['campaignsV2']['campaignCurrentFee'] == 0
    assert len(ledger(camp_runtime)) == 3  # No fabricated intermediate weeks.


def test_account_isolation_and_concurrent_boundary_requests(camp_runtime, camp_token):
    seed_observed_state(camp_runtime)
    with camp_runtime.database.transaction() as session:
        second = create_account(session, camp_runtime.data, 'OtherCampaignDoctor')
        other_id = second.id
    before = database_rows(camp_runtime.database.path)
    set_time(camp_runtime, next_boundary(camp_runtime))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: camp_runtime.sync(camp_token), range(12)))
    assert all(r == results[0] for r in results)
    assert len(ledger(camp_runtime)) == 2
    with camp_runtime.database.transaction(write=False) as session:
        other = Context(session, camp_runtime.data, other_id)
        assert len(other.read_rows(m.CampaignWeek)) == 1
        assert session.get(m.CampaignAccount, other_id).current_fee == 0
    after = database_rows(camp_runtime.database.path)
    for table in ('campaign_break_claims', 'campaign_missions', 'inventory_items'):
        assert after[table] == before[table]
    assert set(before['campaign_stage_progress']).issubset(after['campaign_stage_progress'])
    added = set(after['campaign_stage_progress']) - set(before['campaign_stage_progress'])
    assert all(row[0] == 1 and row[2:] == (0, None) for row in added)


@pytest.mark.parametrize('modules', [3207, 3807])
def test_native_complete_refresh_delivers_week_and_calendar_delta(camp_runtime, camp_token, modules):
    seed_observed_state(camp_runtime)
    before = user(camp_runtime, camp_token)
    set_time(camp_runtime, next_boundary(camp_runtime))
    with TestClient(create_game_app(camp_runtime)) as client:
        response = client.post('/account/syncStatus', headers={'secret': camp_token}, json={'modules': modules})
    assert response.status_code == 200
    payload = response.json()
    assert apply(before, payload['playerDataDelta']) == user(camp_runtime, camp_token)
    assert len(ledger(camp_runtime)) == 2


@pytest.mark.parametrize('failure', ['action', 'database'])
def test_failed_transaction_rolls_back_week_archive_reset_and_receipt(camp_runtime, camp_token, failure):
    seed_observed_state(camp_runtime)
    set_time(camp_runtime, next_boundary(camp_runtime))
    before = database_rows(camp_runtime.database.path)

    def broken_action(ctx):
        if failure == 'action':
            raise DomainError('TEST_REJECTION', 'synthetic rejection')
        return {}

    def reject_insert(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith('INSERT INTO campaign_weeks'):
            raise OperationalError(statement, {}, RuntimeError('synthetic storage failure'))

    if failure == 'database':
        event.listen(camp_runtime.database.engine, 'before_cursor_execute', reject_insert)
    try:
        with pytest.raises(DomainError if failure == 'action' else OperationalError):
            camp_runtime.mutate(camp_token, None, 'failed-week', 'week-check', {}, broken_action)
    finally:
        if failure == 'database':
            event.remove(camp_runtime.database.engine, 'before_cursor_execute', reject_insert)
    assert database_rows(camp_runtime.database.path) == before


def test_restart_backup_restore_and_pure_projection_retain_week_ledger(camp_runtime, camp_token):
    seed_observed_state(camp_runtime)
    set_time(camp_runtime, next_boundary(camp_runtime))
    user(camp_runtime, camp_token)
    expected = ledger(camp_runtime)
    backup = BackupService(camp_runtime)
    saved = backup.create()
    set_time(camp_runtime, next_boundary(camp_runtime))
    user(camp_runtime, camp_token)
    assert len(ledger(camp_runtime)) == 3
    backup.restore(saved['name'])
    assert ledger(camp_runtime) == expected
    before = database_rows(camp_runtime.database.path)
    with camp_runtime.database.transaction(write=False) as session:
        SyncDataAssembler(Context(session, camp_runtime.data, 1)).assemble()
    assert database_rows(camp_runtime.database.path) == before
    camp_runtime.database.close()
    restarted = Runtime(camp_runtime.settings)
    try:
        assert ledger(restarted) == expected
        assert database_rows(restarted.database.path) == before
    finally:
        restarted.database.close()


def test_0016_zero_income_upgrade_preserves_old_rows(camp_runtime):
    camp_runtime.database.close()
    with closing(sqlite3.connect(camp_runtime.database.path)) as connection:
        connection.execute('DROP TABLE campaign_weeks')
        connection.execute('UPDATE alembic_version SET version_num=?', (CAMPAIGN_REVISION,))
        connection.commit()
    before = database_rows(camp_runtime.database.path, ('alembic_version',))
    restarted = Runtime(camp_runtime.settings)
    try:
        assert database_rows(restarted.database.path, ('alembic_version', 'campaign_weeks')) == before
        assert len(ledger(restarted)) == 1
        with closing(sqlite3.connect(restarted.database.path)) as connection:
            assert connection.execute('SELECT version_num FROM alembic_version').fetchone()[0] == REVISION
            assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        restarted.database.close()


def test_unattributed_nonzero_legacy_income_is_rejected_before_migration(camp_runtime):
    seed_observed_state(camp_runtime)
    camp_runtime.database.close()
    with closing(sqlite3.connect(camp_runtime.database.path)) as connection:
        connection.execute('DROP TABLE campaign_weeks')
        connection.execute('UPDATE alembic_version SET version_num=?', (CAMPAIGN_REVISION,))
        connection.commit()
    before = database_rows(camp_runtime.database.path)
    with pytest.raises(ValueError, match='缺少所属周记录'):
        Runtime(camp_runtime.settings)
    assert database_rows(camp_runtime.database.path) == before


@pytest.mark.parametrize('fault', ['mirror', 'closed_active', 'non_monday', 'unknown_policy'])
def test_corrupt_ledger_is_not_reinterpreted_or_reset(camp_runtime, camp_token, fault):
    with camp_runtime.database.transaction() as session:
        ctx = Context(session, camp_runtime.data, 1)
        period = active_week(ctx, session.get(m.CampaignAccount, 1)).period
        row = session.get(m.CampaignWeek, (1, period))
        if fault == 'mirror':
            row.earned_fee = 2
        elif fault == 'closed_active':
            row.closed_at = ctx.now
        elif fault == 'non_monday':
            row.period = '2027-01-12'
        else:
            row.policy_version = 'unknown'
    before = database_rows(camp_runtime.database.path)
    with pytest.raises(DomainError) as error:
        user(camp_runtime, camp_token)
    assert error.value.code == 'CAMPAIGN_WEEK_INCOMPATIBLE'
    assert database_rows(camp_runtime.database.path) == before
