"""Complete life effects, owned transaction failures and historical replay."""

import copy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

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
from terralocal.server.gamedata.rogue_life_relics import CONSTANTS, SOURCES, FirstThemeLifeRelics, LifeGain
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

EXPECTED = {"r01": (2, 1), "r02": (6, 0), "r03": (6, 0), "r04": (8, 0), "r05": (10, 0)}
R01, R05 = "rogue_1_relic_r01", "rogue_1_relic_r05"


def add_life(tables):
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    detail.setdefault("gameConst", {}).update(CONSTANTS)
    targets = (CONSTANTS["hpItemId"], CONSTANTS["populationItemId"])
    for target, kind in zip(targets, ("HP", "POPULATION"), strict=True):
        detail["items"].setdefault(target, {"id": target, "type": kind})
    for index, (suffix, values) in enumerate(EXPECTED.items()):
        key = "rogue_1_relic_" + suffix
        detail["items"][key] = {"id": key, "type": "RELIC", "unlockCondDesc": None}
        detail["relics"][key] = {"id": key, "buffs": [
            {"key": "immediate_reward", "blackboard": [
                {"key": "id", "value": 0.0, "valueStr": target},
                {"key": "count", "value": float(amount), "valueStr": None}]}
            for target, amount in zip(targets, values, strict=True) if amount]}
        detail["relicParams"][key] = {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []}
        detail["archiveComp"]["relic"]["relic"][key] = {"relicId": key, "enrollId": None,
            "isSpRelic": False, "relicGroupId": 1, "relicSortId": index + 1, "orderId": f"{index + 1:03}"}
    return tables


@pytest.fixture
def cost_tables(monkeypatch):
    original = costs.add_costs
    monkeypatch.setattr(costs, "add_costs", lambda tables: add_life(original(tables)))
    monkeypatch.setattr(training_fixture, "recruit_tables", lambda: costs.add_costs(costs.temporary_tables()))
    original_start = start_fixture.recruit_tables
    monkeypatch.setattr(start_fixture, "recruit_tables", lambda: costs.add_costs(original_start()))
    original_map = training_fixture.map_tables
    def maps():
        tables = original_map()
        tables["roguelike_topic_table"]["details"]["rogue_1"]["gameConst"].update(CONSTANTS)
        return tables
    monkeypatch.setattr(training_fixture, "map_tables", maps)


def rules(tables=None, *, special=False, enrollment=None):
    if tables is None:
        tables = add_life(costs.add_costs(costs.temporary_tables()))
    refs = {key: SimpleNamespace(special=special, enrollment=enrollment) for key in SOURCES}
    data = SimpleNamespace(table=lambda name: tables[name], manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda key: None),
        rogue_relic_archive=SimpleNamespace(entries=refs, fingerprint="b" * 64))
    return FirstThemeLifeRelics(data)


def test_complete_five_effects_and_current_capability_budget():
    catalog = rules()
    assert {key: (v.hp, v.hope) for key, v in catalog.entries.items()} == {
        "rogue_1_relic_" + key: values for key, values in EXPECTED.items()}
    assert MAX_RELICS == 122
    assert catalog.apply(R05, 29, 0, 8) == (39, 8)
    with pytest.raises(TypeError):
        catalog.entries[R01] = LifeGain(2, 0)


@pytest.mark.parametrize("damage", ("count", "boolean", "extra", "target", "type", "cap", "condition", "missing", "partial"))
def test_changed_complete_definition_and_missing_mixed_component_rejected(damage):
    tables = add_life(costs.add_costs(costs.temporary_tables()))
    d = tables["roguelike_topic_table"]["details"]["rogue_1"]
    buff = d["relics"][R01]["buffs"][0]
    if damage == "count":
        buff["blackboard"][1]["value"] = 3.0
    elif damage == "boolean":
        buff["blackboard"][0]["value"] = False
    elif damage == "extra":
        d["relics"][R01]["buffs"].append({"key": "unreviewed", "blackboard": []})
    elif damage == "target":
        d["items"][CONSTANTS["hpItemId"]]["id"] = "other"
    elif damage == "type":
        d["items"][CONSTANTS["hpItemId"]]["type"] = "MAX_HP"
    elif damage == "cap":
        d["gameConst"]["maxHpItemId"] = "other"
    elif damage == "condition":
        d["relicParams"][R01]["checkCharBoxTypes"] = ["unreviewed"]
    elif damage == "missing":
        del d["relicParams"][R01]
    else:
        d["relics"][R01]["buffs"].pop()
    with pytest.raises(ValueError):
        rules(tables)


@pytest.mark.parametrize("special,enrollment", ((True, None), (False, "unreviewed")))
def test_special_and_unreviewed_enrollment_rejected(special, enrollment):
    with pytest.raises(ValueError):
        rules(special=special, enrollment=enrollment)


def test_server_declared_vector_cannot_drop_hope(monkeypatch):
    from terralocal.server.gamedata import rogue_life_relics

    values = dict(SOURCES)
    values[R01] = LifeGain(2, 0), values[R01][1]
    monkeypatch.setattr(rogue_life_relics, "SOURCES", values)
    with pytest.raises(ValueError):
        rules()


