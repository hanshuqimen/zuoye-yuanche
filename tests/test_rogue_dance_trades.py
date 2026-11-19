"""Authored four-choice dance transactions, not official spawn distribution."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType

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
from terralocal.server.gamedata import rogue_dance
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def dance_runtime(monkeypatch, request):
    original = start_fixture.recruit_tables
    config = {"hp": 6, "gold": 20, "hope": 10} | getattr(request, "param", {})

    def tables():
        value = original()
        detail = value["roguelike_topic_table"]["details"]["rogue_1"]
        for row in detail["init"]:
            if row["modeId"] == "NORMAL":
                row.update(initialHp=config["hp"], initialGold=config["gold"],
                           initialPopulation=config["hope"], initialShield=7)
        targets = {choice: target for choice, target, *_ in rogue_dance.RULES}
        targets[rogue_dance.ESCAPE[0]] = rogue_dance.ESCAPE[1]
        scenes = {rogue_dance.ENTRY, *targets.values()}
        detail["choiceScenes"] = {key: {"id": key, "title": "Authored scene", "description": "QA text",
            "useHiddenMusic": False} for key in scenes}
        choices = {choice: {"id": choice, "title": "Authored option", "type": "TRADE",
            "nextSceneId": target, "sortId": 0, "isHiddenChoice": False,
            "forceShowWhenOnlyLeave": False} for choice, target in targets.items()}
        choices["choice_leave"] = {"id": "choice_leave", "title": "Authored exit", "type": "LEAVE",
            "nextSceneId": None, "sortId": 0, "isHiddenChoice": False, "forceShowWhenOnlyLeave": False}
        detail["choices"] = choices
        monkeypatch.setattr(rogue_dance, "RULES", tuple((choice, target, fingerprint(choices[choice]), delta, minimum)
            for choice, target, _, delta, minimum in rogue_dance.RULES))
        monkeypatch.setattr(rogue_dance, "ESCAPE", (rogue_dance.ESCAPE[0], rogue_dance.ESCAPE[1],
                                                   fingerprint(choices[rogue_dance.ESCAPE[0]])))
        monkeypatch.setattr(rogue_dance, "LEAVE_DIGEST", fingerprint(choices["choice_leave"]))
        return value

    monkeypatch.setattr(start_fixture, "recruit_tables", tables)
    return request.getfixturevalue("ending_runtime")


def setup(runtime, token, wanted):
    selection = next(s for s in rogue_dance.SELECTIONS if wanted in s)
    key = rogue_dance.PROGRAMS[rogue_dance.SELECTIONS.index(selection)]
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1),
                 Plan("zone_1", (Column(1, 1, (Entry("INCIDENT", 1),)),), 0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "activate").status_code == 200
    with runtime.database.transaction() as session:
        prepare(Context(session, runtime.data, 1), {Point(0, 0): key})
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, "move").status_code == 200
    return selection


@pytest.mark.parametrize("choice,hp,gold,hope", [(1, 14, 10, 10), (2, 6, 10, 16),
    (3, 16, 20, 6), (4, 1, 20, 18), (5, 1, 35, 10)])
def test_five_trades_preserve_other_properties_and_retry_once(dance_runtime, choice, hp, gold, hope):
    runtime, token = dance_runtime
    subset = setup(runtime, token, choice)
    before = runtime.sync(token)["user"]
    props = before["rlv2"]["current"]["player"]["property"]
    options = current(runtime, token)["player"]["pending"][0]["content"]["scene"]["choices"]
    assert options == {**{"choice_exchange_"+str(n): True for n in subset}, "choice_exchange_6": True}
    with TestClient(create_game_app(runtime)) as client:
        body = {"choice": "choice_exchange_"+str(choice)}
        response = post(client, token, "selectChoice", body, "pay")
        assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        expected = props | {"hp": props["hp"] | {"current": hp}, "gold": gold,
                            "population": props["population"] | {"max": hope}}
        assert after["rlv2"]["current"]["player"]["property"] == expected
        assert props["population"]["cost"] == 6 and expected["shield"] == 7
        for seq in ("pay", "another-sequence"):
            assert post(client, token, "selectChoice", body, seq).status_code == 200
        assert runtime.sync(token)["user"] == after
    # One representative result-page recovery, not five identical restores.
    if choice == 3:
        service = BackupService(runtime)
        backup = service.create()
        saved = rows(runtime.database.path)
        service.restore(backup["name"])
        assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == after
        restarted = Runtime(runtime.settings)
        try:
            assert restarted.sync(token)["user"] == after
        finally:
            restarted.database.close()
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "selectChoice", {"choice": "choice_leave"}, "leave").status_code == 200
    final = runtime.sync(token)["user"]
    assert final["rlv2"]["current"]["player"]["property"] == expected
    assert {k: v for k, v in final.items() if k != "rlv2"} == {k: v for k, v in before.items() if k != "rlv2"}


@pytest.mark.parametrize("dance_runtime,choice", [({"gold": 9}, 1), ({"gold": 9}, 2),
    ({"hope": 9}, 3), ({"hp": 5}, 4), ({"hp": 5}, 5)], indirect=["dance_runtime"])
def test_unaffordable_trade_keeps_escape_and_cannot_spend_shield_or_used_hope(dance_runtime, choice):
    runtime, token = dance_runtime
    subset = setup(runtime, token, choice)
    before = runtime.sync(token)["user"]
    options = current(runtime, token)["player"]["pending"][0]["content"]["scene"]["choices"]
    assert options["choice_exchange_"+str(choice)] is False and options["choice_exchange_6"] is True
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "selectChoice", {"choice": "choice_exchange_"+str(choice)}, "bad-pay").status_code == 409
        assert rows(runtime.database.path) == saved
        missing = next(n for n in range(1, 6) if n not in subset)
        assert post(client, token, "selectChoice", {"choice": "choice_exchange_"+str(missing)}, "missing").status_code == 409
        assert rows(runtime.database.path) == saved
        assert post(client, token, "selectChoice", {"choice": "choice_exchange_6"}, "escape").status_code == 200
        assert post(client, token, "selectChoice", {"choice": "choice_leave"}, "leave").status_code == 200
    assert current(runtime, token)["player"]["property"] == before["rlv2"]["current"]["player"]["property"]


def test_all_explicit_subsets_have_four_choices_and_whole_family_rejects_changed_rows(dance_runtime):
    runtime, _ = dance_runtime
    programs = runtime.data.rogue_dance_events
    assert set(programs) == {"rogue1-dance-"+s+"-v1" for s in (
        "123", "124", "125", "134", "135", "145", "234", "235", "245", "345")}
    for program in programs.values():
        assert len(program.frames[program.entry].branches) == 4
        assert program.frames[program.entry].branches[-1].choice == "choice_exchange_6"
    catalog = runtime.data.rogue_scenes
    original = catalog.choices
    catalog.choices = MappingProxyType({k: v for k, v in original.items() if k != "choice_exchange_5"})
    try:
        with pytest.raises(ValueError):
            rogue_dance.programs(catalog)
    finally:
        catalog.choices = original


def test_fault_rolls_back_hope_payment_and_two_sequences_apply_once(dance_runtime):
    runtime, token = dance_runtime
    setup(runtime, token, 3)
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("CREATE TRIGGER fail_dance BEFORE UPDATE ON rlv2_scene_visits BEGIN SELECT RAISE(ABORT,'QA'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "selectChoice", {"choice": "choice_exchange_3"}, "rollback").status_code == 500
    assert rows(runtime.database.path) == saved
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TRIGGER fail_dance")

    def choose(index):
        with TestClient(create_game_app(runtime)) as client:
            return post(client, token, "selectChoice", {"choice": "choice_exchange_3"}, "pay-"+str(index))
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(choose, (1, 2)))
    assert all(r.status_code == 200 for r in replies)
    props = current(runtime, token)["player"]["property"]
    assert props["hp"]["current"] == 16 and props["population"] == {"cost": 6, "max": 6}
    with runtime.database.transaction(write=False) as session:
        assert len(session.query(m.RogueSceneVisit).one().steps) == 1
