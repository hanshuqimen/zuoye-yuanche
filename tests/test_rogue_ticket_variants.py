"""Plain multi-profession tickets; no special offers or official supply pools."""

import copy
from types import SimpleNamespace

import pytest
import test_rogue_training as training_fixture
from fastapi.testclient import TestClient
from test_rogue_paid_training import buy, leave, promote, shop
from test_rogue_training import choice, move
from test_roguelike_initial import current, post
from test_roguelike_recruit import recruit_tables
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.gamedata.rogue_recruit import VARIANTS, FirstThemeRecruitRules
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def variant_tables():
    tables = recruit_tables()
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    for profession in ("PIONEER", "WARRIOR", "SNIPER", "MEDIC", "TANK", "SUPPORT", "CASTER", "SPECIAL"):
        cid = "char_variant_" + profession.lower()
        tables["character_table"][cid] = copy.deepcopy(tables["character_table"]["char_four"]) | {"profession": profession}
        voice = tables["charword_table"]
        voice["voiceLangDict"][cid] = copy.deepcopy(voice["voiceLangDict"]["char_four"])
        voice["charDefaultTypeDict"][cid] = "JP"
    for suffix, (mask, professions, rarity_mask, rarities) in VARIANTS.items():
        key = "rogue_1_recruit_ticket_" + suffix
        detail["items"][key] = {"id": key, "type": "RECRUIT_TICKET"}
        detail["recruitTickets"][key] = {"id": key, "profession": mask, "rarity": rarity_mask,
            "professionList": sorted(professions), "rarityList": sorted(rarities),
            "extraEliteNum": 0, "extraFreeRarity": [], "extraCharIds": ["char_reserve"]}
    return tables


def pure_data(tables):
    return SimpleNamespace(rogue_initial=SimpleNamespace(topic_id="rogue_1", groups={
        "qa": tuple("ticket_" + p.lower() for p in (
            "PIONEER", "WARRIOR", "SNIPER", "MEDIC", "TANK", "SUPPORT", "CASTER", "SPECIAL"))}),
        table=lambda name: tables[name], character=lambda key: tables["character_table"][key])


@pytest.fixture
def install_variants(monkeypatch):
    monkeypatch.setattr(training_fixture, "recruit_tables", variant_tables)


@pytest.fixture
def variants_runtime(install_variants, training_runtime):
    return training_runtime


# Make the existing fixture available without changing its baseline inputs.
from test_rogue_training import training_runtime as training_runtime  # noqa: E402,F401


def test_catalog_keeps_legacy_pool_immutable_and_uses_both_filters():
    tables = variant_tables()
    rules = FirstThemeRecruitRules(pure_data(tables))
    assert len(rules.tickets) == 8 and len(rules.catalog) == 16
    assert sorted(rules.tickets) == sorted(k for k in rules.catalog if k.startswith("ticket_"))
    with pytest.raises(TypeError):
        rules.catalog["new"] = None
    for suffix, (_, professions, _, rarities) in VARIANTS.items():
        rule = rules.catalog["rogue_1_recruit_ticket_" + suffix]
        for profession in ("PIONEER", "WARRIOR", "SNIPER", "MEDIC", "TANK", "SUPPORT", "CASTER", "SPECIAL"):
            for tier in range(1, 7):
                assert rule.matches_definition({"profession": profession, "rarity": "TIER_" + str(tier)}) == (
                    profession in professions and "TIER_" + str(tier) in rarities)
        tables["roguelike_topic_table"]["details"]["rogue_1"]["recruitTickets"][rule.id]["extraCharIds"].clear()
        assert rule.reserves == ("char_reserve",)


@pytest.mark.parametrize("change", [
    {"profession": True}, {"profession": 638}, {"professionList": ["PIONEER"]},
    {"professionList": ["PIONEER"] * 8}, {"rarity": 31}, {"rarityList": ["TIER_6"]},
    {"extraEliteNum": True}, {"extraEliteNum": 1}, {"extraFreeRarity": ["TIER_6"]},
    {"extraCharIds": ["char_missing"]}, {"extraCharIds": ["char_reserve"] * 2},
    {"id": "other"}, {"futureEffect": 1},
])
def test_malformed_variant_is_rejected(change):
    tables = variant_tables()
    tables["roguelike_topic_table"]["details"]["rogue_1"]["recruitTickets"]["rogue_1_recruit_ticket_all"].update(change)
    with pytest.raises((ValueError, KeyError)):
        FirstThemeRecruitRules(pure_data(tables))


def test_special_effects_require_complete_rules_and_supply_contracts():
    tables = variant_tables()
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    key = "rogue_1_recruit_ticket_all_discount"
    detail["items"][key] = {"id": key, "type": "RECRUIT_TICKET"}
    detail["recruitTickets"][key] = copy.deepcopy(detail["recruitTickets"]["rogue_1_recruit_ticket_all"]) | {"id": key}
    detail.setdefault("gameConst", {})["goldItemId"] = "qa_gold"
    detail["items"]["qa_gold"] = {"type": "GOLD"}
    data = pure_data(tables)
    data.rogue_recruit = FirstThemeRecruitRules(data)
    data.rogue_upgrades = SimpleNamespace(tickets={})
    assert key not in data.rogue_recruit.catalog
    with pytest.raises(ValueError, match="完整发放效果|特殊招募供给合同"):
        compile_shop(data, "qa", (Offer("a", key, 0),), evidence="QA special rejection")


