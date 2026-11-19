"""Settlement-backed merchant selection; low thresholds and stock are QA only."""

import copy
import hashlib
import json
import sqlite3
from types import MappingProxyType, SimpleNamespace

import pytest
import test_rogue_cost_relics as costs
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_resource_relics import configure
from test_rogue_resource_relics import resource_runtime as resource_runtime
from test_rogue_resource_relics import resource_tables as resource_tables
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_initial import post, start
from test_roguelike_state import rows

from terralocal.server.domain import rogue_bank_items, rogue_merchant
from terralocal.server.domain.accounts import login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_shops import prepare as save_shops
from terralocal.server.gamedata import rogue_bank_items as bindings
from terralocal.server.gamedata import rogue_gold_relics as gold
from terralocal.server.gamedata import rogue_merchant_relics as merchant
from terralocal.server.gamedata import rogue_resource_relics as resource
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_bank import FirstThemeBankRules
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

R13, Q28 = "rogue_1_relic_r13", "rogue_1_relic_q28"


def augment(tables, monkeypatch):
    d = tables["roguelike_topic_table"]["details"]["rogue_1"]
    sources, prices = {}, {}
    d["bankRewards"] = []
    for key, threshold, name in ((R13, 2, "QA宝玉"), (Q28, 3, "QA酒杯")):
        item = d["items"][key]
        item.update(name=name, iconId=key, rarity="SUPER_RARE",
                    unlockCondDesc=f"在“前瞻性投资系统”中的投资储备余额最高达到过{threshold}")
        identity = {f: item[f] for f in ("id", "type", "iconId", "rarity", "unlockCondDesc")}
        archive = d["archiveComp"]["relic"]["relic"][key]
        digest = fingerprint({"item": identity, "archive": archive})
        reward = "qa-" + key
        sources[key] = reward, threshold, name, digest
        prices[key] = None if key == R13 else 16, digest
        d["bankRewards"].append({"rewardId": reward, "rewardType": "UNLOCK_ITEM", "unlockGoldCnt": threshold,
                                 "desc": "解锁收藏品【" + name + "】"})
        module = gold if key == R13 else resource
        effect_source = {"item": {f: item[f] for f in ("id", "type", "unlockCondDesc")},
            "effect": d["relics"][key], "conditions": d["relicParams"][key], "archive": archive,
            "gold": d["items"][d["gameConst"]["goldItemId"]]}
        old = dict(module.SOURCES)
        old[key] = old[key][0], fingerprint(effect_source)
        monkeypatch.setattr(module, "SOURCES", MappingProxyType(old))
    monkeypatch.setattr(bindings, "SOURCES", MappingProxyType(sources))
    monkeypatch.setattr(merchant, "SOURCES", MappingProxyType(prices))
    return tables


@pytest.fixture
def bank_item_tables(resource_tables, monkeypatch):
    original = costs.add_costs
    monkeypatch.setattr(costs, "add_costs", lambda tables: augment(original(tables), monkeypatch))


@pytest.fixture
def bank_item_runtime(bank_item_tables, resource_runtime):
    return resource_runtime


def qualify(runtime, *, run_id=None, account=1):
    with runtime.database.transaction(write=False) as session:
        run = session.get(m.RogueTopicRun, run_id) if run_id else session.query(m.RogueTopicRun).filter_by(
            account_id=1).order_by(m.RogueTopicRun.created_at.desc()).first()
        return rogue_bank_items.qualification(Context(session, runtime.data, account), run)


def finish_bank(runtime, token):
    configure(runtime, token, bank=True)
    with TestClient(create_game_app(runtime)) as client:
        for n in range(3):
            assert post(client, token, "bankPut", {}, "put-" + str(n)).status_code == 200
        assert not qualify(runtime).items
        assert post(client, token, "giveUpGame", {}, "giveup").status_code == 200
        assert not qualify(runtime).items
        assert post(client, token, "gameSettle", {}, "settle").status_code == 200
    with runtime.database.transaction(write=False) as session:
        run = session.query(m.RogueTopicRun).filter_by(account_id=1).one()
        return run.id


