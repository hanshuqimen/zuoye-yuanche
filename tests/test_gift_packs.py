"""Owned synthetic GP supply; these tests do not claim official supply fidelity."""
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from pydantic import ValidationError

from terralocal.server.compatibility.profile import ClientCompatibilityProfile
from terralocal.server.domain import cash_shop, gift_packs
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.cash_shop import CashShopCatalog
from terralocal.server.gamedata.gift_packs import (
    GiftPackCatalog,
    admit_catalog,
    preflight_saved_catalog,
    read_catalog,
    write_catalog,
)
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def packs(runtime):
    settings = runtime.settings
    profile = ClientCompatibilityProfile(id=settings.client_profile, package="synthetic.test", channel="official",
        client_version="2.7.71", version_code=190, apk_sha256="0" * 64, resource_version="synthetic-resource",
        api_version="V070", gamedata_hash=settings.gamedata_hash)
    profile.save(settings.data_dir / "profiles" / (profile.id + ".json"))
    products = {"productList": [{"product_id": g, "store_id": s, "price": p * 100, "status": 1,
        "platform": 1, "app_id": 1, "channel_id": 1, "world_id": 0, "name": "Synthetic " + g}
        for g, s, p in (("origin", 11, 6), ("pack", 21, 30), ("weekly", 22, 10))]}
    root = settings.data_dir / "client" / "bootstrap" / profile.id
    root.mkdir(parents=True)
    raw = json.dumps(products).encode()
    sdk_hash = hashlib.sha256(raw).hexdigest()
    (root / "sdk_products.json").write_bytes(raw)
    (root / "sources.json").write_text(json.dumps({"sdk_products": {"sha256": sdk_hash}}), "utf-8")

    def offer(good, section="oneTime", currency="DIAMOND", price=1, limit=2, **extra):
        return {"section": section, "goodId": good, "giftPackageId": good + "-image", "priority": 1,
                "displayName": "Synthetic " + good, "currencyUnit": currency, "availCount": limit,
                "price": price, "originPrice": price, "discount": 1.0, "items": [
                    {"id": "material", "type": "MATERIAL", "count": 5}],
                "startDateTime": -1, "endDateTime": -1, "tab": ["Synthetic"], **extra}

    value = {"schema_version": 1, "gamedata_hash": settings.gamedata_hash, "client_profile": profile.id,
        "sdk_products_sha256": sdk_hash, "catalog_id": "synthetic-packs", "mode": "custom",
        "provenance": "Authored GP fixtures; no official supply or visual claim.", "purchase_mode": "local-simulated",
        "offers": [offer("diamond"), offer("level", "level", price=0, limit=1, playerLevel=3),
            offer("pack", currency="CASH", price=30, limit=1, storeId=21, productName="Synthetic pack")],
        "cycles": [{"section": "weekly", "period": period, "groupId": group,
                    "startDateTime": start, "endDateTime": end, "offers": [
                        offer("weekly", "weekly", "CASH", 10, 1, storeId=22, productName="Synthetic weekly")]} for
                   period, group, start, end in (("week-A", "group-A", 1_799_999_900, 1_800_000_100),
                                                ("week-B", "group-B", 1_800_000_100, 1_800_000_300))]}
    path = settings.data_dir / "gift_packs.json"
    path.write_text(json.dumps(value), "utf-8")
    catalog = read_catalog(path, runtime.data, settings.client_profile, products, sdk_hash)
    runtime.gift_pack_catalog = runtime.data.gift_pack_catalog = catalog
    admit_catalog(catalog, runtime.database)
    runtime.cash_shop_catalog = runtime.data.cash_shop_catalog = CashShopCatalog.model_validate({
        "schema_version": 1, "gamedata_hash": settings.gamedata_hash, "client_profile": profile.id,
        "sdk_products_sha256": sdk_hash, "catalog_id": "synthetic-cash", "mode": "custom",
        "provenance": "Synthetic coexistence fixture", "purchase_mode": "local-simulated",
        "first_purchase_scope": "good-id", "startTime": -1, "endTime": -1,
        "offers": [{"goodId": "origin", "storeId": 11, "productName": "Synthetic origin", "slotId": 1,
                    "price": 6, "diamondNum": 1, "doubleCount": 3, "plusNum": 0, "desc": "Synthetic"}]})
    (settings.data_dir / "cash_shop.json").write_text(json.dumps(runtime.cash_shop_catalog.model_dump()), "utf-8")
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).change_item("4002", 5)
    return value, products, sdk_hash


