"""Owned IS2 give-up intent, facts, native pending event and defensive loading.

Not an endpoint or an award operation. Callers must validate the complete run
replay first; the session entry does so. Historical abandoned runs must never
become pending simply because they can be described by this compiler.
"""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from types import SimpleNamespace

from sqlalchemy import JSON, select

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_progress import Layout, row_index, zone_for
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.persistence import models as m

POLICY = "rogue1-normal0-giveup-facts-v1"
TOOL_POLICY = "rogue1-normal0-giveup-tool-facts-v2"
CLOSURE_POLICY = "rogue1-normal0-explicit-giveup-v1"
TOOL_CLOSURE_POLICY = "rogue1-normal0-explicit-giveup-tools-v2"
CLOSURE_FACTS = {CLOSURE_POLICY: POLICY, TOOL_CLOSURE_POLICY: TOOL_POLICY}
LEGACY_RUN_POLICY = "rogue-initial-run-with-closure-v2"
CLOSURE_RUN_POLICY = "rogue-initial-run-with-closure-v3"
CLOSURE_RUN_POLICIES = frozenset({LEGACY_RUN_POLICY, CLOSURE_RUN_POLICY})
SCORE_POLICY = "rogue1-normal0-prts-giveup-v1"
KINDS = ("BATTLE_NORMAL", "BATTLE_ELITE", "BATTLE_BOSS")


def unsupported():
    return DomainError("ROGUE_GIVEUP_UNSUPPORTED", "此放弃结算事实尚未接纳；保留原探索", 501)


def invalid():
    return DomainError("ROGUE_GIVEUP_INCOMPATIBLE", "放弃请求与保留探索或确认记录不一致；请保留原存档", 503)


def confirmed_state(run):
    return "ABANDONED" if run.policy_version == LEGACY_RUN_POLICY else "SETTLED"


def confirmed_closure(run):
    return run.state == "SETTLED" and getattr(run, "policy_version", None) == CLOSURE_RUN_POLICY


def require_rules(ctx, run):
    from terralocal.server.domain import rogue_ending
    from terralocal.server.gamedata.rogue_score import FirstThemeScore

    try:
        if run.topic_id != "rogue_1" or run.mode != "NORMAL" or run.grade != 0:
            raise unsupported()
        rules = FirstThemeScore(ctx.data)
        if rogue_ending.completion_available(ctx.data) and not (
                rogue_ending.deployments_available(ctx.data) and rogue_ending.capacities_available(ctx.data)
                and rogue_ending.variants_available(ctx.data)):
            raise unsupported()
        outer = ctx.session.get(m.RogueTopicOuter, (ctx.account_id, run.topic_id)).state
        if outer["buff"]["unlocked"] or outer["buff"]["pointCost"] or outer["mission"]["list"]:
            raise unsupported()
        return rules
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise unsupported() from exc


