"""Owned first-floor scene nodes and a shared battle/scene traversal ledger.

Event assignments are explicit prepared server rules, not inferred official
encounter pools. No live endpoint accepts a client-selected program or reward.
"""

import json
import sqlite3
import uuid
from collections import Counter
from contextlib import closing
from types import SimpleNamespace

from sqlalchemy import select

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_events import Resources, decide, scene_content
from terralocal.server.domain.rogue_events import replay as scene_replay
from terralocal.server.domain.rogue_giveup import confirmed_closure
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_progress import Layout, index, row_index, zone_for
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_dance import PROGRAMS as DANCE_PROGRAMS
from terralocal.server.gamedata.rogue_events import GOLD_HOPE_PROGRAM, HEALTH_GOLD_PROGRAM
from terralocal.server.gamedata.rogue_recreation import PROGRAM as RECREATION_PROGRAM
from terralocal.server.gamedata.rogue_recreation import RELIC as RECREATION_RELIC
from terralocal.server.gamedata.rogue_recreation import TICKET as RECREATION_TICKET
from terralocal.server.gamedata.rogue_recruit_events import PROGRAMS as RECRUIT_PROGRAMS
from terralocal.server.gamedata.rogue_recruit_events import TICKETS as RECRUIT_TICKETS
from terralocal.server.gamedata.rogue_relic_events import PROGRAMS as RELIC_PROGRAMS
from terralocal.server.gamedata.rogue_relic_events import RELICS as EVENT_RELICS
from terralocal.server.gamedata.rogue_rest import PROGRAMS as REST_PROGRAMS
from terralocal.server.gamedata.rogue_rest import TICKET as REST_TICKET
from terralocal.server.gamedata.rogue_rest import UPGRADE_CHOICE
from terralocal.server.gamedata.rogue_ticket_events import PROGRAMS as TICKET_PROGRAMS
from terralocal.server.gamedata.rogue_ticket_events import TICKETS as EVENT_TICKETS
from terralocal.server.gamedata.rogue_treasures import PROGRAMS as TREASURE_PROGRAMS
from terralocal.server.persistence import models as m

POLICY = "rogue1-fixed-node-visits-v1"
CONFIGURED_PROGRAMS = TREASURE_PROGRAMS | {RECREATION_PROGRAM}


def invalid():
    return DomainError("ROGUE_VISIT_INCOMPATIBLE", "探索节点或事件记录不一致；请保留原存档", 503)


def program_for(data, program_id):
    # Lazy by admitted program family; never make old fixed-gain save replay
    # depend on newly introduced table rows, or change its saved digest.
    if program_id == HEALTH_GOLD_PROGRAM:
        return data.rogue_health_trade_events.get(program_id)
    if program_id in DANCE_PROGRAMS:
        return data.rogue_dance_events.get(program_id)
    if program_id in TICKET_PROGRAMS:
        return data.rogue_ticket_events.get(program_id)
    if program_id in RECRUIT_PROGRAMS:
        return data.rogue_recruit_events.get(program_id)
    if program_id in RELIC_PROGRAMS:
        return data.rogue_relic_events.get(program_id)
    programs = (data.rogue_rest_events if program_id in REST_PROGRAMS else data.rogue_trade_events
                if program_id == GOLD_HOPE_PROGRAM else data.rogue_fixed_events)
    return programs.get(program_id)


def program_for_visit(data, run, draft, row):
    if row.program_id not in CONFIGURED_PROGRAMS:
        return program_for(data, row.program_id)
    from terralocal.server.domain.rogue_content import bound_visit

    row._configured_visit = bound_visit(data, run, draft, row)
    return row._configured_visit.program


def configured_visit(row):
    visit = getattr(row, "_configured_visit", None)
    if visit is None:
        raise invalid()
    return visit


def bind_visited_content(data, run, draft, scenes):
    for row in scenes:
        if row.state != "PREPARED" and row.program_id in CONFIGURED_PROGRAMS:
            program_for_visit(data, run, draft, row)
    return scenes


def relic_for(row, choice, occurrence=0):
    if row.program_id in TREASURE_PROGRAMS:
        return configured_visit(row).grants.get(choice)
    if row.program_id == RECREATION_PROGRAM and choice == RECREATION_RELIC:
        relics = configured_visit(row).relics
        return relics[occurrence] if occurrence < len(relics) else None
    return EVENT_RELICS.get((row.program_id, choice))


