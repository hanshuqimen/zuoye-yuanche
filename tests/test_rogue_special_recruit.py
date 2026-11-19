"""Authored special-catalog/filter cases; no enabled effects or native claims."""

import copy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.gamedata.rogue_special_recruit import ELITE_TICKET_ID, FirstThemeSpecialRecruitRules

PROFESSIONS = ("PIONEER", "WARRIOR", "SNIPER", "MEDIC", "TANK", "SUPPORT", "CASTER", "SPECIAL")
RARITIES = ["TIER_" + str(n) for n in range(1, 7)]


def source():
    tickets, items, chars, predefined = {}, {"gold": {"type": "GOLD"}}, {}, {}
    for profession in PROFESSIONS:
        for tier in (4, 5, 6):
            key = profession.lower() + str(tier)
            chars[key] = {"profession": profession, "rarity": "TIER_" + str(tier), "phases": [{}, {}, {}]}
            predefined[key] = {"charId": key, "recruitType": "FREE", "canBeFree": True, "uniEquipId": None}
    chars["elite"] = {"profession": "WARRIOR", "rarity": "TIER_5", "phases": [{}, {}, {}], "isNotObtainable": True}
    predefined["elite"] = {"charId": "elite", "recruitType": "THIRD", "canBeFree": False, "uniEquipId": None}
    chars["reserve"] = {"profession": "TANK", "rarity": "TIER_3", "phases": [{}, {}]}
    predefined["reserve"] = {"charId": "reserve", "recruitType": "THIRD_LOW", "canBeFree": False, "uniEquipId": None}
    chars["not_free"] = {"profession": "WARRIOR", "rarity": "TIER_6", "phases": [{}, {}, {}]}
    predefined["not_free"] = {"charId": "not_free", "recruitType": "FREE", "canBeFree": False, "uniEquipId": None}
    specs = [(p.lower() + "_sp", p, [p], 0, ["TIER_4"]) for p in PROFESSIONS]
    specs += [(('redecial' if p == "SPECIAL" else p.lower()) + "_red", p, [p], 0, ["TIER_6"]) for p in PROFESSIONS]
    specs += [("all_premium", 639, list(PROFESSIONS), 1, []), ("all_discount", 639, list(PROFESSIONS), 0, []),
        ("quad_melee_discount", 581, ["PIONEER", "WARRIOR", "TANK", "SPECIAL"], 0, []),
        ("quad_ranged_discount", 58, ["SNIPER", "MEDIC", "SUPPORT", "CASTER"], 0, [])]
    for suffix, mask, professions, elite, free in specs:
        key = "rogue_1_recruit_ticket_" + suffix
        tickets[key] = {"id": key, "profession": mask, "professionList": professions, "rarity": "ALL",
            "rarityList": list(RARITIES), "extraEliteNum": elite, "extraFreeRarity": free, "extraCharIds": ["reserve"]}
        items[key] = {"id": key, "type": "RECRUIT_TICKET"}
    return {"constant": {"predefinedChars": predefined}, "details": {"rogue_1": {
        "items": items, "recruitTickets": tickets, "gameConst": {"goldItemId": "gold"}}}}, chars


def load(value):
    table, chars = value
    return FirstThemeSpecialRecruitRules(SimpleNamespace(
        table=lambda name: table, character=lambda key: chars[key], manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda key: key)))


def test_all_twenty_contracts_distinguish_free_elite_and_direct_upgrade():
    rules = load(source())
    assert len(rules.tickets) == 20 and len(rules.candidates) == 25
    assert "not_free" not in rules.candidates and "reserve" not in rules.candidates
    for profession in PROFESSIONS:
        for suffix, tier in (("sp", 4), ("red", 6)):
            name = "redecial" if profession == "SPECIAL" and suffix == "red" else profession.lower()
            ticket = rules.tickets["rogue_1_recruit_ticket_" + name + "_" + suffix]
            assert (ticket.effect, ticket.free_rarities, ticket.elite_count) == (
                "FREE_TEMP_GUARANTEED", frozenset({"TIER_" + str(tier)}), 0)
            pool = rules.pool(ticket.id, kind="FREE", rarity="TIER_" + str(tier))
            assert [c.char_id for c in pool] == [profession.lower() + str(tier)]
            assert rules.pool(ticket.id, kind="FREE", rarity="TIER_" + str(tier), excluded=(pool[0].char_id,)) == ()
    premium = rules.tickets["rogue_1_recruit_ticket_all_premium"]
    assert premium.effect == "ELITE_TEMP_GUARANTEED"
    assert [c.char_id for c in rules.pool(premium.id, kind="THIRD")] == ["elite"]
    for suffix in ("all_discount", "quad_melee_discount", "quad_ranged_discount"):
        assert rules.tickets["rogue_1_recruit_ticket_" + suffix].effect == "DIRECT_UPGRADE_RANDOM"


@pytest.mark.parametrize("damage", ["missing", "id", "item_id", "item_type", "mask", "bool_mask", "rarity",
    "duplicate_prof", "wrong_prof", "duplicate_rarity", "extra_free", "wrong_free", "bool_elite", "elite",
    "unknown_field", "duplicate_reserve", "unknown_reserve", "reserve_kind"])
