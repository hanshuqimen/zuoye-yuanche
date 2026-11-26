"""Native coin batches against authored data; no native gameplay claims."""

import copy
import hashlib
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from crisis_v2_qa import set_time
from fastapi.testclient import TestClient
from test_crisis_v2_claims import ITEM, fixture_tables
from test_crisis_v2_clears import setup
from test_crisis_v2_native_missions import inventory, send
from test_crisis_v2_persistence import rows

from terralocal.server.domain import crisis_v2_missions
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import backup_existing_save, recover_backup
from terralocal.server.services.runtime import Runtime

BODY = {"mapId": "season_a_p", "missions": [{"id": "bag", "type": 0}, {"id": "challenge", "type": 1}]}
COIN = {"id": "crisis_coin", "type": "CRS_SHOP_COIN_V2", "count": 11}


def tables():
    source = fixture_tables()
    source["item_table"]["items"].update(
        {
            "4001": {"itemId": "4001", "itemType": "GOLD", "name": "Authored gold"},
            "authored-exp": {"itemId": "authored-exp", "itemType": "CARD_EXP", "name": "Authored record"},
            "authored-mat": {"itemId": "authored-mat", "itemType": "MATERIAL", "name": "Authored material"},
        }
    )
    info = source["crisis_v2_server_table"]["seasons"]["season_a"]["info"]
    for map_id, detail in info["mapDetailDataMap"].items():
        if map_id.endswith("_p"):
            detail["bagDataMap"]["bag"]["slotPackRewards"] = [COIN | {"count": 7}]
        detail["challengeNodeDataMap"]["challenge"]["rewardList"] = [
            {"isTimeLimit": map_id.endswith("_t"), "reward": dict(COIN)},
            *(
                {"isTimeLimit": False, "reward": {"id": ident, "type": kind, "count": count}}
                for ident, kind, count in (
                    ("4001", "GOLD", 5),
                    ("authored-exp", "CARD_EXP", 2),
                    ("authored-mat", "MATERIAL", 3),
                )
            ),
        ]
    return source


def prepare(directory, *, at=1201, source=None, local_shop=False):
    runtime, token, _ = setup(directory, tables=tables() if source is None else source)
    set_time(runtime, at)
    with runtime.database.transaction() as session:
        for map_id in ("season_a_p", "season_a_t"):
            row = session.get(m.CrisisV2MapProgress, (1, "season_a", map_id))
            row.cleared = True
            row.challenges = {"challenge": 1}
            if map_id.endswith("_p"):
                row.rune_packs = {"bag": 1}
                row.rewards = {"treasure": {"state": 1, "progress": 2}}
    if local_shop:
        settings = runtime.settings
        runtime.database.close()
        (settings.data_dir / "crisis_v2_local_shop.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "gameDataHash": settings.gamedata_hash,
                    "seasonId": "season_a",
                    "credits": {"season_a_p": 6},
                    "offers": [{"id": "chair", "price": 4, "stock": 1, "itemId": ITEM, "itemType": "FURN"}],
                }
            ),
            "utf8",
        )
        runtime = Runtime(settings)
    return runtime, token


def balances(runtime, account=1):
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, account)
        return {
            "shop": session.get(m.CrisisV2Account, account).shop_coin,
            "coin_inventory": ctx.balance("crisis_coin"),
            "gold": ctx.balance("4001"),
            "exp": ctx.balance("authored-exp"),
            "material": ctx.balance("authored-mat"),
            "season_coin": session.get(m.CrisisV2Season, (account, "season_a")).coin,
        }


def test_mixed_missions_delta_business_retry_and_overlap(tmp_path):
    runtime, token = prepare(tmp_path)
    body = BODY | {"missions": [*BODY["missions"], {"id": "treasure", "type": 2}]}
    try:
        base = balances(runtime)
        with TestClient(create_game_app(runtime)) as client:
            before = runtime.sync(token)["user"]
            reply = send(client, token, "mixed", body).raise_for_status().json()
            after = runtime.sync(token)["user"]
            assert apply(before, reply["playerDataDelta"]) == after
            assert after["crisisV2"]["shop"]["coin"] == 18
            assert reply["rewards"] == [
                {"id": "authored-exp", "type": "CARD_EXP", "count": 2},
                COIN | {"count": 18},
                {"id": ITEM, "type": "FURN", "count": 1},
                {"id": "4001", "type": "GOLD", "count": 5},
                {"id": "authored-mat", "type": "MATERIAL", "count": 3},
            ]
            assert send(client, token, "mixed", body).json() == reply
            reversed_body = body | {"missions": list(reversed(body["missions"]))}
            again = send(client, token, "fresh", reversed_body).raise_for_status().json()
            assert again["ts"] == reply["ts"] and again["rewards"] == reply["rewards"]
            assert again["playerDataDelta"] == {"modified": {}, "deleted": {}}
            assert send(client, token, "overlap", BODY).status_code == 409
            assert inventory(runtime) == 1
        assert balances(runtime) == base | {"shop": 18, "gold": base["gold"] + 5, "exp": 2, "material": 3}
    finally:
        runtime.database.close()


