"""Durable, version-bound Crisis V2 starts, before exposing a native route.

Selection arithmetic uses the REA-backed map rules. Admission to the current
season and a map's startTime is an explicit local policy. rewardEndTime is not
treated as a battle closing time. Finish/rewards and new-login recovery need
their own verified transactions; ordinary battle handlers cannot replace them.
"""

import json
import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, ValidationError
from sqlalchemy import select

from terralocal.server.api.schemas import Command, SquadSlot
from terralocal.server.domain import battle, crisis_v2
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.operators import check_condition
from terralocal.server.domain.sessions import battle_binding
from terralocal.server.gamedata.crisis_v2 import MapEvaluation
from terralocal.server.gamedata.repository import SHA256, fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.protocol.crisis_v2_battle import ScoreAxes
from terralocal.server.protocol.crisis_v2_state import Count, Key, NodeState, RuneState

POLICY = "cn-2.7.71-crisis-v2-battle-session-v1"
LoginTime = Annotated[int, Field(ge=0, le=253_402_271_999)]


class _Start(Command):
    map_id: Key
    squad_id: str = Field(min_length=1, max_length=16)
    slots: list[SquadSlot | None] = Field(max_length=12)
    rune_slots: list[Key] = Field(max_length=4096)
    assist_friend: dict | None


class _MapInputs(Command):
    rune: dict[Key, RuneState]
    challenge: dict[Key, NodeState]
    exRunes: dict[Key, RuneState]


class _Selection(Command):
    rune_slots: list[Key] = Field(max_length=4096)
    map_inputs: _MapInputs
    selected_nodes: list[Key] = Field(max_length=4096)
    scores: ScoreAxes


class _Member(Command):
    slot: int = Field(ge=0, le=11)
    charInstId: int = Field(ge=1)
    charId: Key
    skillIndex: int = Field(ge=-1, le=2)
    level: int = Field(ge=1)
    evolvePhase: Count
    skillLevel: int = Field(ge=1)
    potentialRank: Count
    trust: Count
    skinId: Key


class _NativeContext(Command):
    codec_version: Literal[POLICY]
    formation_mode: Literal["CRISIS_V2"]
    login_time: LoginTime
    session_binding: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PendingBattle:
    battle: m.BattleSession
    crisis: m.CrisisV2Battle
    evaluation: MapEvaluation


def _values(record):
    return {column.name: getattr(record, column.name) for column in record.__table__.columns}


def _start_hash(parent, saved):
    return fingerprint({"battle": {key: parent[key] for key in (
        "id", "account_id", "stage_id", "sanity_cost", "practice", "started_at", "seed",
        "squad_snapshot", "native_context")},
        "crisis": {key: saved[key] for key in m.CrisisV2Battle.__table__.columns.keys() if key != "start_hash"}})


def validate_record(data, parent, saved):
    """Read-only validation shared by startup, restore and domain consumers."""
    if not crisis_v2.available(data):
        raise ValueError("危机合约战斗缺少已绑定数据")
    catalog = data.crisis_v2
    if (saved["battle_id"] != parent["id"] or saved["account_id"] != parent["account_id"]
            or saved["policy_version"] != POLICY or saved["gamedata_hash"] != data.manifest["hash"]
            or saved["catalog_hash"] != catalog.fingerprint):
        raise ValueError("危机合约战斗的账号或版本绑定不匹配")
    key = (saved["season_id"], saved["map_id"])
    if key not in catalog.rules:
        raise ValueError("危机合约战斗引用了未导入的地图")
    rule = catalog.rules[key]
    challenges = catalog.challenges(*key)
    stage = catalog.info(key[0])["mapStageDataMap"][key[1]]
    if (saved["map_hash"] != rule.fingerprint or saved["challenge_hash"] != challenges.fingerprint
            or saved["level_id"] != stage["levelId"] or parent["stage_id"] != stage["stageId"]
            or type(parent["sanity_cost"]) is not int or parent["sanity_cost"] != 0
            or parent["practice"] is not False or parent["state"] != "STARTED"
            or parent["finished_at"] is not None or parent["settlement"] is not None
            or parent["request_hash"] is not None
            or type(parent["started_at"]) is not int or parent["started_at"] < 0
            or type(parent["seed"]) is not int or not 0 <= parent["seed"] < 2**31):
        raise ValueError("危机合约战斗的地图、状态或规则不匹配")
    _NativeContext.model_validate(parent["native_context"])
    members = [_Member.model_validate(row) for row in parent["squad_snapshot"]]
    if (not 1 <= len(members) <= 12 or len({row.charInstId for row in members}) != len(members)
            or [row.slot for row in members] != sorted({row.slot for row in members})):
        raise ValueError("危机合约战斗编队快照非法")
    selection = _Selection.model_validate(saved["selection"])
    if any(not rule.nodes[key].lockable for key in selection.map_inputs.exRunes if key in rule.nodes):
        raise ValueError("危机合约战斗附加符文引用非法")
    permanent = saved["map_id"] == catalog.permanent[saved["season_id"]]
    if not permanent and selection.map_inputs.exRunes:
        raise ValueError("危机合约临时地图混入附加符文状态")
    evaluation = rule.evaluate(selection.rune_slots, selection.map_inputs.model_dump(), permanent=permanent)
    if (selection.rune_slots != list(evaluation.rune_slots)
            or selection.selected_nodes != sorted(evaluation.selected_nodes)
            or selection.scores != list(evaluation.dimension_scores)
            or type(saved["start_hash"]) is not str or not SHA256.fullmatch(saved["start_hash"])
            or saved["start_hash"] != _start_hash(parent, saved)):
        raise ValueError("危机合约战斗选择快照或指纹不一致")
    return evaluation


