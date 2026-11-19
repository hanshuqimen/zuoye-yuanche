"""Append-only first-theme training; original offers and battle squads stay intact.

An exploration promotion opens the second table ceiling. It does not create
training absent from the owned operator. Ticket eligibility (four-star+, phase0,
matching ticket) follows frozen GetUpgradableCharCount, not owned elite phase.
"""

from copy import deepcopy
from types import SimpleNamespace

from pydantic import Field, ValidationError

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_recruit import Character, Skill, VoiceLanguage
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.persistence import models as m

POLICY = "rogue1-free-upgrade-history-v1"
PAID_POLICY = "rogue1-paid-upgrade-history-v1"


class TrainedSkill(Skill):
    specializeLevel: int = Field(ge=0, le=3)


class TrainedCharacter(Character):
    evolvePhase: int = Field(ge=0, le=2)
    skills: list[TrainedSkill] = Field(max_length=3)
    voiceLan: VoiceLanguage


def invalid():
    return DomainError("ROGUE_TRAINING_INCOMPATIBLE", "探索晋升记录不一致；请保留原存档", 503)


def history(char):
    value = getattr(char, "training", [])
    if type(value) is not list or len(value) > 1:
        raise invalid()
    return value


def promoted(value, ordinal, *, kind="NORMAL"):
    return TrainedCharacter.model_validate(value).model_dump() | {
        "instId": ordinal, "upgradePhase": 1, "upgradeLimited": True, "type": kind, "charBuff": []}


def check_character(data, value, *, kind="NORMAL"):
    """Admit a frozen owned snapshot, without reading later main-roster stats."""
    try:
        char = TrainedCharacter.model_validate(value).model_dump()
        definition = data.character(char["charId"])
        if (canonical(char) != canonical(value) or len(canonical(char)) > 32768 or char["equip"] or char["voiceLan"] == "NONE"
                or char["currentEquip"] is not None or definition.get("isNotObtainable") and (
                    kind != "THIRD" or char["charId"] not in data.rogue_special_recruit.candidates
                    or data.rogue_special_recruit.candidates[char["charId"]].kind != "THIRD")
                or char["evolvePhase"] >= len(definition["phases"])
                or char["level"] > definition["phases"][char["evolvePhase"]]["maxLevel"]):
            raise invalid()
        skill_defs = definition["skills"]
        if [s["skillId"] for s in char["skills"]] != [s["skillId"] for s in skill_defs]:
            raise invalid()
        from terralocal.server.domain.operators import check_condition

        cap = SimpleNamespace(evolve_phase=char["evolvePhase"], level=char["level"])
        for skill, row in zip(char["skills"], skill_defs, strict=True):
            if (skill["unlock"] != check_condition(cap, row["unlockCond"])
                    or skill["specializeLevel"] and (not skill["unlock"] or char["evolvePhase"] < 2)):
                raise invalid()
        selected = char["defaultSkillIndex"]
        if skill_defs and (selected not in range(len(skill_defs)) or not char["skills"][selected]["unlock"]):
            raise invalid()
        return char
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        raise invalid() from exc


def validate_offer(data, ticket, option, chars, options):
    try:
        target = getattr(option, "target_char_ordinal", None)
        if option.kind not in ("UPGRADE", "UPGRADE_PAID") or type(target) is not int or target < 1:
            raise invalid()
        member = next(c for c in chars if c.ordinal == target)
        base = next(o for o in options if (o.ticket_ordinal, o.ordinal) == (member.ticket_ordinal, member.option_ordinal))
        definition = data.character(base.character["charId"])
        if option.kind == "UPGRADE":
            rule = data.rogue_upgrades.tickets[ticket.item_id]
            matches, cost = rule.matches_definition(definition), 0
        else:
            from terralocal.server.domain.rogue_temporary import rule as recruit_rule

            rule = recruit_rule(data, ticket.item_id)
            matches = rule is not None and rule.matches_definition(definition)
            cost = data.rogue_recruit.upgrade_costs[data.rarity(definition)]
        value = check_character(data, option.character, kind=base.kind)
        if (base.kind not in ("NORMAL", "FREE", "THIRD") or base.source_operator_id != option.source_operator_id
                or base.kind == "NORMAL" and (type(option.source_operator_id) is not int or option.source_operator_id < 1)
                or value["charId"] != base.character["charId"] or value["instId"] != option.ordinal
                or data.rarity(definition) < 3 or not matches or option.hope_cost != cost
                or value["evolvePhase"] < base.character["evolvePhase"]
                or value["evolvePhase"] == base.character["evolvePhase"] and value["level"] < base.character["level"]
                or value["mainSkillLvl"] < base.character["mainSkillLvl"]):
            raise invalid()
        if base.kind in ("FREE", "THIRD"):
            from terralocal.server.domain.rogue_temporary import validate as validate_temporary

            validate_temporary(data, ticket, option, upgraded=True, original=base.character)
        record = history(member)
        if record and ticket.ordinal > record[0]["ticket"]:
            raise invalid()  # An already promoted character cannot enter a later offer.
        return member, base
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        raise invalid() from exc


