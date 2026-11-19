"""Launcher lifecycle, account scope, real SDK expiry and failure recovery."""
import hashlib
import json
import os
import threading
import time

import pytest
from sqlalchemy import select

from terralocal.launcher.android import InstanceLease
from terralocal.launcher.client_binding import BindingStore, atomic_json
from terralocal.launcher.client_connection import ClientConnection
from terralocal.launcher.client_session import ClientConnectionError, prepare_credential
from terralocal.server.domain import accounts
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime


class FakeLease:
    def __init__(self):
        self.held = False

    def acquire(self):
        self.held = True

    def close(self):
        self.held = False


class FakeAndroid:
    def __init__(self, settings, cancel):
        self.settings, self.cancel = settings, cancel
        self.lease = FakeLease()
        self.boot = 1
        self.routes = False
        self.game_running = False
        self.remote = {}
        self.route_repairs, self.launches, self.stops, self.verifications = 0, 0, 0, 0
        self.fail_delivery = False
        self.reject_client = False

    def validate_configuration(self):
        self.verifications += 1
        if self.reject_client:
            raise ClientConnectionError("UNSUPPORTED_CLIENT_APK", "客户端版本未适配")

    def ensure_running(self):
        pass

    def identify(self):
        return self.boot

    def routes_ready(self, identity):
        return self.routes

    def configure_routes(self, identity):
        self.route_repairs += 1
        self.routes = True

    def file_matches(self, name, path):
        return self.remote.get(name) == path.read_bytes()

    def deliver(self, name, path):
        if self.fail_delivery:
            raise ClientConnectionError("CLIENT_FILE_DELIVERY_FAILED", "传送失败")
        self.remote[name] = path.read_bytes()

    def stop_game(self):
        self.stops += 1
        self.game_running = False

    def launch_game(self):
        if not self.game_running:
            self.launches += 1
            self.game_running = True

    def close(self):
        self.lease.close()


def manager(runtime):
    return ClientConnection(runtime, transport_factory=FakeAndroid, poll_seconds=.01)


def sdk_rows(runtime):
    with runtime.database.transaction(write=False) as session:
        return list(session.scalars(select(m.LocalSession).where(m.LocalSession.kind == "sdk")))


def grant(client, code):
    return client.post("/user/oauth2/v2/grant", json={"code": code})


def test_unbound_worker_does_not_start_or_modify_client(runtime):
    connection = manager(runtime)
    connection.tick()
    assert connection.snapshot()["phase"] == "unbound"
    assert [row["name"] for row in connection.snapshot()["accounts"]] == ["Doctor"]
    assert connection.transport.verifications == 0
    assert not connection.store.directory.exists()
    assert not sdk_rows(runtime)


def test_bind_healthy_poll_and_cold_boot_preserve_progress_and_finite_session(runtime, token):
    before = runtime.sync(token)
    connection = manager(runtime)
    connection.request("bind", 1)
    connection.tick()
    first = connection._credential
    assert connection.snapshot()["phase"] == "connected"
    assert 0 < first.expires_at - int(time.time()) <= runtime.settings.session_ttl
    login = connection.store.directory / "terralocal-login.json"
    modified = login.stat().st_mtime_ns
    for _ in range(3):
        connection.tick()
    assert login.stat().st_mtime_ns == modified
    assert len(sdk_rows(runtime)) == 1
    assert connection.transport.route_repairs == connection.transport.launches == 1
    connection.transport.boot += 1
    connection.transport.routes = connection.transport.game_running = False
    connection.transport.remote.clear()
    connection.tick()
    assert connection.transport.route_repairs == connection.transport.launches == 2
    assert connection._credential == first
    assert runtime.sync(token) == before
    assert json.loads(connection.transport.remote["terralocal-login.json"])["code"] == first.code


def test_expired_sdk_is_still_rejected_then_replaced_automatically(runtime, client):
    connection = manager(runtime)
    connection.request("bind", 1)
    connection.tick()
    old = connection._credential
    assert grant(client, old.code).status_code == 200
    with runtime.database.transaction() as session:
        row = session.scalar(select(m.LocalSession).where(
            m.LocalSession.token_hash == hashlib.sha256(old.code.encode()).hexdigest()))
        row.expires_at = int(time.time()) - 1
    assert grant(client, old.code).status_code == 401
    connection.tick()
    new = connection._credential
    assert new.code != old.code
    assert grant(client, new.code).status_code == 200
    assert grant(client, old.code).status_code == 401
    connection.tick()
    assert len(sdk_rows(runtime)) == 2
    assert json.loads(connection.transport.remote["terralocal-login.json"])["code"] == new.code


