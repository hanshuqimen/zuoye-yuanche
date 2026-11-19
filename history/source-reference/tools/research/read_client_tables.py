"""Read only named static IL2CPP tables from the owned test client's ELF mapping.

The protected APK's on-disk method-spec table and some module names differ from
the loaded image. This reads known registration tables in bounded 64 KiB chunks,
never anonymous mappings, player objects, SDK files or authentication state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from inspect_client_native_types import ELF_HASH, METADATA_HASH, NativeTypes

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache/client-metadata"
sys.path.insert(0, str(ROOT / "tools/client"))
from connect_test_instance import adb, root  # noqa: E402


def capture(generic: bool):
    native = NativeTypes(CACHE / "libil2cpp.so", ROOT / "data/research/cached-global-metadata.dat")
    receipt = json.loads((ROOT / "data/client/test-instance/installation.json").read_bytes())
    if receipt["instance"] != 1 or receipt["serial"] != "test-transport-example":
        raise ValueError("Isolated installation receipt differs")
    if adb("shell", "getprop", "ro.serialno") != "test-device-example":
        raise ValueError("Test device identity differs")
    pids = adb("shell", "pidof", "com.hypergryph.arknights").split()
    if len(pids) != 1 or not pids[0].isdigit():
        raise ValueError("Expected one test game process")
    pid = pids[0]
    if adb("shell", "cat", f"/proc/{pid}/cmdline").split("\0")[0] != "com.hypergryph.arknights":
        raise ValueError("Process identity differs")
    segment = native.segments[0]
    if segment[2] or segment[3] or segment[1] != 5:
        raise ValueError("Frozen first ELF segment differs")
    expected_size = (segment[5] + 4095) // 4096 * 4096
    mappings = []
    for row in root(f"cat /proc/{pid}/maps").splitlines():
        parts = row.split()
        if (len(parts) >= 6 and parts[-1].endswith("/lib/arm64/libil2cpp.so") and
                parts[1] == "r--p" and parts[2] == "00000000"):
            begin, end = [int(v, 16) for v in parts[0].split("-")]
            if end - begin == expected_size:
                mappings.append((begin, parts[-1]))
    if len(mappings) != 1:
        raise ValueError("Loaded file-backed text and read-only data mapping is ambiguous")
    begin, image_path = mappings[0]
    if not re.fullmatch(r"/data/app/[A-Za-z0-9._=-]+/lib/arm64/libil2cpp\.so", image_path):
        raise ValueError("Unexpected installed ELF path")
    if root(f"sha256sum {image_path}").split()[0] != ELF_HASH:
        raise ValueError("Installed ELF differs from the frozen official image")
    registration = native.read(0xBE31388, "<16Q")
    code = native.read(0xBAD2390, "<15Q")
    if code[13] != 88 or registration[8] != 290772 or registration[4] != 210466:
        raise ValueError("Static registration counts differ")
    pages = set()
    for module in native.read(code[14], "<88Q"):
        name, _, _ = native.read(module, "<3Q")
        pages.update(range(name // 4096 * 4096, (name + 512 + 4095) // 4096 * 4096, 4096))
    if generic:
        for address, length in ((registration[9], registration[8] * 12),
                                (registration[5], registration[4] * 16)):
            pages.update(range(address // 4096 * 4096, (address + length + 4095) // 4096 * 4096, 4096))
    if not pages or max(pages) + 4096 > segment[5] or min(pages) < 4096:
        raise ValueError("Named tables exceed the frozen file-backed segment")
    chunks = []
    for page in sorted(pages):
        if chunks and page == chunks[-1][1] and page + 4096 - chunks[-1][0] <= 65536:
            chunks[-1][1] = page + 4096
        else:
            chunks.append([page, page + 4096])
    directory = CACHE / "loaded-tables"
    directory.mkdir(parents=True, exist_ok=True)
    report = {"elf_sha256": ELF_HASH, "metadata_sha256": METADATA_HASH,
              "instance": 1, "source": "known static tables in loaded file-backed ELF only",
              "generic_tables": generic, "slices": []}
    guest = "/data/local/tmp/terralocal-static-table.bin"
    for number, (start, end) in enumerate(chunks, 1):
        path = directory / f"{start:08x}-{end:08x}.bin"
        root(f"dd if=/proc/{pid}/mem of={guest} bs=4096 skip={(begin+start)//4096} count={(end-start)//4096}")
        root(f"chmod 644 {guest}")
        adb("pull", guest, str(path))
        body = path.read_bytes()
        if len(body) != end - start:
            raise ValueError("Static table read was incomplete")
        report["slices"].append({"rva": start, "bytes": len(body), "file": path.name,
                                 "sha256": hashlib.sha256(body).hexdigest()})
        if number % 20 == 0 or number == len(chunks):
            print(f"Static table slices: {number}/{len(chunks)}", flush=True)
    (directory / "receipt.json").write_text(json.dumps(report, indent=2), "utf-8")
    return {"slices": len(chunks), "bytes": sum(item["bytes"] for item in report["slices"]),
            "generic_tables": generic, "receipt": str(directory / "receipt.json")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generic", action="store_true", help="Include the method-spec and generic-function tables")
    args = parser.parse_args()
    print(json.dumps(capture(args.generic), ensure_ascii=False))
