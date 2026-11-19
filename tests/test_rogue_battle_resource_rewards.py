"""Source-specific resource effects; explicit QA eligibility, no drop rates."""

import copy
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_rogue_battle_loot import configured, finish_new
from test_rogue_gold_relics import AMOUNTS as GOLD
from test_rogue_gold_relics import R11, R12, R13
from test_rogue_recruit_costs import R25
from test_rogue_resource_relics import AMOUNTS as RESOURCE
from test_rogue_resource_relics import Q26, Q28
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_loot_plans
from terralocal.server.gamedata.rogue_battle_loot import (
    POLICY,
    RESOURCE_POLICY,
    RelicGroups,
    admit_groups,
    compile_groups,
    gold_after_relic,
)
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

pytest_plugins = ("test_rogue_resource_relics", "test_rogue_battle_loot")


@pytest.mark.parametrize("item", [*GOLD, *RESOURCE])
def test_each_complete_effect_claim_delta_retry_replay_and_backup(resource_runtime, item):
    runtime, token = resource_runtime
    configured(runtime, token, groups=((item,),))
    with runtime.database.transaction(write=False) as session:
        plan = session.query(m.RogueBattleLootPlan).one()
        assert plan.policy_version == plan.spec["policy"] == RESOURCE_POLICY
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
        before = runtime.sync(token)["user"]
        old = current(runtime, token)["player"]["property"]["gold"]
        reply = post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "resource-claim")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        state = current(runtime, token)
        assert state["player"]["property"]["gold"] == old + GOLD.get(item, 0)
        inventory = list(state["inventory"]["relic"].values())
        assert inventory[-1]["id"] == item and inventory[-1]["layer"] == 0
        saved = rows(runtime.database.path)
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "resource-claim").json() == reply.json()
        assert rows(runtime.database.path) == saved
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "resource-retry").status_code == 200
        assert current(runtime, token)["player"]["property"]["gold"] == old + GOLD.get(item, 0)
        assert post(client, token, "finishBattleReward", {}, "resource-close").status_code == 200
    expected, saved = runtime.sync(token)["user"], rows(runtime.database.path)
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected
        backups = BackupService(reopened)
        backups.restore(backups.create()["name"])
        assert reopened.sync(token)["user"] == expected and rows(reopened.database.path) == saved
    finally:
        reopened.database.close()


def test_legacy_group_digest_and_plan_remain_v1_new_effects_cannot_masquerade_as_v1(resource_runtime):
    runtime, token = resource_runtime
    old, old_hash = compile_groups(runtime.data, RelicGroups(((R25,),), frozenset({R25}), "Explicit QA"), at=1_800_000_000)
    assert old["policy"] == POLICY and admit_groups(runtime.data, old) == (old, old_hash)
    value, _ = compile_groups(runtime.data, RelicGroups(((R11, Q28),), frozenset({R11, Q28}), "Explicit QA"), at=1_800_000_000)
    assert value["policy"] == RESOURCE_POLICY
    with pytest.raises(ValueError):
        admit_groups(runtime.data, value | {"policy": POLICY})
    with pytest.raises(ValueError):
        admit_groups(runtime.data, old | {"policy": RESOURCE_POLICY})
    configured(runtime, token, groups=((R25,),))
    with runtime.database.transaction(write=False) as session:
        plan = session.query(m.RogueBattleLootPlan).one()
        assert plan.policy_version == POLICY


@pytest.mark.parametrize("first", ["gold", "relic"])
def test_standard_gold_and_immediate_relic_are_independent_of_claim_order(resource_runtime, first):
    runtime, token = resource_runtime
    configured(runtime, token, groups=((R13,),))
    with TestClient(create_game_app(runtime)) as client:
        reward = finish_new(runtime, token, client)
        gold = current(runtime, token)["player"]["property"]["gold"]
        amount = reward["rewards"][0]["items"][0]["count"]
        for index in ((0, 2) if first == "gold" else (2, 0)):
            result = post(client, token, "chooseBattleReward", {"index": index, "sub": 0}, "order-" + str(index))
            assert result.status_code == 200, result.text
        assert current(runtime, token)["player"]["property"]["gold"] == gold + amount + 25
        before = rows(runtime.database.path)
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "retry-gold-relic").status_code == 200
        assert current(runtime, token)["player"]["property"]["gold"] == gold + amount + 25
        assert rows(runtime.database.path)["rlv2_relics"] == before["rlv2_relics"]


