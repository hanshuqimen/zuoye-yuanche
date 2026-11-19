"""Gold-layer effects with explicit QA stock; no native combat claim."""

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from types import MappingProxyType, SimpleNamespace

import pytest
import test_rogue_cost_relics as costs
import test_rogue_training as training_fixture
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_gold_relics import add_gold
from test_rogue_training import move, setup
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_banks
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_bank_ledger import compile_terms
from terralocal.server.domain.rogue_collection import project
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_relics import Replay
from terralocal.server.domain.rogue_shops import prepare
from terralocal.server.gamedata import rogue_resource_relics as resource
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

AMOUNTS = {"rogue_1_relic_q26": 3, "rogue_1_relic_q27": 5, "rogue_1_relic_q28": 7}
Q26, Q27, Q28 = AMOUNTS
R11 = "rogue_1_relic_r11"


def add_resource(tables, monkeypatch):
    d = tables["roguelike_topic_table"]["details"]["rogue_1"]
    target = "test_gold"
    d.setdefault("gameConst", {})["goldItemId"] = target
    d["items"].setdefault(target, {"id": target, "type": "GOLD"})
    sources = {}
    for number, (key, amount) in enumerate(AMOUNTS.items()):
        item = {"id": key, "type": "RELIC", "unlockCondDesc": "QA source " + str(number)}
        effect = {"id": key, "buffs": [{"key": "layer_char_attribute_add", "blackboard": [
            {"key": "attack_speed", "value": float(amount), "valueStr": None},
            {"key": "stack_by_res", "value": 0.0, "valueStr": target},
            {"key": "stack_by_res_cnt", "value": 5.0, "valueStr": None}]}]}
        conditions = {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []}
        archive = {"relicId": key, "enrollId": None, "isSpRelic": False,
                   "orderId": "QA-resource" + str(number), "relicGroupId": 4, "relicSortId": number}
        d["items"][key], d["relics"][key], d["relicParams"][key] = item, effect, conditions
        d["archiveComp"]["relic"]["relic"][key] = archive
        sources[key] = amount, fingerprint({"item": item, "effect": effect, "conditions": conditions,
                                           "archive": archive, "gold": d["items"][target]})
    monkeypatch.setattr(resource, "SOURCES", MappingProxyType(sources))
    return tables


@pytest.fixture
def resource_tables(cost_tables, monkeypatch):
    original = costs.add_costs
    monkeypatch.setattr(costs, "add_costs", lambda tables: add_resource(add_gold(original(tables), monkeypatch), monkeypatch))
    original_map = training_fixture.map_tables
    def maps():
        tables = original_map()
        tables["roguelike_topic_table"]["details"]["rogue_1"]["gameConst"].update(
            bankMaxGold=999, bankRewardCountType="HIGHEST_RECORD")
        return tables
    monkeypatch.setattr(training_fixture, "map_tables", maps)


@pytest.fixture
def resource_runtime(resource_tables, cost_runtime):
    return cost_runtime


def rules(monkeypatch):
    tables = add_resource(costs.add_costs(costs.temporary_tables()), monkeypatch)
    d = tables["roguelike_topic_table"]["details"]["rogue_1"]
    data = SimpleNamespace(table=lambda name: tables[name], manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda topic: None),
        rogue_relic_archive=SimpleNamespace(entries={key: SimpleNamespace(special=False, enrollment=None)
                                                   for key in AMOUNTS}))
    return data, d


@pytest.mark.parametrize("key,amount", tuple(AMOUNTS.items()))
def test_all_three_exact_effects_and_native_division_boundaries(monkeypatch, key, amount):
    data, _ = rules(monkeypatch)
    catalog = resource.FirstThemeResourceRelics(data)
    effect = catalog.require(key)
    assert effect.per_layer == amount
    assert [effect.layers(n) for n in (0, 4, 5, 9, 10, 24, 25)] == [0, 0, 1, 1, 2, 4, 5]
    assert effect.layers(2**31 - 1) == 429496729
    with pytest.raises(TypeError):
        catalog.entries[key] = effect
    with pytest.raises(FrozenInstanceError):
        effect.per_layer = 100


@pytest.mark.parametrize("value", [True, -1, 1.0, "5", None, 2**31])
def test_invalid_gold_cannot_authorize_layers(monkeypatch, value):
    data, _ = rules(monkeypatch)
    with pytest.raises(ValueError):
        resource.FirstThemeResourceRelics(data).require(Q28).layers(value)


@pytest.mark.parametrize("field", ["step", "resource", "bonus", "condition", "archive", "selector", "extra_effect"])
def test_changed_complete_definition_never_reuses_previous_capability(monkeypatch, field):
    data, d = rules(monkeypatch)
    board = d["relics"][Q28]["buffs"][0]["blackboard"]
    if field == "step":
        board[2]["value"] = 0.0
    elif field == "resource":
        board[1]["valueStr"] = "other"
    elif field == "bonus":
        board[0]["value"] = 8.0
    elif field == "condition":
        d["items"][Q28]["unlockCondDesc"] = "other"
    elif field == "archive":
        d["archiveComp"]["relic"]["relic"][Q28]["isSpRelic"] = True
    elif field == "selector":
        d["relicParams"][Q28]["checkCharBoxTypes"] = ["different"]
    else:
        d["relics"][Q28]["buffs"].append({"key": "unknown", "blackboard": []})
    with pytest.raises(ValueError):
        resource.FirstThemeResourceRelics(data)


