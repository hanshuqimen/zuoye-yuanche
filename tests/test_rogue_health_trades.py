"""Authored life-payment transactions; actual frozen rows are checked separately."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_ending import ending_runtime as ending_runtime
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_visits import prepare
from terralocal.server.gamedata import rogue_events
from terralocal.server.gamedata.rogue_events import HEALTH_GOLD_PROGRAM, Branch, Delta, EventSpec, Frame
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def health_trade_runtime(monkeypatch, request):
    original = start_fixture.recruit_tables
    hp = getattr(request, "param", 4)

    def tables():
        value = original()
        detail = value["roguelike_topic_table"]["details"]["rogue_1"]
        for row in detail["init"]:
            if row["modeId"] == "NORMAL" and row["modeGrade"] == 0:
                row.update(initialHp=hp, initialShield=8)
        detail["choiceScenes"] = {key: {"id": key, "title": "Authored scene",
            "description": "Authored text", "useHiddenMusic": False} for key in ("entry", "paid", "declined")}
        detail["choices"] = {key: {"id": key, "title": "Authored choice", "type": kind,
            "nextSceneId": target, "sortId": 0, "isHiddenChoice": False, "forceShowWhenOnlyLeave": False}
            for key, kind, target in (("pay", "TRADE", "paid"), ("decline", "NEXT", "declined"),
                                      ("leave", "LEAVE", None))}
        return value

    def programs(catalog):
        def branch(choice, delta=Delta(), minimum=()):
            return Branch(choice, catalog.choices[choice].digest, delta, minimum)

        spec = EventSpec(HEALTH_GOLD_PROGRAM, "entry", (
            Frame("entry", (branch("pay", Delta(hp=-2, gold=8), (("hp", 3),)), branch("decline"))),
            Frame("paid", (branch("leave"),)), Frame("declined", (branch("leave"),))),
            "Authored QA life trade; no official data or encounter weights")
        return {spec.id: catalog.compile(spec)}

    monkeypatch.setattr(start_fixture, "recruit_tables", tables)
    monkeypatch.setattr(rogue_events, "health_trade_programs", programs)
    return request.getfixturevalue("ending_runtime")


def setup(runtime, token, count=1):
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1),
                 Plan("zone_1", (Column(1, 1, (Entry("INCIDENT", 1),)),) * count, 0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "activate").status_code == 200
    with runtime.database.transaction() as session:
        prepare(Context(session, runtime.data, 1), {Point(x, 0): HEALTH_GOLD_PROGRAM for x in range(count)})


def move(client, token, x=0):
    return post(client, token, "moveTo", {"to": {"x": x, "y": 0}}, "move-"+str(x))


@pytest.mark.parametrize("health_trade_runtime", [1, 2, 3, 4], indirect=True)
def test_life_boundary_preserves_one_lp_and_never_spends_shield(health_trade_runtime):
    runtime, token = health_trade_runtime
    setup(runtime, token)
    initial = runtime.sync(token)["user"]
    props = initial["rlv2"]["current"]["player"]["property"]
    hp, gold = props["hp"]["current"], props["gold"]
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        choices = current(runtime, token)["player"]["pending"][0]["content"]["scene"]["choices"]
        assert choices == {"pay": hp >= 3, "decline": True}
        before = runtime.sync(token)["user"]
        saved = rows(runtime.database.path)
        assert post(client, token, "finishEvent", {}, "cannot-skip").status_code == 409
        if hp < 3:
            assert post(client, token, "selectChoice", {"choice": "pay"}, "no-life").status_code == 409
            assert rows(runtime.database.path) == saved
            choice = "decline"
        else:
            choice = "pay"
        reply = post(client, token, "selectChoice", {"choice": choice}, "decision")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        changed = after["rlv2"]["current"]["player"]["property"]
        assert changed == props | {
            "hp": props["hp"] | {"current": hp-(2 if choice == "pay" else 0)},
            "gold": gold+(8 if choice == "pay" else 0)}
        assert changed["shield"] == 8
        for seq in ("decision", "new-decision"):
            assert post(client, token, "selectChoice", {"choice": choice}, seq).status_code == 200
        assert runtime.sync(token)["user"] == after
        assert post(client, token, "selectChoice", {"choice": "leave"}, "leave").status_code == 200
        assert post(client, token, "finishEvent", {}, "leave-retry").status_code == 200
    final = runtime.sync(token)["user"]
    assert {k:v for k,v in final.items() if k != "rlv2"} == {k:v for k,v in initial.items() if k != "rlv2"}


def test_result_restart_backup_and_decline_keep_both_resource_legs(health_trade_runtime):
    runtime, token = health_trade_runtime
    setup(runtime, token, 2)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert post(client, token, "selectChoice", {"choice":"pay"}, "pay").status_code == 200
    pending = runtime.sync(token)["user"]
    saved = rows(runtime.database.path)
    backups = BackupService(runtime)
    backup = backups.create()
    backups.restore(backup["name"])
    assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == pending
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == pending
        with TestClient(create_game_app(reopened)) as client:
            assert post(client, token, "selectChoice", {"choice":"pay"}, "retry-after-restart").status_code == 200
            assert reopened.sync(token)["user"] == pending
            assert post(client, token, "selectChoice", {"choice":"leave"}, "leave").status_code == 200
            assert move(client, token, 1).status_code == 200
            assert current(reopened, token)["player"]["pending"][0]["content"]["scene"]["choices"] == {
                "pay":False, "decline":True}
            assert post(client, token, "selectChoice", {"choice":"decline"}, "decline").status_code == 200
            assert post(client, token, "selectChoice", {"choice":"leave"}, "leave-second").status_code == 200
        assert current(reopened, token)["player"]["property"] == pending["rlv2"]["current"]["player"]["property"]
    finally:
        reopened.database.close()


def test_fault_rolls_back_payment_and_concurrent_requests_apply_it_once(health_trade_runtime):
    runtime, token = health_trade_runtime
    setup(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("CREATE TRIGGER fail_life BEFORE UPDATE ON rlv2_scene_visits BEGIN SELECT RAISE(ABORT,'QA'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "selectChoice", {"choice":"pay"}, "rollback").status_code == 500
    assert rows(runtime.database.path) == saved
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TRIGGER fail_life")

    def choose(index):
        with TestClient(create_game_app(runtime)) as client:
            return post(client, token, "selectChoice", {"choice":"pay"}, "pay-"+str(index))

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(choose, (1, 2)))
    assert all(reply.status_code == 200 for reply in replies)
    props = current(runtime, token)["player"]["property"]
    assert props["hp"]["current"] == 2 and props["gold"] == 14
    with runtime.database.transaction(write=False) as session:
        assert len(session.query(m.RogueSceneVisit).one().steps) == 1
