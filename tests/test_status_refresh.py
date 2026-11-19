import json

import pytest
from sqlalchemy import select

from terralocal.server.domain import accounts
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply


def refresh(client, token, modules=16, params=None):
    return client.post("/account/syncStatus", json={"modules": modules, "params": params or {}},
                       headers={"secret": token})


def test_refresh_reasserts_scoped_purchase_counters_and_keeps_history(runtime, client, token):
    with runtime.database.transaction() as session:
        other = accounts.create_account(session, runtime.data, "Other")
        for owner, shop, good, period, bought in [
            (1, "CASH", "local-synthetic", "permanent", 1),
            (1, "GP:monthly", "local-month", "2027-01", 2),
            (1, "GP:monthly", "local-month-old", "2026-12", 5),
            (other.id, "CASH", "foreign", "permanent", 9),
        ]:
            session.add(m.ShopState(account_id=owner, shop_id=shop, offer_id=good, period=period, bought=bought))
    # Fixture clock 1_800_000_000 falls in January 2027 in CN's business clock.
    state = runtime.sync(token)["user"]
    # Observed 2.7.71 CLR contract: Dictionary<string, PlayerGoodProgressData>.
    # An empty array here aborts the entire login before the homepage loads.
    assert isinstance(state["shop"]["HS"]["progressInfo"], dict)
    params = {"16": {"goodIdMap": {"GP": ["local-synthetic"], "CASH": []}}}
    response = refresh(client, token, params=params)
    assert response.status_code == 200
    shop = response.json()["playerDataDelta"]["modified"]["shop"]
    assert isinstance(shop["HS"]["progressInfo"], dict)
    assert shop["CASH"]["info"] == [{"id": "local-synthetic", "count": 1}]
    assert shop["GP"]["monthly"]["info"] == [{"id": "local-month", "count": 2}]
    assert apply(state, response.json()["playerDataDelta"]) == runtime.sync(token)["user"]
    with runtime.database.transaction(write=False) as session:
        assert len(list(session.scalars(select(m.ShopState)))) == 4
        assert session.get(m.PlayerProfile, 1).revision == 0


def test_sanity_recovery_refresh_matches_full_snapshot(runtime, client, token):
    with runtime.database.transaction() as session:
        session.get(m.SanityState, 1).current = 2
    before = runtime.sync(token)["user"]
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 720
    response = refresh(client, token)
    after = runtime.sync(token)["user"]
    assert after["status"]["ap"] == 4
    assert apply(before, response.json()["playerDataDelta"]) == after
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.PlayerProfile, 1).revision == 1


def test_unknown_refresh_module_invalid_params_and_unauthorized_fail_explicitly(client, runtime, token):
    before = runtime.sync(token)
    unknown = refresh(client, token, modules=256)
    assert unknown.status_code == 501 and unknown.json()["error"]["code"] == "NOT_IMPLEMENTED"
    assert refresh(client, token, modules=0, params={"16": {"goodIdMap": {}}}).status_code == 400
    assert refresh(client, token, modules=16, params={"1": {"goodIdMap": {}}}).status_code == 400
    assert refresh(client, "invalid").status_code == 401
    assert refresh(client, token, modules=True).status_code == 422
    assert runtime.sync(token) == before
    log = (runtime.settings.data_dir / "logs/requests.jsonl").read_text("utf-8")
    assert '"sync_modules": 256' in log and token not in log


def test_purchase_query_uses_cash_alias_for_furniture_and_rejects_save_branch_name(client, runtime, token):
    before = runtime.sync(token)
    assert refresh(client, token, modules=16,
                   params={"16": {"goodIdMap": {"FURNI": ["synthetic-furniture"]}}}).status_code == 422
    assert runtime.sync(token) == before
    empty = refresh(client, token, modules=16,
                    params={"16": {"goodIdMap": {"CASH": ["synthetic-furniture"]}}})
    assert empty.status_code == 200
    with runtime.database.transaction() as session:
        session.add(m.ShopState(account_id=1, shop_id="FURNI", offer_id="synthetic-furniture",
                                period="permanent", bought=1))
    purchased = runtime.sync(token)
    response = refresh(client, token, modules=16,
                       params={"16": {"goodIdMap": {"CASH": ["synthetic-furniture"]}}})
    # Its total purchase cap still requires a verified catalog; never hide
    # an actual queried purchase behind an empty success result.
    assert response.status_code == 501
    assert runtime.sync(token) == purchased


