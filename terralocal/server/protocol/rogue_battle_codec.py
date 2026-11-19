"""Bounded frozen-client rogue finish records; decoding grants no progression.

Frozen M84584 emits a BattleSnapshot with actionKill rows. Its instantiated
M77331 uses JsonConvert/UTF8/ZipUtils.Compress/Base64. Action rows preserve
order and signed coordinates: scheduler eligibility and rewards belong to the
domain, not this codec. M84585 records deaths, not every finished enemy.

The route's separate domain policy must admit outcomes and rewards; decoding
grants none. Call only after looking up the authenticated owned RogueBattle.
"""

import base64
import binascii
import hashlib
import io
import json
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass, field

from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.replays import ReplayRecord
from terralocal.server.protocol.battle_codec import (
    DecodedRogueFinish,
    FinishRequest,
    decode_rogue_payload,
    nonfinite,
    signature_battle_id,
    unique_object,
)
from terralocal.server.protocol.replay_codec import MAX_WIRE, decode_replay

# Local admission budgets; not claimed as official limits for all themes.
MAX_SNAPSHOT_WIRE = 1_000_000
MAX_SNAPSHOT_JSON = 4 * 1024 * 1024
MAX_ACTION_ROWS = 20_000
MAX_DEATHS = 100_000
CODEC = "cn-android-2.7.71-rogue-finish-records-v1"
COUNTER_CODEC = "cn-android-2.7.71-char-stat-counters-v1"
MAX_COUNTER_ROWS, MAX_COUNTER_TOTAL = 4096, 100_000
COUNTER_TYPES = frozenset({"SPAWN", "DEAD", "WITHDRAW"})


class RogueOutput(Command):
    battleSnapshot: str = Field(min_length=1, max_length=MAX_SNAPSHOT_WIRE)


class RogueFinishRequest(FinishRequest):
    # Managed reference type; absence differs from an explicit null. A domain
    # rule may require a journal. Null alone never authorizes settlement.
    battleLog: str | None = Field(min_length=1, max_length=MAX_WIRE)
    rlv2Data: RogueOutput


@dataclass(frozen=True)
class ActionDeaths:
    wave: int
    fragment: int
    action: int
    count: int


@dataclass(frozen=True)
class BattleSnapshot:
    encoded: str = field(repr=False)
    sha256: str
    actions: tuple[ActionDeaths, ...]


@dataclass(frozen=True)
class CharacterCounter:
    char_id: str
    kind: str
    value: int


@dataclass(frozen=True)
class CharacterCounters:
    rows: tuple[CharacterCounter, ...] = field(repr=False)

    @property
    def spawns(self):
        # Deaths/withdrawals are independent counters, not further deployments.
        return sum(row.value for row in self.rows if row.kind == "SPAWN")


@dataclass(frozen=True)
class RogueFinishRecord:
    facts: DecodedRogueFinish = field(repr=False)
    journal: ReplayRecord | None = field(repr=False)
    snapshot: BattleSnapshot
    counters: CharacterCounters | None = field(default=None, repr=False)


def invalid() -> DomainError:
    return DomainError("INVALID_ROGUE_FINISH", "探索战斗记录格式或关联无效；尚未提交结算")


def decode_char_stats(stats: dict) -> CharacterCounters | None:
    """Decode the observed Key/Value pool, never an entire telemetry record.

    One owned ro1_n_1_1 native finish confirmed SPAWN1/DEAD1, matching the
    frozen StringEnumConverter declaration. Missing/null is unavailable, not
    known zero; only an explicit empty list establishes zero recorded counters.
    Ownership, supported effects and persistent progression belong to domain
    admission. Reading these counts alone grants no eligibility or reward.
    """
    if type(stats) is not dict:
        raise invalid()
    source = stats.get("charStats")
    if source is None:
        return None
    if type(source) is not list or len(source) > MAX_COUNTER_ROWS:
        raise invalid()
    rows, seen, total = [], set(), 0
    for raw in source:
        if type(raw) is not dict or set(raw) != {"Key", "Value"}:
            raise invalid()
        key, value = raw["Key"], raw["Value"]
        if type(key) is not dict or set(key) != {"charId", "counterType"}:
            raise invalid()
        char, kind = key["charId"], key["counterType"]
        if (type(char) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", char) is None
                or type(kind) is not str or kind not in COUNTER_TYPES
                or type(value) is not int or not 0 <= value <= MAX_COUNTER_TOTAL
                or (char, kind) in seen):
            raise invalid()
        total += value
        if total > MAX_COUNTER_TOTAL:
            raise invalid()
        seen.add((char, kind))
        rows.append(CharacterCounter(char, kind, value))
    return CharacterCounters(tuple(rows))