@pytest.mark.parametrize("at,earned", [(1698, 11), (1699, 0), (1700, 0)])
def test_temporary_deadline_filters_only_timed_items(tmp_path, at, earned):
    runtime, token = prepare(tmp_path, at=at)
    body = {"mapId": "season_a_t", "missions": [{"id": "challenge", "type": 1}]}
    try:
        base = balances(runtime)
        with TestClient(create_game_app(runtime)) as client:
            reply = send(client, token, "temporary", body).raise_for_status().json()
            assert sum(item["count"] for item in reply["rewards"] if item["type"] == COIN["type"]) == earned
            set_time(runtime, 1900)
            again = send(client, token, "later", body).raise_for_status().json()
            assert again["rewards"] == reply["rewards"] and again["ts"] == reply["ts"]
        assert balances(runtime) == base | {"shop": earned, "gold": base["gold"] + 5, "exp": 2, "material": 3}
    finally:
        runtime.database.close()


@pytest.mark.parametrize("fault", ["not-ready", "not-cleared", "unknown", "bad-count", "bad-coin-id"])
def test_failed_last_mission_rolls_back_all_rewards_and_rows(tmp_path, fault):
    source = tables()
    definition = source["crisis_v2_server_table"]["seasons"]["season_a"]["info"]["mapDetailDataMap"][
        "season_a_p"
    ]
    if fault == "bad-count":
        definition["challengeNodeDataMap"]["challenge"]["rewardList"][0]["reward"]["count"] = True
    elif fault == "bad-coin-id":
        source["item_table"]["items"]["other-coin"] = {
            "itemId": "other-coin",
            "itemType": COIN["type"],
            "name": "Another mode coin",
        }
        definition["challengeNodeDataMap"]["challenge"]["rewardList"][0]["reward"]["id"] = "other-coin"
    runtime, token = prepare(tmp_path, source=source)
    body = copy.deepcopy(BODY)
    try:
        if fault in {"not-ready", "not-cleared"}:
            with runtime.database.transaction() as session:
                row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
                if fault == "not-ready":
                    row.challenges = {"challenge": 0}
                else:
                    row.cleared = False
        if fault == "unknown":
            body["missions"][1]["id"] = "unknown"
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            result = send(client, token, "bad-batch", body)
            assert (
                result.status_code
                == {
                    "not-ready": 409,
                    "not-cleared": 409,
                    "unknown": 404,
                    "bad-count": 503,
                    "bad-coin-id": 503,
                }[fault]
            )
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_other_account_and_future_map_cannot_claim_and_racing_batches_grant_once(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        with runtime.database.transaction() as session:
            create_account(session, runtime.data, "OtherDoctor")
            other = login(session, runtime.settings, name="OtherDoctor")["secret"]
        with TestClient(create_game_app(runtime)) as client:
            assert send(client, other, "other", BODY).status_code == 409
            set_time(runtime, 1199)
            temp = {"mapId": "season_a_t", "missions": [{"id": "challenge", "type": 1}]}
            assert send(client, token, "early", temp).status_code == 409
            set_time(runtime, 1201)
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(lambda key: send(client, token, key, BODY), ("race-a", "race-b")))
            assert [r.status_code for r in replies] == [200, 200]
        assert balances(runtime)["shop"] == 18 and balances(runtime, 2)["shop"] == 0
    finally:
        runtime.database.close()


def test_post_grant_failure_rolls_back_balance_task_and_inventory(tmp_path, monkeypatch):
    runtime, token = prepare(tmp_path)
    original = crisis_v2_missions.validate

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise DomainError("QA_POST_GRANT", "Authored post-grant failure", 503)

    monkeypatch.setattr(crisis_v2_missions, "validate", fail)
    try:
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            assert send(client, token, "post-grant", BODY).status_code == 503
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


