"""Independent first-theme battle starts and immutable formation binding.

Base ordinary clears and natural defeat are admitted by a separate service.
Interrupted-client resumption and native successful combat remain unverified.
The pending battle's state0 matches the frozen default loader, not a server
fixture; no ordinary AP, permanent roster or stage progress is changed.
"""

import json
import secrets
import sqlite3
import uuid
from contextlib import closing
from types import SimpleNamespace

from sqlalchemy import select

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_giveup import confirmed_closure
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_progress import Layout, index, row_index, zone_for
from terralocal.server.domain.sessions import battle_binding
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.gamedata.rogue_map import BATTLE_TYPES
from terralocal.server.persistence import models as m

POLICY = "rogue-first-battle-start-v1"
ZONE_POLICY = "rogue-floor-battle-start-v2"
TOOL_POLICY = "rogue-tool-battle-start-v3"
TOOL_ZONE_POLICY = "rogue-floor-tool-battle-start-v4"
PLANNED_POLICY = "rogue-first-loot-battle-start-v5"
PLANNED_ZONE_POLICY = "rogue-floor-loot-battle-start-v6"
PLANNED_TOOL_POLICY = "rogue-first-loot-tool-start-v7"
PLANNED_TOOL_ZONE_POLICY = "rogue-floor-loot-tool-start-v8"
PLANNED_POLICIES = frozenset({PLANNED_POLICY, PLANNED_ZONE_POLICY, PLANNED_TOOL_POLICY, PLANNED_TOOL_ZONE_POLICY})
TOOL_POLICIES = frozenset({TOOL_POLICY, TOOL_ZONE_POLICY, PLANNED_TOOL_POLICY, PLANNED_TOOL_ZONE_POLICY})
POLICIES = frozenset({POLICY, ZONE_POLICY}) | TOOL_POLICIES | PLANNED_POLICIES


def invalid():
    return DomainError("ROGUE_BATTLE_INCOMPATIBLE", "探索战斗记录不兼容；请保留原存档", 503)


def formation(run, troop, slots):
    if type(slots) is not list or not 1 <= len(slots) <= 12:
        raise DomainError("ROGUE_SQUAD_INVALID", "探索编队必须为有界槽位列表")
    result, used = [], set()
    for slot in slots:
        if slot is None:
            result.append(None)
            continue
        if (type(slot) is not dict or set(slot) - {"charInstId", "skillIndex", "currentEquip"}
                or not {"charInstId", "skillIndex"} <= set(slot)
                or type(slot["charInstId"]) is not int or type(slot["skillIndex"]) is not int):
            raise DomainError("ROGUE_SQUAD_INVALID", "探索编队字段不匹配")
        inst, skill = slot["charInstId"], slot["skillIndex"]
        char = troop.get(str(inst))
        if char is None or inst in used:
            raise DomainError("ROGUE_SQUAD_MEMBER_INVALID", "编队干员不属于当前探索或重复出现")
        if slot.get("currentEquip") is not None:
            raise DomainError("ROGUE_MODULE_UNSUPPORTED", "此主题初始干员不接纳模组战斗", 501)
        skills = char["skills"]
        if (skills and (skill not in range(len(skills)) or not skills[skill]["unlock"])) \
                or (not skills and skill != -1):
            raise DomainError("ROGUE_SKILL_LOCKED", "所选技能未在当前探索干员阶段解锁")
        used.add(inst)
        result.append({"charInstId": inst, "skillIndex": skill,
                       "character": char | {"defaultSkillIndex": skill}})
    if not used or len(used) > run.squad_capacity:
        raise DomainError("ROGUE_SQUAD_CAPACITY", "探索编队为空或超过当前携带上限")
    return result


def request_hash(target, stage, squad, *, zone_index=1, roster_revisions=None, loot_hash=None):
    value = {"to": target.wire(), "stage": stage, "slots": [
        {"charInstId": s["charInstId"], "skillIndex": s["skillIndex"]} if s else None for s in squad]}
    if zone_index != 1:
        value.update(zone=zone_index, policy=ZONE_POLICY)
    if roster_revisions:
        value["rosterRevisions"] = roster_revisions
    if loot_hash is not None:
        value["battleLootPlan"] = loot_hash
    return fingerprint(value)