def test_mixed_resource_groups_claim_each_only_once_and_keep_native_base_layer(resource_runtime):
    runtime, token = resource_runtime
    configured(runtime, token, groups=((Q28,), (R13, R11)))
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
        before = current(runtime, token)["player"]["property"]["gold"]
        for index in (2, 3):
            result = post(client, token, "chooseBattleReward", {"index": index, "sub": 0}, "mixed-" + str(index))
            assert result.status_code == 200, result.text
        state = current(runtime, token)
        assert state["player"]["property"]["gold"] == before + 25
        assert {r["id"]: r["layer"] for r in state["inventory"]["relic"].values() if r["id"] in {Q28, R13}} == {Q28: 0, R13: 0}
        assert runtime.data.rogue_resource_relics.require(Q28).layers(before + 25) == (before + 25) // 5
        saved = rows(runtime.database.path)
        assert post(client, token, "chooseBattleReward", {"index": 3, "sub": 1}, "different").status_code == 409
        assert rows(runtime.database.path) == saved


def test_failed_commit_does_not_grant_gold_inventory_discovery_or_receipt(resource_runtime):
    runtime, token = resource_runtime
    configured(runtime, token, groups=((R13,),))
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
    # A DB trigger is more direct than relying on weak ORM identity-map
    # references: the provider flush must fail after the award was staged.
    import sqlite3

    with sqlite3.connect(runtime.database.path) as con:
        con.execute("CREATE TRIGGER reject_relic BEFORE INSERT ON rlv2_relics WHEN NEW.item_id='rogue_1_relic_r13' BEGIN SELECT RAISE(ABORT,'QA resource claim'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "rollback").status_code == 500
    assert rows(runtime.database.path) == saved


def test_concurrent_new_sequences_grant_one_relic_and_one_immediate_reward(resource_runtime):
    runtime, token = resource_runtime
    configured(runtime, token, groups=((R12,),))
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
    gold = current(runtime, token)["player"]["property"]["gold"]
    def choose(number):
        with TestClient(create_game_app(runtime)) as client:
            return post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "concurrent-" + str(number)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(choose, (1, 2))) == [200, 200]
    assert current(runtime, token)["player"]["property"]["gold"] == gold + 18
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueRunRelic).filter_by(item_id=R12).count() == 1


def test_resource_limit_failure_returns409_without_awarding_any_part(resource_runtime, monkeypatch):
    runtime, token = resource_runtime
    configured(runtime, token, groups=((R13,),))
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
    from terralocal.server.gamedata import rogue_battle_loot

    def overflow(*args):
        raise ValueError("injected exact resource limit")
    monkeypatch.setattr(rogue_battle_loot, "gold_after_relic", overflow)
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "overflow")
        assert result.status_code == 409 and result.json()["error"]["code"] == "ROGUE_REWARD_RESOURCE_LIMIT"
    assert rows(runtime.database.path) == saved


@pytest.mark.parametrize("damage", ["amount", "base-layer", "plan-version", "spec-version"])
def test_tampered_resource_claim_or_new_plan_is_rejected_before_startup_writes(resource_runtime, damage):
    runtime, token = resource_runtime
    configured(runtime, token, groups=((R13,),))
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "claim").status_code == 200
    with runtime.database.transaction() as session:
        if damage == "amount":
            session.query(m.RogueTopicRun).one().gold += 1
        elif damage == "base-layer":
            session.query(m.RogueRunRelic).filter_by(item_id=R13).one().layer = 5
        else:
            plan = session.query(m.RogueBattleLootPlan).one()
            if damage == "plan-version":
                plan.policy_version = POLICY
                plan.rule_hash = rogue_loot_plans.binding(session.query(m.RogueTopicRun).one(), plan)
            else:
                plan.spec = plan.spec | {"policy": POLICY}
                plan.rule_hash = rogue_loot_plans.binding(session.query(m.RogueTopicRun).one(), plan)
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("item", [R11, R12, R13])
def test_immediate_gold_limit_is_exact_and_never_wraps(resource_runtime, item):
    runtime, _ = resource_runtime
    amount = GOLD[item]
    assert gold_after_relic(runtime.data, item, 2**31 - 1 - amount) == 2**31 - 1
    for value in (2**31 - amount, 2**31, -1, True):
        with pytest.raises(ValueError):
            gold_after_relic(runtime.data, item, value)
    assert gold_after_relic(runtime.data, Q28, 30) == 30


def test_explicit_profile_can_compile_mixed_resource_rewards_without_enabling_a_default_pool(resource_runtime):
    runtime, _ = resource_runtime
    spec = RelicGroups(((R11, Q26), (R13, Q28)), frozenset({R11, Q26, R13, Q28}), "Explicit QA, not a natural pool")
    saved, digest = compile_groups(runtime.data, spec, at=1_800_000_000)
    assert admit_groups(runtime.data, copy.deepcopy(saved)) == (saved, digest)
    assert runtime.rogue_content_source is None
