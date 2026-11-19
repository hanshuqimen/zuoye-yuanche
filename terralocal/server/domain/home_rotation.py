"""Account-owned home presets from the frozen DTOs and GameData limits."""

import re
import uuid

from sqlalchemy import delete, select

from terralocal.server.domain.appearance import require_appearance
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError, NotImplementedFeature
from terralocal.server.domain.skins import definition
from terralocal.server.persistence import models as m

NAME, BACKGROUND, THEME, PROFILE, SLOTS = 1, 2, 4, 8, 16


def available(data) -> bool:
    return "display_meta_table" in data.manifest["tables"] and "charRotationPresetMaxCnt" in data.constants


def validate_catalog(data):
    if not available(data):
        return
    const = data.constants
    for key in ("charRotationPresetMaxCnt", "charRotationSkinListMaxCnt"):
        if type(const.get(key)) is not int or not 1 <= const[key] <= 1024:
            raise ValueError("看板轮换上限无效")
    keys = ("defaultCRPresetCharId", "defaultCRPresetCharSkinId", "defaultCRPresetBGId",
            "defaultCRPresetThemeId", "defaultCRPresetName")
    if any(not isinstance(const.get(key), str) or not const[key] for key in keys):
        raise ValueError("看板默认配置缺失")
    skin = definition(data, const["defaultCRPresetCharSkinId"], char_id=const["defaultCRPresetCharId"])
    if 0 not in skin["builtinPhases"] or skin["builtinPatchId"] is not None:
        raise ValueError("默认看板外观不是初始阶段默认外观")
    catalog = data.table("display_meta_table")["homeBackgroundData"]
    if (const["defaultCRPresetBGId"] != catalog["defaultBackgroundId"] or
            const["defaultCRPresetThemeId"] != catalog["defaultThemeId"]):
        raise ValueError("默认看板背景与主题引用不匹配")
    name = const["defaultCRPresetName"]
    if len(name) > 64 or not name.strip() or any(ord(c) < 32 for c in name):
        raise ValueError("默认看板名称无效")


def limits(ctx: Context):
    if not available(ctx.data):
        raise NotImplementedFeature("此数据版本的看板轮换")
    values = [ctx.data.constants.get(key) for key in ("charRotationPresetMaxCnt", "charRotationSkinListMaxCnt")]
    if any(type(v) is not int or not 1 <= v <= 1024 for v in values):
        raise DomainError("GAMEDATA_INVALID", "看板轮换上限无效", 503)
    return values


def owned_skin(ctx, char_id, skin_id, special=False):
    if special:
        raise NotImplementedFeature("助理特殊动态立绘权限")
    op = ctx.session.scalar(select(m.Operator).where(m.Operator.account_id == ctx.account_id,
                                                     m.Operator.char_id == char_id))
    if op is None:
        raise DomainError("UNKNOWN_OPERATOR", "此账号不拥有该助理", 404)
    require_appearance(ctx, op.id, skin_id)
    return op


def preset(ctx, inst_id):
    limits(ctx)
    row = ctx.session.get(m.HomePreset, (ctx.account_id, inst_id))
    if row is None:
        raise DomainError("UNKNOWN_HOME_PRESET", "此账号没有该看板配置", 404)
    return row


def _create(ctx, *, legacy=False):
    const = ctx.data.constants
    char_id = ctx.profile.secretary if legacy else const["defaultCRPresetCharId"]
    skin_id = ctx.profile.secretary_skin if legacy else const["defaultCRPresetCharSkinId"]
    owned_skin(ctx, char_id, skin_id)
    catalog = ctx.data.table("display_meta_table")["homeBackgroundData"]
    background, theme = catalog["defaultBackgroundId"], catalog["defaultThemeId"]
    inst_id = "local-" + uuid.uuid4().hex  # Local stable identity, never an official instance ID.
    row = m.HomePreset(account_id=ctx.account_id, inst_id=inst_id, name=const["defaultCRPresetName"],
                       background=background, theme=theme, profile_skin=skin_id, profile_sp=False)
    ctx.session.add(row)
    ctx.session.flush()
    ctx.session.add(m.HomePresetSlot(account_id=ctx.account_id, inst_id=inst_id, position=0,
                                     char_id=char_id, skin_id=skin_id, skin_sp=False))
    ctx.session.flush()
    return row


def initialize(ctx):
    if not available(ctx.data) or ctx.session.get(m.HomeRotation, ctx.account_id) is not None:
        return
    limits(ctx)
    if ctx.rows(m.HomePreset):
        raise DomainError("HOME_PRESET_INCONSISTENT", "看板配置缺少当前引用", 503)
    row = _create(ctx, legacy=True)
    ctx.session.add(m.HomeRotation(account_id=ctx.account_id, current_id=row.inst_id))
    ctx.session.flush()


def create(ctx):
    maximum, _ = limits(ctx)
    if len(ctx.rows(m.HomePreset)) >= maximum:
        raise DomainError("HOME_PRESET_LIMIT", "看板配置数量已达上限")
    return {"instId": _create(ctx).inst_id}


def remove(ctx, inst_id):
    row = preset(ctx, inst_id)
    state = ctx.session.get(m.HomeRotation, ctx.account_id)
    if state is None or state.current_id == inst_id:
        raise DomainError("HOME_PRESET_CURRENT", "不能删除正在使用的看板配置")
    ctx.session.delete(row)
    return {}


