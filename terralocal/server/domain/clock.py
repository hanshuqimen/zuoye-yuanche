from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone

from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence.models import ServerClockState

# Frozen client DateTime uses UTC+8; the last valid local second is
# 9999-12-31 23:59:59. Epoch arithmetic avoids Windows CRT timestamp limits.
MAX_TIMESTAMP = 253_402_271_999
CN_EPOCH = datetime(1970, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))


def _validate(timestamp: int, *, saved: bool = False) -> int:
    if type(timestamp) is not int or not 0 <= timestamp <= MAX_TIMESTAMP:
        raise DomainError("INVALID_CLOCK_STATE" if saved else "INVALID_CLOCK",
                          "服务器时间超出客户端支持范围，请调整时间设置", 503 if saved else 400)
    return timestamp


class ServerClock:
    def __init__(self, state: ServerClockState, real_now=None):
        self.state = state
        self._real_now = real_now or time.time

    def now(self) -> int:
        if self.state.mode == "fixed":
            return _validate(self.state.fixed_at, saved=True)
        if self.state.mode not in {"realtime", "offset"} or type(self.state.offset) is not int:
            raise DomainError("INVALID_CLOCK_STATE", "存档中的时间模式无效，请调整时间设置", 503)
        return _validate(self._wall_time() + (self.state.offset if self.state.mode == "offset" else 0), saved=True)

    def _wall_time(self) -> int:
        value = self._real_now()
        if type(value) not in {int, float} or type(value) is float and not math.isfinite(value):
            raise DomainError("INVALID_CLOCK_STATE", "本机时间无效，请检查系统时间", 503)
        return _validate(int(value), saved=True)

    def configure(self, mode: str, value: int = 0) -> None:
        if mode not in {"realtime", "fixed", "offset"} or type(value) is not int:
            raise DomainError("INVALID_CLOCK", "时间模式必须为 realtime、fixed 或 offset")
        timestamp = value if mode == "fixed" else self._wall_time() + (value if mode == "offset" else 0)
        _validate(timestamp)
        # Validate the same calendar projections used by refresh before any
        # persistent field changes. Old invalid settings remain repairable.
        for kind in ("daily", "weekly", "monthly"):
            self.period(kind, at=timestamp)
        self.state.mode = mode
        self.state.fixed_at = value if mode == "fixed" else None
        self.state.offset = value if mode == "offset" else 0

    def period(self, kind: str, *, at: int | None = None) -> str:
        # CN daily boundary is 04:00. UTC+8 needs no Windows tzdata package.
        timestamp = self.now() if at is None else _validate(at)
        date = CN_EPOCH + timedelta(seconds=timestamp) - timedelta(hours=4)
        if kind == "daily":
            return date.strftime("%Y-%m-%d")
        if kind == "weekly":
            return (date - timedelta(days=date.weekday())).strftime("%Y-%m-%d")
        if kind == "monthly":
            return date.strftime("%Y-%m")
        return "permanent"
