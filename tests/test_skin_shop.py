"""Catalog provenance, normal purchases and persistence without official data."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_skin_rewards import CHAR, COSTUME, OTHER
from test_skin_rewards import skin_runtime as skin_runtime

from terralocal.server.domain import skin_shop
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.skin_shop import SkinShopCatalog, read_catalog
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

OTHER_COSTUME = f"{OTHER}@shop#1"


def catalog_value(runtime):
    return {"schema_version": 1, "gamedata_hash": runtime.data.manifest["hash"],
            "client_profile": runtime.settings.client_profile, "catalog_id": "synthetic-outfits",
            "mode": "custom", "provenance": "Authored synthetic offers; no official price claims.",
            "blindbox_supply": "closed", "offers": [
                {"goodId": "outfit-one", "skinId": COSTUME, "price": 18, "originPrice": 18,
                 "discount": 0.0, "slotId": 2, "startDateTime": -1, "endDateTime": -1},
                {"goodId": "outfit-two", "skinId": OTHER_COSTUME, "price": 15, "originPrice": 15,
                 "discount": 0.0, "slotId": 1, "startDateTime": 1_799_999_900,
                 "endDateTime": 1_800_000_100}]}


@pytest.fixture
def shop_runtime(skin_runtime):
    value = catalog_value(skin_runtime)
    path = skin_runtime.settings.data_dir / "skin_shop.json"
    path.write_text(json.dumps(value), "utf-8")
    skin_runtime.skin_shop_catalog = read_catalog(path, skin_runtime.data, skin_runtime.settings.client_profile)
    with skin_runtime.database.transaction() as session:
        Context(session, skin_runtime.data, 1).change_item("4002", 60)
    return skin_runtime


@pytest.fixture
def shop_client(shop_runtime):
    with TestClient(create_game_app(shop_runtime)) as client:
        yield client


def purchase(client, token, good="outfit-one", key="buy-once", **changes):
    return client.post("/shop/buySkinGood", headers={"secret": token, "seqnum": key},
                       json={"goodId": good, "isSpecial": False, "enterTs": -1, **changes})


def test_catalog_all_and_character_filters_are_authenticated_read_only(shop_runtime, shop_client, token):
    before = shop_runtime.sync(token)
    for body in ({}, {"charIdList": None}, {"charIdList": []}):
        response = shop_client.post("/shop/getSkinGoodList", json=body, headers={"secret": token})
        assert response.status_code == 200
        result = response.json()
        assert [row["goodId"] for row in result["goodList"]] == ["outfit-two", "outfit-one"]
        assert result["gachaGoodList"] == []
        assert result["playerDataDelta"] == {"modified": {}, "deleted": {}}
        assert all(row["currencyUnit"] == "DIAMOND" and row["isRedeem"] is False for row in result["goodList"])
    filtered = shop_client.post("/shop/getSkinGoodList", json={"charIdList": [CHAR, CHAR]},
                                headers={"secret": token}).json()
    assert [row["skinId"] for row in filtered["goodList"]] == [COSTUME]
    assert shop_client.post("/shop/getSkinGoodList", json={"charIdList": ["char_unknown"]},
                            headers={"secret": token}).status_code == 400
    assert shop_client.post("/shop/getSkinGoodList", json={}).status_code == 401
    assert shop_runtime.sync(token) == before


def test_purchase_debits_once_and_projects_real_ownership_and_counter_delta(shop_runtime, shop_client, token):
    before = shop_runtime.sync(token)["user"]
    response = purchase(shop_client, token)
    assert response.status_code == 200
    after = shop_runtime.sync(token)["user"]
    assert after["status"]["freeDiamond"] == before["status"]["freeDiamond"] - 18
    assert after["skin"]["characterSkins"] == {COSTUME: 1}
    assert after["skin"]["skinTs"] == {COSTUME: 1_800_000_000}
    assert after["skin"]["skinSp"] == {}
    assert after["shop"]["SKIN"] == {"info": [{"id": "outfit-one", "count": 1}], "gachaGood": {"info": []}}
    assert apply(before, response.json()["playerDataDelta"]) == after
    assert purchase(shop_client, token).json() == response.json()
    duplicate = purchase(shop_client, token, key="second-key")
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "SKIN_ALREADY_OWNED"
    assert shop_runtime.sync(token)["user"] == after
    with shop_runtime.database.transaction(write=False) as session:
        ctx = Context(session, shop_runtime.data, 1)
        assert ctx.rows(m.ShopState)[0].bought == 1
        assert len(ctx.rows(m.PurchaseHistory)) == 1
        assert ctx.rows(m.PurchaseHistory)[0].cost == {"items": [{"id": "4002", "count": 18}]}
        assert session.get(m.InventoryItem, (1, COSTUME)) is None


def test_concurrent_buy_requests_cannot_double_charge(shop_runtime, token):
    def send(key):
        with TestClient(create_game_app(shop_runtime)) as client:
            return purchase(client, token, key=key).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = sorted(pool.map(send, ("concurrent-one", "concurrent-two")))
    assert result == [200, 409]
    assert shop_runtime.sync(token)["user"]["status"]["freeDiamond"] == 42


def test_grant_failure_rolls_back_currency_ownership_history_counter_and_receipt(shop_runtime, shop_client, token, monkeypatch):
    before = shop_runtime.sync(token)
    real_grant = skin_shop.grant

    def fail(ctx, skin_id):
        real_grant(ctx, skin_id)
        raise DomainError("INJECTED_OUTFIT_FAILURE", "Synthetic failure", 503)

    monkeypatch.setattr(skin_shop, "grant", fail)
    response = purchase(shop_client, token)
    assert response.status_code == 503
    assert shop_runtime.sync(token) == before
    with shop_runtime.database.transaction(write=False) as session:
        ctx = Context(session, shop_runtime.data, 1)
        assert not ctx.rows(m.ShopState) and not ctx.rows(m.PurchaseHistory)
        assert not ctx.rows(m.OwnedSkin)
        assert session.scalar(select(m.Receipt).where(m.Receipt.account_id == 1)) is None
    monkeypatch.setattr(skin_shop, "grant", real_grant)
    assert purchase(shop_client, token).status_code == 200


@pytest.mark.parametrize("changes", [
    {"price": 0}, {"count": 2}, {"isSpecial": "false"}, {"enterTs": -2},
    {"isSpecial": 2}, {"isSpecial": -1},
    {"goodId": "x" * 97}, {"currencyUnit": "DIAMOND_SHD"}])
def test_untrusted_purchase_fields_cannot_authorize_mutation(shop_runtime, shop_client, token, changes):
    before = shop_runtime.sync(token)
    assert purchase(shop_client, token, **changes).status_code == 422
    assert shop_runtime.sync(token) == before


def test_unsupported_special_dynamic_illustration_is_explicit_and_does_not_charge(shop_runtime, shop_client, token):
    before = shop_runtime.sync(token)
    response = purchase(shop_client, token, isSpecial=True)
    assert response.status_code == 501
    assert shop_runtime.sync(token) == before


def test_frozen_native_zero_flag_purchases_and_retries_same_receipt_as_false(shop_runtime, shop_client, token):
    response = purchase(shop_client, token, isSpecial=0)
    assert response.status_code == 200
    assert purchase(shop_client, token, isSpecial=False).json() == response.json()
    assert shop_runtime.sync(token)["user"]["status"]["freeDiamond"] == 42


def test_frozen_native_one_flag_cannot_silently_buy_special_illustration(shop_runtime, shop_client, token):
    before = shop_runtime.sync(token)
    response = purchase(shop_client, token, isSpecial=1)
    assert response.status_code == 501
    assert shop_runtime.sync(token) == before


def test_insufficient_currency_owned_gift_and_banned_offer_preserve_save(shop_runtime, shop_client, token):
    with shop_runtime.database.transaction() as session:
        ctx = Context(session, shop_runtime.data, 1)
        ctx.change_item("4002", -60)
    before = shop_runtime.sync(token)
    assert purchase(shop_client, token).status_code == 400
    assert shop_runtime.sync(token) == before
    with shop_runtime.database.transaction() as session:
        ctx = Context(session, shop_runtime.data, 1)
        ctx.change_item(COSTUME, 1)
    before = shop_runtime.sync(token)
    assert purchase(shop_client, token).json()["error"]["code"] == "SKIN_ALREADY_OWNED"
    assert shop_runtime.sync(token) == before
    with shop_runtime.database.transaction() as session:
        ctx = Context(session, shop_runtime.data, 1)
        ctx.profile.flags = {**ctx.profile.flags, "featureBans": {"shop": ["outfit-two"]}}
    before = shop_runtime.sync(token)
    assert purchase(shop_client, token, good="outfit-two").status_code == 403
    assert shop_runtime.sync(token) == before


def test_period_cutoff_and_clock_rewind_do_not_restore_spent_currency_or_ownership(shop_runtime, shop_client, token):
    assert purchase(shop_client, token, good="outfit-two").status_code == 200
    with shop_runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = 1_800_000_100
    before = shop_runtime.sync(token)
    assert purchase(shop_client, token, good="outfit-two", key="expired", enterTs=0).json()["error"]["code"] == "GOOD_UNAVAILABLE"
    assert shop_runtime.sync(token) == before
    with shop_runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = 1_800_000_000
    assert purchase(shop_client, token, good="outfit-two", key="rewind").status_code == 409
    assert shop_runtime.sync(token)["user"]["status"]["freeDiamond"] == 45


def test_account_isolation_and_outfit_ownership_before_character_acquisition(shop_runtime, shop_client, token):
    with shop_runtime.database.transaction() as session:
        create_account(session, shop_runtime.data, "OtherDoctor")
        other = login(session, shop_runtime.settings, name="OtherDoctor")["secret"]
        Context(session, shop_runtime.data, 2).change_item("4002", 30)
    assert purchase(shop_client, other, good="outfit-two").status_code == 200
    with shop_runtime.database.transaction(write=False) as session:
        ctx = Context(session, shop_runtime.data, 2)
        assert not any(op.char_id == OTHER for op in ctx.rows(m.Operator))
    assert shop_runtime.sync(other)["user"]["skin"]["characterSkins"] == {OTHER_COSTUME: 1}
    assert shop_runtime.sync(token)["user"]["skin"]["characterSkins"] == {}


def test_missing_catalog_stays_unavailable_instead_of_fake_empty_success(skin_runtime, token):
    with TestClient(create_game_app(skin_runtime)) as client:
        response = client.post("/shop/getSkinGoodList", json={"charIdList": []}, headers={"secret": token})
    assert response.status_code == 503 and response.json()["error"]["code"] == "SKIN_CATALOG_NOT_READY"


@pytest.mark.parametrize("change", ["hash", "profile", "duplicate", "default-skin", "bad-period", "bad-price"])
def test_catalog_binding_and_cross_references_are_rejected_before_runtime_database_open(skin_runtime, change, monkeypatch):
    value = catalog_value(skin_runtime)
    if change == "hash":
        value["gamedata_hash"] = "0" * 64
    if change == "profile":
        value["client_profile"] = "other-client"
    if change == "duplicate":
        value["offers"].append(dict(value["offers"][0]))
    if change == "default-skin":
        value["offers"][0]["skinId"] = CHAR + "#1"
    if change == "bad-period":
        value["offers"][0].update(startDateTime=100, endDateTime=50)
    if change == "bad-price":
        value["offers"][0]["price"] = 19
    path = skin_runtime.settings.data_dir / "skin_shop.json"
    path.write_text(json.dumps(value), "utf-8")
    with pytest.raises((ValueError, DomainError)):
        read_catalog(path, skin_runtime.data, skin_runtime.settings.client_profile)
    monkeypatch.setattr("terralocal.server.services.runtime.Database",
                        lambda *args: pytest.fail("Invalid catalog reached database initialization"))
    with pytest.raises((ValueError, DomainError)):
        Runtime(skin_runtime.settings)


def test_catalog_rejects_duplicate_json_and_unstated_blindbox_supply(skin_runtime, tmp_path):
    path = tmp_path / "duplicates.json"
    path.write_text('{"offers":[],"offers":[]}', "utf-8")
    with pytest.raises(ValueError, match="重复 JSON"):
        read_catalog(path, skin_runtime.data, skin_runtime.settings.client_profile)
    value = catalog_value(skin_runtime)
    del value["blindbox_supply"]
    with pytest.raises(ValueError):
        SkinShopCatalog.model_validate(value)


def test_restart_and_database_restore_keep_bought_ownership_and_receipt(shop_runtime, shop_client, token):
    result = purchase(shop_client, token).json()
    expected = shop_runtime.sync(token)
    backup = BackupService(shop_runtime).create()
    assert purchase(shop_client, token, good="outfit-two", key="after-backup").status_code == 200
    BackupService(shop_runtime).restore(backup["name"])
    assert shop_runtime.sync(token) == expected
    assert purchase(shop_client, token).json() == result
    resumed = Runtime(shop_runtime.settings)
    try:
        assert resumed.skin_shop_catalog.summary() == shop_runtime.skin_shop_catalog.summary()
        assert resumed.sync(token) == expected
        with TestClient(create_game_app(resumed)) as client:
            assert purchase(client, token).json() == result
    finally:
        resumed.database.close()


def test_catalog_cli_dry_run_activation_show_preserves_save_and_exact_old_version(shop_runtime, tmp_path, monkeypatch, capsys):
    from terralocal.cli import main

    old_path = shop_runtime.settings.data_dir / "skin_shop.json"
    old = old_path.read_bytes()
    before = shop_runtime.database.integrity()
    value = catalog_value(shop_runtime)
    value["catalog_id"] = "revised-synthetic-outfits"
    value["offers"][0]["price"] = 17
    incoming = tmp_path / "next-offers.json"
    incoming.write_text(json.dumps(value), "utf-8")
    base = ["terralocal", "--data-dir", str(shop_runtime.settings.data_dir), "skinshop"]
    monkeypatch.setattr("sys.argv", base + ["import", str(incoming), "--dry-run"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert old_path.read_bytes() == old
    assert not (old_path.parent / "skin-catalogs").exists()
    monkeypatch.setattr("sys.argv", base + ["import", str(incoming)])
    assert main() == 0
    activated = json.loads(capsys.readouterr().out)
    assert activated["restart_required"] is True
    assert old in [p.read_bytes() for p in (old_path.parent / "skin-catalogs").iterdir()]
    monkeypatch.setattr("sys.argv", base + ["show"])
    assert main() == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["catalog_hash"] == activated["catalog_hash"]
    assert shown["catalog_id"] == value["catalog_id"]
    assert shop_runtime.database.integrity() == before
    # Import is staged for restart; it cannot silently rewrite a live catalog.
    assert shop_runtime.skin_shop_catalog.catalog_id == "synthetic-outfits"


def test_gift_reissue_preserves_first_acquisition_time_in_native_sync_and_restart(skin_runtime, token):
    with skin_runtime.database.transaction() as session:
        Context(session, skin_runtime.data, 1).change_item(COSTUME, 1)
    original = skin_runtime.sync(token)["user"]["skin"]
    assert original == {"characterSkins": {COSTUME: 1}, "skinTs": {COSTUME: 1_800_000_000}, "skinSp": {}}
    with skin_runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 600
        Context(session, skin_runtime.data, 1).change_item(COSTUME, 1)
    assert skin_runtime.sync(token)["user"]["skin"] == original
    resumed = Runtime(skin_runtime.settings)
    try:
        assert resumed.sync(token)["user"]["skin"] == original
    finally:
        resumed.database.close()


@pytest.mark.parametrize("bans", [None, {"shop": None}, {"shop": [1]}, {"shop": ["x" * 97]}])
def test_invalid_local_restrictions_return_explicit_error_without_mutation(shop_runtime, shop_client, token, bans):
    with shop_runtime.database.transaction() as session:
        ctx = Context(session, shop_runtime.data, 1)
        ctx.profile.flags = {**ctx.profile.flags, "featureBans": bans}
    before = shop_runtime.sync(token)
    response = purchase(shop_client, token)
    assert response.status_code == 503 and response.json()["error"]["code"] == "INVALID_LOCAL_RESTRICTIONS"
    assert shop_runtime.sync(token) == before
