"""Owned support-tool purchases and replacements; authored QA prices only."""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType, SimpleNamespace

import pytest
import test_rogue_cost_relics as costs
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy, leave
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_floor_progress import journal
from test_rogue_settlement import complete
from test_rogue_training import move, setup
from test_rogue_training import training_runtime as training_runtime
from test_roguelike_battle_start import begin, body
from test_roguelike_initial import post

from terralocal.server.domain.context import Context
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_shops import prepare
from terralocal.server.domain.rogue_support_tools import ToolHistory
from terralocal.server.domain.rogue_topics import snapshot
from terralocal.server.gamedata import rogue_support_tools as tools
from terralocal.server.gamedata import rogue_tool_effects as effects
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

A, B = "qa_support_a", "qa_support_b"


def add_tools(detail, monkeypatch):
    sources = {}
    for index, (key, count) in enumerate(((A, 1), (B, 3)), 1):
        item = {"id": key, "type": "ACTIVE_TOOL", "iconId": key,
                "name": "Authored QA tool " + str(index), "usage": "Authored count " + str(count)}
        trap = {"itemId": key, "trapId": "qa_trap_" + str(index), "trapDesc": "Authored QA effect"}
        archive = {"trapId": key, "enrollId": None, "orderId": "QA-" + str(index), "trapSortId": index}
        detail.setdefault("items", {})[key] = item
        detail.setdefault("traps", {})[key] = trap
        detail.setdefault("archiveComp", {}).setdefault("trap", {}).setdefault("trap", {})[key] = archive
        sources[key] = trap["trapId"], count, fingerprint({"item": item, "trap": trap, "archive": archive})
    monkeypatch.setattr(tools, "SOURCES", MappingProxyType(sources))


def rule_data(monkeypatch):
    detail = {}
    add_tools(detail, monkeypatch)
    return SimpleNamespace(table=lambda name: {"details": {"rogue_1": detail}},
        manifest={"hash": "a" * 64}, rogue_topics=SimpleNamespace(topic=lambda key: SimpleNamespace(start=100))), detail


@pytest.mark.parametrize("damage", ["identity", "type", "icon", "trap", "archive", "enroll", "missing"])
def test_changed_tool_definition_cannot_enter_supported_stock(monkeypatch, damage):
    data, detail = rule_data(monkeypatch)
    if damage in ("identity", "type", "icon"):
        detail["items"][A][{"identity": "id", "type": "type", "icon": "iconId"}[damage]] = "different"
    elif damage == "trap":
        detail["traps"][A]["trapId"] = detail["traps"][B]["trapId"]
    elif damage == "archive":
        detail["archiveComp"]["trap"]["trap"][A]["orderId"] = "other"
    elif damage == "enroll":
        detail["archiveComp"]["trap"]["trap"][A]["enrollId"] = "unknown_late_enroll"
    else:
        del detail["items"][A]
    with pytest.raises(ValueError):
        tools.FirstThemeSupportTools(data)


def test_topic_opening_and_unknown_tool_are_not_inferred_from_empty_condition(monkeypatch):
    data, detail = rule_data(monkeypatch)
    detail["items"]["unknown"] = {"id": "unknown", "type": "ACTIVE_TOOL", "unlockCondDesc": None}
    catalog = tools.FirstThemeSupportTools(data)
    for key, at in ((A, 99), (A, True), (A, 2**63), (A, 100.0), ("unknown", 100)):
        with pytest.raises(ValueError):
            catalog.require(key, at)
    assert catalog.require(B, 100).battle_count == 3
    with pytest.raises(TypeError):
        catalog.entries[A] = catalog.entries[B]


@pytest.fixture
def support_tables(cost_tables, monkeypatch):
    original = costs.add_costs
    def add(tables):
        tables = original(tables)
        add_tools(tables["roguelike_topic_table"]["details"]["rogue_1"], monkeypatch)
        return tables
    monkeypatch.setattr(costs, "add_costs", add)


@pytest.fixture
def support_runtime(support_tables, cost_runtime):
    return cost_runtime


