"""Six exact capacity effects and causal acquisition; authored QA supply only."""

from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType, SimpleNamespace

import pytest
import test_rogue_cost_relics as costs
import test_rogue_training as training_fixture
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy, leave
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_training import move, setup
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_relics import Replay
from terralocal.server.domain.rogue_shops import prepare
from terralocal.server.gamedata import rogue_capacity_relics as capacity
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

AMOUNTS = {"rogue_1_relic_a" + str(i): n for i, n in zip(range(35, 41), (1, 1, 1, 2, 2, 3))}
A35, A40 = "rogue_1_relic_a35", "rogue_1_relic_a40"


def add_capacity(tables, monkeypatch):
    d = tables["roguelike_topic_table"]["details"]["rogue_1"]
    d["items"][capacity.TARGET] = {"id": capacity.TARGET, "type": "SQUAD_CAPACITY"}
    d.setdefault("gameConst", {})["squadCapacityItemId"] = capacity.TARGET
    sources = {}
    for number, (key, amount) in enumerate(AMOUNTS.items()):
        item = {"id": key, "type": "RELIC", "unlockCondDesc": None}
        effect = {"id": key, "buffs": [{"key": "immediate_reward", "blackboard": [
            {"key": "id", "value": 0.0, "valueStr": capacity.TARGET},
            {"key": "count", "value": float(amount), "valueStr": None}]}]}
        conditions = {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []}
        archive = {"relicId": key, "enrollId": None, "isSpRelic": False,
                   "orderId": "QA" + str(number), "relicGroupId": 1, "relicSortId": number}
        d["items"][key], d["relics"][key], d["relicParams"][key] = item, effect, conditions
        d["archiveComp"]["relic"]["relic"][key] = archive
        sources[key] = amount, fingerprint({"item": item, "effect": effect, "conditions": conditions,
                                            "archive": archive, "target": d["items"][capacity.TARGET]})
    monkeypatch.setattr(capacity, "SOURCES", MappingProxyType(sources))
    return tables


@pytest.fixture
def capacity_tables(cost_tables, monkeypatch):
    original = costs.add_costs
    monkeypatch.setattr(costs, "add_costs", lambda tables: add_capacity(original(tables), monkeypatch))
    original_map = training_fixture.map_tables
    def maps():
        tables = original_map()
        tables["roguelike_topic_table"]["details"]["rogue_1"]["gameConst"]["squadCapacityItemId"] = capacity.TARGET
        return tables
    monkeypatch.setattr(training_fixture, "map_tables", maps)


@pytest.fixture
def capacity_runtime(capacity_tables, cost_runtime):
    return cost_runtime


def rules(monkeypatch):
    tables = add_capacity(costs.add_costs(costs.temporary_tables()), monkeypatch)
    d = tables["roguelike_topic_table"]["details"]["rogue_1"]
    data = SimpleNamespace(table=lambda name: tables[name], manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda topic: None),
        rogue_relic_archive=SimpleNamespace(entries={key: SimpleNamespace(special=False, enrollment=None)
                                                   for key in AMOUNTS}))
    return capacity.FirstThemeCapacityRelics(data), data, d


@pytest.mark.parametrize("key,amount", tuple(AMOUNTS.items()))
def test_entire_matched_effect_family_adds_exact_resource_once_per_application(monkeypatch, key, amount):
    value, _, _ = rules(monkeypatch)
    assert value.require(key) == amount and value.increase(key, 6) == 6 + amount
    assert value.increase(key, 2**31 - amount - 1) == 2**31 - 1
    with pytest.raises(ValueError):
        value.increase(key, 2**31 - amount)
    with pytest.raises(TypeError):
        value.entries[key] = 999


@pytest.mark.parametrize("value", [True, -1, 1.0, "1", None, 2**31])
def test_invalid_resource_never_becomes_a_reward(monkeypatch, value):
    effect, _, _ = rules(monkeypatch)
    with pytest.raises(ValueError):
        effect.increase(A35, value)


def test_capacity_gain_is_used_by_battle_formation_admission(monkeypatch):
    from terralocal.server.domain.rogue_battle import formation

    effect, _, _ = rules(monkeypatch)
    troop = {str(i): {"skills": []} for i in range(7)}
    slots = [{"charInstId": i, "skillIndex": -1} for i in range(7)]
    with pytest.raises(DomainError) as error:
        formation(SimpleNamespace(squad_capacity=6), troop, slots)
    assert error.value.code == "ROGUE_SQUAD_CAPACITY"
    admitted = formation(SimpleNamespace(squad_capacity=effect.increase(A35, 6)), troop, slots)
    assert [c["charInstId"] for c in admitted] == list(range(7))


@pytest.mark.parametrize("part", ["effect", "conditions", "archive", "target", "binding"])
def test_full_definition_changes_are_not_reduced_to_a_matching_numeric_buff(monkeypatch, part):
    _, data, d = rules(monkeypatch)
    if part == "effect":
        d["relics"][A35]["buffs"].append({"key": "unknown", "blackboard": []})
    elif part == "conditions":
        d["relicParams"][A35]["checkCharBoxTypes"] = ["UNKNOWN"]
    elif part == "archive":
        d["archiveComp"]["relic"]["relic"][A35]["isSpRelic"] = True
    elif part == "target":
        d["items"][capacity.TARGET]["type"] = "GOLD"
    else:
        d["gameConst"]["squadCapacityItemId"] = "other"
    with pytest.raises(ValueError):
        capacity.FirstThemeCapacityRelics(data)


