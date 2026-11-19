"""Authored source graphs and causal inventory; no official assets or native win."""

import copy
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType, SimpleNamespace

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_ending import ending_runtime as ending_runtime
from test_rogue_recruit_costs import source as cost_source
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_ending import collected_relics
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_visits import prepare
from terralocal.server.gamedata import rogue_battle_attributes as attributes
from terralocal.server.gamedata import rogue_relic_events as events
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def relic_event_runtime(monkeypatch, request):
    original = start_fixture.recruit_tables

    def tables():
        value = original()
        detail = value["roguelike_topic_table"]["details"]["rogue_1"]
        archive = detail.setdefault("archiveComp", {}).setdefault("relic", {}).setdefault("relic", {})
        # Causal relic replay also validates the established recruit-cost
        # catalog, even when these four acquisitions do not modify that cost.
        costs = cost_source()["details"]["rogue_1"]
        for section in ("items", "relics", "relicParams"):
            detail[section].update(costs[section])
        archive.update(costs["archiveComp"]["relic"]["relic"])
        expected = dict(attributes.SOURCES)
        for n, key in enumerate(sorted(set(events.RELICS.values()))):
            detail["items"][key] = {"id": key, "type": "RELIC", "unlockCondDesc": None}
            detail["relics"][key] = {"id": key, "buffs": [{"key": "char_attribute_add", "blackboard": [
                {"key": "def", "value": float(n + 1), "valueStr": None}]}]}
            detail["relicParams"][key] = {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []}
            archive[key] = {"relicId": key, "enrollId": None, "isSpRelic": False,
                "relicGroupId": 1, "relicSortId": n, "orderId": "QA-" + str(n)}
            expected[key] = fingerprint({"effect": detail["relics"][key],
                "conditions": detail["relicParams"][key], "item_type": "RELIC"})
        monkeypatch.setattr(attributes, "SOURCES", MappingProxyType(expected))
        scenes, choices = {}, {}
        for _, entry, branches in events.SOURCES:
            for scene in (entry, *(b[1] for b in branches)):
                scenes[scene] = {"id": scene, "title": "Authored scene", "description": "QA text",
                                 "useHiddenMusic": False}
            for choice, target, item, delta in branches:
                choices[choice] = {"id": choice, "type": "NEXT" if choice == "choice_4_3" else "TRADE",
                    "nextSceneId": target, "title": "Authored option", "sortId": 0,
                    "isHiddenChoice": False, "forceShowWhenOnlyLeave": False,
                    "displayData": {"type": "ITEM" if item else "NORMAL", "itemId": item}}
        choices["choice_leave"] = {"id": "choice_leave", "type": "LEAVE", "nextSceneId": None,
            "title": "Authored exit", "sortId": 0, "isHiddenChoice": False, "forceShowWhenOnlyLeave": False}
        detail["choiceScenes"], detail["choices"] = scenes, choices
        monkeypatch.setattr(events, "CHOICE_HASHES", MappingProxyType({k: fingerprint(v)
            for k, v in choices.items() if k != "choice_leave"}))
        monkeypatch.setattr(events, "LEAVE_DIGEST", fingerprint(choices["choice_leave"]))
        return value

    monkeypatch.setattr(start_fixture, "recruit_tables", tables)
    return request.getfixturevalue("ending_runtime")


def setup(runtime, token, program, *, battle=False):
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), Plan("zone_1", (
            Column(1, 1, (Entry("INCIDENT", 1),)), Column(1, 1, (
                Entry("BATTLE_NORMAL", 1, "ordinary") if battle else Entry("INCIDENT", 1),))), 0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "activate-map").status_code == 200
    with runtime.database.transaction() as session:
        prepare(Context(session, runtime.data, 1), {Point(0, 0): program})
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, "move").status_code == 200