def digest(data, run, char, record):
    return fingerprint({"policy": record["policy"], "data": data.manifest["hash"], "run": run.id,
                        "char": char.ordinal, "origin": [char.ticket_ordinal, char.option_ordinal],
                        "record": {k: v for k, v in record.items() if k != "rule_hash"}})


def validate(data, run, tickets, options, chars):
    by_ticket = {t.ordinal: t for t in tickets}
    used = {}
    for member in chars:
        for record in history(member):
            try:
                paid = record.get("policy") == PAID_POLICY if type(record) is dict else False
                if (type(record) is not dict or set(record) != {
                        "version", "policy", "ticket", "option", "source", "at", "before_hash", "after_hash", "rule_hash"} | ({"hope_cost"} if paid else set())
                        or type(record["version"]) is not int or record["version"] != 1 or record["policy"] not in (POLICY, PAID_POLICY)
                        or type(record["ticket"]) is not int or type(record["option"]) is not int
                        or record["ticket"] in used or record["ticket"] < 3
                        or record["rule_hash"] != digest(data, run, member, record)):
                    raise invalid()
                ticket = by_ticket[record["ticket"]]
                option = next(o for o in options if (o.ticket_ordinal, o.ordinal) == (ticket.ordinal, record["option"]))
                if (option.kind != ("UPGRADE_PAID" if paid else "UPGRADE")
                        or paid and (type(record["hope_cost"]) is not int or record["hope_cost"] != option.hope_cost)):
                    raise invalid()
                target, base = validate_offer(data, ticket, option, chars, options)
                source = check_character(data, record["source"], kind=base.kind)
                from terralocal.server.domain.rogue_recruit import recruited_character

                if (target.ordinal != member.ordinal or ticket.state != "DONE"
                        or source != option.character | {"instId": member.ordinal}
                        or record["before_hash"] != fingerprint(recruited_character(base, member.ordinal))
                        or record["after_hash"] != fingerprint(promoted(source, member.ordinal, kind=base.kind))
                        or type(record["at"]) is not int or not run.created_at <= ticket.created_at <= record["at"] < 2**63
                        or run.ended_at is not None and record["at"] > run.ended_at):
                    raise invalid()
                used[ticket.ordinal] = option.ordinal
            except (KeyError, TypeError, ValueError, StopIteration, ValidationError) as exc:
                raise invalid() from exc
    return used


class Troop(dict):
    """Current wire dictionary with explicit historical revisions for battles."""

    def __init__(self, base, chars):
        self._base = deepcopy(base)
        self._history = {str(c.ordinal): deepcopy(history(c)) for c in chars}
        current = deepcopy(base)
        for key, records in self._history.items():
            if records:
                current[key] = promoted(records[0]["source"], int(key), kind=base[key]["type"])
        super().__init__(current)

    def revisions(self, slots):
        return {str(s["charInstId"]): len(self._history[str(s["charInstId"])])
                for s in slots if s and self._history[str(s["charInstId"])]}

    def at(self, revisions, started_at):
        if type(revisions) is not dict or len(revisions) > 12:
            raise invalid()
        result = deepcopy(self._base)
        for key, revision in revisions.items():
            if (key not in result or type(revision) is not int or revision != 1
                    or len(self._history[key]) != revision or self._history[key][0]["at"] > started_at):
                raise invalid()
            result[key] = promoted(self._history[key][0]["source"], int(key), kind=self._base[key]["type"])
        return result


