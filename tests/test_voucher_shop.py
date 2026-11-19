"""Synthetic supply: transactional accounting, native tier state, and recovery."""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from sqlalchemy import select

from terralocal.config import Settings
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import GameData, import_data
from terralocal.server.gamedata.voucher_shop import (
    admit_catalog,
    read_catalog,
    write_catalog,
)
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import HOME_REVISION, REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

NOW = 1_800_000_000


def normal(good, *, group=None, price=10, capacity=5, item="material", quantity=1, kind="MATERIAL"):
    return {"goodId": good, "item": {"id": item, "type": kind, "count": quantity},
            "price": price, "originPrice": price, "discount": 0.0, "availCount": capacity,
            "number": 1, "slotId": 1, "groupId": group}


def catalog_value(data, profile):
    base = {"startTime": NOW - 100, "endTime": NOW + 100,
            "provenance": "Authored test cycle; no claim of official supply or reset schedule."}
    low = {**base, "shop": "LS", "period": "low-one", "shopId": "test-low-one", "type": 1,
           "progressEncoding": "total-spend", "shopEndTime": NOW + 100,
           "groups": ["one", "two", "three"], "groupsInfo": [
               {"groupId": "one", "lggThreshold": 0}, {"groupId": "two", "lggThreshold": 20},
               {"groupId": "three", "lggThreshold": 50}],
           "goodList": [normal("green", group="one"), normal("green-two", group="two", capacity=2),
                        normal("green-three", group="three", price=1, capacity=-1)]}
    next_low = copy.deepcopy(low)
    next_low.update(period="low-two", shopId="test-low-two", startTime=NOW + 100,
                    endTime=NOW + 200, shopEndTime=NOW + 200)
    high = {**base, "shop": "HS", "period": "high-one", "goodList": [
        normal("yellow", price=2, capacity=5, quantity=3),
        {**normal("yellow-steps", capacity=0, price=0), "item": None,
         "progressGoodId": "sequence", "goodType": "PROGRESS"}], "progressGoodList": {
             "sequence": [{"order": i, "price": p, "displayName": "Synthetic bundle",
                           "item": {"id": "book", "type": "MATERIAL", "count": q}}
                          for i, (p, q) in enumerate(((4, 1), (6, 2), (9, 4)), 1)]}}
    classic = {**base, "shop": "CLASSIC", "period": "classic-one", "goodList": [
        normal("classic-char", item="char_synthetic", kind="CHAR", capacity=6)], "progressGoodList": {}}
    extra = {**base, "shop": "ES", "period": "extra-one", "goodList": [{
        "goodId": "red", "displayName": "Synthetic book", "item": {"id": "book", "count": 5, "type": "MATERIAL"},
        "originPrice": 3, "price": 3, "availCount": 2, "discount": 0.0, "slotId": 1,
        "goodEndTime": -1, "shopType": 1, "newFlagTimeStamp": -1}]}
    return {"schema_version": 1, "gamedata_hash": data.manifest["hash"], "client_profile": profile,
            "catalog_id": "synthetic-vouchers", "mode": "custom", "provenance": "Synthetic supply only.",
            "cycles": [low, next_low, high, classic, extra]}