def target_node(zone, target, stage, previous=None, *, check_reachable=True):
    target.validate()
    if check_reachable and target not in zone.successors(previous):
        raise DomainError("ROGUE_NODE_UNREACHABLE", "目标不是当前可进入的相邻节点；未创建战斗", 409)
    node = next((n for n in zone.nodes if n.pos == target), None)
    if node is None:
        raise DomainError("ROGUE_NODE_INVALID", "目标节点不存在")
    if node.kind not in BATTLE_TYPES:
        raise DomainError("ROGUE_NODE_NOT_BATTLE", "非战斗节点不能使用战斗开始接口")
    if node.stage != stage:
        raise DomainError("ROGUE_STAGE_MISMATCH", "战斗关卡与已保存节点不一致")
    return node


def validate(data, run, draft, zone, troop, row, origin):
    try:
        number = row_index(row)
        zone = zone_for(zone, row)
        if (str(uuid.UUID(row.id)) != row.id or row.account_id != run.account_id or row.run_id != run.id
                or row.gamedata_hash != data.manifest["hash"] or row.gamedata_hash != run.gamedata_hash
                or row.policy_version not in POLICIES
                or (row.policy_version in {POLICY, TOOL_POLICY, PLANNED_POLICY, PLANNED_TOOL_POLICY}) != (number == 1)
                or (row.policy_version in PLANNED_POLICIES) != (getattr(row, "_loot_plan", None) is not None)
                or origin is None or origin.account_id != row.account_id
                or origin.kind != "game" or origin.id != row.session_id
                or row.session_binding != battle_binding(origin)
                or type(row.seed) is not int or not 0 <= row.seed <= 2**31 - 1
                or type(row.started_at) is not int or not draft.activated_at <= row.started_at <= 2**63 - 1
                or type(row.login_time) is not int or not 0 <= row.login_time <= 253_402_271_999):
            raise invalid()
        target = Point(row.node_x, row.node_y)
        target_node(zone, target, row.stage_id, check_reachable=False)
        if type(row.squad) is not list or any(s is not None and (
                type(s) is not dict or set(s) != {"charInstId", "skillIndex", "character"}) for s in row.squad):
            raise invalid()
        slots = [{"charInstId": s["charInstId"], "skillIndex": s["skillIndex"]} if s else None for s in row.squad]
        revisions = getattr(row, "roster_revisions", {})
        selected = {str(s["charInstId"]) for s in slots if s}
        if type(revisions) is not dict or not set(revisions) <= selected:
            raise invalid()
        from terralocal.server.domain.rogue_training import Troop

        historical = troop.at(revisions, row.started_at) if isinstance(troop, Troop) else troop
        if (revisions and not isinstance(troop, Troop)
                or canonical(formation(run, historical, slots)) != canonical(row.squad)
                or row.request_hash != request_hash(target, row.stage_id, row.squad, zone_index=number,
                    roster_revisions=revisions, loot_hash=getattr(getattr(row, "_loot_plan", None), "rule_hash", None))):
            raise invalid()
        if row.state == "STARTED":
            if row.ended_at is not None or run.state != "MAP_READY" or run.ended_at is not None:
                raise invalid()
        elif row.state == "FINISHED":
            if (run.state not in ("MAP_READY", "ABANDONED", "SETTLED") or type(row.ended_at) is not int
                    or not row.started_at <= row.ended_at <= 2**63 - 1
                    or (run.ended_at is not None and row.ended_at > run.ended_at)):
                raise invalid()
        elif row.state == "ABANDONED":
            if (run.state != "ABANDONED" and not confirmed_closure(run) or run.ended_at is None or type(row.ended_at) is not int
                    or not row.started_at <= row.ended_at <= run.ended_at <= 2**63 - 1):
                raise invalid()
        else:
            raise invalid()
    except (ValueError, KeyError, TypeError, AttributeError, DomainError) as exc:
        raise invalid() from exc


