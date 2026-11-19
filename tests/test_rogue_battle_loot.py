"""Authored extra-loot transactions, not official probabilities or native combat."""

import copy
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_rogue_floor_progress import journal
from test_rogue_recruit_costs import R25, R26, R27
from test_rogue_settlement import complete
from test_roguelike_battle_start import begin, body
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_settlement
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_floors import FloorSequence
from terralocal.server.domain.rogue_loot_plans import prepare
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_map_drafts import prepare_floors
from terralocal.server.domain.rogue_visits import prepare as save_scenes
from terralocal.server.gamedata.rogue_battle_loot import RelicGroups, admit_groups, compile_groups
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import REVISION, ROGUE_BANK_AWARDS_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.roguelike_state import no_run
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

pytest_plugins = ("test_rogue_cost_relics", "test_rogue_boss_ending", "test_rogue_capacity_relics")


def configured(runtime, token, *, kind="BATTLE_NORMAL", stage="ordinary", groups=((R25, R26, R27),), next_battle=False, install=True):
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), Plan("zone_1", (
            Column(1, 1, (Entry(kind, 1, stage),)), Column(1, 1, (
                Entry("BATTLE_NORMAL", 1, "ordinary") if next_battle else Entry("SHOP", 1),))), 0))
    with TestClient(create_game_app(runtime)) as client:
        result = post(client, token, "finishEvent", {}, "loot-map")
        assert result.status_code == 200, result.text
    spec = RelicGroups(groups, frozenset(item for g in groups for item in g),
                       "Authored QA supply and eligibility; no official drop pool or weights")
    if install:
        with runtime.database.transaction() as session:
            prepare(Context(session, runtime.data, 1), {Point(0, 0): spec})
    return spec


def finish_new(runtime, token, client, *, stage="ordinary", key="loot-start", rank=3, x=0):
    payload = body(stage)
    payload['to']['x'] = x
    payload["squad"]["slots"] = [{"charInstId": 1, "skillIndex": 1, "currentEquip": None}]
    result = begin(client, token, payload, key=key)
    assert result.status_code == 200, result.text
    with runtime.database.transaction(write=False) as session:
        run = session.query(m.RogueTopicRun).one()
        hp = run.hp + runtime.data.rogue_initial.battle_temporary_hp
    trace = journal()
    trace["journal"]["squad"] = trace["journal"]["squad"][:1]
    trace["journal"]["metadata"]["stageId"] = stage
    result = complete(client, token, result.json()["battleId"], trace, hp if rank == 3 else 1 if rank == 2 else 0,
        key + "-finish", stageId=stage, completeState=rank, percent=100 if rank != 1 else 2)
    assert result.status_code == 200, result.text
    pending = current(runtime, token)["player"]["pending"][0]
    return pending if rank == 1 else pending["content"]["battleReward"]


def test_choose_one_relic_atomic_delta_retry_conflict_restart_and_backup(cost_runtime):
    runtime, token = cost_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        reward = finish_new(runtime, token, client)
        assert reward["rewards"][2]["items"] == [
            {"id": key, "count": 1, "sub": sub} for sub, key in enumerate((R25, R26, R27))]
        before = runtime.sync(token)["user"]
        selected = post(client, token, "chooseBattleReward", {"index": 2, "sub": 1}, "loot-select")
        assert selected.status_code == 200, selected.text
        after = runtime.sync(token)["user"]
        assert apply(before, selected.json()["playerDataDelta"]) == after
        assert {k:v for k,v in before.items() if k != "rlv2"} == {k:v for k,v in after.items() if k != "rlv2"}
        inventory = after["rlv2"]["current"]["inventory"]["relic"]
        assert [row["id"] for row in inventory.values()][1:] == [R26]
        saved = rows(runtime.database.path)
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 1}, "loot-select").json() == selected.json()
        assert rows(runtime.database.path) == saved
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 1}, "new-seq").status_code == 200
        saved = rows(runtime.database.path)
        assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 0}, "different-option").status_code == 409
        assert rows(runtime.database.path) == saved
        assert post(client, token, "finishBattleReward", {}, "close-loot").status_code == 200
    before = copy.deepcopy(runtime.sync(token)["user"])
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == before
        backups = BackupService(reopened)
        backups.restore(backups.create()["name"])
        assert reopened.sync(token)["user"] == before and rows(runtime.database.path) == saved
    finally:
        reopened.database.close()


