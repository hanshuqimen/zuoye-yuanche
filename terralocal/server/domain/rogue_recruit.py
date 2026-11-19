"""Persistent ordinary initial-ticket recruitment for the admitted first theme."""

from types import SimpleNamespace
from typing import Literal

from pydantic import Field, ValidationError
from sqlalchemy import select

from terralocal.server.api.schemas import Command
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_temporary import rule as recruit_rule
from terralocal.server.gamedata.repository import canonical
from terralocal.server.persistence import models as m

VoiceLanguage = Literal["NONE", "JP", "CN_MANDARIN", "EN", "KR", "CN_TOPOLECT", "LINKAGE",
                        "ITA", "GER", "RUS", "FRE", "SPA"]


class Skill(Command):
    skillId: str = Field(min_length=1, max_length=128)
    unlock: bool
    state: int = Field(ge=0, le=0)
    specializeLevel: int = Field(ge=0, le=0)
    completeUpgradeTime: int = Field(ge=-1, le=-1)


class Character(Command):
    instId: int = Field(ge=0)
    charId: str = Field(min_length=1, max_length=128)
    favorPoint: int = Field(ge=0)
    potentialRank: int = Field(ge=0, le=5)
    mainSkillLvl: int = Field(ge=1, le=7)
    skin: str = Field(min_length=1, max_length=256)
    level: int = Field(ge=1, le=100)
    exp: int = Field(ge=0)
    evolvePhase: int = Field(ge=0, le=1)
    defaultSkillIndex: int = Field(ge=-1, le=2)
    gainTime: int = Field(ge=0)
    skills: list[Skill] = Field(max_length=3)
    # Null is admitted only for an exact legacy unvoiced-reserve save. The
    # frozen managed VoiceLangType is a value enum and cannot consume null.
    voiceLan: VoiceLanguage | None
    currentEquip: None
    equip: dict
    starMark: int = Field(ge=0, le=1)


class WireCharacter(Character):
    voiceLan: VoiceLanguage


def unvoiced(data, char_id):
    table = data.table("charword_table")
    return char_id not in table["voiceLangDict"] and char_id not in table["charDefaultTypeDict"]


def incompatible():
    return DomainError("ROGUE_RECRUIT_INCOMPATIBLE", "探索招募记录与当前规则不符；请保留原存档", 503)