def context(ctx, *, progress_out=None):
    from terralocal.server.domain.rogue_map_drafts import current_map
    from terralocal.server.domain.rogue_recruit import project as recruit_project
    from terralocal.server.domain.rogue_runs import active

    run, children = active(ctx, required=True, progress_out=progress_out)
    zone = current_map(ctx, run, children[0])
    if run.state != "MAP_READY" or zone is None:
        raise DomainError("ROGUE_MAP_NOT_ACTIVE", "请先完成初始化并进入探索地图", 409)
    troop = recruit_project(children[2], children[3], children[4])[1]
    return run, ctx.session.get(m.RogueMapDraft, run.id), zone, troop


def ensure_no_active(ctx):
    if ctx.session.scalar(select(m.RogueBattle.id).where(m.RogueBattle.account_id == ctx.account_id,
                                                       m.RogueBattle.state == "STARTED")):
        raise DomainError("ROGUE_BATTLE_ACTIVE", "当前探索战斗尚未结算", 409)


def start(ctx, to, stage, slots):
    progress = []
    run, draft, zone, troop = context(ctx, progress_out=progress)
    tool = getattr(progress[0], "support_tool", None)
    if run.hp == 0:
        raise DomainError("ROGUE_RUN_OVER", "探索生命已归零，请先处理探索结束", 409)
    origin = ctx.local_session
    latest = ctx.session.scalar(select(m.LocalSession.id).where(
        m.LocalSession.account_id == ctx.account_id, m.LocalSession.kind == "game")
        .order_by(m.LocalSession.id.desc()).limit(1))
    if origin is None or origin.kind != "game" or origin.account_id != ctx.account_id or origin.id != latest:
        raise DomainError("INVALID_SESSION", "请使用最新的游戏登录开始探索战斗", 401)
    if to is None:
        raise DomainError("ROGUE_BATTLE_RESUME_UNSUPPORTED", "未指定新节点；中断战斗的原生续接尚未接通", 501)
    if type(to) is not dict or set(to) != {"x", "y"}:
        raise DomainError("ROGUE_NODE_INVALID", "探索战斗目标必须为明确坐标")
    target = Point(to["x"], to["y"])
    squad = formation(run, troop, slots)
    revisions = troop.revisions(squad)
    number = index(zone)
    plan = ctx.session.get(m.RogueBattleLootPlan, (run.id, number, target.x, target.y))
    digest = request_hash(target, stage, squad, zone_index=number, roster_revisions=revisions,
                          loot_hash=plan.rule_hash if plan else None)
    existing = ctx.session.scalars(select(m.RogueBattle).where(m.RogueBattle.run_id == run.id)).all()
    if any(r.policy_version in PLANNED_POLICIES for r in existing):
        from terralocal.server.domain import rogue_loot_plans

        rogue_loot_plans.attach(ctx.data, run, draft, rogue_loot_plans.rows(ctx.session, run.id), existing)
    existing.sort(key=lambda row: (row_index(row), row.node_x, row.node_y))
    if any(row.state == "STARTED" and row_index(row) != number for row in existing):
        raise invalid()
    from terralocal.server.domain.rogue_settlement import rows as settlements

    history = settlements(ctx.session, run.id)
    active_rows = [row for row in existing if row.state == "STARTED"]
    if len(active_rows) > 1:
        raise invalid()
    if active_rows:
        row = active_rows[0]
        saved = ctx.session.get(m.LocalSession, row.session_id)
        validate(ctx.data, run, draft, zone, troop, row, saved)
        if row.session_binding != battle_binding(origin):
            raise DomainError("ROGUE_BATTLE_RESUME_UNSUPPORTED", "旧登录的探索战斗已保留，原生续接尚未接通", 501)
        if row.state != "STARTED" or row.request_hash != digest:
            raise DomainError("ROGUE_BATTLE_CONFLICT", "已有不同的探索战斗或编队；未创建新战斗", 409)
        return {"battleId": row.id}
    if history and history[-1].completed_at is None:
        raise DomainError("ROGUE_REWARD_PENDING", "请先处理战斗奖励；未开始下一节点", 409)
    from terralocal.server.domain.rogue_visits import path_in_session

    _, previous, boundary, pending_visit = path_in_session(ctx, run, zone)
    if pending_visit:
        raise DomainError("ROGUE_EVENT_PENDING", "当前场景尚未处理完，未开始战斗", 409)
    target_node(zone, target, stage, previous)
    if ctx.session.scalar(select(m.BattleSession.id).where(m.BattleSession.account_id == ctx.account_id,
                                                         m.BattleSession.state == "STARTED")):
        raise DomainError("ACTIVE_BATTLE", "普通战斗尚未结束，未开始探索战斗", 409)
    login = ctx.profile.flags.get("loginTime", ctx.profile.last_online_at)
    if type(login) is not int or not 0 <= login <= 253_402_271_999:
        raise DomainError("INVALID_LOGIN_TIME", "本地登录时间无效", 503)
    row = m.RogueBattle(id=str(uuid.uuid4()), account_id=ctx.account_id, run_id=run.id,
        session_id=origin.id, session_binding=battle_binding(origin), gamedata_hash=run.gamedata_hash,
        policy_version=(TOOL_POLICY if number == 1 else TOOL_ZONE_POLICY) if tool else (
            POLICY if number == 1 else ZONE_POLICY), zone_index=number,
        node_x=target.x, node_y=target.y, stage_id=stage, state="STARTED",
        seed=secrets.randbelow(2**31), started_at=max(ctx.now, draft.activated_at, boundary), ended_at=None,
        login_time=login, request_hash=digest, squad=squad, roster_revisions=revisions)
    row._loot_plan = plan
    if plan:
        row.policy_version = (PLANNED_TOOL_POLICY if number == 1 else PLANNED_TOOL_ZONE_POLICY) if tool else (
            PLANNED_POLICY if number == 1 else PLANNED_ZONE_POLICY)
    from terralocal.server.domain.rogue_settlement import admit_start

    relics = tuple(ctx.session.scalars(select(m.RogueRunRelic.item_id).where(
        m.RogueRunRelic.run_id == run.id, m.RogueRunRelic.ordinal > 0).order_by(m.RogueRunRelic.ordinal)))
    capsules = getattr(progress[0], "capsule_history", None)
    node = next(n for n in zone.nodes if n.pos == target)
    definition = capsules.matching(number, node.kind) if capsules is not None else None
    admit_start(ctx.data, run, row, zone, relics, definition.id if definition else None)
    ctx.session.add(row)
    ctx.session.flush()
    validate(ctx.data, run, draft, zone, troop, row, origin)
    return {"battleId": row.id}