def compile_facts(data, run, children, battles, records, scenes, shops, layout, *, policy=POLICY, tools=()):
    """Describe a validated closed run, without inventing clears or rewards."""
    events, relics, tickets, options, chars = children
    if (run.topic_id != "rogue_1" or run.mode != "NORMAL" or type(run.grade) is not int or run.grade != 0
            or run.gamedata_hash != data.manifest["hash"] or not (run.state == "ABANDONED" or confirmed_closure(run))
            or type(run.ended_at) is not int or not run.created_at <= run.ended_at < 2**63
            or run.hp <= 0 or len(events) != 3 or any(e.completed_at is None for e in events)
            or run.band_id != data.rogue_initial.band or layout is None):
        raise unsupported()
    if any(row.run_id != run.id for group in (*children, battles, records, scenes, shops) for row in group):
        raise unsupported()
    by_battle = {row.id: row for row in battles}
    if (len(by_battle) != len(battles) or len({r.battle_id for r in records}) != len(records)
            or {b.id for b in battles if b.state == "FINISHED"} != {r.battle_id for r in records}
            or any(b.state not in ("FINISHED", "ABANDONED") for b in battles)
            or any(r.effects.get("outcome") in ("DEFEAT", "SUCCESS") for r in records)):
        raise unsupported()
    entered = [s for s in scenes if s.state != "PREPARED"]
    traded = [s for s in shops if s.state != "PREPARED"]
    visits = [*battles, *entered, *traded]
    positions = [(row_index(v), v.node_x, v.node_y) for v in visits]
    if (len(set(positions)) != len(positions)
            or any(s.state not in ("FINISHED", "ABANDONED") for s in (*entered, *traded))
            or any(type(v.ended_at) is not int or v.ended_at > run.ended_at for v in visits)):
        raise unsupported()
    # Actual arrival and successful battle counters are different: a battle
    # closed before battleFinish contributes no clear and no stage progress.
    stages, counts = {}, [0, len(visits), 0, 0, 0, 0, len(chars)]
    counts[0] = len(layout.journal) if isinstance(layout, Layout) else 0
    for record in records:
        battle = by_battle[record.battle_id]
        node = next((n for n in zone_for(layout, battle).nodes
                     if (n.pos.x, n.pos.y) == (battle.node_x, battle.node_y)), None)
        kind = record.effects.get("kind")
        if node is None or node.kind != kind or kind not in KINDS or node.stage != battle.stage_id:
            raise unsupported()
        counts[2 + KINDS.index(kind)] += 1
        stages[battle.stage_id] = stages.get(battle.stage_id, 0) + 1
    # The original fact version counted only non-band relics. Preserve that
    # historical result, even for a retained old closure that acquired tools.
    catalog = data.table("roguelike_topic_table")["details"][run.topic_id]["items"]
    if ([r.ordinal for r in relics] != list(range(len(relics))) or not relics
            or relics[0].item_id != run.band_id
            or any(catalog.get(r.item_id, {}).get("type") != "RELIC" or r.count != 1 for r in relics[1:])):
        raise unsupported()
    counts[5] = len(relics) - 1
    if policy not in (POLICY, TOOL_POLICY):
        raise unsupported()
    tool_sources = []
    if policy == TOOL_POLICY:
        tool_sources = verified_tools(data, run, shops, tools)
        counts[5] += len(tool_sources)
    proof = {
        "policy": policy, "data": run.gamedata_hash, "run": run.id,
        "account": run.account_id, "start": run.created_at, "end": run.ended_at,
        "battles": [[b.id, b.state, b.stage_id, row_index(b), b.node_x, b.node_y,
                     b.started_at, b.ended_at] for b in sorted(battles, key=lambda b: (row_index(b), b.node_x, b.node_y))],
        "results": [[r.battle_id, r.rule_hash, fingerprint({"facts": r.facts, "claims": r.claims,
                     "completed": r.completed_at})] for r in records],
        "scenes": [[s.id, s.rule_hash, fingerprint({"before": s.before, "steps": s.steps,
                    "recruits": s.recruit_count, "entered": s.entered_at, "ended": s.ended_at})] for s in entered],
        "shops": [[s.id, s.rule_hash, fingerprint({"before": s.before, "purchases": s.purchases,
                   "first_ticket": s.first_ticket, "entered": s.entered_at, "ended": s.ended_at})] for s in traded],
        "items": [[r.ordinal, r.item_id, r.count, r.layer, r.acquired_at, bool(r.used)] for r in relics],
        "recruits": [[c.ordinal, c.ticket_ordinal, c.option_ordinal] for c in chars],
        "floors": [asdict(t) for t in layout.journal] if isinstance(layout, Layout) else [],
    }
    if policy == TOOL_POLICY:
        proof["tools"] = tool_sources
    return {"counts": counts, "stages": stages, "ended": run.ended_at,
            "success": 0, "ending": None, "give_up": proof | {"hash": fingerprint(proof)}}


def verified_tools(data, run, shops, tools):
    """Bind counted acquisitions to exact paid sources in validated replay.

    IDs shown in the permanent archive or final equipment cannot supply this
    count. A second receipt for the same item is a separate acquisition; a
    request retry has no second receipt and cannot increment it.
    """
    from terralocal.server.domain.rogue_support_tools import ToolGrant

    try:
        if type(tools) is not tuple or not 1 <= len(tools) <= 10000:
            raise unsupported()
        actual = []
        for grant in tools:
            if (type(grant) is not ToolGrant or type(grant.at) is not int
                    or not run.created_at <= grant.at <= run.ended_at):
                raise unsupported()
            data.rogue_support_tools.require(grant.item_id, run.created_at)
            actual.append([grant.visit_id, grant.stock_index, grant.item_id, grant.at])
        if len({(v[0], v[1]) for v in actual}) != len(actual):
            raise unsupported()
        expected = []
        for shop in sorted(shops, key=lambda s: (row_index(s), s.node_x, s.node_y)):
            offers = {offer["index"]: offer["item_id"] for offer in shop.quote["offers"]}
            for purchase in shop.purchases:
                item = offers[purchase["index"]]
                if item in data.rogue_support_tools.entries:
                    if purchase["ticket"] is not None or shop.account_id != run.account_id:
                        raise unsupported()
                    expected.append([shop.id, purchase["index"], item, purchase["at"]])
        if actual != expected:
            raise unsupported()
        return actual
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise unsupported() from exc


