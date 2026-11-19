"""Synthetic originite quotes and transaction boundaries, not official sales."""
import copy
import hashlib
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from terralocal.server.compatibility.profile import ClientCompatibilityProfile
from terralocal.server.domain import cash_shop
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.cash_shop import frozen_products, read_catalog, write_catalog
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import REVISION, VOUCHER_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def cash(runtime):
    settings = runtime.settings
    profile = ClientCompatibilityProfile(id=settings.client_profile, package="synthetic.test", channel="official",
        client_version="2.7.71", version_code=190, apk_sha256="0" * 64, resource_version="synthetic-resource",
        api_version="V070", gamedata_hash=settings.gamedata_hash)
    profile.save(settings.data_dir / "profiles" / (profile.id + ".json"))
    products = {"productList": [{"product_id": good, "store_id": store, "price": price * 100,
        "status": 1, "platform": 1, "app_id": 1, "channel_id": 1, "world_id": 0,
        "name": "Synthetic " + good} for good, store, price in (("single", 11, 6), ("group", 12, 30))]}
    root = settings.data_dir / "client" / "bootstrap" / profile.id
    root.mkdir(parents=True)
    raw = json.dumps(products).encode()
    sdk_hash = hashlib.sha256(raw).hexdigest()
    (root / "sdk_products.json").write_bytes(raw)
    (root / "sources.json").write_text(json.dumps({"sdk_products": {"sha256": sdk_hash}}), "utf-8")
    value = {"schema_version": 1, "gamedata_hash": settings.gamedata_hash, "client_profile": profile.id,
        "sdk_products_sha256": sdk_hash, "catalog_id": "synthetic-cash", "mode": "custom",
        "provenance": "Authored synthetic cash supply; no claim of official prices or rewards.",
        "purchase_mode": "local-simulated", "first_purchase_scope": "good-id", "startTime": -1, "endTime": -1,
        "offers": [{"goodId": good, "storeId": store, "productName": "Synthetic " + good, "slotId": slot,
            "price": price, "diamondNum": base, "doubleCount": first, "plusNum": extra, "desc": "Synthetic"}
            for good, store, slot, price, base, first, extra in (("single", 11, 1, 6, 1, 3, 0),
                                                               ("group", 12, 2, 30, 6, 12, 1))]}
    path = settings.data_dir / "cash_shop.json"
    path.write_text(json.dumps(value), "utf-8")
    catalog = read_catalog(path, runtime.data, settings.client_profile, products, sdk_hash)
    runtime.cash_shop_catalog = runtime.data.cash_shop_catalog = catalog
    return value, products, sdk_hash


def create(client, token, good="single", store=11, key="create", **extra):
    return client.post("/pay/createOrder", headers={"secret": token, "seqnum": key},
                       json={"goodId": good, "storeId": store, **extra})


def confirm(client, token, order, key="confirm", **extra):
    return client.post("/pay/confirmOrder", headers={"secret": token, "seqnum": key},
                       json={"orderId": order, "enterTs": -1, **extra})


def approve(runtime, created, account=1, extension=None):
    # Explicit direct-domain test preparation. Native SDK integration is a
    # separate gate, and this helper does not claim to have exercised Java.
    with runtime.database.transaction() as session:
        cash_shop.approve(Context(session, runtime.data, account), created["orderId"],
                          created["extension"] if extension is None else extension)


def balance(runtime, account=1):
    with runtime.database.transaction(write=False) as session:
        return Context(session, runtime.data, account).balance("4002")


def test_cash_list_is_native_shaped_account_scoped_and_read_only(client, runtime, token, cash):
    before = runtime.sync(token)
    result = client.post("/shop/getCashGoodList", json={}, headers={"secret": token})
    assert result.status_code == 200
    assert result.json()["goodList"] == [{k: v for k, v in o.items() if k not in {"storeId", "productName"}}
                                        for o in cash[0]["offers"]]
    assert result.json()["playerDataDelta"]["modified"]["shop"] == {"CASH": {"info": []}}
    assert runtime.sync(token) == before
    assert client.post("/shop/getCashGoodList", json={}).status_code == 401
    assert client.post("/shop/getCashGoodList", json={"arbitrary": 1}, headers={"secret": token}).status_code == 422