def project(ctx, run, zone, troop, *, tool_bindings, tools=(), capsules=()):
    rows = ctx.session.scalars(select(m.RogueBattle).where(m.RogueBattle.run_id == run.id)).all()
    if not rows:
        return None
    if any(r.policy_version in PLANNED_POLICIES for r in rows):
        from terralocal.server.domain import rogue_loot_plans

        rogue_loot_plans.attach(ctx.data, run, ctx.session.get(m.RogueMapDraft, run.id),
                               rogue_loot_plans.rows(ctx.session, run.id), rows)
    if len(rows) > (512 if isinstance(zone, Layout) else 256):
        raise invalid()
    rows.sort(key=lambda r: (row_index(r), r.node_x, r.node_y))
    from terralocal.server.domain.rogue_visits import path_in_session

    path_in_session(ctx, run, zone)
    previous, boundary = None, 0
    for row in rows:
        validate(ctx.data, run, ctx.session.get(m.RogueMapDraft, run.id), zone, troop, row,
                 ctx.session.get(m.LocalSession, row.session_id))
        target_node(zone_for(zone, row), Point(row.node_x, row.node_y), row.stage_id, check_reachable=False)
        if row.started_at < boundary or (row is not rows[-1] and row.state != "FINISHED"):
            raise invalid()
        previous, boundary = Point(row.node_x, row.node_y), row.ended_at or row.started_at
    rows = [r for r in rows if row_index(r) == index(zone)]
    if not rows:
        return None
    row = rows[-1]
    if row.state == "FINISHED":
        from terralocal.server.domain.rogue_settlement import pending
        from terralocal.server.domain.rogue_settlement import rows as settlements

        records = settlements(ctx.session, run.id)
        if not records or records[-1].battle_id != row.id:
            raise invalid()
        relics = tuple(ctx.session.scalars(select(m.RogueRunRelic.item_id).where(
            m.RogueRunRelic.run_id == run.id, m.RogueRunRelic.ordinal > 0).order_by(m.RogueRunRelic.ordinal)))
        return previous.wire(), pending(records[-1], run, records, relics=relics, tools=tools, capsules=capsules) if records[-1].completed_at is None else None
    if row.state != "STARTED":
        raise invalid()
    if row.id not in tool_bindings:
        raise invalid()
    tool = tool_bindings[row.id]
    buffs = ctx.data.rogue_tool_effects.require(tool.item_id, run.created_at).wire() if tool else []
    # The validated timeline binds each battle before later tool replacements.
    # Remaining managed defaults are not a complete official resume fixture.
    content = {"state": 0, "chestCnt": 0, "goldTrapCnt": 0, "tmpChar": [], "unKeepBuff": buffs,
               "diceRoll": [], "sanity": 0, "boxInfo": {}, "isFailProtect": False, "seed": row.seed,
               "enemyHpInfo": {}, "battleSnapshot": None, "battleFailDisplay": "NORMAL"}
    return {"x": row.node_x, "y": row.node_y}, {
        "index": row.id, "type": "BATTLE", "content": {"battle": content}}


