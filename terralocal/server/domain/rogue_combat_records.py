"""Versioned, battle-bound selected counters; never a reward policy.

Older settlements have no counters and remain unknown. The selected pool is
stored separately from the immutable v1..v3 reward facts and their hashes.
No telemetry, login material or retrospective reconstruction is retained.
"""

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.protocol.rogue_battle_codec import COUNTER_CODEC, decode_char_stats

VERSION = "rogue-char-stat-archive-v1"


def invalid():
    return DomainError("ROGUE_COUNTER_ARCHIVE_INCOMPATIBLE", "探索战斗计数归档不一致；请保留原存档", 503)


def archive(counters, *, battle_id, run_id, gamedata_hash, facts):
    if counters is None:
        return None
    body = {"version": VERSION, "codec": COUNTER_CODEC, "battle": battle_id, "run": run_id,
            "gamedata": gamedata_hash, "facts": fingerprint(facts),
            "charStats": [{"Key": {"charId": row.char_id, "counterType": row.kind}, "Value": row.value}
                          for row in sorted(counters.rows, key=lambda row: (row.char_id, row.kind))]}
    return body | {"hash": fingerprint(body)}


def read(value, *, battle_id, run_id, gamedata_hash, facts):
    try:
        if (type(value) is not dict
                or set(value) != {"version", "codec", "battle", "run", "gamedata", "facts", "charStats", "hash"}
                or value["version"] != VERSION or value["codec"] != COUNTER_CODEC
                or value["battle"] != battle_id or value["run"] != run_id or value["gamedata"] != gamedata_hash
                or value["facts"] != fingerprint(facts)
                or value["hash"] != fingerprint({k: v for k, v in value.items() if k != "hash"})):
            raise invalid()
        counters = decode_char_stats({"charStats": value["charStats"]})
        if counters is None or archive(counters, battle_id=battle_id, run_id=run_id,
                                       gamedata_hash=gamedata_hash, facts=facts) != value:
            raise invalid()
        return counters
    except (DomainError, TypeError, ValueError, KeyError, RecursionError) as exc:
        raise invalid() from exc