def test_separate_credit_batches_share_wallet_without_replaying_spent_inventory(tmp_path):
    runtime, token = prepare(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            bag = BODY | {"missions": [BODY["missions"][0]]}
            challenge = BODY | {"missions": [BODY["missions"][1]]}
            first = send(client, token, "bag", bag).raise_for_status().json()
            assert balances(runtime)["shop"] == 7
            send(client, token, "challenge", challenge).raise_for_status()
            with runtime.database.transaction() as session:
                Context(session, runtime.data, 1).change_item("authored-mat", -2)
            before = balances(runtime)
            again = send(client, token, "old-bag", bag).raise_for_status().json()
            assert again["rewards"] == first["rewards"]
            assert again["playerDataDelta"] == {"modified": {}, "deleted": {}}
            assert balances(runtime) == before and before["shop"] == 18 and before["material"] == 1
    finally:
        runtime.database.close()


def test_fully_expired_task_keeps_unclaimed_state_and_does_not_issue_an_empty_success(tmp_path):
    source = tables()
    detail = source["crisis_v2_server_table"]["seasons"]["season_a"]["info"]["mapDetailDataMap"]["season_a_t"]
    detail["challengeNodeDataMap"]["challenge"]["rewardList"] = [{"isTimeLimit": True, "reward": COIN}]
    runtime, token = prepare(tmp_path, at=1700, source=source)
    try:
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            response = send(
                client,
                token,
                "expired",
                {"mapId": "season_a_t", "missions": [{"id": "challenge", "type": 1}]},
            )
            assert (
                response.status_code == 409 and response.json()["error"]["code"] == "CRISIS_V2_CLAIM_CLOSED"
            )
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()


@pytest.mark.parametrize("damage", ["balance", "receipt", "claimed", "deleted-credit"])
def test_damaged_credit_is_refused_before_writable_startup(tmp_path, damage):
    runtime, token = prepare(tmp_path)
    with TestClient(create_game_app(runtime)) as client:
        send(client, token, "credit", BODY).raise_for_status()
    settings = runtime.settings
    runtime.database.close()
    with sqlite3.connect(settings.database_path) as db:
        if damage == "balance":
            db.execute("UPDATE crisis_v2_accounts SET shop_coin=shop_coin+1")
        elif damage == "claimed":
            db.execute("UPDATE crisis_v2_maps SET challenges='{}' WHERE map_id='season_a_p'")
        elif damage == "deleted-credit":
            db.execute(
                "DELETE FROM receipts WHERE substr(key,1,?)=?",
                (len(crisis_v2_missions.PREFIX), crisis_v2_missions.PREFIX),
            )
        else:
            key, raw = db.execute(
                "SELECT key,result FROM receipts WHERE substr(key,1,?)=?",
                (len(crisis_v2_missions.PREFIX), crisis_v2_missions.PREFIX),
            ).fetchone()
            value = json.loads(raw)
            next(item for item in value["response"]["rewards"] if item["type"] == COIN["type"])["count"] += 1
            db.execute("UPDATE receipts SET result=? WHERE key=?", (json.dumps(value), key))
    digest = hashlib.sha256(settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="任务|代币"):
        Runtime(settings)
    assert hashlib.sha256(settings.database_path.read_bytes()).hexdigest() == digest


def test_local_shop_spends_native_credit_and_backup_restores_both_ledgers(tmp_path):
    runtime, token = prepare(tmp_path, local_shop=True)
    base = balances(runtime)
    with TestClient(create_game_app(runtime)) as client:
        send(client, token, "native-credit", BODY).raise_for_status()
        prefix = "/local/v1/crisis-v2/shop"
        headers = {"secret": token, "idempotency-key": "local-purchase"}
        result = (
            client.post(prefix + "/buy", headers=headers, json={"offerId": "chair"}).raise_for_status().json()
        )
        assert result["coin"] == 14 and inventory(runtime) == 1
        assert client.post(prefix + "/buy", headers=headers, json={"offerId": "chair"}).json() == result
        credit = (
            client.post(
                prefix + "/claim-credit",
                headers={"secret": token, "idempotency-key": "local-credit"},
                json={"mapId": "season_a_p"},
            )
            .raise_for_status()
            .json()
        )
        assert credit["coin"] == 20
    settings = runtime.settings
    runtime.database.close()
    backup = backup_existing_save(settings)
    recovered = settings.data_dir / "recovered.sqlite3"
    recover_backup(settings, backup["name"], recovered)
    restored_dir = tmp_path / "restored"
    shutil.copytree(settings.data_dir / "cache", restored_dir / "cache")
    shutil.copyfile(recovered, restored_dir / "terralocal.sqlite3")
    shutil.copyfile(
        settings.data_dir / "crisis_v2_local_shop.json", restored_dir / "crisis_v2_local_shop.json"
    )
    restored = Runtime(settings.model_copy(update={"data_dir": restored_dir}))
    try:
        with restored.database.transaction() as session:
            fresh = login(session, restored.settings, name="CrisisDoctor")["secret"]
        with TestClient(create_game_app(restored)) as client:
            again = send(client, fresh, "after-restore", BODY).raise_for_status().json()
            assert again["playerDataDelta"] == {"modified": {}, "deleted": {}}
        assert balances(restored) == base | {"shop": 20, "gold": base["gold"] + 5, "exp": 2, "material": 3}
        assert inventory(restored) == 1
    finally:
        restored.database.close()
