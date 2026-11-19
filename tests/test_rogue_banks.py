"""Explicit QA banking plans: real HTTP/SQL transactions, not natural supply."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_shops import buy, leave, move
from test_rogue_shops import shop_runtime as shop_runtime
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_banks
from terralocal.server.domain.accounts import login
from terralocal.server.domain.context import Context
from terralocal.server.domain.rogue_bank_ledger import compile_terms
from terralocal.server.domain.rogue_shops import quote
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import REVISION, ROGUE_CLOSURE_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def bank_runtime(monkeypatch, request):
    original = start_fixture.map_tables
    original_recruit = start_fixture.recruit_tables

    def recruits():
        value = original_recruit()
        value["roguelike_topic_table"]["details"]["rogue_1"]["bankRewards"] = [
            {"rewardId": "qa-extra", "rewardType": "ADD_SHOP_POS", "unlockGoldCnt": 25},
            {"rewardId": "qa-draw", "rewardType": "UNLOCK_WITHDRAW", "unlockGoldCnt": 200}]
        return value

    def tables():
        value = original()
        d = value["roguelike_topic_table"]["details"]["rogue_1"]
        d["gameConst"].update(bankMaxGold=999, bankRewardCountType="HIGHEST_RECORD")
        d["bankRewards"] = [{"rewardId": "qa-extra", "rewardType": "ADD_SHOP_POS", "unlockGoldCnt": 25},
                            {"rewardId": "qa-draw", "rewardType": "UNLOCK_WITHDRAW", "unlockGoldCnt": 200}]
        return value

    monkeypatch.setattr(start_fixture, "map_tables", tables)
    monkeypatch.setattr(start_fixture, "recruit_tables", recruits)
    runtime, token = request.getfixturevalue("shop_runtime")
    outcomes = getattr(request, "param", None)
    outcomes = ((False,) * 20, (True,)) if outcomes is None else outcomes
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        for shop in session.query(m.RogueShopVisit).order_by(m.RogueShopVisit.node_x):
            original_time = session.get(m.ServerClockState, 1).fixed_at
            if shop.node_x == 1 and len(outcomes) == 3:
                session.get(m.ServerClockState, 1).fixed_at += outcomes[2]
                ctx = Context(session, runtime.data, 1)
            terms = compile_terms(runtime.data, quote(runtime.data, shop), mode="NORMAL", grade=0,
                bank_open=True, allow_deposit=True, allow_withdraw=True, withdrawal_costs=(1, 2, 4, 8, 16, 32),
                evidence="Forced QA authorization and known-success outcomes, not earned withdrawal or natural bank generation")
            rogue_banks.prepare(ctx, shop.id, terms, outcomes=outcomes[shop.node_x], has_boss=True)
            session.get(m.ServerClockState, 1).fixed_at = original_time
    return runtime, token


def bank(user):
    return user["rlv2"]["outer"]["rogue_1"]["bank"]


def gold(user):
    return user["rlv2"]["current"]["player"]["property"]["gold"]


def test_empty_requests_interleaved_buy_delta_retries_fault_and_restart(bank_runtime):
    runtime, token = bank_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        before = runtime.sync(token)["user"]
        assert bank(before) == {"show": True, "current": 0, "record": 0, "totalPut": 0, "reward": {}}
        first = post(client, token, "bankPut", {}, "put-1")
        assert first.status_code == 200, first.text
        after = runtime.sync(token)["user"]
        assert apply(before, first.json()["playerDataDelta"]) == after
        assert gold(after) == 5 and bank(after)["current"] == bank(after)["totalPut"] == 1
        assert post(client, token, "bankPut", {}, "put-1").json() == first.json()
        assert post(client, token, "bankPut", {}, "put-2").status_code == 200
        assert post(client, token, "bankWithdraw", {}, "draw-1").status_code == 200
        assert buy(client, token, "buy-b", "b").status_code == 200
        user = runtime.sync(token)["user"]
        assert gold(user) == 3 and bank(user)["current"] == 1
        assert bank(user)["record"] == bank(user)["totalPut"] == 2 and bank(user)["reward"] == {}
        assert buy(client, token, "same-stock", "b").status_code == 200
        assert post(client, token, "bankPut", {}, "recruit-pending").status_code == 409
        closed = post(client, token, "closeRecruitTicket", {"id": "3"}, "bank-close-ticket")
        assert closed.status_code == 200, closed.text
        assert leave(client, token, "leave").status_code == 200
        assert move(client, token, 1, "next").status_code == 200
        assert post(client, token, "bankPut", {}, "fault").status_code == 200
        assert post(client, token, "bankPut", {}, "fault-again").status_code == 409
        assert post(client, token, "bankWithdraw", {}, "draw-next-shop").status_code == 200
        user = runtime.sync(token)["user"]
        pending = user["rlv2"]["current"]["player"]["pending"][0]["content"]["shop"]["bank"]
        assert pending["cost"] == 2 and pending["withdraw"] == 1 and not pending["canPut"] and pending["canWithdraw"]
        assert gold(user) == 3 and bank(user)["current"] == 1 and bank(user)["totalPut"] == 3
        reopened = Runtime(runtime.settings)
        try:
            assert reopened.sync(token)["user"] == user
        finally:
            reopened.database.close()
        service = BackupService(runtime)
        backup = service.create()
        assert post(client, token, "bankWithdraw", {}, "insufficient").status_code == 409
        service.restore(backup["name"])
        assert runtime.sync(token)["user"] == user


def test_bank_giveup_closes_journal_and_preserves_wallet(bank_runtime):
    runtime, token = bank_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        assert post(client, token, "bankPut", {}, "put").status_code == 200
        before = bank(runtime.sync(token)["user"])
        assert buy(client, token, "bank-buy-before-abandon", "b").status_code == 200
        response = post(client, token, "giveUpGame", {}, "give-up")
        assert response.status_code == 200, response.text
        assert bank(runtime.sync(token)["user"]) == before
        settled = post(client, token, "gameSettle", {}, "bank-confirm-close")
        assert settled.status_code == 200, settled.text
        assert bank(runtime.sync(token)["user"]) == before
        assert post(client, token, "gameSettle", {}, "bank-confirm-close").json() == settled.json()
        reopened = Runtime(runtime.settings)
        try:
            assert reopened.sync(token)["user"] == runtime.sync(token)["user"]
        finally:
            reopened.database.close()


def test_concurrent_distinct_empty_puts_and_same_key_retries(bank_runtime):
    runtime, token = bank_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda key: post(client, token, "bankPut", {}, key), ["a", "b", "a", "c"]))
        assert all(r.status_code == 200 for r in responses)
        assert responses[0].json() == responses[2].json()
        user = runtime.sync(token)["user"]
        assert gold(user) == 3 and bank(user)["current"] == bank(user)["totalPut"] == 3


def test_bank_flush_failure_rolls_back_wallet_run_journal_and_receipt(bank_runtime, monkeypatch):
    runtime, token = bank_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        before = rows(runtime.settings.database_path)
        real = rogue_banks.refresh

        def fail_after_flush(ctx):
            real(ctx)
            raise RuntimeError("Injected failure after wallet and outer flush")

        with monkeypatch.context() as patch:
            patch.setattr(rogue_banks, "refresh", fail_after_flush)
            with pytest.raises(RuntimeError, match="Injected failure"):
                post(client, token, "bankPut", {}, "rollback")
        assert rows(runtime.settings.database_path) == before
        assert post(client, token, "bankPut", {}, "rollback").status_code == 200


@pytest.mark.parametrize("change", ["wallet", "head", "plan", "journal", "missing-wallet"])
def test_corruption_is_rejected_before_startup_writes(bank_runtime, change):
    runtime, token = bank_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        assert post(client, token, "bankPut", {}, "put").status_code == 200
    with runtime.database.transaction() as session:
        wallet = session.get(m.RogueBankWallet, 1)
        row = session.query(m.RogueBankVisit).filter(m.RogueBankVisit.ordinal.is_not(None)).one()
        if change == "wallet":
            wallet.state = wallet.state | {"current": 99}
        elif change == "head":
            wallet.head_hash = "f" * 64
        elif change == "plan":
            row.plan = row.plan | {"outcomes": [True]}
        elif change == "journal":
            row.journal = row.journal | {"actions": []}
        else:
            session.delete(wallet)
    runtime.database.close()
    before = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == before


def test_migration34_is_additive_and_reopen_keeps_prior_rows(bank_runtime):
    runtime, token = bank_runtime
    runtime.database.close()
    path = runtime.settings.database_path
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE rlv2_bank_visits")
        con.execute("DROP TABLE rlv2_bank_wallets")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_CLOSURE_REVISION,))
    before = rows(path)
    reopened = Runtime(runtime.settings)
    try:
        after = rows(path)
        assert all(after[k] == v for k, v in before.items() if k != "alembic_version")
        assert after["alembic_version"] == [(REVISION,)]
        assert after["rlv2_bank_visits"] == after["rlv2_bank_wallets"] == []
    finally:
        reopened.database.close()


def test_strict_empty_body_missing_plan_and_request_errors_never_spend(shop_runtime):
    runtime, token = shop_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        before = runtime.sync(token)["user"]
        assert post(client, token, "bankPut", {}, "no-plan").status_code == 503
        for body in ({"amount": 1}, {"current": 999}, {"fault_after": False}):
            assert post(client, token, "bankPut", body, "bad").status_code == 422
        assert runtime.sync(token)["user"] == before


@pytest.mark.parametrize("bank_runtime", [((True,), (False,))], indirect=True)
def test_fault_carries_to_later_shop_and_does_not_disable_explicit_withdrawal(bank_runtime):
    runtime, token = bank_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        assert post(client, token, "bankPut", {}, "fault-first").status_code == 200
        assert leave(client, token, "leave").status_code == 200
        assert move(client, token, 1, "next").status_code == 200
        before = runtime.sync(token)["user"]
        assert not before["rlv2"]["current"]["player"]["pending"][0]["content"]["shop"]["bank"]["canPut"]
        assert post(client, token, "bankPut", {}, "blocked").status_code == 409
        assert runtime.sync(token)["user"] == before
        assert post(client, token, "bankWithdraw", {}, "draw").status_code == 200
        after = runtime.sync(token)["user"]
        assert gold(after) == 6 and bank(after)["current"] == 0 and bank(after)["totalPut"] == 1


@pytest.mark.parametrize("bank_runtime", [((), ())], indirect=True)
def test_missing_outcome_is_explicit_unimplemented_source_and_never_silent_success(bank_runtime):
    runtime, token = bank_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        before = rows(runtime.database.path)
        response = post(client, token, "bankPut", {}, "unknown-outcome")
        assert response.status_code == 503 and response.json()["error"]["code"] == "ROGUE_BANK_OUTCOME_MISSING"
        assert rows(runtime.database.path) == before


def test_other_account_and_stale_session_cannot_access_wallet(bank_runtime):
    runtime, token = bank_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        with runtime.database.transaction() as session:
            other = login(session, runtime.settings, name=session.get(m.Account, 2).name)["secret"]
        before = rows(runtime.database.path)
        assert post(client, other, "bankPut", {}, "other").status_code == 409
        assert rows(runtime.database.path) == before
        with runtime.database.transaction() as session:
            fresh = login(session, runtime.settings, name=session.get(m.Account, 1).name)["secret"]
        before = rows(runtime.database.path)
        assert post(client, token, "bankPut", {}, "stale").status_code == 401
        assert rows(runtime.database.path) == before
        assert post(client, fresh, "bankPut", {}, "fresh").status_code == 200


@pytest.mark.parametrize("bank_runtime", [((False,), (False,), 90)], indirect=True)
def test_clock_rewind_close_respects_future_prepared_bank_plan(bank_runtime):
    runtime, token = bank_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        assert post(client, token, "bankPut", {}, "put").status_code == 200
        closed = post(client, token, "giveUpGame", {}, "bank-rewind-close")
        assert closed.status_code == 200, closed.text
        with runtime.database.transaction(write=False) as session:
            run = session.query(m.RogueTopicRun).filter_by(account_id=1).one()
            assert all(run.ended_at >= b.prepared_at for b in session.query(m.RogueBankVisit))
        reopened = Runtime(runtime.settings)
        try:
            assert reopened.sync(token)["user"] == runtime.sync(token)["user"]
        finally:
            reopened.database.close()
