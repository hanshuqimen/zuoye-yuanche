"""Owned multi-floor cursor bound to explicit saved maps and completed visits.

The cursor carries no rewards. Only existing node transactions can advance it;
neither the client nor map preparation chooses a destination or an effect.
This is not an official map distribution or a hidden-floor unlock policy.
"""

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from types import SimpleNamespace

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_floors import FLOOR_POLICIES, MAX_FLOORS
from terralocal.server.domain.rogue_map import Point
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m

POLICY = "rogue-explicit-floor-cursor-v1"


def invalid():
    return DomainError("ROGUE_FLOOR_INCOMPATIBLE", "探索楼层游标或过层记录不一致；请保留原存档", 503)


def row_index(row):
    # Read-only admission of historical schemas before migration. New ORM rows
    # and schema0028 disk rows always have this field and may not default null.
    value = getattr(row, "zone_index", 1)
    if type(value) is not int or not 1 <= value <= MAX_FLOORS:
        raise invalid()
    return value


@dataclass(frozen=True)
class Transition:
    zone: int
    kind: str
    record_id: str
    x: int
    y: int
    at: int


@dataclass(frozen=True)
class Layout:
    zones: tuple
    index: int
    journal: tuple[Transition, ...]
    activated_at: int

    @property
    def current(self):
        return self.zones[self.index - 1]

    @property
    def id(self):
        return self.current.id

    @property
    def nodes(self):
        return self.current.nodes

    def wire(self):
        return self.current.wire()

    def successors(self, point):
        return self.current.successors(point)


def index(layout):
    return layout.index if isinstance(layout, Layout) else 1


def zone_for(layout, row):
    number = row_index(row)
    if isinstance(layout, Layout):
        if number > len(layout.zones):
            raise invalid()
        return layout.zones[number - 1]
    if number != 1 or layout is None:
        raise invalid()
    return layout


def binding(run, draft, cursor):
    return fingerprint({"policy": POLICY, "run": run.id, "data": run.gamedata_hash, "seed": run.seed,
        "map": draft.plan_hash, "activated": cursor.activated_at, "zone": cursor.zone_index,
        "journal": cursor.journal})


def initial_values(run, draft):
    if draft.policy_version not in FLOOR_POLICIES or draft.activated_at is None:
        raise invalid()
    values = dict(run_id=run.id, policy_version=POLICY, map_hash=draft.plan_hash,
                  zone_index=1, activated_at=draft.activated_at, journal=[])
    values["rule_hash"] = binding(run, draft, SimpleNamespace(**values))
    return values


def layout(data, run, draft, cursor, *, legacy=False):
    from terralocal.server.domain.rogue_map_drafts import validate_floors

    zones = validate_floors(data, run, draft)
    if draft.policy_version not in FLOOR_POLICIES:
        if cursor is not None:
            raise invalid()
        return zones[0]
    if draft.activated_at is None:
        if cursor is not None:
            raise invalid()
        return Layout(zones, 1, (), 0)
    if cursor is None:
        if not legacy:
            raise invalid()
        cursor = SimpleNamespace(**initial_values(run, draft))
    try:
        if (cursor.run_id != run.id or cursor.policy_version != POLICY or cursor.map_hash != draft.plan_hash
                or cursor.activated_at != draft.activated_at or type(cursor.journal) is not list
                or len(cursor.journal) >= MAX_FLOORS or type(cursor.zone_index) is not int
                or cursor.zone_index != len(cursor.journal) + 1 or not 1 <= cursor.zone_index <= len(zones)
                or cursor.rule_hash != binding(run, draft, cursor)):
            raise invalid()
        journal, boundary = [], cursor.activated_at
        for number, raw in enumerate(cursor.journal, 1):
            if type(raw) is not dict or set(raw) != {"zone", "kind", "record_id", "x", "y", "at"}:
                raise invalid()
            t = Transition(**raw)
            point = Point(t.x, t.y)
            point.validate()
            if (type(t.zone) is not int or t.zone != number or t.kind not in ("battle", "scene", "shop")
                    or str(uuid.UUID(t.record_id)) != t.record_id or type(t.at) is not int
                    or not boundary <= t.at < 2**63 or run.ended_at is not None and t.at > run.ended_at):
                raise invalid()
            node = next(n for n in zones[number - 1].nodes if n.pos == point)
            if node.next:
                raise invalid()
            journal.append(t)
            boundary = t.at
        return Layout(zones, cursor.zone_index, tuple(journal), cursor.activated_at)
    except (ValueError, KeyError, TypeError, AttributeError, StopIteration) as exc:
        raise invalid() from exc


def in_session(ctx, run, draft=None):
    draft = draft or ctx.session.get(m.RogueMapDraft, run.id)
    if draft is None:
        if ctx.session.get(m.RogueFloorCursor, run.id) is not None:
            raise invalid()
        return None
    return layout(ctx.data, run, draft, ctx.session.get(m.RogueFloorCursor, run.id))


def read_draft(con, run_id):
    raw = con.execute("SELECT * FROM rlv2_map_drafts WHERE run_id=?", (run_id,)).fetchone()
    if raw is None:
        return None
    value = dict(raw)
    value["plan"], value["graph"] = json.loads(value["plan"]), json.loads(value["graph"])
    return SimpleNamespace(**value)


