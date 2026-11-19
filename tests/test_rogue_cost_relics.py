"""Explicit no-stack stock, real transactions, synthetic tables; no native win."""

import copy
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_rogue_training as training_fixture
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_ending import ending_runtime as ending_runtime
from test_rogue_recruit_costs import R25, R26, R27, R28, source
from test_rogue_shop_ending import shop_ending_runtime as shop_ending_runtime
from test_rogue_temporary import temporary_tables
from test_rogue_training import choice, move, setup
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_shops import prepare
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def add_costs(tables):
    detail = tables["roguelike_topic_table"]["details"]["rogue_1"]
    for key, values in source()["details"]["rogue_1"].items():
        detail.setdefault(key, {}).update(values)
    char = copy.deepcopy(tables["character_table"]["char_six"])
    char["name"] = "Synthetic later six-star"
    tables["character_table"]["char_six_later"] = char
    for key in ("voiceLangDict", "charDefaultTypeDict"):
        values = tables["charword_table"][key]
        if "char_six" in values:
            values["char_six_later"] = copy.deepcopy(values["char_six"])
    return tables


@pytest.fixture
def cost_tables(monkeypatch):
    monkeypatch.setattr(training_fixture, "recruit_tables", lambda: add_costs(temporary_tables()))
    original = start_fixture.recruit_tables
    monkeypatch.setattr(start_fixture, "recruit_tables", lambda: add_costs(original()))


@pytest.fixture
def cost_runtime(cost_tables, training_runtime):
    runtime, token = training_runtime
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        for char in ("char_four", "char_five", "char_six_later"):
            ctx.acquire_operator(char)
    return runtime, token


def configure(runtime, token, relic=R25, *, ticket="ticket_pioneer", direct_pool=()):
    setup(runtime, token, ("REST", "REST", "SHOP", "SHOP"))
    second = R26 if relic == R28 else R28
    with runtime.database.transaction() as session:
        first = compile_shop(runtime.data, "qa-cost-relic", (
            Offer("relic", relic, 1, relic_layer=0), Offer("ticket", ticket, 0, direct_pool=direct_pool)),
            evidence="Authored unique no-stack layer0 stock, not official prices, unlocks or natural supply")
        later = compile_shop(runtime.data, "qa-later-cost", (
            Offer("relic", second, 1, relic_layer=0), Offer("ticket", "ticket_pioneer", 0)),
            evidence="Authored later effect for immutable historical fee check")
        prepare(Context(session, runtime.data, 1), {Point(2, 0): first, Point(3, 0): later})
    with TestClient(create_game_app(runtime)) as client:
        for x in (0, 1):
            assert move(client, token, x, "rest-" + str(x)).status_code == 200
            assert choice(client, token, "choice_rest_3", "hope-" + str(x)).status_code == 200
            assert choice(client, token, "choice_leave", "rest-leave-" + str(x)).status_code == 200
        assert move(client, token, 2, "shop").status_code == 200


def buy(client, token, slot, key):
    return post(client, token, "shopAction", {"buy": [slot], "recycle": [], "leave": 0}, key)


def leave(client, token, key="leave"):
    return post(client, token, "shopAction", {"buy": [], "recycle": [], "leave": 1}, key)


def saved_options(runtime, index):
    with runtime.database.transaction(write=False) as session:
        return [(o.ordinal, o.kind, o.hope_cost, copy.deepcopy(o.character)) for o in session.query(
            m.RogueRecruitOption).filter_by(ticket_ordinal=index).order_by(m.RogueRecruitOption.ordinal)]


@pytest.mark.parametrize("relic,char_id,cost", [(R25, "char_four", 0), (R26, "char_five", 1),
    (R27, "char_six_later", 4), (R28, "char_five", 1)])
def test_four_effects_purchase_delta_no_ticket_gap_immutable_prices_and_restore(cost_runtime, relic, char_id, cost):
    runtime, token = cost_runtime
    configure(runtime, token, relic)
    main = runtime.sync(token)["user"]["troop"]
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)["user"]
        reply = buy(client, token, "relic", "relic")
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        state = after["rlv2"]["current"]
        assert len(state["inventory"]["recruit"]) == 3
        assert state["inventory"]["relic"]["1"] == {
            "index": "1", "id": relic, "count": 1, "layer": 0, "ts": 1_800_000_000, "used": False}
        assert buy(client, token, "relic", "relic-retry").status_code == 200
        assert runtime.sync(token)["user"] == after
        assert buy(client, token, "ticket", "ticket").status_code == 200
        candidates = current(runtime, token)["inventory"]["recruit"]["3"]["list"]
        target = next(c for c in candidates if c["charId"] == char_id)
        assert target["population"] == cost and target["type"] == "NORMAL"
        old_options = saved_options(runtime, 3)
        reply = post(client, token, "recruitChar", {"ticketIndex": "3", "optionId": str(target["instId"])}, "select")
        assert reply.status_code == 200, reply.text
        assert current(runtime, token)["player"]["property"]["population"]["cost"] == 6 + cost
        assert leave(client, token).status_code == 200
        assert move(client, token, 3, "later-shop").status_code == 200
        assert buy(client, token, "relic", "later-relic").status_code == 200
        assert buy(client, token, "ticket", "later-ticket").status_code == 200
        assert set(current(runtime, token)["inventory"]["recruit"]) == {"0", "1", "2", "3", "4"}
        assert saved_options(runtime, 3) == old_options
    final = runtime.sync(token)["user"]
    assert final["troop"] == main
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()
    backups = BackupService(runtime)
    backup = backups.create()
    expected = rows(runtime.database.path)
    backups.restore(backup["name"])
    assert rows(runtime.database.path) == expected and runtime.sync(token)["user"] == final