def configure(runtime, token):
    setup(runtime, token, ("SHOP", "SHOP"))
    with runtime.database.transaction() as session:
        quote = compile_shop(runtime.data, "qa-tool-replacement", (
            Offer("early", A, 2), Offer("later", B, 3), Offer("ticket", "ticket_pioneer", 0)),
            evidence="Authored QA replacement stock/prices2,3, not official first-floor stock or normal prices")
        next_quote = compile_shop(runtime.data, "qa-tool-next", (Offer("again", A, 1),),
            evidence="Authored later-node ownership replacement, not official price")
        prepare(Context(session, runtime.data, 1), {Point(0, 0): quote, Point(1, 0): next_quote})
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "tool-shop-enter").status_code == 200


def current(runtime):
    with runtime.database.transaction(write=False) as session:
        return snapshot(Context(session, runtime.data, 1))["current"]


def test_purchase_replace_retry_delta_and_legacy_inventory_are_distinct(support_runtime):
    runtime, token = support_runtime
    configure(runtime, token)
    first = current(runtime)
    initial_gold = first["player"]["property"]["gold"]
    assert first["inventory"]["trap"] is None
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)["user"]
        acquired = buy(client, token, "early", "tool-first")
        assert acquired.status_code == 200, acquired.text
        assert apply(before, acquired.json()["playerDataDelta"]) == runtime.sync(token)["user"]
        one = current(runtime)
        assert one["inventory"]["trap"]["id"] == A and one["player"]["property"]["gold"] == initial_gold - 2
        assert buy(client, token, "early", "tool-first").content == acquired.content
        before = runtime.sync(token)["user"]
        replaced = buy(client, token, "later", "tool-replace")
        assert replaced.status_code == 200, replaced.text
        assert apply(before, replaced.json()["playerDataDelta"]) == runtime.sync(token)["user"]
        final = current(runtime)
        assert final["inventory"]["trap"]["id"] == B and final["player"]["property"]["gold"] == initial_gold - 5
        assert buy(client, token, "early", "old-slot-new-sequence").status_code == 200
        assert current(runtime) == final
    assert final["inventory"]["relic"] == first["inventory"]["relic"]
    assert final["inventory"]["recruit"] == first["inventory"]["recruit"]
    with runtime.database.transaction(write=False) as session:
        progress = []
        from terralocal.server.domain.rogue_runs import active
        active(Context(session, runtime.data, 1), progress_out=progress)
        assert [g.item_id for g in progress[0].support_tool_grants] == [A, B]
        wire = progress[0].support_tool.wire()
        wire["id"] = "forged"
        assert progress[0].support_tool.wire()["id"] == B


def test_tool_replacement_persists_across_nodes_restart_and_real_backup(support_runtime):
    runtime, token = support_runtime
    configure(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "later", "first-node-tool").status_code == 200
        assert leave(client, token, "tool-leave").status_code == 200
        assert move(client, token, 1, "tool-next-node").status_code == 200
        assert buy(client, token, "again", "replace-next-node").status_code == 200
    final = runtime.sync(token)["user"]
    assert final["rlv2"]["current"]["inventory"]["trap"]["id"] == A
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
        backups = BackupService(reopened)
        backup = backups.create()
        backups.restore(backup["name"])
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()


def test_purchase_projection_failure_rolls_back_payment_and_source_receipt(support_runtime, monkeypatch):
    runtime, token = support_runtime
    configure(runtime, token)
    before = current(runtime)
    def fail(*args, **kwargs):
        raise ValueError("Authored failure while validating new tool ownership")
    monkeypatch.setattr(ToolHistory, "acquire", fail)
    with TestClient(create_game_app(runtime)) as client:
        result = buy(client, token, "early", "tool-rollback")
        assert result.status_code == 503, result.text
    assert current(runtime) == before
    with runtime.database.transaction(write=False) as session:
        assert not any(v.purchases for v in session.query(m.RogueShopVisit))


def test_client_cannot_supply_tool_identity_or_price(support_runtime):
    runtime, token = support_runtime
    configure(runtime, token)
    before = current(runtime)
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "shopAction", {"buy": ["early"], "recycle": [], "leave": 0,
                      "itemId": B, "priceCount": 0}, "tool-client-forgery")
        assert result.status_code == 422, result.text
    assert current(runtime) == before


