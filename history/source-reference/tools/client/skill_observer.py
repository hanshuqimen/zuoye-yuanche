"""Bounded native-QA skill taps using frozen screenshots, never battle-state edits.

Used only by an already guarded ClientConnection on the owned test instance.
Reference screenshots remain local; this tool is not a game-server dependency.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import time
from pathlib import Path

from PIL import Image

from terralocal.launcher.android import adb_environment, private_directory

NAME_ROI = (15, 188, 155, 216)
ICON_ROI = (18, 424, 68, 473)
READY_ROI = (786, 448, 889, 477)


def _pixels(frame: Image.Image, box: tuple[int, int, int, int]) -> list[tuple[int, int, int]]:
    assert frame.size == (1280, 720), "Unexpected frozen-client resolution"
    return list(frame.convert("RGB").crop(box).getdata())


def matches_selected(frame: Image.Image, reference: Image.Image) -> bool:
    """Require both the operator-name glyphs and the expected selected-skill icon."""
    actual, expected = _pixels(frame, NAME_ROI), _pixels(reference, NAME_ROI)
    white = [i for i, rgb in enumerate(expected) if min(rgb) > 210]
    dark = [i for i, rgb in enumerate(expected) if max(rgb) < 100]
    if len(white) < 20 or len(dark) < 100:
        return False
    if sum(min(actual[i]) > 185 for i in white) / len(white) < .95:
        return False
    if sum(max(actual[i]) < 135 for i in dark) / len(dark) < .85:
        return False
    actual_icon, expected_icon = _pixels(frame, ICON_ROI), _pixels(reference, ICON_ROI)
    difference = sum(abs(a - b) for left, right in zip(actual_icon, expected_icon, strict=True)
                     for a, b in zip(left, right, strict=True)) / (len(actual_icon) * 3)
    return difference < 12


def skill_ready(frame: Image.Image) -> bool:
    """Recognize the observed yellow-green READY strip; cooldown alone never authorizes a tap."""
    pixels = _pixels(frame, READY_ROI)
    return sum(red > 140 and green > 160 and blue < 135 for red, green, blue in pixels) >= 900


def perform(connection, root: Path, case: Path, *, name: str, x: int, y: int,
            reference: Path, reference_sha256: str, once_per_battle: bool = False,
            battle_fingerprint: str) -> dict:
    """Capture evidence and tap once only after independent visible-selection checks."""
    root, case, reference = root.resolve(), case.resolve(), reference.resolve()
    assert root.drive.upper() == case.drive.upper() == "D:"
    assert case.is_relative_to(root / ".cache") and reference.is_relative_to(root / ".cache")
    assert re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name)
    assert re.fullmatch(r"[a-f0-9]{64}", battle_fingerprint)
    assert type(x) is int and type(y) is int and 0 <= x < 1280 and 0 <= y < 720
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == reference_sha256
    assert connection.snapshot()["phase"] == "connected"
    transport = connection.transport
    transport.identify()
    assert transport.settings.emulator_index == 1
    history_path = case / "observed-skills.jsonl"
    history = [json.loads(line) for line in history_path.read_text("utf-8").splitlines()] if history_path.exists() else []
    number = len(history) + 1
    record = {"name": name, "battle_fingerprint": battle_fingerprint, "reference_sha256": reference_sha256,
              "operation_number": number, "android_timeout_seconds": 8, "clicked": False,
              "click_attempted": False, "once_per_battle": once_per_battle, "phase": "reserved"}

    def persist() -> None:
        with history_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record) + "\n")

    persist()  # Reserve unique screenshot names even if an Android command fails.
    if once_per_battle and any(r["name"] == name and r["battle_fingerprint"] == battle_fingerprint
                              and (r.get("click_attempted") or r["clicked"]) for r in history):
        record["result"] = "already_clicked_in_this_battle"
    else:
        def capture(label: str) -> Image.Image:
            assert transport.command("shell", "getprop", "ro.serialno") == "test-device-example"
            path = case / f"observed-skill-{number:03d}-{name}-{label}.png"
            assert not path.exists()
            result = subprocess.run(
                [str(transport.adb), *transport.adb_arguments("exec-out", "screencap", "-p")],
                capture_output=True, check=True, timeout=8,
                env=adb_environment(private_directory(transport.settings) / "adb-home"),
                creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.stdout.startswith(b"\x89PNG\r\n\x1a\n")
            path.write_bytes(result.stdout)
            record[label + "_sha256"] = hashlib.sha256(result.stdout).hexdigest()
            return Image.open(io.BytesIO(result.stdout))

        transport.command("shell", "input", "tap", str(x), str(y))
        time.sleep(.3)
        frame = capture("before")
        with Image.open(reference) as expected:
            selected = matches_selected(frame, expected)
        ready = skill_ready(frame)
        record.update(selected_verified=selected, ready_verified=ready)
        if selected and ready:
            record.update(click_attempted=True, phase="tap_intent")
            persist()  # An ambiguous timeout must never re-toggle a once-only skill.
            transport.command("shell", "input", "tap", "830", "405")
            record["clicked"] = True
            record["result"] = "visible_ready_skill_tapped_once"
        else:
            record["result"] = "selection_mismatch" if not selected else "not_ready"
        transport.command("shell", "input", "tap", "1020", "520")
        capture("after")
    record["phase"] = "completed"
    persist()
    return record