def purchase(client, token, good="diamond", key="buy", **extra):
    return client.post("/shop/buyGPGood", headers={"secret": token, "seqnum": key},
                       json={"goodId": good, "enterTs": -1, **extra})


def create(client, token, good="pack", store=21, key="quote"):
    return client.post("/pay/createOrder", headers={"secret": token, "seqnum": key},
                       json={"goodId": good, "storeId": store})


def approve(client, runtime, quoted, account=1, extension=None):
    with runtime.database.transaction(write=False) as session:
        uid = session.get(m.Account, account).uid
    return client.post("/u8/pay/confirmOrderState", json={"uid": uid, "orderId": quoted["orderId"],
        "extension": quoted["extension"] if extension is None else extension})


def confirm(client, token, order, key="confirm"):
    return client.post("/pay/confirmOrder", json={"orderId": order, "enterTs": -1},
                       headers={"secret": token, "seqnum": key})


def test_list_requires_supply_authentication_and_actual_empty_request(client, token):
    assert client.post("/shop/getGPGoodList", json={}).status_code == 401
    assert client.post("/shop/getGPGoodList", json={}, headers={"secret": token}).status_code == 503
    assert client.post("/shop/getGPGoodList", json={"fake": 1}, headers={"secret": token}).status_code == 422


def test_native_list_eight_categories_and_account_progress_are_reads(client, runtime, token, packs):
    before = runtime.sync(token)
    response = client.post("/shop/getGPGoodList", json={}, headers={"secret": token})
    assert response.status_code == 200
    body = response.json()
    assert body["weeklyGroup"]["groupId"] == "group-A"
    assert body["weeklyGroup"]["packages"]["weekly"]["groupId"] == "group-A"
    assert set(body) == {"result", "ts", "playerDataDelta", "weeklyGroup", "monthlyGroup", "monthlySub",
                         "levelGP", "oneTimeGP", "chooseGroup", "condtionTriggerGroup", "conditionChooseGroup"}
    assert body["monthlyGroup"] == {"groupId": "", "startDateTime": 0, "endDateTime": 0, "packages": {}}
    assert body["monthlySub"] == []
    assert body["oneTimeGP"][0]["buyCount"] == 0
    assert "storeId" not in body["oneTimeGP"][1]
    assert set(body["playerDataDelta"]["modified"]["shop"]["GP"]) == {
        "oneTime", "level", "weekly", "monthly", "choose", "conditionChoose"}
    assert runtime.sync(token) == before


def test_normal_purchase_uses_wallet_and_atomic_rewards_with_current_retry_delta(client, runtime, token, packs):
    before = runtime.sync(token)["user"]
    first = purchase(client, token)
    assert first.status_code == 200 and first.json()["items"] == [{"id": "material", "type": "MATERIAL", "count": 5}]
    assert apply(before, first.json()["playerDataDelta"]) == runtime.sync(token)["user"]
    assert purchase(client, token, key="second").status_code == 200
    after = runtime.sync(token)["user"]
    retry = purchase(client, token)
    assert retry.json()["items"] == first.json()["items"]
    assert apply(before, retry.json()["playerDataDelta"]) == after
    assert after["status"]["freeDiamond"] == 3 and after["inventory"]["material"] == 10
    assert purchase(client, token, key="soldout").status_code == 409
    assert runtime.sync(token)["user"] == after
    assert purchase(client, token, good="level").status_code == 409  # Same key/different request.
    assert purchase(client, token, price=0).status_code == 422


def test_level_gate_free_reward_and_insufficient_wallet_rollback(client, runtime, token, packs):
    before = runtime.sync(token)["user"]
    assert purchase(client, token, good="level", key="locked").status_code == 409
    assert runtime.sync(token)["user"] == before
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        ctx.profile.level = 3
        ctx.change_item("4002", -5)
    locked_balance = runtime.sync(token)["user"]
    assert purchase(client, token, key="no-money").status_code == 400
    assert runtime.sync(token)["user"] == locked_balance
    assert purchase(client, token, "level", "free").status_code == 200
    assert runtime.sync(token)["user"]["status"]["freeDiamond"] == 0


