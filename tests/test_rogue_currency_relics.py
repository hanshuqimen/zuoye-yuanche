"""Owned scalar-resource fixtures; transaction/replay checks, no native claim."""

import copy
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType, SimpleNamespace

import pytest
import test_rogue_cost_relics as costs
import test_rogue_training as training_fixture
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy, configure
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.rogue_relics import MAX_RELICS, Replay
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_currency_relics import (
    CONSTANTS,
    SOURCES,
    CurrencyGain,
    FirstThemeCurrencyRelics,
)
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

EXPECTED = {"m17": (11, 3, 0), "q01": (0, 2, 1), "q03": (0, 4, 1), "q04": (0, 4, 1),
            "q06": (0, 6, 2), "r06": (0, 4, 0), "r07": (0, 4, 0), "r08": (0, 4, 0),
            "r09": (0, 6, 0), "r10": (0, 8, 0)}
M17, Q06 = "rogue_1_relic_m17", "rogue_1_relic_q06"


def add_currency(tables, *, constants=CONSTANTS):
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    detail.setdefault("gameConst", {}).update(constants)
    targets = tuple(constants.values())
    for key, kind in zip(targets, ("GOLD", "POPULATION", "SQUAD_CAPACITY")):
        detail["items"].setdefault(key, {"id": key, "type": kind})
    for index, (suffix, values) in enumerate(EXPECTED.items()):
        key = "rogue_1_relic_" + suffix
        detail["items"][key] = {"id": key, "type": "RELIC", "unlockCondDesc": None}
        detail["relics"][key] = {"id": key, "buffs": [
            {"key": "immediate_reward", "blackboard": [
                {"key": "id", "value": 0.0, "valueStr": target},
                {"key": "count", "value": float(amount), "valueStr": None}]}
            for target, amount in zip(targets, values) if amount]}
        detail["relicParams"][key] = {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []}
        detail["archiveComp"]["relic"]["relic"][key] = {"relicId": key, "enrollId": None,
            "isSpRelic": False, "relicGroupId": 1, "relicSortId": 100 + index, "orderId": "QA-CURRENCY-" + suffix}
    return tables


@pytest.fixture
def cost_tables(monkeypatch):
    from terralocal.server.gamedata import rogue_currency_relics

    # The existing training driver authors test_gold after its map merge.
    # Bind an explicit synthetic compatibility profile; production constants
    # and source fingerprints are checked separately by rules()/real data.
    constants = dict(CONSTANTS) | {"goldItemId": "test_gold"}
    monkeypatch.setattr(rogue_currency_relics, "CONSTANTS", MappingProxyType(constants))
    original = costs.add_costs
    def add(tables):
        value = add_currency(original(tables), constants=constants)
        detail = value["roguelike_topic_table"]["details"]["rogue_1"]
        sources = {}
        for suffix, amounts in EXPECTED.items():
            key = "rogue_1_relic_" + suffix
            targets = {buff["blackboard"][0]["valueStr"] for buff in detail["relics"][key]["buffs"]}
            source = {"effect": detail["relics"][key], "conditions": detail["relicParams"][key], "item_type": "RELIC",
                      "constants": constants, "targets": {target: {field: detail["items"][target][field]
                                                                  for field in ("id", "type")} for target in targets}}
            sources[key] = CurrencyGain(*amounts), fingerprint(source)
        monkeypatch.setattr(rogue_currency_relics, "SOURCES", MappingProxyType(sources))
        return value
    monkeypatch.setattr(costs, "add_costs", add)
    monkeypatch.setattr(training_fixture, "recruit_tables", lambda: costs.add_costs(costs.temporary_tables()))
    original_start = start_fixture.recruit_tables
    monkeypatch.setattr(start_fixture, "recruit_tables", lambda: costs.add_costs(original_start()))
    original_map = training_fixture.map_tables
    def maps():
        value = original_map()
        value["roguelike_topic_table"]["details"]["rogue_1"]["gameConst"].update(constants)
        return value
    monkeypatch.setattr(training_fixture, "map_tables", maps)


