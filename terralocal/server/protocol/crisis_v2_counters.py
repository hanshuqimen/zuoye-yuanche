"""Selected Crisis V2 statistics, after owned battle/formation admission.

Loaded M66437 copies runtime extraBattleInfoStats (+0x50) into the snapshot's
extraBattleInfo (+0xd8). Never fall back to the runtime field name. ListDict's
ordinary collection shape and its explicit converter's object shape are two
separate local codec admissions; this does not claim a native packet observed
either one. Missing/null pools remain unknown, distinct from explicit empties.
"""

import re
from dataclasses import dataclass

from terralocal.server.domain.errors import DomainError
from terralocal.server.protocol.rogue_battle_codec import (
    MAX_COUNTER_ROWS,
    MAX_COUNTER_TOTAL,
    CharacterCounters,
    decode_char_stats,
)

CODEC = "cn-2.7.71-crisis-v2-selected-counters-v1"
ENEMY_KINDS = frozenset({"HP_ZERO", "FALLDOWN", "REACH_EXIT", "ENCOUNTER", "DEADLIKE_REACH_EXIT"})
EVENTS = frozenset({"COST", "not_build_at_reed"})
ATTRIBUTES = frozenset({"COST", "HP_RATIO"})
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")
INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)")
RATIO = re.compile(r"([01])\.([0-9]{3})")


def invalid():
    return DomainError("INVALID_CRISIS_V2_COUNTERS", "危机合约必要战斗计数无效，尚未提交通关结算")


@dataclass(frozen=True)
class EnemyCounter:
    enemy: str
    kind: str
    invalid_kill: bool
    value: int


@dataclass(frozen=True)
class ExtraCounter:
    kind: str
    entity: str
    name: str
    sample: int | None  # COST integer, HP_RATIO in exact thousandths (F3).
    value: int


@dataclass(frozen=True)
class CounterFacts:
    characters: CharacterCounters | None
    enemies: tuple[EnemyCounter, ...] | None
    extra: tuple[ExtraCounter, ...] | None
    extra_encoding: str

    def canonical(self):
        # The two admitted ListDict representations have identical business
        # facts. Representation itself is diagnostic, not a second reward key.
        return {"codec": CODEC,
            "characters": None if self.characters is None else [
                [r.char_id, r.kind, r.value] for r in sorted(self.characters.rows,
                    key=lambda r: (r.char_id, r.kind))],
            "enemies": None if self.enemies is None else [
                [r.enemy, r.kind, r.invalid_kill, r.value] for r in self.enemies],
            "extra": None if self.extra is None else [
                [r.kind, r.entity, r.name, r.sample, r.value] for r in self.extra]}

    @property
    def has_end_marker(self):
        return self.extra is not None and any(r.kind == "SIMPLE" and not r.entity and r.name == "COST"
                                             for r in self.extra)


def _enemies(stats):
    value = stats.get("enemyStats")
    if value is None:
        return None
    if type(value) is not list or len(value) > MAX_COUNTER_ROWS:
        raise invalid()
    rows, seen, total = [], set(), 0
    for row in value:
        if type(row) is not dict or set(row) != {"Key", "Value"}:
            raise invalid()
        key, count = row["Key"], row["Value"]
        if type(key) is not dict or set(key) != {"enemyId", "counterType", "isInvalidKilled"}:
            raise invalid()
        enemy, kind, flag = key["enemyId"], key["counterType"], key["isInvalidKilled"]
        if (type(enemy) is not str or IDENTIFIER.fullmatch(enemy) is None
                or type(kind) is not str or kind not in ENEMY_KINDS or type(flag) is not bool
                or type(count) is not int or not 0 <= count <= MAX_COUNTER_TOTAL):
            raise invalid()
        ident = (enemy, kind, flag)
        total += count
        if ident in seen or total > MAX_COUNTER_TOTAL:
            raise invalid()
        seen.add(ident)
        rows.append(EnemyCounter(*ident, count))
    return tuple(sorted(rows, key=lambda r: (r.enemy, r.kind, r.invalid_kill)))


