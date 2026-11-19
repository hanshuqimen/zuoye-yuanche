"""Atomic owned normal-run content publication, with frozen source and choices.

This is an explicit local provider, not a reconstruction of official weights.
Legacy manually prepared maps retain their original policy and behavior.
"""

import json
from types import SimpleNamespace

from sqlalchemy.orm import object_session

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_floors import CONTENT_POLICY, saved_graphs
from terralocal.server.domain.rogue_reads import content_facts
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_content_specs import compile_spec, quote
from terralocal.server.persistence import models as m

_PUBLISHING = object()  # Private session-local key; never a request/config flag.
_MATERIAL = object()  # Pure material only, bounded to one publish call below.


def invalid():
    return DomainError("ROGUE_CONTENT_INCOMPATIBLE", "探索内容方案或持久绑定不完整；请保留原存档", 503)


def allocate(data, run, source):
    """Ordered conditional weighted draws; bounded, no retries or fallback pool.

    Reserve all possible nonstack outcomes, as required by existing providers.
    Exhaustion rejects the entire publication, before any client-visible map.
    """
    if (run.topic_id != "rogue_1" or run.mode != "NORMAL" or run.grade != 0
            or run.gamedata_hash != data.manifest["hash"] or run.band_id != data.rogue_initial.band):
        raise invalid()
    spec = compile_spec(data, source, at=run.created_at)
    zones = spec.generate(data, run.seed)
    reserved, assignments, selected = {run.band_id}, [], []
    for number, zone in enumerate(zones, 1):
        for node in sorted(zone.nodes, key=lambda n: (n.pos.x, n.pos.y)):
            entry = spec.choose(number, node.kind, node.pos, run.seed, reserved=frozenset(reserved))
            if entry is None:
                continue
            reserved.update(entry.reservations)
            assignments.append({"zone": number, "x": node.pos.x, "y": node.pos.y,
                                "kind": node.kind, "candidate": entry.id})
            selected.append((number, node.pos, node.kind, entry))
    value = {"schema": 1, "source": json.loads(spec.source), "assignments": assignments}
    digest = fingerprint({"policy": CONTENT_POLICY, "run": run.id, "account": run.account_id,
        "data": run.gamedata_hash, "seed": run.seed, "at": run.created_at, "spec": spec.digest,
        "plan": value})
    return value, digest, zones, tuple(selected)


def validate(data, run, draft):
    try:
        known = content_facts(data, run, draft)
        material = None
        if isinstance(run, m.RogueTopicRun) and isinstance(draft, m.RogueMapDraft):
            session = object_session(run)
            candidate = session.info.get(_MATERIAL) if session is not None and object_session(draft) is session else None
            if (candidate is not None and candidate.ctx.data is data and candidate.ctx.account_id == run.account_id
                    and candidate.run is run and candidate.draft is draft):
                material = candidate
        value = draft.plan
        if (type(value) is not dict or set(value) != {"schema", "source", "assignments"}
                or type(value["schema"]) is not int or value["schema"] != 1):
            raise invalid()
        plan, graph = canonical(value), canonical(draft.graph)
        if known is not None or material is not None:
            # JSON values can change in place without SQLAlchemy marking them dirty.
            # Compare the actual validated inputs as well as observing session writes.
            identity = canonical([run.id, run.account_id, run.topic_id, run.mode, run.grade,
                run.gamedata_hash, data.manifest["hash"], run.band_id, run.seed, run.created_at, draft.plan_hash,
                draft.policy_version, draft.gamedata_hash, draft.seed, draft.prepared_at, draft.activated_at])
            key = identity, plan, graph
            for cached in (known.content if known is not None else None,
                           material.cached if material is not None else None):
                if cached is not None and cached[0] == key:
                    return cached[1]
        expected, digest, zones, selected = allocate(data, run, value["source"])
        if (plan != canonical(expected) or draft.plan_hash != digest or graph != canonical(saved_graphs(zones))):
            raise invalid()
        result = zones, selected
        if known is not None:
            known.content = key, result
        if material is not None:
            material.cached = key, result
        return result
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise invalid() from exc


def prepare(ctx, run):
    source = getattr(ctx.data, "rogue_content_source", None)
    if run.mode != "NORMAL" or run.grade != 0:
        return None
    try:
        if source is None:
            from terralocal.server.gamedata.rogue_default import source as default_source

            owned = frozenset(r.item_id for r in ctx.session.query(m.RogueRunRelic).filter_by(run_id=run.id))
            source = default_source(ctx.data, run, owned)
            if source is None:
                return None
        else:
            source = json.loads(source)
        value, digest, zones, _ = allocate(ctx.data, run, source)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise invalid() from exc
    draft = m.RogueMapDraft(run_id=run.id, policy_version=CONTENT_POLICY,
        gamedata_hash=run.gamedata_hash, seed=run.seed, plan=value, plan_hash=digest,
        graph=saved_graphs(zones), prepared_at=max(run.created_at, ctx.now))
    ctx.session.add(draft)
    ctx.session.flush()
    return draft