def fact_policy(closure, tools):
    if closure is None:
        return TOOL_POLICY if tools else POLICY
    if closure.policy_version not in CLOSURE_FACTS:
        raise invalid()
    return CLOSURE_FACTS[closure.policy_version]


def in_session(ctx, run):
    from terralocal.server.domain import rogue_runs, rogue_settlement, rogue_shops, rogue_visits
    from terralocal.server.domain.rogue_progress import in_session as current_layout

    progress = []
    children = rogue_runs.validated(ctx, run, progress_out=progress)
    tools = progress[0].support_tool_grants if progress[0] is not None else ()
    policy = fact_policy(ctx.session.get(m.RogueRunClosure, run.id), tools)
    battles = ctx.session.scalars(select(m.RogueBattle).where(m.RogueBattle.run_id == run.id)).all()
    return compile_facts(ctx.data, run, children, battles, rogue_settlement.rows(ctx.session, run.id),
                         rogue_visits.rows(ctx.session, run.id), rogue_shops.rows(ctx.session, run.id),
                         current_layout(ctx, run), policy=policy, tools=tools)


def on_disk(data, con, run):
    from terralocal.server.domain import rogue_runs, rogue_settlement, rogue_shops, rogue_visits
    from terralocal.server.domain.rogue_progress import on_disk as current_layout

    children = []
    for entity in rogue_runs.CHILDREN:
        values = []
        for raw in con.execute('SELECT * FROM "' + entity.__tablename__ + '" WHERE run_id=? ORDER BY ordinal', (run.id,)):
            row = dict(raw)
            for column in entity.__table__.columns:
                if isinstance(column.type, JSON):
                    row[column.name] = json.loads(row[column.name])
            values.append(SimpleNamespace(**row))
        children.append(values)
    progress = rogue_settlement.state_on_disk(data, con, run, children[2])
    rogue_runs.validate_run(data, run, *children, progress=progress)
    tools = progress.support_tool_grants if progress is not None else ()
    policy = fact_policy(read_row(con, run.id), tools)
    sources = {row[0]: (row[1], row[2]) for row in con.execute('SELECT id,account_id,char_id FROM operators')}
    rogue_runs.validate_sources(run, children[3], sources)
    battles = [SimpleNamespace(**dict(b)) for b in con.execute('SELECT * FROM rlv2_battles WHERE run_id=?', (run.id,))]
    return compile_facts(data, run, children, battles, rogue_settlement.read_rows(con, run.id),
                         rogue_visits.read_rows(con, run.id), rogue_shops.read_rows(con, run.id),
                         current_layout(data, con, run), policy=policy, tools=tools)


def save(ctx, run, rules):
    from terralocal.server.domain.rogue_ending import balances

    facts = in_session(ctx, run)
    outer = ctx.session.get(m.RogueTopicOuter, (ctx.account_id, run.topic_id))
    # Reject unsupported score bounds before the enclosing transaction commits
    # the closure. This describes eligibility; no balances change here.
    try:
        rules.calculate(facts["counts"], balances(outer.state), facts["ended"])
    except (ValueError, TypeError, KeyError) as exc:
        raise unsupported() from exc
    run.policy_version = CLOSURE_RUN_POLICY
    policy = TOOL_CLOSURE_POLICY if facts["give_up"]["policy"] == TOOL_POLICY else CLOSURE_POLICY
    ctx.session.add(m.RogueRunClosure(run_id=run.id, policy_version=policy,
        rule_hash=fingerprint({"policy": policy, "facts": facts}), facts=facts, created_at=run.ended_at))
    ctx.session.flush()


