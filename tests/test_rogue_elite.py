"""Scoped elite supply, independent recruitment and training; no official pool claim."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_rogue_paid_training import buy, leave, promote
from test_rogue_temporary import install_temporary as install_temporary  # noqa: F401
from test_rogue_temporary import temporary_runtime as temporary_runtime  # noqa: F401
from test_rogue_training import choice, move, setup
from test_rogue_training import training_runtime as training_runtime  # noqa: F401
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_recruit
from terralocal.server.domain.context import Context
from terralocal.server.domain.rogue_battle import formation
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_shops import prepare as save_shops
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.gamedata.rogue_special_recruit import ELITE_TICKET_ID
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

ELITE = "char_temp_elite"


def prepare(runtime, token, *, extended=False, free_upgrade=False, repeat=False):
    setup(runtime, token, ("SHOP", "REST", "SHOP") if extended else ("SHOP", "SHOP") if repeat else ("SHOP",))
    with runtime.database.transaction() as session:
        quote = compile_shop(runtime.data, "qa-explicit-elite", (Offer("one", ELITE_TICKET_ID, 1, (ELITE,)),),
                             evidence="Reviewed QA range only; no automatic topic/global elite pool")
        bindings = {Point(0, 0): quote}
        if extended:
            later = "rogue_1_upgrade_ticket_all" if free_upgrade else "ticket_warrior"
            bindings[Point(2, 0)] = compile_shop(runtime.data, "qa-elite-promotion", (Offer("one", later, 0),),
                                                evidence="QA ordinary or free promotion")
        if repeat:
            bindings[Point(1, 0)] = quote
        save_shops(Context(session, runtime.data, 1), bindings)


def candidate(runtime, token, ticket="3"):
    return next(c for c in current(runtime, token)["inventory"]["recruit"][ticket]["list"] if c["type"] == "THIRD")


@pytest.mark.parametrize("scope", [(), [ELITE], (ELITE, ELITE), ("char_temp_pioneer4",), ("missing",)])
def test_unscoped_duplicate_free_or_unknown_elite_supplies_are_rejected(temporary_runtime, scope):
    runtime, _ = temporary_runtime
    before = rows(runtime.database.path)
    with pytest.raises(ValueError):
        compile_shop(runtime.data, "qa", (Offer("one", ELITE_TICKET_ID, 0, scope),), evidence="Rejected scope")
    assert rows(runtime.database.path) == before


def test_elite_supply_cannot_be_attached_to_an_ordinary_ticket(temporary_runtime):
    runtime, _ = temporary_runtime
    with pytest.raises(ValueError):
        compile_shop(runtime.data, "qa", (Offer("one", "ticket_pioneer", 0, (ELITE,)),), evidence="Wrong effect")


def test_frozen_elite_offer_has_zero_hope_cost_and_can_be_dismissed_without_grant(temporary_runtime):
    runtime, token = temporary_runtime
    prepare(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        before = runtime.sync(token)["user"]
        bought = buy(client, token)
        assert bought.status_code == 200, bought.text
        saved = runtime.sync(token)["user"]
        assert apply(before, bought.json()["playerDataDelta"]) == saved
        elite = candidate(runtime, token)
        assert elite["charId"] == ELITE and elite["population"] == 0
        assert (elite["evolvePhase"], elite["upgradePhase"], elite["mainSkillLvl"], elite["potentialRank"]) == (1, 0, 7, 5)
        assert buy(client, token, "new-buy-sequence").status_code == 200
        assert post(client, token, "activeRecruitTicket", {"id": "3"}, "no-reroll").status_code == 200
        assert runtime.sync(token)["user"] == saved
        assert post(client, token, "closeRecruitTicket", {"id": "3"}, "dismiss-elite").status_code == 200
        assert leave(client, token).status_code == 200
        assert len(current(runtime, token)["troop"]["chars"]) == 1


@pytest.mark.parametrize("free_upgrade", [False, True])
def test_unowned_unobtainable_elite_recruit_and_promotion_preserve_kind_history_and_save(temporary_runtime, free_upgrade):
    runtime, token = temporary_runtime
    prepare(runtime, token, extended=True, free_upgrade=free_upgrade)
    main = runtime.sync(token)["user"]
    assert runtime.data.character(ELITE)["isNotObtainable"] is True
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        elite = candidate(runtime, token)
        before = runtime.sync(token)["user"]
        reply = promote(client, token, elite["instId"], seq="elite")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        assert (reply.json()["chars"][0]["isElite"], reply.json()["chars"][0]["isFree"]) == (1, 1)
        assert promote(client, token, elite["instId"], seq="elite").json() == reply.json()
        assert leave(client, token).status_code == 200
        assert move(client, token, 1, "rest").status_code == 200
        assert choice(client, token, "choice_rest_3", "hope").status_code == 200
        assert choice(client, token, "choice_leave", "rest-leave").status_code == 200
        assert move(client, token, 2, "later").status_code == 200
        assert buy(client, token, "buy-later").status_code == 200
        upgrade = candidate(runtime, token, "4")
        assert upgrade["troopInstId"] == 2 and upgrade["isUpgrade"]
        assert upgrade["population"] == (0 if free_upgrade else 2)
        before = runtime.sync(token)["user"]
        reply = promote(client, token, upgrade["instId"], ticket="4", seq="elite-upgrade")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        result = reply.json()["chars"][0]
        assert (result["type"], result["upgradePhase"], result["evolvePhase"]) == ("THIRD", 1, 2)
        assert all(s["specializeLevel"] == 3 for s in result["skills"] if s["unlock"])
        assert len(current(runtime, token)["troop"]["chars"]) == 2
        assert leave(client, token, "later-leave").status_code == 200
    final = runtime.sync(token)["user"]
    assert {k:v for k,v in main.items() if k != "rlv2"} == {k:v for k,v in final.items() if k != "rlv2"}
    with runtime.database.transaction(write=False) as session:
        assert not session.query(m.Operator).filter_by(account_id=1, char_id=ELITE).count()
        record = session.query(m.RogueRunChar).filter_by(ordinal=2).one().training[0]
        assert record.get("hope_cost", 0) == (0 if free_upgrade else 2)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()
    backups = BackupService(runtime)
    backup = backups.create()
    saved = rows(runtime.database.path)
    backups.restore(backup["name"])
    assert rows(runtime.database.path) == saved


def test_exhausted_explicit_elite_scope_rolls_back_purchase_and_never_repeats_a_member(temporary_runtime):
    runtime, token = temporary_runtime
    prepare(runtime, token, repeat=True)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        assert promote(client, token, candidate(runtime, token)["instId"]).status_code == 200
        assert leave(client, token).status_code == 200
        assert move(client, token, 1, "second-shop").status_code == 200
        before = rows(runtime.database.path)
        response = buy(client, token, "exhausted")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ROGUE_NO_TEMPORARY_CANDIDATES"
        assert rows(runtime.database.path) == before


@pytest.mark.parametrize("damage", ["ticket_scope", "quote_scope", "template", "kind"])
def test_tampered_scope_or_elite_template_is_rejected_before_runtime_writes(temporary_runtime, damage):
    runtime, token = temporary_runtime
    prepare(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        if damage == "ticket_scope":
            con.execute("UPDATE rlv2_tickets SET elite_pool='[]' WHERE ordinal=3")
        elif damage == "quote_scope":
            row = con.execute("SELECT id,quote FROM rlv2_shop_visits").fetchone()
            value = json.loads(row[1])
            value["offers"][0]["elite_pool"] = ["char_temp_pioneer4"]
            con.execute("UPDATE rlv2_shop_visits SET quote=? WHERE id=?", (json.dumps(value), row[0]))
        elif damage == "kind":
            con.execute("UPDATE rlv2_recruit_options SET kind='THIRD_LOW' WHERE kind='THIRD'")
        else:
            row = con.execute("SELECT ordinal,character FROM rlv2_recruit_options WHERE kind='THIRD'").fetchone()
            value = json.loads(row[1])
            value["level"] = 1
            con.execute("UPDATE rlv2_recruit_options SET character=? WHERE ticket_ordinal=3 AND ordinal=?", (json.dumps(value), row[0]))
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before


def test_elite_sql_and_failed_recruit_are_atomic(temporary_runtime, monkeypatch):
    runtime, token = temporary_runtime
    prepare(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        elite = candidate(runtime, token)
        before = rows(runtime.database.path)
        for sql in ("hope_cost=1", "source_operator_id=1"):
            with sqlite3.connect(runtime.database.path) as con, pytest.raises(sqlite3.IntegrityError):
                con.execute("UPDATE rlv2_recruit_options SET "+sql+" WHERE kind='THIRD'")
        assert rows(runtime.database.path) == before
        original = rogue_recruit.recruit

        def fail(*args):
            original(*args)
            raise ValueError("Authored failure after elite recruit flush")

        with monkeypatch.context() as patch:
            patch.setattr(rogue_recruit, "recruit", fail)
            with pytest.raises(ValueError, match="after elite"):
                promote(client, token, elite["instId"])
        assert rows(runtime.database.path) == before


def test_concurrent_elite_recruit_is_single_grant(temporary_runtime):
    runtime, token = temporary_runtime
    prepare(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        elite = candidate(runtime, token)
    second = Runtime(runtime.settings)
    try:
        def select(pair):
            r, seq = pair
            with TestClient(create_game_app(r)) as client:
                return promote(client, token, elite["instId"], seq=seq).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(select, ((runtime, "one"), (second, "two")))) == [200, 409]
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueRunChar).count() == 2
    finally:
        second.database.close()


def test_elite_formation_uses_its_frozen_independent_training(temporary_runtime):
    from terralocal.server.domain.rogue_temporary import character
    from terralocal.server.domain.rogue_training import Troop

    runtime, _ = temporary_runtime
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        initial = character(ctx, ELITE, 0, gained_at=ctx.now)
        upgraded = character(ctx, ELITE, 0, upgraded=True, original=initial)
        base = rogue_recruit.recruited_character(SimpleNamespace(character=initial, kind="THIRD"), 1)
        troop = Troop({"1": base}, [SimpleNamespace(ordinal=1, training=[{"source":upgraded,"at":ctx.now}])])
        slots = [{"charInstId":1,"skillIndex":0,"currentEquip":None}]
        run = SimpleNamespace(squad_capacity=6)
        assert formation(run, troop.at({}, ctx.now), slots)[0]["character"]["evolvePhase"] == 1
        assert formation(run, troop.at({"1":1}, ctx.now), slots)[0]["character"]["evolvePhase"] == 2
