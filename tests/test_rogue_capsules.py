"""Authored capsule supply, causal node effects and full restore; no native battle."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import test_rogue_training as training_fixture
from fastapi.testclient import TestClient
from test_rogue_battle_loot import finish_new
from test_rogue_training import choice, move
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_capsules import History
from terralocal.server.domain.rogue_loot_plans import prepare
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_settlement import claim, state_in_session
from terralocal.server.domain.rogue_visits import prepare as save_scenes
from terralocal.server.gamedata import rogue_capsules as rules
from terralocal.server.gamedata import rogue_events
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_battle_loot import RelicGroups, admit_groups, compile_groups
from terralocal.server.gamedata.rogue_content_specs import candidate
from terralocal.server.gamedata.rogue_events import Branch, Delta, EventSpec, Frame
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

pytest_plugins = ("test_rogue_battle_loot",)
C9, C10 = "rogue_1_capsule_9", "rogue_1_capsule_10"


@pytest.fixture
def capsule_runtime(monkeypatch, request):
    original = training_fixture.import_data

    def imported(folder, cache):
        path = folder / "roguelike_topic_table.json"
        table = json.loads(path.read_bytes())
        detail = table["details"]["rogue_1"]
        sources = {}
        for key, hp, gold in ((C9, 1, 0), (C10, 0, 3)):
            item = {"id": key, "type": "CAPSULE", "subType": "NONE", "name": "Authored capsule",
                    "usage": "Authored fixture only", "description": "No official data"}
            capsule = {"itemId": key, "maskType": "INCIDENT", "innerColor": "ffffff"}
            detail["items"][key] = item
            detail.setdefault("capsuleDict", {})[key] = capsule
            sources[key] = fingerprint(item), fingerprint(capsule), hp, gold
        monkeypatch.setattr(rules, "SOURCES", sources)
        for key in ("scene_gold_enter", "scene_gold_1"):
            detail["choiceScenes"][key] = {"id": key, "title": "Authored gold scene",
                "description": "Authored capsule trigger fixture", "useHiddenMusic": False}
        detail["choices"]["choice_gold"] = {"id": "choice_gold", "type": "TRADE",
            "nextSceneId": "scene_gold_1", "title": "Authored gain", "isHiddenChoice": False,
            "forceShowWhenOnlyLeave": False, "sortId": 0}
        path.write_text(json.dumps(table), "utf8")
        return original(folder, cache)

    def programs(catalog):
        spec = EventSpec("rogue1-fixed-gold", "scene_gold_enter", (
            Frame("scene_gold_enter", (Branch("choice_gold", catalog.choices["choice_gold"].digest, Delta(gold=5)),)),
            Frame("scene_gold_1", (Branch("choice_leave", catalog.choices["choice_leave"].digest, Delta()),))),
            "Authored capsule trigger fixture; no natural pool")
        return {spec.id: catalog.compile(spec)}

    monkeypatch.setattr(rogue_events, "fixed_programs", programs)
    monkeypatch.setattr(training_fixture, "import_data", imported)
    return request.getfixturevalue("cost_runtime")


def configured(runtime, token, capsules=(C9,)):
    kinds = ["BATTLE_NORMAL"] * len(capsules) + ["INCIDENT", "INCIDENT"]
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), Plan("zone_1", tuple(
            Column(1, 1, (Entry(kind, 1, "ordinary" if kind == "BATTLE_NORMAL" else None),))
            for kind in kinds), 0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "capsule-map").status_code == 200
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        save_scenes(ctx, {Point(x, 0): "rogue1-fixed-gold" for x in range(len(capsules), len(kinds))})
        prepare(ctx, {Point(i, 0): RelicGroups((), frozenset(), "Authored capsule supply", key)
                      for i, key in enumerate(capsules)})


@pytest.mark.parametrize("item,hp,gold", [(C9, 1, 0), (C10, 0, 3)])
def test_capsule_claim_trigger_once_delta_cold_restart_and_backup(capsule_runtime, item, hp, gold):
    runtime, token = capsule_runtime
    configured(runtime, token, (item,))
    with TestClient(create_game_app(runtime)) as client:
        reward = finish_new(runtime, token, client)
        assert reward["rewards"][2]["items"] == [{"id": item, "count": 1, "sub": 0}]
        before = runtime.sync(token)["user"]
        result = post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "capsule")
        assert result.status_code == 200, result.text
        acquired = runtime.sync(token)["user"]
        assert apply(before, result.json()["playerDataDelta"]) == acquired
        wire = current(runtime, token)["buff"]["capsule"]
        assert wire["id"] == item and wire["active"] is False
        assert acquired["rlv2"]["outer"]["rogue_1"]["collect"]["capsule"][item]["state"] == 2
        saved = rows(runtime.database.path)
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "capsule").json() == result.json()
        assert rows(runtime.database.path) == saved
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "capsule-new-seq").status_code == 200
        assert post(client, token, "finishBattleReward", {}, "close").status_code == 200
        prop = current(runtime, token)["player"]["property"]
        entry = move(client, token, 1, "incident")
        assert entry.status_code == 200, entry.text
        state = current(runtime, token)
        assert state["buff"]["capsule"] == wire | {"active": True}
        assert state["player"]["property"]["hp"]["current"] == prop["hp"]["current"] + hp
        assert state["player"]["property"]["gold"] == prop["gold"] + gold
        reopened = Runtime(runtime.settings)
        try:
            assert current(reopened, token) == state
        finally:
            reopened.database.close()
        assert move(client, token, 1, "incident-retry").status_code == 200
        assert current(runtime, token) == state
        assert choice(client, token, "choice_gold", "gold").status_code == 200
        assert choice(client, token, "choice_leave", "leave").status_code == 200
        assert current(runtime, token)["buff"]["capsule"] is None
        next_before = current(runtime, token)["player"]["property"]
        assert move(client, token, 2, "second-node").status_code == 200
        assert current(runtime, token)["player"]["property"] == next_before
    users, raw = copy.deepcopy(runtime.sync(token)["user"]), rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == users
        backup = BackupService(reopened)
        backup.restore(backup.create()["name"])
        assert reopened.sync(token)["user"] == users and rows(runtime.database.path) == raw
    finally:
        reopened.database.close()


def test_replacement_preserves_both_discoveries_and_only_latest_effect(capsule_runtime):
    runtime, token = capsule_runtime
    configured(runtime, token, (C9, C10))
    with TestClient(create_game_app(runtime)) as client:
        for x in range(2):
            finish_new(runtime, token, client, key=f"battle{x}", x=x)
            assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, f"capsule{x}").status_code == 200
            assert post(client, token, "finishBattleReward", {}, f"close{x}").status_code == 200
        prop = current(runtime, token)["player"]["property"]
        assert move(client, token, 2, "activate").status_code == 200
        state = current(runtime, token)
        assert state["player"]["property"]["hp"] == prop["hp"]
        assert state["player"]["property"]["gold"] == prop["gold"] + 3
        assert state["buff"]["capsule"]["id"] == C10
        collect = runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["capsule"]
        assert all(collect[k]["state"] == 2 for k in (C9, C10))
        with runtime.database.transaction(write=False) as session:
            run = session.query(m.RogueTopicRun).one()
            tickets = session.query(m.RogueRunTicket).order_by(m.RogueRunTicket.ordinal).all()
            history = state_in_session(Context(session, runtime.data, 1), run, tickets).capsule_grants
            assert [g.item_id for g in history] == [C9, C10]


def test_unclaimed_capsule_is_forfeited_and_failed_claim_rolls_back(capsule_runtime):
    runtime, token = capsule_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
        before, raw = runtime.sync(token)["user"], rows(runtime.database.path)
        def fail(ctx):
            claim(ctx, 2, 0)
            raise DomainError("INJECTED", "rollback capsule")
        with pytest.raises(DomainError, match="rollback capsule"):
            runtime.mutate(token, None, "rollback", "qa-capsule", {}, fail)
        assert runtime.sync(token)["user"] == before and rows(runtime.database.path) == raw
        assert post(client, token, "finishBattleReward", {}, "forfeit").status_code == 200
        assert current(runtime, token)["buff"]["capsule"] is None
        assert move(client, token, 1, "no-effect").status_code == 200
        assert current(runtime, token)["buff"]["capsule"] is None


def test_wrong_definition_red_capsule_and_tampered_saved_proof_are_rejected(capsule_runtime):
    runtime, _ = capsule_runtime
    value, _ = compile_groups(runtime.data, RelicGroups((), frozenset(), "Authored source", C9), at=1_800_000_000)
    assert admit_groups(runtime.data, value)[0] == value
    for change in ({"capsule": {"id": C10, "rule": value["capsule"]["rule"]}}, {"effects": "bad"},
                   {"policy": "rogue1-explicit-battle-relic-groups-v1"}):
        with pytest.raises(ValueError):
            admit_groups(runtime.data, value | change)
    with pytest.raises(ValueError):
        compile_groups(runtime.data, RelicGroups((), frozenset(), "Wrong grade/source", "rogue_1_capsule_26"), at=1_800_000_000)
    detail = runtime.data.table("roguelike_topic_table")["details"]["rogue_1"]
    detail["capsuleDict"][C9]["maskType"] = "REST"
    with pytest.raises(ValueError):
        rules.require(runtime.data, C9, at=1_800_000_000)


def test_untriggered_capsule_expires_at_floor_boundary_without_losing_history(capsule_runtime):
    runtime, _ = capsule_runtime
    run = SimpleNamespace(id="run", account_id=1, topic_id="rogue_1", mode="NORMAL", grade=0,
                          created_at=1_800_000_000, ended_at=None)
    battle = SimpleNamespace(id="battle", run_id="run", account_id=1, ended_at=run.created_at, zone_index=1)
    history = History(runtime.data, run)
    history.acquire(battle, 2, C9, run.created_at)
    history.floor(2)
    assert history.wire() is None and [g.item_id for g in history.grants] == [C9]


def test_capsule_offer_requires_a_reachable_trigger_on_its_own_floor(capsule_runtime):
    runtime, token = capsule_runtime
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), Plan("zone_1", (
            Column(1, 1, (Entry("BATTLE_NORMAL", 1, "ordinary"),)),
            Column(1, 1, (Entry("SHOP", 1),))), 0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "map-no-trigger").status_code == 200
    before = rows(runtime.database.path)
    with pytest.raises(DomainError):
        with runtime.database.transaction() as session:
            prepare(Context(session, runtime.data, 1), {Point(0, 0): RelicGroups((), frozenset(), "QA", C9)})
    assert rows(runtime.database.path) == before


def test_two_runtimes_cannot_duplicate_the_same_capsule_receipt(capsule_runtime):
    runtime, token = capsule_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
    other = Runtime(runtime.settings)
    try:
        def take(pair):
            service, seq = pair
            return service.mutate(token, None, seq, "qa-capsule", {"index": 2, "sub": 0},
                                  lambda ctx: claim(ctx, 2, 0))
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(take, ((runtime, "a"), (other, "b"))))
        assert all(r["result"] == 0 for r in results)
        with runtime.database.transaction(write=False) as session:
            run = session.query(m.RogueTopicRun).one()
            tickets = session.query(m.RogueRunTicket).order_by(m.RogueRunTicket.ordinal).all()
            assert len(state_in_session(Context(session, runtime.data, 1), run, tickets).capsule_grants) == 1
    finally:
        other.database.close()


def test_forged_capsule_archive_rejects_cold_start_without_rewriting_save(capsule_runtime):
    runtime, _ = capsule_runtime
    with runtime.database.transaction() as session:
        outer = session.query(m.RogueTopicOuter).filter_by(account_id=1, topic_id="rogue_1").one()
        state = copy.deepcopy(outer.state)
        state["collect"]["capsule"][C9] = {"state": 2, "progress": []}
        outer.state = state
    runtime.database.close()
    before = rows(runtime.database.path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before


def test_capsule_content_requires_the_new_provider_and_complete_frozen_rule(capsule_runtime):
    runtime, _ = capsule_runtime
    value = {"id": "authored", "weight": 1, "content": {
        "groups": [], "eligibility": [], "evidence": "Authored supply", "capsule": C9}}
    with pytest.raises(ValueError):
        candidate(runtime.data, "battle", value, 1_800_000_000)
    compiled = candidate(runtime.data, "battle", value, 1_800_000_000, capsules=True)
    assert compiled.reservations == frozenset() and compiled.visit is None
    assert json.loads(compiled.source)["capsule"] == C9


def test_giveup_keeps_acquired_capsule_history_and_archive_after_confirmation(capsule_runtime):
    runtime, token = capsule_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "get").status_code == 200
        assert post(client, token, "finishBattleReward", {}, "finish").status_code == 200
        assert move(client, token, 1, "enter").status_code == 200
        closed = post(client, token, "giveUpGame", {}, "giveup")
        assert closed.status_code == 200, closed.text
        event = current(runtime, token)["player"]["pending"][0]
        assert event["content"]["result"]["record"]["capsuleList"] == [C9]
        assert current(runtime, token)["buff"]["capsule"] is None
        ack = post(client, token, "gameSettle", {}, "ack")
        assert ack.status_code == 200, ack.text
        assert runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["capsule"][C9]["state"] == 2