def test_pack_sdk_approval_is_not_fulfillment_and_unpaid_quotes_are_not_pending(client, runtime, token, packs):
    quoted = create(client, token).json()
    assert quoted["result"] == 0
    assert create(client, token).json() == quoted
    assert client.post("/pay/getUnconfirmedOrderIdList", json={}, headers={"secret": token}).json()["orderIdList"] == []
    assert create(client, token, key="reserved").status_code == 409
    assert purchase(client, token, "pack", "wrong-path").status_code == 409
    assert confirm(client, token, quoted["orderId"]).status_code == 409
    assert approve(client, runtime, quoted, extension="").status_code == 401
    assert approve(client, runtime, quoted).json() == {"payState": 3}
    with runtime.database.transaction(write=False) as session:
        assert Context(session, runtime.data, 1).balance("material") == 0
    pending = create(client, token, "origin", 11, "pending").json()
    assert pending["result"] == 2 and pending["orderIdList"] == [quoted["orderId"]]
    received = confirm(client, token, quoted["orderId"]).json()
    assert received["receiveItems"]["items"][0]["count"] == 5
    assert received["receiveItems"]["checkInItems"] == []
    assert approve(client, runtime, quoted, extension="").json() == {"payState": 3}
    assert create(client, token, "origin", 11, "after-claim").json()["result"] == 0


def test_native_pending_queue_includes_both_quote_kinds_after_login_recovery(client, runtime, token, packs):
    pack = create(client, token).json()
    origin = create(client, token, "origin", 11, "origin").json()
    assert approve(client, runtime, pack).status_code == 200
    with runtime.database.transaction() as session:
        cash_shop.approve(Context(session, runtime.data, 1), origin["orderId"], origin["extension"])
    user = runtime.sync(token)["user"]
    assert user["status"]["freeDiamond"] == 8 and user["inventory"]["material"] == 5
    assert runtime.sync(token)["user"] == user
    pending = client.post("/pay/getUnconfirmedOrderIdList", json={}, headers={"secret": token}).json()["orderIdList"]
    assert set(pending) == {pack["orderId"], origin["orderId"]}
    for i, order in enumerate(pending):
        assert confirm(client, token, order, "confirm-" + str(i)).status_code == 200
    assert runtime.sync(token)["user"] == user
    assert client.post("/pay/getUnconfirmedOrderIdList", json={}, headers={"secret": token}).json()["orderIdList"] == []


def test_concurrent_one_time_reservations_and_confirmation_do_not_duplicate(client, runtime, token, packs):
    with ThreadPoolExecutor(max_workers=2) as pool:
        quotes = list(pool.map(lambda i: create(client, token, key="quote-" + str(i)), range(2)))
    assert sorted(q.status_code for q in quotes) == [200, 409]
    quoted = next(q.json() for q in quotes if q.status_code == 200)
    approve(client, runtime, quoted)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: confirm(client, token, quoted["orderId"], "confirm-" + str(i)), range(2)))
    assert all(r.status_code == 200 for r in results)
    assert runtime.sync(token)["user"]["inventory"]["material"] == 5
    with runtime.database.transaction(write=False) as session:
        assert len(Context(session, runtime.data, 1).rows(m.PurchaseHistory)) == 1
        assert len(Context(session, runtime.data, 1).rows(m.LocalPackClaim)) == 1


def test_approved_quote_keeps_rewards_and_old_cycle_across_rollover_and_rewind(client, runtime, token, packs):
    quoted = create(client, token, "weekly", 22).json()
    assert approve(client, runtime, quoted).status_code == 200
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 100
    assert confirm(client, token, quoted["orderId"]).status_code == 200
    assert runtime.sync(token)["user"]["shop"]["GP"]["weekly"]["info"] == []
    newer = create(client, token, "weekly", 22, "new-week").json()
    assert approve(client, runtime, newer).status_code == 200
    assert confirm(client, token, newer["orderId"], "new-week-confirm").status_code == 200
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at -= 100
    assert create(client, token, "weekly", 22, "old-week").status_code == 409
    assert runtime.sync(token)["user"]["inventory"]["material"] == 10
    with runtime.database.transaction(write=False) as session:
        states = Context(session, runtime.data, 1).rows(m.ShopState)
        assert {(r.period, r.bought) for r in states if r.shop_id == "GP:weekly"} == {("week-A", 1), ("week-B", 1)}


