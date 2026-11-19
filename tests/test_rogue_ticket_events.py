"""Authored fixed ticket sources, causal identity and mandatory recruit barrier."""

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
from terralocal.server.gamedata import rogue_ticket_events as events
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def test_null_display_metadata_is_a_controlled_catalog_rejection():
    # Custom data can retain a valid scene catalog while omitting ITEM display
    # metadata. It must fail admission, not leak an AttributeError to a caller.
    source = events.SOURCES[0]
    data = SimpleNamespace(
        rogue_scenes=SimpleNamespace(choices={source[2]: SimpleNamespace(target=source[3])}),
        rogue_upgrades=SimpleNamespace(tickets={source[4]}),
        table=lambda _: {"details": {"rogue_1": {"choices": {source[2]: {"displayData": None}}}}})
    with pytest.raises(ValueError, match="事件进阶券"):
        events.programs(data)


@pytest.fixture
def ticket_event_runtime(monkeypatch, request):
    original = start_fixture.recruit_tables
    profession, rarity = getattr(request, "param", ("PIONEER", 6))

    def tables():
        value = original()
        detail = value["roguelike_topic_table"]["details"]["rogue_1"]
        upgrade = upgrade_source()
        detail["items"].update(upgrade["items"])
        detail["upgradeTickets"] = upgrade["upgradeTickets"]
        detail["detailConst"]["charUpgradeTable"] = upgrade["detailConst"]["charUpgradeTable"]
        value["character_table"]["char_six"].update(profession=profession, rarity="TIER_"+str(rarity))
        # Replace the base fixture's deliberately skeletal placeholder scene.
        detail["choiceScenes"] = {}
        detail["choices"] = {}
        for _, entry, choice, target, ticket, _ in events.SOURCES:
            for scene in (entry, target):
                detail["choiceScenes"][scene] = {"id": scene, "title": "Authored scene",
                    "description": "QA text", "useHiddenMusic": False}
            detail["choices"][choice] = {"id": choice, "title": "Authored fixed reward", "type": "TRADE",
                "nextSceneId": target, "sortId": 0, "isHiddenChoice": False,
                "forceShowWhenOnlyLeave": False, "displayData": {"type": "ITEM", "itemId": ticket}}
        detail["choices"]["choice_leave"] = {"id": "choice_leave", "title": "Authored exit", "type": "LEAVE",
            "nextSceneId": None, "sortId": 0, "isHiddenChoice": False, "forceShowWhenOnlyLeave": False}
        monkeypatch.setattr(events, "LEAVE_DIGEST", fingerprint(detail["choices"]["choice_leave"]))
        monkeypatch.setattr(events, "SOURCES", tuple((*row[:-1], fingerprint(detail["choices"][row[2]]))
                                                     for row in events.SOURCES))
        return value

    monkeypatch.setattr(start_fixture, "recruit_tables", tables)
    return request.getfixturevalue("ending_runtime")


def setup(runtime, token, source, count=1):
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1),
                 Plan("zone_1", (Column(1, 1, (Entry("INCIDENT", 1),)),) * count, 0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "activate-map").status_code == 200
    with runtime.database.transaction() as session:
        prepare(Context(session, runtime.data, 1), {Point(x, 0): source[0] for x in range(count)})
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, "move").status_code == 200


@pytest.mark.parametrize("ticket_event_runtime,which,has_target", [(("PIONEER", 5), 0, True),
    (("PIONEER", 6), 0, False), (("PIONEER", 6), 1, True)], indirect=["ticket_event_runtime"])
