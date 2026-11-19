"""Authored fixed ordinary recruit source, atomic payment and causal replay."""

import copy
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_ending import ending_runtime as ending_runtime
from test_rogue_upgrade_rules import source as upgrade_source
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_visits import prepare
from terralocal.server.gamedata import rogue_recruit_events as events
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_upgrades import PROFESSIONS, RARITIES
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def recruit_event_runtime(monkeypatch, request):
    original = start_fixture.recruit_tables
    gold = getattr(request, "param", 5)

    def tables():
        value = original()
        detail = value["roguelike_topic_table"]["details"]["rogue_1"]
        upgrade = upgrade_source()
        detail["items"].update(upgrade["items"])
        detail["upgradeTickets"] = upgrade["upgradeTickets"]
        detail["detailConst"]["charUpgradeTable"] = upgrade["detailConst"]["charUpgradeTable"]
        for row in detail["init"]:
            if row["modeId"] == "NORMAL" and row["modeGrade"] == 0:
                row.update(initialGold=gold, initialPopulation=8)
        detail["recruitTickets"][events.TICKET] = {"id": events.TICKET, "profession": 639, "rarity": "ALL",
            "professionList": sorted(PROFESSIONS), "rarityList": sorted(RARITIES),
            "extraEliteNum": 0, "extraFreeRarity": [], "extraCharIds": ["char_reserve"]}
        detail["items"][events.TICKET] = {"id": events.TICKET, "type": "RECRUIT_TICKET"}
        detail["choiceScenes"] = {key: {"id": key, "title": "Authored scene", "description": "QA text",
            "useHiddenMusic": False} for key in (events.ENTRY, events.TARGET, events.EXIT_TARGET)}
        detail["choices"] = {key: {"id": key, "title": "Authored choice", "type": kind,
            "nextSceneId": target, "sortId": 0, "isHiddenChoice": False, "forceShowWhenOnlyLeave": False}
            for key, kind, target in ((events.CHOICE, "TRADE", events.TARGET),
                (events.EXIT_CHOICE, "NEXT", events.EXIT_TARGET), ("choice_leave", "LEAVE", None))}
        detail["choices"][events.CHOICE]["displayData"] = {"type": "ITEM", "itemId": events.TICKET}
        for name, choice in (("CHOICE_DIGEST", events.CHOICE), ("EXIT_DIGEST", events.EXIT_CHOICE),
                             ("LEAVE_DIGEST", "choice_leave")):
            monkeypatch.setattr(events, name, fingerprint(detail["choices"][choice]))
        return value

    monkeypatch.setattr(start_fixture, "recruit_tables", tables)
    runtime, token = request.getfixturevalue("ending_runtime")
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        for cid in ("char_zero", "char_four", "char_five"):
            ctx.acquire_operator(cid)
    return runtime, token


def setup(runtime, token):
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), Plan("zone_1", (Column(1, 1, (Entry("INCIDENT", 1),)),), 0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "activate-map").status_code == 200
    with runtime.database.transaction() as session:
        prepare(Context(session, runtime.data, 1), {Point(0, 0): events.PROGRAM})
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, "move").status_code == 200


def test_paid_source_normal_hope_cost_barrier_delta_and_result_recovery(recruit_event_runtime):
    runtime, token = recruit_event_runtime
    setup(runtime, token)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        response = post(client, token, "selectChoice", {"choice": events.CHOICE}, "grant")
        assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        state = current(runtime, token)
        assert state["player"]["property"]["gold"] == 0
        ticket = state["inventory"]["recruit"]["3"]
        assert ticket["id"] == events.TICKET and ticket["state"] == "ACTIVE"
        options = {o["charId"]: o for o in ticket["list"] if not o["isUpgrade"]}
        assert {cid: options[cid]["population"] for cid in ("char_zero", "char_four", "char_five")} == {
            "char_zero": 0, "char_four": 2, "char_five": 3}
        for key in ("grant", "grant-new"):
            assert post(client, token, "selectChoice", {"choice": events.CHOICE}, key).status_code == 200
        assert runtime.sync(token)["user"] == after
        saved = rows(runtime.database.path)
        for route, payload in (("selectChoice", {"choice": "choice_leave"}), ("finishEvent", {}),
                               ("selectChoice", {"choice": "choice_recruit1_1"})):
            assert post(client, token, route, payload, "blocked-"+route+str(len(payload))).status_code == 409
            assert rows(runtime.database.path) == saved
        backups = BackupService(runtime)
        backup = backups.create()
        backups.restore(backup["name"])
        assert runtime.sync(token)["user"] == after and rows(runtime.database.path) == saved
        five = {"ticketIndex": "3", "optionId": str(options["char_five"]["instId"])}
        denied = post(client, token, "recruitChar", five, "unaffordable")
        assert denied.status_code == 400 and denied.json()["error"]["code"] == "ROGUE_HOPE_REQUIRED"
        assert rows(runtime.database.path) == saved
        four = {"ticketIndex": "3", "optionId": str(options["char_four"]["instId"])}
        reply = post(client, token, "recruitChar", four, "recruit")
        assert reply.status_code == 200, reply.text
        assert post(client, token, "recruitChar", four, "recruit").json() == reply.json()
        after_recruit = rows(runtime.database.path)
        assert post(client, token, "recruitChar", four, "another-recruit").status_code == 409
        assert rows(runtime.database.path) == after_recruit
        assert post(client, token, "selectChoice", {"choice": "choice_leave"}, "leave").status_code == 200
    final = runtime.sync(token)["user"]
    assert final["troop"] == before["troop"]
    props = final["rlv2"]["current"]["player"]["property"]
    assert props["gold"] == 0 and props["population"]["cost"] == 8
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == final
    finally:
        restarted.database.close()


