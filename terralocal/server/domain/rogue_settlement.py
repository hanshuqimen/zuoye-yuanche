"""Transactional IS2 ordinary clears, natural defeat and independent loot.

Natural defeat is recorded without clear rewards and projects an ending event.
Retreat, shield use, outer effects and elite loot
still need their own rules; they never become empty successful responses.
Uniform profession-ticket selection is a versioned LOCAL policy, not an
official drop-rate claim. All progress is replay-validated from saved facts.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

from sqlalchemy import select

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_progress import Layout, zone_for
from terralocal.server.domain.rogue_terminal import POLICY as TERMINAL_POLICY
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_rewards import FirstThemeBattleRewards
from terralocal.server.persistence import models as m

POLICY = "rogue1-perfect-ordinary-local-ticket-v1"
CURRENT_POLICY = "rogue1-ordinary-outcome-local-ticket-v2"
LOOT_POLICY = "rogue1-planned-battle-relic-outcomes-v1"
POLICIES = frozenset({POLICY, CURRENT_POLICY, TERMINAL_POLICY, LOOT_POLICY})
PROPERTIES = ("hp", "hp_max", "shield", "gold", "hope_max", "squad_capacity", "level", "max_level", "exp")


def invalid():
    return DomainError("ROGUE_SETTLEMENT_INCOMPATIBLE", "探索结算或领取记录不一致；请保留原存档", 503)


def rows(session, run_id):
    return session.scalars(select(m.RogueBattleSettlement).where(
        m.RogueBattleSettlement.run_id == run_id).order_by(m.RogueBattleSettlement.ordinal)).all()


def read_rows(con, run_id):
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "rlv2_battle_settlements" not in tables:
        return []  # Legacy schema is admitted read-only before its migration.
    result = []
    for raw in con.execute("SELECT s.*, b.gamedata_hash AS counter_gamedata_hash FROM rlv2_battle_settlements s "
                           "JOIN rlv2_battles b ON b.id=s.battle_id WHERE s.run_id=? ORDER BY s.ordinal", (run_id,)):
        value = dict(raw)
        for key in ("facts", "effects", "loot", "claims", "records"):
            value[key] = json.loads(value[key])
        validate_archives(value["records"], value["facts"], battle_id=value["battle_id"], run_id=run_id,
                          gamedata_hash=value.pop("counter_gamedata_hash"))
        del value["records"]
        result.append(SimpleNamespace(**value))
    return result


def validate_archives(records, facts, *, battle_id=None, run_id=None, gamedata_hash=None):
    try:
        if type(records) is not dict or set(records) not in ({"journal", "snapshot"},
                                                            {"journal", "snapshot", "counters"}):
            raise invalid()
        for key in ("journal", "snapshot"):
            value = records[key]
            if (type(value) is not str or not 1 <= len(value) <= 1_000_000
                    or hashlib.sha256(value.encode("ascii")).hexdigest() != facts[key]):
                raise invalid()
        if "counters" in records:
            from terralocal.server.domain.rogue_combat_records import read

            if None in (battle_id, run_id, gamedata_hash):
                raise invalid()
            read(records["counters"], battle_id=battle_id, run_id=run_id, gamedata_hash=gamedata_hash, facts=facts)
    except (UnicodeError, KeyError, TypeError) as exc:
        raise invalid() from exc


def initial(data, run):
    c = data.rogue_initial.configs[run.mode]
    return dict(zip(PROPERTIES, (c.hp, c.max_hp, c.shield, c.gold, c.hope, c.squad_capacity,
                                1, data.rogue_initial.max_level, 0), strict=True))


def require_branch(data, run, kind, before, policy):
    """One capability gate for new starts and historical outcome computation."""
    kinds = {"BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS"} if policy == LOOT_POLICY else {
        "BATTLE_BOSS" if policy == TERMINAL_POLICY else "BATTLE_NORMAL"}
    if (policy not in POLICIES or kind not in kinds
            or run.band_id != data.rogue_initial.band or before["shield"] != 0
            or run.mode != "NORMAL" or run.grade != 0):
        raise DomainError("ROGUE_FINISH_BRANCH", "此作战、分队或难度的完整结算尚未接通；原战斗保留", 501)


def capsule_effect(data, run, kind, capsule):
    if capsule is None:
        return 1, {}
    from terralocal.server.gamedata.rogue_capsules import require

    try:
        definition = require(data, capsule, at=run.created_at)
        if not definition.matches(kind) or definition.exp_multiplier != 2:
            raise ValueError("此剧目没有匹配的战斗结算效果")
        return definition.exp_multiplier, {"capsule": {"id": capsule, "rule": definition.digest}}
    except (ValueError, TypeError, KeyError) as exc:
        raise invalid() from exc


def gold_item(data, policy):
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    # Planned supply uses its explicit currency reference. Legacy policies
    # retain their original sole-GOLD rule and exact historical rule hashes.
    gold_ids = ([detail["gameConst"]["goldItemId"]] if policy == LOOT_POLICY else
                [key for key, value in detail["items"].items() if value.get("type") == "GOLD"])
    if len(gold_ids) != 1:
        raise DomainError("ROGUE_GOLD_ITEM", "主题源石锭物品定义未唯一匹配", 503)
    if detail["items"].get(gold_ids[0], {}).get("type") != "GOLD":
        raise DomainError("ROGUE_GOLD_ITEM", "主题源石锭引用未匹配", 503)
    return gold_ids[0]


def admit_start(data, run, battle, layout, relics, capsule=None):
    """Reject known unfinishable NEW battles before creating pending state.

    This is a read-only capability check, not synthetic battle telemetry. It
    grants no reward, supplies no map and does not alter existing battle rows
    or their retries. Unknown outcome/retreat branches still need evidence.
    """
    zone = zone_for(layout, battle)
    node = next(n for n in zone.nodes if (n.pos.x, n.pos.y) == (battle.node_x, battle.node_y))
    policy = battle_policy(battle, node.kind)
    before = {key: getattr(run, key) for key in PROPERTIES}
    require_branch(data, run, node.kind, before, policy)
    if policy == TERMINAL_POLICY:
        from terralocal.server.domain.rogue_terminal import validate

        validate(data, run, battle, layout, relics)
    else:
        gold_item(data, policy)
    base = FirstThemeBattleRewards(data).base(topic=run.topic_id, mode=run.mode, grade=run.grade,
        zone=zone.id, kind=node.kind, stage=battle.stage_id)
    multiplier, _ = capsule_effect(data, run, node.kind, capsule)
    gain = data.rogue_levels.gains(run.exp, run.exp + base.exp * multiplier)
    if gain.max_hp or gain.battle_char_limit:
        raise DomainError("ROGUE_LEVEL_EFFECT", "此升级的生命或部署上限效果尚未接通，未开始战斗", 501)


def compute(data, run, battle, zone_id, kind, before, facts, *, policy=CURRENT_POLICY, layout=None, relics=(), capsule=None):
    """Pure, deterministic effects; neither raw telemetry nor client rewards trusted."""
    require_branch(data, run, kind, before, policy)
    multiplier, capsule_proof = capsule_effect(data, run, kind, capsule)
    plan = getattr(battle, "_loot_plan", None)
    if policy == LOOT_POLICY:
        from terralocal.server.domain.rogue_loot_plans import binding
        from terralocal.server.gamedata.rogue_battle_loot import admit_groups

        if (plan is None or plan.rule_hash != binding(run, plan) or plan.stage_id != battle.stage_id
                or plan.kind != kind or plan.spec["at"] != run.created_at):
            raise invalid()
        admit_groups(data, plan.spec)
    keys = {"rank", "interrupt", "giveUp", "percent", "kills", "validKills", "duration", "leftHp",
            "snapshot", "journal"}
    if (type(facts) is not dict or set(facts) != keys
            or any(type(facts[k]) is not int for k in ("rank", "kills", "validKills", "duration", "leftHp"))
            or any(type(facts[k]) is not bool for k in ("interrupt", "giveUp"))
            or type(facts["percent"]) not in (int, float)
            or any(type(facts[k]) is not str or len(facts[k]) != 64
                   or any(c not in "0123456789abcdef" for c in facts[k]) for k in ("snapshot", "journal"))
            or not 0 <= facts["validKills"] <= facts["kills"] <= 100_000
            or not 0 <= facts["duration"] <= 86400):
        raise invalid()
    if policy == TERMINAL_POLICY:
        from terralocal.server.domain.rogue_terminal import compute as terminal

        return terminal(data, run, battle, zone_id, kind, before, facts, layout=layout, relics=relics,
                        exp_multiplier=multiplier, capsule_proof=capsule_proof)
    base = FirstThemeBattleRewards(data).base(topic=run.topic_id, mode=run.mode, grade=run.grade,
                                            zone=zone_id, kind=kind, stage=battle.stage_id)
    # Native v16 ro1_n_1_4: rank1, interrupt/giveUp=false, leftHp0,
    # percent2, kills/validKills1 and an empty actionKill snapshot. Snapshot
    # death rows are not assumed to equal every valid kill or HP loss.
    if (policy in (CURRENT_POLICY, LOOT_POLICY) and facts["rank"] == 1 and not facts["interrupt"] and not facts["giveUp"]
            and facts["leftHp"] == 0 and 0 <= facts["percent"] <= 100 and before["hp"] > 0):
        earn = dict.fromkeys(("exp", "populationMax", "squadCapacity", "hp", "shield", "maxHpUp"), 0)
        effects = {"zone": zone_id, "kind": kind, "before": before,
                   "after": before | {"hp": 0}, "earn": earn, "outcome": "DEFEAT", "isPerfect": False}
        rule = fingerprint({"policy": policy, "base": base.rule_hash, "outcome": "DEFEAT",
                            "band": run.band_id, "temporary_hp": data.rogue_initial.battle_temporary_hp}
                           | ({"loot_plan": plan.rule_hash} if plan else {}) | capsule_proof)
        return effects, [], rule
    # Frozen M81283 distinguishes rank2/3 by current versus maximum life;
    # loaded M66437 snapshots GetLifePoint(playerSide). Rank alone supplies
    # no loss amount. Use the bound base life pool and recorded current life.
    total_hp = before["hp"] + data.rogue_initial.battle_temporary_hp
    perfect = facts["rank"] == 3 and facts["leftHp"] == total_hp
    damaged_clear = policy in (CURRENT_POLICY, LOOT_POLICY) and facts["rank"] == 2 and 0 < facts["leftHp"] < total_hp
    if (not (perfect or damaged_clear) or facts["interrupt"] or facts["giveUp"] or facts["percent"] != 100
            or before["hp"] <= 0):
        raise DomainError("ROGUE_FINISH_BRANCH", "结果、生命或中止标志不符合已接通分支；原战斗保留", 501)
    curve = data.rogue_levels
    exp = base.exp * multiplier
    gains = curve.gains(before["exp"], before["exp"] + exp)
    if gains.max_hp or gains.battle_char_limit:
        raise DomainError("ROGUE_LEVEL_EFFECT", "此升级的生命或部署上限效果尚未接通", 501)
    after = before | {"exp": before["exp"] + exp, "level": gains.to_level,
        "hope_max": before["hope_max"] + gains.hope_max,
        "squad_capacity": before["squad_capacity"] + gains.squad_capacity}
    if policy in (CURRENT_POLICY, LOOT_POLICY):
        # The base flow has shield0 and only its per-battle life addition.
        # Current battle life includes that buffer (M84576/M66437). Discard
        # unused temporary lives; never turn them into permanent HP or heal
        # beyond the saved pre-battle amount. Other modifiers stay unsupported.
        after["hp"] = min(before["hp"], facts["leftHp"])
    pool = sorted(data.rogue_recruit.tickets)
    if not pool:
        raise invalid()
    seed = fingerprint({"policy": policy, "run": run.seed, "battle": battle.id, "pool": pool})
    ticket = pool[int(seed, 16) % len(pool)]
    gold = gold_item(data, policy)
    loot = [{"id": gold, "count": base.gold, "kind": "GOLD"},
            {"id": ticket, "count": 1, "kind": "RECRUIT_TICKET"}]
    if policy == LOOT_POLICY:
        from terralocal.server.gamedata.rogue_battle_loot import loot as relic_loot

        loot += relic_loot(plan.spec)
    rule = fingerprint({"policy": policy, "base": base.rule_hash, "levels": curve.fingerprint,
                        "pool": pool, "gold": gold} | ({"loot_plan": plan.rule_hash} if plan else {}) | capsule_proof)
    earn = {"exp": exp, "populationMax": gains.hope_max, "squadCapacity": gains.squad_capacity,
            "hp": after["hp"] - before["hp"], "shield": 0, "maxHpUp": 0}
    effects = {"zone": zone_id, "kind": kind, "before": before, "after": after, "earn": earn}
    if policy in (CURRENT_POLICY, LOOT_POLICY):
        effects |= {"outcome": "CLEAR", "isPerfect": perfect}
    return effects, loot, rule


def battle_policy(battle, kind):
    if getattr(battle, "_loot_plan", None) is not None:
        return LOOT_POLICY
    return TERMINAL_POLICY if kind == "BATTLE_BOSS" else CURRENT_POLICY


def relic_grants(row):
    """Read only replay-validated claim sources; never count unclaimed options."""
    if row.policy_version != LOOT_POLICY:
        return ()
    from terralocal.server.gamedata.rogue_battle_loot import selected

    return tuple((selected(row.loot[c["index"]], c["sub"]), c["at"]) for c in row.claims
                 if row.loot[c["index"]]["kind"] == "RELIC_CHOICE")


def replay(data, run, records, battles, zone, tickets, scenes=(), draft=None, costs=(), shops=()):
    """Replay independent scene/battle writes in the same edge-bound history."""
    from terralocal.server.domain import rogue_shops, rogue_visits
    from terralocal.server.domain.rogue_capsules import History as CapsuleHistory
    from terralocal.server.domain.rogue_relics import Replay, resources_after_relic
    from terralocal.server.domain.rogue_support_tools import ToolHistory

    state, extras = initial(data, run), {}
    try:
        relic_history = Replay(data, tickets)
        tool_history = ToolHistory(data, run)
        capsule_history = CapsuleHistory(data, run)
        relic_history.capacity(state["squad_capacity"])
        elite_scopes = {}
        direct_scopes = {}
        relic_programs = [s.program_id for s in scenes if s.program_id in rogue_visits.RELIC_PROGRAMS]
        if len(relic_programs) != len(set(relic_programs)):
            raise invalid()
        if len(records) > (512 if isinstance(zone, Layout) else 256) or [r.ordinal for r in records] != list(range(len(records))):
            raise invalid()
        for scene in scenes:
            rogue_visits.validate(data, run, draft, zone, scene, costs)
        for shop in shops:
            rogue_shops.validate(data, run, draft, zone, shop)
        entries = rogue_visits.timeline(run, zone, battles, scenes, records, shops)[0]
        by_battle = {r.battle_id: r for r in records}
        ordinal = 0
        for _, _, kind, battle in entries:
            from terralocal.server.domain.rogue_progress import row_index

            capsule_history.floor(row_index(battle))
            if kind == "shop":
                q, paid = rogue_shops.validate(data, run, draft, zone, battle)
                if canonical(battle.before) != canonical(state) or battle.first_ticket != 3 + len(extras):
                    raise invalid()
                state = state | {"gold": paid.gold}
                for purchase in paid.purchases:
                    if purchase.index in q.support_indices:
                        tool_history.acquire(battle, purchase, q.offers[purchase.index],
                            recruit_pending=any(relic_history.tickets[i].state != "DONE"
                                                for i in relic_history.issued))
                        continue
                    if purchase.ticket is None:
                        relic_history.relic(q.offers[purchase.index], purchase.at)
                        key = q.offers[purchase.index].item_id
                        state = resources_after_relic(data, key, state, credit_gold=False)
                        relic_history.capacity(state["squad_capacity"])
                        continue
                    extras[purchase.ticket] = q.offers[purchase.index].item_id, purchase.at
                    relic_history.ticket(purchase.ticket)
                    elite_scopes[purchase.ticket] = list(q.offers[purchase.index].elite_pool)
                    direct_scopes[purchase.ticket] = list(q.offers[purchase.index].direct_pool)
                continue
            if kind == "scene":
                node = next(n for n in zone_for(zone, battle).nodes if n.pos == Point(battle.node_x, battle.node_y))
                state = capsule_history.enter(battle, node.kind, state)
                state = rogue_visits.apply(data, run, draft, zone, battle, costs, state,
                                           capacity_observer=relic_history.capacity)
                capsule_history.finish(battle)
                for index, item_id, at in rogue_visits.acquisitions(battle):
                    if index is None:
                        if battle.program_id not in rogue_visits.CONFIGURED_PROGRAMS:
                            data.rogue_battle_attributes.require_open(item_id, run.created_at)
                        relic_history.relic(SimpleNamespace(item_id=item_id, relic_layer=0), at)
                    else:
                        if type(index) is not int or index != 3 + len(extras):
                            raise invalid()
                        extras[index] = item_id, at
                        relic_history.ticket(index)
                continue
            graph = zone_for(zone, battle)
            node = next(n for n in graph.nodes if n.pos == Point(battle.node_x, battle.node_y))
            capsule = capsule_history.battle(battle, node.kind)
            tool_history.bind_battle(battle)
            if battle.state != "FINISHED":
                capsule_history.finish(battle)
                continue  # A started/abandoned terminal has no reward effect.
            row = by_battle[battle.id]
            if (row.ordinal != ordinal or row.run_id != run.id or row.policy_version not in POLICIES
                    or type(row.created_at) is not int or row.created_at != battle.ended_at
                    or row.created_at < battle.started_at):
                raise invalid()
            ordinal += 1
            point = Point(battle.node_x, battle.node_y)
            node = next(n for n in graph.nodes if n.pos == point)
            if getattr(battle, "_loot_plan", None) is not None and row.policy_version != LOOT_POLICY:
                raise invalid()
            effects, loot, rule = compute(data, run, battle, graph.id, node.kind, state, row.facts,
                                          policy=row.policy_version, layout=zone,
                                          relics=tuple(g.item_id for g in relic_history.grants), capsule=capsule)
            if (row.rule_hash != rule or canonical(row.effects) != canonical(effects)
                    or canonical(row.loot) != canonical(loot) or type(row.claims) is not list
                    or len(row.claims) > len(loot)):
                raise invalid()
            state, seen = effects["after"].copy(), set()
            capsule_history.finish(battle)
            relic_history.capacity(state["squad_capacity"])
            boundary = row.created_at
            for claim in row.claims:
                expected_keys = {"index", "at", "ticket"} | ({"sub"} if row.policy_version == LOOT_POLICY else set())
                if (type(claim) is not dict or set(claim) != expected_keys
                        or type(claim["index"]) is not int or claim["index"] not in range(len(loot))
                        or claim["index"] in seen or type(claim["at"]) is not int
                        or not boundary <= claim["at"] <= 2**63 - 1):
                    raise invalid()
                seen.add(claim["index"])
                boundary = claim["at"]
                item = loot[claim["index"]]
                if item["kind"] == "RELIC_CHOICE":
                    from terralocal.server.gamedata.rogue_battle_loot import selected

                    if claim["ticket"] is not None:
                        raise invalid()
                    chosen = selected(item, claim["sub"])
                    relic_history.relic(SimpleNamespace(item_id=chosen, relic_layer=0), claim["at"])
                    state = resources_after_relic(data, chosen, state)
                    relic_history.capacity(state["squad_capacity"])
                elif item["kind"] == "GOLD":
                    if claim["ticket"] is not None:
                        raise invalid()
                    state["gold"] += item["count"]
                elif item["kind"] == "CAPSULE":
                    if claim["ticket"] is not None:
                        raise invalid()
                    capsule_history.acquire(battle, claim["index"], item["id"], claim["at"])
                else:
                    index = claim["ticket"]
                    if type(index) is not int or index != 3 + len(extras):
                        raise invalid()
                    extras[index] = item["id"], claim["at"]
                    relic_history.ticket(index)
                if row.policy_version == LOOT_POLICY and item["kind"] != "RELIC_CHOICE" and (
                        type(claim["sub"]) is not int or claim["sub"] != 0):
                    raise invalid()
            if row.completed_at is not None:
                if effects.get("outcome") in ("DEFEAT", "SUCCESS"):
                    raise invalid()  # Defeat acknowledgement has its own ledger.
                if type(row.completed_at) is not int or not boundary <= row.completed_at <= 2**63 - 1:
                    raise invalid()
                boundary = row.completed_at
            if run.ended_at is not None and boundary > run.ended_at:
                raise invalid()
        if {b.id for b in battles if b.state == "FINISHED"} != set(by_battle):
            raise invalid()
        if {t.ordinal: (t.item_id, t.created_at) for t in tickets if t.ordinal >= 3} != extras:
            raise invalid()
        if any(getattr(t, "elite_pool", []) != elite_scopes.get(t.ordinal, []) for t in tickets):
            raise invalid()
        if any(getattr(t, "direct_pool", []) != direct_scopes.get(t.ordinal, []) for t in tickets):
            raise invalid()
        result = relic_history.finish(state)
        result.support_tool, result.support_tool_grants = tool_history.current, tuple(tool_history.grants)
        result.support_tool_battles = tool_history.battle_bindings
        from terralocal.server.domain.rogue_progress import index

        capsule_history.floor(index(zone))
        result.capsule_history, result.capsule_grants = capsule_history, tuple(capsule_history.grants)
        return result
    except (KeyError, TypeError, ValueError, AttributeError, StopIteration, DomainError) as exc:
        raise invalid() from exc


def normalize(record):
    f = record.facts
    hp = f.battleData.stats.get("leftHp")
    if record.journal is None:
        raise DomainError("ROGUE_JOURNAL_REQUIRED", "此结算分支需要与开战阵容匹配的战斗记录")
    return {"rank": f.completeState, "interrupt": f.interrupt, "giveUp": f.giveUp, "percent": f.percent,
            "kills": f.killCnt, "validKills": f.validKillCnt, "duration": f.battleData.completeTime,
            "leftHp": hp, "snapshot": record.snapshot.sha256, "journal": record.journal.sha256}


def state_in_session(ctx, run, tickets):
    records = rows(ctx.session, run.id)
    from terralocal.server.domain import rogue_loot_plans, rogue_shops, rogue_visits

    scenes = rogue_visits.rows(ctx.session, run.id)
    shops = rogue_shops.rows(ctx.session, run.id)
    battles = ctx.session.scalars(select(m.RogueBattle).where(m.RogueBattle.run_id == run.id)).all()
    draft = ctx.session.get(m.RogueMapDraft, run.id)
    plans = rogue_loot_plans.rows(ctx.session, run.id)
    from terralocal.server.domain.rogue_content import check_session

    check_session(ctx, run, draft, scenes, shops, plans)
    rogue_loot_plans.attach(ctx.data, run, draft, plans, battles,
                           reserved=rogue_loot_plans.other_candidate_ids(shops, scenes, data=ctx.data, run=run, draft=draft) if plans else ())
    cursor = ctx.session.get(m.RogueFloorCursor, run.id)
    if not records and not scenes and not shops and not battles and (cursor is None or not cursor.journal):
        return None
    from terralocal.server.domain.rogue_progress import in_session

    zone = in_session(ctx, run)
    return replay(ctx.data, run, records, battles, zone, tickets, scenes,
                  draft, rogue_visits.costs_in_session(ctx.session, run.id), shops)


def state_on_disk(data, con, run, tickets):
    records = read_rows(con, run.id)
    from terralocal.server.domain import rogue_loot_plans, rogue_shops, rogue_visits

    scenes = rogue_visits.read_rows(con, run.id)
    shops = rogue_shops.read_rows(con, run.id)
    plans = rogue_loot_plans.read_rows(con, run.id)
    from terralocal.server.domain.rogue_content import check_disk

    check_disk(data, con, run, scenes, shops, plans)
    has_battles = con.execute("SELECT 1 FROM rlv2_battles WHERE run_id=? LIMIT 1", (run.id,)).fetchone() if con.execute(
        "SELECT 1 FROM sqlite_master WHERE name='rlv2_battles'").fetchone() else None
    cursor = con.execute("SELECT journal FROM rlv2_floor_cursors WHERE run_id=?", (run.id,)).fetchone() if con.execute(
        "SELECT 1 FROM sqlite_master WHERE name='rlv2_floor_cursors'").fetchone() else None
    if not plans and not records and not scenes and not shops and not has_battles and (cursor is None or json.loads(cursor[0]) == []):
        return None
    from terralocal.server.domain.rogue_progress import on_disk

    raw = con.execute("SELECT * FROM rlv2_map_drafts WHERE run_id=?", (run.id,)).fetchone()
    if raw is None:
        raise invalid()
    draft = SimpleNamespace(**dict(raw))
    draft.plan, draft.graph = json.loads(draft.plan), json.loads(draft.graph)
    zone = on_disk(data, con, run, draft)
    battles = [SimpleNamespace(**dict(r)) for r in con.execute("SELECT * FROM rlv2_battles WHERE run_id=?", (run.id,))]
    rogue_loot_plans.attach(data, run, draft, plans, battles,
                           reserved=rogue_loot_plans.other_candidate_ids(shops, scenes, data=data, run=run, draft=draft) if plans else ())
    return replay(data, run, records, battles, zone, tickets, scenes, draft,
                  rogue_visits.costs_on_disk(con, run.id), shops)


def finish(ctx, request):
    from terralocal.server.domain import rogue_battle, rogue_combat_records
    from terralocal.server.protocol.battle_codec import signature_battle_id

    record = rogue_battle.inspect_finish(ctx, request)
    battle = ctx.session.get(m.RogueBattle, signature_battle_id(request.battleData.isCheat))
    progress = []
    run, _, zone, _ = rogue_battle.context(ctx, progress_out=progress)
    facts = normalize(record)
    counters = rogue_combat_records.archive(record.counters, battle_id=battle.id, run_id=run.id,
                                            gamedata_hash=battle.gamedata_hash, facts=facts)
    old = ctx.session.get(m.RogueBattleSettlement, battle.id)
    if old:
        # Never backfill an older receipt from a later request. New receipts
        # bind their selected counters as well as the existing reward facts.
        if (canonical(old.facts) != canonical(facts)
                or "counters" in old.records and old.records["counters"] != counters):
            raise DomainError("ROGUE_FINISH_CONFLICT", "此战斗已有不同结算；未重复发奖", 409)
        return response()
    if battle.state != "STARTED":
        raise DomainError("ROGUE_BATTLE_ENDED", "此探索战斗不能再次结算", 409)
    node = next(n for n in zone.nodes if (n.pos.x, n.pos.y) == (battle.node_x, battle.node_y))
    before = {key: getattr(run, key) for key in PROPERTIES}
    policy = battle_policy(battle, node.kind)
    relics = tuple(ctx.session.scalars(select(m.RogueRunRelic.item_id).where(
        m.RogueRunRelic.run_id == run.id, m.RogueRunRelic.ordinal > 0).order_by(m.RogueRunRelic.ordinal)))
    capsules = getattr(progress[0], "capsule_history", None)
    capsule = capsules.battle(battle, node.kind) if capsules is not None else None
    effects, loot, rule = compute(ctx.data, run, battle, zone.id, node.kind, before, facts,
                                  policy=policy, layout=zone, relics=relics, capsule=capsule)
    prior = rows(ctx.session, run.id)
    ended = max(ctx.now, battle.started_at)
    saved = m.RogueBattleSettlement(battle_id=battle.id, run_id=run.id, ordinal=len(prior),
        policy_version=policy, rule_hash=rule, facts=facts, effects=effects, loot=loot, claims=[],
        records={"journal": record.journal.encoded, "snapshot": record.snapshot.encoded}
                | ({"counters": counters} if counters is not None else {}),
        created_at=ended, completed_at=None)
    ctx.session.add(saved)
    battle.state, battle.ended_at = "FINISHED", ended
    for key, value in effects["after"].items():
        setattr(run, key, value)
    ctx.session.flush()
    return response()


def response():
    return {"apFailReturn": 0, **{key: [] for key in ("itemReturn", "rewards", "unusualRewards",
        "overrideRewards", "additionalRewards", "diamondMaterialRewards", "furnitureRewards")}}


def pending(row, run=None, history=(), *, relics=(), tools=(), capsules=()):
    if row.effects.get("outcome") in ("DEFEAT", "SUCCESS"):
        if run is None:
            raise invalid()
        # The caller supplies replay-validated non-band inventory for every
        # ending. Ordinary defeat must retain it just like the terminal boss;
        # this display neither grants items nor calculates score/unlocks.
        success = row.effects.get("outcome") == "SUCCESS"
        brief = {"level": run.level, "success": int(success), "ending": row.effects.get("ending"), "failEnding": None,
                 "theme": run.topic_id, "mode": run.mode, "predefined": None, "band": run.band_id,
                 "startTs": run.created_at, "endTs": row.created_at, "endZoneId": row.effects["zone"],
                 "modeGrade": run.grade, "seed": str(run.seed), "activity": None}
        terminal = row.policy_version == TERMINAL_POLICY
        record = {"cntZone": 5 if terminal else len({r.effects["zone"] for r in history}),
                  "relicList": list(relics), "capsuleList": list(capsules),
                  "activeToolList": list(tools), "charBuff": [], "squadBuff": [], "totemList": [],
                  "exploreToolList": [], "fragmentList": [], "copperCounter": {}, "scrapCounter": {},
                  "legacyList": []}
        return {"index": row.battle_id, "type": "GAME_SETTLE", "content": {
            "result": {"brief": brief, "record": record}, "done": False}}
    claimed = {c["index"] for c in row.claims}
    return {"index": row.battle_id, "type": "BATTLE_REWARD", "content": {"battleReward": {
        "rewards": [{"index": str(i), "items": item["items"] if item["kind"] == "RELIC_CHOICE" else [
                         {"id": item["id"], "count": item["count"], "sub": 0}],
                     "done": i in claimed, "exDrop": False, "exDropSrc": ""}
                    for i, item in enumerate(row.loot)], "earn": row.effects["earn"],
        "show": "1", "state": 0, "isPerfect": int(row.effects.get("isPerfect", True))}}}


def current(ctx):
    from terralocal.server.domain.rogue_runs import active

    if ctx.local_session is None or ctx.local_session.kind != "game":
        raise DomainError("INVALID_SESSION", "请使用游戏登录处理探索奖励", 401)
    run, children = active(ctx, required=True)
    records = rows(ctx.session, run.id)
    if (not records or records[-1].completed_at is not None or run.state != "MAP_READY"
            or records[-1].effects.get("outcome") in ("DEFEAT", "SUCCESS")):
        raise DomainError("ROGUE_REWARD_NOT_PENDING", "当前没有待处理的战斗奖励", 409)
    return run, children, records[-1]


def claim(ctx, index, sub):
    run, children, row = current(ctx)
    if type(index) is not int or index not in range(len(row.loot)) or type(sub) is not int:
        raise DomainError("ROGUE_REWARD_SELECTION", "奖励或选项不属于当前结算")
    item, chosen = row.loot[index], None
    if item["kind"] == "RELIC_CHOICE":
        from terralocal.server.gamedata.rogue_battle_loot import selected

        try:
            chosen = selected(item, sub)
        except ValueError as exc:
            raise DomainError("ROGUE_REWARD_SELECTION", "收藏品选项不属于当前奖励组") from exc
    elif sub != 0:
        raise DomainError("ROGUE_REWARD_SELECTION", "奖励或选项不属于当前结算")
    old = next((c for c in row.claims if c["index"] == index), None)
    if old is not None:
        if old.get("sub", 0) != sub:
            raise DomainError("ROGUE_REWARD_CONFLICT", "此奖励组已领取其他选项，未重复发奖", 409)
        return {}  # New sequence replays a claim without a second grant.
    if any(t.state == "ACTIVE" for t in children[2]):
        raise DomainError("ROGUE_RECRUIT_PENDING", "请先处理当前招募", 409)
    at = max(ctx.now, row.created_at, *(c["at"] for c in row.claims))
    ticket = None
    if chosen is not None:
        if any(t.state != "DONE" for t in children[2]):
            raise DomainError("ROGUE_RECRUIT_PENDING", "请先处理全部招募，再领取收藏品", 409)
        if any(r.item_id == chosen for r in children[1]):
            raise DomainError("ROGUE_RELIC_ALREADY_OWNED", "探索已持有此无叠层收藏品", 409)
        from terralocal.server.domain.rogue_relics import resources_after_relic

        try:
            resources = resources_after_relic(ctx.data, chosen,
                {"gold": run.gold, "hope_max": run.hope_max, "squad_capacity": run.squad_capacity,
                 "hp": run.hp, "hp_max": run.hp_max})
        except ValueError as exc:
            raise DomainError("ROGUE_REWARD_RESOURCE_LIMIT", "即时资源奖励超出范围，未领取", 409) from exc
        ctx.session.add(m.RogueRunRelic(run_id=run.id, ordinal=len(children[1]), item_id=chosen,
            count=1, layer=0, acquired_at=at, used=False))
        run.gold, run.hope_max, run.squad_capacity = resources["gold"], resources["hope_max"], resources["squad_capacity"]
        run.hp = resources["hp"]
    elif item["kind"] == "GOLD":
        run.gold += item["count"]
    elif item["kind"] == "CAPSULE":
        if any(t.state != "DONE" for t in children[2]):
            raise DomainError("ROGUE_RECRUIT_PENDING", "请先处理全部招募，再领取剧目", 409)
        from terralocal.server.gamedata.rogue_capsules import require

        require(ctx.data, item["id"], at=run.created_at)
    else:
        ticket = len(children[2])
        ctx.session.add(m.RogueRunTicket(run_id=run.id, ordinal=ticket, item_id=item["id"],
                                        state="CREATE", created_at=at))
    row.claims = row.claims + [{"index": index, "at": at, "ticket": ticket}
                              | ({"sub": sub} if row.policy_version == LOOT_POLICY else {})]
    ctx.session.flush()
    if ticket is not None:
        from terralocal.server.domain.rogue_recruit import activate

        activate(ctx, str(ticket))  # Offer creation and claim commit together.
    return {}


def close(ctx):
    """Finish only the owned last battle reward, including a harmless close retry.

    The frozen reward-list handler constructs FinishNodeRequest but sends it
    to finishBattleReward (native v26), not a type-name-derived route.
    This is not a scene/initial-event/floor-transition shortcut.
    """
    from terralocal.server.domain.rogue_map_drafts import current_map
    from terralocal.server.domain.rogue_runs import active
    from terralocal.server.domain.rogue_visits import authorize, path_in_session

    authorize(ctx)
    run, children = active(ctx, required=True)
    zone = current_map(ctx, run, children[0])
    records = rows(ctx.session, run.id)
    entries, _, boundary, _ = path_in_session(ctx, run, zone, whole=True)
    if (run.state != "MAP_READY" or zone is None or not records or not entries
            or entries[-1][2] != "battle" or entries[-1][3].id != records[-1].battle_id
            or records[-1].effects.get("outcome") in ("DEFEAT", "SUCCESS") or run.hp <= 0):
        raise DomainError("ROGUE_REWARD_NOT_PENDING", "当前不是可结束的战斗奖励节点", 409)
    row = records[-1]
    if any(t.state != "DONE" for t in children[2]):
        raise DomainError("ROGUE_RECRUIT_PENDING", "招募尚未处理完，未离开奖励页", 409)
    if row.completed_at is not None:
        from terralocal.server.domain.rogue_progress import advance

        advance(ctx)
        return {}  # Same logical close on a new sequence cannot move or grant again.
    # Unclaimed loot is explicitly forfeited; it never reaches any wallet.
    row.completed_at = max(ctx.now, row.created_at, boundary)
    ctx.session.flush()
    from terralocal.server.domain.rogue_progress import advance

    advance(ctx)
    return {}


def preflight(path):
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        from terralocal.server.persistence.migrations import (
            CURRENT_REVISIONS,
            ROGUE_ENDING_REVISION,
            ROGUE_SCENE_REVISION,
            ROGUE_SETTLEMENT_REVISION,
        )

        version = con.execute("SELECT version_num FROM alembic_version").fetchone() \
            if "alembic_version" in tables else None
        if "rlv2_battle_settlements" not in tables:
            if version and version[0] in (*CURRENT_REVISIONS, ROGUE_SCENE_REVISION, ROGUE_ENDING_REVISION, ROGUE_SETTLEMENT_REVISION):
                raise ValueError(invalid().message)
            return
        if "rlv2_battles" not in tables:
            if con.execute("SELECT 1 FROM rlv2_battle_settlements LIMIT 1").fetchone():
                raise ValueError(invalid().message)
            return
        if (con.execute("SELECT 1 FROM rlv2_battle_settlements s LEFT JOIN rlv2_battles b "
                        "ON b.id=s.battle_id WHERE b.id IS NULL OR s.run_id!=b.run_id OR b.state!='FINISHED' LIMIT 1").fetchone()
                or con.execute("SELECT 1 FROM rlv2_battles b LEFT JOIN rlv2_battle_settlements s "
                               "ON b.id=s.battle_id WHERE b.state='FINISHED' AND s.battle_id IS NULL LIMIT 1").fetchone()):
            raise ValueError(invalid().message)