@pytest.fixture
def runtime(tmp_path):
    tables = miniature()
    for key, kind in {"4004": "HGG_SHD", "4005": "LGG_SHD", "classic_normal_ticket": "CLASSIC_SHD",
                      "classic-token": "MATERIAL"}.items():
        tables["item_table"]["items"][key] = {"itemId": key, "name": "Synthetic " + key, "itemType": kind}
    tables["character_table"]["char_synthetic"]["classicPotentialItemId"] = "classic-token"
    source = tmp_path / "source"
    source.mkdir()
    for name, table in tables.items():
        (source / (name + ".json")).write_text(json.dumps(table), "utf-8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    data = GameData(settings.data_dir / "cache" / manifest["hash"])
    (settings.data_dir / "voucher_shop.json").write_text(json.dumps(catalog_value(data, settings.client_profile)), "utf-8")
    instance = Runtime(settings)
    with instance.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", NOW
        create_account(session, instance.data, "Doctor")
        ctx = Context(session, instance.data, 1)
        for wallet in ("4004", "4005", "classic_normal_ticket", "4006"):
            ctx.change_item(wallet, 100)
    yield instance
    instance.database.close()


def buy(client, token, name="High", good="yellow", count=1, key="buy", **extra):
    return client.post("/shop/buy" + name + "Good", headers={"secret": token, "seqnum": key},
                       json={"goodId": good, "count": count, **extra})


def load_value(runtime, value):
    path = runtime.settings.data_dir / "candidate.json"
    path.write_text(json.dumps(value), "utf-8")
    return read_catalog(path, runtime.data, runtime.settings.client_profile)


def test_all_catalog_lists_reassert_real_scoped_state_without_mutations(runtime, client, token):
    before = runtime.sync(token)
    for name, shop in (("Low", "LS"), ("High", "HS"), ("Classic", "CLASSIC"), ("Extra", "ES")):
        response = client.post("/shop/get" + name + "GoodList", json={}, headers={"secret": token})
        assert response.status_code == 200 and response.json()["goodList"]
        assert apply(before["user"], response.json()["playerDataDelta"]) == before["user"]
        if shop in {"HS", "CLASSIC", "ES"}:
            assert "curShopId" not in before["user"]["shop"][shop]
            assert isinstance(before["user"]["shop"][shop]["progressInfo"], dict)
    assert client.post("/shop/getHighGoodList", json={}).status_code == 401
    assert client.post("/shop/getLowGoodList", json={"groupId": "one"}, headers={"secret": token}).status_code == 422
    assert runtime.sync(token) == before


@pytest.mark.parametrize("name,good,count,wallet,cost,reward,quantity", [
    ("High", "yellow", 2, "4004", 4, "material", 6),
    ("Extra", "red", 2, "4006", 6, "book", 10),
    ("Low", "green", 2, "4005", 20, "material", 2),
])
def test_purchase_accounting_delta_limits_and_exact_retry(runtime, client, token, name, good, count,
                                                        wallet, cost, reward, quantity):
    before = runtime.sync(token)["user"]
    response = buy(client, token, name, good, count)
    assert response.status_code == 200
    assert response.json()["items"] == [{"id": reward, "count": quantity, "type": "MATERIAL"}]
    after = runtime.sync(token)["user"]
    assert apply(before, response.json()["playerDataDelta"]) == after
    assert buy(client, token, name, good, count).json() == response.json()
    assert buy(client, token, name, good, count + 1).status_code == 409
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        assert ctx.balance(wallet) == 100 - cost and ctx.balance(reward) == quantity
        assert len(ctx.rows(m.PurchaseHistory)) == 1
    assert runtime.sync(token)["user"] == after


def test_low_locked_groups_unlock_from_actual_spend_and_keep_previous_groups_buyable(runtime, client, token):
    assert buy(client, token, "Low", "green-two").status_code == 409
    assert buy(client, token, "Low", "green", 2).status_code == 200
    low = runtime.sync(token)["user"]["shop"]["LS"]
    assert (low["curGroupId"], low["lggCostTotal"]) == ("two", 20)
    assert buy(client, token, "Low", "green", 3, key="finish-first").status_code == 200
    low = runtime.sync(token)["user"]["shop"]["LS"]
    assert (low["curGroupId"], low["lggCostTotal"]) == ("three", 50)
    assert buy(client, token, "Low", "green", key="over-cap").status_code == 409
    assert buy(client, token, "Low", "green-three", 10, key="unlimited").status_code == 200


@pytest.mark.parametrize("legacy", [False, True])
def test_low_explicit_alternative_policies_are_not_guessed_from_client_fields(runtime, client, token, legacy):
    value = catalog_value(runtime.data, runtime.settings.client_profile)
    value["cycles"] = [value["cycles"][0]]
    low = value["cycles"][0]
    low["period"] = "separate-policy"
    low.update(type=0 if legacy else 1, progressEncoding=None if legacy else "stage-spend")
    if not legacy:
        low["groupsInfo"][2]["lggThreshold"] = 30
    policy = load_value(runtime, value)
    admit_catalog(policy, runtime.database)
    runtime.data.voucher_shop_catalog = policy
    assert buy(client, token, "Low", "green", 2).status_code == 200
    state = runtime.sync(token)["user"]["shop"]["LS"]
    assert (state["curGroupId"], state["lggCostTotal"]) == (("one", 20) if legacy else ("two", 0))
    assert buy(client, token, "Low", "green", 3, key="finish").status_code == 200
    state = runtime.sync(token)["user"]["shop"]["LS"]
    assert (state["curGroupId"], state["lggCostTotal"]) == (("two", 50) if legacy else ("three", 0))


def test_progress_uses_current_tier_reward_price_and_valid_terminal_state(runtime, client, token):
    before = runtime.sync(token)["user"]
    assert buy(client, token, good="yellow-steps", count=2).status_code == 409
    for index, (next_order, terminal, quantity) in enumerate(((2, 0, 1), (3, 0, 2), (3, 1, 4)), 1):
        response = buy(client, token, good="yellow-steps", key="tier-" + str(index))
        assert response.status_code == 200
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        assert after["shop"]["HS"]["progressInfo"]["sequence"] == {"order": next_order, "count": terminal}
        assert response.json()["items"] == [{"id": "book", "type": "MATERIAL", "count": quantity}]
        assert after["shop"]["HS"]["info"] == []
        before = after
    assert buy(client, token, good="yellow-steps", key="last-over").status_code == 409
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        assert ctx.balance("4004") == 81 and ctx.balance("book") == 7
        assert [r.cost["order"] for r in ctx.rows(m.PurchaseHistory)] == [1, 2, 3]


def test_classic_character_uses_classic_tokens_and_certificates(runtime, client, token):
    response = buy(client, token, "Classic", "classic-char", 2)
    assert response.status_code == 200
    assert [r["charGet"]["itemGet"][-1]["count"] for r in response.json()["items"]] == [10, 5]
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        assert ctx.balance("classic_normal_ticket") == 95
        assert ctx.balance("classic-token") == 2 and ctx.balance("token") == 0
        assert ctx.balance("4004") == 100 and ctx.balance("4005") == 100


def test_concurrent_normal_and_progress_purchases_preserve_caps_and_accounting(runtime, token):
    def send(entry):
        good, key = entry
        with TestClient(create_game_app(runtime)) as client:
            return buy(client, token, good=good, key=key).status_code
    for good, requests, expected in (("yellow", 8, [200] * 5 + [409] * 3),
                                     ("yellow-steps", 4, [200] * 3 + [409])):
        with ThreadPoolExecutor(max_workers=4) as executor:
            result = list(executor.map(send, [(good, f"{good}-{n}") for n in range(requests)]))
        assert sorted(result) == expected
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        assert ctx.balance("4004") == 71
        assert ctx.balance("material") == 15 and ctx.balance("book") == 7
        assert len(ctx.rows(m.PurchaseHistory)) == 8


@pytest.mark.parametrize("name,good", [("Low", "green"), ("High", "yellow-steps"), ("Extra", "red")])
def test_grant_failure_rolls_back_all_purchase_effects(runtime, client, token, monkeypatch, name, good):
    before = runtime.sync(token)
    real = Context.rewards

    def fail(ctx, *args):
        real(ctx, *args)
        raise DomainError("SYNTHETIC_FAILURE", "Synthetic grant failure", 503)

    monkeypatch.setattr(Context, "rewards", fail)
    assert buy(client, token, name, good).status_code == 503
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        assert not ctx.rows(m.ShopState) and not ctx.rows(m.PurchaseHistory)
        assert not ctx.rows(m.ShopProgress) and not ctx.rows(m.LowShopProgress)
        assert not ctx.rows(m.Receipt)


@pytest.mark.parametrize("changes", [{"count": True}, {"count": 0}, {"count": -1}, {"count": 1.0},
                                     {"price": 0}, {"item": {"id": "4002", "count": 999}},
                                     {"groupId": "three"}, {"order": 3}])
def test_untrusted_purchase_fields_do_not_authorize_state_changes(runtime, client, token, changes):
    before = runtime.sync(token)
    count = changes.pop("count", 1)
    assert buy(client, token, count=count, **changes).status_code == 422
    assert runtime.sync(token) == before


def test_other_accounts_cannot_share_purchase_caps_or_progress(runtime, client, token):
    assert buy(client, token, good="yellow-steps").status_code == 200
    with runtime.database.transaction() as session:
        account = create_account(session, runtime.data, "Other")
        ctx = Context(session, runtime.data, account.id)
        ctx.change_item("4004", 20)
        other = login(session, runtime.settings, name="Other")["secret"]
    assert runtime.sync(other)["user"]["shop"]["HS"]["progressInfo"]["sequence"] == {"order": 1, "count": 0}
    assert buy(client, other, good="yellow-steps").status_code == 200
    assert runtime.sync(token)["user"]["shop"]["HS"]["progressInfo"]["sequence"]["order"] == 2


def test_purchase_state_reports_total_capacity_not_bought_or_remaining(runtime, client, token):
    assert buy(client, token, count=2).status_code == 200
    ids = {"HS": ["yellow"], "ES": ["red"], "LS": ["green-three"]}
    response = client.post("/shop/getGoodPurchaseState", json={"goodIdMap": ids}, headers={"secret": token})
    assert response.status_code == 200
    assert response.json()["result"] == {"yellow": 5, "red": 2, "green-three": -1}
    state = runtime.sync(token)["user"]
    refreshed = client.post("/account/syncStatus", headers={"secret": token},
        json={"modules": 16, "params": {"16": {"goodIdMap": ids}}})
    assert refreshed.status_code == 200
    assert refreshed.json()["result"]["16"]["goodPurchaseState"]["result"]["yellow"] == 5
    assert apply(state, refreshed.json()["playerDataDelta"]) == runtime.sync(token)["user"]
    unsupported = client.post("/shop/getGoodPurchaseState", headers={"secret": token},
                              json={"goodIdMap": {"HS": ["yellow-steps"]}})
    assert unsupported.status_code == 501


def test_cycle_rollover_and_clock_rewind_keep_purchase_history(runtime, client, token):
    assert buy(client, token, "Low", "green", 2).status_code == 200
    old = runtime.sync(token)["user"]
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = NOW + 100
    response = client.post("/account/syncStatus", headers={"secret": token}, json={"modules": 3807, "params": {}})
    assert response.status_code == 200
    fresh = runtime.sync(token)["user"]
    assert apply(old, response.json()["playerDataDelta"]) == fresh
    assert fresh["shop"]["LS"] == {"curShopId": "test-low-two", "curGroupId": "one", "lggCostTotal": 0, "info": []}
    assert buy(client, token, "Low", "green", 2, key="next-cycle").status_code == 200
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = NOW
    assert runtime.sync(token)["user"]["shop"]["LS"] == old["shop"]["LS"]
    assert buy(client, token, "Low", "green", 4, key="rewind-cap").status_code == 409
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        assert len(ctx.rows(m.PurchaseHistory)) == 2 and len(ctx.rows(m.LowShopProgress)) == 2


def test_restart_and_backup_restore_preserve_tiers_and_normal_inventory(runtime, client, token):
    assert buy(client, token, good="yellow-steps").status_code == 200
    assert buy(client, token, "Low", "green", 2, key="green").status_code == 200
    expected = runtime.sync(token)
    service = BackupService(runtime)
    backup = service.create()
    assert backup["voucher_catalog_hash"] and backup["skin_catalog_hash"] is None
    assert buy(client, token, good="yellow-steps", key="advance").status_code == 200
    assert service.restore(backup["name"])["restored"] == backup["name"]
    assert runtime.sync(token) == expected
    runtime.database.close()
    resumed = Runtime(runtime.settings)
    try:
        assert resumed.sync(token) == expected
        with TestClient(create_game_app(resumed)) as fresh:
            assert buy(fresh, token, good="yellow-steps").status_code == 200
        assert resumed.sync(token) == expected  # Original receipt, no second debit.
    finally:
        resumed.database.close()


@pytest.mark.parametrize("change", ["hash", "wallet", "sequence-gap", "sequence-order", "missing-sequence",
                                    "extra-sequence", "group", "overlap", "reward-type", "repeat", "infinite-character"])
def test_bad_catalogs_fail_without_touching_save(runtime, change):
    value = catalog_value(runtime.data, runtime.settings.client_profile)
    if change == "hash":
        value["gamedata_hash"] = "a" * 64
    elif change == "wallet":
        value["client_profile"] = "other"
    elif change in {"sequence-gap", "sequence-order"}:
        seq = value["cycles"][2]["progressGoodList"]["sequence"]
        if change == "sequence-gap":
            seq[1]["order"] = 4
        else:
            seq.reverse()
    elif change == "missing-sequence":
        value["cycles"][2]["progressGoodList"] = {}
    elif change == "extra-sequence":
        value["cycles"][2]["progressGoodList"]["unused"] = copy.deepcopy(value["cycles"][2]["progressGoodList"]["sequence"])
    elif change == "group":
        value["cycles"][0]["goodList"][0]["groupId"] = "missing"
    elif change == "overlap":
        value["cycles"][1]["startTime"] = NOW
    elif change == "reward-type":
        value["cycles"][0]["goodList"][0]["item"]["type"] = "DIAMOND"
    elif change == "repeat":
        value["cycles"][2]["goodList"].append(copy.deepcopy(value["cycles"][2]["goodList"][0]))
    else:
        value["cycles"][3]["goodList"][0]["availCount"] = -1
    before = runtime.database.backup(runtime.settings.data_dir / "validation-before.sqlite3").read_bytes()
    with pytest.raises((ValueError, DomainError)):
        load_value(runtime, value)
    after = runtime.database.backup(runtime.settings.data_dir / "validation-after.sqlite3").read_bytes()
    assert before == after


def test_redefinition_is_rejected_before_migration_or_active_catalog_replacement(runtime):
    path = runtime.settings.data_dir / "voucher_shop.json"
    active = path.read_bytes()
    changed = json.loads(active)
    changed["cycles"][0]["goodList"][0]["price"] = 1
    catalog = load_value(runtime, changed)
    before = runtime.database.backup(runtime.settings.data_dir / "before-import.sqlite3").read_bytes()
    with pytest.raises(ValueError, match="周期"):
        write_catalog(catalog, runtime.settings.data_dir)
    assert path.read_bytes() == active
    path.write_text(json.dumps(changed), "utf-8")
    runtime.database.close()
    save = runtime.settings.database_path
    digest = hashlib.sha256(save.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="周期"):
        Runtime(runtime.settings)
    assert hashlib.sha256(save.read_bytes()).hexdigest() == digest
    assert before == runtime.database.backup(runtime.settings.data_dir / "after-import.sqlite3").read_bytes()


def test_migration_from_home_revision_keeps_existing_gameplay_and_rejects_unbound_legacy_purchases(runtime):
    runtime.database.close()
    with closing(sqlite3.connect(runtime.settings.database_path)) as con:
        for table in ("low_shop_progress", "shop_progress", "shop_catalog_cycles"):
            con.execute('DROP TABLE "' + table + '"')
        con.execute("UPDATE alembic_version SET version_num=?", (HOME_REVISION,))
        con.commit()
    resumed = Runtime(runtime.settings)
    try:
        with resumed.database.transaction(write=False) as session:
            assert session.execute(select(m.Account)).scalar_one().name == "Doctor"
            assert Context(session, resumed.data, 1).balance("4004") == 100
            assert session.execute(m.Base.metadata.tables["shop_catalog_cycles"].select()).all()
        with closing(sqlite3.connect(runtime.settings.database_path)) as con:
            assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
            con.execute("DELETE FROM shop_catalog_cycles WHERE shop_id='HS'")
            con.execute("INSERT INTO shop_states VALUES(1,'HS','legacy','permanent',1)")
            con.commit()
    finally:
        resumed.database.close()
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="已有凭证"):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