def inspect_finish(ctx, request):
    """Read and bind owned finish records without writes.

    The separate settlement service admits only its explicit outcome/reward
    policy. Inspection alone grants no rewards or node completion.
    """
    from terralocal.server.protocol.battle_codec import signature_battle_id
    from terralocal.server.protocol.rogue_battle_codec import decode_finish_records

    local = ctx.local_session
    if local is None or local.kind != "game" or local.account_id != ctx.account_id:
        raise DomainError("INVALID_SESSION", "请使用游戏登录提交探索战斗记录", 401)
    row = ctx.session.get(m.RogueBattle, signature_battle_id(request.battleData.isCheat))
    if row is None or row.account_id != ctx.account_id:
        raise DomainError("ROGUE_BATTLE_NOT_FOUND", "此账号没有该探索战斗", 404)
    run, draft, zone, troop = context(ctx)
    validate(ctx.data, run, draft, zone, troop, row, ctx.session.get(m.LocalSession, row.session_id))
    record = decode_finish_records(request, [row.login_time,
        ctx.profile.flags.get("loginTime", ctx.profile.last_online_at)],
        expected_battle_id=row.id, expected_stage_id=row.stage_id)
    if record.journal is not None:
        selected = {slot["charInstId"]: slot for slot in row.squad if slot is not None}
        if {member.operator_id for member in record.journal.squad} != set(selected):
            raise DomainError("ROGUE_JOURNAL_SQUAD", "探索记录与开战编队不一致")
        for member in record.journal.squad:
            slot = selected[member.operator_id]
            index, skills = slot["skillIndex"], slot["character"]["skills"]
            skill_id = skills[index]["skillId"] if skills else None
            if (member.skill_index != index or member.skill_id != skill_id or member.template_id is not None
                    or member.module_id != "" or member.module_level != 0 or member.is_assist):
                raise DomainError("ROGUE_JOURNAL_SQUAD", "探索记录的技能、模组或助战与开战快照不一致")
    return record


