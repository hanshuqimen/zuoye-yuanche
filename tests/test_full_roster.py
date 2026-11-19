"""Synthetic training trees test valid states, isolation, rollback and restart persistence."""

import copy
import json

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from sqlalchemy import select

from terralocal.admin.app import create_admin_app
from terralocal.config import Settings
from terralocal.server.domain.accounts import complete_roster, create_account
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import import_data
from terralocal.server.persistence import models as m
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def roster_runtime(tmp_path):
    tables = miniature()
    high = tables["character_table"]["char_synthetic"]
    high["phases"] = [{"maxLevel": 40, "evolveCost": None},
                      {"maxLevel": 60, "evolveCost": []}, {"maxLevel": 80, "evolveCost": []}]
    high["allSkillLvlup"] = [{"unlockCond": {"phase": "PHASE_1" if i >= 3 else "PHASE_0", "level": 1},
                             "lvlUpCost": []} for i in range(6)]
    high["skills"][0]["levelUpCostCond"] = [
        {"unlockCond": {"phase": "PHASE_2", "level": n}, "levelUpCost": [], "lvlUpTime": 10}
        for n in (1, 20, 30)]
    high["skills"].append({"skillId": "skill_2", "unlockCond": {"phase": "PHASE_2", "level": 5},
                           "levelUpCostCond": [{"unlockCond": {"phase": "PHASE_2", "level": n},
                                                "levelUpCost": [], "lvlUpTime": 10} for n in (1, 30, 40)]})
    tables["skill_table"]["skill_2"] = {}
    low = copy.deepcopy(high)
    low["rarity"], low["phases"] = "TIER_3", high["phases"][:2]
    low["skills"] = [{"skillId": "skill", "unlockCond": {"phase": "PHASE_0", "level": 1},
                      "levelUpCostCond": []}]
    no_skill = copy.deepcopy(low)
    no_skill["rarity"], no_skill["skills"], no_skill["allSkillLvlup"] = "TIER_2", [], []
    no_skill["phases"] = no_skill["phases"][:1]
    no_potential = copy.deepcopy(high)
    no_potential["maxPotentialLevel"] = 0
    blocked = {**high, "isNotObtainable": True}
    tables["character_table"].update({"char_low": low, "char_no_skill": no_skill,
                                      "char_no_potential": no_potential, "char_blocked": blocked,
                                      "token_synthetic": high})
    for char_id in ("char_low", "char_no_skill", "char_no_potential"):
        tables["charword_table"]["voiceLangDict"][char_id] = copy.deepcopy(
            tables["charword_table"]["voiceLangDict"]["char_synthetic"])
        tables["charword_table"]["charDefaultTypeDict"][char_id] = "JP"
    source = tmp_path / "source"
    source.mkdir()
    for name, table in tables.items():
        (source / f"{name}.json").write_text(json.dumps(table), "utf-8")
    manifest = import_data(source, tmp_path / "data" / "cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        create_account(session, runtime.data, "Primary")
        create_account(session, runtime.data, "Other")
    yield runtime
    runtime.database.close()


def character_state(runtime, account_id):
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, account_id)
        return SyncDataAssembler(ctx).assemble()["troop"]["chars"]


def test_full_roster_repeated_and_account_scoped_after_restart(roster_runtime):
    runtime = roster_runtime
    other_before = character_state(runtime, 2)
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        op = ctx.rows(m.Operator)[0]
        op.evolve_phase, op.level, op.exp = 2, 70, 123
        rows = session.scalars(select(m.OperatorSkill).where(m.OperatorSkill.operator_id == op.id)).all()
        rows[0].training_complete_at = ctx.now + 86400
        result = complete_roster(ctx)
        assert result == {"totalOperators": 4, "grantedOperators": 3, "updatedOperators": 4,
                          "masteredSkills": 4, "skillsWithoutMastery": 1, "maxTrust": 25570}
        assert ctx.balance("token") == 0
    before_restart = character_state(runtime, 1)
    chars = {o["charId"]: o for o in before_restart.values()}
    assert chars["char_synthetic"]["level"] == 70 and chars["char_synthetic"]["exp"] == 123
    assert chars["char_no_potential"]["level"] == 40  # Highest skill-specific M3 requirement.
    assert chars["char_no_potential"]["potentialRank"] == 0
    assert all(o["favorPoint"] == 25570 for o in chars.values())
    assert all(s["specializeLevel"] == 3 and s["unlock"] == 1 and s["state"] == 0
               and s["completeUpgradeTime"] == -1 for s in chars["char_synthetic"]["skills"])
    assert chars["char_low"]["evolvePhase"] == 1 and chars["char_low"]["mainSkillLvl"] == 7
    assert chars["char_low"]["skills"][0]["specializeLevel"] == 0
    assert chars["char_no_skill"]["evolvePhase"] == 0 and chars["char_no_skill"]["mainSkillLvl"] == 1
    assert chars["char_no_skill"]["skills"] == []
    with runtime.database.transaction() as session:
        result = complete_roster(Context(session, runtime.data, 1))
        assert result["grantedOperators"] == result["updatedOperators"] == 0
    assert character_state(runtime, 1) == before_restart
    assert character_state(runtime, 2) == other_before
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert character_state(reopened, 1) == before_restart
        assert character_state(reopened, 2) == other_before
    finally:
        reopened.database.close()


def test_full_roster_transaction_rolls_back_on_partial_failure(roster_runtime, monkeypatch):
    runtime = roster_runtime
    before = character_state(runtime, 1)
    original = Context.acquire_operator

    def fail_after_first_grant(ctx, char_id, count=1):
        if char_id == "char_no_skill":
            raise DomainError("TEST_FAILURE", "synthetic interruption")
        return original(ctx, char_id, count)

    monkeypatch.setattr(Context, "acquire_operator", fail_after_first_grant)
    with pytest.raises(DomainError, match="synthetic interruption"):
        with runtime.database.transaction() as session:
            complete_roster(Context(session, runtime.data, 1))
    assert character_state(runtime, 1) == before


def test_sandbox_creation_and_admin_apply_are_audited(roster_runtime):
    runtime = roster_runtime
    with TestClient(create_admin_app(runtime), base_url="http://127.0.0.1:8080") as client:
        csrf = client.get("/api/session").json()["csrf"]
        command = {"accountId": 1, "action": "complete-roster"}
        assert client.post("/api/gm", json=command).status_code == 403
        response = client.post("/api/gm", json=command, headers={"x-csrf-token": csrf})
        assert response.status_code == 200 and response.json()["roster"]["totalOperators"] == 4
        assert response.json()["revision"] == 1
        log = client.get("/api/logs").json()["audit"][0]
        assert log["action"] == "complete-roster" and log["accountId"] == 1
        assert log["detail"]["outcome"]["masteredSkills"] == 4
        response = client.post("/api/accounts", json={"name": "Full Sandbox", "preset": "Sandbox"},
                               headers={"x-csrf-token": csrf})
        assert response.status_code == 200
        sandbox_id = response.json()["id"]
    chars = list(character_state(runtime, sandbox_id).values())
    assert len(chars) == 4 and all(o["favorPoint"] == 25570 for o in chars)
    high = next(o for o in chars if o["charId"] == "char_synthetic")
    assert high["evolvePhase"] == 2 and high["level"] == 40


def test_incomplete_gamedata_rejects_roster_without_changing_account(runtime):
    before = character_state(runtime, 1)
    manifest = runtime.data.manifest
    original = manifest["tables"].pop("favor_table")
    try:
        with pytest.raises(DomainError, match="favor_table"):
            with runtime.database.transaction() as session:
                complete_roster(Context(session, runtime.data, 1))
    finally:
        manifest["tables"]["favor_table"] = original
    assert character_state(runtime, 1) == before


def test_invalid_training_condition_fails_before_any_modification(roster_runtime):
    runtime = roster_runtime
    before = character_state(runtime, 1)
    condition = runtime.data.characters["char_no_potential"]["skills"][1]["levelUpCostCond"][2]["unlockCond"]
    original_level = condition["level"]
    condition["level"] = 81  # Above this synthetic character's phase-two maximum of 80.
    try:
        with pytest.raises(DomainError) as failure:
            with runtime.database.transaction() as session:
                complete_roster(Context(session, runtime.data, 1))
        assert failure.value.code == "GAMEDATA_INVALID" and failure.value.status == 503
    finally:
        condition["level"] = original_level
    assert character_state(runtime, 1) == before
