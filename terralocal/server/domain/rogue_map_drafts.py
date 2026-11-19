"""Transactional explicit map preparation and initial-event activation.

Missing floor plans fail closed. Preparing graphs alone grants no movement,
event completion, rewards or unlocks; finishEvent activates only a saved zone1.
An explicit floor sequence freezes future maps. Completed node transactions
advance its separately persisted cursor; preparation itself does not.
"""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from types import SimpleNamespace

from terralocal.server.domain import rogue_floors
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import (
    LEGACY_POLICY,
    POLICIES,
    POLICY,
    Plan,
    admit_plan,
    admit_wire,
    generate,
    plan_fingerprint,
)
from terralocal.server.gamedata.repository import canonical
from terralocal.server.persistence import models as m


def invalid():
    return DomainError("ROGUE_MAP_DRAFT_INCOMPATIBLE", "探索地图准备记录不兼容；请保留原存档", 503)


def validate_floors(data, run, draft):
    """Verify every saved floor, including unrevealed future recipes, read-only."""
    try:
        if (data is None or run.gamedata_hash != data.manifest["hash"] or run.topic_id != "rogue_1"
                or draft.run_id != run.id or draft.policy_version not in POLICIES | rogue_floors.FLOOR_POLICIES
                or draft.gamedata_hash != run.gamedata_hash or draft.seed != run.seed
                or run.recruit_group is None or run.state not in ("INIT_RECRUIT", "MAP_READY", "ABANDONED", "SETTLED")
                or type(draft.prepared_at) is not int or not run.created_at <= draft.prepared_at <= 2**63 - 1):
            raise invalid()
        activation = getattr(draft, "activated_at", None)  # Read-only schema0021 admission before migration.
        if activation is not None and (type(activation) is not int or not draft.prepared_at <= activation <= 2**63 - 1):
            raise invalid()
        if draft.policy_version == rogue_floors.CONTENT_POLICY:
            from terralocal.server.domain.rogue_content import validate as validate_content

            return validate_content(data, run, draft)[0]
        if draft.policy_version == rogue_floors.POLICY:
            spec = rogue_floors.admit_sequence(data.rogue_map, draft.plan)
            if draft.plan_hash != rogue_floors.plan_hash(spec):
                raise invalid()
            return rogue_floors.validate_graphs(data, spec, run.seed, draft.graph)
        spec = admit_plan(data.rogue_map, draft.plan)
        legacy = draft.policy_version == LEGACY_POLICY
        graph = admit_wire(data.rogue_map, draft.graph, legacy_keys=legacy)
        if (draft.plan_hash != plan_fingerprint(spec, policy=draft.policy_version)
                or canonical(generate(data, spec, run.seed, policy=draft.policy_version).wire(legacy_keys=legacy))
                != canonical(graph.wire(legacy_keys=legacy))):
            raise invalid()
        return (graph,)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise invalid() from exc


def validate(data, run, draft):
    """Existing single-floor drivers consume only floor1 until transition admission."""
    return validate_floors(data, run, draft)[0]


def prepare(ctx, spec):
    from terralocal.server.domain.rogue_runs import active

    run, children = active(ctx, required=True)
    if run.state != "INIT_RECRUIT" or any(t.state != "DONE" for t in children[2]):
        raise DomainError("ROGUE_MAP_DRAFT_NOT_READY", "请先处理完当前初始招募券；未生成地图", 409)
    if not isinstance(spec, Plan):
        raise invalid()
    spec.validate(ctx.data.rogue_map)
    draft = ctx.session.get(m.RogueMapDraft, run.id)
    if draft is not None:
        graph = validate(ctx.data, run, draft)
        if (draft.policy_version not in POLICIES
                or draft.plan_hash != plan_fingerprint(spec, policy=draft.policy_version)):
            raise DomainError("ROGUE_MAP_DRAFT_CONFLICT", "已有地图准备记录，不能替换方案或重抽", 409)
        return graph
    graph = generate(ctx.data, spec, run.seed)
    draft = m.RogueMapDraft(run_id=run.id, policy_version=POLICY,
                           gamedata_hash=run.gamedata_hash, seed=run.seed, plan=json.loads(canonical(asdict(spec))),
                           plan_hash=plan_fingerprint(spec), graph=graph.wire(),
                           prepared_at=max(run.created_at, ctx.now))
    ctx.session.add(draft)
    ctx.session.flush()
    return validate(ctx.data, run, draft)


