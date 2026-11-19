"""Reviewed intrinsic availability; authored identities are not official data."""

import copy
import hashlib
import json
import sqlite3
from dataclasses import FrozenInstanceError
from types import MappingProxyType, SimpleNamespace

import pytest
import test_rogue_cost_relics as costs
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_recruit_costs import R25, R26, R27
from test_rogue_training import move, setup
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_merchant import quote
from terralocal.server.domain.rogue_shops import prepare
from terralocal.server.domain.rogue_shops import quote as saved_quote
from terralocal.server.domain.rogue_topics import snapshot
from terralocal.server.gamedata import rogue_base_relics as base
from terralocal.server.gamedata import rogue_merchant_relics as merchant
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def identity(detail, key):
    return fingerprint({"item": {f: detail["items"][key][f] for f in
                                ("id", "type", "iconId", "rarity", "unlockCondDesc")},
                        "archive": detail["archiveComp"]["relic"]["relic"][key]})


def rule_data(monkeypatch):
    detail = {"items": {}, "archiveComp": {"relic": {"relic": {}}}}
    entries, refs, sources = {}, {}, {}
    for key, name, price, opens in (("qa_base", "Authored base", 8, 0), ("qa_late", "Authored late", 16, 200)):
        detail["items"][key] = {"id": key, "type": "RELIC", "iconId": key, "rarity": "NORMAL",
                                "unlockCondDesc": None, "name": name}
        detail["archiveComp"]["relic"]["relic"][key] = {"id": key, "enrollment": None}
        entries[key] = SimpleNamespace(price=price, opens_at=opens)
        refs[key] = SimpleNamespace(special=False)
        sources[key] = name, price, identity(detail, key)
    monkeypatch.setattr(base, "SOURCES", MappingProxyType(sources))
    data = SimpleNamespace(table=lambda name: {"details": {"rogue_1": detail}},
        manifest={"hash": "a" * 64, "tables": {"roguelike_topic_table": "b" * 64}},
        rogue_topics=SimpleNamespace(topic=lambda key: SimpleNamespace(start=100)),
        rogue_merchant_relics=SimpleNamespace(entries=entries, fingerprint="c" * 64),
        rogue_relic_archive=SimpleNamespace(entries=refs))
    return data, detail


def test_reviewed_set_opening_and_later_enrollment_are_separate_from_discovery(monkeypatch):
    data, detail = rule_data(monkeypatch)
    detail["items"]["unreviewed"] = {"id": "unreviewed", "type": "RELIC", "unlockCondDesc": None}
    assert base.available(data)
    rules = base.FirstThemeBaseRelics(data)
    assert set(rules.openings) == {"qa_base", "qa_late"}
    assert rules.evaluate(99)["qa_base"].wire() == {"state": 0, "progress": []}
    assert rules.evaluate(100)["qa_base"].wire() == {"state": 1, "progress": []}
    assert rules.evaluate(199)["qa_late"].wire() == {"state": 0, "progress": []}
    assert rules.evaluate(200)["qa_late"].wire() == {"state": 1, "progress": []}
    with pytest.raises(TypeError):
        rules.openings["unreviewed"] = 0
    value = rules.evaluate(100)["qa_base"]
    with pytest.raises(FrozenInstanceError):
        value.opened = False
    value.wire()["progress"].append(999)
    assert value.wire() == {"state": 1, "progress": []}


@pytest.mark.parametrize("at", [True, -1, 2**63, 100.0, None])
def test_invalid_clock_cannot_authorize_intrinsic_availability(monkeypatch, at):
    with pytest.raises(ValueError):
        base.FirstThemeBaseRelics(rule_data(monkeypatch)[0]).evaluate(at)


@pytest.mark.parametrize("change", ["condition", "name", "icon", "price", "special", "missing_sibling", "missing_effect"])
def test_declared_profile_rejects_changed_binding_and_partial_capability(monkeypatch, change):
    data, detail = rule_data(monkeypatch)
    if change == "condition":
        detail["items"]["qa_base"]["unlockCondDesc"] = "new prerequisite"
    elif change == "name":
        detail["items"]["qa_base"]["name"] = "other name"
    elif change == "icon":
        detail["items"]["qa_base"]["iconId"] = "other"
    elif change == "price":
        data.rogue_merchant_relics.entries["qa_base"].price = 12
    elif change == "special":
        data.rogue_relic_archive.entries["qa_base"].special = True
    elif change == "missing_sibling":
        del detail["items"]["qa_base"]
    else:
        del data.rogue_merchant_relics.entries["qa_base"]
    assert base.available(data)  # The other declared item prevents silent disabling.
    with pytest.raises(ValueError):
        base.FirstThemeBaseRelics(data)


@pytest.fixture
def base_tables(cost_tables, monkeypatch):
    original = costs.add_costs
    def add(tables):
        tables = original(tables)
        d = tables["roguelike_topic_table"]["details"]["rogue_1"]
        sources, terms = {}, {}
        for key, name, price in ((R25, "QA intrinsic one", 8), (R26, "QA intrinsic two", 12)):
            d["items"][key].update(name=name, iconId=key, rarity="RARE", unlockCondDesc=None)
            digest = identity(d, key)
            sources[key], terms[key] = (name, price, digest), (price, digest)
        d["items"][R27].update(name="QA unreviewed null condition", iconId=R27, rarity="RARE", unlockCondDesc=None)
        terms[R27] = 8, identity(d, R27)  # Priced and supported, still outside the reviewed base set.
        for config in d["init"]:
            config["initialGold"] = 30  # Explicit authored funding, no official budget claim.
        monkeypatch.setattr(base, "SOURCES", MappingProxyType(sources))
        monkeypatch.setattr(merchant, "SOURCES", MappingProxyType(terms))
        return tables
    monkeypatch.setattr(costs, "add_costs", add)


