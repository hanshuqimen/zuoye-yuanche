"""The shared clock rejects invalid settings before committing, even on Windows."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from terralocal.admin.app import create_admin_app
from terralocal.server.domain.clock import MAX_TIMESTAMP, ServerClock
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime

REAL_NOW = 1_800_000_000


def new_clock():
    state = m.ServerClockState(id=1, mode="fixed", fixed_at=REAL_NOW, offset=0)
    return ServerClock(state, real_now=lambda: REAL_NOW)


@pytest.mark.parametrize("value,daily,weekly,monthly", [
    (0, "1970-01-01", "1969-12-29", "1970-01"),
    (MAX_TIMESTAMP, "9999-12-31", "9999-12-27", "9999-12"),
])
def test_supported_limits_project_all_periods(value, daily, weekly, monthly):
    clock = new_clock()
    for mode, amount in (("fixed", value), ("offset", value - REAL_NOW)):
        clock.configure(mode, amount)
        assert clock.now() == value
        assert clock.period("daily") == daily
        assert clock.period("weekly") == weekly
        assert clock.period("monthly") == monthly


@pytest.mark.parametrize("mode,value", [
    ("fixed", -1), ("fixed", MAX_TIMESTAMP + 1), ("fixed", 1_000_000_000_000),
    ("offset", -REAL_NOW - 1), ("offset", MAX_TIMESTAMP - REAL_NOW + 1),
    ("unknown", 0), ("fixed", True), ("fixed", 3.5),
])
def test_invalid_config_preserves_previous_settings(mode, value):
    clock = new_clock()
    before = (clock.state.mode, clock.state.fixed_at, clock.state.offset)
    with pytest.raises(DomainError) as caught:
        clock.configure(mode, value)
    assert caught.value.code == "INVALID_CLOCK"
    assert caught.value.status == 400
    assert (clock.state.mode, clock.state.fixed_at, clock.state.offset) == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, MAX_TIMESTAMP + 1, 2**10000, True, "0"])
def test_invalid_wall_clock_has_explicit_error(value):
    clock = new_clock()
    clock._real_now = lambda: value
    with pytest.raises(DomainError) as caught:
        clock.configure("realtime")
    assert caught.value.code == "INVALID_CLOCK_STATE"
    assert caught.value.status == 503
    assert clock.now() == REAL_NOW


@pytest.mark.parametrize("month_boundary", [False, True])
def test_cn_four_am_week_and_month_boundaries(month_boundary):
    boundary = datetime(2026, 10, 1 if month_boundary else 12, 4, tzinfo=timezone(timedelta(hours=8)))
    clock = new_clock()
    at = int(boundary.timestamp())
    assert clock.period("daily", at=at - 1) == ("2026-09-30" if month_boundary else "2026-10-11")
    assert clock.period("daily", at=at) == ("2026-10-01" if month_boundary else "2026-10-12")
    if month_boundary:
        assert clock.period("monthly", at=at - 1) == "2026-09"
        assert clock.period("monthly", at=at) == "2026-10"
    else:
        assert clock.period("weekly", at=at - 1) == "2026-10-05"
        assert clock.period("weekly", at=at) == "2026-10-12"


def test_calendar_projection_failure_does_not_change_settings(monkeypatch):
    clock = new_clock()

    def fail(*args, **kwargs):
        raise DomainError("SYNTHETIC_CALENDAR_ERROR", "Synthetic calendar failure")

    monkeypatch.setattr(clock, "period", fail)
    with pytest.raises(DomainError, match="Synthetic calendar failure"):
        clock.configure("fixed", REAL_NOW + 60)
    assert clock.state.fixed_at == REAL_NOW


def test_http_rejects_bad_clock_keeps_audit_and_sync_and_restart(runtime, token, client, monkeypatch):
    before = runtime.sync(token)
    # Business-clock simulation must not move the separate authentication TTL.
    monkeypatch.setattr(ServerClock, "_wall_time", lambda _clock: REAL_NOW)
    with TestClient(create_admin_app(runtime), base_url="http://127.0.0.1:8080") as admin:
        csrf = admin.get("/api/session").json()["csrf"]
        for body in ({"mode": "fixed", "value": 10**12}, {"mode": "fixed", "value": -1},
                     {"mode": "offset", "value": -REAL_NOW - 1},
                     {"mode": "offset", "value": MAX_TIMESTAMP - REAL_NOW + 1},
                     {"mode": "invalid", "value": 0}):
            response = admin.post("/api/clock", json=body, headers={"x-csrf-token": csrf})
            assert response.status_code in {400, 422}
            assert client.post("/account/syncData", headers={"secret": token}).status_code == 200
            assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert not session.scalars(select(m.AuditLog)).all()
            assert session.get(m.ServerClockState, 1).fixed_at == REAL_NOW
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == before
    finally:
        reopened.database.close()


def test_old_invalid_clock_returns_clear_error_and_remains_repairable(runtime, token, client):
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = 10**12
    response = client.post("/account/syncData", headers={"secret": token})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INVALID_CLOCK_STATE"
    with TestClient(create_admin_app(runtime), base_url="http://127.0.0.1:8080") as admin:
        csrf = admin.get("/api/session").json()["csrf"]
        dashboard = admin.get("/api/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["clock"]["now"] is None
        assert dashboard.json()["clock"]["error"]
        response = admin.post("/api/clock", json={"mode": "fixed", "value": REAL_NOW},
                              headers={"x-csrf-token": csrf})
        assert response.status_code == 200
        assert client.post("/account/syncData", headers={"secret": token}).status_code == 200


def test_saved_mode_and_offset_corruption_fails_explicitly():
    clock = new_clock()
    clock.state.mode = "unsupported"
    with pytest.raises(DomainError) as caught:
        clock.now()
    assert caught.value.code == "INVALID_CLOCK_STATE"
    clock.state.mode, clock.state.offset = "offset", None
    with pytest.raises(DomainError) as caught:
        clock.now()
    assert caught.value.code == "INVALID_CLOCK_STATE"
