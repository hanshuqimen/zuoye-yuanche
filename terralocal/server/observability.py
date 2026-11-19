"""Metadata-only protocol observation. No request values or secret headers are persisted."""

from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock


def schema(value, depth: int = 0):
    if depth > 6:
        return "nested"
    if isinstance(value, dict):
        return {str(k)[:96]: schema(v, depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, list):
        return {"type": "array", "items": schema(value[0], depth + 1) if value else "unknown"}
    return "null" if value is None else type(value).__name__


class RequestLog:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.recent = deque(maxlen=200)
        self._lock = Lock()
        self._failed_files: set[str] = set()
        self._failure_count = 0
        self._last_failure_at: str | None = None

    def append(self, entry: dict, *, unknown: bool = False) -> None:
        entry = {"timestamp": datetime.now(UTC).isoformat(), **entry}
        filename = "unknown-routes.jsonl" if unknown else "requests.jsonl"
        serialized = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            # A diagnostic file failure must not change a committed command's
            # HTTP response. Keep bounded observations even during an outage.
            self.recent.append(entry)
            try:
                with (self.directory / filename).open("a", encoding="utf-8") as stream:
                    stream.write(serialized)
            except OSError:
                self._failed_files.add(filename)
                self._failure_count += 1
                self._last_failure_at = entry["timestamp"]
            else:
                self._failed_files.discard(filename)

    def snapshot(self) -> list:
        with self._lock:
            return list(self.recent)[::-1]

    def status(self) -> dict:
        with self._lock:
            return {"fileLoggingAvailable": not self._failed_files,
                    "failedFiles": sorted(self._failed_files), "failureCount": self._failure_count,
                    "lastFailureAt": self._last_failure_at}