def configure(runtime, token, *, two=False):
    setup(runtime, token, ("SHOP", "SHOP") if two else ("SHOP",))
    with runtime.database.transaction() as session:
        first = compile_shop(runtime.data, "qa-capacity", (Offer("relic", A35, 1, relic_layer=0),
            Offer("ticket", "ticket_pioneer", 0)), evidence="Authored explicit capacity QA; not official prices or pool")
        stock = {Point(0, 0): first}
        if two:
            later = compile_shop(runtime.data, "qa-capacity-later", (Offer("relic", A40, 1, relic_layer=0),),
                evidence="Authored second distinct capacity effect; not natural stock")
            stock[Point(1, 0)] = later
        prepare(Context(session, runtime.data, 1), stock)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "capacity-enter").status_code == 200


def property_of(runtime, token):
    return current(runtime, token)["player"]["property"]


def test_atomic_delta_retry_distinct_effects_ticket_barrier_restart_and_backup(capacity_runtime):
    runtime, token = capacity_runtime
    configure(runtime, token, two=True)
    original = runtime.sync(token)["user"]
    before = property_of(runtime, token).copy()
    with TestClient(create_game_app(runtime)) as client:
        reply = buy(client, token, "relic", "capacity-buy")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(original, reply.json()["playerDataDelta"]) == after
        assert after["troop"] == original["troop"]
        assert property_of(runtime, token)["capacity"] == before["capacity"] + 1
        assert property_of(runtime, token)["gold"] == before["gold"] - 1
        assert after["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][A35]["state"] == 2
        assert buy(client, token, "relic", "capacity-retry").status_code == 200
        assert runtime.sync(token)["user"] == after
        assert buy(client, token, "ticket", "capacity-ticket").status_code == 200
        assert leave(client, token, "capacity-pending").status_code == 409
        assert post(client, token, "closeRecruitTicket", {"id": "3"}, "capacity-close").status_code == 200
        assert leave(client, token, "capacity-leave").status_code == 200
        assert move(client, token, 1, "capacity-next").status_code == 200
        assert buy(client, token, "relic", "capacity-later").status_code == 200
        assert property_of(runtime, token)["capacity"] == before["capacity"] + 4
    expected = runtime.sync(token)["user"]
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected
    finally:
        reopened.database.close()
    saved = rows(runtime.database.path)
    backups = BackupService(runtime)
    backup = backups.create()
    backups.restore(backup["name"])
    assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == expected


def test_concurrent_requests_in_two_runtimes_apply_capacity_and_payment_once(capacity_runtime):
    runtime, token = capacity_runtime
    configure(runtime, token)
    before = property_of(runtime, token).copy()
    other = Runtime(runtime.settings)
    try:
        def pay(pair):
            r, seq = pair
            with TestClient(create_game_app(r)) as client:
                return buy(client, token, "relic", seq).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(pay, ((runtime, "capacity-first"), (other, "capacity-second")))) == [200, 200]
        assert property_of(runtime, token)["capacity"] == before["capacity"] + 1
        assert property_of(runtime, token)["gold"] == before["gold"] - 1
    finally:
        other.database.close()


def test_projection_failure_rolls_back_resource_inventory_payment_stock_and_receipt(capacity_runtime, monkeypatch):
    runtime, token = capacity_runtime
    configure(runtime, token)
    original = Replay.finish
    def fail(self, values):
        if any(g.item_id == A35 for g in self.grants):
            raise ValueError("Injected post-grant failure")
        return original(self, values)
    monkeypatch.setattr(Replay, "finish", fail)
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "capacity-rollback").status_code == 503
    assert rows(runtime.database.path) == before


def test_resource_without_its_purchase_history_is_rejected_read_only(capacity_runtime):
    runtime, token = capacity_runtime
    configure(runtime, token)
    with runtime.database.transaction() as session:
        session.query(m.RogueTopicRun).filter_by(account_id=1, ended_at=None).one().squad_capacity += 1
    before = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == before


def test_abandon_preserves_discovery_but_new_run_has_its_base_capacity(capacity_runtime):
    runtime, token = capacity_runtime
    configure(runtime, token)
    base = property_of(runtime, token)["capacity"]
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "capacity-owned").status_code == 200
        assert post(client, token, "giveUpGame", {}, "capacity-abandon").status_code == 200
        assert post(client, token, "gameSettle", {}, "capacity-confirm").status_code == 200
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += runtime.data.rogue_initial.cooldown
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0},
                    "capacity-new").status_code == 200
    state = runtime.sync(token)["user"]["rlv2"]
    assert state["current"]["player"]["property"]["capacity"] == base
    assert state["current"]["inventory"]["relic"] == {}
    assert state["outer"]["rogue_1"]["collect"]["relic"][A35]["state"] == 2
