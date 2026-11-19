"""Authored FREE transactions and immutable history; no native assertions."""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import test_rogue_training as training_fixture
from fastapi.testclient import TestClient
from test_rogue_paid_training import buy, leave, promote
from test_rogue_special_recruit import source as special_source
from test_rogue_training import choice, move, setup
from test_rogue_training import training_runtime as training_runtime  # noqa: F401
from test_roguelike_initial import current, post
from test_roguelike_recruit import recruit_tables
from test_roguelike_state import rows

from terralocal.server.domain import rogue_recruit
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_battle import formation
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_shops import prepare as save_shops
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.gamedata.rogue_special_recruit import FREE_TICKET_IDS
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def temporary_tables():
    tables = recruit_tables()
    source, chars = special_source()
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    source_detail = source["details"]["rogue_1"]
    detail["items"].update(source_detail["items"])
    detail["items"]["gold"]["id"] = "gold"
    detail["recruitTickets"].update(source_detail["recruitTickets"])
    for ticket in source_detail["recruitTickets"].values():
        ticket["extraCharIds"] = ["char_reserve"]
    predefined = tables["roguelike_topic_table"]["constant"]["predefinedChars"]
    predefined["char_reserve"].update(canBeFree=False, uniEquipId=None)
    for key, value in source["constant"]["predefinedChars"].items():
        if key == "reserve":
            continue
        cid = "char_temp_" + key
        char = copy.deepcopy(tables["character_table"]["char_four"])
        char.update(chars[key])
        char["phases"] = copy.deepcopy(tables["character_table"]["char_four"]["phases"])
        tables["character_table"][cid] = char
        predefined[cid] = value | {"charId": cid}
        voice = tables["charword_table"]
        voice["voiceLangDict"][cid] = copy.deepcopy(voice["voiceLangDict"]["char_four"])
        voice["charDefaultTypeDict"][cid] = "JP"
    return tables


@pytest.fixture
def install_temporary(monkeypatch):
    monkeypatch.setattr(training_fixture, "recruit_tables", temporary_tables)


@pytest.fixture
def temporary_runtime(install_temporary, training_runtime):
    return training_runtime


def prepare(runtime, token, ticket, *, extended=False, upgrade_ticket=False):
    setup(runtime, token, ("SHOP", "REST", "SHOP") if extended else ("SHOP",))
    with runtime.database.transaction() as session:
        first = compile_shop(runtime.data, "qa-temporary", (Offer("one", ticket, 0),), evidence="QA guaranteed temporary quote")
        quotes = {Point(0, 0): first}
        if extended:
            profession = next(iter(runtime.data.rogue_special_recruit.tickets[ticket].professions))
            later = "rogue_1_upgrade_ticket_all" if upgrade_ticket else "ticket_" + profession.lower()
            quotes[Point(2, 0)] = compile_shop(runtime.data, "qa-later", (Offer("one", later, 0),), evidence="QA promotion quote")
        save_shops(Context(session, runtime.data, 1), quotes)


@pytest.mark.parametrize("ticket", sorted(FREE_TICKET_IDS))
def test_every_guaranteed_ticket_exposes_one_matching_frozen_offer_and_can_cancel(temporary_runtime, ticket):
    runtime, token = temporary_runtime
    prepare(runtime, token, ticket)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        old = runtime.sync(token)["user"]
        reply = buy(client, token)
        assert reply.status_code == 200, reply.text
        saved = runtime.sync(token)["user"]
        assert apply(old, reply.json()["playerDataDelta"]) == saved
        offers = current(runtime, token)["inventory"]["recruit"]["3"]["list"]
        free = [o for o in offers if o["type"] == "FREE"]
        assert len(free) == 1
        value = free[0]
        spec = runtime.data.rogue_special_recruit.tickets[ticket]
        candidate = runtime.data.rogue_special_recruit.candidates[value["charId"]]
        assert candidate.profession in spec.professions and candidate.rarity in spec.free_rarities
        assert (value["population"], value["potentialRank"], value["evolvePhase"], value["mainSkillLvl"]) == (0, 5, 1, 7)
        assert buy(client, token, "new-sequence").status_code == 200
        assert post(client, token, "activeRecruitTicket", {"id": "3"}, "active-again").status_code == 200
        assert runtime.sync(token)["user"] == saved
        assert post(client, token, "closeRecruitTicket", {"id": "3"}, "cancel").status_code == 200
        assert leave(client, token).status_code == 200


