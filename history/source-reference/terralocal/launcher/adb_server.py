"""An owned loopback ADB server, independent of a user's shared port 5037."""
from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from terralocal.launcher.client_session import ClientConnectionError

STARTUP_TIMEOUT = 8


def adb_environment(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for key in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_PORT", "ANDROID_ADB_SERVER_ADDRESS"):
        environment.pop(key, None)
    environment.update(ANDROID_USER_HOME=str(directory), ANDROID_SDK_HOME=str(directory))
    return environment


class OwnedAdbServer:
    def __init__(self, executable: Path, directory: Path, serial: str, cancel: threading.Event):
        self.executable, self.directory, self.serial, self.cancel = executable, directory, serial, cancel
        self._process: subprocess.Popen | None = None
        self._port: int | None = None
        self._lock = threading.RLock()

    def ensure(self) -> int:
        with self._lock:
            if self.cancel.is_set():
                raise ClientConnectionError("CLIENT_CANCELLED", "连接已停止")
            if self._process is not None and self._process.poll() is None:
                return self._port
            self.close()
            # Release the reservation before ADB binds. If another process wins
            # that race, readiness never accepts an exited owned child.
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            try:
                self._process = subprocess.Popen(
                    [str(self.executable), "-L", f"tcp:{port}", "--one-device", self.serial, "server", "nodaemon"],
                    env=adb_environment(self.directory), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                self._port = port
                deadline = time.monotonic() + STARTUP_TIMEOUT
                while self._process.poll() is None:
                    if self.cancel.is_set():
                        raise ClientConnectionError("CLIENT_CANCELLED", "连接已停止")
                    if time.monotonic() >= deadline:
                        break
                    if self._ready(port) and self._process.poll() is None:
                        return port
                    self.cancel.wait(.05)
            except ClientConnectionError:
                self.close()
                raise
            except OSError:
                self.close()
                raise ClientConnectionError("EMULATOR_TOOLS_MISSING", "请检查雷电安装目录和连接工具") from None
            self.close()
            raise ClientConnectionError("CLIENT_ADB_SERVER_FAILED", "独立设备连接服务未能启动，将自动重试")

    @staticmethod
    def _ready(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=.1) as client:
                client.settimeout(.1)
                client.sendall(b"000chost:version")
                reply = bytearray()
                while len(reply) < 12:
                    chunk = client.recv(12 - len(reply))
                    if not chunk:
                        return False
                    reply.extend(chunk)
                return (reply[:8] == b"OKAY0004" and all(
                    byte in b"0123456789abcdefABCDEF" for byte in reply[8:]) and int(reply[8:], 16) > 0)
        except OSError:
            return False

    def close(self) -> None:
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=.75)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=.75)
            self._process, self._port = None, None
