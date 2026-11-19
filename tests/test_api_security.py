import json

from fastapi.testclient import TestClient

from terralocal.admin.app import create_admin_app


def test_login_and_invalid_session(client):
    response = client.post("/local/v1/login", json={"name": "Doctor"})
    assert response.status_code == 200
    secret = response.json()["secret"]
    assert client.post("/account/syncData", headers={"secret": secret}).status_code == 200
    assert client.post("/account/syncData", headers={"secret": "wrong"}).status_code == 401


def test_unknown_route_logs_schema_not_credentials(client, runtime):
    response = client.post("/unknown/current-client", json={"token": "NEVER-LOG-ME", "data": {"value": 4}},
                           headers={"secret": "NEVER-LOG-ME", "uid": "private"})
    assert response.status_code == 501 and response.json()["error"]["code"] == "NOT_IMPLEMENTED"
    content = (runtime.settings.data_dir / "logs" / "unknown-routes.jsonl").read_text("utf-8")
    assert "NEVER-LOG-ME" not in content and '"private"' not in content
    assert json.loads(content)["body_schema"]["token"] == "str"


def test_write_needs_key_and_strict_types(client, token):
    response = client.post("/local/v1/battle/start", json={"stageId": "test_1"}, headers={"secret": token})
    assert response.status_code == 400
    response = client.post("/local/v1/battle/finish", json={"battleId": "test", "stars": -1},
                           headers={"secret": token, "idempotency-key": "1"})
    assert response.status_code == 422


def test_admin_origin_csrf_and_audit(runtime):
    app = create_admin_app(runtime)
    with TestClient(app, base_url="http://127.0.0.1:8080") as client:
        assert client.get("/api/accounts").status_code == 401
        auth = client.get("/api/session").json()
        assert client.post("/api/gm", json={"accountId": 1, "action": "grant-item",
                                            "id": "material", "value": 1}).status_code == 403
        response = client.post("/api/gm", json={"accountId": 1, "action": "grant-item",
                                                "id": "material", "value": 1},
                               headers={"x-csrf-token": auth["csrf"]})
        assert response.status_code == 200
        assert client.get("/api/logs").json()["audit"][0]["action"] == "grant-item"
        assert client.get("/api/accounts", headers={"host": "evil.example:8080"}).status_code == 403
        assert client.post("/api/clock", json={"mode": "realtime"}, headers={
            "origin": "https://evil.example", "x-csrf-token": auth["csrf"]}).status_code == 403