def validate(run, row, facts):
    if (row is None or run.policy_version not in CLOSURE_RUN_POLICIES or row.run_id != run.id
            or row.policy_version not in CLOSURE_FACTS
            or facts.get("give_up", {}).get("policy") != CLOSURE_FACTS[row.policy_version]
            or type(row.created_at) is not int or row.created_at != run.ended_at
            or row.rule_hash != fingerprint({"policy": row.policy_version, "facts": facts})
            or canonical(row.facts) != canonical(facts)):
        raise invalid()
    return facts


def read_row(con, run_id):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='rlv2_run_closures'").fetchone():
        return None
    raw = con.execute('SELECT * FROM rlv2_run_closures WHERE run_id=?', (run_id,)).fetchone()
    if raw is None:
        return None
    value = dict(raw)
    value["facts"] = json.loads(value["facts"])
    return SimpleNamespace(**value)


def pending(run, row, layout, *, tools=(), capsules=()):
    proof = row.facts["give_up"]
    return {"index": run.id, "type": "GAME_SETTLE", "content": {"done": False, "result": {
        "brief": {"level": run.level, "success": 0, "ending": None, "failEnding": None,
                  "theme": run.topic_id, "mode": run.mode, "predefined": None, "band": run.band_id,
                  "startTs": run.created_at, "endTs": row.created_at, "endZoneId": layout.id,
                  "modeGrade": run.grade, "seed": str(run.seed), "activity": None},
        "record": {"cntZone": len(proof["floors"]) + 1,
                   "relicList": [r[1] for r in proof["items"][1:]], "capsuleList": list(capsules),
                   "activeToolList": list(tools), "charBuff": [], "squadBuff": [], "totemList": [],
                   "exploreToolList": [], "fragmentList": [], "copperCounter": {}, "scrapCounter": {},
                   "legacyList": []}}}}


def preflight(data, path):
    if not path.exists():
        return
    from terralocal.server.domain.rogue_completion_rewards import GIVEUP_POLICY
    from terralocal.server.persistence.migrations import (
        REVISION,
        ROGUE_BANK_AWARDS_REVISION,
        ROGUE_BANK_REVISION,
        ROGUE_CLOSURE_REVISION,
    )

    versions = (ROGUE_CLOSURE_REVISION, ROGUE_BANK_REVISION, ROGUE_BANK_AWARDS_REVISION, REVISION)

    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = con.execute('SELECT version_num FROM alembic_version').fetchone() if 'alembic_version' in tables else None
        if 'rlv2_run_closures' not in tables:
            if version and version[0] in versions or ('rlv2_runs' in tables and con.execute(
                    'SELECT 1 FROM rlv2_runs WHERE policy_version IN (?,?) LIMIT 1', tuple(CLOSURE_RUN_POLICIES)).fetchone()):
                raise ValueError(invalid().message)
            return
        try:
            if con.execute('SELECT 1 FROM rlv2_runs r LEFT JOIN rlv2_run_closures c ON c.run_id=r.id '
                           'WHERE r.policy_version IN (?,?) AND c.run_id IS NULL LIMIT 1', tuple(CLOSURE_RUN_POLICIES)).fetchone():
                raise invalid()
            pending_accounts = set()
            for raw in con.execute('SELECT run_id FROM rlv2_run_closures'):
                saved = con.execute('SELECT * FROM rlv2_runs WHERE id=?', (raw[0],)).fetchone()
                if saved is None or data is None or not version or version[0] not in versions:
                    raise invalid()
                run = SimpleNamespace(**dict(saved))
                row = read_row(con, run.id)
                validate(run, row, on_disk(data, con, run))
                result = con.execute('SELECT policy_version FROM rlv2_game_settlements WHERE run_id=?', (run.id,)).fetchone()
                if result:
                    if result[0] not in (SCORE_POLICY, GIVEUP_POLICY) or run.state != confirmed_state(run):
                        raise invalid()
                elif (run.policy_version == LEGACY_RUN_POLICY or run.state != "ABANDONED"
                      or run.account_id in pending_accounts or con.execute(
                        'SELECT 1 FROM rlv2_runs WHERE account_id=? AND id!=? '
                        'AND (ended_at IS NULL OR created_at>=?) LIMIT 1',
                        (run.account_id, run.id, run.created_at)).fetchone()):
                    raise invalid()
                else:
                    pending_accounts.add(run.account_id)
        except (DomainError, ValueError, TypeError, KeyError, AttributeError, sqlite3.DatabaseError) as exc:
            raise ValueError(invalid().message) from exc
