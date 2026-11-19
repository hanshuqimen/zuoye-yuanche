"""Character costume definitions and ownership, separate from stackable items.

The frozen skin table's ``isBuySkin`` also covers event costumes; it is not a
payment classification. Built-in evolution and patch skins cannot be granted
as rewards. Prices, availability, duplicate compensation and costume changes
are outside this ownership operation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m

if TYPE_CHECKING:
    from terralocal.server.domain.context import Context
    from terralocal.server.gamedata import GameData


def _identifier(value: object, maximum: int) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= maximum and not any(
        character.isspace() for character in value)


def _invalid_data() -> DomainError:
    return DomainError("GAMEDATA_INVALID", "服装定义或角色归属无效", 503)


def definition(data: GameData, skin_id: str, *, char_id: str | None = None) -> dict:
    """Resolve an exact skin ID, preserving its authoritative owner/template.

    ``builtinPhases`` contains the evolution-map phases for this skin.
    ``builtinPatchId`` identifies a patch-map default, whose unlock rules are
    not established here. ``tmplId`` retains the table's nullable value.
    Patch templates can be absent from ``character_table``; their provenance
    comes from the owner's patch mapping and its matching built-in skin row.
    ``char_id``, when supplied by a catalog, must match the actual ``charId``;
    a skin ID's prefix does not establish its owner.
    """
    if not _identifier(skin_id, 128):
        raise DomainError("INVALID_SKIN_ID", "服装标识无效")
    table = data.table("skin_table")
    catalog = table.get("charSkins")
    if not isinstance(catalog, dict):
        raise _invalid_data()
    row = catalog.get(skin_id)
    if row is None:
        raise DomainError("UNKNOWN_SKIN", "服装不存在")
    if (not isinstance(row, dict) or row.get("skinId") != skin_id
            or not _identifier(row.get("charId"), 96) or type(row.get("isBuySkin")) is not bool):
        raise _invalid_data()
    owner = row["charId"]
    if not owner.startswith("char_"):
        raise DomainError("NOT_CHARACTER_SKIN", "召唤物或其他对象的外观不能作为干员服装")
    try:
        character = data.character(owner)
    except DomainError as exc:
        raise _invalid_data() from exc
    if not isinstance(character, dict):
        raise _invalid_data()
    if character.get("isNotObtainable"):
        raise DomainError("UNOBTAINABLE_OPERATOR", "该外观所属角色不是可获取干员")
    if char_id is not None:
        if not _identifier(char_id, 96):
            raise DomainError("INVALID_OPERATOR_ID", "干员标识无效")
        if char_id != owner:
            raise DomainError("SKIN_CHARACTER_MISMATCH", "服装不属于指定干员")

    evolve_map = table.get("buildinEvolveMap", {})
    patch_map = table.get("buildinPatchMap", {})
    if not isinstance(evolve_map, dict) or not isinstance(patch_map, dict):
        raise _invalid_data()
    evolution, patches = evolve_map.get(owner, {}), patch_map.get(owner, {})
    phases = character.get("phases")
    if not isinstance(evolution, dict) or not isinstance(patches, dict) or not isinstance(phases, list):
        raise _invalid_data()
    builtin_phases = []
    for phase, mapped_skin in evolution.items():
        if (phase not in {"0", "1", "2"} or int(phase) >= len(phases)
                or not _identifier(mapped_skin, 128)):
            raise _invalid_data()
        if mapped_skin == skin_id:
            builtin_phases.append(int(phase))
    builtin_patch = None
    for patch_id, mapped_skin in patches.items():
        if not _identifier(patch_id, 96) or not _identifier(mapped_skin, 128):
            raise _invalid_data()
        if mapped_skin == skin_id:
            if builtin_patch is not None:
                raise _invalid_data()
            builtin_patch = patch_id

    template = row.get("tmplId")
    if template is not None:
        if not _identifier(template, 96):
            raise _invalid_data()
        if template != owner:
            # Patch IDs are separate templates, not ordinary character IDs.
            # Require both frozen references instead of accepting an arbitrary
            # template merely because its spelling resembles an operator.
            mapped_builtin = patches.get(template)
            builtin = catalog.get(mapped_builtin) if mapped_builtin is not None else None
            if (not isinstance(builtin, dict) or builtin.get("skinId") != mapped_builtin
                    or builtin.get("charId") != owner or builtin.get("tmplId") != template
                    or builtin.get("isBuySkin") is not False):
                raise _invalid_data()
    if builtin_patch is not None and template != builtin_patch:
        raise _invalid_data()
    if row["isBuySkin"] and (builtin_phases or builtin_patch is not None):
        raise _invalid_data()
    if not row["isBuySkin"] and not builtin_phases and builtin_patch is None:
        raise DomainError("SKIN_UNLOCK_RULE_UNVERIFIED", "此默认外观缺少已验证的解锁映射", 503)
    display = row.get("displaySkin")
    if not isinstance(display, dict) or (
            display.get("skinName") is not None and not isinstance(display["skinName"], str)):
        raise _invalid_data()
    return {"itemId": skin_id, "itemType": "CHAR_SKIN", "name": display.get("skinName") or skin_id,
            "skinId": skin_id, "charId": owner, "tmplId": template, "isBuySkin": row["isBuySkin"],
            "builtinPhases": sorted(builtin_phases), "builtinPatchId": builtin_patch}


def grant(ctx: Context, skin_id: str, count: int = 1, *, char_id: str | None = None,
          operator_id: int | None = None) -> dict:
    """Grant one costume to the context account, whether it owns the operator.

    Repeated grants preserve the same row and its first acquisition time, with
    no invented compensation. Optional operator/catalog claims are checked
    before writing; the operation never equips the costume or acquires a char.
    The caller owns the transaction and any purchase/availability validation.
    """
    if type(count) is not int or count != 1:
        raise DomainError("INVALID_REWARD", "服装奖励数量必须为整数 1")
    if ctx.local_session is not None and ctx.local_session.account_id != ctx.account_id:
        raise DomainError("ACCOUNT_MISMATCH", "游戏会话与奖励账号不匹配", 403)
    skin = definition(ctx.data, skin_id, char_id=char_id)
    if not skin["isBuySkin"]:
        raise DomainError("BUILTIN_SKIN", "默认、精英化及转职默认外观不能作为服装奖励发放")
    if operator_id is not None:
        if type(operator_id) is not int or operator_id <= 0:
            raise DomainError("INVALID_OPERATOR_ID", "干员实例标识无效")
        if ctx.operator(operator_id).char_id != skin["charId"]:
            raise DomainError("SKIN_CHARACTER_MISMATCH", "服装不属于指定干员")
    row = ctx.session.get(m.OwnedSkin, (ctx.account_id, skin_id))
    if row is None:
        ctx.session.add(m.OwnedSkin(account_id=ctx.account_id, skin_id=skin_id, obtained_at=ctx.now))
        ctx.session.flush()
    return {"id": skin_id, "type": "CHAR_SKIN", "count": 1}
