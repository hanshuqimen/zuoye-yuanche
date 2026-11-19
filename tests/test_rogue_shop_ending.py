"""Shop + scene + defeat composition, using authored HTTP records, no gameplay."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_native_replay import journal as make_journal
from test_rogue_defeat import defeat
from test_rogue_ending import ending_runtime as ending_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_battle_start import begin, body
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_ending import POLICY, SCENE_POLICY, SHOP_POLICY, facts
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_shops import prepare as prepare_shops
from terralocal.server.domain.rogue_visits import prepare as prepare_scenes
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.roguelike_state import no_run
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def shop_ending_runtime(monkeypatch, request):
    original = start_fixture.map_tables

    def tables():
        value = original()
        value["roguelike_topic_table"]["details"]["rogue_1"]["gameConst"]["goldItemId"] = "test_gold"
        return value

    monkeypatch.setattr(start_fixture, "map_tables", tables)
    return request.getfixturevalue("visits_runtime")


def prepare(runtime, token, *, scene=False, shop_first=True):
    sequence = (["INCIDENT"] if scene else []) + (["SHOP", "BATTLE_NORMAL", "SHOP"] if shop_first
                                                             else ["BATTLE_NORMAL", "SHOP"])
    spec = Plan("zone_1", tuple(Column(1, 1, (Entry(kind, 1, "ordinary" if kind == "BATTLE_NORMAL" else None),))
                               for kind in sequence), 0)
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), spec)
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "finishEvent", {}, "shop-end-map")
        assert reply.status_code == 200, reply.text
    with runtime.database.transaction() as session:
        q = compile_shop(runtime.data, "qa-ending", (Offer("a", "ticket_medic", 5),),
                         evidence="Authored QA quote; not official pool/prices")
        ctx = Context(session, runtime.data, 1)
        prepare_shops(ctx, {Point(x, 0): q for x, kind in enumerate(sequence) if kind == "SHOP"})
        if scene:
            prepare_scenes(ctx, {Point(0, 0): "rogue1-fixed-hp"})
    return sequence


def to_defeat(runtime, token, *, scene=False, shop_first=True):
    sequence = prepare(runtime, token, scene=scene, shop_first=shop_first)
    journal = make_journal()
    journal["journal"]["metadata"]["stageId"] = "ordinary"
    member = journal["journal"]["squad"][0]
    member["skillIndex"], member["skillId"] = 1, "s1"
    journal["journal"]["squad"].append(member | {"charInstId": 2, "skillIndex": -1, "skillId": None})
    with TestClient(create_game_app(runtime)) as client:
        if scene:
            assert post(client, token, "moveTo", {"to":{"x":0,"y":0}}, "shop-end-scene").status_code == 200
            assert post(client, token, "selectChoice", {"choice":"choice_hp"}, "shop-end-gain").status_code == 200
            assert post(client, token, "finishEvent", {}, "shop-end-scene-exit").status_code == 200
        if shop_first:
            x = sequence.index("SHOP")
            assert post(client, token, "moveTo", {"to":{"x":x,"y":0}}, "shop-end-enter").status_code == 200
            assert post(client, token, "shopAction", {"buy":["a"],"recycle":[],"leave":0},
                        "shop-end-buy").status_code == 200
            assert post(client, token, "closeRecruitTicket", {"id":"3"}, "shop-end-close").status_code == 200
            assert post(client, token, "shopAction", {"buy":[],"recycle":[],"leave":1},
                        "shop-end-leave").status_code == 200
        started = begin(client, token, body() | {"to":{"x":sequence.index("BATTLE_NORMAL"),"y":0}},
                        "shop-end-battle")
        assert started.status_code == 200, started.text
        reply = defeat(client, token, started.json()["battleId"], journal, "shop-end-defeat")
        assert reply.status_code == 200, reply.text


@pytest.mark.parametrize("scene", [False, True])
def test_shop_is_one_node_bought_ticket_is_not_item_or_recruit_score_and_ack_restores(shop_ending_runtime, scene):
    runtime, token = shop_ending_runtime
    to_defeat(runtime, token, scene=scene)
    before = runtime.sync(token)["user"]
    steps, score = 2 + int(scene), 6 + int(scene)
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "shop-end-ack")
        assert reply.status_code == 200, reply.text
        result = reply.json()
        assert result["game"]["record"]["cntArrivedNode"] == steps
        assert result["game"]["record"]["cntRecruitChar"] == 2
        assert result["game"]["score"]["detail"] == [[0,0],[steps,steps],[0,0],[0,0],[0,0],[0,0],[2,4]]
        assert result["game"]["score"]["score"] == score
        after = runtime.sync(token)["user"]
        assert apply(before, result["playerDataDelta"]) == after
        assert after["rlv2"]["current"] == no_run()
        assert after["rlv2"]["outer"]["rogue_1"]["bp"]["point"] == score
        assert {k:v for k,v in before.items() if k != "rlv2"} == {k:v for k,v in after.items() if k != "rlv2"}
        for key in ("shop-end-ack", "shop-end-new-sequence"):
            repeated = post(client, token, "gameSettle", {}, key)
            assert repeated.status_code == 200 and repeated.json()["game"] == result["game"]
        saved = rows(runtime.database.path)
        with runtime.database.transaction(write=False) as session:
            ending = session.query(m.RogueGameSettlement).one()
            assert ending.policy_version == SHOP_POLICY and len(ending.facts["shops"]) == 1
            assert len(ending.facts["scenes"]) == int(scene)
        reopened = Runtime(runtime.settings)
        try:
            assert reopened.sync(token)["user"] == after
        finally:
            reopened.database.close()
        backup = BackupService(runtime)
        name = backup.create()["name"]
        backup.restore(name)
        assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == after


def test_future_prepared_shop_keeps_original_policy_counts_and_hash_compatibility(shop_ending_runtime):
    runtime, token = shop_ending_runtime
    to_defeat(runtime, token, shop_first=False)
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "unvisited-shop")
        assert reply.status_code == 200, reply.text
        assert reply.json()["game"]["score"]["score"] == 5
    with runtime.database.transaction(write=False) as session:
        row = session.query(m.RogueGameSettlement).one()
        assert row.policy_version == POLICY and "shops" not in row.facts and "scenes" not in row.facts


def test_old_policy_cannot_silently_omit_entered_shop(shop_ending_runtime):
    runtime, token = shop_ending_runtime
    to_defeat(runtime, token)
    with runtime.database.transaction(write=False) as session:
        args = (session.query(m.RogueTopicRun).one(), session.query(m.RogueBattleSettlement).all(),
                session.query(m.RogueRunChar).all(), session.query(m.RogueBattle).all(), (),
                session.query(m.RogueShopVisit).all())
        for policy in (POLICY, SCENE_POLICY):
            with pytest.raises(DomainError):
                facts(*args, policy=policy)


def test_concurrent_ending_sequences_award_one_ledger_and_payment_stays_spent(shop_ending_runtime):
    runtime, token = shop_ending_runtime
    to_defeat(runtime, token)
    second = Runtime(runtime.settings)
    try:
        def ack(pair):
            r, key = pair
            with TestClient(create_game_app(r)) as client:
                return post(client, token, "gameSettle", {}, key).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(ack, ((runtime,"ack-a"),(second,"ack-b")))) == [200,200]
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueGameSettlement).count() == 1
            assert session.query(m.RogueTopicRun).one().gold == 1
            assert session.query(m.RogueRunTicket).count() == 4
    finally:
        second.database.close()


@pytest.mark.parametrize("damage", ["purchase", "quote", "missing", "policy"])
def test_shop_ending_corruption_is_rejected_before_startup_writes(shop_ending_runtime, damage):
    runtime, token = shop_ending_runtime
    to_defeat(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "gameSettle", {}, "ack").status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as con:
        if damage == "purchase":
            con.execute("UPDATE rlv2_shop_visits SET purchases='[]' WHERE state='FINISHED'")
        elif damage == "quote":
            con.execute("UPDATE rlv2_shop_visits SET rule_hash=? WHERE state='FINISHED'", ("0"*64,))
        elif damage == "missing":
            con.execute("DELETE FROM rlv2_shop_visits WHERE state='FINISHED'")
        else:
            con.execute("UPDATE rlv2_game_settlements SET policy_version=?", (SCENE_POLICY,))
    before = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == before


def test_failed_ending_insert_rolls_back_outer_balance_state_and_receipt(shop_ending_runtime):
    runtime, token = shop_ending_runtime
    to_defeat(runtime, token)
    with sqlite3.connect(runtime.settings.database_path) as con:
        con.execute("CREATE TRIGGER reject_shop_end BEFORE INSERT ON rlv2_game_settlements "
                    "BEGIN SELECT RAISE(ABORT,'QA'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "gameSettle", {}, "rollback").status_code == 500
    assert rows(runtime.database.path) == saved
