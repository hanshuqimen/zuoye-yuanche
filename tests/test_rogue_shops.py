"""Authored shop transactions; current official prices/pools are not fixtures."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.accounts import login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_shops import prepare
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import REVISION, ROGUE_SCENE_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def shop_runtime(monkeypatch, request):
    original = start_fixture.map_tables

    def tables():
        value = original()
        value["roguelike_topic_table"]["details"]["rogue_1"]["gameConst"]["goldItemId"] = "test_gold"
        return value

    monkeypatch.setattr(start_fixture, "map_tables", tables)
    runtime, token = request.getfixturevalue("rogue_battle_runtime")
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        save_map(ctx, Plan("zone_1", (Column(1, 1, (Entry("SHOP", 1),)),) * 2, 0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "map").status_code == 200
    with runtime.database.transaction() as session:
        q = compile_shop(runtime.data, "qa-shop", (Offer("a", "ticket_medic", 5),
            Offer("b", "ticket_caster", 2)), evidence="Authored QA quote, not official prices or pool")
        prepare(Context(session, runtime.data, 1), {Point(0, 0): q, Point(1, 0): q})
    return runtime, token


def move(client, token, x, key):
    return post(client, token, "moveTo", {"to": {"x": x, "y": 0}}, key)


def buy(client, token, key, index="a"):
    return post(client, token, "shopAction", {"buy": [index], "recycle": [], "leave": 0}, key)


def leave(client, token, key):
    return post(client, token, "shopAction", {"buy": [], "recycle": [], "leave": 1}, key)


def test_payment_ticket_stock_delta_retry_restart_and_restore(shop_runtime):
    runtime, token = shop_runtime
    original = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        state = current(runtime, token)
        assert state["player"]["pending"][0]["type"] == "SHOP"
        before = runtime.sync(token)["user"]
        response = buy(client, token, "buy")
        assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        state = after["rlv2"]["current"]
        assert state["player"]["property"]["gold"] == 1
        assert state["inventory"]["recruit"]["3"]["state"] == "ACTIVE"
        assert state["inventory"]["recruit"]["3"]["id"] == "ticket_medic"
        goods = next(e for e in state["player"]["pending"] if e["type"] == "SHOP")["content"]["shop"]["goods"]
        assert [(g["index"], g["count"]) for g in goods] == [("a", 0), ("b", 1)]
        for key in ("buy", "new-buy-sequence"):
            assert buy(client, token, key).status_code == 200
        assert runtime.sync(token)["user"] == after
        assert leave(client, token, "early-leave").status_code == 409
        assert move(client, token, 1, "early-move").status_code == 409
        reopened = Runtime(runtime.settings)
        try:
            assert reopened.sync(token)["user"] == after
        finally:
            reopened.database.close()
        assert post(client, token, "closeRecruitTicket", {"id": "3"}, "shop-close").status_code == 200
        assert buy(client, token, "poor", "b").status_code == 409
        assert leave(client, token, "leave").status_code == 200
        finished = runtime.sync(token)["user"]
        assert finished["rlv2"]["current"]["player"]["state"] == "WAIT_MOVE"
        assert leave(client, token, "leave-again").status_code == 200
        assert runtime.sync(token)["user"] == finished
        assert move(client, token, 1, "next").status_code == 200
        assert move(client, token, 0, "back").status_code == 409
    final = runtime.sync(token)["user"]
    assert {k:v for k,v in original.items() if k != "rlv2"} == {k:v for k,v in final.items() if k != "rlv2"}
    backups = BackupService(runtime)
    backup = backups.create()
    saved = rows(runtime.database.path)
    backups.restore(backup["name"])
    assert rows(runtime.database.path) == saved
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()


def test_concurrent_new_sequences_make_one_payment_and_ticket(shop_runtime):
    runtime, token = shop_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
    second = Runtime(runtime.settings)
    try:
        def pay(pair):
            r, key = pair
            with TestClient(create_game_app(r)) as client:
                return buy(client, token, key).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(pay, ((runtime, "one"), (second, "two")))) == [200, 200]
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueRunTicket).count() == 4
            assert len(session.query(m.RogueShopVisit).filter_by(state="ACTIVE").one().purchases) == 1
        assert current(runtime, token)["player"]["property"]["gold"] == 1
    finally:
        second.database.close()


def test_reward_failure_rolls_back_payment_stock_and_receipt(shop_runtime, monkeypatch):
    from terralocal.server.domain import rogue_recruit

    runtime, token = shop_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        before = rows(runtime.database.path)
        def fail(*args):
            raise DomainError("QA_GRANT_FAILURE", "Authored failure after payment", 409)
        monkeypatch.setattr(rogue_recruit, "activate", fail)
        assert buy(client, token, "failed").status_code == 409
        assert rows(runtime.database.path) == before


def test_unimplemented_non_ticket_adapter_rolls_back_payment_and_stock(shop_runtime, monkeypatch):
    from dataclasses import replace

    from terralocal.server.domain import rogue_shops

    runtime, token = shop_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        before = rows(runtime.database.path)
        old_quote = rogue_shops.quote
        # Simulate a future compiler extension without its effect adapter.
        # This is a failure injection, not an official relic purchase fixture.
        monkeypatch.setattr(rogue_shops, "quote", lambda *args: replace(old_quote(*args),
                                                                       ticket_indices=frozenset({"b"})))
        response = buy(client, token, "unsupported")
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "ROGUE_SHOP_GRANT_UNSUPPORTED"
        assert rows(runtime.database.path) == before


@pytest.mark.parametrize("change", ["price", "purchase", "owner", "before"])
def test_corrupt_saved_shop_is_rejected_before_startup_writes(shop_runtime, change):
    runtime, _ = shop_runtime
    with TestClient(create_game_app(runtime)) as client:
        token = shop_runtime[1]
        assert move(client, token, 0, "enter").status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as con:
        if change == "owner":
            con.execute("UPDATE rlv2_shop_visits SET account_id=2 WHERE node_x=0")
        elif change == "price":
            raw = con.execute("SELECT quote FROM rlv2_shop_visits WHERE node_x=0").fetchone()[0]
            value = json.loads(raw)
            value["offers"][0]["price"] = 0
            con.execute("UPDATE rlv2_shop_visits SET quote=? WHERE node_x=0", (json.dumps(value),))
        elif change == "purchase":
            con.execute("UPDATE rlv2_shop_visits SET purchases=? WHERE node_x=0",
                        (json.dumps([{"index":"a","ticket":3,"at":1}]),))
        else:
            con.execute("UPDATE rlv2_shop_visits SET before='{}' WHERE node_x=0")
    before = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == before


def test_schema26_upgrade_adds_only_empty_shop_table_and_preserves_prior_rows(shop_runtime):
    runtime, _ = shop_runtime
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as con:
        con.execute("DROP TABLE rlv2_floor_cursors")
        con.execute("DROP TABLE rlv2_shop_visits")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_SCENE_REVISION,))
    before = rows(runtime.settings.database_path)
    reopened = Runtime(runtime.settings)
    try:
        after = rows(runtime.settings.database_path)
        assert set(after) - set(before) == {"rlv2_shop_visits", "rlv2_floor_cursors"}
        assert not after["rlv2_floor_cursors"] and not after["rlv2_shop_visits"]
        assert all(after[k] == v for k,v in before.items() if k != "alembic_version")
        assert after["alembic_version"] == [(REVISION,)]
    finally:
        reopened.database.close()


def test_other_account_forged_prices_and_unsupported_actions_do_not_write(shop_runtime):
    runtime, token = shop_runtime
    with runtime.database.transaction() as session:
        other = session.get(m.Account, 2)
        other_token = login(session, runtime.settings, name=other.name)["secret"]
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        for owner, payload, expected in (
            (other_token, {"buy":["a"], "recycle":[], "leave":0}, 409),
            (token, {"buy":["a"], "recycle":[], "leave":0, "price":0}, 422),
            (token, {"buy":["a","b"], "recycle":[], "leave":0}, 501),
            (token, {"buy":[], "recycle":["a"], "leave":0}, 501),
            (token, {"buy":["unknown"], "recycle":[], "leave":0}, 400),
        ):
            before = rows(runtime.database.path)
            response = post(client, owner, "shopAction", payload, "invalid-" + str(expected))
            assert response.status_code == expected, response.text
            assert rows(runtime.database.path) == before


def test_missing_table_in_current_schema_and_missing_scene_in_old26_are_readonly_failures(shop_runtime):
    runtime, _ = shop_runtime
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as con:
        con.execute("DROP TABLE rlv2_shop_visits")
    before = rows(runtime.settings.database_path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.settings.database_path) == before
    with sqlite3.connect(runtime.settings.database_path) as con:
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_SCENE_REVISION,))
        con.execute("DROP TABLE rlv2_scene_visits")
    before = rows(runtime.settings.database_path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.settings.database_path) == before