def next_run(runtime, token):
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += runtime.data.rogue_initial.cooldown + 1
        token = login(session, runtime.settings, name=session.get(m.Account, 1).name)["secret"]
    with TestClient(create_game_app(runtime)) as client:
        response = start(client, token)
        assert response.status_code == 200, response.text
        assert post(client, token, "chooseInitialRelic", {"select": "0"}, "new-band").status_code == 200
        assert post(client, token, "chooseInitialRecruitSet", {"select": "recruit_group_1"}, "new-group").status_code == 200
        for n in range(3):
            assert post(client, token, "activeRecruitTicket", {"id": str(n)}, "active-" + str(n)).status_code == 200
            assert post(client, token, "closeRecruitTicket", {"id": str(n)}, "close-" + str(n)).status_code == 200
        with runtime.database.transaction() as session:
            save_map(Context(session, runtime.data, 1), Plan("zone_1", (Column(1, 1, (Entry("SHOP", 1),)),) * 2, 0))
        assert post(client, token, "finishEvent", {}, "new-map").status_code == 200
    return token


def test_confirmed_awards_only_qualify_subsequent_owned_run_and_survive_restore(bank_item_runtime):
    runtime, token = bank_item_runtime
    old_run = finish_bank(runtime, token)
    assert not qualify(runtime, run_id=old_run).items
    token = next_run(runtime, token)
    earned = qualify(runtime)
    assert earned.items == frozenset({R13, Q28})
    with runtime.database.transaction() as session:
        q = rogue_merchant.quote(Context(session, runtime.data, 1), "earned-shop", (("cup", Q28),))
        assert q.offers["cup"].price == 16
        with pytest.raises(DomainError, match="所选商品缺少"):
            rogue_merchant.quote(Context(session, runtime.data, 1), "not-for-sale", (("gem", R13),))
        # Explicit QA funding stock; the cup's independently earned base price
        # remains 16. This is not a natural distribution or official event.
        funded = compile_shop(runtime.data, q.id, tuple(q.offers.values()) + (Offer("qa-funds", "rogue_1_relic_r11", 0, relic_layer=0),),
                              evidence=q.evidence + "; QA-only funding slot")
        save_shops(Context(session, runtime.data, 1), {Point(0, 0): funded})
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, "new-enter").status_code == 200
        assert buy(client, token, "qa-funds", "qa-funds").status_code == 200
        before = runtime.sync(token)["user"]
        response = buy(client, token, "cup", "earned-cup")
        assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        assert after["rlv2"]["current"]["player"]["property"]["gold"] == 0
        assert buy(client, token, "cup", "earned-cup-retry").status_code == 200
        assert runtime.sync(token)["user"] == after
    saved, user = rows(runtime.database.path), runtime.sync(token)["user"]
    reopened = Runtime(runtime.settings)
    try:
        assert qualify(reopened) == earned and reopened.sync(token)["user"] == user
        service = BackupService(reopened)
        service.restore(service.create()["name"])
        assert qualify(reopened) == earned and rows(runtime.database.path) == saved
    finally:
        reopened.database.close()


def test_purchase_discovery_does_not_bypass_missing_bank_award(bank_item_runtime):
    runtime, token = bank_item_runtime
    configure(runtime, token, bank=True)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "resource", "qa-acquisition").status_code == 200
    assert runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][Q28]["state"] == 2
    assert not qualify(runtime).items
    with runtime.database.transaction(write=False) as session:
        with pytest.raises(DomainError, match="所选商品缺少"):
            rogue_merchant.quote(Context(session, runtime.data, 1), "no-earned-bank", (("cup", Q28),))