def prepare_floors(ctx, spec):
    """Internal whole-sequence preparation; no live client selects floor recipes."""
    from terralocal.server.domain.rogue_runs import active

    run, children = active(ctx, required=True)
    if run.state != "INIT_RECRUIT" or any(t.state != "DONE" for t in children[2]):
        raise DomainError("ROGUE_MAP_DRAFT_NOT_READY", "请先处理完当前初始招募券；未生成地图", 409)
    if not isinstance(spec, rogue_floors.FloorSequence):
        raise invalid()
    spec.validate(ctx.data.rogue_map)
    digest = rogue_floors.plan_hash(spec)
    draft = ctx.session.get(m.RogueMapDraft, run.id)
    if draft is not None:
        graphs = validate_floors(ctx.data, run, draft)
        if draft.policy_version != rogue_floors.POLICY or draft.plan_hash != digest:
            raise DomainError("ROGUE_MAP_DRAFT_CONFLICT", "已有地图准备记录，不能替换方案或重抽", 409)
        return graphs
    graphs = rogue_floors.generate_sequence(ctx.data, spec, run.seed)
    draft = m.RogueMapDraft(run_id=run.id, policy_version=rogue_floors.POLICY,
        gamedata_hash=run.gamedata_hash, seed=run.seed, plan=json.loads(canonical(spec.saved())),
        plan_hash=digest, graph=rogue_floors.saved_graphs(graphs), prepared_at=max(run.created_at, ctx.now))
    ctx.session.add(draft)
    ctx.session.flush()
    return validate_floors(ctx.data, run, draft)


def read_floors(ctx):
    """Owned immutable preparation, including future floors; not gameplay wire."""
    from terralocal.server.domain.rogue_runs import active

    run, children = active(ctx, required=True)
    draft = ctx.session.get(m.RogueMapDraft, run.id)
    if draft is not None and any(t.state != "DONE" for t in children[2][:3]):
        raise invalid()
    return validate_floors(ctx.data, run, draft) if draft is not None else None


def read(ctx):
    """An account may inspect only the draft bound to its current active run."""
    from terralocal.server.domain.rogue_runs import active

    run, children = active(ctx, required=True)
    draft = ctx.session.get(m.RogueMapDraft, run.id)
    if draft is not None and any(t.state != "DONE" for t in children[2]):
        raise invalid()
    return validate(ctx.data, run, draft) if draft is not None else None


def current_map(ctx, run, events):
    draft = ctx.session.get(m.RogueMapDraft, run.id)
    completed = events[2].completed_at
    if draft is None:
        if completed is not None:
            raise invalid()
        return None
    graph = validate(ctx.data, run, draft)
    if draft.activated_at != completed:
        raise invalid()
    if completed is None:
        return None
    if graph.id != "zone_1":
        raise invalid()
    from terralocal.server.domain.rogue_progress import in_session

    return in_session(ctx, run, draft)


def finish_initial(ctx):
    from terralocal.server.domain.rogue_runs import active

    run, children = active(ctx, required=True)
    if run.state == "MAP_READY":
        from terralocal.server.domain.rogue_visits import finish_if_scene

        if finish_if_scene(ctx):
            return {}
        from terralocal.server.domain.rogue_battle import ensure_no_active
        from terralocal.server.domain.rogue_settlement import rows

        ensure_no_active(ctx)
        if any(r.completed_at is None for r in rows(ctx.session, run.id)):
            raise DomainError("ROGUE_REWARD_PENDING", "战斗奖励须由奖励页处理，未跳过事件", 409)
        current_map(ctx, run, children[0])  # Retry on a new sequence never regenerates/advances.
        return {}
    if run.state != "INIT_RECRUIT" or any(t.state != "DONE" for t in children[2]):
        raise DomainError("ROGUE_EVENT_ORDER", "初始招募尚未处理完，未完成事件", 409)
    ctx.data.rogue_topics.topic(run.topic_id, at=ctx.now)
    draft = ctx.session.get(m.RogueMapDraft, run.id)
    if draft is None:
        from terralocal.server.domain.rogue_content import prepare as prepare_content

        draft = prepare_content(ctx, run)
        if draft is None:
            raise DomainError("ROGUE_MAP_NOT_PREPARED", "缺少已接纳并保存的首层地图方案；未完成事件", 503)
    graph = validate(ctx.data, run, draft)
    if graph.id != "zone_1":
        raise DomainError("ROGUE_INITIAL_MAP_UNSUPPORTED", "此准备地图不是已接纳的首层区域", 501)
    if draft.activated_at is not None:
        raise invalid()
    ts = max(ctx.now, draft.prepared_at)
    draft.activated_at = children[0][2].completed_at = ts
    run.state = "MAP_READY"
    from terralocal.server.domain.rogue_progress import activate

    activate(ctx, run, draft)
    ctx.session.flush()
    from terralocal.server.domain.rogue_content import publish

    publish(ctx, run, draft)
    current_map(ctx, run, children[0])
    return {}


