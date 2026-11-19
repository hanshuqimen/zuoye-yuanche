"""Owned synthetic effect fixtures and transactions; no native-effect claim."""

import copy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import test_rogue_cost_relics as costs
import test_rogue_training as training_fixture
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_battle_attributes import A11, add_attribute
from test_rogue_cost_relics import buy, configure
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.rogue_relics import MAX_RELICS, Replay
from terralocal.server.gamedata.rogue_global_buffs import EXCLUDED_RELICS, SOURCES, FirstThemeGlobalBuffs
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

A02 = "rogue_1_relic_a02"


def add_global(tables):
    """One minimal authored rule; no official table or creative text fixture."""
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    detail["items"][A02] = {"id": A02, "type": "RELIC", "unlockCondDesc": None}
    detail["relics"][A02] = {"id": A02, "buffs": [{"key": "global_buff_normal", "blackboard": [
        {"key": "key", "value": 0.0, "valueStr": "enemy_atk_down"},
        {"key": "atk", "value": -0.07, "valueStr": None}]}]}
    detail["relicParams"][A02] = {"id": A02, "checkCharBoxParams": [], "checkCharBoxTypes": []}
    detail["archiveComp"]["relic"]["relic"][A02] = {"relicId": A02, "enrollId": None,
        "isSpRelic": False, "relicGroupId": 1, "relicSortId": 2, "orderId": "QA-GLOBAL"}
    return tables


@pytest.fixture
def cost_tables(monkeypatch):
    original = costs.add_costs
    monkeypatch.setattr(costs, "add_costs", lambda tables: add_global(add_attribute(original(tables))))
    monkeypatch.setattr(training_fixture, "recruit_tables", lambda: costs.add_costs(costs.temporary_tables()))
    original_start = start_fixture.recruit_tables
    monkeypatch.setattr(start_fixture, "recruit_tables", lambda: costs.add_costs(original_start()))


def rules(tables=None, *, special=False, enrollment=None):
    if tables is None:
        tables = add_global(costs.add_costs(costs.temporary_tables()))
    data = SimpleNamespace(table=lambda name: tables[name], manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda key: None), rogue_relic_archive=SimpleNamespace(
            entries={A02: SimpleNamespace(special=special, enrollment=enrollment)}, fingerprint="b" * 64))
    return FirstThemeGlobalBuffs(data)


def test_frozen_rule_and_separate_capability_budget():
    value = rules()
    value.require_open(A02, 1)
    assert set(value.entries) == {A02}
    assert len(SOURCES) == 42 and len(EXCLUDED_RELICS) == 10 and MAX_RELICS == 122
    assert not SOURCES.keys() & EXCLUDED_RELICS
    with pytest.raises(TypeError):
        value.entries[A02] = "changed"
    for key in EXCLUDED_RELICS:
        with pytest.raises(ValueError):
            value.require(key)


@pytest.mark.parametrize("kind", ("value", "bool", "selector", "extra_effect", "stack", "condition", "missing_condition"))
def test_complete_definition_changes_are_rejected(kind):
    tables = add_global(costs.add_costs(costs.temporary_tables()))
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    buff = detail["relics"][A02]["buffs"][0]
    if kind == "value":
        buff["blackboard"][1]["value"] = -0.08
    elif kind == "bool":
        buff["blackboard"][0]["value"] = False
    elif kind == "selector":
        buff["blackboard"].append({"key": "selector.profession", "value": 0.0, "valueStr": "CASTER"})
    elif kind == "extra_effect":
        detail["relics"][A02]["buffs"].append({"key": "immediate_reward", "blackboard": []})
    elif kind == "stack":
        buff["key"] = "global_buff_stack"
    elif kind == "condition":
        detail["relicParams"][A02]["checkCharBoxTypes"] = ["UNKNOWN"]
    else:
        del detail["relicParams"][A02]
    with pytest.raises(ValueError):
        rules(tables)


def test_special_and_enrollment_are_independent_gates():
    with pytest.raises(ValueError):
        rules(special=True)
    tables = add_global(costs.add_costs(costs.temporary_tables()))
    tables["roguelike_topic_table"]["details"]["rogue_1"]["enrolls"] = {
        "qa-dlc": {"enrollId": "qa-dlc", "enrollTime": 100}}
    value = rules(tables, enrollment="qa-dlc")
    for at in (99, True, 100.0, -1, 2**63):
        with pytest.raises(ValueError):
            value.require_open(A02, at)
    value.require_open(A02, 100)