def test_ticket_corruption_fails_without_ordinary_fallback(damage):
    value = source()
    table, _ = value
    d = table["details"]["rogue_1"]
    key = "rogue_1_recruit_ticket_pioneer_sp"
    row = d["recruitTickets"][key]
    if damage == "missing":
        del d["recruitTickets"][key]
    elif damage == "id":
        row["id"] = "other"
    elif damage.startswith("item_"):
        d["items"][key]["id" if damage == "item_id" else "type"] = "other"
    elif damage in ("mask", "bool_mask"):
        row["profession"] = 512 if damage == "mask" else True
    elif damage == "rarity":
        row["rarity"] = 63
    elif damage in ("duplicate_prof", "wrong_prof"):
        row["professionList"] = ["PIONEER", "PIONEER"] if damage == "duplicate_prof" else ["MEDIC"]
    elif damage == "duplicate_rarity":
        row["rarityList"].append("TIER_6")
    elif damage in ("extra_free", "wrong_free"):
        row["extraFreeRarity"] = ["TIER_4", "TIER_6"] if damage == "extra_free" else ["TIER_6"]
    elif damage in ("bool_elite", "elite"):
        row["extraEliteNum"] = False if damage == "bool_elite" else 1
    elif damage == "unknown_field":
        row["futureEffect"] = 1
    elif damage in ("duplicate_reserve", "unknown_reserve"):
        row["extraCharIds"] = ["reserve", "reserve"] if damage == "duplicate_reserve" else ["unknown"]
    else:
        table["constant"]["predefinedChars"]["reserve"]["recruitType"] = "FREE"
    with pytest.raises((ValueError, KeyError)):
        load(value)


@pytest.mark.parametrize("damage", ["id", "kind", "can_free", "module", "profession", "rarity", "phase", "obtainable", "empty_free", "empty_elite"])
def test_predefined_references_and_guaranteed_pools_are_checked(damage):
    value = source()
    table, chars = value
    p = table["constant"]["predefinedChars"]
    row = p["pioneer4"]
    if damage in ("id", "kind", "can_free", "module"):
        field = {"id": "charId", "kind": "recruitType", "can_free": "canBeFree", "module": "uniEquipId"}[damage]
        row[field] = {"id": "other", "kind": "FUTURE", "can_free": 1, "module": {}}[damage]
    elif damage == "profession":
        chars["pioneer4"]["profession"] = []
    elif damage == "rarity":
        chars["pioneer4"]["rarity"] = "TIER_3"
    elif damage == "phase":
        chars["pioneer4"]["phases"].pop()
    elif damage == "obtainable":
        chars["pioneer4"]["isNotObtainable"] = True
    elif damage == "empty_free":
        row["canBeFree"] = False
    else:
        del p["elite"]
    with pytest.raises((ValueError, KeyError)):
        load(value)


def test_filters_are_immutable_and_only_implemented_guaranteed_free_quotes_are_admitted():
    value = source()
    rules = load(value)
    before = rules.fingerprint
    with pytest.raises(TypeError):
        rules.tickets["new"] = None
    with pytest.raises(FrozenInstanceError):
        rules.candidates["pioneer4"].module_id = "new"
    value[0]["constant"]["predefinedChars"]["pioneer4"]["canBeFree"] = False
    assert rules.fingerprint == before
    assert rules.pool("rogue_1_recruit_ticket_pioneer_sp", kind="FREE", rarity="TIER_4")
    data = SimpleNamespace(rogue_recruit=SimpleNamespace(catalog={}), rogue_upgrades=SimpleNamespace(tickets={}),
        rogue_special_recruit=rules, table=lambda name: value[0], manifest={"hash": "a" * 64})
    for key, ticket in rules.tickets.items():
        if ticket.effect == "FREE_TEMP_GUARANTEED":
            assert compile_shop(data, "qa", (Offer("one", key, 0),), evidence="QA temporary quote").offers["one"].item_id == key
        elif key == ELITE_TICKET_ID:
            with pytest.raises(ValueError, match="明确"):
                compile_shop(data, "qa", (Offer("one", key, 0),), evidence="Missing theme/account scope")
            assert compile_shop(data, "qa", (Offer("one", key, 0, ("elite",)),),
                                evidence="Explicit QA elite scope").offers["one"].elite_pool == ("elite",)
        else:
            with pytest.raises(ValueError, match="明确"):
                compile_shop(data, "qa", (Offer("one", key, 0),), evidence="QA unsupported special effect")


@pytest.mark.parametrize("args", [
    {"ticket_id": "missing", "kind": "FREE", "rarity": "TIER_4"},
    {"ticket_id": "rogue_1_recruit_ticket_pioneer_sp", "kind": "NORMAL", "rarity": "TIER_4"},
    {"ticket_id": "rogue_1_recruit_ticket_pioneer_sp", "kind": "FREE", "rarity": "TIER_6"},
    {"ticket_id": "rogue_1_recruit_ticket_all_discount", "kind": "FREE", "rarity": "TIER_4"},
    {"ticket_id": "rogue_1_recruit_ticket_all_premium", "kind": "THIRD", "rarity": "TIER_5"},
    {"ticket_id": "rogue_1_recruit_ticket_pioneer_sp", "kind": "FREE", "rarity": "TIER_4", "excluded": ["pioneer4"]},
])
def test_pool_requests_do_not_invent_an_effect(args):
    with pytest.raises(ValueError):
        load(copy.deepcopy(source())).pool(**args)
