"""The local history endpoint must not write or export raw telemetry."""

from fastapi.testclient import TestClient
from test_crisis_v2_clears import begin, finish, request, setup
from test_crisis_v2_persistence import rows

from terralocal.server.domain.accounts import create_account, login
from terralocal.server.main import create_game_app

PATH = "/local/v1/crisis-v2/history"


def test_owner_only_terminal_history_paginates_and_preserves_save(tmp_path):
    runtime, token, payload = setup(tmp_path)
    try:
        one = begin(runtime, token, payload)["battleId"]
        with TestClient(create_game_app(runtime)) as client:
            auth = {"secret": token}
            assert client.get(PATH, headers=auth).json() == {"records": [], "nextOffset": None}
            assert client.get(f"{PATH}/{one}", headers=auth).status_code == 409
            finish(runtime, token, request(one, payload))
            two = begin(runtime, token, payload, key="start-two")["battleId"]
            finish(runtime, token, request(two, payload), key="finish-two")
            with runtime.database.transaction() as session:
                create_account(session, runtime.data, "HistoryOther")
                other = login(session, runtime.settings, name="HistoryOther")["secret"]
            before = rows(runtime.database.path)
            assert client.get(PATH).status_code == 401
            assert client.get(f"{PATH}/{one}", headers={"secret": other}).status_code == 404
            assert client.get(PATH, headers={"secret": other}).json()["records"] == []
            first = client.get(PATH, params={"limit": 1}, headers=auth).raise_for_status().json()
            next_page = client.get(PATH, params={"limit": 1, "offset": first["nextOffset"]},
                                   headers=auth).raise_for_status().json()
            assert {first["records"][0]["battleId"], next_page["records"][0]["battleId"]} == {one, two}
            assert next_page["nextOffset"] is None
            body = client.get(f"{PATH}/{one}", headers=auth).raise_for_status().json()
            assert body["outcome"] == "CLEARED" and body["playableReplay"] is False
            assert set(body) == {"version", "battleId", "seasonId", "mapId", "startedAt", "finishedAt",
                                 "outcome", "runeSlots", "score", "comments", "playableReplay"}
            assert "authored-unused-private-marker" not in str(body)
            assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()