@pytest.mark.parametrize("program,choice,item", [(p, c, i) for (p, c), i in events.RELICS.items()])
def test_every_fixed_source_grants_once_delta_discovery_and_giveup_score(relic_event_runtime, program, choice, item):
    runtime, token = relic_event_runtime
    setup(runtime, token, program)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "selectChoice", {"choice": choice}, "gain")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        held = after["rlv2"]["current"]["inventory"]["relic"]
        assert list(held) == ["0", "1"] and held["1"]["id"] == item and held["1"]["count"] == 1
        assert held["0"] == before["rlv2"]["current"]["inventory"]["relic"]["0"]
        assert after["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][item]["state"] == 2
        assert after["rlv2"]["current"]["player"]["property"] == before["rlv2"]["current"]["player"]["property"]
        assert after["troop"] == before["troop"]
        for key in ("gain", "gain-new"):
            assert post(client, token, "selectChoice", {"choice": choice}, key).status_code == 200
        assert runtime.sync(token)["user"] == after
        assert post(client, token, "finishEvent", {}, "leave").status_code == 200
        assert post(client, token, "giveUpGame", {}, "close").status_code == 200
        settled = post(client, token, "gameSettle", {}, "settle")
        assert settled.status_code == 200, settled.text
        assert settled.json()["game"]["score"]["detail"][5][0] == 1
        final = runtime.sync(token)["user"]
        assert post(client, token, "gameSettle", {}, "settle-new").status_code == 200
        assert runtime.sync(token)["user"] == final
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueRunRelic).count() == 2  # band plus one source grant
        assert session.query(m.RogueBattle).count() == 0


@pytest.mark.parametrize("program,choice,hp,hope", [
    (events.SOURCES[0][0], "choice_4_3", 0, 0),
    (events.SOURCES[1][0], "choice_bottle1_2", 0, 2),
    (events.SOURCES[2][0], "choice_bottle2_1", 3, 0)])
def test_all_non_relic_alternatives_and_exact_result_edges(relic_event_runtime, program, choice, hp, hope):
    runtime, token = relic_event_runtime
    setup(runtime, token, program)
    before = current(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "selectChoice", {"choice": choice}, "alt").status_code == 200
        state = current(runtime, token)
        target = next(t for p, _, bs in events.SOURCES if p == program for c, t, _, _ in bs if c == choice)
        assert state["player"]["pending"][0]["content"]["scene"]["id"] == target
        assert state["inventory"] == before["inventory"]
        assert state["player"]["property"]["hp"]["current"] == before["player"]["property"]["hp"]["current"] + hp
        assert state["player"]["property"]["population"]["max"] == before["player"]["property"]["population"]["max"] + hope
        assert post(client, token, "selectChoice", {"choice": "choice_leave"}, "leave").status_code == 200


def test_mid_result_restart_backup_and_causal_source_tamper_rejection(relic_event_runtime):
    runtime, token = relic_event_runtime
    program, choice = next(iter(events.RELICS))
    setup(runtime, token, program)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "selectChoice", {"choice": choice}, "gain").status_code == 200
    expected, saved = runtime.sync(token)["user"], rows(runtime.database.path)
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == expected
        backups = BackupService(restarted)
        backup = backups.create()
        backups.restore(backup["name"])
        assert restarted.sync(token)["user"] == expected and rows(runtime.database.path) == saved
    finally:
        restarted.database.close()
    with runtime.database.transaction() as session:
        visit = session.query(m.RogueSceneVisit).one()
        visit.steps = [visit.steps[0] | {"choice": "choice_4_3"}]
    damaged = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == damaged
    runtime.database.close()
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


def test_atomic_failure_then_concurrent_retries_do_not_duplicate_grant(relic_event_runtime):
    runtime, token = relic_event_runtime
    program, choice = next(iter(events.RELICS))
    setup(runtime, token, program)
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("CREATE TRIGGER fail_event_relic BEFORE INSERT ON rlv2_relics WHEN NEW.ordinal>0 "
                    "BEGIN SELECT RAISE(ABORT,'QA'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "selectChoice", {"choice": choice}, "failed").status_code == 500
    assert rows(runtime.database.path) == saved
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TRIGGER fail_event_relic")

    def choose(n):
        with TestClient(create_game_app(runtime)) as client:
            return post(client, token, "selectChoice", {"choice": choice}, "parallel-" + str(n)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(choose, (1, 2))) == [200, 200]
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueRunRelic).count() == 2
        assert len(session.query(m.RogueSceneVisit).one().steps) == 1


