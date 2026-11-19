"""Inspect error logging in the owned, isolated 2.7.71 test process.

Read only: verified class metadata and bounded logging configuration fields.
Reads class metadata to verify the target, never player objects or credentials.
Collection emits only exception types, method names and validated JSON paths.
The original APK and files are untouched. Restart also discards these switches.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

from inspect_client_native_types import ELF_HASH, NativeTypes

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache/client-metadata"
sys.path.insert(0, str(ROOT / "tools/client"))
from connect_test_instance import ADB, SERIAL, adb, root  # noqa: E402

SLOT = 0xC0FC480  # DLog TypeInfo, independently referenced by SetLogLevel and LogError.


class Target:
    def __init__(self):
        routing = json.loads((ROOT / "data/client/test-instance/routing.json").read_bytes())
        if routing["instance"] != 1 or routing["serial"] != SERIAL or routing.get("host_game_port") != 18443:
            raise ValueError("Error logging is restricted to the isolated diagnostic listener")
        if adb("shell", "getprop", "ro.serialno") != "test-device-example":
            raise ValueError("Test device identity differs")
        self.pid = adb("shell", "pidof", "com.hypergryph.arknights")
        if not self.pid.isdecimal():
            raise ValueError("Expected one test game process")
        if adb("shell", "cat", f"/proc/{self.pid}/cmdline").split("\0")[0] != "com.hypergryph.arknights":
            raise ValueError("Process identity differs")
        self.start_ticks = root(f"cat /proc/{self.pid}/stat").split(")", 1)[1].split()[19]
        self.maps = []
        for row in root(f"cat /proc/{self.pid}/maps").splitlines():
            p = row.split()
            begin, end = [int(v, 16) for v in p[0].split("-")]
            self.maps.append((begin, end, p[1], p[-1] if len(p) >= 6 else "", int(p[2], 16)))
        native = NativeTypes(CACHE / "libil2cpp.so", ROOT / "data/research/cached-global-metadata.dat")
        expected = (native.segments[0][5] + 4095) // 4096 * 4096
        images = [m for m in self.maps if m[3].endswith("/lib/arm64/libil2cpp.so")
                  and m[2] == "r--p" and m[4] == 0 and m[1] - m[0] == expected]
        if len(images) != 1:
            raise ValueError("Loaded frozen ELF is ambiguous")
        self.base, _, _, image, _ = images[0]
        if not re.fullmatch(r"/data/app/[A-Za-z0-9._=-]+/lib/arm64/libil2cpp\.so", image):
            raise ValueError("Unexpected installed ELF path")
        if root(f"sha256sum {image}").split()[0] != ELF_HASH:
            raise ValueError("Installed ELF differs")
        self.mapping(self.base + SLOT, 8, image=image)
        # The ADRP/LDR operand addresses a GOT entry containing the address of
        # the TypeInfo variable; the method then dereferences that variable.
        type_info_slot = self.pointer(self.base + SLOT)
        if not any(self.base + s[3] <= type_info_slot < type_info_slot + 8 <= self.base + s[3] + s[6]
                   for s in native.segments):
            raise ValueError("DLog TypeInfo slot is outside the frozen ELF image")
        klass = self.pointer(type_info_slot)
        name, namespace = struct.unpack("<2Q", self.read(klass + 0x10, 16))
        if self.read(name, 5) != b"DLog\0" or self.read(namespace, 12) != b"UnityEngine\0":
            raise ValueError("The resolved class is not UnityEngine.DLog")
        statics = self.pointer(klass + 0xB8)
        self.level, self.channels = statics + 0x18, statics + 0x20
        self.mapping(self.level, 4)
        self.mapping(self.channels, 4)
        if self.value(self.level) & ~15:
            raise ValueError("Unexpected logging-level layout")

    def mapping(self, address, length, *, writable=False, image=None):
        matches = [m for m in self.maps if m[0] <= address < address + length <= m[1]
                   and "r" in m[2] and (not writable or "w" in m[2]) and (image is None or m[3] == image)]
        if len(matches) != 1:
            raise ValueError("The bounded metadata/diagnostic field is not in the expected mapping")

    def read(self, address, length):
        if not 1 <= length <= 16:
            raise ValueError("Diagnostic reads are bounded to 16 bytes")
        self.mapping(address, length)
        guest = "/data/local/tmp/terralocal-logger-field.bin"
        path = CACHE / "logger-field.bin"
        root(f"dd if=/proc/{self.pid}/mem of={guest} bs=1 skip={address} count={length}")
        root(f"chmod 644 {guest}")
        adb("pull", guest, str(path))
        body = path.read_bytes()
        if len(body) != length:
            raise ValueError("Diagnostic field read was incomplete")
        return body

    def pointer(self, address):
        return struct.unpack("<Q", self.read(address, 8))[0]

    def value(self, address):
        return struct.unpack("<I", self.read(address, 4))[0]







def class_name(target, klass):
    name, namespace = struct.unpack("<2Q", target.read(klass + 0x10, 16))
    def identifier(address):
        body = bytearray()
        for offset in range(0, 128, 16):
            chunk = target.read(address + offset, 16)
            body.extend(chunk.split(b"\0", 1)[0])
            if b"\0" in chunk:
                value = body.decode("ascii")
                if not re.fullmatch(r"[A-Za-z0-9_.+<>]*", value):
                    raise ValueError("Unexpected logging class identifier")
                return value
        raise ValueError("Unterminated logging class identifier")
    return identifier(namespace) + "." + identifier(name)


def inspect():
    target = Target()
    statics = target.level - 0x18
    default = target.pointer(statics + 8)
    console = target.pointer(statics)
    debug = target.pointer(target.pointer(target.base + 0xC095608))
    if class_name(target, debug) != "UnityEngine.Debug":
        raise ValueError("Unexpected Unity Debug class")
    logger = target.pointer(target.pointer(debug + 0xB8) + 8)
    if not logger or class_name(target, target.pointer(logger)) != "UnityEngine.Logger":
        raise ValueError("Unexpected Unity logger")
    enabled = target.read(logger + 24, 1)[0]
    filter_type = target.value(logger + 28)
    if enabled not in (0, 1) or filter_type > 4:
        raise ValueError("Unexpected Unity logger configuration")
    return {"pid": int(target.pid), "level": target.value(target.level),
            "default_channel_enabled": bool(target.value(target.channels) & 1),
            "default_logger_class": class_name(target, target.pointer(default)) if default else None,
            "console_logger_class": class_name(target, target.pointer(console)) if console else None,
            "unity": {"enabled": bool(enabled), "filter_log_type": filter_type}}


def collect():
    target = Target()
    raw = subprocess.run([str(ADB), "-s", SERIAL, "logcat", "--pid=" + target.pid, "-d", "-v", "brief"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
    types = collections.Counter(re.findall(r"\b[A-Za-z_][A-Za-z0-9_.]*Exception\b", raw))
    paths = collections.Counter(p for p in re.findall(r"\bPath '([^']{1,160})'", raw)
                                if re.fullmatch(r"[A-Za-z0-9_.\[\]]+", p))
    names = sorted(set(re.findall(r"\b(?:Torappu|Newtonsoft)\.[A-Za-z0-9_.+`<>]+", raw)))
    report = {"pid": int(target.pid), "log_line_count": len(raw.splitlines()),
              "exception_type_counts": dict(types), "json_path_counts": dict(paths), "method_names": names[:80],
              "lua_nil_errors": raw.count("attempt to index a nil value")}
    filename = CACHE / f"error-types-{target.pid}.json"
    filename.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report | {"report_sha256": hashlib.sha256(filename.read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "collect"))
    arguments = parser.parse_args()
    print(json.dumps({"inspect": inspect, "collect": collect}[arguments.action](), indent=2))
