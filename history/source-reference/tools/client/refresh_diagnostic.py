"""Controlled refresh comparison on a private, frozen copy of the local save.

This is a research app, never a release adapter. It retains normal responses and
errors, and can omit only pushFlags equal to this session's delivered snapshot.
Shared cache/client/profile/certificate directories are read-only inputs to the
game app; the database, settings and logs live under .cache/refresh-diagnostic.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from starlette.responses import Response

from terralocal.config import load_settings
from terralocal.server.domain.refresh import Module
from terralocal.server.main import create_game_app, credentials
from terralocal.server.services.runtime import Runtime

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".cache/refresh-diagnostic"
ENVIRONMENT = "TERRALOCAL_DIAGNOSTIC_DIR"


def private_directory(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(BASE.resolve()) or resolved == BASE.resolve():
        raise ValueError("Diagnostic directory must be a child of the workspace diagnostic cache")
    return resolved


def session_key(request: Request) -> str:
    token, uid = credentials(request)
    return hashlib.sha256((token + "\0" + (uid or "")).encode()).hexdigest()


def omit_unchanged_flags(envelope: dict, delivered: dict | None) -> bool:
    delta = envelope.get("playerDataDelta")
    if delivered is None or not isinstance(delta, dict):
        return False
    modified = delta.get("modified")
    if not isinstance(modified, dict) or "pushFlags" not in modified:
        return False
    if modified["pushFlags"] != delivered:
        return False
    del modified["pushFlags"]
    return True


def omit_selected_results(envelope: dict, mask: int) -> list[str]:
    if type(mask) is not int or mask < 0 or mask & ~sum(int(m) for m in Module):
        raise ValueError("Diagnostic mask must contain only known sync module bits")
    result = envelope.get("result")
    if not isinstance(result, dict):
        return []
    removed = [key for key in result if key.isdecimal() and int(key) & mask]
    for key in removed:
        del result[key]
    return sorted(removed)


GAMEPLAY_FIELDS = {
    "/gacha/getPoolDetail": {"poolId", "gachaObjGroupType"},
    "/gacha/choosePoolUp": {"poolId", "chooseChar"},
    "/gacha/advancedGacha": {"poolId", "useTkt", "itemId"},
    "/gacha/tenAdvancedGacha": {"poolId", "useTkt", "itemList"},
    "/gacha/normalGacha": {"slotId", "tagList", "duration", "specialTagId"},
    "/gacha/boostNormalGacha": {"slotId", "buy"},
    "/gacha/cancelNormalGacha": {"slotId"},
    "/gacha/finishNormalGacha": {"slotId"},
    "/story/finishStory": {"storyId"},
    "/quest/squadFormation": {"squadId", "changeSkill"},
    "/quest/battleStart": {"stageId", "usePracticeTicket", "isReplay", "isRetro", "pry", "battleType"},
    "/quest/saveBattleReplay": {"battleId"},
    "/mission/confirmMission": {"missionId"},
    "/charBuild/upgradeChar": {"charInstId", "expMats"},
    "/charBuild/evolveChar": {"charInstId", "destEvolvePhase"},
    "/charBuild/changeCharSkin": {"charInstId", "skinId"},
    "/user/changeSecretary": {"charInstId", "skinId"},
}


def gameplay_fields(path: str, payload) -> dict:
    """Only bounded gameplay identifiers/enums, never arbitrary request data."""
    if not isinstance(payload, dict):
        return {}
    result = {}
    for key in GAMEPLAY_FIELDS.get(path, set()):
        value = payload.get(key)
        if key in {"poolId", "itemId", "storyId", "squadId", "stageId", "battleId", "missionId"}:
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_/#.-]{0,160}", value):
                result[key] = value
        elif key == "skinId":
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_/#.@-]{1,128}", value):
                result[key] = value
        elif key == "tagList":
            if (isinstance(value, list) and len(value) <= 3
                    and all(type(tag) is int and 0 <= tag <= 10000 for tag in value)):
                result[key] = value
        elif key in {"itemList", "expMats"}:
            maximum = 20 if key == "expMats" else 10
            if (isinstance(value, list) and len(value) <= maximum and all(
                    isinstance(item, dict) and isinstance(item.get("id"), str)
                    and re.fullmatch(r"[A-Za-z0-9_/#.-]{1,96}", item["id"])
                    and type(item.get("count")) is int and 1 <= item["count"] <= 2_000_000_000
                    for item in value)):
                result[key] = [{"id": item["id"], "count": item["count"]} for item in value]
        elif key == "chooseChar":
            if (isinstance(value, dict) and set(value) == {"4", "5"} and all(
                    isinstance(ids, list) and len(ids) == 3 and all(
                        isinstance(cid, str) and re.fullmatch(r"char_[A-Za-z0-9_]{1,80}", cid)
                        for cid in ids) for ids in value.values())):
                result[key] = {rarity: list(ids) for rarity, ids in value.items()}
        elif type(value) is int and -1 <= value <= 2**31 - 1:
            result[key] = value
    return result


def capture_local_finish(runtime, directory: Path, token: str, uid: str | None, payload) -> bool:
    """Private research fixture from an authenticated, owned local battle only.

    Never capture headers, SDK traffic or the surrounding telemetry. Encrypted
    data remains private; publishable fixtures need decryption and sanitization.
    """
    from terralocal.server.domain import accounts
    from terralocal.server.domain.errors import DomainError
    from terralocal.server.persistence import models as m

    if not isinstance(payload, dict) or not isinstance(payload.get("battleData"), dict):
        return False
    battle_data = payload["battleData"]
    signature = battle_data.get("isCheat")
    data = payload.get("data")
    if not isinstance(signature, str) or len(signature) > 128 or not isinstance(data, str):
        return False
    try:
        encoded = base64.b64decode(signature, validate=True)
        battle_id = bytes((value - 7) % 256 for value in encoded).decode("utf-8")
        if str(uuid.UUID(battle_id)) != battle_id:
            return False
        with runtime.database.transaction(write=False) as session:
            account = accounts.authenticate(session, token, uid)
            row = session.get(m.BattleSession, battle_id)
            if row is None or row.account_id != account.id:
                return False
    except (ValueError, UnicodeError, DomainError):
        return False
    safe_stats = {}
    stats = battle_data.get("stats")
    if isinstance(stats, dict):
        for key in ("killedEnemiesCnt", "beginTs", "endTs", "leftHp", "fixedPlayTime", "checkKilledCnt"):
            value = stats.get(key)
            if isinstance(value, str) and re.fullmatch(r"[0-9. -]{0,48}|true|false", value):
                safe_stats[key] = value
    fixture = {"data": data, "battleData": {"isCheat": signature,
               "completeTime": battle_data.get("completeTime"), "stats": safe_stats},
               "telemetry_schema": schema_of_finish(stats)}
    output = directory / f"native-finish-{uuid.uuid4().hex}.private.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(fixture, stream, separators=(",", ":"))
    return True


def schema_of_finish(stats) -> dict:
    from terralocal.server.observability import schema

    return schema(stats)


def capture_local_replay(runtime, directory: Path, token: str, uid: str | None, payload) -> bool:
    """Retain only the owned synthetic battle's opaque proxy journal, privately."""
    from terralocal.server.domain.errors import DomainError
    from terralocal.server.domain.sessions import authenticate_session
    from terralocal.server.persistence import models as m
    from terralocal.server.protocol.replay_codec import MAX_WIRE

    if not isinstance(payload, dict):
        return False
    battle_id, replay = payload.get("battleId"), payload.get("battleReplay")
    if not isinstance(battle_id, str) or not isinstance(replay, str) or not 1 <= len(replay) <= MAX_WIRE:
        return False
    try:
        if str(uuid.UUID(battle_id)) != battle_id:
            return False
        with runtime.database.transaction(write=False) as session:
            account, _ = authenticate_session(session, token, uid)
            row = session.get(m.BattleSession, battle_id)
            if row is None or row.account_id != account.id or row.state != "FINISHED":
                return False
    except (ValueError, DomainError):
        return False
    fixture = {"battleId": battle_id, "battleReplay": replay}
    output = directory / f"native-replay-{uuid.uuid4().hex}.private.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(fixture, stream, separators=(",", ":"))
    return True