def test_restart_recovers_current_file_without_extra_credentials(runtime, client):
    first = manager(runtime)
    first.request("bind", 1)
    first.tick()
    credential = first._credential
    first.transport.close()
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        second = manager(reopened)
        second.tick()
        assert second._credential == credential
        assert len(sdk_rows(reopened)) == 1
        assert second.transport.launches == 1
        assert grant(client, credential.code).status_code == 200
    finally:
        reopened.database.close()


def test_rotation_has_overlap_without_restarting_active_game(runtime, client):
    connection = manager(runtime)
    connection.request("bind", 1)
    connection.tick()
    old = connection._credential
    with runtime.database.transaction() as session:
        row = session.scalar(select(m.LocalSession).where(
            m.LocalSession.token_hash == hashlib.sha256(old.code.encode()).hexdigest()))
        row.expires_at = int(time.time()) + 100
    connection.tick()
    assert connection._credential.code != old.code
    assert grant(client, old.code).status_code == grant(client, connection._credential.code).status_code == 200
    assert connection.transport.stops == connection.transport.launches == 1


def test_corrupted_callback_flags_are_repaired_without_extra_sdk_issuance(runtime):
    connection = manager(runtime)
    connection.request("bind", 1)
    connection.tick()
    credential = connection._credential
    login = connection.store.directory / "terralocal-login.json"
    for corrupted in ({"code": credential.code, "isSuc": False, "type": 1},
                      {"code": credential.code, "isSuc": True, "type": True},
                      {"code": credential.code, "isSuc": True, "type": 1, "other": "invalid"}):
        atomic_json(login, corrupted)
        connection.tick()
        assert json.loads(login.read_bytes()) == credential.callback()
        assert len(sdk_rows(runtime)) == 1
        assert connection._credential == credential


def test_delivery_failure_reuses_pending_credential_and_keeps_progress(runtime, token):
    before = runtime.sync(token)
    connection = manager(runtime)
    connection.transport.fail_delivery = True
    connection.request("bind", 1)
    for _ in range(2):
        with pytest.raises(ClientConnectionError, match="传送失败"):
            connection.tick()
    pending = connection._credential
    assert len(sdk_rows(runtime)) == 1
    assert connection.transport.launches == 0
    connection.transport.fail_delivery = False
    connection.tick()
    assert connection._credential == pending
    assert len(sdk_rows(runtime)) == 1
    assert runtime.sync(token) == before


def test_account_switch_restarts_client_and_never_reuses_another_account_code(runtime, client, token):
    before = runtime.sync(token)
    with runtime.database.transaction() as session:
        second = accounts.create_account(session, runtime.data, "Second", password="local-only")
        second_id = second.id
    connection = manager(runtime)
    connection.request("bind", 1)
    connection.tick()
    first = connection._credential
    connection.request("bind", second_id)
    connection.tick()
    other = connection._credential
    assert first.account_id != other.account_id and first.code != other.code
    assert connection.transport.launches == connection.transport.stops == 2
    assert grant(client, other.code).status_code == 200
    with runtime.database.transaction(write=False) as session:
        row = session.scalar(select(m.LocalSession).where(
            m.LocalSession.token_hash == hashlib.sha256(other.code.encode()).hexdigest()))
        assert row.account_id == second_id
    assert runtime.sync(token) == before


def test_binding_uid_mismatch_after_restore_requires_selection_and_does_not_touch_device(runtime):
    connection = manager(runtime)
    binding = BindingStore(runtime.settings).bind(runtime, 1)
    atomic_json(connection.store.directory / "binding.json", {**binding.model_dump(), "account_uid": "different"})
    with pytest.raises(ClientConnectionError) as error:
        connection.tick()
    assert error.value.code == "BOUND_ACCOUNT_MISSING"
    assert connection.transport.verifications == connection.transport.route_repairs == 0
    assert not sdk_rows(runtime)


def test_unsupported_client_and_bad_binding_never_issue_credentials(runtime):
    connection = manager(runtime)
    connection.transport.reject_client = True
    connection.request("bind", 1)
    with pytest.raises(ClientConnectionError) as error:
        connection.tick()
    assert error.value.code == "UNSUPPORTED_CLIENT_APK"
    assert not connection.store.directory.exists()
    assert not sdk_rows(runtime)
    connection._pending_account = None
    connection.transport.reject_client = False
    binding = connection.store.bind(runtime, 1)
    atomic_json(connection.store.directory / "binding.json", {**binding.model_dump(), "instance": 0})
    with pytest.raises(ClientConnectionError) as error:
        connection.tick()
    assert error.value.code == "INVALID_CLIENT_BINDING"
    assert not sdk_rows(runtime)


