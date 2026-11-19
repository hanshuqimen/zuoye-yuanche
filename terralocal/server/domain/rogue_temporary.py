"""Frozen FREE/THIRD offers, independent of the permanent roster.

The base temporary template uses table phase/skill ceilings and full character
values. Predefined modules remain a separate unresolved contract: no module
is fabricated or granted to the main account by this adapter.
"""

from types import SimpleNamespace

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_special_recruit import (
    DIRECT_TICKET_IDS,
    ELITE_TICKET_ID,
    FREE_TICKET_IDS,
)


def rule(data, ticket_id):
    if ticket_id in data.rogue_recruit.catalog:
        return data.rogue_recruit.catalog[ticket_id]
    if ticket_id in FREE_TICKET_IDS or ticket_id == ELITE_TICKET_ID or ticket_id in DIRECT_TICKET_IDS:
        return data.rogue_special_recruit.tickets[ticket_id]
    return None


def default_skin(data, char_id):
    return data.table("skin_table").get("buildinEvolveMap", {}).get(char_id, {}).get("0", char_id + "#1") \
        if "skin_table" in data.manifest["tables"] else char_id + "#1"


def character(ctx, char_id, ordinal, *, upgraded=False, original=None, gained_at=None):
    from terralocal.server.domain.operator_limits import maximum_trust
    from terralocal.server.domain.rogue_recruit import Character
    from terralocal.server.domain.rogue_training import TrainedCharacter
    from terralocal.server.domain.voice import initial_language
    from terralocal.server.protocol.sync import SyncDataAssembler

    candidate = ctx.data.rogue_special_recruit.candidates[char_id]
    if candidate.kind not in ("FREE", "THIRD"):
        raise DomainError("ROGUE_TEMPORARY_INCOMPATIBLE", "此干员不是已接纳临时候选", 503)
    definition = ctx.data.character(char_id)
    cap = ctx.data.rogue_upgrades.ceilings[int(upgraded)]
    phase = cap.evolve_phase
    skin = default_skin(ctx.data, char_id)
    op = SimpleNamespace(id=ordinal, char_id=char_id, evolve_phase=phase, level=definition["phases"][phase]["maxLevel"],
        exp=0, potential=5, trust=maximum_trust(ctx.data), skill_level=min(cap.skill_level, len(definition["allSkillLvlup"]) + 1),
        skin=skin, default_skill=0, gained_at=original["gainTime"] if original else gained_at if gained_at is not None else ctx.now,
        voice_language=original["voiceLan"] if original else initial_language(ctx, char_id), current_module=None, locked=False)
    skills = {ordinal: [SimpleNamespace(skill_id=s["skillId"], mastery=cap.specialize_level, training_complete_at=None)
                        for s in definition["skills"]]} if upgraded else {}
    value = SyncDataAssembler(ctx).operator(op, skills)
    for skill in value["skills"]:
        skill["unlock"] = bool(skill["unlock"])
        if not skill["unlock"]:
            skill["specializeLevel"] = 0
    return (TrainedCharacter if upgraded else Character).model_validate(value).model_dump()


def validate(data, ticket, option, *, upgraded=False, original=None):
    from terralocal.server.domain.operator_limits import maximum_trust
    from terralocal.server.domain.rogue_recruit import incompatible

    value = option.character
    candidate = data.rogue_special_recruit.candidates.get(value["charId"])
    definition = data.character(value["charId"])
    cap = data.rogue_upgrades.ceilings[int(upgraded)]
    if candidate is None or candidate.kind not in ("FREE", "THIRD"):
        raise incompatible()
    if not upgraded:
        if candidate.kind == "THIRD":
            pool = data.rogue_special_recruit.elite_scope(ticket.item_id, tuple(ticket.elite_pool))
        else:
            pool = data.rogue_special_recruit.pool(ticket.item_id, kind="FREE", rarity=candidate.rarity)
        if option.kind != candidate.kind or value["charId"] not in {c.char_id for c in pool}:
            raise incompatible()
    if (option.source_operator_id is not None
            or value["evolvePhase"] != cap.evolve_phase
            or value["level"] != definition["phases"][cap.evolve_phase]["maxLevel"]
            or value["favorPoint"] != maximum_trust(data) or value["potentialRank"] != 5
            or value["exp"] != 0 or value["skin"] != default_skin(data, value["charId"]) or value["starMark"] != 0
            or value["voiceLan"] not in data.table("charword_table")["voiceLangDict"][value["charId"]]["dict"]
            or value["mainSkillLvl"] != min(cap.skill_level, len(definition["allSkillLvlup"]) + 1)
            or value["gainTime"] != (original["gainTime"] if original else ticket.created_at)
            or any(s["specializeLevel"] != (cap.specialize_level if s["unlock"] else 0) for s in value["skills"])):
        raise incompatible()