def test_concurrent_new_sequences_buy_one_tool_and_spend_once(support_runtime):
    runtime, token = support_runtime
    configure(runtime, token)
    initial_gold = current(runtime)["player"]["property"]["gold"]
    other = Runtime(runtime.settings)
    def pay(pair):
        service, key = pair
        with TestClient(create_game_app(service)) as client:
            return buy(client, token, "early", key).status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(pay, ((runtime, "tool-race-a"), (other, "tool-race-b")))) == [200, 200]
        assert current(runtime)["player"]["property"]["gold"] == initial_gold - 2
        with runtime.database.transaction(write=False) as session:
            assert sum(len(v.purchases) for v in session.query(m.RogueShopVisit)) == 1
    finally:
        other.database.close()


@pytest.mark.parametrize("damage", ["source", "time"])
def test_forged_tool_receipt_is_rejected_before_startup_writes(support_runtime, damage):
    runtime, token = support_runtime
    configure(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "early", "tool-before-forgery").status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as con:
        key, quote, purchases, entered = con.execute(
            "SELECT id,quote,purchases,entered_at FROM rlv2_shop_visits WHERE state='ACTIVE'").fetchone()
        if damage == "source":
            quote = json.loads(quote)
            quote["offers"][0]["item_id"] = "unknown_tool"
            con.execute("UPDATE rlv2_shop_visits SET quote=? WHERE id=?", (json.dumps(quote), key))
        else:
            purchases = json.loads(purchases)
            purchases[0]["at"] = entered - 1
            con.execute("UPDATE rlv2_shop_visits SET purchases=? WHERE id=?", (json.dumps(purchases), key))
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


def add_effects(tables, monkeypatch):
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    sources = {}
    for key, count in ((A, 1), (B, 3)):
        trap_id = detail["traps"][key]["trapId"]
        template = tables["character_table"].get("char_six", {
            "phases": [{"maxLevel": 30}], "skills": [{"skillId": "qa_skill"}]})
        token = copy.deepcopy(template) | {"profession": "TRAP", "isNotObtainable": True}
        token["skills"] = [] if key == A else token["skills"][:1]
        tables["character_table"][trap_id] = token
        effect = {"key": "misc_insert_token_card", "blackboard": [
            {"key": "token_key", "value": 0.0, "valueStr": trap_id},
            {"key": "level", "value": 1.0, "valueStr": None},
            {"key": "skill", "value": -1.0 if key == A else 0.0, "valueStr": None},
            {"key": "cnt", "value": float(count), "valueStr": None}]}
        relic = {"id": key, "buffs": [effect]}
        detail.setdefault("relics", {})[key] = relic
        sources[key] = fingerprint(relic), fingerprint(token)
    monkeypatch.setattr(effects, "SOURCES", MappingProxyType(sources))
    return tables


def effect_rule_data(monkeypatch):
    data, detail = rule_data(monkeypatch)
    tables = {"roguelike_topic_table": {"details": {"rogue_1": detail}}, "character_table": {}}
    add_effects(tables, monkeypatch)
    data.characters = tables["character_table"]
    data.rogue_support_tools = tools.FirstThemeSupportTools(data)
    return data, detail


def test_effects_use_reviewed_blackboards_and_return_independent_battle_lists(monkeypatch):
    data, _ = effect_rule_data(monkeypatch)
    catalog = effects.FirstThemeToolEffects(data)
    assert (catalog.require(A, 100).count, catalog.require(B, 100).count) == (1, 3)
    first = catalog.require(B, 100).wire()
    first[0]["blackboard"][3]["value"] = 999
    assert catalog.require(B, 100).wire()[0]["blackboard"][3]["value"] == 3
    with pytest.raises(TypeError):
        catalog.entries[A] = catalog.entries[B]
    for key, at in (("unreviewed", 100), (A, 99), (A, True)):
        with pytest.raises(ValueError):
            catalog.require(key, at)


@pytest.mark.parametrize("damage", ["effect", "token", "count", "level", "skill", "template"])
def test_changed_battle_source_cannot_silently_grant_a_different_tool(monkeypatch, damage):
    data, detail = effect_rule_data(monkeypatch)
    board = detail["relics"][B]["buffs"][0]["blackboard"]
    if damage == "effect":
        detail["relics"][B]["buffs"][0]["key"] = "different_effect"
    elif damage == "template":
        data.characters[detail["traps"][B]["trapId"]]["profession"] = "PIONEER"
    else:
        index = {"token": 0, "level": 1, "skill": 2, "count": 3}[damage]
        board[index]["valueStr" if damage == "token" else "value"] = "different_trap" if damage == "token" else 2.0
    with pytest.raises(ValueError):
        effects.FirstThemeToolEffects(data)


