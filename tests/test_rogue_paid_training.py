"""Ordinary-ticket promotion, charging, history and old-save counterexamples."""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_rogue_training import choice, move, setup
from test_rogue_training import training_runtime as training_runtime  # noqa: F401
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_training
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_shops import prepare as save_shops
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def shop(runtime, token, kinds=("SHOP", "REST"), ticket=None):
    setup(runtime, token, kinds)
    if ticket is None:
        with runtime.database.transaction(write=False) as session:
            profession = runtime.data.character(session.query(m.Operator).filter_by(char_id="char_six").one().char_id)["profession"]
        ticket = next(k for k, value in runtime.data.rogue_recruit.tickets.items() if value[0] == profession)
    with runtime.database.transaction() as session:
        quote = compile_shop(runtime.data, "qa-paid-upgrade", (Offer("one", ticket, 0),),
                             evidence="Authored free QA purchase; not official stock or prices")
        save_shops(Context(session, runtime.data, 1), {Point(x, 0): quote for x, kind in enumerate(kinds) if kind == "SHOP"})


def buy(client, token, seq="buy"):
    return post(client, token, "shopAction", {"buy": ["one"], "recycle": [], "leave": 0}, seq)


def leave(client, token, seq="leave"):
    return post(client, token, "shopAction", {"buy": [], "recycle": [], "leave": 1}, seq)


def candidate(runtime, token, ticket="3"):
    return next(c for c in current(runtime, token)["inventory"]["recruit"][ticket]["list"] if c["isUpgrade"])


def promote(client, token, option, ticket="3", seq="promote"):
    return post(client, token, "recruitChar", {"ticketIndex": ticket, "optionId": str(option)}, seq)


@pytest.mark.parametrize("training_runtime", [("PIONEER", 4)], indirect=True)
def test_multiple_owned_upgrade_offers_charge_only_the_selected_option(training_runtime):
    runtime, token = training_runtime
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).acquire_operator("char_four")
    shop(runtime, token, ("SHOP", "REST", "SHOP"))
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        option = next(c for c in current(runtime, token)["inventory"]["recruit"]["3"]["list"]
                      if c["charId"] == "char_four" and not c["isUpgrade"])
        assert promote(client, token, option["instId"]).status_code == 200
        assert leave(client, token).status_code == 200
        assert move(client, token, 1, "rest").status_code == 200
        assert choice(client, token, "choice_rest_3", "hope").status_code == 200
        assert choice(client, token, "choice_leave", "rest-leave").status_code == 200
        assert move(client, token, 2, "next").status_code == 200
        assert buy(client, token, "buy-next").status_code == 200
        offers = [c for c in current(runtime, token)["inventory"]["recruit"]["4"]["list"] if c["isUpgrade"]]
        assert len(offers) == 2 and [c["population"] for c in offers] == [1, 1]
        target = next(c for c in offers if c["charId"] == "char_six")
        before = current(runtime, token)["player"]["property"]["population"]["cost"]
        response = promote(client, token, target["instId"], ticket="4", seq="one-target")
        assert response.status_code == 200, response.text
        assert current(runtime, token)["player"]["property"]["population"]["cost"] == before + 1
        with runtime.database.transaction(write=False) as session:
            assert sum(len(c.training) for c in session.query(m.RogueRunChar)) == 1


@pytest.mark.parametrize("training_runtime,cost", [(("PIONEER", 4), 1), (("PIONEER", 5), 2), (("PIONEER", 6), 3)], indirect=["training_runtime"])
def test_paid_costs_delta_insufficient_funds_then_charge_once_and_new_scene_prefix(training_runtime, cost):
    runtime, token = training_runtime
    shop(runtime, token)
    before = copy.deepcopy(current(runtime, token)["player"]["property"]["population"])
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert buy(client, token).status_code == 200
        c = candidate(runtime, token)
        assert (c["population"], c["troopInstId"], c["upgradePhase"], c["evolvePhase"]) == (cost, 1, 1, 2)
        # Initial hope is exhausted for six-star only. Other tiers have enough.
        if cost == 3:
            saved = rows(runtime.database.path)
            reply = promote(client, token, c["instId"], seq="no-hope")
            assert reply.status_code == 409 and reply.json()["error"]["code"] == "ROGUE_HOPE_REQUIRED"
            assert rows(runtime.database.path) == saved
            # Positive six-star charging uses REST provenance below.
            return
        old_user = runtime.sync(token)["user"]
        reply = promote(client, token, c["instId"])
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(old_user, reply.json()["playerDataDelta"]) == after
        assert reply.json()["chars"][0]["isFree"] == 0
        assert after["rlv2"]["current"]["player"]["property"]["population"]["cost"] == before["cost"] + cost
        assert promote(client, token, c["instId"]).json() == reply.json()
        assert leave(client, token).status_code == 200
        assert move(client, token, 1, "rest").status_code == 200
        assert choice(client, token, "choice_rest_3", "hope").status_code == 200
        assert choice(client, token, "choice_leave", "rest-leave").status_code == 200
    with runtime.database.transaction(write=False) as session:
        char = session.query(m.RogueRunChar).one()
        assert len(char.training) == 1 and char.training[0]["policy"] == rogue_training.PAID_POLICY
        assert char.training[0]["hope_cost"] == cost
        assert session.query(m.RogueSceneVisit).filter_by(state="FINISHED").one().recruit_count == 2
    final = runtime.sync(token)["user"]
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
        backup = BackupService(reopened)
        saved = rows(runtime.database.path)
        result = backup.create()
        backup.restore(result["name"])
        assert rows(runtime.database.path) == saved
    finally:
        reopened.database.close()


