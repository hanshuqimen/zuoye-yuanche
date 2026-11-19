"""History peaks, not final resources or saved claims; no native play."""

import copy
from types import MappingProxyType, SimpleNamespace

import pytest
import test_rogue_cost_relics as costs
from fastapi.testclient import TestClient
from test_rogue_capacity_relics import AMOUNTS
from test_rogue_capacity_relics import capacity_runtime as capacity_runtime
from test_rogue_capacity_relics import capacity_tables as capacity_tables
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_roster_unlocks import add_conditions, table
from test_rogue_training import choice, move, setup
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_events import Resources, replay
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_relics import Replay
from terralocal.server.gamedata import rogue_capacity_relics as effects
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_capacity_unlocks import (
    DESCRIPTION,
    ITEM,
    FirstThemeCapacityUnlocks,
    RunCapacity,
)
from terralocal.server.gamedata.rogue_collection import FirstThemeRelicArchive
from terralocal.server.gamedata.rogue_events import Branch, Delta, EventProgram, Frame, SceneChoice
from terralocal.server.gamedata.rogue_roster_unlocks import FirstThemeRosterUnlocks
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def rule_data():
    source = table()
    d = source["details"]["rogue_1"]
    d["items"][ITEM] = {"id": ITEM, "type": "RELIC", "unlockCondDesc": DESCRIPTION}
    d["relics"][ITEM] = {"id": ITEM, "buffs": []}
    d["archiveComp"]["relic"]["relic"][ITEM] = {"relicId": ITEM, "enrollId": None,
        "isSpRelic": False, "orderId": "QA", "relicGroupId": 1, "relicSortId": 1}
    d["items"][effects.TARGET] = {"id": effects.TARGET, "type": "SQUAD_CAPACITY"}
    d.setdefault("gameConst", {})["squadCapacityItemId"] = effects.TARGET
    data = SimpleNamespace(table=lambda name: source, manifest={"hash": "a" * 64},
                           rogue_topics=SimpleNamespace(topic=lambda topic: SimpleNamespace(start=100)))
    data.rogue_relic_archive = FirstThemeRelicArchive(data)
    data.rogue_roster_unlocks = FirstThemeRosterUnlocks(data)
    return data, d


def run(peak, **changes):
    return RunCapacity(**({"mode": "NORMAL", "grade": 0, "started_at": 200, "peak": peak} | changes))


@pytest.mark.parametrize("peak,current,state", [(0, 0, 0), (6, 6, 0), (12, 12, 0), (13, 13, 1), (16, 13, 1)])
def test_exact_threshold_and_saturated_two_integer_progress(peak, current, state):
    value = FirstThemeCapacityUnlocks(rule_data()[0]).evaluate((run(peak),))[ITEM]
    assert value.wire() == {"state": state, "progress": [current, 13]}


def test_peak_is_not_a_sum_and_easy_or_preopening_runs_do_not_contribute():
    rules = FirstThemeCapacityUnlocks(rule_data()[0])
    assert rules.evaluate((run(7), run(6), run(20, mode="EASY"), run(20, started_at=99)))[ITEM].current == 7
    assert rules.evaluate(())[ITEM].current == 0


@pytest.mark.parametrize("bad", [run(True), run(-1), run(2**31), run(13, grade=True),
    run(13, mode="UNKNOWN"), run(13, started_at=True), {"peak": 13}])
def test_invalid_or_client_shaped_history_is_rejected(bad):
    with pytest.raises(ValueError):
        FirstThemeCapacityUnlocks(rule_data()[0]).evaluate((bad,))


@pytest.mark.parametrize("change", ["description", "special", "resource", "binding"])
def test_changed_condition_identity_or_target_binding_is_not_reused(change):
    data, d = rule_data()
    if change == "description":
        d["items"][ITEM]["unlockCondDesc"] = "QA changed"
    elif change == "special":
        d["archiveComp"]["relic"]["relic"][ITEM]["isSpRelic"] = True
    elif change == "resource":
        d["items"][effects.TARGET]["type"] = "GOLD"
    else:
        d["gameConst"]["squadCapacityItemId"] = "wrong"
    data.rogue_relic_archive = FirstThemeRelicArchive(data)
    with pytest.raises(ValueError):
        FirstThemeCapacityUnlocks(data)


def transient_program(data_hash="b" * 64):
    # Explicit authored three-choice event, not an official event distribution.
    choices = {"up": SceneChoice("up", "TRADE", "high", "a"),
               "down": SceneChoice("down", "TRADE", "low", "b"),
               "leave": SceneChoice("leave", "LEAVE", None, "c")}
    frames = {"start": Frame("start", (Branch("up", "a", Delta(squad_capacity=7)),)),
              "high": Frame("high", (Branch("down", "b", Delta(squad_capacity=-7)),)),
              "low": Frame("low", (Branch("leave", "c", Delta()),))}
    return EventProgram("qa-capacity", "start", frames, choices, "a" * 64, data_hash, "Authored QA")


