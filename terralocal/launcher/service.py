from __future__ import annotations

import os
import socket
import threading
import time
from contextlib import ExitStack

import uvicorn

from terralocal.admin.app import create_admin_app
from terralocal.server.main import create_game_app
from terralocal.server.services.backups import BackupService, own_save_directory
from terralocal.server.services.runtime import Runtime
from terralocal.server.services.tls import ensure_certificate

LISTENER_NAMES = ("游戏服务", "管理服务")


class ListenerError(ValueError):
    """A listener failure that can be shown in the launcher or the CLI."""


class ServerGroup:
    def __init__(self, settings):
        self.settings = settings
        self.servers, self.threads = [], []
        self.stop_event = threading.Event()
        self.runtime = None
        self.client = None
        self._lifecycle = threading.RLock()
        self._listener_sockets = ExitStack()
        self._save_owner = ExitStack()
        self._start_called = False
        self._runtime_closed = False

    def start(self):
        with self._lifecycle:
            if self._start_called:
                raise RuntimeError("服务不能重复启动")
            self._start_called = True
            try:
                self._start()
            except BaseException as error:
                try:
                    self._stop_locked()
                except Exception as cleanup_error:
                    error.add_note(f"服务清理尚未完成（{type(cleanup_error).__name__}）")
                raise

    def _check_startup(self):
        if self.stop_event.is_set():
            raise RuntimeError("服务启动已取消")

    def _reserve_listener(self, name, host, port):
        try:
            listener = self._listener_sockets.enter_context(socket.socket())
            if os.name == "posix":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((host, port))
        except OSError as exc:
            raise ListenerError(f"无法绑定{name}端口 {port}。请检查端口占用情况和监听地址。") from exc
        return listener

    def _run_thread(self, name, target, *args):
        thread = threading.Thread(target=target, args=args, name=name, daemon=True)
        thread.start()
        self.threads.append(thread)

    def failed_listener(self) -> str | None:
        return next((name for name, thread in zip(LISTENER_NAMES, self.threads) if not thread.is_alive()), None)

    def _start(self):
        self._check_startup()
        addresses = ((self.settings.game_host, self.settings.game_port),
                     (self.settings.admin_host, self.settings.admin_port))
        listeners = [self._reserve_listener(name, host, port)
                     for name, (host, port) in zip(LISTENER_NAMES, addresses, strict=True)]
        self._check_startup()
        self._save_owner.enter_context(own_save_directory(self.settings.data_dir))
        self.runtime = Runtime(self.settings)
        self._check_startup()
        game = create_game_app(self.runtime)
        admin = create_admin_app(self.runtime, game.state.request_log)
        tls = {}
        if self.settings.tls:
            certificate, key = ensure_certificate(self.settings)
            tls = {"ssl_certfile": certificate, "ssl_keyfile": key}
        self._check_startup()
        for index, (app, (host, port), options, listener) in enumerate(
                zip((game, admin), addresses, (tls, {}), listeners, strict=True)):
            self._check_startup()
            config = uvicorn.Config(app, host=host, port=port, access_log=False,
                                    log_level=self.settings.log_level.lower(), timeout_graceful_shutdown=5, **options)
            server = uvicorn.Server(config)
            self.servers.append(server)
            self._run_thread(f"terralocal-listener-{index}", server.run, [listener])
        deadline = time.monotonic() + 15
        while True:
            self._check_startup()
            if name := self.failed_listener():
                raise ListenerError(f"{name}启动失败，请检查服务日志。")
            if all(server.started for server in self.servers):
                break
            if time.monotonic() > deadline:
                raise ListenerError("服务启动超时，请检查服务日志。")
            self.stop_event.wait(.05)
        self._run_thread("terralocal-backup", self._backup_loop)
        self._check_startup()
        if name := self.failed_listener():
            raise ListenerError(f"{name}启动失败，请检查服务日志。")

    def create_backup(self) -> dict:
        with self._lifecycle:
            if self.stop_event.is_set() or self.runtime is None or self.failed_listener():
                raise RuntimeError("服务尚未就绪")
            return BackupService(self.runtime).create()

    def _backup_loop(self):
        while not self.stop_event.is_set():
            try:
                BackupService(self.runtime).automatic()
            except Exception as exc:
                import logging

                logging.getLogger("terralocal").error("自动备份失败: %s", type(exc).__name__)
            self.stop_event.wait(60)

    def request_stop(self):
        self.stop_event.set()
        if self.client:
            self.client.request_stop()
        for server in tuple(self.servers):
            server.should_exit = True

    def stop(self):
        self.request_stop()
        with self._lifecycle:
            self._stop_locked()

    def _stop_locked(self):
        self.request_stop()
        for thread in self.threads:
            thread.join(timeout=8)
        if self.client:
            self.client.stop()
        if any(thread.is_alive() for thread in self.threads):
            raise RuntimeError("后台任务仍在停止，请稍后重试")
        self._listener_sockets.close()
        if self.runtime and not self._runtime_closed:
            self.runtime.database.close()
            self._runtime_closed = True
        self._save_owner.close()


def serve(settings):
    group = ServerGroup(settings)
    try:
        group.start()
        print(f"TerraLocal running\nGame: {settings.advertised_url}\nAdmin: http://{settings.admin_host}:{settings.admin_port}", flush=True)
        while not group.stop_event.is_set():
            if name := group.failed_listener():
                raise ListenerError(f"{name}意外停止，请检查服务日志。")
            group.stop_event.wait(.5)
    except KeyboardInterrupt:
        pass
    finally:
        group.stop()
