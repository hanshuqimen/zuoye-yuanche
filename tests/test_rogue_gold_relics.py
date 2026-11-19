"""Immediate gold with authored QA supply; no natural-pool/native claims."""

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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

from terralocal.server.domain import rogue_banks
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_bank_ledger import compile_terms
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_relics import Replay
from terralocal.server.domain.rogue_shop import Purchase, replay
from terralocal.server.domain.rogue_shops import prepare
from terralocal.server.gamedata import rogue_gold_relics as gold
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

AMOUNTS = {"rogue_1_relic_r11": 10, "rogue_1_relic_r12": 18, "rogue_1_relic_r13": 25}
R11, R12, R13 = AMOUNTS


def add_gold(tables, monkeypatch):
    d = tables["roguelike_topic_table"]["details"]["rogue_1"]
    target = "test_gold"  # The composed training fixture replaces its currency.
    d.setdefault("gameConst", {}).update(goldItemId=target, bankMaxGold=999, bankRewardCountType="HIGHEST_RECORD")
    d["bankRewards"] = [{"rewardId": "qa-draw", "rewardType": "UNLOCK_WITHDRAW", "unlockGoldCnt": 200}]
    d["items"].setdefault(target, {"id": target, "type": "GOLD"})
    sources = {}
    for number, (key, amount) in enumerate(AMOUNTS.items()):
        item = {"id": key, "type": "RELIC", "unlockCondDesc": "QA-only identity " + str(number)}
        effect = {"id": key, "buffs": [{"key": "immediate_reward", "blackboard": [
            {"key": "id", "value": 0.0, "valueStr": target},
            {"key": "count", "value": float(amount), "valueStr": None}]}]}
        conditions = {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []}
        archive = {"relicId": key, "enrollId": None, "isSpRelic": False,
                   "orderId": "QA" + str(number), "relicGroupId": 1, "relicSortId": number}
        d["items"][key], d["relics"][key], d["relicParams"][key] = item, effect, conditions
        d["archiveComp"]["relic"]["relic"][key] = archive
        sources[key] = amount, fingerprint({"item": item, "effect": effect, "conditions": conditions,
                                           "archive": archive, "gold": d["items"][target]})
    monkeypatch.setattr(gold, "SOURCES", MappingProxyType(sources))
    return tables


@pytest.fixture
def gold_tables(cost_tables, monkeypatch):
    original = costs.add_costs
    monkeypatch.setattr(costs, "add_costs", lambda tables: add_gold(original(tables), monkeypatch))
    original_map = training_fixture.map_tables
    def maps():
        tables = original_map()
        tables["roguelike_topic_table"]["details"]["rogue_1"]["gameConst"].update(
            bankMaxGold=999, bankRewardCountType="HIGHEST_RECORD")
        return tables
    monkeypatch.setattr(training_fixture, "map_tables", maps)


@pytest.fixture
def gold_runtime(gold_tables, cost_runtime):
    return cost_runtime


def rules(monkeypatch):
    tables = add_gold(costs.add_costs(costs.temporary_tables()), monkeypatch)
    d = tables["roguelike_topic_table"]["details"]["rogue_1"]
    data = SimpleNamespace(table=lambda name: tables[name], manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda topic: None),
        rogue_relic_archive=SimpleNamespace(entries={key: SimpleNamespace(special=False, enrollment=None)
                                                   for key in AMOUNTS}))
    return data, d


@pytest.mark.parametrize("key,amount", tuple(AMOUNTS.items()))
def test_exact_family_immutable_and_mismatched_full_definition_rejected(monkeypatch, key, amount):
    data, detail = rules(monkeypatch)
    value = gold.FirstThemeGoldRelics(data)
    assert value.require(key) == amount
    with pytest.raises(TypeError):
        value.entries[key] = 99
    detail["relics"][key]["buffs"][0]["blackboard"][1]["value"] += 1
    with pytest.raises(ValueError):
        gold.FirstThemeGoldRelics(data)


@pytest.mark.parametrize("field", ["item", "effect", "conditions", "archive", "gold", "reference"])
def test_changed_reference_or_condition_cannot_keep_previous_effect(monkeypatch, field):
    data, detail = rules(monkeypatch)
    if field == "item":
        detail["items"][R13]["unlockCondDesc"] = "changed"
    elif field == "effect":
        detail["relics"][R13]["buffs"].append({"key": "unknown", "blackboard": []})
    elif field == "conditions":
        detail["relicParams"][R13]["checkCharBoxTypes"] = ["unknown"]
    elif field == "archive":
        detail["archiveComp"]["relic"]["relic"][R13]["isSpRelic"] = True
    elif field == "gold":
        detail["items"][detail["gameConst"]["goldItemId"]]["id"] = "other"
    else:
        data.rogue_relic_archive.entries[R13].enrollment = "future"
    with pytest.raises(ValueError):
        gold.FirstThemeGoldRelics(data)


def test_reviewed_amount_must_match_effect_even_when_digest_matches(monkeypatch):
    data, _ = rules(monkeypatch)
    sources = dict(gold.SOURCES)
    sources[R13] = (26, sources[R13][1])
    monkeypatch.setattr(gold, "SOURCES", MappingProxyType(sources))
    with pytest.raises(ValueError):
        gold.FirstThemeGoldRelics(data)


@pytest.mark.parametrize("gains", [{"r1": True}, {"r1": -1}, {"r1": 1.0}, {"r1": 2**31},
                                   {"missing": 1}, {"t1": 1}])
def test_invalid_quote_resource_capability_cannot_change_balance(gains):
    from test_rogue_shop_receipts import mixed

    q = replace(mixed(), gold_gains=MappingProxyType(gains))
    with pytest.raises(DomainError):
        replay(q, 10, 90, 3, ())