def prepare(name: str, variant: str) -> Path:
    if variant not in {"production", "no-reassert"}:
        raise ValueError("Unknown diagnostic variant")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
        raise ValueError("Diagnostic name must be a short directory identifier")
    directory = private_directory(BASE / name)
    if directory.exists():
        raise ValueError("Retain existing evidence; select a new diagnostic name")
    source = load_settings(ROOT / "data")
    if not source.database_path.is_file():
        raise ValueError("The source save does not exist")
    directory.mkdir(parents=True)
    for member in ("cache", "client", "profiles", "certs"):
        origin = (source.data_dir / member).resolve()
        if not origin.is_dir():
            raise ValueError(f"Missing frozen input directory: {member}")
        link = directory / member
        if os.name == "nt":
            # One shell, literal paths, no deletion or moves. These are directory
            # junctions, so no developer-mode symlink privilege is required.
            def quote(value):
                return "'" + str(value).replace("'", "''") + "'"
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "New-Item -ItemType Junction -Path " + quote(link)
                            + " -Target " + quote(origin) + " | Out-Null"], check=True)
        else:
            link.symlink_to(origin, target_is_directory=True)
    database = directory / "terralocal.sqlite3"
    with closing(sqlite3.connect(source.database_path.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(database)) as clone:
            original.backup(clone)
            if clone.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Cloned database failed integrity verification")
            frozen_at = int(time.time())
            clone.execute("UPDATE server_clock SET mode='fixed', fixed_at=?, offset=0 WHERE id=1",
                          (frozen_at,))
            clone.commit()
    settings = source.model_copy(update={"data_dir": directory})
    settings.save()
    for name in ("drop_rules.json", "headhunting_rules.json"):
        rules = source.data_dir / name
        if rules.is_file():
            shutil.copyfile(rules, directory / rules.name)
    receipt = {"purpose": "isolated-refresh-comparison", "variant": variant,
               "source_data_dir": str(source.data_dir), "fixed_at": frozen_at,
               "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
               "client_profile": settings.client_profile, "gamedata_hash": settings.gamedata_hash,
               "created_at": datetime.now(timezone.utc).isoformat()}
    (directory / "diagnostic.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    (directory / "control.json").write_text(json.dumps({"omit_result_mask": 0}), encoding="utf-8")
    return directory


def create_app():
    directory = private_directory(Path(os.environ[ENVIRONMENT]))
    receipt = json.loads((directory / "diagnostic.json").read_bytes())
    if (receipt["purpose"] != "isolated-refresh-comparison"
            or Path(receipt["source_data_dir"]).resolve() != (ROOT / "data").resolve()
            or receipt["variant"] not in {"production", "no-reassert"}):
        raise ValueError("Unrecognized diagnostic receipt")
    runtime = Runtime(load_settings(directory))
    with runtime.database.transaction(write=False) as session:
        from terralocal.server.persistence.models import ServerClockState

        state = session.get(ServerClockState, 1)
        if state.mode != "fixed" or state.fixed_at != receipt["fixed_at"]:
            raise ValueError("Diagnostic clock is not frozen")
    app = create_game_app(runtime)
    delivered: dict[str, dict] = {}
    audit = directory / "refresh-observation.jsonl"

    @app.middleware("http")
    async def inspect_refresh(request: Request, call_next):
        fields = {}
        if request.url.path in GAMEPLAY_FIELDS:
            try:
                if int(request.headers.get("content-length", "0")) <= 4096:
                    fields = gameplay_fields(request.url.path, await request.json())
            except (ValueError, json.JSONDecodeError):
                pass
        response = await call_next(request)
        if request.url.path == "/quest/battleFinish":
            try:
                payload = json.loads(request.state.body)
                capture_local_finish(runtime, directory, *credentials(request), payload)
            except (ValueError, AttributeError):
                pass
        if request.url.path == "/quest/saveBattleReplay":
            try:
                capture_local_replay(runtime, directory, *credentials(request), json.loads(request.state.body))
            except (ValueError, AttributeError):
                pass
        if request.url.path in GAMEPLAY_FIELDS:
            record = {"at": datetime.now(timezone.utc).isoformat(), "route": request.url.path,
                      "status": response.status_code, "fields": fields}
            with (directory / "gameplay-observation.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record) + "\n")
        watched = {"/account/syncData", "/account/syncStatus", "/account/syncPushMessage"}
        if request.url.path not in watched or response.status_code != 200:
            return response
        body = b"".join([part async for part in response.body_iterator])
        envelope = json.loads(body)
        key = session_key(request)
        removed = False
        omitted_results = []
        before = []
        if request.url.path == "/account/syncData":
            delivered[key] = envelope["user"]["pushFlags"]
        else:
            delta = envelope.get("playerDataDelta", {})
            before = sorted(delta.get("modified", {}))
            if receipt["variant"] == "no-reassert":
                removed = omit_unchanged_flags(envelope, delivered.get(key))
            flags = delta.get("modified", {}).get("pushFlags")
            if isinstance(flags, dict) and key in delivered:
                delivered[key] = flags
            if request.url.path == "/account/syncStatus":
                control_path = directory / "control.json"
                control = json.loads(control_path.read_bytes()) if control_path.is_file() else {"omit_result_mask": 0}
                if set(control) != {"omit_result_mask"}:
                    raise ValueError("Unknown diagnostic control")
                # Intentionally missing results isolate module callbacks. This
                # experiment is never claimed to implement or fix a module.
                omitted_results = omit_selected_results(envelope, control["omit_result_mask"])
        delta = envelope.get("playerDataDelta", {})
        record = {"at": datetime.now(timezone.utc).isoformat(), "route": request.url.path,
                  "variant": receipt["variant"], "modified_before": before,
                  "snapshot_available": key in delivered,
                  "modified_after": sorted(delta.get("modified", {})),
                  "deleted_roots": sorted(delta.get("deleted", {})),
                  "omitted_unchanged_flags": removed, "omitted_module_results": omitted_results}
        if request.url.path == "/account/syncStatus":
            record["modules"] = getattr(request.state, "sync_modules", None)
        # Only route/root names and diagnostic booleans, never credentials or
        # response values. A 200 remains only server-side evidence.
        with audit.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
        if removed or omitted_results:
            body = json.dumps(envelope, separators=(",", ":")).encode()
        headers = dict(response.headers)
        headers["content-length"] = str(len(body))
        return Response(body, status_code=response.status_code, headers=headers,
                        background=response.background)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            runtime.database.close()

    app.router.lifespan_context = lifespan
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--variant", choices=("production", "no-reassert"), required=True)
    arguments = parser.parse_args()
    print(prepare(arguments.name, arguments.variant))