@pytest.fixture
def base_runtime(base_tables, cost_runtime):
    return cost_runtime


def collection(runtime, token):
    return runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["relic"]


def test_new_account_base_stock_purchase_delta_and_restart_do_not_fabricate_discovery(base_runtime):
    runtime, token = base_runtime
    assert collection(runtime, token) == {R25: {"state": 1, "progress": []}, R26: {"state": 1, "progress": []}}
    setup(runtime, token, ("SHOP",))
    before_rows = rows(runtime.database.path)
    with runtime.database.transaction(write=False) as session:
        q = quote(Context(session, runtime.data, 1), "intrinsic-stock", (("0", R25), ("1", R26)))
        assert [o.price for o in q.offers.values()] == [8, 12]
    assert rows(runtime.database.path) == before_rows
    with runtime.database.transaction() as session:
        prepare(Context(session, runtime.data, 1), {Point(0, 0): q})
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token, 0, "enter").status_code == 200
        before = runtime.sync(token)["user"]
        response = buy(client, token, "0", "base-buy")
        assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        assert after["rlv2"]["current"]["player"]["property"]["gold"] == 22
        assert collection(runtime, token)[R25] == {"state": 2, "progress": []}
        assert collection(runtime, token)[R26] == {"state": 1, "progress": []}
        assert buy(client, token, "0", "base-buy-retry").status_code == 200
        assert runtime.sync(token)["user"] == after
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after and rows(runtime.database.path) == saved
        backup = BackupService(reopened)
        backup.restore(backup.create()["name"])
        assert reopened.sync(token)["user"] == after and rows(runtime.database.path) == saved
    finally:
        reopened.database.close()


def test_unreviewed_null_condition_or_saved_available_claim_cannot_expand_base_stock(base_runtime):
    runtime, token = base_runtime
    setup(runtime, token, ("SHOP",))
    with runtime.database.transaction() as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        state = copy.deepcopy(outer.state)
        state["collect"]["relic"][R27] = {"state": 1, "progress": []}
        outer.state = state
    saved = rows(runtime.database.path)
    with runtime.database.transaction(write=False) as session:
        with pytest.raises(DomainError):
            quote(Context(session, runtime.data, 1), "not-in-base-set", (("0", R27),))
    assert rows(runtime.database.path) == saved


@pytest.mark.parametrize("claim", [{"state": 2, "progress": []}, {"state": 1, "progress": [0, 1]}])
def test_fabricated_discovery_or_counter_is_rejected_before_startup_writes(base_runtime, claim):
    runtime, _ = base_runtime
    runtime.database.close()
    with sqlite3.connect(runtime.settings.database_path) as con:
        state = json.loads(con.execute("SELECT state FROM rlv2_topics WHERE account_id=1 AND topic_id='rogue_1'").fetchone()[0])
        state["collect"]["relic"][R25] = claim
        con.execute("UPDATE rlv2_topics SET state=? WHERE account_id=1 AND topic_id='rogue_1'", (json.dumps(state),))
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


def test_base_policy_revision_binds_new_quotes_without_rewriting_saved_stock(base_runtime, monkeypatch):
    runtime, token = base_runtime
    setup(runtime, token, ("SHOP",))
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        original = quote(ctx, "policy-bound", (("0", R25),))
        prepare(ctx, {Point(0, 0): original})
    before = rows(runtime.database.path)
    monkeypatch.setattr(base, "POLICY", base.POLICY + "-new-review")
    runtime.data.__dict__.pop("rogue_base_relics")
    with runtime.database.transaction(write=False) as session:
        replacement = quote(Context(session, runtime.data, 1), "policy-bound", (("0", R25),))
        assert original.digest != replacement.digest
        assert dict(original.offers) == dict(replacement.offers)
        visit = session.query(m.RogueShopVisit).filter_by(node_x=0).one()
        assert saved_quote(runtime.data, visit).digest == original.digest
    assert rows(runtime.database.path) == before


def test_saved_clock_opening_boundary_agrees_in_readonly_preflight_and_live_projection(base_runtime):
    runtime, _ = base_runtime
    start = runtime.data.rogue_topics.topic("rogue_1").start
    assert start > 0
    runtime.database.close()
    for at, expected in ((start - 1, 0), (start, 1)):
        with sqlite3.connect(runtime.settings.database_path) as con:
            con.execute("UPDATE server_clock SET mode='fixed',fixed_at=?,offset=0 WHERE id=1", (at,))
        before = rows(runtime.database.path)
        reopened = Runtime(runtime.settings)
        try:
            with reopened.database.transaction(write=False) as session:
                wire = snapshot(Context(session, reopened.data, 1))["outer"]["rogue_1"]["collect"]["relic"]
                assert wire[R25] == {"state": expected, "progress": []}
                assert wire[R26] == {"state": expected, "progress": []}
            assert rows(runtime.database.path) == before
        finally:
            reopened.database.close()
