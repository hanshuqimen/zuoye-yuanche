"""Choose an account-owned appearance without changing ownership or unlocks."""

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError, NotImplementedFeature
from terralocal.server.domain.skins import definition
from terralocal.server.persistence import models as m


def require_appearance(ctx: Context, operator_id: int, skin_id: str):
    if type(operator_id) is not int or not 1 <= operator_id <= 2**31 - 1:
        raise DomainError("INVALID_OPERATOR_ID", "干员实例标识无效")
    op = ctx.operator(operator_id)
    skin = definition(ctx.data, skin_id, char_id=op.char_id)
    if skin["builtinPatchId"] is not None or skin["tmplId"] not in {None, op.char_id}:
        raise NotImplementedFeature("升变干员外观的模板解锁")
    phases = skin["builtinPhases"]
    if phases:
        if not any(phase <= op.evolve_phase for phase in phases):
            raise DomainError("SKIN_LOCKED", "此默认外观的精英阶段尚未解锁")
    elif ctx.session.get(m.OwnedSkin, (ctx.account_id, skin_id)) is None:
        raise DomainError("SKIN_NOT_OWNED", "此账号尚未获得该外观")
    return op


def change_skin(ctx: Context, operator_id: int, skin_id: str) -> dict:
    op = require_appearance(ctx, operator_id, skin_id)
    op.skin = skin_id
    return {}


def change_secretary(ctx: Context, operator_id: int, skin_id: str) -> dict:
    op = require_appearance(ctx, operator_id, skin_id)
    ctx.profile.secretary = op.char_id
    ctx.profile.secretary_skin = skin_id
    from terralocal.server.domain.home_rotation import available

    if available(ctx.data):
        from sqlalchemy import delete

        state = ctx.session.get(m.HomeRotation, ctx.account_id)
        if state is None:
            raise DomainError("HOME_PRESET_NOT_READY", "看板配置尚未初始化", 503)
        row = ctx.session.get(m.HomePreset, (ctx.account_id, state.current_id))
        row.profile_skin, row.profile_sp = skin_id, False
        ctx.session.execute(delete(m.HomePresetSlot).where(m.HomePresetSlot.account_id == ctx.account_id,
                                                          m.HomePresetSlot.inst_id == state.current_id))
        ctx.session.add(m.HomePresetSlot(account_id=ctx.account_id, inst_id=state.current_id, position=0,
                                         char_id=op.char_id, skin_id=skin_id, skin_sp=False))
    return {}