def test_count_cannot_disagree_with_tool_binding_even_with_a_new_source_digest(monkeypatch):
    data, detail = effect_rule_data(monkeypatch)
    detail["relics"][B]["buffs"][0]["blackboard"][3]["value"] = 4.0
    sources = dict(effects.SOURCES)
    sources[B] = fingerprint(detail["relics"][B]), sources[B][1]
    monkeypatch.setattr(effects, "SOURCES", MappingProxyType(sources))
    with pytest.raises(ValueError):
        effects.FirstThemeToolEffects(data)


@pytest.fixture
def effect_tables(support_tables, monkeypatch):
    original = costs.add_costs
    def add(tables):
        tables = original(tables)
        # training_runtime adds test_gold; inherited temporary-table gold is
        # unused here and would violate the real unique-currency contract.
        tables["roguelike_topic_table"]["details"]["rogue_1"]["items"].pop("gold", None)
        return add_effects(tables, monkeypatch)
    monkeypatch.setattr(costs, "add_costs", add)


@pytest.fixture
def effect_runtime(effect_tables, cost_runtime):
    return cost_runtime


def configure_tool_battles(runtime, token):
    setup(runtime, token, ("SHOP", "BATTLE_NORMAL", "SHOP", "BATTLE_NORMAL"))
    with runtime.database.transaction() as session:
        quotes = {Point(x, 0): compile_shop(runtime.data, "qa-tool-battle-" + str(x),
            (Offer("tool", key, price),), evidence="Authored QA tool battle stock/prices, not official natural supply")
            for x, key, price in ((0, A, 1), (2, B, 2))}
        prepare(Context(session, runtime.data, 1), quotes)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "battle-tool-shop").status_code == 200


def tool_battle_request(x):
    payload = body()
    payload["to"]["x"] = x
    payload["squad"]["slots"] = [{"charInstId": 1, "skillIndex": 1, "currentEquip": None}]
    return payload


def test_each_battle_binds_its_prior_tool_replacement_retry_delta_and_backup(effect_runtime):
    runtime, token = effect_runtime
    configure_tool_battles(runtime, token)
    permanent = runtime.sync(token)["user"]["troop"]
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "tool", "before-first-battle").status_code == 200
        assert leave(client, token, "tool-first-shop-leave").status_code == 200
        before = runtime.sync(token)["user"]
        first = begin(client, token, tool_battle_request(1), "tool-battle-first")
        assert first.status_code == 200, first.text
        assert apply(before, first.json()["playerDataDelta"]) == runtime.sync(token)["user"]
        pending = current(runtime)["player"]["pending"][0]["content"]["battle"]
        assert pending["unKeepBuff"] == runtime.data.rogue_tool_effects.require(A, 1_800_000_000).wire()
        assert begin(client, token, tool_battle_request(1), "tool-battle-first").content == first.content
        assert buy(client, token, "tool", "no-buy-during-battle").status_code == 409
        trace = journal()
        trace["journal"]["squad"] = trace["journal"]["squad"][:1]
        hp = current(runtime)["player"]["property"]["hp"]["current"]
        ended = complete(client, token, first.json()["battleId"], trace,
                         hp + runtime.data.rogue_initial.battle_temporary_hp, "tool-first-finish")
        assert ended.status_code == 200, ended.text
        assert post(client, token, "finishBattleReward", {}, "tool-first-reward-leave").status_code == 200
        assert move(client, token, 2, "tool-replacement-shop").status_code == 200
        assert buy(client, token, "tool", "before-second-battle").status_code == 200
        assert leave(client, token, "tool-second-shop-leave").status_code == 200
        second = begin(client, token, tool_battle_request(3), "tool-battle-second")
        assert second.status_code == 200, second.text
    with runtime.database.transaction(write=False) as session:
        from terralocal.server.domain.rogue_runs import active
        progress = []
        active(Context(session, runtime.data, 1), progress_out=progress)
        bound = progress[0].support_tool_battles
        assert bound[first.json()["battleId"]].item_id == A and bound[second.json()["battleId"]].item_id == B
        assert bound[first.json()["battleId"]].at == bound[second.json()["battleId"]].at
        with pytest.raises(TypeError):
            bound[first.json()["battleId"]] = bound[second.json()["battleId"]]
        assert session.query(m.RogueBattle).count() == 2
    final = runtime.sync(token)["user"]
    assert final["troop"] == permanent
    assert final["rlv2"]["current"]["player"]["pending"][0]["content"]["battle"]["unKeepBuff"] == (
        runtime.data.rogue_tool_effects.require(B, 1_800_000_000).wire())
    runtime.database.close()
    again = Runtime(runtime.settings)
    try:
        assert again.sync(token)["user"] == final
        backups = BackupService(again)
        saved = backups.create()
        backups.restore(saved["name"])
        assert again.sync(token)["user"] == final
    finally:
        again.database.close()


