"""Paid scene transactions on authored data; not official encounter pools."""

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
from terralocal.server.gamedata.rogue_events import GOLD_HOPE_PROGRAM, Branch, Delta, EventSpec, Frame
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def trade_runtime(monkeypatch, request):
    original = start_fixture.recruit_tables
    gold = getattr(request, "param", 6)

    def tables():
        value = original()
        detail = value["roguelike_topic_table"]["details"]["rogue_1"]
        for row in detail["init"]:
            if row["modeId"] == "NORMAL" and row["modeGrade"] == 0:
                row["initialGold"] = gold
        detail["choiceScenes"] = {key: {"id": key, "title": "Authored scene",
            "description": "Authored text", "useHiddenMusic": False} for key in ("entry", "bought", "declined")}
        detail["choices"] = {key: {"id": key, "title": "Authored choice", "type": kind,
            "nextSceneId": target, "sortId": 0, "isHiddenChoice": False, "forceShowWhenOnlyLeave": False}
            for key, kind, target in (("pay", "TRADE", "bought"), ("decline", "NEXT", "declined"),
                                      ("leave", "LEAVE", None))}
        return value

    def programs(c):
        def b(key, d=Delta(), minimum=()):
            return Branch(key, c.choices[key].digest, d, minimum)

        spec = EventSpec(GOLD_HOPE_PROGRAM, "entry", (
            Frame("entry", (b("pay", Delta(gold=-5, hope_max=3), (("gold", 5),)), b("decline"))),
            Frame("bought", (b("leave"),)), Frame("declined", (b("leave"),))), "Authored QA trade")
        return {spec.id: c.compile(spec)}

    monkeypatch.setattr(start_fixture, "recruit_tables", tables)
    monkeypatch.setattr(rogue_events, "trade_programs", programs)
    return request.getfixturevalue("ending_runtime")


def setup(runtime, token, count=1):
    with runtime.database.transaction() as s:
        save_map(Context(s, runtime.data, 1), Plan("zone_1", (Column(1, 1, (Entry("INCIDENT", 1),)),) * count, 0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "activate-map").status_code == 200
    with runtime.database.transaction() as s:
        prepare(Context(s, runtime.data, 1), {Point(x, 0): GOLD_HOPE_PROGRAM for x in range(count)})


def move(client, token, x, seq):
    return post(client, token, "moveTo", {"to": {"x": x, "y": 0}}, seq)


@pytest.mark.parametrize("trade_runtime", [0, 4, 5, 6], indirect=True)
def test_cost_boundaries_disable_pay_keep_decline_and_commit_both_resource_legs(trade_runtime):
    runtime, token = trade_runtime
    setup(runtime, token)
    initial = runtime.sync(token)["user"]
    gold = initial["rlv2"]["current"]["player"]["property"]["gold"]
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "move").status_code == 200
        scene = current(runtime, token)["player"]["pending"][0]["content"]["scene"]
        assert scene["choices"] == {"pay": gold >= 5, "decline": True}
        saved = rows(runtime.database.path)
        assert post(client, token, "finishEvent", {}, "cannot-skip-choice").status_code == 409
        if gold < 5:
            assert post(client, token, "selectChoice", {"choice": "pay"}, "no-money").status_code == 409
            assert rows(runtime.database.path) == saved
            selected = "decline"
        else:
            selected = "pay"
        before = runtime.sync(token)["user"]
        reply = post(client, token, "selectChoice", {"choice": selected}, "decision")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        for seq in ("decision", "decision-new"):
            assert post(client, token, "selectChoice", {"choice": selected}, seq).status_code == 200
        assert runtime.sync(token)["user"] == after
        props = after["rlv2"]["current"]["player"]["property"]
        assert props["gold"] == gold - (5 if selected == "pay" else 0)
        assert props["population"] == initial["rlv2"]["current"]["player"]["property"]["population"] | {
            "max": 9 if selected == "pay" else 6}
        assert current(runtime, token)["player"]["pending"][0]["content"]["scene"]["id"] == (
            "bought" if selected == "pay" else "declined")
        reopened = Runtime(runtime.settings)
        try:
            assert reopened.sync(token)["user"] == after
        finally:
            reopened.database.close()
        assert post(client, token, "selectChoice", {"choice": "leave"}, "leave").status_code == 200
        assert post(client, token, "finishEvent", {}, "exit-retry").status_code == 200
    final = runtime.sync(token)["user"]
    assert {k: v for k, v in final.items() if k != "rlv2"} == {k: v for k, v in initial.items() if k != "rlv2"}
    saved = rows(runtime.database.path)
    service = BackupService(runtime)
    backup = service.create()
    service.restore(backup["name"])
    assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == final


def test_payment_failure_rolls_back_both_legs_then_concurrent_new_sequences_charge_once(trade_runtime):
    runtime, token = trade_runtime
    setup(runtime, token, 2)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "move").status_code == 200
    with sqlite3.connect(runtime.database.path) as c:
        c.execute("CREATE TRIGGER fail_payment BEFORE UPDATE ON rlv2_scene_visits BEGIN SELECT RAISE(ABORT,'QA'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "selectChoice", {"choice": "pay"}, "rollback").status_code == 500
    assert rows(runtime.database.path) == saved
    with sqlite3.connect(runtime.database.path) as c:
        c.execute("DROP TRIGGER fail_payment")

    def choose(n):
        with TestClient(create_game_app(runtime)) as client:
            return post(client, token, "selectChoice", {"choice": "pay"}, "pay" + str(n))

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(choose, (1, 2)))
    assert all(r.status_code == 200 for r in replies)
    props = current(runtime, token)["player"]["property"]
    assert props["gold"] == 1 and props["population"]["max"] == 9
    with runtime.database.transaction(write=False) as s:
        assert len(s.query(m.RogueSceneVisit).filter_by(node_x=0).one().steps) == 1
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "selectChoice", {"choice": "leave"}, "exit").status_code == 200
        assert move(client, token, 1, "next-scene").status_code == 200
        assert current(runtime, token)["player"]["pending"][0]["content"]["scene"]["choices"] == {
            "pay": False, "decline": True}
        assert post(client, token, "selectChoice", {"choice": "decline"}, "no-second-buy").status_code == 200
        assert post(client, token, "selectChoice", {"choice": "leave"}, "exit-second").status_code == 200
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == runtime.sync(token)["user"]
    finally:
        reopened.database.close()
