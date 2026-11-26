"""Local-only shop configuration, transactions and backup binding."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from test_crisis_v2_claims import ITEM, clear, inventory, prepare

from terralocal.server.domain.accounts import login
from terralocal.server.main import create_game_app
from terralocal.server.services.backups import backup_existing_save, recover_backup
from terralocal.server.services.runtime import Runtime

PATH = "/local/v1/crisis-v2/shop"


def test_explicit_catalog_credit_purchase_retry_and_backup_drift(tmp_path):
    runtime, token, battle = prepare(tmp_path)
    with TestClient(create_game_app(runtime)) as client:
        assert client.get(PATH, headers={"secret": token}).status_code == 503
    settings = runtime.settings
    runtime.database.close()
    path = settings.data_dir / "crisis_v2_local_shop.json"
    catalog = {"schemaVersion": 1, "gameDataHash": settings.gamedata_hash, "seasonId": "season_a",
               "credits": {"season_a_p": 6}, "offers": [{"id": "chair", "price": 4, "stock": 1,
                                                         "itemId": ITEM, "itemType": "FURN"}]}
    path.write_text(json.dumps(catalog), encoding="utf-8")
    runtime = Runtime(settings)
    try:
        with runtime.database.transaction() as session:
            token = login(session, settings, name="CrisisDoctor")["secret"]
        with TestClient(create_game_app(runtime)) as client:
            def send(where, key, payload):
                return client.post(PATH + where, headers={"secret": token, "idempotency-key": key}, json=payload)

            assert client.get(PATH, headers={"secret": token}).json()["coin"] == 0
            assert send("/buy", "poor", {"offerId": "chair"}).status_code == 409
            assert send("/claim-credit", "early", {"mapId": "season_a_p"}).status_code == 409
            clear(runtime, token, battle)
            credit = send("/claim-credit", "credit", {"mapId": "season_a_p"}).raise_for_status().json()
            assert credit["coin"] == 6
            assert send("/claim-credit", "credit", {"mapId": "season_a_p"}).json() == credit
            assert send("/claim-credit", "second-credit", {"mapId": "season_a_p"}).status_code == 409
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(lambda key: send("/buy", key, {"offerId": "chair"}), ("x", "y")))
            assert sorted(reply.status_code for reply in replies) == [200, 409]
            shop = client.get(PATH, headers={"secret": token}).raise_for_status().json()
            assert shop["coin"] == 2 and shop["offers"][0]["remaining"] == 0
            assert inventory(runtime) == 1
    finally:
        runtime.database.close()
    backup = backup_existing_save(settings)
    restored = settings.data_dir / "restored-shop.sqlite3"
    recover_backup(settings, backup["name"], restored)
    assert restored.exists()
    catalog["offers"][0]["price"] = 5
    path.write_text(json.dumps(catalog), encoding="utf-8")
    before = settings.database_path.read_bytes()
    with pytest.raises(ValueError, match="不同的危机合约本地商店配置"):
        Runtime(settings)
    assert settings.database_path.read_bytes() == before
    with pytest.raises(ValueError, match="不同的危机合约本地商店配置"):
        recover_backup(settings, backup["name"], settings.data_dir / "should-not-exist.sqlite3")
    assert not (settings.data_dir / "should-not-exist.sqlite3").exists()
    catalog["offers"][0]["price"] = 4
    path.write_text(json.dumps(catalog), encoding="utf-8")
    with closing(sqlite3.connect(settings.database_path)) as connection:
        connection.execute("UPDATE crisis_v2_accounts SET shop_coin = shop_coin + 1")
        connection.commit()
    corrupted = settings.database_path.read_bytes()
    with pytest.raises(ValueError, match="本地商店余额或库存账本不一致"):
        Runtime(settings)
    assert settings.database_path.read_bytes() == corrupted


def test_optional_shop_ignores_legacy_schema_without_a_shop_ledger(tmp_path):
    from types import SimpleNamespace

    from terralocal.server.domain.crisis_v2_shop import preflight

    path = tmp_path / "older.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE receipts (key TEXT, request_hash TEXT)")
    before = path.read_bytes()
    preflight(SimpleNamespace(model_dump=lambda: {"synthetic": True}), path)
    assert path.read_bytes() == before