def test_invalid_tool_effect_rolls_back_new_battle_and_pending_state(effect_runtime, monkeypatch):
    runtime, token = effect_runtime
    configure_tool_battles(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "tool", "tool-for-rollback").status_code == 200
        assert leave(client, token, "tool-rollback-leave").status_code == 200
        before = current(runtime)
        def fail(*args):
            raise ValueError("Authored unavailable battle source")
        monkeypatch.setattr(runtime.data.rogue_tool_effects, "require", fail)
        result = begin(client, token, tool_battle_request(1), "tool-battle-rollback")
        assert result.status_code == 503, result.text
        assert current(runtime) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueBattle).count() == 0


def test_client_cannot_supply_its_own_temporary_tool_buffs(effect_runtime):
    runtime, token = effect_runtime
    configure_tool_battles(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "tool", "tool-before-extra-field").status_code == 200
        assert leave(client, token, "tool-extra-field-leave").status_code == 200
        before = current(runtime)
        result = begin(client, token, tool_battle_request(1) | {"unKeepBuff": [{"key": "free-tool"}]}, "tool-forged-buffs")
        assert result.status_code == 422
        assert current(runtime) == before


def test_two_runtimes_start_once_with_the_same_owned_tool_effect(effect_runtime):
    runtime, token = effect_runtime
    configure_tool_battles(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "tool", "tool-before-concurrency").status_code == 200
        assert leave(client, token, "tool-concurrent-leave").status_code == 200
    before_gold = current(runtime)["player"]["property"]["gold"]
    other = Runtime(runtime.settings)
    try:
        def start(pair):
            owner, key = pair
            with TestClient(create_game_app(owner)) as client:
                return begin(client, token, tool_battle_request(1), key)
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(start, [(runtime, "tool-parallel-one"), (other, "tool-parallel-two")]))
        assert [r.status_code for r in replies] == [200, 200]
        assert len({r.json()["battleId"] for r in replies}) == 1
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueBattle).count() == 1
        state = current(runtime)
        assert state["player"]["property"]["gold"] == before_gold
        assert state["player"]["pending"][0]["content"]["battle"]["unKeepBuff"] == (
            runtime.data.rogue_tool_effects.require(A, 1_800_000_000).wire())
    finally:
        other.database.close()


@pytest.mark.parametrize("damage", ["legacy", "wrong_floor", "missing_owned_tool", "old_reader"])
def test_saved_tool_battle_capability_cannot_be_downgraded_or_invented(effect_runtime, monkeypatch, damage):
    from terralocal.server.domain import rogue_battle

    runtime, token = effect_runtime
    configure_tool_battles(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        if damage != "missing_owned_tool":
            assert buy(client, token, "tool", "tool-before-policy").status_code == 200
        assert leave(client, token, "tool-policy-leave").status_code == 200
        started = begin(client, token, tool_battle_request(1), "tool-policy-battle")
        assert started.status_code == 200, started.text
    runtime.database.close()
    if damage == "old_reader":
        # This is the exact older reader's admitted capability set. It must
        # reject the newer battle before SQLite initialization writes.
        monkeypatch.setattr(rogue_battle, "POLICIES", frozenset({rogue_battle.POLICY, rogue_battle.ZONE_POLICY}))
    else:
        policy = {"legacy": rogue_battle.POLICY, "wrong_floor": rogue_battle.TOOL_ZONE_POLICY,
                  "missing_owned_tool": rogue_battle.TOOL_POLICY}[damage]
        with sqlite3.connect(runtime.database.path) as con:
            con.execute("UPDATE rlv2_battles SET policy_version=? WHERE id=?", (policy, started.json()["battleId"]))
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before
