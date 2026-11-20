"""Select REA's authenticated loopback transport for workspace-only WSL runs.

Check by default; --apply requires idle REA providers and preserves the original
third-party file. Unknown installed versions are rejected without mutation.
No authentication, permissions or bridge implementation is changed.
"""

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BEFORE = "68d0d0d1de1bb7142d84a6b80fbb6c1d54d983c32dc687e59b24a747ada7fde5"
AFTER = "616a25afb1dbb43e754bc7c73184d59a2ade8b4b8d59a5d78f3e0840a19346b9"
ORIGINAL = (b'transport: installation.platform === "win32"\n'
            b'            ? "authenticated-loopback-tcp"\n'
            b'            : "unix-socket",')


def configure(apply=False):
    path = ROOT / "tools/local/rea/node_modules/rea-agents/dist/ghidra/GhidraProviderClient.js"
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
        raise ValueError("REA provider path must be a regular file inside this project")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest not in (BEFORE, AFTER):
        raise ValueError("Unrecognized REA provider version; original file was not changed")
    result = {"configured": digest == AFTER, "changed": False, "sha256": digest,
              "target_transport": "authenticated-loopback-tcp", "bind_host": "127.0.0.1",
              "required_runtime_parent": "tools/local/rea-tmp", "requires_idle_providers_to_apply": True}
    if apply and digest == BEFORE:
        if raw.count(ORIGINAL) != 1:
            raise ValueError("REA transport selector did not match the verified version")
        updated = raw.replace(ORIGINAL, b'transport: "authenticated-loopback-tcp",')
        if hashlib.sha256(updated).hexdigest() != AFTER:
            raise ValueError("REA transport configuration fingerprint differs")
        name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        backup = ROOT / ".cache/rea-transport" / name
        backup.mkdir(parents=True, exist_ok=False)
        with (backup / "GhidraProviderClient.js.original").open("xb") as file:
            file.write(raw)
        pending = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
        with pending.open("xb") as file:
            file.write(updated)
        if path.read_bytes() != raw:
            raise ValueError("REA provider changed during preparation; original and pending files retained")
        os.replace(pending, path)
        result.update(configured=True, changed=True, sha256=AFTER, backup=str(backup.relative_to(ROOT)))
        (backup / "configuration.json").write_text(json.dumps(result, indent=2) + "\n", "utf8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply to the verified idle local REA installation")
    args = parser.parse_args()
    try:
        print(json.dumps(configure(args.apply), ensure_ascii=False))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
