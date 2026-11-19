"""Trusted configured publication; synthetic recipes, never official weights."""

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_rogue_battle_loot import finish_new
from test_rogue_content_specs import wire
from test_rogue_floor_progress import journal, scene
from test_rogue_settlement import complete
from test_roguelike_battle_start import begin, body
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_shops, rogue_visits
from terralocal.server.domain.rogue_floors import CONTENT_POLICY
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

pytest_plugins = ("test_rogue_battle_loot",)


def source_path(runtime):
    return runtime.settings.data_dir / "rogue_content.json"


@pytest.fixture
def content_runtime(loot_boss_runtime):
    original, token = loot_boss_runtime
    source_path(original).write_bytes(json.dumps(wire(original.data)).encode())
    original.database.close()
    runtime = Runtime(original.settings)
    try:
        yield runtime, token
    finally:
        runtime.database.close()


def activate(runtime, token, key="content-open"):
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "finishEvent", {}, key)
        assert result.status_code == 200, result.text
        return result


def test_open_publishes_every_floor_atomically_and_retry_never_rerolls(content_runtime):
    runtime, token = content_runtime
    before = runtime.sync(token)["user"]
    reply = activate(runtime, token)
    after = runtime.sync(token)["user"]
    assert apply(before, reply.json()["playerDataDelta"]) == after
    with runtime.database.transaction(write=False) as session:
        draft = session.query(m.RogueMapDraft).one()
        run = session.query(m.RogueTopicRun).one()
        assert draft.policy_version == CONTENT_POLICY and run.state == "MAP_READY"
        assert len(draft.graph["zones"]) == 5 and len(draft.plan["assignments"]) == 4
        assert session.query(m.RogueSceneVisit).count() == 2
        assert session.query(m.RogueShopVisit).count() == 1
        assert session.query(m.RogueBattleLootPlan).count() == 1
        assert session.query(m.RogueFloorCursor).one().zone_index == 1
        assert session.query(m.RogueRunRelic).count() == 1
    saved = rows(runtime.database.path)
    assert activate(runtime, token).json() == reply.json()
    assert rows(runtime.database.path) == saved
    activate(runtime, token, "new-sequence")
    now = rows(runtime.database.path)
    assert {k for k, value in saved.items() if now[k] != value} == {"receipts", "player_profiles"}


@pytest.mark.parametrize("provider", ["scene", "shop", "final-check"])
def test_provider_failure_rolls_back_activation_every_binding_cursor_and_receipt(content_runtime, monkeypatch, provider):
    runtime, token = content_runtime
    def broken(*args, **kwargs):
        raise RuntimeError("injected content publication failure")
    if provider == "final-check":
        from terralocal.server.domain import rogue_content
        original = rogue_content.check_bindings
        def last_check(*args, **kwargs):
            if not kwargs.get("partial", False):
                broken()
            return original(*args, **kwargs)
        monkeypatch.setattr(rogue_content, "check_bindings", last_check)
    else:
        monkeypatch.setattr(rogue_visits if provider == "scene" else rogue_shops, "prepare", broken)
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "finishEvent", {}, "injected").status_code == 500
    assert rows(runtime.database.path) == saved


def test_simultaneous_opening_publishes_one_graph_and_one_set_of_bindings(content_runtime):
    runtime, token = content_runtime
    def open_one(index):
        return activate(runtime, token, "concurrent-" + str(index)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(open_one, (1, 2))) == [200, 200]
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueMapDraft).count() == session.query(m.RogueFloorCursor).count() == 1
        assert session.query(m.RogueSceneVisit).count() == 2
        assert session.query(m.RogueBattleLootPlan).count() == 1


def test_saved_recipe_survives_config_removal_restart_and_backup(content_runtime):
    runtime, token = content_runtime
    activate(runtime, token)
    source_path(runtime).unlink()
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        saved = rows(reopened.database.path)
        before = reopened.sync(token)["user"]
        backups = BackupService(reopened)
        info = backups.create()
        assert info["rogue_content_hash"] is None
        backups.restore(info["name"])
        assert reopened.sync(token)["user"] == before and rows(reopened.database.path) == saved
        with TestClient(create_game_app(reopened)) as client:
            assert scene(client, token, "floor1").status_code == 200
            assert current(reopened, token)["player"]["cursor"]["zone"] == 2
            assert scene(client, token, "floor2").status_code == 200
            assert current(reopened, token)["player"]["cursor"]["zone"] == 3
            reward = finish_new(reopened, token, client, stage="ro1_b_1")
            assert reward["rewards"][2]["items"]
            assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "middle-claim").status_code == 200
            assert post(client, token, "finishBattleReward", {}, "middle-close").status_code == 200
            assert current(reopened, token)["player"]["cursor"]["zone"] == 4
            assert post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, "shop-enter").status_code == 200
            left = post(client, token, "shopAction", {"buy": [], "recycle": [], "leave": 1}, "shop-leave")
            assert left.status_code == 200, left.text
            assert current(reopened, token)["player"]["cursor"]["zone"] == 5
            payload = body("ro1_b_6")
            payload["squad"]["slots"] = [{"charInstId": 1, "skillIndex": 1, "currentEquip": None}]
            started = begin(client, token, payload, key="final")
            assert started.status_code == 200, started.text
            with reopened.database.transaction(write=False) as session:
                hp = session.query(m.RogueTopicRun).one().hp + reopened.data.rogue_initial.battle_temporary_hp
            trace = journal()
            trace["journal"]["squad"] = trace["journal"]["squad"][:1]
            trace["journal"]["metadata"]["stageId"] = "ro1_b_6"
            result = complete(client, token, started.json()["battleId"], trace, hp, "final-finish", stageId="ro1_b_6")
            assert result.status_code == 200, result.text
            assert current(reopened, token)["player"]["pending"][0]["type"] == "GAME_SETTLE"
            assert post(client, token, "gameSettle", {}, "final-ack").status_code == 200
    finally:
        reopened.database.close()