@pytest.mark.parametrize("corruption", ["award", "score_facts"])
def test_bank_qualification_rejects_foreign_owner_and_live_corrupted_award(bank_item_runtime, corruption):
    runtime, token = bank_item_runtime
    old_run = finish_bank(runtime, token)
    with pytest.raises(DomainError):
        qualify(runtime, run_id=old_run, account=2)
    token = next_run(runtime, token)
    assert qualify(runtime).items
    with runtime.database.transaction() as session:
        if corruption == "award":
            wallet = session.get(m.RogueBankWallet, 1)
            log = copy.deepcopy(wallet.awards)
            log[0]["score"] = "0" * 64
            wallet.awards = log
        else:
            score = session.get(m.RogueGameSettlement, old_run)
            value = copy.deepcopy(score.facts)
            value["counts"][5] += 1
            score.facts = value
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError):
        qualify(runtime)
    assert rows(runtime.database.path) == saved


def test_unknown_legacy_reward_keys_and_malformed_selection_cannot_grant(bank_item_runtime):
    runtime, token = bank_item_runtime
    configure(runtime, token)
    with runtime.database.transaction() as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        state = copy.deepcopy(outer.state)
        state["bank"] = {"show": True, "current": 325, "record": 325, "totalPut": 325,
                         "reward": {row[0]: 0 for row in bindings.SOURCES.values()}}
        outer.state = state
    assert not qualify(runtime).items
    before = rows(runtime.database.path)
    for slots in (None, (None,), (("cup",),), (("cup", []),), (("cup", Q28),)):
        with runtime.database.transaction(write=False) as session:
            with pytest.raises(DomainError):
                rogue_merchant.quote(Context(session, runtime.data, 1), "untrusted", slots)
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("change", ["description", "threshold", "reward_type", "name", "identity", "special", "counter"])
def test_reward_binding_checks_full_row_and_item_identity(bank_item_runtime, change):
    runtime, _ = bank_item_runtime
    tables = copy.deepcopy(runtime.data.table("roguelike_topic_table"))
    detail = tables["details"]["rogue_1"]
    row = detail["bankRewards"][0]
    if change == "description":
        row["desc"] += " changed"
    elif change == "threshold":
        row["unlockGoldCnt"] += 1
    elif change == "reward_type":
        row["rewardType"] = "UNLOCK_WITHDRAW"
    elif change == "name":
        detail["items"][R13]["name"] = "changed"
    elif change == "identity":
        detail["items"][R13]["iconId"] = "wrong"
    elif change == "special":
        # Archive compiler catches malformed/changed enrollment flags too.
        detail["archiveComp"]["relic"]["relic"][R13]["isSpRelic"] = True
    else:
        detail["gameConst"]["bankRewardCountType"] = "TOTAL_SUM"
    data = SimpleNamespace(manifest=runtime.data.manifest, table=lambda name: tables,
                           rogue_topics=runtime.data.rogue_topics, rogue_relic_archive=runtime.data.rogue_relic_archive)
    data.rogue_bank = FirstThemeBankRules(data)
    with pytest.raises(ValueError):
        bindings.FirstThemeBankItems(data)


def bank_collection(runtime, token):
    return runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["relic"]