def test_later_relic_cannot_reprice_an_older_persisted_offer_on_restart(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, R26)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "ticket", "before").status_code == 200
        before = saved_options(runtime, 3)
        assert next(o[2] for o in before if o[3]["charId"] == "char_five") == 3
        assert post(client, token, "closeRecruitTicket", {"id": "3"}, "close").status_code == 200
        assert buy(client, token, "relic", "after").status_code == 200
        assert saved_options(runtime, 3) == before
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as con:
        con.execute("UPDATE rlv2_recruit_options SET hope_cost=1 WHERE ticket_ordinal=3 AND kind='NORMAL' "
                    "AND json_extract(character,'$.charId')='char_five'")
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


def test_concurrent_relic_purchase_grants_once_and_keeps_ticket_ordinals(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token)
    other = Runtime(runtime.settings)
    try:
        def pay(pair):
            r, key = pair
            with TestClient(create_game_app(r)) as client:
                return buy(client, token, "relic", key).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(pay, ((runtime, "a"), (other, "b")))) == [200, 200]
        state = current(runtime, token)
        assert len(state["inventory"]["relic"]) == 2 and len(state["inventory"]["recruit"]) == 3
        assert state["player"]["property"]["gold"] == 5
    finally:
        other.database.close()


def test_post_grant_validation_failure_rolls_back_relic_stock_gold_and_receipt(cost_runtime, monkeypatch):
    from terralocal.server.domain.rogue_relics import Replay

    runtime, token = cost_runtime
    configure(runtime, token)
    original = Replay.finish
    def fail(self, values):
        if self.grants:
            raise ValueError("Failure after relic row insertion")
        return original(self, values)
    before = rows(runtime.database.path)
    monkeypatch.setattr(Replay, "finish", fail)
    with TestClient(create_game_app(runtime)) as client:
        response = buy(client, token, "relic", "fail")
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "ROGUE_SETTLEMENT_INCOMPATIBLE"
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("field,value", [("count", 2), ("layer", 1), ("used", 1), ("acquired_at", 1)])
def test_inventory_without_matching_owned_receipt_is_rejected_read_only(cost_runtime, field, value):
    runtime, token = cost_runtime
    configure(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "buy").status_code == 200
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as con:
        con.execute('UPDATE rlv2_relics SET "'+field+'"=? WHERE ordinal=1', (value,))
    before = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == before


def test_duplicate_relic_supply_across_nodes_is_rejected_before_publishing(cost_runtime):
    runtime, token = cost_runtime
    setup(runtime, token, ("SHOP", "SHOP"))
    before = rows(runtime.database.path)
    with pytest.raises(DomainError):
        with runtime.database.transaction() as session:
            quote = compile_shop(runtime.data, "duplicate", (Offer("r", R25, 1, relic_layer=0),),
                                 evidence="Invalid duplicate no-stack plan fixture")
            prepare(Context(session, runtime.data, 1), {Point(0, 0): quote, Point(1, 0): quote})
    assert rows(runtime.database.path) == before


def test_discounted_direct_recruit_and_unchanged_paid_upgrade_prices(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, R25, ticket="rogue_1_recruit_ticket_all_discount", direct_pool=("char_four",))
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "relic").status_code == 200
        assert buy(client, token, "ticket", "ticket").status_code == 200
        candidates = current(runtime, token)["inventory"]["recruit"]["3"]["list"]
        direct = next(c for c in candidates if c["charId"] == "char_four")
        assert direct["population"] == 0 and direct["upgradePhase"] == 1 and direct["type"] == "NORMAL"
        upgrades = [c for c in candidates if c["isUpgrade"]]
        assert upgrades and all(c["population"] == 3 for c in upgrades)


