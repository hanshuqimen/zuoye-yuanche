"""Owned miniature supply; integration checks do not claim native gameplay."""

import copy
import hashlib
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from crisis_v2_qa import set_time
from fastapi.testclient import TestClient
from test_crisis_v2_claims import ITEM
from test_crisis_v2_coin_missions import BODY, balances, tables
from test_crisis_v2_coin_missions import prepare as prepare_coins
from test_crisis_v2_native_missions import send as claim
from test_crisis_v2_persistence import rows

from terralocal.server.domain import crisis_v2_native_shop as shop
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.crisis_v2_shop import read_catalog
from terralocal.server.main import create_game_app
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService, backup_existing_save, recover_backup
from terralocal.server.services.runtime import Runtime

LIST = "/crisisV2/getGoodList"
BUY = "/crisisV2/buyGood"
FILE = "crisis_v2_native_shop.json"


def source():
    data = tables()
    data["item_table"]["uniqueInfo"] = {ITEM: 1}
    data["item_table"]["items"].update(
        {
            "char_shop": {"itemId": "char_shop", "itemType": "CHAR", "name": "Authored shop operator"},
            "shop-token": {"itemId": "shop-token", "itemType": "MATERIAL", "name": "Authored shop token"},
            "4004": {"itemId": "4004", "itemType": "HGG_SHD", "name": "Authored gold certificate"},
            "4005": {"itemId": "4005", "itemType": "LGG_SHD", "name": "Authored green certificate"},
        }
    )
    data["character_table"]["char_shop"] = copy.deepcopy(data["character_table"]["char_synthetic"])
    data["character_table"]["char_shop"]["potentialItemId"] = "shop-token"
    data["charword_table"]["voiceLangDict"]["char_shop"] = copy.deepcopy(
        data["charword_table"]["voiceLangDict"]["char_synthetic"]
    )
    data["charword_table"]["charDefaultTypeDict"]["char_shop"] = "JP"
    return data


def catalog(runtime):
    def common(ident, item, price, stock):
        return {
            "goodId": ident,
            "displayName": None,
            "item": item,
            "progressGoodId": None,
            "price": price,
            "availCount": stock,
            "itemSupplyTime": -1,
        }

    def item(ident, kind, quantity=1):
        return {"id": ident, "type": kind, "count": quantity}

    def permanent(ident, bundle, price, stock, slot):
        return common(ident, bundle, price, stock) | {
            "isSingle": 0,
            "slotId1": 1,
            "slotId2": slot,
            "seasonId": "season_a",
            "title": "NONE",
        }

    return {
        "schema_version": 1,
        "gamedata_hash": runtime.settings.gamedata_hash,
        "client_profile": runtime.settings.client_profile,
        "catalog_id": "authored-native-shop-v1",
        "mode": "custom",
        "provenance": "Owned miniature supply; not an official catalog",
        "valid_from": 1000,
        "progress_policy": "finite-tiers-v1",
        "permanent": [
            permanent("chair", item(ITEM, "FURN"), 4, 1, 1),
            permanent("materials", item("authored-mat", "MATERIAL", 2), 2, 3, 2),
            permanent("gold", item("4001", "GOLD", 70), 1, -1, 3),
            permanent("operator", None, 0, 0, 4) | {"progressGoodId": "operator-tiers"},
        ],
        "seasons": {
            "season_a": {
                "start_ts": 1100,
                "end_ts": 1900,
                "goods": [
                    common("records", item("authored-exp", "CARD_EXP"), 3, 2)
                    | {"slotId": 1, "rarity": "normal"}
                ],
            }
        },
        "progress": {
            "operator-tiers": [
                {
                    "item": item("char_shop", "CHAR"),
                    "displayName": "Authored operator",
                    "order": 1,
                    "price": 4,
                },
                {
                    "item": item("shop-token", "MATERIAL"),
                    "displayName": "Authored token",
                    "order": 2,
                    "price": 2,
                },
                {
                    "item": item("shop-token", "MATERIAL"),
                    "displayName": "Authored token",
                    "order": 3,
                    "price": 3,
                },
            ]
        },
    }