def test_cli_dry_run_and_activation_preserve_catalogs_and_do_not_open_a_database(runtime, monkeypatch, capsys):
    from terralocal.cli import main
    from terralocal.server.persistence.database import Database

    old_path = runtime.settings.data_dir / "voucher_shop.json"
    old = old_path.read_bytes()
    value = json.loads(old)
    value["catalog_id"] = "same-supply-new-description"
    candidate = runtime.settings.data_dir / "cli-candidate.json"
    candidate.write_text(json.dumps(value), "utf-8")
    snapshots = runtime.settings.data_dir / "voucher-catalogs"
    base = ["terralocal", "--data-dir", str(runtime.settings.data_dir), "shop"]

    def forbidden(*args, **kwargs):
        raise AssertionError("CLI catalog work must not initialize/migrate a save")

    monkeypatch.setattr(Database, "__init__", forbidden)
    monkeypatch.setattr("sys.argv", [*base, "import", str(candidate), "--dry-run"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert old_path.read_bytes() == old and not snapshots.exists()
    monkeypatch.setattr("sys.argv", [*base, "import", str(candidate)])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["restart_required"] is True
    assert old in [p.read_bytes() for p in snapshots.iterdir()]
    monkeypatch.setattr("sys.argv", [*base, "show"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["catalog_id"] == "same-supply-new-description"
    assert runtime.voucher_shop_catalog.catalog_id == "synthetic-vouchers"


def test_backup_catalog_mismatch_fails_before_creating_or_replacing_data(runtime, client, token):
    service = BackupService(runtime)
    assert buy(client, token, good="yellow-steps").status_code == 200
    backup = service.create()
    path = runtime.settings.data_dir / "voucher_shop.json"
    value = json.loads(path.read_bytes())
    value["catalog_id"] = "changed-manifest"
    path.write_text(json.dumps(value), "utf-8")
    runtime.database.close()
    resumed = Runtime(runtime.settings)
    try:
        before = resumed.sync(token)
        old_backups = set(service.directory.iterdir())
        with pytest.raises(ValueError, match="商店目录"):
            BackupService(resumed).restore(backup["name"])
        assert set(service.directory.iterdir()) == old_backups
        assert resumed.sync(token) == before
    finally:
        resumed.database.close()


@pytest.mark.parametrize("mode", ["missing", "expired", "unaffordable", "forbidden", "unknown"])
def test_unavailable_supply_and_restrictions_do_not_change_a_save(runtime, client, token, mode):
    name, good = "High", "yellow"
    if mode == "missing":
        runtime.data.voucher_shop_catalog = None
    elif mode in {"expired", "unaffordable", "forbidden"}:
        with runtime.database.transaction() as session:
            if mode == "expired":
                session.get(m.ServerClockState, 1).fixed_at = NOW + 300
            elif mode == "unaffordable":
                session.get(m.Currency, (1, "4004")).balance = 0
            else:
                profile = session.get(m.PlayerProfile, 1)
                profile.flags = {**profile.flags, "featureBans": {"shop": [good]}}
    else:
        good = "unknown"
    before = runtime.sync(token)
    response = buy(client, token, name, good)
    assert response.status_code == {"missing": 503, "expired": 503, "unaffordable": 400,
                                    "forbidden": 403, "unknown": 404}[mode]
    assert runtime.sync(token) == before


def test_literal_boolean_mode_is_rejected(runtime):
    value = catalog_value(runtime.data, runtime.settings.client_profile)
    value["cycles"][0]["type"] = True
    with pytest.raises(ValueError, match="type"):
        load_value(runtime, value)
