"""Synthetic transport fixtures; no official account credentials or network requests."""

import hashlib
import json

import pytest

from terralocal.server.compatibility.profile import ClientCompatibilityProfile


@pytest.fixture
def bootstrap(runtime):
    settings = runtime.settings
    profile = ClientCompatibilityProfile(
        id=settings.client_profile, package="synthetic.test", channel="official", client_version="2.7.71",
        version_code=190, apk_sha256="0" * 64, resource_version="synthetic-resource", api_version="V070",
        resource_manifest_version="V077", gamedata_hash=settings.gamedata_hash)
    profile.save(settings.data_dir / "profiles" / f"{profile.id}.json")
    root = settings.data_dir / "client" / "bootstrap" / profile.id
    root.mkdir(parents=True)
    documents = {"network": {"sign": "synthetic-signature", "content": json.dumps(
        {"configVer": "5", "funcVer": "V070", "configs": {}})}, "remote": {"enableGameBI": True},
        "network_android": {"gs": "https://synthetic.invalid", "configVer": 5},
        "remote_android": {"enableGameBI": True, "HGDownload_1": 10000},
        "sdk_app": {"status": 0, "data": {"payment": [{"key": "synthetic"}],
                   "app": {"appName": "Synthetic", "enablePayment": True}}},
        "sdk_products": {"productList": [{"product_id": "synthetic-product", "price": 100}]}}
    sources = {}
    for name, value in documents.items():
        body = json.dumps(value).encode()
        (root / f"{name}.json").write_bytes(body)
        sources[name] = {"sha256": hashlib.sha256(body).hexdigest()}
    (root / "sources.json").write_text(json.dumps(sources), "utf-8")
    return root, documents


def test_bootstrap_frozen_signature_and_missing_or_corrupt_documents(client, runtime, bootstrap):
    root, documents = bootstrap
    assert client.get("/config/prod/official/network_config").json() == documents["network"]
    assert client.get("/api/remote_config/1/prod/default/Android/network_config").json() == documents[
        "network_android"]
    assert client.get("/config/prod/official/Android/version").json() == {
        "clientVersion": "2.7.71", "resVersion": "synthetic-resource"}
    assert client.get("/config/prod/official/remote_config").json()["enableGameBI"] is False
    assert client.get("/api/remote_config/1/prod/default/Android/remote_config").json() == {
        "enableGameBI": False, "HGDownload_1": 10000}
    sdk = client.get("/app/v1/config").json()
    assert sdk["data"]["app"]["appName"] == "Synthetic"
    assert sdk["data"]["payment"] == [] and sdk["data"]["app"]["enablePayment"] is False
    assert client.get("/general/v1/server_time").json() == {
        "status": 0, "msg": "OK", "type": "A", "data": {"serverTime": 1_800_000_000, "isHoliday": False}}
    request = {"appId": "1", "channelId": "1", "worldId": 1, "platform": 1}
    assert client.post("/u8/pay/getAllProductList", json=request).json() == documents["sdk_products"]
    assert client.post("/u8/pay/getAllProductList", json={**request, "channelId": "2"}).status_code == 409
    assert client.get("/config/prod/announce_meta/Android/announcement.meta.json").json()["announceList"]
    assert client.get("/api/gate/meta/Android").json()["preAnnounceUrl"].endswith("/gameBulletin")
    assert client.get("/gameBulletin").status_code == 200
    (root / "network.json").write_text("{}", "utf-8")
    assert client.get("/config/prod/official/network_config").status_code == 503
    (root / "network.json").unlink()
    assert client.get("/config/prod/official/network_config").status_code == 503


def test_sdk_u8_game_token_stages_and_version_gate(client, bootstrap):
    sdk = client.post("/local/v1/sdk/login", json={"name": "Doctor"}).json()
    assert sdk["callback"] == {"code": sdk["code"], "isSuc": True, "type": 1}
    assert client.post("/account/syncData", headers={"secret": sdk["code"]}).status_code == 401
    assert client.post("/user/oauth2/v2/grant", json={"code": "invalid"}).status_code == 401
    grant = client.post("/user/oauth2/v2/grant", json={"code": sdk["code"]}).json()
    assert grant["data"]["uid"] == sdk["uid"]
    u8_request = {"appId": "1", "platform": 1, "channelId": "1",
                  "extension": json.dumps({"uid": sdk["uid"], "code": sdk["code"]})}
    u8 = client.post("/u8/user/v1/getToken", json=u8_request).json()
    assert u8["uid"] == sdk["uid"]
    assert client.post("/account/syncData", headers={"secret": u8["token"]}).status_code == 401
    game_request = {"uid": sdk["uid"], "token": u8["token"], "platform": 1,
                    "clientVersion": "2.7.71", "assetsVersion": "synthetic-resource", "networkVersion": "5",
                    "udtVersion": "synthetic-transport-version"}
    assert client.post("/account/login", json={**game_request, "assetsVersion": "mismatch"}).status_code == 409
    assert client.post("/account/login", json={**game_request, "token": sdk["code"]}).status_code == 401
    assert client.post("/account/login", json={**game_request, "uid": "another-account"}).status_code == 401
    game = client.post("/account/login", json=game_request).json()
    assert game["uid"] == sdk["uid"] and game["result"] == 0
    assert client.post("/account/syncData", headers={"secret": game["secret"]}).status_code == 200


def test_u8_validates_extension_and_logs_neither_secrets_nor_devices(client, runtime, bootstrap):
    body = {"appId": "1", "platform": 1, "channelId": "1", "extension": "[]"}
    assert client.post("/u8/user/v1/getToken", json=body).status_code == 400
    assert client.post("/u8/user/v1/getToken", json={**body, "extension": "not-json"}).status_code == 400
    assert client.post("/u8/user/v1/getToken", json={**body, "channelId": "2"}).status_code == 409
    value = "UNTRUSTED-SECRET-DO-NOT-LOG"
    response = client.post("/u8/user/v1/getToken", json={**body,
        "extension": json.dumps({"code": value}), "deviceId": value})
    assert response.status_code == 401
    assert value not in response.text
    for path in (runtime.settings.data_dir / "logs").glob("*.jsonl"):
        assert value not in path.read_text("utf-8")