def prepare(directory, *, local_shop=False, source_data=None):
    runtime, token = prepare_coins(
        directory, source=source() if source_data is None else source_data, local_shop=local_shop
    )
    settings = runtime.settings
    value = catalog(runtime)
    # Use the actual shared-table window, never a presumed test date.
    season = runtime.data.crisis_v2.seasons["season_a"]
    value["seasons"]["season_a"].update(start_ts=season.start, end_ts=season.end)
    runtime.database.close()
    (settings.data_dir / FILE).write_text(json.dumps(value), "utf8")
    return Runtime(settings), token


def send(client, token, key, *, good="materials", count=1, perm=1, path=BUY, body=None):
    headers = {"secret": token}
    if key is not None:
        headers["seqnum"] = key
    if body is None:
        body = {} if path == LIST else {"goodId": good, "count": count, "perm": perm}
    return client.post(path, headers=headers, json=body)


def credit(client, token):
    return claim(client, token, "native-credit", BODY).raise_for_status().json()


def test_native_inventory_delta_transport_retry_and_new_purchase_intent(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            credit(client, token)
            before = runtime.sync(token)["user"]
            first = send(client, token, "purchase", count=2).raise_for_status().json()
            after = runtime.sync(token)["user"]
            assert first["items"] == [{"id": "authored-mat", "type": "MATERIAL", "count": 4}]
            assert apply(before, first["playerDataDelta"]) == after
            assert after["crisisV2"]["shop"]["coin"] == 14
            assert after["crisisV2"]["shop"]["info"] == [{"id": "materials", "count": 2}]
            assert send(client, token, "purchase", count=2).json() == first
            assert send(client, token, "purchase").status_code == 409
            listing = send(client, token, "list", path=LIST).raise_for_status().json()
            assert (
                next(row for row in listing["permanent"] if row["goodId"] == "materials")["availCount"] == 1
            )
            assert next(row for row in listing["permanent"] if row["goodId"] == "gold")["availCount"] == -1
            send(client, token, "next-intent").raise_for_status()
            assert send(client, token, "sold-out").status_code == 409
        assert balances(runtime)["shop"] == 12 and balances(runtime)["material"] == 9
    finally:
        runtime.database.close()


def test_new_identical_intent_after_login_and_cold_restart_is_not_a_claim_retry(tmp_path):
    runtime, token = prepare(tmp_path)
    settings = runtime.settings
    try:
        with TestClient(create_game_app(runtime)) as client:
            credit(client, token)
            send(client, token, "one").raise_for_status()
        with runtime.database.transaction() as session:
            token = login(session, settings, name="CrisisDoctor")["secret"]
        with TestClient(create_game_app(runtime)) as client:
            send(client, token, "one").raise_for_status()
        assert balances(runtime)["shop"] == 14
    finally:
        runtime.database.close()
    runtime = Runtime(settings)
    try:
        with TestClient(create_game_app(runtime)) as client:
            before = balances(runtime)
            # Native task business replay remains empty and does not refund spend.
            again = claim(client, token, "old-claim", BODY).raise_for_status().json()
            assert again["playerDataDelta"] == {"modified": {}, "deleted": {}}
            assert balances(runtime) == before
            send(client, token, "third").raise_for_status()
            assert send(client, token, "fourth").status_code == 409
        assert balances(runtime)["shop"] == 12
    finally:
        runtime.database.close()


@pytest.mark.parametrize(
    "fault,status",
    [
        ({"count": True}, 422),
        ({"count": "1"}, 422),
        ({"count": 0}, 422),
        ({"count": -1}, 422),
        ({"perm": True}, 422),
        ({"perm": 2}, 422),
        ({"price": 0}, 422),
        ({"goodId": "missing"}, 404),
        ({"goodId": "records", "perm": 1}, 404),
        ({"count": 4}, 409),
        ({"goodId": "operator", "count": 2}, 409),
    ],
)
def test_bad_or_unavailable_purchase_does_not_change_save(tmp_path, fault, status):
    runtime, token = prepare(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            credit(client, token)
            before = rows(runtime.database.path)
            response = send(client, token, "bad", body={"goodId": "materials", "count": 1, "perm": 1} | fault)
            assert response.status_code == status
            assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_missing_catalog_auth_quantity_and_insufficient_balance_are_real_errors(tmp_path):
    runtime, token = prepare_coins(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            before = rows(runtime.database.path)
            assert send(client, token, "missing", path=LIST).status_code == 503
            assert send(client, "invalid", "auth", path=LIST).status_code == 401
            assert send(client, token, None).status_code == 400
            assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_shared_stock_concurrency_and_grant_exception_roll_back(tmp_path, monkeypatch):
    runtime, token = prepare(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            credit(client, token)
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(lambda key: send(client, token, key, count=2), ("a", "b")))
            assert sorted(reply.status_code for reply in replies) == [200, 409]
            assert balances(runtime)["shop"] == 14
            before = rows(runtime.database.path)
            grant = Context.rewards

            def fail(ctx, *args, **kwargs):
                grant(ctx, *args, **kwargs)
                raise DomainError("TEST_ROLLBACK", "Authored post-grant fault", 503)

            monkeypatch.setattr(Context, "rewards", fail)
            assert send(client, token, "grant-failure", good="chair").status_code == 503
            assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_finite_progress_operator_tokens_and_exhaustion(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            credit(client, token)
            before = runtime.sync(token)["user"]
            first = send(client, token, "tier-1", good="operator").raise_for_status().json()
            assert first["items"][0]["type"] == "CHAR" and first["items"][0]["charGet"]["isNew"] == 1
            assert apply(before, first["playerDataDelta"]) == runtime.sync(token)["user"]
            for number, cost in ((2, 2), (3, 3)):
                old_coin = balances(runtime)["shop"]
                reply = send(client, token, f"tier-{number}", good="operator").raise_for_status().json()
                assert reply["items"] == [{"id": "shop-token", "type": "MATERIAL", "count": 1}]
                assert balances(runtime)["shop"] == old_coin - cost
            assert send(client, token, "tier-1", good="operator").json() == first
            listing = send(client, token, "completed-list", path=LIST).raise_for_status().json()
            assert "operator" not in {row["goodId"] for row in listing["permanent"]}
            assert send(client, token, "too-many-tiers", good="operator").status_code == 409
        user = runtime.sync(token)["user"]
        assert user["crisisV2"]["shop"]["progressInfo"] == {"operator-tiers": {"count": 3, "order": 3}}
        assert user["crisisV2"]["shop"]["info"] == []
    finally:
        runtime.database.close()


def test_unique_ownership_from_another_reward_prevents_another_purchase(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        with runtime.database.transaction() as session:
            Context(session, runtime.data, 1).rewards([{"id": ITEM, "type": "FURN", "count": 1}])
        with TestClient(create_game_app(runtime)) as client:
            credit(client, token)
            listing = send(client, token, "list", path=LIST).raise_for_status().json()
            assert next(row for row in listing["permanent"] if row["goodId"] == "chair")["availCount"] == 0
            before = rows(runtime.database.path)
            assert send(client, token, "duplicate-unique", good="chair").status_code == 409
            assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_unlimited_bulk_keeps_native_quantity_range_without_small_arbitrary_cap(tmp_path):
    data = source()
    bag = data["crisis_v2_server_table"]["seasons"]["season_a"]["info"]["mapDetailDataMap"]["season_a_p"]
    bag["bagDataMap"]["bag"]["slotPackRewards"][0]["count"] = 1_100_000
    runtime, token = prepare(tmp_path, source_data=data)
    try:
        with TestClient(create_game_app(runtime)) as client:
            credit(client, token)
            base_gold = balances(runtime)["gold"]
            reply = send(client, token, "bulk", good="gold", count=1_000_001).raise_for_status().json()
            assert reply["items"] == [{"id": "4001", "type": "GOLD", "count": 70_000_070}]
            before = rows(runtime.database.path)
            assert send(client, token, "too-expensive", good="gold", count=1_000_001).status_code == 409
            assert rows(runtime.database.path) == before
        assert balances(runtime)["gold"] == base_gold + 70_000_070
    finally:
        runtime.database.close()


def test_season_boundary_permanent_after_close_and_rewind_do_not_restock(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        supply = runtime.crisis_v2_native_shop.seasons["season_a"]
        with TestClient(create_game_app(runtime)) as client:
            credit(client, token)
            set_time(runtime, supply.end_ts)
            send(client, token, "last-second", good="records", perm=0).raise_for_status()
            set_time(runtime, supply.end_ts + 1)
            assert send(client, token, "closed", good="records", perm=0).status_code == 404
            listing = send(client, token, "after-season", path=LIST).raise_for_status().json()
            assert listing["season"] == [] and listing["permanent"]
            send(client, token, "permanent-after-season", good="gold").raise_for_status()
            set_time(runtime, supply.start_ts)
            listing = send(client, token, "rewound", path=LIST).raise_for_status().json()
            assert listing["season"][0]["availCount"] == 1
    finally:
        runtime.database.close()


def test_native_and_local_ledgers_share_credits_and_survive_online_and_fresh_restore(tmp_path):
    runtime, token = prepare(tmp_path, local_shop=True)
    settings = runtime.settings
    with TestClient(create_game_app(runtime)) as client:
        credit(client, token)
        send(client, token, "native-buy").raise_for_status()
        prefix = "/local/v1/crisis-v2/shop"
        client.post(
            prefix + "/buy",
            json={"offerId": "chair"},
            headers={"secret": token, "idempotency-key": "local-buy"},
        ).raise_for_status()
        client.post(
            prefix + "/claim-credit",
            json={"mapId": "season_a_p"},
            headers={"secret": token, "idempotency-key": "local-credit"},
        ).raise_for_status()
        # A second native credit must still validate both debit sources.
        claim(
            client,
            token,
            "temporary-credit",
            {"mapId": "season_a_t", "missions": [{"id": "challenge", "type": 1}]},
        ).raise_for_status()
    expected = balances(runtime)
    service = BackupService(runtime)
    backup = service.create()
    with TestClient(create_game_app(runtime)) as client:
        send(client, token, "later-buy", good="gold").raise_for_status()
    service.restore(backup["name"])
    assert balances(runtime) == expected
    runtime.database.close()
    backup = backup_existing_save(settings)
    recovered = settings.data_dir / "recovered-native-shop.sqlite3"
    recover_backup(settings, backup["name"], recovered)
    fresh_dir = tmp_path / "fresh-native-shop"
    shutil.copytree(settings.data_dir / "cache", fresh_dir / "cache")
    shutil.copyfile(recovered, fresh_dir / "terralocal.sqlite3")
    for filename in (FILE, "crisis_v2_local_shop.json"):
        shutil.copyfile(settings.data_dir / filename, fresh_dir / filename)
    restored = Runtime(settings.model_copy(update={"data_dir": fresh_dir}))
    try:
        assert balances(restored) == expected
    finally:
        restored.database.close()


@pytest.mark.parametrize(
    "damage", ["missing-catalog", "price", "info", "boolean-info", "ledger", "deleted-ledger", "coin"]
)
def test_corrupt_or_replaced_purchase_records_refuse_startup_and_restore_without_writes(tmp_path, damage):
    runtime, token = prepare(tmp_path)
    with TestClient(create_game_app(runtime)) as client:
        credit(client, token)
        send(client, token, "purchase").raise_for_status()
    settings = runtime.settings
    runtime.database.close()
    backup = backup_existing_save(settings)
    path = settings.data_dir / FILE
    if damage == "missing-catalog":
        path.rename(path.with_suffix(".preserved"))
    elif damage == "price":
        value = json.loads(path.read_bytes())
        value["permanent"][1]["price"] += 1
        path.write_text(json.dumps(value), "utf8")
    else:
        with sqlite3.connect(settings.database_path) as db:
            if damage == "info":
                db.execute("UPDATE crisis_v2_accounts SET shop_info='[]'")
            elif damage == "boolean-info":
                db.execute(
                    "UPDATE crisis_v2_accounts SET shop_info=?",
                    (json.dumps([{"id": "materials", "count": True}]),),
                )
            elif damage == "deleted-ledger":
                db.execute("DELETE FROM receipts WHERE key=?", (shop.LEDGER,))
            elif damage == "coin":
                db.execute("UPDATE crisis_v2_accounts SET shop_coin=shop_coin+1")
            else:
                value = json.loads(
                    db.execute("SELECT result FROM receipts WHERE key=?", (shop.LEDGER,)).fetchone()[0]
                )
                value["purchases"]["materials"] += 1
                db.execute("UPDATE receipts SET result=? WHERE key=?", (json.dumps(value), shop.LEDGER))
    before = hashlib.sha256(settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(settings)
    assert hashlib.sha256(settings.database_path.read_bytes()).hexdigest() == before
    if damage in ("missing-catalog", "price"):
        output = settings.data_dir / "rejected.sqlite3"
        with pytest.raises(ValueError):
            recover_backup(settings, backup["name"], output)
        assert not output.exists()


@pytest.mark.parametrize(
    "fault", ["duplicate", "wrong-window", "wrong-item-type", "missing-tier", "broken-order", "unused-tier"]
)
def test_catalog_rejects_mismatched_data_and_ambiguous_supply(tmp_path, fault):
    runtime, _ = prepare(tmp_path)
    try:
        value = catalog(runtime)
        season = runtime.data.crisis_v2.seasons["season_a"]
        value["seasons"]["season_a"].update(start_ts=season.start, end_ts=season.end)
        if fault == "duplicate":
            value["permanent"][1]["goodId"] = "chair"
        elif fault == "wrong-window":
            value["seasons"]["season_a"]["end_ts"] += 1
        elif fault == "wrong-item-type":
            value["permanent"][0]["item"]["type"] = "MATERIAL"
        elif fault == "missing-tier":
            value["progress"].clear()
        elif fault == "broken-order":
            value["progress"]["operator-tiers"][0]["order"] = 0
        else:
            value["progress"]["extra"] = copy.deepcopy(value["progress"]["operator-tiers"])
        path = runtime.settings.data_dir / "bad-native-catalog.json"
        path.write_text(json.dumps(value), "utf8")
        with pytest.raises(ValueError):
            read_catalog(path, runtime.data, runtime.settings.client_profile)
    finally:
        runtime.database.close()


def test_accounts_do_not_share_native_stock_or_purchase_receipts(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        with runtime.database.transaction() as session:
            create_account(session, runtime.data, "OtherShopDoctor")
            other = login(session, runtime.settings, name="OtherShopDoctor")["secret"]
        with TestClient(create_game_app(runtime)) as client:
            credit(client, token)
            send(client, token, "purchase", good="chair").raise_for_status()
            listing = send(client, other, "list", path=LIST).raise_for_status().json()
            assert next(row for row in listing["permanent"] if row["goodId"] == "chair")["availCount"] == 1
            before = rows(runtime.database.path)
            assert send(client, other, "purchase", good="chair").status_code == 409
            assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_active_season_missing_supply_refuses_empty_success(tmp_path):
    runtime, token = prepare(tmp_path)
    settings = runtime.settings
    runtime.database.close()
    path = settings.data_dir / FILE
    value = json.loads(path.read_bytes())
    value["seasons"] = {}
    path.write_text(json.dumps(value), "utf8")
    runtime = Runtime(settings)
    try:
        with TestClient(create_game_app(runtime)) as client:
            before = rows(runtime.database.path)
            result = send(client, token, "missing-season", path=LIST)
            assert (
                result.status_code == 503
                and result.json()["error"]["code"] == "CRISIS_V2_NATIVE_SHOP_MISSING"
            )
            assert rows(runtime.database.path) == before
            set_time(runtime, 2000)
            result = send(client, token, "after-season", path=LIST).raise_for_status().json()
            assert result["permanent"] and result["season"] == []
    finally:
        runtime.database.close()


def test_wrong_reward_response_rolls_back_the_grant_and_debit(tmp_path, monkeypatch):
    runtime, token = prepare(tmp_path)
    try:
        original = Context.rewards

        def wrong(ctx, *args, **kwargs):
            original(ctx, *args, **kwargs)
            return []

        with TestClient(create_game_app(runtime)) as client:
            credit(client, token)
            before = rows(runtime.database.path)
            monkeypatch.setattr(Context, "rewards", wrong)
            result = send(client, token, "bad-reward-response")
            assert result.status_code == 503
            assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


@pytest.mark.parametrize("bad_cap", [True, "1"])
def test_progress_unique_cap_is_validated_before_admission(tmp_path, bad_cap):
    data = source()
    data["item_table"]["uniqueInfo"]["shop-token"] = bad_cap
    runtime, _ = prepare_coins(tmp_path, source=data)
    try:
        value = catalog(runtime)
        season = runtime.data.crisis_v2.seasons["season_a"]
        value["seasons"]["season_a"].update(start_ts=season.start, end_ts=season.end)
        path = runtime.settings.data_dir / FILE
        path.write_text(json.dumps(value), "utf8")
        before = rows(runtime.database.path)
        with pytest.raises(ValueError, match="唯一上限"):
            read_catalog(path, runtime.data, runtime.settings.client_profile)
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()
