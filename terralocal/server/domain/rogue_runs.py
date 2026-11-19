"""Transactional first-theme initialization; exploration is not yet fabricated."""

import json
import secrets
import sqlite3
import uuid
from contextlib import closing
from types import SimpleNamespace

from sqlalchemy import select

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import canonical
from terralocal.server.persistence import models as m
from terralocal.server.protocol.roguelike_state import no_run

POLICY = "rogue-initial-run-v1"
KINDS = ("GAME_INIT_RELIC", "GAME_INIT_RECRUIT_SET", "GAME_INIT_RECRUIT")
PHASES = ("INIT_RELIC", "INIT_GROUP", "INIT_RECRUIT", "MAP_READY")
CHILDREN = (m.RogueRunEvent, m.RogueRunRelic, m.RogueRunTicket, m.RogueRecruitOption, m.RogueRunChar)


def invalid() -> DomainError:
    return DomainError("ROGUE_RUN_INCOMPATIBLE", "探索记录与已接纳的初始化流程不匹配；请保留原存档", 503)


def contents(rules, group=None) -> list[dict]:
    return [
        {"initRelic": {"step": [1, 3], "items": {"0": {"id": rules.band, "count": 1}}}},
        {"initRecruitSet": {"step": [2, 3], "option": list(rules.groups)}},
        {"initRecruit": {"step": [3, 3], "tickets": ["0", "1", "2"] if group else [],
                         "showChar": [], "team": None}},
    ]


def validate_run(data, run, events, relics, tickets, options=(), chars=(), *, progress=None) -> None:
    from terralocal.server.domain.rogue_giveup import CLOSURE_RUN_POLICIES

    rules = data.rogue_initial
    if (run.gamedata_hash != data.manifest["hash"] or run.policy_version not in (POLICY, *CLOSURE_RUN_POLICIES)
            or run.policy_version in CLOSURE_RUN_POLICIES and (run.state not in ("ABANDONED", "SETTLED") or run.ended_at is None)
            or run.topic_id != rules.topic_id or run.mode not in rules.configs or run.grade != 0
            or type(run.seed) is not int or not 0 <= run.seed <= 2**63 - 1):
        raise invalid()
    config = rules.configs[run.mode]
    expected = {"hp": config.hp, "hp_max": config.max_hp, "shield": config.shield, "gold": config.gold,
                "hope_max": config.hope, "squad_capacity": config.squad_capacity,
                "level": 1, "max_level": rules.max_level, "exp": 0}
    if progress is not None:
        expected = progress
    if any(type(getattr(run, key)) is not int or getattr(run, key) != value for key, value in expected.items()):
        raise invalid()
    if (type(run.created_at) is not int or run.created_at < 0 or len(events) != 3
            or [r.ordinal for r in events] != [0, 1, 2] or tuple(r.kind for r in events) != KINDS):
        raise invalid()
    completed = [r.completed_at is not None for r in events]
    if completed not in ([False, False, False], [True, False, False], [True, True, False], [True, True, True]):
        raise invalid()
    phase = sum(completed)
    timestamps = [run.created_at, *(e.completed_at for e in events if e.completed_at is not None),
                  *(r.acquired_at for r in relics), *(t.created_at for t in tickets)]
    if run.ended_at is not None:
        timestamps.append(run.ended_at)
    if any(type(ts) is not int or not 0 <= ts <= 2**63 - 1 for ts in timestamps):
        raise invalid()
    if ((run.ended_at is None and run.state != PHASES[phase])
            or (run.ended_at is not None and run.state not in ("ABANDONED", "SETTLED"))):
        raise invalid()
    if run.band_id != (rules.band if phase else None):
        raise invalid()
    if (phase < 2 and run.recruit_group is not None) or (phase >= 2 and run.recruit_group not in rules.groups):
        raise invalid()
    if canonical([r.content for r in events]) != canonical(contents(rules, run.recruit_group)):
        raise invalid()
    if phase:
        grants = getattr(progress, "relic_grants", ())
        if (len(relics) != 1 + len(grants) or relics[0].ordinal != 0 or relics[0].item_id != rules.band
                or relics[0].count != 1 or relics[0].layer != 0 or relics[0].used):
            raise invalid()
        for relic, grant in zip(relics[1:], grants, strict=True):
            if (relic.ordinal != grant.ordinal or relic.item_id != grant.item_id
                    or type(relic.count) is not int or relic.count != 1
                    or type(relic.layer) is not int or relic.layer != grant.layer
                    or relic.acquired_at != grant.at or type(relic.used) not in (bool, int) or relic.used != 0):
                raise invalid()
    elif relics:
        raise invalid()
    if phase >= 2:
        if ([r.ordinal for r in tickets] != list(range(len(tickets))) or len(tickets) < 3
                or tuple(r.item_id for r in tickets[:3]) != rules.groups[run.recruit_group]
                or (len(tickets) > 3 and progress is None)):
            raise invalid()
    elif tickets or options or chars:
        raise invalid()
    from terralocal.server.domain.rogue_recruit import validate

    validate(data, run, tickets, options, chars, cost_history=getattr(progress, "cost_history", None))