def test_cost_relic_does_not_change_free_temporary_recruit_or_credit_hope(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, R28, ticket="rogue_1_recruit_ticket_pioneer_sp")
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "relic").status_code == 200
        assert buy(client, token, "ticket", "ticket").status_code == 200
        free = next(c for c in current(runtime, token)["inventory"]["recruit"]["3"]["list"] if c["type"] == "FREE")
        assert free["population"] == 0
        response = post(client, token, "recruitChar", {"ticketIndex": "3", "optionId": str(free["instId"])}, "free")
        assert response.status_code == 200, response.text
        assert current(runtime, token)["player"]["property"]["population"]["cost"] == 6


@pytest.mark.parametrize("layer", [None, True, -1, 1, "0"])
def test_missing_or_unadmitted_layer_cannot_become_a_purchase(cost_runtime, layer):
    runtime, _ = cost_runtime
    with pytest.raises(ValueError):
        compile_shop(runtime.data, "bad-layer", (Offer("r", R25, 1, relic_layer=layer),),
                     evidence="Invalid acquisition shape fixture")


def test_duplicate_relic_slots_and_relic_fields_on_tickets_are_rejected(cost_runtime):
    runtime, _ = cost_runtime
    for offers in ((Offer("r1", R25, 1, relic_layer=0), Offer("r2", R25, 1, relic_layer=0)),
                   (Offer("t", "ticket_pioneer", 1, relic_layer=0),)):
        with pytest.raises(ValueError):
            compile_shop(runtime.data, "bad-shape", offers, evidence="Invalid stock fixture")


def test_relic_score_count_survives_defeat_acknowledgement_and_restore(cost_tables, shop_ending_runtime):
    from test_native_replay import journal as make_journal
    from test_rogue_defeat import defeat
    from test_roguelike_battle_start import begin, body

    from terralocal.server.domain.rogue_ending import RELIC_POLICY

    runtime, token = shop_ending_runtime
    setup(runtime, token, ("SHOP", "BATTLE_NORMAL", "SHOP"))
    with runtime.database.transaction() as session:
        stock = compile_shop(runtime.data, "cost-ending", (Offer("relic", R25, 1, relic_layer=0),),
                             evidence="Authored relic-count ending fixture, no native battle")
        prepare(Context(session, runtime.data, 1), {Point(0, 0): stock})
    journal = make_journal()
    journal["journal"]["metadata"]["stageId"] = "ordinary"
    member = journal["journal"]["squad"][0]
    member["skillIndex"], member["skillId"] = 1, "s1"
    journal["journal"]["squad"].append(member | {"charInstId": 2, "skillIndex": -1, "skillId": None})
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "shop").status_code == 200
        assert buy(client, token, "relic", "relic").status_code == 200
        assert leave(client, token).status_code == 200
        started = begin(client, token, body() | {"to": {"x": 1, "y": 0}}, "battle-fixture")
        assert started.status_code == 200, started.text
        reply = defeat(client, token, started.json()["battleId"], journal, "defeat-fixture")
        assert reply.status_code == 200, reply.text
        response = post(client, token, "gameSettle", {}, "ending")
        assert response.status_code == 200, response.text
        assert response.json()["game"]["score"]["detail"][5] == [1, 5]
        repeated = post(client, token, "gameSettle", {}, "ending-retry")
        assert repeated.status_code == 200 and repeated.json()["game"] == response.json()["game"]
    final = runtime.sync(token)["user"]
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueGameSettlement).one().policy_version == RELIC_POLICY
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()
    backups = BackupService(runtime)
    backup = backups.create()
    expected = rows(runtime.database.path)
    backups.restore(backup["name"])
    assert rows(runtime.database.path) == expected


def test_abandon_retains_relic_history_without_discount_leaking_to_a_new_run(cost_runtime):
    runtime, token = cost_runtime
    configure(runtime, token, R25)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "relic").status_code == 200
        assert buy(client, token, "ticket", "ticket").status_code == 200
        reply = post(client, token, "giveUpGame", {}, "abandon")
        assert reply.status_code == 200, reply.text
        assert post(client, token, "gameSettle", {}, "confirm-abandon").status_code == 200
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == runtime.sync(token)["user"]
    finally:
        reopened.database.close()
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueRunRelic).count() == 2
        assert session.query(m.RogueShopVisit).filter_by(state="ABANDONED").count() == 1
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0}, "too-early")
        assert reply.status_code == 400 and reply.json()["error"]["code"] == "ROGUE_REOPEN_COOLDOWN"
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += runtime.data.rogue_initial.cooldown
        reply = post(client, token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0}, "new-run")
        assert reply.status_code == 200, reply.text
        assert post(client, token, "chooseInitialRelic", {"select": "0"}, "new-band").status_code == 200
        assert post(client, token, "chooseInitialRecruitSet", {"select": "recruit_group_1"}, "new-group").status_code == 200
        assert post(client, token, "activeRecruitTicket", {"id": "0"}, "new-offer").status_code == 200
        ordinary = next(c for c in current(runtime, token)["inventory"]["recruit"]["0"]["list"] if c["charId"] == "char_four")
        assert ordinary["population"] == 2
