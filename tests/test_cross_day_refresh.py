"""Cross-day client acknowledgement, transaction rollback and durable deltas."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from terralocal.server.domain import accounts
from terralocal.server.domain.clock import ServerClock
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime

FULL_REFRESH = 3807  # Observed frozen-client request; do not derive the test from the implementation.


def refresh(client, token, modules=FULL_REFRESH):
    return client.post("/account/syncStatus", headers={"secret": token},
                       json={"modules": modules, "params": {}})


def test_full_refresh_delivers_and_persists_the_cross_day_checkpoint(runtime, client, token):
    original = runtime.sync(token)["user"]
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 86400
    # Full snapshot reads must not pretend that the account refresh has completed.
    before = runtime.sync(token)["user"]
    assert before["status"]["lastRefreshTs"] == original["status"]["lastRefreshTs"]
    partial = refresh(client, token, modules=2143)
    assert partial.status_code == 200
    assert "lastRefreshTs" not in partial.json()["playerDataDelta"]["modified"].get("status", {})
    response = refresh(client, token)
    assert response.status_code == 200
    data = response.json()
    assert data["playerDataDelta"]["modified"]["status"]["lastRefreshTs"] == data["ts"]
    after = runtime.sync(token)["user"]
    assert apply(before, data["playerDataDelta"]) == after
    assert after["status"]["registerTs"] == original["status"]["registerTs"]
    with runtime.database.transaction(write=False) as session:
        profile = session.get(m.PlayerProfile, 1)
        assert profile.flags["lastRefreshTs"] == data["ts"]
        assert profile.revision == 1


@pytest.mark.parametrize("previous,current,changed", [
    ("2026-10-08 23:59:59", "2026-10-09 00:00:00", False),
    ("2026-10-09 03:59:59", "2026-10-09 04:00:00", True),
    ("2026-10-09 04:00:00", "2026-10-09 15:00:00", False),
])
def test_refresh_uses_the_client_four_am_boundary(runtime, client, token, previous, current, changed):
    def stamp(value):
        return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone(timedelta(hours=8))).timestamp())

    previous, current = stamp(previous), stamp(current)
    with runtime.database.transaction() as session:
        session.get(m.PlayerProfile, 1).flags = {"lastRefreshTs": previous}
        session.get(m.ServerClockState, 1).fixed_at = current
    before = runtime.sync(token)["user"]
    response = refresh(client, token).json()
    assert ("lastRefreshTs" in response["playerDataDelta"]["modified"].get("status", {})) == changed
    after = runtime.sync(token)["user"]
    assert after["status"]["lastRefreshTs"] == (current if changed else previous)
    assert apply(before, response["playerDataDelta"]) == after


def test_concurrent_and_duplicate_refreshes_change_only_the_target_account_once(runtime, client, token):
    with runtime.database.transaction() as session:
        other = accounts.create_account(session, runtime.data, "Other")
        profile = session.get(m.PlayerProfile, 1)
        profile.flags = {**profile.flags, "story": {"preserved": 1}, "voiceLan": "JP"}
        old_flags = dict(profile.flags)
        other_flags = dict(session.get(m.PlayerProfile, other.id).flags)
        session.get(m.ServerClockState, 1).fixed_at += 86400
        gold = session.get(m.Currency, (1, "4001")).balance
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: refresh(client, token), range(8)))
    assert all(response.status_code == 200 for response in responses)
    assert sum("lastRefreshTs" in r.json()["playerDataDelta"]["modified"].get("status", {})
               for r in responses) == 1
    with runtime.database.transaction(write=False) as session:
        profile = session.get(m.PlayerProfile, 1)
        assert profile.flags == {**old_flags, "lastRefreshTs": 1_800_086_400}
        assert profile.revision == 1
        assert session.get(m.PlayerProfile, other.id).flags == other_flags
        assert session.get(m.Currency, (1, "4001")).balance == gold


def test_cross_day_checkpoint_survives_a_server_restart(runtime, client, token):
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 86400
    assert refresh(client, token).status_code == 200
    expected = runtime.sync(token)
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == expected
        with TestClient(create_game_app(restarted)) as fresh_client:
            again = refresh(fresh_client, token)
            assert again.status_code == 200
            assert "lastRefreshTs" not in again.json()["playerDataDelta"]["modified"].get("status", {})
        assert restarted.sync(token) == expected
    finally:
        restarted.database.close()


def test_response_assembly_failure_rolls_back_recovery_and_refresh(runtime, client, token, monkeypatch):
    with runtime.database.transaction() as session:
        state = session.get(m.SanityState, 1)
        state.current = 2
        old_recovery = state.last_recovery_at
        old_flags = dict(session.get(m.PlayerProfile, 1).flags)
        session.get(m.ServerClockState, 1).fixed_at += 86400
    original = SyncDataAssembler.assemble
    count = 0

    def fail_after_refresh(self):
        nonlocal count
        count += 1
        if count == 2:
            assert self.ctx.profile.flags["lastRefreshTs"] == self.ctx.now
            raise RuntimeError("Synthetic assembly failure")
        return original(self)

    with monkeypatch.context() as patch:
        patch.setattr(SyncDataAssembler, "assemble", fail_after_refresh)
        with pytest.raises(RuntimeError, match="Synthetic assembly failure"):
            refresh(client, token)
    with runtime.database.transaction(write=False) as session:
        state = session.get(m.SanityState, 1)
        assert (state.current, state.last_recovery_at) == (2, old_recovery)
        profile = session.get(m.PlayerProfile, 1)
        assert profile.flags == old_flags and profile.revision == 0


@pytest.mark.parametrize("system", ["building", "event", "medal"])
def test_unimplemented_cross_day_work_cannot_be_acknowledged(runtime, client, token, system):
    with runtime.database.transaction() as session:
        profile = session.get(m.PlayerProfile, 1)
        if system == "building":
            session.add(m.Building(account_id=1, control_level=1, last_settled_at=1))
        elif system == "event":
            session.add(m.EventProgress(account_id=1, event_id="synthetic", key="progress", value={"count": 1}))
        else:
            profile.flags = {**profile.flags, "medals": ["synthetic"]}
        old_flags = dict(profile.flags)
        session.get(m.ServerClockState, 1).fixed_at += 86400
        session.get(m.SanityState, 1).current = 2
    assert refresh(client, token).status_code == 501
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.PlayerProfile, 1).flags == old_flags
        assert session.get(m.PlayerProfile, 1).revision == 0
        assert session.get(m.SanityState, 1).current == 2


def test_clock_rewind_does_not_reissue_claims_or_currency(runtime, client, token):
    with runtime.database.transaction() as session:
        session.add(m.MissionProgress(account_id=1, mission_id="synthetic", period="permanent",
                                      progress=1, claimed=True))
        gold = session.get(m.Currency, (1, "4001")).balance
        session.get(m.ServerClockState, 1).fixed_at += 86400
    assert refresh(client, token).status_code == 200
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at -= 86400
    before = runtime.sync(token)["user"]
    response = refresh(client, token).json()
    assert response["playerDataDelta"]["modified"]["status"]["lastRefreshTs"] == 1_800_000_000
    assert apply(before, response["playerDataDelta"]) == runtime.sync(token)["user"]
    assert "lastRefreshTs" not in refresh(client, token).json()["playerDataDelta"]["modified"].get("status", {})
    with runtime.database.transaction(write=False) as session:
        mission = session.get(m.MissionProgress, (1, "synthetic", "permanent"))
        assert mission.claimed and mission.progress == 1
        assert session.get(m.Currency, (1, "4001")).balance == gold


@pytest.mark.parametrize("bad", [True, -1, 253_402_272_000, 253_402_300_799, "yesterday", None])
def test_invalid_saved_refresh_time_fails_explicitly(runtime, client, token, bad):
    with runtime.database.transaction() as session:
        profile = session.get(m.PlayerProfile, 1)
        profile.flags = {**profile.flags, "lastRefreshTs": bad}
    response = refresh(client, token)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INVALID_REFRESH_STATE"
    with runtime.database.transaction(write=False) as session:
        profile = session.get(m.PlayerProfile, 1)
        assert profile.flags["lastRefreshTs"] == bad and profile.revision == 0


def test_snapshot_keeps_one_business_period_when_wall_clock_crosses_the_boundary(runtime, token, monkeypatch):
    before_boundary = int(datetime(2026, 10, 9, 3, 59, 59,
                                   tzinfo=timezone(timedelta(hours=8))).timestamp())
    with runtime.database.transaction() as session:
        for period, progress in [("2026-10-08", 1), ("2026-10-09", 9)]:
            session.add(m.MissionProgress(account_id=1, mission_id="synthetic", period=period,
                                          progress=progress, claimed=False))
    observed = before_boundary

    def moving_clock(_clock):
        nonlocal observed
        value = observed
        observed += 2
        return value

    monkeypatch.setattr(ServerClock, "now", moving_clock)
    snapshot = runtime.sync(token)
    assert snapshot["ts"] == before_boundary
    assert snapshot["user"]["mission"]["missions"]["DAILY"]["synthetic"]["progress"][0]["value"] == 1


@pytest.mark.parametrize("fresh_snapshot", [False, True])
def test_rollover_delta_replaces_old_missions_and_keeps_claim_history(runtime, client, token, fresh_snapshot):
    with runtime.database.transaction() as session:
        clock = ServerClock(session.get(m.ServerClockState, 1))
        old_period = clock.period("daily")
        next_period = clock.period("daily", at=clock.now() + 86400)
        for mission_id, period, progress, claimed in [
            ("old-only", old_period, 3, True), ("both", old_period, 5, True),
            ("new-only", next_period, 1, False), ("both", next_period, 0, False),
        ]:
            session.add(m.MissionProgress(account_id=1, mission_id=mission_id, period=period,
                                          progress=progress, claimed=claimed))
    before = runtime.sync(token)["user"]
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 86400
    if fresh_snapshot:
        before = runtime.sync(token)["user"]
    delta = refresh(client, token).json()["playerDataDelta"]
    after = runtime.sync(token)["user"]
    # Both the connected client holding yesterday's state and a fresh login
    # must reach the full current snapshot by applying the same rollover delta.
    assert apply(before, delta) == after
    assert "old-only" not in after["mission"]["missions"]["DAILY"]
    assert after["mission"]["missions"]["DAILY"]["both"] == {
        "progress": [{"target": 10, "value": 0, "compare": ">="}], "state": 2}
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.MissionProgress, (1, "both", old_period)).claimed
        assert session.get(m.MissionProgress, (1, "old-only", old_period)).claimed
