"""Stage requirements apply to the saved formation before AP/session writes."""

from copy import deepcopy

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from test_native_battle_finish import complete, encoded
from test_native_battle_start import begin, body, login

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.domain.context import Context
from terralocal.server.gamedata import import_data
from terralocal.server.gamedata.repository import canonical
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def required_runtime(tmp_path):
    tables = miniature()
    char = tables["character_table"]["char_synthetic"]
    char["phases"].append(deepcopy(char["phases"][-1]))
    tables["character_table"]["char_required"] = deepcopy(char)
    tables["charword_table"]["voiceLangDict"]["char_required"] = deepcopy(
        tables["charword_table"]["voiceLangDict"]["char_synthetic"])
    tables["charword_table"]["charDefaultTypeDict"]["char_required"] = "JP"
    for stage in tables["stage_table"]["stages"].values():
        stage.update(stageType="MAIN", difficulty="NORMAL", diffGroup="NONE", apProtectTimes=0,
                     isPredefined=False, isStagePatch=False)
    tables["stage_table"]["stageStartConds"] = {"test_1": {
        "isNotPass": True, "requireChars": [{"charId": "char_synthetic", "evolvePhase": "PHASE_2"}],
        "excludeAssists": ["char_synthetic"]}}
    source = tmp_path / "source"
    source.mkdir()
    for key, value in tables.items():
        (source / f"{key}.json").write_bytes(canonical(value))
    manifest = import_data(source, tmp_path / "data/cache")
    runtime = Runtime(Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False))
    runtime.drop_rules = {"test_1": {"rewards": [], "first_rewards": []}}
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        session.get(m.SanityState, 1).current = 100
    yield runtime
    runtime.database.close()


def test_first_pass_requires_phase_but_repeat_clear_does_not(required_runtime):
    runtime = required_runtime
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)
        refused = begin(client, token, body(), "phase-missing")
        assert refused.json()["error"]["code"] == "STAGE_REQUIRED_OPERATOR"
        assert runtime.sync(token) == before
        with runtime.database.transaction() as session:
            session.get(m.Operator, 1).evolve_phase = 2
        started = begin(client, token, body(), "qualified")
        assert started.status_code == 200
        assert complete(client, token, encoded(started.json()["battleId"], state=2)).status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.Operator, 1).evolve_phase = 0
        assert begin(client, token, body(), "after-first-pass").status_code == 200


def test_owned_operator_outside_formation_cannot_satisfy_requirement(required_runtime):
    runtime = required_runtime
    runtime.data.table("stage_table")["stageStartConds"]["test_1"]["requireChars"] = [
        {"charId": "char_required", "evolvePhase": "PHASE_2"}]
    with runtime.database.transaction() as session:
        op, _ = Context(session, runtime.data, 1).acquire_operator("char_required")
        op.evolve_phase = 2
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)
        assert begin(client, token, body()).json()["error"]["code"] == "STAGE_REQUIRED_OPERATOR"
        assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).count() == 0


def test_invalid_requirement_is_rejected_before_ap_charge(required_runtime):
    runtime = required_runtime
    runtime.data.table("stage_table")["stageStartConds"]["test_1"]["requireChars"][0]["evolvePhase"] = "PHASE_9"
    token = login(runtime)
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)
        assert begin(client, token, body()).status_code == 503
        assert runtime.sync(token) == before