def test_legacy_quotes_do_not_depend_on_new_capability_catalog(cost_runtime, monkeypatch):
    runtime, _ = cost_runtime
    offer = (Offer("a", A11, 1, relic_layer=0),)
    legacy = compile_shop(runtime.data, "legacy-attribute", offer, evidence="Owned legacy quote")
    global_offer = (Offer("g", A02, 1, relic_layer=0),)
    quote = compile_shop(runtime.data, "new-global", global_offer, evidence="Owned global quote")
    catalog = runtime.data.rogue_global_buffs
    monkeypatch.setattr(catalog, "fingerprint", "f" * 64)
    assert compile_shop(runtime.data, "legacy-attribute", offer, evidence="Owned legacy quote").digest == legacy.digest
    assert compile_shop(runtime.data, "new-global", global_offer, evidence="Owned global quote").digest != quote.digest
    for offers in ((Offer("g", A02, 1, relic_layer=1),),
                   (Offer("g", A02, 1, relic_layer=0), Offer("h", A02, 1, relic_layer=0))):
        with pytest.raises(ValueError):
            compile_shop(runtime.data, "invalid-global", offers, evidence="Invalid owned quote")


def test_purchase_delta_retries_discovery_recruit_cost_restart_backup(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, A02)
    permanent = copy.deepcopy(runtime.sync(token)["user"]["troop"])
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)["user"]
        response = buy(client, token, "relic", "global-buy")
        assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        assert after["troop"] == permanent
        state = after["rlv2"]["current"]
        assert state["inventory"]["relic"]["1"]["id"] == A02
        assert state["player"]["property"]["gold"] == before["rlv2"]["current"]["player"]["property"]["gold"] - 1
        assert after["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][A02]["state"] == 2
        saved = rows(runtime.database.path)
        assert buy(client, token, "relic", "global-buy").json() == response.json()
        assert rows(runtime.database.path) == saved
        assert buy(client, token, "relic", "global-new-sequence").status_code == 200
        assert runtime.sync(token)["user"] == after
        assert buy(client, token, "ticket", "global-ticket").status_code == 200
        candidates = current(runtime, token)["inventory"]["recruit"]["3"]["list"]
        assert next(c for c in candidates if c["charId"] == "char_four")["population"] == 2
        assert post(client, token, "giveUpGame", {}, "global-abandon").status_code == 200
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


def test_concurrent_purchase_has_one_payment_and_one_grant(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, A02)
    before = current(runtime, token)["player"]["property"]["gold"]
    other = Runtime(runtime.settings)
    try:
        def pay(pair):
            instance, key = pair
            with TestClient(create_game_app(instance)) as client:
                return buy(client, token, "relic", key).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(pay, ((runtime, "global-first"), (other, "global-second")))) == [200, 200]
        state = current(runtime, token)
        assert len(state["inventory"]["relic"]) == 2
        assert state["player"]["property"]["gold"] == before - 1
    finally:
        other.database.close()


def test_post_grant_failure_rolls_back_inventory_gold_stock_and_receipt(cost_runtime, monkeypatch):
    runtime, token = cost_runtime
    configure(runtime, token, A02)
    original = Replay.finish
    def fail(self, values):
        if any(g.item_id == A02 for g in self.grants):
            raise ValueError("Injected failure after global-buff insertion")
        return original(self, values)
    monkeypatch.setattr(Replay, "finish", fail)
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        response = buy(client, token, "relic", "global-rollback")
        assert response.status_code == 503
    assert rows(runtime.database.path) == saved


@pytest.mark.parametrize("field,value", (("count", 2), ("layer", 1), ("item_id", "unknown")))
def test_corrupt_owned_global_inventory_is_rejected_on_readonly_start(cost_runtime, field, value):
    runtime, token = cost_runtime
    configure(runtime, token, A02)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "global-grant").status_code == 200
    with runtime.database.transaction() as session:
        setattr(session.query(m.RogueRunRelic).filter_by(ordinal=1).one(), field, value)
    saved = rows(runtime.database.path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved


def test_explicit_battle_reward_grants_global_effect_once(cost_runtime):
    from test_rogue_battle_loot import configured, finish_new

    runtime, token = cost_runtime
    configured(runtime, token, groups=((A02,),))
    with TestClient(create_game_app(runtime)) as client:
        reward = finish_new(runtime, token, client)
        assert reward["rewards"][2]["items"] == [{"id": A02, "count": 1, "sub": 0}]
        before = runtime.sync(token)["user"]
        response = post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "global-loot")
        assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        assert after["rlv2"]["current"]["inventory"]["relic"]["1"]["id"] == A02
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "global-loot-again").status_code == 200
        assert runtime.sync(token)["user"] == after
        assert post(client, token, "finishBattleReward", {}, "global-loot-close").status_code == 200
    expected = runtime.sync(token)["user"]
    other = Runtime(runtime.settings)
    try:
        assert other.sync(token)["user"] == expected
    finally:
        other.database.close()