def check_bindings(data, run, draft, scenes, shops, plans, *, partial=False):
    """Check content identity as well as each provider's own journal/hash checks."""
    if draft is None or draft.policy_version != CONTENT_POLICY:
        return
    _, selected = validate(data, run, draft)
    expected = {"scene": {}, "shop": {}, "battle": {}}
    for number, point, kind, entry in selected:
        role = "scene" if kind in ("INCIDENT", "REST") or entry.visit else "shop" if kind == "SHOP" else "battle"
        content = {"program": entry.visit.program.id} if entry.visit else json.loads(entry.source)
        expected[role][(number, point.x, point.y)] = content
    from terralocal.server.gamedata.rogue_battle_loot import RelicGroups, compile_groups

    for role, rows in (("scene", scenes), ("shop", shops), ("battle", plans)):
        actual = {}
        for row in rows:
            key = row.zone_index, row.node_x, row.node_y
            if key in actual or key not in expected[role]:
                raise invalid()
            actual[key] = row
            content = expected[role][key]
            if role == "scene":
                matches = row.program_id == content["program"]
            elif role == "shop":
                # Normalise through the same provider serializer, including
                # optional scopes/layer fields that JSON may otherwise omit.
                from terralocal.server.domain.rogue_shops import offer_payload

                q = quote(data, content)
                payload = {"id": q.id, "offers": [offer_payload(o) for o in q.offers.values()], "evidence": q.evidence}
                matches = canonical(row.quote) == canonical(payload)
            else:
                value, _ = compile_groups(data, RelicGroups(tuple(tuple(g) for g in content["groups"]),
                    frozenset(content["eligibility"]), content["evidence"], content.get("capsule"),
                    content.get("base_only", False)), at=run.created_at)
                matches = canonical(row.spec) == canonical(value)
            if not matches or row.prepared_at != draft.activated_at:
                raise invalid()
        if not partial and set(actual) != set(expected[role]):
            raise invalid()


def publish(ctx, run, draft):
    """Called after activation, inside finishEvent's existing transaction."""
    if draft.policy_version != CONTENT_POLICY:
        return
    from terralocal.server.domain import rogue_loot_plans, rogue_shops, rogue_visits
    from terralocal.server.gamedata.rogue_battle_loot import RelicGroups

    if _PUBLISHING in ctx.session.info or _MATERIAL in ctx.session.info:
        raise invalid()
    ctx.session.info[_MATERIAL] = SimpleNamespace(ctx=ctx, run=run, draft=draft, cached=None)
    try:
        _, selected = validate(ctx.data, run, draft)
        ctx.session.info[_PUBLISHING] = run.id
        try:
            # Reuse immutable compilation/graph material, never live rows or
            # their validation outcomes. validate still compares actual JSON
            # and run/draft identity before every hit, including in-place edits.
            for number, point, kind, entry in selected:
                if entry.visit:
                    rogue_visits.prepare(ctx, {point: entry.visit.program.id}, zone_index=number)
                    continue
                content = json.loads(entry.source)
                if kind in ("INCIDENT", "REST"):
                    rogue_visits.prepare(ctx, {point: content["program"]}, zone_index=number)
                elif kind == "SHOP":
                    rogue_shops.prepare(ctx, {point: quote(ctx.data, content)}, zone_index=number)
                else:
                    spec = RelicGroups(tuple(tuple(g) for g in content["groups"]),
                                       frozenset(content["eligibility"]), content["evidence"], content.get("capsule"),
                                       content.get("base_only", False))
                    rogue_loot_plans.prepare(ctx, {point: spec}, zone_index=number)
        finally:
            ctx.session.info.pop(_PUBLISHING, None)
        check_bindings(ctx.data, run, draft, rogue_visits.rows(ctx.session, run.id),
                       rogue_shops.rows(ctx.session, run.id), rogue_loot_plans.rows(ctx.session, run.id))
    finally:
        ctx.session.info.pop(_MATERIAL, None)


def check_session(ctx, run, draft, scenes, shops, plans):
    check_bindings(ctx.data, run, draft, scenes, shops, plans,
                   partial=ctx.session.info.get(_PUBLISHING) == run.id)


def check_disk(data, con, run, scenes, shops, plans):
    raw = con.execute("SELECT * FROM rlv2_map_drafts WHERE run_id=?", (run.id,)).fetchone() if con.execute(
        "SELECT 1 FROM sqlite_master WHERE name='rlv2_map_drafts'").fetchone() else None
    if raw is None or raw["policy_version"] != CONTENT_POLICY:
        return
    draft = SimpleNamespace(**dict(raw))
    draft.plan, draft.graph = json.loads(draft.plan), json.loads(draft.graph)
    check_bindings(data, run, draft, scenes, shops, plans)


def bound_visit(data, run, draft, row):
    """Derive a visit's outcomes only from its complete frozen content source."""
    if draft is None or draft.policy_version != CONTENT_POLICY:
        raise invalid()
    _, selected = validate(data, run, draft)
    for number, point, _, entry in selected:
        if (number, point.x, point.y) == (row.zone_index, row.node_x, row.node_y):
            if entry.visit is None or row.program_id != entry.visit.program.id:
                raise invalid()
            return entry.visit
    raise invalid()
