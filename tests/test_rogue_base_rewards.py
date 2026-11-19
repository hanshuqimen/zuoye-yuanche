"""Explicit ordinary base outcomes, mixed pools and full-run publication."""

import copy
import json
import random
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient
from test_rogue_battle_loot import configured, finish_new
from test_rogue_content_publication import source_path
from test_rogue_content_specs import wire
from test_rogue_floor_progress import journal, scene
from test_rogue_recruit_costs import R25
from test_rogue_settlement import complete
from test_roguelike_battle_start import begin, body
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_loot_plans import prepare
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.gamedata.rogue_battle_loot import (
    BASE_POLICY,
    CAPSULE_POLICY,
    POLICY,
    RESOURCE_POLICY,
    RelicGroups,
    admit_groups,
    compile_groups,
    loot,
)
from terralocal.server.gamedata.rogue_content_specs import BASE_REWARD_POLICY, compile_spec
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

pytest_plugins = ("test_rogue_battle_loot",)


def base_spec():
    return RelicGroups((), frozenset(), "Explicit ordinary base-only outcome; no drop weight claim", base_only=True)


def base_candidate():
    return {"id": "base-rewards", "weight": 1, "content": {
        "groups": [], "eligibility": [], "evidence": "Explicit ordinary outcome; no extra reward",
        "base_only": True}}


def normal_source(data):
    value = wire(data)
    value["policy"] = BASE_REWARD_POLICY
    for supply in value["supplies"]:
        supply.update(treasure=[], recreation=[])
    value["floors"][0] = asdict(Plan("zone_1", (Column(1, 1, (Entry("BATTLE_NORMAL", 1, "ordinary"),)),), 0))
    value["supplies"][0]["incident"] = []
    value["supplies"][0]["battle"] = [base_candidate()]
    # The shared battle role may contain ordinary-only outcomes. The middle
    # boss must retain its separately supplied extra-relic candidates.
    value["supplies"][2]["battle"].append(base_candidate())
    return json.loads(json.dumps(value))


def test_empty_extras_need_explicit_version_and_complete_currency_proof(cost_runtime):
    runtime, _ = cost_runtime
    with pytest.raises(ValueError):
        compile_groups(runtime.data, RelicGroups((), frozenset(), "Unspecified empty outcome"), at=1_800_000_000)
    value, digest = compile_groups(runtime.data, base_spec(), at=1_800_000_000)
    assert value["policy"] == BASE_POLICY and value["base_only"] is True
    assert value["groups"] == value["eligibility"] == [] and len(value["effects"]) == 64
    assert admit_groups(runtime.data, value) == (value, digest) and loot(value) == []
    for old in (POLICY, RESOURCE_POLICY, CAPSULE_POLICY):
        with pytest.raises(ValueError):
            admit_groups(runtime.data, value | {"policy": old})
    for change in ({"effects": "0" * 64}, {"base_only": False}, {"base_only": 1}):
        with pytest.raises(ValueError):
            admit_groups(runtime.data, value | change)
    detail = runtime.data.table("roguelike_topic_table")["details"]["rogue_1"]
    detail["gameConst"]["goldItemId"] = "missing-currency"
    with pytest.raises(ValueError):
        compile_groups(runtime.data, base_spec(), at=1_800_000_000)


@pytest.mark.parametrize("groups,eligibility,capsule,flag", [
    (((R25,),), frozenset({R25}), None, True),
    ((), frozenset({R25}), None, True),
    ((), frozenset(), "rogue_1_capsule_3", True),
    ((), frozenset(), None, 1),
])
def test_base_only_never_hides_extra_rewards_or_truthy_flags(cost_runtime, groups, eligibility, capsule, flag):
    runtime, _ = cost_runtime
    with pytest.raises(ValueError):
        compile_groups(runtime.data, RelicGroups(groups, eligibility, "Invalid base-only source", capsule, flag),
                       at=1_800_000_000)


@pytest.mark.parametrize("kind,stage", [("BATTLE_ELITE", "emergency"), ("BATTLE_BOSS", "boss")])
def test_ordinary_base_outcome_is_not_reused_for_emergency_or_boss(cost_runtime, kind, stage):
    runtime, token = cost_runtime
    configured(runtime, token, kind=kind, stage=stage, install=False)
    before, raw = current(runtime, token), rows(runtime.database.path)
    with pytest.raises(DomainError):
        with runtime.database.transaction() as session:
            prepare(Context(session, runtime.data, 1), {Point(0, 0): base_spec()})
    assert rows(runtime.database.path) == raw and current(runtime, token) == before


