"""Version-bound local extra-rune unlocks with no automatic grants."""

from concurrent.futures import ThreadPoolExecutor

from crisis_v2_qa import set_time
from fastapi.testclient import TestClient
from test_crisis_v2_clears import map_row, setup, source
from test_crisis_v2_persistence import rows

from terralocal.server.domain.accounts import create_account, login
from terralocal.server.main import create_game_app
from terralocal.server.persistence.models import CrisisV2MapProgress
from terralocal.server.services.runtime import Runtime

PATH = "/local/v1/crisis-v2/unlock-rune"
PAYLOAD = {"seasonId": "season_a", "mapId": "season_a_p", "slotId": "daily"}


def post(client, token, key, payload=None):
    return client.post(PATH, json=PAYLOAD if payload is None else payload,
                       headers={"secret": token, "idempotency-key": key})


def complete_temporary(runtime):
    # Explicit test seed, separate from end-to-end clear tests.
    with runtime.database.transaction() as session:
        session.get(CrisisV2MapProgress, (1, "season_a", "season_a_t")).cleared = True


def test_unlock_checks_gate_uses_own_progress_and_survives_cold_restart(tmp_path):
    runtime, token, _ = setup(tmp_path)
    try:
        with TestClient(create_game_app(runtime)) as client:
            assert post(client, token, "early").json()["error"]["code"] == "CRISIS_V2_UNLOCK_NOT_OPEN"
            set_time(runtime, 1300)
            assert post(client, token, "uncleared").json()["error"]["code"] == "CRISIS_V2_UNLOCK_NOT_READY"
            complete_temporary(runtime)
            assert post(client, token, "foreign-map", PAYLOAD | {"mapId": "season_a_t"}).status_code == 404
            assert post(client, token, "non-extra", PAYLOAD | {"slotId": "rune"}).status_code == 404
            with runtime.database.transaction() as session:
                create_account(session, runtime.data, "OtherDoctor")
                other = login(session, runtime.settings, name="OtherDoctor")["secret"]
            assert post(client, other, "other").json()["error"]["code"] == "CRISIS_V2_UNLOCK_NOT_READY"
            ids = ("first", "second")
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda k: post(client, token, k), ids))
            assert sorted(res.status_code for res in responses) == [200, 409]
            index = 0 if responses[0].status_code == 200 else 1
            winning_key, receipt = ids[index], responses[index].json()
            assert receipt["state"] == 2 and receipt["sourceMapId"] == "season_a_t"
            assert map_row(runtime)["extra_runes"] == {"daily": 2}
            rules = runtime.data.crisis_v2.rules["season_a", "season_a_p"]
            assert rules.evaluate(["daily"], {"rune": {}, "challenge": {}, "exRunes": {"daily": 2}},
                                  permanent=True).rune_slots == ("daily",)
        settings = runtime.settings
    finally:
        runtime.database.close()
    cold = Runtime(settings)
    try:
        with cold.database.transaction() as session:
            new_token = login(session, settings, name="CrisisDoctor")["secret"]
        with TestClient(create_game_app(cold)) as client:
            assert post(client, new_token, winning_key).json() == receipt
            set_time(cold, 2000)
            assert post(client, new_token, "closed").json()["error"]["code"] == "CRISIS_V2_UNLOCK_CLOSED"
        assert map_row(cold)["extra_runes"] == {"daily": 2}
    finally:
        cold.database.close()


def test_bad_attachment_rejected_without_mutation(tmp_path):
    tables = source()
    detail = tables["crisis_v2_server_table"]["seasons"]["season_a"]["info"]["mapDetailDataMap"]["season_a_p"]
    detail["dailyRuneUnlcokDataMap"]["daily"]["mapAttachOn"] = "season_a_p"
    runtime, token, _ = setup(tmp_path, tables=tables)
    try:
        set_time(runtime, 1300)
        before = rows(runtime.database.path)
        with TestClient(create_game_app(runtime)) as client:
            assert post(client, token, "invalid-catalog").status_code == 503
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()