def test_real_startup_modules_refresh_only_known_or_uninitialized_state(client, runtime, token):
    before = runtime.sync(token)["user"]
    response = refresh(client, token, modules=3807, params={"16": {"goodIdMap": {"GP": ["synthetic-pack"]}}})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["4"]["announcementVersion"] == "1"
    assert result["2048"] == {"gacha": [], "shop": []}
    assert result["16"] == {"goodPurchaseState": {"result": {}}}
    assert set(result) == {"1", "2", "4", "8", "16", "64", "128", "512", "1024", "2048"}
    assert apply(before, response.json()["playerDataDelta"]) == runtime.sync(token)["user"]
    assert runtime.sync(token)["user"]["status"]["progress"] == 0
    assert runtime.sync(token)["user"]["status"]["flags"] == {}
    assert "shop" not in response.json()["playerDataDelta"]["modified"]
    assert "mainStageProgress" not in response.json()["playerDataDelta"]["modified"].get("status", {})


@pytest.mark.parametrize("modules", [3207, 3807])
def test_existing_base_or_event_state_cannot_be_silently_skipped(client, runtime, token, modules):
    with runtime.database.transaction() as session:
        session.add(m.Building(account_id=1, control_level=1, last_settled_at=1))
    before = runtime.sync(token)
    assert refresh(client, token, modules=modules).status_code == 501
    assert runtime.sync(token) == before
    with runtime.database.transaction() as session:
        session.delete(session.get(m.Building, 1))
        session.add(m.EventProgress(account_id=1, event_id="synthetic", key="progress", value={"count": 1}))
    assert refresh(client, token, modules=512).status_code == 501


def test_native_home_cross_day_mask_updates_checkpoint_and_logs_only_public_metadata(client, runtime, token):
    before = runtime.sync(token)["user"]
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 86400
    response = refresh(client, token, modules=3207)
    assert response.status_code == 200
    body = response.json()
    assert set(body["result"]) == {"1", "2", "4", "128", "1024", "2048"}
    assert body["playerDataDelta"]["modified"]["status"]["lastRefreshTs"] == body["ts"]
    assert apply(before, body["playerDataDelta"]) == runtime.sync(token)["user"]
    logs = (runtime.settings.data_dir / "logs/requests.jsonl").read_text("utf-8")
    logged = [json.loads(line) for line in logs.splitlines() if json.loads(line)["route"] == "/account/syncStatus"][-1]
    assert logged["status"] == 200 and logged["sync_modules"] == 3207
    assert "body_schema" not in logged and token not in logs


@pytest.mark.parametrize("modules", [3206, 2143, 2049])
def test_unobserved_smaller_masks_do_not_acknowledge_the_calendar(client, runtime, token, modules):
    before = runtime.sync(token)["user"]["status"]["lastRefreshTs"]
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 86400
    response = refresh(client, token, modules=modules)
    assert response.status_code == 200
    assert "lastRefreshTs" not in response.json()["playerDataDelta"]["modified"].get("status", {})
    assert runtime.sync(token)["user"]["status"]["lastRefreshTs"] == before


def test_queried_existing_purchase_state_requires_a_verified_derived_response(client, runtime, token):
    with runtime.database.transaction() as session:
        session.add(m.ShopState(account_id=1, shop_id="GP:level", offer_id="synthetic-pack",
                                period="permanent", bought=1))
    before = runtime.sync(token)
    assert refresh(client, token, params={"16": {"goodIdMap": {"GP": ["synthetic-pack"]}}}).status_code == 501
    assert runtime.sync(token) == before


def test_restrictions_and_mail_flags_are_account_scoped(client, runtime, token):
    with runtime.database.transaction() as session:
        other = accounts.create_account(session, runtime.data, "Other")
        session.get(m.PlayerProfile, other.id).flags = {"featureBans": {"shop": ["foreign-offer"]}}
        for row in session.scalars(select(m.Mail).where(m.Mail.account_id == 1)):
            row.read = True
        session.get(m.PlayerProfile, 1).flags = {"featureBans": {"gacha": ["local-banner"]}}
    response = refresh(client, token, modules=2049)
    assert response.json()["result"]["2048"] == {"gacha": ["local-banner"], "shop": []}
    assert response.json()["playerDataDelta"]["modified"]["pushFlags"]["hasGifts"] == 0
    with runtime.database.transaction() as session:
        session.get(m.PlayerProfile, 1).flags = {"featureBans": {"shop": "bad-state"}}
    assert refresh(client, token, modules=2048).status_code == 503