def ticket_item(row, choice, occurrence=0):
    program_id = row.program_id
    if program_id == RECREATION_PROGRAM and choice == RECREATION_TICKET:
        tickets = configured_visit(row).tickets
        return tickets[occurrence] if occurrence < len(tickets) else None
    if program_id in REST_PROGRAMS and choice == UPGRADE_CHOICE:
        return REST_TICKET
    return EVENT_TICKETS.get((program_id, choice)) or RECRUIT_TICKETS.get((program_id, choice))


def rows(session, run_id):
    return session.scalars(select(m.RogueSceneVisit).where(m.RogueSceneVisit.run_id == run_id)
                           .order_by(m.RogueSceneVisit.zone_index, m.RogueSceneVisit.node_x,
                                     m.RogueSceneVisit.node_y)).all()


def read_rows(con, run_id):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='rlv2_scene_visits'").fetchone():
        return []
    result = []
    for raw in con.execute("SELECT * FROM rlv2_scene_visits WHERE run_id=? ORDER BY zone_index,node_x,node_y", (run_id,)):
        value = dict(raw)
        value["before"], value["steps"] = json.loads(value["before"]), json.loads(value["steps"])
        result.append(SimpleNamespace(**value))
    return result


def recruit_costs(options, chars):
    by_id = {(o.ticket_ordinal, o.ordinal): o for o in options}
    events = [(c.ticket_ordinal, by_id[(c.ticket_ordinal, c.option_ordinal)].hope_cost) for c in chars]
    from terralocal.server.domain.rogue_training import PAID_POLICY, history

    events += [(r["ticket"], r["hope_cost"]) for c in chars for r in history(c) if r["policy"] == PAID_POLICY]
    return [cost for _, cost in sorted(events)]


def costs_on_disk(con, run_id):
    events = [(r[0], r[1]) for r in con.execute("SELECT c.ticket_ordinal,o.hope_cost FROM rlv2_chars c JOIN rlv2_recruit_options o "
        "ON c.run_id=o.run_id AND c.ticket_ordinal=o.ticket_ordinal AND c.option_ordinal=o.ordinal "
        "WHERE c.run_id=? ORDER BY c.ordinal", (run_id,))]
    from terralocal.server.domain.rogue_training import PAID_POLICY

    columns = {r[1] for r in con.execute("PRAGMA table_info(rlv2_chars)")}
    if "training" in columns:
        for row in con.execute("SELECT training FROM rlv2_chars WHERE run_id=?", (run_id,)):
            events += [(r["ticket"], r["hope_cost"]) for r in json.loads(row[0]) if r["policy"] == PAID_POLICY]
    return [cost for _, cost in sorted(events)]


def costs_in_session(session, run_id):
    options = session.scalars(select(m.RogueRecruitOption).where(m.RogueRecruitOption.run_id == run_id)).all()
    chars = session.scalars(select(m.RogueRunChar).where(m.RogueRunChar.run_id == run_id)).all()
    return recruit_costs(options, chars)


def assignment_hash(data, run, draft, row, program):
    return fingerprint({"policy": POLICY, "data": data.manifest["hash"], "run": run.id, "seed": run.seed,
        "map": draft.plan_hash, "zone": row.zone_index, "x": row.node_x, "y": row.node_y,
        "program": program.digest})