def apply(ctx, run, ticket, option, children):
    from terralocal.server.domain.rogue_battle import ensure_no_active

    ensure_no_active(ctx)
    members, options = children[4], children[3]
    member, base = validate_offer(ctx.data, ticket, option, members, options)
    if history(member):
        raise DomainError("ROGUE_ALREADY_UPGRADED", "此探索干员已经进阶，未消耗票券", 409)
    if run.hope_cost + option.hope_cost > run.hope_max:
        raise DomainError("ROGUE_HOPE_REQUIRED", "希望不足，未消耗招募券或晋升干员", 409)
    source = option.character | {"instId": member.ordinal}
    result = promoted(source, member.ordinal, kind=base.kind)
    from terralocal.server.domain.rogue_recruit import recruited_character

    paid = option.kind == "UPGRADE_PAID"
    record = {"version": 1, "policy": PAID_POLICY if paid else POLICY, "ticket": ticket.ordinal, "option": option.ordinal,
              "source": source, "at": ctx.now, "before_hash": fingerprint(recruited_character(base, member.ordinal)),
              "after_hash": fingerprint(result)}
    if paid:
        record["hope_cost"] = option.hope_cost
    if ctx.now < max(run.created_at, ticket.created_at):
        raise DomainError("ROGUE_CLOCK_REWIND", "服务器时间早于此招募券，未消耗票券", 409)
    record["rule_hash"] = digest(ctx.data, run, member, record)
    member.training = [record]
    run.hope_cost += option.hope_cost
    ticket.state = "DONE"
    ctx.session.flush()
    return {"chars": [result | {"isAddition": 0, "isElite": 0, "isFree": int(option.hope_cost == 0)}]}


def activate(ctx, run, ticket, children):
    from terralocal.server.domain.rogue_battle import ensure_no_active

    ensure_no_active(ctx)
    if ticket.item_id not in ctx.data.rogue_upgrades.tickets:
        raise invalid()
    add_offers(ctx, run, ticket, children)
    # Empty lists remain dismissible; never fabricate a reserve or promotion.
    ticket.state = "ACTIVE"
    ctx.session.flush()
    return {}


def add_offers(ctx, run, ticket, children, *, start=0, paid=False):
    from terralocal.server.domain.rogue_recruit import capped_character
    from terralocal.server.domain.rogue_temporary import rule as recruit_rule

    rule = recruit_rule(ctx.data, ticket.item_id) if paid else ctx.data.rogue_upgrades.tickets[ticket.item_id]
    offers = {(o.ticket_ordinal, o.ordinal): o for o in children[3]}
    ordinal = start
    for char in children[4]:
        base = offers[(char.ticket_ordinal, char.option_ordinal)]
        definition = ctx.data.character(base.character["charId"])
        if (history(char) or base.kind not in ("NORMAL", "FREE", "THIRD") or ctx.data.rarity(definition) < 3
                or not rule.matches_definition(definition)):
            continue
        if base.kind in ("FREE", "THIRD"):
            from terralocal.server.domain.rogue_temporary import character as temporary_character

            source_id = None
            value = temporary_character(ctx, base.character["charId"], ordinal, upgraded=True, original=base.character)
        else:
            source = ctx.session.get(m.Operator, base.source_operator_id)
            if source is None or source.account_id != ctx.account_id or source.char_id != base.character["charId"]:
                raise invalid()
            source_id = source.id
            value = capped_character(ctx, source, ordinal, upgraded=True)
        # A GM may lower permanent training after recruitment. Do not let a
        # promotion silently lower the independent exploration snapshot.
        if (value["evolvePhase"] < base.character["evolvePhase"]
                or value["evolvePhase"] == base.character["evolvePhase"] and value["level"] < base.character["level"]
                or value["mainSkillLvl"] < base.character["mainSkillLvl"]):
            continue
        ctx.session.add(m.RogueRecruitOption(run_id=run.id, ticket_ordinal=ticket.ordinal, ordinal=ordinal,
            source_operator_id=source_id, kind="UPGRADE_PAID" if paid else "UPGRADE",
            hope_cost=ctx.data.rogue_recruit.upgrade_costs[ctx.data.rarity(definition)] if paid else 0, character=value,
            target_char_ordinal=char.ordinal))
        ordinal += 1


def eligible(data, ticket_id, options, chars):
    """Frozen client count conditions; owned elite phase is not a condition."""
    rule = data.rogue_upgrades.tickets[ticket_id]
    offered = {(o.ticket_ordinal, o.ordinal): o for o in options}
    return [c for c in chars if not history(c)
            and (o := offered[(c.ticket_ordinal, c.option_ordinal)]).kind in ("NORMAL", "FREE", "THIRD")
            and data.rarity(data.character(o.character["charId"])) >= 3
            and rule.matches_definition(data.character(o.character["charId"]))]
