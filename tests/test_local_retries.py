from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from terralocal.server.api.schemas import Formation
from terralocal.server.domain import accounts, operators
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime

FORMATION_PATH = "/local/v1/squads/formation"


def login(client, name="Doctor"):
    response = client.post("/local/v1/login", json={"name": name})
    response.raise_for_status()
    return response.json()["secret"]


def save(client, token, key, name):
    body = {"squadId": "0", "slots": [], "name": name}
    return client.post(FORMATION_PATH, json=body, headers={"secret": token, "Idempotency-Key": key})


def receipt_count(runtime):
    with runtime.database.transaction(write=False) as session:
        return session.scalar(select(func.count()).select_from(m.Receipt))


def test_old_request_cannot_replace_newer_save_after_relogin_and_restart(client, runtime, token):
    first = save(client, token, "first-save", "First")
    assert first.status_code == 200
    new_token = login(client)
    later = save(client, new_token, "later-save", "Later")
    assert later.status_code == 200
    assert later.json()["revision"] == first.json()["revision"] + 1

    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(restarted)) as recovered:
            renewed = login(recovered)
            retry = save(recovered, renewed, "first-save", "First")
            assert retry.status_code == 200
            assert retry.json() == first.json()
            conflict = save(recovered, renewed, "first-save", "Different")
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
            sync = recovered.post("/local/v1/sync", headers={"secret": renewed}).json()
            assert sync["revision"] == later.json()["revision"]
            assert sync["user"]["troop"]["squads"]["0"]["name"] == "Later"
        assert receipt_count(restarted) == 2
    finally:
        restarted.database.close()


def test_concurrent_retries_from_two_sessions_commit_once(client, runtime, token):
    second = login(client)
    parallel = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(parallel)) as other_client, ThreadPoolExecutor(max_workers=4) as pool:
            requests = [(client, token), (other_client, second)] * 2
            responses = list(pool.map(lambda request: save(*request, "parallel-save", "Saved"), requests))
        assert all(response.status_code == 200 for response in responses)
        original = responses[0].json()
        assert original["revision"] == 1
        assert all(response.json() == original for response in responses)
        assert receipt_count(runtime) == 1
    finally:
        parallel.database.close()


def test_a_confirmed_legacy_receipt_can_be_replayed_in_a_new_session(client, runtime, token):
    payload = Formation(squadId="0", slots=[], name="Legacy").model_dump()
    original = runtime.mutate(token, None, "legacy-save", "formation", payload,
                              lambda ctx: operators.formation(ctx, "0", [], "Legacy"))
    conflict = save(client, token, "legacy-save", "Different")
    assert conflict.status_code == 409
    assert receipt_count(runtime) == 1

    recovered = save(client, token, "legacy-save", "Legacy")
    assert recovered.status_code == 200
    assert recovered.json() == original
    retry = save(client, login(client), "legacy-save", "Legacy")
    assert retry.status_code == 200
    assert retry.json() == original
    assert receipt_count(runtime) == 2


def test_replay_is_limited_to_the_authenticated_account(client, runtime, token):
    original = save(client, token, "shared-key", "First account")
    assert original.status_code == 200
    with runtime.database.transaction() as session:
        session.scalar(select(m.LocalSession)).expires_at = 0
        accounts.create_account(session, runtime.data, "Other Fixture")

    expired = save(client, token, "shared-key", "First account")
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "INVALID_SESSION"
    other = save(client, login(client, "Other Fixture"), "shared-key", "Second account")
    assert other.status_code == 200
    assert other.json()["revision"] == 1
    assert other.json() != original.json()
    assert receipt_count(runtime) == 2