def abandon_run(ctx, run):
    boundary = run.created_at
    from terralocal.server.domain.rogue_settlement import rows

    for record in rows(ctx.session, run.id):
        boundary = max(boundary, record.created_at, record.completed_at or 0,
                       *(c["at"] for c in record.claims))
    for row in ctx.session.scalars(select(m.RogueBattle).where(m.RogueBattle.run_id == run.id)):
        boundary = max(boundary, row.ended_at or row.started_at)
        if row.state == "STARTED":
            _, draft, zone, troop = context(ctx)
            validate(ctx.data, run, draft, zone, troop, row, ctx.session.get(m.LocalSession, row.session_id))
            row.state, row.ended_at = "ABANDONED", max(row.started_at, ctx.now)
            boundary = max(boundary, row.ended_at)
    return boundary


def preflight(data, path):
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "rlv2_battles" not in tables:
            from terralocal.server.persistence.migrations import (
                CURRENT_REVISIONS,
                ROGUE_BATTLE_REVISION,
                ROGUE_ENDING_REVISION,
            ROGUE_SCENE_REVISION,
                ROGUE_SETTLEMENT_REVISION,
            )

            version = con.execute("SELECT version_num FROM alembic_version").fetchone() \
                if "alembic_version" in tables else None
            if version and version[0] in (*CURRENT_REVISIONS, ROGUE_SCENE_REVISION, ROGUE_ENDING_REVISION, ROGUE_SETTLEMENT_REVISION, ROGUE_BATTLE_REVISION):
                raise ValueError(invalid().message)
            return
        rows = list(con.execute("SELECT * FROM rlv2_battles"))
        if not rows:
            return
        try:
            from terralocal.server.domain.rogue_progress import on_disk
            from terralocal.server.domain.rogue_recruit import project as recruit_project

            active_accounts = set()
            for raw in rows:
                row = SimpleNamespace(**dict(raw))
                row.squad = json.loads(row.squad)
                if hasattr(row, "roster_revisions"):
                    row.roster_revisions = json.loads(row.roster_revisions)
                r = con.execute("SELECT * FROM rlv2_runs WHERE id=?", (row.run_id,)).fetchone()
                d = con.execute("SELECT * FROM rlv2_map_drafts WHERE run_id=?", (row.run_id,)).fetchone()
                local = con.execute("SELECT * FROM local_sessions WHERE id=?", (row.session_id,)).fetchone()
                if r is None or d is None or local is None:
                    raise invalid()
                run, draft = SimpleNamespace(**dict(r)), SimpleNamespace(**dict(d))
                draft.plan, draft.graph = json.loads(draft.plan), json.loads(draft.graph)
                children = []
                for table in ("rlv2_tickets", "rlv2_recruit_options", "rlv2_chars"):
                    values = []
                    for raw_child in con.execute('SELECT * FROM "' + table + '" WHERE run_id=? ORDER BY ordinal',
                                                 (row.run_id,)):
                        value = dict(raw_child)
                        if table == "rlv2_recruit_options":
                            value["character"] = json.loads(value["character"])
                        if table == "rlv2_chars" and "training" in value:
                            value["training"] = json.loads(value["training"])
                        values.append(SimpleNamespace(**value))
                    children.append(values)
                troop = recruit_project(*children)[1]
                from terralocal.server.domain import rogue_loot_plans

                rogue_loot_plans.attach(data, run, draft, rogue_loot_plans.read_rows(con, run.id), [row])
                validate(data, run, draft, on_disk(data, con, run, draft), troop, row,
                         SimpleNamespace(**dict(local)))
                if row.state == "STARTED":
                    if row.account_id in active_accounts or con.execute(
                            "SELECT 1 FROM battle_sessions WHERE account_id=? AND state='STARTED' LIMIT 1",
                            (row.account_id,)).fetchone():
                        raise invalid()
                    active_accounts.add(row.account_id)
        except (DomainError, ValueError, TypeError, KeyError, AttributeError, sqlite3.DatabaseError) as exc:
            raise ValueError(invalid().message) from exc