def test_cash_list_requires_explicit_matching_supply(client, token):
    assert client.post("/shop/getCashGoodList", json={}, headers={"secret": token}).status_code == 503


def test_quote_does_not_grant_or_consume_first_purchase_and_retries_are_identical(client, runtime, token, cash):
    initial = balance(runtime)
    first = create(client, token).json()
    assert set(first) == {"result", "orderId", "extension", "orderIdList", "alertMinor", "errMsg"}
    assert first["result"] == 0 and first["orderId"].startswith("TL-") and first["orderIdList"] == []
    assert create(client, token).json() == first
    assert balance(runtime) == initial
    assert runtime.sync(token)["user"]["shop"]["CASH"] == {"info": []}
    with runtime.database.transaction(write=False) as session:
        assert len(Context(session, runtime.data, 1).rows(m.LocalOrder)) == 1
        assert Context(session, runtime.data, 1).rows(m.LocalCashOrder)[0].approved_at is None
    assert confirm(client, token, first["orderId"]).status_code == 409
    assert client.post("/pay/getUnconfirmedOrderIdList", json={}, headers={"secret": token}).json()["orderIdList"] == []
    assert create(client, token, store=12).status_code == 409  # Same key/different request.
    assert create(client, token, store=12, key="mismatch").status_code == 404
    assert create(client, token, key="spoof", price=0).status_code == 422


def test_first_total_repeat_total_and_global_order_idempotence(client, runtime, token, cash):
    before = runtime.sync(token)["user"]
    initial = balance(runtime)
    first = create(client, token).json()
    approve(runtime, first)
    assert client.post("/pay/getUnconfirmedOrderIdList", json={}, headers={"secret": token}).json()["orderIdList"] == [first["orderId"]]
    result = confirm(client, token, first["orderId"]).json()
    assert result["receiveItems"] == {"items": [{"id": "4002", "type": "DIAMOND", "count": 3}],
                                      "checkInItems": []}
    assert balance(runtime) == initial + 3
    assert apply(before, result["playerDataDelta"]) == runtime.sync(token)["user"]
    second = create(client, token, key="create2").json()
    approve(runtime, second)
    repeat = confirm(client, token, second["orderId"], key="confirm2").json()
    assert repeat["receiveItems"]["items"][0]["count"] == 1
    assert balance(runtime) == initial + 4
    # Replaying the original receipt must reassert the current balance,
    # rather than undoing the second purchase's delta on a stale client.
    replay = confirm(client, token, first["orderId"]).json()
    assert replay["playerDataDelta"]["modified"]["status"]["freeDiamond"] == initial + 4
    with runtime.database.transaction() as session:
        newer = login(session, runtime.settings, name="Doctor")["secret"]
    again = confirm(client, newer, first["orderId"], key="new-session").json()
    assert again["receiveItems"] == result["receiveItems"] and balance(runtime) == initial + 4
    with runtime.database.transaction(write=False) as session:
        assert len(Context(session, runtime.data, 1).rows(m.PurchaseHistory)) == 2
        assert session.get(m.ShopState, (1, "CASH", "single", "permanent")).bought == 2


def test_first_bonus_applies_once_when_two_paid_quotes_confirm_concurrently(client, runtime, token, cash):
    initial = balance(runtime)
    quotes = [create(client, token, good="group", store=12, key=f"create-{i}").json() for i in range(2)]
    for quote in quotes:
        approve(runtime, quote)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: confirm(client, token, p[1]["orderId"], key=f"confirm-{p[0]}"),
                                enumerate(quotes)))
    assert all(r.status_code == 200 for r in results)
    assert sorted(r.json()["receiveItems"]["items"][0]["count"] for r in results) == [7, 12]
    assert balance(runtime) == initial + 19
    with ThreadPoolExecutor(max_workers=2) as pool:
        retries = list(pool.map(lambda i: confirm(client, token, quotes[0]["orderId"], key=f"retry-{i}"), range(2)))
    assert all(r.status_code == 200 for r in retries) and balance(runtime) == initial + 19


