"""New supply dispatch/type/geometry contracts; authored data is not official."""

import copy
import json
import random
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_rogue_base_rewards import normal_source
from test_roguelike_initial import current, post
from test_roguelike_map import assert_reachability
from test_roguelike_map import map_data as map_data
from test_roguelike_state import rows

from terralocal.server.domain import rogue_shops
from terralocal.server.domain.rogue_map import (
    DISTINCT_POLICY,
    LEGACY_POLICY,
    POLICY,
    Column,
    Entry,
    Plan,
    Point,
    generate,
)
from terralocal.server.gamedata import rogue_default
from terralocal.server.gamedata.repository import canonical
from terralocal.server.gamedata.rogue_content_specs import BASE_REWARD_POLICY, TYPED_POLICY, compile_spec
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

pytest_plugins = ("test_rogue_battle_loot",)


def typed_source(data):
    value = normal_source(data)
    value["policy"] = TYPED_POLICY
    for supply in value["supplies"]:
        for entry in supply["battle"]:
            entry["content"]["kinds"] = ["BATTLE_NORMAL"] if entry["content"].get("base_only") else ["BATTLE_BOSS"]
    return value


def test_column_battles_are_distinct_but_nonbattle_types_may_repeat(map_data):
    plan = Plan("floor", (Column(3, 3, (Entry("BATTLE_NORMAL", 500, "ordinary"), Entry("INCIDENT", 1))),), 0)
    state = random.getstate()
    for seed in range(64):
        graph = generate(map_data, plan, seed, policy=DISTINCT_POLICY)
        assert sum(n.stage == "ordinary" for n in graph.nodes) == 1
        assert len(graph.nodes) == 3
        assert_reachability(graph)
        assert generate(map_data, plan, seed, policy=DISTINCT_POLICY) == graph
    assert state == random.getstate()


def test_distinct_battle_exhaustion_rejects_without_retry_or_old_policy_changes(map_data):
    plan = Plan("floor", (Column(2, 2, (Entry("BATTLE_NORMAL", 1, "ordinary"),)),), 0)
    with pytest.raises(ValueError):
        generate(map_data, plan, 1, policy=DISTINCT_POLICY)
    for policy in (LEGACY_POLICY, POLICY):
        assert [n.stage for n in generate(map_data, plan, 1, policy=policy).nodes] == ["ordinary", "ordinary"]


def test_typed_rewards_do_not_leak_a_boss_menu_into_ordinary_battles(loot_boss_runtime):
    runtime, _ = loot_boss_runtime
    spec = compile_spec(runtime.data, typed_source(runtime.data), at=1_800_000_000)
    for seed in range(64):
        assert spec.choose(3, "BATTLE_NORMAL", Point(0, 0), seed).base_only
        boss = spec.choose(3, "BATTLE_BOSS", Point(0, 0), seed)
        assert not boss.base_only and boss.battle_kinds == {"BATTLE_BOSS"}
    with pytest.raises(ValueError):
        spec.choose(3, "BATTLE_ELITE", Point(0, 0), 0)


@pytest.mark.parametrize("kinds", [None, [], [True], ["INCIDENT"], ["BATTLE_BOSS", "BATTLE_BOSS"], "BATTLE_BOSS"])
def test_bad_or_ambiguous_kind_list_is_rejected_before_save_writes(loot_boss_runtime, kinds):
    runtime, _ = loot_boss_runtime
    value = typed_source(runtime.data)
    value["supplies"][2]["battle"][0]["content"]["kinds"] = kinds
    saved = rows(runtime.database.path)
    with pytest.raises(ValueError):
        compile_spec(runtime.data, value, at=1_800_000_000)
    assert rows(runtime.database.path) == saved


def test_missing_kind_supply_and_base_only_boss_are_not_automatic_success(loot_boss_runtime):
    runtime, _ = loot_boss_runtime
    value = typed_source(runtime.data)
    value["supplies"][2]["battle"] = [value["supplies"][2]["battle"][-1]]
    with pytest.raises(ValueError):
        compile_spec(runtime.data, value, at=1_800_000_000)
    value["supplies"][2]["battle"][0]["content"]["kinds"] = ["BATTLE_BOSS"]
    with pytest.raises(ValueError):
        compile_spec(runtime.data, value, at=1_800_000_000)


def test_v5_cannot_silently_gain_v6_kind_semantics(loot_boss_runtime):
    runtime, _ = loot_boss_runtime
    value = typed_source(runtime.data)
    value["policy"] = BASE_REWARD_POLICY
    with pytest.raises(ValueError):
        compile_spec(runtime.data, value, at=1_800_000_000)


def test_unrecognized_dataset_is_not_given_frozen_default_supply(loot_boss_runtime):
    runtime, _ = loot_boss_runtime
    with runtime.database.transaction(write=False) as session:
        run = session.query(m.RogueTopicRun).one()
        assert rogue_default.source(runtime.data, run, frozenset()) is None


def open_run(runtime, token, key):
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "finishEvent", {}, key)
        assert result.status_code == 200, result.text
        return result.json()


def test_default_dispatch_is_atomic_once_and_frozen_across_restart_and_backup(loot_boss_runtime, monkeypatch):
    runtime, token = loot_boss_runtime
    calls = []
    def authored_default(data, run, owned):
        calls.append((run.id, run.account_id, owned))
        assert owned == {run.band_id}
        return typed_source(data)
    monkeypatch.setattr(rogue_default, "source", authored_default)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(lambda i: open_run(runtime, token, "typed-open-" + str(i)), range(2)))) == 2
    assert len(calls) == 1
    assert current(runtime, token)["player"]["cursor"]["zone"] == 1
    with runtime.database.transaction(write=False) as session:
        draft = session.query(m.RogueMapDraft).one()
        assert draft.plan["source"]["policy"] == TYPED_POLICY and len(draft.graph["zones"]) == 5
    before, raw = runtime.sync(token)["user"], rows(runtime.database.path)
    runtime.database.close()
    monkeypatch.setattr(rogue_default, "source", lambda *args: pytest.fail("saved run must not replan"))
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == before
        backup = BackupService(reopened)
        saved = backup.create()
        backup.restore(saved["name"])
        assert reopened.sync(token)["user"] == before and rows(reopened.database.path) == raw
    finally:
        reopened.database.close()


def test_explicit_config_precedes_default_and_failing_default_publication_rolls_back(loot_boss_runtime, monkeypatch):
    runtime, token = loot_boss_runtime
    value = typed_source(runtime.data)
    runtime.data.rogue_content_source = canonical(value)
    monkeypatch.setattr(rogue_default, "source", lambda *args: pytest.fail("explicit source owns this run"))
    before = rows(runtime.database.path)
    def broken(*args, **kwargs):
        raise RuntimeError("authored provider fault")
    original = rogue_shops.prepare
    monkeypatch.setattr(rogue_shops, "prepare", broken)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "finishEvent", {}, "typed-fault").status_code == 500
    assert rows(runtime.database.path) == before
    monkeypatch.setattr(rogue_shops, "prepare", original)
    open_run(runtime, token, "typed-recovered")
    with runtime.database.transaction(write=False) as session:
        saved = session.query(m.RogueMapDraft).one()
        assert json.loads(canonical(saved.plan["source"])) == copy.deepcopy(value)
