"""Install a fingerprinted local adapter on the dedicated TerraLocal test instance.

Only Bundles are retained. SDK/private application data are deliberately not copied.
The original LDPlayer instance is never a valid target for this tool.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADB = Path("<emulator-directory>/adb.exe")
CONSOLE = ADB.with_name("ldconsole.exe")
SERIAL = "test-transport-example"
PACKAGE = "com.hypergryph.arknights"
SOURCE = f"/sdcard/Android/data/{PACKAGE}/files/Bundles"
BACKUP = "/sdcard/TerraLocal-backup/resources-cn-2.7.71"
INDEX = "c3151e169fcbbf9fb10106100b071c7d.idx"
PATCH = ROOT / "data/client/patch/cn-2.7.71-static-sdk-v2"


def command(*args: str) -> str:
    result = subprocess.run([str(ADB), "-s", SERIAL, *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=True)
    return result.stdout.strip()


def inventory(path: str) -> str:
    # Filenames come from a resource tree, never from application credentials.
    return command("shell", f"find {path} -type f -exec stat -c '%s %n' '{{}}' '+'")


def exists(path: str) -> bool:
    try:
        command("shell", "ls", "-d", path)
        return True
    except subprocess.CalledProcessError:
        return False


def install_candidate(apk: Path, fingerprint: str, *, replace: bool = False) -> str:
    """Use the verified D-drive share when available; avoid slow streamed APK writes."""
    shared = "/mnt/shared/Applications/TerraLocal-client-v2.apk"
    marker = "/mnt/shared/Applications/terralocal-test-marker.txt"
    flags = ["-r", "-g"] if replace else ["-g"]
    if exists(marker) and command("shell", "cat", marker).strip() == "TerraLocal index 1 workspace share":
        if command("shell", "sha256sum", shared).split()[0] == fingerprint:
            print("Installing from the verified workspace share", flush=True)
            result = command("shell", "pm", "install", *flags, shared)
            if result != "Success":
                raise RuntimeError(f"Android package installation failed: {result}")
            return result
        raise RuntimeError("Shared APK fingerprint mismatch")
    return command("install", *flags, str(apk))


def main() -> None:
    listing = subprocess.run([str(CONSOLE), "list2"], capture_output=True, check=True).stdout.decode(
        "utf-8", errors="replace").splitlines()
    if not any(row.startswith("1,TerraLocal,") and row.split(",")[4] == "1" for row in listing):
        raise RuntimeError("The dedicated index 1 TerraLocal instance is not running")
    if command("shell", "getprop", "ro.serialno") != "test-device-example":
        raise RuntimeError("Unexpected emulator identity; refusing to modify it")
    manifest = json.loads((PATCH / "manifest.json").read_bytes())
    apk = PATCH / "TerraLocal-client.apk"
    with apk.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != manifest["output_apk_sha256"]:
        raise RuntimeError("Adapter APK fingerprint mismatch")
    command("shell", "am", "force-stop", PACKAGE)
    record_dir = ROOT / "data/client/test-instance"
    record_dir.mkdir(parents=True, exist_ok=True)
    record = record_dir / "resources-before.txt"
    receipt = record_dir / "installation.json"
    if receipt.exists() and PACKAGE in command("shell", "pm", "list", "packages", PACKAGE):
        prior = json.loads(receipt.read_bytes())
        apk_path = command("shell", "pm", "path", PACKAGE).removeprefix("package:")
        if not apk_path.startswith("/data/app/") or not apk_path.endswith("/base.apk") or " " in apk_path:
            raise RuntimeError("Unexpected installed APK path")
        installed_hash = command("shell", "sha256sum", apk_path).split()[0]
        if installed_hash not in {prior["apk_sha256"], actual}:
            raise RuntimeError("The installed APK differs from the local adapter receipt")
        upgrade_record = record_dir / f"resources-upgrade-before-{actual[:12]}.txt"
        if installed_hash != actual:
            # The client can legitimately refresh its cache between upgrades.
            # Compare an upgrade to its own immediate pre-install snapshot.
            upgrade_record.write_text(inventory(SOURCE), encoding="utf-8")
            print("Upgrading the verified local adapter; retaining resources and local data", flush=True)
            print(install_candidate(apk, actual, replace=True), flush=True)
        baseline = upgrade_record if upgrade_record.exists() else record
        after = inventory(SOURCE)
        if sorted(after.splitlines()) != sorted(baseline.read_text(encoding="utf-8").splitlines()):
            raise RuntimeError("Resource inventory differs after adapter upgrade")
        prior["apk_sha256"], prior["client_verified"] = actual, False
        prior["resource_files"] = len(after.splitlines())
        receipt.write_text(json.dumps(prior, indent=2), encoding="utf-8")
        print("Adapter upgrade verified", flush=True)
        return
    if exists(SOURCE):
        if exists(BACKUP):
            raise RuntimeError("Both resource paths exist; reconcile them before installing")
        before = inventory(SOURCE)
        # Several manifest entries share packed bundles. Their count is not a
        # file-count contract; the exact inventory is retained and checked below.
        if INDEX not in before or len(before.splitlines()) < 1000:
            raise RuntimeError("Resource inventory appears incomplete")
        record.write_text(before, encoding="utf-8")
        command("shell", "mkdir", "-p", "/sdcard/TerraLocal-backup")
        command("shell", "mv", SOURCE, BACKUP)
    elif not exists(BACKUP) or not record.exists():
        raise RuntimeError("No verified resource backup is available")
    before = record.read_text(encoding="utf-8")
    expected = sorted(line.replace(SOURCE, BACKUP, 1) for line in before.splitlines())
    if sorted(inventory(BACKUP).splitlines()) != expected:
        raise RuntimeError("Resource backup inventory differs; app was not uninstalled")
    print(f"Verified resource backup: {len(expected)} files", flush=True)
    if PACKAGE in command("shell", "pm", "list", "packages", PACKAGE):
        if command("uninstall", PACKAGE) != "Success":
            raise RuntimeError("Test package uninstall failed; resource backup is retained")
    print("Installing the local APK adapter on the isolated test instance", flush=True)
    print(install_candidate(apk, actual), flush=True)
    command("shell", "mkdir", "-p", f"/sdcard/Android/data/{PACKAGE}/files")
    if exists(SOURCE):
        raise RuntimeError("A new Bundles path already exists; backup is retained")
    command("shell", "mv", BACKUP, SOURCE)
    if sorted(inventory(SOURCE).splitlines()) != sorted(before.splitlines()):
        raise RuntimeError("Installed resource inventory differs")
    receipt.write_text(json.dumps(
        {"instance": 1, "name": "TerraLocal", "serial": SERIAL, "apk_sha256": actual,
         "resource_files": len(expected), "resource_manifest": INDEX,
         "official_authentication_copied": False, "client_verified": False}, indent=2), encoding="utf-8")
    print("Adapter installed; resource filenames and sizes are unchanged", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Test preparation failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