def validate_sources(run, options, sources):
    for option in options:
        if (option.kind in ("NORMAL", "DIRECT") or option.kind in ("UPGRADE", "UPGRADE_PAID") and option.source_operator_id is not None) and sources.get(option.source_operator_id) != (
                run.account_id, option.character["charId"]):
            raise invalid()


def preflight(data, path) -> None:
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "alembic_version" in tables:
            from terralocal.server.persistence.migrations import (
                CURRENT_REVISIONS,
                ROGUE_ELITE_REVISION,
                ROGUE_FREE_REVISION,
            )

            revision = con.execute("SELECT version_num FROM alembic_version").fetchone()
            if revision and revision[0] in (*CURRENT_REVISIONS, ROGUE_ELITE_REVISION, ROGUE_FREE_REVISION):
                schema = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='rlv2_recruit_options'").fetchone()
                normalized = "".join(schema[0].split()) if schema and schema[0] else ""
                if ("'UPGRADE_PAID'" not in normalized or "hope_cost>0" not in normalized
                        or "'FREE'" not in normalized or "rlv2_free_source" not in normalized
                        or "hope_cost=0ANDsource_operator_idISNULL" not in normalized):
                    raise ValueError(invalid().message)
                if revision[0] in (*CURRENT_REVISIONS, ROGUE_ELITE_REVISION) and ("'THIRD'" not in normalized or "rlv2_elite_source" not in normalized
                        or "kind!='THIRD'OR(hope_cost=0ANDsource_operator_idISNULL)" not in normalized
                        or "elite_pool" not in {r[1] for r in con.execute('PRAGMA table_info("rlv2_tickets")')}):
                    raise ValueError(invalid().message)
                if revision[0] in CURRENT_REVISIONS and ("'DIRECT'" not in normalized or "rlv2_direct_source" not in normalized
                        or "kind!='DIRECT'ORsource_operator_id>0ANDsource_operator_idISNOTNULL" not in normalized
                        or "direct_pool" not in {r[1] for r in con.execute('PRAGMA table_info("rlv2_tickets")')}):
                    raise ValueError(invalid().message)
                for name, column in (("rlv2_recruit_options", "target_char_ordinal"),
                                     ("rlv2_chars", "training"), ("rlv2_battles", "roster_revisions")):
                    if column not in {r[1] for r in con.execute('PRAGMA table_info("' + name + '")')}:
                        raise ValueError(invalid().message)
        names = {"rlv2_runs", "rlv2_events", "rlv2_relics", "rlv2_tickets"}
        recruit_names = {"rlv2_recruit_options", "rlv2_chars"}
        if "alembic_version" in tables:
            from terralocal.server.persistence.migrations import (
                CURRENT_REVISIONS,
                ROGUE_ACTIVATION_REVISION,
                ROGUE_BATTLE_REVISION,
                ROGUE_ENDING_REVISION,
                ROGUE_MAP_REVISION,
                ROGUE_RECRUIT_REVISION,
                ROGUE_SCENE_REVISION,
                ROGUE_SETTLEMENT_REVISION,
            )

            revision = con.execute("SELECT version_num FROM alembic_version").fetchone()
            if revision and revision[0] in (*CURRENT_REVISIONS, ROGUE_SCENE_REVISION, ROGUE_ENDING_REVISION, ROGUE_SETTLEMENT_REVISION, ROGUE_BATTLE_REVISION, ROGUE_ACTIVATION_REVISION,
                                           ROGUE_MAP_REVISION, ROGUE_RECRUIT_REVISION) \
                    and not recruit_names <= tables:
                raise ValueError(invalid().message)
        if tables.intersection(recruit_names) and not recruit_names <= tables:
            raise ValueError(invalid().message)
        if recruit_names <= tables:
            names |= recruit_names
        if not tables.intersection(names):
            return
        if not names <= tables:
            raise ValueError(invalid().message)
        runs = list(con.execute("SELECT * FROM rlv2_runs"))
        if not runs:
            if any(con.execute('SELECT 1 FROM "' + name + '" LIMIT 1').fetchone() for name in names - {"rlv2_runs"}):
                raise ValueError(invalid().message)
            return
        if (data is None or "roguelike_topic_table" not in data.manifest["tables"]
                or "rlv2_accounts" not in tables):
            raise ValueError(invalid().message)
        accounts = {r[0] for r in con.execute("SELECT account_id FROM rlv2_accounts")}
        sources = {r[0]: (r[1], r[2]) for r in con.execute("SELECT id,account_id,char_id FROM operators")}
        active = set()
        try:
            for raw in runs:
                run = SimpleNamespace(**dict(raw))
                if run.account_id not in accounts or (run.ended_at is None and run.account_id in active):
                    raise invalid()
                if run.ended_at is None:
                    active.add(run.account_id)
                children = []
                for entity in CHILDREN:
                    values = []
                    if entity.__tablename__ not in tables:  # Read-only admission of schema0019 before upgrade.
                        children.append(values)
                        continue
                    for row in con.execute('SELECT * FROM "' + entity.__tablename__ + '" WHERE run_id=? ORDER BY ordinal',
                                           (run.id,)):
                        value = dict(row)
                        if entity is m.RogueRunEvent:
                            value["content"] = json.loads(value["content"])
                        if entity is m.RogueRecruitOption:
                            value["character"] = json.loads(value["character"])
                        if entity is m.RogueRunTicket:
                            for field in ("elite_pool", "direct_pool"):
                                if field in value:
                                    value[field] = json.loads(value[field])
                        if entity is m.RogueRunChar and "training" in value:
                            value["training"] = json.loads(value["training"])
                        values.append(SimpleNamespace(**value))
                    children.append(values)
                from terralocal.server.domain.rogue_settlement import state_on_disk

                validate_run(data, run, *children, progress=state_on_disk(data, con, run, children[2]))
                validate_sources(run, children[3], sources)
            for name in names - {"rlv2_runs"}:
                if con.execute('SELECT 1 FROM "' + name + '" c LEFT JOIN rlv2_runs r ON c.run_id=r.id '
                               'WHERE r.id IS NULL LIMIT 1').fetchone():
                    raise invalid()
        except (DomainError, ValueError, TypeError, KeyError) as exc:
            raise ValueError(invalid().message) from exc