def test_sdk_scope_credential_repr_and_game_token_replacement(runtime, client, token):
    connection = manager(runtime)
    binding = connection.store.bind(runtime, 1)
    atomic_json(connection.store.directory / "terralocal-login.json", {"code": token, "isSuc": True, "type": 1})
    connection.tick()
    sdk = connection._credential
    assert sdk.code != token
    assert sdk.code not in repr(sdk) and sdk.account_uid not in repr(sdk)
    assert client.post("/account/syncData", headers={"secret": sdk.code}).status_code == 401
    assert grant(client, sdk.code).status_code == 200
    assert connection.store.load() == binding


def test_atomic_callback_failure_preserves_valid_file(tmp_path, monkeypatch):
    path = tmp_path / "terralocal-login.json"
    previous = {"code": "synthetic-old", "isSuc": True, "type": 1}
    atomic_json(path, previous)
    def fail_replace(*_args):
        raise PermissionError("Synthetic private-file replacement failure")
    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        atomic_json(path, {"code": "synthetic-new", "isSuc": True, "type": 1})
    assert json.loads(path.read_bytes()) == previous
    assert not path.with_name(path.name + ".tmp").exists()


def test_cancelled_issue_does_not_commit_any_session(runtime):
    binding = BindingStore(runtime.settings).bind(runtime, 1)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ClientConnectionError) as error:
        prepare_credential(runtime, binding.account_id, binding.account_uid, cancel=cancelled)
    assert error.value.code == "CLIENT_CANCELLED"
    assert not sdk_rows(runtime)


def test_transient_disconnect_file_failure_keeps_cancellation_pending(runtime, monkeypatch):
    connection = manager(runtime)
    connection.request("bind", 1)
    connection.tick()
    prepared = connection._credential
    original_clear = connection.store.clear
    attempts = []

    def busy_once():
        attempts.append(True)
        if len(attempts) == 1:
            raise PermissionError("Synthetic Windows sharing violation")
        original_clear()

    monkeypatch.setattr(connection.store, "clear", busy_once)
    connection.request("disconnect")
    with pytest.raises(PermissionError):
        connection.tick()
    assert connection._disconnect_requested
    connection.tick()
    assert connection.store.load() is None and not connection.transport.lease.held
    assert connection.snapshot()["phase"] == "unbound"
    assert len(sdk_rows(runtime)) == 1 and prepared.expires_at > int(time.time())
    assert connection.transport.launches == 1


def test_cancellation_during_delivery_does_not_launch_or_rotate_repeatedly(runtime, monkeypatch):
    connection = manager(runtime)
    deliver = connection.transport.deliver

    def interrupt(name, path):
        deliver(name, path)
        connection.request("disconnect")

    monkeypatch.setattr(connection.transport, "deliver", interrupt)
    connection.request("bind", 1)
    with pytest.raises(ClientConnectionError) as error:
        connection.tick()
    assert error.value.code == "CLIENT_CANCELLED"
    assert connection.transport.launches == 0 and len(sdk_rows(runtime)) == 1
    connection.tick()
    assert connection.store.load() is None and not connection.transport.lease.held
    assert connection.transport.launches == 0 and len(sdk_rows(runtime)) == 1


def test_worker_disconnect_stop_and_safe_status(runtime):
    connection = manager(runtime)
    connection.start()
    try:
        connection.request("bind", 1)
        deadline = time.monotonic() + 3
        while connection.snapshot()["phase"] != "connected" and time.monotonic() < deadline:
            time.sleep(.01)
        assert connection.snapshot()["phase"] == "connected"
        secret = connection._credential.code
        assert secret not in json.dumps(connection.snapshot())
        connection.request("disconnect")
        deadline = time.monotonic() + 3
        while connection.snapshot()["phase"] != "unbound" and time.monotonic() < deadline:
            time.sleep(.01)
        assert connection.snapshot()["phase"] == "unbound"
    finally:
        connection.stop()
    assert connection.store.load() is None
    assert connection.snapshot()["phase"] == "stopped"
    assert not connection.thread.is_alive() and not connection.transport.lease.held


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex")
def test_worker_start_failure_remains_stoppable(runtime, monkeypatch):
    connection = ClientConnection(runtime, transport_factory=FakeAndroid)

    def fail(_thread):
        raise RuntimeError("synthetic client worker startup failure")

    monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(RuntimeError, match="synthetic client worker startup failure"):
        connection.start()
    connection.stop()
    assert connection.thread is None and connection.stopping.is_set()


def test_only_one_launcher_can_claim_the_dedicated_instance():
    first, second = InstanceLease(), InstanceLease()
    try:
        first.acquire()
        with pytest.raises(ClientConnectionError) as error:
            second.acquire()
        assert error.value.code == "CLIENT_ALREADY_CONNECTED"
        first.close()
        second.acquire()
    finally:
        first.close()
        second.close()