@pytest.mark.parametrize("kind,stage,rank", [
    ("BATTLE_ELITE", "emergency", 3), ("BATTLE_ELITE", "emergency", 2), ("BATTLE_ELITE", "emergency", 1),
    ("BATTLE_NORMAL", "ordinary", 2), ("BATTLE_NORMAL", "ordinary", 1)])
def test_planned_normal_and_elite_outcomes_keep_reward_and_ending_rules(cost_runtime, kind, stage, rank):
    runtime, token = cost_runtime
    configured(runtime, token, kind=kind, stage=stage)
    with TestClient(create_game_app(runtime)) as client:
        reward = finish_new(runtime, token, client, stage=stage, rank=rank)
        if rank == 1:
            assert reward["type"] == "GAME_SETTLE" and reward["content"]["result"]["brief"]["success"] == 0
            assert post(client, token, "gameSettle", {}, "defeat-ack").status_code == 200
            assert current(runtime, token) == no_run()
        else:
            assert reward["isPerfect"] == int(rank == 3)
            assert post(client, token, "chooseBattleReward", {"index": 2, "sub": 2}, "choose").status_code == 200
            assert post(client, token, "finishBattleReward", {}, "close").status_code == 200
        with runtime.database.transaction(write=False) as session:
            result = session.query(m.RogueBattleSettlement).one()
            assert result.policy_version == rogue_settlement.LOOT_POLICY
            assert result.effects["kind"] == kind
            assert len(result.loot) == (0 if rank == 1 else 3)
            assert session.query(m.RogueRunRelic).filter(m.RogueRunRelic.ordinal > 0).count() == int(rank != 1)


@pytest.mark.parametrize("selection", [{"index": 99, "sub": 0}, {"index": 2, "sub": 3},
    {"index": 2, "sub": -1}, {"index": True, "sub": 1}, {"index": 2, "sub": False}])
def test_invalid_or_bool_selection_never_changes_reward_or_inventory(cost_runtime, selection):
    runtime, token = cost_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
        before = rows(runtime.database.path)
        assert post(client, token, "chooseBattleReward", selection, "invalid-choice").status_code in (400, 422)
        assert rows(runtime.database.path) == before


def test_claim_rolls_back_source_inventory_receipt_and_delta(cost_runtime):
    runtime, token = cost_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
    before, snapshot = rows(runtime.database.path), runtime.sync(token)["user"]
    def fail(ctx):
        rogue_settlement.claim(ctx, 2, 2)
        raise DomainError("INJECTED", "rollback extra relic claim")
    with pytest.raises(DomainError, match="rollback extra relic"):
        runtime.mutate(token, None, "rollback-loot", "qa-loot", {"index": 2, "sub": 2}, fail)
    assert rows(runtime.database.path) == before and runtime.sync(token)["user"] == snapshot


def test_two_runtimes_claim_the_same_group_only_once(cost_runtime):
    runtime, token = cost_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
    other = Runtime(runtime.settings)
    def claim(args):
        service, key = args
        return service.mutate(token, None, key, "qa-loot", {"index":2,"sub":1},
                              lambda ctx: rogue_settlement.claim(ctx, 2, 1))
    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(claim, ((runtime, "one"), (other, "two"))))
        assert all(result["result"] == 0 for result in results)
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueRunRelic).filter(m.RogueRunRelic.ordinal > 0).count() == 1
            assert len(session.query(m.RogueBattleSettlement).one().claims) == 1
    finally:
        other.database.close()


def test_recruit_pending_blocks_relic_and_closing_unclaimed_groups_forfeits_them(cost_runtime):
    runtime, token = cost_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
        assert post(client, token, "chooseBattleReward", {"index":1,"sub":0}, "ticket").status_code == 200
        saved = rows(runtime.database.path)
        assert post(client, token, "chooseBattleReward", {"index":2,"sub":1}, "blocked-relic").status_code == 409
        assert post(client, token, "finishBattleReward", {}, "blocked-leave").status_code == 409
        assert rows(runtime.database.path) == saved
        assert post(client, token, "closeRecruitTicket", {"id":"3"}, "close-ticket").status_code == 200
        assert post(client, token, "finishBattleReward", {}, "leave-unclaimed").status_code == 200
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueRunRelic).filter(m.RogueRunRelic.ordinal > 0).count() == 0
        assert len(session.query(m.RogueBattleSettlement).one().claims) == 1