def rules(tables=None, *, special=False, enrollment=None):
    if tables is None:
        tables = add_currency(costs.add_costs(costs.temporary_tables()))
    refs = {key: SimpleNamespace(special=special, enrollment=enrollment) for key in SOURCES}
    data = SimpleNamespace(table=lambda name: tables[name], manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda key: None),
        rogue_relic_archive=SimpleNamespace(entries=refs, fingerprint="b" * 64))
    return FirstThemeCurrencyRelics(data)


def test_all_complete_vectors_and_capability_budget():
    catalog = rules()
    assert {key: (v.gold, v.hope, v.capacity) for key, v in catalog.entries.items()} == {
        "rogue_1_relic_" + key: value for key, value in EXPECTED.items()}
    assert MAX_RELICS == 122
    with pytest.raises(TypeError):
        catalog.entries[M17] = CurrencyGain(0, 0, 0)


@pytest.mark.parametrize("damage", ("count", "boolean", "extra", "constant", "target_type", "condition", "missing", "mixed"))
def test_changed_complete_definition_is_rejected(damage):
    tables = add_currency(costs.add_costs(costs.temporary_tables()))
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    buff = detail["relics"][M17]["buffs"][0]
    if damage == "count":
        buff["blackboard"][1]["value"] = 12.0
    elif damage == "boolean":
        buff["blackboard"][0]["value"] = False
    elif damage == "extra":
        buff["blackboard"].append({"key": "unreviewed", "value": 0.0, "valueStr": None})
    elif damage == "constant":
        detail["gameConst"]["populationItemId"] = "unknown"
    elif damage == "target_type":
        detail["items"]["rogue_1_population"]["type"] = "HP"
    elif damage == "condition":
        detail["relicParams"][M17]["checkCharBoxTypes"] = ["unreviewed"]
    elif damage == "missing":
        del detail["relicParams"][M17]
    else:
        detail["relics"][M17]["buffs"].append({"key": "level_char_limit_add", "blackboard": []})
    with pytest.raises(ValueError):
        rules(tables)


@pytest.mark.parametrize("special,enrollment", ((True, None), (False, "unreviewed")))
def test_special_or_new_enrollment_is_not_silently_admitted(special, enrollment):
    with pytest.raises(ValueError):
        rules(special=special, enrollment=enrollment)


def test_compiled_vector_must_match_all_actual_reward_components(monkeypatch):
    from terralocal.server.gamedata import rogue_currency_relics

    damaged = dict(SOURCES)
    damaged[M17] = CurrencyGain(11, 0, 0), damaged[M17][1]
    monkeypatch.setattr(rogue_currency_relics, "SOURCES", damaged)
    with pytest.raises(ValueError):
        rules()


def test_old_quotes_do_not_bind_new_catalog_but_new_quotes_do(cost_runtime):
    runtime, _ = cost_runtime
    old = (Offer("old", costs.R25, 1, relic_layer=0),)
    new = (Offer("mixed", M17, 1, relic_layer=0),)
    first = compile_shop(runtime.data, "old-owned", old, evidence="Owned old contract")
    second = compile_shop(runtime.data, "new-owned", new, evidence="Owned new contract")
    assert dict(second.gold_gains) == {"mixed": 11}
    runtime.data.rogue_currency_relics.fingerprint = "changed"
    assert compile_shop(runtime.data, "old-owned", old, evidence="Owned old contract").digest == first.digest
    assert compile_shop(runtime.data, "new-owned", new, evidence="Owned new contract").digest != second.digest


