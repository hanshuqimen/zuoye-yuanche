"""Native reinforcement/promotion and both frozen UpgradeChar mission modes."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import miniature
from fastapi.testclient import TestClient

from terralocal.config import Settings
from terralocal.server.domain import accounts, operators
from terralocal.server.domain.clock import ServerClock
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.mission_rules import target, upgrade_char_rule
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def build_runtime(tmp_path):
    tables = miniature()
    for ident in ("char_second", "char_third"):
        tables["character_table"][ident] = copy.deepcopy(tables["character_table"]["char_synthetic"])
        tables["charword_table"]["voiceLangDict"][ident] = copy.deepcopy(
            tables["charword_table"]["voiceLangDict"]["char_synthetic"])
        tables["charword_table"]["charDefaultTypeDict"][ident] = "JP"
    for char in tables["character_table"].values():
        char["phases"].append({"maxLevel": 5, "evolveCost": [{"id": "material", "count": 2}]})
    tables["gamedata_const"]["characterExpMap"].append([300, 400, 500, 600])
    tables["gamedata_const"]["characterUpgradeCostMap"].append([90, 120, 150, 180])
    for entry in tables["gamedata_const"]["evolveGoldCost"]:
        entry.append(50)
    specs = {"guide_count": ("GUIDE", ["0", "2"], "guide_root"),
             "guide_one": ("GUIDE", ["1", "1", "0", "2"], "guide_root"),
             "guide_three": ("GUIDE", ["1", "3", "0", "2"], "guide_root"),
             "guide_locked": ("GUIDE", ["1", "1", "0", "3"], "guide_next"),
             "sub_e2": ("SUB", ["1", "1", "2", "1"], "sub_root"),
             "sub_locked": ("SUB", ["0", "1"], "sub_locked_root"),
             "daily_assigned": ("DAILY", ["0", "5"], "daily_group"),
             "daily_unassigned": ("DAILY", ["0", "5"], "daily_group"),
             "weekly_assigned": ("WEEKLY", ["0", "5"], "weekly_group")}
    definitions = {ident: {"id": ident, "type": kind, "template": "UpgradeChar", "param": params,
                           "templateType": params[0], "missionGroup": group, "periodicalPoint": 0,
                           "preMissionIds": None, "unlockCondition": None, "unlockParam": None,
                           "countEndTs": -1, "rewards": [{"id": "2001", "type": "CARD_EXP", "count": 5}]}
                   for ident, (kind, params, group) in specs.items()}
    groups = {ident: {"id": ident, "type": definitions[members[0]]["type"], "missionIds": members,
                      "preMissionGroup": None, "rewards": None, "period": None, "startTs": -1, "endTs": -1}
              for ident, members in {"guide_root": ["guide_count", "guide_one", "guide_three"],
                                     "guide_next": ["guide_locked"], "sub_root": ["sub_e2"],
                                     "sub_locked_root": ["sub_locked"]}.items()}
    groups["guide_root"]["rewards"] = [{"id": "book", "count": 1, "type": "MATERIAL"}]
    groups["guide_next"]["preMissionGroup"] = "guide_root"
    definitions["sub_locked"]["preMissionIds"] = ["guide_one"]
    tables["mission_table"] = {"missions": definitions, "missionGroups": groups}
    source = tmp_path / "source"
    source.mkdir()
    for name, table in tables.items():
        (source / f"{name}.json").write_text(json.dumps(table), encoding="utf-8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        accounts.create_account(session, runtime.data, "Other")
        ctx = Context(session, runtime.data, 1)
        ctx.change_item("2001", 30)
        ctx.change_item("material", 10)
        for ident, kind in (("daily_assigned", "daily"), ("weekly_assigned", "weekly")):
            session.add(m.MissionProgress(account_id=1, mission_id=ident,
                                          period=ServerClock(clock).period(kind), progress=0, claimed=False))
    yield runtime
    runtime.database.close()


def login(runtime, name="Doctor", kind="game"):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name=name, kind=kind)["secret"]


def reinforce(client, token, operator_id=1, count=1, sequence="upgrade-1"):
    return client.post("/charBuild/upgradeChar", headers={"secret": token, "seqnum": sequence},
                       json={"charInstId": operator_id, "expMats": [{"id": "2001", "count": count}]})


def test_native_upgrade_updates_count_and_roster_missions_without_unlocking_future_groups(build_runtime):
    runtime, token = build_runtime, login(build_runtime)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        response = reinforce(client, token)
        assert response.status_code == 200
        assert set(response.json()) == {"result", "playerDataDelta", "ts", "revision"}
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        assert after["troop"]["chars"]["1"]["level"] == 2
        assert after["inventory"]["2001"] == 29
        groups = after["mission"]["missions"]
        assert groups["GUIDE"]["guide_count"]["progress"][0] == {"target": 2, "value": 1, "compare": ">="}
        assert groups["GUIDE"]["guide_three"]["progress"][0]["value"] == 1
        assert "guide_locked" not in groups["GUIDE"] and "sub_locked" not in groups["SUB"]
        assert "daily_unassigned" not in groups["DAILY"]
        assert groups["DAILY"]["daily_assigned"]["progress"][0]["value"] == 1
        assert after["mission"]["missionGroups"]["guide_root"] == 0
        assert reinforce(client, token).json() == response.json()
        assert runtime.sync(token)["user"] == after


def test_roster_count_uses_distinct_operators_not_number_of_upgrades(build_runtime):
    runtime, token = build_runtime, login(build_runtime)
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        ctx.acquire_operator("char_second")
        ctx.acquire_operator("char_third")
        ids = [op.id for op in ctx.rows(m.Operator)]
    with TestClient(create_game_app(runtime)) as client:
        for index, ident in enumerate([ids[0], ids[0], ids[1], ids[2]]):
            assert reinforce(client, token, ident, sequence=str(index)).status_code == 200
            with runtime.database.transaction(write=False) as session:
                row = session.get(m.MissionProgress, (1, "guide_three", "permanent"))
                assert row.progress == (1 if index < 2 else index)
        claim = client.post("/mission/confirmMission", headers={"secret": token, "seqnum": "claim"},
                            json={"missionId": "guide_three"})
        assert claim.status_code == 200
        after = runtime.sync(token)["user"]
        assert client.post("/mission/confirmMission", headers={"secret": token, "seqnum": "retry"},
                           json={"missionId": "guide_three"}).status_code == 200
        assert runtime.sync(token)["user"] == after
        assert after["mission"]["missionGroups"]["guide_root"] == 0


def test_promotion_recomputes_phase_threshold_without_counting_as_reinforcement(build_runtime):
    runtime, token = build_runtime, login(build_runtime)
    with TestClient(create_game_app(runtime)) as client:
        assert reinforce(client, token, count=3).status_code == 200
        headers = {"secret": token, "seqnum": "e1"}
        body = {"charInstId": 1, "destEvolvePhase": 1}
        before = runtime.sync(token)["user"]
        response = client.post("/charBuild/evolveChar", headers=headers, json=body)
        assert response.status_code == 200
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        assert after["troop"]["chars"]["1"]["evolvePhase"] == 1
        assert after["troop"]["chars"]["1"]["level"] == 1
        assert after["mission"]["missions"]["GUIDE"]["guide_one"]["progress"][0]["value"] == 1
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.MissionProgress, (1, "guide_count", "permanent")).progress == 1
        # Same requested phase with a fresh sequence also cannot charge twice.
        assert client.post("/charBuild/evolveChar", headers={"secret": token, "seqnum": "retry"},
                           json=body).status_code == 200
        assert runtime.sync(token)["user"] == after
        assert reinforce(client, token, count=9, sequence="e1-max").status_code == 200
        assert client.post("/charBuild/evolveChar", headers={"secret": token, "seqnum": "e2"},
                           json={"charInstId": 1, "destEvolvePhase": 2}).status_code == 200
        after_e2 = runtime.sync(token)["user"]
        assert after_e2["mission"]["missions"]["SUB"]["sub_e2"]["progress"][0]["value"] == 1
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.MissionProgress, (1, "guide_count", "permanent")).progress == 2


def test_concurrent_native_reinforcement_has_one_charge_and_one_event(build_runtime):
    runtime, token = build_runtime, login(build_runtime)
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: reinforce(client, token), range(6)))
        assert all(response.status_code == 200 and response.json() == responses[0].json() for response in responses)
    assert runtime.sync(token)["user"]["inventory"]["2001"] == 29
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.DomainEvent).filter_by(event_type="OperatorLeveled").count() == 1


def test_upgrade_state_mission_claim_backup_and_restart_remain_consistent(build_runtime):
    runtime, token = build_runtime, login(build_runtime)
    with TestClient(create_game_app(runtime)) as client:
        assert reinforce(client, token).status_code == 200
        assert client.post("/mission/confirmMission", headers={"secret": token, "seqnum": "claim-one"},
                           json={"missionId": "guide_one"}).status_code == 200
    expected = runtime.sync(token)
    saved = BackupService(runtime).create()
    with TestClient(create_game_app(runtime)) as client:
        assert reinforce(client, token, sequence="another").status_code == 200
    BackupService(runtime).restore(saved["name"])
    assert runtime.sync(token) == expected
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == expected
    finally:
        restarted.database.close()


def test_failed_upgrade_does_not_consume_or_create_any_mission_or_event(build_runtime, monkeypatch):
    runtime, token = build_runtime, login(build_runtime)
    before = runtime.sync(token)
    from terralocal.server.domain import mission_upgrade

    progress = mission_upgrade.progress

    def fail(ctx, event):
        progress(ctx, event)
        raise RuntimeError("failure after mission progress")

    monkeypatch.setattr(mission_upgrade, "progress", fail)
    with TestClient(create_game_app(runtime)) as client:
        with pytest.raises(RuntimeError, match="failure after mission progress"):
            reinforce(client, token)
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.DomainEvent).filter_by(event_type="OperatorLeveled").count() == 0


def test_upgrade_claim_unlocks_only_individual_prerequisite_not_group_reward(build_runtime):
    runtime, token = build_runtime, login(build_runtime)
    with TestClient(create_game_app(runtime)) as client:
        assert reinforce(client, token).status_code == 200
        assert client.post("/mission/confirmMission", headers={"secret": token, "seqnum": "claim-one"},
                           json={"missionId": "guide_one"}).status_code == 200
        assert reinforce(client, token, sequence="next").status_code == 200
    groups = runtime.sync(token)["user"]["mission"]["missions"]
    assert "sub_locked" in groups["SUB"] and "guide_locked" not in groups["GUIDE"]


def test_wrong_account_stage_skip_and_insufficient_items_leave_state_unchanged(build_runtime):
    runtime, token = build_runtime, login(build_runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert reinforce(client, token, operator_id=2).status_code == 404
        assert reinforce(client, token, count=31, sequence="insufficient").status_code == 400
        assert client.post("/charBuild/evolveChar", headers={"secret": token, "seqnum": "skip"},
                           json={"charInstId": 1, "destEvolvePhase": 2}).status_code == 409
        assert client.post("/charBuild/evolveChar", headers={"secret": token, "seqnum": "low-level"},
                           json={"charInstId": 1, "destEvolvePhase": 1}).status_code == 400
    assert runtime.sync(token) == before


@pytest.mark.parametrize("body", [{"charInstId": True, "expMats": []}, {"charInstId": 1, "expMats": []},
    {"charInstId": 1, "expMats": [{"id": "2001", "count": -1}]},
    {"charInstId": 1, "expMats": [{"id": "2001", "count": 1}], "cost": 0}])
def test_native_upgrade_validation_cannot_mutate(build_runtime, body):
    runtime, token = build_runtime, login(build_runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert client.post("/charBuild/upgradeChar", headers={"secret": token, "seqnum": "bad"},
                           json=body).status_code == 422
    assert runtime.sync(token) == before


@pytest.mark.parametrize("parameters", [["2", "1"], ["1", "1", "3", "1"], ["0", "0"],
                                       ["1", "1", "0", "91"], ["0", True]])
def test_unknown_or_invalid_upgrade_mission_rules_fail_explicitly(parameters):
    with pytest.raises(DomainError):
        upgrade_char_rule({"template": "UpgradeChar", "param": parameters})


def test_local_upgrade_uses_the_same_complete_mission_rules(build_runtime):
    runtime, token = build_runtime, login(build_runtime)
    response = runtime.mutate(token, None, "local", "operator-upgrade", {},
                              lambda ctx: operators.upgrade(ctx, 1, [{"id": "2001", "count": 1}]))
    assert response["level"] == 2
    assert target(runtime.data.table("mission_table")["missions"]["guide_three"]) == 3