def test_plan_retry_is_immutable_after_its_battle_finished(cost_runtime):
    runtime, token = cost_runtime
    spec = configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
    saved = rows(runtime.database.path)
    with runtime.database.transaction() as session:
        prepare(Context(session, runtime.data, 1), {Point(0, 0): spec})
    assert rows(runtime.database.path) == saved
    changed = RelicGroups(((R27,),), frozenset({R27}), spec.evidence)
    with pytest.raises(DomainError, match="不能替换"):
        with runtime.database.transaction() as session:
            prepare(Context(session, runtime.data, 1), {Point(0, 0): changed})
    assert rows(runtime.database.path) == saved


def test_legacy_started_battle_cannot_be_retroactively_given_a_plan(cost_runtime, monkeypatch):
    runtime, token = cost_runtime
    spec = configured(runtime, token, install=False)
    payload = body()
    payload['squad']['slots'] = [{'charInstId':1,'skillIndex':1,'currentEquip':None}]
    with TestClient(create_game_app(runtime)) as client:
        # Preserve the legacy STARTED scenario. Current admission correctly
        # rejects this fixture's ambiguous unplanned currency before writing.
        with monkeypatch.context() as legacy:
            legacy.setattr(rogue_settlement, "admit_start", lambda *args: None)
            result = begin(client,token,payload)
        assert result.status_code == 200,result.text
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError, match='不能追加'):
        with runtime.database.transaction() as session:
            prepare(Context(session,runtime.data,1),{Point(0,0):spec})
    assert rows(runtime.database.path) == saved


@pytest.mark.parametrize("damage", ["missing", "groups", "map", "time", "data"])
def test_corrupt_plan_is_rejected_before_startup_writes(cost_runtime, damage):
    runtime, token = cost_runtime
    configured(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
    with runtime.database.transaction() as session:
        plan = session.query(m.RogueBattleLootPlan).one()
        if damage == "missing":
            session.delete(plan)
        elif damage == "groups":
            plan.spec = plan.spec | {"groups":[[R25,R25]]}
        elif damage == "map":
            plan.map_hash = "0" * 64
        elif damage == "time":
            plan.prepared_at += 1
        else:
            plan.gamedata_hash = "f" * 64
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def test_0036_additive_migration_keeps_all_old_rows(cost_runtime):
    runtime, _ = cost_runtime
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TABLE rlv2_battle_loot_plans")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_BANK_AWARDS_REVISION,))
    old = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        now = rows(runtime.database.path)
        assert now['alembic_version'] == [(REVISION,)] and now['rlv2_battle_loot_plans'] == []
        assert all(now[k] == value for k,value in old.items() if k != 'alembic_version')
    finally:
        reopened.database.close()


def test_additive_migration_failure_rolls_back_new_table_and_version(cost_runtime, monkeypatch):
    runtime, _ = cost_runtime
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute('DROP TABLE rlv2_battle_loot_plans')
        con.execute('UPDATE alembic_version SET version_num=?',(ROGUE_BANK_AWARDS_REVISION,))
    before = rows(runtime.database.path)
    table = m.RogueBattleLootPlan.__table__
    original = table.create
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('injected after loot table creation')
    with monkeypatch.context() as injected:
        injected.setattr(table,'create',fail)
        with pytest.raises(RuntimeError,match='injected after loot'):
            Runtime(runtime.settings)
    assert rows(runtime.database.path) == before
    reopened = Runtime(runtime.settings)
    try:
        assert rows(runtime.database.path)['alembic_version'] == [(REVISION,)]
    finally:
        reopened.database.close()


@pytest.mark.parametrize('version',[ROGUE_BANK_AWARDS_REVISION,REVISION])
def test_missing_prior_awards_column_still_rejects_before_migration(cost_runtime, version):
    runtime, _ = cost_runtime
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute('UPDATE alembic_version SET version_num=?',(version,))
        con.execute('ALTER TABLE rlv2_bank_wallets DROP COLUMN awards')
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("damage", ["empty", "duplicate", "eligibility", "bool-schema", "bad-eligibility"])
def test_compiled_groups_reject_incomplete_or_forged_sources(cost_runtime, damage):
    runtime, _ = cost_runtime
    spec = RelicGroups(((R25,R26),), frozenset({R25,R26}), "Authored source only")
    value, _ = compile_groups(runtime.data, spec, at=1_800_000_000)
    if damage == "empty":
        value['groups'] = []
    elif damage == "duplicate":
        value['groups'] = [[R25,R25]]
    elif damage == "eligibility":
        value['eligibility'] = [R25]
    elif damage == "bool-schema":
        value['schema'] = True
    else:
        value['eligibility'] = [{}]
    with pytest.raises(ValueError):
        admit_groups(runtime.data, value)


def test_capacity_relic_applies_its_resource_in_the_same_claim(capacity_runtime):
    runtime, token = capacity_runtime
    key = next(iter(runtime.data.rogue_capacity_relics.entries))
    configured(runtime, token, groups=((key,),))
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime, token, client)
        before = current(runtime, token)['player']['property']['capacity']
        reply = post(client, token, 'chooseBattleReward', {'index':2,'sub':0}, 'capacity')
        assert reply.status_code == 200, reply.text
        assert current(runtime, token)['player']['property']['capacity'] == runtime.data.rogue_capacity_relics.increase(key,before)