@pytest.mark.parametrize("suffix,amounts", tuple(EXPECTED.items()))
def test_purchase_all_components_delta_and_retry_once(cost_runtime, suffix, amounts):
    runtime, token = cost_runtime
    key = "rogue_1_relic_" + suffix
    configure(runtime, token, key)
    before = runtime.sync(token)["user"]
    original = before["rlv2"]["current"]["player"]["property"]
    with TestClient(create_game_app(runtime)) as client:
        response = buy(client, token, "relic", "currency-first")
        assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        prop = after["rlv2"]["current"]["player"]["property"]
        assert prop["gold"] == original["gold"] - 1 + amounts[0]
        assert prop["population"] == {**original["population"], "max": original["population"]["max"] + amounts[1]}
        assert prop["capacity"] == original["capacity"] + amounts[2]
        assert after["troop"] == before["troop"]
        assert after["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][key]["state"] == 2
        saved = rows(runtime.database.path)
        assert buy(client, token, "relic", "currency-first").json() == response.json()
        assert rows(runtime.database.path) == saved
        assert buy(client, token, "relic", "currency-new-sequence").status_code == 200
        assert runtime.sync(token)["user"] == after


def test_concurrent_purchase_has_one_payment_and_one_mixed_grant(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, M17)
    before = current(runtime, token)["player"]["property"]
    other = Runtime(runtime.settings)
    try:
        def pay(pair):
            instance, key = pair
            with TestClient(create_game_app(instance)) as client:
                return buy(client, token, "relic", key).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(pay, ((runtime, "currency-a"), (other, "currency-b")))) == [200, 200]
        after = current(runtime, token)["player"]["property"]
        assert after["gold"] == before["gold"] + 10
        assert after["population"]["max"] == before["population"]["max"] + 3
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueRunRelic).filter_by(item_id=M17).count() == 1
    finally:
        other.database.close()


def test_post_grant_failure_rolls_back_every_table(cost_runtime, monkeypatch):
    runtime, token = cost_runtime
    configure(runtime, token, M17)
    original = Replay.finish
    def fail(self, values):
        if any(grant.item_id == M17 for grant in self.grants):
            raise ValueError("Injected mixed-resource projection failure")
        return original(self, values)
    monkeypatch.setattr(Replay, "finish", fail)
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "currency-rollback").status_code == 503
    assert rows(runtime.database.path) == saved


def test_later_resource_overflow_returns409_without_partial_payment(cost_runtime, monkeypatch):
    from terralocal.server.domain import rogue_relics

    runtime, token = cost_runtime
    configure(runtime, token, Q06)
    increase = rogue_relics.increase
    def fail_capacity(value, amount):
        if amount == 2:
            raise ValueError("Injected capacity limit after hope calculation")
        return increase(value, amount)
    monkeypatch.setattr(rogue_relics, "increase", fail_capacity)
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        response = buy(client, token, "relic", "currency-overflow")
        assert response.status_code == 409 and response.json()["error"]["code"] == "ROGUE_SHOP_RESOURCE_LIMIT"
    assert rows(runtime.database.path) == saved


def test_explicit_reward_mix_survives_restart_and_real_restore(cost_runtime):
    from test_rogue_battle_loot import configured, finish_new

    runtime, token = cost_runtime
    configured(runtime, token, groups=((Q06,), (M17,)))
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
        before = runtime.sync(token)["user"]
        original = copy.deepcopy(before["rlv2"]["current"]["player"]["property"])
        for index in (2, 3):
            response = post(client, token, "chooseBattleReward", {"index": index, "sub": 0}, "currency-loot-" + str(index))
            assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        prop = after["rlv2"]["current"]["player"]["property"]
        assert prop["gold"] == original["gold"] + 11
        assert prop["population"]["max"] == original["population"]["max"] + 9
        assert prop["capacity"] == original["capacity"] + 2
        assert post(client, token, "chooseBattleReward", {"index": 3, "sub": 0}, "currency-loot-retry").status_code == 200
        assert runtime.sync(token)["user"] == after
        assert post(client, token, "finishBattleReward", {}, "currency-loot-close").status_code == 200
    expected = runtime.sync(token)["user"]
    other = Runtime(runtime.settings)
    try:
        assert other.sync(token)["user"] == expected
        service = BackupService(other)
        saved = rows(other.database.path)
        service.restore(service.create()["name"])
        assert rows(other.database.path) == saved and other.sync(token)["user"] == expected
    finally:
        other.database.close()
