"""Owned native proxy records; gameplay rewards remain in battle settlement."""

import hashlib
from dataclasses import dataclass

from terralocal.server.domain.battle import BattleMember, get_session, native_context, unlocked
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.operators import check_condition
from terralocal.server.persistence import models as m

NATIVE_REPLAY_VERSION = "cn-android-2.7.71-zip-json-v1"
MAX_REPLAY_WIRE = 1_000_000


@dataclass(frozen=True)
class ReplayMember:
    operator_id: int
    template_id: str | None
    skill_id: str | None
    skill_index: int
    module_id: str
    module_level: int
    is_assist: bool


@dataclass(frozen=True)
class ReplayRecord:
    encoded: str
    stage_id: str
    sha256: str
    squad: tuple[ReplayMember, ...]


@dataclass(frozen=True)
class ProxyFormation:
    members: tuple[BattleMember, ...]
    sha256: str
    battle_id: str


def available(ctx, row: m.StageReplay) -> bool:
    data = row.replay
    if (not isinstance(data, dict) or data.get("codec_version") != NATIVE_REPLAY_VERSION
            or data.get("gamedata_hash") != ctx.data.manifest["hash"]
            or not isinstance(data.get("battleReplay"), str)
            or not 1 <= len(data["battleReplay"]) <= MAX_REPLAY_WIRE):
        return False
    try:
        return hashlib.sha256(data["battleReplay"].encode("ascii")).hexdigest() == data.get("sha256")
    except UnicodeError:
        return False


def load_native(ctx, stage_id: str) -> dict:
    """Read the current account's exact journal, without a receipt or reward.

    Check the cheap wire fingerprint during sync; decompress and validate the
    persisted archive only when it is actually requested. A damaged or legacy
    record never becomes an empty successful proxy response.
    """
    _, _, record = _load(ctx, stage_id)
    return {"battleReplay": record.encoded}


def _load(ctx, stage_id: str):
    definition = ctx.data.stage(stage_id)
    row = ctx.session.get(m.StageReplay, (ctx.account_id, stage_id))
    if row is None:
        raise DomainError("REPLAY_NOT_FOUND", "此账号尚未保存该关卡的代理记录", 404)
    if not definition.get("canBattleReplay", False):
        raise DomainError("REPLAY_UNAVAILABLE", "此关卡不能使用代理记录", 409)
    if not available(ctx, row):
        raise DomainError("INVALID_REPLAY_STATE", "代理记录版本或指纹无效，已有记录已保留", 503)
    battle = get_session(ctx, row.battle_id)
    if (battle.stage_id != stage_id or battle.practice or battle.state != "FINISHED"
            or not isinstance(battle.settlement, dict) or battle.settlement.get("stars") != 3):
        raise DomainError("INVALID_REPLAY_STATE", "代理记录缺少对应的成功战斗，已有记录已保留", 503)
    from terralocal.server.protocol.replay_codec import decode_replay

    try:
        record = decode_replay(row.replay["battleReplay"])
    except DomainError as exc:
        raise DomainError("INVALID_REPLAY_STATE", "已保存的代理记录格式无效，已有记录已保留", 503) from exc
    if record.stage_id != stage_id:
        raise DomainError("INVALID_REPLAY_STATE", "代理记录的关卡不匹配，已有记录已保留", 503)
    return row, battle, record


def _members(ctx, record: ReplayRecord, source: m.BattleSession) -> tuple[BattleMember, ...]:
    """Bind journal members/selections to the completed owned battle.

    Replay playback takes current growth and skins. A saved formation can be
    changed or removed without invalidating these independent selections.
    """
    snapshot = source.squad_snapshot
    if (not isinstance(snapshot, list) or not 1 <= len(snapshot) <= 12
            or any(not isinstance(row, dict) for row in snapshot)):
        raise DomainError("INVALID_REPLAY_STATE", "原战斗阵容记录无效，已有记录已保留", 503)
    if [r.operator_id for r in record.squad] != [r.get("charInstId") for r in snapshot]:
        raise DomainError("REPLAY_SQUAD_CONFLICT", "代理成员与原战斗阵容不一致", 409)
    selected = []
    for member, saved in zip(record.squad, snapshot, strict=True):
        op = ctx.operator(member.operator_id)
        if saved.get("charId") != op.char_id:
            raise DomainError("REPLAY_SQUAD_CONFLICT", "代理干员与原战斗角色身份不一致", 409)
        if member.is_assist:
            raise DomainError("REPLAY_SQUAD_CONFLICT", "普通本地代理不能包含未验证的助战", 409)
        if member.template_id not in (None, op.char_id):
            raise DomainError("REPLAY_TEMPLATE_UNSUPPORTED", "此代理的替换形态尚未完成适配", 501)
        skills = ctx.data.character(op.char_id)["skills"]
        skill_index = saved.get("skillIndex", 0)
        if not skills:
            if member.skill_id is not None or member.skill_index not in {-1, 0} or skill_index not in {-1, 0}:
                raise DomainError("REPLAY_SKILL_CONFLICT", "无主动技能干员的代理技能无效", 409)
            skill_index = 0  # The native no-skill request omits this default.
        elif (type(skill_index) is not int or skill_index not in range(len(skills))
              or member.skill_index != skill_index or member.skill_id != skills[skill_index]["skillId"]
              or not check_condition(op, skills[skill_index]["unlockCond"])):
            raise DomainError("REPLAY_SKILL_CONFLICT", "代理技能不匹配或尚未解锁", 409)
        if member.module_id or member.module_level:
            raise DomainError("REPLAY_MODULE_UNSUPPORTED", "带模组代理仍需完成装备同步适配", 501)
        selected.append(BattleMember(op.id, skill_index))
    return tuple(selected)


