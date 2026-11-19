"""Immutable, owned battle-relic supply; no client plan or random fallback."""

import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

from sqlalchemy import select

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_progress import row_index
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_battle_loot import POLICIES, admit_groups, compile_groups
from terralocal.server.persistence import models as m


def invalid():
    return DomainError("ROGUE_LOOT_PLAN_INCOMPATIBLE", "战斗收藏品方案与探索或完整效果不一致；请保留原存档", 503)


def rows(session, run_id):
    return session.scalars(select(m.RogueBattleLootPlan).where(m.RogueBattleLootPlan.run_id == run_id)
        .order_by(m.RogueBattleLootPlan.zone_index, m.RogueBattleLootPlan.node_x, m.RogueBattleLootPlan.node_y)).all()


def read_rows(con, run_id):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='rlv2_battle_loot_plans'").fetchone():
        return []
    result = []
    for raw in con.execute("SELECT * FROM rlv2_battle_loot_plans WHERE run_id=? ORDER BY zone_index,node_x,node_y", (run_id,)):
        values = dict(raw)
        values["spec"] = json.loads(values["spec"])
        result.append(SimpleNamespace(**values))
    return result


def key(row):
    return row_index(row), row.node_x, row.node_y


def candidate_ids(plans):
    return {item for plan in plans for group in plan.spec["groups"] for item in group}


def other_candidate_ids(shops, scenes, *, data=None, run=None, draft=None):
    """Local nonstack reservation; never an official encounter-pool rule."""
    from terralocal.server.domain.rogue_visits import CONFIGURED_PROGRAMS
    from terralocal.server.gamedata.rogue_relic_events import RELICS

    result = set()
    for shop in shops:
        result.update(o["item_id"] for o in shop.quote["offers"] if o.get("relic_layer") is not None)
    programs = {scene.program_id for scene in scenes}
    result.update(item for (program, _), item in RELICS.items() if program in programs)
    for scene in scenes:
        if scene.program_id in CONFIGURED_PROGRAMS:
            from terralocal.server.domain.rogue_content import bound_visit

            if data is None or run is None:
                raise invalid()
            result.update(bound_visit(data, run, draft, scene).reservations)
    return result


def binding(run, row):
    return fingerprint({"policy": row.policy_version, "run": run.id, "account": run.account_id, "data": run.gamedata_hash,
        "map": row.map_hash, "node": list(key(row)), "stage": row.stage_id, "kind": row.kind,
        "spec": row.spec, "prepared": row.prepared_at})


def graphs(data, run, draft):
    from terralocal.server.domain.rogue_map_drafts import validate_floors

    return validate_floors(data, run, draft)


def validate(data, run, draft, zones, row):
    try:
        number = row_index(row)
        if (run.topic_id != "rogue_1" or run.mode != "NORMAL" or run.grade != 0
                or draft.activated_at is None or number > len(zones)
                or row.account_id != run.account_id or row.run_id != run.id
                or row.policy_version not in POLICIES or row.gamedata_hash != run.gamedata_hash
                or row.map_hash != draft.plan_hash or row.rule_hash != binding(run, row)
                or type(row.prepared_at) is not int or row.prepared_at < draft.activated_at
                or row.prepared_at >= 2**63 or run.ended_at is not None and row.prepared_at > run.ended_at):
            raise invalid()
        group, _ = admit_groups(data, row.spec)
        if group["at"] != run.created_at or group["policy"] != row.policy_version:
            raise invalid()
        point = Point(row.node_x, row.node_y)
        point.validate()
        zone = zones[number - 1]
        node = next((n for n in zone.nodes if n.pos == point), None)
        if (node is None or node.kind != row.kind or node.stage != row.stage_id
                or node.kind not in ("BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS")):
            raise invalid()
        if "capsule" in group:
            # A supplied ordinary capsule must have a reachable trigger later
            # on THIS floor. This verifies possibility, not an official pool.
            from terralocal.server.gamedata.rogue_capsules import require

            definition = require(data, group["capsule"]["id"], at=run.created_at)
            reached, queue = set(), list(zone.successors(point))
            while queue:
                target = queue.pop()
                if target in reached:
                    continue
                reached.add(target)
                queue.extend(zone.successors(target))
            if not any(definition.matches(n.kind) and n.pos in reached for n in zone.nodes):
                raise invalid()
        data.rogue_map.require_placement(node.kind, node.stage, zone.id)
        if group.get("base_only", False):
            if node.kind != "BATTLE_NORMAL":
                raise invalid()
            from terralocal.server.gamedata.rogue_rewards import FirstThemeBattleRewards

            FirstThemeBattleRewards(data).base(topic=run.topic_id, mode=run.mode, grade=run.grade,
                                               zone=zone.id, kind=node.kind, stage=node.stage)
        if node.kind == "BATTLE_BOSS":
            # Reviewed middle bosses continue into zone4, never a final ending.
            if (number != 3 or len(zones) < 4 or tuple(z.id for z in zones[:4])
                    != ("zone_1", "zone_2", "zone_3", "zone_4") or node.next
                    or data.rogue_endings.cleared(node.stage, zone.id, ()).next_zone != "zone_4"):
                raise invalid()
        return group
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        raise invalid() from exc