def test_base_ordinary_clear_claims_retry_and_restore_have_only_two_rewards(cost_runtime):
    runtime, token = cost_runtime
    configured(runtime, token, install=False)
    with runtime.database.transaction() as session:
        prepare(Context(session, runtime.data, 1), {Point(0, 0): base_spec()})
    before_relics = copy.deepcopy(current(runtime, token)["inventory"]["relic"])
    with TestClient(create_game_app(runtime)) as client:
        reward = finish_new(runtime, token, client)
        assert len(reward["rewards"]) == 2 and reward["earn"]["exp"] == 10
        before, raw = runtime.sync(token)["user"], rows(runtime.database.path)
        rejected = post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "no-extra")
        assert rejected.status_code == 400 and rows(runtime.database.path) == raw
        result = post(client, token, "chooseBattleReward", {"index": 0, "sub": 0}, "base-gold")
        assert result.status_code == 200
        after = runtime.sync(token)["user"]
        assert apply(before, result.json()["playerDataDelta"]) == after
        raw = rows(runtime.database.path)
        assert post(client, token, "chooseBattleReward", {"index": 0, "sub": 0}, "base-gold").json() == result.json()
        assert rows(runtime.database.path) == raw
        assert post(client, token, "chooseBattleReward", {"index": 0, "sub": 0}, "base-gold-new").status_code == 200
        assert current(runtime, token)["player"]["property"]["gold"] == after["rlv2"]["current"]["player"]["property"]["gold"]
        assert post(client, token, "chooseBattleReward", {"index": 1, "sub": 0}, "base-ticket").status_code == 200
        assert post(client, token, "closeRecruitTicket", {"id": "3"}, "base-ticket-close").status_code == 200
        assert post(client, token, "finishBattleReward", {}, "base-close").status_code == 200
        assert current(runtime, token)["inventory"]["relic"] == before_relics
    users, raw = runtime.sync(token)["user"], rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == users
        backup = BackupService(reopened)
        backup.restore(backup.create()["name"])
        assert reopened.sync(token)["user"] == users and rows(reopened.database.path) == raw
    finally:
        reopened.database.close()


def test_mixed_pool_is_kind_filtered_before_weighted_draw_and_never_falls_back(loot_boss_runtime):
    runtime, _ = loot_boss_runtime
    value = normal_source(runtime.data)
    before = random.getstate()
    spec = compile_spec(runtime.data, value, at=1_800_000_000)
    for seed in range(128):
        for kind in ("BATTLE_ELITE", "BATTLE_BOSS"):
            assert not spec.choose(3, kind, Point(0, 0), seed).base_only
    assert {spec.choose(3, "BATTLE_NORMAL", Point(0, 0), seed).base_only for seed in range(128)} == {False, True}
    assert random.getstate() == before
    value["supplies"][2]["battle"] = [base_candidate()]
    with pytest.raises(ValueError):
        compile_spec(runtime.data, value, at=1_800_000_000)


@pytest.mark.parametrize("policy", ["rogue1-explicit-normal-content-spec-v" + str(i) for i in range(1, 5)])
def test_old_recipe_versions_do_not_silently_admit_new_outcome(loot_boss_runtime, policy):
    runtime, _ = loot_boss_runtime
    value = normal_source(runtime.data)
    value["policy"] = policy
    if policy.endswith("v1"):
        for supply in value["supplies"]:
            supply.pop("treasure")
            supply.pop("recreation")
    elif policy.endswith("v2"):
        for supply in value["supplies"]:
            supply.pop("recreation")
    with pytest.raises(ValueError):
        compile_spec(runtime.data, value, at=1_800_000_000)


@pytest.fixture
def base_content_runtime(loot_boss_runtime):
    original, token = loot_boss_runtime
    source_path(original).write_text(json.dumps(normal_source(original.data)), "utf8")
    original.database.close()
    runtime = Runtime(original.settings)
    try:
        yield runtime, token
    finally:
        runtime.database.close()


def test_five_floor_publication_base_clear_middle_loot_and_final_settlement(base_content_runtime):
    runtime, token = base_content_runtime
    with TestClient(create_game_app(runtime)) as client:
        opened = post(client, token, "finishEvent", {}, "base-content-open")
        assert opened.status_code == 200, opened.text
        reward = finish_new(runtime, token, client, key="ordinary-base")
        assert len(reward["rewards"]) == 2
        assert post(client, token, "finishBattleReward", {}, "ordinary-close").status_code == 200
        assert scene(client, token, "second-floor").status_code == 200
        middle = finish_new(runtime, token, client, stage="ro1_b_1", key="middle")
        assert len(middle["rewards"]) == 3
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "middle-loot").status_code == 200
        assert post(client, token, "finishBattleReward", {}, "middle-close").status_code == 200
        assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, "shop-enter").status_code == 200
        assert post(client, token, "shopAction", {"buy": [], "recycle": [], "leave": 1}, "shop-leave").status_code == 200
        payload = body("ro1_b_6")
        payload["squad"]["slots"] = [{"charInstId": 1, "skillIndex": 1, "currentEquip": None}]
        started = begin(client, token, payload, key="default-boss")
        assert started.status_code == 200, started.text
        with runtime.database.transaction(write=False) as session:
            run = session.query(m.RogueTopicRun).one()
            hp = run.hp + runtime.data.rogue_initial.battle_temporary_hp
        trace = journal()
        trace["journal"]["squad"] = trace["journal"]["squad"][:1]
        trace["journal"]["metadata"]["stageId"] = "ro1_b_6"
        result = complete(client, token, started.json()["battleId"], trace, hp, "default-boss-finish", stageId="ro1_b_6")
        assert result.status_code == 200, result.text
        assert current(runtime, token)["player"]["pending"][0]["type"] == "GAME_SETTLE"
        assert post(client, token, "gameSettle", {}, "full-ack").status_code == 200
    final, raw = runtime.sync(token)["user"], rows(runtime.database.path)
    source_path(runtime).rename(source_path(runtime).with_suffix(".retained"))
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
        backup = BackupService(reopened)
        backup.restore(backup.create()["name"])
        assert reopened.sync(token)["user"] == final and rows(reopened.database.path) == raw
    finally:
        reopened.database.close()