@pytest.mark.parametrize("recruit_event_runtime", [4, 5], indirect=True)
def test_exact_gold_gate_and_narrative_exit_issue_no_ticket(recruit_event_runtime):
    runtime, token = recruit_event_runtime
    setup(runtime, token)
    before = current(runtime, token)
    gold = before["player"]["property"]["gold"]
    choices = before["player"]["pending"][0]["content"]["scene"]["choices"]
    assert choices == {events.CHOICE: gold >= 5, events.EXIT_CHOICE: True}
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        if gold < 5:
            assert post(client, token, "selectChoice", {"choice": events.CHOICE}, "poor").status_code == 409
            assert rows(runtime.database.path) == saved
        # The unimplemented probabilistic branch must not become a free or
        # all-profession source just because it is present in a client table.
        assert post(client, token, "selectChoice", {"choice": "choice_recruit1_1"}, "unknown").status_code == 409
        assert rows(runtime.database.path) == saved
        assert post(client, token, "selectChoice", {"choice": events.EXIT_CHOICE}, "decline").status_code == 200
        assert post(client, token, "selectChoice", {"choice": "choice_leave"}, "leave").status_code == 200
    state = current(runtime, token)
    assert state["player"]["property"] == before["player"]["property"]
    assert state["inventory"]["recruit"] == before["inventory"]["recruit"]


def test_failed_payment_and_concurrent_requests_issue_only_once(recruit_event_runtime):
    runtime, token = recruit_event_runtime
    setup(runtime, token)
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("CREATE TRIGGER fail_ticket BEFORE INSERT ON rlv2_tickets WHEN NEW.ordinal>=3 BEGIN SELECT RAISE(ABORT,'QA'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "selectChoice", {"choice": events.CHOICE}, "failed").status_code == 500
    assert rows(runtime.database.path) == saved
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TRIGGER fail_ticket")

    def choose(index):
        with TestClient(create_game_app(runtime)) as client:
            return post(client, token, "selectChoice", {"choice": events.CHOICE}, "parallel-"+str(index))
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(r.status_code == 200 for r in pool.map(choose, (1, 2)))
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueRunTicket).count() == 4
        assert session.query(m.RogueSceneVisit).one().steps[0]["ticket"] == 3
    assert current(runtime, token)["player"]["property"]["gold"] == 0


@pytest.mark.parametrize("damage", ["premium", "ordinal", "missing_source"])
def test_corrupt_paid_source_cannot_rewrite_or_load(recruit_event_runtime, damage):
    runtime, token = recruit_event_runtime
    setup(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "selectChoice", {"choice": events.CHOICE}, "grant").status_code == 200
    with runtime.database.transaction() as session:
        visit = session.query(m.RogueSceneVisit).one()
        if damage == "premium":
            session.query(m.RogueRunTicket).filter_by(ordinal=3).one().item_id += "_premium"
        elif damage == "ordinal":
            visit.steps = [visit.steps[0] | {"ticket": 4}]
        else:
            visit.steps = [{"choice": events.EXIT_CHOICE, "at": visit.steps[0]["at"]}]
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == saved
    runtime.database.close()
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("display", [None, {"type": "ITEM", "itemId": "rogue_1_recruit_ticket_all_premium"}])
def test_unknown_or_special_display_is_rejected(recruit_event_runtime, display):
    runtime, _ = recruit_event_runtime
    table = copy.deepcopy(runtime.data.table("roguelike_topic_table"))
    table["details"]["rogue_1"]["choices"][events.CHOICE]["displayData"] = display
    fake = SimpleNamespace(rogue_scenes=runtime.data.rogue_scenes, rogue_recruit=runtime.data.rogue_recruit,
                           table=lambda _: table)
    with pytest.raises(ValueError, match="普通招募事件"):
        events.programs(fake)