@pytest.fixture
def loot_boss_runtime(cost_tables, request):
    return request.getfixturevalue("boss_runtime")


@pytest.mark.parametrize("stage", ["ro1_b_" + str(i) for i in range(1,6)])
def test_all_five_intermediate_bosses_reward_then_advance_without_ending(loot_boss_runtime, stage):
    from test_rogue_floor_progress import scene

    runtime, token = loot_boss_runtime
    spec = FloorSequence(tuple(Plan("zone_"+str(i), (Column(1,1,(
        Entry("BATTLE_BOSS",1,stage) if i == 3 else Entry("INCIDENT",1),)),),0) for i in range(1,6)))
    with runtime.database.transaction() as session:
        prepare_floors(Context(session,runtime.data,1),spec)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client,token,'finishEvent',{},'boss-loot-map').status_code == 200
    with runtime.database.transaction() as session:
        for number in (1,2):
            save_scenes(Context(session,runtime.data,1),{Point(0,0):'rogue1-fixed-gold'},zone_index=number)
        prepare(Context(session,runtime.data,1),{Point(0,0):RelicGroups(((R25,R26,R27),),
            frozenset({R25,R26,R27}),'Authored intermediate-Boss eligibility; not natural weights')},zone_index=3)
    with TestClient(create_game_app(runtime)) as client:
        assert scene(client,token,'floor1').status_code == 200
        assert scene(client,token,'floor2').status_code == 200
        reward = finish_new(runtime,token,client,stage=stage)
        assert len(reward['rewards'][2]['items']) == 3
        assert post(client,token,'chooseBattleReward',{'index':2,'sub':1},'boss-relic').status_code == 200
        assert post(client,token,'finishBattleReward',{},'boss-reward-close').status_code == 200
        state = current(runtime,token)
        assert state['player']['cursor'] == {'zone':4,'position':None}
        assert state['player']['pending'] == [] and state['player']['state'] == 'WAIT_MOVE'
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueGameSettlement).count() == 0


def test_intermediate_relic_persists_through_default_final_boss_and_score(loot_boss_runtime):
    from test_rogue_floor_progress import scene

    runtime, token = loot_boss_runtime
    sequence = FloorSequence(tuple(Plan('zone_'+str(i),(Column(1,1,(
        Entry('BATTLE_BOSS',1,'ro1_b_1' if i==3 else 'ro1_b_6') if i in (3,5) else Entry('INCIDENT',1),)),),0)
        for i in range(1,6)))
    with runtime.database.transaction() as session:
        prepare_floors(Context(session,runtime.data,1),sequence)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client,token,'finishEvent',{},'full-map').status_code == 200
    with runtime.database.transaction() as session:
        for number in (1,2,4):
            save_scenes(Context(session,runtime.data,1),{Point(0,0):'rogue1-fixed-gold'},zone_index=number)
        prepare(Context(session,runtime.data,1),{Point(0,0):RelicGroups(((R25,R26,R27),),
            frozenset({R25,R26,R27}),'Explicit full-route QA reward')},zone_index=3)
    with TestClient(create_game_app(runtime)) as client:
        for number in (1,2):
            assert scene(client,token,'full-floor'+str(number)).status_code == 200
        finish_new(runtime,token,client,stage='ro1_b_1',key='middle')
        assert post(client,token,'chooseBattleReward',{'index':2,'sub':1},'full-relic').status_code == 200
        assert post(client,token,'finishBattleReward',{},'middle-close').status_code == 200
        assert scene(client,token,'full-floor4').status_code == 200
        payload = body('ro1_b_6')
        payload['squad']['slots'] = [{'charInstId':1,'skillIndex':1,'currentEquip':None}]
        started = begin(client,token,payload,key='terminal')
        assert started.status_code == 200,started.text
        with runtime.database.transaction(write=False) as session:
            hp = session.query(m.RogueTopicRun).one().hp + runtime.data.rogue_initial.battle_temporary_hp
            recruits = session.query(m.RogueRunChar).count()
        trace = journal()
        trace['journal']['squad'] = trace['journal']['squad'][:1]
        trace['journal']['metadata']['stageId'] = 'ro1_b_6'
        result = complete(client,token,started.json()['battleId'],trace,hp,'final-finish',stageId='ro1_b_6')
        assert result.status_code == 200,result.text
        record = current(runtime,token)['player']['pending'][0]['content']['result']['record']
        assert record['relicList'] == [R26]
        settled = post(client,token,'gameSettle',{},'full-settle')
        assert settled.status_code == 200,settled.text
    with runtime.database.transaction(write=False) as session:
        result = session.query(m.RogueGameSettlement).one()
        assert result.facts['counts'] == [5,5,0,0,2,1,recruits]
    before = runtime.sync(token)['user']
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)['user'] == before
        backups = BackupService(reopened)
        backups.restore(backups.create()['name'])
        assert reopened.sync(token)['user'] == before
    finally:
        reopened.database.close()


