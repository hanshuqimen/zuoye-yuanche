"""Restore missing bundles from verified local archives on the dedicated test guest."""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
import zipfile

from prepare_resources import inventory, load_settings, resource_entries, verify_archive
from prepare_test_instance import CONSOLE, PACKAGE, ROOT, SOURCE, command


def main() -> None:
    listing = subprocess.run([str(CONSOLE), "list2"], capture_output=True, check=True).stdout.decode(
        "utf-8", "replace").splitlines()
    if not any(row.startswith("1,TerraLocal,") and row.split(",")[4] == "1" for row in listing):
        raise RuntimeError("Dedicated test instance is not running")
    if command("shell", "getprop", "ro.serialno") != "test-device-example":
        raise RuntimeError("Unexpected emulator identity")
    if command("shell", "cat", "/mnt/shared/Applications/terralocal-test-marker.txt").strip() != (
            "TerraLocal index 1 workspace share"):
        raise RuntimeError("Workspace share is not bound to this test instance")
    command("shell", "am", "force-stop", PACKAGE)
    records = ROOT / "data/client/test-instance"
    from prepare_test_instance import inventory as guest_inventory

    current_path = records / "resources-before-repair.txt"
    current_path.write_text(guest_inventory(SOURCE), "utf-8")
    before = inventory(records / "resources-before.txt")
    after = inventory(current_path)
    if (set(after) - set(before) or any(after[n] != before[n] for n in after
                                      if n != "persistent_res_list.json")):
        raise RuntimeError("Unexpected resource modifications; no files were repaired")
    settings = load_settings(ROOT / "data")
    from terralocal.server.protocol.bootstrap import Bootstrap

    profile = Bootstrap(settings).profile()
    cache = settings.data_dir / "client/assets" / profile.resource_version
    manifest = json.loads((cache / "hot_update_list.json").read_bytes())
    entries = {e["name"]: (name, e) for name, e in resource_entries(manifest).items()}
    missing = sorted(set(before) - set(after))
    stage = ROOT / ".cache/emulator-share/Misc/resource-repair"
    stage.mkdir(parents=True, exist_ok=True)
    script = ["#!/system/bin/sh", "set -e"]
    staged = []
    for name in missing:
        filename, entry = entries[name]
        if entry["abSize"] != before[name]:
            raise RuntimeError("The frozen manifest does not match the preserved inventory")
        archive = cache / filename
        verify_archive(archive, entry)
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as source, source.open(name) as raw, target.open("wb") as output:
            shutil.copyfileobj(raw, output)
        destination = f"{SOURCE}/{name}"
        shared = f"/mnt/shared/Misc/resource-repair/{name}"
        parent = destination.rsplit("/", 1)[0]
        script += [f"mkdir -p {shlex.quote(parent)}",
                   f"cp {shlex.quote(shared)} {shlex.quote(destination + '.terralocal-tmp')}",
                   f"test $(md5sum {shlex.quote(destination + '.terralocal-tmp')} | cut -d' ' -f1) = {entry['md5']}",
                   f"mv {shlex.quote(destination + '.terralocal-tmp')} {shlex.quote(destination)}"]
        staged.append(target)
    current_manifest = records / "persistent-res-current.json"
    command("pull", f"{SOURCE}/persistent_res_list.json", str(current_manifest))
    persistent = json.loads(current_manifest.read_bytes())
    known = {e["name"] for e in persistent["abInfos"]} | set(missing)
    persistent["abInfos"] = [e for e in manifest["abInfos"] if e["name"] in known]
    body = json.dumps(persistent, separators=(",", ":")).encode()
    if len(body) != before["persistent_res_list.json"]:
        raise RuntimeError("Reconstructed manifest differs from preserved inventory")
    manifest_stage = stage / "persistent_res_list.json"
    manifest_stage.write_bytes(body)
    script += [f"cp /mnt/shared/Misc/resource-repair/persistent_res_list.json {SOURCE}/persistent_res_list.json"]
    path = records / "repair-resources.sh"
    path.write_text("\n".join(script) + "\n", "utf-8", newline="\n")
    command("push", str(path), "/data/local/tmp/terralocal-repair-resources.sh")
    print(f"Restoring {len(missing)} verified bundles", flush=True)
    command("shell", "sh", "/data/local/tmp/terralocal-repair-resources.sh")
    verified = guest_inventory(SOURCE)
    if sorted(verified.splitlines()) != sorted((records / "resources-before.txt").read_text().splitlines()):
        raise RuntimeError("Final resource inventory differs; repair staging retained")
    (records / "resources-after-repair.txt").write_text(verified, "utf-8")
    (records / "resource-repair.json").write_text(json.dumps({
        "restored_count": len(missing), "restored": missing,
        "manifest_sha256": hashlib.sha256(body).hexdigest(), "file_inventory_matches_original": True,
        "restored_bundle_checksums_verified": True}, indent=2), "utf-8")
    for path in [*staged, manifest_stage]:
        path.unlink()
    print("Restored bundle MD5s and complete resource inventory verified", flush=True)


if __name__ == "__main__":
    main()