def test_u8_callback_requires_capability_and_sdk_success_never_grants_game_rewards(client, runtime, token, cash):
    created = create(client, token).json()
    with runtime.database.transaction(write=False) as session:
        uid = session.get(m.Account, 1).uid
    body = {"uid": uid, "orderId": created["orderId"], "extension": created["extension"]}
    assert client.post("/u8/pay/confirmOrderState", json={**body, "extension": ""}).status_code == 401
    assert client.post("/u8/pay/confirmOrderState", json={**body, "uid": "foreign"}).status_code == 404
    assert client.post("/u8/pay/confirmOrderState", json={**body, "payState": 3}).status_code == 422
    assert client.post("/u8/pay/confirmOrderState", json=body).json() == {"payState": 3}
    assert client.post("/u8/pay/confirmOrderState", json=body).json() == {"payState": 3}
    assert balance(runtime) == 0
    # A native cold restart loses the extension. Empty-extension polling may
    # read this paid local order, but could not authorize its first approval.
    assert client.post("/u8/pay/confirmOrderState", json={**body, "extension": ""}).json() == {"payState": 3}
    assert confirm(client, token, created["orderId"]).json()["receiveItems"]["items"][0]["count"] == 3
    assert client.post("/u8/pay/confirmOrderState", json={**body, "extension": ""}).json() == {"payState": 3}
    assert balance(runtime) == 3


def test_native_pending_orders_branch_prevents_new_unpaid_quote_until_paid_order_is_claimed(client, runtime, token, cash):
    paid = create(client, token).json()
    approve(runtime, paid)
    pending = create(client, token, key="pending").json()
    assert pending == {"result": 2, "orderId": "", "extension": "", "orderIdList": [paid["orderId"]],
                       "alertMinor": False, "errMsg": ""}
    with runtime.database.transaction(write=False) as session:
        assert len(Context(session, runtime.data, 1).rows(m.LocalOrder)) == 1
    confirm(client, token, paid["orderId"])
    assert create(client, token, key="after-claim").json()["result"] == 0


def test_callback_proof_tampering_other_account_and_missing_quote_cannot_approve(client, runtime, token, cash):
    created = create(client, token).json()
    bad = json.loads(created["extension"])
    with runtime.database.transaction() as session:
        other = create_account(session, runtime.data, "Other")
        other_token = login(session, runtime.settings, name="Other")["secret"]
    for change in ({"receipt": "X" * 43}, {"goodId": "group"}, {"orderId": "TL-other"},
                   {"terralocal": False}, {"terralocal": 1}, {"unknown": True}):
        with pytest.raises(DomainError):
            approve(runtime, created, extension=json.dumps({**bad, **change}))
    with pytest.raises(DomainError):
        approve(runtime, created, account=other.id)
    assert confirm(client, other_token, created["orderId"]).status_code == 404
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.LocalCashOrder, (1, created["orderId"])).approved_at is None
    assert balance(runtime) == 0


def test_approved_order_uses_quote_after_catalog_changes_or_closes(client, runtime, token, cash):
    created = create(client, token).json()
    approve(runtime, created)
    changed = runtime.cash_shop_catalog.model_copy(deep=True)
    changed.offers[0].doubleCount = 100
    changed.endTime = 1
    runtime.cash_shop_catalog = runtime.data.cash_shop_catalog = changed
    assert create(client, token, key="closed").status_code == 409
    result = confirm(client, token, created["orderId"])
    assert result.status_code == 200 and result.json()["receiveItems"]["items"][0]["count"] == 3