@pytest.mark.parametrize("damage", ["item", "count", "layer", "time"])
def test_unearned_or_changed_inventory_fails_readonly_replay(relic_event_runtime, damage):
    runtime, token = relic_event_runtime
    program, choice = next(iter(events.RELICS))
    setup(runtime, token, program)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "selectChoice", {"choice": choice}, "gain").status_code == 200
    with runtime.database.transaction() as session:
        r = session.query(m.RogueRunRelic).filter_by(ordinal=1).one()
        if damage == "item":
            r.item_id = "rogue_1_relic_m14"
        elif damage == "count":
            r.count = 2
        elif damage == "layer":
            r.layer = 1
        else:
            r.acquired_at += 1
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == saved


def test_trusted_plan_duplicate_source_and_changed_item_display_rejected(relic_event_runtime):
    runtime, token = relic_event_runtime
    setup(runtime, token, events.SOURCES[0][0])
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError, match="其他节点"):
        with runtime.database.transaction() as session:
            prepare(Context(session, runtime.data, 1), {Point(1, 0): events.SOURCES[0][0]})
    assert rows(runtime.database.path) == saved
    table = copy.deepcopy(runtime.data.table("roguelike_topic_table"))
    table["details"]["rogue_1"]["choices"]["choice_4_1"]["displayData"] = None
    fake = SimpleNamespace(rogue_scenes=runtime.data.rogue_scenes,
        rogue_battle_attributes=runtime.data.rogue_battle_attributes, table=lambda _: table)
    with pytest.raises(ValueError, match="ITEM"):
        events.programs(fake)


def test_ending_count_combines_only_earned_scene_and_shop_relics():
    program, choice = next(iter(events.RELICS))
    scene = SimpleNamespace(program_id=program, state="FINISHED", steps=[{"choice": choice, "at": 100}])
    plain = SimpleNamespace(program_id="rogue1-fixed-gold", state="FINISHED", steps=[{"choice": "choice_gold_1", "at": 100}])
    prepared = SimpleNamespace(program_id=program, state="PREPARED", steps=[])
    shop = SimpleNamespace(state="FINISHED", purchases=[{"index": "relic", "at": 100, "ticket": None},
                                                       {"index": "ticket", "at": 100, "ticket": 3}])
    assert collected_relics((shop,), (scene, plain, prepared)) == 2
    assert collected_relics((shop,)) == 1


def test_scene_relic_is_retained_and_counted_by_ordinary_defeat(relic_event_runtime):
    from test_native_replay import journal as make_journal
    from test_rogue_defeat import defeat
    from test_roguelike_battle_start import begin, body

    runtime, token = relic_event_runtime
    program, choice = next(iter(events.RELICS))
    item = events.RELICS[program, choice]
    setup(runtime, token, program, battle=True)
    journal = make_journal()
    journal["journal"]["metadata"]["stageId"] = "ordinary"
    member = journal["journal"]["squad"][0]
    member["skillIndex"], member["skillId"] = 1, "s1"
    journal["journal"]["squad"].append(member | {"charInstId": 2, "skillIndex": -1, "skillId": None})
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "selectChoice", {"choice": choice}, "gain").status_code == 200
        assert post(client, token, "finishEvent", {}, "leave").status_code == 200
        started = begin(client, token, body() | {"to": {"x": 1, "y": 0}})
        assert started.status_code == 200, started.text
        assert defeat(client, token, started.json()["battleId"], journal).status_code == 200
        ending = current(runtime, token)["player"]["pending"][0]
        assert ending["content"]["result"]["record"]["relicList"] == [item]
        reply = post(client, token, "gameSettle", {}, "settle")
        assert reply.status_code == 200, reply.text
        assert reply.json()["game"]["score"]["detail"][5][0] == 1
