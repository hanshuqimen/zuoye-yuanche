"""Frozen client: UTF-8 BattleLog JSON in one ZIP entry, encoded as Base64.

Read the archive in memory; no member paths are ever extracted. The wire bytes
are retained exactly, while bounded parsing verifies their stage association.
"""

import base64
import binascii
import hashlib
import io
import json
import struct
import zipfile
import zlib

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.replays import MAX_REPLAY_WIRE, ReplayMember, ReplayRecord

MAX_WIRE = MAX_REPLAY_WIRE
MAX_JSON = 16 * 1024 * 1024


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate replay field")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Nonfinite replay value")


def _member(value) -> ReplayMember:
    if not isinstance(value, dict):
        raise ValueError("Invalid replay member")
    identifier = value["charInstId"]
    template, skill, module = value["tmplId"], value["skillId"], value["uniequipId"]
    index, level, assist = value["skillIndex"], value["uniequipLevel"], value["isAssistChar"]
    if (type(identifier) is not int or not 1 <= identifier < 2**31
            or type(index) is not int or not -1 <= index <= 2
            or type(level) is not int or not 0 <= level <= 3 or type(assist) is not bool
            or any(text is not None and (not isinstance(text, str) or not 1 <= len(text) <= 128)
                   for text in (template, skill))
            or not isinstance(module, str) or len(module) > 128):
        raise ValueError("Invalid replay selections")
    return ReplayMember(identifier, template, skill, index, module, level, assist)


def decode_replay(encoded: str) -> ReplayRecord:
    try:
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= MAX_WIRE:
            raise ValueError("Invalid wire size")
        packed = base64.b64decode(encoded, validate=True)
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise ValueError("Expected one journal")
            entry = entries[0]
            if (entry.is_dir() or entry.flag_bits & 1 or entry.file_size > MAX_JSON
                    or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                raise ValueError("Unsupported archive")
            with archive.open(entry) as stream:
                raw = stream.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ValueError("Journal too large")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_invalid_constant)
        if (not isinstance(data, dict) or set(data) - {"campaignOnlyVersion", "timestamp", "journal", "battleMeta"}
                or not isinstance(data.get("journal"), dict)):
            raise ValueError("Invalid BattleLog")
        journal = data["journal"]
        metadata = journal.get("metadata")
        if (not isinstance(metadata, dict) or not isinstance(metadata.get("stageId"), str)
                or not 1 <= len(metadata["stageId"]) <= 128
                or not isinstance(journal.get("squad"), list) or not 1 <= len(journal["squad"]) <= 12
                or not isinstance(journal.get("logs"), list)
                or type(journal.get("randomSeed")) is not int
                or not -(2**31) <= journal["randomSeed"] < 2**31):
            raise ValueError("Invalid battle journal")
        if "campaignOnlyVersion" in data and (type(data["campaignOnlyVersion"]) is not int
                or not 0 <= data["campaignOnlyVersion"] < 2**32):
            raise ValueError("Invalid campaign version")
        if not isinstance(data.get("timestamp"), str) or not 1 <= len(data["timestamp"]) <= 160:
            raise ValueError("Invalid timestamp")
        members = tuple(_member(value) for value in journal["squad"])
        if len({member.operator_id for member in members}) != len(members):
            raise ValueError("Duplicate replay member")
        return ReplayRecord(encoded=encoded, stage_id=metadata["stageId"],
                            sha256=hashlib.sha256(encoded.encode("ascii")).hexdigest(), squad=members)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, binascii.Error,
            zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, struct.error, zlib.error) as exc:
        raise DomainError("INVALID_NATIVE_REPLAY", "代理记录格式无效，已有存档未改写") from exc
