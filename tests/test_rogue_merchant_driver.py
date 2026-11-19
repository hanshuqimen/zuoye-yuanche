"""History-backed quote planning; synthetic terms, no native play or random pool."""

import copy
from types import MappingProxyType

import pytest
import test_rogue_cost_relics as costs
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy, configure
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_recruit_costs import R25, R26
from test_rogue_training import move, setup
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_merchant import POLICY, quote
from terralocal.server.domain.rogue_shops import prepare as save_shops
from terralocal.server.gamedata import rogue_merchant_relics
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def merchant_tables(cost_tables, monkeypatch):
    original = costs.add_costs

    def add(tables):
        value = original(tables)
        detail = value["roguelike_topic_table"]["details"]["rogue_1"]
        item = detail["items"][R25]
        item.update(iconId=R25, rarity="RARE", unlockCondDesc=None)
        identity = {k: item[k] for k in ("id", "type", "iconId", "rarity", "unlockCondDesc")}
        # Explicit authored price/identity; never pass this fixture off as a
        # recovered official shop or change production SOURCES for convenience.
        digest = fingerprint({"item": identity, "archive": detail["archiveComp"]["relic"]["relic"][R25]})
        monkeypatch.setattr(rogue_merchant_relics, "SOURCES", MappingProxyType({R25: (2, digest)}))
        return value

    monkeypatch.setattr(costs, "add_costs", add)


@pytest.fixture
def merchant_runtime(merchant_tables, cost_runtime):
    return cost_runtime


def compile_now(runtime, *, slots=(("0", R25),), account=1):
    with runtime.database.transaction(write=False) as session:
        return quote(Context(session, runtime.data, account), "history-shop", slots)


@pytest.mark.parametrize("claim", [None, 1, 2])
def test_missing_history_or_persisted_collection_claim_cannot_authorize_stock(merchant_runtime, claim):
    runtime, token = merchant_runtime
    setup(runtime, token, ("SHOP",))
    if claim is not None:
        with runtime.database.transaction() as session:
            outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
            state = copy.deepcopy(outer.state)
            state["collect"]["relic"][R25] = {"state": claim, "progress": []}
            outer.state = state
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as error:
        compile_now(runtime)
    assert error.value.code == "ROGUE_MERCHANT_ELIGIBILITY_MISSING"
    assert rows(runtime.database.path) == before


def archived_relic_then_new_map(runtime, token):
    configure(runtime, token, R25)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "driver-old-buy").status_code == 200
        with pytest.raises(DomainError):
            compile_now(runtime)  # Known discovery does not allow duplicate ownership.
        assert post(client, token, "giveUpGame", {}, "driver-abandon").status_code == 200
        assert post(client, token, "gameSettle", {}, "driver-confirm").status_code == 200
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += runtime.data.rogue_initial.cooldown
    with TestClient(create_game_app(runtime)) as client:
        for route, body, key in (
            ("createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0}, "create"),
            ("chooseInitialRelic", {"select": "0"}, "band"),
            ("chooseInitialRecruitSet", {"select": "recruit_group_1"}, "group"),
        ):
            reply = post(client, token, route, body, "driver-new-" + key)
            assert reply.status_code == 200, reply.text
        for i in range(3):
            assert post(client, token, "activeRecruitTicket", {"id": str(i)}, "driver-active-" + str(i)).status_code == 200
            assert post(client, token, "closeRecruitTicket", {"id": str(i)}, "driver-close-" + str(i)).status_code == 200
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), Plan("zone_1", (Column(1, 1, (Entry("SHOP", 1),)),), 0))
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "driver-new-map").status_code == 200


def test_verified_history_quote_persists_and_uses_existing_payment_retry_delta_and_restore(merchant_runtime):
    runtime, token = merchant_runtime
    archived_relic_then_new_map(runtime, token)
    before = rows(runtime.database.path)
    q = compile_now(runtime)
    assert q.offers["0"].price == 2 and POLICY in q.evidence
    assert compile_now(runtime).digest == q.digest
    assert rows(runtime.database.path) == before
    with runtime.database.transaction() as session:
        save_shops(Context(session, runtime.data, 1), {Point(0, 0): q})
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "driver-enter").status_code == 200
        initial = runtime.sync(token)["user"]
        reply = buy(client, token, "0", "driver-buy")
        assert reply.status_code == 200, reply.text
        final = runtime.sync(token)["user"]
        assert apply(initial, reply.json()["playerDataDelta"]) == final
        assert current(runtime, token)["player"]["property"]["gold"] == initial["rlv2"]["current"]["player"]["property"]["gold"] - 2
        assert buy(client, token, "0", "driver-buy-again").status_code == 200
        assert runtime.sync(token)["user"] == final
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()
    saved = rows(runtime.database.path)
    backups = BackupService(runtime)
    name = backups.create()["name"]
    backups.restore(name)
    assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == final
    with runtime.database.transaction(write=False) as session:
        old = session.query(m.RogueShopVisit).filter(m.RogueShopVisit.quote["id"].as_string() == "qa-cost-relic").one()
        assert old.quote["offers"][0]["price"] == 1  # No repricing of old QA history.


def test_partial_or_duplicate_selection_does_not_publish_or_write_any_quote(merchant_runtime):
    runtime, token = merchant_runtime
    archived_relic_then_new_map(runtime, token)
    before = rows(runtime.database.path)
    for slots in ((("0", R25), ("1", R26)), (("0", R25), ("1", R25))):
        with pytest.raises(DomainError):
            compile_now(runtime, slots=slots)
    assert rows(runtime.database.path) == before


def test_changed_catalog_is_incompatible_not_an_eligibility_claim(merchant_runtime, monkeypatch):
    runtime, token = merchant_runtime
    setup(runtime, token, ("SHOP",))
    monkeypatch.setattr(rogue_merchant_relics, "SOURCES", MappingProxyType({R25: (2, "f" * 64)}))
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as error:
        compile_now(runtime)
    assert error.value.code == "ROGUE_MERCHANT_INCOMPATIBLE"
    assert rows(runtime.database.path) == before
