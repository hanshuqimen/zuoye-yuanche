"""Background account binding, finite credential rotation and cold-boot repair."""
from __future__ import annotations

import json
import queue
import threading
from dataclasses import asdict, dataclass

from terralocal.launcher.android import AndroidTransport
from terralocal.launcher.client_binding import BindingStore, atomic_json, bound_account_name, local_accounts
from terralocal.launcher.client_session import ClientConnectionError, prepare_credential
from terralocal.server.domain.errors import DomainError


@dataclass(frozen=True)
class ConnectionStatus:
    phase: str = "unbound"
    message: str = "请选择本地账号，连接已准备的测试客户端"
    error_code: str | None = None
    account_name: str | None = None
    expires_at: int | None = None


class ClientConnection:
    def __init__(self, runtime, *, transport_factory=AndroidTransport, poll_seconds: float = 5):
        self.runtime = runtime
        self.store = BindingStore(runtime.settings)
        self.cancel, self.stopping, self.wake = threading.Event(), threading.Event(), threading.Event()
        self.transport = transport_factory(runtime.settings, self.cancel)
        self.poll_seconds = poll_seconds
        self._lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._status = ConnectionStatus()
        self._accounts = []
        self._commands = queue.Queue(maxsize=8)
        self._pending_account = None
        self._disconnect_requested = False
        self._credential, self._binding_key = None, None
        self._restart_game = False
        self.thread = None

    def snapshot(self) -> dict:
        with self._lock:
            return {**asdict(self._status), "accounts": list(self._accounts)}

    def _publish(self, phase: str, message: str, *, code=None, account_name=None, expires_at=None):
        with self._lock:
            self._status = ConnectionStatus(phase, message, code, account_name, expires_at)

    def request(self, command: str, account_id: int | None = None) -> None:
        if command not in {"bind", "disconnect", "retry", "refresh"}:
            raise ClientConnectionError("INVALID_CONNECTION_ACTION", "客户端连接操作无效")
        if command == "bind" and (type(account_id) is not int or account_id < 1):
            raise ClientConnectionError("BOUND_ACCOUNT_MISSING", "请选择已有本地账号")
        with self._command_lock:
            if self.stopping.is_set():
                raise ClientConnectionError("CLIENT_STOPPING", "服务正在停止")
            try:
                self._commands.put_nowait((command, account_id))
            except queue.Full:
                raise ClientConnectionError("CLIENT_BUSY", "连接操作正在处理中，请稍后重试") from None
            if command in {"bind", "disconnect"}:
                self.cancel.set()
            self.wake.set()

    def start(self) -> None:
        if self.thread is not None:
            raise RuntimeError("Client connection worker already started")
        thread = threading.Thread(target=self._worker, name="terralocal-client", daemon=True)
        thread.start()
        self.thread = thread

    def request_stop(self) -> None:
        with self._command_lock:
            self.stopping.set()
            self.cancel.set()
            self.wake.set()

    def stop(self) -> None:
        self.request_stop()
        if self.thread is not None:
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                raise RuntimeError("客户端连接任务仍在停止，请稍后重试")

    def _check_cancel(self):
        if self.cancel.is_set() or self.stopping.is_set():
            raise ClientConnectionError("CLIENT_CANCELLED", "连接已停止")

    def _refresh_accounts(self):
        rows = local_accounts(self.runtime)
        with self._lock:
            self._accounts = rows

    def _actions(self):
        processed = False
        # Drain and clear cancellation atomically with incoming owner requests.
        # A failed disconnect remains pending until its private files are cleared.
        with self._command_lock:
            while not self.stopping.is_set():
                try:
                    command, account_id = self._commands.get_nowait()
                except queue.Empty:
                    break
                processed = True
                if command == "bind":
                    self._pending_account, self._disconnect_requested = account_id, False
                elif command == "disconnect":
                    self._pending_account, self._disconnect_requested = None, True
            if processed and not self.stopping.is_set():
                self.cancel.clear()
        self._check_cancel()
        if self._disconnect_requested:
            self.store.clear()
            self.transport.close()
            self._credential, self._binding_key = None, None
            self._restart_game, self._disconnect_requested = False, False
            self._publish("unbound", "已取消自动连接，可重新选择本地账号")
        elif self._pending_account is not None:
            self._publish("connecting", "正在确认测试实例和所选账号…")

    def tick(self) -> None:
        """One real cycle; exposed for deterministic lifecycle and failure checks."""
        self._actions()
        self._check_cancel()
        self._refresh_accounts()
        if self._pending_account is not None:
            if self._pending_account not in {row["id"] for row in self._accounts}:
                raise ClientConnectionError("BOUND_ACCOUNT_MISSING", "请选择已有的本地账号")
            self.transport.validate_configuration()
            self.transport.lease.acquire()
            self.transport.ensure_running()
            self.transport.identify()
            self._check_cancel()
            self.store.bind(self.runtime, self._pending_account)
            self._pending_account = None
            self._credential, self._binding_key = None, None
            self._restart_game = True
        binding = self.store.load()
        if binding is None:
            self._publish("unbound", "请选择本地账号，连接已准备的测试客户端")
            return
        account_name = bound_account_name(self.runtime, binding)
        self.transport.validate_configuration()
        self.transport.lease.acquire()
        self.transport.ensure_running()
        identity = self.transport.identify()
        self._check_cancel()
        key = (binding.account_id, binding.account_uid, binding.client_profile, binding.gamedata_hash)
        if self._binding_key != key:
            self._credential = self.store.credential(binding)
            self._binding_key = key
        if not self.transport.routes_ready(identity):
            self._publish("connecting", "正在恢复测试实例的本地连接…", account_name=account_name)
            self.transport.configure_routes(identity)
        self._check_cancel()
        self._credential = prepare_credential(self.runtime, binding.account_id, binding.account_uid,
                                              self._credential, cancel=self.cancel)
        self._check_cancel()
        login = self.store.directory / "terralocal-login.json"
        callback = self._credential.callback()
        # Atomic replacement is needed when the app reads while credentials rotate.
        saved = self.store.credential(binding)
        if saved is None or saved.code != self._credential.code:
            atomic_json(login, callback)
        update = self.store.directory / "terralocal-update.json"
        expected_update = {"code": 0, "version": "2.7.71", "action": 0, "updateType": 0,
                           "updateInfo": "", "state": 0}
        if update.is_symlink() or update.is_junction():
            raise ClientConnectionError("CLIENT_BINDING_PATH", "启动器更新文件不能使用目录链接")
        try:
            current_update = json.loads(update.read_bytes()) if update.stat().st_size <= 8192 else None
        except (FileNotFoundError, ValueError, UnicodeError):
            current_update = None
        if current_update != expected_update:
            atomic_json(update, expected_update)
        for name, path in (("terralocal-login.json", login), ("terralocal-update.json", update)):
            self._check_cancel()
            if not self.transport.file_matches(name, path):
                self.transport.deliver(name, path)
        self._check_cancel()
        if self._restart_game:
            self.transport.stop_game()
            self._restart_game = False
        self.transport.launch_game()
        self._publish("connected", "客户端连接已准备 · 登录凭据自动续期中", account_name=account_name,
                      expires_at=self._credential.expires_at)

    def _worker(self):
        try:
            while not self.stopping.is_set():
                try:
                    self.tick()
                except ClientConnectionError as error:
                    if error.code != "CLIENT_CANCELLED":
                        self._publish("waiting" if error.code in {"EMULATOR_STARTING", "EMULATOR_NOT_READY",
                                      "EMULATOR_TIMEOUT", "CLIENT_ADB_SERVER_FAILED"} else "error", str(error), code=error.code)
                except DomainError as error:
                    self._publish("error", error.message, code=error.code)
                except OSError:
                    self._publish("error", "无法保存客户端连接文件，请检查数据目录", code="CLIENT_FILE_IO")
                except Exception:
                    # UI never exposes exception payloads or credential-bearing data.
                    self._publish("error", "客户端连接准备失败，请重新连接并查看服务日志", code="CLIENT_CONNECTION_FAILED")
                self.wake.wait(self.poll_seconds)
                self.wake.clear()
        finally:
            self.transport.close()
            self._publish("stopped", "客户端自动连接已停止")