def attach(data, run, draft, plans, battles, *, reserved=()):
    from terralocal.server.domain.rogue_battle import PLANNED_POLICIES

    zones = graphs(data, run, draft) if plans else ()
    mapping, candidates = {}, set(reserved)
    for plan in plans:
        validate(data, run, draft, zones, plan)
        ids = {item for group in plan.spec["groups"] for item in group}
        if key(plan) in mapping or ids & candidates:
            raise invalid()
        mapping[key(plan)] = plan
        candidates.update(ids)
    for battle in battles:
        plan = mapping.get(key(battle))
        if (battle.policy_version in PLANNED_POLICIES) != (plan is not None):
            raise invalid()
        if plan is not None and (plan.stage_id != battle.stage_id or plan.prepared_at > battle.started_at):
            raise invalid()
        battle._loot_plan = plan


def prepare(ctx, bindings, *, zone_index=None):
    """Trusted internal provider only; freeze eligibility/source before battle."""
    from terralocal.server.domain.rogue_progress import index
    from terralocal.server.domain.rogue_visits import context

    run, children, layout, draft = context(ctx)
    if any(t.state != "DONE" for t in children[2]):
        raise DomainError("ROGUE_RECRUIT_PENDING", "请先处理全部招募，再准备战斗奖励", 409)
    number = index(layout) if zone_index is None else zone_index
    if (type(number) is not int or number < index(layout) or type(bindings) is not dict
            or not 1 <= len(bindings) <= 64):
        raise invalid()
    zones = graphs(ctx.data, run, draft)
    if number > len(zones):
        raise invalid()
    existing = rows(ctx.session, run.id)
    reserved = other_candidate_ids(
        ctx.session.scalars(select(m.RogueShopVisit).where(m.RogueShopVisit.run_id == run.id)).all(),
        ctx.session.scalars(select(m.RogueSceneVisit).where(m.RogueSceneVisit.run_id == run.id)).all(),
        data=ctx.data, run=run, draft=draft)
    battles = ctx.session.scalars(select(m.RogueBattle).where(m.RogueBattle.run_id == run.id)).all()
    owned = {r.item_id for r in children[1]}
    for point, spec in bindings.items():
        if type(point) is not Point:
            raise invalid()
        value, _ = compile_groups(ctx.data, spec, at=run.created_at)
        old = next((p for p in existing if key(p) == (number, point.x, point.y)), None)
        if old is not None:
            validate(ctx.data, run, draft, zones, old)
            if canonical(old.spec) != canonical(value):
                raise DomainError("ROGUE_LOOT_PLAN_CONFLICT", "该节点已有不同战斗奖励，不能替换或重抽", 409)
            continue
        if any(key(b) == (number, point.x, point.y) for b in battles):
            raise DomainError("ROGUE_LOOT_PLAN_TOO_LATE", "战斗已开始，不能追加或更改奖励", 409)
        proposed = {item for group in value["groups"] for item in group}
        if proposed & (owned | candidate_ids(existing) | reserved):
            raise DomainError("ROGUE_LOOT_SUPPLY_CONFLICT", "无叠层奖励已经持有或配置到其他战斗", 409)
        node = next((n for n in zones[number - 1].nodes if n.pos == point), None)
        if node is None:
            raise invalid()
        row = m.RogueBattleLootPlan(run_id=run.id, zone_index=number, node_x=point.x, node_y=point.y,
            account_id=ctx.account_id, policy_version=value["policy"], gamedata_hash=run.gamedata_hash,
            map_hash=draft.plan_hash, stage_id=node.stage, kind=node.kind, spec=value,
            prepared_at=max(ctx.now, draft.activated_at), rule_hash="")
        row.rule_hash = binding(run, row)
        validate(ctx.data, run, draft, zones, row)
        ctx.session.add(row)
        existing.append(row)
    ctx.session.flush()


def preflight(data, path):
    """Validate before startup writes, including an additive old-schema read."""
    if not path.exists():
        return
    from terralocal.server.persistence.migrations import REVISION

    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = con.execute("SELECT version_num FROM alembic_version").fetchone() if "alembic_version" in tables else None
        if "rlv2_battle_loot_plans" not in tables:
            if version and version[0] == REVISION:
                raise ValueError(invalid().message)
            return
        try:
            ids = [r[0] for r in con.execute("SELECT DISTINCT run_id FROM rlv2_battle_loot_plans")]
            for run_id in ids:
                run = SimpleNamespace(**dict(con.execute("SELECT * FROM rlv2_runs WHERE id=?", (run_id,)).fetchone()))
                draft = SimpleNamespace(**dict(con.execute("SELECT * FROM rlv2_map_drafts WHERE run_id=?", (run_id,)).fetchone()))
                draft.plan, draft.graph = json.loads(draft.plan), json.loads(draft.graph)
                battles = [SimpleNamespace(**dict(r)) for r in con.execute("SELECT * FROM rlv2_battles WHERE run_id=?", (run_id,))]
                from terralocal.server.domain import rogue_shops, rogue_visits

                attach(data, run, draft, read_rows(con, run_id), battles,
                    reserved=other_candidate_ids(rogue_shops.read_rows(con, run_id), rogue_visits.read_rows(con, run_id),
                                                 data=data, run=run, draft=draft))
        except (ValueError, TypeError, KeyError, AttributeError, DomainError, sqlite3.DatabaseError) as exc:
            raise ValueError(invalid().message) from exc