def prepare_funded(runtime, token, profession="PIONEER"):
    # Hope from REST is real domain provenance; no ad-hoc run resource write.
    setup(runtime, token, ("REST", "SHOP", "SHOP", "REST"))
    with runtime.database.transaction() as session:
        ticket = next(k for k, value in runtime.data.rogue_recruit.tickets.items() if value[0] == profession)
        quote = compile_shop(runtime.data, "qa-funded-upgrade", (Offer("one", ticket, 0),),
                             evidence="Authored QA shop; not official price or stock")
        save_shops(Context(session, runtime.data, 1), {Point(1, 0): quote, Point(2, 0): quote})
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert choice(client, token, "choice_rest_3", "hope").status_code == 200
        assert choice(client, token, "choice_leave", "rest-leave").status_code == 200
        assert move(client, token, 1, "shop").status_code == 200
        assert buy(client, token).status_code == 200


@pytest.mark.parametrize("training_runtime", [(p, 6) for p in ("PIONEER", "SNIPER", "SPECIAL", "TANK", "CASTER", "WARRIOR", "SUPPORT", "MEDIC")], indirect=True)
def test_all_eight_ordinary_professions_promote_and_disappear_from_next_ticket(training_runtime):
    runtime, token = training_runtime
    with runtime.database.transaction(write=False) as session:
        profession = runtime.data.character(session.query(m.Operator).filter_by(char_id="char_six").one().char_id)["profession"]
    prepare_funded(runtime, token, profession)
    with TestClient(create_game_app(runtime)) as client:
        c = candidate(runtime, token)
        assert c["population"] == 3
        assert promote(client, token, c["instId"]).status_code == 200
        assert current(runtime, token)["player"]["property"]["population"] == {"cost": 9, "max": 9}
        assert len(current(runtime, token)["troop"]["chars"]) == 1
        assert leave(client, token).status_code == 200
        assert move(client, token, 2, "shop2").status_code == 200
        assert buy(client, token, "buy2").status_code == 200
        assert all(not c["isUpgrade"] for c in current(runtime, token)["inventory"]["recruit"]["4"]["list"])
        assert post(client, token, "closeRecruitTicket", {"id": "4"}, "close").status_code == 200
        assert leave(client, token, "leave2").status_code == 200
    final = runtime.sync(token)["user"]
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()


def test_paid_rollback_and_concurrent_idempotency_keep_one_charge(training_runtime, monkeypatch):
    runtime, token = training_runtime
    prepare_funded(runtime, token)
    c = candidate(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        saved = rows(runtime.database.path)
        original = rogue_training.apply
        def fail(*args):
            original(*args)
            raise DomainError("QA_ROLLBACK", "Injected failure after paid training flush")
        monkeypatch.setattr(rogue_training, "apply", fail)
        assert promote(client, token, c["instId"], seq="fail").status_code == 400
        assert rows(runtime.database.path) == saved
        monkeypatch.setattr(rogue_training, "apply", original)
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: promote(client, token, c["instId"]), range(2)))
        assert replies[0].status_code == replies[1].status_code == 200
        assert replies[0].json() == replies[1].json()
        saved = rows(runtime.database.path)
        assert promote(client, token, c["instId"], seq="different-seq").status_code == 409
        assert rows(runtime.database.path) == saved
    assert current(runtime, token)["player"]["property"]["population"] == {"cost": 9, "max": 9}