def test_fixed_ticket_grant_filter_barrier_zero_hope_and_result_recovery(ticket_event_runtime, which, has_target):
    runtime, token = ticket_event_runtime
    source = events.SOURCES[which]
    setup(runtime, token, source)
    before = runtime.sync(token)["user"]
    main_roster = copy.deepcopy(before["troop"])
    with TestClient(create_game_app(runtime)) as client:
        response = post(client, token, "selectChoice", {"choice": source[2]}, "grant")
        assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        ticket = current(runtime, token)["inventory"]["recruit"]["3"]
        assert ticket["id"] == source[4] and ticket["state"] == "ACTIVE"
        assert bool(ticket["list"]) == has_target
        if has_target:
            assert all(c["population"] == 0 and c["isUpgrade"] for c in ticket["list"])
        for seq in ("grant", "new-grant"):
            assert post(client, token, "selectChoice", {"choice": source[2]}, seq).status_code == 200
        assert runtime.sync(token)["user"] == after
        saved = rows(runtime.database.path)
        for route, body in (("selectChoice", {"choice": "choice_leave"}), ("finishEvent", {})):
            assert post(client, token, route, body, "blocked-"+route).status_code == 409
            assert rows(runtime.database.path) == saved
    if has_target and which == 0:
        backups = BackupService(runtime)
        backup = backups.create()
        saved = rows(runtime.database.path)
        backups.restore(backup["name"])
        assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == after
        restarted = Runtime(runtime.settings)
        try:
            assert restarted.sync(token)["user"] == after
        finally:
            restarted.database.close()
    with TestClient(create_game_app(runtime)) as client:
        if has_target:
            option = ticket["list"][0]
            reply = post(client, token, "recruitChar", {"ticketIndex": "3", "optionId": str(option["instId"])}, "upgrade")
            assert reply.status_code == 200, reply.text
            assert post(client, token, "recruitChar", {"ticketIndex": "3", "optionId": str(option["instId"])}, "upgrade").json() == reply.json()
            saved = rows(runtime.database.path)
            assert post(client, token, "recruitChar", {"ticketIndex": "3", "optionId": str(option["instId"])}, "retry-upgrade").status_code == 409
            assert rows(runtime.database.path) == saved
        else:
            assert post(client, token, "closeRecruitTicket", {"id": "3"}, "discard-empty").status_code == 200
        assert post(client, token, "selectChoice", {"choice": "choice_leave"}, "leave").status_code == 200
    final = runtime.sync(token)["user"]
    assert final["troop"] == main_roster
    assert final["rlv2"]["current"]["player"]["property"] == before["rlv2"]["current"]["player"]["property"]
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueRunTicket).count() == 4
        assert session.query(m.RogueSceneVisit).one().state == "FINISHED"


def test_failed_grant_rolls_back_and_concurrent_new_sequences_issue_one_ticket(ticket_event_runtime):
    runtime, token = ticket_event_runtime
    source = events.SOURCES[1]
    setup(runtime, token, source)
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("CREATE TRIGGER fail_event_ticket BEFORE INSERT ON rlv2_tickets WHEN NEW.ordinal>=3 BEGIN SELECT RAISE(ABORT,'QA'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "selectChoice", {"choice": source[2]}, "fail").status_code == 500
    assert rows(runtime.database.path) == saved
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TRIGGER fail_event_ticket")

    def choose(index):
        with TestClient(create_game_app(runtime)) as client:
            return post(client, token, "selectChoice", {"choice": source[2]}, "grant-"+str(index))
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(choose, (1, 2)))
    assert all(r.status_code == 200 for r in replies)
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueRunTicket).count() == 4
        assert len(session.query(m.RogueSceneVisit).one().steps) == 1


@pytest.mark.parametrize("damage", ["ticket_type", "source_ordinal", "missing_source"])
def test_tampered_fixed_reward_source_is_rejected_without_rewriting_save(ticket_event_runtime, damage):
    runtime, token = ticket_event_runtime
    source = events.SOURCES[1]
    setup(runtime, token, source)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "selectChoice", {"choice": source[2]}, "grant").status_code == 200
    with runtime.database.transaction() as session:
        visit = session.query(m.RogueSceneVisit).one()
        if damage == "ticket_type":
            session.query(m.RogueRunTicket).filter_by(ordinal=3).one().item_id = events.SOURCES[0][4]
        elif damage == "source_ordinal":
            visit.steps = [visit.steps[0] | {"ticket": 4}]
        else:
            visit.steps = [visit.steps[0] | {"choice": "choice_leave"}]
    corrupt = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == corrupt
    runtime.database.close()
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest
