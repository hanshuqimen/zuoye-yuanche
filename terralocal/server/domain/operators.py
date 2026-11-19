from __future__ import annotations

from sqlalchemy import delete

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError, NotImplementedFeature
from terralocal.server.domain.operator_level_cost import cost as level_cost
from terralocal.server.gamedata.repository import GameData
from terralocal.server.persistence import models as m


def check_condition(op, cond) -> bool:
    phase = cond.get("phase", 0)
    phase = int(phase.removeprefix("PHASE_")) if isinstance(phase, str) else phase
    return op.evolve_phase >= phase and (op.evolve_phase > phase or op.level >= cond.get("level", 1))


def upgrade(ctx: Context, operator_id: int, materials: list[dict]) -> dict:
    op = ctx.operator(operator_id)
    definition = ctx.data.character(op.char_id)
    maximum = definition["phases"][op.evolve_phase]["maxLevel"]
    if op.level >= maximum:
        raise DomainError("MAX_LEVEL", "当前精英阶段已达到最高等级")
    exp_items = ctx.data.table("item_table")["expItems"]
    gained = 0
    for entry in materials:
        if entry["id"] not in exp_items or entry["count"] <= 0:
            raise DomainError("INVALID_EXP_ITEM", "只能使用有效的作战记录")
        gained += exp_items[entry["id"]]["gainExp"] * entry["count"]
    if gained <= 0:
        raise DomainError("INVALID_EXP_ITEM", "请选择作战记录")
    exp_map = ctx.data.constants["characterExpMap"][op.evolve_phase]
    cost_map = ctx.data.constants["characterUpgradeCostMap"][op.evolve_phase]
    level, exp, remaining = op.level, op.exp, gained
    while remaining and level < maximum:
        need = exp_map[level - 1]
        used = min(need - exp, remaining)
        exp += used
        remaining -= used
        if exp >= need:
            exp -= need
            level += 1
    if remaining:
        raise DomainError("EXP_OVERFLOW", "所选作战记录会超出最高等级")
    gold = level_cost(exp_map, cost_map, op.level, op.exp, level, exp)
    ctx.consume([*materials, {"id": "4001", "count": gold}])
    op.level, op.exp = level, exp
    ctx.emit("OperatorLeveled", operator_id=op.id)
    return {"level": level, "exp": exp, "cost": gold}


def evolve(ctx: Context, operator_id: int) -> dict:
    op = ctx.operator(operator_id)
    definition = ctx.data.character(op.char_id)
    next_phase = op.evolve_phase + 1
    if next_phase >= len(definition["phases"]):
        raise DomainError("MAX_EVOLVE", "干员已达到最高精英阶段")
    if op.level != definition["phases"][op.evolve_phase]["maxLevel"]:
        raise DomainError("LEVEL_REQUIRED", "需要达到当前阶段最高等级")
    costs = list(definition["phases"][next_phase].get("evolveCost") or [])
    gold = ctx.data.constants["evolveGoldCost"][GameData.rarity(definition)][next_phase - 1]
    ctx.consume([*costs, {"id": "4001", "count": gold}])
    op.evolve_phase, op.level, op.exp = next_phase, 1, 0
    ctx.emit("OperatorEvolved", operator_id=op.id)
    return {"evolvePhase": next_phase}


def skill_level(ctx: Context, operator_id: int) -> dict:
    op = ctx.operator(operator_id)
    upgrades = ctx.data.character(op.char_id)["allSkillLvlup"]
    if op.skill_level > len(upgrades):
        raise DomainError("MAX_SKILL", "技能已达到最高通用等级")
    definition = upgrades[op.skill_level - 1]
    if not check_condition(op, definition["unlockCond"]):
        raise DomainError("SKILL_CONDITION", "技能升级条件未满足")
    ctx.consume(definition["lvlUpCost"])
    op.skill_level += 1
    return {"mainSkillLvl": op.skill_level}


def formation(ctx: Context, squad_id: str, slots: list[dict | None], name: str | None = None,
              *, change_skill: bool = False) -> dict:
    squad = ctx.session.get(m.Squad, (ctx.account_id, squad_id))
    if squad is None or len(slots) > 12:
        raise DomainError("INVALID_SQUAD", "编队不存在或超过 12 个槽位")
    checked, selected_skills, seen = [], [], set()
    for index, slot in enumerate(slots):
        if slot is None:
            continue
        if slot.get("currentEquip"):
            raise NotImplementedFeature("编队模组的所有权与开放条件")
        op = ctx.operator(slot["charInstId"])
        if op.id in seen:
            raise DomainError("DUPLICATE_OPERATOR", "同一干员不能重复编入队伍")
        seen.add(op.id)
        skill_index = slot.get("skillIndex", 0)
        skills = ctx.data.character(op.char_id)["skills"]
        if skills and (skill_index not in range(len(skills)) or
                       not check_condition(op, skills[skill_index]["unlockCond"])):
            raise DomainError("SKILL_LOCKED", "所选技能尚未解锁")
        if not skills and skill_index not in {0, -1}:
            raise DomainError("INVALID_SKILL", "该干员没有主动技能")
        if change_skill:
            selected_skills.append((op, skill_index))
        checked.append(m.SquadSlot(account_id=ctx.account_id, squad_id=squad_id, slot=index,
                                    operator_id=op.id, skill_index=skill_index))
    ctx.session.execute(delete(m.SquadSlot).where(m.SquadSlot.account_id == ctx.account_id,
                                                 m.SquadSlot.squad_id == squad_id))
    ctx.session.add_all(checked)
    for op, skill_index in selected_skills:
        op.default_skill = skill_index
    if name is not None:
        if not name.strip() or len(name) > 32:
            raise DomainError("INVALID_SQUAD_NAME", "编队名称长度必须为 1 至 32 字")
        squad.name = name
    return {"squadId": squad_id}