def _extra(stats):
    value = stats.get("extraBattleInfo")
    if value is None:
        return None, "absent"
    if type(value) in (dict, list) and len(value) > MAX_COUNTER_ROWS:
        raise invalid()
    if type(value) is dict:
        source, encoding = list(value.items()), "object"
    elif type(value) is list:
        source, encoding = [], "list"
        for row in value:
            if type(row) is not dict or set(row) != {"Key", "Value"}:
                raise invalid()
            source.append((row["Key"], row["Value"]))
    else:
        raise invalid()
    if len(source) > MAX_COUNTER_ROWS:
        raise invalid()
    rows, seen, occurrences = [], set(), 0
    for key, count in source:
        if (type(key) is not str or not 1 <= len(key) <= 512 or "\0" in key
                or type(count) is not int or not -(2**31) <= count < 2**31 or key in seen):
            raise invalid()
        seen.add(key)
        parts = key.split(",")
        if len(parts) < 3 or parts[2] not in EVENTS | ATTRIBUTES:
            continue  # Other logs are neither retained nor treated as comments.
        kind, entity, name = parts[:3]
        if (kind not in {"SIMPLE", "DETAILED", "ATTRIBUTE"} or len(entity) > 160
                or any(ord(c) < 32 for c in entity)):
            raise invalid()
        sample = None
        if kind == "ATTRIBUTE":
            if len(parts) != 4 or name not in ATTRIBUTES or not 0 <= count <= MAX_COUNTER_TOTAL:
                raise invalid()
            if name == "COST":
                if len(parts[3]) > 11 or INTEGER.fullmatch(parts[3]) is None:
                    raise invalid()
                sample = int(parts[3])
                if not -(2**31) <= sample < 2**31:
                    raise invalid()
            else:
                match = RATIO.fullmatch(parts[3])
                if match is None:
                    raise invalid()
                sample = int(match[1])*1000 + int(match[2])
                if sample > 1000:
                    raise invalid()
        elif len(parts) != 3 or name not in EVENTS or kind == "SIMPLE" and entity:
            raise invalid()
        elif name != "COST" and not 0 <= count <= MAX_COUNTER_TOTAL:
            raise invalid()
        if name != "COST" or kind == "ATTRIBUTE":
            occurrences += count
            if occurrences > MAX_COUNTER_TOTAL:
                raise invalid()
        rows.append(ExtraCounter(kind, entity, name, sample, count))
    return tuple(sorted(rows, key=lambda r: (r.kind, r.entity, r.name,
                 r.sample if r.sample is not None else -(2**63)))), encoding


def decode_counters(stats):
    if type(stats) is not dict:
        raise invalid()
    try:
        characters = decode_char_stats(stats)
        enemies = _enemies(stats)
        extra, encoding = _extra(stats)
        return CounterFacts(characters, enemies, extra, encoding)
    except (ValueError, TypeError, KeyError, DomainError):
        raise invalid() from None


def restore_counters(value):
    """Validate the minimal versioned receipt, without admitting raw telemetry."""
    try:
        if (type(value) is not dict or set(value) != {"codec", "characters", "enemies", "extra"}
                or value["codec"] != CODEC):
            raise ValueError()
        for key in ("characters", "enemies", "extra"):
            if value[key] is not None and (type(value[key]) is not list or len(value[key]) > MAX_COUNTER_ROWS):
                raise ValueError()
        stats = {}
        if value["characters"] is not None:
            stats["charStats"] = [{"Key": {"charId": char, "counterType": kind}, "Value": count}
                                  for char, kind, count in value["characters"]]
        if value["enemies"] is not None:
            stats["enemyStats"] = [{"Key": {"enemyId": enemy, "counterType": kind, "isInvalidKilled": flag},
                                     "Value": count} for enemy, kind, flag, count in value["enemies"]]
        if value["extra"] is not None:
            rows = []
            for kind, entity, name, sample, count in value["extra"]:
                if any(type(v) is not str for v in (kind, entity, name)):
                    raise ValueError()
                key = ",".join((kind, entity, name))
                if kind == "ATTRIBUTE":
                    if type(sample) is not int:
                        raise ValueError()
                    text = f"{sample//1000}.{sample%1000:03d}" if name == "HP_RATIO" else str(sample)
                    key += "," + text
                elif sample is not None:
                    raise ValueError()
                rows.append({"Key": key, "Value": count})
            stats["extraBattleInfo"] = rows
        restored = decode_counters(stats)
        if restored.canonical() != value:
            raise ValueError()
        return restored
    except (ValueError, TypeError, KeyError, DomainError):
        raise ValueError("危机合约回执计数不符合绑定格式") from None