@pytest.mark.parametrize("suffix", tuple(VARIANTS))
def test_every_plain_variant_http_filters_recruits_retries_and_restores(variants_runtime, suffix):
    runtime, token = variants_runtime
    key = "rogue_1_recruit_ticket_" + suffix
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        for name in ("zero", "four", "five", "sniper"):
            ctx.acquire_operator("char_" + name)
        for profession in ("PIONEER", "WARRIOR", "SNIPER", "MEDIC", "TANK", "SUPPORT", "CASTER", "SPECIAL"):
            ctx.acquire_operator("char_variant_" + profession.lower())
        owned_ids = {op.char_id for op in session.query(m.Operator).filter_by(account_id=1) if op.char_id != "char_six"}
    shop(runtime, token, ("REST", "SHOP"), key)
    original_pool = dict(runtime.data.rogue_recruit.tickets)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert choice(client, token, "choice_rest_3", "hope").status_code == 200
        assert choice(client, token, "choice_leave", "rest-leave").status_code == 200
        assert move(client, token, 1, "shop").status_code == 200
        old = runtime.sync(token)["user"]
        reply = buy(client, token)
        assert reply.status_code == 200, reply.text
        saved = runtime.sync(token)["user"]
        assert apply(old, reply.json()["playerDataDelta"]) == saved
        candidates = current(runtime, token)["inventory"]["recruit"]["3"]["list"]
        rule = runtime.data.rogue_recruit.catalog[key]
        normal = {c["charId"] for c in candidates if c["type"] == "NORMAL" and not c["isUpgrade"]}
        expected = {cid for cid in owned_ids if rule.matches_definition(runtime.data.character(cid))}
        assert normal == expected
        upgrades = [c for c in candidates if c["isUpgrade"]]
        assert bool(upgrades) == rule.matches_definition(runtime.data.character("char_six"))
        assert [c["charId"] for c in candidates if c["type"] == "THIRD_LOW"] == ["char_reserve"]
        assert buy(client, token, "buy-again").status_code == 200
        assert post(client, token, "activeRecruitTicket", {"id": "3"}, "active-again").status_code == 200
        assert runtime.sync(token)["user"] == saved
        selected = next(c for c in candidates if c["charId"].startswith("char_variant_") and not c["isUpgrade"])
        before_recruit = runtime.sync(token)["user"]
        recruited = promote(client, token, selected["instId"], seq="ordinary")
        assert recruited.status_code == 200, recruited.text
        after_recruit = runtime.sync(token)["user"]
        assert apply(before_recruit, recruited.json()["playerDataDelta"]) == after_recruit
        assert recruited.json()["chars"][0]["charId"] == selected["charId"]
        assert promote(client, token, selected["instId"], seq="ordinary").json() == recruited.json()
        assert leave(client, token).status_code == 200
    assert dict(runtime.data.rogue_recruit.tickets) == original_pool
    final = runtime.sync(token)["user"]
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()
    backup = BackupService(runtime)
    name = backup.create()["name"]
    before = rows(runtime.database.path)
    backup.restore(name)
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("training_runtime,suffix,profession", [((p, 4), suffix, p) for suffix, p in (
    ("all", "PIONEER"), ("5star", "PIONEER"), ("double_1", "PIONEER"), ("double_2", "TANK"),
    ("double_3", "MEDIC"), ("double_4", "CASTER"), ("quad_melee", "SPECIAL"), ("quad_ranged", "SNIPER"))],
    indirect=["training_runtime"])
def test_all_variant_paid_promotions_have_one_history_and_restart(variants_runtime, suffix, profession):
    # Each independent authored fixture starts one matching four-star character.
    runtime, token = variants_runtime
    definition = runtime.data.character("char_six")
    if definition["profession"] != profession or definition["rarity"] != "TIER_4":
        pytest.fail("variant promotion fixture must use its declared profession/four-star")
    shop(runtime, token, ("SHOP",), "rogue_1_recruit_ticket_" + suffix)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        options = current(runtime, token)["inventory"]["recruit"]["3"]["list"]
        option = next(o for o in options if o["isUpgrade"])
        assert option["population"] == 1
        before = runtime.sync(token)["user"]
        reply = promote(client, token, option["instId"])
        assert reply.status_code == 200, reply.text
        final = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == final
        assert promote(client, token, option["instId"]).json() == reply.json()
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueRunChar).count() == 1
            assert len(session.query(m.RogueRunChar).one().training) == 1
        assert leave(client, token).status_code == 200
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == runtime.sync(token)["user"]
    finally:
        reopened.database.close()
