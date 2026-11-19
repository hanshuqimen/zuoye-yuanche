"""Temporary diagnostics for the isolated test instance, separate from the server."""

import argparse
import json
import subprocess
import time
from pathlib import Path

import frida

PACKAGE = "com.hypergryph.arknights"
APK_HASH = "0b79b85383e21a6343283bc6bfd7a9d24eb4134abf901115f757da6a5d50f6db"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("script", type=Path)
    parser.add_argument("--seconds", type=float, default=10)
    args = parser.parse_args()
    adb = Path("<emulator-directory>/adb.exe")
    base = [str(adb), "-s", "test-transport-example", "shell"]
    if subprocess.check_output([*base, "getprop", "ro.serialno"], text=True).strip() != "test-device-example":
        raise RuntimeError("Refusing to attach: emulator identity differs")
    pid = int(subprocess.check_output([*base, "pidof", PACKAGE], text=True).strip())
    identity = subprocess.check_output([*base, "cat", f"/proc/{pid}/cmdline"])
    if identity.split(b"\x00", 1)[0] != PACKAGE.encode():
        raise RuntimeError("Refusing to attach: process identity differs")
    print(json.dumps({"target": PACKAGE, "test_device": "test-transport-example", "pid": pid}))
    device = frida.get_device_manager().add_remote_device("127.0.0.1:27043")
    session = device.attach(pid)
    bridge = Path(frida.__file__).parent.parent / "frida_tools" / "bridges" / "java.js"
    source = bridge.read_text("utf-8") + "\nglobalThis.Java = bridge;\n" + args.script.read_text("utf-8")
    script = session.create_script(source)
    script.on("message", lambda message, data: print(json.dumps(message, ensure_ascii=False), flush=True))
    try:
        script.load()
        time.sleep(min(max(args.seconds, 1), 60))
    finally:
        session.detach()


if __name__ == "__main__":
    main()