def test_unapproved_order_expiry_clock_rewind_and_counter_persistence(client, runtime, token, cash):
    old = create(client, token).json()
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 3600
    with pytest.raises(DomainError):
        approve(runtime, old)
    new = create(client, token, key="new").json()
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.LocalOrder, (1, old["orderId"])).state == "CANCELLED"
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at -= 7200
    with pytest.raises(DomainError):
        approve(runtime, old)
    approve(runtime, new)
    assert confirm(client, token, new["orderId"]).status_code == 200
    assert confirm(client, token, old["orderId"], key="old").status_code == 409


def test_failed_inventory_credit_rolls_back_order_counter_and_history(client, runtime, token, cash):
    created = create(client, token).json()
    approve(runtime, created)
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).change_item("4002", 2_000_000_000)
    assert confirm(client, token, created["orderId"]).status_code == 400
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.LocalOrder, (1, created["orderId"])).state == "READY"
        assert session.get(m.LocalCashOrder, (1, created["orderId"])).fulfillment is None
        assert Context(session, runtime.data, 1).rows(m.PurchaseHistory) == []
        assert session.get(m.ShopState, (1, "CASH", "single", "permanent")) is None
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).change_item("4002", -2_000_000_000)
    assert confirm(client, token, created["orderId"]).json()["receiveItems"]["items"][0]["count"] == 3


def test_cash_pending_order_and_first_counter_survive_restart_and_backup_restore(client, runtime, token, cash):
    old = create(client, token).json()
    approve(runtime, old)
    service = BackupService(runtime)
    saved = service.create()
    assert saved["cash_catalog_hash"] == fingerprint(runtime.cash_shop_catalog.model_dump())
    confirm(client, token, old["orderId"])
    service.restore(saved["name"])
    assert balance(runtime) == 0
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(restarted)) as fresh:
            assert confirm(fresh, token, old["orderId"]).json()["receiveItems"]["items"][0]["count"] == 3
            assert confirm(fresh, token, old["orderId"], key="global-retry").status_code == 200
            assert balance(restarted) == 3
    finally:
        restarted.database.close()


def test_0012_upgrade_is_additive_and_repeatable(runtime, token, cash):
    before = runtime.sync(token)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("DROP TABLE local_cash_orders")
        con.execute("UPDATE alembic_version SET version_num=?", (VOUCHER_REVISION,))
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == before
        restarted.database.initialize()
        assert restarted.sync(token) == before
        with sqlite3.connect(restarted.database.path) as con:
            assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
            assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        restarted.database.close()




@pytest.mark.parametrize("change", [{"sdk_products_sha256": "0" * 64}, {"client_profile": "different"},
                                  {"gamedata_hash": "0" * 64}, {"purchase_mode": "official-payment"},
                                  {"first_purchase_scope": "monthly"}])
def test_catalog_rejects_wrong_bindings_before_database_migration(runtime, cash, change):
    path = runtime.settings.data_dir / "cash_shop.json"
    path.write_text(json.dumps({**cash[0], **change}), "utf-8")
    runtime.database.close()
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("change", [{"storeId": 99}, {"price": 600}, {"diamondNum": True},
                                  {"doubleCount": 0}, {"plusNum": -1}, {"productName": "mismatch"}])
def test_catalog_rejects_invalid_sdk_pair_price_or_reward(runtime, cash, change):
    value = copy.deepcopy(cash[0])
    value["offers"][0].update(change)
    path = runtime.settings.data_dir / "candidate.json"
    path.write_text(json.dumps(value), "utf-8")
    with pytest.raises(ValueError):
        read_catalog(path, runtime.data, runtime.settings.client_profile, cash[1], cash[2])