def on_disk(data, con, run, draft=None):
    if draft is None:
        draft = read_draft(con, run.id)
        if draft is None:
            return None
    raw = con.execute("SELECT * FROM rlv2_floor_cursors WHERE run_id=?", (run.id,)).fetchone() if con.execute(
        "SELECT 1 FROM sqlite_master WHERE name='rlv2_floor_cursors'").fetchone() else None
    cursor = None
    if raw is not None:
        value = dict(raw)
        value["journal"] = json.loads(value["journal"])
        cursor = SimpleNamespace(**value)
    from terralocal.server.persistence.migrations import CURRENT_REVISIONS

    version = con.execute("SELECT version_num FROM alembic_version").fetchone()
    return layout(data, run, draft, cursor, legacy=version is not None and version[0] not in CURRENT_REVISIONS)


def activate(ctx, run, draft):
    if draft.policy_version in FLOOR_POLICIES:
        if ctx.session.get(m.RogueFloorCursor, run.id) is not None:
            raise invalid()
        ctx.session.add(m.RogueFloorCursor(**initial_values(run, draft)))


def advance(ctx):
    """Same transaction as completing the last node; never a public jump API."""
    from terralocal.server.domain.rogue_runs import active
    from terralocal.server.domain.rogue_visits import path_in_session

    run, children = active(ctx, required=True)
    current = in_session(ctx, run)
    if not isinstance(current, Layout) or run.state != "MAP_READY" or run.hp <= 0:
        return False
    entries, point, boundary, pending = path_in_session(ctx, run, current)
    if (not entries or pending or point is None or current.successors(point)
            or any(t.state != "DONE" for t in children[2]) or current.index == len(current.zones)):
        return False
    x, y, kind, visit = entries[-1]
    if visit.state != "FINISHED":
        raise invalid()
    t = Transition(current.index, kind, visit.id, x, y, max(ctx.now, boundary))
    cursor = ctx.session.get(m.RogueFloorCursor, run.id)
    cursor.zone_index += 1
    cursor.journal = cursor.journal + [asdict(t)]
    cursor.rule_hash = binding(run, ctx.session.get(m.RogueMapDraft, run.id), cursor)
    ctx.session.flush()
    return True


def preflight(data, path):
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        from terralocal.server.persistence.migrations import CURRENT_REVISIONS, ROGUE_SHOP_REVISION

        version = con.execute("SELECT version_num FROM alembic_version").fetchone() if "alembic_version" in tables else None
        if version and version[0] == ROGUE_SHOP_REVISION:
            for table in m.Base.metadata.sorted_tables:
                if table.name == "rlv2_battle_loot_plans":
                    continue  # This branch admits legacy0027 before additive0037 migration.
                if not table.name.startswith("rlv2_") or (
                        version[0] == ROGUE_SHOP_REVISION and table.name in ("rlv2_floor_cursors", "rlv2_run_closures")):
                    continue
                columns = set(table.columns.keys())
                if version[0] == ROGUE_SHOP_REVISION and table.name == "rlv2_battles":
                    columns.remove("zone_index")
                if table.name not in tables or columns - {
                        r[1] for r in con.execute('PRAGMA table_info("' + table.name + '")')}:
                    raise ValueError(invalid().message)
            if version[0] == ROGUE_SHOP_REVISION and "rlv2_floor_cursors" in tables and con.execute(
                    "SELECT 1 FROM rlv2_floor_cursors LIMIT 1").fetchone():
                raise ValueError(invalid().message)
        if version and version[0] in CURRENT_REVISIONS and ("rlv2_floor_cursors" not in tables or
                "rlv2_battles" in tables and "zone_index" not in {
                    r[1] for r in con.execute("PRAGMA table_info(rlv2_battles)")}):
            raise ValueError(invalid().message)
        if "rlv2_floor_cursors" not in tables:
            return
        if "rlv2_map_drafts" not in tables and version and version[0] in CURRENT_REVISIONS:
            from terralocal.server.domain.rogue_map_drafts import invalid as invalid_draft

            raise ValueError(invalid_draft().message)
        try:
            for raw in con.execute("SELECT * FROM rlv2_floor_cursors"):
                run = con.execute("SELECT * FROM rlv2_runs WHERE id=?", (raw["run_id"],)).fetchone()
                if run is None or on_disk(data, con, SimpleNamespace(**dict(run))) is None:
                    raise invalid()
            if version and version[0] in CURRENT_REVISIONS:
                for raw in con.execute("SELECT r.* FROM rlv2_runs r JOIN rlv2_map_drafts d ON r.id=d.run_id "
                    "WHERE d.policy_version IN (?,?) AND d.activated_at IS NOT NULL", tuple(sorted(FLOOR_POLICIES))):
                    on_disk(data, con, SimpleNamespace(**dict(raw)))
        except (DomainError, ValueError, KeyError, TypeError, AttributeError, sqlite3.DatabaseError) as exc:
            raise ValueError(invalid().message) from exc
