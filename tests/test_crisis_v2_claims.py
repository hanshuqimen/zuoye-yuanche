"""Local-only reward claims against an authored database and fixture catalog."""

import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_crisis_v2_clears import begin, finish, map_row, request, setup, source
from test_crisis_v2_persistence import rows

from terralocal.server.domain.accounts import login
from terralocal.server.main import create_game_app
from terralocal.server.persistence.models import CrisisV2MapProgress, OwnedFurniture
from terralocal.server.services.backups import backup_existing_save, recover_backup
from terralocal.server.services.runtime import Runtime

PATH = "/local/v1/crisis-v2/claim-treasure"
PAYLOAD = {"seasonId": "season_a", "mapId": "season_a_p", "slotId": "treasure"}
ITEM = "authored-crisis-chair"


def fixture_tables(reward_type="FURN"):
    tables = source()
    tables["item_table"]["items"][ITEM] = {"itemId": ITEM, "itemType": "FURN", "name": "Authored chair"}
    detail = tables["crisis_v2_server_table"]["seasons"]["season_a"]["info"]["mapDetailDataMap"]["season_a_p"]
    detail["rewardNodeDataMap"]["treasure"]["reward"] = {"id": ITEM, "type": reward_type, "count": 1}
    return tables


def prepare(directory, reward_type="FURN"):
    runtime, token, payload = setup(directory, tables=fixture_tables(reward_type))
    return runtime, token, payload


def clear(runtime, token, payload):
    ident = begin(runtime, token, payload)["battleId"]
    return finish(runtime, token, request(ident, payload))


def claim(client, token, key, payload=None):
    headers = {"secret": token}
    if key is not None:
        headers["idempotency-key"] = key
    return client.post(PATH, json=PAYLOAD if payload is None else payload, headers=headers)


def inventory(runtime):
    with runtime.database.transaction(write=False) as session:
        item = session.get(OwnedFurniture, (1, ITEM))
        return item.count if item else 0


def save_state(runtime):
    return map_row(runtime)["rewards"]["treasure"]


def test_only_cleared_owner_can_claim_and_duplicate_never_regrants(tmp_path):
    runtime, token, payload = prepare(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            before = rows(runtime.database.path)
            assert claim(client, token, None).status_code == 400
            assert claim(client, token, "early").status_code == 409
            assert claim(client, "invalid-token", "unknown").status_code == 401
            assert claim(client, token, "wrong", PAYLOAD | {"mapId": "season_a_t"}).status_code == 404
            assert rows(runtime.database.path) == before
            clear(runtime, token, payload)
            assert save_state(runtime) == {"state": 1, "progress": 2}
            result = claim(client, token, "claim").raise_for_status().json()
            assert result["rewards"] == [{"id": ITEM, "type": "FURN", "count": 1}]
            assert save_state(runtime) == {"state": 2, "progress": 2}
            assert inventory(runtime) == 1
            assert claim(client, token, "claim").json() == result
            assert claim(client, token, "different").json()["error"]["code"] == "CRISIS_V2_CLAIM_ALREADY_TAKEN"
            assert claim(client, token, "claim", PAYLOAD | {"slotId": "another"}).json()["error"]["code"] == (
                "IDEMPOTENCY_CONFLICT"
            )
            assert inventory(runtime) == 1
    finally:
        runtime.database.close()


@pytest.mark.parametrize("reward_type", ["UNKNOWN_TYPE", "CHAR_SKIN"])
def test_unsupported_or_wrong_type_never_consumes_claim(tmp_path, reward_type):
    runtime, token, payload = prepare(tmp_path, reward_type)
    try:
        clear(runtime, token, payload)
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            result = claim(client, token, "unsupported")
        assert result.status_code == (501 if reward_type == "UNKNOWN_TYPE" else 503)
        assert rows(runtime.database.path) == before
        assert inventory(runtime) == 0
    finally:
        runtime.database.close()


def test_impossible_marker_and_grant_exception_roll_back(tmp_path, monkeypatch):
    from terralocal.server.domain.context import Context

    runtime, token, payload = prepare(tmp_path)
    try:
        clear(runtime, token, payload)
        with runtime.database.transaction() as session:
            progress = session.get(CrisisV2MapProgress, (1, "season_a", "season_a_p"))
            progress.rewards = {"treasure": {"state": 1, "progress": 1}}
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            assert claim(client, token, "bad").status_code == 503
        assert rows(runtime.database.path) == before
        with runtime.database.transaction() as session:
            progress = session.get(CrisisV2MapProgress, (1, "season_a", "season_a_p"))
            progress.rewards = {"treasure": {"state": 1, "progress": 2}}
        before = rows(runtime.database.path)
        grant = Context.rewards

        def fail_after_grant(ctx, *args, **kwargs):
            from terralocal.server.domain.errors import DomainError

            grant(ctx, *args, **kwargs)
            raise DomainError("QA_FAILURE", "authored failure", 503)

        monkeypatch.setattr(Context, "rewards", fail_after_grant)
        with TestClient(create_game_app(runtime)) as client:
            assert claim(client, token, "failed-grant").status_code == 503
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_concurrent_claim_and_cross_session_retry_survive_backup_restore(tmp_path):
    runtime, token, payload = prepare(tmp_path)
    try:
        clear(runtime, token, payload)
        with TestClient(create_game_app(runtime)) as client, ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda key: claim(client, token, key), ("one", "two")))
        assert sorted(result.status_code for result in results) == [200, 409]
        winner = 0 if results[0].status_code == 200 else 1
        key, reply = ("one", "two")[winner], results[winner].json()
        assert inventory(runtime) == 1
        settings = runtime.settings
    finally:
        runtime.database.close()
    backup = backup_existing_save(settings)
    recover_backup(settings, backup["name"], settings.data_dir / "restored.sqlite3")
    restored_dir = tmp_path / "restored"
    shutil.copytree(settings.data_dir / "cache", restored_dir / "cache")
    shutil.copyfile(settings.data_dir / "restored.sqlite3", restored_dir / "terralocal.sqlite3")
    restored = Runtime(settings.model_copy(update={"data_dir": restored_dir}))
    try:
        with restored.database.transaction() as session:
            fresh_token = login(session, restored.settings, name="CrisisDoctor")["secret"]
        with TestClient(create_game_app(restored)) as client:
            assert claim(client, fresh_token, key).json() == reply
            assert claim(client, fresh_token, "after-restore").status_code == 409
        assert inventory(restored) == 1
        assert save_state(restored) == {"state": 2, "progress": 2}
    finally:
        restored.database.close()