def test_catalog_retains_original_bytes_snapshots_and_restore_rejects_mismatch(runtime, cash):
    path = runtime.settings.data_dir / "cash_shop.json"
    old = path.read_bytes()
    saved = BackupService(runtime).create()
    snapshot = write_catalog(runtime.cash_shop_catalog, runtime.settings.data_dir)
    assert snapshot.exists()
    assert (runtime.settings.data_dir / "cash-catalogs" / (hashlib.sha256(old).hexdigest() + ".json")).read_bytes() == old
    runtime.cash_shop_catalog = runtime.cash_shop_catalog.model_copy(update={"catalog_id": "another"})
    with pytest.raises(ValueError, match="不同的商店目录"):
        BackupService(runtime).restore(saved["name"])
    assert frozen_products(runtime.settings)[1] == cash[2]


def test_login_snapshot_includes_approved_reward_until_native_claim_acknowledges(client, runtime, token, cash):
    created = create(client, token).json()
    approve(runtime, created)
    before = balance(runtime)
    first = client.post('/account/syncData', headers={'secret': token}, json={})
    assert first.status_code == 200
    assert first.json()['user']['status']['freeDiamond'] == before + 3
    assert first.json()['user']['shop']['CASH']['info'] == [{'id': 'single', 'count': 1}]
    assert client.post('/pay/getUnconfirmedOrderIdList', headers={'secret': token}, json={}).json()['orderIdList'] == [created['orderId']]
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.LocalOrder, (1, created['orderId'])).state == 'CONFIRMED'
        assert session.get(m.LocalCashClaim, (1, created['orderId'])) is None
    assert create(client, token, key='blocked-before-ack').json()['result'] == 2
    assert confirm(client, token, created['orderId']).json()['receiveItems']['items'][0]['count'] == 3
    assert balance(runtime) == before + 3
    assert client.post('/pay/getUnconfirmedOrderIdList', headers={'secret': token}, json={}).json()['orderIdList'] == []
    assert confirm(client, token, created['orderId'], key='new-session-retry').status_code == 200
    assert runtime.sync(token)['user']['status']['freeDiamond'] == before + 3
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.LocalCashClaim, (1, created['orderId'])) is not None
        assert len(session.query(m.AuditLog).filter_by(action='local-cash-acknowledge').all()) == 1


def test_sync_never_credits_unpaid_quotes_or_other_accounts(client, runtime, token, cash):
    unpaid = create(client, token).json()
    paid = create(client, token, key='paid').json()
    approve(runtime, paid)
    with runtime.database.transaction() as session:
        create_account(session, runtime.data, 'Other')
        other = login(session, runtime.settings, name='Other')['secret']
    before = balance(runtime)
    runtime.sync(other)
    assert balance(runtime) == before
    runtime.sync(token)
    assert balance(runtime) == before + 3
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.LocalOrder, (1, unpaid['orderId'])).state == 'READY'
        assert session.get(m.LocalCashOrder, (1, unpaid['orderId'])).approved_at is None
        assert Context(session, runtime.data, 2).balance('4002') == 0


def test_reconcile_multiple_approved_quotes_consumes_first_bonus_once(client, runtime, token, cash):
    quotes = [create(client, token, key=str(i)).json() for i in range(2)]
    for quote in quotes:
        approve(runtime, quote)
    before = balance(runtime)
    snapshot = runtime.sync(token)
    assert snapshot['user']['status']['freeDiamond'] == before + 4
    assert snapshot['user']['shop']['CASH']['info'] == [{'id': 'single', 'count': 2}]
    assert runtime.sync(token)['user']['status']['freeDiamond'] == before + 4
    counts = sorted(confirm(client, token, q['orderId'], key='ack-' + str(i)).json()['receiveItems']['items'][0]['count']
                    for i, q in enumerate(quotes))
    assert counts == [1, 3]
    assert balance(runtime) == before + 4


