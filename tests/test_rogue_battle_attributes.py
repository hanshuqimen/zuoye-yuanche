"""Matched definitions and owned transactions; no native battle claim."""

import copy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import test_rogue_cost_relics as costs
import test_rogue_training as training_fixture
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy, configure, leave, saved_options
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_training import move
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.rogue_relics import MAX_RELICS, Replay
from terralocal.server.gamedata.rogue_battle_attributes import (
    ROUTE_RELICS,
    SOURCES,
    FirstThemeBattleAttributes,
)
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

A11 = "rogue_1_relic_a11"


def add_attribute(tables):
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    detail["items"][A11] = {"id": A11, "type": "RELIC", "unlockCondDesc": None}
    detail["relics"][A11] = {"id": A11, "buffs": [{"key": "char_attribute_mul", "blackboard": [
        {"key": "def", "value": 0.15, "valueStr": None}]}]}
    detail["relicParams"][A11] = {"id": A11, "checkCharBoxParams": [], "checkCharBoxTypes": []}
    detail["archiveComp"]["relic"]["relic"][A11] = {"relicId": A11, "enrollId": None,
        "isSpRelic": False, "relicGroupId": 1, "relicSortId": 11, "orderId": "QA-A11"}
    return tables


@pytest.fixture
def cost_tables(monkeypatch):
    original = costs.add_costs
    monkeypatch.setattr(costs, "add_costs", lambda tables: add_attribute(original(tables)))
    monkeypatch.setattr(training_fixture, "recruit_tables", lambda: costs.add_costs(costs.temporary_tables()))
    original_start = start_fixture.recruit_tables
    monkeypatch.setattr(start_fixture, "recruit_tables", lambda: costs.add_costs(original_start()))


def rules(table=None, *, enrollment=None):
    tables = add_attribute(costs.add_costs(costs.temporary_tables())) if table is None else table
    data = SimpleNamespace(table=lambda name: tables[name], manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda key: None), rogue_relic_archive=SimpleNamespace(
            entries={A11: SimpleNamespace(special=False, enrollment=enrollment)}, fingerprint="b" * 64))
    return FirstThemeBattleAttributes(data)


def test_single_matched_effect_without_copying_official_tables():
    value = rules()
    assert set(value.entries) == {A11}
    value.require_open(A11, 1)
    assert len(SOURCES) == 49 and MAX_RELICS == 122 and not SOURCES.keys() & ROUTE_RELICS
    with pytest.raises(TypeError):
        value.entries[A11] = "invalid"
    with pytest.raises(ValueError):
        value.require("rogue_1_relic_unknown")


@pytest.mark.parametrize("field,value", [("key", "atk"), ("value", 0.16), ("value", True), ("valueStr", "0.15")])
def test_changed_effect_fails_closed(field, value):
    tables = add_attribute(costs.add_costs(costs.temporary_tables()))
    tables["roguelike_topic_table"]["details"]["rogue_1"]["relics"][A11]["buffs"][0]["blackboard"][0][field] = value
    with pytest.raises(ValueError):
        rules(tables)


def test_unsupported_extra_effect_and_changed_conditions_are_not_admitted():
    tables = add_attribute(costs.add_costs(costs.temporary_tables()))
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    detail["relics"][A11]["buffs"].append({"key": "immediate_reward", "blackboard": []})
    with pytest.raises(ValueError):
        rules(tables)
    detail["relics"][A11]["buffs"].pop()
    detail["relicParams"][A11]["checkCharBoxTypes"] = ["UNKNOWN"]
    with pytest.raises(ValueError):
        rules(tables)


def test_enrollment_gate_has_real_integer_boundary():
    tables = add_attribute(costs.add_costs(costs.temporary_tables()))
    tables["roguelike_topic_table"]["details"]["rogue_1"]["enrolls"] = {
        "qa-dlc": {"enrollId": "qa-dlc", "enrollTime": 100}}
    value = rules(tables, enrollment="qa-dlc")
    for at in (99, True, 100.0, -1, 2**63):
        with pytest.raises(ValueError):
            value.require_open(A11, at)
    value.require_open(A11, 100)


def test_purchase_increment_retry_discovery_abandon_restart_backup(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, A11)
    permanent = copy.deepcopy(runtime.sync(token)["user"]["troop"])
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)["user"]
        reply = buy(client, token, "relic", "attribute-buy")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        from terralocal.server.protocol.delta import apply

        assert apply(before, reply.json()["playerDataDelta"]) == after
        assert after["troop"] == permanent
        assert after["rlv2"]["current"]["inventory"]["relic"]["1"]["id"] == A11
        assert after["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][A11]["state"] == 2
        assert buy(client, token, "relic", "attribute-new-sequence").status_code == 200
        assert runtime.sync(token)["user"] == after
        assert post(client, token, "giveUpGame", {}, "attribute-abandon").status_code == 200
    expected = runtime.sync(token)["user"]
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected
    finally:
        reopened.database.close()
    backups = BackupService(runtime)
    backup = backups.create()
    expected_rows = rows(runtime.database.path)
    backups.restore(backup["name"])
    assert rows(runtime.database.path) == expected_rows
    assert runtime.sync(token)["user"] == expected


def test_attribute_acquisition_does_not_create_cost_modifier_or_reprice_recruit(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, A11)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "attr").status_code == 200
        assert buy(client, token, "ticket", "new-ticket").status_code == 200
    candidates = current(runtime, token)["inventory"]["recruit"]["3"]["list"]
    four = next(c for c in candidates if c["charId"] == "char_four")
    assert four["population"] == 2