def active(ctx, *, required=False, allow_closure=False, progress_out=None):
    if required:
        from terralocal.server.domain.rogue_topics import _account

        _account(ctx)
    ctx.session.flush()
    runs = ctx.session.scalars(select(m.RogueTopicRun).where(m.RogueTopicRun.account_id == ctx.account_id,
                                                           m.RogueTopicRun.ended_at.is_(None))).all()
    runs += ctx.session.scalars(select(m.RogueTopicRun).join(m.RogueRunClosure)
        .outerjoin(m.RogueGameSettlement).where(m.RogueTopicRun.account_id == ctx.account_id,
            m.RogueTopicRun.ended_at.is_not(None), m.RogueGameSettlement.run_id.is_(None))).all()
    if len(runs) > 1:
        raise invalid()
    if not runs:
        if required:
            raise DomainError("ROGUE_NO_RUN", "当前没有进行中的探索", 409)
        return None, ([], [], [], [], [])
    run = runs[0]
    closure = ctx.session.get(m.RogueRunClosure, run.id)
    if closure is not None:
        from terralocal.server.domain import rogue_giveup

        if run.state != "ABANDONED" or run.policy_version == rogue_giveup.LEGACY_RUN_POLICY:
            raise rogue_giveup.invalid()
        try:
            rogue_giveup.validate(run, closure, rogue_giveup.in_session(ctx, run))
        except (DomainError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise rogue_giveup.invalid() from exc
        if required and not allow_closure:
            raise DomainError("ROGUE_ENDING_PENDING", "请先确认已经放弃的探索结算", 409)
    return run, validated(ctx, run, progress_out=progress_out)


def validated(ctx, run, *, progress_out=None):
    """Validate an owned active or archived run against the same causal facts."""
    if run.account_id != ctx.account_id:
        raise invalid()
    from terralocal.server.domain.rogue_reads import facts

    known = facts(ctx)
    if known is not None and run.id in known.runs:
        children, progress = known.runs[run.id]
        if progress_out is not None:
            progress_out.append(progress)
        return children
    from terralocal.server.domain.rogue_giveup import CLOSURE_RUN_POLICIES, LEGACY_RUN_POLICY

    if run.policy_version in CLOSURE_RUN_POLICIES:
        if (ctx.session.get(m.RogueRunClosure, run.id) is None
                or (run.state == "SETTLED" or run.policy_version == LEGACY_RUN_POLICY)
                and ctx.session.get(m.RogueGameSettlement, run.id) is None):
            raise invalid()
    children = [ctx.session.scalars(select(entity).where(entity.run_id == run.id).order_by(entity.ordinal)).all()
                for entity in CHILDREN]
    from terralocal.server.domain.rogue_settlement import state_in_session

    progress = state_in_session(ctx, run, children[2])
    validate_run(ctx.data, run, *children, progress=progress)
    source_ids = {o.source_operator_id for o in children[3] if o.kind in ("NORMAL", "DIRECT", "UPGRADE", "UPGRADE_PAID")}
    sources = {row.id: (row.account_id, row.char_id) for row in ctx.session.execute(
        select(m.Operator.id, m.Operator.account_id, m.Operator.char_id).where(m.Operator.id.in_(source_ids)))} \
        if source_ids else {}
    validate_sources(run, children[3], sources)
    if known is not None:
        known.runs[run.id] = children, progress
    if progress_out is not None:
        progress_out.append(progress)
    return children


def create(ctx, theme: str, mode: str, grade: int, predefined: str | None, activity: str | None) -> dict:
    from terralocal.server.domain.rogue_topics import _account

    _account(ctx)
    ctx.data.rogue_topics.topic(theme, at=ctx.now)
    if theme != "rogue_1":
        raise DomainError("ROGUE_THEME_UNSUPPORTED", "此主题的探索流程尚未接通，未创建探索", 501)
    rules = ctx.data.rogue_initial
    c = rules.require_base(mode, grade, predefined or None, activity)
    gate = ctx.session.get(m.StageProgress, (ctx.account_id, ctx.data.rogue_topics.unlock_stage))
    if gate is None or gate.stars < 1:
        raise DomainError("ROGUE_SYSTEM_LOCKED", "尚未通关集成战略的开放前置关卡")
    if active(ctx)[0] is not None:
        raise DomainError("ROGUE_RUN_ACTIVE", "已有进行中的探索，请先继续或放弃", 409)
    if ctx.session.scalar(select(m.BattleSession.id).where(m.BattleSession.account_id == ctx.account_id,
                                                         m.BattleSession.state == "STARTED")):
        raise DomainError("ROGUE_BATTLE_ACTIVE", "普通战斗尚未结束，未创建探索", 409)
    # Reentry is measured from starting an exploration, not abandoning it.
    # Existing rows retain their original end timestamps for audit/recovery.
    last = ctx.session.scalar(select(m.RogueTopicRun.created_at).where(
        m.RogueTopicRun.account_id == ctx.account_id
    ).order_by(m.RogueTopicRun.created_at.desc()).limit(1))
    if last is not None and ctx.now < last + rules.cooldown:
        raise DomainError("ROGUE_REOPEN_COOLDOWN", "探索重开冷却尚未结束")
    run = m.RogueTopicRun(id=str(uuid.uuid4()), account_id=ctx.account_id, gamedata_hash=ctx.data.manifest["hash"],
        policy_version=POLICY, topic_id=theme, mode=mode, grade=grade, state=PHASES[0], seed=secrets.randbits(63),
        hp=c.hp, hp_max=c.max_hp, shield=c.shield, gold=c.gold, hope_max=c.hope, hope_cost=0,
        squad_capacity=c.squad_capacity, level=1, max_level=rules.max_level, exp=0, band_id=None,
        recruit_group=None, created_at=ctx.now, ended_at=None)
    ctx.session.add(run)
    ctx.session.flush()
    for index, content in enumerate(contents(rules)):
        ctx.session.add(m.RogueRunEvent(run_id=run.id, ordinal=index, kind=KINDS[index], content=content))
    remember_start(ctx, run)
    ctx.session.flush()
    return {}


def choose_band(ctx, selection: str) -> dict:
    run, (events, _, _, _, _) = active(ctx, required=True)
    if run.state != "INIT_RELIC":
        raise DomainError("ROGUE_EVENT_ORDER", "当前不是初始分队选择步骤", 409)
    item = events[0].content["initRelic"]["items"].get(selection)
    if item is None:
        raise DomainError("ROGUE_INVALID_SELECTION", "此分队不在当前可选列表中")
    ctx.session.add(m.RogueRunRelic(run_id=run.id, ordinal=0, item_id=item["id"], count=1, layer=0,
                                  acquired_at=ctx.now, used=False))
    run.band_id, run.state, events[0].completed_at = item["id"], "INIT_GROUP", ctx.now
    ctx.session.flush()
    return {}


def choose_group(ctx, selection: str) -> dict:
    run, (events, _, _, _, _) = active(ctx, required=True)
    if run.state != "INIT_GROUP":
        raise DomainError("ROGUE_EVENT_ORDER", "当前不是初始招募组合选择步骤", 409)
    if selection not in events[1].content["initRecruitSet"]["option"]:
        raise DomainError("ROGUE_INVALID_SELECTION", "此招募组合不在当前可选列表中")
    for index, ticket in enumerate(ctx.data.rogue_initial.groups[selection]):
        ctx.session.add(m.RogueRunTicket(run_id=run.id, ordinal=index, item_id=ticket, state="CREATE",
                                        created_at=ctx.now))
    events[1].completed_at = ctx.now
    events[2].content = contents(ctx.data.rogue_initial, selection)[2]
    run.recruit_group, run.state = selection, "INIT_RECRUIT"
    ctx.session.flush()
    return {}


def remember_start(ctx, run) -> None:
    outer = ctx.session.get(m.RogueTopicOuter, (ctx.account_id, run.topic_id))
    state = json.loads(json.dumps(outer.state))
    state["record"]["last"] = run.created_at
    outer.state = state


def abandon(ctx) -> dict:
    run, _ = active(ctx, required=True, allow_closure=True)
    from terralocal.server.domain import rogue_giveup
    from terralocal.server.domain.rogue_settlement import rows as settlements

    records = settlements(ctx.session, run.id)
    if ctx.session.get(m.RogueRunClosure, run.id) is not None:
        return {}
    if records and records[-1].effects.get("outcome") in ("DEFEAT", "SUCCESS"):
        # The close-game callback reloads the player delta, then opens the
        # dungeon when GAME_SETTLE is pending. Preserve that event until the
        # existing gameSettle transaction acknowledges it; do not discard a
        # completed result or award it through this empty delta response.
        return {}
    score_rules = rogue_giveup.require_rules(ctx, run) if run.state == "MAP_READY" else None
    from terralocal.server.domain.rogue_battle import abandon_run
    from terralocal.server.domain.rogue_shops import abandon as abandon_shops
    from terralocal.server.domain.rogue_visits import abandon as abandon_scenes

    cursor = ctx.session.get(m.RogueFloorCursor, run.id)
    floor_boundary = max((t["at"] for t in cursor.journal), default=run.created_at) if cursor else run.created_at
    draft = ctx.session.get(m.RogueMapDraft, run.id)
    if draft is not None:
        floor_boundary = max(floor_boundary, draft.prepared_at, draft.activated_at or 0)
    battle_boundary = max(abandon_run(ctx, run), abandon_scenes(ctx, run), abandon_shops(ctx, run), floor_boundary)
    # A virtual-clock rewind must not erase the original start boundary.
    run.state, run.ended_at = "ABANDONED", max(run.created_at, ctx.now, battle_boundary)
    remember_start(ctx, run)
    ctx.session.flush()
    if score_rules is not None:
        rogue_giveup.save(ctx, run, score_rules)
    return {}


def wire_exp(data, total):
    """M152771 consumes EXP within the saved level; domain totals stay intact.

    Zero needs no level-table expansion during the initial bootstrap. Positive
    values use the same reviewed cumulative curve as settlement and replay.
    """
    if type(total) is int and total == 0:
        return 0
    return data.rogue_levels.at(total).in_level_exp


def snapshot(ctx) -> dict:
    progress = []
    run, (events, relics, tickets, options, chars) = active(ctx, progress_out=progress)
    if run is None:
        return no_run()
    support_tool = getattr(progress[0], "support_tool", None)
    # Ending display uses this run's validated acquisition history. Replaced
    # tools remain part of that history; other runs' permanent archive does not.
    support_tools = tuple(dict.fromkeys(g.item_id for g in progress[0].support_tool_grants)) if progress[0] else ()
    capsule_items = tuple(g.item_id for g in progress[0].capsule_grants) if progress[0] else ()
    closure = ctx.session.get(m.RogueRunClosure, run.id)
    from terralocal.server.domain.rogue_battle import project as battle_project
    from terralocal.server.domain.rogue_map_drafts import current_map
    from terralocal.server.domain.rogue_progress import Layout, index, row_index
    from terralocal.server.domain.rogue_recruit import project

    recruits, troop, pending = project(tickets, options, chars)
    zone = current_map(ctx, run, events)
    tool_bindings = progress[0].support_tool_battles if progress[0] is not None else {}
    battle_state = battle_project(ctx, run, zone, troop,
        tool_bindings=tool_bindings, tools=support_tools, capsules=capsule_items) if zone and closure is None else None
    from terralocal.server.domain import rogue_shops, rogue_visits

    scene_state = rogue_visits.pending(ctx, run, zone, (events, relics, tickets, options, chars)) if zone and closure is None else None
    if scene_state:
        battle_state = scene_state
    shop_state = rogue_shops.pending(ctx, run, zone) if zone and closure is None else None
    if shop_state:
        battle_state = shop_state
    battle_pending = [battle_state[1]] if battle_state and battle_state[1] else []
    history = ctx.session.scalars(select(m.RogueBattle).where(m.RogueBattle.run_id == run.id)
                                  .order_by(m.RogueBattle.node_x, m.RogueBattle.node_y)).all()
    entered_scenes = [s for s in rogue_visits.rows(ctx.session, run.id) if s.state != "PREPARED"]
    entered_shops = [s for s in rogue_shops.rows(ctx.session, run.id) if s.state != "PREPARED"]
    history = sorted([*history, *entered_scenes, *entered_shops], key=lambda v: (row_index(v), v.node_x, v.node_y))
    trace = [{"zone": row_index(b), "position": {"x": b.node_x, "y": b.node_y}} for b in history]
    map_zones = ({str(i): z.wire() for i, z in enumerate(zone.zones[:zone.index], 1)}
                 if isinstance(zone, Layout) else {"1": zone.wire()} if zone else {})
    if map_zones:
        for b in history:
            if b.state == "FINISHED":
                from terralocal.server.domain.rogue_map import Point

                pos = Point(b.node_x, b.node_y)
                map_wire = map_zones[str(row_index(b))]
                key = pos.legacy_key if pos.key not in map_wire["nodes"] else pos.key
                map_wire["nodes"][key]["fts"] = b.ended_at
    wire = {
        "player": {"state": "PENDING" if battle_pending or (zone and pending) else "WAIT_MOVE" if zone else "INIT", "property": {
            "exp": wire_exp(ctx.data, run.exp), "level": run.level, "maxLevel": run.max_level,
            "hp": {"current": run.hp, "max": run.hp_max}, "shield": run.shield, "gold": run.gold,
            "capacity": run.squad_capacity, "population": {"cost": run.hope_cost, "max": run.hope_max},
            "conPerfectBattle": 0}, "cursor": {"zone": index(zone) if zone else 0,
                "position": battle_state[0] if battle_state else None}, "pending": (
                pending + battle_pending) + [
                {"index": str(e.ordinal), "type": e.kind, "content": e.content}
                for e in events if e.completed_at is None], "trace": trace, "status": {"bankPut": 0},
            "toEnding": None, "chgEnding": False, "innerMission": [], "nodeMission": None,
            "zoneReward": {}, "traderReturn": {}},
        "map": {"zones": map_zones, "verticalCostDelta": 0},
        "inventory": {"relic": {str(r.ordinal): {"index": str(r.ordinal), "id": r.item_id, "count": r.count,
            "layer": r.layer, "ts": r.acquired_at, "used": r.used} for r in relics},
            "recruit": recruits,
            "stashedRecruit": [], "stashedRecruitLimit": 0,
            "trap": support_tool.wire() if support_tool is not None else None, "exploreTool": {}, "consumable": {}},
        # eGrade/outer are the established community wire aliases; the frozen
        # managed fields are modeGrade/outerBuff. Native consumption is pending.
        "game": {"uid": run.id, "theme": run.topic_id, "mode": run.mode, "eGrade": run.grade,
            "equivalentGrade": run.grade, "predefined": None, "difficult": 0,
            "outer": {}, "start": run.created_at, "activity": None},
        "troop": {"chars": troop, "expedition": [], "expeditionDetails": {}, "expeditionReturn": None,
                  "hasExpeditionReturn": False},
        "buff": {"tmpHP": 0, "capsule": progress[0].capsule_history.wire() if progress[0] else None, "squadBuff": []},
        "module": dict.fromkeys(("san", "dice", "totem", "vision", "chaos", "fragment", "disaster",
                                 "nodeUpgrade", "copper", "wrath", "sky", "gridZone", "scrap", "weather")),
    }
    if closure is not None:
        from terralocal.server.domain import rogue_giveup

        wire["player"]["state"] = "PENDING"
        wire["player"]["pending"] = [rogue_giveup.pending(run, closure, zone, tools=support_tools, capsules=capsule_items)]
        wire["player"]["cursor"]["position"] = trace[-1]["position"] if trace else None
    return wire
