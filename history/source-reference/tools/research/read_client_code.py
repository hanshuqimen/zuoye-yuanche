"""Read a bounded code range of the owned, frozen client on test instance 1.

The protected ELF's selected method bodies differ after loading. Read only its
file-backed first PT_LOAD mapping; never read anonymous memory, player objects,
credentials or another process. Outputs stay in the workspace research cache.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from inspect_client_native_types import NativeTypes

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/client"))
from connect_test_instance import adb, root  # noqa: E402


def read_code(rva: int, size: int, output: Path) -> dict:
    if not 1 <= size <= 65536:
        raise ValueError("Code reads are limited to 64 KiB")
    output = output.resolve()
    cache = (ROOT / ".cache/client-metadata").resolve()
    if not output.is_relative_to(cache):
        raise ValueError("Code output must stay in the private workspace cache")
    native = NativeTypes(cache / "libil2cpp.so", ROOT / "data/research/cached-global-metadata.dat")
    segment = native.segments[0]
    if segment[2] != 0 or segment[3] != 0 or segment[1] != 5:
        raise ValueError("Frozen first code segment differs")
    start, end = rva // 4096 * 4096, (rva + size + 4095) // 4096 * 4096
    if end - start > 65536:
        raise ValueError("The page-aligned code read exceeds 64 KiB")
    if not 4096 <= start < end <= segment[5]:
        raise ValueError("Requested code exceeds the frozen file-backed text segment")
    receipt = json.loads((ROOT / "data/client/test-instance/installation.json").read_bytes())
    if receipt["instance"] != 1 or receipt["serial"] != "test-transport-example":
        raise ValueError("Isolated installation receipt is missing")
    if adb("shell", "getprop", "ro.serialno") != "test-device-example":
        raise ValueError("Test device identity differs")
    pid = adb("shell", "pidof", "com.hypergryph.arknights").split()
    if len(pid) != 1 or not pid[0].isdigit():
        raise ValueError("Expected exactly one test game process")
    pid = pid[0]
    if adb("shell", "cat", f"/proc/{pid}/cmdline").split("\0")[0] != "com.hypergryph.arknights":
        raise ValueError("Process identity differs")
    expected_size = (segment[5] + 4095) // 4096 * 4096
    mappings = []
    for row in root(f"cat /proc/{pid}/maps").splitlines():
        parts = row.split()
        if (len(parts) >= 6 and parts[-1].endswith("/lib/arm64/libil2cpp.so") and
                parts[1] == "r--p" and parts[2] == "00000000"):
            begin, limit = [int(value, 16) for value in parts[0].split("-")]
            if limit - begin == expected_size:
                mappings.append((begin, limit))
    if len(mappings) != 1:
        raise ValueError("Loaded first code segment is ambiguous")
    begin, limit = mappings[0]
    if begin + end > limit:
        raise ValueError("Requested code exceeds the loaded file-backed mapping")
    guest = "/data/local/tmp/terralocal-method-code.bin"
    root(f"dd if=/proc/{pid}/mem of={guest} bs=4096 skip={(begin + start) // 4096} count={(end-start) // 4096}")
    root(f"chmod 644 {guest}")
    output.parent.mkdir(parents=True, exist_ok=True)
    adb("pull", guest, str(output))
    body = output.read_bytes()
    if len(body) != end - start:
        raise ValueError("Bounded code read was incomplete")
    report = {"process": "com.hypergryph.arknights", "instance": 1, "rva": rva, "size": size,
              "file_start_rva": start, "file_size": len(body), "sha256": hashlib.sha256(body).hexdigest(),
              "source": "loaded file-backed ARM64 code only"}
    output.with_suffix(".json").write_text(json.dumps(report, indent=2), "utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rva", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--size", type=lambda value: int(value, 0), default=4096)
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/client-metadata/loaded-code.bin")
    args = parser.parse_args()
    print(json.dumps(read_code(args.rva, args.size, args.output)))