def validate(data, run, draft, zone, row, costs):
    """Validate an assignment and its complete decision log without writes."""
    from terralocal.server.domain.rogue_settlement import PROPERTIES

    try:
        zone = zone_for(zone, row)
        program = program_for_visit(data, run, draft, row)
        point = Point(row.node_x, row.node_y)
        node = next((n for n in zone.nodes if n.pos == point), None)
        kind = ("ENTERTAINMENT" if row.program_id == RECREATION_PROGRAM else
                "TREASURE" if row.program_id in TREASURE_PROGRAMS else
                "REST" if row.program_id in REST_PROGRAMS else "INCIDENT")
        if (program is None or program.data_hash != run.gamedata_hash
                or row.account_id != run.account_id or row.run_id != run.id
                or node is None or node.kind != kind
                or run.mode != "NORMAL" or run.grade != 0 or run.topic_id != "rogue_1"
                or row.policy_version != POLICY or str(uuid.UUID(row.id)) != row.id
                or row.rule_hash != assignment_hash(data, run, draft, row, program)
                or type(row.prepared_at) is not int or not run.created_at <= row.prepared_at < 2**63
                or run.ended_at is not None and row.prepared_at > run.ended_at
                or type(row.steps) is not list or len(row.steps) > 256):
            raise invalid()
        if row.state == "PREPARED":
            if row.before != {} or row.steps or any(v is not None for v in (row.recruit_count, row.entered_at, row.ended_at)):
                raise invalid()
            return program, None
        if (row.state not in ("ACTIVE", "FINISHED", "ABANDONED")
                or type(row.before) is not dict or set(row.before) != set(PROPERTIES)
                or any(type(v) is not int or not 0 <= v < 2**31 for v in row.before.values())
                or type(row.recruit_count) is not int or row.recruit_count not in range(len(costs) + 1)
                or type(row.entered_at) is not int
                or not max(row.prepared_at, draft.activated_at or 0) <= row.entered_at < 2**63):
            raise invalid()
        # Acquisitions have immutable ordinal order. Retain the original prefix,
        # not the later run's spent hope when replaying a historical scene.
        initial = Resources(row.before["hp"], row.before["gold"], row.before["hope_max"],
                            sum(costs[:row.recruit_count]), row.before["squad_capacity"])
        boundary, choices, occurrences = row.entered_at, [], Counter()
        for step in row.steps:
            if type(step) is not dict or type(step.get("choice")) is not str:
                raise invalid()
            choice = step["choice"]
            grant = ticket_item(row, choice, occurrences[choice]) is not None
            if (set(step) != ({"choice", "at", "ticket"} if grant else {"choice", "at"})
                    or grant and (type(step["ticket"]) is not int or step["ticket"] < 3)
                    or type(step["at"]) is not int or not boundary <= step["at"] < 2**63):
                raise invalid()
            boundary = step["at"]
            choices.append(choice)
            occurrences[choice] += 1
        state = scene_replay(program, initial, tuple(choices))
        if row.state == "ACTIVE":
            if state.scene is None or row.ended_at is not None or run.ended_at is not None:
                raise invalid()
        else:
            if (type(row.ended_at) is not int or not boundary <= row.ended_at < 2**63
                    or row.state == "FINISHED" and state.scene is not None
                    or row.state == "ABANDONED" and (run.state != "ABANDONED" and not confirmed_closure(run) or state.scene is None)):
                raise invalid()
        if run.ended_at is not None and max(boundary, row.ended_at or 0) > run.ended_at:
            raise invalid()
        return program, state
    except (DomainError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as exc:
        raise invalid() from exc


def timeline(run, zone, battles, scenes, records, shops=()):
    """Validate actual visits only; prepared future assignments are not steps."""
    finished = {r.battle_id: r for r in records}
    entries = [(b.node_x, b.node_y, "battle", b) for b in battles] + [
        (s.node_x, s.node_y, "scene", s) for s in scenes if s.state != "PREPARED"] + [
        (s.node_x, s.node_y, "shop", s) for s in shops if s.state != "PREPARED"]
    entries.sort(key=lambda v: (row_index(v[3]), v[0], v[1]))
    limit = 512 if isinstance(zone, Layout) else 256
    if len(entries) > limit or len({(row_index(e[3]), e[0], e[1]) for e in entries}) != len(entries):
        raise invalid()
    previous, boundary, pending, number, last = None, 0, False, 1, None

    def cross_floor():
        if not isinstance(zone, Layout) or last is None or pending or previous is None:
            raise invalid()
        if number > len(zone.journal) or zone.zones[number - 1].successors(previous):
            raise invalid()
        t = zone.journal[number - 1]
        if ((t.zone, t.x, t.y, t.kind, t.record_id) != (number, *last[:3], last[3].id)
                or t.at < boundary or last[3].state != "FINISHED"):
            raise invalid()
        return t.at

    for x, y, kind, row in entries:
        floor = row_index(row)
        if floor != number:
            if floor != number + 1:
                raise invalid()
            boundary, previous, number = cross_floor(), None, floor
        point = Point(x, y)
        graph = zone_for(zone, row)
        if (pending or point not in graph.successors(previous)
                or isinstance(zone, Layout) and floor > zone.index):
            raise invalid()
        start = row.started_at if kind == "battle" else row.entered_at
        end = row.ended_at
        if type(start) is not int or start < boundary:
            raise invalid()
        boundary = end or start
        if kind == "battle":
            record = finished.get(row.id)
            if row.state == "FINISHED":
                if record is None:
                    raise invalid()
                boundary = max(boundary, record.created_at, record.completed_at or 0,
                               *(c["at"] for c in record.claims))
                pending = record.completed_at is None
            else:
                if record is not None:
                    raise invalid()
                pending = True  # STARTED or abandoned terminal never has a successor.
        else:
            actions = row.steps if kind == "scene" else row.purchases
            boundary = max([boundary, *(step["at"] for step in actions)])
            bank = getattr(row, "_bank_visit", None)
            if bank is not None:
                from terralocal.server.domain.rogue_bank_ledger import load

                boundary = max([boundary, *(a.at for a in load(bank.journal).actions)])
            pending = row.state != "FINISHED"
        previous = point
        last = x, y, kind, row
    if isinstance(zone, Layout):
        if zone.index == number + 1:
            boundary, previous, number = cross_floor(), None, zone.index
        if zone.index != number:
            raise invalid()
    if run.ended_at is not None and boundary > run.ended_at:
        raise invalid()
    return entries, previous, boundary, pending


def apply(data, run, draft, zone, row, costs, before, *, capacity_observer=None):
    _, state = validate(data, run, draft, zone, row, costs)
    if state is None or canonical(row.before) != canonical(before):
        raise invalid()
    if capacity_observer is not None:
        capacity_observer(state.capacity_peak)
    return before | {key: getattr(state.resources, key) for key in ("hp", "gold", "hope_max", "squad_capacity")}


def context(ctx):
    from terralocal.server.domain import rogue_runs
    from terralocal.server.domain.rogue_map_drafts import current_map

    run, children = rogue_runs.active(ctx, required=True)
    zone = current_map(ctx, run, children[0])
    if run.state != "MAP_READY" or zone is None or run.hp <= 0:
        raise DomainError("ROGUE_MAP_NOT_ACTIVE", "请先进入生命有效的探索地图", 409)
    return run, children, zone, ctx.session.get(m.RogueMapDraft, run.id)


def path_in_session(ctx, run, zone, *, whole=False):
    from terralocal.server.domain.rogue_settlement import rows as settlements
    from terralocal.server.domain.rogue_shops import rows as shops

    battles = ctx.session.scalars(select(m.RogueBattle).where(m.RogueBattle.run_id == run.id)).all()
    entries, previous, boundary, pending = timeline(
        run, zone, battles, rows(ctx.session, run.id), settlements(ctx.session, run.id), shops(ctx.session, run.id))
    if not whole:
        entries = [e for e in entries if row_index(e[3]) == index(zone)]
    return entries, previous, boundary, pending


def authorize(ctx):
    local = ctx.local_session
    latest = ctx.session.scalar(select(m.LocalSession.id).where(m.LocalSession.account_id == ctx.account_id,
        m.LocalSession.kind == "game").order_by(m.LocalSession.id.desc()).limit(1))
    if local is None or local.kind != "game" or local.account_id != ctx.account_id or local.id != latest:
        raise DomainError("INVALID_SESSION", "请使用最新游戏登录处理探索事件", 401)


def prepare(ctx, bindings, *, zone_index=None):
    """Internal explicit map plan admission; never a client reward API."""
    run, children, zone, draft = context(ctx)
    number = index(zone) if zone_index is None else zone_index
    if type(number) is not int or number < index(zone):
        raise invalid()
    zone_for(zone, SimpleNamespace(zone_index=number))
    if type(bindings) is not dict or not 1 <= len(bindings) <= 256:
        raise invalid()
    costs = recruit_costs(children[3], children[4])
    assigned_relic_programs = {r.program_id for r in rows(ctx.session, run.id) if r.program_id in RELIC_PROGRAMS}
    for point, program_id in bindings.items():
        if not isinstance(point, Point):
            raise invalid()
        proposed = SimpleNamespace(program_id=program_id, zone_index=number, node_x=point.x, node_y=point.y)
        program = program_for_visit(ctx.data, run, draft, proposed)
        if program is None:
            raise invalid()
        existing = next((r for r in rows(ctx.session, run.id) if r.zone_index == number
                         and (r.node_x, r.node_y) == (point.x, point.y)), None)
        if existing:
            validate(ctx.data, run, draft, zone, existing, costs)
            if existing.program_id != program_id:
                raise DomainError("ROGUE_EVENT_PLAN_CONFLICT", "该节点已有不同的已保存事件", 409)
            continue
        # Local trusted-plan constraint, not an inferred official spawn rule.
        # Each complete source is assigned once per run; no duplicate farming.
        if program_id in RELIC_PROGRAMS or program_id in CONFIGURED_PROGRAMS:
            from terralocal.server.domain import rogue_loot_plans

            item_ids = (proposed._configured_visit.reservations if program_id in CONFIGURED_PROGRAMS else
                        {item for (source, _), item in EVENT_RELICS.items() if source == program_id})
            if item_ids & rogue_loot_plans.candidate_ids(rogue_loot_plans.rows(ctx.session, run.id)):
                raise DomainError("ROGUE_RELIC_SUPPLY_CONFLICT", "收藏品已配置为战斗奖励，不能再配置到事件", 409)
            if program_id in RELIC_PROGRAMS and program_id in assigned_relic_programs:
                raise DomainError("ROGUE_RELIC_EVENT_DUPLICATE", "此固定收藏品来源已绑定其他节点", 409)
            assigned_relic_programs.add(program_id)
        row = m.RogueSceneVisit(id=str(uuid.uuid4()), run_id=run.id, account_id=ctx.account_id,
            zone_index=number, node_x=point.x, node_y=point.y, program_id=program_id, policy_version=POLICY,
            rule_hash="", state="PREPARED", before={}, recruit_count=None, steps=[],
            prepared_at=max(ctx.now, draft.activated_at), entered_at=None, ended_at=None)
        row.rule_hash = assignment_hash(ctx.data, run, draft, row, program)
        validate(ctx.data, run, draft, zone, row, costs)
        ctx.session.add(row)
    ctx.session.flush()


def move(ctx, target):
    authorize(ctx)
    run, children, zone, draft = context(ctx)
    point = Point(target["x"], target["y"])
    point.validate()
    visits = rows(ctx.session, run.id)
    from terralocal.server.domain import rogue_shops

    visits = [*visits, *rogue_shops.rows(ctx.session, run.id)]
    row = next((r for r in visits if r.zone_index == index(zone)
                and (r.node_x, r.node_y) == (point.x, point.y)), None)
    entries, previous, boundary, pending = path_in_session(ctx, run, zone)
    if row and row.state != "PREPARED":
        if previous == point:
            return {}  # Last-node retry cannot recreate an event or its effects.
        raise DomainError("ROGUE_NODE_PASSED", "不能返回已经离开的节点", 409)
    if pending or any(t.state != "DONE" for t in children[2]):
        raise DomainError("ROGUE_EVENT_PENDING", "请先处理当前事件、战斗或招募", 409)
    if point not in zone.successors(previous):
        raise DomainError("ROGUE_NODE_UNREACHABLE", "目标不是当前可达的相邻节点", 409)
    node = next(n for n in zone.nodes if n.pos == point)
    if node.kind == "SHOP":
        return rogue_shops.enter(ctx, run, children, zone, draft, point, boundary)
    if node.kind not in ("INCIDENT", "REST", "TREASURE", "ENTERTAINMENT"):
        raise DomainError("ROGUE_NODE_FLOW_UNSUPPORTED", "此节点需要专用处理流程", 501)
    if row is None:
        raise DomainError("ROGUE_EVENT_PLAN_MISSING", "缺少此节点匹配版本的已保存事件方案", 503)
    from terralocal.server.domain.rogue_settlement import PROPERTIES, state_in_session

    history = state_in_session(ctx, run, children[2]).capsule_history
    before = {key: getattr(run, key) for key in PROPERTIES}
    try:
        row.before = history.preview(index(zone), node.kind, before)
    except ValueError as exc:
        raise DomainError("ROGUE_CAPSULE_RESOURCE_LIMIT", "剧目入场收益超出范围，未进入节点", 409) from exc
    for key in ("hp", "gold"):
        setattr(run, key, row.before[key])
    row.recruit_count = len(recruit_costs(children[3], children[4]))
    row.entered_at, row.state = max(ctx.now, boundary, row.prepared_at), "ACTIVE"
    ctx.session.flush()
    validate(ctx.data, run, draft, zone, row, recruit_costs(children[3], children[4]))
    return {}


def choose(ctx, choice):
    authorize(ctx)
    run, children, zone, draft = context(ctx)
    entries, _, _, _ = path_in_session(ctx, run, zone)
    if not entries and isinstance(zone, Layout):
        previous = path_in_session(ctx, run, zone, whole=True)[0]
        if (previous and previous[-1][2] == "scene" and row_index(previous[-1][3]) == zone.index - 1
                and previous[-1][3].steps and previous[-1][3].steps[-1]["choice"] == choice):
            return {}  # Retry after that scene advanced to an unvisited next floor.
    if not entries or entries[-1][2] != "scene":
        raise DomainError("ROGUE_SCENE_NOT_PENDING", "当前不是可处理的场景", 409)
    row = entries[-1][3]
    program, state = validate(ctx.data, run, draft, zone, row, recruit_costs(children[3], children[4]))
    if row.steps and row.steps[-1]["choice"] == choice and (
            state.scene is None or not any(b.choice == choice for b in program.frames[state.scene].branches)):
        if row.state == "FINISHED":
            from terralocal.server.domain.rogue_progress import advance

            advance(ctx)
        return {}
    if row.state != "ACTIVE":
        raise DomainError("ROGUE_SCENE_NOT_PENDING", "场景已经结束", 409)
    if any(t.state != "DONE" for t in children[2]):
        raise DomainError("ROGUE_EVENT_PENDING", "请先完成或放弃当前招募，未离开休整节点", 409)
    choices = tuple(s["choice"] for s in row.steps)
    occurrence = choices.count(choice)
    grant = ticket_item(row, choice, occurrence)
    relic = relic_for(row, choice, occurrence)
    if relic:
        if row.program_id not in CONFIGURED_PROGRAMS:
            ctx.data.rogue_battle_attributes.require_open(relic, run.created_at)
        if any(r.item_id == relic for r in children[1]):
            raise DomainError("ROGUE_RELIC_ALREADY_OWNED", "探索已拥有此无叠层收藏品，未重复发放", 409)
    if grant and row.program_id in REST_PROGRAMS:
        from terralocal.server.domain.rogue_training import eligible

        if not eligible(ctx.data, REST_TICKET, children[3], children[4]):
            raise DomainError("ROGUE_NO_UPGRADE_TARGET", "没有符合当前进阶券的未进阶干员，未发放票券", 409)
    initial = Resources(row.before["hp"], row.before["gold"], row.before["hope_max"],
                        sum(recruit_costs(children[3], children[4])[:row.recruit_count]), row.before["squad_capacity"])
    state = decide(program, initial, choices, choice)
    at = max(ctx.now, row.entered_at, *(s["at"] for s in row.steps))
    step = {"choice": choice, "at": at}
    if grant:
        step["ticket"] = len(children[2])
        ctx.session.add(m.RogueRunTicket(run_id=run.id, ordinal=step["ticket"], item_id=grant,
                                        state="CREATE", created_at=at))
    if relic:
        ctx.session.add(m.RogueRunRelic(run_id=run.id, ordinal=len(children[1]), item_id=relic,
            count=1, layer=0, acquired_at=at, used=False))
    row.steps = row.steps + [step]
    for key in ("hp", "gold", "hope_max", "squad_capacity"):
        setattr(run, key, getattr(state.resources, key))
    if state.scene is None:
        row.state, row.ended_at = "FINISHED", at
    ctx.session.flush()
    if grant:
        from terralocal.server.domain.rogue_recruit import activate

        activate(ctx, str(step["ticket"]))
    if row.state == "FINISHED":
        from terralocal.server.domain.rogue_progress import advance

        advance(ctx)
    return {}


def finish_if_scene(ctx):
    run, children, zone, draft = context(ctx)
    entries, _, _, _ = path_in_session(ctx, run, zone)
    if not entries or entries[-1][2] != "scene":
        return False
    row = entries[-1][3]
    if row.state == "FINISHED":
        authorize(ctx)
        from terralocal.server.domain.rogue_progress import advance

        advance(ctx)
        return True
    program, state = validate(ctx.data, run, draft, zone, row, recruit_costs(children[3], children[4]))
    options = program.frames[state.scene].branches
    leaves = [b.choice for b in options if program.choices[b.choice].kind == "LEAVE"]
    if len(options) != 1 or len(leaves) != 1:
        raise DomainError("ROGUE_SCENE_CHOICE_REQUIRED", "请先作出当前场景选择，未跳过收益或条件", 409)
    choose(ctx, leaves[0])
    return True


def pending(ctx, run, zone, children):
    entries, point, _, _ = path_in_session(ctx, run, zone)
    if not entries or entries[-1][2] != "scene":
        return None
    row = entries[-1][3]
    if row.state == "FINISHED":
        return point.wire(), None
    program, state = validate(ctx.data, run, ctx.session.get(m.RogueMapDraft, run.id), zone,
                              row, recruit_costs(children[3], children[4]))
    content = scene_content(program, state)
    owned = {r.item_id for r in children[1]}
    for choice in content["choices"]:
        if relic_for(row, choice, state.steps.count(choice)) in owned:
            content["choices"][choice] = False
    if row.program_id in REST_PROGRAMS and UPGRADE_CHOICE in content["choices"]:
        from terralocal.server.domain.rogue_training import eligible

        content["choices"][UPGRADE_CHOICE] = bool(eligible(ctx.data, REST_TICKET, children[3], children[4]))
    return point.wire(), {"index": row.id, "type": "SCENE", "content": {"scene": content, "done": False}}


def acquisitions(row):
    """Read the validated ticket and relic grants in the original step order."""
    occurrences = Counter()
    for step in row.steps:
        choice = step["choice"]
        occurrence = occurrences[choice]
        item = ticket_item(row, choice, occurrence) or relic_for(row, choice, occurrence)
        if item is not None:
            yield step.get("ticket"), item, step["at"]
        occurrences[choice] += 1


def relic_grants(row):
    return [(item, at) for ticket, item, at in acquisitions(row) if ticket is None]


def owns_pending_ticket(ctx, run, ordinal):
    from terralocal.server.domain.rogue_progress import in_session

    draft = ctx.session.get(m.RogueMapDraft, run.id)
    entries = path_in_session(ctx, run, in_session(ctx, run, draft))[0]
    if not entries or entries[-1][2] != "scene" or entries[-1][3].state != "ACTIVE":
        return False
    row = entries[-1][3]
    if row.program_id == RECREATION_PROGRAM:
        program_for_visit(ctx.data, run, draft, row)
    return any(index == ordinal for index, _, _ in acquisitions(row))


def abandon(ctx, run):
    boundary = run.created_at
    for row in rows(ctx.session, run.id):
        boundary = max(boundary, row.prepared_at, row.ended_at or row.entered_at or 0,
                       *(s["at"] for s in row.steps))
        if row.state == "ACTIVE":
            row.state, row.ended_at = "ABANDONED", max(ctx.now, boundary)
            boundary = row.ended_at
    return boundary


def preflight(path):
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        present = con.execute("SELECT 1 FROM sqlite_master WHERE name='rlv2_scene_visits'").fetchone()
        if not present:
            from terralocal.server.persistence.migrations import CURRENT_REVISIONS, ROGUE_SCENE_REVISION

            v = con.execute("SELECT version_num FROM alembic_version").fetchone() if con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone() else None
            if v and v[0] in (*CURRENT_REVISIONS, ROGUE_SCENE_REVISION):
                raise ValueError(invalid().message)
            return
        if con.execute("SELECT 1 FROM rlv2_scene_visits s LEFT JOIN rlv2_runs r ON s.run_id=r.id "
                       "WHERE r.id IS NULL OR s.account_id!=r.account_id LIMIT 1").fetchone():
            raise ValueError(invalid().message)