def test_reviewed_bonus_is_checked_independently_of_digest(monkeypatch):
    data, _ = rules(monkeypatch)
    sources = dict(resource.SOURCES)
    sources[Q28] = (5, sources[Q28][1])
    monkeypatch.setattr(resource, "SOURCES", MappingProxyType(sources))
    with pytest.raises(ValueError):
        resource.FirstThemeResourceRelics(data)


def configure(runtime, token, key=Q28, *, bank=False):
    setup(runtime, token, ("SHOP", "SHOP"))
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        q = compile_shop(runtime.data, "qa-gold-layer", (
            Offer("resource", key, 1, relic_layer=0), Offer("gold", R11, 0, relic_layer=0)),
            evidence="Authored QA only; no official unlock, natural supply or merchant-price claim")
        assert q.gold_gains == {"gold": 10}
        prepare(ctx, {Point(0, 0): q})
        if bank:
            shop = session.query(m.RogueShopVisit).filter_by(node_x=0).one()
            terms = compile_terms(runtime.data, q, mode="NORMAL", grade=0, bank_open=True,
                allow_deposit=True, allow_withdraw=True, withdrawal_costs=(1, 2, 4, 8, 16, 32),
                evidence="Forced QA bank authorization; no earned entitlement or natural opening")
            rogue_banks.prepare(ctx, shop.id, terms, outcomes=(False,) * 5, has_boss=True)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "resource-enter").status_code == 200
    return q


@pytest.mark.parametrize("key,amount", tuple(AMOUNTS.items()))
def test_acquisition_delta_gold_changes_native_inputs_remain_live_after_restart(resource_runtime, key, amount):
    runtime, token = resource_runtime
    configure(runtime, token, key, bank=True)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        bought = buy(client, token, "resource", "resource-buy")
        assert bought.status_code == 200, bought.text
        after = runtime.sync(token)["user"]
        assert apply(before, bought.json()["playerDataDelta"]) == after
        assert after["troop"] == before["troop"]
        assert current(runtime, token)["player"]["property"]["gold"] == 5
        relic = copy.deepcopy(current(runtime, token)["inventory"]["relic"]["1"])
        assert relic["id"] == key and relic["layer"] == 0 and relic["count"] == 1
        assert after["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][key]["state"] == 2
        assert buy(client, token, "resource", "resource-retry").status_code == 200
        assert runtime.sync(token)["user"] == after
        assert buy(client, token, "gold", "resource-gold").status_code == 200
        assert post(client, token, "bankPut", {}, "resource-put").status_code == 200
        changed = current(runtime, token)
        assert changed["player"]["property"]["gold"] == 14
        assert changed["inventory"]["relic"]["1"] == relic  # Never persist a derived layer2 into base input.
        effect = runtime.data.rogue_resource_relics.require(key)
        assert effect.layers(14) * amount == 2 * amount
        assert post(client, token, "bankWithdraw", {}, "resource-draw").status_code == 200
        assert current(runtime, token)["player"]["property"]["gold"] == 15
        assert current(runtime, token)["inventory"]["relic"]["1"] == relic
    expected = runtime.sync(token)["user"]
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected
    finally:
        reopened.database.close()
    saved = rows(runtime.database.path)
    backups = BackupService(runtime)
    backups.restore(backups.create()["name"])
    assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == expected


def test_concurrent_acquisition_and_failure_after_grant_preserve_transactions(resource_runtime, monkeypatch):
    runtime, token = resource_runtime
    configure(runtime, token)
    original = Replay.finish
    def fail(self, values):
        if any(g.item_id == Q28 for g in self.grants):
            raise ValueError("Injected layer acquisition projection failure")
        return original(self, values)
    monkeypatch.setattr(Replay, "finish", fail)
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "resource", "resource-rollback").status_code == 503
    assert rows(runtime.database.path) == before
    monkeypatch.setattr(Replay, "finish", original)
    other = Runtime(runtime.settings)
    try:
        def pay(pair):
            target, key = pair
            with TestClient(create_game_app(target)) as client:
                return buy(client, token, "resource", key).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(pay, ((runtime, "resource-one"), (other, "resource-two")))) == [200, 200]
        assert current(runtime, token)["player"]["property"]["gold"] == 5
        assert len(current(runtime, token)["inventory"]["relic"]) == 2
    finally:
        other.database.close()


def test_derived_layer_written_into_base_inventory_is_rejected_readonly(resource_runtime):
    runtime, token = resource_runtime
    configure(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "resource", "resource-base").status_code == 200
    with runtime.database.transaction() as session:
        session.query(m.RogueRunRelic).filter_by(item_id=Q28).one().layer = 1
    before = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == before
    with pytest.raises(ValueError):
        reopened = Runtime(runtime.settings)
        reopened.database.close()
    assert rows(runtime.database.path) == before


def test_forged_discovery_is_not_an_unlock_or_acquisition_source():
    state = {"collect": {"relic": {Q28: {"state": 2, "progress": []}}}}
    before = copy.deepcopy(state)
    with pytest.raises(DomainError):
        project(state, frozenset())
    assert state == before
