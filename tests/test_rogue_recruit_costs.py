"""Mechanical cost filters are independent of item descriptions and grants."""

import copy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from terralocal.server.gamedata.rogue_recruit_costs import FirstThemeRecruitCostRules

R25, R26, R27, R28 = ("rogue_1_relic_r" + str(n) for n in range(25, 29))


def source():
    items, relics, params = {}, {}, {}
    for key, tiers in ((R25, "TIER_4"), (R26, "TIER_5"), (R27, "TIER_6"), (R28, "TIER_4,TIER_5,TIER_6")):
        items[key] = {"id": key, "type": "RELIC", "usage": "All operators, deliberately misleading QA text"}
        relics[key] = {"id": key, "buffs": [{"key": "recruit_cost", "blackboard": [
            {"key": "rarity", "value": 0.0, "valueStr": tiers},
            {"key": "profession", "value": 0.0, "valueStr": "PIONEER,WARRIOR,TANK,SNIPER,CASTER,SUPPORT,MEDIC,SPECIAL"},
            {"key": "delta", "value": -2.0, "valueStr": None}]}]}
        params[key] = {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []}
    archive = {key: {"relicId": key, "enrollId": None, "isSpRelic": False,
                    "relicGroupId": 1, "relicSortId": index, "orderId": str(index)}
               for index, key in enumerate(items)}
    return {"details": {"rogue_1": {"items": items, "relics": relics, "relicParams": params,
                                    "archiveComp": {"relic": {"relic": archive}}, "enrolls": {}}}}


def load(table):
    return FirstThemeRecruitCostRules(SimpleNamespace(table=lambda name: table, manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda topic: topic)))


def quote(rules, base=3, *, rarity="TIER_5", modifiers=(R28,), operation="RECRUIT"):
    return rules.quote(base, profession="SNIPER", rarity=rarity, modifiers=modifiers, operation=operation)


@pytest.mark.parametrize("rarity,base,total", [("TIER_3", 0, 0), ("TIER_4", 2, 0), ("TIER_5", 3, 1), ("TIER_6", 6, 4)])
def test_speech_uses_actual_high_rarity_filter_instead_of_all_operator_description(rarity, base, total):
    rules = load(source())
    result = quote(rules, base, rarity=rarity)
    assert result.total == total
    assert result.applied == (() if rarity == "TIER_3" else (R28,))


def test_specific_relics_do_not_discount_other_rarities_upgrade_fees_or_generate_hope():
    rules = load(source())
    assert quote(rules, 3, modifiers=(R25, R27)).total == 3
    assert quote(rules, 2, modifiers=(R26, R28), operation="UPGRADE").total == 2
    assert quote(rules, 0, modifiers=(R26, R28)).total == 0
    reduced = quote(rules, 3, modifiers=(R26, R28))
    assert (reduced.base, reduced.delta, reduced.total) == (3, -4, 0)
    assert reduced.rule_hash == quote(rules, 3, modifiers=(R28, R26)).rule_hash
    # Retain even nonmatching effects in the immutable context hash.
    one = quote(rules, modifiers=(R26,))
    other = quote(rules, modifiers=(R26, R27))
    assert one.total == other.total and one.rule_hash != other.rule_hash


def test_compiled_effects_and_quotes_are_immutable_when_source_table_changes():
    table = source()
    rules = load(table)
    result = quote(rules)
    table["details"]["rogue_1"]["relics"][R28]["buffs"][0]["blackboard"][2]["value"] = 100
    assert quote(rules) == result
    with pytest.raises(TypeError):
        rules.modifiers[R28] = None
    with pytest.raises(FrozenInstanceError):
        result.total = 900


@pytest.mark.parametrize("damage", ["missing", "item_id", "item_type", "relic_id", "extra_effect", "empty_effect",
    "wrong_effect", "conditional", "duplicate_field", "unknown_field", "missing_field", "duplicate_rarity",
    "low_tier_speech", "wrong_profession", "bool_filter", "wrong_delta", "bool_delta", "nan_delta", "string_delta"])
def test_changed_or_ambiguous_effects_fail_instead_of_silent_base_cost_fallback(damage):
    table = source()
    detail = table["details"]["rogue_1"]
    row = detail["relics"][R28]
    board = row["buffs"][0]["blackboard"]
    if damage == "missing":
        del detail["relics"][R28]
    elif damage == "item_id":
        detail["items"][R28]["id"] = R27
    elif damage == "item_type":
        detail["items"][R28]["type"] = "RECRUIT_TICKET"
    elif damage == "relic_id":
        row["id"] = R27
    elif damage == "extra_effect":
        row["buffs"].append(copy.deepcopy(row["buffs"][0]))
    elif damage == "empty_effect":
        row["buffs"] = []
    elif damage == "wrong_effect":
        row["buffs"][0]["key"] = "upgrade_cost"
    elif damage == "conditional":
        detail["relicParams"][R28]["checkCharBoxTypes"] = ["WARRIOR"]
    elif damage == "duplicate_field":
        board.append(copy.deepcopy(board[0]))
    elif damage == "unknown_field":
        board.append({"key": "chance", "value": 0.5, "valueStr": None})
    elif damage == "missing_field":
        del board[2]["valueStr"]
    elif damage == "duplicate_rarity":
        board[0]["valueStr"] += ",TIER_4"
    elif damage == "low_tier_speech":
        board[0]["valueStr"] += ",TIER_3"
    elif damage == "wrong_profession":
        board[1]["valueStr"] = "SNIPER"
    elif damage == "bool_filter":
        board[1]["value"] = False
    else:
        board[2]["value"] = {"wrong_delta": -1.5, "bool_delta": True, "nan_delta": float("nan"), "string_delta": "-2"}[damage]
    with pytest.raises(ValueError):
        load(table)


@pytest.mark.parametrize("override", [{"base": True}, {"base": -1}, {"base": 2**31}, {"rarity": "TIER_7"},
    {"profession": "ALL"}, {"operation": "SHOP"}, {"operation": None}, {"modifiers": [R28]},
    {"modifiers": (R28, R28)}, {"modifiers": ("rogue_1_relic_c13",)}, {"modifiers": (None,)}])
def test_invalid_quote_context_is_rejected(override):
    rules = load(source())
    args = {"base": 3, "profession": "SNIPER", "rarity": "TIER_5", "modifiers": (R28,)} | override
    with pytest.raises(ValueError):
        rules.quote(**args)