def test_capability_account_isolation_and_inventory_failure_preserve_approved_order(client, runtime, token, packs):
    quoted = create(client, token).json()
    with runtime.database.transaction() as session:
        other = create_account(session, runtime.data, "Other")
        other_token = login(session, runtime.settings, name="Other")["secret"]
    assert approve(client, runtime, quoted, other.id).status_code == 404
    assert confirm(client, other_token, quoted["orderId"]).status_code == 404
    proof = json.loads(quoted["extension"])
    for change in ({"terralocal": 1}, {"receipt": "X" * 43}, {"goodId": "origin"}, {"unknown": True}):
        assert approve(client, runtime, quoted, extension=json.dumps({**proof, **change})).status_code == 401
    assert approve(client, runtime, quoted).status_code == 200
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).change_item("material", 2_000_000_000)
    assert confirm(client, token, quoted["orderId"]).status_code == 400
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.LocalOrder, (1, quoted["orderId"])).state == "READY"
        assert session.get(m.LocalPackClaim, (1, quoted["orderId"])) is None
        assert session.get(m.ShopState, (1, "GP:oneTime", "pack", "permanent")) is None
        assert Context(session, runtime.data, 1).rows(m.PurchaseHistory) == []
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).change_item("material", -10)
    assert confirm(client, token, quoted["orderId"], "retry-credit").status_code == 200


def test_expired_unpaid_quote_cancels_without_resetting_cycle_or_exposing_legacy_pending(client, runtime, token, packs):
    quoted = create(client, token, "weekly", 22).json()
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 100
    assert approve(client, runtime, quoted).json() == {"payState": 4}
    assert create(client, token, "weekly", 22, "next-cycle").status_code == 200
    with runtime.database.transaction() as session:
        assert session.get(m.LocalOrder, (1, quoted["orderId"])).state == "CANCELLED"
        session.get(m.ServerClockState, 1).fixed_at -= 100
    assert approve(client, runtime, quoted).json() == {"payState": 4}
    assert client.post("/pay/getUnconfirmedOrderIdList", json={}, headers={"secret": token}).json()["orderIdList"] == []


def test_catalog_rejects_mismatches_missing_rules_and_preserves_admitted_cycles(runtime, packs):
    value, products, digest = packs
    for change in ({"price": 1}, {"storeId": 999}, {"currencyUnit": "GOLD"},
                   {"currencyUnit": "DIAMOND_SHD"}, {"gpTicketIdList": ["coupon"]}):
        altered = json.loads(json.dumps(value))
        altered["offers"][2].update(change)
        with pytest.raises((ValueError, DomainError)):
            candidate = GiftPackCatalog.model_validate(altered)
            candidate.validate_data(runtime.data, runtime.settings.client_profile, products, digest)
    with pytest.raises(ValidationError):
        GiftPackCatalog.model_validate({**value, "offers": [], "cycles": []})
    with pytest.raises(ValueError):
        runtime.gift_pack_catalog.validate_data(runtime.data, runtime.settings.client_profile, products, "f" * 64)
    altered = runtime.gift_pack_catalog.model_copy(deep=True)
    altered.cycles[0].offers[0].items[0].count = 99
    with pytest.raises(ValueError):
        preflight_saved_catalog(altered, runtime.settings.database_path)
    with pytest.raises(ValueError):
        write_catalog(altered, runtime.settings.data_dir)
    assert json.loads((runtime.settings.data_dir / "gift_packs.json").read_text("utf-8")) == value


def test_restart_backup_restore_and_migration_preserve_cash_and_pack_receipts(client, runtime, token, packs):
    quoted = create(client, token).json()
    approve(client, runtime, quoted)
    confirm(client, token, quoted["orderId"])
    original = runtime.sync(token)["user"]
    backup = BackupService(runtime).create()
    assert backup["gift_pack_catalog_hash"]
    assert purchase(client, token).status_code == 200
    BackupService(runtime).restore(backup["name"])
    assert runtime.sync(token)["user"] == original
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == original
        with reopened.database.transaction(write=False) as session:
            assert gift_packs.pair(Context(session, reopened.data, 1), quoted["orderId"])[0].state == "CONFIRMED"
    finally:
        reopened.database.close()
    with closing(sqlite3.connect(runtime.settings.database_path)) as con:
        assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
        assert not con.execute("PRAGMA foreign_key_check").fetchall()


