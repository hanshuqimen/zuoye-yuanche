"""Verify full-roster persistence using local GameData in an isolated audit database.

This tool neither contacts a game client nor changes the production data directory.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from terralocal.admin.app import create_admin_app
from terralocal.config import Settings
from terralocal.server.domain.accounts import create_account
from terralocal.server.domain.context import Context
from terralocal.server.gamedata import import_data
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime


def snapshot(runtime, account_id):
    with runtime.database.transaction(write=False) as session:
        return SyncDataAssembler(Context(session, runtime.data, account_id)).assemble()["troop"]["chars"]


def verify(runtime, account_id):
    chars = {row["charId"]: row for row in snapshot(runtime, account_id).values()}
    eligible = {key: char for key, char in runtime.data.characters.items()
                if key.startswith("char_") and not char.get("isNotObtainable")}
    assert chars.keys() == eligible.keys(), "roster differs from obtainable character definitions"
    mastered, without_mastery = 0, 0
    for char_id, definition in eligible.items():
        op = chars[char_id]
        assert op["potentialRank"] == definition["maxPotentialLevel"], char_id
        assert op["favorPoint"] == runtime.data.table("favor_table")["maxFavor"], char_id
        assert op["mainSkillLvl"] == len(definition["allSkillLvlup"]) + 1, char_id
        assert 0 <= op["evolvePhase"] < len(definition["phases"]), char_id
        assert 1 <= op["level"] <= definition["phases"][op["evolvePhase"]]["maxLevel"], char_id
        assert len(op["skills"]) == len(definition["skills"]), char_id
        conditions = [row["unlockCond"] for row in definition["allSkillLvlup"]]
        for value, skill in zip(op["skills"], definition["skills"], strict=True):
            tree = skill.get("levelUpCostCond") or []
            target = min(3, len(tree))
            assert value["skillId"] == skill["skillId"] and value["specializeLevel"] == target, char_id
            assert value["unlock"] == 1 and value["state"] == 0 and value["completeUpgradeTime"] == -1, char_id
            conditions.extend([skill["unlockCond"], *(row["unlockCond"] for row in tree[:target])])
            mastered += int(target == 3)
            without_mastery += int(target == 0)
        for condition in conditions:
            phase = int(str(condition["phase"]).removeprefix("PHASE_"))
            assert op["evolvePhase"] > phase or (op["evolvePhase"] == phase and
                                                op["level"] >= condition["level"]), char_id
    return {"operators": len(chars), "masteredSkills": mastered, "skillsWithoutMastery": without_mastery}


def main():
    directory = Path(".cache/roster-audit").resolve()
    manifest = import_data(Path("data/gamedata/source/excel"), directory / "cache",
                           source="user-local-roster-audit")
    settings = Settings(data_dir=directory, gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    with runtime.database.transaction() as session:
        primary = create_account(session, runtime.data, f"Roster GM {stamp}")
        primary_id = primary.id
        other = create_account(session, runtime.data, f"Roster Other {stamp}")
        other_id = other.id
        sandbox = create_account(session, runtime.data, f"Roster Sandbox {stamp}", "Sandbox")
        sandbox_id = sandbox.id
    original = snapshot(runtime, primary_id)
    other_original = snapshot(runtime, other_id)
    start = time.perf_counter()
    with TestClient(create_admin_app(runtime), base_url="http://127.0.0.1:8080") as client:
        headers = {"x-csrf-token": client.get("/api/session").json()["csrf"]}
        command = {"accountId": primary_id, "action": "complete-roster"}
        first = client.post("/api/gm", json=command, headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()["roster"]["totalOperators"] == 429
        checks = verify(runtime, primary_id)
        sandbox_checks = verify(runtime, sandbox_id)
        saved = snapshot(runtime, primary_id)
        assert all(saved[key]["charId"] == row["charId"] for key, row in original.items())
        repeated = client.post("/api/gm", json=command, headers=headers)
        assert repeated.status_code == 200
        assert repeated.json()["roster"]["grantedOperators"] == repeated.json()["roster"]["updatedOperators"] == 0
        audit = client.get("/api/logs").json()["audit"]
        assert audit[0]["action"] == "complete-roster" and audit[0]["accountId"] == primary_id
        assert audit[0]["detail"]["outcome"]["masteredSkills"] == 928
    assert checks == sandbox_checks == {"operators": 429, "masteredSkills": 928, "skillsWithoutMastery": 17}
    assert snapshot(runtime, primary_id) == saved
    assert snapshot(runtime, other_id) == other_original
    elapsed = time.perf_counter() - start
    runtime.database.close()
    reopened = Runtime(settings)
    try:
        assert snapshot(reopened, primary_id) == saved
        assert snapshot(reopened, other_id) == other_original
        assert verify(reopened, primary_id) == verify(reopened, sandbox_id) == checks
        assert reopened.database.integrity() == "ok"
    finally:
        reopened.database.close()
    report = {"verifiedAt": datetime.now().isoformat(), "kind": "local-domain-and-admin-audit",
              "clientVerified": False, "gamedataHash": manifest["hash"], "databaseDirectory": str(directory),
              "primaryAccount": primary_id, "sandboxAccount": sandbox_id, "otherAccount": other_id,
              "checks": checks, "firstApplication": first.json()["roster"],
              "secondApplication": repeated.json()["roster"], "accountIsolation": True,
              "starterInstanceIdsPreserved": True, "restartRestoredExactly": True, "databaseIntegrity": "ok",
              "applyAndVerifySeconds": round(elapsed, 4)}
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
