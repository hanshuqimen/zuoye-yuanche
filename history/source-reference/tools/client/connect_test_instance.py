"""Route the dedicated Android test client to TerraLocal over ADB reverse.

All changes are restricted to index 1. The local CA and hosts backup remain
inside the workspace. The game's external network access is blocked during
validation, while its loopback connection to the server remains available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from terralocal.config import load_settings  # noqa: E402

ADB = Path("<emulator-directory>/adb.exe")
SERIAL = "test-transport-example"
PACKAGE = "com.hypergryph.arknights"
RECORDS = ROOT / "data/client/test-instance"
MARKER = "TerraLocal isolated test routing"


def adb(*args: str) -> str:
    return subprocess.run([str(ADB), "-s", SERIAL, *args], check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout.strip()


def root(command: str) -> str:
    if "'" in command:
        raise ValueError("Unexpected quote in root command")
    return adb("shell", f"su -c '{command}'")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-game-port", type=int, default=8443,
                        help="Host loopback game listener; Android still uses the frozen HTTPS route")
    options = parser.parse_args()
    if not 1024 <= options.host_game_port <= 65535:
        parser.error("Host game port must be in 1024..65535")
    identity = json.loads((RECORDS / "installation.json").read_bytes())
    if identity["instance"] != 1 or identity["serial"] != SERIAL:
        raise RuntimeError("Missing isolated installation receipt")
    listing = subprocess.run([str(ADB.with_name("ldconsole.exe")), "list2"], check=True,
                             capture_output=True).stdout.decode("utf-8", "replace")
    if not any(row.startswith("1,TerraLocal,") and row.split(",")[4] == "1"
               for row in listing.splitlines()):
        raise RuntimeError("The dedicated test instance is not running")
    if adb("shell", "getprop", "ro.serialno") != "test-device-example":
        raise RuntimeError("Emulator identity mismatch")
    if root("id").split()[0] != "uid=0(root)":
        raise RuntimeError("Root is required on this isolated Android test image")
    settings = load_settings()
    ca_path = settings.data_dir / "certs/ca.pem"
    ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
    subject_hash = int.from_bytes(hashlib.md5(ca.subject.public_bytes()).digest()[:4], "little")
    ca_name = f"{subject_hash:08x}.0"
    host_names = settings.tls_dns_names
    if not host_names or settings.game_port != 8443:
        raise RuntimeError("The local TLS routing configuration is not ready")
    current = adb("shell", "cat", "/system/etc/hosts").replace("\r", "")
    backup = RECORDS / "hosts.original"
    if not backup.exists():
        backup.write_text(current + "\n", encoding="utf-8", newline="\n")
    # Repeating this operation replaces only the marker-delimited local block.
    clean = re.sub(rf"(?ms)^# BEGIN {MARKER}\n.*?^# END {MARKER}\n?", "", current + "\n")
    block = "\n".join(f"127.0.0.1 {host}" for host in host_names)
    hosts = RECORDS / "hosts.local"
    hosts.write_text(clean.rstrip() + f"\n# BEGIN {MARKER}\n{block}\n# END {MARKER}\n",
                     encoding="utf-8", newline="\n")
    adb("push", str(hosts), "/data/local/tmp/terralocal-hosts")
    adb("push", str(ca_path), "/data/local/tmp/terralocal-ca.pem")
    # A unique TerraLocal issuer should not collide with an existing CA; never
    # replace a differently fingerprinted certificate at the same hash slot.
    target = f"/system/etc/security/cacerts/{ca_name}"
    try:
        existing = adb("shell", "cat", target)
    except subprocess.CalledProcessError:
        existing = ""
    if existing and x509.load_pem_x509_certificate(existing.encode()).fingerprint(
            hashes.SHA256()) != ca.fingerprint(hashes.SHA256()):
        raise RuntimeError("CA hash collision; the existing Android certificate was retained")
    # LDPlayer's base image is a read-only block device. Bind a local overlay
    # instead of altering the base image or disabling verified boot.
    install_script = RECORDS / "install-routing.sh"
    mirror = "/data/local/tmp/terralocal-cacerts"
    script = ["#!/system/bin/sh", "set -e", f"mkdir -p {mirror}",
              "for cert in /system/etc/security/cacerts/*; do",
              f'  name=${{cert##*/}}; [ -f {mirror}/"$name" ] || cp "$cert" {mirror}/', "done",
              f"cp /data/local/tmp/terralocal-ca.pem {mirror}/{ca_name}",
              f"chmod 755 {mirror}", f"chmod 644 {mirror}/* /data/local/tmp/terralocal-hosts",
              f"chcon -R u:object_r:system_file:s0 {mirror}",
              "chcon u:object_r:system_file:s0 /data/local/tmp/terralocal-hosts"]
    mounted = {row.split()[1] for row in adb("shell", "cat", "/proc/mounts").splitlines()}
    if "/system/etc/hosts" in mounted:
        if MARKER not in current:
            raise RuntimeError("Hosts is mounted by another tool; refusing to replace that mount")
        script.append("umount /system/etc/hosts")
    script.append("mount -o bind /data/local/tmp/terralocal-hosts /system/etc/hosts")
    if "/system/etc/security/cacerts" not in mounted:
        script.append(f"mount -o bind {mirror} /system/etc/security/cacerts")
    install_script.write_text("\n".join(script) + "\n", encoding="utf-8", newline="\n")
    adb("push", str(install_script), "/data/local/tmp/terralocal-install-routing.sh")
    root("sh /data/local/tmp/terralocal-install-routing.sh")
    if MARKER not in adb("shell", "cat", "/system/etc/hosts"):
        raise RuntimeError("Hosts overlay is not visible outside the root shell")
    adb("reverse", "tcp:8443", f"tcp:{options.host_game_port}")
    package_info = adb("shell", "dumpsys", "package", PACKAGE)
    uid = re.search(r"\buserId=(\d+)", package_info)
    if uid is None:
        raise RuntimeError("No application UID")
    uid = uid.group(1)
    # Unprivileged adbd cannot bind port 443. Redirect only this application's
    # loopback HTTPS connections to the high-port reverse tunnel.
    try:
        root("iptables -t nat -N TL_HTTPS")
    except subprocess.CalledProcessError:
        pass
    root("iptables -t nat -F TL_HTTPS")
    root("iptables -t nat -A TL_HTTPS -p tcp --dport 443 -j REDIRECT --to-ports 8443")
    nat_rule = f"OUTPUT -d 127.0.0.0/8 -m owner --uid-owner {uid} -j TL_HTTPS"
    try:
        root(f"iptables -t nat -C {nat_rule}")
    except subprocess.CalledProcessError:
        root(f"iptables -t nat -I {nat_rule}")
    for tool, loopback in (("iptables", "127.0.0.0/8"), ("ip6tables", "::1/128")):
        try:
            root(f"{tool} -N TL_OFFLINE")
        except subprocess.CalledProcessError:
            pass
        root(f"{tool} -F TL_OFFLINE")
        root(f"{tool} -A TL_OFFLINE -d {loopback} -j RETURN")
        root(f"{tool} -A TL_OFFLINE -j REJECT")
        rule = f"OUTPUT -m owner --uid-owner {uid} -j TL_OFFLINE"
        try:
            root(f"{tool} -C {rule}")
        except subprocess.CalledProcessError:
            root(f"{tool} -I {rule}")
    with httpx.Client(verify=str(ca_path), trust_env=False) as client:
        host_url = f"https://127.0.0.1:{options.host_game_port}"
        version = client.get(host_url + "/config/prod/official/Android/version")
        version.raise_for_status()
        if version.json()["clientVersion"] != "2.7.71":
            raise RuntimeError("The server does not match the frozen test client version")
        response = client.post(host_url + "/local/v1/sdk/login", json={"name": "Doctor"})
        response.raise_for_status()
        callback = response.json()["callback"]
    # Only a locally issued credential is placed in the test client's own files.
    login_file = RECORDS / "terralocal-login.json"
    login_file.write_text(json.dumps(callback, separators=(",", ":")), encoding="utf-8")
    adb("push", str(login_file), f"/sdcard/Android/data/{PACKAGE}/files/terralocal-login.json")
    update_file = RECORDS / "terralocal-update.json"
    update_file.write_text(json.dumps({"code": 0, "version": version.json()["clientVersion"],
                                     "action": 0, "updateType": 0, "updateInfo": "", "state": 0},
                                    separators=(",", ":")), encoding="utf-8")
    adb("push", str(update_file), f"/sdcard/Android/data/{PACKAGE}/files/terralocal-update.json")
    (RECORDS / "routing.json").write_text(json.dumps(
        {"instance": 1, "serial": SERIAL, "hosts": host_names, "ca_file": ca_name,
         "application_uid": int(uid), "reverse_ports": [8443], "local_https_redirect": "443 -> 8443",
         "host_game_port": options.host_game_port,
         "external_game_network": "blocked",
         "account_name": "Doctor", "client_verified": False}, indent=2), encoding="utf-8")
    print("Local account bound; Android test routing and offline firewall are active", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError, httpx.HTTPError) as exc:
        print(f"Test routing failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