@pytest.mark.parametrize("damage", ["record_cost", "option_cost", "policy", "total", "source"])
def test_paid_corruption_rejected_without_startup_writes(training_runtime, damage):
    runtime, token = training_runtime
    prepare_funded(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert promote(client, token, candidate(runtime, token)["instId"]).status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        if damage == "option_cost":
            con.execute("UPDATE rlv2_recruit_options SET hope_cost=2 WHERE kind='UPGRADE_PAID'")
        elif damage == "total":
            con.execute("UPDATE rlv2_runs SET hope_cost=6")
        elif damage == "source":
            con.execute("UPDATE rlv2_recruit_options SET source_operator_id=999999 WHERE kind='UPGRADE_PAID'")
        else:
            history = json.loads(con.execute("SELECT training FROM rlv2_chars").fetchone()[0])
            if damage == "record_cost":
                history[0]["hope_cost"] = 2
            else:
                history[0]["policy"] = rogue_training.POLICY
            con.execute("UPDATE rlv2_chars SET training=?", (json.dumps(history),))
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("choose_reserve", [False, True])
def test_cancel_or_choose_reserve_never_charges_promotion(training_runtime, choose_reserve):
    runtime, token = training_runtime
    prepare_funded(runtime, token)
    before = copy.deepcopy(current(runtime, token))
    with TestClient(create_game_app(runtime)) as client:
        if choose_reserve:
            c = next(c for c in before["inventory"]["recruit"]["3"]["list"] if c["type"] == "THIRD_LOW")
            reply = promote(client, token, c["instId"])
        else:
            reply = post(client, token, "closeRecruitTicket", {"id": "3"}, "close")
        assert reply.status_code == 200, reply.text
        assert leave(client, token).status_code == 200
        assert move(client, token, 2, "shop2").status_code == 200
        assert buy(client, token, "buy2").status_code == 200
        assert candidate(runtime, token, "4")["troopInstId"] == 1
    after = current(runtime, token)
    assert after["player"]["property"]["population"] == before["player"]["property"]["population"]
    assert after["troop"]["chars"]["1"] == before["troop"]["chars"]["1"]


def test_paid_snapshot_frozen_despite_later_owned_training(training_runtime):
    runtime, token = training_runtime
    prepare_funded(runtime, token)
    frozen = copy.deepcopy(candidate(runtime, token))
    with runtime.database.transaction() as session:
        op = session.query(m.Operator).filter_by(char_id="char_six").one()
        op.level = 2
        session.query(m.OperatorSkill).filter_by(operator_id=op.id, skill_id="s2").one().mastery = 0
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "activeRecruitTicket", {"id": "3"}, "repeat").status_code == 200
        assert candidate(runtime, token) == frozen
        assert promote(client, token, frozen["instId"]).status_code == 200
    char = current(runtime, token)["troop"]["chars"]["1"]
    assert char["level"] == 1 and char["skills"][2]["specializeLevel"] == 3


def test_paid_historical_battle_roster_unchanged_and_next_battle_promoted(training_runtime):
    from test_rogue_floor_progress import journal
    from test_rogue_settlement import complete
    from test_roguelike_battle_start import begin, body

    runtime, token = training_runtime
    setup(runtime, token, ("BATTLE_NORMAL", "REST", "SHOP", "BATTLE_NORMAL"))
    with runtime.database.transaction() as session:
        ticket = next(k for k, value in runtime.data.rogue_recruit.tickets.items() if value[0] == "PIONEER")
        quote = compile_shop(runtime.data, "qa-history-paid", (Offer("one", ticket, 0),), evidence="Authored QA quote")
        save_shops(Context(session, runtime.data, 1), {Point(2, 0): quote})
    payload = body()
    payload["squad"]["slots"] = [{"charInstId": 1, "skillIndex": 1, "currentEquip": None}]
    trace = journal()
    trace["journal"]["squad"] = trace["journal"]["squad"][:1]
    with TestClient(create_game_app(runtime)) as client:
        reply = begin(client, token, payload)
        assert reply.status_code == 200, reply.text
        old_id = reply.json()["battleId"]
        hp = current(runtime, token)["player"]["property"]["hp"]["current"]
        assert complete(client, token, old_id, trace, hp + runtime.data.rogue_initial.battle_temporary_hp).status_code == 200
        assert post(client, token, "finishBattleReward", {}, "reward-leave").status_code == 200
        with runtime.database.transaction(write=False) as session:
            old = session.get(m.RogueBattle, old_id)
            old_values = (copy.deepcopy(old.squad), old.request_hash, copy.deepcopy(old.roster_revisions))
        assert move(client, token, 1, "rest").status_code == 200
        assert choice(client, token, "choice_rest_3", "hope").status_code == 200
        assert choice(client, token, "choice_leave", "rest-leave").status_code == 200
        assert move(client, token, 2, "shop").status_code == 200
        assert buy(client, token).status_code == 200
        assert promote(client, token, candidate(runtime, token)["instId"]).status_code == 200
        assert leave(client, token).status_code == 200
        payload["to"]["x"], payload["squad"]["slots"][0]["skillIndex"] = 3, 2
        new = begin(client, token, payload, "new-battle")
        assert new.status_code == 200, new.text
        with runtime.database.transaction(write=False) as session:
            old = session.get(m.RogueBattle, old_id)
            promoted = session.get(m.RogueBattle, new.json()["battleId"])
            assert (old.squad, old.request_hash, old.roster_revisions) == old_values
            assert promoted.roster_revisions == {"1": 1} and promoted.squad[0]["character"]["evolvePhase"] == 2
    final = runtime.sync(token)["user"]
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()