def test_bank_collection_separates_reached_peak_from_settled_unlock_and_preserves_delta(bank_item_runtime):
    runtime, token = bank_item_runtime
    assert {key: bank_collection(runtime, token)[key] for key in (R13, Q28)} == {
        R13: {"state": 0, "progress": []}, Q28: {"state": 0, "progress": []}}
    configure(runtime, token, bank=True)
    with TestClient(create_game_app(runtime)) as client:
        for n in range(3):
            before = runtime.sync(token)["user"]
            response = post(client, token, "bankPut", {}, "collect-put-" + str(n))
            assert response.status_code == 200
            after = runtime.sync(token)["user"]
            assert apply(before, response.json()["playerDataDelta"]) == after
            relics = bank_collection(runtime, token)
            for key, target in ((R13, 2), (Q28, 3)):
                assert relics[key] == {"state": 0, "progress": [min(n + 1, target), target]}
        assert post(client, token, "bankWithdraw", {}, "collect-draw").status_code == 200
        assert bank_collection(runtime, token)[Q28] == {"state": 0, "progress": [3, 3]}
        assert post(client, token, "giveUpGame", {}, "collect-end").status_code == 200
        before = runtime.sync(token)["user"]
        response = post(client, token, "gameSettle", {}, "collect-confirm")
        assert response.status_code == 200
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        assert bank_collection(runtime, token)[R13] == {"state": 1, "progress": [2, 2]}
        assert bank_collection(runtime, token)[Q28] == {"state": 1, "progress": [3, 3]}
        assert post(client, token, "gameSettle", {}, "collect-confirm-again").status_code == 200
        assert runtime.sync(token)["user"] == after
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.RogueTopicOuter, (1, "rogue_1")).state["collect"]["relic"] == {}
        assert session.get(m.RogueBankWallet, 1).state["current"] == 2  # Record remains3.
    saved = rows(runtime.database.path)
    copy_wire = bank_collection(runtime, token)
    copy_wire[Q28]["progress"][0] = 999
    assert runtime.sync(token)["user"] == after and rows(runtime.database.path) == saved
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after and rows(runtime.database.path) == saved
        service = BackupService(reopened)
        service.restore(service.create()["name"])
        assert reopened.sync(token)["user"] == after and rows(runtime.database.path) == saved
    finally:
        reopened.database.close()


@pytest.mark.parametrize("claim", [
    {"state": 1, "progress": []}, {"state": 2, "progress": []},
    {"state": 0, "progress": [0, 3]}, {"state": 0, "progress": [1, 3]},
])
def test_bank_collection_unowned_legacy_claim_rejected_live_and_before_writes(bank_item_runtime, claim):
    runtime, token = bank_item_runtime
    with runtime.database.transaction() as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        state = copy.deepcopy(outer.state)
        state["bank"] = {"show": True, "current": 325, "record": 325, "totalPut": 325,
                         "reward": {row[0]: 0 for row in bindings.SOURCES.values()}}
        outer.state = state
    assert bank_collection(runtime, token)[Q28] == {"state": 0, "progress": []}
    with runtime.database.transaction() as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        state = copy.deepcopy(outer.state)
        state["collect"]["relic"][Q28] = claim
        outer.state = state
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == saved
    runtime.database.close()
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("claim", [
    {"state": 1, "progress": [1, 3]}, {"state": 0, "progress": [2, 3]},
    {"state": 0, "progress": [1, 4]}, {"state": 0, "progress": [1]},
])
def test_bank_collection_owned_counter_overclaims_rejected_without_startup_rewrite(bank_item_runtime, claim):
    runtime, token = bank_item_runtime
    configure(runtime, token, bank=True)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "bankPut", {}, "counter-put").status_code == 200
    assert bank_collection(runtime, token)[Q28] == {"state": 0, "progress": [1, 3]}
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as con:
        state = json.loads(con.execute("SELECT state FROM rlv2_topics WHERE account_id=1 AND topic_id='rogue_1'").fetchone()[0])
        state["collect"]["relic"][Q28] = claim
        con.execute("UPDATE rlv2_topics SET state=? WHERE account_id=1 AND topic_id='rogue_1'", (json.dumps(state),))
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("change", ["reward_ids", "item_conditions"])
def test_bank_collection_declared_binding_changes_cannot_silently_disable_capability(bank_item_runtime, change):
    runtime, _ = bank_item_runtime
    tables = copy.deepcopy(runtime.data.table("roguelike_topic_table"))
    detail = tables["details"]["rogue_1"]
    if change == "reward_ids":
        for row in detail["bankRewards"]:
            row["rewardId"] = "changed-" + row["rewardId"]
    else:
        for key in (R13, Q28):
            detail["items"][key]["unlockCondDesc"] = "changed condition"
    data = SimpleNamespace(manifest=runtime.data.manifest, table=lambda name: tables,
                           rogue_topics=runtime.data.rogue_topics, rogue_relic_archive=runtime.data.rogue_relic_archive)
    data.rogue_bank = FirstThemeBankRules(data)
    assert bindings.available(data)
    with pytest.raises(ValueError):
        bindings.FirstThemeBankItems(data)