def proxy_formation(ctx, stage_id: str, squad_id: str, slots: list[dict | None]) -> ProxyFormation:
    # Frozen UIGuideController AUTO_BATTLE(9), resolved through metadata to tr_06.
    if "tr_06" not in ctx.data.stages:
        raise DomainError("REPLAY_UNLOCK_RULE_MISSING", "GameData 缺少代理功能解锁关卡", 503)
    gate = ctx.session.get(m.StageProgress, (ctx.account_id, "tr_06"))
    if gate is None or gate.stars < 1 or not unlocked(ctx, "tr_06"):
        raise DomainError("REPLAY_LOCKED", "请先完成代理功能的训练关卡", 409)
    progress = ctx.session.get(m.StageProgress, (ctx.account_id, stage_id))
    if progress is None or progress.stars != 3:
        raise DomainError("REPLAY_UNAVAILABLE", "普通关卡需三星通关后才能代理", 409)
    row, source, record = _load(ctx, stage_id)
    members = _members(ctx, record, source)
    if squad_id != "0":
        raise DomainError("REPLAY_SQUAD_CONFLICT", "原生代理编队标识无效", 409)
    actual = []
    for slot in slots:
        if slot is None:
            actual.append(None)
        else:
            op = ctx.operator(slot["charInstId"])
            index = slot["skillIndex"]
            if not ctx.data.character(op.char_id)["skills"] and index in {-1, 0}:
                index = 0
            actual.append((op.id, index, slot.get("currentEquip") or ""))
    expected = [(member.operator_id, member.skill_index, "") for member in members]
    if actual + [None] * (12 - len(actual)) != expected + [None] * (12 - len(expected)):
        raise DomainError("REPLAY_SQUAD_CONFLICT", "代理开战阵容与所保存记录不一致", 409)
    return ProxyFormation(members, record.sha256, row.battle_id)


def save_native(ctx, battle_id: str, record: ReplayRecord) -> dict:
    battle = get_session(ctx, battle_id)
    context = native_context(ctx, battle_id)
    if (battle.state != "FINISHED" or battle.practice
            or not isinstance(battle.settlement, dict) or battle.settlement.get("stars") != 3
            or not ctx.data.stage(battle.stage_id).get("canBattleReplay", False)):
        raise DomainError("REPLAY_UNAVAILABLE", "此战斗不能保存代理记录")
    if context["gamedata_hash"] != ctx.data.manifest["hash"]:
        raise DomainError("BATTLE_DATA_CHANGED", "战斗与当前 GameData 版本不匹配", 503)
    if record.stage_id != battle.stage_id:
        raise DomainError("REPLAY_STAGE_CONFLICT", "代理记录与战斗关卡不一致", 409)
    generation = context.get("replay_generation")
    if generation is not None and (type(generation) is not int or generation < 1):
        raise DomainError("INVALID_REPLAY_STATE", "代理记录的战斗顺序无效", 503)
    row = ctx.session.get(m.StageReplay, (ctx.account_id, battle.stage_id))
    if row is not None:
        if row.battle_id == battle_id:
            if not available(ctx, row) or row.replay.get("sha256") != record.sha256:
                raise DomainError("REPLAY_CONFLICT", "同一战斗不能提交不同代理记录", 409)
            return {}
        previous = row.replay.get("replay_generation") if isinstance(row.replay, dict) else None
        if type(previous) is not int or generation is None:
            raise DomainError("REPLAY_ORDER_UNKNOWN", "无法确认代理记录顺序，已有记录已保留", 409)
        if generation <= previous:
            raise DomainError("REPLAY_STALE", "旧战斗不能覆盖较新的代理记录", 409)
    _members(ctx, record, battle)
    data = {"codec_version": NATIVE_REPLAY_VERSION, "gamedata_hash": ctx.data.manifest["hash"],
            "battleReplay": record.encoded, "sha256": record.sha256, "replay_generation": generation}
    if row is None:
        ctx.session.add(m.StageReplay(account_id=ctx.account_id, stage_id=battle.stage_id,
                                      battle_id=battle_id, replay=data, created_at=ctx.now))
    else:
        row.battle_id, row.replay, row.created_at = battle_id, data, ctx.now
    return {}