def configure(runtime, token, *, bank=False):
    setup(runtime, token, ("SHOP", "SHOP"))
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        q = compile_shop(runtime.data, "qa-gold-relic-effects", tuple(
            Offer(key, key, 2, relic_layer=0) for key in AMOUNTS),
            evidence="Authored effect-only QA; r13 is NOT admitted to the normal merchant pool")
        prepare(ctx, {Point(0, 0): q})
        if bank:
            row = session.query(m.RogueShopVisit).filter_by(node_x=0).one()
            terms = compile_terms(runtime.data, q, mode="NORMAL", grade=0,
                bank_open=True, allow_deposit=True, allow_withdraw=True,
                withdrawal_costs=(1, 2, 4, 8, 16, 32), evidence="Forced QA outcomes; no earned/natural claim")
            rogue_banks.prepare(ctx, row.id, terms, outcomes=(False,) * 40, has_boss=True)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "gold-enter").status_code == 200
    return q


def balance(runtime, token):
    return current(runtime, token)["player"]["property"]["gold"]


@pytest.mark.parametrize("key,amount", tuple(AMOUNTS.items()))
def test_three_real_api_grants_delta_retry_restart_backup_and_collection(gold_runtime, key, amount):
    runtime, token = gold_runtime
    q = configure(runtime, token)
    assert dict(q.gold_gains) == AMOUNTS
    before = runtime.sync(token)["user"]
    original = balance(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        reply = buy(client, token, key, "gold-buy")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        assert balance(runtime, token) == original - 2 + amount
        assert after["troop"] == before["troop"]
        assert after["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][key]["state"] == 2
        assert buy(client, token, key, "gold-buy").json() == reply.json()
        assert buy(client, token, key, "gold-new-seq").status_code == 200
        assert runtime.sync(token)["user"] == after
        assert leave(client, token, "gold-leave").status_code == 200
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


def test_causal_payment_cannot_borrow_own_reward_and_overflow_is_rejected(gold_runtime):
    runtime, token = gold_runtime
    q = configure(runtime, token)
    with pytest.raises(DomainError):
        replay(q, 1, 100, 3, (Purchase(R13, 100, None),))
    assert replay(q, 2, 100, 3, (Purchase(R13, 100, None),)).gold == 25
    with pytest.raises(DomainError):
        replay(q, 2**31 - 1, 100, 3, (Purchase(R13, 100, None),))
    # Earlier rewards can pay later prices; total alone cannot reorder history.
    assert replay(q, 2, 100, 3, (Purchase(R11, 100, None), Purchase(R13, 100, None))).gold == 33


def test_bank_buy_deposit_withdraw_share_reward_and_restart_history(gold_runtime):
    runtime, token = gold_runtime
    configure(runtime, token, bank=True)
    initial = balance(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "bankPut", {}, "gold-bank-first").status_code == 200
        assert buy(client, token, R13, "gold-bank-buy").status_code == 200
        assert balance(runtime, token) == initial - 3 + 25
        for n in range(8):
            assert post(client, token, "bankPut", {}, "gold-bank-put-" + str(n)).status_code == 200
        assert post(client, token, "bankWithdraw", {}, "gold-bank-draw").status_code == 200
        assert buy(client, token, R12, "gold-bank-later").status_code == 200
        assert balance(runtime, token) == initial - 3 + 25 - 8 + 1 - 2 + 18
        assert buy(client, token, R13, "gold-bank-retry").status_code == 200
    expected = runtime.sync(token)["user"]
    bank = expected["rlv2"]["outer"]["rogue_1"]["bank"]
    assert bank["current"] == 8 and bank["totalPut"] == bank["record"] == 9
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected
    finally:
        reopened.database.close()


@pytest.mark.parametrize("bank", [False, True])
def test_postgrant_failure_rolls_back_payment_gold_inventory_receipt_and_bank(gold_runtime, monkeypatch, bank):
    runtime, token = gold_runtime
    configure(runtime, token, bank=bank)
    original = Replay.finish
    def fail(self, values):
        if any(g.item_id == R13 for g in self.grants):
            raise ValueError("Injected post-grant projection failure")
        return original(self, values)
    monkeypatch.setattr(Replay, "finish", fail)
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, R13, "gold-rollback").status_code == 503
    assert rows(runtime.database.path) == before


def test_two_runtimes_concurrent_purchase_rewards_only_once(gold_runtime):
    runtime, token = gold_runtime
    configure(runtime, token, bank=True)
    before = balance(runtime, token)
    other = Runtime(runtime.settings)
    try:
        def pay(pair):
            target, key = pair
            with TestClient(create_game_app(target)) as client:
                return buy(client, token, R13, key).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(pay, ((runtime, "gold-one"), (other, "gold-two")))) == [200, 200]
        assert balance(runtime, token) == before - 2 + 25
    finally:
        other.database.close()


def test_unjournaled_gold_is_rejected_read_only(gold_runtime):
    runtime, token = gold_runtime
    configure(runtime, token)
    before = copy.deepcopy(runtime.sync(token)["user"])
    with runtime.database.transaction() as session:
        session.query(m.RogueTopicRun).filter_by(account_id=1, ended_at=None).one().gold += 25
    snapshot = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == snapshot and before["rlv2"]["current"]


def test_unearned_collection_is_not_an_acquisition_source():
    from terralocal.server.domain.rogue_collection import project

    forged = {"collect": {"relic": {R13: {"state": 2, "progress": []}}}}
    before = copy.deepcopy(forged)
    with pytest.raises(DomainError):
        project(forged, frozenset())
    assert forged == before