def validate(data, run, tickets, options, chars, *, cost_history=None):
    """Check immutable offers/results without comparing later main-roster training."""
    from terralocal.server.gamedata.rogue_special_recruit import DIRECT_TICKET_IDS, ELITE_TICKET_ID

    for ticket in tickets:
        scope = getattr(ticket, "elite_pool", [])  # Read schema0031 before its transactional migration.
        if type(scope) is not list:
            raise incompatible()
        if ticket.item_id == ELITE_TICKET_ID:
            try:
                data.rogue_special_recruit.elite_scope(ticket.item_id, tuple(scope))
            except ValueError as exc:
                raise incompatible() from exc
        elif scope:
            raise incompatible()
        direct = getattr(ticket, "direct_pool", [])
        if type(direct) is not list:
            raise incompatible()
        if ticket.item_id in DIRECT_TICKET_IDS:
            try:
                data.rogue_special_recruit.direct_scope(ticket.item_id, tuple(direct))
            except (KeyError, ValueError) as exc:
                raise incompatible() from exc
        elif direct:
            raise incompatible()
    if not options and not chars and all(t.state == "CREATE" for t in tickets):
        if run.hope_cost != 0:
            raise incompatible()
        return
    rules = data.rogue_recruit
    # Local bounded budgets for a persisted exploration, not official limits.
    if (len(tickets) > 259 or len(options) > 131072 or len(chars) > 259
            or sum(t.state == "ACTIVE" for t in tickets) > 1):
        raise incompatible()
    offered = {}
    for option in options:
        try:
            if option.kind in ("UPGRADE", "UPGRADE_PAID"):
                from terralocal.server.domain.rogue_training import validate_offer

                ticket = next(t for t in tickets if t.ordinal == option.ticket_ordinal)
                validate_offer(data, ticket, option, chars, options)
                key = (option.ticket_ordinal, option.ordinal)
                if option.ordinal < 0 or key in offered:
                    raise incompatible()
                offered[key] = option
                continue
            if option.kind == "DIRECT":
                from terralocal.server.domain.rogue_training import check_character

                value = check_character(data, option.character)
            else:
                value = Character.model_validate(option.character).model_dump()
            if (canonical(value) != canonical(option.character) or len(canonical(value)) > 32768 or value["equip"]
                    or getattr(option, "target_char_ordinal", None) is not None):
                raise incompatible()
            ticket = next(t for t in tickets if t.ordinal == option.ticket_ordinal)
            rule = recruit_rule(data, ticket.item_id)
            if rule is None:
                raise incompatible()
            reserves = rule.reserves
            definition = data.character(value["charId"])
            if value["instId"] != option.ordinal or option.ordinal < 0:
                raise incompatible()
            phase = value["evolvePhase"]
            if phase >= len(definition["phases"]) or value["level"] > definition["phases"][phase]["maxLevel"]:
                raise incompatible()
            skill_defs = definition["skills"]
            if [s["skillId"] for s in value["skills"]] != [s["skillId"] for s in skill_defs]:
                raise incompatible()
            from terralocal.server.domain.operators import check_condition

            capped = SimpleNamespace(evolve_phase=phase, level=value["level"])
            if any(s["unlock"] != check_condition(capped, d["unlockCond"])
                   for s, d in zip(value["skills"], skill_defs, strict=True)):
                raise incompatible()
            default = value["defaultSkillIndex"]
            if skill_defs and (default not in range(len(skill_defs)) or not value["skills"][default]["unlock"]):
                raise incompatible()
            if option.kind in ("NORMAL", "DIRECT"):
                expected_cost = rules.costs[data.rarity(definition)]
                if cost_history is not None:
                    expected_cost = cost_history.quote(ticket.ordinal, expected_cost,
                        profession=definition["profession"], rarity=definition["rarity"]).total
                if (type(option.source_operator_id) is not int or option.source_operator_id < 1
                        or value["voiceLan"] is None
                        or not rule.matches_definition(definition) or definition.get("isNotObtainable")
                        or (value["charId"] in getattr(ticket, "direct_pool", [])) != (option.kind == "DIRECT")
                        or option.hope_cost != expected_cost):
                    raise incompatible()
            elif option.kind in ("FREE", "THIRD"):
                from terralocal.server.domain.rogue_temporary import validate as validate_temporary

                if option.hope_cost != 0:
                    raise incompatible()
                validate_temporary(data, ticket, option)
            elif (option.kind != "THIRD_LOW" or value["charId"] not in reserves
                  or option.source_operator_id is not None or option.hope_cost != 0):
                raise incompatible()
            if value["voiceLan"] in (None, "NONE") and (
                    option.kind != "THIRD_LOW" or not unvoiced(data, value["charId"])):
                raise incompatible()
            key = (option.ticket_ordinal, option.ordinal)
            if key in offered:
                raise incompatible()
            offered[key] = option
        except (ValidationError, KeyError, IndexError, StopIteration, TypeError, ValueError) as exc:
            raise incompatible() from exc
    chosen, sources, selected_chars, total = {}, set(), {}, 0
    if [c.ordinal for c in chars] != list(range(1, len(chars) + 1)):
        raise incompatible()
    for char in chars:
        option = offered.get((char.ticket_ordinal, char.option_ordinal))
        if option is None or option.kind in ("UPGRADE", "UPGRADE_PAID") or char.ticket_ordinal in chosen:
            raise incompatible()
        if option.source_operator_id is not None:
            if option.source_operator_id in sources:
                raise incompatible()
            sources.add(option.source_operator_id)
        char_id = option.character["charId"]
        if char_id in selected_chars and {"FREE", "THIRD"}.intersection((selected_chars[char_id], option.kind)):
            raise incompatible()
        selected_chars[char_id] = option.kind
        chosen[char.ticket_ordinal] = option
        total += option.hope_cost
    from terralocal.server.domain.rogue_training import validate as validate_training

    trained = validate_training(data, run, tickets, options, chars)
    total += sum(o.hope_cost for o in options if o.kind == "UPGRADE_PAID" and trained.get(o.ticket_ordinal) == o.ordinal)
    if type(run.hope_cost) is not int or run.hope_cost != total or total > run.hope_max:
        raise incompatible()
    for ticket in tickets:
        upgrade = recruit_rule(data, ticket.item_id) is None
        if upgrade and (ticket.ordinal < 3 or ticket.item_id not in data.rogue_upgrades.tickets):
            raise incompatible()
        indices = sorted(o.ordinal for o in options if o.ticket_ordinal == ticket.ordinal)
        if indices != list(range(len(indices))) or ticket.state not in ("CREATE", "ACTIVE", "DONE"):
            raise incompatible()
        if (ticket.state == "CREATE" and indices) or (ticket.state == "ACTIVE" and not indices and not upgrade):
            raise incompatible()
        if ticket.ordinal in chosen and ticket.state != "DONE":
            raise incompatible()
        if not upgrade and ticket.item_id not in rules.catalog and ticket.state != "CREATE":
            spec = data.rogue_special_recruit.tickets[ticket.item_id]
            kinds = [o.kind for o in options if o.ticket_ordinal == ticket.ordinal]
            if kinds.count("FREE") != len(spec.free_rarities) or kinds.count("THIRD") != spec.elite_count:
                raise incompatible()
            if kinds.count("DIRECT") != len(getattr(ticket, "direct_pool", [])):
                raise incompatible()