@pytest.mark.parametrize("damage", ["scene", "shop", "battle", "all", "assignment", "source", "cursor"])
def test_missing_or_changed_persisted_content_is_rejected_before_startup_writes(content_runtime, damage):
    runtime, token = content_runtime
    activate(runtime, token)
    with runtime.database.transaction() as session:
        if damage in ("scene", "shop", "battle", "all"):
            entities = {"scene": m.RogueSceneVisit, "shop": m.RogueShopVisit, "battle": m.RogueBattleLootPlan}
            for entity in entities.values() if damage == "all" else (entities[damage],):
                session.query(entity).delete()
        elif damage == "cursor":
            session.query(m.RogueFloorCursor).delete()
        else:
            draft = session.query(m.RogueMapDraft).one()
            value = copy.deepcopy(draft.plan)
            if damage == "assignment":
                value["assignments"][0]["candidate"] = "different-candidate"
            else:
                value["source"]["supplies"][0]["incident"][0]["content"]["program"] = "missing"
            draft.plan = value
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("damage", ["duplicate-json", "oversized", "pool", "data"])
def test_bad_trusted_configuration_is_rejected_without_touching_existing_database(content_runtime, damage):
    runtime, _ = content_runtime
    value = wire(runtime.data)
    if damage == "pool":
        value["supplies"][0]["incident"] = []
    elif damage == "data":
        value["gamedata_hash"] = "0" * 64
    source = json.dumps(value).encode()
    if damage == "duplicate-json":
        source = source[:-1] + b',"schema":1}'
    elif damage == "oversized":
        source = b" " * 1_048_577
    source_path(runtime).write_bytes(source)
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def test_backup_rejects_changed_new_run_configuration_before_replacing_save(content_runtime):
    runtime, token = content_runtime
    activate(runtime, token)
    backups = BackupService(runtime)
    info = backups.create()
    assert info["rogue_content_hash"]
    runtime.rogue_content_source = None
    before = rows(runtime.database.path)
    with pytest.raises(ValueError, match="探索内容方案"):
        backups.restore(info["name"])
    assert rows(runtime.database.path) == before


def test_unconfigured_opening_keeps_original_fail_closed_behavior(loot_boss_runtime):
    runtime, token = loot_boss_runtime
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "finishEvent", {}, "no-source")
        assert result.status_code == 503 and result.json()["error"]["code"] == "ROGUE_MAP_NOT_PREPARED"
    assert rows(runtime.database.path) == before


def test_resource_exhaustion_rejects_opening_before_creating_any_map(loot_boss_runtime):
    runtime, token = loot_boss_runtime
    value = wire(runtime.data)
    # Two middle-floor battles but only one nonstack reward candidate. The
    # complete program must be rejected before exposing the first node.
    battle = {"minimum": 1, "maximum": 1, "pool": [
        {"kind": "BATTLE_NORMAL", "weight": 1, "stage": "ordinary"}]}
    value["floors"][0]["columns"] = [battle, copy.deepcopy(battle)]
    value["supplies"][0]["battle"] = copy.deepcopy(value["supplies"][2]["battle"][:1])
    from terralocal.server.gamedata.rogue_content_specs import compile_spec

    assert len(compile_spec(runtime.data, value, at=1_800_000_000).generate(runtime.data, 12)[0].nodes) == 2
    # Fixture placement is intentionally explicit for this new floor binding.
    runtime.data.rogue_content_source = json.dumps(value).encode()
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "finishEvent", {}, "exhausted")
        assert result.status_code == 503 and result.json()["error"]["code"] == "ROGUE_CONTENT_INCOMPATIBLE"
    assert rows(runtime.database.path) == before