def _apply_profile(ctx, row):
    char_id = definition(ctx.data, row.profile_skin)["charId"]
    owned_skin(ctx, char_id, row.profile_skin, row.profile_sp)
    ctx.profile.secretary, ctx.profile.secretary_skin = char_id, row.profile_skin


def set_current(ctx, inst_id):
    row = preset(ctx, inst_id)
    state = ctx.session.get(m.HomeRotation, ctx.account_id)
    if state is None:
        raise DomainError("HOME_PRESET_INCONSISTENT", "看板配置缺少当前引用", 503)
    _apply_profile(ctx, row)
    state.current_id = inst_id
    return {}


def update(ctx, inst_id, flag, data):
    row = preset(ctx, inst_id)
    _, maximum = limits(ctx)
    if type(flag) is not int or not 1 <= flag <= 31:
        raise DomainError("INVALID_HOME_PRESET_FLAG", "看板更新标记无效")
    required = {bit: fields for bit, fields in (
        (NAME, {"name"}), (BACKGROUND, {"background"}), (THEME, {"homeTheme"}),
        (PROFILE, {"profile", "profileInst", "profileSp"}), (SLOTS, {"slots"}))}
    for bit, fields in required.items():
        if flag & bit and any(data.get(field) is None for field in fields):
            raise DomainError("INVALID_HOME_PRESET_DATA", "更新标记对应的数据缺失")
    if flag & NAME:
        name = data["name"]
        if not name.strip() or len(name) > 64 or any(ord(c) < 32 for c in name):
            raise DomainError("INVALID_HOME_PRESET_NAME", "看板名称不能为空或包含控制字符")
        row.name = name
    catalog = ctx.data.table("display_meta_table")["homeBackgroundData"]
    for bit, field, default, column in ((BACKGROUND, "background", "defaultBackgroundId", "background"),
                                        (THEME, "homeTheme", "defaultThemeId", "theme")):
        if flag & bit:
            if data[field] != catalog[default]:
                raise DomainError("HOME_DISPLAY_NOT_OWNED", "此账号尚未获得该背景或界面主题")
            setattr(row, column, data[field])
    proposed_slots = None
    if flag & SLOTS:
        proposed_slots = data["slots"]
        if not 1 <= len(proposed_slots) <= maximum:
            raise DomainError("HOME_SKIN_LIMIT", "助理轮换外观数量无效")
        seen = set()
        for slot in proposed_slots:
            owned_skin(ctx, slot["charId"], slot["skinId"], slot["skinSp"])
            key = (slot["skinId"], slot["skinSp"])
            if key in seen:
                raise DomainError("DUPLICATE_HOME_SKIN", "助理轮换外观不能重复")
            seen.add(key)
    if flag & PROFILE:
        inst = data["profileInst"]
        if not re.fullmatch(r"[1-9][0-9]{0,9}", inst) or int(inst) > 2**31 - 1:
            raise DomainError("INVALID_OPERATOR_ID", "助理实例标识无效")
        op = require_appearance(ctx, int(inst), data["profile"])
        owned_skin(ctx, op.char_id, data["profile"], data["profileSp"])
        row.profile_skin, row.profile_sp = data["profile"], data["profileSp"]
    current_slots = proposed_slots if proposed_slots is not None else [
        {"skinId": s.skin_id, "skinSp": s.skin_sp} for s in ctx.rows(m.HomePresetSlot) if s.inst_id == inst_id]
    if not any(s["skinId"] == row.profile_skin and s["skinSp"] == row.profile_sp for s in current_slots):
        raise DomainError("HOME_PROFILE_NOT_IN_SLOTS", "资料页助理必须属于此配置的轮换外观")
    if proposed_slots is not None:
        ctx.session.execute(delete(m.HomePresetSlot).where(m.HomePresetSlot.account_id == ctx.account_id,
                                                          m.HomePresetSlot.inst_id == inst_id))
        for i, slot in enumerate(proposed_slots):
            ctx.session.add(m.HomePresetSlot(account_id=ctx.account_id, inst_id=inst_id, position=i,
                                             char_id=slot["charId"], skin_id=slot["skinId"], skin_sp=slot["skinSp"]))
    state = ctx.session.get(m.HomeRotation, ctx.account_id)
    if state and state.current_id == inst_id:
        _apply_profile(ctx, row)
    return {}


def snapshot(ctx):
    if not available(ctx.data):
        return {}
    state = ctx.session.get(m.HomeRotation, ctx.account_id)
    if state is None:
        raise DomainError("HOME_PRESET_NOT_READY", "看板配置尚未初始化", 503)
    slots = {}
    for s in sorted(ctx.read_rows(m.HomePresetSlot), key=lambda s: (s.inst_id, s.position)):
        slots.setdefault(s.inst_id, []).append({"charId": s.char_id, "skinId": s.skin_id, "skinSp": s.skin_sp})
    presets = {r.inst_id: {"name": r.name, "background": r.background, "homeTheme": r.theme,
                            "profile": r.profile_skin, "profileSp": r.profile_sp, "slots": slots.get(r.inst_id, [])}
               for r in ctx.read_rows(m.HomePreset)}
    if state.current_id not in presets or any(not p["slots"] for p in presets.values()):
        raise DomainError("HOME_PRESET_INCONSISTENT", "看板配置引用或外观列表无效", 503)
    return {"charRotation": {"current": state.current_id, "preset": presets}}
