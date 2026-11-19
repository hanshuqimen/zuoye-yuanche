"""The frozen native ten cost, detail view and contradictory saved histories."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_headhunting import head_runtime, login, pull  # noqa: F401 -- shared validated fixture
from test_recruitment import recruit_runtime  # noqa: F401 -- dependency of head_runtime

from terralocal.server.domain.headhunting import POLICY
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply

NATIVE_COST = [{"id": "4003", "count": 3800}]


def funded(request):
    runtime = request.getfixturevalue("head_runtime")
    with runtime.database.transaction() as session:
        session.get(m.Currency, (1, "4003")).balance = 10000
    return runtime, login(runtime)


def test_frozen_combine_ten_cost_is_atomic_for_concurrent_retries(request):
    runtime, token = funded(request)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(
                lambda _: pull(client, token, 1, count=10, useTkt=9, itemList=NATIVE_COST), range(8)))
        assert all(r.status_code == 200 for r in responses)
        result = responses[0].json()
        assert all(r.json() == result for r in responses)
    after = runtime.sync(token)["user"]
    assert apply(before, result["playerDataDelta"]) == after
    assert len(result["gachaResultList"]) == 10
    assert after["status"]["diamondShard"] == 6200
    assert after["gacha"]["newbee"]["cnt"] == 11
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.GachaHistory).count() == 10
        state = session.get(m.GachaPity, (1, "BOOT_0_1_3"))
        assert state.total_pulls == state.rng_counter == 10


@pytest.mark.parametrize("items", [None, [], [{"id": "4003", "count": 1}],
                                   [{"id": "4003", "count": 3799}],
                                   [{"id": "4003", "count": 3801}],
                                   [{"id": "4002", "count": 3800}],
                                   [{"id": "4003", "count": 1900}] * 2,
                                   NATIVE_COST * 2])
def test_untrusted_combine_cost_cannot_change_save_or_charge(request, items):
    runtime, token = funded(request)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        response = pull(client, token, 1, count=10, useTkt=9, itemList=items)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_GACHA_PAYMENT"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.GachaHistory).count() == session.query(m.GachaPity).count() == 0


def test_native_ten_with_insufficient_orundum_leaves_everything_unchanged(request):
    runtime = request.getfixturevalue("head_runtime")
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1, count=10, useTkt=9, itemList=NATIVE_COST).status_code == 400
    assert runtime.sync(token) == before


def test_detail_contract_matches_draw_roster_rates_and_does_not_write(request):
    runtime, token = funded(request)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        response = client.post("/gacha/getPoolDetail", json={
            "poolId": "BOOT_0_1_3", "gachaObjGroupType": 0}, headers={"secret": token})
        assert response.status_code == 200
        detail = response.json()
        assert detail["gachaObjGroupType"] == 0 and detail["hasRateUp"] is False
        assert "playerDataDelta" not in detail
        expected = runtime.data.headhunting.newcomer["BOOT_0_1_3"]
        groups = detail["detailInfo"]["availCharInfo"]["perAvailList"]
        assert len(groups) == 4
        assert sum(r["totalPercent"] for r in groups) == pytest.approx(1)
        for row in groups:
            assert row["charIdList"] == expected["characters"][row["rarityRank"]]
            assert row["totalPercent"] == expected["weights"][row["rarityRank"]] / 10000
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.Receipt).count() == session.query(m.GachaHistory).count() == 0


def test_detail_does_not_reopen_an_exhausted_pool(request):
    runtime, token = funded(request)
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1, count=10, useTkt=9, itemList=NATIVE_COST).status_code == 200
        assert pull(client, token, 2, count=10, useTkt=9, itemList=NATIVE_COST).status_code == 200
        assert pull(client, token, 3).status_code == 200
        before = runtime.sync(token)
        assert before["user"]["gacha"]["newbee"]["cnt"] == 0
        assert client.post("/gacha/getPoolDetail", json={
            "poolId": "BOOT_0_1_3", "gachaObjGroupType": 0}, headers={"secret": token}).status_code == 200
        assert runtime.sync(token) == before
        assert pull(client, token, 4).status_code == 409
        assert runtime.sync(token) == before


@pytest.mark.parametrize("body,status,code", [
    ({"poolId": "UNKNOWN", "gachaObjGroupType": 0}, 404, "UNKNOWN_GACHA_POOL"),
    ({"poolId": "NORM_TEST", "gachaObjGroupType": 0}, 503, "GACHA_DETAIL_NOT_READY"),
    ({"poolId": "BOOT_0_1_3", "gachaObjGroupType": 1}, 400, "INVALID_GACHA_GROUP"),
    ({"poolId": "BOOT_0_1_3", "gachaObjGroupType": True}, 422, "INVALID_REQUEST"),
])
def test_detail_rejects_unknown_or_incompatible_groups_without_writes(request, body, status, code):
    runtime, token = funded(request)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert client.post("/gacha/getPoolDetail", json={
            "poolId": "BOOT_0_1_3", "gachaObjGroupType": 0}).status_code == 401
        response = client.post("/gacha/getPoolDetail", json=body, headers={"secret": token})
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
    assert runtime.sync(token) == before


@pytest.mark.parametrize("field", ["pulls_without_six", "guarantee_used", "rarity"])
def test_contradictory_history_cannot_advance_rng_or_spend_currency(request, monkeypatch, field):
    import random

    runtime, token = funded(request)
    monkeypatch.setattr(random.Random, "choices", lambda *a, **k: [2])
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1).status_code == 200
        with runtime.database.transaction() as session:
            state = session.get(m.GachaPity, (1, "BOOT_0_1_3"))
            if field == "rarity":
                session.query(m.GachaHistory).one().rarity = 3
            elif field == "guarantee_used":
                state.guarantee_used = True
            else:
                state.pulls_without_six = 0
        before = runtime.sync(token)
        response = pull(client, token, 2)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "INVALID_HEADHUNTING_STATE"
    assert runtime.sync(token) == before


def test_a_six_after_the_first_ten_cannot_hide_broken_first_ten_history(request):
    runtime, token = funded(request)
    with runtime.database.transaction() as session:
        session.add(m.GachaPity(account_id=1, group_id="BOOT_0_1_3", total_pulls=11,
                                rng_counter=11, pulls_without_six=0, guarantee_used=True, seed=1,
                                policy_version=POLICY, gamedata_hash=runtime.data.manifest["hash"]))
        session.add_all(m.GachaHistory(account_id=1, banner_id="BOOT_0_1_3", char_id="char_recruit_2",
                                       rarity=2, is_new=False, drawn_at=1_800_000_000) for _ in range(10))
        session.add(m.GachaHistory(account_id=1, banner_id="BOOT_0_1_3", char_id="char_recruit_5",
                                   rarity=5, is_new=False, drawn_at=1_800_000_000))
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        response = pull(client, token, 1)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "INVALID_HEADHUNTING_STATE"
    assert runtime.sync(token) == before