@pytest.mark.parametrize('battle_first',[False,True])
def test_cross_source_duplicate_is_rejected_before_publishing_either_plan(cost_runtime,battle_first):
    from terralocal.server.domain.rogue_shops import prepare as save_shops
    from terralocal.server.gamedata.rogue_shops import Offer, compile_shop

    runtime,token = cost_runtime
    spec = configured(runtime,token,install=battle_first)
    quote = compile_shop(runtime.data,'overlap',(Offer('r',R25,1,relic_layer=0),),evidence='Explicit QA stock')
    if not battle_first:
        with runtime.database.transaction() as session:
            save_shops(Context(session,runtime.data,1),{Point(1,0):quote})
    before = rows(runtime.database.path)
    with pytest.raises(DomainError):
        with runtime.database.transaction() as session:
            ctx = Context(session,runtime.data,1)
            if battle_first:
                save_shops(ctx,{Point(1,0):quote})
            else:
                prepare(ctx,{Point(0,0):spec})
    assert rows(runtime.database.path) == before


def test_shop_then_battle_relic_sources_replay_in_node_order_and_keep_old_quote(cost_runtime):
    from terralocal.server.domain.rogue_shops import prepare as save_shops
    from terralocal.server.gamedata.rogue_shops import Offer, compile_shop

    runtime,token = cost_runtime
    with runtime.database.transaction() as session:
        save_map(Context(session,runtime.data,1),Plan('zone_1',(
            Column(1,1,(Entry('SHOP',1),)),Column(1,1,(Entry('BATTLE_NORMAL',1,'ordinary'),))),0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client,token,'finishEvent',{},'mixed-map').status_code == 200
    quote = compile_shop(runtime.data,'earlier-shop',(Offer('r',R25,1,relic_layer=0),),evidence='Earlier owned QA source')
    with runtime.database.transaction() as session:
        ctx = Context(session,runtime.data,1)
        save_shops(ctx,{Point(0,0):quote})
        prepare(ctx,{Point(1,0):RelicGroups(((R26,R27),),frozenset({R26,R27}),'Later explicit QA source')})
    with runtime.database.transaction(write=False) as session:
        old_quote = copy.deepcopy(session.query(m.RogueShopVisit).one().quote)
        old_hash = session.query(m.RogueShopVisit).one().rule_hash
    with TestClient(create_game_app(runtime)) as client:
        assert post(client,token,'moveTo',{'to':{'x':0,'y':0}},'mixed-shop').status_code == 200
        assert post(client,token,'shopAction',{'buy':['r'],'recycle':[],'leave':0},'mixed-buy').status_code == 200
        assert post(client,token,'shopAction',{'buy':[],'recycle':[],'leave':1},'mixed-leave').status_code == 200
        finish_new(runtime,token,client,x=1)
        assert post(client,token,'chooseBattleReward',{'index':2,'sub':0},'mixed-relic').status_code == 200
        assert post(client,token,'finishBattleReward',{},'mixed-close').status_code == 200
    with runtime.database.transaction(write=False) as session:
        inventory = session.query(m.RogueRunRelic).filter(m.RogueRunRelic.ordinal>0).order_by(m.RogueRunRelic.ordinal).all()
        assert [r.item_id for r in inventory] == [R25,R26]
        assert inventory[0].acquired_at == inventory[1].acquired_at  # Ordering is causal, not a timestamp sort.
        assert session.query(m.RogueShopVisit).one().quote == old_quote
        assert session.query(m.RogueShopVisit).one().rule_hash == old_hash
    before = runtime.sync(token)['user']
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)['user'] == before
        backups = BackupService(reopened)
        backups.restore(backups.create()['name'])
        assert reopened.sync(token)['user'] == before
    finally:
        reopened.database.close()


