"""Settlement-bound bank keys; low QA thresholds are not official data."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_shops import move
from test_rogue_shops import shop_runtime as shop_runtime
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import post, start
from test_roguelike_state import rows

from terralocal.server.domain import rogue_bank_awards as awards
from terralocal.server.domain import rogue_banks
from terralocal.server.domain.accounts import login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_bank_ledger import compile_terms
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_shops import prepare as prepare_shop
from terralocal.server.domain.rogue_shops import quote
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import REVISION, ROGUE_BANK_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def awards_runtime(monkeypatch, request):
    originals = start_fixture.map_tables, start_fixture.recruit_tables

    def patch(factory):
        def tables():
            value = factory()
            detail = value["roguelike_topic_table"]["details"]["rogue_1"]
            if "gameConst" in detail:
                detail["gameConst"].update(bankMaxGold=999, bankRewardCountType="HIGHEST_RECORD")
            detail["bankRewards"] = [
                {"rewardId": "qa-slot", "rewardType": "ADD_SHOP_POS", "unlockGoldCnt": 1},
                {"rewardId": "qa-draw", "rewardType": "UNLOCK_WITHDRAW", "unlockGoldCnt": 2},
                {"rewardId": "qa-item", "rewardType": "UNLOCK_ITEM", "unlockGoldCnt": 4}]
            return value
        return tables

    monkeypatch.setattr(start_fixture, "map_tables", patch(originals[0]))
    monkeypatch.setattr(start_fixture, "recruit_tables", patch(originals[1]))
    runtime, token = request.getfixturevalue("shop_runtime")
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        for shop in session.query(m.RogueShopVisit):
            terms = compile_terms(runtime.data, quote(runtime.data, shop), mode="NORMAL", grade=0,
                bank_open=True, allow_deposit=True, allow_withdraw=True, withdrawal_costs=(1, 2, 4, 8, 16, 32),
                evidence="QA only: low artificial thresholds and forced initial withdrawal, no natural source")
            rogue_banks.prepare(ctx, shop.id, terms, outcomes=(False,) * 8, has_boss=True)
    return runtime, token


def bank(runtime, token):
    return runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["bank"]


def reach(client, token):
    assert move(client, token, 0, "enter").status_code == 200
    for number in range(3):
        assert post(client, token, "bankPut", {}, "put-" + str(number)).status_code == 200
    assert post(client, token, "bankWithdraw", {}, "withdraw-1").status_code == 200
    assert post(client, token, "bankWithdraw", {}, "withdraw-2").status_code == 200
    assert post(client, token, "giveUpGame", {}, "close").status_code == 200


def confirm(client, token, key="settle"):
    response = post(client, token, "gameSettle", {}, key)
    assert response.status_code == 200, response.text
    return response


def test_only_confirmed_settlement_awards_peak_keys_with_exact_delta_and_retries(awards_runtime):
    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        reach(client, token)
        assert bank(runtime, token) == {"show": True, "current": 0, "record": 3, "totalPut": 3, "reward": {}}
        before = runtime.sync(token)["user"]
        response = confirm(client, token)
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        assert bank(runtime, token)["reward"] == {"qa-draw": 1, "qa-slot": 1}
        assert confirm(client, token).json() == response.json()
        confirm(client, token, "settle-again")
        assert runtime.sync(token)["user"] == after
    with runtime.database.transaction(write=False) as session:
        wallet = session.get(m.RogueBankWallet, 1)
        assert len(wallet.awards) == 1 and wallet.visits == 1
        assert wallet.awards[0]["rewards"] == ["qa-draw", "qa-slot"]
        assert session.query(m.RogueGameSettlement).count() == 1
        assert session.query(m.BattleSession).count() == 0
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after
        assert rows(runtime.database.path) == saved
        backup = BackupService(reopened).create()
        BackupService(reopened).restore(backup["name"])
        assert reopened.sync(token)["user"] == after and rows(runtime.database.path) == saved
    finally:
        reopened.database.close()


def test_earned_terms_need_settled_keys_not_peak_or_forced_qa_permission(awards_runtime):
    runtime, token = awards_runtime
    def terms():
        with runtime.database.transaction(write=False) as session:
            shop = session.query(m.RogueShopVisit).filter_by(node_x=0).one()
            return rogue_banks.earned_terms(Context(session, runtime.data, 1), quote(runtime.data, shop),
                                            mode="NORMAL", grade=0, open_bank=False)
    with TestClient(create_game_app(runtime)) as client:
        reach(client, token)
        assert not terms().allow_withdraw
        confirm(client, token)
        earned = terms()
        assert earned.allow_withdraw and earned.bank_open and earned.withdrawal_costs == (1, 2, 4, 8, 16, 32)
    with runtime.database.transaction(write=False) as session:
        shop = session.query(m.RogueShopVisit).first()
        other = rogue_banks.earned_terms(Context(session, runtime.data, 2), quote(runtime.data, shop),
                                         mode="NORMAL", grade=0, open_bank=True)
        assert not other.allow_withdraw


def test_next_run_earned_visit_preserves_award_chain_and_resets_withdraw_cost(awards_runtime):
    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        reach(client, token)
        confirm(client, token)
        with runtime.database.transaction() as session:
            old_visit = session.query(m.RogueShopVisit).filter_by(node_x=0).one()
            q = quote(runtime.data, old_visit)
            session.get(m.ServerClockState, 1).fixed_at += runtime.data.rogue_initial.cooldown
            token = login(session, runtime.settings, name=session.get(m.Account, 1).name)["secret"]
        response = start(client, token)
        assert response.status_code == 200, response.text
        assert post(client, token, "chooseInitialRelic", {"select": "0"}, "next-band").status_code == 200
        assert post(client, token, "chooseInitialRecruitSet", {"select": "recruit_group_1"}, "next-group").status_code == 200
        for number in range(3):
            assert post(client, token, "activeRecruitTicket", {"id": str(number)}, "next-active-" + str(number)).status_code == 200
            assert post(client, token, "closeRecruitTicket", {"id": str(number)}, "next-close-" + str(number)).status_code == 200
        with runtime.database.transaction() as session:
            ctx = Context(session, runtime.data, 1)
            save_map(ctx, Plan("zone_1", (Column(1, 1, (Entry("SHOP", 1),)),) * 2, 0))
        assert post(client, token, "finishEvent", {}, "next-map").status_code == 200
        with runtime.database.transaction() as session:
            ctx = Context(session, runtime.data, 1)
            prepare_shop(ctx, {Point(0, 0): q, Point(1, 0): q})
            run = session.query(m.RogueTopicRun).filter_by(account_id=1, state="MAP_READY").one()
            shop = session.query(m.RogueShopVisit).filter_by(run_id=run.id, node_x=0).one()
            rogue_banks.prepare_earned(ctx, shop.id, open_bank=False, outcomes=(False,), has_boss=True)
        assert move(client, token, 0, "next-enter").status_code == 200
        wire = runtime.sync(token)["user"]["rlv2"]["current"]["player"]["pending"][0]["content"]["shop"]["bank"]
        assert wire["canWithdraw"] and wire["withdraw"] == 0 and wire["cost"] == 1
        assert post(client, token, "bankPut", {}, "next-put").status_code == 200
        assert post(client, token, "bankWithdraw", {}, "next-draw").status_code == 200
    with runtime.database.transaction(write=False) as session:
        assert len(session.get(m.RogueBankWallet, 1).awards) == 1
        latest = session.query(m.RogueBankVisit).filter_by(ordinal=1).one()
        assert latest.before_bank['reward'] == {'qa-draw': 1, 'qa-slot': 1}
    expected = runtime.sync(token)["user"]
    saved = rows(runtime.settings.database_path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected and rows(runtime.settings.database_path) == saved
    finally:
        reopened.database.close()


def test_concurrent_new_confirmation_keys_do_not_duplicate_awards(awards_runtime):
    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        reach(client, token)
        with ThreadPoolExecutor(max_workers=2) as workers:
            responses = list(workers.map(lambda key: post(client, token, "gameSettle", {}, key), ("one", "two")))
        assert all(r.status_code == 200 for r in responses)
    with runtime.database.transaction(write=False) as session:
        assert len(session.get(m.RogueBankWallet, 1).awards) == 1
        assert session.query(m.RogueGameSettlement).count() == 1


def test_no_award_below_first_threshold_and_clock_rewind_clamps_confirmation(awards_runtime):
    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        assert post(client, token, "giveUpGame", {}, "close").status_code == 200
        with runtime.database.transaction() as session:
            run = session.query(m.RogueTopicRun).filter_by(account_id=1).one()
            ended = run.ended_at
            session.get(m.ServerClockState, 1).fixed_at = ended - 100
        confirm(client, token)
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.RogueBankWallet, 1).awards == []
        assert session.query(m.RogueGameSettlement).one().created_at >= ended
    assert bank(runtime, token)["reward"] == {}


def test_award_after_clock_rewind_uses_confirmed_result_time(awards_runtime):
    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        reach(client, token)
        with runtime.database.transaction() as session:
            run = session.query(m.RogueTopicRun).filter_by(account_id=1).one()
            ended = run.ended_at
            session.get(m.ServerClockState, 1).fixed_at = ended - 100
        confirm(client, token)
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.RogueBankWallet, 1).awards[0]["at"] >= ended
        assert session.get(m.RogueBankWallet, 1).awards[0]["at"] == session.query(m.RogueGameSettlement).one().created_at


def test_exception_after_bank_refresh_rolls_back_score_run_wallet_and_receipt(awards_runtime, monkeypatch):
    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        reach(client, token)
        saved = rows(runtime.database.path)
        original = rogue_banks.refresh
        def fail(ctx):
            original(ctx)
            raise RuntimeError("injected after bank refresh")
        monkeypatch.setattr(rogue_banks, "refresh", fail)
        with pytest.raises(RuntimeError, match="injected"):
            post(client, token, "gameSettle", {}, "rollback")
        assert rows(runtime.database.path) == saved
        monkeypatch.setattr(rogue_banks, "refresh", original)
        confirm(client, token, "rollback")
        assert bank(runtime, token)["reward"] == {"qa-draw": 1, "qa-slot": 1}


@pytest.mark.parametrize("field,value", [("head", "0" * 64), ("before", "0" * 64), ("at", True),
                                         ("score", "1" * 64), ("rewards", ["qa-item"]), ("visits", 2)])
def test_tampered_grant_is_rejected_before_writable_startup(awards_runtime, field, value):
    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        reach(client, token)
        confirm(client, token)
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as con:
        log = json.loads(con.execute('SELECT awards FROM rlv2_bank_wallets WHERE account_id=1').fetchone()[0])
        log[0][field] = value
        con.execute('UPDATE rlv2_bank_wallets SET awards=? WHERE account_id=1', (json.dumps(log),))
    before = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("field,value", [("account", 2), ("data", "0" * 64)])
def test_foreign_account_or_data_grant_cannot_be_rebound(awards_runtime, field, value):
    test_tampered_grant_is_rejected_before_writable_startup(awards_runtime, field, value)


def test_marker_zero_is_preserved_and_not_reawarded_by_pure_kernel(awards_runtime):
    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        reach(client, token)
        confirm(client, token)
    with runtime.database.transaction(write=False) as session:
        run = session.query(m.RogueTopicRun).filter_by(account_id=1).one()
        result = session.get(m.RogueGameSettlement, run.id)
        original = {"show": True, "current": 0, "record": 3, "totalPut": 3, "reward": {"qa-slot": 0}}
        event = awards.event(runtime.data.rogue_bank, original, run, result, visits=1, head="f" * 64)
        assert event["rewards"] == ["qa-draw"]
        final = awards.apply(runtime.data.rogue_bank, original, event, run, result, visits=1, head="f" * 64)
        assert final["reward"] == {"qa-slot": 0, "qa-draw": 1} and original["reward"] == {"qa-slot": 0}
        foreign = deepcopy(run)
        foreign.gamedata_hash = "a" * 64
        with pytest.raises(DomainError):
            awards.apply(runtime.data.rogue_bank, original, event, foreign, result, visits=1, head="f" * 64)


def test_revision35_adds_only_empty_award_column_and_preserves_all_old_rows(awards_runtime):
    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        assert post(client, token, "bankPut", {}, "put").status_code == 200
    runtime.database.close()
    path = runtime.settings.database_path
    with sqlite3.connect(path) as con:
        con.execute('ALTER TABLE rlv2_bank_wallets DROP COLUMN awards')
        con.execute('UPDATE alembic_version SET version_num=?', (ROGUE_BANK_REVISION,))
    before = rows(path)
    reopened = Runtime(runtime.settings)
    try:
        after = rows(path)
        assert after['alembic_version'] == [(REVISION,)]
        assert set(before) == set(after)
        assert all(after[k] == v for k, v in before.items() if k not in {'alembic_version', 'rlv2_bank_wallets'})
        assert [row[:-1] for row in after['rlv2_bank_wallets']] == before['rlv2_bank_wallets']
        assert all(row[-1] == '[]' for row in after['rlv2_bank_wallets'])
        assert bank(reopened, token)['reward'] == {}
    finally:
        reopened.database.close()


def test_current_revision_missing_award_column_is_not_silently_repaired(awards_runtime):
    runtime, _ = awards_runtime
    runtime.database.close()
    path = runtime.settings.database_path
    with sqlite3.connect(path) as con:
        con.execute('ALTER TABLE rlv2_bank_wallets DROP COLUMN awards')
    saved = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == saved


def test_revision35_rollback_restores_old_schema_and_rows(awards_runtime, monkeypatch):
    from alembic.operations import Operations

    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
    runtime.database.close()
    path = runtime.settings.database_path
    with sqlite3.connect(path) as con:
        con.execute('ALTER TABLE rlv2_bank_wallets DROP COLUMN awards')
        con.execute('UPDATE alembic_version SET version_num=?', (ROGUE_BANK_REVISION,))
    before = rows(path)
    original = Operations.add_column
    def fail(self, table, column, **kwargs):
        result = original(self, table, column, **kwargs)
        if table == "rlv2_bank_wallets":
            raise RuntimeError("injected migration rollback")
        return result
    monkeypatch.setattr(Operations, "add_column", fail)
    with pytest.raises(RuntimeError, match="injected migration rollback"):
        Runtime(runtime.settings)
    assert rows(path) == before
    with sqlite3.connect(path) as con:
        assert 'awards' not in {r[1] for r in con.execute('PRAGMA table_info(rlv2_bank_wallets)')}


def test_completed_legacy_run_is_not_retroactively_awarded_at_startup(awards_runtime):
    runtime, token = awards_runtime
    with TestClient(create_game_app(runtime)) as client:
        reach(client, token)
        confirm(client, token)
    with runtime.database.transaction() as session:
        session.get(m.RogueBankWallet, 1).awards = []
        rogue_banks.refresh(Context(session, runtime.data, 1))
    runtime.database.close()
    path = runtime.settings.database_path
    with sqlite3.connect(path) as con:
        con.execute('ALTER TABLE rlv2_bank_wallets DROP COLUMN awards')
        con.execute('UPDATE alembic_version SET version_num=?', (ROGUE_BANK_REVISION,))
    reopened = Runtime(runtime.settings)
    try:
        assert bank(reopened, token)['reward'] == {}
        with reopened.database.transaction(write=False) as session:
            assert session.get(m.RogueBankWallet, 1).awards == []
            assert session.query(m.RogueGameSettlement).count() == 1
    finally:
        reopened.database.close()