def test_new_quote_binds_definition_and_rejects_duplicate_or_stack(cost_runtime):
    runtime, _ = cost_runtime
    first = compile_shop(runtime.data, "qa-attributes", (Offer("a", A11, 1, relic_layer=0),), evidence="QA explicit stock")
    second = compile_shop(runtime.data, "qa-attributes", (Offer("a", A11, 2, relic_layer=0),), evidence="QA explicit stock")
    assert first.digest != second.digest
    for offers in [(Offer("a", A11, 1, relic_layer=1),),
                   (Offer("a", A11, 1, relic_layer=0), Offer("b", A11, 1, relic_layer=0))]:
        with pytest.raises(ValueError):
            compile_shop(runtime.data, "qa-attributes", offers, evidence="QA explicit stock")


@pytest.mark.parametrize("field,value", [("count", 2), ("layer", 1), ("item_id", "unknown")])
def test_corrupt_inventory_is_rejected_on_readonly_startup(cost_runtime, field, value):
    runtime, token = cost_runtime
    configure(runtime, token, A11)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "attribute").status_code == 200
    with runtime.database.transaction() as session:
        row = session.query(m.RogueRunRelic).filter_by(ordinal=1).one()
        setattr(row, field, value)
    before = rows(runtime.database.path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before


def test_attribute_then_cost_effect_preserves_old_offer_and_discounts_only_later_offer(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, A11)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "attribute").status_code == 200
        assert buy(client, token, "ticket", "first-ticket").status_code == 200
        first = current(runtime, token)["inventory"]["recruit"]["3"]["list"]
        target = next(c for c in first if c["charId"] == "char_four")
        assert target["population"] == 2
        frozen = saved_options(runtime, 3)
        assert post(client, token, "recruitChar", {"ticketIndex": "3", "optionId": str(target["instId"])},
                    "choose-four").status_code == 200
        assert leave(client, token).status_code == 200
        assert move(client, token, 3, "later-shop").status_code == 200
        assert buy(client, token, "relic", "later-cost").status_code == 200
        assert buy(client, token, "ticket", "later-ticket").status_code == 200
        later = current(runtime, token)["inventory"]["recruit"]["4"]["list"]
        assert next(c for c in later if c["charId"] == "char_five")["population"] == 1
        assert saved_options(runtime, 3) == frozen
    expected = runtime.sync(token)["user"]
    other = Runtime(runtime.settings)
    try:
        assert other.sync(token)["user"] == expected
    finally:
        other.database.close()


def test_concurrent_attribute_purchase_has_one_grant_and_one_payment(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, A11)
    before = current(runtime, token)["player"]["property"]["gold"]
    other = Runtime(runtime.settings)
    try:
        def pay(pair):
            instance, key = pair
            with TestClient(create_game_app(instance)) as client:
                return buy(client, token, "relic", key).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(pay, ((runtime, "first"), (other, "second")))) == [200, 200]
        state = current(runtime, token)
        assert len(state["inventory"]["relic"]) == 2
        assert state["player"]["property"]["gold"] == before - 1
        assert len(state["inventory"]["recruit"]) == 3
    finally:
        other.database.close()


def test_post_grant_projection_failure_rolls_back_attribute_inventory_stock_gold_and_receipt(cost_runtime, monkeypatch):
    runtime, token = cost_runtime
    configure(runtime, token, A11)
    original = Replay.finish
    def fail(self, values):
        if any(g.item_id == A11 for g in self.grants):
            raise ValueError("Injected failure after new attribute inventory insertion")
        return original(self, values)
    monkeypatch.setattr(Replay, "finish", fail)
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        response = buy(client, token, "relic", "rollback-attribute")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "ROGUE_SETTLEMENT_INCOMPATIBLE"
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("key", sorted(ROUTE_RELICS))
def test_route_chain_is_not_admitted_even_with_an_attribute_only_effect_row(key):
    tables = add_attribute(costs.add_costs(costs.temporary_tables()))
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    detail.setdefault("gameConst", {})["goldItemId"] = "qa_gold"
    detail["items"]["qa_gold"] = {"id": "qa_gold", "type": "GOLD"}
    detail["items"][key] = {"id": key, "type": "RELIC"}
    detail["relics"][key] = copy.deepcopy(detail["relics"][A11]) | {"id": key}
    data = SimpleNamespace(table=lambda name: tables[name], manifest={"hash": "a" * 64},
                           rogue_recruit_costs=SimpleNamespace(modifiers={}))
    with pytest.raises(ValueError):
        compile_shop(data, "qa-rejected-route", (Offer("a", key, 1, relic_layer=0),),
                     evidence="An attribute row alone must not bypass the hidden route")