def preflight(connection, data):
    # SQLite is already open read-only, before any migration or WAL setup.
    import sqlite3

    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("""SELECT 1 FROM battle_sessions b
                WHERE json_extract(b.native_context,'$.formation_mode')='CRISIS_V2'
                AND NOT EXISTS (SELECT 1 FROM crisis_v2_battles c WHERE c.battle_id=b.id) LIMIT 1""").fetchone():
            raise ValueError("危机合约公共会话缺少模式记录")
        if connection.execute("""SELECT 1 FROM crisis_v2_battles b
                LEFT JOIN crisis_v2_maps p ON p.account_id=b.account_id AND p.season_id=b.season_id AND p.map_id=b.map_id
                WHERE p.account_id IS NULL LIMIT 1""").fetchone():
            raise ValueError("危机合约战斗缺少所属地图纪录")
        for row in connection.execute("SELECT * FROM crisis_v2_battles"):
            saved = dict(row)
            source = connection.execute("SELECT * FROM battle_sessions WHERE id=?", (saved["battle_id"],)).fetchone()
            if source is None:
                raise ValueError("危机合约战斗缺少公共会话")
            parent = dict(source)
            saved["selection"] = json.loads(saved["selection"])
            for field in ("squad_snapshot", "native_context", "settlement"):
                parent[field] = json.loads(parent[field]) if parent[field] is not None else None
            parent["practice"] = {0: False, 1: True}.get(parent["practice"], parent["practice"])
            validate_record(data, parent, saved)
    except (sqlite3.DatabaseError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("危机合约战斗保存不兼容；请保留原配置和存档") from exc


def _latest_session(ctx):
    local = ctx.local_session
    if local is None or local.account_id != ctx.account_id or local.kind != "game":
        raise DomainError("INVALID_SESSION", "请重新登录后开始危机合约战斗", 401)
    latest = ctx.session.scalar(select(m.LocalSession.id).where(
        m.LocalSession.account_id == ctx.account_id, m.LocalSession.kind == "game")
        .order_by(m.LocalSession.id.desc()).limit(1))
    if latest != local.id:
        raise DomainError("INVALID_SESSION", "此账号已重新登录，请刷新客户端", 401)
    return battle_binding(local)


def context(ctx, battle_id, *, require_session=False):
    source = battle.get_session(ctx, battle_id)  # Ownership before reading the selection.
    saved = ctx.session.get(m.CrisisV2Battle, battle_id)
    if saved is None:
        raise DomainError("CRISIS_V2_BATTLE_CONTEXT_MISSING", "此战斗没有危机合约会话记录", 503)
    try:
        evaluation = validate_record(ctx.data, _values(source), _values(saved))
    except (ValueError, KeyError, TypeError) as exc:
        raise DomainError("CRISIS_V2_BATTLE_INCOMPATIBLE", "危机合约战斗保存或规则不匹配", 503) from exc
    if require_session and source.native_context["session_binding"] != _latest_session(ctx):
        # Preserve the pending session: automatic abandonment is not established
        # for this mode and must not be borrowed from ordinary battle recovery.
        raise DomainError("CRISIS_V2_SESSION_CONFLICT", "战斗属于较早登录，尚未修改待结算记录", 409)
    return PendingBattle(source, saved, evaluation)


def start(ctx, map_id, squad_id, slots, rune_slots, *, assist_friend=None):
    from terralocal.server.domain.rogue_battle import ensure_no_active

    try:
        request = _Start(map_id=map_id, squad_id=squad_id, slots=slots,
                         rune_slots=rune_slots, assist_friend=assist_friend)
    except ValidationError as exc:
        raise DomainError("INVALID_CRISIS_V2_START", "危机合约开战参数无效") from exc
    if request.assist_friend is not None:
        raise DomainError("CRISIS_V2_ASSIST_UNSUPPORTED", "危机合约助战尚未完成适配", 501)
    binding = _latest_session(ctx)
    if not crisis_v2.available(ctx.data):
        raise DomainError("CRISIS_V2_NOT_CONFIGURED", "尚未导入匹配的危机合约信息源", 503)
    crisis_v2.initialize(ctx)
    catalog = ctx.data.crisis_v2
    season = catalog.current(ctx.now)
    if not season:
        raise DomainError("CRISIS_V2_SEASON_CLOSED", "当前本地日历没有开放的危机合约赛季", 409)
    info = catalog.info(season)
    if map_id not in info["mapStageDataMap"]:
        raise DomainError("UNKNOWN_CRISIS_V2_MAP", "当前赛季不存在此危机合约地图", 404)
    stage = info["mapStageDataMap"][map_id]
    if stage["startTime"] != -1 and ctx.now < stage["startTime"]:
        raise DomainError("CRISIS_V2_MAP_NOT_STARTED", "危机合约地图尚未到本地开放时间", 409)
    ensure_no_active(ctx)
    if ctx.session.scalar(select(m.BattleSession.id).where(
            m.BattleSession.account_id == ctx.account_id, m.BattleSession.state == "STARTED")):
        raise DomainError("ACTIVE_BATTLE", "已有未结算战斗，请结算或放弃", 409)
    saved_map = ctx.session.get(m.CrisisV2MapProgress, (ctx.account_id, season, map_id))
    if saved_map is None:
        raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约地图存档未初始化", 503)
    try:
        player = crisis_v2._map(ctx, saved_map).model_dump()
    except (ValueError, TypeError) as exc:
        raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约地图保存字段无效", 503) from exc
    inputs = {key: player.get(key, {}) for key in ("rune", "challenge", "exRunes")}
    rule = catalog.rules[(season, map_id)]
    try:
        catalog.challenges(season, map_id)  # Reject unknown settlement conditions before insertion.
    except ValueError as exc:
        raise DomainError("CRISIS_V2_RULES_UNSUPPORTED", "危机合约挑战条件尚未完成适配", 503) from exc
    try:
        evaluation = rule.evaluate(rune_slots, inputs, permanent=stage["stageType"] == "PERMANENT")
    except (ValueError, TypeError) as exc:
        raise DomainError("CRISIS_V2_SELECTION_INVALID", "危机合约符文选择或条件不受支持") from exc
    try:
        members = battle.saved_squad(ctx, squad_id, [slot.model_dump() if slot else None for slot in request.slots])
    except (IndexError, KeyError, TypeError) as exc:
        raise DomainError("CRISIS_V2_BATTLE_INCOMPATIBLE", "危机合约编队保存字段无效", 503) from exc
    if not members:
        raise DomainError("EMPTY_SQUAD", "请选择有干员的编队")
    formation = []
    for member in members:
        op = ctx.operator(member.operator_id)
        skills = ctx.data.character(op.char_id)["skills"]
        if (skills and (member.skill_index not in range(len(skills))
                        or not check_condition(op, skills[member.skill_index]["unlockCond"]))
                or not skills and member.skill_index not in {-1, 0}):
            raise DomainError("SKILL_LOCKED", "所选技能尚未解锁")
        formation.append({"slot": member.slot, "charInstId": op.id, "charId": op.char_id,
            "skillIndex": member.skill_index, "level": op.level, "evolvePhase": op.evolve_phase,
            "skillLevel": op.skill_level, "potentialRank": op.potential, "trust": op.trust, "skinId": op.skin})
    parent = m.BattleSession(id=str(uuid.uuid4()), account_id=ctx.account_id, stage_id=stage["stageId"],
        state="STARTED", sanity_cost=0, practice=False, started_at=ctx.now, finished_at=None,
        seed=secrets.randbelow(2**31), squad_snapshot=formation, request_hash=None, settlement=None,
        native_context={"codec_version": POLICY, "formation_mode": "CRISIS_V2",
            "login_time": ctx.profile.flags.get("loginTime", ctx.profile.last_online_at), "session_binding": binding})
    saved = m.CrisisV2Battle(battle_id=parent.id, account_id=ctx.account_id, season_id=season, map_id=map_id,
        level_id=stage["levelId"], policy_version=POLICY, gamedata_hash=ctx.data.manifest["hash"],
        catalog_hash=catalog.fingerprint, map_hash=rule.fingerprint,
        challenge_hash=catalog.challenges(season, map_id).fingerprint,
        selection={"rune_slots": list(evaluation.rune_slots), "map_inputs": inputs,
            "selected_nodes": sorted(evaluation.selected_nodes), "scores": list(evaluation.dimension_scores)})
    saved.start_hash = _start_hash(_values(parent), _values(saved))
    try:
        validate_record(ctx.data, _values(parent), _values(saved))
    except (ValueError, KeyError, TypeError) as exc:
        raise DomainError("CRISIS_V2_BATTLE_INCOMPATIBLE", "危机合约战斗快照无法验证", 503) from exc
    ctx.session.add(parent)
    ctx.session.flush()
    ctx.session.add(saved)
    return {"battleId": parent.id}
