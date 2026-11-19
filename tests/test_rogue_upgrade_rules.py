"""Authored static-filter cases; no native, eligibility or effect claims."""

import copy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from terralocal.server.gamedata.rogue_upgrades import FirstThemeUpgradeRules

PROFESSIONS = ("WARRIOR", "SNIPER", "TANK", "MEDIC", "SUPPORT", "CASTER", "SPECIAL", "PIONEER")
RARITIES = ["TIER_" + str(i) for i in range(1, 7)]


def source():
    tickets = {}
    for name, professions, rarities, profession, rarity in [
        ("all", list(PROFESSIONS), RARITIES, 639, "ALL"),
        ("5star", list(PROFESSIONS), RARITIES[:5], 639, 31),
        *[(p.lower(), [p], RARITIES, p, "ALL") for p in PROFESSIONS],
    ]:
        key = "rogue_1_upgrade_ticket_" + name
        tickets[key] = {"id": key, "profession": profession, "rarity": rarity,
                        "professionList": list(professions), "rarityList": list(rarities)}
    return {"upgradeTickets": tickets,
            "items": {key: {"id": key, "type": "UPGRADE_TICKET"} for key in tickets},
            "detailConst": {"charUpgradeTable": {
                "0": {"evolvePhase": "PHASE_1", "skillLevel": 7, "skillSpecializeLevel": 0},
                "1": {"evolvePhase": "PHASE_2", "skillLevel": 7, "skillSpecializeLevel": 3}}}}


def load(detail):
    return FirstThemeUpgradeRules(SimpleNamespace(
        rogue_topics=SimpleNamespace(topic=lambda key: key), manifest={"hash": "a" * 64},
        table=lambda name: {"details": {"rogue_1": detail}}))


def test_every_ticket_filters_all_eight_professions_and_six_rarities():
    rules = load(source())
    assert len(rules.tickets) == 10
    # Whole-family matrix, not repeated gameplay of a single operator.
    for profession in PROFESSIONS:
        for rarity in range(6):
            definition = {"profession": profession, "rarity": rarity}
            assert rules.tickets["rogue_1_upgrade_ticket_all"].matches_definition(definition)
            assert rules.tickets["rogue_1_upgrade_ticket_5star"].matches_definition(definition) == (rarity < 5)
            for selected in PROFESSIONS:
                ticket = rules.tickets["rogue_1_upgrade_ticket_" + selected.lower()]
                assert ticket.matches_definition(definition) == (selected == profession)
                assert ticket.matches_definition(definition | {"rarity": RARITIES[rarity]}) == (selected == profession)
    assert [(c.evolve_phase, c.skill_level, c.specialize_level) for c in rules.ceilings] == [(1, 7, 0), (2, 7, 3)]


@pytest.mark.parametrize("damage", ["missing", "extra", "id", "item", "item_id", "mask", "bool_mask",
                                  "duplicate", "empty", "unknown", "not_list", "mixed", "cap", "cap_bool"])
def test_unknown_or_inconsistent_rules_fail_without_fallback(damage):
    detail = source()
    key = "rogue_1_upgrade_ticket_all"
    row = detail["upgradeTickets"][key]
    if damage == "missing":
        del detail["upgradeTickets"][key]
    elif damage == "extra":
        detail["upgradeTickets"]["future"] = copy.deepcopy(row)
    elif damage == "id":
        row["id"] = "other"
    elif damage in ("item", "item_id"):
        detail["items"][key]["type" if damage == "item" else "id"] = "other"
    elif damage in ("mask", "bool_mask"):
        row["profession"] = 255 if damage == "mask" else True
    elif damage == "duplicate":
        row["professionList"].append("WARRIOR")
    elif damage == "empty":
        row["rarityList"] = []
    elif damage == "unknown":
        row["rarityList"][-1] = "TIER_7"
    elif damage == "not_list":
        row["professionList"] = "WARRIOR"
    elif damage == "mixed":
        row["professionList"][-1] = {}
    else:
        detail["detailConst"]["charUpgradeTable"]["1"]["skillSpecializeLevel"] = 4 if damage == "cap" else True
    with pytest.raises(ValueError):
        load(detail)


@pytest.mark.parametrize("rarity", [True, -1, 6, 1.0, None, "ALL", "TIER_7"])
def test_invalid_character_rarity_is_not_coerced(rarity):
    with pytest.raises(ValueError):
        load(source()).tickets["rogue_1_upgrade_ticket_all"].matches_definition(
            {"profession": "MEDIC", "rarity": rarity})


def test_catalog_copies_filters_and_does_not_alias_input_rows():
    detail = source()
    rules = load(detail)
    before = rules.fingerprint
    detail["upgradeTickets"]["rogue_1_upgrade_ticket_all"]["professionList"].clear()
    detail["detailConst"]["charUpgradeTable"]["1"]["skillLevel"] = 1
    assert rules.fingerprint == before
    assert rules.tickets["rogue_1_upgrade_ticket_all"].matches_definition({"profession": "MEDIC", "rarity": "TIER_6"})
    assert rules.ceilings[1].skill_level == 7
    with pytest.raises(TypeError):
        rules.tickets["other"] = rules.tickets["rogue_1_upgrade_ticket_all"]
    with pytest.raises(FrozenInstanceError):
        rules.ceilings[1].evolve_phase = 0