def preflight(data, path):
    """Reject damaged drafts read-only, before any startup migration or write."""
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        from terralocal.server.persistence.migrations import (
            CURRENT_REVISIONS,
            ROGUE_ACTIVATION_REVISION,
            ROGUE_BATTLE_REVISION,
            ROGUE_ENDING_REVISION,
            ROGUE_MAP_REVISION,
            ROGUE_SCENE_REVISION,
            ROGUE_SETTLEMENT_REVISION,
        )

        version = con.execute("SELECT version_num FROM alembic_version").fetchone() \
            if "alembic_version" in tables else None
        if "rlv2_map_drafts" not in tables:
            if version and version[0] in (*CURRENT_REVISIONS, ROGUE_SCENE_REVISION, ROGUE_ENDING_REVISION, ROGUE_SETTLEMENT_REVISION, ROGUE_BATTLE_REVISION,
                                          ROGUE_ACTIVATION_REVISION, ROGUE_MAP_REVISION):
                raise ValueError(invalid().message)
            return
        columns = {r[1] for r in con.execute("PRAGMA table_info(rlv2_map_drafts)")}
        if version and version[0] in (*CURRENT_REVISIONS, ROGUE_SCENE_REVISION, ROGUE_ENDING_REVISION, ROGUE_SETTLEMENT_REVISION, ROGUE_BATTLE_REVISION,
                                     ROGUE_ACTIVATION_REVISION) and "activated_at" not in columns:
            raise ValueError(invalid().message)
        if {"rlv2_runs", "rlv2_events"} <= tables and con.execute(
                "SELECT 1 FROM rlv2_runs r JOIN rlv2_events e ON e.run_id=r.id AND e.ordinal=2 "
                "LEFT JOIN rlv2_map_drafts d ON d.run_id=r.id "
                "WHERE e.completed_at IS NOT NULL AND d.run_id IS NULL LIMIT 1").fetchone():
            raise ValueError(invalid().message)
        drafts = list(con.execute("SELECT * FROM rlv2_map_drafts"))
        if not drafts:
            return
        try:
            if not {"rlv2_runs", "rlv2_tickets"} <= tables:
                raise invalid()
            for raw in drafts:
                values = dict(raw)
                values["plan"], values["graph"] = json.loads(values["plan"]), json.loads(values["graph"])
                draft = SimpleNamespace(**values)
                raw_run = con.execute("SELECT * FROM rlv2_runs WHERE id=?", (draft.run_id,)).fetchone()
                if raw_run is None:
                    raise invalid()
                tickets = con.execute("SELECT state FROM rlv2_tickets WHERE run_id=? AND ordinal<3",
                                      (draft.run_id,)).fetchall()
                if len(tickets) != 3 or any(t[0] != "DONE" for t in tickets):
                    raise invalid()
                graph = validate(data, SimpleNamespace(**dict(raw_run)), draft)
                event = con.execute("SELECT completed_at FROM rlv2_events WHERE run_id=? AND ordinal=2",
                                    (draft.run_id,)).fetchone()
                if (event is None or getattr(draft, "activated_at", None) != event[0]
                        or (event[0] is not None and graph.id != "zone_1")):
                    raise invalid()
        except (DomainError, ValueError, TypeError, KeyError, sqlite3.DatabaseError) as exc:
            raise ValueError(invalid().message) from exc
