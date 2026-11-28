"""Native record invalidation, first zero clears and immutable v1 recovery."""

import copy

import pytest
from crisis_v2_qa import set_time
from fastapi.testclient import TestClient
from test_crisis_v2_battle_sessions import pending
from test_crisis_v2_clears import request, setup
from test_crisis_v2_native_battles import cache, finish, native, source, start
from test_crisis_v2_persistence import rows

from terralocal.server.domain import crisis_v2_clears
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime

LEGACY = "cn-2.7.71-crisis-v2-local-clear-receipt-v1"


@pytest.fixture
def ready(tmp_path):
    tables = source()
    for entry in tables["crisis_v2_server_table"]["seasons"].values():
        for detail in entry["info"]["mapDetailDataMap"].values():
            for bag in detail["bagDataMap"].values():
                bag["rewardScore"] = 0
    runtime, token, payload = setup(tmp_path, tables=tables)
    payload["rune_slots"] = []
    yield runtime, token, payload
    runtime.database.close()


def select_kind(runtime, payload, kind):
    if kind == "temporary":
        payload["map_id"] = "season_a_t"
        set_time(runtime, 1300)


def record_ts(runtime):
    with runtime.database.transaction(write=False) as session:
        return session.get(m.CrisisV2Account, 1).new_record_ts


def clear(client, token, payload, key):
    begun = start(client, token, payload, key + "-start")
    assert begun.status_code == 200, begun.text
    ident = begun.json()["battleId"]
    body = request(ident, payload)
    result = finish(client, token, body, key + "-finish")
    assert result.status_code == 200, result.text
    return ident, body, result.json()


@pytest.mark.parametrize("kind", ["permanent", "temporary"])
def test_first_zero_clear_creates_a_record_and_updates_native_delta(ready, kind):
    runtime, token, payload = ready
    select_kind(runtime, payload, kind)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        ident, body, response = clear(client, token, payload, "first-zero")
        assert response["scoreCurrent"] == [0] * 6
        assert record_ts(runtime) == response["ts"] > 0
        assert response["isNewRecord"] is True
        saved = pending(runtime, token, ident).battle.settlement
        assert saved["result"]["newSingleRecord"] == (kind == "permanent")
        assert not saved["map_before"]["state"] and saved["map_after"]["state"]
        assert apply(before, response["playerDataDelta"]) == runtime.sync(token)["user"]
        original = cache(runtime, ident)
        set_time(runtime, 1400)
        repeated = finish(client, token, body, "first-zero-again")
        assert repeated.status_code == 200, repeated.text
        assert native(repeated.json()) == native(response)
        assert cache(runtime, ident) == original and record_ts(runtime) == response["ts"]


def test_another_zero_clear_keeps_the_first_record_and_token(ready):
    runtime, token, payload = ready
    with TestClient(create_game_app(runtime)) as client:
        one, _, first = clear(client, token, payload, "one")
        initial = record_ts(runtime)
        set_time(runtime, 1101)
        two, _, second = clear(client, token, payload, "two")
        assert first["isNewRecord"] and not second["isNewRecord"]
        assert record_ts(runtime) == initial == 1001
        assert pending(runtime, token, one).battle.settlement["result"]["newSingleRecord"]
        assert not pending(runtime, token, two).battle.settlement["result"]["newSingleRecord"]


@pytest.mark.parametrize("next_time", [1600, 1500], ids=["same-second", "clock-rewind"])
def test_new_record_invalidates_cache_even_at_the_same_or_earlier_clock(ready, next_time):
    runtime, token, payload = ready
    set_time(runtime, 1600)
    with TestClient(create_game_app(runtime)) as client:
        clear(client, token, payload, "zero")
        previous = record_ts(runtime)
        set_time(runtime, next_time)
        payload["rune_slots"] = ["rune"]
        _, _, response = clear(client, token, payload, "improved")
        assert response["scoreCurrent"][0] == 10 and response["isNewRecord"]
        assert record_ts(runtime) > previous
        assert response["ts"] == next_time


@pytest.mark.parametrize("kind", ["permanent", "temporary"])
def test_legacy_zero_receipt_native_reply_and_journal_survive_cold_restart(ready, monkeypatch, kind):
    runtime, token, payload = ready
    select_kind(runtime, payload, kind)
    runtime.settings.crisis_archive_replays = True
    project = crisis_v2_clears.project

    def legacy_project(*args, **kwargs):
        return project(*args, **(kwargs | {"policy_version": LEGACY}))

    with monkeypatch.context() as patch, TestClient(create_game_app(runtime)) as client:
        patch.setattr(crisis_v2_clears, "VERSION", LEGACY)
        patch.setattr(crisis_v2_clears, "project", legacy_project)
        ident, body, first = clear(client, token, payload, "legacy")
        assert not first["isNewRecord"] and record_ts(runtime) == 0
        canonical = copy.deepcopy(pending(runtime, token, ident).battle.settlement)
        original_native = cache(runtime, ident)
        assert canonical["version"] == LEGACY
    runtime.database.close()
    recovered = Runtime(runtime.settings)
    try:
        assert pending(recovered, token, ident).battle.settlement == canonical
        with TestClient(create_game_app(recovered)) as client:
            replayed = finish(client, token, body, "legacy-new-sequence")
            assert replayed.status_code == 200, replayed.text
            assert native(replayed.json()) == native(first)
            assert cache(recovered, ident) == original_native
            assert record_ts(recovered) == 0
            journal = client.get(f"/local/v1/crisis-v2/history/{ident}/journal", headers={"secret": token})
            assert journal.status_code == 200, journal.text
            assert pending(recovered, token, ident).battle.settlement == canonical
    finally:
        recovered.database.close()


@pytest.mark.parametrize("version", ["future-clear-policy", [], None])
def test_unknown_clear_versions_fail_without_reinterpreting_or_writing(ready, version):
    runtime, token, payload = ready
    with TestClient(create_game_app(runtime)) as client:
        ident, body, _ = clear(client, token, payload, "known")
        with runtime.database.transaction() as session:
            row = session.get(m.BattleSession, ident)
            row.settlement = row.settlement | {"version": version}
        before = rows(runtime.database.path)
        result = finish(client, token, body, "unknown-version")
        assert result.status_code == 503, result.text
        assert rows(runtime.database.path) == before


def test_exhausted_record_token_refuses_clear_without_partial_writes(ready):
    runtime, token, payload = ready
    with TestClient(create_game_app(runtime)) as client:
        started = start(client, token, payload)
        assert started.status_code == 200, started.text
        ident = started.json()["battleId"]
        with runtime.database.transaction() as session:
            session.get(m.CrisisV2Account, 1).new_record_ts = 2**63 - 1
        before = rows(runtime.database.path)
        result = finish(client, token, request(ident, payload))
        assert result.status_code == 503, result.text
        assert rows(runtime.database.path) == before
        assert pending(runtime, token, ident).battle.state == "STARTED"