def test_scene_peak_survives_a_capacity_reduction_within_the_same_event():
    program = transient_program()
    state = replay(program, Resources(4, 6, 6, 0, 6), ("up", "down", "leave"))
    assert state.resources.squad_capacity == 6 and state.capacity_peak == 13
    history = Replay(SimpleNamespace(rogue_recruit_costs=None), ())
    history.capacity(6)
    history.capacity(state.capacity_peak)
    progress = history.finish({"squad_capacity": 6})
    assert progress.capacity_peak == 13 and dict(progress) == {"squad_capacity": 6}


@pytest.fixture
def goal_tables(capacity_tables, monkeypatch):
    original = costs.add_costs
    def add(tables):
        result = original(tables)
        d = result["roguelike_topic_table"]["details"]["rogue_1"]
        add_conditions(d)
        d["items"][ITEM]["unlockCondDesc"] = DESCRIPTION
        # Rebind the authored capacity effects after adding explicit conditions.
        sources = {key: (amount, fingerprint({
            "item": {f: d["items"][key][f] for f in ("id", "type", "unlockCondDesc")},
            "effect": d["relics"][key], "conditions": d["relicParams"][key],
            "archive": d["archiveComp"]["relic"]["relic"][key], "target": d["items"][effects.TARGET]}))
            for key, amount in AMOUNTS.items()}
        monkeypatch.setattr(effects, "SOURCES", MappingProxyType(sources))
        return result
    monkeypatch.setattr(costs, "add_costs", add)


@pytest.fixture
def goal_runtime(goal_tables, capacity_runtime):
    return capacity_runtime


def progress(runtime, token):
    return runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][ITEM]


def test_live_scene_history_keeps_unlock_after_capacity_falls_back(goal_runtime, monkeypatch):
    from terralocal.server.domain.rogue_visits import prepare

    runtime, token = goal_runtime
    setup(runtime, token, ("INCIDENT",))
    program = transient_program(runtime.data.manifest["hash"])
    # One explicit QA program is installed in this in-memory authored profile;
    # it is not a shipped official encounter or a restart acceptance claim.
    monkeypatch.setitem(runtime.data.__dict__, "rogue_fixed_events", {program.id: program})
    with runtime.database.transaction() as session:
        prepare(Context(session, runtime.data, 1), {Point(0, 0): program.id})
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "transient-enter").status_code == 200
        for name in ("up", "down", "leave"):
            before = runtime.sync(token)["user"]
            reply = choice(client, token, name, "transient-" + name)
            assert reply.status_code == 200, reply.text
            after = runtime.sync(token)["user"]
            assert apply(before, reply.json()["playerDataDelta"]) == after
            assert progress(runtime, token) == {"state": 1, "progress": [13, 13]}
    assert runtime.sync(token)["user"]["rlv2"]["current"]["player"]["property"]["capacity"] == 6
    saved = rows(runtime.database.path)
    assert progress(runtime, token)["state"] == 1 and rows(runtime.database.path) == saved


def test_rest_capacity_threshold_delta_retry_abandon_new_run_and_full_restore(goal_runtime):
    runtime, token = goal_runtime
    setup(runtime, token, ("REST",) * 7,
          rest_programs={i: "rogue1-rest-without-1-v1" for i in range(7)})
    assert progress(runtime, token) == {"state": 0, "progress": [6, 13]}
    with TestClient(create_game_app(runtime)) as client:
        for x in range(7):
            assert move(client, token, x, "cap-move-" + str(x)).status_code == 200
            before = runtime.sync(token)["user"]
            reply = choice(client, token, "choice_rest_4", "cap-gain-" + str(x))
            assert reply.status_code == 200, reply.text
            after = runtime.sync(token)["user"]
            assert apply(before, reply.json()["playerDataDelta"]) == after
            assert progress(runtime, token) == {"state": int(x == 6), "progress": [7 + x, 13]}
            assert choice(client, token, "choice_rest_4", "cap-gain-" + str(x)).status_code == 200
            assert runtime.sync(token)["user"] == after
            assert choice(client, token, "choice_leave", "cap-leave-" + str(x)).status_code == 200
        assert post(client, token, "giveUpGame", {}, "cap-abandon").status_code == 200
        assert post(client, token, "gameSettle", {}, "cap-confirm").status_code == 200
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += runtime.data.rogue_initial.cooldown
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0},
                    "cap-new").status_code == 200
    final = runtime.sync(token)["user"]
    assert final["rlv2"]["current"]["player"]["property"]["capacity"] == 6
    assert progress(runtime, token) == {"state": 1, "progress": [13, 13]}
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()
    saved = rows(runtime.database.path)
    service = BackupService(runtime)
    service.restore(service.create()["name"])
    assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == final


def test_claimed_capacity_or_completed_goal_cannot_bypass_history(goal_runtime):
    runtime, token = goal_runtime
    with runtime.database.transaction() as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        value = copy.deepcopy(outer.state)
        value["collect"]["relic"][ITEM] = {"state": 1, "progress": [13, 13]}
        outer.state = value
    before = rows(runtime.database.path)
    with pytest.raises(DomainError):
        progress(runtime, token)
    assert rows(runtime.database.path) == before
    runtime.database.close()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