def decode_snapshot(encoded: str) -> BattleSnapshot:
    """Read one ZIP entry in memory; never extract or interpret member paths."""
    try:
        if type(encoded) is not str or not 1 <= len(encoded) <= MAX_SNAPSHOT_WIRE:
            raise ValueError("Snapshot wire size")
        packed = base64.b64decode(encoded, validate=True)
        if base64.b64encode(packed).decode("ascii") != encoded:
            raise ValueError("Non-canonical Base64")
        # ZipUtils emits one archive with no prefix/trailer/comment. Reject an
        # appended archive/payload instead of silently reading its final entry.
        if len(packed) < 22 or packed[-22:-18] != b"PK\x05\x06" or packed[-2:] != b"\0\0":
            raise ValueError("Snapshot archive boundary")
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise ValueError("Expected one snapshot")
            entry = entries[0]
            if (entry.header_offset != 0 or entry.is_dir() or entry.flag_bits & 1
                    or entry.file_size > MAX_SNAPSHOT_JSON
                    or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                raise ValueError("Unsupported snapshot archive")
            with archive.open(entry) as stream:
                raw = stream.read(MAX_SNAPSHOT_JSON + 1)
            if len(raw) > MAX_SNAPSHOT_JSON:
                raise ValueError("Snapshot expansion budget")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=nonfinite)
        if type(value) is not dict or set(value) != {"actionKill"}:
            raise ValueError("Snapshot fields")
        rows = value["actionKill"]
        if type(rows) is not list or len(rows) > MAX_ACTION_ROWS:
            raise ValueError("Snapshot action budget")
        actions, deaths = [], 0
        for row in rows:
            if (type(row) is not list or len(row) != 4 or any(type(n) is not int for n in row)
                    or any(not -(2**31) <= n < 2**31 for n in row[:3]) or not 1 <= row[3] <= MAX_DEATHS):
                raise ValueError("Snapshot death row")
            deaths += row[3]
            if deaths > MAX_DEATHS:
                raise ValueError("Snapshot total budget")
            actions.append(ActionDeaths(*row))
        return BattleSnapshot(encoded, hashlib.sha256(encoded.encode("ascii")).hexdigest(), tuple(actions))
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, binascii.Error,
            zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, struct.error, zlib.error) as exc:
        raise invalid() from exc


def decode_finish_records(request: RogueFinishRequest, login_times: list[int], *,
                          expected_battle_id: str, expected_stage_id: str) -> RogueFinishRecord:
    """Bind records to the previously authenticated battle, with no DB writes.

    All outcome flags remain raw facts. In particular rank2 is not treated as
    a two-star win, and snapshot deaths are not equated with validKillCnt/EXP.
    Journal formation/seed and level action references need domain admission.
    """
    if signature_battle_id(request.battleData.isCheat) != expected_battle_id:
        raise invalid()
    facts = decode_rogue_payload(request, login_times)
    if facts.battleId != expected_battle_id or facts.stageId != expected_stage_id:
        raise invalid()
    counters = decode_char_stats(facts.battleData.stats)
    journal = decode_replay(request.battleLog) if request.battleLog is not None else None
    if journal is not None and journal.stage_id != expected_stage_id:
        raise invalid()
    return RogueFinishRecord(facts, journal, decode_snapshot(request.rlv2Data.battleSnapshot), counters)