def test_reconcile_rolls_back_every_order_if_later_credit_overflows(client, runtime, token, cash):
    quotes = [create(client, token, key=str(i)).json() for i in range(2)]
    for quote in quotes:
        approve(runtime, quote)
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).change_item('4002', 1_999_999_997)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert balance(runtime) == 1_999_999_997
    with runtime.database.transaction(write=False) as session:
        assert all(session.get(m.LocalOrder, (1, q['orderId'])).state == 'READY' for q in quotes)
        assert session.query(m.ShopState).filter_by(shop_id='CASH').count() == 0
        assert session.query(m.PurchaseHistory).filter_by(shop_id='CASH').count() == 0
        assert session.query(m.LocalCashClaim).count() == 0


def test_0013_additive_claim_migration_does_not_relist_old_confirmed_orders(client, runtime, token, cash):
    from terralocal.server.persistence.migrations import CASH_REVISION

    done = create(client, token).json()
    approve(runtime, done)
    assert confirm(client, token, done['orderId']).status_code == 200
    pending = create(client, token, key='pending').json()
    approve(runtime, pending)
    with sqlite3.connect(runtime.settings.database_path) as con:
        con.execute('DROP TABLE local_cash_claims')
        con.execute('UPDATE alembic_version SET version_num=?', (CASH_REVISION,))
        con.commit()
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if r[0] != 'alembic_version']
        before = {t: con.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall() for t in tables}
    runtime.database.initialize()
    runtime.database.initialize()
    with sqlite3.connect(runtime.settings.database_path) as con:
        assert {t: con.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall() for t in tables} == before
        assert con.execute('SELECT version_num FROM alembic_version').fetchone()[0] == REVISION
        assert con.execute('SELECT count(*) FROM local_cash_claims').fetchone()[0] == 1
    assert client.post('/pay/getUnconfirmedOrderIdList', headers={'secret': token}, json={}).json()['orderIdList'] == [pending['orderId']]


def test_simultaneous_snapshot_and_claim_do_not_double_credit(client, runtime, token, cash):
    created = create(client, token).json()
    approve(runtime, created)
    before = balance(runtime)
    with ThreadPoolExecutor(max_workers=2) as pool:
        snapshot = pool.submit(runtime.sync, token)
        claimed = pool.submit(confirm, client, token, created['orderId'])
        assert snapshot.result()['user']['status']['freeDiamond'] == before + 3
        assert claimed.result().status_code == 200
    assert balance(runtime) == before + 3
    assert client.post('/pay/getUnconfirmedOrderIdList', headers={'secret': token}, json={}).json()['orderIdList'] == []


def test_reconciled_unacknowledged_order_survives_process_restart(client, runtime, token, cash):
    created = create(client, token).json()
    approve(runtime, created)
    before = balance(runtime)
    runtime.sync(token)
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        native = TestClient(create_game_app(reopened))
        assert reopened.sync(token)['user']['status']['freeDiamond'] == before + 3
        assert native.post('/pay/getUnconfirmedOrderIdList', headers={'secret': token}, json={}).json()['orderIdList'] == [created['orderId']]
        assert confirm(native, token, created['orderId']).status_code == 200
        assert balance(reopened) == before + 3
        assert native.post('/pay/getUnconfirmedOrderIdList', headers={'secret': token}, json={}).json()['orderIdList'] == []
    finally:
        reopened.database.close()


def test_backup_restore_preserves_reward_without_losing_pending_native_ack(client, runtime, token, cash):
    created = create(client, token).json()
    approve(runtime, created)
    before = balance(runtime)
    runtime.sync(token)
    service = BackupService(runtime)
    saved = service.create()
    assert confirm(client, token, created['orderId']).status_code == 200
    assert client.post('/pay/getUnconfirmedOrderIdList', headers={'secret': token}, json={}).json()['orderIdList'] == []
    service.restore(saved['name'])
    assert runtime.sync(token)['user']['status']['freeDiamond'] == before + 3
    assert client.post('/pay/getUnconfirmedOrderIdList', headers={'secret': token}, json={}).json()['orderIdList'] == [created['orderId']]
    assert confirm(client, token, created['orderId'], key='after-restore').status_code == 200
    assert balance(runtime) == before + 3