def test_paid_pack_uses_frozen_quote_after_supply_changes_and_claim_replay_keeps_newer_wallet(client, runtime, token, packs):
    quoted = create(client, token).json()
    approve(client, runtime, quoted)
    changed = runtime.gift_pack_catalog.model_copy(deep=True)
    changed.offers[2].items[0].count = 99
    changed.offers[2].endDateTime = 1
    runtime.gift_pack_catalog = runtime.data.gift_pack_catalog = changed
    assert confirm(client, token, quoted["orderId"]).json()["receiveItems"]["items"][0]["count"] == 5
    first = runtime.sync(token)["user"]
    assert purchase(client, token).status_code == 200
    second = runtime.sync(token)["user"]
    retry = confirm(client, token, quoted["orderId"]).json()
    assert retry["receiveItems"]["items"][0]["count"] == 5
    assert apply(first, retry["playerDataDelta"]) == second


def test_timed_rewards_and_wrong_reward_types_are_not_admitted_as_permanent_inventory(runtime, packs):
    value, products, digest = packs
    table = runtime.data.table("item_table")
    table["apSupplies"] = {"material": {"hasTs": True, "ap": 80}}
    with pytest.raises(ValueError, match="限时"):
        GiftPackCatalog.model_validate(value).validate_data(runtime.data, runtime.settings.client_profile, products, digest)
    table.pop("apSupplies")
    altered = json.loads(json.dumps(value))
    altered["offers"][0]["items"][0]["type"] = "DIAMOND"
    with pytest.raises(ValueError, match="类型"):
        GiftPackCatalog.model_validate(altered).validate_data(runtime.data, runtime.settings.client_profile, products, digest)


def test_0014_upgrade_creates_empty_pack_state_preserving_unacknowledged_cash(runtime, packs):
    # A freshly created 0014 unacknowledged cash receipt must never be seeded
    # as acknowledged by a later migration (unlike legacy 0013 behavior).
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        result = cash_shop.create(ctx, 11, "origin", runtime.protocol_profile)
        cash_shop.approve(ctx, result["orderId"], result["extension"])
        cash_shop.fulfill(ctx, result["orderId"], runtime.protocol_profile)
    with closing(sqlite3.connect(runtime.settings.database_path)) as con:
        retained = con.execute("SELECT * FROM local_cash_orders").fetchall()
        con.execute("DROP TABLE local_pack_claims")
        con.execute("DROP TABLE local_pack_orders")
        con.execute("UPDATE alembic_version SET version_num='0014_cash_claims'")
        con.commit()
    runtime.database.initialize()
    with closing(sqlite3.connect(runtime.settings.database_path)) as con:
        assert con.execute("SELECT * FROM local_cash_orders").fetchall() == retained
        assert con.execute("SELECT count(*) FROM local_cash_claims").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM local_pack_orders").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM local_pack_claims").fetchone()[0] == 0
        assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION


def test_purchase_refresh_recognizes_paid_gp_and_level_flag_matches_unclaimed_free_pack(client, runtime, token, packs):
    quoted = create(client, token).json()
    approve(client, runtime, quoted)
    confirm(client, token, quoted["orderId"])
    body = {"modules": 16, "params": {"16": {"goodIdMap": {"GP": ["pack", "level", "weekly"]}}}}
    response = client.post("/account/syncStatus", json=body, headers={"secret": token})
    assert response.status_code == 200
    assert response.json()["result"]["16"]["goodPurchaseState"]["result"] == {"pack": 1, "level": 0, "weekly": 1}
    assert runtime.sync(token)["user"]["pushFlags"]["hasFreeLevelGP"] is False
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).profile.level = 3
    assert runtime.sync(token)["user"]["pushFlags"]["hasFreeLevelGP"] is True
    assert purchase(client, token, "level", "free-level").status_code == 200
    assert runtime.sync(token)["user"]["pushFlags"]["hasFreeLevelGP"] is False


@pytest.mark.parametrize("good,store", [("pack", 21), ("origin", 11)])
def test_sdk_expiry_persists_cancellation_before_clock_rewind(client, runtime, token, packs, good, store):
    quoted = create(client, token, good, store).json()
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 3600
    assert approve(client, runtime, quoted).json() == {"payState": 4}
    with runtime.database.transaction() as session:
        assert session.get(m.LocalOrder, (1, quoted["orderId"])).state == "CANCELLED"
        session.get(m.ServerClockState, 1).fixed_at -= 7200
    assert approve(client, runtime, quoted).json() == {"payState": 4}
    assert confirm(client, token, quoted["orderId"]).status_code == 409
    with runtime.database.transaction(write=False) as session:
        assert Context(session, runtime.data, 1).rows(m.PurchaseHistory) == []
