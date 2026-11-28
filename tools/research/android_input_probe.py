"""Passive touch-driver counters for an already admitted, leased QA transport.

This module does not launch or instrument the client, generate inputs, borrow
ADB credentials, or create an ADB server. A positive UI click control is needed
before interpreting these counters as evidence about this emulator's inputs.
On the frozen LDPlayer 9 / Android 9 QA image, a successful UI click produced
zero event2 records. These kernel counters therefore remain unvalidated for
that input path and cannot diagnose failed Unity gestures.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COUNTERS = ("syn_reports", "x_records", "y_records", "contact_starts", "contact_ends")
SCRIPT = r'''#!/system/bin/sh
[ "$(getprop ro.serialno)" = "0063090c" ] || exit 97
[ -c /dev/input/event2 ] || exit 98
{
  timeout -k 1 5 getevent -l /dev/input/event2 2>/dev/null
  printf '\nTL_INPUT_PRODUCER_STATUS %s\n' "$?"
} | awk '
/EV_SYN[[:space:]]+SYN_REPORT/ { reports++ }
/EV_ABS[[:space:]]+ABS_MT_POSITION_X/ { xrecords++ }
/EV_ABS[[:space:]]+ABS_MT_POSITION_Y/ { yrecords++ }
/EV_ABS[[:space:]]+ABS_MT_TRACKING_ID/ {
  if ($NF == "ffffffff") ends++; else starts++
}
/^TL_INPUT_PRODUCER_STATUS [0-9]+$/ { status=$2; markers++ }
END {
  printf "{\"syn_reports\":%d,\"x_records\":%d,\"y_records\":%d,\"contact_starts\":%d,\"contact_ends\":%d,\"producer_status\":%d,\"status_markers\":%d}\n", reports,xrecords,yrecords,starts,ends,status,markers
}'
'''


class InputProbeError(ValueError):
    """A probe refusal or failed sample, never evidence of zero game events."""


def parse_counts(raw: str, *, expected_status: int = 124) -> dict:
    """Reject missing producer status, early exit, and malformed counter output."""
    # GNU timeout uses 124; this frozen LDPlayer's timeout was measured as 142.
    # The caller must select the result of a separate bounded calibration.
    if type(expected_status) is not int or expected_status not in {124, 142}:
        raise InputProbeError("Unsupported calibrated timeout status")
    if not isinstance(raw, str) or len(raw) > 4096:
        raise InputProbeError("Invalid counter output size")
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise InputProbeError("Counter output is not a JSON object") from None
    if not isinstance(value, dict) or set(value) != {*COUNTERS, "producer_status", "status_markers"}:
        raise InputProbeError("Counter output fields differ")
    if any(type(value[key]) is not int or not 0 <= value[key] <= 100_000 for key in COUNTERS):
        raise InputProbeError("Invalid touch record counter")
    if type(value["status_markers"]) is not int or value["status_markers"] != 1:
        raise InputProbeError("Producer completion is missing or ambiguous")
    if type(value["producer_status"]) is not int or value["producer_status"] != expected_status:
        raise InputProbeError("Producer did not reach its bounded capture deadline")
    return value


class PassiveTouchProbe:
    """Use the owning controller's existing transport and retain only counts."""

    def __init__(self, transport, output: Path):
        self.transport = transport
        self.output = output.resolve()
        if not self.output.is_relative_to(ROOT / ".cache") or not self.output.is_dir():
            raise InputProbeError("Use an existing project-local .cache output directory")
        self.guest = "/data/local/tmp/terralocal-input-probe-" + secrets.token_hex(6) + ".sh"
        self.deployed = False
        self.boot_id = None
        self.timeout_status = None
        self.timeout_calibration = None

    def _identity(self):
        if self.transport.lease.handle is None or self.transport.settings.emulator_index != 1:
            raise InputProbeError("Only an already leased index1 controller can prepare this probe")
        self.transport.validate_configuration()
        identity = self.transport.identify()
        if self.boot_id is not None and identity.boot_id != self.boot_id:
            raise InputProbeError("Emulator boot identity changed")
        return identity

    def prepare(self) -> dict:
        if self.deployed:
            raise InputProbeError("Keep the existing deployment receipt; do not prepare twice")
        identity = self._identity()
        if not self.transport.routes_ready(identity):
            raise InputProbeError("Existing TLS and offline routing admission is not ready")
        sdk = self.transport.command("shell", "getprop", "ro.build.version.sdk")
        abi = self.transport.command("shell", "getprop", "ro.product.cpu.abi")
        if (sdk, abi) != ("28", "x86_64"):
            raise InputProbeError("This probe's hardware contract is Android 9 x86_64 only")
        devices = self.transport.root("cat /proc/bus/input/devices") or ""
        if not any('N: Name="input"' in item and re.search(r"\bevent2\b", item)
                   and "B: ABS=660800000000000" in item for item in devices.split("\n\n")):
            raise InputProbeError("Touch-driver capability differs from the admitted emulator")
        for command in ("awk", "timeout", "getevent"):
            if not self.transport.root("command -v " + command, probe=True):
                raise InputProbeError("A required bounded counter command is unavailable")
        calibration_start = time.monotonic()
        deadline_status = self.transport.root('timeout -k 1 1 sleep 3; printf "%s" "$?"') or ""
        calibration_seconds = time.monotonic() - calibration_start
        self.timeout_calibration = {"status": deadline_status if deadline_status.isdecimal() else None,
                                    "elapsed_seconds": calibration_seconds}
        if deadline_status not in {"124", "142"} or not 0.8 <= calibration_seconds <= 3:
            raise InputProbeError("The device timeout command has an unsupported exit contract")
        self.timeout_status = int(deadline_status)
        if self.transport.root("test ! -e " + self.guest, probe=True) is None:
            raise InputProbeError("Preserve the existing guest file")
        host = self.output / "touch-counts.sh"
        with host.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(SCRIPT)
        digest = hashlib.sha256(host.read_bytes()).hexdigest()
        self.transport.command("push", str(host), self.guest)
        if (self.transport.root("sha256sum " + self.guest) or "").split()[:1] != [digest]:
            raise InputProbeError("Guest counter script differs")
        self.deployed, self.boot_id = True, identity.boot_id
        return {"guest_script": self.guest, "script_sha256": digest, "deployed_and_sha_verified": True,
                "capture_seconds": 5, "android_command_limit_seconds": 8,
                "coordinates_or_keyboard_values_emitted": False, "client_instrumented": False,
                "timeout_calibration": self.timeout_calibration,
                "positive_click_control_required": True}

    def _game_identity(self) -> dict:
        package = "com.hypergryph.arknights"
        pid = self.transport.command("shell", "pidof", package) or ""
        if not re.fullmatch(r"[1-9][0-9]{0,9}", pid):
            raise InputProbeError("A single running game process is required")
        command = self.transport.root(f"cat /proc/{pid}/cmdline") or ""
        if command.split("\0", 1)[0] != package:
            raise InputProbeError("Game process identity differs")
        stat = self.transport.root(f"cat /proc/{pid}/stat") or ""
        fields = stat.rsplit(")", 1)[-1].split()
        if len(fields) < 20 or not fields[19].isdecimal():
            raise InputProbeError("Game process start time is unavailable")
        return {"pid": int(pid), "start_ticks": int(fields[19])}

    def capture(self, started=None) -> dict:
        if not self.deployed or self.timeout_status is None:
            raise InputProbeError("Prepare the existing controller's probe before capture")
        self._identity()
        game = self._game_identity()
        before = time.monotonic()
        if started is not None:
            started()
        raw = self.transport.root("sh " + self.guest) or ""
        elapsed = time.monotonic() - before
        counts = parse_counts(raw, expected_status=self.timeout_status)
        if elapsed < 4.5:
            raise InputProbeError("Counter ended before the capture interval")
        self._identity()
        if self._game_identity() != game:
            raise InputProbeError("Game process changed during the sample")
        return {"game_pid": game["pid"], "game_start_ticks": game["start_ticks"],
                "same_game_pid": True, "elapsed_seconds": elapsed,
                "counts": counts, "valid_producer_sample": True,
                "positive_click_control_verified": False, "client_input_delivery_proven": False}
