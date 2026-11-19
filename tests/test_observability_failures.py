"""Diagnostic disk failures must preserve committed gameplay and real errors."""
import errno
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_standard_headhunting import (  # noqa: F401 -- shared fixture dependency chain
    DOUBLE,
    head_runtime,
    modern_runtime,
    recruit_runtime,
)

from terralocal.admin.app import create_admin_app
from terralocal.server.domain import accounts, standard_headhunting
from terralocal.server.main import create_game_app
from terralocal.server.observability import RequestLog
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


def fail_log_files(monkeypatch, directory):
    original = Path.open

    def failing_open(path, *args, **kwargs):
        if path.parent == directory and path.name in {"requests.jsonl", "unknown-routes.jsonl"}:
            raise PermissionError("Synthetic diagnostic outage")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)


@pytest.mark.parametrize("phase", ["open", "write", "close"])
def test_disk_failure_keeps_bounded_observations_and_reports_recovery(tmp_path, monkeypatch, phase):
    log = RequestLog(tmp_path / "logs")
    original = Path.open

    @contextmanager
    def failing_file(path, *args, **kwargs):
        if phase == "open":
            raise PermissionError("Synthetic inaccessible file")

        class File:
            def write(self, text):
                if phase == "write":
                    raise OSError(errno.ENOSPC, "Synthetic full disk")

        yield File()
        if phase == "close":
            raise OSError(errno.ENOSPC, "Synthetic buffered flush failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", failing_file)
        for sequence in range(210):
            log.append({"route": "/health", "sequence": sequence})
        log.append({"route": "/unsupported", "sequence": 210}, unknown=True)
    assert len(log.snapshot()) == 200
    assert log.snapshot()[0]["sequence"] == 210
    status = log.status()
    assert status["fileLoggingAvailable"] is False
    assert status["failedFiles"] == ["requests.jsonl", "unknown-routes.jsonl"]
    assert status["failureCount"] == 211
    assert status["lastFailureAt"] is not None
    assert "Synthetic" not in str(status)
    assert Path.open == original
    log.append({"route": "/health"})
    assert log.status()["failedFiles"] == ["unknown-routes.jsonl"]
    log.append({"route": "/unsupported"}, unknown=True)
    assert log.status()["fileLoggingAvailable"] is True
    assert log.status()["failureCount"] == 211


@pytest.mark.parametrize("count", [1, 10])
def test_gacha_outage_concurrent_retries_delta_and_restart(request, monkeypatch, count):
    runtime = request.getfixturevalue("modern_runtime")
    with runtime.database.transaction() as session:
        token = accounts.login(session, runtime.settings, name="Doctor")["secret"]
    before = runtime.sync(token)["user"]
    endpoint = "/gacha/advancedGacha" if count == 1 else "/gacha/tenAdvancedGacha"
    body = {"poolId": DOUBLE, "useTkt": 0}
    headers = {"secret": token, "seqnum": "outage-gacha"}
    app = create_game_app(runtime)
    with monkeypatch.context() as scoped:
        fail_log_files(scoped, runtime.settings.data_dir / "logs")
        with TestClient(app) as client:
            with ThreadPoolExecutor(max_workers=4) as workers:
                responses = list(workers.map(lambda _: client.post(endpoint, json=body, headers=headers), range(8)))
            assert all(response.status_code == 200 for response in responses)
            result = responses[0].json()
            assert all(response.json() == result for response in responses)
            after = runtime.sync(token)["user"]
            assert apply(before, result["playerDataDelta"]) == after
            assert before["status"]["diamondShard"] - after["status"]["diamondShard"] == 600 * count
            assert after["gacha"]["double"][DOUBLE]["showCnt"] == count
            assert client.get("/health").json()["logging"]["fileLoggingAvailable"] is False
            assert client.post(endpoint, json=body, headers={"secret": "invalid", "seqnum": "x"}).status_code == 401
            conflict = client.post(endpoint, json={**body, "useTkt": 1}, headers=headers)
            assert conflict.status_code == 409
            unknown = client.post("/unknown", json={"token": "SECRET-VALUE"})
            assert unknown.status_code == 501
        assert "SECRET-VALUE" not in str(app.state.request_log.snapshot())
        assert token not in str(app.state.request_log.snapshot())
        with runtime.database.transaction(write=False) as session:
            assert len(session.scalars(select(m.GachaHistory)).all()) == count
            assert len(session.scalars(select(m.Receipt)).all()) == 1
        runtime.database.close()
        reopened = Runtime(runtime.settings)
        try:
            assert reopened.sync(token)["user"] == after
            with TestClient(create_game_app(reopened)) as client:
                retry = client.post(endpoint, json=body, headers=headers)
                assert retry.status_code == 200
                assert retry.json() == result
            assert reopened.sync(token)["user"] == after
        finally:
            reopened.database.close()


def test_diagnostic_failure_does_not_hide_domain_exception(request, monkeypatch):
    runtime = request.getfixturevalue("modern_runtime")
    with runtime.database.transaction() as session:
        token = accounts.login(session, runtime.settings, name="Doctor")["secret"]
    before = runtime.sync(token)

    def broken_draw(ctx, *args, **kwargs):
        ctx.change_item("4003", -600)
        raise RuntimeError("Synthetic domain failure after debit")

    app = create_game_app(runtime)
    fail_log_files(monkeypatch, runtime.settings.data_dir / "logs")
    monkeypatch.setattr(standard_headhunting, "draw", broken_draw)
    with TestClient(app) as client, pytest.raises(RuntimeError, match="Synthetic domain failure after debit"):
        client.post("/gacha/advancedGacha", json={"poolId": DOUBLE, "useTkt": 0},
                    headers={"secret": token, "seqnum": "broken-domain"})
    assert runtime.sync(token) == before
    assert app.state.request_log.snapshot()[0]["status"] == 500
    with runtime.database.transaction(write=False) as session:
        assert not session.scalars(select(m.Receipt)).all()
        assert not session.scalars(select(m.GachaHistory)).all()


def test_degraded_status_visible_in_admin_and_audit_still_required(runtime, monkeypatch):
    app = create_game_app(runtime)
    fail_log_files(monkeypatch, runtime.settings.data_dir / "logs")
    with TestClient(app) as game:
        assert game.get("/health").status_code == 200
    with TestClient(create_admin_app(runtime, app.state.request_log), base_url="http://127.0.0.1:8080",
                    raise_server_exceptions=False) as admin:
        csrf = admin.get("/api/session").json()["csrf"]
        assert admin.get("/api/dashboard").json()["logging"]["fileLoggingAvailable"] is False
        assert admin.get("/api/logs").json()["logging"]["fileLoggingAvailable"] is False
        with runtime.database.transaction(write=False) as session:
            before = session.get(m.Currency, (1, "4001")).balance

        def reject_audit(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().lower().startswith("insert into audit_log"):
                raise RuntimeError("Synthetic mandatory audit failure")

        event.listen(runtime.database.engine, "before_cursor_execute", reject_audit)
        try:
            response = admin.post("/api/gm", json={"accountId": 1, "action": "grant-item",
                                  "id": "4001", "value": 123}, headers={"x-csrf-token": csrf})
            assert response.status_code == 500
        finally:
            event.remove(runtime.database.engine, "before_cursor_execute", reject_audit)
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.Currency, (1, "4001")).balance == before
            assert not session.scalars(select(m.AuditLog)).all()