@pytest.mark.parametrize("suffix,cost,upgrade_ticket", [("sp", 1, False), ("red", 3, False), ("sp", 0, True)])
def test_unowned_temporary_recruit_promotion_delta_replay_and_restore(temporary_runtime, suffix, cost, upgrade_ticket):
    runtime, token = temporary_runtime
    prepare(runtime, token, "rogue_1_recruit_ticket_pioneer_" + suffix, extended=True, upgrade_ticket=upgrade_ticket)
    main = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        free = next(o for o in current(runtime, token)["inventory"]["recruit"]["3"]["list"] if o["type"] == "FREE")
        before = runtime.sync(token)["user"]
        reply = promote(client, token, free["instId"], seq="temporary")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        assert reply.json()["chars"][0]["isFree"] == 1
        assert promote(client, token, free["instId"], seq="temporary").json() == reply.json()
        assert len(current(runtime, token)["troop"]["chars"]) == 2
        assert leave(client, token).status_code == 200
        assert move(client, token, 1, "rest").status_code == 200
        assert choice(client, token, "choice_rest_3", "hope").status_code == 200
        assert choice(client, token, "choice_leave", "rest-leave").status_code == 200
        assert move(client, token, 2, "later").status_code == 200
        assert buy(client, token, "buy-later").status_code == 200
        offer = next(o for o in current(runtime, token)["inventory"]["recruit"]["4"]["list"] if o["isUpgrade"] and o["type"] == "FREE")
        assert offer["population"] == cost and offer["troopInstId"] == 2
        before = runtime.sync(token)["user"]
        promoted = promote(client, token, offer["instId"], ticket="4", seq="temporary-promotion")
        assert promoted.status_code == 200, promoted.text
        after = runtime.sync(token)["user"]
        assert apply(before, promoted.json()["playerDataDelta"]) == after
        result = promoted.json()["chars"][0]
        assert (result["type"], result["evolvePhase"], result["upgradePhase"]) == ("FREE", 2, 1)
        assert all(s["specializeLevel"] == 3 for s in result["skills"] if s["unlock"])
        assert len(current(runtime, token)["troop"]["chars"]) == 2
        assert leave(client, token, "later-leave").status_code == 200
    final = runtime.sync(token)["user"]
    assert {k:v for k,v in main.items() if k != "rlv2"} == {k:v for k,v in final.items() if k != "rlv2"}
    with runtime.database.transaction(write=False) as session:
        assert not session.query(m.Operator).filter_by(account_id=1, char_id=free["charId"]).count()
        assert len(session.query(m.RogueRunChar).filter_by(ordinal=2).one().training) == 1
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


@pytest.mark.parametrize("field,value", [("potentialRank", 1), ("favorPoint", 0), ("evolvePhase", 0),
    ("level", 1), ("exp", 1), ("voiceLan", "GER"), ("gainTime", 1), ("skin", "other"), ("starMark", 1)])
def test_corrupt_free_template_is_rejected_before_runtime_writes(temporary_runtime, field, value):
    runtime, token = temporary_runtime
    prepare(runtime, token, "rogue_1_recruit_ticket_pioneer_sp")
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        row = con.execute("SELECT run_id,ticket_ordinal,ordinal,character FROM rlv2_recruit_options WHERE kind='FREE'").fetchone()
        char = json.loads(row[3])
        char[field] = value
        con.execute("UPDATE rlv2_recruit_options SET character=? WHERE run_id=? AND ticket_ordinal=? AND ordinal=?",
                    (json.dumps(char), *row[:3]))
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before


def test_free_sql_constraints_and_recruit_failure_leave_every_table_unchanged(temporary_runtime, monkeypatch):
    runtime, token = temporary_runtime
    prepare(runtime, token, "rogue_1_recruit_ticket_pioneer_sp")
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        value = next(o for o in current(runtime, token)["inventory"]["recruit"]["3"]["list"] if o["type"] == "FREE")
        before = rows(runtime.database.path)
        for update in ("hope_cost=1", "source_operator_id=1"):
            with sqlite3.connect(runtime.database.path) as con, pytest.raises(sqlite3.IntegrityError):
                con.execute("UPDATE rlv2_recruit_options SET " + update + " WHERE kind='FREE'")
        assert rows(runtime.database.path) == before
        original = rogue_recruit.recruit

        def fail(*args):
            original(*args)
            raise ValueError("Authored failure after FREE record flush")

        with monkeypatch.context() as patch:
            patch.setattr(rogue_recruit, "recruit", fail)
            with pytest.raises(ValueError, match="after FREE"):
                promote(client, token, value["instId"])
        assert rows(runtime.database.path) == before
        assert promote(client, token, value["instId"]).status_code == 200


def test_concurrent_free_selection_creates_one_independent_run_character(temporary_runtime):
    runtime, token = temporary_runtime
    prepare(runtime, token, "rogue_1_recruit_ticket_pioneer_sp")
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        value = next(o for o in current(runtime, token)["inventory"]["recruit"]["3"]["list"] if o["type"] == "FREE")
    second = Runtime(runtime.settings)
    try:
        def select(pair):
            r, seq = pair
            with TestClient(create_game_app(r)) as client:
                return promote(client, token, value["instId"], seq=seq).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(select, ((runtime, "one"), (second, "two")))) == [200, 409]
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueRunChar).count() == 2
            assert not session.query(m.Operator).filter_by(account_id=1, char_id=value["charId"]).count()
    finally:
        second.database.close()


def test_free_formation_uses_independent_historical_training_without_main_operator(temporary_runtime):
    from terralocal.server.domain.rogue_temporary import character
    from terralocal.server.domain.rogue_training import Troop

    runtime, _ = temporary_runtime
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        cid = "char_temp_pioneer4"
        assert not session.query(m.Operator).filter_by(account_id=1, char_id=cid).count()
        initial = character(ctx, cid, 0, gained_at=ctx.now)
        upgraded = character(ctx, cid, 0, upgraded=True, original=initial)
        option = SimpleNamespace(character=initial, kind="FREE")
        base = rogue_recruit.recruited_character(option, 1)
        troop = Troop({"1": base}, [SimpleNamespace(ordinal=1, training=[{"source": upgraded, "at": ctx.now}])])
        run = SimpleNamespace(squad_capacity=6)
        old = troop.at({}, ctx.now)
        assert old["1"] == base and old["1"]["type"] == "FREE"
        with pytest.raises(DomainError, match="所选技能"):
            formation(run, old, [{"charInstId": 1, "skillIndex": 2}])
        revisions = troop.revisions([{"charInstId": 1}])
        assert revisions == {"1": 1}
        saved = formation(run, troop.at(revisions, ctx.now), [{"charInstId": 1, "skillIndex": 2}])
        assert saved[0]["character"]["type"] == "FREE"
        assert saved[0]["character"]["skills"][2]["specializeLevel"] == 3
        assert troop.at({}, ctx.now) == old