def test_rehashed_changed_plan_still_cannot_change_a_started_battle(cost_runtime):
    from terralocal.server.domain.rogue_loot_plans import binding

    runtime,token = cost_runtime
    configured(runtime,token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime,token,client)
    with runtime.database.transaction() as session:
        plan = session.query(m.RogueBattleLootPlan).one()
        plan.spec,_ = compile_groups(runtime.data,RelicGroups(((R27,),),frozenset({R27}),'Different source'),at=plan.spec['at'])
        plan.rule_hash = binding(session.get(m.RogueTopicRun,plan.run_id),plan)
    runtime.database.close()
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before


def test_multiple_groups_keep_their_own_subselection_and_monotone_claim_time(cost_runtime):
    runtime,token = cost_runtime
    configured(runtime,token,groups=((R25,),(R26,R27)))
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime,token,client)
        first = post(client,token,'chooseBattleReward',{'index':2,'sub':0},'group1')
        assert first.status_code == 200,first.text
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState,1).fixed_at -= 120
        second = post(client,token,'chooseBattleReward',{'index':3,'sub':1},'group2')
        assert second.status_code == 200,second.text
        reward = current(runtime,token)['player']['pending'][0]['content']['battleReward']
        assert [row['done'] for row in reward['rewards']] == [False,False,True,True]
    with runtime.database.transaction(write=False) as session:
        result = session.query(m.RogueBattleSettlement).one()
        assert [(c['index'],c['sub']) for c in result.claims] == [(2,0),(3,1)]
        assert all(c['at'] == result.created_at for c in result.claims)
        relics = session.query(m.RogueRunRelic).filter(m.RogueRunRelic.ordinal>0).order_by(m.RogueRunRelic.ordinal).all()
        assert [r.item_id for r in relics] == [R25,R27]


def test_other_valid_local_account_cannot_prepare_or_claim_owned_rewards(cost_runtime):
    from terralocal.server.domain.accounts import login

    runtime,token = cost_runtime
    spec = configured(runtime,token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime,token,client)
    with runtime.database.transaction() as session:
        other = login(session,runtime.settings,name='OtherDoctor')['secret']
        other_uid = session.get(m.Account,2).uid
    assert runtime.sync(other)['user']['status']['uid'] == other_uid
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        result = post(client,other,'chooseBattleReward',{'index':2,'sub':1},'foreign-claim')
        assert result.status_code in (403,409),result.text
    with pytest.raises(DomainError):
        with runtime.database.transaction() as session:
            prepare(Context(session,runtime.data,2),{Point(0,0):spec})
    assert rows(runtime.database.path) == before


def test_relic_claim_survives_restart_before_closing_reward(cost_runtime):
    runtime,token = cost_runtime
    configured(runtime,token)
    with TestClient(create_game_app(runtime)) as client:
        finish_new(runtime,token,client)
        assert post(client,token,'chooseBattleReward',{'index':2,'sub':2},'mid-relic').status_code == 200
    snapshot = runtime.sync(token)['user']
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)['user'] == snapshot
        backups = BackupService(reopened)
        backups.restore(backups.create()['name'])
        assert reopened.sync(token)['user'] == snapshot
        with TestClient(create_game_app(reopened)) as client:
            assert post(client,token,'chooseBattleReward',{'index':2,'sub':2},'mid-retry').status_code == 200
            assert post(client,token,'finishBattleReward',{},'mid-close').status_code == 200
        with reopened.database.transaction(write=False) as session:
            assert session.query(m.RogueRunRelic).filter(m.RogueRunRelic.ordinal>0).count() == 1
    finally:
        reopened.database.close()
