"""Frozen LDPlayer client transport. Never target the original instance 0."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from terralocal.launcher.adb_server import OwnedAdbServer, adb_environment
from terralocal.launcher.client_binding import (
    CAMPAIGN_CLIENT_PROFILE,
    DEVICE_SERIAL,
    INSTANCE,
    INSTANCE_NAME,
    PACKAGE,
    SERIAL,
    expected_apk,
    installation_folder,
    private_directory,
)
from terralocal.launcher.client_session import ClientConnectionError
from terralocal.server.compatibility.profile import (
    CAMPAIGN_DATA_HASH,
    CRISIS_NATIVE_PROFILES,
    ROGUE_CLIENT_PROFILE,
    ROGUE_DATA_HASH,
)
from terralocal.server.protocol.bootstrap import Bootstrap

ORIGINAL_APK = "0b79b85383e21a6343283bc6bfd7a9d24eb4134abf901115f757da6a5d50f6db"
FROZEN_DATA = "f44199a7d34a82bdbb232674db3a3cdf9d7958230217fce3960ccafd351b7406"
CAMPAIGN_DATA = CAMPAIGN_DATA_HASH
RESOURCE_INDEX = "c3151e169fcbbf9fb10106100b071c7d.idx"
HOSTS = {"ak-conf.hypergryph.com", "ak-gs-gf.hypergryph.com", "ak-webview.hypergryph.com",
         "ak.hycdn.cn", "ak.hypergryph.com", "as.hypergryph.com", "game-config.hypergryph.com"}
MARKER = "TerraLocal isolated test routing"
FILES = f"/sdcard/Android/data/{PACKAGE}/files"
CA_MIRROR = "/data/local/tmp/terralocal-cacerts"


@dataclass(frozen=True)
class AndroidIdentity:
    boot_id: str
    apk_path: str
    application_uid: int


class InstanceLease:
    """One launcher can own this emulator at a time, across private save roots."""
    def __init__(self):
        self.handle = None
        self.kernel = None

    def acquire(self) -> None:
        if self.handle is not None:
            return
        if os.name != "nt":
            raise ClientConnectionError("CLIENT_HOST_UNSUPPORTED", "此客户端连接适配需要 Windows")
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel.ReleaseMutex.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        handle = kernel.CreateMutexW(None, True, r"Local\TerraLocal-LDPlayer-0063090c")
        if not handle:
            raise ClientConnectionError("CLIENT_LEASE_FAILED", "无法锁定测试实例连接，请重试")
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle(handle)
            raise ClientConnectionError("CLIENT_ALREADY_CONNECTED", "另一个 TerraLocal 已连接此测试实例")
        self.kernel, self.handle = kernel, handle

    def close(self) -> None:
        if self.handle is not None:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class AndroidTransport:
    def __init__(self, settings, cancel: threading.Event):
        self.settings, self.cancel = settings, cancel
        self.adb = settings.emulator_dir / "adb.exe"
        self.console = settings.emulator_dir / "ldconsole.exe"
        self.lease = InstanceLease()
        self._verified = None
        self._launch_retry_at = 0.0
        self._adb_server = OwnedAdbServer(self.adb, private_directory(settings) / "adb-home", SERIAL, cancel)

    def adb_arguments(self, *args: str) -> tuple[str, ...]:
        return ("-H", "127.0.0.1", "-P", str(self._adb_server.ensure()), "-s", SERIAL, *args)

    def _run(self, executable: Path, args: tuple[str, ...], *, probe: bool = False) -> str | None:
        if self.cancel.is_set():
            raise ClientConnectionError("CLIENT_CANCELLED", "连接已停止")
        adb_home = private_directory(self.settings) / "adb-home"
        environment = adb_environment(adb_home)
        try:
            result = subprocess.run([str(executable), *args], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=8, env=environment,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            if executable == self.adb:
                # Only terminate our Popen child; never kill a shared daemon or
                # identify ownership by a possibly reused numeric process ID.
                self._adb_server.close()
            raise ClientConnectionError("EMULATOR_TIMEOUT", "测试模拟器响应超时，连接会自动重试") from None
        except OSError:
            raise ClientConnectionError("EMULATOR_TOOLS_MISSING", "请检查雷电安装目录和连接工具") from None
        if self.cancel.is_set():
            raise ClientConnectionError("CLIENT_CANCELLED", "连接已停止")
        if result.returncode != 0:
            if probe:
                return None
            # Never include stderr, shell commands, credential contents or paths.
            raise ClientConnectionError("EMULATOR_NOT_READY", "正在等待测试模拟器完成启动")
        return result.stdout.strip()

    def command(self, *args: str, probe: bool = False) -> str | None:
        return self._run(self.adb, self.adb_arguments(*args), probe=probe)

    def root(self, command: str, *, probe: bool = False) -> str | None:
        if "'" in command:
            raise ClientConnectionError("INVALID_ANDROID_COMMAND", "客户端连接指令无效")
        # Recheck hardware identity inside the same privileged shell invocation.
        guard = f'[ "$(getprop ro.serialno)" = "{DEVICE_SERIAL}" ] || exit 97; '
        return self.command("shell", f"su -c '{guard}{command}'", probe=probe)

    def validate_configuration(self) -> None:
        profile = Bootstrap(self.settings).profile()
        # The extra table has its own explicit QA profile/save admission. Do
        # not accept either hash interchangeably for the older profiles.
        expected_data = {CAMPAIGN_CLIENT_PROFILE: CAMPAIGN_DATA, ROGUE_CLIENT_PROFILE: ROGUE_DATA_HASH,
                         **CRISIS_NATIVE_PROFILES}.get(self.settings.client_profile, FROZEN_DATA)
        if (profile.package, profile.channel, profile.client_version, profile.version_code,
                profile.apk_sha256, profile.resource_version, profile.api_version, profile.gamedata_hash) != (
                PACKAGE, "official", "2.7.71", 190, ORIGINAL_APK, "26-09-22-07-47-20_6c71fa", "V070", expected_data):
            raise ClientConnectionError("UNSUPPORTED_CLIENT_PROFILE", "此客户端版本尚未完成连接适配")
        url = urlsplit(self.settings.advertised_url)
        if (not self.settings.tls or self.settings.game_host not in {"0.0.0.0", "127.0.0.1"}
                or url.scheme != "https" or url.hostname != "127.0.0.1" or url.port != 8443
                or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment
                or set(self.settings.tls_dns_names) != HOSTS or self.settings.emulator_index not in {None, INSTANCE}):
            raise ClientConnectionError("CLIENT_ROUTING_CONFIG", "测试实例的本地 HTTPS 配置尚未准备完成")
        try:
            receipt = json.loads((self.settings.data_dir / "client" /
                                  installation_folder(self.settings.client_profile) / "installation.json").read_bytes())
        except (OSError, ValueError, UnicodeError):
            raise ClientConnectionError("CLIENT_NOT_PREPARED", "请先准备匹配版本的独立测试客户端") from None
        if (not isinstance(receipt, dict) or type(receipt.get("instance")) is not int
                or receipt.get("official_authentication_copied") is not False or (
                receipt.get("instance"), receipt.get("name"), receipt.get("serial"), receipt.get("apk_sha256"),
                receipt.get("resource_manifest"), receipt.get("official_authentication_copied")) != (
                INSTANCE, INSTANCE_NAME, SERIAL, expected_apk(self.settings.client_profile), RESOURCE_INDEX, False)):
            raise ClientConnectionError("CLIENT_RECEIPT_MISMATCH", "独立测试客户端的准备记录不匹配")
        if not self.adb.is_file() or not self.console.is_file():
            raise ClientConnectionError("EMULATOR_TOOLS_MISSING", "请检查雷电安装目录和连接工具")

    def ensure_running(self) -> None:
        listing = self._run(self.console, ("list2",)) or ""
        rows = [line.split(",") for line in listing.splitlines() if line.startswith(f"{INSTANCE},")]
        if len(rows) != 1 or len(rows[0]) < 7 or rows[0][1] != INSTANCE_NAME:
            raise ClientConnectionError("EMULATOR_INSTANCE_MISMATCH", "未找到已准备的 TerraLocal 测试实例")
        if rows[0][4] != "1":
            at = time.monotonic()
            if at >= self._launch_retry_at:
                self._launch_retry_at = at + 30
                self._run(self.console, ("launch", "--index", str(INSTANCE)))
            raise ClientConnectionError("EMULATOR_STARTING", "正在启动 TerraLocal 测试实例")
        self._launch_retry_at = 0.0

    def identify(self) -> AndroidIdentity:
        serial = self.command("shell", "getprop", "ro.serialno")
        if serial != DEVICE_SERIAL:
            raise ClientConnectionError("EMULATOR_IDENTITY_MISMATCH", "测试实例身份不匹配，连接已停止")
        boot = self.command("shell", "cat", "/proc/sys/kernel/random/boot_id") or ""
        if not re.fullmatch(r"[a-f0-9-]{36}", boot):
            raise ClientConnectionError("EMULATOR_NOT_READY", "正在等待测试模拟器完成启动")
        apk = self.command("shell", "pm", "path", PACKAGE) or ""
        if not re.fullmatch(r"package:/data/app/[A-Za-z0-9_./+=~-]+\.apk", apk):
            raise ClientConnectionError("CLIENT_APK_MISSING", "测试实例没有匹配的客户端安装")
        path = apk.removeprefix("package:")
        package = self.command("shell", "dumpsys", "package", PACKAGE) or ""
        uid = re.search(r"\buserId=(\d+)\b", package)
        update = re.search(r"\blastUpdateTime=([^\r\n]+)", package)
        if uid is None or not 1 <= int(uid.group(1)) < 2**31:
            raise ClientConnectionError("CLIENT_PACKAGE_INVALID", "无法确认测试客户端的安装身份")
        identity = AndroidIdentity(boot, path, int(uid.group(1)))
        key = (identity, update.group(1) if update else package, expected_apk(self.settings.client_profile))
        if self._verified != key:
            digest = self.command("shell", "sha256sum", path) or ""
            if digest.split()[:1] != [expected_apk(self.settings.client_profile)]:
                raise ClientConnectionError("UNSUPPORTED_CLIENT_APK", "客户端安装包已变化，请准备经过验证的适配版本")
            if self.command("shell", "test", "-f", f"{FILES}/Bundles/{RESOURCE_INDEX}", probe=True) is None:
                raise ClientConnectionError("CLIENT_RESOURCES_MISSING", "测试客户端资源不完整，请重新准备资源")
            if not (self.root("id") or "").startswith("uid=0(root)"):
                raise ClientConnectionError("EMULATOR_ROOT_REQUIRED", "独立测试实例需要已准备的 root 环境")
            self._verified = key
        return identity

    def routes_ready(self, identity: AndroidIdentity) -> bool:
        reverse = self.command("reverse", "--list", probe=True) or ""
        expected = ("tcp:8443", f"tcp:{self.settings.game_port}")
        if not any(tuple(row.split()[-2:]) == expected for row in reverse.splitlines()):
            return False
        hosts = self.command("shell", "cat", "/system/etc/hosts", probe=True) or ""
        if MARKER not in hosts or any(f"127.0.0.1 {host}" not in hosts for host in HOSTS):
            return False
        ca = x509.load_pem_x509_certificate((self.settings.data_dir / "certs/ca.pem").read_bytes())
        subject_hash = int.from_bytes(hashlib.md5(ca.subject.public_bytes()).digest()[:4], "little")
        visible = self.command("shell", "cat", f"/system/etc/security/cacerts/{subject_hash:08x}.0", probe=True)
        try:
            if not visible or x509.load_pem_x509_certificate(visible.encode()).fingerprint(hashes.SHA256()) != (
                    ca.fingerprint(hashes.SHA256())):
                return False
        except ValueError:
            return False
        for tool, loopback in (("iptables", "127.0.0.0/8"), ("ip6tables", "::1/128")):
            rules = (self.root(f"{tool} -S TL_OFFLINE", probe=True) or "").splitlines()
            if (len(rules) != 3 or rules[0] != "-N TL_OFFLINE"
                    or rules[1] != f"-A TL_OFFLINE -d {loopback} -j RETURN"
                    or not re.fullmatch(r"-A TL_OFFLINE -j REJECT(?: --reject-with [a-z0-9-]+)?", rules[2])):
                return False
            if self.root(f"{tool} -C OUTPUT -m owner --uid-owner {identity.application_uid} -j TL_OFFLINE",
                         probe=True) is None:
                return False
        nat = (self.root("iptables -t nat -S TL_HTTPS", probe=True) or "").splitlines()
        return (len(nat) == 2 and nat[0] == "-N TL_HTTPS"
                and self.root("iptables -t nat -C TL_HTTPS -p tcp --dport 443 -j REDIRECT --to-ports 8443",
                              probe=True) is not None
                and self.root("iptables -t nat -C OUTPUT -d 127.0.0.0/8 -m owner --uid-owner "
                              f"{identity.application_uid} -j TL_HTTPS", probe=True) is not None)

    def configure_routes(self, identity: AndroidIdentity) -> None:
        certificate = self.settings.data_dir / "certs/ca.pem"
        ca = x509.load_pem_x509_certificate(certificate.read_bytes())
        subject_hash = int.from_bytes(hashlib.md5(ca.subject.public_bytes()).digest()[:4], "little")
        ca_name = f"{subject_hash:08x}.0"
        target = f"/system/etc/security/cacerts/{ca_name}"
        current = (self.command("shell", "cat", "/system/etc/hosts") or "").replace("\r", "")
        mounted = {row.split()[1] for row in (self.command("shell", "cat", "/proc/mounts") or "").splitlines()}
        if "/system/etc/hosts" in mounted and MARKER not in current:
            raise ClientConnectionError("ANDROID_HOSTS_BUSY", "测试实例的网络配置被其他工具占用")
        existing = self.command("shell", "cat", target, probe=True)
        if existing and x509.load_pem_x509_certificate(existing.encode()).fingerprint(hashes.SHA256()) != (
                ca.fingerprint(hashes.SHA256())):
            raise ClientConnectionError("ANDROID_CA_COLLISION", "测试实例已有不同证书，请检查客户端准备状态")
        if "/system/etc/security/cacerts" in mounted and not existing:
            raise ClientConnectionError("ANDROID_CA_BUSY", "测试实例的证书配置被其他工具占用")
        records = private_directory(self.settings)
        records.mkdir(parents=True, exist_ok=True)
        backup = records / "hosts.original"
        if not backup.exists():
            backup.write_text(current + "\n", "utf-8", newline="\n")
        clean = re.sub(rf"(?ms)^# BEGIN {MARKER}\n.*?^# END {MARKER}\n?", "", current + "\n")
        hosts = records / "hosts.local"
        hosts.write_text(clean.rstrip() + f"\n# BEGIN {MARKER}\n"
                         + "\n".join(f"127.0.0.1 {name}" for name in sorted(HOSTS))
                         + f"\n# END {MARKER}\n", "utf-8", newline="\n")
        # Block external game traffic before swapping network overlays.
        for tool, loopback in (("iptables", "127.0.0.0/8"), ("ip6tables", "::1/128")):
            self.root(f"{tool} -N TL_OFFLINE", probe=True)
            self.root(f"{tool} -F TL_OFFLINE")
            self.root(f"{tool} -A TL_OFFLINE -d {loopback} -j RETURN")
            self.root(f"{tool} -A TL_OFFLINE -j REJECT")
            rule = f"OUTPUT -m owner --uid-owner {identity.application_uid} -j TL_OFFLINE"
            if self.root(f"{tool} -C {rule}", probe=True) is None:
                self.root(f"{tool} -I {rule}")
        self.command("push", str(hosts), "/data/local/tmp/terralocal-hosts")
        self.command("push", str(certificate), "/data/local/tmp/terralocal-ca.pem")
        script = ["#!/system/bin/sh", "set -e", f"mkdir -p {CA_MIRROR}",
                  "for cert in /system/etc/security/cacerts/*; do",
                  f'  name=${{cert##*/}}; [ -f {CA_MIRROR}/"$name" ] || cp "$cert" {CA_MIRROR}/', "done",
                  f"cp /data/local/tmp/terralocal-ca.pem {CA_MIRROR}/{ca_name}",
                  f"chmod 755 {CA_MIRROR}", f"chmod 644 {CA_MIRROR}/* /data/local/tmp/terralocal-hosts",
                  f"chcon -R u:object_r:system_file:s0 {CA_MIRROR}",
                  "chcon u:object_r:system_file:s0 /data/local/tmp/terralocal-hosts"]
        if "/system/etc/hosts" in mounted:
            script.append("umount /system/etc/hosts")
        script.append("mount -o bind /data/local/tmp/terralocal-hosts /system/etc/hosts")
        if "/system/etc/security/cacerts" not in mounted:
            script.append(f"mount -o bind {CA_MIRROR} /system/etc/security/cacerts")
        install = records / "install-routing.sh"
        install.write_text("\n".join(script) + "\n", "utf-8", newline="\n")
        self.command("push", str(install), "/data/local/tmp/terralocal-install-routing.sh")
        self.root("sh /data/local/tmp/terralocal-install-routing.sh")
        visible = self.command("shell", "cat", target) or ""
        if x509.load_pem_x509_certificate(visible.encode()).fingerprint(hashes.SHA256()) != ca.fingerprint(
                hashes.SHA256()):
            raise ClientConnectionError("ANDROID_CA_NOT_VISIBLE", "本地证书未成功加载，请重新连接测试实例")
        self.command("reverse", "tcp:8443", f"tcp:{self.settings.game_port}")
        self.root("iptables -t nat -N TL_HTTPS", probe=True)
        self.root("iptables -t nat -F TL_HTTPS")
        self.root("iptables -t nat -A TL_HTTPS -p tcp --dport 443 -j REDIRECT --to-ports 8443")
        rule = f"OUTPUT -d 127.0.0.0/8 -m owner --uid-owner {identity.application_uid} -j TL_HTTPS"
        if self.root(f"iptables -t nat -C {rule}", probe=True) is None:
            self.root(f"iptables -t nat -I {rule}")
        if not self.routes_ready(identity):
            raise ClientConnectionError("CLIENT_ROUTE_FAILED", "客户端连接尚未准备完成，会自动重试")

    def file_matches(self, name: str, path: Path) -> bool:
        if name not in {"terralocal-login.json", "terralocal-update.json"}:
            raise ClientConnectionError("INVALID_CLIENT_FILE", "客户端连接文件无效")
        digest = self.command("shell", "sha256sum", f"{FILES}/{name}", probe=True) or ""
        return digest.split()[:1] == [hashlib.sha256(path.read_bytes()).hexdigest()]

    def deliver(self, name: str, path: Path) -> None:
        if name not in {"terralocal-login.json", "terralocal-update.json"}:
            raise ClientConnectionError("INVALID_CLIENT_FILE", "客户端连接文件无效")
        self.command("shell", "mkdir", "-p", FILES)
        self.command("push", str(path), f"{FILES}/{name}.tmp")
        self.command("shell", "mv", f"{FILES}/{name}.tmp", f"{FILES}/{name}")
        if not self.file_matches(name, path):
            raise ClientConnectionError("CLIENT_FILE_DELIVERY_FAILED", "登录文件未成功更新，会自动重试")

    def launch_game(self) -> None:
        if not self.command("shell", "pidof", PACKAGE, probe=True):
            self.command("shell", "monkey", "-p", PACKAGE, "-c", "android.intent.category.LAUNCHER", "1")

    def stop_game(self) -> None:
        self.command("shell", "am", "force-stop", PACKAGE)

    def close(self) -> None:
        self._adb_server.close()
        self.lease.close()
