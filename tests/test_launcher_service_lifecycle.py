"""Cancellation before readiness cannot leave a late server using a closed DB."""
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from terralocal.config import Settings
from terralocal.launcher import service
from terralocal.server.services.backups import own_save_directory
from terralocal.server.services.runtime import Runtime


class FakeSocket:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def bind(self, _address):
        pass

    def setsockopt(self, *_args):
        pass


def settings(data_dir):
    return SimpleNamespace(game_host="127.0.0.1", game_port=18443, admin_host="127.0.0.1",
                           admin_port=18080, tls=True, log_level="ERROR", data_dir=data_dir)


def test_stop_during_initialization_waits_for_owner_and_cancels_late_start(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    closed, errors, started = [], [], []

    def runtime(_settings):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(database=SimpleNamespace(close=lambda: closed.append(True)))

    monkeypatch.setattr(service.socket, "socket", FakeSocket)
    monkeypatch.setattr(service, "Runtime", runtime)
    monkeypatch.setattr(service, "create_game_app", lambda *_args: started.append(True))
    group = service.ServerGroup(settings(tmp_path))

    def start():
        try:
            group.start()
        except RuntimeError as error:
            errors.append(str(error))

    owner = threading.Thread(target=start)
    owner.start()
    assert entered.wait(3)
    with pytest.raises(ValueError, match="数据目录正由"):
        with own_save_directory(tmp_path):
            pytest.fail("Startup must still own the save directory")
    stopping = threading.Thread(target=group.stop)
    stopping.start()
    assert group.stop_event.wait(3)
    assert not closed
    release.set()
    owner.join(3)
    stopping.join(3)
    assert not owner.is_alive() and not stopping.is_alive()
    assert closed == [True] and started == [] and errors == ["服务启动已取消"]
    assert group.client is None and not group.servers
    group.stop()
    assert closed == [True]
    with own_save_directory(tmp_path):
        assert group.stop_event.is_set()


def test_tls_failure_closes_initialized_database_and_preserves_error(monkeypatch, tmp_path):
    closed = []
    runtime = SimpleNamespace(database=SimpleNamespace(close=lambda: closed.append(True)))
    monkeypatch.setattr(service.socket, "socket", FakeSocket)
    monkeypatch.setattr(service, "Runtime", lambda *_args: runtime)
    monkeypatch.setattr(service, "create_game_app", lambda *_args: SimpleNamespace(
        state=SimpleNamespace(request_log=None)))
    monkeypatch.setattr(service, "create_admin_app", lambda *_args: None)

    def fail(*_args):
        raise PermissionError("Synthetic certificate write failure")

    monkeypatch.setattr(service, "ensure_certificate", fail)
    group = service.ServerGroup(settings(tmp_path))
    with pytest.raises(PermissionError):
        group.start()
    assert closed == [True] and not group.servers and group.client is None
    with own_save_directory(tmp_path):
        assert group.stop_event.is_set()
    with pytest.raises(RuntimeError, match="重复启动"):
        group.start()


def test_database_remains_open_until_worker_really_exits(tmp_path):
    closed = []
    group = service.ServerGroup(settings(tmp_path))
    group.runtime = SimpleNamespace(database=SimpleNamespace(close=lambda: closed.append(True)))

    class BusyThread:
        alive = True

        def join(self, timeout):
            assert timeout == 8

        def is_alive(self):
            return self.alive

    thread = BusyThread()
    group.threads.append(thread)
    group._save_owner.enter_context(own_save_directory(tmp_path))
    with pytest.raises(RuntimeError, match="后台任务"):
        group.stop()
    assert not closed
    with pytest.raises(ValueError, match="数据目录正由"):
        with own_save_directory(tmp_path):
            pytest.fail("A pending worker must keep the save directory locked")
    thread.alive = False
    group.stop()
    assert closed == [True]
    with own_save_directory(tmp_path):
        assert not thread.is_alive()


def test_manual_backup_keeps_the_save_open_until_shutdown_can_finish(monkeypatch, tmp_path):
    copying, release = threading.Event(), threading.Event()
    closed = []
    group = service.ServerGroup(settings(tmp_path))
    group.runtime = SimpleNamespace(settings=group.settings, database=SimpleNamespace(close=lambda: closed.append(True)))
    group._save_owner.enter_context(own_save_directory(tmp_path))

    def create(_service):
        copying.set()
        assert release.wait(5)
        assert not closed
        return {"name": "manual-synthetic.sqlite3"}

    monkeypatch.setattr(service.BackupService, "create", create)
    with ThreadPoolExecutor(max_workers=2) as pool:
        backup = pool.submit(group.create_backup)
        try:
            assert copying.wait(3)
            shutdown = pool.submit(group.stop)
            assert group.stop_event.wait(3)
            assert not shutdown.done() and not closed
            with pytest.raises(ValueError, match="数据目录正由"):
                with own_save_directory(tmp_path):
                    pytest.fail("Manual backup must keep the save directory locked")
        finally:
            release.set()
        assert backup.result(timeout=3)["name"] == "manual-synthetic.sqlite3"
        shutdown.result(timeout=3)
    assert closed == [True]
    with own_save_directory(tmp_path), pytest.raises(RuntimeError, match="尚未就绪"):
        group.create_backup()


def test_busy_admin_port_releases_reserved_game_port_without_opening_save(tmp_path):
    domain = settings(tmp_path / "untouched")
    with socket.socket() as game, socket.socket() as admin:
        game.bind((domain.game_host, 0))
        admin.bind((domain.admin_host, 0))
        domain.game_port, domain.admin_port = game.getsockname()[1], admin.getsockname()[1]
        game.close()
        admin.listen(1)
        group = service.ServerGroup(domain)
        with pytest.raises(service.ListenerError, match=f"管理服务端口 {domain.admin_port}"):
            group.start()
    assert group.runtime is None and not domain.data_dir.exists()
    with socket.socket() as game:
        game.bind((domain.game_host, domain.game_port))


def test_listener_thread_start_failure_keeps_original_error_and_cleans_up(monkeypatch, tmp_path):
    closed, calls = [], []
    domain = settings(tmp_path)
    domain.tls = False
    with socket.socket() as game, socket.socket() as admin:
        game.bind((domain.game_host, 0))
        admin.bind((domain.admin_host, 0))
        domain.game_port, domain.admin_port = game.getsockname()[1], admin.getsockname()[1]
    runtime = SimpleNamespace(database=SimpleNamespace(close=lambda: closed.append(True)))
    monkeypatch.setattr(service, "Runtime", lambda *_args: runtime)
    monkeypatch.setattr(service, "create_game_app", lambda *_args: SimpleNamespace(
        state=SimpleNamespace(request_log=None)))
    monkeypatch.setattr(service, "create_admin_app", lambda *_args: None)

    def fail(thread):
        calls.append(thread.name)
        raise RuntimeError("synthetic thread creation failure")

    monkeypatch.setattr(threading.Thread, "start", fail)
    group = service.ServerGroup(domain)
    with pytest.raises(RuntimeError, match="synthetic thread creation failure"):
        group.start()
    assert calls == ["terralocal-listener-0"] and closed == [True] and not group.threads
    with own_save_directory(tmp_path), socket.socket() as game, socket.socket() as admin:
        game.bind((domain.game_host, domain.game_port))
        admin.bind((domain.admin_host, domain.admin_port))


def test_initialization_failure_closes_database(monkeypatch, tmp_path):
    closed = []

    def fail():
        raise ValueError("synthetic save initialization failure")

    database = SimpleNamespace(initialize=fail, close=lambda: closed.append(True))
    monkeypatch.setattr("terralocal.server.services.runtime.Database", lambda _path: database)
    with pytest.raises(ValueError, match="synthetic save initialization failure"):
        Runtime(Settings(data_dir=tmp_path))
    assert closed == [True]
