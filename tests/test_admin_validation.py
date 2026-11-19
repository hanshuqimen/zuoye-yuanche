"""Nullable catalog data and rejected GM input must leave saves untouched."""
import pytest
from conftest import miniature
from fastapi.testclient import TestClient

from terralocal.admin.app import create_admin_app
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import validate_tables


@pytest.fixture
def admin(runtime):
    with TestClient(create_admin_app(runtime), base_url="http://127.0.0.1:8080") as client:
        client.headers["x-csrf-token"] = client.get("/api/session").json()["csrf"]
        yield client


def test_normal_search_is_not_broken_by_unrelated_nullable_stage(runtime, admin):
    original = runtime.data.stages["test_1"]
    runtime.data.stages.update({
        "test_1": {**original, "code": "0-1"},
        "nullable_stage": {**original, "stageId": "nullable_stage", "name": None, "code": None},
        "named_stage": {**original, "stageId": "named_stage", "name": "Mixed CASE", "code": None},
    })
    response = admin.get("/api/catalog/stages", params={"q": "0-1"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["entries"][0]["id"] == "test_1"
    response = admin.get("/api/catalog/stages", params={"q": "NULLABLE"})
    assert response.status_code == 200
    assert response.json()["entries"][0]["name"] == "nullable_stage"
    assert response.json()["entries"][0]["code"] == ""
    response = admin.get("/api/catalog/stages", params={"q": "mixed case"})
    assert response.status_code == 200 and response.json()["total"] == 1
    response = admin.get("/api/catalog/stages", params={"limit": 500})
    assert response.status_code == 200
    assert all(isinstance(row["name"], str) and isinstance(row["code"], str)
               for row in response.json()["entries"])


@pytest.mark.parametrize("field,value", [("name", 12), ("code", [])])
def test_invalid_stage_display_type_rejected_during_import(field, value):
    tables = miniature()
    tables["stage_table"]["stages"]["test_1"][field] = value
    with pytest.raises(ValueError, match="显示字段"):
        validate_tables(tables)


def test_invalid_catalog_display_type_has_explicit_data_error(runtime, admin):
    runtime.data.stages["test_1"]["name"] = 12
    response = admin.get("/api/catalog/stages")
    assert response.status_code == 503 and response.json()["code"] == "GAMEDATA_INVALID"


@pytest.mark.parametrize("action", [
    "grant-item", "set-item", "grant-operator", "set-acquisition-count", "unlock-stage",
])
def test_missing_action_identifier_is_rejected_without_save_or_audit_changes(admin, action):
    before, logs = admin.get("/api/accounts/1").json(), admin.get("/api/logs").json()["audit"]
    response = admin.post("/api/gm", json={"accountId": 1, "action": action, "value": 1})
    assert response.status_code == 422
    assert admin.get("/api/accounts/1").json() == before
    assert admin.get("/api/logs").json()["audit"] == logs


@pytest.mark.parametrize("identifier", [None, "", " ", "bad id", 123, []])
def test_invalid_item_identifier_is_rejected_without_mutation(admin, identifier):
    before, logs = admin.get("/api/accounts/1").json(), admin.get("/api/logs").json()["audit"]
    response = admin.post("/api/gm", json={"accountId": 1, "action": "grant-item", "id": identifier, "value": 1})
    assert response.status_code == 422
    assert admin.get("/api/accounts/1").json() == before
    assert admin.get("/api/logs").json()["audit"] == logs


@pytest.mark.parametrize("identifier", [None, [], 123, "", " "])
def test_domain_item_lookup_rejects_invalid_identifiers(runtime, identifier):
    with pytest.raises(DomainError) as result:
        runtime.data.item(identifier)
    assert result.value.code == "INVALID_ITEM_ID" and result.value.status == 400


def test_valid_item_commands_and_action_without_identifier_still_work(admin):
    before = admin.get("/api/accounts/1").json()["user"]["inventory"].get("material", 0)
    assert admin.post("/api/gm", json={"accountId": 1, "action": "grant-item",
                                      "id": "material", "value": 2}).status_code == 200
    assert admin.get("/api/accounts/1").json()["user"]["inventory"]["material"] == before + 2
    assert admin.post("/api/gm", json={"accountId": 1, "action": "set-item",
                                      "id": "material", "value": 4}).status_code == 200
    assert admin.get("/api/accounts/1").json()["user"]["inventory"]["material"] == 4
    assert admin.post("/api/gm", json={"accountId": 1, "action": "set-sanity", "value": 7}).status_code == 200
    logs = admin.get("/api/logs").json()["audit"]
    assert [entry["action"] for entry in logs[:3]] == ["set-sanity", "set-item", "grant-item"]