def capped_character(ctx, source, ordinal, *, reserve=False, upgraded=False):
    """Use the normal serializer, applying table caps to an independent value."""
    from terralocal.server.domain.voice import initial_language
    from terralocal.server.protocol.sync import SyncDataAssembler

    data, rules = ctx.data, ctx.data.rogue_recruit
    if upgraded and reserve:
        raise incompatible()
    ceiling = ctx.data.rogue_upgrades.ceilings[1] if upgraded else None
    if reserve:
        char_id = source
        definition = data.character(char_id)
        skin = data.table("skin_table").get("buildinEvolveMap", {}).get(char_id, {}).get("0", char_id + "#1") \
            if "skin_table" in data.manifest["tables"] else char_id + "#1"
        # NONE is the frozen client's explicit unvoiced value, not a JP actor
        # or a nullable string. Keep ordinary voice-catalog checks intact.
        op = SimpleNamespace(id=ordinal, char_id=char_id, level=definition["phases"][1]["maxLevel"], exp=0,
            evolve_phase=1, potential=0, trust=0, skill_level=min(rules.skill_level, len(definition["allSkillLvlup"]) + 1),
            skin=skin, default_skill=0, gained_at=ctx.now,
            voice_language="NONE" if unvoiced(data, char_id) else initial_language(ctx, char_id),
            current_module=None, locked=False)
    else:
        definition = data.character(source.char_id)
        phase = min(source.evolve_phase, ceiling.evolve_phase if ceiling else rules.phase)
        op = SimpleNamespace(id=ordinal, char_id=source.char_id,
            level=definition["phases"][phase]["maxLevel"] if source.evolve_phase > phase else source.level,
            exp=0 if source.evolve_phase > phase else source.exp, evolve_phase=phase,
            potential=source.potential, trust=source.trust, skill_level=min(source.skill_level, rules.skill_level),
            skin=source.skin, default_skill=source.default_skill, gained_at=source.gained_at,
            voice_language=source.voice_language, current_module=None, locked=source.locked)
    progress = {}
    if upgraded:
        from terralocal.server.domain.rogue_training import TrainedCharacter

        rows = ctx.session.scalars(select(m.OperatorSkill).where(m.OperatorSkill.operator_id == source.id)).all()
        progress[ordinal] = [SimpleNamespace(skill_id=row.skill_id,
            mastery=min(row.mastery, ceiling.specialize_level) if phase >= 2 else 0, training_complete_at=None)
            for row in rows]
    value = SyncDataAssembler(ctx).operator(op, progress)
    for skill in value["skills"]:
        skill["unlock"] = bool(skill["unlock"])
    unlocked = [i for i, skill in enumerate(value["skills"]) if skill["unlock"]]
    if op.default_skill not in unlocked:
        value["defaultSkillIndex"] = unlocked[0] if unlocked else 0
    return (TrainedCharacter if upgraded else Character).model_validate(value).model_dump()


def ticket_context(ctx, index):
    from terralocal.server.domain.rogue_runs import active

    run, children = active(ctx, required=True)
    if run.state not in ("INIT_RECRUIT", "MAP_READY"):
        raise DomainError("ROGUE_EVENT_ORDER", "当前不是初始干员招募步骤", 409)
    ticket = next((t for t in children[2] if str(t.ordinal) == index), None)
    if ticket is None:
        raise DomainError("ROGUE_INVALID_TICKET", "招募券不属于当前探索")
    if run.state == "MAP_READY":
        from terralocal.server.domain.rogue_settlement import rows

        records = rows(ctx.session, run.id)
        from terralocal.server.domain.rogue_shops import owns_pending_ticket
        from terralocal.server.domain.rogue_visits import owns_pending_ticket as scene_owns_ticket

        battle_ticket = bool(records and records[-1].completed_at is None
                             and any(c["ticket"] == ticket.ordinal for c in records[-1].claims))
        if ticket.ordinal < 3 or not (battle_ticket or owns_pending_ticket(ctx, run, ticket.ordinal)
                                      or scene_owns_ticket(ctx, run, ticket.ordinal)):
            raise DomainError("ROGUE_EVENT_ORDER", "此券不是当前战斗奖励产生的招募", 409)
    return run, ticket, children


