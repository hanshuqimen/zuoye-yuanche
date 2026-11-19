"""Explicit direct-upgrade outcomes; no inferred natural draw distribution."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

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
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_battle import formation
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_shops import prepare as save_shops
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

ALL = "rogue_1_recruit_ticket_all_discount"
MELEE = "rogue_1_recruit_ticket_quad_melee_discount"
RANGED = "rogue_1_recruit_ticket_quad_ranged_discount"


def prepare(runtime, token, ticket=ALL, char_id="char_four", *, phase=2, own=True):
    if own:
        with runtime.database.transaction() as session:
            ctx = Context(session, runtime.data, 1)
            op, _ = ctx.acquire_operator(char_id)
            op.evolve_phase, op.level, op.skill_level, op.default_skill = phase, 1, 7, 0
            session.query(m.OperatorSkill).filter_by(operator_id=op.id, skill_id="s2").one().mastery = 3
    setup(runtime, token, ("REST", "SHOP", "SHOP"))
    with runtime.database.transaction() as session:
        first = compile_shop(runtime.data, "qa-direct-outcome", (Offer("one", ticket, 1, direct_pool=(char_id,)),),
                             evidence="Reviewed direct outcome, not a natural probability or count")
        later = compile_shop(runtime.data, "qa-later-upgrade", (Offer("one", "rogue_1_upgrade_ticket_all", 0),),
                             evidence="QA eligibility after direct recruitment")
        save_shops(Context(session, runtime.data, 1), {Point(1, 0): first, Point(2, 0): later})


def enter(client, token):
    assert move(client, token).status_code == 200
    assert choice(client, token, "choice_rest_3", "hope").status_code == 200
    assert choice(client, token, "choice_leave", "rest-leave").status_code == 200
    assert move(client, token, 1, "shop").status_code == 200


@pytest.mark.parametrize("ticket,char_id", [(ALL, "char_four"), (MELEE, "char_four"), (RANGED, "char_temp_sniper4")])
@pytest.mark.parametrize("phase", [0, 2])
def test_three_ticket_families_freeze_direct_ceiling_charge_base_cost_and_restore(temporary_runtime, ticket, char_id, phase):
    runtime, token = temporary_runtime
    prepare(runtime, token, ticket, char_id, phase=phase)
    main = runtime.sync(token)["user"]["troop"]
    with TestClient(create_game_app(runtime)) as client:
        enter(client, token)
        before = runtime.sync(token)["user"]
        response = buy(client, token)
        assert response.status_code == 200, response.text
        saved = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == saved
        candidates = current(runtime, token)["inventory"]["recruit"]["3"]["list"]
        selected = next(c for c in candidates if c["charId"] == char_id)
        assert (selected["type"], selected["isUpgrade"], selected["upgradePhase"], selected["population"]) == ("NORMAL", False, 1, 2)
        assert selected["evolvePhase"] == phase and selected["level"] == 1
        assert selected["skills"][2]["specializeLevel"] == (3 if phase == 2 else 0)
        assert any(c["upgradePhase"] == 0 for c in candidates)  # No all-candidates direct fallback.
        assert post(client, token, "activeRecruitTicket", {"id": "3"}, "freeze-again").status_code == 200
        assert runtime.sync(token)["user"] == saved
        before = saved
        response = promote(client, token, selected["instId"])
        assert response.status_code == 200, response.text
        final = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == final
        assert promote(client, token, selected["instId"]).json() == response.json()
        member = current(runtime, token)["troop"]["chars"]["2"]
        assert member["upgradePhase"] == 1 and member["type"] == "NORMAL" and member["charId"] == char_id
        assert current(runtime, token)["player"]["property"]["population"] == {"cost": 8, "max": 9}
        assert runtime.sync(token)["user"]["troop"] == main
        assert leave(client, token).status_code == 200
        assert move(client, token, 2, "later").status_code == 200
        assert buy(client, token, "later-buy").status_code == 200
        assert not any(c["charId"] == char_id for c in current(runtime, token)["inventory"]["recruit"]["4"]["list"])
        assert post(client, token, "closeRecruitTicket", {"id": "4"}, "dismiss").status_code == 200
    expected = runtime.sync(token)["user"]
    with runtime.database.transaction(write=False) as session:
        run = session.query(m.RogueTopicRun).filter_by(account_id=1).one()
        assert session.query(m.RogueRunChar).filter_by(run_id=run.id, ordinal=2).one().training == []
        slot = {"charInstId": 2, "skillIndex": 0, "currentEquip": None}
        assert formation(run, expected["rlv2"]["current"]["troop"]["chars"], [slot])[0]["character"]["upgradePhase"] == 1
    service = BackupService(runtime)
    backup = service.create()
    saved_rows = rows(runtime.database.path)
    service.restore(backup["name"])
    assert rows(runtime.database.path) == saved_rows
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == expected
    finally:
        reopened.database.close()


@pytest.mark.parametrize("ticket,scope", [(ALL, ()), (ALL, ["char_four"]), (ALL, ("char_four", "char_four")),
    (ALL, ("char_zero",)), (MELEE, ("char_sniper",)), (RANGED, ("char_four",)),
    (ALL, ("char_reserve",)), (ALL, ("missing",)), ("ticket_pioneer", ("char_four",))])
def test_unsupported_or_mismatched_direct_outcomes_cannot_compile(temporary_runtime, ticket, scope):
    runtime, _ = temporary_runtime
    with pytest.raises(ValueError):
        compile_shop(runtime.data, "qa-invalid", (Offer("one", ticket, 0, direct_pool=scope),), evidence="Rejected")


def test_unowned_direct_outcome_rolls_back_purchase_stock_and_gold(temporary_runtime):
    runtime, token = temporary_runtime
    prepare(runtime, token, own=False)
    with TestClient(create_game_app(runtime)) as client:
        enter(client, token)
        before = rows(runtime.database.path)
        response = buy(client, token)
        assert response.status_code == 409 and response.json()["error"]["code"] == "ROGUE_NO_DIRECT_CANDIDATES"
        assert rows(runtime.database.path) == before


@pytest.mark.parametrize("damage", ["scope", "quote", "kind", "source", "template"])
def test_direct_history_corruption_fails_before_runtime_writes(temporary_runtime, damage):
    runtime, token = temporary_runtime
    prepare(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        enter(client, token)
        assert buy(client, token).status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        if damage == "scope":
            con.execute("UPDATE rlv2_tickets SET direct_pool='[]' WHERE ordinal=3")
        elif damage == "quote":
            key, raw = con.execute("SELECT id,quote FROM rlv2_shop_visits WHERE state='ACTIVE'").fetchone()
            value = json.loads(raw)
            value["offers"][0]["direct_pool"] = ["char_five"]
            con.execute("UPDATE rlv2_shop_visits SET quote=? WHERE id=?", (json.dumps(value), key))
        elif damage == "kind":
            con.execute("UPDATE rlv2_recruit_options SET kind='NORMAL' WHERE kind='DIRECT'")
        elif damage == "source":
            con.execute("PRAGMA ignore_check_constraints=ON")
            con.execute("UPDATE rlv2_recruit_options SET source_operator_id=NULL WHERE kind='DIRECT'")
        else:
            ordinal, raw = con.execute("SELECT ordinal,character FROM rlv2_recruit_options WHERE kind='DIRECT'").fetchone()
            value = json.loads(raw)
            value["level"] = 999
            con.execute("UPDATE rlv2_recruit_options SET character=? WHERE ticket_ordinal=3 AND ordinal=?", (json.dumps(value), ordinal))
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before


def test_direct_offer_does_not_follow_later_permanent_training_and_can_dismiss(temporary_runtime):
    runtime, token = temporary_runtime
    prepare(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        enter(client, token)
        assert buy(client, token).status_code == 200
        expected = current(runtime, token)
        with runtime.database.transaction() as session:
            op = session.query(m.Operator).filter_by(account_id=1, char_id="char_four").one()
            op.evolve_phase, op.level, op.skill_level = 0, 1, 1
        assert current(runtime, token) == expected
        assert post(client, token, "closeRecruitTicket", {"id": "3"}, "dismiss-direct").status_code == 200
        assert len(current(runtime, token)["troop"]["chars"]) == 1


def test_direct_recruit_atomic_failure_and_two_concurrent_sequences_grant_once(temporary_runtime, monkeypatch):
    runtime, token = temporary_runtime
    prepare(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        enter(client, token)
        assert buy(client, token).status_code == 200
    offered = current(runtime, token)["inventory"]["recruit"]["3"]["list"]
    option = next(c for c in offered if c["charId"] == "char_four")
    before = rows(runtime.database.path)
    original = rogue_recruit.recruited_character

    def fail(*args, **kwargs):
        raise RuntimeError("Authored failure after direct flush")

    monkeypatch.setattr(rogue_recruit, "recruited_character", fail)
    with pytest.raises(RuntimeError, match="after direct flush"):
        with runtime.database.transaction() as session:
            rogue_recruit.recruit(Context(session, runtime.data, 1), "3", str(option["instId"]))
    assert rows(runtime.database.path) == before
    monkeypatch.setattr(rogue_recruit, "recruited_character", original)

    def recruit_once(_):
        try:
            with runtime.database.transaction() as session:
                rogue_recruit.recruit(Context(session, runtime.data, 1), "3", str(option["instId"]))
            return "granted"
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(recruit_once, range(2)))
    assert sorted(results) == ["ROGUE_TICKET_STATE", "granted"]
    assert len(current(runtime, token)["troop"]["chars"]) == 2
    assert current(runtime, token)["player"]["property"]["population"] == {"cost": 8, "max": 9}


@pytest.mark.parametrize("source", ["other_account", "missing", "wrong_character"])
def test_direct_source_ownership_is_checked_live_and_before_restart_writes(temporary_runtime, source):
    runtime, token = temporary_runtime
    prepare(runtime, token)
    with runtime.database.transaction() as session:
        foreign, _ = Context(session, runtime.data, 2).acquire_operator("char_four")
        own_wrong = session.query(m.Operator).filter_by(account_id=1, char_id="char_six").one()
        source_id = foreign.id if source == "other_account" else own_wrong.id if source == "wrong_character" else 999999
    with TestClient(create_game_app(runtime)) as client:
        enter(client, token)
        assert buy(client, token).status_code == 200
        with sqlite3.connect(runtime.database.path) as con:
            con.execute("UPDATE rlv2_recruit_options SET source_operator_id=? WHERE kind='DIRECT'", (source_id,))
        before = rows(runtime.database.path)
        response = post(client, token, "activeRecruitTicket", {"id": "3"}, "invalid-source")
        assert response.status_code == 503 and response.json()["error"]["code"] == "ROGUE_RUN_INCOMPATIBLE"
        assert rows(runtime.database.path) == before
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest
