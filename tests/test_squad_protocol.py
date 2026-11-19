"""Observed formation requests, preferred skills, isolation and atomic saves."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from conftest import miniature
from fastapi.testclient import TestClient

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def formation_runtime(tmp_path):
    tables = miniature()
    character = tables["character_table"]["char_synthetic"]
    character["skills"].append({"skillId": "skill_second", "unlockCond": {"phase": "PHASE_1", "level": 1}})
    tables["skill_table"]["skill_second"] = {}
    for char_id, name in [("char_second", "Second"), ("char_no_skill", "No skill")]:
        tables["character_table"][char_id] = {**deepcopy(character), "name": name}
        tables["charword_table"]["voiceLangDict"][char_id] = deepcopy(
            tables["charword_table"]["voiceLangDict"]["char_synthetic"])
        tables["charword_table"]["charDefaultTypeDict"][char_id] = "JP"
    tables["character_table"]["char_no_skill"]["skills"] = []
    tables["gamedata_const"]["initCharIdList"] = list(tables["character_table"])
    source = tmp_path / "source"
    source.mkdir()
    for name, content in tables.items():
        (source / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        session.get(m.Operator, 1).evolve_phase = 1
    yield runtime
    runtime.database.close()


def login(runtime):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name="Doctor")["secret"]


def request_body(change_skill=1):
    return {"squadId": "0", "slots": [
        {"charInstId": 1, "skillIndex": 1, "currentEquip": None}, None,
        {"charInstId": 3, "skillIndex": -1, "currentEquip": None}], "changeSkill": change_skill}


def save(client, token, body, key="formation"):
    return client.post("/quest/squadFormation", headers={"secret": token, "seqnum": key}, json=body)


@pytest.mark.parametrize("wire", [0, 1, False, True])
def test_native_boolean_shape_and_empty_positions(formation_runtime, wire):
    runtime = formation_runtime
    token = login(runtime)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        response = save(client, token, request_body(wire))
    assert response.status_code == 200
    envelope = response.json()
    assert "squadId" not in envelope
    after = runtime.sync(token)["user"]
    assert apply(before, envelope["playerDataDelta"]) == after
    squad = after["troop"]["squads"]["0"]["slots"]
    assert len(squad) == 12 and squad[1] is None and squad[3:] == [None] * 9
    assert squad[0]["charInstId"] == 1 and squad[0]["skillIndex"] == 1
    assert after["troop"]["chars"]["1"]["defaultSkillIndex"] == int(bool(wire))
    assert after["troop"]["chars"]["3"]["defaultSkillIndex"] == (-1 if wire else 0)


@pytest.mark.parametrize("wire", [2, -1, "1", 1.0, None])
def test_other_boolean_encodings_fail_without_changing_the_save(formation_runtime, wire):
    runtime = formation_runtime
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert save(client, token, request_body(wire)).status_code == 422
    assert runtime.sync(token) == before


def test_concurrent_retries_and_restart_preserve_one_formation(formation_runtime):
    runtime = formation_runtime
    token = login(runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=8) as workers:
            responses = list(workers.map(lambda _: save(client, token, request_body()), range(8)))
        assert all(response.status_code == 200 for response in responses)
        assert all(response.json() == responses[0].json() for response in responses)
        assert save(client, token, request_body(0)).status_code == 409
    after = runtime.sync(token)
    assert after["revision"] == before["revision"] + 1
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == after
    finally:
        restarted.database.close()


@pytest.mark.parametrize("kind,status", [("duplicate", 400), ("locked", 400), ("foreign", 404),
                                          ("module", 501), ("long", 422)])
def test_failed_validation_keeps_prior_slots_and_preferred_skill(formation_runtime, kind, status):
    runtime = formation_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
    before = runtime.sync(token)
    body = request_body()
    if kind == "duplicate":
        body["slots"].append(deepcopy(body["slots"][0]))
    elif kind == "locked":
        body["slots"].append({"charInstId": 2, "skillIndex": 1})
    elif kind == "foreign":
        body["slots"].append({"charInstId": 4, "skillIndex": 0})
    elif kind == "module":
        body["slots"][0]["currentEquip"] = "unverified_module"
    else:
        body["slots"] = [None] * 13
    with TestClient(create_game_app(runtime)) as client:
        assert save(client, token, body).status_code == status
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.Receipt).count() == 0


def test_response_failure_rolls_back_formation_and_default_skills(formation_runtime, monkeypatch):
    runtime = formation_runtime
    token = login(runtime)
    before = runtime.sync(token)
    original = SyncDataAssembler.assemble
    count = 0

    def fail_after_save(self):
        nonlocal count
        count += 1
        if count == 2:
            assert self.ctx.session.get(m.Operator, 1).default_skill == 1
            raise RuntimeError("Synthetic response failure")
        return original(self)

    monkeypatch.setattr(SyncDataAssembler, "assemble", fail_after_save)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert save(client, token, request_body()).status_code == 500
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.Receipt).count() == 0


def test_local_formation_name_contract_stays_separate(formation_runtime):
    runtime = formation_runtime
    token = login(runtime)
    local_body = {"squadId": "0", "slots": [{"charInstId": 1, "skillIndex": 1}], "name": "Local"}
    with TestClient(create_game_app(runtime)) as client:
        response = client.post("/local/v1/squads/formation", headers={
            "secret": token, "idempotency-key": "local"}, json=local_body)
        assert response.status_code == 200
        assert save(client, token, {**request_body(), "name": "Ignored"}).status_code == 422
    view = runtime.sync(token)["user"]["troop"]
    assert view["squads"]["0"]["name"] == "Local"
    assert view["chars"]["1"]["defaultSkillIndex"] == 0