def activate(ctx, index):
    run, ticket, children = ticket_context(ctx, index)
    if ticket.state == "ACTIVE":
        return {}  # Preserve the existing offer; no reroll on a new sequence.
    if ticket.state != "CREATE" or any(t.state == "ACTIVE" for t in children[2]):
        raise DomainError("ROGUE_TICKET_STATE", "请先完成当前招募；此券不能再次激活", 409)
    rules = ctx.data.rogue_recruit
    rule = recruit_rule(ctx.data, ticket.item_id)
    if rule is None:
        from terralocal.server.domain.rogue_training import activate as activate_upgrade

        return activate_upgrade(ctx, run, ticket, children)
    modifiers = ()
    if len(children[1]) > 1:
        from terralocal.server.domain.rogue_settlement import state_in_session

        progress = state_in_session(ctx, run, children[2])
        if progress is None or progress.cost_history is None:
            raise incompatible()
        modifiers = progress.cost_history.final_modifiers
    used_chars = {o.character["charId"] for c in children[4] for o in children[3]
                  if (o.ticket_ordinal, o.ordinal) == (c.ticket_ordinal, c.option_ordinal)}
    temporary = []
    if ticket.item_id not in rules.catalog:
        from secrets import choice

        for rarity in sorted(rule.free_rarities):
            pool = ctx.data.rogue_special_recruit.pool(ticket.item_id, kind="FREE", rarity=rarity,
                                                      excluded=tuple(sorted(used_chars)))
            if not pool:
                raise DomainError("ROGUE_NO_TEMPORARY_CANDIDATES", "此保证临时招募没有可用候选，未消耗券", 409)
            temporary.append((choice(pool).char_id, "FREE"))
        if rule.elite_count:
            pool = [c for c in ctx.data.rogue_special_recruit.elite_scope(ticket.item_id, tuple(ticket.elite_pool))
                    if c.char_id not in used_chars]
            if not pool:
                raise DomainError("ROGUE_NO_TEMPORARY_CANDIDATES", "精英候选已在探索队伍中，未消耗券", 409)
            temporary.append((choice(pool).char_id, "THIRD"))
    used = {o.source_operator_id for c in children[4] for o in children[3]
            if (o.ticket_ordinal, o.ordinal) == (c.ticket_ordinal, c.option_ordinal)
            and o.source_operator_id is not None}
    owned = ctx.session.scalars(select(m.Operator).where(m.Operator.account_id == ctx.account_id)
                               .order_by(m.Operator.id)).all()
    sources = [(op, "NORMAL") for op in owned if op.id not in used
               and op.char_id not in used_chars and op.char_id not in {c for c, _ in temporary}
               and rule.matches_definition(ctx.data.character(op.char_id))
               and not ctx.data.character(op.char_id).get("isNotObtainable")]
    direct = set(ticket.direct_pool)
    if direct - {op.char_id for op, _ in sources}:
        raise DomainError("ROGUE_NO_DIRECT_CANDIDATES", "直升供给候选未匹配当前可招募阵容，未消耗券", 409)
    sources = [(op, "DIRECT" if op.char_id in direct else kind) for op, kind in sources]
    sources += [(char_id, "THIRD_LOW") for char_id in rule.reserves]
    sources += temporary
    if not sources:
        raise DomainError("ROGUE_NO_CANDIDATES", "此招募券没有已接纳的普通或备用候选", 409)
    for ordinal, (source, kind) in enumerate(sources):
        if kind in ("FREE", "THIRD"):
            from terralocal.server.domain.rogue_temporary import character as temporary_character

            char = temporary_character(ctx, source, ordinal, gained_at=ticket.created_at)
        else:
            char = capped_character(ctx, source, ordinal, reserve=kind == "THIRD_LOW", upgraded=kind == "DIRECT")
        cost = rules.costs[ctx.data.rarity(ctx.data.character(char["charId"]))] if kind in ("NORMAL", "DIRECT") else 0
        if modifiers and kind in ("NORMAL", "DIRECT"):
            definition = ctx.data.character(char["charId"])
            cost = ctx.data.rogue_recruit_costs.quote(cost, profession=definition["profession"],
                rarity=definition["rarity"], modifiers=modifiers).total
        ctx.session.add(m.RogueRecruitOption(run_id=run.id, ticket_ordinal=ticket.ordinal, ordinal=ordinal,
            kind=kind, source_operator_id=source.id if kind in ("NORMAL", "DIRECT") else None,
            hope_cost=cost,
            character=char))
    from terralocal.server.domain.rogue_training import add_offers

    add_offers(ctx, run, ticket, children, start=len(sources), paid=True)
    ticket.state = "ACTIVE"
    ctx.session.flush()
    return {}