def test_skin_claim_uses_owned_skin_table_and_does_not_change_roster(tmp_path):
    from terralocal.server.persistence.models import OwnedSkin

    tables = fixture_tables("CHAR_SKIN")
    skin = "char_synthetic#authored-crisis"
    tables["skin_table"] = {"charSkins": {skin: {"skinId": skin, "charId": "char_synthetic",
        "tmplId": None, "isBuySkin": True, "displaySkin": {"skinName": "Authored outfit"}}}}
    detail = tables["crisis_v2_server_table"]["seasons"]["season_a"]["info"]["mapDetailDataMap"]["season_a_p"]
    detail["rewardNodeDataMap"]["treasure"]["reward"]["id"] = skin
    runtime, token, payload = setup(tmp_path, tables=tables)
    try:
        clear(runtime, token, payload)
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            result = claim(client, token, "skin").raise_for_status().json()
        assert result["rewards"] == [{"id": skin, "type": "CHAR_SKIN", "count": 1}]
        assert rows(runtime.database.path)["operators"] == before["operators"]
        with runtime.database.transaction(write=False) as session:
            assert session.get(OwnedSkin, (1, skin)) is not None
    finally:
        runtime.database.close()


def test_closed_season_does_not_consume_earned_reward(tmp_path):
    from crisis_v2_qa import set_time

    runtime, token, payload = prepare(tmp_path)
    try:
        clear(runtime, token, payload)
        set_time(runtime, 2000)
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            result = claim(client, token, "expired")
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "CRISIS_V2_CLAIM_CLOSED"
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


@pytest.mark.parametrize("malformed", [False, True])
def test_pack_grants_only_bound_material_contents(tmp_path, malformed):
    from terralocal.server.persistence.models import InventoryItem

    tables = fixture_tables("ITEM_PACK")
    item_table = tables["item_table"]
    item_table["items"][ITEM]["itemType"] = "ITEM_PACK"
    material = "authored-material"
    item_table["items"][material] = {"itemId": material, "itemType": "MATERIAL", "name": "Authored part"}
    reward = {"id": material, "count": 3, "type": "MATERIAL"}
    contents = [reward, reward] if malformed else [reward]
    item_table["itemPackInfos"] = {ITEM: {"packId": ITEM, "content": contents}}
    runtime, token, payload = setup(tmp_path, tables=tables)
    try:
        clear(runtime, token, payload)
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            result = claim(client, token, "pack")
        if malformed:
            assert result.status_code == 503
            assert rows(runtime.database.path) == before
        else:
            assert result.raise_for_status().json()["rewards"] == [reward]
            with runtime.database.transaction(write=False) as session:
                assert session.get(InventoryItem, (1, material)).count == 3
                assert session.get(InventoryItem, (1, ITEM)) is None
            assert save_state(runtime) == {"state": 2, "progress": 2}
    finally:
        runtime.database.close()