@pytest.mark.parametrize("hp,cap,hope", ((2**31 - 2, 0, 6), (4, 0, 2**31 - 1),
                                         (True, 0, 6), (-1, 0, 6), (4, False, 6), (4, 10, 6)))
def test_integer_bounds_and_other_life_cap_are_not_inferred(hp, cap, hope):
    with pytest.raises(ValueError):
        rules().apply(R01, hp, cap, hope)


def test_legacy_quote_digest_independent_of_life_catalog(cost_runtime):
    runtime, _ = cost_runtime
    old, new = (Offer("old", costs.R25, 1, relic_layer=0),), (Offer("new", R01, 1, relic_layer=0),)
    legacy = compile_shop(runtime.data, "owned-old", old, evidence="Owned legacy quote")
    life = compile_shop(runtime.data, "owned-new", new, evidence="Owned life quote")
    runtime.data.rogue_life_relics.fingerprint = "changed"
    assert compile_shop(runtime.data, "owned-old", old, evidence="Owned legacy quote").digest == legacy.digest
    assert compile_shop(runtime.data, "owned-new", new, evidence="Owned life quote").digest != life.digest


@pytest.mark.parametrize("suffix,amounts", tuple(EXPECTED.items()))
def test_buy_each_life_relic_complete_delta_and_retries(cost_runtime, suffix, amounts):
    runtime, token = cost_runtime
    key = "rogue_1_relic_" + suffix
    configure(runtime, token, key)
    before = runtime.sync(token)["user"]
    prop = before["rlv2"]["current"]["player"]["property"]
    with TestClient(create_game_app(runtime)) as client:
        first = buy(client, token, "relic", "life-first")
        assert first.status_code == 200, first.text
        after = runtime.sync(token)["user"]
        assert apply(before, first.json()["playerDataDelta"]) == after
        changed = after["rlv2"]["current"]["player"]["property"]
        assert changed["hp"] == {"current": prop["hp"]["current"] + amounts[0], "max": 0}
        assert changed["population"] == prop["population"] | {"max": prop["population"]["max"] + amounts[1]}
        assert changed["gold"] == prop["gold"] - 1
        assert after["troop"] == before["troop"]
        assert after["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][key]["state"] == 2
        saved = rows(runtime.database.path)
        assert buy(client, token, "relic", "life-first").json() == first.json()
        assert rows(runtime.database.path) == saved
        assert buy(client, token, "relic", "life-new").status_code == 200
        assert runtime.sync(token)["user"] == after


def test_two_runtimes_buy_mixed_reward_once(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, R01)
    before = current(runtime, token)["player"]["property"]
    other = Runtime(runtime.settings)
    try:
        def pay(pair):
            instance, key = pair
            with TestClient(create_game_app(instance)) as client:
                return buy(client, token, "relic", key).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(pay, ((runtime, "life-a"), (other, "life-b")))) == [200, 200]
        after = current(runtime, token)["player"]["property"]
        assert after["hp"]["current"] == before["hp"]["current"] + 2
        assert after["population"]["max"] == before["population"]["max"] + 1
        assert after["gold"] == before["gold"] - 1
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueRunRelic).filter_by(item_id=R01).count() == 1
    finally:
        other.database.close()


@pytest.mark.parametrize("failure", ("hope-overflow", "projection"))
def test_every_table_rolls_back_after_payment_or_partial_resource_calculation(cost_runtime, monkeypatch, failure):
    from terralocal.server.gamedata import rogue_life_relics

    runtime, token = cost_runtime
    configure(runtime, token, R01)
    if failure == "hope-overflow":
        original = rogue_life_relics.increase
        def increase(value, amount):
            if amount == 1:
                raise ValueError("Injected hope limit after HP calculation")
            return original(value, amount)
        monkeypatch.setattr(rogue_life_relics, "increase", increase)
    else:
        original = Replay.finish
        def finish(self, values):
            if any(g.item_id == R01 for g in self.grants):
                raise ValueError("Injected projection failure after life grant")
            return original(self, values)
        monkeypatch.setattr(Replay, "finish", finish)
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        response = buy(client, token, "relic", "life-rollback")
        assert response.status_code == (409 if failure == "hope-overflow" else 503)
    assert rows(runtime.database.path) == saved


def test_life_battle_rewards_replay_after_real_backup_and_cold_reopen(cost_runtime):
    from test_rogue_battle_loot import configured, finish_new

    runtime, token = cost_runtime
    configured(runtime, token, groups=((R01,), (R05,)))
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
        before = runtime.sync(token)["user"]
        prop = copy.deepcopy(before["rlv2"]["current"]["player"]["property"])
        for index in (2, 3):
            response = post(client, token, "chooseBattleReward", {"index": index, "sub": 0}, "life-loot-" + str(index))
            assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        changed = after["rlv2"]["current"]["player"]["property"]
        assert changed["hp"] == {"current": prop["hp"]["current"] + 12, "max": 0}
        assert changed["population"]["max"] == prop["population"]["max"] + 1
        assert post(client, token, "chooseBattleReward", {"index": 3, "sub": 0}, "life-loot-retry").status_code == 200
        assert runtime.sync(token)["user"] == after
        assert post(client, token, "finishBattleReward", {}, "life-loot-close").status_code == 200
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