def recruit(ctx, ticket_index, option_index):
    run, ticket, children = ticket_context(ctx, ticket_index)
    if ticket.state != "ACTIVE":
        raise DomainError("ROGUE_TICKET_STATE", "招募券尚未激活或已经完成", 409)
    option = next((o for o in children[3] if o.ticket_ordinal == ticket.ordinal and str(o.ordinal) == option_index), None)
    if option is None:
        raise DomainError("ROGUE_INVALID_OPTION", "干员不在当前券的可选列表中")
    if option.kind in ("UPGRADE", "UPGRADE_PAID"):
        from terralocal.server.domain.rogue_training import apply

        return apply(ctx, run, ticket, option, children)
    if run.hope_cost + option.hope_cost > run.hope_max:
        raise DomainError("ROGUE_HOPE_REQUIRED", "希望不足，未消耗招募券")
    char = m.RogueRunChar(run_id=run.id, ordinal=len(children[4]) + 1,
                         ticket_ordinal=ticket.ordinal, option_ordinal=option.ordinal)
    ctx.session.add(char)
    run.hope_cost += option.hope_cost
    ticket.state = "DONE"
    ctx.session.flush()
    result = recruited_character(option, char.ordinal)
    # Legacy response flags are a compatibility candidate; native verification
    # of their visual handling is still outstanding, not an official fixture.
    return {"chars": [result | {"isAddition": 1, "isElite": int(option.kind == "THIRD"), "isFree": int(option.hope_cost == 0)}]}


def close(ctx, index):
    _, ticket, _ = ticket_context(ctx, index)
    if ticket.state != "ACTIVE":
        raise DomainError("ROGUE_TICKET_STATE", "只有正在选择的招募券可以放弃", 409)
    ticket.state = "DONE"
    ctx.session.flush()
    return {}


def recruited_character(option, ordinal):
    value = option.character
    if option.kind == "DIRECT":
        from terralocal.server.domain.rogue_training import promoted

        return promoted(value, ordinal, kind="NORMAL")
    if value["voiceLan"] is None and option.kind == "THIRD_LOW":
        value = value | {"voiceLan": "NONE"}  # Read-only legacy projection; preserve the saved offer.
    return WireCharacter.model_validate(value).model_dump() | {"instId": ordinal, "upgradePhase": 0,
                               "upgradeLimited": True, "type": option.kind, "charBuff": []}


def project(tickets, options, chars):
    results = {c.ticket_ordinal: next(o for o in options if (o.ticket_ordinal, o.ordinal) ==
               (c.ticket_ordinal, c.option_ordinal)) for c in chars}
    from terralocal.server.domain.rogue_training import Troop, history, promoted

    base = {str(c.ordinal): recruited_character(results[c.ticket_ordinal], c.ordinal) for c in chars}
    troop = Troop(base, chars)
    upgrades = {r["ticket"]: promoted(r["source"], c.ordinal, kind=base[str(c.ordinal)]["type"])
                for c in chars for r in history(c)}
    recruits = {}
    for ticket in tickets:
        candidates = [o for o in options if o.ticket_ordinal == ticket.ordinal] if ticket.state == "ACTIVE" else []
        result = upgrades.get(ticket.ordinal) or next((base[str(c.ordinal)] for c in chars
                                                      if c.ticket_ordinal == ticket.ordinal), None)
        recruits[str(ticket.ordinal)] = {"index": str(ticket.ordinal), "id": ticket.item_id, "state": ticket.state,
            "list": [(promoted(o.character, o.ordinal, kind=base[str(o.target_char_ordinal)]["type"])
                      if o.kind in ("UPGRADE", "UPGRADE_PAID") else recruited_character(o, o.ordinal))
                     | {"population": o.hope_cost, "isUpgrade": o.kind in ("UPGRADE", "UPGRADE_PAID"),
                        "troopInstId": o.target_char_ordinal if o.kind in ("UPGRADE", "UPGRADE_PAID") else 0}
                     for o in candidates], "result": result, "ts": ticket.created_at,
            "needAssist": False, "assistList": {}, "starFriendAssistList": {}}
    pending = [{"index": "recruit_" + str(t.ordinal), "type": "RECRUIT",
                "content": {"recruit": {"ticket": str(t.ordinal)}}} for t in tickets if t.state == "ACTIVE"]
    return recruits, troop, pending
